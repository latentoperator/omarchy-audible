"""``sync``: build ``catalog.json``, download covers, cache remote positions.

ARCHITECTURE 4.5, 4.6 and 4.8. ``sync`` pages the library (``num_results=50``,
the §4.5 response groups), keeps every content type except ``Podcast*``
(``Lecture`` stays), downloads the covers that are missing, reads the account's
last positions in batches of at most 25 (``positions.py``) into ``remote.json``,
and writes both files atomically. ``catalog.json`` is written **last**, so an
interrupted sync leaves the previous catalog untouched.

``sync`` never pushes a position: the only mutating call is
``PUT 1.0/lastpositions/``, which lives with B6's ``position-push`` and is not
reachable from this module (``tests/test_sync.py`` asserts that).

The ``audible`` library is imported lazily, inside real-mode code paths only, so
the suite runs without it installed.
"""

from __future__ import annotations

import contextlib
import json
import os
import urllib.request
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any, Protocol

from . import fsutil, protocol
from .auth import DEFAULT_MARKETPLACE
from .errors import PipelineError
from .library import iso_now
from .log import log
from .paths import Paths
from .positions import (
    FakePositions,
    PositionsPort,
    RealPositions,
    fetch_positions,
    write_remote,
)

CATALOG_SCHEMA = 1
LIBRARY_ENDPOINT = "1.0/library"
PAGE_SIZE = 50
# The smallest response_groups that returns every §4.5 field without a timeout
# (SPIKE-RESULTS S4).
RESPONSE_GROUPS = (
    "product_desc,media,contributors,series,product_attrs,"
    "listening_status,percent_complete,is_finished"
)
FIXTURE_NAME = "library-sample.json"
FIXTURE_ENV = "OMARCHY_AUDIBLE_FIXTURE"
COVER_USER_AGENT = (
    "omarchy-audible/0.1 (+https://github.com/latentoperator/omarchy-audible)"
)

Emitter = Callable[..., None]
CoverFetch = Callable[[str], bytes]


class LibraryPort(Protocol):
    """The paged ``1.0/library`` read, one ``(page_items, total)`` per page."""

    def pages(self) -> Iterator[tuple[list[dict[str, Any]], int | None]]: ...


# --- raw item -> catalog book (ARCHITECTURE 4.5) -----------------------------
def is_podcast(item: dict[str, Any]) -> bool:
    """True for the content types ``sync`` drops. ``Lecture`` is not a podcast."""
    content_type = item.get("content_type")
    return isinstance(content_type, str) and content_type.lower().startswith("podcast")


def is_kept(item: dict[str, Any]) -> bool:
    return not is_podcast(item)


def _names(people: Any) -> list[str]:
    if not isinstance(people, list):
        return []
    names: list[str] = []
    for person in people:
        name = person.get("name") if isinstance(person, dict) else person
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _series(item: dict[str, Any]) -> dict[str, str | None] | None:
    series = item.get("series")
    if not isinstance(series, list) or not series:
        return None
    first = series[0]
    if not isinstance(first, dict):
        return None
    name = first.get("title")
    if not isinstance(name, str) or not name:
        return None
    part = first.get("sequence")
    if isinstance(part, (int, float)) and not isinstance(part, bool):
        part = str(part)
    return {"name": name, "part": part if isinstance(part, str) and part else None}


def _date_added(item: dict[str, Any]) -> str | None:
    status = item.get("library_status")
    if isinstance(status, dict):
        value = status.get("date_added")
        if isinstance(value, str) and value:
            return value
    value = item.get("purchase_date")
    return value if isinstance(value, str) and value else None


def _percent_complete(item: dict[str, Any]) -> float:
    status = item.get("listening_status")
    fallback = status.get("percent_complete") if isinstance(status, dict) else None
    for value in (item.get("percent_complete"), fallback):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return 0.0


def _is_finished(item: dict[str, Any]) -> bool:
    status = item.get("listening_status")
    if isinstance(status, dict) and status.get("is_finished") is True:
        return True
    return item.get("is_finished") is True


def cover_url(item: dict[str, Any]) -> str | None:
    """The best cover URL the item offers (smallest size first, then fallback)."""
    images = item.get("product_images")
    if not isinstance(images, dict) or not images:
        return None

    def rank(key: str) -> tuple[int, int]:
        try:
            return (0, int(key))
        except (TypeError, ValueError):
            return (1, 0)

    for key in sorted(images, key=rank):
        value = images.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def book_entry(item: dict[str, Any]) -> tuple[dict[str, Any], str | None] | None:
    """Map a raw library item onto a catalog book plus its cover URL.

    Returns ``None`` when the item cannot become a book (no usable ASIN), so a
    malformed entry is skipped rather than written into the catalog.
    """
    asin = item.get("asin")
    if not isinstance(asin, str) or not asin:
        return None
    title = item.get("title")
    subtitle = item.get("subtitle")
    runtime = item.get("runtime_length_min")
    if not isinstance(runtime, (int, float)) or isinstance(runtime, bool):
        runtime = None
    url = cover_url(item)
    book = {
        "asin": asin,
        "title": title if isinstance(title, str) else "",
        "subtitle": subtitle if isinstance(subtitle, str) and subtitle else None,
        "authors": _names(item.get("authors")),
        "narrators": _names(item.get("narrators")),
        "series": _series(item),
        "cover": f"covers/{asin}.jpg" if url else None,
        "runtime_min": int(runtime) if runtime is not None else None,
        "date_added": _date_added(item),
        "percent_complete": _percent_complete(item),
        "is_finished": _is_finished(item),
        "multipart": item.get("content_delivery_type") == "MultiPartBook",
    }
    return book, url


def build_catalog(
    items: Sequence[dict[str, Any]], *, marketplace: str, synced_at: str
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build the catalog payload and the ``{asin: cover_url}`` map it implies."""
    books: list[dict[str, Any]] = []
    covers: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict) or not is_kept(item):
            continue
        mapped = book_entry(item)
        if mapped is None:
            continue
        book, url = mapped
        books.append(book)
        if url:
            covers[book["asin"]] = url
    catalog = {
        "schema": CATALOG_SCHEMA,
        "synced_at": synced_at,
        "marketplace": marketplace,
        "books": books,
    }
    return catalog, covers


# --- library ports -----------------------------------------------------------
def default_fixture_path() -> Path:
    """The fake-mode library fixture (``fixtures/library-sample.json``)."""
    override = os.environ.get(FIXTURE_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "fixtures" / FIXTURE_NAME


def fixture_items(path: Path | str | None = None) -> list[dict[str, Any]]:
    """Load the invented-library fixture used by fake mode."""
    source = Path(path) if path is not None else default_fixture_path()
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PipelineError(
            protocol.ErrorCode.INTERNAL,
            "the fake library fixture could not be read",
            hint=f"expected {source}",
        ) from exc
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise PipelineError(
            protocol.ErrorCode.INTERNAL,
            "the fake library fixture has no items",
            hint=f"expected {source}",
        )
    return [item for item in items if isinstance(item, dict)]


class FakeLibrary:
    """``LibraryPort`` over the fixture; no network, no account."""

    def __init__(
        self,
        items: Sequence[dict[str, Any]] | None = None,
        *,
        page_size: int = PAGE_SIZE,
        fixture_path: Path | str | None = None,
    ) -> None:
        self._items = list(items) if items is not None else fixture_items(fixture_path)
        self._page_size = max(1, page_size)

    def pages(self) -> Iterator[tuple[list[dict[str, Any]], int | None]]:
        total = len(self._items)
        if total == 0:
            yield [], 0
            return
        for start in range(0, total, self._page_size):
            yield self._items[start : start + self._page_size], total


class RealLibrary:
    """``LibraryPort`` over an authenticated ``audible.Client`` (ARCHITECTURE 4.5)."""

    def __init__(self, client: Any, *, page_size: int = PAGE_SIZE) -> None:
        self._client = client
        self._page_size = page_size
        # ``image_sizes=252`` gives a small thumbnail; S4 only ever saw a 500 px
        # URL, so it is requested once and dropped if the API rejects it.
        self._image_sizes = True

    def pages(self) -> Iterator[tuple[list[dict[str, Any]], int | None]]:
        page = 1
        while True:
            payload = self._page(page)
            items = payload.get("items") if isinstance(payload, dict) else None
            batch = items if isinstance(items, list) else []
            if batch or page == 1:
                total = (
                    payload.get("total_results") if isinstance(payload, dict) else None
                )
                yield batch, total if isinstance(total, int) and total >= 0 else None
            if len(batch) < self._page_size:
                return
            page += 1

    def _page(self, page: int) -> Any:
        params: dict[str, Any] = {
            "num_results": self._page_size,
            "page": page,
            "response_groups": RESPONSE_GROUPS,
            "sort_by": "-PurchaseDate",
        }
        if self._image_sizes:
            try:
                return self._client.get(
                    LIBRARY_ENDPOINT, image_sizes="252", **params
                )
            except Exception as exc:  # noqa: BLE001 - the parameter is optional
                log(
                    "library image_sizes=252 unavailable "
                    f"({type(exc).__name__}); using the default sizes"
                )
                self._image_sizes = False
        return self._client.get(LIBRARY_ENDPOINT, **params)


def open_client(paths: Paths) -> Any:
    """Open an authenticated ``audible.Client``; ``audible`` is imported lazily."""
    if not paths.auth_file.is_file():
        raise PipelineError(
            protocol.ErrorCode.AUTH_FAILED,
            "no Audible login",
            hint="sign in from the drawer",
        )
    try:
        import audible
    except ImportError as exc:
        raise PipelineError(
            protocol.ErrorCode.NO_VENV,
            "the audible library is not installed",
            hint="run: omarchy-audible setup",
        ) from exc
    try:
        auth = audible.Authenticator.from_file(paths.auth_file)
        return audible.Client(auth=auth)
    except Exception as exc:  # any credential failure is auth_failed
        log(f"opening the Audible client failed: {type(exc).__name__}")
        raise PipelineError(
            protocol.ErrorCode.AUTH_FAILED,
            "the saved Audible login could not be used",
            hint="sign in again from the drawer",
        ) from exc


# --- covers ------------------------------------------------------------------
def http_fetch_cover(url: str) -> bytes:
    """Download one cover image (real mode only)."""
    request = urllib.request.Request(url, headers={"User-Agent": COVER_USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def fetch_covers(
    paths: Paths,
    covers: dict[str, str],
    *,
    fetch: CoverFetch | None,
    full: bool = False,
) -> int:
    """Download the covers that are missing (all of them with ``full``).

    A cover that cannot be fetched is logged and skipped: the catalog still
    points at ``covers/<asin>.jpg`` and the UI falls back to a placeholder.
    """
    if fetch is None:
        return 0
    downloaded = 0
    for asin, url in covers.items():
        target = paths.covers_dir / f"{asin}.jpg"
        if target.is_file() and not full:
            continue
        try:
            data = fetch(url)
        except Exception as exc:  # noqa: BLE001 - a cover is optional
            log(f"cover download failed ({type(exc).__name__})")
            continue
        if not isinstance(data, (bytes, bytearray)) or not data:
            continue
        fsutil.atomic_write_bytes(target, bytes(data))
        downloaded += 1
    return downloaded


# --- the command -------------------------------------------------------------
def _read_library(library: LibraryPort, emit: Emitter) -> list[dict[str, Any]]:
    """Page the library, emitting a ``progress`` event per page (ARCHITECTURE 4.2)."""
    items: list[dict[str, Any]] = []
    try:
        for batch, total in library.pages():
            items.extend(batch)
            known = len(items)
            if isinstance(total, int) and total >= known:
                known = total
            emit("progress", stage="library", n=len(items), of=known)
    except PipelineError:
        raise
    except Exception as exc:  # any library failure is a read failure
        log(f"library read failed: {type(exc).__name__}")
        raise PipelineError(
            protocol.ErrorCode.NETWORK,
            "could not read the library",
            hint="check the network and retry",
        ) from exc
    return items


def run_sync(
    paths: Paths,
    *,
    fake: bool,
    full: bool = False,
    marketplace: str = DEFAULT_MARKETPLACE,
    library: LibraryPort | None = None,
    positions_port: PositionsPort | None = None,
    cover_fetch: CoverFetch | None = None,
    emit: Emitter = protocol.emit,
) -> dict[str, int]:
    """Refresh ``catalog.json`` and ``remote.json`` (ARCHITECTURE 4.5, 4.6).

    Accumulates everything in memory and writes ``catalog.json`` last, through an
    atomic rename, so an interruption never leaves a half-written catalog.
    """
    with contextlib.ExitStack() as stack:
        client = None
        if not fake and (library is None or positions_port is None):
            client = stack.enter_context(open_client(paths))
        if library is None:
            library = FakeLibrary() if fake else RealLibrary(client)
        if positions_port is None:
            positions_port = FakePositions() if fake else RealPositions(client)
        if cover_fetch is None and not fake:
            cover_fetch = http_fetch_cover

        items = _read_library(library, emit)
        built, covers = build_catalog(
            items, marketplace=marketplace, synced_at=iso_now()
        )
        downloaded = fetch_covers(paths, covers, fetch=cover_fetch, full=full)

        asins = [book["asin"] for book in built["books"]]
        remote = fetch_positions(asins, positions_port)
        write_remote(paths.remote_file, remote)
        fsutil.atomic_write_json(paths.catalog_file, built)

    return {
        "books": len(built["books"]),
        "covers": downloaded,
        "positions": len(remote),
    }

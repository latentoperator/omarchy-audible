"""Remote positions: the cache, the newest-wins merge, and the write-back.

``sync`` and ``position-get`` read the account's last positions for a set of
ASINs and cache them in ``remote.json``. ``position-push`` performs the single
mutating Audible call in the whole backend, ``PUT 1.0/lastpositions/{asin}``
(ARCHITECTURE 4.4, 4.6). ``state.json`` is never touched here; it belongs to
``Service.qml`` (ARCHITECTURE 4.8).

The file is the bare mapping documented in ARCHITECTURE 3 —
``{asin: {ms, updated_at}}`` — with ``updated_at`` null when the account has no
position for the book, so the newest-wins merge always resolves to the local
position. ``position-get`` refreshes the requested entries in place, keeping
every other cached book.

The read endpoint is ``GET 1.0/annotations/lastpositions`` (SPIKE-RESULTS S3),
whose response key is ``asin_last_position_heard_annots``. The API allows **at
most 25 ASINs per call**, so :func:`batches` chunks the request.

:func:`merge` is the newest-wins rule the QML service implements; keep the two
in step (ARCHITECTURE 4.6, 4.8). The entry with the newest ``updated_at`` wins,
a missing or ``None`` timestamp counts as the oldest, and an equal timestamp
goes to the local entry.

Push rules (ARCHITECTURE 4.6): a push re-reads the remote position immediately
before writing and refuses with ``error(code=stale)`` when the account's
position is newer than the local timestamp of the listening that produced it.
``acr`` comes from the local ``meta.json`` when the book is downloaded, and
otherwise from the content metadata.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from . import fsutil, protocol
from .errors import PipelineError
from .library import book_dir, iso_now, read_meta
from .log import log

LASTPOSITIONS_ENDPOINT = "1.0/annotations/lastpositions"
POSITION_BATCH_SIZE = 25
CONTENT_REFERENCE_GROUPS = "content_reference"
# Fake mode has no account, so a pushed position only has to look plausible.
FAKE_ACR = "FAKEACR0"


def empty_entry() -> dict[str, Any]:
    """The cache entry for a book with no position on the account."""
    return {"ms": 0, "updated_at": None}


def _clean(entry: Any) -> dict[str, Any] | None:
    """Normalise one ``{ms, updated_at}`` entry, or ``None`` when it is not one."""
    if not isinstance(entry, dict):
        return None
    ms = entry.get("ms")
    if not isinstance(ms, (int, float)) or isinstance(ms, bool):
        ms = 0
    updated = entry.get("updated_at")
    return {
        "ms": max(0, int(ms)),
        "updated_at": updated if isinstance(updated, str) and updated else None,
    }


def parse_updated_at(value: Any) -> datetime | None:
    """Parse a position timestamp into an aware UTC datetime.

    Audible returns ``YYYY-MM-DD HH:MM:SS.f`` with no timezone, which S3 found
    looks like UTC; ``state.json`` timestamps are ISO 8601 with a ``Z`` or an
    offset. Anything unparseable (including ``None``) sorts as the oldest.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if " " in text:
        text = text.replace(" ", "T", 1)
    if text[-1] in "Zz":
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def merge(local: Any, remote: Any) -> dict[str, Any]:
    """Newest-wins merge of two ``{ms, updated_at}`` entries (ARCHITECTURE 4.6).

    The QML service implements this same rule; change both together. A missing
    entry or timestamp loses, and an equal ``updated_at`` goes to the local
    entry. Returns a new dict, never one of the inputs.
    """
    local_entry = _clean(local)
    remote_entry = _clean(remote)
    if local_entry is None:
        return remote_entry if remote_entry is not None else empty_entry()
    if remote_entry is None:
        return local_entry
    local_key = parse_updated_at(local_entry["updated_at"])
    remote_key = parse_updated_at(remote_entry["updated_at"])
    if remote_key is None:
        return local_entry
    if local_key is None:
        return remote_entry
    return remote_entry if remote_key > local_key else local_entry


def is_remote_newer(remote_entry: Any, local_updated_at: Any) -> bool:
    """True when the remote position is strictly newer than the local one."""
    local_key = parse_updated_at(local_updated_at)
    if local_key is None:
        return False
    remote_key = parse_updated_at(
        remote_entry.get("updated_at") if isinstance(remote_entry, dict) else None
    )
    return remote_key is not None and remote_key > local_key


def batches(
    asins: Sequence[str], size: int = POSITION_BATCH_SIZE
) -> list[list[str]]:
    """Chunk ``asins`` (deduplicated, order kept) into calls of at most ``size``."""
    unique = list(dict.fromkeys(asins))
    return [unique[start : start + size] for start in range(0, len(unique), size)]


def _entry(last_position_heard: Any) -> dict[str, Any]:
    if not isinstance(last_position_heard, dict):
        return empty_entry()
    if last_position_heard.get("status") != "Exists":
        return empty_entry()
    ms = last_position_heard.get("position_ms")
    if not isinstance(ms, (int, float)) or isinstance(ms, bool):
        return empty_entry()
    updated = last_position_heard.get("last_updated")
    return {
        "ms": max(0, int(ms)),
        "updated_at": updated if isinstance(updated, str) and updated else None,
    }


def parse_lastpositions(
    payload: Any, asins: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """Map a ``lastpositions`` response onto one entry per requested ASIN."""
    heard: dict[str, dict[str, Any]] = {}
    annots = (
        payload.get("asin_last_position_heard_annots")
        if isinstance(payload, dict)
        else None
    )
    for annot in annots or []:
        if not isinstance(annot, dict):
            continue
        asin = annot.get("asin")
        if isinstance(asin, str) and asin:
            heard[asin] = _entry(annot.get("last_position_heard"))
    return {asin: heard.get(asin, empty_entry()) for asin in asins}


class PositionsPort(Protocol):
    """One ``lastpositions`` call, already batched by the caller."""

    def fetch_batch(self, asins: Sequence[str]) -> dict[str, dict[str, Any]]: ...


class PushPort(Protocol):
    """What a push needs: re-read the remote position, resolve ``acr``, write."""

    def fetch_batch(self, asins: Sequence[str]) -> dict[str, dict[str, Any]]: ...

    def fetch_acr(self, asin: str) -> str | None: ...

    def push(self, asin: str, acr: str, position_ms: int) -> Any: ...


class FakePositions:
    """Fake mode has no account: reads are empty and a push is a local no-op."""

    def __init__(self) -> None:
        self.pushed: list[tuple[str, int]] = []

    def fetch_batch(self, asins: Sequence[str]) -> dict[str, dict[str, Any]]:
        return {asin: empty_entry() for asin in asins}

    def fetch_acr(self, asin: str) -> str | None:
        return FAKE_ACR

    def push(self, asin: str, acr: str, position_ms: int) -> None:
        self.pushed.append((asin, position_ms))


def _payload_acr(payload: Any) -> str | None:
    content = payload.get("content_metadata") if isinstance(payload, dict) else None
    reference = content.get("content_reference") if isinstance(content, dict) else None
    acr = reference.get("acr") if isinstance(reference, dict) else None
    return acr if isinstance(acr, str) and acr else None


class RealPositions:
    """``PositionsPort``/``PushPort`` over an authenticated ``audible.Client``."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def fetch_batch(self, asins: Sequence[str]) -> dict[str, dict[str, Any]]:
        payload = self._client.get(LASTPOSITIONS_ENDPOINT, asins=",".join(asins))
        return parse_lastpositions(payload, asins)

    def fetch_acr(self, asin: str) -> str | None:
        try:
            payload = self._client.get(
                f"1.0/content/{asin}/metadata", response_groups=CONTENT_REFERENCE_GROUPS
            )
        except Exception as exc:  # any library failure is a read failure
            log(f"content reference read failed: {type(exc).__name__}")
            raise PipelineError(
                protocol.ErrorCode.NETWORK,
                f"could not read the content reference for {asin}",
                hint="check the network and retry",
            ) from exc
        return _payload_acr(payload)

    def push(self, asin: str, acr: str, position_ms: int) -> Any:
        body = {"acr": acr, "asin": asin, "position_ms": position_ms}
        try:
            # The only mutating Audible call in the backend (ARCHITECTURE 4.4).
            return self._client.put(f"1.0/lastpositions/{asin}", body=body)
        except Exception as exc:
            log(f"position write failed: {type(exc).__name__}")
            raise PipelineError(
                protocol.ErrorCode.NETWORK,
                f"could not write the position for {asin}",
                hint="check the network and retry",
            ) from exc


def fetch_positions(
    asins: Sequence[str], port: PositionsPort
) -> dict[str, dict[str, Any]]:
    """Read every ASIN's position in batches of at most 25 (ARCHITECTURE 4.6)."""
    unique = list(dict.fromkeys(asins))
    collected: dict[str, dict[str, Any]] = {}
    for batch in batches(unique):
        try:
            collected.update(port.fetch_batch(batch))
        except PipelineError:
            raise
        except Exception as exc:  # any library failure is a read failure
            log(f"reading remote positions failed: {type(exc).__name__}")
            raise PipelineError(
                protocol.ErrorCode.NETWORK,
                "could not read the remote positions",
                hint="check the network and retry",
            ) from exc
    return {asin: collected.get(asin, empty_entry()) for asin in unique}


def load_remote(path: Path) -> dict[str, dict[str, Any]]:
    """Read ``remote.json`` as clean entries; ``{}`` when absent or malformed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    entries: dict[str, dict[str, Any]] = {}
    for asin, entry in data.items():
        if not isinstance(asin, str):
            continue
        cleaned = _clean(entry)
        if cleaned is not None:
            entries[asin] = cleaned
    return entries


def meta_acr(books_dir: Path, asin: str) -> str | None:
    """The cached ``acr`` from a local book's ``meta.json``, else ``None``."""
    acr = read_meta(book_dir(books_dir, asin)).get("acr")
    return acr if isinstance(acr, str) and acr else None


def push_position(
    asin: str,
    position_ms: int,
    *,
    books_dir: Path,
    port: PushPort,
    local_updated_at: str | None = None,
) -> None:
    """Write one locally-listened position back to the account (4.6).

    The remote position is re-read immediately before the write; when it is
    newer than ``local_updated_at`` (default: now) the push is refused as
    ``stale``. ``acr`` is read from the local ``meta.json`` when the book is
    downloaded, and otherwise from the content metadata; without either the
    write is ``unsupported``.
    """
    remote = port.fetch_batch([asin]).get(asin, empty_entry())
    if is_remote_newer(remote, local_updated_at or iso_now()):
        raise PipelineError(
            protocol.ErrorCode.STALE,
            f"the remote position for {asin} is newer than this listening",
            hint="resume from the remote position instead of pushing",
        )
    acr = meta_acr(books_dir, asin) or port.fetch_acr(asin)
    if not acr:
        raise PipelineError(
            protocol.ErrorCode.UNSUPPORTED,
            f"no acr for {asin}; the position cannot be written",
            hint="download the book first, or retry when the network is up",
        )
    port.push(asin, acr, position_ms)


def write_remote(path: Path, items: dict[str, dict[str, Any]]) -> None:
    """Write ``remote.json`` atomically (ARCHITECTURE 3, 4.8)."""
    payload = {
        asin: {"ms": int(entry["ms"]), "updated_at": entry.get("updated_at")}
        for asin, entry in items.items()
    }
    fsutil.atomic_write_json(path, payload)

"""B4 — ``sync``: the catalog, the covers and the remote-position cache.

ARCHITECTURE 4.5 (catalog fields, ``Podcast*`` filtered, ``Lecture`` kept),
4.6 (positions read in batches of at most 25) and 4.8 (``catalog.json`` and
``remote.json`` are written by ``sync``; ``state.json`` never is). The
acceptance list is covered here: fake mode yields the fixture catalog, an
interrupted sync leaves the old catalog intact, and ``sync`` never pushes a
position.
"""

from __future__ import annotations

import http.client
import json
import socket
import urllib.request
from pathlib import Path

import pytest
from omarchy_audible import catalog, commands, positions, protocol
from omarchy_audible.errors import PipelineError

FIXTURE = catalog.fixture_items()
FIXTURE_ASINS = [item["asin"] for item in FIXTURE]

# Exactly the fields ARCHITECTURE 4.5 documents for a catalog book.
BOOK_KEYS = {
    "asin",
    "title",
    "subtitle",
    "authors",
    "narrators",
    "series",
    "cover",
    "runtime_min",
    "date_added",
    "percent_complete",
    "is_finished",
    "multipart",
}


def _collect() -> tuple[list[dict], object]:
    events: list[dict] = []

    def emit(event_type: str, **fields) -> None:
        events.append({"type": event_type, **fields})

    return events, emit


def _item(asin: str, **overrides) -> dict:
    item = {
        "asin": asin,
        "title": f"Invented {asin}",
        "content_type": "Product",
        "content_delivery_type": "SinglePartBook",
        "runtime_length_min": 10,
    }
    item.update(overrides)
    return item


class _StaticLibrary:
    def __init__(self, items: list[dict]) -> None:
        self._items = items

    def pages(self):
        yield list(self._items), len(self._items)


class _TwoPageLibrary:
    def pages(self):
        yield [_item("B0PAGE00001")], 3
        yield [_item("B0PAGE00002"), _item("B0PAGE00003")], 3


class _BoomLibrary:
    def pages(self):
        yield [_item("B0NEW00001")], 1
        raise PipelineError(protocol.ErrorCode.NETWORK, "simulated interruption")


class _SpyPositions:
    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def fetch_batch(self, asins):
        self.batches.append(list(asins))
        entry = {"ms": 1000, "updated_at": "2026-01-01 00:00:00.0"}
        return {asin: dict(entry) for asin in asins}


# --- pure mapping (ARCHITECTURE 4.5) -----------------------------------------
def test_is_kept_drops_only_podcasts():
    assert catalog.is_kept({"content_type": "Product"}) is True
    assert catalog.is_kept({"content_type": "Lecture"}) is True
    assert catalog.is_kept({"content_type": "Podcast"}) is False
    assert catalog.is_kept({"content_type": "PodcastEpisode"}) is False
    assert catalog.is_kept({"content_type": "podcast"}) is False
    # A missing content type is not a podcast, so it is kept.
    assert catalog.is_kept({}) is True


def test_book_entry_maps_the_fixture_fields():
    item = next(entry for entry in FIXTURE if entry["asin"] == "B0FAKE0002")
    mapped = catalog.book_entry(item)
    assert mapped is not None
    book, cover_url = mapped

    assert set(book) == BOOK_KEYS
    assert book["asin"] == "B0FAKE0002"
    assert book["subtitle"] == "The Cinder Cycle, Book 2"
    assert book["authors"] == ["Ilse Varga"]
    assert book["narrators"] == ["Priya Ndlovu"]
    assert book["series"] == {"name": "The Cinder Cycle", "part": "2"}
    assert book["cover"] == "covers/B0FAKE0002.jpg"
    assert book["runtime_min"] == 731
    assert book["date_added"] == "2026-01-02T09:10:11.000Z"
    assert book["percent_complete"] == 0.0
    assert book["is_finished"] is False
    assert book["multipart"] is False
    assert cover_url == "https://example.invalid/covers/B0FAKE0002._SL500_.jpg"


def test_book_entry_flags_multipart_and_the_lecture_is_not_a_book_of_a_special_kind():
    multi = next(entry for entry in FIXTURE if entry["asin"] == "B0FAKE0003")
    lecture = next(entry for entry in FIXTURE if entry["asin"] == "B0FAKE0004")
    assert catalog.book_entry(multi)[0]["multipart"] is True
    assert catalog.book_entry(lecture)[0]["multipart"] is False
    # The lecture keeps its invented title and stays in the catalog.
    assert catalog.book_entry(lecture)[0]["title"] == "A Short Course in Starlight"


def test_book_entry_returns_none_without_an_asin():
    assert catalog.book_entry({"title": "no asin"}) is None


def test_build_catalog_keeps_products_and_lectures_only():
    items = [
        _item("B0KEEP00001"),
        _item("B0KEEP00002", content_type="Lecture", title="A Course"),
        _item("B0DROP00001", content_type="Podcast"),
        _item("B0DROP00002", content_type="PodcastSeries"),
        {"title": "no asin"},
    ]
    built, covers = catalog.build_catalog(
        items, marketplace="us", synced_at="2026-10-04T12:00:00Z"
    )
    assert built["schema"] == catalog.CATALOG_SCHEMA
    assert built["marketplace"] == "us"
    assert built["synced_at"] == "2026-10-04T12:00:00Z"
    assert [book["asin"] for book in built["books"]] == ["B0KEEP00001", "B0KEEP00002"]
    assert covers == {}


# --- the CLI in fake mode -----------------------------------------------------
def test_fake_sync_writes_the_fixture_catalog(run_cli, validate_stream, paths):
    result = run_cli("sync", fake=True)
    assert result.returncode == 0, result.stderr
    parsed = validate_stream(result, expect_last="done")

    library_events = [
        event
        for event in parsed
        if event["type"] == "progress" and event["stage"] == "library"
    ]
    assert library_events
    assert library_events[-1]["of"] == len(FIXTURE_ASINS)
    assert library_events[-1]["n"] == len(FIXTURE_ASINS)

    built = json.loads(paths.catalog_file.read_text(encoding="utf-8"))
    assert built["schema"] == catalog.CATALOG_SCHEMA
    assert built["marketplace"] == "us"
    assert built["synced_at"]
    assert [book["asin"] for book in built["books"]] == FIXTURE_ASINS
    for book in built["books"]:
        assert set(book) == BOOK_KEYS

    remote = json.loads(paths.remote_file.read_text(encoding="utf-8"))
    assert set(remote) == set(FIXTURE_ASINS)
    assert remote["B0FAKE0001"] == {"ms": 0, "updated_at": None}


def test_sync_writes_remote_json_but_never_state_json(run_cli, paths):
    assert run_cli("sync", fake=True).returncode == 0
    assert paths.remote_file.is_file()
    # state.json belongs to Service.qml (ARCHITECTURE 4.8).
    assert not paths.state_file.exists()


def test_sync_reports_progress_for_every_page(paths):
    events, emit = _collect()
    catalog.run_sync(
        paths,
        fake=True,
        library=_TwoPageLibrary(),
        positions_port=positions.FakePositions(),
        cover_fetch=None,
        emit=emit,
    )
    reported = [
        (event["n"], event["of"]) for event in events if event["stage"] == "library"
    ]
    assert reported == [(1, 3), (3, 3)]


# --- atomicity ---------------------------------------------------------------
def test_interrupted_sync_leaves_the_old_catalog_intact(paths):
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    old_catalog = {
        "schema": 1,
        "synced_at": "2026-01-01T00:00:00Z",
        "marketplace": "us",
        "books": [{"asin": "B0OLD00001"}],
    }
    old_remote = {"B0OLD00001": {"ms": 5, "updated_at": None}}
    paths.catalog_file.write_text(json.dumps(old_catalog), encoding="utf-8")
    paths.remote_file.write_text(json.dumps(old_remote), encoding="utf-8")
    catalog_before = paths.catalog_file.read_bytes()
    remote_before = paths.remote_file.read_bytes()

    with pytest.raises(PipelineError) as info:
        catalog.run_sync(
            paths,
            fake=True,
            library=_BoomLibrary(),
            positions_port=positions.FakePositions(),
            cover_fetch=None,
            emit=lambda *args, **kwargs: None,
        )
    assert info.value.code == protocol.ErrorCode.NETWORK
    assert paths.catalog_file.read_bytes() == catalog_before
    assert paths.remote_file.read_bytes() == remote_before


def test_sync_leaves_no_half_written_temp_files(run_cli, paths):
    assert run_cli("sync", fake=True).returncode == 0
    leftovers = [path for path in paths.data_dir.rglob("*.tmp")]
    assert leftovers == []
    json.loads(paths.catalog_file.read_text(encoding="utf-8"))


# --- covers ------------------------------------------------------------------
def test_covers_are_downloaded_only_when_missing_unless_full(paths):
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return b"fake-jpeg"

    item = _item(
        "B0COVER001",
        product_images={"500": "https://example.invalid/B0COVER001.jpg"},
    )
    library = _StaticLibrary([item])
    port = positions.FakePositions()

    catalog.run_sync(
        paths, fake=True, library=library, positions_port=port, cover_fetch=fetch,
        emit=lambda *args, **kwargs: None,
    )
    target = paths.covers_dir / "B0COVER001.jpg"
    assert fetched == ["https://example.invalid/B0COVER001.jpg"]
    assert target.read_bytes() == b"fake-jpeg"

    # A second run finds the cover present and does not download it again.
    catalog.run_sync(
        paths, fake=True, library=library, positions_port=port, cover_fetch=fetch,
        emit=lambda *args, **kwargs: None,
    )
    assert len(fetched) == 1

    # --full refreshes it anyway.
    catalog.run_sync(
        paths, fake=True, full=True, library=library, positions_port=port,
        cover_fetch=fetch, emit=lambda *args, **kwargs: None,
    )
    assert len(fetched) == 2


def test_a_failed_cover_download_does_not_fail_the_sync(paths):
    def fetch(url: str) -> bytes:
        raise OSError("no network")

    catalog.run_sync(
        paths,
        fake=True,
        library=_StaticLibrary(
            [_item("B0COVER002", product_images={"500": "https://x.invalid/c.jpg"})]
        ),
        positions_port=positions.FakePositions(),
        cover_fetch=fetch,
        emit=lambda *args, **kwargs: None,
    )
    built = json.loads(paths.catalog_file.read_text(encoding="utf-8"))
    assert [book["asin"] for book in built["books"]] == ["B0COVER002"]
    assert not (paths.covers_dir / "B0COVER002.jpg").exists()


# --- remote positions (ARCHITECTURE 4.6) -------------------------------------
def test_position_batches_are_never_larger_than_25():
    asins = [f"B0{i:08d}" for i in range(60)]
    grouped = positions.batches(asins)
    assert [len(batch) for batch in grouped] == [25, 25, 10]
    assert [asin for batch in grouped for asin in batch] == asins


def test_sync_fetches_positions_in_batches_of_at_most_25(paths):
    asins = [f"B0POS{i:05d}" for i in range(60)]
    library = _StaticLibrary([_item(asin) for asin in asins])
    spy = _SpyPositions()

    catalog.run_sync(
        paths,
        fake=True,
        library=library,
        positions_port=spy,
        cover_fetch=None,
        emit=lambda *args, **kwargs: None,
    )

    assert spy.batches
    assert all(len(batch) <= 25 for batch in spy.batches)
    assert sorted(asin for batch in spy.batches for asin in batch) == sorted(asins)
    remote = json.loads(paths.remote_file.read_text(encoding="utf-8"))
    assert set(remote) == set(asins)
    assert remote[asins[0]] == {"ms": 1000, "updated_at": "2026-01-01 00:00:00.0"}


def test_parse_lastpositions_maps_exists_and_missing():
    payload = {
        "asin_last_position_heard_annots": [
            {
                "asin": "B0EXIST001",
                "last_position_heard": {
                    "status": "Exists",
                    "position_ms": 123,
                    "last_updated": "2026-01-01 00:00:00.0",
                },
            },
            {"asin": "B0MISSING1", "last_position_heard": {"status": "DoesNotExist"}},
        ]
    }
    parsed = positions.parse_lastpositions(
        payload, ["B0EXIST001", "B0MISSING1", "B0ABSENT01"]
    )
    assert parsed["B0EXIST001"] == {
        "ms": 123,
        "updated_at": "2026-01-01 00:00:00.0",
    }
    assert parsed["B0MISSING1"] == {"ms": 0, "updated_at": None}
    # A requested asin the response never mentions still gets an entry.
    assert parsed["B0ABSENT01"] == {"ms": 0, "updated_at": None}


# --- safety ------------------------------------------------------------------
def test_sync_never_pushes_a_position():
    module_dir = Path(__file__).resolve().parents[1] / "backend" / "omarchy_audible"
    for name in ("catalog.py", "positions.py"):
        text = (module_dir / name).read_text(encoding="utf-8")
        compact = text.replace(" ", "")
        # No mutating API call: the read side only ever calls ``.get(...)``.
        assert ".put(" not in compact, name
        assert ".post(" not in compact, name
        assert ".patch(" not in compact, name
        # No reference to the push command or a push helper.
        assert '"position-push"' not in text, name
        assert "position_push" not in text, name
        assert "push_position" not in text, name


def test_sync_is_a_job_command():
    assert commands.REGISTRY["sync"].is_job is True


def test_fake_sync_makes_no_network_call(env, monkeypatch, capsys, paths):
    """Run ``sync --fake`` in-process with every socket entry point blocked."""

    def blocked(*_args, **_kwargs):
        raise AssertionError("fake sync attempted a network call")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", blocked)
    for key in (
        "HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_RUNTIME_DIR",
        "OMARCHY_AUDIBLE_BOOKS_DIR",
    ):
        monkeypatch.setenv(key, env[key])
    monkeypatch.delenv("OMARCHY_AUDIBLE_FAKE", raising=False)

    from omarchy_audible.cli import main

    code = main(["sync", "--fake"])
    assert code == 0
    events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    assert events[-1]["type"] == "done"
    built = json.loads(paths.catalog_file.read_text(encoding="utf-8"))
    assert [book["asin"] for book in built["books"]] == FIXTURE_ASINS


def test_real_mode_without_a_login_reports_auth_failed(paths):
    with pytest.raises(PipelineError) as info:
        catalog.run_sync(paths, fake=False, emit=lambda *args, **kwargs: None)
    assert info.value.code == protocol.ErrorCode.AUTH_FAILED
    assert not paths.catalog_file.exists()


# --- the real library port: paging and the image_sizes fallback --------------
class _FakeClient:
    """The slice of ``audible.Client`` the library page needs, with recorded calls."""

    def __init__(self, pages: list[dict], *, reject_image_sizes: bool = False) -> None:
        self._pages = pages
        self.reject_image_sizes = reject_image_sizes
        self.calls: list[tuple[str, dict]] = []

    def get(self, endpoint: str, **params):
        self.calls.append((endpoint, params))
        if "image_sizes" in params and self.reject_image_sizes:
            raise RuntimeError("unsupported parameter")
        return self._pages[int(params.get("page", 1)) - 1]


def _payload(count: int, prefix: str, total: int, start: int = 0) -> dict:
    items = [_item(f"{prefix}{index:05d}") for index in range(start, start + count)]
    return {"items": items, "total_results": total}


def test_real_library_pages_with_the_documented_request():
    client = _FakeClient(
        [_payload(50, "B0REAL", 60), _payload(10, "B0REAL", 60, start=50)]
    )
    pages = list(catalog.RealLibrary(client).pages())

    assert [len(batch) for batch, _total in pages] == [50, 10]
    assert [total for _batch, total in pages] == [60, 60]
    endpoint, params = client.calls[0]
    assert endpoint == catalog.LIBRARY_ENDPOINT
    assert params["num_results"] == catalog.PAGE_SIZE
    assert params["response_groups"] == catalog.RESPONSE_GROUPS
    assert params["page"] == 1
    assert params["image_sizes"] == "252"


def test_real_library_withdraws_image_sizes_when_the_api_rejects_it():
    client = _FakeClient(
        [{"items": [_item("B0IMGSZ001")], "total_results": 1}],
        reject_image_sizes=True,
    )
    pages = list(catalog.RealLibrary(client).pages())

    assert [len(batch) for batch, _total in pages] == [1]
    assert "image_sizes" in client.calls[0][1]
    assert "image_sizes" not in client.calls[1][1]


def test_real_library_does_not_report_an_empty_trailing_page():
    client = _FakeClient(
        [
            _payload(50, "B0EXACT", 50),
            {"items": [], "total_results": 50},
        ]
    )
    pages = list(catalog.RealLibrary(client).pages())

    assert len(pages) == 1
    assert len(client.calls) == 2  # the short/empty page is still inspected

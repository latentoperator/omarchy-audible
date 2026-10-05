"""P3a — ``qml/lib/Library.js``: rows, the §5.3 state machine, sort/filter/
search and the ``state.json`` v1 parse/serialize.

These run in PySide6's ``QJSEngine`` (the engine Quickshell uses) through the
loader in ``tests/qjs.py``. The catalog shapes are the backend's own: the
fixture goes through ``catalog.build_catalog`` exactly as ``sync`` would.
"""

from __future__ import annotations

import json

import pytest

import qjs
from omarchy_audible.catalog import build_catalog, fixture_items

EXPECTED_API = {
    "FILTER_ALL",
    "FILTER_IN_PROGRESS",
    "FILTER_LOCAL",
    "SCHEMA_VERSION",
    "SORT_ADDED",
    "SORT_AUTHOR",
    "SORT_RECENT",
    "SORT_TITLE",
    "STATE_CLOUD",
    "STATE_CONVERTING",
    "STATE_DOWNLOADING",
    "STATE_ERROR",
    "STATE_LOCAL",
    "STATE_QUEUED",
    "_p",
    "buildRows",
    "filterRows",
    "parseState",
    "searchRows",
    "serializeState",
    "sortRows",
}

A1, A2, A3, A4, A5 = (
    "B0FAKE0001",
    "B0FAKE0002",
    "B0FAKE0003",
    "B0FAKE0004",
    "B0FAKE0005",
)
ALL_ASINS = [A1, A2, A3, A4, A5]


@pytest.fixture(scope="module")
def library() -> qjs.JsModule:
    return qjs.load("Library")


@pytest.fixture(scope="module")
def catalog() -> dict:
    built, _covers = build_catalog(
        fixture_items(), marketplace="us", synced_at="2026-10-05T00:00:00Z"
    )
    return built


def build(
    module: qjs.JsModule,
    catalog,
    *,
    remote=None,
    state=None,
    local=None,
    jobs=None,
) -> list[dict]:
    return module.call("buildRows", catalog, remote, state, local, jobs)


def rows_by_asin(rows: list[dict]) -> dict[str, dict]:
    return {row["asin"]: row for row in rows}


def asins(rows: list[dict]) -> list[str]:
    return [row["asin"] for row in rows]


# --- API and constants -------------------------------------------------------
def test_exports_the_expected_api(library: qjs.JsModule) -> None:
    assert set(library.functions) == EXPECTED_API


def test_state_and_key_constants(library: qjs.JsModule) -> None:
    assert library.evaluate("SCHEMA_VERSION") == 1
    assert library.evaluate("STATE_CLOUD") == "cloud"
    assert library.evaluate("STATE_QUEUED") == "queued"
    assert library.evaluate("STATE_DOWNLOADING") == "downloading"
    assert library.evaluate("STATE_CONVERTING") == "converting"
    assert library.evaluate("STATE_LOCAL") == "local"
    assert library.evaluate("STATE_ERROR") == "error"
    assert library.evaluate("SORT_RECENT") == "recent"
    assert library.evaluate("SORT_ADDED") == "added"
    assert library.evaluate("SORT_TITLE") == "title"
    assert library.evaluate("SORT_AUTHOR") == "author"
    assert library.evaluate("FILTER_ALL") == "all"
    assert library.evaluate("FILTER_LOCAL") == "local"
    assert library.evaluate("FILTER_IN_PROGRESS") == "in-progress"


def test_fixture_catalog_has_the_expected_shapes(catalog: dict) -> None:
    assert catalog["schema"] == 1
    assert catalog["marketplace"] == "us"
    assert [book["asin"] for book in catalog["books"]] == ALL_ASINS
    by_asin = {book["asin"]: book for book in catalog["books"]}
    assert by_asin[A1]["title"] == "The Lighthouse Ledger"
    assert by_asin[A2]["series"] == {"name": "The Cinder Cycle", "part": "2"}
    assert by_asin[A3]["runtime_min"] == 2244
    assert by_asin[A5]["is_finished"] is True


# --- buildRows basics --------------------------------------------------------
def test_one_cloud_row_per_catalog_book(library: qjs.JsModule, catalog: dict) -> None:
    rows = build(library, catalog)
    assert asins(rows) == ALL_ASINS
    for row in rows:
        assert row["state"] == "cloud"
        assert row["local"] is False
        assert row["size"] is None
        assert row["downloadedAt"] is None
        assert row["positionMs"] == 0
        assert row["recentKey"] is None
        assert row["jobState"] is None
        assert row["error"] is None
    first = rows_by_asin(rows)[A1]
    assert first["authors"] == ["Mara Quill"]
    assert first["narrators"] == ["Owen Hale"]
    assert first["cover"] == "covers/B0FAKE0001.jpg"
    assert first["runtimeMin"] == 512
    assert first["multipart"] is False


def test_a_local_scan_entry_wins(library: qjs.JsModule, catalog: dict) -> None:
    local = [{"asin": A1, "size": 12345, "downloaded_at": "2026-02-03T04:05:06Z"}]
    row = rows_by_asin(build(library, catalog, local=local))[A1]
    assert row["state"] == "local"
    assert row["local"] is True
    assert row["size"] == 12345
    assert row["downloadedAt"] == "2026-02-03T04:05:06Z"


def test_local_beats_a_job_for_the_same_book(library: qjs.JsModule, catalog: dict) -> None:
    local = [{"asin": A1, "size": 1, "downloaded_at": "2026-02-03T04:05:06Z"}]
    jobs = [{"asin": A1, "state": "downloading"}]
    row = rows_by_asin(build(library, catalog, local=local, jobs=jobs))[A1]
    assert row["state"] == "local"


@pytest.mark.parametrize(
    "asin,job_state",
    [
        (A1, "queued"),
        (A2, "downloading"),
        (A3, "converting"),
        (A4, "error"),
    ],
)
def test_every_job_state_is_reflected(
    library: qjs.JsModule, catalog: dict, asin: str, job_state: str
) -> None:
    rows = rows_by_asin(build(library, catalog, jobs=[{"asin": asin, "state": job_state}]))
    assert rows[asin]["state"] == job_state
    assert rows[asin]["jobState"] == job_state
    assert rows[A5]["state"] == "cloud"


def test_a_job_error_carries_its_message(library: qjs.JsModule, catalog: dict) -> None:
    jobs = [{"asin": A4, "state": "error", "message": "disk full"}]
    row = rows_by_asin(build(library, catalog, jobs=jobs))[A4]
    assert row["state"] == "error"
    assert row["error"] == "disk full"


def test_job_states_accept_a_map(library: qjs.JsModule, catalog: dict) -> None:
    rows = rows_by_asin(build(library, catalog, jobs={A2: "converting"}))
    assert rows[A2]["state"] == "converting"


def test_the_most_advanced_job_state_wins(library: qjs.JsModule, catalog: dict) -> None:
    jobs = [{"asin": A2, "state": "queued"}, {"asin": A2, "state": "error", "message": "x"}]
    assert rows_by_asin(build(library, catalog, jobs=jobs))[A2]["state"] == "error"


def test_unknown_job_states_are_ignored(library: qjs.JsModule, catalog: dict) -> None:
    rows = rows_by_asin(build(library, catalog, jobs=[{"asin": A2, "state": "exploded"}]))
    assert rows[A2]["state"] == "cloud"


def test_local_and_jobs_for_books_outside_the_catalog_are_ignored(
    library: qjs.JsModule, catalog: dict
) -> None:
    rows = build(
        library,
        catalog,
        local=[{"asin": "NOTINCAT1", "size": 1, "downloaded_at": None}],
        jobs=[{"asin": "NOTINCAT2", "state": "error"}],
    )
    assert asins(rows) == ALL_ASINS


def test_build_rows_never_throws_on_bad_input(library: qjs.JsModule) -> None:
    assert library.call("buildRows", None, None, None, None, None) == []
    assert library.call("buildRows", "garbage", None, None, None, None) == []
    assert library.call("buildRows", {"books": "nope"}, None, None, None, None) == []
    assert build(
        library,
        [{"asin": ""}, {"no_asin": 1}, {"asin": A1}, "junk"],
    ) == [
        {
            "asin": A1,
            "title": "",
            "subtitle": None,
            "authors": [],
            "narrators": [],
            "series": None,
            "cover": None,
            "runtimeMin": None,
            "dateAdded": None,
            "isFinished": False,
            "multipart": False,
            "state": "cloud",
            "local": False,
            "size": None,
            "downloadedAt": None,
            "positionMs": 0,
            "percent": 0,
            "lastPlayedAt": None,
            "remoteUpdatedAt": None,
            "recentKey": None,
            "jobState": None,
            "error": None,
        }
    ]


# --- position merge (newest wins) -------------------------------------------
def merged_position(
    library: qjs.JsModule,
    catalog: dict,
    *,
    local_ms=None,
    local_at=None,
    remote_ms=None,
    remote_at=None,
) -> int:
    state = None
    if local_ms is not None or local_at is not None:
        state = {"books": {A1: {"ms": local_ms, "updated_at": local_at}}}
    remote = None
    if remote_ms is not None or remote_at is not None:
        remote = {A1: {"ms": remote_ms, "updated_at": remote_at}}
    row = rows_by_asin(build(library, catalog, state=state, remote=remote))[A1]
    return row["positionMs"]


def test_local_position_wins_when_it_is_newer(library: qjs.JsModule, catalog: dict) -> None:
    assert (
        merged_position(
            library,
            catalog,
            local_ms=5000,
            local_at="2026-05-01T00:00:00Z",
            remote_ms=9000,
            remote_at="2026-01-01T00:00:00Z",
        )
        == 5000
    )


def test_remote_position_wins_when_it_is_newer(library: qjs.JsModule, catalog: dict) -> None:
    assert (
        merged_position(
            library,
            catalog,
            local_ms=5000,
            local_at="2026-01-01T00:00:00Z",
            remote_ms=9000,
            remote_at="2026-06-01 00:00:00.0",
        )
        == 9000
    )


def test_equal_timestamps_go_to_the_local_entry(library: qjs.JsModule, catalog: dict) -> None:
    # The Audible no-timezone shape and the local ISO shape are the same instant.
    assert (
        merged_position(
            library,
            catalog,
            local_ms=5000,
            local_at="2025-08-09T21:14:03.000Z",
            remote_ms=9000,
            remote_at="2025-08-09 21:14:03.0",
        )
        == 5000
    )


def test_a_missing_remote_entry_keeps_the_local_position(
    library: qjs.JsModule, catalog: dict
) -> None:
    assert merged_position(library, catalog, local_ms=7000, local_at=None) == 7000


def test_a_missing_local_entry_keeps_the_remote_position(
    library: qjs.JsModule, catalog: dict
) -> None:
    assert merged_position(library, catalog, remote_ms=8000, remote_at="2026-06-01T00:00:00Z") == 8000


def test_no_positions_means_zero(library: qjs.JsModule, catalog: dict) -> None:
    assert merged_position(library, catalog) == 0


def test_a_local_entry_without_a_timestamp_loses_to_a_timestamped_remote(
    library: qjs.JsModule, catalog: dict
) -> None:
    assert (
        merged_position(library, catalog, local_ms=5000, remote_ms=9000, remote_at="2026-06-01T00:00:00Z")
        == 9000
    )


# --- recentKey ---------------------------------------------------------------
def recent_key(
    library: qjs.JsModule,
    catalog: dict,
    *,
    last_played_at=None,
    remote_at=None,
) -> str | None:
    state = None
    if last_played_at is not None:
        state = {"books": {A1: {"ms": 0, "last_played_at": last_played_at}}}
    remote = None
    if remote_at is not None:
        remote = {A1: {"ms": 0, "updated_at": remote_at}}
    row = rows_by_asin(build(library, catalog, state=state, remote=remote))[A1]
    return row["recentKey"]


def test_recent_key_prefers_the_newer_remote_timestamp(library: qjs.JsModule, catalog: dict) -> None:
    assert (
        recent_key(
            library,
            catalog,
            last_played_at="2026-01-01T00:00:00Z",
            remote_at="2026-02-01 00:00:00.0",
        )
        == "2026-02-01 00:00:00.0"
    )


def test_recent_key_prefers_the_newer_local_timestamp(library: qjs.JsModule, catalog: dict) -> None:
    assert (
        recent_key(
            library,
            catalog,
            last_played_at="2026-03-01T00:00:00Z",
            remote_at="2026-02-01T00:00:00Z",
        )
        == "2026-03-01T00:00:00Z"
    )


def test_recent_key_uses_the_only_value_available(library: qjs.JsModule, catalog: dict) -> None:
    assert recent_key(library, catalog, last_played_at="2026-03-01T00:00:00Z") == "2026-03-01T00:00:00Z"
    assert recent_key(library, catalog, remote_at="2026-03-01T00:00:00Z") == "2026-03-01T00:00:00Z"
    assert recent_key(library, catalog) is None


def test_recent_key_compares_no_timezone_as_utc(library: qjs.JsModule, catalog: dict) -> None:
    # Same instant: the local ISO form is not "newer" than the Audible form.
    assert (
        recent_key(
            library,
            catalog,
            last_played_at="2025-08-09T21:14:03.000Z",
            remote_at="2025-08-09 21:14:03.0",
        )
        == "2025-08-09T21:14:03.000Z"
    )


# --- percent -----------------------------------------------------------------
def test_percent_falls_back_to_the_catalog_when_there_is_no_position(
    library: qjs.JsModule, catalog: dict
) -> None:
    rows = rows_by_asin(build(library, catalog))
    assert rows[A1]["percent"] == pytest.approx(12.5)
    assert rows[A3]["percent"] == pytest.approx(41.0)
    assert rows[A4]["percent"] == pytest.approx(3.2)
    assert rows[A5]["percent"] == pytest.approx(100.0)


def test_percent_is_derived_from_the_merged_position(library: qjs.JsModule, catalog: dict) -> None:
    # 2244 minutes * 60000 ms; 41% of it.
    remote = {A3: {"ms": 55202400, "updated_at": "2026-06-01T00:00:00Z"}}
    rows = rows_by_asin(build(library, catalog, remote=remote))
    assert rows[A3]["percent"] == pytest.approx(41.0)


def test_percent_is_clamped_to_one_hundred(library: qjs.JsModule, catalog: dict) -> None:
    remote = {A1: {"ms": 512 * 60000 * 3, "updated_at": "2026-06-01T00:00:00Z"}}
    row = rows_by_asin(build(library, catalog, remote=remote))[A1]
    assert row["percent"] == 100


# --- sortRows ----------------------------------------------------------------
def recent_input() -> tuple[dict, dict, dict]:
    state = {
        "books": {
            A1: {"last_played_at": "2026-01-01T00:00:00Z"},
            A3: {"last_played_at": "2025-12-01T00:00:00Z"},
            A5: {"last_played_at": "2025-06-01T00:00:00Z"},
        }
    }
    remote = {
        A2: {"ms": 0, "updated_at": "2026-02-01 00:00:00.0"},
        A3: {"ms": 0, "updated_at": "2025-11-01T00:00:00Z"},
        A5: {"ms": 0, "updated_at": "2026-03-01T00:00:00Z"},
    }
    return state, remote, {}


def test_sort_recent_newest_first_with_missing_last(library: qjs.JsModule, catalog: dict) -> None:
    state, remote, _ = recent_input()
    rows = build(library, catalog, state=state, remote=remote)
    assert asins(library.call("sortRows", rows, "recent")) == [A5, A2, A1, A3, A4]


def test_sort_added_newest_first(library: qjs.JsModule, catalog: dict) -> None:
    rows = build(library, catalog)
    assert asins(library.call("sortRows", rows, "added")) == [A2, A5, A1, A4, A3]


def test_sort_title_ignores_articles_and_case(library: qjs.JsModule, catalog: dict) -> None:
    rows = build(library, catalog)
    assert asins(library.call("sortRows", rows, "title")) == [A3, A2, A1, A5, A4]


def test_sort_author_uses_surname(library: qjs.JsModule, catalog: dict) -> None:
    # Abernathy, Fairweather, Quill, Reyes (after "Dr."), Varga.
    rows = build(library, catalog)
    assert asins(library.call("sortRows", rows, "author")) == [A5, A3, A1, A4, A2]


def test_sort_title_strips_articles() -> None:
    library = qjs.load("Library")
    rows = [
        {"title": "The Beta", "authors": ["The Zenith"], "dateAdded": None, "recentKey": None},
        {"title": "Alpha", "authors": ["A Young"], "dateAdded": None, "recentKey": None},
        {"title": "An Epsilon", "authors": ["An Aardvark"], "dateAdded": None, "recentKey": None},
    ]
    assert [row["title"] for row in library.call("sortRows", rows, "title")] == [
        "Alpha",
        "The Beta",
        "An Epsilon",
    ]
    # Author names keep a leading "A"/"An"/"The"; they sort by surname.
    assert [row["authors"][0] for row in library.call("sortRows", rows, "author")] == [
        "An Aardvark",
        "A Young",
        "The Zenith",
    ]


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Dr. Tamsin Reyes", "reyes tamsin"),
        ("Tamsin Reyes", "reyes tamsin"),
        ("Martin Luther King Jr.", "king martin luther"),
        ("Martin Luther King, Jr.", "king martin luther"),
        ("Jane Doe PhD", "doe jane"),
        ("Prof. Sir Ian Moss III", "moss ian"),
        ("Ursula K. Le Guin", "le guin ursula k."),
        ("Daphne du Maurier", "du maurier daphne"),
        ("Ludwig van der Berg", "van der berg ludwig"),
        ("Reyes, Tamsin", "reyes tamsin"),
        ("Zoë Ångström", "angstrom zoe"),
        ("Plato", "plato"),
        ("Dr.", "dr."),
        ("Jr.", "jr."),
        ("A Young", "young a"),
        ("The Zenith", "zenith the"),
        ("  Mara   Quill  ", "quill mara"),
        ("", ""),
    ],
)
def test_author_key(library: qjs.JsModule, name: str, key: str) -> None:
    assert library.evaluate(f"_p.authorKey({json.dumps(name)})") == key


def test_author_key_tolerates_bad_input(library: qjs.JsModule) -> None:
    for expression in ("null", "undefined", "7", "{}", "[]"):
        assert library.evaluate(f"_p.authorKey({expression})") == ""


def test_sort_author_by_surname_with_honorifics_and_suffixes() -> None:
    library = qjs.load("Library")
    names = [
        "Dr. Tamsin Reyes",
        "Martin Luther King Jr.",
        "Ursula K. Le Guin",
        "June Abernathy",
        "Jane Doe PhD",
        "Daphne du Maurier",
    ]
    rows = [{"title": n, "authors": [n], "dateAdded": None, "recentKey": None} for n in names]
    assert [row["authors"][0] for row in library.call("sortRows", rows, "author")] == [
        "June Abernathy",
        "Jane Doe PhD",
        "Daphne du Maurier",
        "Martin Luther King Jr.",
        "Ursula K. Le Guin",
        "Dr. Tamsin Reyes",
    ]


def test_sort_is_stable_for_equal_keys() -> None:
    library = qjs.load("Library")
    rows = [
        {"title": "The Alpha", "authors": ["Author"], "dateAdded": None, "recentKey": None},
        {"title": "alpha", "authors": ["author"], "dateAdded": None, "recentKey": None},
        {"title": "A Alpha", "authors": ["an author"], "dateAdded": None, "recentKey": None},
    ]
    result = library.call("sortRows", rows, "title")
    assert [row["title"] for row in result] == ["The Alpha", "alpha", "A Alpha"]
    result = library.call("sortRows", rows, "author")
    assert [row["authors"][0] for row in result] == ["Author", "author", "an author"]


def test_sort_does_not_mutate_its_input(library: qjs.JsModule, catalog: dict) -> None:
    rows = build(library, catalog)
    before = [row["asin"] for row in rows]
    library.call("sortRows", rows, "title")
    assert [row["asin"] for row in rows] == before


def test_sort_with_an_unknown_key_returns_a_copy(library: qjs.JsModule, catalog: dict) -> None:
    rows = build(library, catalog)
    assert asins(library.call("sortRows", rows, "sideways")) == ALL_ASINS


def test_sort_tolerates_bad_input(library: qjs.JsModule) -> None:
    assert library.call("sortRows", None, "title") == []
    assert library.call("sortRows", [{"title": None, "authors": None}], "title") is not None


# --- filterRows --------------------------------------------------------------
def test_filter_all_returns_every_row(library: qjs.JsModule, catalog: dict) -> None:
    rows = build(library, catalog)
    assert asins(library.call("filterRows", rows, "all")) == ALL_ASINS


def test_filter_local_keeps_downloaded_books(library: qjs.JsModule, catalog: dict) -> None:
    local = [
        {"asin": A2, "size": 10, "downloaded_at": "2026-01-01T00:00:00Z"},
        {"asin": A5, "size": 20, "downloaded_at": "2026-01-02T00:00:00Z"},
    ]
    rows = build(library, catalog, local=local)
    assert asins(library.call("filterRows", rows, "local")) == [A2, A5]


def test_filter_in_progress_keeps_started_unfinished_books(
    library: qjs.JsModule, catalog: dict
) -> None:
    rows = build(library, catalog)
    assert asins(library.call("filterRows", rows, "in-progress")) == [A1, A3, A4]


def test_filter_in_progress_excludes_a_finished_book(library: qjs.JsModule, catalog: dict) -> None:
    # A5 is at 100% and finished; a book with a position but finished is out.
    remote = {A1: {"ms": 512 * 60000, "updated_at": "2026-06-01T00:00:00Z"}}
    state = {"books": {A1: {"finished": True}}}
    rows = build(library, catalog, remote=remote, state=state)
    assert A1 not in asins(library.call("filterRows", rows, "in-progress"))


def test_filter_unknown_value_behaves_like_all(library: qjs.JsModule, catalog: dict) -> None:
    rows = build(library, catalog)
    assert asins(library.call("filterRows", rows, "whatever")) == ALL_ASINS


def test_filter_tolerates_bad_input(library: qjs.JsModule) -> None:
    assert library.call("filterRows", None, "all") == []


# --- searchRows --------------------------------------------------------------
@pytest.fixture(scope="module")
def fixture_rows(library: qjs.JsModule, catalog: dict) -> list[dict]:
    return build(library, catalog)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("cinder", [A2]),  # series name
        ("varga", [A2]),  # author
        ("ndlovu", [A2]),  # narrator
        ("winter", [A3]),  # title
        ("seven novels", [A3]),  # subtitle
        ("astronomy", [A4]),  # subtitle
        ("fairweather", [A3]),  # author, case-insensitive
        ("QUILL", [A1]),  # author, case-insensitive
        ("winter tales", [A3]),  # every token must match
        ("winter varga", []),  # tokens from different books do not match
        ("zzzz", []),
        ("", ALL_ASINS),
        ("   ", ALL_ASINS),
    ],
)
def test_search(fixture_rows: list[dict], text: str, expected: list[str], library: qjs.JsModule) -> None:
    assert asins(library.call("searchRows", fixture_rows, text)) == expected


def test_search_is_accent_insensitive_and_tolerates_bad_input() -> None:
    library = qjs.load("Library")
    catalog = [
        {
            "asin": "B0ACCENT01",
            "title": "Café Noir",
            "subtitle": None,
            "authors": ["Zoë Ångström"],
            "narrators": [],
            "series": {"name": "Thé Vert", "part": "1"},
        }
    ]
    rows = library.call("buildRows", catalog, None, None, None, None)
    assert asins(library.call("searchRows", rows, "cafe")) == ["B0ACCENT01"]
    assert asins(library.call("searchRows", rows, "café")) == ["B0ACCENT01"]
    assert asins(library.call("searchRows", rows, "zoe")) == ["B0ACCENT01"]
    assert asins(library.call("searchRows", rows, "angstrom")) == ["B0ACCENT01"]
    assert asins(library.call("searchRows", rows, "the vert")) == ["B0ACCENT01"]
    assert library.call("searchRows", None, "x") == []
    assert library.call("searchRows", rows, None) == rows


# --- parseState --------------------------------------------------------------
def sample_state() -> dict:
    return {
        "schema": 1,
        "books": {
            "B2": {
                "ms": 1000.0,
                "updated_at": "2025-08-09 21:14:03.0",
                "last_played_at": "2026-01-01T00:00:00Z",
                "played_since_download": True,
                "finished": False,
                "rating": 5,
            },
            "B1": {"ms": 0},
        },
        "push_queue": [
            {"asin": "B2", "ms": 1000, "at": "2026-01-01T00:00:00Z", "tries": 2}
        ],
        "volume": 0.8,
        "speed": 1.25,
        "device": "laptop",
    }


def test_parse_state_valid_keeps_unknown_keys(library: qjs.JsModule) -> None:
    parsed = library.call("parseState", json.dumps(sample_state()))
    assert parsed["schema"] == 1
    assert parsed["recovered"] is False
    assert parsed["volume"] == 0.8
    assert parsed["speed"] == 1.25
    assert parsed["device"] == "laptop"
    assert parsed["books"]["B2"] == {
        "ms": 1000,
        "updated_at": "2025-08-09 21:14:03.0",
        "last_played_at": "2026-01-01T00:00:00Z",
        "played_since_download": True,
        "finished": False,
        "rating": 5,
    }
    # A book entry is normalised: missing fields get their defaults.
    assert parsed["books"]["B1"] == {
        "ms": 0,
        "updated_at": None,
        "last_played_at": None,
        "played_since_download": False,
        "finished": False,
    }
    assert parsed["push_queue"] == [
        {"asin": "B2", "ms": 1000, "at": "2026-01-01T00:00:00Z", "tries": 2}
    ]


def test_parse_state_minimal_is_not_recovered(library: qjs.JsModule) -> None:
    parsed = library.call("parseState", '{"schema":1}')
    assert parsed == {
        "schema": 1,
        "books": {},
        "push_queue": [],
        "volume": None,
        "speed": None,
        "recovered": False,
    }


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "   ",
        "not json at all",
        '{"schema":1,"books":{"B0',
        '{"schema":2,"books":{}}',
        '{"books":{}}',
        "[1,2,3]",
        "42",
        "null",
    ],
)
def test_parse_state_recovers_from_bad_input(library: qjs.JsModule, text) -> None:
    parsed = library.call("parseState", text)
    assert parsed == {
        "schema": 1,
        "books": {},
        "push_queue": [],
        "volume": None,
        "speed": None,
        "recovered": True,
    }


def test_parse_state_recovers_when_books_or_queue_have_the_wrong_type(
    library: qjs.JsModule,
) -> None:
    parsed = library.call("parseState", '{"schema":1,"books":"nope","push_queue":"nope"}')
    assert parsed["recovered"] is True
    assert parsed["books"] == {}
    assert parsed["push_queue"] == []


def test_parse_state_drops_non_numeric_volume_and_speed(library: qjs.JsModule) -> None:
    parsed = library.call("parseState", '{"schema":1,"volume":"loud","speed":true}')
    assert parsed["volume"] is None
    assert parsed["speed"] is None


def test_parse_state_drops_non_object_queue_entries(library: qjs.JsModule) -> None:
    parsed = library.call("parseState", '{"schema":1,"push_queue":[1,"x",null,{"asin":"B1"}]}')
    assert parsed["push_queue"] == [{"asin": "B1", "ms": 0, "at": None}]


# --- serializeState ----------------------------------------------------------
def test_serialize_state_is_deterministic_and_sorted(library: qjs.JsModule) -> None:
    first = {
        "schema": 1,
        "books": {"B2": {"ms": 2}, "B1": {"ms": 1}},
        "push_queue": [],
        "volume": 0.5,
        "speed": 1.0,
        "zeta": 1,
        "alpha": 2,
    }
    second = {
        "alpha": 2,
        "zeta": 1,
        "speed": 1.0,
        "volume": 0.5,
        "push_queue": [],
        "books": {"B1": {"ms": 1}, "B2": {"ms": 2}},
        "schema": 1,
    }
    text = library.call("serializeState", first)
    assert text == library.call("serializeState", second)
    parsed = json.loads(text)
    assert list(parsed) == ["schema", "books", "push_queue", "volume", "speed", "alpha", "zeta"]
    assert list(parsed["books"]) == ["B1", "B2"]
    assert text.find("recovered") == -1


def test_serialize_state_keeps_unknown_keys(library: qjs.JsModule) -> None:
    text = library.call(
        "serializeState",
        {
            "schema": 1,
            "books": {"B1": {"ms": 1, "bookmark": "here"}},
            "push_queue": [{"asin": "B1", "ms": 1, "at": None, "tries": 3}],
            "volume": None,
            "speed": None,
            "note": "hello",
        },
    )
    parsed = json.loads(text)
    assert parsed["note"] == "hello"
    assert parsed["books"]["B1"]["bookmark"] == "here"
    assert parsed["push_queue"][0]["tries"] == 3


def test_serialize_parse_round_trip(library: qjs.JsModule) -> None:
    text = library.call("serializeState", sample_state())
    parsed = library.call("parseState", text)
    # Serialization normalises every entry, so the round trip equals that
    # normalised form (defaults filled in, unknown keys kept).
    assert parsed == {
        "schema": 1,
        "books": {
            "B1": {
                "ms": 0,
                "updated_at": None,
                "last_played_at": None,
                "played_since_download": False,
                "finished": False,
            },
            "B2": {
                "ms": 1000,
                "updated_at": "2025-08-09 21:14:03.0",
                "last_played_at": "2026-01-01T00:00:00Z",
                "played_since_download": True,
                "finished": False,
                "rating": 5,
            },
        },
        "push_queue": [
            {"asin": "B2", "ms": 1000, "at": "2026-01-01T00:00:00Z", "tries": 2}
        ],
        "volume": 0.8,
        "speed": 1.25,
        "device": "laptop",
        "recovered": False,
    }


def test_serialize_state_never_throws_on_bad_input(library: qjs.JsModule) -> None:
    for value in (None, "garbage", 42, [1, 2]):
        text = library.call("serializeState", value)
        assert json.loads(text) == {
            "schema": 1,
            "books": {},
            "push_queue": [],
            "volume": None,
            "speed": None,
        }

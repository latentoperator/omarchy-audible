"""L2 — ``qml/lib/LibraryUi.js`` in PySide6's ``QJSEngine``.

The rows these functions see are the real ones: the backend builds the catalog
from ``fixtures/library-sample.json`` with ``catalog.build_catalog`` and
``Library.buildRows`` turns it into rows, exactly as the service does. That
covers every §5.3 row state, offline versus online, and the empty and
no-results list cases.
"""

from __future__ import annotations

import pytest

import qjs
from omarchy_audible.catalog import build_catalog, fixture_items

EXPECTED_API = {
    "ACTION_DOWNLOAD",
    "ACTION_NONE",
    "ACTION_PLAY",
    "ACTION_RETRY",
    "BADGE_CLOUD",
    "BADGE_CONVERTING",
    "BADGE_DOWNLOADING",
    "BADGE_ERROR",
    "BADGE_LOCAL",
    "BADGE_OFFLINE",
    "BADGE_QUEUED",
    "BANNER_OFFLINE",
    "BANNER_RECONNECT",
    "BANNER_SYNCING",
    "BYTES_PER_HOUR",
    "CHOICE_ASK",
    "CHOICE_RESUME",
    "CHOICE_START_OVER",
    "FINISH_TRAILING_MS",
    "ICON_DOWNLOAD",
    "ICON_PLAY",
    "ICON_RETRY",
    "PICK_CONFIRM",
    "PICK_DOWNLOAD",
    "PICK_NONE",
    "PICK_PLAY",
    "PICK_RETRY",
    "STATE_EMPTY",
    "STATE_ERROR",
    "STATE_LIST",
    "STATE_LOADING",
    "STATE_NO_RESULTS",
    "_p",
    "badge",
    "confirmValid",
    "estimatedBytes",
    "listState",
    "moveSelection",
    "pickDecision",
    "primaryAction",
    "resumeChoice",
    "rowIcon",
    "storage",
    "syncDue",
}

A1, A2, A3, A4, A5 = (
    "B0FAKE0001",
    "B0FAKE0002",
    "B0FAKE0003",
    "B0FAKE0004",
    "B0FAKE0005",
)
ALL_ASINS = [A1, A2, A3, A4, A5]

A5_DURATION_MS = 145 * 60000  # the fixture book is 145 minutes

# The five states other than `cloud` and their badge in the online case.
STATE_BADGES = [
    ("queued", "queued", "Queued"),
    ("downloading", "downloading", "Downloading"),
    ("converting", "converting", "Converting"),
    ("local", "local", "On this device"),
    ("error", "error", "Failed \u2014 Retry"),
]


@pytest.fixture(scope="module")
def ui() -> qjs.JsModule:
    return qjs.load("LibraryUi")


@pytest.fixture(scope="module")
def library() -> qjs.JsModule:
    return qjs.load("Library")


@pytest.fixture(scope="module")
def catalog() -> dict:
    built, _covers = build_catalog(
        fixture_items(), marketplace="us", synced_at="2026-10-05T00:00:00Z"
    )
    return built


def build_rows(
    library: qjs.JsModule,
    catalog: dict,
    *,
    remote=None,
    state=None,
    local=None,
    jobs=None,
) -> list[dict]:
    return library.call("buildRows", catalog, remote, state, local, jobs)


def by_asin(rows: list[dict]) -> dict[str, dict]:
    return {row["asin"]: row for row in rows}


def row_in_state(library: qjs.JsModule, catalog: dict, state: str) -> dict:
    """A real A2 row (a plain catalog book) in the requested §5.3 state."""
    local = (
        [{"asin": A2, "size": 100, "downloaded_at": "2026-01-01T00:00:00Z"}]
        if state == "local"
        else None
    )
    jobs = (
        [{"asin": A2, "state": state}]
        if state in ("queued", "downloading", "converting", "error")
        else None
    )
    return by_asin(build_rows(library, catalog, local=local, jobs=jobs))[A2]


def finished_a5(library: qjs.JsModule, catalog: dict, *, ms: int) -> dict:
    """The finished fixture book A5 with a local position of ``ms``."""
    state = {
        "books": {
            A5: {
                "ms": ms,
                "updated_at": "2026-06-01T00:00:00Z",
                "finished": True,
            }
        }
    }
    return by_asin(build_rows(library, catalog, state=state))[A5]


# --- API ---------------------------------------------------------------------
def test_exports_the_expected_api(ui: qjs.JsModule) -> None:
    assert set(ui.functions) == EXPECTED_API


def test_constant_values(ui: qjs.JsModule) -> None:
    assert ui.evaluate("FINISH_TRAILING_MS") == 30000
    assert ui.evaluate("BADGE_CLOUD") == "cloud"
    assert ui.evaluate("BADGE_OFFLINE") == "offline"
    assert ui.evaluate("BADGE_QUEUED") == "queued"
    assert ui.evaluate("BADGE_DOWNLOADING") == "downloading"
    assert ui.evaluate("BADGE_CONVERTING") == "converting"
    assert ui.evaluate("BADGE_LOCAL") == "local"
    assert ui.evaluate("BADGE_ERROR") == "error"
    assert ui.evaluate("ACTION_PLAY") == "play"
    assert ui.evaluate("ACTION_DOWNLOAD") == "download"
    assert ui.evaluate("ACTION_RETRY") == "retry"
    assert ui.evaluate("ACTION_NONE") == "none"
    assert ui.evaluate("CHOICE_RESUME") == "resume"
    assert ui.evaluate("CHOICE_ASK") == "ask"
    assert ui.evaluate("CHOICE_START_OVER") == "start-over"
    assert ui.evaluate("STATE_LOADING") == "loading"
    assert ui.evaluate("STATE_ERROR") == "error"
    assert ui.evaluate("STATE_EMPTY") == "empty"
    assert ui.evaluate("STATE_NO_RESULTS") == "no-results"
    assert ui.evaluate("STATE_LIST") == "list"
    assert ui.evaluate("BANNER_OFFLINE") == "offline"
    assert ui.evaluate("BANNER_RECONNECT") == "reconnect"
    assert ui.evaluate("BANNER_SYNCING") == "syncing"


# --- badge -------------------------------------------------------------------
def test_badge_cloud_online(
    ui: qjs.JsModule, library: qjs.JsModule, catalog: dict
) -> None:
    row = row_in_state(library, catalog, "cloud")
    assert ui.call("badge", row, None, False) == {"kind": "cloud", "label": "Cloud"}


def test_badge_cloud_offline(
    ui: qjs.JsModule, library: qjs.JsModule, catalog: dict
) -> None:
    row = row_in_state(library, catalog, "cloud")
    assert ui.call("badge", row, None, True) == {"kind": "offline", "label": "Offline"}


@pytest.mark.parametrize("state,kind,label", STATE_BADGES)
def test_badge_every_other_state(
    ui: qjs.JsModule,
    library: qjs.JsModule,
    catalog: dict,
    state: str,
    kind: str,
    label: str,
) -> None:
    row = row_in_state(library, catalog, state)
    assert ui.call("badge", row, None, False) == {"kind": kind, "label": label}


@pytest.mark.parametrize("state,kind,label", STATE_BADGES)
def test_badge_offline_does_not_hide_a_job_state(
    ui: qjs.JsModule,
    library: qjs.JsModule,
    catalog: dict,
    state: str,
    kind: str,
    label: str,
) -> None:
    # A downloaded book, a running job and a failed book all read the same
    # whether or not the network is down; only a cloud book goes "Offline".
    row = row_in_state(library, catalog, state)
    assert ui.call("badge", row, None, True) == {"kind": kind, "label": label}


def test_badge_downloading_shows_the_get_percent(
    ui: qjs.JsModule, library: qjs.JsModule, catalog: dict
) -> None:
    row = row_in_state(library, catalog, "downloading")
    progress = {"type": "progress", "stage": "download", "bytes": 512, "total": 1024}
    assert ui.call("badge", row, progress, False) == {
        "kind": "downloading",
        "label": "Downloading 50%",
    }


@pytest.mark.parametrize(
    "progress,expected",
    [
        ({"bytes": 1, "total": 3}, "Downloading 33%"),
        ({"bytes": 2, "total": 3}, "Downloading 67%"),
        ({"bytes": 5, "total": 6}, "Downloading 83%"),
        ({"bytes": 0, "total": 100}, "Downloading 0%"),
        ({"bytes": 100, "total": 100}, "Downloading 100%"),
        ({"bytes": 500, "total": 100}, "Downloading 100%"),
        ({"bytes": 0, "total": 0}, "Downloading"),
        ({"bytes": 5}, "Downloading"),
        ({"total": 100}, "Downloading"),
        ({"bytes": -1, "total": 100}, "Downloading"),
        ("garbage", "Downloading"),
        (None, "Downloading"),
    ],
)
def test_badge_downloading_percent_edges(
    ui: qjs.JsModule,
    library: qjs.JsModule,
    catalog: dict,
    progress,
    expected: str,
) -> None:
    row = row_in_state(library, catalog, "downloading")
    assert ui.call("badge", row, progress, False) == {
        "kind": "downloading",
        "label": expected,
    }


def test_badge_only_downloading_uses_progress(
    ui: qjs.JsModule, library: qjs.JsModule, catalog: dict
) -> None:
    # A converting book ignores the download progress object.
    row = row_in_state(library, catalog, "converting")
    progress = {"bytes": 512, "total": 1024}
    assert ui.call("badge", row, progress, False) == {
        "kind": "converting",
        "label": "Converting",
    }


@pytest.mark.parametrize(
    "row",
    [None, "garbage", 42, {}, {"state": "exploded"}, {"state": None}],
)
def test_badge_bad_input_reads_as_a_cloud_row(ui: qjs.JsModule, row) -> None:
    assert ui.call("badge", row, None, False) == {"kind": "cloud", "label": "Cloud"}
    assert ui.call("badge", row, None, True) == {"kind": "offline", "label": "Offline"}


# --- primaryAction -----------------------------------------------------------
@pytest.mark.parametrize(
    "state,offline,expected",
    [
        ("local", False, "play"),
        ("local", True, "play"),  # a downloaded book plays offline
        ("cloud", False, "download"),
        ("cloud", True, "none"),  # nothing to download while offline
        ("queued", False, "none"),
        ("queued", True, "none"),
        ("downloading", False, "none"),
        ("converting", False, "none"),
        ("converting", True, "none"),
        ("error", False, "retry"),
        ("error", True, "retry"),  # retry is offered offline too
    ],
)
def test_primary_action_every_state(
    ui: qjs.JsModule,
    library: qjs.JsModule,
    catalog: dict,
    state: str,
    offline: bool,
    expected: str,
) -> None:
    row = row_in_state(library, catalog, state)
    assert ui.call("primaryAction", row, offline) == expected


@pytest.mark.parametrize("row", [None, "garbage", {}, {"state": "exploded"}])
def test_primary_action_bad_input(ui: qjs.JsModule, row) -> None:
    # An unknown row is treated as a cloud book.
    assert ui.call("primaryAction", row, False) == "download"
    assert ui.call("primaryAction", row, True) == "none"


# --- resumeChoice ------------------------------------------------------------
def test_resume_choice_a_book_that_is_not_finished(
    ui: qjs.JsModule, library: qjs.JsModule, catalog: dict
) -> None:
    cloud = row_in_state(library, catalog, "cloud")
    local = row_in_state(library, catalog, "local")
    assert ui.call("resumeChoice", cloud, None) == "resume"
    assert ui.call("resumeChoice", local, A5_DURATION_MS) == "resume"


def test_resume_choice_finished_far_from_the_end_asks(
    ui: qjs.JsModule, library: qjs.JsModule, catalog: dict
) -> None:
    # A5 is finished in the fixture; position 0 is nowhere near the end.
    row = by_asin(build_rows(library, catalog))[A5]
    assert row["isFinished"] is True
    assert ui.call("resumeChoice", row, A5_DURATION_MS) == "ask"


def test_resume_choice_finished_at_the_end_starts_over(
    ui: qjs.JsModule, library: qjs.JsModule, catalog: dict
) -> None:
    row = finished_a5(library, catalog, ms=A5_DURATION_MS - 1000)
    assert ui.call("resumeChoice", row, A5_DURATION_MS) == "start-over"


@pytest.mark.parametrize(
    "offset,expected",
    [
        (30000, "start-over"),  # exactly 30 s from the end
        (30001, "ask"),  # 1 ms further out
        (0, "start-over"),
        (-1000, "start-over"),  # past the end
    ],
)
def test_resume_choice_thirty_second_boundary(
    ui: qjs.JsModule,
    library: qjs.JsModule,
    catalog: dict,
    offset: int,
    expected: str,
) -> None:
    row = finished_a5(library, catalog, ms=A5_DURATION_MS - offset)
    assert ui.call("resumeChoice", row, A5_DURATION_MS) == expected


def test_resume_choice_falls_back_to_the_row_runtime(
    ui: qjs.JsModule, library: qjs.JsModule, catalog: dict
) -> None:
    row = finished_a5(library, catalog, ms=A5_DURATION_MS - 1000)
    assert ui.call("resumeChoice", row, None) == "start-over"


def test_resume_choice_uses_the_given_duration_over_the_runtime(
    ui: qjs.JsModule, library: qjs.JsModule, catalog: dict
) -> None:
    # Near the end of a 145-minute book, but not of a 200-minute one.
    row = finished_a5(library, catalog, ms=A5_DURATION_MS - 1000)
    assert ui.call("resumeChoice", row, 200 * 60000) == "ask"


def test_resume_choice_finished_with_unknown_duration_asks(ui: qjs.JsModule) -> None:
    row = {"isFinished": True, "positionMs": 0, "runtimeMin": None}
    assert ui.call("resumeChoice", row, None) == "ask"
    assert ui.call("resumeChoice", row, 0) == "ask"
    assert ui.call("resumeChoice", row, -1) == "ask"
    assert ui.call("resumeChoice", row, "garbage") == "ask"


def test_resume_choice_bad_input_resumes(ui: qjs.JsModule) -> None:
    assert ui.call("resumeChoice", None, 1000) == "resume"
    assert ui.call("resumeChoice", "garbage", 1000) == "resume"
    assert ui.call("resumeChoice", {}, None) == "resume"


# --- listState ---------------------------------------------------------------
def test_list_state_defaults_to_loading(ui: qjs.JsModule) -> None:
    for value in (
        None,
        "garbage",
        {},
        {"catalogLoaded": False},
        {"catalogLoaded": "yes"},
    ):
        assert ui.call("listState", value) == {"state": "loading", "banner": None}


def test_list_state_empty(ui: qjs.JsModule) -> None:
    assert ui.call("listState", {"catalogLoaded": True, "total": 0, "shown": 0}) == {
        "state": "empty",
        "banner": None,
    }


def test_list_state_no_results(ui: qjs.JsModule) -> None:
    assert ui.call("listState", {"catalogLoaded": True, "total": 5, "shown": 0}) == {
        "state": "no-results",
        "banner": None,
    }


def test_list_state_list(ui: qjs.JsModule) -> None:
    assert ui.call("listState", {"catalogLoaded": True, "total": 5, "shown": 3}) == {
        "state": "list",
        "banner": None,
    }


def test_list_state_error_before_the_catalog_loads(ui: qjs.JsModule) -> None:
    assert ui.call("listState", {"catalogLoaded": False, "errorCode": "network"}) == {
        "state": "error",
        "banner": None,
    }


def test_list_state_auth_failed_is_reconnect(ui: qjs.JsModule) -> None:
    # Nothing cached yet: an error, with the reconnect banner.
    assert ui.call(
        "listState", {"catalogLoaded": False, "errorCode": "auth_failed"}
    ) == {"state": "error", "banner": "reconnect"}
    # A cached library stays usable; local playback is unaffected (FR-A4).
    assert ui.call(
        "listState",
        {"catalogLoaded": True, "total": 5, "shown": 5, "errorCode": "auth_failed"},
    ) == {"state": "list", "banner": "reconnect"}


def test_list_state_loaded_with_a_background_error_still_lists(
    ui: qjs.JsModule,
) -> None:
    assert ui.call(
        "listState",
        {"catalogLoaded": True, "total": 5, "shown": 5, "errorCode": "network"},
    ) == {"state": "list", "banner": None}


def test_list_state_syncing_banner(ui: qjs.JsModule) -> None:
    assert ui.call("listState", {"catalogLoaded": False, "syncing": True}) == {
        "state": "loading",
        "banner": "syncing",
    }
    assert ui.call(
        "listState", {"catalogLoaded": True, "total": 5, "shown": 5, "syncing": True}
    ) == {"state": "list", "banner": "syncing"}


def test_list_state_banner_precedence(ui: qjs.JsModule) -> None:
    # Offline beats syncing; reconnect beats offline.
    assert ui.call(
        "listState", {"catalogLoaded": False, "syncing": True, "offline": True}
    ) == {"state": "loading", "banner": "offline"}
    assert ui.call(
        "listState",
        {"catalogLoaded": True, "total": 5, "shown": 5, "offline": True},
    ) == {"state": "list", "banner": "offline"}
    assert ui.call(
        "listState",
        {"catalogLoaded": False, "offline": True, "errorCode": "auth_failed"},
    ) == {"state": "error", "banner": "reconnect"}


def test_list_state_ignores_bad_counts(ui: qjs.JsModule) -> None:
    assert ui.call(
        "listState", {"catalogLoaded": True, "total": "5", "shown": "3"}
    ) == {"state": "empty", "banner": None}
    assert ui.call("listState", {"catalogLoaded": True, "total": -3, "shown": 0}) == {
        "state": "empty",
        "banner": None,
    }
    assert ui.call("listState", {"catalogLoaded": True, "total": 5, "shown": -1}) == {
        "state": "no-results",
        "banner": None,
    }


# --- moveSelection -----------------------------------------------------------
@pytest.mark.parametrize(
    "index,delta,count,expected",
    [
        (0, 1, 5, 1),
        (2, 1, 5, 3),
        (4, 1, 5, 4),  # clamps at the last
        (10, 1, 5, 4),
        (0, -1, 5, 0),  # clamps at the first
        (2, -1, 5, 1),
        (-10, 1, 5, 0),
        (-1, 1, 5, 0),  # nothing selected, move down
        (-1, -1, 5, 0),  # nothing selected, move up
        (2, 0, 5, 2),
        (2, 3, 5, 4),
        (2, -5, 5, 0),
        (0, 1, 1, 0),  # a one-item list
        (0, -1, 1, 0),
    ],
)
def test_move_selection(
    ui: qjs.JsModule, index: int, delta: int, count: int, expected: int
) -> None:
    assert ui.call("moveSelection", index, delta, count) == expected


@pytest.mark.parametrize("count", [0, -1, None, "garbage", float("nan")])
def test_move_selection_empty_list_is_minus_one(ui: qjs.JsModule, count) -> None:
    if isinstance(count, float):
        # NaN cannot cross the JSON boundary; call it in-engine instead.
        assert ui.evaluate("moveSelection(0, 1, NaN)") == -1
    else:
        assert ui.call("moveSelection", 0, 1, count) == -1


def test_move_selection_bad_input(ui: qjs.JsModule) -> None:
    assert ui.call("moveSelection", None, None, None) == -1
    assert ui.call("moveSelection", None, 1, 5) == 0
    assert ui.call("moveSelection", "x", "y", 5) == 0
    assert ui.evaluate("moveSelection(NaN, NaN, 5)") == 0


def test_move_selection_floors_a_fractional_count(ui: qjs.JsModule) -> None:
    assert ui.call("moveSelection", 0, 1, 2.9) == 1
    assert ui.call("moveSelection", 5, 1, 2.9) == 1


# --- syncDue -----------------------------------------------------------------
@pytest.mark.parametrize(
    "age,hours,expected",
    [
        (None, 6, True),  # never synced
        ("garbage", 6, True),
        (-5, 6, True),
        (0, 6, False),
        (6 * 3600 - 1, 6, False),
        (6 * 3600, 6, True),
        (10 * 3600, 6, True),
        (0, 0, True),
        (1, 0, True),
        (100, None, True),
        (100, -1, True),
        (None, None, True),
    ],
)
def test_sync_due(ui: qjs.JsModule, age, hours, expected: bool) -> None:
    assert ui.call("syncDue", age, hours) is expected


def test_sync_due_non_finite_age_is_due(ui: qjs.JsModule) -> None:
    # A non-finite age cannot establish freshness, so it reads as never synced.
    assert ui.evaluate("syncDue(NaN, 6)") is True
    assert ui.evaluate("syncDue(Infinity, 6)") is True
    assert ui.evaluate("syncDue(-Infinity, 6)") is True


# --- storage -----------------------------------------------------------------
def test_storage_from_the_local_scan(ui: qjs.JsModule) -> None:
    items = [
        {"asin": A1, "size": 12 * 1024 * 1024, "downloaded_at": "2026-01-01T00:00:00Z"},
        {"asin": A3, "size": 5, "downloaded_at": "2026-02-01T00:00:00Z"},
    ]
    assert ui.call("storage", items) == {"count": 2, "bytes": 12 * 1024 * 1024 + 5}


def test_storage_from_library_rows(
    ui: qjs.JsModule, library: qjs.JsModule, catalog: dict
) -> None:
    local = [
        {"asin": A2, "size": 100, "downloaded_at": "2026-01-01T00:00:00Z"},
        {"asin": A4, "size": 250, "downloaded_at": "2026-02-01T00:00:00Z"},
    ]
    rows = build_rows(library, catalog, local=local)
    # Cloud rows carry `local: false` and must not count.
    assert ui.call("storage", rows) == {"count": 2, "bytes": 350}


def test_storage_empty_and_bad_input(ui: qjs.JsModule) -> None:
    assert ui.call("storage", []) == {"count": 0, "bytes": 0}
    assert ui.call("storage", None) == {"count": 0, "bytes": 0}
    assert ui.call("storage", "garbage") == {"count": 0, "bytes": 0}
    assert ui.call("storage", 42) == {"count": 0, "bytes": 0}


def test_storage_skips_unusable_entries(ui: qjs.JsModule) -> None:
    items = [
        None,
        42,
        {"size": 10},  # no asin
        {"asin": "", "size": 10},
        {"asin": A1, "size": None},  # counted, size unknown
        {"asin": A2, "size": -5},  # counted, bad size
        {"asin": A3, "size": 7},
    ]
    assert ui.call("storage", items) == {"count": 3, "bytes": 7}


def test_storage_accepts_a_map(ui: qjs.JsModule) -> None:
    assert ui.call("storage", {A1: {"size": 10}, A2: True, A3: {}}) == {
        "count": 3,
        "bytes": 10,
    }
    assert ui.call("storage", {"": {"size": 10}}) == {"count": 0, "bytes": 0}


# --- row icons and the download question (G3 finding 3) ---------------------
STATES = ["cloud", "queued", "downloading", "converting", "local", "error"]


@pytest.mark.parametrize(
    ("state", "offline", "glyph", "tooltip", "pick"),
    [
        ("local", False, "\uf04b", "Play", "play"),
        ("local", True, "\uf04b", "Play", "play"),
        ("cloud", False, "\uf019", "Download to this device", "confirm"),
        ("cloud", True, "", "", "none"),
        ("error", False, "\uf01e", "Retry download", "retry"),
        ("queued", False, "", "", "none"),
        ("downloading", False, "", "", "none"),
        ("converting", False, "", "", "none"),
    ],
)
def test_row_icon_and_pick_follow_primary_action(
    ui, library, catalog, state, offline, glyph, tooltip, pick
) -> None:
    row = row_in_state(library, catalog, state)
    assert ui.call("rowIcon", row, offline) == {"glyph": glyph, "tooltip": tooltip}
    assert ui.call("pickDecision", row, offline, "") == pick


def test_pick_confirms_then_downloads_the_same_book(ui, library, catalog) -> None:
    cloud = row_in_state(library, catalog, "cloud")
    assert ui.call("pickDecision", cloud, False, None) == "confirm"
    assert ui.call("pickDecision", cloud, False, "B0FAKE9999") == "confirm"
    assert ui.call("pickDecision", cloud, False, cloud["asin"]) == "download"
    # Offline, even an answered question downloads nothing.
    assert ui.call("pickDecision", cloud, True, cloud["asin"]) == "none"


def test_retry_and_play_never_ask(ui, library, catalog) -> None:
    for state, expected in (("error", "retry"), ("local", "play")):
        row = row_in_state(library, catalog, state)
        assert ui.call("pickDecision", row, False, row["asin"]) == expected


@pytest.mark.parametrize("row", [None, "garbage", {}, {"state": "exploded"}, []])
def test_pick_decision_bad_input(ui, row) -> None:
    # An unknown row reads as a cloud book with no ASIN: it can only ask.
    assert ui.call("pickDecision", row, False, "") in ("confirm", "none")
    assert ui.call("pickDecision", row, True, "") == "none"
    assert ui.call("rowIcon", row, True) == {"glyph": "", "tooltip": ""}


@pytest.mark.parametrize(
    ("runtime_min", "expected"),
    [
        (60, 57000000),
        (810, 769500000),  # 13.5 h, about the 773 MB measured
        (145, 137750000),  # 2.4 h, about the 138 MB measured
        (0, 0),
        (-5, 0),
        (None, 0),
        ("60", 0),
    ],
)
def test_estimated_bytes(ui, runtime_min, expected) -> None:
    assert ui.call("estimatedBytes", {"runtimeMin": runtime_min}) == expected


@pytest.mark.parametrize("row", [None, "x", [], 7])
def test_estimated_bytes_bad_row(ui, row) -> None:
    assert ui.call("estimatedBytes", row) == 0


def test_estimated_bytes_of_a_real_row(ui, library, catalog) -> None:
    row = row_in_state(library, catalog, "cloud")
    assert row["runtimeMin"] > 0
    assert ui.call("estimatedBytes", row) == round(row["runtimeMin"] / 60 * 57000000)


def test_confirm_stays_only_for_a_downloadable_cloud_book(ui, library, catalog) -> None:
    for state in STATES:
        row = row_in_state(library, catalog, state)
        expected = state == "cloud"
        assert ui.call("confirmValid", row["asin"], row, False) is expected
        assert ui.call("confirmValid", row["asin"], row, True) is False
    cloud = row_in_state(library, catalog, "cloud")
    assert ui.call("confirmValid", "B0FAKE9999", cloud, False) is False
    assert ui.call("confirmValid", "", cloud, False) is False
    assert ui.call("confirmValid", None, cloud, False) is False
    assert ui.call("confirmValid", cloud["asin"], None, False) is False

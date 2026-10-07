"""U2 — ``qml/lib/Drawer.js``: Library view decisions not covered by LibraryUi."""

from __future__ import annotations

import pytest

import qjs


@pytest.fixture(scope="module")
def drawer() -> qjs.JsModule:
    return qjs.load("Drawer")


def test_sorts_and_filters_match_library(drawer):
    library = qjs.load("Library")
    sorts = [s["value"] for s in drawer.evaluate("SORTS")]
    filters = [f["value"] for f in drawer.evaluate("FILTERS")]
    assert sorts == [
        library.evaluate(n)
        for n in ("SORT_RECENT", "SORT_ADDED", "SORT_TITLE", "SORT_AUTHOR")
    ]
    assert filters == [
        library.evaluate(n)
        for n in ("FILTER_ALL", "FILTER_LOCAL", "FILTER_IN_PROGRESS")
    ]
    assert drawer.evaluate("SORTS[0].label") == "Recently listened"


@pytest.mark.parametrize(
    "status_age,status_at,last_sync,now,age",
    [
        (100, 1000, 0, 11000, 110),
        (100, 1000, None, 1000, 100),
        (100, 1000, 5000, 65000, 60),
        (None, 1000, 5000, 5000, 0),
        (None, 1000, 0, 5000, None),
        (-1, 1000, 0, 5000, None),
        (100, 0, 0, 5000, None),
        (100, 1000, 0, None, None),
        (100, 9000, 0, 5000, 100),
    ],
)
def test_catalog_age(drawer, status_age, status_at, last_sync, now, age):
    assert drawer.call("catalogAgeS", status_age, status_at, last_sync, now) == age


@pytest.mark.parametrize(
    "pending,active,result",
    [
        ([], None, False),
        ([{"command": "sync"}], None, True),
        ([], {"command": "sync"}, True),
        ([{"command": "get"}], {"command": "local"}, False),
        (None, None, False),
        ([None, 3], None, False),
    ],
)
def test_syncing(drawer, pending, active, result):
    assert drawer.call("syncing", pending, active) is result


@pytest.mark.parametrize(
    "code,result",
    [
        ("", {"offline": False, "errorCode": None}),
        (None, {"offline": False, "errorCode": None}),
        ("network", {"offline": True, "errorCode": None}),
        ("auth_failed", {"offline": False, "errorCode": "auth_failed"}),
        ("internal", {"offline": False, "errorCode": "internal"}),
    ],
)
def test_sync_failure(drawer, code, result):
    assert drawer.call("syncFailure", code) == result


ESC, RET, ENT, UP, DOWN, SPACE = (
    0x01000000,
    0x01000004,
    0x01000005,
    0x01000013,
    0x01000015,
    0x20,
)


@pytest.mark.parametrize(
    "key,text,action",
    [
        (ESC, "", "close"),
        (ESC, "abc", "close"),
        (UP, "", "up"),
        (DOWN, "abc", "down"),
        (RET, "", "pick"),
        (ENT, "abc", "pick"),
        (SPACE, "", "toggle"),
        (SPACE, None, "toggle"),
        (SPACE, "a", "type"),
        (0x41, "", "type"),
        (None, "", "type"),
    ],
)
def test_search_key(drawer, key, text, action):
    assert drawer.call("searchKey", key, text) == action


@pytest.mark.parametrize(
    "selected,count,index",
    [
        (-1, 5, 0),
        (None, 5, 0),
        (2, 5, 2),
        (9, 5, 4),
        (2.7, 5, 2),
        (0, 0, -1),
        (-1, 0, -1),
        (3, None, -1),
    ],
)
def test_pick_index(drawer, selected, count, index):
    assert drawer.call("pickIndex", selected, count) == index


def test_row_progress(drawer):
    progress = {"stage": "download", "bytes": 1, "total": 2}
    active = {"command": "get", "args": ["B0FAKE0001"]}
    assert drawer.call("rowProgress", "B0FAKE0001", active, progress) == progress
    assert (
        drawer.call(
            "rowProgress",
            "B0FAKE0001",
            {"command": "get", "asin": "B0FAKE0001"},
            progress,
        )
        == progress
    )
    assert drawer.call("rowProgress", "B0FAKE0002", active, progress) is None
    assert (
        drawer.call(
            "rowProgress", "B0FAKE0001", {"command": "sync", "args": []}, progress
        )
        is None
    )
    assert drawer.call("rowProgress", "B0FAKE0001", None, progress) is None
    assert drawer.call("rowProgress", "B0FAKE0001", active, None) is None


@pytest.mark.parametrize(
    "row,ok",
    [
        ({"asin": "A", "local": True}, True),
        ({"asin": "A", "local": False}, False),
        ({"local": True}, False),
        (None, False),
    ],
)
def test_can_remove(drawer, row, ok):
    assert drawer.call("canRemove", row) is ok


def test_removable_asins(drawer):
    rows = [
        {"asin": "A", "local": True},
        {"asin": "B", "local": False},
        {"asin": "C", "local": True},
        None,
    ]
    assert drawer.call("removableAsins", rows) == ["A", "C"]
    assert drawer.call("removableAsins", None) == []


@pytest.mark.parametrize(
    "asin,busy,ok",
    [
        ("A", [], True),
        ("A", ["", "B", ""], True),
        ("A", ["A", "", ""], False),
        ("A", ["", "A", ""], False),
        ("A", ["", "", "A"], False),
        ("A", None, True),
        ("", [], False),
        (None, [], False),
    ],
)
def test_removal_allowed(drawer, asin, busy, ok):
    assert drawer.call("removalAllowed", asin, busy) is ok


@pytest.mark.parametrize(
    "row,text",
    [
        ({"state": "error", "error": "Not enough disk space"}, "Not enough disk space"),
        ({"state": "error", "error": "  "}, "Download failed"),
        ({"state": "error"}, "Download failed"),
        ({"state": "local", "error": "x"}, ""),
        (None, ""),
    ],
)
def test_error_text(drawer, row, text):
    assert drawer.call("errorText", row) == text


@pytest.mark.parametrize(
    "last,now,blocked",
    [
        (0, 1000, False),
        (None, 1000, False),
        (1000, 1000, True),
        (1000, 600999, True),
        (1000, 601000, False),
        (1000, None, False),
    ],
)
def test_auto_sync_blocked(drawer, last, now, blocked):
    assert drawer.call("autoSyncBlocked", last, now) is blocked


@pytest.mark.parametrize(
    "index,count,ok",
    [
        (0, 1, True),
        (4, 5, True),
        (5, 5, False),
        (-1, 5, False),
        (1.5, 5, False),
        (None, 5, False),
        (0, 0, False),
    ],
)
def test_valid_index(drawer, index, count, ok):
    assert drawer.call("validIndex", index, count) is ok


@pytest.mark.parametrize(
    "selected,count,result",
    [
        (2, 5, 2),
        (7, 5, 4),
        (-1, 5, -1),
        (3, 0, -1),
        (None, 5, -1),
        (2.9, 5, 2),
    ],
)
def test_clamp_selection(drawer, selected, count, result):
    assert drawer.call("clampSelection", selected, count) == result


@pytest.mark.parametrize(
    "count,text",
    [
        (0, ""),
        (None, ""),
        (-2, ""),
        (1, "Remove 1 download from this device?"),
        (3, "Remove 3 downloads from this device?"),
    ],
)
def test_remove_all_question(drawer, count, text):
    assert drawer.call("removeAllQuestion", count) == text


@pytest.mark.parametrize("state", ["loading", "error", "empty", "no-results"])
def test_state_text(drawer, state):
    assert drawer.call("stateText", state) != ""


@pytest.mark.parametrize("state", ["list", None, "bogus"])
def test_state_text_blank(drawer, state):
    assert drawer.call("stateText", state) == ""


@pytest.mark.parametrize(
    "banner,blank",
    [
        ("offline", False),
        ("reconnect", False),
        ("syncing", False),
        (None, True),
        ("x", True),
    ],
)
def test_banner_text(drawer, banner, blank):
    assert (drawer.call("bannerText", banner) == "") is blank


@pytest.mark.parametrize(
    "row,ms",
    [
        ({"runtimeMin": 90}, 5400000),
        ({"runtimeMin": 0}, 0),
        ({"runtimeMin": None}, 0),
        ({}, 0),
        (None, 0),
    ],
)
def test_runtime_ms(drawer, row, ms):
    assert drawer.call("runtimeMs", row) == ms


@pytest.mark.parametrize(
    "row,fraction",
    [
        ({"percent": 50}, 0.5),
        ({"percent": 150}, 1),
        ({"percent": -3}, 0),
        ({}, 0),
        (None, 0),
    ],
)
def test_progress_fraction(drawer, row, fraction):
    assert drawer.call("progressFraction", row) == fraction


@pytest.mark.parametrize(
    "row,names",
    [
        ({"authors": ["Mara Quill", " Owen Hale "]}, ["Mara Quill", "Owen Hale"]),
        ({"authors": ["", None, 3, "A"]}, ["A"]),
        ({"authors": "Mara Quill"}, []),
        ({"authors": None}, []),
        ({}, []),
        (None, []),
    ],
)
def test_authors(drawer, row, names):
    assert drawer.call("authors", row) == names


def test_authors_array_like(drawer):
    assert drawer.evaluate(
        'authors({"authors": {"length": 2, "0": "A", "1": "B"}})'
    ) == ["A", "B"]


def test_removing(drawer):
    rm = {"command": "remove", "args": ["A"]}
    assert drawer.call("removing", "A", ["A"], [], None) is True
    assert drawer.call("removing", "A", [], [rm], None) is True
    assert drawer.call("removing", "A", [], [], rm) is True
    assert drawer.call("removing", "B", ["A"], [rm], rm) is False
    assert (
        drawer.call("removing", "A", [], [{"command": "get", "args": ["A"]}], None)
        is False
    )
    assert drawer.call("removing", "A", None, None, None) is False
    assert drawer.call("removing", "", ["", ""], [], None) is False


@pytest.mark.parametrize(
    "row,text",
    [
        ({"title": "The Quiet Orchard"}, "You finished The Quiet Orchard."),
        ({"title": "  "}, "You finished this book."),
        (None, "You finished this book."),
    ],
)
def test_ask_text(drawer, row, text):
    assert drawer.call("askText", row) == text


@pytest.mark.parametrize(
    "size,text",
    [
        ("770 MB", "Download up to 770 MB?"),
        (" 1.2 GB ", "Download up to 1.2 GB?"),
        ("", "Download this book?"),
        (None, "Download this book?"),
        (7, "Download this book?"),
    ],
)
def test_download_question(drawer, size, text):
    assert drawer.call("downloadQuestion", size) == text


def test_download_question_with_format_bytes(drawer):
    fmt = qjs.load("Format")
    ui = qjs.load("LibraryUi")
    size = fmt.call("bytes", ui.call("estimatedBytes", {"runtimeMin": 810}))
    assert drawer.call("downloadQuestion", size) == "Download up to " + size + "?"
    assert size == "734 MB"  # Format.bytes uses 1024-based units

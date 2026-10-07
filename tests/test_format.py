"""L1 — ``qml/lib/Format.js`` in PySide6's ``QJSEngine``.

The same V4 engine Quickshell uses runs the module through ``tests/qjs.py``.
These cover every public formatter, including the PLAN acceptance cases: zero,
under a minute, over 100 hours, negatives, NaN, null, missing title/author and
singular versus plural.
"""

from __future__ import annotations

import datetime

import pytest

import qjs

EXPECTED_API = {
    "_p",
    "ago",
    "bytes",
    "clock",
    "duration",
    "left",
    "names",
    "storageLine",
    "tooltip",
}

# A fixed "now" so the relative-time cases are deterministic (whole seconds).
NOW = 1_800_000_000_000  # 2027-01-15T08:00:00Z

HOUR = 3600000
MINUTE = 60000
DAY = 86400000


def iso_at(offset_ms: int) -> str:
    """An ISO-8601 UTC timestamp ``offset_ms`` from ``NOW`` (millisecond safe)."""
    total = NOW + offset_ms
    moment = datetime.datetime.fromtimestamp(total // 1000, datetime.UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S") + f".{total % 1000:03d}Z"


@pytest.fixture(scope="module")
def module() -> qjs.JsModule:
    return qjs.load("Format")


# --- API ---------------------------------------------------------------------
def test_exports_the_expected_api(module: qjs.JsModule) -> None:
    assert set(module.functions) == EXPECTED_API


# --- duration ----------------------------------------------------------------
@pytest.mark.parametrize(
    "ms,expected",
    [
        (0, "0m"),
        (1, "<1m"),
        (30000, "<1m"),
        (59999, "<1m"),
        (MINUTE, "1m"),
        (44 * MINUTE, "44m"),
        (45 * MINUTE, "45m"),
        (59 * MINUTE + 59000, "59m"),
        (HOUR, "1h"),
        (HOUR + MINUTE, "1h 1m"),
        (3 * HOUR + 12 * MINUTE, "3h 12m"),
        (3 * HOUR + 12 * MINUTE + 59000, "3h 12m"),
        (100 * HOUR + 4 * MINUTE, "100h 4m"),
        (123 * HOUR + 4 * MINUTE + 5000, "123h 4m"),
    ],
)
def test_duration(module: qjs.JsModule, ms: int, expected: str) -> None:
    assert module.call("duration", ms) == expected


@pytest.mark.parametrize("value", [-1, -60000, None, "", "1000", "3h"])
def test_duration_bad_input_gives_empty(module: qjs.JsModule, value) -> None:
    assert module.call("duration", value) == ""


def test_duration_nan_and_infinity_give_empty(module: qjs.JsModule) -> None:
    assert module.evaluate("duration(NaN)") == ""
    assert module.evaluate("duration(Infinity)") == ""
    assert module.evaluate("duration(-Infinity)") == ""
    assert module.evaluate("duration(undefined)") == ""


# --- left --------------------------------------------------------------------
@pytest.mark.parametrize(
    "position,duration_ms,expected",
    [
        (0, 3 * HOUR + 12 * MINUTE, "3h 12m left"),
        (0, HOUR, "1h left"),
        (0, MINUTE, "1m left"),
        (0, 123 * HOUR + 4 * MINUTE, "123h 4m left"),
        (3 * HOUR + 12 * MINUTE - 5 * MINUTE, 3 * HOUR + 12 * MINUTE, "5m left"),
        (3 * HOUR + 12 * MINUTE - 30000, 3 * HOUR + 12 * MINUTE, "<1m left"),
        (3 * HOUR + 12 * MINUTE, 3 * HOUR + 12 * MINUTE, ""),  # at the end
        (3 * HOUR + 12 * MINUTE + 1, 3 * HOUR + 12 * MINUTE, ""),  # past the end
        (5, 0, ""),
        (100, 50, ""),
    ],
)
def test_left(
    module: qjs.JsModule, position: int, duration_ms: int, expected: str
) -> None:
    assert module.call("left", position, duration_ms) == expected


@pytest.mark.parametrize(
    "position,duration_ms",
    [(-1, HOUR), (None, HOUR), (0, None), ("x", HOUR), (0, "x"), (0, -HOUR), (HOUR, 0)],
)
def test_left_bad_input_gives_empty(
    module: qjs.JsModule, position, duration_ms
) -> None:
    assert module.call("left", position, duration_ms) == ""


def test_left_nan_and_infinity_give_empty(module: qjs.JsModule) -> None:
    assert module.evaluate("left(NaN, 60000)") == ""
    assert module.evaluate("left(0, NaN)") == ""
    assert module.evaluate("left(Infinity, 60000)") == ""
    assert module.evaluate("left(0, Infinity)") == ""


# --- clock -------------------------------------------------------------------
@pytest.mark.parametrize(
    "ms,expected",
    [
        (0, "0:00"),
        (999, "0:00"),
        (1000, "0:01"),
        (59000, "0:59"),
        (60000, "1:00"),
        (125000, "2:05"),
        (3599000, "59:59"),
        (HOUR, "1:00:00"),
        (HOUR + 33000, "1:00:33"),
        (HOUR + 2 * MINUTE + 33000, "1:02:33"),
        (123 * HOUR + 4 * MINUTE + 5000, "123:04:05"),
    ],
)
def test_clock(module: qjs.JsModule, ms: int, expected: str) -> None:
    assert module.call("clock", ms) == expected


@pytest.mark.parametrize("value", [-1, -1000, None, "", "5000"])
def test_clock_bad_input_gives_empty(module: qjs.JsModule, value) -> None:
    assert module.call("clock", value) == ""


def test_clock_nan_and_infinity_give_empty(module: qjs.JsModule) -> None:
    assert module.evaluate("clock(NaN)") == ""
    assert module.evaluate("clock(Infinity)") == ""


# --- bytes -------------------------------------------------------------------
@pytest.mark.parametrize(
    "n,expected",
    [
        (0, "0 B"),
        (1, "1 B"),
        (512, "512 B"),
        (1023, "1023 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (10 * 1024, "10 KB"),
        (12 * 1024 * 1024, "12 MB"),
        (5767168, "5.5 MB"),  # 5.5 MiB
        (780 * 1024 * 1024, "780 MB"),
        (1024**3, "1.0 GB"),
        (int(2.5 * 1024**3), "2.5 GB"),
        (100 * 1024**3, "100 GB"),
        (2048 * 1024**3, "2048 GB"),  # beyond the listed units, stays in GB
    ],
)
def test_bytes(module: qjs.JsModule, n: int, expected: str) -> None:
    assert module.call("bytes", n) == expected


@pytest.mark.parametrize("value", [-1, None, "", "1024"])
def test_bytes_bad_input_gives_empty(module: qjs.JsModule, value) -> None:
    assert module.call("bytes", value) == ""


def test_bytes_nan_and_infinity_give_empty(module: qjs.JsModule) -> None:
    assert module.evaluate("bytes(NaN)") == ""
    assert module.evaluate("bytes(Infinity)") == ""


# --- storageLine -------------------------------------------------------------
@pytest.mark.parametrize(
    "count,total,expected",
    [
        (0, 0, "No books on this device"),
        (0, 999_999_999, "No books on this device"),
        (1, 12 * 1024 * 1024, "1 book \u00b7 12 MB"),
        (3, 780 * 1024 * 1024, "3 books \u00b7 780 MB"),
        (2, 5767168, "2 books \u00b7 5.5 MB"),
        (1, 0, "1 book \u00b7 0 B"),
        (100, 123456789012, "100 books \u00b7 115 GB"),
        (2.9, 100, "2 books \u00b7 100 B"),  # a fractional count floors
    ],
)
def test_storage_line(module: qjs.JsModule, count, total, expected: str) -> None:
    assert module.call("storageLine", count, total) == expected


@pytest.mark.parametrize("count", [-1, None, "", "3"])
def test_storage_line_plural_and_bad_count(module: qjs.JsModule, count) -> None:
    assert module.call("storageLine", count, 123) == "No books on this device"


def test_storage_line_without_a_size(module: qjs.JsModule) -> None:
    assert module.call("storageLine", 1, None) == "1 book"
    assert module.call("storageLine", 1, -5) == "1 book"
    assert module.evaluate("storageLine(1, NaN)") == "1 book"


# --- ago ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "offset,expected",
    [
        (0, "just now"),
        (-5000, "just now"),
        (-59999, "just now"),
        (10000, "just now"),  # a future timestamp
        (-MINUTE, "1 min ago"),
        (-5 * MINUTE, "5 min ago"),
        (-3599000, "59 min ago"),
        (-HOUR, "1 h ago"),
        (-3 * HOUR, "3 h ago"),
        (-86399000, "23 h ago"),
        (-DAY, "1 day ago"),
        (-2 * DAY, "2 days ago"),
        (-(3 * DAY + 5000), "3 days ago"),
    ],
)
def test_ago(module: qjs.JsModule, offset: int, expected: str) -> None:
    assert module.call("ago", iso_at(offset), NOW) == expected


@pytest.mark.parametrize("value", [None, "", "not a date", "2026-13-45T00:00:00Z", 42])
def test_ago_is_never_for_a_missing_or_bad_timestamp(
    module: qjs.JsModule, value
) -> None:
    assert module.call("ago", value, NOW) == "never"


def test_ago_falls_back_to_the_engine_clock(module: qjs.JsModule) -> None:
    now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert module.call("ago", now) == "just now"


# --- names -------------------------------------------------------------------
@pytest.mark.parametrize(
    "items,expected",
    [
        ([], ""),
        (["Mara Quill"], "Mara Quill"),
        (["Mara Quill", "Owen Hale"], "Mara Quill and Owen Hale"),
        (["A", "B", "C"], "A, B and C"),
        (["A", "B", "C", "D"], "A, B and 2 more"),
        (["A", "B", "C", "D", "E"], "A, B and 3 more"),
        (["A", None, "", "B"], "A and B"),
        ([None], ""),
        ([42], ""),
        (["  Mara Quill  "], "Mara Quill"),
    ],
)
def test_names(module: qjs.JsModule, items, expected: str) -> None:
    assert module.call("names", items) == expected


@pytest.mark.parametrize("value", [None, "", "Mara Quill", 42])
def test_names_not_a_list_gives_empty(module: qjs.JsModule, value) -> None:
    assert module.call("names", value) == ""


# --- tooltip (FR-U1) ---------------------------------------------------------
@pytest.mark.parametrize(
    "title,author,left_text,expected",
    [
        ("Title", "Author", "3h 12m left", "Title \u2014 Author \u00b7 3h 12m left"),
        ("Title", "Author", None, "Title \u2014 Author"),
        ("Title", "Author", "", "Title \u2014 Author"),
        ("Title", None, "3h 12m left", "Title \u00b7 3h 12m left"),
        ("Title", None, None, "Title"),
        (None, "Author", None, "Author"),
        (None, None, "3h 12m left", "3h 12m left"),
        (None, None, None, ""),
        ("", "", "", ""),
        ("  ", "  ", "  ", ""),
        (42, "Author", None, "Author"),
        ("Title", "Author", "  ", "Title \u2014 Author"),
    ],
)
def test_tooltip(module: qjs.JsModule, title, author, left_text, expected: str) -> None:
    assert module.call("tooltip", title, author, left_text) == expected

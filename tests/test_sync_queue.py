"""P4 — ``qml/lib/Sync.js``: queue helpers around the position push rules."""

from __future__ import annotations

import pytest

import qjs


@pytest.fixture(scope="module")
def sync() -> qjs.JsModule:
    return qjs.load("Sync")


def entry(asin, ms=1000, at="2026-10-05T14:00:00Z"):
    return {"asin": asin, "ms": ms, "at": at}


def test_asins_of_is_distinct_ordered_and_capped(sync):
    queue = [entry("B"), entry("A"), entry("B", 2000), entry("C")]
    assert sync.call("asinsOf", queue, 25) == ["B", "A", "C"]
    assert sync.call("asinsOf", queue, 2) == ["B", "A"]
    assert sync.call("asinsOf", [entry("X")] * 3, None) == ["X"]
    assert sync.call("asinsOf", None, 25) == []
    assert sync.call("asinsOf", [None, {"asin": 5}, entry("A")], 25) == ["A"]


def test_batch_size_matches_the_api_limit(sync):
    queue = [entry(f"B{i:03d}") for i in range(40)]
    assert len(sync.call("asinsOf", queue, None)) == 25


def test_remove_entry_only_removes_the_same_push(sync):
    queue = [entry("A", 1000), entry("B", 5)]
    assert sync.call("removeEntry", queue, entry("A", 1000)) == [entry("B", 5)]
    # A newer push for the same book arrived while the old one was in flight.
    newer = [entry("A", 2000, "2026-10-05T14:05:00Z")]
    assert sync.call("removeEntry", newer, entry("A", 1000)) == newer
    assert sync.call("removeEntry", queue, None) == queue
    assert sync.call("removeEntry", None, entry("A")) == []


def test_push_args(sync):
    assert sync.call("pushArgs", entry("A", 1234.6)) == [
        "A",
        "1235",
        "--at",
        "2026-10-05T14:00:00Z",
    ]
    assert sync.call("pushArgs", {"asin": "A", "ms": 5, "at": None}) == ["A", "5"]


def test_sendable_waits_for_a_fresh_read(sync):
    send = [entry("A"), entry("Z")]
    assert sync.call("sendable", send, ["A", "B"]) == [entry("A")]
    assert sync.call("sendable", send, None) == []
    assert sync.call("sendable", None, ["A"]) == []


# --- staleNotice (P6, F1: a run of refused pushes is worth a line) -----------
def test_stale_notice_is_silent_below_two(sync):
    assert sync.call("staleNotice", 0) == ""
    assert sync.call("staleNotice", 1) == ""


def test_stale_notice_tells_the_user_after_two(sync):
    line = sync.call("staleNotice", 2)
    assert line != ""
    assert "Audible" in line
    assert "clock" in line
    assert "\n" not in line
    assert sync.call("staleNotice", 5) == line


def test_stale_notice_never_throws_on_bad_input(sync):
    for value in (None, "2", -1, True, [], {}):
        assert sync.call("staleNotice", value) == ""


def test_stale_notice_threshold_is_two(sync):
    assert sync.evaluate("STALE_NOTICE_AFTER") == 2


def test_stale_count_after(sync):
    stale = {"ok": False, "code": "stale"}
    # Two refusals in a row build the run; a push that goes through ends it.
    assert sync.call("staleCountAfter", 0, stale) == 1
    assert sync.call("staleCountAfter", 1, stale) == 2
    assert sync.call("staleCountAfter", 2, {"ok": True}) == 0
    # Being offline or refused says nothing about the clock.
    assert sync.call("staleCountAfter", 2, {"ok": False, "code": "network"}) == 2
    assert sync.call("staleCountAfter", 1, {"ok": False, "code": "refused"}) == 1
    # Bad input never throws and never counts.
    assert sync.call("staleCountAfter", None, stale) == 1
    assert sync.call("staleCountAfter", -3, {"ok": True}) == 0
    assert sync.call("staleCountAfter", 2, None) == 2


def test_stale_run_reaches_the_notice(sync):
    count = 0
    for _ in range(sync.evaluate("STALE_NOTICE_AFTER")):
        assert sync.call("staleNotice", count) == ""
        count = sync.call("staleCountAfter", count, {"ok": False, "code": "stale"})
    assert "Check this computer's clock" in sync.call("staleNotice", count)
    count = sync.call("staleCountAfter", count, {"ok": True})
    assert sync.call("staleNotice", count) == ""

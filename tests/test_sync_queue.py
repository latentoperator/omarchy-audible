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
    assert sync.call("pushArgs", entry("A", 1234.6)) == ["A", "1235", "--at", "2026-10-05T14:00:00Z"]
    assert sync.call("pushArgs", {"asin": "A", "ms": 5, "at": None}) == ["A", "5"]


def test_sendable_waits_for_a_fresh_read(sync):
    send = [entry("A"), entry("Z")]
    assert sync.call("sendable", send, ["A", "B"]) == [entry("A")]
    assert sync.call("sendable", send, None) == []
    assert sync.call("sendable", None, ["A"]) == []


def test_own_writes_do_not_look_like_another_device(sync):
    items = {"A": {"ms": 60000, "updated_at": "2026-10-05T14:01:05Z"},
             "B": {"ms": 5, "updated_at": "2026-10-05T14:00:00Z"}}
    out = sync.call("withoutOwnWrites", items, {"A": 60000, "B": 999})
    assert out["A"] == {"ms": 60000, "updated_at": None}
    assert out["B"] == items["B"]
    assert sync.call("withoutOwnWrites", items, None) == items
    assert sync.call("withoutOwnWrites", None, {"A": 1}) == {}
    assert items["A"]["updated_at"] == "2026-10-05T14:01:05Z"


def test_own_write_entries_are_sent_at_the_remote_stamp_but_keep_their_at(sync):
    send = [entry("A", 62000, "2026-10-05T14:01:02Z"), entry("B", 5)]
    items = {"A": {"ms": 60000, "updated_at": "2026-10-05T14:01:05Z"},
             "B": {"ms": 9, "updated_at": "2026-10-05T14:00:00Z"}}
    out = sync.call("atOwnWrites", send, items, {"A": 60000, "B": 1})
    assert out[0]["sendAt"] == "2026-10-05T14:01:05Z" and out[0]["at"] == "2026-10-05T14:01:02Z"
    assert "sendAt" not in out[1]
    assert sync.call("pushArgs", out[0]) == ["A", "62000", "--at", "2026-10-05T14:01:05Z"]
    assert sync.call("pushArgs", out[1]) == ["B", "5", "--at", "2026-10-05T14:00:00Z"]
    assert sync.call("atOwnWrites", send, items, None) == send
    assert sync.call("atOwnWrites", None, items, {}) == []

"""P3 — ``qml/lib/Playback.js``: path to ASIN, position recording, job states for the library."""

from __future__ import annotations

import pytest

import qjs


@pytest.fixture(scope="module")
def playback() -> qjs.JsModule:
    return qjs.load("Playback")


@pytest.mark.parametrize("path,asin", [
    ("/home/u/.local/share/omarchy-audible/books/B0FAKE0001/book.m4b", "B0FAKE0001"),
    ("/home/u/.local/share/omarchy-audible/books/B0FAKE0001/book.aaxc", "B0FAKE0001"),
    ("/home/u/.local/share/omarchy-audible/books/B0FAKE0001/book.aax", "B0FAKE0001"),
    ("/x/B0A/book.m4b", "B0A"),
    ("/x/B0A/other.m4b", ""), ("book.m4b", ""), ("book.aaxc", ""),
    ("/x/B0A/book.aaxcz", ""), ("", ""), (None, ""), (5, ""),
])
def test_asin_from_path(playback, path, asin):
    assert playback.call("asinFromPath", path) == asin


def test_parse_json_falls_back(playback):
    assert playback.call("parseJson", '{"a":1}', {}) == {"a": 1}
    for text in ["", "{", "null", None, 7]:
        assert playback.call("parseJson", text, {"x": 1}) == {"x": 1}


NOW = "2026-10-05T14:00:00.000Z"


def test_record_position_creates_and_updates_without_mutating(playback):
    state = {"schema": 1, "books": {}, "push_queue": [], "volume": None, "speed": None}
    after = playback.call("recordPosition", state, "B0A", 61234.6, NOW)
    assert after["books"]["B0A"] == {
        "ms": 61235, "updated_at": NOW, "last_played_at": NOW,
        "played_since_download": True, "finished": False}
    assert state["books"] == {}
    assert after["push_queue"] == [] and after["schema"] == 1


def test_record_position_keeps_finished_and_other_books(playback):
    state = {"schema": 1, "books": {
        "B0A": {"ms": 5, "updated_at": None, "last_played_at": None,
                "played_since_download": False, "finished": True},
        "B0B": {"ms": 9, "updated_at": None, "last_played_at": None,
                "played_since_download": False, "finished": False}}}
    after = playback.call("recordPosition", state, "B0A", 100, NOW)
    assert after["books"]["B0A"]["finished"] is True and after["books"]["B0B"]["ms"] == 9


@pytest.mark.parametrize("asin,ms", [("", 5), (None, 5), ("B0A", -1), ("B0A", None), ("B0A", "x")])
def test_record_position_ignores_bad_input(playback, asin, ms):
    state = {"schema": 1, "books": {}}
    assert playback.call("recordPosition", state, asin, ms, NOW) == state


def test_job_states_queue_active_and_progress(playback):
    pending = [{"command": "get", "asin": "B0B"}, {"command": "sync", "asin": None}]
    active = {"command": "get", "asin": "B0A"}
    out = playback.call("jobStates", pending, active, {"stage": "download"}, {})
    assert out == [{"asin": "B0B", "state": "queued"}, {"asin": "B0A", "state": "downloading"}]
    out = playback.call("jobStates", [], active, {"stage": "convert"}, {})
    assert out == [{"asin": "B0A", "state": "converting"}]
    assert playback.call("jobStates", [], active, None, {}) == [{"asin": "B0A", "state": "downloading"}]


def test_job_states_ignores_non_get_active(playback):
    assert playback.call("jobStates", [], {"command": "sync"}, None, {}) == []


def test_job_states_failure_shown_until_retried(playback):
    failures = {"B0A": "boom"}
    assert playback.call("jobStates", [], None, None, failures) == [
        {"asin": "B0A", "state": "error", "message": "boom"}]
    retry = playback.call("jobStates", [{"command": "get", "asin": "B0A"}], None, None, failures)
    assert retry == [{"asin": "B0A", "state": "queued"}]


def test_update_failures(playback):
    job = {"command": "get", "asin": "B0A"}
    failed = playback.call("updateFailures", {}, job, {"ok": False, "message": "no space"})
    assert failed == {"B0A": "no space"}
    assert playback.call("updateFailures", failed, job, {"ok": True}) == {}
    assert playback.call("updateFailures", failed, job, None) == {"B0A": "download failed"}
    assert playback.call("updateFailures", failed, {"command": "sync"}, {"ok": False}) == failed
    assert playback.call("updateFailures", None, None, None) == {}


def test_mark_finished_keeps_the_position_and_play_flag(playback):
    state = {"schema": 1, "books": {"B0A": {"ms": 5, "updated_at": NOW, "last_played_at": NOW,
                                           "played_since_download": True, "finished": False}}}
    after = playback.call("markFinished", state, "B0A")
    assert after["books"]["B0A"] == {"ms": 5, "updated_at": NOW, "last_played_at": NOW,
                                     "played_since_download": True, "finished": True}
    assert state["books"]["B0A"]["finished"] is False


def test_mark_finished_for_an_unplayed_book_stays_unplayed(playback):
    after = playback.call("markFinished", {"schema": 1, "books": {}}, "B0A")
    assert after["books"]["B0A"]["finished"] is True
    assert after["books"]["B0A"]["played_since_download"] is False
    assert playback.call("markFinished", {"schema": 1}, "") == {"schema": 1}


def test_with_queue_replaces_the_queue_only(playback):
    state = {"schema": 1, "books": {}, "push_queue": [{"asin": "B0A"}], "volume": 3}
    after = playback.call("withQueue", state, [{"asin": "B0B", "ms": 1, "at": None}])
    assert after["push_queue"] == [{"asin": "B0B", "ms": 1, "at": None}]
    assert after["volume"] == 3 and state["push_queue"] == [{"asin": "B0A"}]
    assert playback.call("withQueue", state, None)["push_queue"] == []

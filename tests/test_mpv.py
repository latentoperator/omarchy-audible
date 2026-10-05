"""P2 — ``qml/lib/Mpv.js``: mpv IPC parsing, derived state, commands, retry, sleep fade."""

from __future__ import annotations

import json

import pytest

import qjs


@pytest.fixture(scope="module")
def mpv() -> qjs.JsModule:
    return qjs.load("Mpv")


def test_observe_commands_cover_every_property(mpv):
    commands = mpv.call("observeCommands")
    assert [c[1] for c in commands] == list(range(1, len(commands) + 1))
    names = {c[2] for c in commands}
    assert {"time-pos", "pause", "chapter-list", "path", "eof-reached"} <= names


def test_parse_property_change(mpv):
    line = json.dumps({"event": "property-change", "id": 1, "name": "time-pos", "data": 12.5})
    assert mpv.call("parseMessage", line) == {"kind": "property", "name": "time-pos", "data": 12.5}


def test_parse_property_change_without_data_is_null(mpv):
    line = json.dumps({"event": "property-change", "id": 1, "name": "path"})
    assert mpv.call("parseMessage", line)["data"] is None


def test_parse_events_and_replies(mpv):
    assert mpv.call("parseMessage", '{"event":"end-file","reason":"eof"}') == {
        "kind": "event", "event": "end-file", "reason": "eof"}
    assert mpv.call("parseMessage", '{"error":"success","data":null,"request_id":4}') == {
        "kind": "reply", "id": 4, "error": None, "data": None}
    reply = mpv.call("parseMessage", '{"error":"property unavailable","request_id":5}')
    assert reply["error"] == "property unavailable"


@pytest.mark.parametrize("line", [None, "", "nope", "[]", "42", '{"x":1}'])
def test_parse_garbage_returns_null(mpv, line):
    assert mpv.call("parseMessage", line) is None


def test_apply_property_copies_and_ignores_unknown(mpv):
    state = mpv.call("emptyState")
    after = mpv.call("applyProperty", state, "pause", False)
    assert after["pause"] is False and state["pause"] is None
    assert "bogus" not in mpv.call("applyProperty", state, "bogus", 1)


def test_derive_empty_is_not_loaded(mpv):
    derived = mpv.call("derive", mpv.call("emptyState"))
    assert derived["loaded"] is False and derived["playing"] is False
    assert derived["positionMs"] == 0 and derived["chapterIndex"] == -1 and derived["speed"] == 1


def test_derive_playing_book(mpv):
    state = mpv.call("emptyState")
    for name, data in {
        "path": "/b/book.m4b", "idle-active": False, "pause": False, "time-pos": 43.5,
        "duration": 180.0, "chapter": 1, "speed": 1.5,
        "chapter-list": [{"title": "One", "time": 0.0}, {"title": "Two", "time": 60.0}],
    }.items():
        state = mpv.call("applyProperty", state, name, data)
    derived = mpv.call("derive", state)
    assert derived["playing"] is True and derived["loaded"] is True
    assert derived["positionMs"] == 43500 and derived["durationMs"] == 180000
    assert derived["chapters"] == [{"title": "One", "startMs": 0}, {"title": "Two", "startMs": 60000}]
    assert derived["chapterIndex"] == 1 and derived["speed"] == 1.5


def test_derive_paused_and_idle(mpv):
    state = mpv.call("emptyState")
    state = mpv.call("applyProperty", state, "path", "/b/book.m4b")
    state = mpv.call("applyProperty", state, "pause", True)
    assert mpv.call("derive", state)["playing"] is False
    state = mpv.call("applyProperty", state, "idle-active", True)
    assert mpv.call("derive", state)["loaded"] is False


def test_parse_chapters_skips_bad_items(mpv):
    items = [{"title": "A", "time": 1.2345}, None, {"title": "x"}, {"time": 5}, "str"]
    assert mpv.call("parseChapters", items) == [
        {"title": "A", "startMs": 1235}, {"title": "", "startMs": 5000}]
    assert mpv.call("parseChapters", None) == []


def test_commands(mpv):
    assert mpv.call("loadCommand", "/b/book.m4b", 42) == ["loadfile", "/b/book.m4b", "replace", 0, "start=42"]
    assert mpv.call("loadCommand", "/b/book.m4b", -3)[-1] == "start=0"
    assert mpv.call("pauseCommand", True) == ["set_property", "pause", True]
    assert mpv.call("pauseCommand", False) == ["set_property", "pause", False]
    assert mpv.call("skipCommand", -30) == ["seek", -30, "relative"]
    assert mpv.call("seekCommand", -5) == ["seek", 0, "absolute"]
    assert mpv.call("chapterCommand", 2) == ["set_property", "chapter", 2]
    assert mpv.call("volumeCommand", 500) == ["set_property", "volume", 130]


@pytest.mark.parametrize("given,expected", [(1.25, 1.25), (0.1, 0.5), (9, 3.0), ("x", 1), (0, 1), (-1, 1)])
def test_speed_is_clamped(mpv, given, expected):
    assert mpv.call("speedCommand", given) == ["set_property", "speed", expected]


@pytest.mark.parametrize("index,count,delta,expected", [
    (0, 3, 1, 1), (1, 3, -1, 0), (2, 3, 1, -1), (0, 3, -1, -1), (0, 0, 1, -1), (None, 3, 1, -1)])
def test_chapter_target(mpv, index, count, delta, expected):
    assert mpv.call("chapterTarget", index, count, delta) == expected


def test_backoff_grows_and_caps(mpv):
    values = [mpv.call("backoffMs", n) for n in range(10)]
    assert values == sorted(values) and values[0] == 300 and values[-1] == 2000


def test_retry_only_while_wanted_and_under_the_cap(mpv):
    assert mpv.call("shouldRetry", 0, True) is True
    assert mpv.call("shouldRetry", 5, True) is True
    assert mpv.call("shouldRetry", 6, True) is False
    assert mpv.call("shouldRetry", 0, False) is False


@pytest.mark.parametrize("remaining,expected", [(10000, 80), (5000, 80), (2500, 40), (0, 0), (-5, 0)])
def test_fade_volume(mpv, remaining, expected):
    assert mpv.call("fadeVolume", 80, remaining, 5000) == pytest.approx(expected)


def test_chapter_end(mpv):
    chapters = [{"startMs": 0}, {"startMs": 60000}, {"startMs": 120000}]
    assert mpv.call("chapterEndMs", chapters, 0, 180000) == 60000
    assert mpv.call("chapterEndMs", chapters, 2, 180000) == 180000
    assert mpv.call("chapterEndMs", chapters, 2, 0) == -1
    assert mpv.call("chapterEndMs", chapters, 3, 180000) == -1
    assert mpv.call("chapterEndMs", [], 0, 180000) == -1


def test_sleep_remaining(mpv):
    chapters = [{"startMs": 0}, {"startMs": 60000}]
    minutes = {"mode": "minutes", "endsAtMs": 10000}
    assert mpv.call("sleepRemainingMs", minutes, 4000, 0, [], -1, 0, 1) == 6000
    chapter = {"mode": "chapter"}
    assert mpv.call("sleepRemainingMs", chapter, 0, 50000, chapters, 0, 120000, 1) == 10000
    assert mpv.call("sleepRemainingMs", chapter, 0, 50000, chapters, 0, 120000, 2) == 5000
    assert mpv.call("sleepRemainingMs", None, 0, 0, [], -1, 0, 1) == -1
    assert mpv.call("sleepRemainingMs", {"mode": "x"}, 0, 0, [], -1, 0, 1) == -1

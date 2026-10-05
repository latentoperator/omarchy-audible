"""U2a — ``qml/lib/Mini.js``: Mini view text and key decisions."""

from __future__ import annotations

import pytest

import qjs


@pytest.fixture(scope="module")
def mini() -> qjs.JsModule:
    return qjs.load("Mini")


@pytest.mark.parametrize("row,text", [
    ({"title": "The Lighthouse Ledger"}, "The Lighthouse Ledger"),
    ({"title": "  Padded  "}, "Padded"),
    ({"title": ""}, "Unknown title"),
    ({"title": "   "}, "Unknown title"),
    ({"title": None}, "Unknown title"),
    ({"title": 7}, "Unknown title"),
    ({}, "Unknown title"),
    (None, "Unknown title"),
])
def test_title(mini, row, text):
    assert mini.call("title", row) == text


@pytest.mark.parametrize("pos,dur,left", [
    (0, 60000, 60000),
    (15000, 60000, 45000),
    (60000, 60000, 0),
    (90000, 60000, 0),
    (-5000, 60000, 60000),
    (1000, 0, 0),
    (1000, -1, 0),
    (None, 60000, 0),
    (1000, None, 0),
    ("1000", 60000, 0),
])
def test_remaining(mini, pos, dur, left):
    assert mini.call("remainingMs", pos, dur) == left


def test_remaining_not_finite(mini):
    assert mini.evaluate("remainingMs(NaN, 60000)") == 0
    assert mini.evaluate("remainingMs(0, Infinity)") == 0


@pytest.mark.parametrize("playing,glyph", [
    (True, ""), (False, ""), (None, ""), ("yes", ""),
])
def test_play_glyph(mini, playing, glyph):
    assert mini.call("playGlyph", playing) == glyph


@pytest.mark.parametrize("view,loaded,kind,dx,action", [
    ("mini", True, "activate", 0, "toggle"),
    ("mini", True, "move", -1, "back"),
    ("mini", True, "move", 1, "forward"),
    ("mini", True, "move", 0, "none"),
    ("mini", True, "bogus", 1, "none"),
    ("full", True, "move", 1, "forward"),
    ("full", True, "activate", 0, "toggle"),
    ("mini", False, "activate", 0, "none"),
    ("mini", None, "move", 1, "none"),
    ("library", True, "activate", 0, "none"),
    ("library", True, "move", -1, "none"),
    ("onboarding", True, "move", 1, "none"),
    (None, True, "activate", 0, "none"),
])
def test_key_action(mini, view, loaded, kind, dx, action):
    assert mini.call("keyAction", view, loaded, kind, dx) == action


@pytest.mark.parametrize("action,seconds", [
    ("back", -15), ("forward", 15), ("toggle", 0), ("none", 0), (None, 0),
])
def test_skip_seconds(mini, action, seconds):
    assert mini.call("skipSeconds", action) == seconds

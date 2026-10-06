"""U1 — ``qml/lib/Panel.js``: the bar glyph, the optional title and the panel view."""

from __future__ import annotations

import pytest

import qjs


@pytest.fixture(scope="module")
def panel() -> qjs.JsModule:
    return qjs.load("Panel")


@pytest.mark.parametrize("view,index", [
    ("onboarding", 0), ("library", 1), ("mini", 2), ("full", 3), ("bogus", 1), (None, 1),
])
def test_view_index(panel, view, index):
    assert panel.call("viewIndex", view) == index


@pytest.mark.parametrize("loaded,playing,glyph", [
    (False, False, ""), (False, True, ""), (None, None, ""),
    (True, True, ""), (True, False, ""), (True, None, ""),
])
def test_glyph(panel, loaded, playing, glyph):
    assert panel.call("glyph", loaded, playing) == glyph


@pytest.mark.parametrize("setting,vertical,loaded,title", [
    ("Off", False, True, "A Book"),
    ("On", True, True, "A Book"),
    ("On", False, False, "A Book"),
    ("On", False, True, None),
    ("On", False, True, "   "),
    (None, False, True, "A Book"),
])
def test_bar_title_hidden(panel, setting, vertical, loaded, title):
    assert panel.call("barTitle", setting, vertical, loaded, title) == ""


def test_bar_title_shown_and_trimmed(panel):
    assert panel.call("barTitle", "On", False, True, "  A Book  ") == "A Book"


def test_bar_title_cut_at_max(panel):
    title = "The Unreasonably Long Title of an Invented Fake Audiobook"
    out = panel.call("barTitle", "On", False, True, title)
    assert len(out) <= 32 and out.endswith("…")
    assert panel.call("barTitle", "On", False, True, "x" * 32) == "x" * 32


@pytest.mark.parametrize("view,open_,closes", [
    ("mini", True, False),
    ("mini", False, True),
    ("full", True, True),
    ("library", True, True),
    ("mini", None, True),
])
def test_dismiss_closes_panel(panel, view, open_, closes):
    assert panel.call("dismissClosesPanel", view, open_) is closes
@pytest.mark.parametrize("view,width,cap", [
    ("full", 680, 760),
    ("mini", 420, 560),
    ("library", 420, 560),
    ("onboarding", 420, 560),
    ("bogus", 420, 560),
    (None, 420, 560),
])
def test_panel_size_per_view(panel, view, width, cap):
    assert panel.call("contentWidth", view) == width
    assert panel.call("heightCap", view) == cap

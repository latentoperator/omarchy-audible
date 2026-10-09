"""U1 — ``qml/lib/Panel.js``: the bar glyph, the optional title and the panel view."""

from __future__ import annotations

import pathlib

import pytest

import qjs


@pytest.fixture(scope="module")
def panel() -> qjs.JsModule:
    return qjs.load("Panel")


@pytest.mark.parametrize(
    "view,index",
    [
        ("onboarding", 0),
        ("library", 1),
        ("mini", 2),
        ("full", 3),
        ("bogus", 1),
        (None, 1),
    ],
)
def test_view_index(panel, view, index):
    assert panel.call("viewIndex", view) == index


@pytest.mark.parametrize(
    "loaded,playing,glyph",
    [
        (False, False, ""),
        (False, True, ""),
        (None, None, ""),
        (True, True, ""),
        (True, False, ""),
        (True, None, ""),
    ],
)
def test_glyph(panel, loaded, playing, glyph):
    assert panel.call("glyph", loaded, playing) == glyph


@pytest.mark.parametrize(
    "setting,vertical,loaded,title",
    [
        ("Off", False, True, "A Book"),
        ("On", True, True, "A Book"),
        ("On", False, False, "A Book"),
        ("On", False, True, None),
        ("On", False, True, "   "),
        (None, False, True, "A Book"),
    ],
)
def test_bar_title_hidden(panel, setting, vertical, loaded, title):
    assert panel.call("barTitle", setting, vertical, loaded, title) == ""


def test_bar_title_shown_and_trimmed(panel):
    assert panel.call("barTitle", "On", False, True, "  A Book  ") == "A Book"


def test_bar_title_cut_at_max(panel):
    title = "The Unreasonably Long Title of an Invented Fake Audiobook"
    out = panel.call("barTitle", "On", False, True, title)
    assert len(out) <= 32 and out.endswith("…")
    assert panel.call("barTitle", "On", False, True, "x" * 32) == "x" * 32


@pytest.mark.parametrize(
    "view,open_,closes",
    [
        ("mini", True, False),
        ("mini", False, True),
        ("full", True, True),
        ("library", True, True),
        ("mini", None, True),
    ],
)
def test_dismiss_closes_panel(panel, view, open_, closes):
    assert panel.call("dismissClosesPanel", view, open_) is closes


@pytest.mark.parametrize(
    "view,width,cap",
    [
        ("full", 680, 760),
        ("mini", 420, 560),
        ("library", 420, 560),
        ("onboarding", 420, 560),
        ("bogus", 420, 560),
        (None, 420, 560),
    ],
)
def test_panel_size_per_view(panel, view, width, cap):
    assert panel.call("contentWidth", view) == width
    assert panel.call("heightCap", view) == cap


@pytest.mark.parametrize(
    "list_open,panel_open,shown",
    [
        (True, True, True),
        # F25: the other monitor's Mini view, whose panel is closed.
        (True, False, False),
        (False, True, False),
        (False, False, False),
        (None, True, False),
        (True, None, False),
        ("yes", 1, False),
    ],
)
def test_chapter_popup_only_in_the_open_panel(panel, list_open, panel_open, shown):
    assert panel.call("chapterPopupShown", list_open, panel_open) is shown


@pytest.mark.parametrize(
    "loaded,wanted,reconcile",
    [
        (True, False, False),
        (True, True, False),
        (False, True, False),
        (False, False, True),
    ],
)
def test_library_after_unload(panel, loaded, wanted, reconcile):
    assert panel.call("libraryAfterUnload", loaded, wanted) is reconcile


def test_mini_view_opens_the_popup_only_through_the_gate():
    root = pathlib.Path(__file__).resolve().parent.parent
    mini = (root / "qml/views/MiniView.qml").read_text(encoding="utf-8")
    bar = (root / "BarWidget.qml").read_text(encoding="utf-8")
    assert "Panel.chapterPopupShown(" in mini
    assert "onChapterListOpenChanged" not in mini
    assert mini.count("chapterMenu.open()") == 1
    assert "panelOpen: root.opened" in bar


def test_the_soft_text_colour_lives_in_one_place():
    # F26: the 75% popup-text colour is SoftText's, and nowhere else.
    root = pathlib.Path(__file__).resolve().parent.parent
    files = sorted((root / "qml").rglob("*.qml")) + [root / "BarWidget.qml"]
    holders = [f.name for f in files if "Color.popups.text.b, 0.75)" in f.read_text()]
    assert holders == ["SoftText.qml"]

"""U4 — ``qml/lib/Parts.js``: cover location and state-badge tone."""

from __future__ import annotations

import pytest

import qjs


@pytest.fixture(scope="module")
def parts() -> qjs.JsModule:
    return qjs.load("Parts")


@pytest.mark.parametrize("data_dir", [
    "/home/u/.local/share/omarchy-audible",
    "/home/u/.local/share/omarchy-audible/",
    "/home/u/.local/share/omarchy-audible//",
])
def test_cover_url(parts, data_dir):
    assert parts.call("coverUrl", data_dir, "B0FAKE0001") == \
        "file:///home/u/.local/share/omarchy-audible/covers/B0FAKE0001.jpg"


@pytest.mark.parametrize("data_dir,asin", [
    ("", "B0FAKE0001"),
    ("/", "B0FAKE0001"),
    ("relative/dir", "B0FAKE0001"),
    (None, "B0FAKE0001"),
    (42, "B0FAKE0001"),
    ("/d", ""),
    ("/d", None),
    ("/d", "../../etc/x"),
    ("/d", "B0FAKE000/"),
    ("/d", "b0fake0001"),
    ("/d", "B0FAKE00011"),
    ("/d", "B0FAKE001"),
])
def test_cover_url_refused(parts, data_dir, asin):
    assert parts.call("coverUrl", data_dir, asin) == ""


def test_cover_set(parts):
    names = ["B0FAKE0001.jpg", "B0FAKE0002.jpg", "b0fake0003.jpg", "B0FAKE0004.png",
             "B0FAKE0005.jpg.part", "../x.jpg", "B0FAKE06.jpg", 7, None]
    assert parts.call("coverSet", names) == {"B0FAKE0001": True, "B0FAKE0002": True}


@pytest.mark.parametrize("value", [None, 42, "B0FAKE0001.jpg", {}, []])
def test_cover_set_bad_input(parts, value):
    assert parts.call("coverSet", value) == {}


@pytest.mark.parametrize("kind,tone", [
    ("local", "accent"),
    ("error", "urgent"),
    ("queued", "text"),
    ("downloading", "text"),
    ("converting", "text"),
    ("cloud", "muted"),
    ("offline", "muted"),
    ("bogus", "muted"),
    (None, "muted"),
])
def test_badge_tone(parts, kind, tone):
    assert parts.call("badgeTone", kind) == tone


def test_every_library_ui_badge_kind_has_a_tone():
    ui = qjs.load("LibraryUi")
    parts = qjs.load("Parts")
    kinds = [ui.evaluate(name) for name in (
        "BADGE_CLOUD", "BADGE_OFFLINE", "BADGE_QUEUED", "BADGE_DOWNLOADING",
        "BADGE_CONVERTING", "BADGE_LOCAL", "BADGE_ERROR")]
    assert len(set(kinds)) == 7
    tones = {k: parts.call("badgeTone", k) for k in kinds}
    assert tones["local"] == "accent" and tones["error"] == "urgent"

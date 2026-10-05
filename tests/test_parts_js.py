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


@pytest.mark.parametrize("version,suffix", [
    (1759700000123, "?v=1759700000123"),
    (1759700000123.9, "?v=1759700000123"),
    (1, "?v=1"),
    (0, ""), (-5, ""), (None, ""), ("123", ""),
])
def test_cover_url_version(parts, version, suffix):
    assert parts.call("coverUrl", "/d", "B0FAKE0001", version) == \
        "file:///d/covers/B0FAKE0001.jpg" + suffix


@pytest.mark.parametrize("version", ["NaN", "Infinity", "-Infinity"])
def test_cover_url_version_not_finite(parts, version):
    assert parts.evaluate(f'coverUrl("/d", "B0FAKE0001", {version})') == \
        "file:///d/covers/B0FAKE0001.jpg"


@pytest.mark.parametrize("data_dir,asin", [
    ("", "B0FAKE0001"),
    ("/", "B0FAKE0001"),
    ("//", "B0FAKE0001"),
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


@pytest.mark.parametrize("path,url", [
    ("/tmp/cache#test", "file:///tmp/cache%23test"),
    ("/tmp/a?b", "file:///tmp/a%3Fb"),
    ("/tmp/x%2Fy", "file:///tmp/x%252Fy"),
    ("/home/u/My Books", "file:///home/u/My%20Books"),
    ("/home/u/Bücher/", "file:///home/u/B%C3%BCcher"),
])
def test_file_url_encodes_segments(parts, path, url):
    assert parts.call("fileUrl", path) == url


def test_file_url_round_trips_through_qurl(parts):
    from PySide6.QtCore import QUrl
    for path in ["/tmp/cache#test", "/tmp/a?b", "/tmp/x%2Fy", "/home/u/My Books", "/home/u/Bücher"]:
        assert QUrl(parts.call("fileUrl", path)).toLocalFile() == path
    url = QUrl(parts.call("coverUrl", "/tmp/cache#test", "B0FAKE0001", 42))
    assert url.toLocalFile() == "/tmp/cache#test/covers/B0FAKE0001.jpg"
    assert url.query() == "v=42"


@pytest.mark.parametrize("path", ["", "/", "//", "rel", None, 3])
def test_file_url_refused(parts, path):
    assert parts.call("fileUrl", path) == ""


def test_cover_set(parts):
    entries = [
        {"name": "B0FAKE0001.jpg", "modified": 1759700000123},
        {"name": "B0FAKE0002.jpg", "modified": 0},
        {"name": "B0FAKE0003.jpg"},
        {"name": "b0fake0004.jpg", "modified": 5},
        {"name": "B0FAKE0005.png", "modified": 5},
        {"name": "B0FAKE0006.jpg.part", "modified": 5},
        {"name": "../x.jpg", "modified": 5},
        {"name": 7}, None, "B0FAKE0007.jpg",
    ]
    assert parts.call("coverSet", entries) == {
        "B0FAKE0001": 1759700000123, "B0FAKE0002": 1, "B0FAKE0003": 1}


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

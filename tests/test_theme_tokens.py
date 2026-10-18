"""Palette tokens are read as ``Commons.Color.*`` (Qt 6.12 shadows bare ``Color``).

Qt 6.12 registers a ``QtQuick`` ``Color`` singleton. In a plugin file that
imports ``QtQuick`` and ``qs.Commons`` unqualified, a bare ``Color.background``
then resolves to Qt's type, the binding is ``undefined``, and the theme colour
disappears (``Unable to assign [undefined] to QColor``). Omarchy's host-side
workaround (``//@ pragma OmarchyLoadPatch``, omacom/omarchy#14845) pins plugin
QtQuick imports to 6.11 only until plugins make this change themselves.

``import qs.Commons as Commons`` plus ``Commons.Color.*`` keeps the palette
unambiguous. ``Style``, ``Util`` and ``Border`` stay unqualified. The static
guard keeps every plugin QML file that way; the harness proves the colours
actually arrive, loading the real files against a stub ``qs.Commons`` because
this machine and CI have no Omarchy shell.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HARNESS = Path(__file__).with_name("color_harness.py")

# The qualification itself: `Color.` not preceded by a word character or dot.
BARE_COLOR = re.compile(r"(?<![.\w])Color\.")
ALIAS_IMPORT = "import qs.Commons as Commons"
# Not plugin QML: caches, linked worktrees and the test doubles themselves.
IGNORED = frozenset({".venv", ".worktrees", "tests", "node_modules"})

# The stub palette the harness loads, in 1/255 steps so the float values are exact.
_STUBS = {
    "qs/Commons/qmldir": (
        "module qs.Commons\n"
        "singleton Color 1.0 Color.qml\n"
        "singleton Style 1.0 Style.qml\n"
        "singleton Util 1.0 Util.qml\n"
    ),
    "qs/Commons/Color.qml": """pragma Singleton
import QtQuick
QtObject {
  readonly property QtObject popups: QtObject {
    readonly property color text: "#336699"
  }
  readonly property color muted: "#cc9966"
  readonly property color accent: "#339933"
  readonly property color urgent: "#cc3333"
}
""",
    # Only what StateBadge reads: its size, radius, fill alphas and font.
    "qs/Commons/Style.qml": """pragma Singleton
import QtQuick
QtObject {
  readonly property QtObject spacing: QtObject {
    readonly property int xs: 2
    readonly property int lg: 8
  }
  readonly property QtObject font: QtObject {
    readonly property string family: "Sans"
    readonly property int caption: 10
  }
  readonly property int cornerRadius: 4
  readonly property real selectedFillAlpha: 0.2
  readonly property int normalBorderWidth: 1
  readonly property real normalBorderAlpha: 0.4
}
""",
    "qs/Commons/Util.qml": """pragma Singleton
import QtQml
QtObject {
  function alpha(color, value) { return Qt.rgba(color.r, color.g, color.b, value) }
}
""",
}

# What the stubs promise, and so what a palette-bound property must show.
POPUP_TEXT = [0.2, 0.4, 0.6, 1.0]
MUTED = [0.8, 0.6, 0.4, 1.0]


def plugin_qml() -> list[Path]:
    """Every QML file the plugin ships: the root widgets and ``qml/**``."""
    paths = sorted(REPO.glob("*.qml")) + sorted((REPO / "qml").rglob("*.qml"))
    return [path for path in paths if not IGNORED & set(path.relative_to(REPO).parts)]


def test_no_plugin_qml_reads_a_bare_palette_token():
    found = {}
    for path in plugin_qml():
        for match in BARE_COLOR.finditer(path.read_text(encoding="utf-8")):
            relative = str(path.relative_to(REPO))
            found.setdefault(relative, []).append(match.group(0))
    assert found == {}


def test_every_file_that_reads_the_palette_imports_the_alias():
    missing = [
        str(path.relative_to(REPO))
        for path in plugin_qml()
        if "Commons.Color." in path.read_text(encoding="utf-8")
        and ALIAS_IMPORT not in path.read_text(encoding="utf-8")
    ]
    assert missing == []


def test_the_guard_sees_every_plugin_qml_file():
    # A guard over an empty or truncated walk would pass vacuously.
    names = {str(path.relative_to(REPO)) for path in plugin_qml()}
    assert {
        "BarWidget.qml",
        "Service.qml",
        "qml/views/LibraryView.qml",
        "qml/components/SoftText.qml",
    } <= names


def test_the_guard_recognises_bare_and_qualified_reads():
    assert BARE_COLOR.search("color: Color.urgent")
    assert BARE_COLOR.search("Style.fillFor(Color.urgent)")
    assert not BARE_COLOR.search("color: Commons.Color.urgent")
    assert not BARE_COLOR.search("border.color: value")
    assert not BARE_COLOR.search("foregroundColor: value")


@pytest.fixture(scope="module")
def observed(tmp_path_factory) -> dict:
    stubs = tmp_path_factory.mktemp("color-stubs")
    for relative, text in _STUBS.items():
        target = stubs / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(HARNESS), str(stubs)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_real_files_load_without_qml_warnings(observed):
    assert observed["warnings"] == []


def test_a_palette_channel_binding_receives_the_theme_colour(observed):
    # SoftText: the popup text colour at 75%, read through its channels.
    # Qt rounds colour channels to 8 bits, so compare within one step.
    assert observed["soft_text"]["color"] == pytest.approx(
        [*POPUP_TEXT[:3], 0.75], abs=1 / 255
    )


def test_a_palette_choice_binding_receives_the_theme_colour(observed):
    # StateBadge with no row: the JavaScript picks the muted tone, and the
    # badge's fill takes that colour at the style's alpha.
    assert observed["state_badge"]["toneColor"] == pytest.approx(MUTED, abs=1 / 255)
    assert observed["state_badge"]["color"] == pytest.approx(
        [*MUTED[:3], 0.2], abs=1 / 255
    )

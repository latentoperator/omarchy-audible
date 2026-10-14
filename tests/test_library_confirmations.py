"""U02: execute Library's confirmation lifecycle in isolated offscreen Qt."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def observed(tmp_path_factory):
    home = tmp_path_factory.mktemp("confirmations-home")
    (home / "runtime").mkdir(mode=0o700)
    env = {
        **os.environ,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / "config"),
        "XDG_DATA_HOME": str(home / "data"),
        "XDG_RUNTIME_DIR": str(home / "runtime"),
        "TMPDIR": str(home),
        "OMARCHY_AUDIBLE_FAKE": "1",
        "QT_QPA_PLATFORM": "offscreen",
    }
    script = (
        r"""
import json, sys
from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
sys.path.insert(0, str(Path(sys.argv[1]) / 'tests'))
from test_removals import function_body
repo = Path(sys.argv[1])
source = (repo / 'qml/views/LibraryView.qml').read_text()
# Actual view properties, callbacks and functions; shell controls are omitted.
prefix = source[source.index('  property int selected:'):source.index('  RowLayout {')]
prefix = prefix.replace('  spacing: Style.spacing.md', '')
key = source[source.index('Keys.onPressed: function(event)'):]
key = function_body(key.replace('Keys.onPressed: function', 'function searchKey', 1), 'searchKey')
qml = """
        + '"""'
        + r"""import QtQuick
import "file:%s/qml/lib/Drawer.js" as Drawer
import "file:%s/qml/lib/Panel.js" as Panel
import "file:%s/qml/lib/LibraryUi.js" as LibraryUi
Item {
  id: root
  property QtObject search: QtObject { property string text: '' }
  property QtObject service: QtObject {
    property string view: 'library'
    property string removeConfirmAsin: ''
    property string confirmAsin: ''
  }
  property QtObject library: QtObject {
    property var allRows: [{asin:'B0FAKE0001',local:true,inLibrary:true}]
    property int count: 1
    signal rowsChanged()
  }
  property QtObject surface: QtObject {
    signal panelClosed()
    signal panelEscapeRequested(var event)
    property QtObject escapeEvent: QtObject { property bool accepted: false }
  }
  readonly property var removable: Drawer.removableAsins(library.allRows)
  property int closes: 0
  onCloseRequested: closes++
  %s
  %s
  function exercise(kind, question) {
    service.view = 'library'; closes = 0
    library.allRows = [{asin:'B0FAKE0001',local:true,inLibrary:true}]
    confirmRemoveAll = question === 'remove'; confirmDisconnect = question === 'disconnect'
    if (kind === 'escape') searchKey({key:Qt.Key_Escape,accepted:false})
    else if (kind === 'catcher') {
      surface.escapeEvent.accepted = false
      surface.panelEscapeRequested(surface.escapeEvent)
      if (!surface.escapeEvent.accepted) closeRequested()
    }
    else if (kind === 'view') service.view = 'mini'
    else if (kind === 'eligible') library.allRows = [{asin:'B0FAKE0002',local:true,inLibrary:true}]
    else if (kind === 'reorder') library.allRows = library.allRows.slice()
    else surface.panelClosed()
    var result = {remove:confirmRemoveAll,disconnect:confirmDisconnect,closes:closes}
    service.view = 'library'
    result.reopenedRemove = confirmRemoveAll; result.reopenedDisconnect = confirmDisconnect
    return result
  }
}
"""
        + '"""'
        + r""" % (repo, repo, repo, prefix, key)
app = QGuiApplication([]); engine = QQmlEngine(); warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
component = QQmlComponent(engine)
component.setData(qml.encode(), QUrl.fromLocalFile(str(repo / 'confirmations-harness.qml')))
obj = component.create()
assert obj is not None, [e.toString() for e in component.errors()]
if obj.metaObject().indexOfProperty('panelSurface') >= 0:
    obj.setProperty('panelSurface', obj.property('surface'))
out = {}
for kind in ('escape','catcher','close','view','eligible','reorder'):
    for question in ('remove','disconnect'):
        out[kind + '-' + question] = obj.exercise(kind, question).toVariant()
out['warnings'] = warnings
print(json.dumps(out))
"""
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(REPO)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("question", ["remove", "disconnect"])
@pytest.mark.parametrize("kind", ["escape", "catcher", "close", "view", "eligible"])
def test_dismissal_and_bulk_set_change_require_fresh_consent(observed, kind, question):
    result = observed[f"{kind}-{question}"]
    assert result == {
        "remove": False,
        "disconnect": False,
        "closes": 0,
        "reopenedRemove": False,
        "reopenedDisconnect": False,
    }


@pytest.mark.parametrize("question", ["remove", "disconnect"])
def test_same_eligible_set_does_not_reset_consent(observed, question):
    result = observed[f"reorder-{question}"]
    assert result[question] is True
    assert result["closes"] == 0


def test_lifecycle_loads_without_warnings(observed):
    assert observed["warnings"] == []


def test_bar_emits_explicit_close_signal_for_every_opened_transition():
    bar = (REPO / "BarWidget.qml").read_text()
    assert "signal panelClosed()" in bar
    assert "onOpenedChanged: if (!opened) panelClosed()" in bar
    assert "signal panelEscapeRequested(var event)" in bar
    assert "root.panelEscapeRequested(root.panelEscapeEvent)" in bar
    assert "if (!root.panelEscapeEvent.accepted) root.close()" in bar
    library = bar.split("LibraryView {", 1)[1].split("}", 1)[0]
    assert "panelSurface: root" in library
    # Click-away/popout and the view's dismiss button all reach opened=false.
    assert "function close()" in bar and "opened = false" in bar
    assert "function closeForPopoutSwitch()" in bar
    assert "onCloseRequested: root.close()" in library

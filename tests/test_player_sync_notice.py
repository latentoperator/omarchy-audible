"""U03: both player notice bindings follow the shared stale-push state."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def observed(tmp_path_factory):
    home = tmp_path_factory.mktemp("notices-home")
    (home / "runtime").mkdir(mode=0o700)
    script = (
        r"""
import json, re, sys
from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
repo = Path(sys.argv[1])
blocks = []
for name in ('Mini', 'Full'):
    source = (repo / f'qml/views/{name}View.qml').read_text()
    blocks_for_notice = re.findall(r'SoftText\s*\{[^{}]*service.staleNotice[^{}]*\}', source)
    block = blocks_for_notice[0] if blocks_for_notice else 'Text { visible: false; text: "" }'
    block = block.replace('SoftText {', 'Text {')
    block = re.sub(r'^\s*(?:Layout\.|font\.)[^\n]*', '', block, flags=re.M)
    block = block.replace('Text {', 'Text { id: ' + name.lower() + 'Notice;', 1)
    blocks.append(block)
qml = """
        + '"""'
        + r"""import QtQuick
import QtQuick.Layouts
import "file:%s/qml/lib/Sync.js" as Sync
Item {
  id: root
  property string view: 'mini'
  property var state: Sync.createState()
  property QtObject service: QtObject {
    readonly property string staleNotice: Sync.staleNotice(root.state.staleCount)
  }
  StackLayout {
    currentIndex: root.view === 'full' ? 1 : 0
    Item { %s }
    Item { %s }
  }
  function outcome(code, ok) {
    var pending = Sync.createState()
    pending.staleCount = state.staleCount; pending.flushing = true
    pending.current = {asin:'B0FAKE0001',ms:1000,at:'2027-01-01T12:00:00Z'}
    state = Sync.step(pending, {type:'finished',job:{purpose:'push'},outcome:{ok:ok,code:code},queue:[]}).state
  }
  function snapshot() {
    return {mini:miniNotice.text,full:fullNotice.text,
      miniVisible:miniNotice.visible,fullVisible:fullNotice.visible}
  }
}
"""
        + '"""'
        + r""" % (repo, *blocks)
app = QGuiApplication([]); engine = QQmlEngine(); warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
component = QQmlComponent(engine)
component.setData(qml.encode(), QUrl.fromLocalFile(str(repo / 'notices-harness.qml')))
obj = component.create()
assert obj is not None, [e.toString() for e in component.errors()]
out = {'initial':obj.snapshot().toVariant()}
obj.outcome('network', False); out['offline'] = obj.snapshot().toVariant()
obj.outcome('stale', False); obj.outcome('stale', False)
out['staleMini'] = obj.snapshot().toVariant()
obj.setProperty('view', 'full'); out['staleFull'] = obj.snapshot().toVariant()
obj.outcome('network', False); out['staleOffline'] = obj.snapshot().toVariant()
obj.outcome('', True); out['successFull'] = obj.snapshot().toVariant()
obj.setProperty('view', 'mini'); out['successMini'] = obj.snapshot().toVariant()
out['warnings'] = warnings
print(json.dumps(out))
"""
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(REPO)],
        env={
            **os.environ,
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_DATA_HOME": str(home / "data"),
            "XDG_RUNTIME_DIR": str(home / "runtime"),
            "TMPDIR": str(home),
            "OMARCHY_AUDIBLE_FAKE": "1",
            "QT_QPA_PLATFORM": "offscreen",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("phase", ["staleMini", "staleFull", "staleOffline"])
def test_stale_notice_persists_in_both_player_views(observed, phase):
    notice = observed[phase]
    assert notice["mini"] == notice["full"]
    assert "Check this computer's clock" in notice["full"]
    assert notice["miniVisible"] is (phase == "staleMini")
    assert notice["fullVisible"] is (phase != "staleMini")


@pytest.mark.parametrize("phase", ["initial", "offline", "successFull", "successMini"])
def test_only_stale_pushes_warn_and_success_clears_everywhere(observed, phase):
    assert observed[phase] == {
        "mini": "",
        "full": "",
        "miniVisible": False,
        "fullVisible": False,
    }


def test_notice_components_load_cleanly(observed):
    assert observed["warnings"] == []


@pytest.mark.parametrize("view", ["Mini", "Full"])
def test_warning_is_plain_wrapping_text_bound_to_service(view):
    source = (REPO / f"qml/views/{view}View.qml").read_text()
    blocks = re.findall(r"SoftText\s*\{[^{}]*service.staleNotice[^{}]*\}", source)
    assert len(blocks) == 1
    assert "visible: text.length > 0" in blocks[0]
    assert "textFormat: Text.PlainText" in blocks[0]
    assert "wrapMode: Text.WordWrap" in blocks[0]
    assert "font.pixelSize: Style.font.bodySmall" in blocks[0]

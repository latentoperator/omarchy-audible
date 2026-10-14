"""U01: synthetic orphan copies require per-book consent, including queued jobs."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_removals import function_body

import qjs

REPO = Path(__file__).resolve().parents[1]
ORPHAN = {
    "asin": "B0FAKE0001",
    "title": "The Quiet Orchard",
    "local": True,
    "inLibrary": False,
}
REGULAR = {**ORPHAN, "inLibrary": True}


@pytest.fixture
def service():
    module = qjs.load("Drawer")
    for name in ("Drawer", "Unload", "PlayRequest"):
        path = REPO / "qml/lib" / f"{name}.js"
        source, imports = qjs._resolve_imports(path.read_text(), path)
        value = module._engine.evaluate(
            qjs._wrap(name, qjs._strip_pragma(source), imports)
        )
        module._check(value, f"loading {name}")
    source = (REPO / "Service.qml").read_text()
    for name in (
        "removeBook",
        "askRemoveBook",
        "confirmRemoveBook",
        "cancelRemoveConfirm",
    ):
        if f"function {name}(" in source:
            module._check(module._engine.evaluate(function_body(source, name)), name)
    value = module._engine.evaluate(
        """
var commands = [], unloaded = [], removeConfirm = null, removeConfirmSurface = null;
var askAsin = '', pendingResume = '', playRequest = null, loadedAsin = '';
var library = {rows: {}, rowFor: function(a) { return this.rows[a] || null; }};
var removals = {unloadThenRemove: function(a, p) {
  unloaded.push({asin:a, purpose:p}); return 'unloading';
}};
function run(c,a,p) {commands.push({command:c,args:a,purpose:p});return true;}
function openSurface() {return null;}
"""
    )
    module._check(value, "synthetic service")
    module.evaluate(f"library.rows = {json.dumps({ORPHAN['asin']: ORPHAN})}")
    return module


@pytest.mark.parametrize("loaded", [False, True])
def test_orphan_request_does_not_remove_or_unload(service, loaded):
    if loaded:
        service.evaluate(f"loadedAsin = {json.dumps(ORPHAN['asin'])}")
    assert service.call("removeBook", ORPHAN["asin"]) == "confirm"
    assert service.evaluate("commands") == []
    assert service.evaluate("unloaded") == []


@pytest.mark.parametrize("loaded", [False, True])
def test_ordinary_library_removal_is_unchanged(service, loaded):
    service.evaluate(f"library.rows = {json.dumps({REGULAR['asin']: REGULAR})}")
    if loaded:
        service.evaluate(f"loadedAsin = {json.dumps(REGULAR['asin'])}")
    assert service.call("removeBook", REGULAR["asin"]) == (
        "unloading" if loaded else "ok"
    )
    effects = service.evaluate("unloaded" if loaded else "commands")
    assert effects[0]["purpose"] == "user"


@pytest.mark.parametrize("loaded", [False, True])
def test_confirmation_authorizes_only_the_named_orphan(service, loaded):
    if loaded:
        service.evaluate(f"loadedAsin = {json.dumps(ORPHAN['asin'])}")
    service.call("removeBook", ORPHAN["asin"])
    assert service.call("confirmRemoveBook", "B0FAKE0002") != "ok"
    assert service.evaluate("commands") == []
    service.call("removeBook", ORPHAN["asin"])
    assert service.call("confirmRemoveBook", ORPHAN["asin"]) == (
        "unloading" if loaded else "ok"
    )
    effects = service.evaluate("unloaded" if loaded else "commands")
    assert effects[0]["purpose"] == "user-confirmed"
    assert service.evaluate("removeConfirm") is None
    before = len(effects)
    service.call("confirmRemoveBook", ORPHAN["asin"])
    assert len(service.evaluate("unloaded" if loaded else "commands")) == before


def test_cancel_keeps_copy_and_consumes_no_consent(service):
    service.call("removeBook", ORPHAN["asin"])
    service.call("cancelRemoveConfirm")
    service.call("confirmRemoveBook", ORPHAN["asin"])
    assert service.evaluate("commands") == []
    assert service.evaluate("unloaded") == []
    assert service.call("removeBook", ORPHAN["asin"]) == "confirm"


def test_full_regular_question_cannot_authorize_a_new_orphan(service):
    service.evaluate(f"library.rows = {json.dumps({REGULAR['asin']: REGULAR})}")
    service.call("askRemoveBook", REGULAR["asin"])
    service.evaluate(f"library.rows = {json.dumps({ORPHAN['asin']: ORPHAN})}")
    service.call("confirmRemoveBook", ORPHAN["asin"])
    assert service.evaluate("commands") == []


@pytest.mark.parametrize("purpose", ["autoremove", "autoremove-unloaded"])
def test_service_auto_removal_cannot_ask_or_delete_an_orphan(service, purpose):
    assert service.call("removeBook", ORPHAN["asin"], purpose) == "error: protected"
    assert service.evaluate("commands") == []
    assert service.evaluate("unloaded") == []
    assert service.evaluate("removeConfirm") is None


@pytest.mark.parametrize(
    "purpose,decision",
    [("user", "confirm"), ("user-confirmed", "remove"), ("autoremove", "blocked")],
)
def test_orphan_decision_is_in_js(purpose, decision):
    assert qjs.load("Drawer").call("removalDecision", ORPHAN, purpose) == decision


@pytest.mark.parametrize("row", [ORPHAN, {**ORPHAN, "title": " <b>Orchard</b> "}])
def test_warning_names_title_and_does_not_promise_recovery(row):
    text = qjs.load("Drawer").call("removeQuestion", row)
    assert row["title"].strip() in text
    assert "no longer in your Audible library" in text
    assert "may not be able to download it again" in text
    assert "It stays in your library" not in text


def test_regular_full_confirmation_does_not_grant_orphan_permission(service):
    service.evaluate(f"library.rows = {json.dumps({REGULAR['asin']: REGULAR})}")
    service.call("askRemoveBook", REGULAR["asin"])
    assert service.call("confirmRemoveBook", REGULAR["asin"]) == "ok"
    assert service.evaluate("commands")[0]["purpose"] == "user"


def test_confirmed_orphan_job_cannot_run_after_a_new_play_intent():
    assert (
        qjs.load("Unload").call(
            "jobAllowed",
            {
                "command": "remove",
                "args": [ORPHAN["asin"]],
                "purpose": "user-confirmed",
            },
            False,
            False,
            False,
            [ORPHAN["asin"]],
        )
        is False
    )


def test_confirmation_survives_unload_but_not_new_play_intent():
    unload = qjs.load("Unload")
    pending = unload.call(
        "step", [], {"type": "add", "asin": ORPHAN["asin"], "purpose": "user-confirmed"}
    )["pending"]
    assert len(pending) == 1
    effects = unload.call(
        "step", pending, {"type": "unloaded", "busy": [], "autoRemove": False}
    )["effects"]
    assert {
        "type": "run",
        "asin": ORPHAN["asin"],
        "purpose": "user-confirmed",
    } in effects
    assert (
        unload.call("step", pending, {"type": "intent", "asin": ORPHAN["asin"]})[
            "pending"
        ]
        == []
    )


@pytest.fixture(scope="module")
def removals_observed(tmp_path_factory):
    # Separate GUI process: the rest of the suite owns a QCoreApplication.
    home = tmp_path_factory.mktemp("orphan-home")
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
    (home / "runtime").mkdir(mode=0o700)
    script = r'''
import json, sys
from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
app = QGuiApplication([])
engine = QQmlEngine()
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
component = QQmlComponent(engine)
qml = """import QtQuick
import "file:%s/qml"
Item {
  id: host
  property var row: ({asin:'B0FAKE0001',local:true,inLibrary:false,title:'The Quiet Orchard'})
  property var commands: []
  property var unloads: []
  property bool autoRemoveFinished: true
  property string loadedAsin: ''
  property bool playing: false
  function atEnd(a) { return true }
  function busyAsins() { return [] }
  function rowFor(a) { return row }
  function logEvent(c,t) {}
  function run(c,a,p) { commands = commands.concat([{command:c,args:a,purpose:p}]); return true }
  function removeBook(a,p) { unloads = unloads.concat([{asin:a,purpose:p}]) }
  Removals { id: removals; service: host; library: host; player: host }
  function checkAuto(loaded, orphan) {
    commands = []; unloads = []
    loadedAsin = loaded ? 'B0FAKE0001' : ''
    row = {asin:'B0FAKE0001',local:true,inLibrary:!orphan,title:'The Quiet Orchard'}
    removals.candidate = 'B0FAKE0001'
    removals.removeIfStillFinished()
    return {commands:commands,unloads:unloads}
  }
  function checkJob(purpose, orphan) {
    row = {asin:'B0FAKE0001',local:true,inLibrary:!orphan}
    return removals.jobAllowed({command:'remove',args:['B0FAKE0001'],purpose:purpose})
  }
}
""" % Path(sys.argv[1]).as_posix()
component.setData(qml.encode(), QUrl.fromLocalFile(str(Path(sys.argv[1]) / 'orphan-harness.qml')))
obj = component.create()
assert obj is not None, [e.toString() for e in component.errors()]
observed = {'auto':{}, 'jobs':{}}
for loaded in (False, True):
    for orphan in (False, True):
        observed['auto'][f'{loaded}-{orphan}'] = obj.checkAuto(loaded, orphan).toVariant()
for purpose in ('user','user-confirmed','autoremove','autoremove-unloaded',''):
    for orphan in (False, True):
        observed['jobs'][f'{purpose}-{orphan}'] = obj.checkJob(purpose, orphan)
# Exercise the actual Service removal properties, functions and surface-close
# Connections in Qt, without loading backend/player/process components.
sys.path.insert(0, str(Path(sys.argv[1]) / 'tests'))
from test_removals import function_body
source = (Path(sys.argv[1]) / 'Service.qml').read_text()
observed['dismissals'] = {}
if 'property var removeConfirm: null' in source:
    properties = source.split('  property var removeConfirm: null', 1)[1].split('  property real lastSyncAttemptAtMs', 1)[0]
    properties = 'property var removeConfirm: null' + properties
    connections = source.split('  Connections {\n    target: root.removeConfirmSurface', 1)[1].split('\n  function removeAll()', 1)[0]
    connections = 'Connections {\n    target: root.removeConfirmSurface' + connections
    functions = '\n'.join(function_body(source, name) for name in (
        'askRemoveBook', 'cancelRemoveConfirm', 'dropInvalidRemoveConfirm',
        'confirmRemoveBook', 'removeBook'))
    isolated = """import QtQuick
import "file:%s/qml/lib/Drawer.js" as Drawer
import "file:%s/qml/lib/Unload.js" as Unload
import "file:%s/qml/lib/PlayRequest.js" as PlayRequest
Item {
  id: root
  property string view: 'full'
  property string askAsin: ''
  property string pendingResume: ''
  property string loadedAsin: ''
  property var playRequest: null
  property var commands: []
  property var library: ({rowFor: function(a) {
    return {asin:a,local:true,inLibrary:false,title:'The Quiet Orchard'};
  }})
  property QtObject surface: QtObject { property bool opened: true }
  function openSurface() {return surface}
  function run(c,a,p) {commands = commands.concat([c]);return true}
  %s
  %s
  %s
  function dismiss(kind) {
    commands = []; surface.opened = true; view = 'full'
    askRemoveBook('B0FAKE0001')
    var asked = removeConfirmAsin === 'B0FAKE0001'
    if (kind === 'cancel') cancelRemoveConfirm()
    else if (kind === 'view') view = 'mini'
    else surface.opened = false
    var cleared = removeConfirm === null
    confirmRemoveBook('B0FAKE0001')
    return {asked:asked,cleared:cleared,commands:commands}
  }
}""" % (sys.argv[1], sys.argv[1], sys.argv[1], properties, functions, connections)
    component.setData(isolated.encode(), QUrl.fromLocalFile(str(Path(sys.argv[1]) / 'service-removal-harness.qml')))
    isolated_obj = component.create()
    assert isolated_obj is not None, [e.toString() for e in component.errors()]
    for kind in ('cancel', 'esc', 'click-away', 'view'):
        observed['dismissals'][kind] = isolated_obj.dismiss(kind).toVariant()
        app.processEvents()
    isolated_obj.deleteLater()
observed['warnings'] = warnings
print(json.dumps(observed))
obj.deleteLater()
app.processEvents()
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(REPO)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("loaded", [False, True])
def test_real_removals_component_never_auto_removes_orphans(removals_observed, loaded):
    assert removals_observed["auto"][f"{loaded}-True"] == {
        "commands": [],
        "unloads": [],
    }


@pytest.mark.parametrize("purpose", ["user", "autoremove", "autoremove-unloaded", ""])
def test_queued_jobs_recheck_orphan_protection(removals_observed, purpose):
    assert removals_observed["jobs"][f"{purpose}-True"] is False


def test_real_removals_component_preserves_ordinary_and_confirmed_removal(
    removals_observed,
):
    assert removals_observed["warnings"] == []
    for loaded in (False, True):
        effects = removals_observed["auto"][f"{loaded}-False"]
        assert effects["unloads" if loaded else "commands"]
    assert removals_observed["jobs"]["user-False"] is True
    assert removals_observed["jobs"]["user-confirmed-True"] is True


@pytest.mark.parametrize("kind", ["cancel", "esc", "click-away", "view"])
def test_service_dismissal_clears_orphan_consent_in_qt(removals_observed, kind):
    assert removals_observed["dismissals"].get(kind) == {
        "asked": True,
        "cleared": True,
        "commands": [],
    }


def test_library_escape_cancels_without_removing(service):
    source = (
        (REPO / "qml/views/LibraryView.qml")
        .read_text()
        .replace("Keys.onPressed: function(event)", "function libraryKey(event)", 1)
    )
    value = service._engine.evaluate(function_body(source, "libraryKey"))
    service._check(value, "Library key handler")
    value = service._engine.evaluate(
        """
var closed = false;
Object.defineProperty(this, 'removeConfirmAsin', {get: function() {
  return removeConfirm ? removeConfirm.asin : '';
}});
var root = {service:this, closeRequested:function() {closed=true;}};
var search = {text:''};
"""
    )
    service._check(value, "Library focus boundary")
    service.call("removeBook", ORPHAN["asin"])
    service.call("libraryKey", {"key": 0x01000000})
    assert service.evaluate("removeConfirm") is None
    assert service.evaluate("commands") == []
    assert service.evaluate("closed") is False


def test_library_and_full_bind_explicit_confirmation_and_cancel():
    row = (REPO / "qml/components/BookRow.qml").read_text()
    library = (REPO / "qml/views/LibraryView.qml").read_text()
    full = (REPO / "qml/views/FullView.qml").read_text()
    assert "signal confirmRemoveRequested()" in row
    assert (
        "onConfirmRemoveRequested: root.service.confirmRemoveBook(modelData.asin)"
        in library
    )
    assert "onCancelRemoveRequested: root.service.cancelRemoveConfirm()" in library
    esc = library.split("Drawer.KEY_CLOSE", 1)[1].split("event.accepted = true", 1)[0]
    assert esc.index("cancelRemoveConfirm()") < esc.index("root.closeRequested()")
    assert "text: Drawer.removeQuestion(root.row)" in full
    assert "root.service.askRemoveBook(root.asin)" in full
    assert "root.service.confirmRemoveBook(root.asin)" in full
    assert "onClicked: root.service.cancelRemoveConfirm()" in full
    assert "It stays in your library" not in full

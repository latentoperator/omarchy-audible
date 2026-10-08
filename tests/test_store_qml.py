"""Headless wiring checks for the real StateStore.qml and stub I/O types."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

try:
    from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QCoreApplication, QMetaObject, QUrl
    from PySide6.QtQml import QQmlComponent, QQmlEngine
except ImportError as exc:  # pragma: no cover - required dev dependency
    raise ImportError("PySide6 is required for StateStore QML wiring tests") from exc

REPO = Path(__file__).resolve().parents[1]
_APP: QCoreApplication | None = None


def _application() -> QCoreApplication:
    global _APP
    if _APP is None:
        _APP = QCoreApplication.instance() or QCoreApplication([])
    return _APP


def _variant(value):
    return value.toVariant() if hasattr(value, "toVariant") else value


@pytest.fixture
def qml_store(tmp_path, monkeypatch):
    from PySide6.QtCore import qInstallMessageHandler

    _application()
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    module = tmp_path / "Quickshell"
    io = module / "Io"
    io.mkdir(parents=True)
    (module / "qmldir").write_text(
        "module Quickshell\nDummy 1.0 Dummy.qml\n", encoding="utf-8"
    )
    (module / "Dummy.qml").write_text("import QtQml\nQtObject {}\n", encoding="utf-8")
    (io / "qmldir").write_text(
        "module Quickshell.Io\n"
        "FileView 1.0 FileView.qml\n"
        "Process 1.0 Process.qml\n"
        "singleton FileViewError 1.0 FileViewError.qml\n",
        encoding="utf-8",
    )
    (io / "FileView.qml").write_text(
        """import QtQml
QtObject {
  property string path: ""
  property bool atomicWrites: false
  property bool printErrors: true
  property var log: []
  property string content: ""
  signal loaded()
  signal loadFailed(int error)
  signal saved()
  signal saveFailed(int error)
  function text() { return content }
  function setText(value) { log = log.concat([["write", value]]) }
  function waitForJob() { log = log.concat([["wait"]]) }
  function reload() {}
}
""",
        encoding="utf-8",
    )
    (io / "Process.qml").write_text(
        """import QtQml
QtObject {
  property var command: []
  property bool running: false
  signal exited(int code, int status)
  function finish(code) { running = false; exited(code, 0) }
}
""",
        encoding="utf-8",
    )
    (io / "FileViewError.qml").write_text(
        "pragma Singleton\nimport QtQml\nQtObject { enum Kind { Other, FileNotFound } }\n",
        encoding="utf-8",
    )
    app_dir = tmp_path / "app"
    lib_dir = app_dir / "lib"
    lib_dir.mkdir(parents=True)
    shutil.copy2(REPO / "qml/StateStore.qml", app_dir / "StateStore.qml")
    for source in (REPO / "qml/lib").glob("*.js"):
        shutil.copy2(source, lib_dir / source.name)
    (app_dir / "Main.qml").write_text(
        """import QtQuick
Item {
  id: top
  property var storeRef: null
  property var fileRef: null
  property var processRef: null
  property bool reactToLoaded: false
  StateStore {
    id: store
    path: "/fake/state.json"
    Component.onCompleted: {
      top.storeRef = store
      for (var i = 0; i < store.data.length; i++) {
        if (store.data[i].log !== undefined) top.fileRef = store.data[i]
        if (store.data[i].command !== undefined) top.processRef = store.data[i]
      }
    }
  }
  Connections {
    target: store
    function onLoadedChanged() {
      if (top.reactToLoaded && store.loaded)
        store.setQueue([{ "asin": "A", "ms": 5000, "at": "queued" }])
    }
  }
  function clearLog() { fileRef.log = [] }
  function runLoadedReaction(text) {
    reactToLoaded = true
    store.record("A", 4000)
    fileRef.content = text
    fileRef.loaded()
    return { writes: fileRef.log, warningsMarker: store.loaded }
  }
  function runCorrupt() {
    reactToLoaded = false
    store.record("A", 2000)
    fileRef.content = "broken"
    fileRef.loaded()
    var initial = { command: processRef.command, log: fileRef.log, loaded: store.loaded }
    processRef.finish(1)
    var failed = { log: fileRef.log, retryRunning: backupRetryRunning(), loaded: store.loaded }
    processRef.finish(0)
    return {
      command: initial.command,
      initialLog: initial.log,
      initialLoaded: initial.loaded,
      failedLog: failed.log,
      retryRunning: failed.retryRunning,
      failedLoaded: failed.loaded,
      finalLog: fileRef.log,
      finalLoaded: store.loaded
    }
  }
  function backupRetryRunning() {
    var running = false
    for (var i = 0; i < store.data.length; i++)
      if (store.data[i].interval === 30000 && store.data[i].running !== undefined)
        running = running || store.data[i].running
    return running
  }
  function runFlush() {
    store.record("B", 9000)
    clearLog()
    store.flush()
    return fileRef.log
  }
}
""",
        encoding="utf-8",
    )
    warnings: list[str] = []
    previous_handler = qInstallMessageHandler(
        lambda mode, context, message: warnings.append(message)
    )
    engine = QQmlEngine()
    engine.addImportPath(str(tmp_path))
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(app_dir / "Main.qml")))
    obj = component.create()
    assert obj is not None, component.errorString()

    def invoke(name, arg=None):
        if arg is None:
            result = QMetaObject.invokeMethod(obj, name, Q_RETURN_ARG("QVariant"))
        else:
            result = QMetaObject.invokeMethod(
                obj, name, Q_RETURN_ARG("QVariant"), Q_ARG("QVariant", arg)
            )
        return _variant(result)

    yield invoke, warnings
    qInstallMessageHandler(previous_handler)
    engine.deleteLater()


def _valid_state() -> str:
    return json.dumps(
        {"schema": 1, "books": {}, "push_queue": [], "volume": None, "speed": None}
    )


def test_loaded_reaction_queue_is_saved_once_without_binding_warning(qml_store):
    invoke, warnings = qml_store
    result = invoke("runLoadedReaction", _valid_state())
    assert len(result["writes"]) == 1
    written = json.loads(result["writes"][0][1])
    assert written["push_queue"] == [{"asin": "A", "ms": 5000, "at": "queued"}]
    assert not [
        warning
        for warning in warnings
        if "StateStore" in warning or "Binding loop" in warning
    ]


def test_corrupt_backup_retry_and_successful_replay_wiring(qml_store):
    invoke, _warnings = qml_store
    result = invoke("runCorrupt")
    assert result["command"] == [
        "cp",
        "-f",
        "/fake/state.json",
        "/fake/state.json.corrupt",
    ]
    assert result["initialLog"] == []
    assert result["initialLoaded"] is False
    assert result["failedLog"] == []
    assert result["retryRunning"] is True
    assert result["failedLoaded"] is False
    assert result["finalLoaded"] is True
    assert len(result["finalLog"]) == 1
    written = json.loads(result["finalLog"][0][1])
    assert written["books"]["A"]["ms"] == 2000


def test_flush_writes_then_waits_for_file(qml_store):
    invoke, _warnings = qml_store
    invoke("runLoadedReaction", _valid_state())
    events = invoke("runFlush")
    assert events[0][0] == "write"
    assert events[1] == ["wait"]

"""Backend records reach the service as plain JS values on every Qt (Qt 6.12).

From Qt 6.12 a ``var`` signal argument is handed to the handler as a converted
copy: arrays inside it arrive as objects keyed "0", "1", ... and a mark the service
puts on a job in one handler is gone in the next. ``Library.js`` and ``PlayRequest.js`` check
``Array.isArray``, so on 6.12 downloaded books showed as cloud books and a play
request never matched its job. The runner now calls function properties, which
pass the JS value itself on 6.10, 6.11 and 6.12 alike.

This drives the real ``JobRunner``/``BackendCall`` under the recording
``Process`` stub and looks at what the service-side handlers receive.
"""

from __future__ import annotations

import json
import re

import test_argv_privacy as harness
from PySide6.QtCore import Q_ARG, QEventLoop, QMetaObject, QObject, QTimer
from test_argv_privacy import REPO

MAIN = """import QtQuick
Item {
  id: top
  property var seen: []
  property var job: null
  JobRunner {
    id: runner
    launcher: "/invented/backend"
    eventHandler: function(record, job) {
      if (record.type !== "local") return
      top.seen = top.seen.concat([{
        "booksIsArray": Array.isArray(record.books),
        "nestedIsArray": Array.isArray(record.books[0].chapters),
        "argsIsArray": Array.isArray(job.args)
      }])
      job.marked = true
    }
    finishedHandler: function(job, outcome) {
      top.seen = top.seen.concat([{
        "finishedArgsIsArray": Array.isArray(job.args),
        "markKept": job.marked === true,
        "eventsIsArray": Array.isArray(outcome.terminal ? [outcome.terminal] : []),
        "ok": outcome.ok
      }])
    }
  }
  function start() { runner.run("local", [], "t") }
}
"""

RECORD = {
    "type": "local",
    "books": [{"asin": "B0FAKE0001", "chapters": [1, 2]}, {"asin": "B0FAKE0002"}],
}


def test_records_and_jobs_reach_the_handlers_as_js_values(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "_MAIN", MAIN)
    stub = harness._STUBS["Quickshell/Io/Process.qml"]
    monkeypatch.setitem(
        harness._STUBS,
        "Quickshell/Io/Process.qml",
        stub.replace("QtObject {", 'QtObject {\n  objectName: "recordingProcess"', 1),
    )
    runner = harness._Runner(tmp_path)
    try:
        assert QMetaObject.invokeMethod(runner.root, "start")
        process = runner.root.findChild(QObject, "recordingProcess")
        assert process is not None
        lines = json.dumps(RECORD) + "\n" + json.dumps({"type": "done"}) + "\n"
        assert QMetaObject.invokeMethod(
            process.property("stdout"), "read", Q_ARG(str, lines)
        )
        assert QMetaObject.invokeMethod(process, "exited", Q_ARG(int, 0), Q_ARG(int, 0))
        loop = QEventLoop()
        QTimer.singleShot(150, loop.quit)
        loop.exec()
        seen = runner.root.property("seen").toVariant()
        assert seen == [
            {
                "booksIsArray": True,
                "nestedIsArray": True,
                "argsIsArray": True,
            },
            {
                "finishedArgsIsArray": True,
                "markKept": True,
                "eventsIsArray": True,
                "ok": True,
            },
        ]
    finally:
        runner.close()


def test_no_var_signal_carries_backend_values():
    # A `var` signal on the runner or the call would bring the 6.12 copy back.
    for name in ("qml/JobRunner.qml", "qml/BackendCall.qml"):
        source = (REPO / name).read_text()
        assert not re.search(r"^\s*signal\s+\w+\(.*\bvar\b", source, re.MULTILINE), name
    service = (REPO / "Service.qml").read_text()
    assert "onEvent:" not in service
    assert "onJobFinished:" not in service

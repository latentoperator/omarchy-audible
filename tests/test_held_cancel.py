"""S04: cancellation belongs to one get request, including BackendCall's drain."""

import json

import pytest
from test_held_lifecycle import REPO, UNTIL, A, B
from test_held_lifecycle import service as service  # noqa: PLC0414
from test_p8_service import function_body

import qjs


def start_get(service, queued=True):
    service.call("run", "get", [A], "download")
    service.evaluate("job = JobQueue.take(runner.queue)")
    service.evaluate("runner.sync()")
    if queued:
        service.call("run", "get", [B], "download")
    return service.evaluate("job")


def backend_boundary(service):
    path = REPO / "qml/lib/Ndjson.js"
    source, imports = qjs._resolve_imports(qjs._strip_pragma(path.read_text()), path)
    service._check(
        service._engine.evaluate(qjs._wrap("Ndjson", source, imports)), "Ndjson"
    )
    source = (REPO / "qml/BackendCall.qml").read_text()
    start = source.index("    onExited: function(")
    exited = function_body(
        source[start:].replace("onExited: function", "function exited", 1), "exited"
    )
    code = (
        """backend = (function() {
var root = {splitter:Ndjson.createSplitter(),exitCode:-1,stderrText:'',record:function(){}};
var splitter = root.splitter;
var drain = {running:false,restart:function(){this.running=true;}};
"""
        + function_body(source, "emitRecords")
        + function_body(source, "settle")
        + exited
        + """
root.emitRecords = emitRecords; root.settle = settle; root.exited = exited; root.drain = drain;
root.feed = function(text){emitRecords(Ndjson.feed(splitter,text));};
root.finished = function(outcome){
  completedOutcome = outcome;
  completion = JobQueue.complete(runner.queue,outcome);
  runner.sync(); onJobFinished(job,outcome);
};
return root;
})()"""
    )
    service._check(service._engine.evaluate(code), "synthetic exit/drain boundary")


@pytest.mark.parametrize("timing", ["before_denial", "exit_drain", "late_stdout"])
def test_cancelled_throttled_request_never_reappears_at_expiry(service, timing):
    start_get(service)
    backend_boundary(service)
    terminal = json.dumps({"type": "error", "code": "throttled", "until": UNTIL})
    if timing == "exit_drain":
        service.call("backend.feed", terminal + "\n")
        service.call("backend.exited", 1, 0)
    assert service.call("cancelDownload", A) == "send_cancel"
    if timing == "before_denial":
        service.call("backend.feed", terminal + "\n")
        service.call("backend.exited", 1, 0)
    elif timing == "late_stdout":
        service.call("backend.exited", 1, 0)
        service.call("backend.feed", terminal)  # the final line drains on settle
    assert service.evaluate("backend.drain.running") is True
    # The separate cancel command may be too late; its result must not erase intent.
    service.call(
        "onJobFinished",
        {"command": "cancel", "args": [A]},
        {"ok": False, "code": "not_running"},
    )
    service.call("backend.settle")
    assert service.evaluate("held.asins") == [B]
    assert service.evaluate("held.until") == UNTIL
    service.evaluate("commands = []")
    service.evaluate("NOW = Date.parse('2027-01-16T12:00:00Z')")
    service.call("onPauseElapsed")
    gets = service.evaluate("commands.filter(function(j){return j.command==='get';})")
    assert [j["args"][0] for j in gets] == [B]
    assert service.evaluate("failures") == {}


@pytest.mark.parametrize("result", ["cancelled", "throttled", "network"])
def test_cancel_intent_lives_on_the_request_until_completion(result):
    queue = qjs.load("JobQueue")
    state = queue.hold("create")
    queue.call("enqueue", state, {"command": "get", "args": [A]})
    queue.call("take", state)
    queue.call("cancel", state, A)
    assert state.read()["active"].get("cancelRequested") is True
    completed = queue.call("complete", state, {"ok": False, "code": result})
    assert completed["job"].get("cancelRequested") is True
    assert state.read()["active"] is None
    queue.call("enqueue", state, {"command": "get", "args": [A]})
    assert queue.call("take", state).get("cancelRequested", False) is False


def test_cancelled_busy_request_is_not_automatically_retried():
    queue = qjs.load("JobQueue")
    state = queue.hold("create")
    queue.call("enqueue", state, {"command": "get", "args": [A]})
    queue.call("take", state)
    queue.call("cancel", state, A)
    result = queue.call("complete", state, {"ok": False, "busy": True, "code": "busy"})
    assert result["action"] == "fail"
    assert state.read()["pending"] == []


def test_cancel_after_atomic_install_preserves_success(service):
    start_get(service, queued=False)
    backend_boundary(service)
    service.call("backend.feed", '{"type":"done","command":"get"}\n')
    service.call("backend.exited", 0, 0)
    assert service.call("cancelDownload", A) == "send_cancel"
    service.call("backend.settle")
    assert service.evaluate("completedOutcome.ok") is True
    assert service.evaluate("completion.action") == "ok"
    assert service.evaluate("held.asins") == []
    assert service.evaluate("failures") == {}
    assert (
        service.evaluate("commands.some(function(j){return j.command==='status';})")
        is True
    )


def test_cancel_after_held_display_drops_only_that_intent(service):
    job = start_get(service)
    service.evaluate("JobQueue.complete(runner.queue,{ok:false,code:'throttled'})")
    service.evaluate("runner.sync()")
    service.call(
        "onJobFinished",
        job,
        {"ok": False, "code": "throttled", "terminal": {"until": UNTIL}},
    )
    assert service.evaluate("held.asins") == [A, B]
    assert service.call("cancelDownload", A) == "dropped"
    assert service.evaluate("held.asins") == [B]


def test_cancellation_of_other_asin_does_not_cancel_running_request(service):
    start_get(service)
    assert service.call("cancelDownload", B) == "dropped"
    service.evaluate("JobQueue.complete(runner.queue,{ok:false,code:'throttled'})")
    service.evaluate("runner.sync()")
    service.call(
        "onJobFinished",
        service.evaluate("job"),
        {"ok": False, "code": "throttled", "terminal": {"until": UNTIL}},
    )
    assert service.evaluate("held.asins") == [A]


@pytest.mark.parametrize(
    "terminal,exit_code", [("throttled", 1), ("busy", 3), ("done", 0)]
)
def test_real_qml_runner_keeps_cancel_intent_across_backend_exit_drain(
    tmp_path, monkeypatch, terminal, exit_code
):
    import test_argv_privacy as harness
    from PySide6.QtCore import (
        Q_ARG,
        Q_RETURN_ARG,
        QEventLoop,
        QMetaObject,
        QObject,
        QTimer,
    )

    main = """import QtQuick
Item {
  id: top
  property var outcomes: []
  JobRunner {
    id: runner
    launcher: "/invented/backend"
    onJobFinished: function(job, outcome) {
      if (job.command === "get") top.outcomes = top.outcomes.concat([{
        cancelled: job.cancelRequested === true, ok: outcome.ok, code: outcome.code
      }])
    }
  }
  function start() {runner.run("get", ["B0FAKE0002"], "download")}
  function cancel() {return runner.cancel("B0FAKE0002")}
}
"""
    monkeypatch.setattr(harness, "_MAIN", main)
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
        record = (
            {"type": "done"}
            if terminal == "done"
            else {"type": "error", "code": terminal, "until": UNTIL}
        )
        assert QMetaObject.invokeMethod(
            process.property("stdout"), "read", Q_ARG(str, json.dumps(record) + "\n")
        )
        assert QMetaObject.invokeMethod(
            process, "exited", Q_ARG(int, exit_code), Q_ARG(int, 0)
        )
        action = QMetaObject.invokeMethod(
            runner.root, "cancel", Q_RETURN_ARG("QVariant")
        )
        assert action == "send_cancel"
        loop = QEventLoop()
        QTimer.singleShot(150, loop.quit)
        loop.exec()
        outcomes = runner.root.property("outcomes").toVariant()
        assert outcomes == [
            {
                "cancelled": True,
                "ok": terminal == "done",
                "code": None if terminal == "done" else terminal,
            }
        ]
    finally:
        runner.close()

"""S02: execute Service's resume callbacks with synthetic backend/player boundaries."""

from __future__ import annotations

from itertools import permutations
from pathlib import Path

import pytest
from test_p8_service import function_body

import qjs

REPO = Path(__file__).resolve().parents[1]
A = "B0FAKE0002"
B = "B0FAKE0003"


@pytest.fixture
def service():
    module = qjs.load("Positions")
    for name in ("Positions", "Playback", "PlayRequest", "Drawer", "Unload", "Signin"):
        path = REPO / "qml/lib" / f"{name}.js"
        source, imports = qjs._resolve_imports(
            qjs._strip_pragma(path.read_text()), path
        )
        module._check(module._engine.evaluate(qjs._wrap(name, source, imports)), name)
    source = (REPO / "Service.qml").read_text()
    for name in (
        "playBook",
        "finishResume",
        "resumeCurrent",
        "recordResume",
        "cachedStartSec",
        "noteIntent",
        "quitPlayer",
        "removeBook",
        "busyAsins",
        "playNow",
        "startPlayInfo",
        "finishPlayInfo",
    ):
        if f"function {name}(" in source:
            module._check(module._engine.evaluate(function_body(source, name)), name)
    for signal in ("onEvent", "onJobFinished"):
        start = source.index(f"    {signal}: function(")
        body = function_body(
            source[start:].replace(f"{signal}: function", "function callback", 1),
            "callback",
        )
        module._check(
            module._engine.evaluate(body.replace("callback", signal, 1)), signal
        )
    module.evaluate("""(function() {
this.root = this;
this.booksDir = '/invented/books'; this.pendingResume = ''; this.resumeRemotes = {};
this.resumeRequest = null; this.resumeSerial = 0; this.playRequest = null; this.playSerial = 0;
this.playError = ''; this.askAsin = ''; this.confirmAsin = ''; this.loadedAsin = '';
this.commands = []; this.plays = []; this.failures = {}; this.refuseRead = false;
this.rows = {
  B0FAKE0002:{asin:'B0FAKE0002',local:true,state:'local',inLibrary:true,positionMs:42000,title:'Invented A'},
  B0FAKE0003:{asin:'B0FAKE0003',local:true,state:'local',inLibrary:true,positionMs:84000,title:'Invented B'}
};
this.library = {rowFor:function(a){return rows[a] || null;}};
this.store = {loaded:true,doc:{books:{}}};
this.run = function(c,a,p){
  if(c==='position-get' && refuseRead) return false;
  commands.push({command:c,args:a,purpose:p||''});return true;
};
this.saveSettings = function(){}; this.cancelRemoveConfirm = function(){};
this.player = {pendingLoad:null,quit:function(){},play:function(path,start){
  plays.push({path:path,start:start});return true;
}};
this.removals = {dropIntent:function(){},unloadThenRemove:function(){return 'unloading';}};
this.catchupFlow = {noteIntent:function(){},handleEvent:function(){},handleFinished:function(){}};
this.sync = {handleEvent:function(){},handleFinished:function(){}};
this.signinFlow = {handleEvent:function(){},handleFinished:function(){}};
this.remoteFile = {reload:function(){}};
this.EventLog = {summarize:function(){return '';}};
this.logEvent = function(){};
this.failPlay = function(){throw new Error('unexpected play failure');};
this.reads = function(){return commands.filter(function(j){return j.command==='position-get';});};
this.loads = function(){return commands.filter(function(j){return j.command==='play-info';});};
})()""")
    return module


def start(service, asin=A):
    assert service.call("playBook", asin, -1) == "ok"
    return service.evaluate("reads()[reads().length-1]")


def record(service, job, ms):
    service.call(
        "onEvent",
        {
            "type": "positions",
            "items": {job["args"][0]: {"ms": ms, "updated_at": "2027-01-15T12:00:00Z"}},
        },
        job,
    )


def finish(service, job, ok=True):
    service.call("onJobFinished", job, {"ok": ok, "code": "" if ok else "network"})


def assert_latest_load(service, expected=200):
    loads = service.evaluate("loads()")
    assert len(loads) == 1
    assert service.evaluate("playRequest.startSec") == expected
    service.call(
        "onEvent",
        {"type": "play_info", "path": f"/invented/books/{A}/book.m4b"},
        loads[0],
    )
    assert service.evaluate("plays") == [
        {"path": f"/invented/books/{A}/book.m4b", "start": expected}
    ]


@pytest.mark.parametrize("sequence", ["stop", "switch", "repeat"])
@pytest.mark.parametrize(
    "order",
    [
        order
        for order in permutations(
            ("old_record", "old_finish", "new_record", "new_finish")
        )
        if order.index("old_record") < order.index("old_finish")
        and order.index("new_record") < order.index("new_finish")
    ],
)
def test_only_latest_resume_uses_its_own_response(service, sequence, order):
    # A process emits its record before its terminal signal; different reads
    # can interleave in every other way, including the stdout-drain window.
    old = start(service)
    if sequence == "stop":
        service.call("quitPlayer")
    elif sequence == "switch":
        middle = start(service, B)
        record(service, middle, 300000)
    new = start(service)
    for action in order:
        if action == "old_record":
            record(service, old, 100000)
        elif action == "old_finish":
            finish(service, old)
        elif action == "new_record":
            record(service, new, 200000)
        else:
            finish(service, new)
        if action != "new_finish" and order.index(action) < order.index("new_finish"):
            assert service.evaluate("loads()") == []
    if sequence == "switch":
        finish(service, middle)
    assert_latest_load(service)


@pytest.mark.parametrize("old_ok", [False, True])
def test_old_completion_cannot_consume_the_new_results_waiting_for_exit(
    service, old_ok
):
    old = start(service)
    service.call("quitPlayer")
    new = start(service)
    record(service, old, 100000)
    record(service, new, 200000)
    finish(service, old, old_ok)
    assert service.evaluate("loads()") == []
    finish(service, new)
    assert_latest_load(service)


@pytest.mark.parametrize("next_ok", [False, True])
def test_old_failure_after_new_success_cannot_poison_another_replay(service, next_ok):
    old = start(service)
    service.call("quitPlayer")
    new = start(service)
    record(service, new, 200000)
    finish(service, new)
    next_read = start(service)
    record(service, next_read, 400000)
    finish(service, old, False)
    assert len(service.evaluate("loads()")) == 1
    finish(service, next_read, next_ok)
    assert service.evaluate("playRequest.startSec") == (400 if next_ok else 42)


@pytest.mark.parametrize("boundary", ["before_record", "after_record"])
@pytest.mark.parametrize("new_play", [False, True])
def test_removal_invalidates_resume_even_if_same_book_is_played_again(
    service, boundary, new_play
):
    old = start(service)
    if boundary == "after_record":
        record(service, old, 100000)
    assert service.call("removeBook", A) == "ok"
    assert A not in service.call("busyAsins")
    if new_play:
        new = start(service)
        record(service, new, 200000)
    if boundary == "before_record":
        record(service, old, 100000)
    finish(service, old)
    assert service.evaluate("loads()") == []
    if new_play:
        finish(service, new)
        assert_latest_load(service)


@pytest.mark.parametrize("supersede", ["note_same", "note_other", "explicit_start"])
def test_other_play_intents_invalidate_resume(service, supersede):
    old = start(service)
    if supersede == "explicit_start":
        service.call("playBook", A, 7)
    else:
        service.call("noteIntent", A if supersede == "note_same" else B)
    record(service, old, 100000)
    finish(service, old)
    if supersede == "explicit_start":
        assert_latest_load(service, 7)
    else:
        assert service.evaluate("loads()") == []


@pytest.mark.parametrize(
    "fallback", ["failure", "no_record", "missing_item", "refused"]
)
def test_latest_resume_keeps_defined_cached_fallback(service, fallback):
    old = start(service)
    service.call("quitPlayer")
    record(service, old, 100000)
    if fallback == "refused":
        service.evaluate("refuseRead = true")
        service.call("playBook", A, -1)
    else:
        new = start(service)
        if fallback == "failure":
            record(service, new, 200000)
        elif fallback == "missing_item":
            service.call("onEvent", {"type": "positions", "items": {}}, new)
        finish(service, new, fallback != "failure")
    finish(service, old)
    assert_latest_load(service, 42)


def test_a_new_resume_supersedes_pending_play_info(service):
    service.call("playBook", A, 7)
    old_load = service.evaluate("loads()[0]")
    start(service, B)
    service.call(
        "onEvent",
        {"type": "play_info", "path": f"/invented/books/{A}/book.m4b"},
        old_load,
    )
    assert service.evaluate("plays") == []


def test_new_resume_still_merges_newer_local_position(service):
    service.evaluate(
        "store.doc.books.B0FAKE0002 = {ms:250000,updated_at:'2027-01-15T13:00:00Z'}"
    )
    job = start(service)
    record(service, job, 200000)
    finish(service, job)
    assert_latest_load(service, 250)


@pytest.mark.parametrize("order", list(permutations((0, 1, 2))))
def test_a_b_a_all_three_completion_orders(service, order):
    jobs = [start(service), start(service, B), start(service)]
    for job, ms in zip(jobs, (100000, 300000, 200000), strict=True):
        record(service, job, ms)
    for index in order:
        finish(service, jobs[index])
        if 2 not in order[: order.index(index) + 1]:
            assert service.evaluate("loads()") == []
    assert_latest_load(service)


def test_stop_without_replay_does_not_restart_on_delayed_resume(service):
    job = start(service)
    service.call("quitPlayer")
    record(service, job, 100000)
    finish(service, job)
    assert service.evaluate("loads()") == []
    assert A not in service.call("busyAsins")


def test_removal_of_other_book_leaves_latest_resume_valid(service):
    job = start(service)
    service.call("removeBook", B)
    record(service, job, 200000)
    finish(service, job)
    assert_latest_load(service)


@pytest.mark.parametrize("purpose", ["catchup", "push-read", "resume"])
def test_unrelated_position_reads_cannot_replace_resume_result(service, purpose):
    job = start(service)
    record(service, job, 200000)
    unrelated = {"command": "position-get", "args": [A], "purpose": purpose}
    record(service, unrelated, 100000)
    finish(service, unrelated)
    assert service.evaluate("loads()") == []
    finish(service, job)
    assert_latest_load(service)

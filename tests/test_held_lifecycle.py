"""S01/S03/S04: real service callbacks with synthetic process/timer boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_p8_service import function_body

import qjs

REPO = Path(__file__).resolve().parents[1]
A = "B0FAKE0002"
B = "B0FAKE0003"
UNTIL = "2027-01-15T16:00:00Z"


@pytest.fixture
def service():
    module = qjs.load("Held")
    for name in (
        "Held",
        "JobQueue",
        "Signin",
        "Onboarding",
        "LibraryUi",
        "Playback",
        "PlayRequest",
    ):
        path = REPO / "qml/lib" / f"{name}.js"
        source, imports = qjs._resolve_imports(
            qjs._strip_pragma(path.read_text()), path
        )
        module._check(module._engine.evaluate(qjs._wrap(name, source, imports)), name)
    source = (REPO / "Service.qml").read_text()
    for name in (
        "run",
        "applyHeld",
        "runHeldEffect",
        "schedulePauseWake",
        "onPauseElapsed",
        "holdRefusedDownloads",
        "refusedUntil",
        "cancelDownload",
        "beginDisconnect",
        "finishDisconnect",
        "downloadsConnected",
        "jobAllowed",
        "statusCurrent",
        "acceptStatus",
        "requestStatus",
        "invalidateStatus",
        "finishStatus",
    ):
        if f"function {name}(" in source:
            module._check(module._engine.evaluate(function_body(source, name)), name)
    # Execute the product's signal bodies too, rather than copying their decisions.
    for signal, args in (("onEvent", "record, job"), ("onJobFinished", "job, outcome")):
        start = source.index(f"    {signal}: function(")
        body = function_body(
            source[start:].replace(f"{signal}: function", "function callback", 1),
            "callback",
        )
        module._check(
            module._engine.evaluate(body.replace("callback", signal, 1)), args
        )
    signin = (REPO / "qml/SigninFlow.qml").read_text()
    for name in ("disconnect", "onboardingFinished"):
        module._check(module._engine.evaluate(function_body(signin, name)), name)
    module.evaluate(
        """(function() {
var root = this;
this.root = root; this.service = root;
this.NOW = Date.parse('2027-01-15T12:00:00Z');
Date.now = function() { return root.NOW; };
this.held = Held.create(); this.commands = []; this.logs = [];
this.flagKnown = true; this.status = {authenticated:true}; this.statusAtMs = NOW;
this.downloadLifecycle = 0; this.downloadsDisconnected = false;
this.statusRequest = ''; this.statusSerial = 0; this.statusRefreshNeeded = false;
this.statusAgain = false;
this.statusRetryMs = 30000;
Object.defineProperty(this, 'downloadsPausedUntil', {get:function(){return Held.until(held);}});
Object.defineProperty(this, 'downloadsPaused', {get:function(){return Held.paused(held,statusAtMs);}});
function timer() {return {running:false,interval:0,
  stop:function(){this.running=false;},restart:function(){this.running=true;}};}
this.pauseTimer = timer(); this.statusRetryTimer = timer();
this.runner = {
  queue:JobQueue.create(), pendingJobs:[], activeJob:null,
  sync:function(){this.pendingJobs=this.queue.pending.slice();this.activeJob=this.queue.active;},
  run:function(c,a,p){
    commands.push({command:c,args:a,purpose:p||''});
    if(JobQueue.isJobCommand(c)) {var j=JobQueue.enqueue(this.queue,{command:c,args:a});j.purpose=p||'';this.sync();}
  },
  cancel:function(a){var out=JobQueue.cancel(this.queue,a);
    if(out.action==='send_cancel') run('cancel',[a]);this.sync();return out.action;}
};
this.library = {rowFor:function(a){return {asin:a,state:'downloading'};},localBooks:[]};
this.removals = {jobAllowed:function(){return true;}};
this.booksAckState = {}; this.settingsReceived = false;
this.BooksLocation = {ackStep:function(s){return {state:s};}};
this.EventLog = {summarize:function(){return '';}};
this.confirmAsin = ''; this.failures = {}; this.resumeRemotes = {};
this.sync = {handleEvent:function(){},handleFinished:function(){}};
this.catchupFlow = {handleEvent:function(){},handleFinished:function(){}};
this.signinFlow = {handleEvent:function(){},handleFinished:function(j,o){
  if(Signin.isOnboardingCommand(j.command)) onboardingFinished(j,o);
}};
this.clipboardNotice = ''; this.reconnecting = false; this.authFailed = false;
this.onboardingError = null; this.loginSession = '';
this.logEvent = function(c,t){logs.push([c,t]);};
this.refreshCatalogAge = function(){}; this.refreshLocal = function(){};
this.downloadActive = function(){return false;};
this.checkStatus = function(){run('status',[]);};
this.startSync = function(p){run('sync',[],p);};
this.clearPaste = function(){};
})()"""
    )
    return module


def hold_and_queue(service):
    service.call("applyHeld", {"type": "hold", "asins": [A, B], "until": UNTIL})
    service.call("run", "get", ["B0FAKE0004"], "download")
    service.call("run", "remove", ["B0FAKE0005"], "user")


def status_event(service, job, authenticated=True, until=None):
    service.call(
        "onEvent",
        {
            "type": "status",
            "authenticated": authenticated,
            "downloads_paused_until": until,
        },
        job,
    )


@pytest.mark.parametrize("stale_until", [None, UNTIL])
def test_disconnect_drops_waiting_downloads_and_ignores_old_status(
    service, stale_until
):
    hold_and_queue(service)
    service.call("run", "status", [])
    old = service.evaluate("commands[commands.length-1]")
    assert service.call("disconnect") == "ok"
    assert service.evaluate("held.asins") == []
    assert (
        service.evaluate(
            "runner.pendingJobs.filter(function(j){return j.command==='get';})"
        )
        == []
    )
    assert (
        service.evaluate(
            "runner.pendingJobs.some(function(j){return j.command==='remove';})"
        )
        is True
    )
    before = service.evaluate("commands.length")
    status_event(service, old, until=stale_until)
    assert service.evaluate("commands.length") == before
    assert service.evaluate("held") == {"asins": [], "until": ""}
    assert service.evaluate("pauseTimer.running") is False


@pytest.mark.parametrize("old_authenticated", [False, True])
def test_delayed_logout_status_cannot_overwrite_reconnected_lifecycle(
    service, old_authenticated
):
    hold_and_queue(service)
    service.call("disconnect")
    service.call("onboardingFinished", {"command": "logout"}, {"ok": True})
    logout_status = service.evaluate("commands[commands.length-1]")
    status_event(service, logout_status, authenticated=False)
    assert service.evaluate("held.asins") == []
    service.call("onboardingFinished", {"command": "login-finish"}, {"ok": True})
    new_status = service.evaluate("commands[commands.length-1]")
    status_event(service, new_status, authenticated=True, until=UNTIL)
    service.call("applyHeld", {"type": "hold", "asins": [A], "until": UNTIL})
    before = service.evaluate("commands.length")
    status_event(service, logout_status, authenticated=old_authenticated)
    assert service.evaluate("status.authenticated") is True
    assert service.evaluate("held.asins") == [A]
    assert service.evaluate("commands.length") == before


def test_disconnect_blocks_expiry_and_inflight_throttled_reholding(service):
    hold_and_queue(service)
    service.call("disconnect")
    service.call(
        "holdRefusedDownloads",
        {"command": "get", "asin": A},
        {"terminal": {"until": UNTIL}},
    )
    service.evaluate("NOW = Date.parse('2027-01-16T12:00:00Z')")
    service.call("onPauseElapsed")
    assert service.evaluate("held.asins") == []
    assert service.call("run", "get", [A], "download") is False
    if "function jobAllowed(" in (REPO / "Service.qml").read_text():
        assert service.call("jobAllowed", {"command": "get", "asin": A}) is False


def test_signed_out_status_does_not_release_waiting_books(service):
    service.call("applyHeld", {"type": "hold", "asins": [A, B], "until": UNTIL})
    service.call("run", "status", [])
    job = service.evaluate("commands[commands.length-1]")
    before = service.evaluate("commands.length")
    status_event(service, job, authenticated=False)
    assert service.evaluate("commands.length") == before
    assert service.evaluate("held.asins") == []


def test_cooldown_still_releases_in_order_when_connected(service):
    service.call("applyHeld", {"type": "hold", "asins": [A, B], "until": UNTIL})
    service.call("run", "status", [])
    job = service.evaluate("commands[commands.length-1]")
    status_event(service, job)
    gets = service.evaluate("commands.filter(function(j){return j.command==='get';})")
    assert [j["args"][0] for j in gets] == [A, B]


def test_failed_logout_does_not_restore_dropped_intents(service):
    hold_and_queue(service)
    service.call("disconnect")
    service.call(
        "onboardingFinished", {"command": "logout"}, {"ok": False, "code": "network"}
    )
    assert service.evaluate("held.asins") == []
    assert service.call("run", "get", [A], "download") is False


def test_service_uses_lifecycle_gate_for_queued_gets():
    source = (REPO / "Service.qml").read_text()
    assert "gate: root.jobAllowed" in source

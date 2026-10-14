"""Read-only QJSEngine probes of source-extracted Service/Signin callbacks.
No backend processes, sockets, user-data files, credentials or live shell are used.
Run with the inspected clone's .venv/bin/python and PYTHONDONTWRITEBYTECODE=1.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tests"))
from test_p8_service import function_body

import qjs

m = qjs.load("Held")


def ev(s):
    v = m._engine.evaluate(s)
    m._check(v, s)
    return v


for lib in (
    "Held",
    "JobQueue",
    "Signin",
    "Onboarding",
    "Positions",
    "Playback",
    "LibraryUi",
):
    p = REPO / "qml/lib" / (lib + ".js")
    src, nested = qjs._resolve_imports(qjs._strip_pragma(p.read_text()), p)
    ev(qjs._wrap(lib, src, nested))

source = (REPO / "Service.qml").read_text()
for name in (
    "applyHeld",
    "runHeldEffect",
    "schedulePauseWake",
    "onPauseElapsed",
    "holdRefusedDownloads",
    "refusedUntil",
    "cancelDownload",
    "playBook",
    "finishResume",
):
    ev(function_body(source, name))

ev("""
var root = this;
var NOW = Date.parse('2027-01-15T12:00:00Z');
Date.now = function() { return NOW; };
var held, commands, logs, pauseTimer, statusAtMs, status, flagKnown = true;
var downloadsPausedUntil = '';
var library = {rowFor: function(a) {return {asin:a,state:'downloading'};}};
var runner = {
  queue: JobQueue.create(), pendingJobs: [],
  sync: function() {this.pendingJobs=this.queue.pending.slice();},
  cancel: function(a) {
    var out=JobQueue.cancel(this.queue,a);
    if(out.action==='send_cancel') run('cancel',[a]);
    this.sync(); return out.action;
  }
};
function run(c,a,p) {commands.push({command:c,args:a,purpose:p||''});return true;}
function logEvent(c,t) {logs.push([c,t]);}
function reset() {
  held=Held.create(); commands=[]; logs=[]; statusAtMs=NOW; status={authenticated:true};
  pauseTimer={running:false,interval:0,stop:function(){this.running=false;},restart:function(){this.running=true;}};
  runner.queue=JobQueue.create();runner.sync();
}
var service = root;
var clipboardNotice='', reconnecting=false, authFailed=false, onboardingError=null,loginSession='';
function checkStatus() {run('status',[]);}
function startSync(p) {run('sync',[],p);}
""")
ev(function_body((REPO / "qml/SigninFlow.qml").read_text(), "onboardingFinished"))


def output(name, expression):
    print(name + ": " + json.dumps(m.evaluate(expression), sort_keys=True))


# Actual successful logout callback, then the status-event block's Held input.
ev("""reset();
applyHeld({type:Held.EVENT_THROTTLED,asin:'B0FAKE0002',queued:['B0FAKE0003'],until:'2027-01-15T16:00:00Z'});
onboardingFinished({command:'logout'}, {ok:true});
status={authenticated:false, downloads_paused_until:null};
applyHeld({type:Held.EVENT_STATUS,until:status.downloads_paused_until,now:Date.now()});
""")
output("logout_releases_gets", "({status:status,held:held,commands:commands})")
assert [x["command"] for x in m.evaluate("commands")] == ["status", "get", "get"]

# Restart loses held list by contract; cancelling its last book has same state.
# The status subprocess failing emits no status event; repeat timer manually.
ev("""reset();
applyHeld({type:Held.EVENT_STATUS,until:'2027-01-15T12:00:01Z',now:NOW});
NOW+=2000;
for(var i=0;i<3;i++){onPauseElapsed();NOW+=1000;}
""")
output(
    "empty_deadline_status_failure",
    "({held:held,commands:commands,timerRunning:pauseTimer.running,nextWakeMs:pauseTimer.interval,bannerPaused:Held.paused(held,statusAtMs)})",
)
assert m.evaluate(
    "pauseTimer.running && pauseTimer.interval===1000 && commands.length===3"
)

# Cancel requested on active download. It subsequently exits throttled instead
# of cancelled (e.g. denial already produced; cancel says not_running).
ev("""reset();
JobQueue.enqueue(runner.queue,{command:'get',args:['B0FAKE0002']});
var job=JobQueue.take(runner.queue);runner.sync();
var cancelResult=cancelDownload('B0FAKE0002');
JobQueue.complete(runner.queue,{ok:false,code:'throttled'});runner.sync();
holdRefusedDownloads(job,{ok:false,code:'throttled',terminal:{until:'2027-01-15T16:00:00Z'}});
""")
output(
    "cancel_then_throttled", "({cancelResult:cancelResult,held:held,commands:commands})"
)
assert m.evaluate("Held.has(held,'B0FAKE0002')")

# Two independent resume reads for the same book, separated by Stop/new play:
# finishResume identifies only ASIN, unlike serialised PlayRequest.
ev("""reset();
var booksDir='/invented/books',pendingResume='',store={loaded:true,doc:{books:{}}};
var plays=[];
function playNow(a,s){plays.push({asin:a,start:s});return 'ok';}
function cachedStartSec(a){return 0;}
playBook('B0FAKE0002',-1);
pendingResume=''; // quitPlayer clears the previous intent, not the running read
playBook('B0FAKE0002',-1);
finishResume('B0FAKE0002',{ms:100000,updated_at:'2027-01-15T11:00:00Z'});
finishResume('B0FAKE0002',{ms:200000,updated_at:'2027-01-15T11:59:00Z'});
""")
output(
    "older_resume_wins_after_stop_and_retry",
    "({plays:plays,pendingResume:pendingResume,commands:commands})",
)
assert m.evaluate("plays.length===1 && plays[0].start===100")
print("All four observed-bug assertions reproduced (this is not a product test PASS).")

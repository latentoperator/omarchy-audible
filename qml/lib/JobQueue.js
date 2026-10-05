.pragma library

// Job queue for the backend commands (ARCHITECTURE 4.8).
//
// `JobRunner.qml` spawns one backend process at a time. The job commands take
// the backend's exclusive lock, so a second one started while the first runs
// exits with `error(code=busy)`. This queue runs the job commands one at a
// time in FIFO order, retries the busy case exactly once after a delay the
// caller supplies, and lets every non-job command bypass the queue entirely
// (`isJobCommand` is the caller's check before it spawns).
//
// This is a pure state machine: it never spawns anything and never waits. The
// caller drives it — `create`, `enqueue`, `take`, `complete` — and switches on
// the `action` the returned object carries. `cancel` decides whether the caller
// drops a queued download or sends `cancel <asin>` to the running one.
//
// Pure ECMAScript for the Qt JS engine: no imports, no Qt types, and nothing
// here throws on bad input.

// The commands that take the backend job lock (§4.8), in the backend's order.
var JOB_COMMANDS = ["setup", "sync", "get", "remove", "login-finish", "login-import-cli", "logout"];

// Actions returned by `complete` and `cancel`.
var ACTION_OK = "ok";
var ACTION_FAIL = "fail";
var ACTION_RETRY = "retry";
var ACTION_IDLE = "idle";
var CANCEL_DROPPED = "dropped";
var CANCEL_SEND = "send_cancel";
var CANCEL_NONE = "none";

// How long the caller should wait before taking a re-queued busy job, unless
// it passes its own `busyDelayMs` to `create`.
var DEFAULT_BUSY_DELAY_MS = 1500;

function isJobCommand(command) {
  return JOB_COMMANDS.indexOf(command) !== -1;
}

// A fresh queue. `options.busyDelayMs` is the retry delay the caller wants.
function create(options) {
  var delay = DEFAULT_BUSY_DELAY_MS;
  if (!isNull(options) && typeof options.busyDelayMs === "number" && options.busyDelayMs >= 0) {
    delay = options.busyDelayMs;
  }
  return { "pending": [], "active": null, "busyDelayMs": delay };
}

// Queue a job command. Non-job commands bypass the queue: they return null and
// leave the queue untouched.
function enqueue(state, job) {
  if (isNull(state) || isNull(job) || !isJobCommand(job.command)) {
    return null;
  }
  var queued = {
    "command": job.command,
    "args": Array.isArray(job.args) ? job.args.slice() : [],
    "asin": jobAsin(job),
    "retried": job.retried === true
  };
  state.pending.push(queued);
  return queued;
}

// The next job to run, or null when one is already active or nothing is queued.
function take(state) {
  if (isNull(state) || !isNull(state.active) || state.pending.length === 0) {
    return null;
  }
  state.active = state.pending.shift();
  return state.active;
}

// Report the outcome of the active job. A `busy` outcome goes back to the head
// of the queue once; a second busy fails instead of looping forever.
function complete(state, result) {
  if (isNull(state) || isNull(state.active)) {
    return action(ACTION_IDLE, null, 0, result);
  }
  var job = state.active;
  state.active = null;
  if (!isNull(result) && result.busy === true) {
    if (job.retried !== true) {
      job.retried = true;
      state.pending.unshift(job);
      return action(ACTION_RETRY, job, state.busyDelayMs, result);
    }
    return action(ACTION_FAIL, job, 0, result);
  }
  if (!isNull(result) && result.ok === true) {
    return action(ACTION_OK, job, 0, result);
  }
  return action(ACTION_FAIL, job, 0, result);
}

// `cancel <asin>`: drop a queued `get`, or tell the caller to send the cancel
// command when that `get` is the running one. Other commands are never touched.
function cancel(state, asin) {
  if (isNull(state) || typeof asin !== "string" || asin.length === 0) {
    return action(CANCEL_NONE, null, 0, null);
  }
  if (!isNull(state.active) && state.active.command === "get" && state.active.asin === asin) {
    return action(CANCEL_SEND, state.active, 0, null);
  }
  for (var index = 0; index < state.pending.length; index++) {
    var job = state.pending[index];
    if (job.command === "get" && job.asin === asin) {
      state.pending.splice(index, 1);
      return action(CANCEL_DROPPED, job, 0, null);
    }
  }
  return action(CANCEL_NONE, null, 0, null);
}

// Pending plus active, for the caller's UI.
function size(state) {
  if (isNull(state)) {
    return 0;
  }
  return state.pending.length + (isNull(state.active) ? 0 : 1);
}

// The ASIN a job is keyed by. `get` may carry it explicitly or as its first
// positional argument, past any flags (only `--fake-fail` takes a value).
function jobAsin(job) {
  if (typeof job.asin === "string" && job.asin.length > 0) {
    return job.asin;
  }
  if (job.command !== "get" || !Array.isArray(job.args)) {
    return null;
  }
  var skipValue = false;
  for (var index = 0; index < job.args.length; index++) {
    var token = job.args[index];
    if (typeof token !== "string" || token.length === 0) {
      continue;
    }
    if (skipValue) {
      skipValue = false;
      continue;
    }
    if (token === "--fake-fail") {
      skipValue = true;
      continue;
    }
    if (token.charAt(0) === "-") {
      continue;
    }
    return token;
  }
  return null;
}

function action(name, job, delayMs, result) {
  return { "action": name, "job": job, "delayMs": delayMs, "result": result };
}

function isNull(value) {
  return value === null || value === undefined;
}

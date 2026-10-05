.pragma library

// Small pure helpers between the player, the job runner and `state.json`
// (ARCHITECTURE 3, 4.8, 5.2). `Library.js` owns the state schema and the row
// logic; this file holds the pieces that feed it: which book a path is, how a
// position is recorded, and which jobs the library should show.
//
// Pure ECMAScript for the Qt JS engine: no imports, no Qt types, and nothing
// here throws on bad input.

// The ASIN of the book mpv has loaded: the directory above `book.m4b`.
// Returns "" for anything else.
function asinFromPath(path) {
  if (typeof path !== "string") {
    return "";
  }
  var match = /\/([A-Za-z0-9]+)\/book\.m4b$/.exec(path);
  return match === null ? "" : match[1];
}

// JSON.parse that returns `fallback` for empty or malformed text.
function parseJson(text, fallback) {
  if (typeof text !== "string" || text.length === 0) {
    return fallback;
  }
  try {
    var value = JSON.parse(text);
    return value === null || value === undefined ? fallback : value;
  } catch (error) {
    return fallback;
  }
}

// A copy of `state` with the book's local position recorded: `ms`, the write
// time, the last-played time, and `played_since_download` (which is what lets
// the position be pushed). The finished flag is kept. A bad ASIN or position
// returns `state` unchanged.
function recordPosition(state, asin, ms, nowIso) {
  if (typeof asin !== "string" || asin.length === 0 || typeof ms !== "number" || !isFinite(ms) || ms < 0) {
    return state;
  }
  var next = {};
  for (var key in state) {
    next[key] = state[key];
  }
  var books = {};
  var current = isObject(state) && isObject(state.books) ? state.books : {};
  for (var name in current) {
    books[name] = current[name];
  }
  var previous = isObject(books[asin]) ? books[asin] : {};
  books[asin] = {
    "ms": Math.round(ms),
    "updated_at": nowIso,
    "last_played_at": nowIso,
    "played_since_download": true,
    "finished": previous.finished === true
  };
  next.books = books;
  return next;
}

// The failure map after a job ends: a failed `get` is remembered by ASIN with
// its message, a successful one clears it. Other commands change nothing.
function updateFailures(failures, job, outcome) {
  var next = {};
  var current = isObject(failures) ? failures : {};
  for (var key in current) {
    next[key] = current[key];
  }
  if (!isObject(job) || job.command !== "get" || typeof job.asin !== "string" || job.asin.length === 0) {
    return next;
  }
  if (isObject(outcome) && outcome.ok === true) {
    delete next[job.asin];
  } else {
    var message = isObject(outcome) && typeof outcome.message === "string" ? outcome.message : "download failed";
    next[job.asin] = message;
  }
  return next;
}

// The job entries `Library.buildRows` takes: queued `get`s, the running one
// (converting once its progress says so), and remembered failures. A book that
// is queued or running is not shown as failed, so a retry clears the error.
function jobStates(pending, active, progress, failures) {
  var entries = [];
  var busy = {};
  var queued = Array.isArray(pending) ? pending : [];
  for (var index = 0; index < queued.length; index++) {
    var job = queued[index];
    if (isGet(job)) {
      busy[job.asin] = true;
      entries.push({ "asin": job.asin, "state": "queued" });
    }
  }
  if (isGet(active)) {
    busy[active.asin] = true;
    var converting = isObject(progress) && progress.stage === "convert";
    entries.push({ "asin": active.asin, "state": converting ? "converting" : "downloading" });
  }
  var failed = isObject(failures) ? failures : {};
  for (var asin in failed) {
    if (busy[asin] !== true) {
      entries.push({ "asin": asin, "state": "error", "message": failed[asin] });
    }
  }
  return entries;
}

function isGet(job) {
  return isObject(job) && job.command === "get" && typeof job.asin === "string" && job.asin.length > 0;
}

function isObject(value) {
  return value !== null && value !== undefined && typeof value === "object" && !Array.isArray(value);
}

// A copy of `state` with the finished flag set for a book. A book with no
// entry yet gets one that has never been played, so nothing is pushed for it.
function markFinished(state, asin) {
  if (typeof asin !== "string" || asin.length === 0) {
    return state;
  }
  var next = {};
  for (var key in state) {
    next[key] = state[key];
  }
  var books = {};
  var current = isObject(state) && isObject(state.books) ? state.books : {};
  for (var name in current) {
    books[name] = current[name];
  }
  var previous = isObject(books[asin]) ? books[asin] : {};
  books[asin] = {
    "ms": typeof previous.ms === "number" ? previous.ms : 0,
    "updated_at": typeof previous.updated_at === "string" ? previous.updated_at : null,
    "last_played_at": typeof previous.last_played_at === "string" ? previous.last_played_at : null,
    "played_since_download": previous.played_since_download === true,
    "finished": true
  };
  next.books = books;
  return next;
}

// A copy of `state` with the push queue replaced.
function withQueue(state, queue) {
  var next = {};
  for (var key in state) {
    next[key] = state[key];
  }
  next.push_queue = Array.isArray(queue) ? queue : [];
  return next;
}

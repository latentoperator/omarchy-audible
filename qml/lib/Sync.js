.pragma library
.import "Positions.js" as Positions

// Queue helpers for position write-back (ARCHITECTURE 4.6). `Positions.js`
// decides what may be pushed (`shouldPush`, `enqueue`, `flushPlan`); this file
// holds the plain list handling around it. Pure ECMAScript for the Qt JS
// engine: no imports, no Qt types, and nothing here throws on bad input.

// The `position-get` call takes at most this many ASINs.
var BATCH_SIZE = 25;

// How many `stale` refusals in a row before the user is told (P6, F1). A
// single one is normal — another device listened; a run of them means this
// machine's position is not reaching Audible, most often because its clock is
// behind the server's.
var STALE_NOTICE_AFTER = 2;

// The offline retry (F18): a minute apart while no flush has failed, doubling
// with each failed flush in a row (two minutes after the first), and never
// more than half an hour apart.
var RETRY_BASE_MS = 60000;
var RETRY_CAP_MS = 1800000;

// How long to wait before the next flush after `failures` failed ones in a
// row. Zero or nonsense failures is the base delay.
function retryDelayMs(failures) {
  var count = typeof failures === "number" && isFinite(failures) && failures > 0 ? Math.floor(failures) : 0;
  // 2^5 already passes the cap; stop doubling there so nothing overflows.
  var delay = RETRY_BASE_MS * Math.pow(2, Math.min(count, 6));
  return Math.min(delay, RETRY_CAP_MS);
}

// The failure count after a flush ended with `result` (PositionSync.finish):
// "done" means it got through, anything else ("offline", a push error code,
// "refused") is one more failure.
function failuresAfter(failures, result) {
  var count = typeof failures === "number" && isFinite(failures) && failures > 0 ? Math.floor(failures) : 0;
  return result === "done" ? 0 : count + 1;
}

// Up to `max` distinct ASINs from the queue, oldest first.
function asinsOf(queue, max) {
  var limit = typeof max === "number" && max > 0 ? max : BATCH_SIZE;
  var asins = [];
  var items = Array.isArray(queue) ? queue : [];
  for (var index = 0; index < items.length && asins.length < limit; index++) {
    var entry = items[index];
    if (isObject(entry) && typeof entry.asin === "string" && asins.indexOf(entry.asin) === -1) {
      asins.push(entry.asin);
    }
  }
  return asins;
}

// A copy of the queue without the entries that have the same ASIN, ms and
// `at` as `entry`. A newer push for the same book (different ms or `at`) stays.
function removeEntry(queue, entry) {
  var items = Array.isArray(queue) ? queue : [];
  if (!isObject(entry)) {
    return items.slice();
  }
  return items.filter(function (item) {
    return !(isObject(item) && item.asin === entry.asin && item.ms === entry.ms && item.at === entry.at);
  });
}

// The `position-push` arguments for one entry: `<asin> <ms> [--at <iso>]`.
function pushArgs(entry) {
  var args = [String(entry.asin), String(Math.round(entry.ms))];
  if (typeof entry.at === "string" && entry.at.length > 0) {
    args.push("--at");
    args.push(entry.at);
  }
  return args;
}

// The entries of `send` whose ASIN was part of the batch that was just read.
// Anything else has not had its remote position re-read, so it waits.
function sendable(send, requestedAsins) {
  var list = Array.isArray(send) ? send : [];
  var asins = Array.isArray(requestedAsins) ? requestedAsins : [];
  return list.filter(function (entry) {
    return isObject(entry) && asins.indexOf(entry.asin) !== -1;
  });
}

function isObject(value) {
  return value !== null && value !== undefined && typeof value === "object" && !Array.isArray(value);
}

// The run of `stale` refusals after one push finishes (P6). A push that went
// through ends the run; a `stale` one adds to it; any other outcome (offline,
// refused, an error) says nothing about the clock and leaves it as it was.
function staleCountAfter(count, outcome) {
  var current = typeof count === "number" && isFinite(count) && count > 0 ? Math.floor(count) : 0;
  if (!isObject(outcome)) return current;
  if (outcome.ok === true) return 0;
  if (outcome.code === "stale") return current + 1;
  return current;
}

// The Mini line to show after a run of refused pushes, or "" when there is
// nothing to say. A single `stale` is ordinary; two or more in a row mean the
// position is not getting through and the usual cause is this computer's clock
// (F1). Pure: a missing, negative or nonsense count says nothing.
function staleNotice(consecutiveStale) {
  var count =
    typeof consecutiveStale === "number" && isFinite(consecutiveStale) ? consecutiveStale : 0;
  if (count < STALE_NOTICE_AFTER) return "";
  return "Your position isn't reaching Audible. Check this computer's clock.";
}

// PositionSync's flush/position-get/position-push sequence. The caller owns
// this plain state and applies the returned effects; this reducer never runs
// a process, writes the queue, schedules work, or throws on bad input.
function createState() {
  return {
    "flushing": false,
    "lastResult": "",
    "failedFlushes": 0,
    "staleCount": 0,
    "lastPushed": {},
    "requested": [],
    "plan": [],
    "current": null,
    "progressed": false
  };
}

// Events: flush(queue), positions(queue, items, purpose), finished(job, outcome,
// queue), refused(purpose, queue), reset_retry, and deferred_flush(queue).
// Effects: run(command, args, purpose), setQueue(queue), flush_later, and
// finish(result). `Positions.flushPlan` remains the authority for drop/send.
function step(state, event) {
  var current = _sync.cleanState(state);
  if (!_sync.isObject(event)) return _sync.result(current, []);
  var type = event.type;
  if (type === "reset_retry") {
    current.failedFlushes = 0;
    return _sync.result(current, []);
  }
  if (type === "flush") {
    var queue = _sync.list(event.queue);
    if (current.flushing || queue.length === 0) return _sync.result(current, []);
    current.requested = asinsOf(queue, BATCH_SIZE);
    current.plan = [];
    current.current = null;
    current.progressed = false;
    current.flushing = true;
    return _sync.result(current, [{ "type": "run", "command": "position-get", "args": current.requested.slice(), "purpose": "flush" }]);
  }
  if (type === "positions" && event.purpose === "flush" && current.flushing) {
    var positionQueue = _sync.list(event.queue);
    var split = Positions.flushPlan(positionQueue, event.items);
    var next = positionQueue;
    for (var d = 0; d < split.drop.length; d++) {
      next = removeEntry(next, split.drop[d]);
      current.progressed = true;
    }
    var effects = [];
    if (split.drop.length > 0) effects.push({ "type": "setQueue", "queue": next });
    current.plan = sendable(split.send, current.requested);
    return _sync.result(current, effects);
  }
  if (type === "finished" && _sync.isObject(event.job) && event.job.purpose === "flush" && current.flushing) {
    if (!_sync.isObject(event.outcome) || event.outcome.ok !== true) {
      return _sync.finish(current, event.queue, "offline");
    }
    return _sync.sendNext(current, event.queue);
  }
  if (type === "finished" && _sync.isObject(event.job) && event.job.purpose === "push" && current.flushing) {
    var entry = current.current;
    current.current = null;
    current.staleCount = staleCountAfter(current.staleCount, event.outcome);
    if (_sync.isObject(event.outcome) && (event.outcome.ok === true || event.outcome.code === "stale")) {
      var pushedQueue = removeEntry(_sync.list(event.queue), entry);
      var pushEffects = [{ "type": "setQueue", "queue": pushedQueue }];
      if (event.outcome.ok === true && _sync.isObject(entry)) {
        current.lastPushed[entry.asin] = entry.ms;
      }
      current.progressed = true;
      var nextSend = _sync.sendNext(current, pushedQueue);
      return _sync.result(nextSend.state, pushEffects.concat(nextSend.effects));
    }
    return _sync.finish(current, event.queue, String(_sync.isObject(event.outcome) && event.outcome.code ? event.outcome.code : "error"));
  }
  if (type === "refused" && current.flushing) {
    return _sync.finish(current, event.queue, "refused");
  }
  if (type === "deferred_flush") {
    var deferredQueue = _sync.list(event.queue);
    if (current.progressed && deferredQueue.length > 0) {
      return _sync.result(current, [{ "type": "flush_later" }]);
    }
  }
  return _sync.result(current, []);
}

var _sync = {};

_sync.isObject = function (value) {
  return value !== null && value !== undefined && typeof value === "object" && !Array.isArray(value);
};
_sync.list = function (value) { return Array.isArray(value) ? value : []; };
_sync.count = function (value) { return typeof value === "number" && isFinite(value) && value > 0 ? Math.floor(value) : 0; };
_sync.cleanState = function (state) {
  var base = createState();
  if (!_sync.isObject(state)) return base;
  base.flushing = state.flushing === true;
  base.lastResult = typeof state.lastResult === "string" ? state.lastResult : "";
  base.failedFlushes = _sync.count(state.failedFlushes);
  base.staleCount = _sync.count(state.staleCount);
  base.lastPushed = {};
  if (_sync.isObject(state.lastPushed)) {
    Object.keys(state.lastPushed).forEach(function (asin) { base.lastPushed[asin] = state.lastPushed[asin]; });
  }
  base.requested = _sync.list(state.requested).slice();
  base.plan = _sync.list(state.plan).slice();
  base.current = _sync.isObject(state.current) ? state.current : null;
  base.progressed = state.progressed === true;
  return base;
};
_sync.result = function (state, effects) { return { "state": state, "effects": effects }; };
_sync.finish = function (state, queue, result) {
  state.flushing = false;
  state.lastResult = result;
  state.failedFlushes = failuresAfter(state.failedFlushes, result);
  state.requested = [];
  state.plan = [];
  state.current = null;
  var effects = [{ "type": "finish", "result": result }];
  if (state.progressed && _sync.list(queue).length > 0) effects.push({ "type": "flush_later" });
  return _sync.result(state, effects);
};
_sync.sendNext = function (state, queue) {
  var plan = state.plan.slice();
  var items = _sync.list(queue);
  while (plan.length > 0) {
    var candidate = plan.shift();
    var stillQueued = items.some(function (entry) {
      return _sync.isObject(entry) && entry.asin === candidate.asin && entry.ms === candidate.ms && entry.at === candidate.at;
    });
    if (!stillQueued) {
      state.progressed = true;
      continue;
    }
    state.plan = plan;
    state.current = candidate;
    return _sync.result(state, [{ "type": "run", "command": "position-push", "args": pushArgs(candidate), "purpose": "push" }]);
  }
  state.plan = [];
  return _sync.finish(state, items, "done");
};

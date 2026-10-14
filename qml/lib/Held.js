.pragma library

// The held downloads: books Audible refused to license, waiting for the pause
// to pass (0.1.5, ARCHITECTURE 4.2, 4.8 and 5.3).
//
// A `get` that Audible answers with `throttled` is not a failure. The book
// waits instead, and so does every `get` still queued behind it, so the app
// stops making license requests until the pause is over. The service keeps
// that list here — in memory only, so a shell restart loses it and the
// backend's own pause is what stops it asking meanwhile — and this module owns
// the transitions: what to hold, what a cancel drops, and when the held books
// go back to the runner, in the order they were held.
//
// Pure ECMAScript for the Qt JS engine: no imports, no Qt types, and nothing
// here throws on bad input. `step` is the only thing that changes anything,
// and it never mutates the state it is handed.
//
// The public surface is the constants and the five functions below.

// `step` event types.
var EVENT_HOLD = "hold";
var EVENT_DROP = "drop";
var EVENT_STATUS = "status";
var EVENT_NOW = "now";
var EVENT_THROTTLED = "throttled";

// `step` effect kinds.
var EFFECT_RELEASE = "release";

var _p = {};

_p.isObject = function (value) {
  return value !== null && value !== undefined && typeof value === "object" && !Array.isArray(value);
};

_p.asin = function (value) {
  return typeof value === "string" && value.length > 0 ? value : "";
};

// A timestamp from an event: the trimmed string, or "" for anything else. A
// value that is not a real time is kept as it is — `paused` is what decides
// it means nothing, so a bad file can never hold downloads for good.
_p.until = function (value) {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : "";
};

_p.numberOrNull = function (value) {
  if (typeof value !== "number" || !isFinite(value)) {
    return null;
  }
  return value;
};

// The ASINs in a list, in order, without repeats and without empty entries.
_p.asins = function (value) {
  var out = [];
  var list = Array.isArray(value) ? value : [];
  for (var index = 0; index < list.length; index++) {
    var asin = _p.asin(list[index]);
    if (asin.length > 0 && out.indexOf(asin) === -1) {
      out.push(asin);
    }
  }
  return out;
};

// `list` plus `asins`, keeping the order and never repeating one.
_p.added = function (list, asins) {
  var out = list.slice();
  for (var index = 0; index < asins.length; index++) {
    if (out.indexOf(asins[index]) === -1) {
      out.push(asins[index]);
    }
  }
  return out;
};

// The held state as `{asins, until}`, from anything (a missing or broken value
// is an empty list).
_p.state = function (value) {
  if (!_p.isObject(value)) {
    return { "asins": [], "until": "" };
  }
  return { "asins": _p.asins(value.asins), "until": _p.until(value.until) };
};

_p.result = function (state, effects) {
  return { "state": state, "effects": effects === undefined ? [] : effects };
};

// The state after the pause's own deadline is applied: still held when the
// pause is running, released — once, in order — when it is not. The stale
// resume time goes with the release, so the banner goes too; the next
// `status` writes the real one.
_p.settled = function (state, now) {
  if (state.asins.length === 0 || paused(state, now)) {
    return _p.result(state);
  }
  return _p.result(
    { "asins": [], "until": "" },
    [{ "kind": EFFECT_RELEASE, "asins": state.asins }]
  );
};

// A fresh held list: nothing held, no pause.
function create() {
  return { "asins": [], "until": "" };
}

// Whether `state` holds `asin` — a book waiting for the pause to pass.
function has(state, asin) {
  return _p.state(state).asins.indexOf(_p.asin(asin)) !== -1;
}

// Whether downloads are paused as of `nowMs` (the engine clock when it is
// missing). An unknown or unusable `until` is not a pause: the download runs
// and Audible says no again if it must.
function paused(state, nowMs) {
  var until = _p.state(state).until;
  if (until.length === 0) {
    return false;
  }
  var deadline = Date.parse(until);
  if (isNaN(deadline)) {
    return false;
  }
  var now = _p.numberOrNull(nowMs);
  if (now === null) {
    now = Date.now();
  }
  return deadline > now;
}

// The recorded resume time, "" when there is none. The banner shows it only
// while `paused` is true.
function until(state) {
  return _p.state(state).until;
}

// How long until the pause ends, in whole ms, for the service's wake timer:
// at least a second, even for a deadline that has just gone by, and 0 when
// there is no usable deadline to wake for.
function wakeInMs(state, nowMs) {
  var until = _p.state(state).until;
  if (until.length === 0) {
    return 0;
  }
  var deadline = Date.parse(until);
  if (isNaN(deadline)) {
    return 0;
  }
  var now = _p.numberOrNull(nowMs);
  if (now === null) {
    now = Date.now();
  }
  return Math.max(1000, deadline - now + 1000);
}

// Whether two held states hold the same books in the same order with the same
// resume time. The service writes its property only when something changed,
// so a `status` that says nothing new does not rebuild the library rows.
function same(one, other) {
  var left = _p.state(one);
  var right = _p.state(other);
  if (left.until !== right.until || left.asins.length !== right.asins.length) {
    return false;
  }
  for (var index = 0; index < left.asins.length; index++) {
    if (left.asins[index] !== right.asins[index]) {
      return false;
    }
  }
  return true;
}

// The held list after `event`, as `{state, effects}`. `effects` is `[]` or one
// `{kind: "release", asins: [...]}` — the books to hand back to the runner, in
// the order they were held. An event this module does not know changes
// nothing.
//
//   {type: "hold", asins: [...], until: iso}   pick or confirm while paused
//   {type: "drop", asin: "…"}                  the held row's ✕
//   {type: "throttled", asin: "…", queued: […], until: iso}
//                                              Audible refused a license
//   {type: "status", until: iso|null, now: ms} the backend's pause, re-read
//   {type: "now", now: ms}                     the pause's own deadline
function step(state, event) {
  var current = _p.state(state);
  if (!_p.isObject(event)) {
    return _p.result(current);
  }
  var type = typeof event.type === "string" ? event.type : "";

  if (type === EVENT_HOLD) {
    return _p.result({
      "asins": _p.added(current.asins, _p.asins(event.asins)),
      "until": _p.until(event.until) === "" ? current.until : _p.until(event.until)
    });
  }

  if (type === EVENT_THROTTLED) {
    var refused = _p.asins([event.asin]);
    var next = {
      "asins": _p.added(_p.added(current.asins, refused), _p.asins(event.queued)),
      "until": _p.until(event.until) === "" ? current.until : _p.until(event.until)
    };
    return _p.result(next);
  }

  if (type === EVENT_DROP) {
    var asin = _p.asin(event.asin);
    var kept = [];
    for (var index = 0; index < current.asins.length; index++) {
      if (current.asins[index] !== asin) {
        kept.push(current.asins[index]);
      }
    }
    return _p.result({ "asins": kept, "until": current.until });
  }

  if (type === EVENT_STATUS) {
    // The backend's file is the authority on the pause; its absence means the
    // pause is over, which releases the held books.
    return _p.settled({ "asins": current.asins, "until": _p.until(event.until) }, event.now);
  }

  if (type === EVENT_NOW) {
    // The pause's deadline arrived while the status read is still in flight.
    return _p.settled({ "asins": current.asins, "until": current.until }, event.now);
  }

  return _p.result(current);
}

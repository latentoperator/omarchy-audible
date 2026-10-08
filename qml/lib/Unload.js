.pragma library
.import "Drawer.js" as Drawer

// Books waiting for the player to unload them before they are removed (F17,
// P9), and whether a queued removal may still run. `Removals.qml` holds the
// list and applies the effects `step` returns; it decides nothing itself.
//
// Pure ECMAScript for the Qt JS engine: no imports but `Drawer.js`, no Qt
// types, and nothing here throws on bad input.

// Who asked for a removal: the job purpose, and a pending entry's `purpose`.
// A loaded book's auto-remove waits for the unload too, and keeps saying it
// is an auto-remove after it (P8 nit 3): its job runs as AUTO_UNLOADED.
var PURPOSE_USER = "user";
var PURPOSE_AUTO = "autoremove";
var PURPOSE_AUTO_UNLOADED = "autoremove-unloaded";

// The ASINs waiting for the unload, in order.
function asins(pending) {
  var out = [];
  var list = Array.isArray(pending) ? pending : [];
  for (var i = 0; i < list.length; i++) {
    if (_p.isEntry(list[i])) out.push(list[i].asin);
  }
  return out;
}

// The next pending list and the effects of `event`:
//   {type: "add", asin, purpose}  a loaded book is to be removed once unloaded;
//                                 a user's Remove wins over a waiting auto one
//   {type: "intent", asin}        the user chose this book again: drop it
//   {type: "unloaded", busy, autoRemove}
//                                 the loaded book changed: remove every book
//                                 no longer busy (Drawer.removalAllowed); an
//                                 auto-remove whose setting is off by now is
//                                 dropped instead
//   {type: "timeout"}             the player never let go: give up on all
// Effects, applied in order: {type: "run", asin, purpose} (a `remove` job),
// {type: "log", text}, {type: "timer", on} (start or stop the unload timer).
function step(pending, event) {
  var list = _p.clean(pending);
  var type = event !== null && typeof event === "object" ? event.type : null;
  if (type === "add") {
    return _p.add(list, event.asin, event.purpose);
  }
  if (type === "intent") {
    var kept = list.filter(function (entry) { return entry.asin !== event.asin; });
    return { "pending": kept, "effects": kept.length === 0 ? [{ "type": "timer", "on": false }] : [] };
  }
  if (type === "unloaded") {
    return _p.unloaded(list, event.busy, event.autoRemove === true);
  }
  if (type === "timeout") {
    return {
      "pending": [],
      "effects": list.map(function (entry) {
        return { "type": "log", "text": "skipped " + entry.asin + ": the player did not unload it" };
      })
    };
  }
  return { "pending": list, "effects": [] };
}

// Whether a queued `remove` job may start now. A user's removal never runs
// for a book that is busy again; an auto-remove of a book still loaded needs
// the setting, the book at its end and playback stopped; one sent after the
// unload needs the setting and the book not busy, since `atEnd` is false once
// the book is unloaded. Any other job may run.
function jobAllowed(job, autoRemove, atEnd, playing, busy) {
  if (job === null || typeof job !== "object" || job.command !== "remove" || !Array.isArray(job.args)) {
    return true;
  }
  var asin = job.args[0];
  if (job.purpose === PURPOSE_USER) {
    return Drawer.removalAllowed(asin, busy);
  }
  if (job.purpose === PURPOSE_AUTO) {
    return autoRemove === true && atEnd === true && playing !== true;
  }
  if (job.purpose === PURPOSE_AUTO_UNLOADED) {
    return autoRemove === true && Drawer.removalAllowed(asin, busy);
  }
  return true;
}

var _p = {};

_p.isEntry = function (entry) {
  return entry !== null && typeof entry === "object" && typeof entry.asin === "string" && entry.asin.length > 0
    && (entry.purpose === PURPOSE_USER || entry.purpose === PURPOSE_AUTO);
};

_p.clean = function (pending) {
  return Array.isArray(pending) ? pending.filter(_p.isEntry) : [];
};

_p.add = function (list, asin, purpose) {
  var effects = [{ "type": "timer", "on": true }];
  var entry = { "asin": asin, "purpose": purpose };
  if (!_p.isEntry(entry)) {
    return { "pending": list, "effects": [] };
  }
  var next = [];
  var found = false;
  for (var i = 0; i < list.length; i++) {
    if (list[i].asin === asin) {
      found = true;
      next.push(purpose === PURPOSE_USER ? entry : list[i]);
    } else {
      next.push(list[i]);
    }
  }
  if (!found) next.push(entry);
  return { "pending": next, "effects": effects };
};

_p.unloaded = function (list, busy, autoRemove) {
  var ready = list.filter(function (entry) { return Drawer.removalAllowed(entry.asin, busy); });
  var kept = list.filter(function (entry) { return ready.indexOf(entry) < 0; });
  var effects = kept.length === 0 ? [{ "type": "timer", "on": false }] : [];
  ready.forEach(function (entry) {
    if (entry.purpose === PURPOSE_USER) {
      effects.push({ "type": "run", "asin": entry.asin, "purpose": PURPOSE_USER });
    } else if (autoRemove) {
      effects.push({ "type": "log", "text": "auto-remove " + entry.asin });
      effects.push({ "type": "run", "asin": entry.asin, "purpose": PURPOSE_AUTO_UNLOADED });
    } else {
      effects.push({ "type": "log", "text": "auto-remove of " + entry.asin + " cancelled: the setting is off" });
    }
  });
  return { "pending": kept, "effects": effects };
};

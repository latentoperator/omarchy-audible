.pragma library

// Position rules for the player service (ARCHITECTURE 4.6, PLAN P4a).
//
// This is the JS port of `backend/omarchy_audible/positions.py`: the timestamp
// parse, the newest-wins merge, and the push rules that decide what may be
// written back to Audible. `Library.js` has a private copy of the *parse* and
// *merge* helpers; this module is the public, tested port, and the shared
// vectors in `tests/fixtures/position-vectors.json` are asserted against the
// Python implementation and this file, so the two stay in step.
//
// Push rules (D4, G0): only positions produced by listening on this machine are
// pushed, and a queued push is dropped when the account's position moved past
// its local listening time.
//
// The book entry is the `state.json` book shape (ARCHITECTURE 3). `shouldPush`
// reads one extra key, `last_pushed_ms`: the position at the last successful
// push. `state.json` keeps unknown keys across a round trip, so the service can
// record it there without a schema change; a missing value means "never pushed".
//
// Pure ECMAScript for the Qt JS engine: no imports, no Qt types, and nothing
// here throws on bad input. Timestamps parse to integer epoch milliseconds;
// the documented grammar is the Audible `YYYY-MM-DD HH:MM:SS.f` form and ISO
// 8601 with a `Z` or an `HH:MM`/`HHMM` offset. Anything outside it is null.

// A position within this many milliseconds of the end counts as finished.
var FINISH_TRAILING_MS = 30000;

var _p = {};

_p.DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
_p.TIME_NO_SECONDS = /T\d{2}:\d{2}$/;
_p.OFFSET_NO_COLON = /([+-])(\d{2})(\d{2})$/;
_p.TZ_TAIL = /(z|[+-]\d{2}:?\d{2})$/i;
_p.DATE_PREFIX = /^(\d{4})-(\d{2})-(\d{2})/;
_p.TIME_PART = /[T ](\d{2}):(\d{2})(?::(\d{2}))?/;
_p.OFFSET_PART = /([+-])(\d{2}):(\d{2})$/;

// The keys a push_queue entry defines; unknown keys survive a round trip.
_p.QUEUE_KEYS = ["asin", "ms", "at"];

_p.isNull = function (value) {
  return value === null || value === undefined;
};

_p.isObject = function (value) {
  return !_p.isNull(value) && typeof value === "object" && !Array.isArray(value);
};

_p.trim = function (value) {
  return value.replace(/^\s+|\s+$/g, "");
};

_p.stringOrNull = function (value) {
  return typeof value === "string" && value.length > 0 ? value : null;
};

// A position in milliseconds: truncated and clamped at zero, or null when the
// value is not a finite number (mirrors `positions._clean`).
_p.positionMs = function (value) {
  if (typeof value !== "number" || !isFinite(value)) {
    return null;
  }
  var truncated = value < 0 ? Math.ceil(value) : Math.floor(value);
  return Math.max(0, truncated);
};

_p.daysInMonth = function (year, month) {
  var leap = (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
  var days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return days[month - 1];
};

// Mirror `datetime.fromisoformat`: reject a calendar date, a minute/second or
// an offset Python would reject. The JS `Date` engine rolls invalid days over
// (Feb 30 becomes Mar 2), so this check is what keeps garbage as null.
_p.validCalendar = function (text) {
  var date = _p.DATE_PREFIX.exec(text);
  if (date) {
    var year = Number(date[1]);
    var month = Number(date[2]);
    var day = Number(date[3]);
    if (month < 1 || month > 12) {
      return false;
    }
    if (day < 1 || day > _p.daysInMonth(year, month)) {
      return false;
    }
  }
  var time = _p.TIME_PART.exec(text);
  if (time) {
    if (Number(time[2]) > 59) {
      return false;
    }
    if (time[3] !== undefined && Number(time[3]) > 59) {
      return false;
    }
    if (Number(time[1]) > 23) {
      return false;
    }
  }
  var offset = _p.OFFSET_PART.exec(text);
  if (offset && (Number(offset[2]) > 23 || Number(offset[3]) > 59)) {
    return false;
  }
  return true;
};

_p.emptyEntry = function () {
  return { "ms": 0, "updated_at": null };
};

// One `{ms, updated_at}` entry, cleaned the way `positions._clean` does, or
// null when the value is not an entry at all.
_p.cleanEntry = function (entry) {
  if (!_p.isObject(entry)) {
    return null;
  }
  var ms = _p.positionMs(entry.ms);
  return {
    "ms": ms === null ? 0 : ms,
    "updated_at": _p.stringOrNull(entry.updated_at)
  };
};

_p.withExtras = function (target, source, known) {
  var keys = Object.keys(source).sort();
  for (var index = 0; index < keys.length; index++) {
    var key = keys[index];
    if (known.indexOf(key) === -1) {
      target[key] = source[key];
    }
  }
  return target;
};

// One push_queue entry, or null when it has no usable ASIN.
_p.cleanQueueEntry = function (entry) {
  if (!_p.isObject(entry)) {
    return null;
  }
  var asin = _p.stringOrNull(entry.asin);
  if (asin === null) {
    return null;
  }
  var ms = _p.positionMs(entry.ms);
  var out = {
    "asin": asin,
    "ms": ms === null ? 0 : ms,
    "at": _p.stringOrNull(entry.at)
  };
  return _p.withExtras(out, entry, _p.QUEUE_KEYS);
};

// Order two listening times; a missing one sorts as the oldest.
_p.compareAt = function (left, right) {
  var leftKey = parseUpdatedAt(left);
  var rightKey = parseUpdatedAt(right);
  if (leftKey === null && rightKey === null) {
    return 0;
  }
  if (leftKey === null) {
    return -1;
  }
  if (rightKey === null) {
    return 1;
  }
  return leftKey - rightKey;
};

// Parse a position timestamp into epoch milliseconds, or null when it is not a
// timestamp. Mirrors `positions.parse_updated_at`: the Audible no-timezone form
// is UTC, a trailing `Z`/`z` is UTC, and anything unparseable sorts as oldest.
function parseUpdatedAt(value) {
  if (typeof value !== "string") {
    return null;
  }
  var text = _p.trim(value);
  if (!text) {
    return null;
  }
  // Python replaces the first space with `T`, leaving the rest untouched.
  var space = text.indexOf(" ");
  if (space !== -1) {
    text = text.slice(0, space) + "T" + text.slice(space + 1);
  }
  if (_p.DATE_ONLY.test(text)) {
    text = text + "T00:00:00";
  } else if (_p.TIME_NO_SECONDS.test(text)) {
    text = text + ":00";
  }
  // `Date.parse` needs the colon Python accepts without one.
  var offset = _p.OFFSET_NO_COLON.exec(text);
  if (offset) {
    text = text.slice(0, offset.index) + offset[1] + offset[2] + ":" + offset[3];
  }
  var last = text.charAt(text.length - 1);
  if (last === "z" || last === "Z") {
    text = text.slice(0, text.length - 1) + "Z";
  }
  if (!_p.TZ_TAIL.test(text)) {
    text = text + "Z";
  }
  if (!_p.validCalendar(text)) {
    return null;
  }
  var parsed = Date.parse(text);
  return isNaN(parsed) ? null : parsed;
}

// Newest-wins merge of two position entries (ARCHITECTURE 4.6). A missing entry
// or timestamp loses, and an equal `updated_at` goes to the local entry.
// Returns a new object, never one of the inputs.
function merge(local, remote) {
  var localEntry = _p.cleanEntry(local);
  var remoteEntry = _p.cleanEntry(remote);
  if (localEntry === null) {
    return remoteEntry === null ? _p.emptyEntry() : remoteEntry;
  }
  if (remoteEntry === null) {
    return localEntry;
  }
  var localKey = parseUpdatedAt(localEntry.updated_at);
  var remoteKey = parseUpdatedAt(remoteEntry.updated_at);
  if (remoteKey === null) {
    return localEntry;
  }
  if (localKey === null) {
    return remoteEntry;
  }
  return remoteKey > localKey ? remoteEntry : localEntry;
}

// The position to resume from: the merged entry's milliseconds.
function resumeMs(local, remote) {
  return merge(local, remote).ms;
}

// True when this book's local position may be written back to the account: it
// was listened to on this machine (`played_since_download`), it has a real
// position, and that position moved since the last successful push.
function shouldPush(book) {
  if (!_p.isObject(book) || book.played_since_download !== true) {
    return false;
  }
  var ms = _p.positionMs(book.ms);
  if (ms === null || ms <= 0) {
    return false;
  }
  var pushed = _p.positionMs(book.last_pushed_ms);
  return pushed === null || pushed !== ms;
}

// Add a push to the queue, keeping at most one entry per ASIN: the one with the
// newest listening time (`at`) wins. The queue array is updated in place and
// returned; a non-array queue becomes a new one.
function enqueue(queue, item) {
  var items = Array.isArray(queue) ? queue : [];
  var entry = _p.cleanQueueEntry(item);
  if (entry === null) {
    return items;
  }
  for (var index = 0; index < items.length; index++) {
    if (_p.isObject(items[index]) && items[index].asin === entry.asin) {
      if (_p.compareAt(entry.at, items[index].at) > 0) {
        items[index] = entry;
      }
      return items;
    }
  }
  items.push(entry);
  return items;
}

// Split a push queue into what may be sent and what must be dropped: a queued
// push is stale when the account's position is newer than its `at` (4.6).
// `remoteNow` is the `positions` event's items map, `{asin: {ms, updated_at}}`.
function flushPlan(queue, remoteNow) {
  var items = Array.isArray(queue) ? queue : [];
  var remote = _p.isObject(remoteNow) ? remoteNow : {};
  var send = [];
  var drop = [];
  for (var index = 0; index < items.length; index++) {
    var entry = _p.cleanQueueEntry(items[index]);
    if (entry === null) {
      continue;
    }
    var at = parseUpdatedAt(entry.at);
    var remoteEntry = remote[entry.asin];
    var remoteKey = _p.isObject(remoteEntry) ? parseUpdatedAt(remoteEntry.updated_at) : null;
    if (at !== null && remoteKey !== null && remoteKey > at) {
      drop.push(entry);
    } else {
      send.push(entry);
    }
  }
  return { "send": send, "drop": drop };
}

// Finished when playback reached EOF or the position is within 30 s of the end.
function isFinished(posMs, durMs, eofReached) {
  if (eofReached === true) {
    return true;
  }
  var duration = _p.positionMs(durMs);
  if (duration === null || duration <= 0) {
    return false;
  }
  var position = _p.positionMs(posMs);
  if (position === null) {
    position = 0;
  }
  return position >= duration - FINISH_TRAILING_MS;
}

// Auto-remove needs the setting on, a finished book, and playback stopped.
function autoRemoveAllowed(setting, finished, isPlaying) {
  return setting === true && finished === true && isPlaying !== true;
}

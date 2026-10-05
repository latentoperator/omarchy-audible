.pragma library

// View logic for the Library drawer (PLAN L2, SCOPE FR-L2/FR-L6, ARCHITECTURE
// 5.3 and 6).
//
// It reads `Library.js` rows (`buildRows` output) plus the running `get`
// progress event and the online flag, and answers the questions the Library
// view asks: which badge a row shows, what picking it does, whether to resume
// or offer a choice, which empty/loading/error state to draw, where selection
// moves and whether a sync is due. It holds no state: the same rows and flags
// always give the same answer, so a view can bind straight to it.
//
// This is pure ECMAScript for the Qt JS engine: no imports, no Qt types, and
// nothing here throws on bad input. A row whose `state` is missing or not one
// of the six 5.3 values reads as the cloud row, which is a catalog book with no
// local copy and no job.
//
// The public surface is the constants and the seven functions below. Everything
// else lives on the private `_p` namespace so it cannot leak into QML.

// A position within this many milliseconds of the end counts as at-the-end, so
// a finished book there has nothing left to resume. Matches
// `Positions.FINISH_TRAILING_MS` and SCOPE 6.
var FINISH_TRAILING_MS = 30000;

// `badge` kinds: the 5.3 state values, plus `offline` for a cloud book seen
// while offline.
var BADGE_CLOUD = "cloud";
var BADGE_OFFLINE = "offline";
var BADGE_QUEUED = "queued";
var BADGE_DOWNLOADING = "downloading";
var BADGE_CONVERTING = "converting";
var BADGE_LOCAL = "local";
var BADGE_ERROR = "error";

// `primaryAction` results.
var ACTION_PLAY = "play";
var ACTION_DOWNLOAD = "download";
var ACTION_RETRY = "retry";
var ACTION_NONE = "none";

// `resumeChoice` results.
var CHOICE_RESUME = "resume";
var CHOICE_ASK = "ask";
var CHOICE_START_OVER = "start-over";

// `listState().state` values.
var STATE_LOADING = "loading";
var STATE_ERROR = "error";
var STATE_EMPTY = "empty";
var STATE_NO_RESULTS = "no-results";
var STATE_LIST = "list";

// `listState().banner` values.
var BANNER_OFFLINE = "offline";
var BANNER_RECONNECT = "reconnect";
var BANNER_SYNCING = "syncing";

var _p = {};

// The 5.3 state machine values a row's `state` may hold.
_p.STATES = [
  BADGE_CLOUD,
  BADGE_QUEUED,
  BADGE_DOWNLOADING,
  BADGE_CONVERTING,
  BADGE_LOCAL,
  BADGE_ERROR
];

_p.isNull = function (value) {
  return value === null || value === undefined;
};

_p.isObject = function (value) {
  return !_p.isNull(value) && typeof value === "object" && !Array.isArray(value);
};

_p.numberOrNull = function (value) {
  if (typeof value !== "number" || !isFinite(value)) {
    return null;
  }
  return value;
};

_p.stringOrNull = function (value) {
  return typeof value === "string" && value.length > 0 ? value : null;
};

// A count: a positive integer, or 0 for anything unusable (missing, negative,
// non-finite, fractional down to a whole number).
_p.count = function (value) {
  var number = _p.numberOrNull(value);
  if (number === null || number <= 0) {
    return 0;
  }
  return Math.floor(number);
};

// A position in milliseconds, clamped at zero, or 0 for bad input.
_p.positionMs = function (value) {
  var number = _p.numberOrNull(value);
  if (number === null || number <= 0) {
    return 0;
  }
  return Math.floor(number);
};

// A size in bytes for the storage total: a positive integer, or 0.
_p.sizeBytes = function (value) {
  var number = _p.numberOrNull(value);
  if (number === null || number <= 0) {
    return 0;
  }
  return Math.floor(number);
};

// `row.state` when it is one of the six 5.3 values; anything else reads as the
// cloud row.
_p.rowState = function (row) {
  if (_p.isObject(row) && typeof row.state === "string" && _p.STATES.indexOf(row.state) !== -1) {
    return row.state;
  }
  return BADGE_CLOUD;
};

// The rounded download percent from a `get` progress event, clamped to 0..100,
// or null when there is not enough to compute one.
_p.progressPercent = function (progress) {
  if (!_p.isObject(progress)) {
    return null;
  }
  var bytes = _p.numberOrNull(progress.bytes);
  var total = _p.numberOrNull(progress.total);
  if (bytes === null || bytes < 0 || total === null || total <= 0) {
    return null;
  }
  var percent = Math.round(bytes / total * 100);
  if (percent < 0) {
    return 0;
  }
  if (percent > 100) {
    return 100;
  }
  return percent;
};

// --- public API --------------------------------------------------------------

// The row's state badge (FR-L6) as `{kind, label}`. `kind` is a BADGE_*
// constant; a cloud book with `offline` true is `offline`. `progress` is the
// running `get` event and is used only for the downloading percent.
function badge(row, progress, offline) {
  var state = _p.rowState(row);
  if (state === BADGE_LOCAL) {
    return { "kind": BADGE_LOCAL, "label": "On this laptop" };
  }
  if (state === BADGE_QUEUED) {
    return { "kind": BADGE_QUEUED, "label": "Queued" };
  }
  if (state === BADGE_DOWNLOADING) {
    var percent = _p.progressPercent(progress);
    return {
      "kind": BADGE_DOWNLOADING,
      "label": percent === null ? "Downloading" : "Downloading " + percent + "%"
    };
  }
  if (state === BADGE_CONVERTING) {
    return { "kind": BADGE_CONVERTING, "label": "Converting" };
  }
  if (state === BADGE_ERROR) {
    return { "kind": BADGE_ERROR, "label": "Failed \u2014 Retry" };
  }
  if (offline === true) {
    return { "kind": BADGE_OFFLINE, "label": "Offline" };
  }
  return { "kind": BADGE_CLOUD, "label": "Cloud" };
}

// What picking a row does: play a local book, download a cloud book while
// online, retry a failed one, and nothing while a job is in flight or a cloud
// book is offline.
function primaryAction(row, offline) {
  var state = _p.rowState(row);
  if (state === BADGE_LOCAL) {
    return ACTION_PLAY;
  }
  if (state === BADGE_ERROR) {
    return ACTION_RETRY;
  }
  if (state === BADGE_CLOUD) {
    return offline === true ? ACTION_NONE : ACTION_DOWNLOAD;
  }
  return ACTION_NONE;
}

// Whether picking a book resumes, asks or starts over (SCOPE 6). A book that is
// not finished resumes. A finished book whose position is within 30 s of the
// end has nothing left to resume, so it starts over; a finished book further
// from the end offers the choice (`ask`). `durationMs` wins when it is a
// positive number, otherwise the row's runtime is used.
function resumeChoice(row, durationMs) {
  if (!_p.isObject(row) || row.isFinished !== true) {
    return CHOICE_RESUME;
  }
  var duration = _p.numberOrNull(durationMs);
  if (duration === null || duration <= 0) {
    var runtime = _p.numberOrNull(row.runtimeMin);
    duration = runtime !== null && runtime > 0 ? runtime * 60000 : 0;
  }
  var position = _p.positionMs(row.positionMs);
  if (duration > 0 && position >= duration - FINISH_TRAILING_MS) {
    return CHOICE_START_OVER;
  }
  return CHOICE_ASK;
}

// The Library view's state and banner (FR-L2, FR-A4). Inputs: `catalogLoaded`,
// `syncing`, `total`, `shown`, `offline`, `errorCode`.
//
// With no catalog yet the view is `loading`, or `error` when `errorCode` says
// the load failed. Once the catalog is loaded the view is `empty` for no books
// at all, `no-results` for a search/filter that matched none, otherwise `list`.
// A cached catalog keeps listing even if a later sync failed; an `auth_failed`
// error is a reconnect banner, and offline still wins over syncing.
function listState(state) {
  var source = _p.isObject(state) ? state : {};
  var errorCode = _p.stringOrNull(source.errorCode);
  var loaded = source.catalogLoaded === true;
  var total = _p.count(source.total);
  var shown = _p.count(source.shown);

  var banner = null;
  if (errorCode === "auth_failed") {
    banner = BANNER_RECONNECT;
  } else if (source.offline === true) {
    banner = BANNER_OFFLINE;
  } else if (source.syncing === true) {
    banner = BANNER_SYNCING;
  }

  var view;
  if (!loaded) {
    view = errorCode === null ? STATE_LOADING : STATE_ERROR;
  } else if (total === 0) {
    view = STATE_EMPTY;
  } else if (shown === 0) {
    view = STATE_NO_RESULTS;
  } else {
    view = STATE_LIST;
  }
  return { "state": view, "banner": banner };
}

// Move a list selection by `delta`, clamped to [0, count - 1]. An empty list
// has no selection, so the result is -1. An `index` of -1 means nothing is
// selected yet, and moving from there lands on the first row.
function moveSelection(index, delta, count) {
  var size = _p.count(count);
  if (size === 0) {
    return -1;
  }
  var step = _p.numberOrNull(delta);
  step = step === null ? 0 : (step < 0 ? Math.ceil(step) : Math.floor(step));
  var start = _p.numberOrNull(index);
  start = start === null ? -1 : (start < 0 ? Math.ceil(start) : Math.floor(start));
  var next = start + step;
  if (next < 0) {
    return 0;
  }
  if (next > size - 1) {
    return size - 1;
  }
  return next;
}

// A sync is due when the catalog age is unknown or at least `hours` old
// (FR-L2). The age is in seconds; a missing or negative age reads as unknown.
// A missing or negative `hours` window means always due.
function syncDue(catalogAgeS, hours) {
  var age = _p.numberOrNull(catalogAgeS);
  if (age === null || age < 0) {
    return true;
  }
  var window = _p.numberOrNull(hours);
  if (window === null || window < 0) {
    window = 0;
  }
  return age >= window * 3600;
}

// Total local usage (FR-S4) as `{count, bytes}`. Accepts the `local` event's
// list `[{asin, size, downloaded_at}]` or an ASIN-keyed map; Library rows work
// too, because a row that is not on this laptop carries `local: false`.
// Entries without a usable ASIN are ignored, and a missing or bad size adds no
// bytes.
function storage(localBooks) {
  var count = 0;
  var bytes = 0;
  if (Array.isArray(localBooks)) {
    for (var index = 0; index < localBooks.length; index++) {
      var item = localBooks[index];
      if (!_p.isObject(item) || item.local === false) {
        continue;
      }
      if (_p.stringOrNull(item.asin) === null) {
        continue;
      }
      count += 1;
      bytes += _p.sizeBytes(item.size);
    }
  } else if (_p.isObject(localBooks)) {
    var asins = Object.keys(localBooks);
    for (var key = 0; key < asins.length; key++) {
      var asin = asins[key];
      if (!asin) {
        continue;
      }
      var mapped = localBooks[asin];
      if (mapped === true) {
        count += 1;
      } else if (_p.isObject(mapped) && mapped.local !== false) {
        count += 1;
        bytes += _p.sizeBytes(mapped.size);
      }
    }
  }
  return { "count": count, "bytes": bytes };
}

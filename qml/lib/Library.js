.pragma library
.import "Positions.js" as Positions

// Library logic for the player service: one row per catalog book, the row's
// state machine (ARCHITECTURE 5.3), sorting, filtering and search, and the
// `state.json` schema v1 (ARCHITECTURE 3).
//
// This is pure ECMAScript for the Qt JS engine: no Qt types, and nothing here
// throws on bad input. `LibraryModel.qml` (the laptop task P3) feeds it the
// parsed `catalog.json`, `remote.json`, `state.json`, the `local` scan and the
// in-memory job states, and binds views to the returned rows.
//
// The newest-wins position merge and the timestamp parse come from
// `qml/lib/Positions.js` (P4a, the public port of
// `backend/omarchy_audible/positions.py`). `_p.timeKey` and `_p.mergePosition`
// are thin calls into it, so there is only one implementation (F20): a
// malformed `updated_at` cannot make the row's `positionMs` and `resumeChoice`
// disagree.
//
// The public surface is the constants and the six functions below. Everything
// else lives on the private `_p` namespace so it cannot leak into QML.

// --- constants ---------------------------------------------------------------
var SCHEMA_VERSION = 1;

// The §5.3 state machine values.
var STATE_CLOUD = "cloud";
var STATE_QUEUED = "queued";
var STATE_DOWNLOADING = "downloading";
var STATE_CONVERTING = "converting";
var STATE_LOCAL = "local";
var STATE_ERROR = "error";

// `sortRows` keys.
var SORT_RECENT = "recent";
var SORT_ADDED = "added";
var SORT_TITLE = "title";
var SORT_AUTHOR = "author";

// `filterRows` values.
var FILTER_ALL = "all";
var FILTER_LOCAL = "local";
var FILTER_IN_PROGRESS = "in-progress";

// --- private helpers ---------------------------------------------------------
var _p = {};

// The keys `state.json` v1 defines, in their canonical order.
_p.TOP_KEYS = ["schema", "books", "push_queue", "volume", "speed"];
_p.BOOK_KEYS = ["ms", "updated_at", "last_played_at", "played_since_download", "finished"];
_p.QUEUE_KEYS = ["asin", "ms", "at"];

// The job states a book can be in, least to most advanced.
_p.JOB_STATES = [STATE_QUEUED, STATE_DOWNLOADING, STATE_CONVERTING, STATE_ERROR];

_p.isNull = function (value) {
  return value === null || value === undefined;
};

_p.isObject = function (value) {
  return !_p.isNull(value) && typeof value === "object" && !Array.isArray(value);
};

// Lower-case and strip combining accents, so search and the title/author sorts
// are case- and accent-insensitive.
_p.foldText = function (value) {
  if (typeof value !== "string") {
    return "";
  }
  var lowered = value.toLowerCase();
  try {
    return lowered.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  } catch (error) {
    return lowered;
  }
};

// A comparable sort key for a title: folded, trimmed, and without a leading
// "The"/"A"/"An".
_p.titleKey = function (value) {
  var folded = _p.foldText(value).replace(/^\s+/, "");
  var match = /^(the|a|an)\s+/.exec(folded);
  if (match) {
    folded = folded.slice(match[0].length);
  }
  return folded;
};

// Name parts the author sort skips: honorifics before a name, and suffixes
// after it. Compared folded and without a trailing ".".
_p.NAME_PREFIXES = ["dr", "mr", "mrs", "ms", "miss", "mx", "prof", "professor", "sir", "dame", "lord", "lady", "rev", "fr", "capt", "col", "gen"];
_p.NAME_SUFFIXES = ["jr", "sr", "ii", "iii", "iv", "phd", "md", "dds", "esq", "obe", "mbe", "cbe"];
// Particles kept with the surname ("Le Guin", "du Maurier", "van der Berg").
_p.SURNAME_PARTICLES = ["de", "da", "di", "du", "del", "della", "der", "den", "van", "von", "le", "la", "st"];

_p.bareWord = function (word) {
  return word.replace(/[.,]+$/, "");
};

// The words of a name part, folded, with empty words dropped.
_p.nameWords = function (text) {
  return text.trim().split(/\s+/).filter(function (word) {
    return word.length > 0;
  });
};

_p.isSuffix = function (word) {
  return _p.NAME_SUFFIXES.indexOf(_p.bareWord(word)) !== -1;
};

_p.isPrefix = function (word) {
  return _p.NAME_PREFIXES.indexOf(_p.bareWord(word)) !== -1;
};

// Words without leading honorifics and trailing suffixes, keeping at least
// one word.
_p.trimTitles = function (words) {
  var start = 0;
  var end = words.length;
  while (end - start > 1 && _p.isSuffix(words[end - 1])) {
    end--;
  }
  while (end - start > 1 && _p.isPrefix(words[start])) {
    start++;
  }
  return words.slice(start, end);
};

// A comparable sort key for an author name: surname first, then the given
// names, folded. Honorifics ("Dr.") and suffixes ("Jr.", "PhD") are skipped,
// a particle after the given name stays with the surname, and a name already
// written "Surname, Given" keeps that order (its surname is never treated as
// an honorific). Unlike `titleKey`, a leading "A"/"An"/"The" is part of the
// name.
_p.authorKey = function (value) {
  if (typeof value !== "string") {
    return "";
  }
  // Comma-separated parts; a trailing part made only of suffixes ("King,
  // Jr.") is dropped rather than read as a given name.
  var parts = _p.foldText(value).split(",").map(_p.nameWords).filter(function (words) {
    return words.length > 0;
  });
  while (parts.length > 1 && parts[parts.length - 1].every(_p.isSuffix)) {
    parts.pop();
  }
  if (parts.length === 0) {
    return "";
  }
  if (parts.length > 1) {
    // "Reyes, Tamsin" or "Reyes,Dr. Tamsin": already surname first.
    var surnameWords = parts[0];
    var givenWords = [];
    for (var index = 1; index < parts.length; index++) {
      givenWords = givenWords.concat(parts[index]);
    }
    givenWords = givenWords.filter(function (word) {
      return !_p.isPrefix(word) && !_p.isSuffix(word);
    });
    return surnameWords.concat(givenWords).join(" ");
  }
  var words = _p.trimTitles(parts[0]);
  var cut = words.length - 1;
  while (cut - 1 > 0 && _p.SURNAME_PARTICLES.indexOf(_p.bareWord(words[cut - 1])) !== -1) {
    cut--;
  }
  return words.slice(cut).concat(words.slice(0, cut)).join(" ");
};

// Parse a timestamp into epoch milliseconds, or null when it is unparseable.
// Thin call into `Positions.parseUpdatedAt`, the single implementation (F20):
// the Audible no-timezone form is UTC, dates are validated against the
// calendar, and anything bad sorts as the oldest.
_p.timeKey = function (value) {
  return Positions.parseUpdatedAt(value);
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

_p.nonNegativeInt = function (value, fallback) {
  if (typeof value !== "number" || !isFinite(value)) {
    return fallback;
  }
  var truncated = value < 0 ? Math.ceil(value) : Math.floor(value);
  return Math.max(0, truncated);
};

// Copy `source`'s keys that `known` does not name, sorted, so the result is
// deterministic and unknown keys survive a parse/serialize round trip.
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

_p.normalizeBookEntry = function (entry) {
  var source = _p.isObject(entry) ? entry : {};
  var out = {
    "ms": _p.nonNegativeInt(source.ms, 0),
    "updated_at": _p.stringOrNull(source.updated_at),
    "last_played_at": _p.stringOrNull(source.last_played_at),
    "played_since_download": source.played_since_download === true,
    "finished": source.finished === true
  };
  return _p.withExtras(out, source, _p.BOOK_KEYS);
};

_p.normalizeQueueEntry = function (entry) {
  if (!_p.isObject(entry)) {
    return null;
  }
  var out = {
    "asin": _p.stringOrNull(entry.asin),
    "ms": _p.nonNegativeInt(entry.ms, 0),
    "at": _p.stringOrNull(entry.at)
  };
  return _p.withExtras(out, entry, _p.QUEUE_KEYS);
};

_p.emptyState = function (recovered) {
  return {
    "schema": SCHEMA_VERSION,
    "books": {},
    "push_queue": [],
    "volume": null,
    "speed": null,
    "recovered": recovered === true
  };
};

// Newest-wins merge of two position entries (ARCHITECTURE 4.6). Thin call into
// `Positions.merge`, the single implementation (F20): a missing entry or
// timestamp loses, and an equal `updated_at` goes to the local entry.
_p.mergePosition = function (local, remote) {
  return Positions.merge(local, remote);
};

// The newer of two timestamps, by parsed time. Ties and missing values favour
// the local `last_played_at` (ARCHITECTURE 4.6, 5.3).
_p.recentKey = function (lastPlayedAt, remoteUpdatedAt) {
  var local = _p.stringOrNull(lastPlayedAt);
  var remote = _p.stringOrNull(remoteUpdatedAt);
  if (local === null) {
    return remote;
  }
  if (remote === null) {
    return local;
  }
  var localKey = _p.timeKey(local);
  var remoteKey = _p.timeKey(remote);
  if (remoteKey === null) {
    return local;
  }
  if (localKey === null) {
    return remote;
  }
  return remoteKey > localKey ? remote : local;
};

_p.indexByAsin = function (value) {
  var out = {};
  if (_p.isObject(value)) {
    var keys = Object.keys(value);
    for (var index = 0; index < keys.length; index++) {
      if (_p.isObject(value[keys[index]])) {
        out[keys[index]] = value[keys[index]];
      }
    }
  }
  return out;
};

// The `local` scan is the backend's `local` event: a list of
// `{asin, size, downloaded_at}`. A map keyed by ASIN is tolerated too.
_p.indexLocal = function (value) {
  var out = {};
  var entries = Array.isArray(value) ? value : null;
  if (entries !== null) {
    for (var index = 0; index < entries.length; index++) {
      var entry = entries[index];
      if (!_p.isObject(entry) || typeof entry.asin !== "string" || !entry.asin) {
        continue;
      }
      out[entry.asin] = {
        "size": _p.numberOrNull(entry.size),
        "downloadedAt": _p.stringOrNull(entry.downloaded_at)
      };
    }
    return out;
  }
  if (_p.isObject(value)) {
    var asins = Object.keys(value);
    for (index = 0; index < asins.length; index++) {
      var mapped = value[asins[index]];
      if (_p.isObject(mapped)) {
        out[asins[index]] = {
          "size": _p.numberOrNull(mapped.size),
          "downloadedAt": _p.stringOrNull(mapped.downloaded_at)
        };
      } else if (mapped === true) {
        out[asins[index]] = { "size": null, "downloadedAt": null };
      }
    }
  }
  return out;
};

// The in-memory job states: a list of `{asin, state, message}` where state is
// one of `_p.JOB_STATES`. A map keyed by ASIN is tolerated. When a book somehow
// has several jobs the most advanced wins.
_p.indexJobs = function (value) {
  var out = {};
  var entries = Array.isArray(value) ? value : null;
  if (entries === null && _p.isObject(value)) {
    entries = [];
    var asins = Object.keys(value);
    for (var index = 0; index < asins.length; index++) {
      var mapped = value[asins[index]];
      if (_p.isObject(mapped)) {
        entries.push({ "asin": asins[index], "state": mapped.state, "message": mapped.message });
      } else if (typeof mapped === "string") {
        entries.push({ "asin": asins[index], "state": mapped });
      }
    }
  }
  if (entries === null) {
    return out;
  }
  for (index = 0; index < entries.length; index++) {
    var entry = entries[index];
    if (!_p.isObject(entry) || typeof entry.asin !== "string" || !entry.asin) {
      continue;
    }
    if (_p.JOB_STATES.indexOf(entry.state) === -1) {
      continue;
    }
    var existing = out[entry.asin];
    // JOB_STATES runs least to most advanced, so the later state wins.
    if (existing === undefined || _p.JOB_STATES.indexOf(existing.state) < _p.JOB_STATES.indexOf(entry.state)) {
      out[entry.asin] = { "state": entry.state, "message": _p.stringOrNull(entry.message) };
    }
  }
  return out;
};

_p.clampPercent = function (value) {
  if (value === null || value < 0) {
    return 0;
  }
  if (value > 100) {
    return 100;
  }
  return value;
};

_p.buildRow = function (book, asin, remoteEntry, stateBook, localEntry, jobEntry) {
  var runtime = _p.numberOrNull(book.runtime_min);
  var catalogPercent = _p.clampPercent(_p.numberOrNull(book.percent_complete));
  var localPosition = stateBook === null
    ? null
    : { "ms": stateBook.ms, "updated_at": stateBook.updated_at };
  var merged = _p.mergePosition(localPosition, remoteEntry);
  var durationMs = runtime !== null && runtime > 0 ? runtime * 60000 : 0;
  // Position drives the progress bar once there is one; the account's cached
  // `percent_complete` is the fallback for a book never played on this machine.
  var percent = durationMs > 0 && merged.ms > 0
    ? _p.clampPercent(merged.ms / durationMs * 100)
    : catalogPercent;
  var lastPlayedAt = stateBook === null ? null : _p.stringOrNull(stateBook.last_played_at);
  var remoteUpdatedAt = remoteEntry === null ? null : _p.stringOrNull(remoteEntry.updated_at);
  var state = STATE_CLOUD;
  if (localEntry !== null) {
    state = STATE_LOCAL;
  } else if (jobEntry !== null) {
    state = jobEntry.state;
  }
  return {
    "asin": asin,
    "title": _p.stringOrNull(book.title) === null ? "" : book.title,
    "subtitle": _p.stringOrNull(book.subtitle),
    "authors": Array.isArray(book.authors) ? book.authors.slice() : [],
    "narrators": Array.isArray(book.narrators) ? book.narrators.slice() : [],
    "series": _p.isObject(book.series) ? book.series : null,
    "cover": _p.stringOrNull(book.cover),
    "runtimeMin": runtime,
    "dateAdded": _p.stringOrNull(book.date_added),
    "isFinished": book.is_finished === true || (stateBook !== null && stateBook.finished === true),
    "multipart": book.multipart === true,
    "state": state,
    "local": localEntry !== null,
    "size": localEntry === null ? null : localEntry.size,
    "downloadedAt": localEntry === null ? null : localEntry.downloadedAt,
    "positionMs": merged.ms,
    "percent": percent,
    "lastPlayedAt": lastPlayedAt,
    "remoteUpdatedAt": remoteUpdatedAt,
    "recentKey": _p.recentKey(lastPlayedAt, remoteUpdatedAt),
    "jobState": jobEntry === null ? null : jobEntry.state,
    "error": jobEntry === null ? null : jobEntry.message
  };
};

// A stable sort: equal keys keep their input order regardless of the engine.
_p.stableSort = function (items, compare) {
  var decorated = [];
  for (var index = 0; index < items.length; index++) {
    decorated.push({ "item": items[index], "index": index });
  }
  decorated.sort(function (left, right) {
    var result = compare(left.item, right.item);
    return result !== 0 ? result : left.index - right.index;
  });
  var out = [];
  for (index = 0; index < decorated.length; index++) {
    out.push(decorated[index].item);
  }
  return out;
};

// Newest-first by parsed time; a missing value sorts last.
_p.compareDescending = function (leftValue, rightValue) {
  var leftKey = _p.timeKey(leftValue);
  var rightKey = _p.timeKey(rightValue);
  if (leftKey === null && rightKey === null) {
    return 0;
  }
  if (leftKey === null) {
    return 1;
  }
  if (rightKey === null) {
    return -1;
  }
  return rightKey - leftKey;
};

_p.compareText = function (leftValue, rightValue) {
  if (leftValue === rightValue) {
    return 0;
  }
  return leftValue < rightValue ? -1 : 1;
};

_p.firstAuthor = function (row) {
  return Array.isArray(row.authors) && row.authors.length > 0 && typeof row.authors[0] === "string"
    ? row.authors[0]
    : "";
};

_p.searchText = function (row) {
  var parts = [];
  _p.appendText(parts, row.title);
  _p.appendText(parts, row.subtitle);
  _p.appendText(parts, row.authors);
  _p.appendText(parts, row.narrators);
  if (_p.isObject(row.series)) {
    _p.appendText(parts, row.series.name);
    _p.appendText(parts, row.series.part);
  }
  return _p.foldText(parts.join(" "));
};

_p.appendText = function (parts, value) {
  if (typeof value === "string" && value) {
    parts.push(value);
  } else if (Array.isArray(value)) {
    for (var index = 0; index < value.length; index++) {
      if (typeof value[index] === "string" && value[index]) {
        parts.push(value[index]);
      }
    }
  }
};

// --- public API --------------------------------------------------------------
// Parse `state.json`. Never throws: garbage, a wrong schema and a missing file
// all yield an empty v1 with `recovered` true. Unknown keys are kept.
function parseState(text) {
  if (typeof text !== "string" || text.length === 0) {
    return _p.emptyState(true);
  }
  var data;
  try {
    data = JSON.parse(text);
  } catch (error) {
    return _p.emptyState(true);
  }
  if (!_p.isObject(data) || data.schema !== SCHEMA_VERSION) {
    return _p.emptyState(true);
  }
  var recovered = false;
  var out = { "schema": SCHEMA_VERSION };
  var books = {};
  if (!_p.isNull(data.books) && !_p.isObject(data.books)) {
    recovered = true;
  } else if (_p.isObject(data.books)) {
    var asins = Object.keys(data.books);
    for (var index = 0; index < asins.length; index++) {
      books[asins[index]] = _p.normalizeBookEntry(data.books[asins[index]]);
    }
  }
  out.books = books;
  var queue = [];
  if (!_p.isNull(data.push_queue) && !Array.isArray(data.push_queue)) {
    recovered = true;
  } else if (Array.isArray(data.push_queue)) {
    for (index = 0; index < data.push_queue.length; index++) {
      var entry = _p.normalizeQueueEntry(data.push_queue[index]);
      if (entry !== null) {
        queue.push(entry);
      }
    }
  }
  out.push_queue = queue;
  out.volume = _p.numberOrNull(data.volume);
  out.speed = _p.numberOrNull(data.speed);
  out.recovered = recovered;
  return _p.withExtras(out, data, _p.TOP_KEYS.concat(["recovered"]));
}

// Serialize `state.json` deterministically: known keys first in schema order,
// books sorted by ASIN, unknown keys sorted after them. Never throws. The
// parse-time `recovered` flag is not part of the file and is dropped.
function serializeState(obj) {
  var data = _p.isObject(obj) ? obj : {};
  var out = { "schema": SCHEMA_VERSION };
  var books = {};
  if (_p.isObject(data.books)) {
    var asins = Object.keys(data.books).sort();
    for (var index = 0; index < asins.length; index++) {
      books[asins[index]] = _p.normalizeBookEntry(data.books[asins[index]]);
    }
  }
  out.books = books;
  var queue = [];
  if (Array.isArray(data.push_queue)) {
    for (index = 0; index < data.push_queue.length; index++) {
      var entry = _p.normalizeQueueEntry(data.push_queue[index]);
      if (entry !== null) {
        queue.push(entry);
      }
    }
  }
  out.push_queue = queue;
  out.volume = _p.numberOrNull(data.volume);
  out.speed = _p.numberOrNull(data.speed);
  return JSON.stringify(_p.withExtras(out, data, _p.TOP_KEYS.concat(["recovered"])));
}

// One row per catalog book. `catalog` is `catalog.json` (or its `books`
// array); `remote` is `remote.json`; `state` is the parsed `state.json`;
// `local` is the `local` scan; `jobs` is the in-memory job states.
function buildRows(catalog, remote, state, local, jobs) {
  var books = [];
  if (Array.isArray(catalog)) {
    books = catalog;
  } else if (_p.isObject(catalog) && Array.isArray(catalog.books)) {
    books = catalog.books;
  }
  var remoteMap = _p.indexByAsin(remote);
  var stateBooks = _p.isObject(state) ? _p.indexByAsin(state.books) : {};
  var localMap = _p.indexLocal(local);
  var jobMap = _p.indexJobs(jobs);
  var rows = [];
  for (var index = 0; index < books.length; index++) {
    var book = books[index];
    if (!_p.isObject(book) || typeof book.asin !== "string" || !book.asin) {
      continue;
    }
    var asin = book.asin;
    rows.push(_p.buildRow(
      book,
      asin,
      Object.prototype.hasOwnProperty.call(remoteMap, asin) ? remoteMap[asin] : null,
      Object.prototype.hasOwnProperty.call(stateBooks, asin) ? stateBooks[asin] : null,
      Object.prototype.hasOwnProperty.call(localMap, asin) ? localMap[asin] : null,
      Object.prototype.hasOwnProperty.call(jobMap, asin) ? jobMap[asin] : null
    ));
  }
  return rows;
}

// A new, stable-sorted array: "recent"/"added" newest first, "title"
// ascending and ignoring case and a leading "The"/"A"/"An", "author" by the
// first author's surname (`authorKey`).
function sortRows(rows, key) {
  var items = Array.isArray(rows) ? rows : [];
  if (key === SORT_RECENT) {
    return _p.stableSort(items, function (left, right) {
      return _p.compareDescending(left.recentKey, right.recentKey);
    });
  }
  if (key === SORT_ADDED) {
    return _p.stableSort(items, function (left, right) {
      return _p.compareDescending(left.dateAdded, right.dateAdded);
    });
  }
  if (key === SORT_TITLE) {
    return _p.stableSort(items, function (left, right) {
      return _p.compareText(_p.titleKey(left.title), _p.titleKey(right.title));
    });
  }
  if (key === SORT_AUTHOR) {
    return _p.stableSort(items, function (left, right) {
      return _p.compareText(_p.authorKey(_p.firstAuthor(left)), _p.authorKey(_p.firstAuthor(right)));
    });
  }
  return items.slice();
}

// `all`, downloaded books only, or books started but not finished. An unknown
// filter is treated as `all`.
function filterRows(rows, filter) {
  var items = Array.isArray(rows) ? rows : [];
  if (filter === FILTER_LOCAL) {
    return items.filter(function (row) {
      return row.state === STATE_LOCAL;
    });
  }
  if (filter === FILTER_IN_PROGRESS) {
    return items.filter(function (row) {
      return row.percent > 0 && row.percent < 100 && row.isFinished !== true;
    });
  }
  return items.slice();
}

// Case- and accent-insensitive search across title, subtitle, authors,
// narrators and series. Every whitespace-separated token must match somewhere.
function searchRows(rows, text) {
  var items = Array.isArray(rows) ? rows : [];
  var query = _p.foldText(text).replace(/^\s+|\s+$/g, "");
  if (!query) {
    return items.slice();
  }
  var tokens = query.split(/\s+/);
  return items.filter(function (row) {
    var haystack = _p.searchText(row);
    for (var index = 0; index < tokens.length; index++) {
      if (haystack.indexOf(tokens[index]) === -1) {
        return false;
      }
    }
    return true;
  });
}

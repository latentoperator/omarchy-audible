.pragma library

// Display formatting for the drawer and the bar widget (PLAN L1, SCOPE FR-U1).
//
// Every string a view shows for a duration, a clock, a size, a relative time,
// a name list or the bar tooltip comes from here, so the Library and Mini views
// and the bar widget all read the same way. The laptop's QML files import this
// library instead of building strings themselves.
//
// This is pure ECMAScript for the Qt JS engine: no imports, no Qt types, and
// nothing here throws on bad input. A value that cannot be formatted comes back
// as "" (or the documented neutral value) rather than `NaN`, `undefined` or a
// thrown error, so a view can bind the result straight into a text property.
//
// Durations are floor-rounded to the minute and shown as "3h 12m" or "45m"; a
// zero part is dropped ("1h"), and a positive remainder under a minute is
// "<1m". `clock` is the elapsed/remaining time: "0:00", "2:05", "1:02:33",
// "123:04:05". `bytes` is 1024-based and shows one decimal under 10.
//
// The public surface is the nine functions below. Everything else lives on the
// private `_p` namespace so it cannot leak into QML.

var _p = {};

_p.MINUTE_MS = 60000;
_p.HOUR_MS = 3600000;
_p.DAY_MS = 86400000;

// 1024-based, largest first-wins; the list decides when a size stops.
_p.BYTE_UNITS = ["B", "KB", "MB", "GB"];

// The em dash between a title and its author, and the middle dot before the
// remaining-time part of the tooltip (FR-U1).
_p.DASH = "\u2014";
_p.DOT = "\u00b7";

_p.isNull = function (value) {
  return value === null || value === undefined;
};

// A finite, non-negative number of milliseconds/bytes, or null. Negative,
// non-finite and non-numeric values are all "bad input".
_p.amount = function (value) {
  if (typeof value !== "number" || !isFinite(value) || value < 0) {
    return null;
  }
  return value;
};

// A non-empty, trimmed string, or null. Names and labels never render a
// whitespace-only part.
_p.text = function (value) {
  if (typeof value !== "string") {
    return null;
  }
  var text = value.replace(/^\s+|\s+$/g, "");
  return text.length > 0 ? text : null;
};

_p.pad2 = function (value) {
  return value < 10 ? "0" + value : String(value);
};

// The "h"/"m" form of a whole number of minutes.
_p.hoursMinutes = function (totalMinutes) {
  var hours = Math.floor(totalMinutes / 60);
  var minutes = totalMinutes % 60;
  if (hours === 0) {
    return minutes + "m";
  }
  return minutes === 0 ? hours + "h" : hours + "h " + minutes + "m";
};

// --- public API --------------------------------------------------------------

// "3h 12m", "45m", "<1m", "0m"; bad input gives "".
function duration(ms) {
  var value = _p.amount(ms);
  if (value === null) {
    return "";
  }
  if (value === 0) {
    return "0m";
  }
  if (value < _p.MINUTE_MS) {
    return "<1m";
  }
  return _p.hoursMinutes(Math.floor(value / _p.MINUTE_MS));
}

// "3h 12m left", and "" at or past the end (or on bad input).
function left(positionMs, durationMs) {
  var position = _p.amount(positionMs);
  var total = _p.amount(durationMs);
  if (position === null || total === null || total === 0 || position >= total) {
    return "";
  }
  return duration(total - position) + " left";
}

// "0:00", "2:05", "1:02:33", "123:04:05"; bad input gives "".
function clock(ms) {
  var value = _p.amount(ms);
  if (value === null) {
    return "";
  }
  var seconds = Math.floor(value / 1000);
  var hours = Math.floor(seconds / 3600);
  var minutes = Math.floor((seconds % 3600) / 60);
  var remainder = seconds % 60;
  if (hours === 0) {
    return minutes + ":" + _p.pad2(remainder);
  }
  return hours + ":" + _p.pad2(minutes) + ":" + _p.pad2(remainder);
}

// 1024-based size: "0 B", "512 B", "1.0 KB", "5.5 MB", "780 MB", "100 GB".
// One decimal under 10, a whole number above it. Values beyond GB stay in GB.
function bytes(n) {
  var value = _p.amount(n);
  if (value === null) {
    return "";
  }
  var unit = 0;
  while (value >= 1024 && unit < _p.BYTE_UNITS.length - 1) {
    value = value / 1024;
    unit += 1;
  }
  if (unit === 0) {
    return Math.round(value) + " B";
  }
  var number = value < 10 ? value.toFixed(1) : String(Math.round(value));
  return number + " " + _p.BYTE_UNITS[unit];
}

// "No books on this device", "1 book \u00b7 12 MB", "3 books \u00b7 780 MB".
// A missing size leaves just the count, e.g. "1 book".
function storageLine(count, totalBytes) {
  var books = _p.amount(count);
  if (books === null) {
    return "No books on this device";
  }
  books = Math.floor(books);
  if (books === 0) {
    return "No books on this device";
  }
  var label = books === 1 ? "1 book" : books + " books";
  var size = bytes(totalBytes);
  return size === "" ? label : label + " " + _p.DOT + " " + size;
}

// "just now", "5 min ago", "3 h ago", "2 days ago"; "never" for a missing or
// unparseable timestamp. `nowMs` is the current epoch time for testability;
// when omitted the engine clock is used. A future timestamp reads "just now".
function ago(iso, nowMs) {
  if (typeof iso !== "string" || iso.length === 0) {
    return "never";
  }
  var then = Date.parse(iso);
  if (isNaN(then)) {
    return "never";
  }
  var now = _p.amount(nowMs);
  if (now === null) {
    now = Date.now();
  }
  var diff = now - then;
  if (diff < _p.MINUTE_MS) {
    return "just now";
  }
  if (diff < _p.HOUR_MS) {
    return Math.floor(diff / _p.MINUTE_MS) + " min ago";
  }
  if (diff < _p.DAY_MS) {
    return Math.floor(diff / _p.HOUR_MS) + " h ago";
  }
  var days = Math.floor(diff / _p.DAY_MS);
  return days + (days === 1 ? " day ago" : " days ago");
}

// "A", "A and B", "A, B and C", or "A, B and 2 more" past three names.
// Non-string and blank entries are skipped.
function names(list) {
  if (!Array.isArray(list)) {
    return "";
  }
  var items = [];
  for (var index = 0; index < list.length; index++) {
    var text = _p.text(list[index]);
    if (text !== null) {
      items.push(text);
    }
  }
  if (items.length === 0) {
    return "";
  }
  if (items.length === 1) {
    return items[0];
  }
  if (items.length === 2) {
    return items[0] + " and " + items[1];
  }
  if (items.length === 3) {
    return items[0] + ", " + items[1] + " and " + items[2];
  }
  return items[0] + ", " + items[1] + " and " + (items.length - 2) + " more";
}

// The bar tooltip (FR-U1): "Title \u2014 Author \u00b7 3h 12m left", with any
// missing part and its separator left out. `leftText` is already formatted,
// e.g. the result of `left`.
function tooltip(title, author, leftText) {
  var name = _p.text(title);
  var writer = _p.text(author);
  var remaining = _p.text(leftText);
  var result = name;
  if (writer !== null) {
    result = result === null ? writer : result + " " + _p.DASH + " " + writer;
  }
  if (remaining !== null) {
    result = result === null ? remaining : result + " " + _p.DOT + " " + remaining;
  }
  return result === null ? "" : result;
}

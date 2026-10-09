.pragma library

// Library view (drawer) decisions that `LibraryUi.js` does not make (U2): the
// sort and filter choices, the catalog's age for the sync-on-open check, the
// sync state, keys typed in the search field, which row Enter picks, which
// books can be removed, and the text for each list state and banner.
//
// Pure ECMAScript for the Qt JS engine: no imports, no Qt types, and nothing
// here throws on bad input.

// After any sync attempt, an automatic sync waits this long, so a failing
// sync (offline) is not retried on every open.
var SYNC_RETRY_MS = 600000;

// Sort and filter choices (FR-L3, FR-L4). Values are the `Library.js` keys.
var SORTS = [
  { "value": "recent", "label": "Recently listened" },
  { "value": "added", "label": "Recently added" },
  { "value": "title", "label": "Title" },
  { "value": "author", "label": "Author" }
];
var FILTERS = [
  { "value": "all", "label": "All" },
  { "value": "local", "label": "On this device" },
  { "value": "in-progress", "label": "In progress" }
];

// Qt key codes (Qt::Key) the search field reacts to. The one home for them:
// `Signin.js` imports Escape, Return and Enter for the paste field.
var KEY_ESCAPE = 0x01000000;
var KEY_RETURN = 0x01000004;
var KEY_ENTER = 0x01000005;
var KEY_UP = 0x01000013;
var KEY_DOWN = 0x01000015;
var KEY_SPACE = 0x20;

// `searchKey` results.
var KEY_CLOSE = "close";
var KEY_MOVE_UP = "up";
var KEY_MOVE_DOWN = "down";
var KEY_PICK = "pick";
var KEY_TOGGLE = "toggle";
var KEY_TYPE = "type";

var _p = {};

_p.number = function (value) {
  return typeof value === "number" && isFinite(value) ? value : null;
};

// Age of the catalog in seconds, or null when unknown. A sync this session
// wins; otherwise the `status` event's `catalog_age_s` plus the time since
// that event arrived.
function catalogAgeS(statusAgeS, statusAtMs, lastSyncAtMs, nowMs) {
  var now = _p.number(nowMs);
  if (now === null) return null;
  var synced = _p.number(lastSyncAtMs);
  if (synced !== null && synced > 0) return Math.max(0, (now - synced) / 1000);
  var age = _p.number(statusAgeS);
  var at = _p.number(statusAtMs);
  if (age === null || age < 0 || at === null || at <= 0) return null;
  return age + Math.max(0, (now - at) / 1000);
}

// Whether a sync is queued or running, from the runner's pending list and
// active job.
function syncing(pending, active) {
  if (active && active.command === "sync") return true;
  if (!Array.isArray(pending)) return false;
  for (var i = 0; i < pending.length; i++) {
    if (pending[i] && pending[i].command === "sync") return true;
  }
  return false;
}

// The last sync's failure: `{offline, errorCode}`. A `network` error means
// offline; other codes are passed to `LibraryUi.listState` as the error.
function syncFailure(code) {
  if (typeof code !== "string" || code.length === 0) return { "offline": false, "errorCode": null };
  if (code === "network") return { "offline": true, "errorCode": null };
  return { "offline": false, "errorCode": code };
}

// What a key pressed in the search field does (ARCHITECTURE 6): Esc closes,
// ↑/↓ move, Enter picks, Space plays/pauses only while the field is empty;
// everything else is typed.
function searchKey(key, text) {
  if (key === KEY_ESCAPE) return KEY_CLOSE;
  if (key === KEY_UP) return KEY_MOVE_UP;
  if (key === KEY_DOWN) return KEY_MOVE_DOWN;
  if (key === KEY_RETURN || key === KEY_ENTER) return KEY_PICK;
  if (key === KEY_SPACE && (typeof text !== "string" || text.length === 0)) return KEY_TOGGLE;
  return KEY_TYPE;
}

// Whether an automatic sync must wait: one was attempted less than
// `SYNC_RETRY_MS` ago.
function autoSyncBlocked(lastAttemptMs, nowMs) {
  var last = _p.number(lastAttemptMs);
  var now = _p.number(nowMs);
  if (last === null || last <= 0 || now === null) return false;
  return now - last < SYNC_RETRY_MS;
}

// Whether `index` is a row of a list of `count` rows.
function validIndex(index, count) {
  var i = _p.number(index);
  var n = _p.number(count);
  return i !== null && n !== null && i >= 0 && i < n && Math.floor(i) === i;
}

// The selection after the list changed to `count` rows: kept when still in
// range, else moved to the last row, or -1 for an empty list.
function clampSelection(selected, count) {
  var n = _p.number(count);
  var i = _p.number(selected);
  if (n === null || n < 1) return -1;
  if (i === null || i < 0) return -1;
  return Math.min(Math.floor(i), n - 1);
}

// The row Enter picks: the selection, else the first row, else none (-1).
function pickIndex(selected, count) {
  var size = _p.number(count);
  if (size === null || size < 1) return -1;
  var index = _p.number(selected);
  if (index === null || index < 0) return 0;
  return Math.min(Math.floor(index), size - 1);
}

// The `get` progress to show on a row: the runner's progress while that row's
// download is the active job, else null.
function rowProgress(asin, active, progress) {
  if (!active || active.command !== "get" || typeof asin !== "string") return null;
  var args = Array.isArray(active.args) ? active.args : [];
  var jobAsin = typeof active.asin === "string" ? active.asin : args[0];
  return jobAsin === asin && progress && typeof progress === "object" ? progress : null;
}

// Any book on the laptop can be removed (FR-S2); the service unloads a
// loaded one first.
function canRemove(row) {
  return !!row && row.local === true && typeof row.asin === "string";
}

// The ASINs "Remove all downloads" removes: every book on the laptop.
function removableAsins(rows) {
  var out = [];
  if (!Array.isArray(rows)) return out;
  for (var i = 0; i < rows.length; i++) {
    if (canRemove(rows[i])) out.push(rows[i].asin);
  }
  return out;
}

// Whether a user removal may run now: never for a book that is loaded,
// waiting on its resume position, or about to load (`busy` lists those
// ASINs), because it was picked again after the removal was asked for.
function removalAllowed(asin, busy) {
  if (typeof asin !== "string" || asin.length === 0) return false;
  if (!Array.isArray(busy)) return true;
  return busy.indexOf(asin) < 0;
}

// Whether `asin` is being removed: waiting for the player to unload it, or
// a `remove` job for it is queued or running.
function removing(asin, waiting, pending, active) {
  if (typeof asin !== "string" || asin.length === 0) return false;
  if (Array.isArray(waiting) && waiting.indexOf(asin) >= 0) return true;
  var jobs = Array.isArray(pending) ? pending.slice() : [];
  if (active) jobs.push(active);
  for (var i = 0; i < jobs.length; i++) {
    var job = jobs[i];
    if (job && job.command === "remove" && Array.isArray(job.args) && job.args[0] === asin) return true;
  }
  return false;
}

// The Resume / Start over question for a finished book (SCOPE 6).
function askText(row) {
  var title = row && typeof row.title === "string" && row.title.trim().length > 0 ? row.title.trim() : "this book";
  return "You finished " + title + ".";
}

// The Resume / Start over question on a finished book's own row (U10b). The
// row already shows the title, so the question doesn't repeat it.
var ROW_ASK_TEXT = "You finished this book. Resume, or start over?";

// The download question in a cloud book's row (G3 finding 3). The view
// passes `Format.bytes(LibraryUi.estimatedBytes(row))`, or "" when the
// estimate is 0 (no runtime); without a size, the question gives none.
function downloadQuestion(sizeText) {
  var size = typeof sizeText === "string" ? sizeText.trim() : "";
  return size.length > 0 ? "Download up to " + size + "?" : "Download this book?";
}

// The failure line under a failed row (SCOPE 6), else "".
function errorText(row) {
  if (!row || row.state !== "error") return "";
  return typeof row.error === "string" && row.error.trim().length > 0 ? row.error.trim() : "Download failed";
}

// The confirm question for "Remove all downloads", or "" when there is
// nothing to remove.
function removeAllQuestion(count) {
  var n = _p.number(count);
  if (n === null || n < 1) return "";
  return n === 1 ? "Remove 1 download from this device?" : "Remove " + Math.floor(n) + " downloads from this device?";
}

// The message for a `LibraryUi.listState` state other than `list`.
function stateText(state) {
  if (state === "loading") return "Loading your library…";
  if (state === "error") return "Couldn't load your library. Try refreshing.";
  if (state === "empty") return "Your library is empty.";
  if (state === "no-results") return "No books match.";
  return "";
}

// The banner line for a `LibraryUi.listState` banner, or "".
function bannerText(banner) {
  if (banner === "offline") return "Offline — showing your saved library";
  if (banner === "reconnect") return "Audible needs you to sign in again";
  if (banner === "syncing") return "Updating your library…";
  return "";
}

// A row's author names as a plain array for `Format.names`. A row that
// reaches a ListView delegate carries its lists as Qt sequences, which are
// not `Array.isArray`, so anything with a length is copied.
function authors(row) {
  var list = row ? row.authors : null;
  var out = [];
  if (!list || typeof list === "string" || typeof list.length !== "number") return out;
  for (var i = 0; i < list.length; i++) {
    var name = list[i];
    if (typeof name === "string" && name.trim().length > 0) out.push(name.trim());
  }
  return out;
}

// Runtime in ms for a row, 0 when unknown.
function runtimeMs(row) {
  var minutes = row ? _p.number(row.runtimeMin) : null;
  return minutes !== null && minutes > 0 ? minutes * 60000 : 0;
}

// Progress bar fill, 0..1.
function progressFraction(row) {
  var percent = row ? _p.number(row.percent) : null;
  if (percent === null || percent <= 0) return 0;
  return Math.min(1, percent / 100);
}

.pragma library

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

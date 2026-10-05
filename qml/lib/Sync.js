.pragma library

// Queue helpers for position write-back (ARCHITECTURE 4.6). `Positions.js`
// decides what may be pushed (`shouldPush`, `enqueue`, `flushPlan`); this file
// holds the plain list handling around it. Pure ECMAScript for the Qt JS
// engine: no imports, no Qt types, and nothing here throws on bad input.

// The `position-get` call takes at most this many ASINs.
var BATCH_SIZE = 25;

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
// `sendAt`, when set, is used instead of `at` (see `atOwnWrites`).
function pushArgs(entry) {
  var args = [String(entry.asin), String(Math.round(entry.ms))];
  var at = typeof entry.sendAt === "string" && entry.sendAt.length > 0 ? entry.sendAt : entry.at;
  if (typeof at === "string" && at.length > 0) {
    args.push("--at");
    args.push(at);
  }
  return args;
}

// Entries whose remote position is our own earlier write get `sendAt` set to
// that write's timestamp. The backend refuses a push whose `--at` is older
// than the account's `updated_at`, and our own write is stamped when it
// arrived, which can be later than the next listening time. The queue entry
// keeps its real `at`, so it is still removed when it has been sent.
function atOwnWrites(send, items, lastPushed) {
  var list = Array.isArray(send) ? send : [];
  var source = isObject(items) ? items : {};
  var pushed = isObject(lastPushed) ? lastPushed : {};
  return list.map(function (entry) {
    var remote = isObject(entry) ? source[entry.asin] : null;
    if (isObject(remote) && typeof pushed[entry.asin] === "number" && remote.ms === pushed[entry.asin]
        && typeof remote.updated_at === "string" && remote.updated_at.length > 0) {
      var copy = {};
      for (var key in entry) {
        copy[key] = entry[key];
      }
      copy.sendAt = remote.updated_at;
      return copy;
    }
    return entry;
  });
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

// The `positions` items with our own writes made invisible. Audible stamps a
// push with the time it arrived, which can be later than the listening time of
// the next local position. A remote position equal to the one we last pushed
// is our own write, not another device, so its timestamp must not make a newer
// local position look stale: those entries get `updated_at: null`.
function withoutOwnWrites(items, lastPushed) {
  var out = {};
  var source = isObject(items) ? items : {};
  var pushed = isObject(lastPushed) ? lastPushed : {};
  for (var asin in source) {
    var entry = source[asin];
    if (isObject(entry) && typeof pushed[asin] === "number" && entry.ms === pushed[asin]) {
      out[asin] = { "ms": entry.ms, "updated_at": null };
    } else {
      out[asin] = entry;
    }
  }
  return out;
}

function isObject(value) {
  return value !== null && value !== undefined && typeof value === "object" && !Array.isArray(value);
}

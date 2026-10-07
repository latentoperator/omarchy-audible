.pragma library

// The service's pending `play-info` request (B11). Every way into playback
// asks the backend which file to load and with which key, then loads it when
// the reply comes. Only the newest request may load: each one gets its own
// id, carried in the job's purpose, so a reply for an older request (the same
// book asked for twice, or a book the user has since moved on from) is
// dropped instead of loading or failing in its place.
//
// The request holds the book and where to start, never the key: that goes
// from the reply straight to the player.
//
// Pure ECMAScript for the Qt JS engine: no imports, no Qt types, and nothing
// here throws on bad input.

var COMMAND = "play-info";
var PURPOSE_PREFIX = "play:";

// A request for `asin` from `startSec`, with a caller-supplied id that is
// different for every request.
function create(asin, startSec, id) {
  return {
    "asin": String(asin),
    "startSec": typeof startSec === "number" && isFinite(startSec) ? startSec : 0,
    "id": id,
    "purpose": PURPOSE_PREFIX + String(id)
  };
}

// Whether `job` (a finished or reporting backend job) is the reply to
// `request`: the same command, book and id.
function matches(request, job) {
  if (!isObject(request) || !isObject(job)) {
    return false;
  }
  return job.command === COMMAND && job.purpose === request.purpose
    && Array.isArray(job.args) && job.args[0] === request.asin;
}

// The book a removal must leave alone while its request waits, or "".
function busyAsin(request) {
  return isObject(request) && typeof request.asin === "string" ? request.asin : "";
}

function isObject(value) {
  return value !== null && value !== undefined && typeof value === "object" && !Array.isArray(value);
}

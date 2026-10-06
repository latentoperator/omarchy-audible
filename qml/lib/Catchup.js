.pragma library

// ⏯ catching up with other devices (SCOPE FR-P4, G3 finding 5). A Library
// pick always reads the account first; ⏯ on a paused book reads it only after
// a pause long enough to have listened elsewhere, and opening the drawer
// starts that read early. These are the decisions; `Service.qml` runs the
// read. Pure ECMAScript for the Qt JS engine: no imports, no Qt types, and
// nothing here throws on bad input.

// A pause shorter than this resumes at once: nobody switched devices.
var PAUSE_CHECK_MS = 30000;

// How long ⏯ waits for the account before resuming the local spot.
var READ_TIMEOUT_MS = 3000;

// A read started when the drawer opened is used for this long.
var PREFETCH_FRESH_MS = 60000;

// A newer account position closer than this to the player is not a jump.
var JUMP_MIN_MS = 2000;

function _number(value) {
  return typeof value === "number" && isFinite(value) ? value : null;
}

// Whether resuming after a pause that began at `pausedAtMs` reads the account
// first. An unknown pause time (0, after a shell restart) or a clock that went
// backwards reads, to be safe.
function needsRead(pausedAtMs, nowMs) {
  var paused = _number(pausedAtMs);
  var now = _number(nowMs);
  if (paused === null || paused <= 0 || now === null || now < paused) return true;
  return now - paused >= PAUSE_CHECK_MS;
}

// Whether a finished read `{asin, atMs, remote}` still answers for `asin`.
// `remote` may be null (the account has no position for the book).
function prefetchUsable(prefetch, asin, nowMs) {
  if (!prefetch || typeof prefetch !== "object" || prefetch.asin !== asin) return false;
  var at = _number(prefetch.atMs);
  var now = _number(nowMs);
  if (at === null || now === null || now < at) return false;
  return now - at <= PREFETCH_FRESH_MS;
}

// Where to seek before resuming, or -1 to resume in place. Only an account
// position newer than the saved local one counts (`localKey` and `remoteKey`
// are `Positions.parseUpdatedAt` values; a null `localKey` means nothing was
// saved here), so a skip made while paused is never pulled back.
function jumpTarget(currentMs, localKey, remoteMs, remoteKey) {
  var remote = _number(remoteMs);
  var remoteAt = _number(remoteKey);
  if (remote === null || remote < 0 || remoteAt === null) return -1;
  var localAt = _number(localKey);
  if (localAt !== null && remoteAt <= localAt) return -1;
  var current = _number(currentMs);
  if (current !== null && Math.abs(remote - current) < JUMP_MIN_MS) return -1;
  return remote;
}

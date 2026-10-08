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
// saved here). `ownMs` lists positions this laptop wrote (its last push, its
// saved pause position): the account stamps a push with the server's later
// clock, so without this a skip made while paused would be pulled back to the
// laptop's own pause push. The account keeps a pushed value to the
// millisecond, so only an exact match is the laptop's echo; a phone position
// near it is still a phone position.
function jumpTarget(currentMs, localKey, remoteMs, remoteKey, ownMs) {
  var remote = _number(remoteMs);
  var remoteAt = _number(remoteKey);
  if (remote === null || remote < 0 || remoteAt === null) return -1;
  var localAt = _number(localKey);
  if (localAt !== null && remoteAt <= localAt) return -1;
  if (Array.isArray(ownMs)) {
    for (var i = 0; i < ownMs.length; i++) {
      var own = _number(ownMs[i]);
      if (own !== null && Math.round(own) === Math.round(remote)) return -1;
    }
  }
  var current = _number(currentMs);
  if (current !== null && Math.abs(remote - current) < JUMP_MIN_MS) return -1;
  return remote;
}

// What a ⏯ press does. `state`: {loaded, playing, waiting (a ⏯ already waits
// on a read), pendingResume (a Library pick is reading its position),
// needsRead, prefetchUsable, reading (a read for this book is in flight)}.
var PRESS_NONE = "none";          // nothing loaded
var PRESS_PAUSE = "pause";        // playing: pause, drop any wait
var PRESS_CANCEL = "cancel";      // second press while waiting: stay paused
var PRESS_BUSY = "busy";          // the pick decides where to play
var PRESS_RESUME = "resume";      // short pause: resume at once
var PRESS_PREFETCH = "prefetch";  // use the drawer's finished read
var PRESS_READ = "read";          // start a read and wait
var PRESS_WAIT = "wait";          // a read is in flight: wait for it

function pressAction(state) {
  if (!state || typeof state !== "object" || state.loaded !== true) return PRESS_NONE;
  if (state.playing === true) return PRESS_PAUSE;
  if (state.waiting === true) return PRESS_CANCEL;
  if (state.pendingResume === true) return PRESS_BUSY;
  if (state.needsRead !== true) return PRESS_RESUME;
  if (state.prefetchUsable === true) return PRESS_PREFETCH;
  return state.reading === true ? PRESS_WAIT : PRESS_READ;
}

// Whether a finished read of `readAsin` resumes playback: only while a ⏯ for
// that same book still waits. A cancel, a pause or a newer pick clears the
// wait, so a late read resumes nothing.
function readResumes(waitingAsin, readAsin) {
  return typeof waitingAsin === "string" && waitingAsin.length > 0 && waitingAsin === readAsin;
}

// What resuming after the wait does. `state`: {loaded, sameBook (the waiting
// book is still the loaded one), playing, storeLoaded, hasRemote}. "compare"
// runs `jumpTarget` first; "resume" resumes in place; "none" leaves the
// player alone.
function resumeAction(state) {
  if (!state || typeof state !== "object") return "none";
  if (state.loaded !== true || state.sameBook !== true || state.playing === true) return "none";
  return state.hasRemote === true && state.storeLoaded === true ? "compare" : "resume";
}

// The Mini line after a catch-up jump, so a jump never looks like a glitch:
// it says why the position moved and where it was. Shown for NOTE_MS.
var NOTE_MS = 5000;

function jumpNote(wasText) {
  var base = "Continued from your other device";
  return typeof wasText === "string" && wasText.length > 0 ? base + " (was " + wasText + ")" : base;
}

// The bookkeeping when the catch-up read of `readAsin` finishes (`ok` is the
// job's outcome). `state`: {reads (the books with a read queued or running,
// asin -> true), results (finished reads' results by ASIN, each
// `{asin, atMs, remote}`), prefetched (the last finished read, or null),
// waitingAsin (the book a ⏯ waits on, or "")}. Returns the next `reads`,
// `results` and `prefetched`, and whether the waiting ⏯ resumes now with
// `remote` (the account entry, or null to resume in place). The read is
// dropped and only its own result is used, so overlapping reads of different
// books never touch each other: a failed read of A never clears B's
// prefetched result. The inputs are not changed.
function finishRead(state, readAsin, ok) {
  var s = state !== null && typeof state === "object" ? state : {};
  var reads = _copy(s.reads);
  var results = _copy(s.results);
  var own = ok === true && Object.prototype.hasOwnProperty.call(results, readAsin) ? results[readAsin] : null;
  var result = own !== null && typeof own === "object" ? own : null;
  delete reads[readAsin];
  delete results[readAsin];
  var prefetched = s.prefetched !== null && typeof s.prefetched === "object" ? s.prefetched : null;
  if (result) prefetched = result;
  else if (prefetched && prefetched.asin === readAsin) prefetched = null;
  var resume = readResumes(s.waitingAsin, readAsin);
  return {
    "reads": reads,
    "results": results,
    "prefetched": prefetched,
    "resume": resume,
    "remote": resume && result ? (result.remote || null) : null
  };
}

function _copy(object) {
  var out = {};
  if (object === null || typeof object !== "object" || Array.isArray(object)) return out;
  for (var key in object) {
    if (Object.prototype.hasOwnProperty.call(object, key)) out[key] = object[key];
  }
  return out;
}

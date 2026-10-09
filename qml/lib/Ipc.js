.pragma library

// Shell IPC argument logic for Service.qml (ARCHITECTURE 6).
//
// The IpcHandler passes every argument as a string. This file turns the
// `skip <seconds>` argument into a number or null so the QML can return a
// short error instead of seeking by a bogus amount. Pure ECMAScript for the
// Qt JS engine: no imports, no Qt types, and nothing here throws.

var MAX_SECONDS = 86400;

// A strict decimal, so hex ("0x10"), "NaN", "Infinity" and "1e3" are all
// rejected rather than silently coercion-parsed by Number().
var DECIMAL = /^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$/;

// A signed number of seconds from an IPC string, or null: empty, non-numeric,
// over the bound, or not a string at all.
function parseSeconds(text) {
  if (typeof text !== "string") {
    return null;
  }
  var trimmed = text.trim();
  if (!DECIMAL.test(trimmed)) {
    return null;
  }
  var value = Number(trimmed);
  if (!isFinite(value) || Math.abs(value) > MAX_SECONDS) {
    return null;
  }
  return value;
}

// Stop is available while a book or any pending playback request is active.
// `pendingLoad` and `playRequest` are the held objects (or null), not flags.
function stopAllowed(loaded, wanted, pendingLoad, pendingResume, playRequest) {
  return loaded === true || wanted === true ||
    (pendingLoad !== null && pendingLoad !== undefined && pendingLoad !== false) ||
    (typeof pendingResume === "string" && pendingResume.length > 0) ||
    (playRequest !== null && playRequest !== undefined && playRequest !== false);
}

// What a test-only method returns outside fake mode (H1 F27).
var DEV_ONLY = "error: dev only";

// Methods anyone may call in real mode: the documented controls (README
// "Hotkeys and IPC", ARCHITECTURE 6) that keybindings use.
var PUBLIC_METHODS = ["toggle", "openLibrary", "playPause", "skip", "nextChapter", "prevChapter", "stop"];

// Methods that only read state. They stay in real mode so a session can
// confirm which mode the shell is in and that the service is attached
// (FOLLOWUPS-desktop §0 and §5); none of them changes anything.
var STATUS_METHODS = ["playerStatus", "libraryState", "onboardingState", "panelState", "pushState", "events"];

// Every other method is test-only: it works only in fake mode.
function isRealModeMethod(name) {
  return PUBLIC_METHODS.indexOf(name) !== -1 || STATUS_METHODS.indexOf(name) !== -1;
}

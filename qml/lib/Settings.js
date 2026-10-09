.pragma library
.import "Mpv.js" as Mpv

// The plugin's manifest-backed settings. Keep these fallbacks in sync with
// manifest.json; normalize untrusted inline values before exposing them to UI
// or playback behavior.
var DEFAULTS = {
  "skipSeconds": 15,
  "defaultSort": "Recently listened",
  "autoRemoveFinished": "Off",
  "showTitleInBar": "Off",
  "defaultSpeed": 1.0,
  "syncOnOpenHours": 6,
  "booksDir": "~/Audiobooks/Audible"
};
var PLUGIN_ID = "latentoperator.audible";

var SORTS = ["Recently listened", "Recently added", "Title", "Author"];
var SPEEDS = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0];

function normalize(raw) {
  var source = raw !== null && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
  return {
    "skipSeconds": _s.integer(source.skipSeconds, 5, 120, DEFAULTS.skipSeconds),
    "defaultSort": _s.choice(source.defaultSort, SORTS, DEFAULTS.defaultSort),
    "autoRemoveFinished": _s.toggle(source.autoRemoveFinished, DEFAULTS.autoRemoveFinished),
    "showTitleInBar": _s.toggle(source.showTitleInBar, DEFAULTS.showTitleInBar),
    "defaultSpeed": _s.speed(source.defaultSpeed),
    "syncOnOpenHours": _s.integer(source.syncOnOpenHours, 1, 48, DEFAULTS.syncOnOpenHours),
    "booksDir": typeof source.booksDir === "string" && source.booksDir.trim().length > 0
      ? source.booksDir.trim() : DEFAULTS.booksDir
  };
}

function shouldForward(moduleName, raw) {
  return String(moduleName || "") === PLUGIN_ID;
}

function applyStep(state, moduleName, raw) {
  var current = state && typeof state === "object" ? state : {};
  var received = current.settingsReceived === true;
  if (!shouldForward(moduleName, raw)) {
    return { "accepted": false, "state": { "settingsReceived": received }, "settings": null };
  }
  return {
    "accepted": true,
    "state": { "settingsReceived": true },
    "settings": normalize(raw)
  };
}

function shouldApplySpeed(settingsReceived, storeLoaded) {
  return settingsReceived === true && storeLoaded === true;
}

function sortKey(label) {
  if (label === "Recently added") return "added";
  if (label === "Title") return "title";
  if (label === "Author") return "author";
  return "recent";
}

// Saved speed is user-controlled by the pill. A setting marker stored with
// state.json distinguishes a changed default from an unchanged startup.
function speedChoice(savedSpeed, settingSpeed, lastAppliedSetting) {
  // The saved speed is whatever the pill last set: any 0.05 step in mpv's
  // range (Full's fine buttons), not only a preset. Validate it the way
  // Mpv.startSpeed does, or an upgrade would reset a fine-step speed.
  var saved = typeof savedSpeed === "number" && isFinite(savedSpeed)
    && savedSpeed >= Mpv.MIN_SPEED && savedSpeed <= Mpv.MAX_SPEED ? savedSpeed : null;
  var setting = _s.validSpeed(settingSpeed);
  if (setting === null) setting = DEFAULTS.defaultSpeed;
  var changed = lastAppliedSetting !== null && lastAppliedSetting !== undefined
    && _s.validSpeed(lastAppliedSetting) !== setting;
  var fresh = lastAppliedSetting === null || lastAppliedSetting === undefined;
  var apply = changed || (fresh && saved === null);
  return { "apply": apply, "speed": apply ? setting : saved };
}

var _s = {};
_s.integer = function(value, min, max, fallback) {
  if (typeof value === "string" && /^\s*\d+\s*$/.test(value)) value = Number(value);
  if (typeof value !== "number" || !isFinite(value) || Math.floor(value) !== value || value < min || value > max) return fallback;
  return value;
};
_s.choice = function(value, choices, fallback) {
  if (typeof value !== "string") return fallback;
  var normalized = value.trim().toLowerCase();
  for (var i = 0; i < choices.length; i++) {
    if (choices[i].toLowerCase() === normalized) return choices[i];
  }
  return fallback;
};
_s.toggle = function(value, fallback) {
  if (value === true) return "On";
  if (value === false) return "Off";
  return _s.choice(value, ["On", "Off"], fallback);
};
_s.validSpeed = function(value) {
  if (typeof value === "string") {
    value = value.trim().replace(/[×xX]$/, "");
    if (value.length === 0) return null;
    value = Number(value);
  }
  if (typeof value !== "number" || !isFinite(value)) return null;
  for (var i = 0; i < SPEEDS.length; i++) if (Math.abs(value - SPEEDS[i]) < 1e-6) return SPEEDS[i];
  return null;
};
_s.speed = function(value) {
  var speed = _s.validSpeed(value);
  return speed === null ? DEFAULTS.defaultSpeed : speed;
};

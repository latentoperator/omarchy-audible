.pragma library

// mpv JSON IPC logic for PlayerController (ARCHITECTURE 5.1, S5 pitfalls).
//
// mpv speaks one JSON object per line over its unix socket. This file turns
// those lines into plain state, builds the command arrays, and holds the small
// decisions (retry/backoff, skip targets, the sleep-timer fade) so the QML can
// stay wiring. Pure ECMAScript for the Qt JS engine: no imports, no Qt types,
// and nothing here throws on bad input.

// Properties the controller observes. The position in this list is the
// observe id, so keep it stable.
var OBSERVED = [
  "time-pos", "duration", "pause", "speed", "chapter", "chapter-list",
  "path", "idle-active", "eof-reached", "volume"
];

var MIN_SPEED = 0.5;
var MAX_SPEED = 3.0;

// Reconnect: `backoffMs` grows by step and caps; the caller stops after
// MAX_ATTEMPTS so an absent mpv costs nothing (S5 pitfall 5).
var BACKOFF_BASE_MS = 300;
var BACKOFF_STEP_MS = 300;
var BACKOFF_CAP_MS = 2000;
var MAX_ATTEMPTS = 6;

// Sleep timer fade length.
var FADE_MS = 5000;

// A fresh, empty observed-property record.
function emptyState() {
  return {
    "time-pos": null, "duration": null, "pause": null, "speed": null,
    "chapter": null, "chapter-list": [], "path": null, "idle-active": null,
    "eof-reached": null, "volume": null
  };
}

// The argv for the observe_property commands, one per observed property.
function observeCommands() {
  var commands = [];
  for (var index = 0; index < OBSERVED.length; index++) {
    commands.push(["observe_property", index + 1, OBSERVED[index]]);
  }
  return commands;
}

// One socket line to a record, or null. Kinds: property, reply, event.
function parseMessage(line) {
  if (isNull(line)) {
    return null;
  }
  var message;
  try {
    message = JSON.parse(String(line));
  } catch (error) {
    return null;
  }
  if (message === null || typeof message !== "object" || Array.isArray(message)) {
    return null;
  }
  if (message.event === "property-change" && typeof message.name === "string") {
    return { "kind": "property", "name": message.name, "data": message.data === undefined ? null : message.data };
  }
  if (typeof message.event === "string") {
    return { "kind": "event", "event": message.event, "reason": message.reason === undefined ? null : message.reason };
  }
  if (message.request_id !== undefined) {
    var failed = typeof message.error === "string" && message.error !== "success";
    return { "kind": "reply", "id": message.request_id, "error": failed ? message.error : null, "data": message.data === undefined ? null : message.data };
  }
  return null;
}

// Copy of `state` with one property updated. Unknown names are ignored.
function applyProperty(state, name, data) {
  var next = {};
  for (var key in state) {
    next[key] = state[key];
  }
  if (OBSERVED.indexOf(name) !== -1) {
    next[name] = data === undefined ? null : data;
  }
  return next;
}

// The values the UI binds to, from the raw observed state.
function derive(state) {
  var chapters = parseChapters(state["chapter-list"]);
  var path = typeof state["path"] === "string" ? state["path"] : "";
  var loaded = path.length > 0 && state["idle-active"] !== true;
  var chapterIndex = typeof state["chapter"] === "number" ? state["chapter"] : -1;
  return {
    "loaded": loaded,
    "playing": loaded && state["pause"] === false,
    "path": path,
    "positionMs": toMs(state["time-pos"]),
    "durationMs": toMs(state["duration"]),
    "chapters": chapters,
    "chapterIndex": chapterIndex,
    "speed": typeof state["speed"] === "number" ? state["speed"] : 1,
    "volume": typeof state["volume"] === "number" ? state["volume"] : 100,
    "eof": state["eof-reached"] === true
  };
}

// mpv's chapter-list [{title,time}] to [{title,startMs}].
function parseChapters(list) {
  var chapters = [];
  if (!Array.isArray(list)) {
    return chapters;
  }
  for (var index = 0; index < list.length; index++) {
    var item = list[index];
    if (isNull(item) || typeof item !== "object" || typeof item.time !== "number") {
      continue;
    }
    chapters.push({ "title": typeof item.title === "string" ? item.title : "", "startMs": Math.round(item.time * 1000) });
  }
  return chapters;
}

function toMs(seconds) {
  return typeof seconds === "number" && isFinite(seconds) ? Math.round(seconds * 1000) : 0;
}

// ---- commands (argv arrays for mpv's `command` field) ----

function loadCommand(path, startSec) {
  var start = typeof startSec === "number" && startSec > 0 ? startSec : 0;
  return ["loadfile", String(path), "replace", 0, "start=" + start];
}

function pauseCommand(paused) {
  return ["set_property", "pause", paused === true];
}

function skipCommand(seconds) {
  return ["seek", Number(seconds) || 0, "relative"];
}

function seekCommand(seconds) {
  return ["seek", Math.max(0, Number(seconds) || 0), "absolute"];
}

function chapterCommand(index) {
  return ["set_property", "chapter", index];
}

function speedCommand(speed) {
  return ["set_property", "speed", clampSpeed(speed)];
}

function volumeCommand(volume) {
  return ["set_property", "volume", Math.max(0, Math.min(130, Number(volume) || 0))];
}

function clampSpeed(speed) {
  var value = Number(speed);
  if (!isFinite(value) || value <= 0) {
    return 1;
  }
  return Math.max(MIN_SPEED, Math.min(MAX_SPEED, value));
}

// The chapter index a +/-delta jump lands on, or -1 when there is nowhere to
// go (no chapters, or already at the first/last one).
function chapterTarget(chapterIndex, chapterCount, delta) {
  if (typeof chapterCount !== "number" || chapterCount <= 0 || typeof chapterIndex !== "number") {
    return -1;
  }
  var target = chapterIndex + delta;
  if (target < 0 || target >= chapterCount || target === chapterIndex) {
    return -1;
  }
  return target;
}

// ---- connection retry ----

function backoffMs(attempt) {
  var n = Math.max(0, Number(attempt) || 0);
  return Math.min(BACKOFF_CAP_MS, BACKOFF_BASE_MS + n * BACKOFF_STEP_MS);
}

// Keep retrying only while a book is wanted and the cap is not reached.
function shouldRetry(attempt, wanted) {
  return wanted === true && (Number(attempt) || 0) < MAX_ATTEMPTS;
}

// ---- sleep timer ----

// Volume during the fade: full until the last `fadeMs`, then linear to 0.
function fadeVolume(baseVolume, remainingMs, fadeMs) {
  var fade = typeof fadeMs === "number" && fadeMs > 0 ? fadeMs : FADE_MS;
  if (remainingMs >= fade) {
    return baseVolume;
  }
  if (remainingMs <= 0) {
    return 0;
  }
  return baseVolume * (remainingMs / fade);
}

// Where the current chapter ends, in ms: the next chapter's start, or the
// book's end for the last one. -1 when unknown.
function chapterEndMs(chapters, chapterIndex, durationMs) {
  if (!Array.isArray(chapters) || chapterIndex < 0 || chapterIndex >= chapters.length) {
    return -1;
  }
  if (chapterIndex + 1 < chapters.length) {
    return chapters[chapterIndex + 1].startMs;
  }
  return durationMs > 0 ? durationMs : -1;
}

// An end-of-chapter timer, fixed to where the current chapter ends when it is
// set, so it does not move on when playback reaches the next chapter. Null
// when the chapter end is unknown.
function chapterSleepTimer(chapters, chapterIndex, durationMs) {
  var end = chapterEndMs(chapters, chapterIndex, durationMs);
  return end < 0 ? null : { "mode": "chapter", "endMs": end };
}

// Wall-clock ms until the sleep timer fires. Minutes mode counts real time;
// chapter mode counts media time left until the fixed chapter end, at the
// current speed.
function sleepRemainingMs(timer, nowMs, positionMs, speed) {
  if (isNull(timer)) {
    return -1;
  }
  if (timer.mode === "minutes") {
    return timer.endsAtMs - nowMs;
  }
  if (timer.mode === "chapter" && typeof timer.endMs === "number") {
    return (timer.endMs - positionMs) / (speed > 0 ? speed : 1);
  }
  return -1;
}

function isNull(value) {
  return value === null || value === undefined;
}

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
    "hasPosition": typeof state["time-pos"] === "number",
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

// `loadfile` for a book. With no `options` this is the plain form used for an
// old unlocked `.m4b`. With `{lavf, chaptersFile}` it becomes mpv's per-file
// option map: mpv >= 0.38 takes the index (-1 = "no index") before the map
// (ARCHITECTURE 5.1). Empty or null option values are left out, so an old book
// and a locked one both load through this one function.
function loadCommand(path, startSec, options) {
  var start = typeof startSec === "number" && startSec > 0 ? startSec : 0;
  if (isNull(options) || typeof options !== "object" || Array.isArray(options)) {
    return ["loadfile", String(path), "replace", 0, "start=" + start];
  }
  var map = { "start": String(start) };
  if (typeof options.lavf === "string" && options.lavf.length > 0) {
    map["demuxer-lavf-o"] = options.lavf;
  }
  if (typeof options.chaptersFile === "string" && options.chaptersFile.length > 0) {
    map["chapters-file"] = options.chaptersFile;
  }
  return ["loadfile", String(path), "replace", -1, map];
}

// The `loadCommand` options for a book from `play-info`'s {lavf, chaptersFile},
// or null when both are empty (an old `.m4b`), so that book keeps the plain
// loadfile form it has always used.
function loadOptions(options) {
  if (isNull(options) || typeof options !== "object") {
    return null;
  }
  var lavf = typeof options.lavf === "string" ? options.lavf : "";
  var chaptersFile = typeof options.chaptersFile === "string" ? options.chaptersFile : "";
  if (lavf.length === 0 && chaptersFile.length === 0) {
    return null;
  }
  return { "lavf": lavf, "chaptersFile": chaptersFile };
}

// Drop the key material from mpv's options after the file is loaded: the key is
// readable over the socket while `demuxer-lavf-o` is set (SPIKE-RESULTS S7).
function clearKeyCommand() {
  return ["set_property", "demuxer-lavf-o", ""];
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

// Whether a seek, skip or chapter jump sent now moves the file mpv shows as
// `path` (F38). Not while a later `loadfile` this controller sent (for
// `loadPath`) is still on its way: the move lands on that file, not on the
// book still showing. Nothing sent since connecting ("", a reattach) means the
// file showing is the one that moves. Comparing paths, not counting events,
// holds when one load overtakes another before it opens.
function moveHitsPath(path, loadPath) {
  if (typeof loadPath !== "string" || loadPath.length === 0) {
    return true;
  }
  return typeof path === "string" && path === loadPath;
}

// Where a user's move lands, in milliseconds, so it can be saved before mpv
// reports it (F38): "skip" by `value` seconds from `positionMs`, "seek" to
// `value` ms, or "chapter" to chapter `value`'s start. Clamped to the book:
// mpv runs with --keep-open, so a seek past the end stops at the end. -1 when
// it can't be known (no duration, no such chapter, a bad value).
function moveTargetMs(kind, value, positionMs, durationMs, chapters) {
  var duration = Number(durationMs);
  if (!isFinite(duration) || duration <= 0) {
    return -1;
  }
  var target = -1;
  if (kind === "skip" && typeof value === "number" && isFinite(value) && typeof positionMs === "number" && isFinite(positionMs)) {
    target = positionMs + value * 1000;
  } else if (kind === "seek" && typeof value === "number" && isFinite(value)) {
    target = value;
  } else if (kind === "chapter" && Array.isArray(chapters) && typeof value === "number" && value >= 0 && value < chapters.length
      && !isNull(chapters[value]) && typeof chapters[value].startMs === "number") {
    target = chapters[value].startMs;
  } else {
    return -1;
  }
  return Math.round(Math.max(0, Math.min(duration, target)));
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
    // Held while paused (F23): the time left doesn't move.
    if (typeof timer.remainingMs === "number") {
      return timer.remainingMs;
    }
    return timer.endsAtMs - nowMs;
  }
  if (timer.mode === "chapter" && typeof timer.endMs === "number") {
    return (timer.endMs - positionMs) / (speed > 0 ? speed : 1);
  }
  return -1;
}

// A minutes timer that is set now. While paused it holds its length and
// starts counting on resume (F23); playing, it ends `minutes` from now.
function minutesSleepTimer(minutes, nowMs, playing) {
  var ms = Number(minutes) * 60000;
  if (!isFinite(ms) || ms <= 0) {
    return null;
  }
  return playing === true ? { "mode": "minutes", "endsAtMs": nowMs + ms } : { "mode": "minutes", "remainingMs": ms };
}

// Pausing: a running minutes timer keeps the time it has left instead of its
// wall-clock end, so time spent paused doesn't count (F23). Anything else is
// returned as it is.
function holdSleepTimer(timer, nowMs) {
  if (isNull(timer) || timer.mode !== "minutes" || typeof timer.endsAtMs !== "number") {
    return timer;
  }
  return { "mode": "minutes", "remainingMs": Math.max(0, timer.endsAtMs - nowMs) };
}

// Resuming: a held minutes timer ends the time it had left from now.
function resumeSleepTimer(timer, nowMs) {
  if (isNull(timer) || timer.mode !== "minutes" || typeof timer.remainingMs !== "number") {
    return timer;
  }
  return { "mode": "minutes", "endsAtMs": nowMs + timer.remainingMs };
}

// ---- saved volume and speed (F21) ----

// The volume to save: the one before a sleep fade began, if one is running,
// so a fade never becomes the saved volume.
function userVolume(volume, fadeBaseVolume) {
  return typeof fadeBaseVolume === "number" && fadeBaseVolume >= 0 ? fadeBaseVolume : volume;
}

// The volume a new mpv starts with: the saved one if it is a number in
// mpv's 0–130 range, else `fallback`.
function startVolume(saved, fallback) {
  if (typeof saved === "number" && isFinite(saved) && saved >= 0 && saved <= 130) {
    return Math.round(saved);
  }
  return fallback;
}

// The speed a new mpv starts with: the saved one if it is a number in range
// (MIN_SPEED–MAX_SPEED), else 1.
function startSpeed(saved) {
  if (typeof saved === "number" && isFinite(saved) && saved >= MIN_SPEED && saved <= MAX_SPEED) {
    return saved;
  }
  return 1;
}

function isNull(value) {
  return value === null || value === undefined;
}

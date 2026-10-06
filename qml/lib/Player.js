.pragma library

// Player view decisions for the Mini and Full views (SCOPE FR-U3, FR-U4,
// FR-P2, FR-P3): chapter labels and rows, the speed pill and its preset cycle,
// the scrub bar's ticks and when a seek has landed. The views bind to these
// and call the player; they decide nothing themselves.
//
// Pure ECMAScript for the Qt JS engine: no imports, no Qt types, and nothing
// here throws on bad input. Times are milliseconds.

// The speed pill's presets, in cycle order (FR-P2: 0.75–3.0×).
var SPEED_PRESETS = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0];

// Two speeds this close are the same preset (mpv reports binary fractions).
// Small enough that a real non-preset speed (1.2495) never counts as one.
var SPEED_EPSILON = 1e-6;

// More chapters than this and the scrub bar shows no chapter ticks: at 100+
// they would merge into a solid band.
var MAX_TICKS = 40;

// A seek has landed once the player reports a position this close to it.
var SEEK_SETTLE_MS = 1500;

// Glyphs from the theme's icon font (Font Awesome, as the bar uses).
var GLYPH_PREV_CHAPTER = "";
var GLYPH_NEXT_CHAPTER = "";
var GLYPH_MAXIMIZE = "";
var GLYPH_DISMISS = "";
var GLYPH_CHAPTERS = "";

function isNumber(value) {
  return typeof value === "number" && isFinite(value);
}

// The label for chapter `index`: its trimmed title, or "Chapter N" (1-based)
// when the title is empty. "" when there is no such chapter.
function chapterLabel(chapters, index) {
  if (!Array.isArray(chapters) || !isNumber(index) || index < 0 || index >= chapters.length
      || Math.floor(index) !== index) {
    return "";
  }
  var chapter = chapters[index];
  var title = chapter && typeof chapter.title === "string" ? chapter.title.trim() : "";
  return title.length > 0 ? title : "Chapter " + (index + 1);
}

// Where chapter `index` starts, or -1 when it is unknown.
function chapterStartMs(chapters, index) {
  if (!Array.isArray(chapters) || !isNumber(index) || index < 0 || index >= chapters.length) return -1;
  var chapter = chapters[index];
  return chapter && isNumber(chapter.startMs) && chapter.startMs >= 0 ? chapter.startMs : -1;
}

// How long chapter `index` runs: to the next chapter's start, or to the end of
// the book for the last one. -1 when unknown.
function chapterDurationMs(chapters, index, durationMs) {
  var start = chapterStartMs(chapters, index);
  if (start < 0) return -1;
  var end = index + 1 < chapters.length ? chapterStartMs(chapters, index + 1)
    : (isNumber(durationMs) && durationMs > 0 ? durationMs : -1);
  return end < start ? -1 : end - start;
}

// Whether ⏮ (delta -1) or ⏭ (delta 1) has a chapter to go to: the same rule
// as `Mpv.chapterTarget`, which the player uses for the jump.
function canJumpChapter(chapterIndex, chapterCount, delta) {
  if (!isNumber(chapterIndex) || !isNumber(chapterCount) || chapterCount <= 0 || chapterIndex < 0) return false;
  if (delta !== 1 && delta !== -1) return false;
  var target = chapterIndex + delta;
  return target >= 0 && target < chapterCount;
}

// One row per chapter for a chapter list: {index, label, startMs, durationMs}.
// A malformed entry still gets a row (label "Chapter N", times -1), so row
// numbers always match mpv's chapter indexes.
function chapterRows(chapters, durationMs) {
  var rows = [];
  if (!Array.isArray(chapters)) return rows;
  for (var i = 0; i < chapters.length; i++) {
    rows.push({
      "index": i,
      "label": chapterLabel(chapters, i),
      "startMs": chapterStartMs(chapters, i),
      "durationMs": chapterDurationMs(chapters, i, durationMs)
    });
  }
  return rows;
}

// The speed pill's text: "1.0×", "1.25×", "0.75×", "2.0×".
function speedLabel(speed) {
  var value = isNumber(speed) && speed > 0 ? speed : 1;
  var rounded = Math.round(value * 100) / 100;
  var text = Math.abs(rounded * 10 - Math.round(rounded * 10)) < SPEED_EPSILON
    ? rounded.toFixed(1) : rounded.toFixed(2);
  return text + "×";
}

// The preset a click on the pill moves to: the next preset above `speed`, so
// a preset steps to the following one and any other speed snaps up to the
// nearest preset above it. Past the last preset it wraps to the first. Bad
// input gives 1.0.
function nextSpeed(speed) {
  if (!isNumber(speed) || speed <= 0) return 1.0;
  for (var i = 0; i < SPEED_PRESETS.length; i++) {
    if (SPEED_PRESETS[i] > speed + SPEED_EPSILON) return SPEED_PRESETS[i];
  }
  return SPEED_PRESETS[0];
}

// Where chapter ticks go on a book-level scrub bar, as fractions in (0, 1):
// one per chapter start after the first. Empty when the book has more than
// `maxTicks` chapters (default MAX_TICKS), or nothing is known.
function tickFractions(chapters, durationMs, maxTicks) {
  var limit = isNumber(maxTicks) ? maxTicks : MAX_TICKS;
  if (!Array.isArray(chapters) || chapters.length > limit || !isNumber(durationMs) || durationMs <= 0) return [];
  var ticks = [];
  for (var i = 1; i < chapters.length; i++) {
    var start = chapterStartMs(chapters, i);
    if (start > 0 && start < durationMs) ticks.push(start / durationMs);
  }
  return ticks;
}

// The scrub bar's position as a fraction of the book, clamped to [0, 1].
function fraction(positionMs, durationMs) {
  if (!isNumber(positionMs) || !isNumber(durationMs) || durationMs <= 0) return 0;
  return Math.max(0, Math.min(1, positionMs / durationMs));
}

// The book position under a fraction of the scrub bar, whole milliseconds.
function positionAt(fractionValue, durationMs) {
  if (!isNumber(fractionValue) || !isNumber(durationMs) || durationMs <= 0) return 0;
  return Math.round(Math.max(0, Math.min(1, fractionValue)) * durationMs);
}

// After a release the bar shows the seek target until the seek has landed,
// so the handle doesn't jump back to the old spot first. A position report
// alone can't prove that (one sent just before the seek can sit anywhere
// near the target), so the bar waits for mpv's playback-restart after the
// release (`restartsNow` > `restartsAtRelease`) and then for a position near
// the target. ScrubBar also lets go after a few seconds.
function seekSettled(positionMs, targetMs, restartsAtRelease, restartsNow) {
  if (!isNumber(targetMs) || targetMs < 0) return true;
  if (!isNumber(positionMs) || !isNumber(restartsAtRelease) || !isNumber(restartsNow)) return false;
  if (restartsNow <= restartsAtRelease) return false;
  return Math.abs(positionMs - targetMs) <= SEEK_SETTLE_MS;
}

// ---- Full view (U6) ----

// Fine speed control: ±0.05 steps, clamped to FR-P2's 0.75–3.0.
var SPEED_STEP = 0.05;
var SPEED_MIN = 0.75;
var SPEED_MAX = 3.0;

// Sleep timer choices in minutes, plus end of chapter (FR-P2).
var SLEEP_MINUTES = [15, 30, 45, 60];

// After the user scrolls the chapter list, leave it alone this long before
// following the current chapter again.
var USER_SCROLL_HOLD_MS = 4000;

var GLYPH_COLLAPSE = "";
var GLYPH_MOON = "";
var GLYPH_SLOWER = "";
var GLYPH_FASTER = "";

// `fullKeyAction` results.
var KEY_COLLAPSE = "collapse";
var KEY_NONE = "none";

function round2(value) {
  return Math.round(value * 100) / 100;
}

// Whole percent of the book heard, 0–100; 100 only at the very end.
function percentComplete(positionMs, durationMs) {
  if (!isNumber(positionMs) || !isNumber(durationMs) || durationMs <= 0) return 0;
  return Math.max(0, Math.min(100, Math.floor(positionMs / durationMs * 100)));
}

// Real time left to listen at `speed`, in ms; 0 when unknown or finished.
function leftAtSpeedMs(positionMs, durationMs, speed) {
  if (!isNumber(positionMs) || !isNumber(durationMs) || durationMs <= 0) return 0;
  var rate = isNumber(speed) && speed > 0 ? speed : 1;
  return Math.round(Math.max(0, durationMs - Math.max(0, positionMs)) / rate);
}

// The speed one fine step slower (direction -1) or faster (1), on the 0.05
// grid and clamped to 0.75–3.0. A speed off the grid moves to the next grid
// value in that direction. Bad input gives 1.0.
function fineSpeed(speed, direction) {
  if (!isNumber(speed) || speed <= 0) return 1.0;
  var steps = speed / SPEED_STEP;
  var onGrid = Math.abs(steps - Math.round(steps)) < SPEED_EPSILON * 100;
  var next;
  if (direction === 1) next = (onGrid ? Math.round(steps) + 1 : Math.ceil(steps)) * SPEED_STEP;
  else if (direction === -1) next = (onGrid ? Math.round(steps) - 1 : Math.floor(steps)) * SPEED_STEP;
  else return round2(Math.max(SPEED_MIN, Math.min(SPEED_MAX, speed)));
  return round2(Math.max(SPEED_MIN, Math.min(SPEED_MAX, next)));
}

// Whether a fine step in `direction` would change the speed.
function canFineStep(speed, direction) {
  if (!isNumber(speed) || speed <= 0) return false;
  return Math.abs(fineSpeed(speed, direction) - speed) > SPEED_EPSILON;
}

// Whether `speed` is `preset` (for the selected chip).
function isSpeed(speed, preset) {
  return isNumber(speed) && isNumber(preset) && Math.abs(speed - preset) < SPEED_EPSILON;
}

// The narrators line's names (the view joins them with `Format.names`).
function narrators(row) {
  if (!row || !Array.isArray(row.narrators)) return [];
  var list = [];
  for (var i = 0; i < row.narrators.length; i++) {
    var name = row.narrators[i];
    if (typeof name === "string" && name.trim().length > 0) list.push(name.trim());
  }
  return list;
}

// "0:05", "12:40", "1:00:00" for a countdown; rounds up so it never shows
// 0:00 while time is left.
function countdown(ms) {
  var seconds = Math.max(0, Math.ceil(ms / 1000));
  var h = Math.floor(seconds / 3600);
  var m = Math.floor((seconds % 3600) / 60);
  var s = seconds % 60;
  var ss = (s < 10 ? "0" : "") + s;
  if (h === 0) return m + ":" + ss;
  return h + ":" + (m < 10 ? "0" : "") + m + ":" + ss;
}

// The sleep timer line: "" with no timer, "At end of chapter" for a
// chapter timer, "Sleeping in 12:40" for a minutes timer. `remainingMs` is
// `Mpv.sleepRemainingMs` output.
function sleepText(timer, remainingMs) {
  if (!timer || typeof timer !== "object") return "";
  if (timer.mode === "chapter") return "At end of chapter";
  if (timer.mode === "minutes") return "Sleeping in " + countdown(isNumber(remainingMs) ? remainingMs : 0);
  return "";
}

// Whether the chapter list should scroll itself to the current chapter: not
// while the user is scrolling it, nor within USER_SCROLL_HOLD_MS of the end
// of their last scroll.
function followChapter(nowMs, userScrolledAtMs, userMoving) {
  if (userMoving === true) return false;
  if (!isNumber(userScrolledAtMs) || userScrolledAtMs <= 0) return true;
  if (!isNumber(nowMs)) return false;
  return nowMs - userScrolledAtMs >= USER_SCROLL_HOLD_MS;
}

// A text key in the Full view: Backspace ("\b") collapses to Mini.
function fullKeyAction(view, text) {
  return view === "full" && text === "\b" ? KEY_COLLAPSE : KEY_NONE;
}

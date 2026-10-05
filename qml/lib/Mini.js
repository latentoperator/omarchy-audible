.pragma library

// Mini view decisions (SCOPE FR-U3, U2a subset): what the title line says,
// the time left, and which player action a key press means while the Mini
// (or, from U5, the Full) view is showing. The view binds to these and calls
// the player; it decides nothing itself.
//
// Pure ECMAScript for the Qt JS engine: no imports, no Qt types, and nothing
// here throws on bad input.

// Seconds one skip moves. Fixed until the setting arrives in R1.
var SKIP_SECONDS = 15;

// Shown when the loaded file has no catalog row, or the row has no title.
var UNKNOWN_TITLE = "Unknown title";

// Glyphs from the theme's icon font (Font Awesome, as the bar uses).
var GLYPH_BACK = "";
var GLYPH_FORWARD = "";
var GLYPH_PLAY = "";
var GLYPH_PAUSE = "";
var GLYPH_LIBRARY = "";

// `keyAction` results.
var ACTION_TOGGLE = "toggle";
var ACTION_BACK = "back";
var ACTION_FORWARD = "forward";
var ACTION_NONE = "none";

// The title to show for the loaded book's row.
function title(row) {
  if (row && typeof row.title === "string" && row.title.trim().length > 0) {
    return row.title.trim();
  }
  return UNKNOWN_TITLE;
}

// Milliseconds left, never negative; 0 when either value is unusable.
function remainingMs(positionMs, durationMs) {
  if (typeof positionMs !== "number" || typeof durationMs !== "number") return 0;
  if (!isFinite(positionMs) || !isFinite(durationMs) || durationMs <= 0) return 0;
  return Math.max(0, durationMs - Math.max(0, positionMs));
}

// The play button's glyph: pause while playing, play otherwise.
function playGlyph(playing) {
  return playing === true ? GLYPH_PAUSE : GLYPH_PLAY;
}

// What a panel key means in `view` (ARCHITECTURE 6): Space toggles, ←/→
// skip back/forward, in Mini and Full only and only with a book loaded.
// `kind` is "activate" (Space or Enter from the key catcher) or "move" with
// `dx` -1/1; vertical moves and anything else do nothing here.
function keyAction(view, loaded, kind, dx) {
  if (loaded !== true || (view !== "mini" && view !== "full")) return ACTION_NONE;
  if (kind === "activate") return ACTION_TOGGLE;
  if (kind === "move") {
    if (dx === -1) return ACTION_BACK;
    if (dx === 1) return ACTION_FORWARD;
  }
  return ACTION_NONE;
}

// The skip in seconds for a back/forward action, else 0.
function skipSeconds(action) {
  if (action === ACTION_BACK) return -SKIP_SECONDS;
  if (action === ACTION_FORWARD) return SKIP_SECONDS;
  return 0;
}

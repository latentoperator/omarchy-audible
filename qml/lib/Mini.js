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

// Shown when nothing is loaded.
var NOTHING_PLAYING = "Nothing playing";

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

// The title line: "Nothing playing" when nothing is loaded, else the row's
// title, or "Unknown title" when the file has no catalog row or no title.
function title(loaded, row) {
  if (loaded !== true) return NOTHING_PLAYING;
  if (row && typeof row.title === "string" && row.title.trim().length > 0) {
    return row.title.trim();
  }
  return UNKNOWN_TITLE;
}

// The authors to list under the title (the view formats them with
// `Format.names`); empty, and the line hidden, when nothing is loaded or the
// row has no author names.
function authors(loaded, row) {
  if (loaded !== true || !row || !Array.isArray(row.authors)) return [];
  var list = [];
  for (var i = 0; i < row.authors.length; i++) {
    var name = row.authors[i];
    if (typeof name === "string" && name.trim().length > 0) list.push(name.trim());
  }
  return list;
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
// `kind` is "space", "enter" or "move" with `dx` -1/1. Enter does nothing
// here (in ARCHITECTURE 6 it plays the selected Library row, so it must never
// pause the book that is playing); vertical moves do nothing either.
function keyAction(view, loaded, kind, dx) {
  if (loaded !== true || (view !== "mini" && view !== "full")) return ACTION_NONE;
  if (kind === "space") return ACTION_TOGGLE;
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

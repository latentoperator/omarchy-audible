.pragma library

// Bar widget and panel decisions (SCOPE FR-U1, FR-U5). The service owns the
// state; the widgets, one per monitor, bind to what these return.
//
// Pure ECMAScript for the Qt JS engine: no imports, no Qt types, and nothing
// here throws on bad input.

var VIEW_ONBOARDING = "onboarding";
var VIEW_LIBRARY = "library";
var VIEW_MINI = "mini";
var VIEW_FULL = "full";

// The panel's view stack, in order.
var VIEWS = [VIEW_ONBOARDING, VIEW_LIBRARY, VIEW_MINI, VIEW_FULL];

// Theme icon-font glyphs (Font Awesome code points, as the stock bar uses).
var GLYPH_BOOK = "";
var GLYPH_PLAYING = "";
var GLYPH_PAUSED = "";

// Longest title the bar shows before it is cut with an ellipsis.
var TITLE_MAX = 32;

// Index of `view` in the stack; an unknown view falls back to Library.
function viewIndex(view) {
  var index = VIEWS.indexOf(view);
  return index === -1 ? VIEWS.indexOf(VIEW_LIBRARY) : index;
}

// The bar glyph: the book when nothing is loaded, else the play state.
function glyph(loaded, playing) {
  if (loaded !== true) {
    return GLYPH_BOOK;
  }
  return playing === true ? GLYPH_PLAYING : GLYPH_PAUSED;
}

// The title shown next to the glyph, or "" when the bar shows the glyph only:
// the setting is off, the bar is vertical, nothing is loaded, or no title.
function barTitle(setting, vertical, loaded, title) {
  if (setting !== "On" || vertical === true || loaded !== true || typeof title !== "string") {
    return "";
  }
  var text = title.trim();
  if (text.length <= TITLE_MAX) {
    return text;
  }
  return text.slice(0, TITLE_MAX - 1).trim() + "…";
}

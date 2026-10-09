.pragma library
.import "Glyphs.js" as Glyphs

// Bar widget and panel decisions (SCOPE FR-U1, FR-U5). The service owns the
// state; the widgets, one per monitor, bind to what these return.
//
// Pure ECMAScript for the Qt JS engine: no imports but `Glyphs.js`, no Qt
// types, and nothing here throws on bad input.

var VIEW_ONBOARDING = "onboarding";
var VIEW_LIBRARY = "library";
var VIEW_MINI = "mini";
var VIEW_FULL = "full";

// The panel's view stack, in order.
var VIEWS = [VIEW_ONBOARDING, VIEW_LIBRARY, VIEW_MINI, VIEW_FULL];

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
    return Glyphs.GLYPH_BOOK;
  }
  return playing === true ? Glyphs.GLYPH_PLAYING : Glyphs.GLYPH_PAUSED;
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

// A dismissal (a click outside, on this or another monitor) while the Mini
// chapter popup is open closes only the popup; the panel stays (U5).
function dismissClosesPanel(view, chapterListOpen) {
  return !(view === VIEW_MINI && chapterListOpen === true);
}

// Whether a Mini view shows the chapter popup: the shared flag is set and that
// view's own panel is open (H1 F25). Every monitor has a Mini view; a closed
// panel's must never open its modal popup.
function chapterPopupShown(chapterListOpen, panelOpen) {
  return chapterListOpen === true && panelOpen === true;
}

// A switch or reconnect briefly has no loaded path while playback is still
// wanted. Reconcile the view only after an actual unload.
function libraryAfterUnload(loaded, wanted) {
  return loaded !== true && wanted !== true;
}

// The panel's content width and height cap per view, in unscaled units for
// `Style.space`. The Full view grows the same drawer (ARCHITECTURE 6).
var WIDTH = 420;
var HEIGHT_CAP = 560;
var FULL_WIDTH = 680;
var FULL_HEIGHT_CAP = 760;

function contentWidth(view) {
  return view === VIEW_FULL ? FULL_WIDTH : WIDTH;
}

function heightCap(view) {
  return view === VIEW_FULL ? FULL_HEIGHT_CAP : HEIGHT_CAP;
}

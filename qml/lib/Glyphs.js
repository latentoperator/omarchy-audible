.pragma library

// Every icon-font glyph the plugin shows, defined once (P9, F28). Font
// Awesome code points from the theme's icon font, as the stock bar uses.
// Views reference `Glyphs.GLYPH_*`; a lib that picks a glyph in logic
// `.import`s this file.
//
// Pure ECMAScript for the Qt JS engine: no imports, no Qt types.

// The bar (Panel.glyph) and a cover with no art.
var GLYPH_BOOK = "";
var GLYPH_PLAYING = "";
var GLYPH_PAUSED = "";

// Transport and the Library button (Mini.playGlyph picks play or pause).
var GLYPH_BACK = "";
var GLYPH_FORWARD = "";
var GLYPH_PLAY = "";
var GLYPH_PAUSE = "";
var GLYPH_LIBRARY = "";

// Mini and Full view controls.
var GLYPH_PREV_CHAPTER = "";
var GLYPH_NEXT_CHAPTER = "";
var GLYPH_MAXIMIZE = "";
var GLYPH_CHAPTERS = "";
var GLYPH_COLLAPSE = "";
var GLYPH_MOON = "";
var GLYPH_SLOWER = "";
var GLYPH_FASTER = "";

// Library rows and banners; GLYPH_DISMISS also closes the Mini and Full views.
var GLYPH_REMOVE = "";
var GLYPH_REFRESH = "";
var GLYPH_DISMISS = "";

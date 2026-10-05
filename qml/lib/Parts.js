.pragma library

// Decisions for the small shared parts in `qml/components/` (U4): where a
// book's cover lives, and which theme colour a state badge uses. The badge's
// kind and label come from `LibraryUi.badge`; this file only picks the tone.
//
// Pure ECMAScript for the Qt JS engine: no imports, no Qt types, and nothing
// here throws on bad input.

// Badge tones. A view maps each one to a `qs.Commons` colour token.
var TONE_ACCENT = "accent";
var TONE_URGENT = "urgent";
var TONE_TEXT = "text";
var TONE_MUTED = "muted";

// An Audible ASIN: ten upper-case letters or digits. Anything else could
// carry a path, so it never reaches a file URL.
var ASIN_PATTERN = /^[A-Z0-9]{10}$/;

// `file://` URL of `<dataDir>/covers/<asin>.jpg` (ARCHITECTURE file table),
// or "" when the data dir is unknown or the ASIN is not a plain ASIN. The
// cover may still be missing; the view shows its placeholder then.
function coverUrl(dataDir, asin) {
  if (typeof dataDir !== "string" || typeof asin !== "string") return "";
  var dir = dataDir.replace(/\/+$/, "");
  if (dir.length === 0 || dir.charAt(0) !== "/") return "";
  if (!ASIN_PATTERN.test(asin)) return "";
  return "file://" + dir + "/covers/" + asin + ".jpg";
}

// `{asin: true}` for each `<asin>.jpg` in a list of file names (the covers
// directory listing). Other names are skipped. Lets a cover skip loading a
// file that is not there, which Qt would log as a warning.
function coverSet(fileNames) {
  var set = {};
  if (!fileNames || typeof fileNames.length !== "number") return set;
  for (var i = 0; i < fileNames.length; i++) {
    var name = fileNames[i];
    if (typeof name !== "string" || name.length !== 14) continue;
    if (name.slice(10) !== ".jpg") continue;
    var asin = name.slice(0, 10);
    if (ASIN_PATTERN.test(asin)) set[asin] = true;
  }
  return set;
}

// Tone for a `LibraryUi.badge` kind: the book on this laptop stands out, a
// failure is urgent, work in progress reads as normal text, and cloud,
// offline and anything unknown are muted.
function badgeTone(kind) {
  if (kind === "local") return TONE_ACCENT;
  if (kind === "error") return TONE_URGENT;
  if (kind === "queued" || kind === "downloading" || kind === "converting") return TONE_TEXT;
  return TONE_MUTED;
}

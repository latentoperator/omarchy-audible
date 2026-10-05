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

// `file://` URL for an absolute path, each segment percent-encoded so a
// `#`, `?`, `%` or space in a directory name stays part of the path. Runs of
// `/` collapse to one (the same path on Linux), so a leading `//` can never
// read as a URL host. "" for anything that is not an absolute path.
function fileUrl(path) {
  if (typeof path !== "string" || path.length < 2 || path.charAt(0) !== "/") return "";
  var parts = path.replace(/\/{2,}/g, "/").replace(/\/+$/, "").split("/");
  for (var i = 0; i < parts.length; i++) parts[i] = encodeURIComponent(parts[i]);
  var joined = parts.join("/");
  return joined.length > 1 ? "file://" + joined : "";
}

// Whether `FolderListModel` can list this directory. It decodes its folder URL
// and parses the path again, so a literal `#`, `?` or `%` in the path lists
// the wrong place. Such a directory is not listed; covers then load without
// the presence check (`LibraryModel.hasCover` answers true) and without live
// refresh: a cover fetched or replaced later shows after a shell restart.
function listable(path) {
  return fileUrl(path).length > 0 && !/[#?%]/.test(path);
}

// `file://` URL of `<dataDir>/covers/<asin>.jpg` (ARCHITECTURE file table),
// or "" when the data dir is unknown or the ASIN is not a plain ASIN. A
// positive `version` (the file's modified time in ms) is added as `?v=`, so a
// cover that `sync` replaces is a new URL and is not served from Qt's image
// cache. The cover may still be missing; the view shows its placeholder then.
function coverUrl(dataDir, asin, version) {
  if (typeof asin !== "string" || !ASIN_PATTERN.test(asin)) return "";
  var dir = fileUrl(dataDir);
  if (dir.length === 0) return "";
  var url = dir + "/covers/" + asin + ".jpg";
  if (typeof version === "number" && isFinite(version) && version > 0) {
    url += "?v=" + Math.floor(version);
  }
  return url;
}

// `{asin: version}` for each `<asin>.jpg` in a covers directory listing, a
// list of `{name, modified}` (`modified` in ms; anything else counts as 1).
// Other names are skipped. Lets a cover skip loading a file that is not
// there, which Qt would log as a warning, and reload one that changed.
function coverSet(entries) {
  var set = {};
  if (!entries || typeof entries !== "object" || typeof entries.length !== "number") return set;
  for (var i = 0; i < entries.length; i++) {
    var entry = entries[i];
    if (!entry || typeof entry !== "object") continue;
    var name = entry.name;
    if (typeof name !== "string" || name.length !== 14) continue;
    if (name.slice(10) !== ".jpg") continue;
    var asin = name.slice(0, 10);
    if (!ASIN_PATTERN.test(asin)) continue;
    var modified = entry.modified;
    set[asin] = typeof modified === "number" && isFinite(modified) && modified > 0
      ? Math.floor(modified) : 1;
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

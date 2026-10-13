.pragma library

// Editing for the plugin's text fields (`components/BoundedTextField.qml`).
//
// Qt reads the clipboard by itself whenever an editable text field exists and
// the clipboard changes, with no size limit or deadline. The plugin's fields
// are therefore read-only to Qt for their whole life, and typing, deleting,
// cutting and pasting are done here instead. A paste never goes through Qt:
// the field runs `bin/omarchy-audible-paste`, which reads the clipboard
// outside the shell with a byte limit and a deadline.
//
// Pure ECMAScript for the Qt JS engine: no imports, no Qt types, and nothing
// here throws on bad input. Key and modifier values are Qt's (Qt::Key,
// Qt::KeyboardModifier).

// What a key press does in a field. `ACTION_PASS` leaves the key to Qt
// (cursor movement, selection, copy) or to the view (Esc, Enter, arrows).
var ACTION_PASS = "pass";
var ACTION_INSERT = "insert";
var ACTION_BACKSPACE = "backspace";
var ACTION_DELETE = "delete";
var ACTION_SELECT_ALL = "select-all";
var ACTION_CUT = "cut";
var ACTION_PASTE = "paste";

// The Library search field: the longest text it takes, and the largest
// clipboard a paste into it reads.
var SEARCH_MAX_CHARS = 256;
var SEARCH_PASTE_BYTES = 1024;

// The sign-in field: Amazon's page address after sign-in is about 1,500
// characters, so both leave plenty of room.
var SIGNIN_MAX_CHARS = 8192;
var SIGNIN_PASTE_BYTES = 16384;

// The paste helper's total deadline, in seconds. The field also stops the
// helper itself `PASTE_GRACE_MS` after that, in case it never exits.
var PASTE_TIMEOUT_S = 2;
var PASTE_GRACE_MS = 1500;

// The most helper output a field keeps while a paste runs, in characters.
// The helper writes JSON with every non-ASCII character escaped, so this is
// the byte limit times the longest escape (`\uXXXX`, six characters), plus
// the wrapper; anything longer is not the helper's answer and is dropped.
var PASTE_OUTPUT_MAX = 65536 * 6 + 64;

var _p = {};

_p.SHIFT = 0x02000000;
_p.CONTROL = 0x04000000;
_p.ALT = 0x08000000;
_p.META = 0x10000000;

_p.KEY_A = 0x41;
_p.KEY_V = 0x56;
_p.KEY_X = 0x58;
_p.KEY_BACKSPACE = 0x01000003;
_p.KEY_INSERT = 0x01000006;
_p.KEY_DELETE = 0x01000007;

_p.int = function (value, fallback) {
  return typeof value === "number" && isFinite(value) ? Math.floor(value) : fallback;
};

// Text a key may insert: something, and no control characters.
_p.printable = function (text) {
  if (typeof text !== "string" || text.length === 0) return false;
  for (var index = 0; index < text.length; index++) {
    var code = text.charCodeAt(index);
    if (code < 32 || code === 127) return false;
  }
  return true;
};

// UTF-16 surrogate halves, so Backspace and Delete never split an emoji.
_p.high = function (code) {
  return code >= 0xd800 && code <= 0xdbff;
};
_p.low = function (code) {
  return code >= 0xdc00 && code <= 0xdfff;
};

// What a key press does. `modifiers` is the event's bit mask, `text` the
// characters it types.
function keyAction(key, modifiers, text) {
  var mods = _p.int(modifiers, 0);
  var shift = (mods & _p.SHIFT) !== 0;
  var control = (mods & _p.CONTROL) !== 0;
  var alt = (mods & _p.ALT) !== 0;
  var meta = (mods & _p.META) !== 0;
  var command = (control || meta) && !alt;
  if (command && key === _p.KEY_V) return ACTION_PASTE;
  if (shift && !control && !alt && !meta && key === _p.KEY_INSERT) return ACTION_PASTE;
  if (command && key === _p.KEY_A) return ACTION_SELECT_ALL;
  if (command && key === _p.KEY_X) return ACTION_CUT;
  if (!control && !alt && !meta) {
    if (key === _p.KEY_BACKSPACE) return ACTION_BACKSPACE;
    if (key === _p.KEY_DELETE) return ACTION_DELETE;
  }
  // AltGr arrives as Control+Alt on some layouts and types a character.
  var altGr = control && alt && !meta;
  if (((!control && !alt && !meta) || altGr) && _p.printable(text)) return ACTION_INSERT;
  return ACTION_PASS;
}

// Pasted text made fit for a one-line field: line breaks at either end go,
// line breaks and tabs inside become one space, other control characters go.
function clean(text) {
  if (typeof text !== "string") return "";
  return text
    .replace(/^[\r\n]+|[\r\n]+$/g, "")
    .replace(/[\r\n\t]+/g, " ")
    .replace(/[\u0000-\u001f\u007f]/g, "");
}

// The field after an edit, as `{text, cursor}`, or null when nothing
// changes (nothing to delete, nothing to insert, or the result would be
// longer than `maxChars`, which is refused whole rather than cut short).
// `state` is `{text, start, end}`: the selection, or the cursor twice.
function apply(state, action, value, maxChars) {
  var source = state && typeof state.text === "string" ? state.text : "";
  var limit = _p.int(maxChars, 0);
  var start = Math.max(0, Math.min(_p.int(state ? state.start : 0, 0), source.length));
  var end = Math.max(0, Math.min(_p.int(state ? state.end : start, start), source.length));
  if (end < start) {
    var swap = start;
    start = end;
    end = swap;
  }
  var selected = end > start;
  if (action === ACTION_INSERT || action === ACTION_PASTE) {
    var insert = clean(value);
    if (insert.length === 0) return null;
    var text = source.slice(0, start) + insert + source.slice(end);
    if (text.length > limit) return null;
    return { "text": text, "cursor": start + insert.length };
  }
  if (action === ACTION_CUT) {
    if (!selected) return null;
    return { "text": source.slice(0, start) + source.slice(end), "cursor": start };
  }
  if (action === ACTION_BACKSPACE || action === ACTION_DELETE) {
    if (!selected) {
      if (action === ACTION_BACKSPACE) {
        if (start === 0) return null;
        start -= 1;
        if (start > 0 && _p.low(source.charCodeAt(start)) && _p.high(source.charCodeAt(start - 1))) start -= 1;
      } else {
        if (end >= source.length) return null;
        end += 1;
        if (end < source.length && _p.high(source.charCodeAt(end - 1)) && _p.low(source.charCodeAt(end))) end += 1;
      }
    }
    return { "text": source.slice(0, start) + source.slice(end), "cursor": start };
  }
  return null;
}

// The pasted text from the helper's output line, or null when it is not the
// helper's answer. The helper writes its one line only after a complete,
// bounded read; a paste that was too large, too slow, empty or not text
// writes nothing, so nothing is pasted.
function pasteResult(output) {
  if (typeof output !== "string" || output.length === 0) return null;
  if (output.length > PASTE_OUTPUT_MAX) return null;
  try {
    var parsed = JSON.parse(output);
    if (parsed && typeof parsed.text === "string" && parsed.text.length > 0) return parsed.text;
  } catch (error) {
    // Not the helper's answer: nothing is pasted.
  }
  return null;
}

// The helper's command line for a field.
function pasteCommand(helper, maxBytes) {
  return [String(helper), "--max-bytes", String(_p.int(maxBytes, 1)), "--timeout", String(PASTE_TIMEOUT_S)];
}

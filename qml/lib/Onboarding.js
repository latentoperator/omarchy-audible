.pragma library
.import "Panel.js" as Panel

// Onboarding logic for the drawer (PLAN L3, ARCHITECTURE §6, SCOPE FR-A1–A4).
//
// The service feeds it the `status` event and the flags it already holds, and
// it answers: which step of onboarding to show, the exact install command for
// the missing tools, which of the four views a request opens, the human text
// for a backend error, whether pasted text looks like the Amazon redirect URL,
// the marketplace list, and whether to warn about the clipboard history.
//
// It holds no state: the same inputs always give the same answer, so a view can
// bind straight to it. This is pure ECMAScript for the Qt JS engine: no
// imports but `Panel.js` (the view names), no Qt types, and nothing here
// throws on bad input. A pasted URL is never echoed — `looksLikeRedirect`
// returns only a boolean, and `errorText` drops any message or hint carrying
// the one-time-code marker.
//
// The public surface is the constants and the seven functions below.
// Everything else lives on the private `_p` namespace so it cannot leak into
// QML.

// `step` values, in the order the UI walks them.
var STEP_LOADING = "loading";
var STEP_MISSING = "missing";
var STEP_SETUP = "setup";
var STEP_CONNECT = "connect";
var STEP_READY = "ready";

var _p = {};

// The base of the install command (ARCHITECTURE §4.1).
_p.INSTALL_PREFIX = "omarchy pkg add ";

// The query parameter that carries the one-time code: the marker the backend
// extracts, and the one whose presence means "never show this text".
_p.AUTH_CODE_MARKER = "openid.oa2.authorization_code=";

// `ffprobe` is part of the `ffmpeg` package; the tools `status` can report as
// missing are exactly `mpv`, `ffmpeg` and `ffprobe` (ARCHITECTURE §4.1).
_p.PACKAGE_ALIASES = { "ffprobe": "ffmpeg" };

// The marketplaces the sign-in picker offers, in the backend's order
// (`auth.MARKETPLACES`, ARCHITECTURE §4.7). Codes must match it exactly.
_p.MARKETPLACES = [
  { "code": "us", "label": "United States" },
  { "code": "uk", "label": "United Kingdom" },
  { "code": "de", "label": "Germany" },
  { "code": "fr", "label": "France" },
  { "code": "ca", "label": "Canada" },
  { "code": "it", "label": "Italy" },
  { "code": "au", "label": "Australia" },
  { "code": "in", "label": "India" },
  { "code": "jp", "label": "Japan" },
  { "code": "es", "label": "Spain" },
  { "code": "br", "label": "Brazil" }
];

// The title, fallback body and reconnect flag for every `protocol.ErrorCode`.
// `reconnect` is true only for `auth_failed`, the code any job emits when the
// credentials are gone (FR-A4, matching `LibraryUi.BANNER_RECONNECT`).
_p.ERROR_TEXT = {
  "invalid_args": {
    "title": "Something went wrong",
    "body": "The app sent a request the plugin could not use.",
    "reconnect": false
  },
  "unknown_command": {
    "title": "Something went wrong",
    "body": "The app asked for an action the plugin does not know.",
    "reconnect": false
  },
  "not_implemented": {
    "title": "Not available yet",
    "body": "That feature is not part of this version.",
    "reconnect": false
  },
  "no_venv": {
    "title": "Setup needed",
    "body": "The plugin's tools are not installed yet. Run Set up to install them.",
    "reconnect": false
  },
  "busy": {
    "title": "Audible is busy",
    "body": "Another Audible task is running. Try again in a moment.",
    "reconnect": false
  },
  "internal": {
    "title": "Something went wrong",
    "body": "An unexpected error occurred. Check the diagnostics and try again.",
    "reconnect": false
  },
  "setup_failed": {
    "title": "Set up failed",
    "body": "The installation did not finish. Try Set up again.",
    "reconnect": false
  },
  "disk_space": {
    "title": "Not enough disk space",
    "body": "Free up some space on this device, then try again.",
    "reconnect": false
  },
  "network": {
    "title": "Connection problem",
    "body": "Could not reach Audible. Check your connection and try again.",
    "reconnect": false
  },
  "decrypt": {
    "title": "Could not unlock the book",
    "body": "The download could not be decrypted.",
    "reconnect": false
  },
  "convert": {
    "title": "Could not prepare the book",
    "body": "The download could not be converted for playback.",
    "reconnect": false
  },
  "no_voucher": {
    "title": "Book not downloadable",
    "body": "Audible did not offer downloadable audio for this book.",
    "reconnect": false
  },
  "cancelled": {
    "title": "Download cancelled",
    "body": "The download was cancelled.",
    "reconnect": false
  },
  "not_running": {
    "title": "Nothing to cancel",
    "body": "No download is running.",
    "reconnect": false
  },
  "not_local": {
    "title": "Not on this device",
    "body": "That book has not been downloaded.",
    "reconnect": false
  },
  "unsafe_path": {
    "title": "Unsafe to remove",
    "body": "That file is outside the books folder, so it was left alone.",
    "reconnect": false
  },
  "bad_asin": {
    "title": "Unknown book",
    "body": "That book is not in the library.",
    "reconnect": false
  },
  "auth_failed": {
    "title": "Reconnect Audible",
    "body": "The Audible sign-in is no longer valid. Reconnect to keep syncing; local playback is unaffected.",
    "reconnect": true
  },
  "bad_url": {
    "title": "That doesn't look like the Amazon page address",
    "body": "Copy the address of the 'page not found' page you landed on after signing in.",
    "reconnect": false
  },
  "expired": {
    "title": "Sign-in expired",
    "body": "The sign-in took too long. Start the sign-in again.",
    "reconnect": false
  },
  "no_auth_file": {
    "title": "No existing login found",
    "body": "Could not find an audible-cli login to use.",
    "reconnect": false
  },
  "stale": {
    "title": "Position not sent",
    "body": "Audible has a newer position for this book, so this one was not sent.",
    "reconnect": false
  },
  "unsupported": {
    "title": "Not supported",
    "body": "This book cannot be synced with Audible.",
    "reconnect": false
  }
};

// --- private helpers ---------------------------------------------------------
_p.isNull = function (value) {
  return value === null || value === undefined;
};

_p.isObject = function (value) {
  return !_p.isNull(value) && typeof value === "object" && !Array.isArray(value);
};

// A trimmed, non-empty string, or null.
_p.stringOrNull = function (value) {
  if (typeof value !== "string") {
    return null;
  }
  var trimmed = value.replace(/^\s+|\s+$/g, "");
  return trimmed.length > 0 ? trimmed : null;
};

// True when the text holds the one-time-code marker. Works on any input.
_p.hasAuthCode = function (text) {
  return typeof text === "string" && text.indexOf(_p.AUTH_CODE_MARKER) !== -1;
};

// Text that is safe to show: non-empty and free of the code marker, else null.
// This is the guarantee that `errorText` can never echo a pasted URL.
_p.safeText = function (value) {
  var text = _p.stringOrNull(value);
  if (text === null || _p.hasAuthCode(text)) {
    return null;
  }
  return text;
};

// The entry for `code`, or the internal-error entry for anything unknown.
_p.errorEntry = function (code) {
  var key = _p.stringOrNull(code);
  if (key !== null && Object.prototype.hasOwnProperty.call(_p.ERROR_TEXT, key)) {
    return _p.ERROR_TEXT[key];
  }
  return _p.ERROR_TEXT.internal;
};

// --- public API --------------------------------------------------------------

// Which step of onboarding a `status` event calls for (ARCHITECTURE §6).
// Anything that is not a status object reads as `loading`; a non-empty
// `missing` wins over everything, then a `venv_ready` that is false, then not
// being authenticated. `ready` is derived, never read from the event, so the
// fields cannot disagree with it.
function step(status) {
  if (!_p.isObject(status)) {
    return STEP_LOADING;
  }
  if (Array.isArray(status.missing) && status.missing.length > 0) {
    return STEP_MISSING;
  }
  if (status.venv_ready === false) {
    return STEP_SETUP;
  }
  if (status.authenticated !== true) {
    return STEP_CONNECT;
  }
  return STEP_READY;
}

// The command that installs the missing tools (ARCHITECTURE §4.1): `ffprobe`
// comes from `ffmpeg`, duplicates collapse, and the first-seen order is kept so
// the same status always shows the same command. Nothing missing gives "".
function installCommand(missing) {
  var items = Array.isArray(missing) ? missing : [];
  var packages = [];
  for (var index = 0; index < items.length; index++) {
    var name = _p.stringOrNull(items[index]);
    if (name === null) {
      continue;
    }
    if (Object.prototype.hasOwnProperty.call(_p.PACKAGE_ALIASES, name)) {
      name = _p.PACKAGE_ALIASES[name];
    }
    if (packages.indexOf(name) === -1) {
      packages.push(name);
    }
  }
  if (packages.length === 0) {
    return "";
  }
  return _p.INSTALL_PREFIX + packages.join(" ");
}

// The view to show (ARCHITECTURE §6). Onboarding replaces everything until the
// step is ready. Then `requested` names a view: `full` and `mini` need a loaded
// book and fall back to `library` without one, `library` is always itself, and
// a missing or unknown request is a bar click, which opens `mini` when a book
// is loaded and `library` otherwise.
function view(stepName, playerLoaded, requested) {
  if (stepName !== STEP_READY) {
    return Panel.VIEW_ONBOARDING;
  }
  var loaded = playerLoaded === true;
  var want = _p.stringOrNull(requested);
  if (want === Panel.VIEW_FULL) {
    return loaded ? Panel.VIEW_FULL : Panel.VIEW_LIBRARY;
  }
  if (want === Panel.VIEW_MINI) {
    return loaded ? Panel.VIEW_MINI : Panel.VIEW_LIBRARY;
  }
  if (want === Panel.VIEW_LIBRARY) {
    return Panel.VIEW_LIBRARY;
  }
  return loaded ? Panel.VIEW_MINI : Panel.VIEW_LIBRARY;
}

// The human text for an `error` event (SCOPE §6, FR-A4) as
// `{title, body, reconnect}`. Every `protocol.ErrorCode` and `no_venv` has an
// entry; an unknown code falls back to the internal-error text. The backend's
// `message` and `hint` refine the body, but any text carrying the one-time-code
// marker is dropped, so a pasted URL can never reach the UI.
function errorText(code, message, hint) {
  var entry = _p.errorEntry(code);
  var body = _p.safeText(message);
  if (body === null) {
    body = entry.body;
  }
  var extra = _p.safeText(hint);
  if (extra !== null) {
    body = body + " " + extra;
  }
  return {
    "title": entry.title,
    "body": body,
    "reconnect": entry.reconnect === true
  };
}

// True when the pasted text looks like the Amazon redirect URL the user brings
// back from the browser (FR-A1). It tests for the marker only and returns a
// boolean, so the text is never echoed.
function looksLikeRedirect(text) {
  return _p.hasAuthCode(text);
}

// The marketplaces the sign-in picker offers, as `[{code, label}]`, in the
// backend's order (ARCHITECTURE §4.7). A fresh array each call.
function marketplaces() {
  var items = [];
  for (var index = 0; index < _p.MARKETPLACES.length; index++) {
    items.push({
      "code": _p.MARKETPLACES[index].code,
      "label": _p.MARKETPLACES[index].label
    });
  }
  return items;
}

// The notice shown after a successful sign-in when the one-time code is still
// in Omarchy's clipboard history (ARCHITECTURE §4.7; G1 note). "" when it is
// not, so the view can render the string directly.
function clipboardNotice(done) {
  if (!_p.isObject(done) || done.clipboard_history_contains_code !== true) {
    return "";
  }
  return "Your sign-in link may still be in the clipboard history. Clear it from the Omarchy clipboard menu.";
}

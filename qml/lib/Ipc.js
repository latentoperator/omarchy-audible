.pragma library

// Shell IPC argument logic for Service.qml (ARCHITECTURE 6).
//
// The IpcHandler passes every argument as a string. This file turns the
// `skip <seconds>` argument into a number or null so the QML can return a
// short error instead of seeking by a bogus amount. Pure ECMAScript for the
// Qt JS engine: no imports, no Qt types, and nothing here throws.

var MAX_SECONDS = 86400;

// A strict decimal, so hex ("0x10"), "NaN", "Infinity" and "1e3" are all
// rejected rather than silently coercion-parsed by Number().
var DECIMAL = /^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$/;

// A signed number of seconds from an IPC string, or null: empty, non-numeric,
// over the bound, or not a string at all.
function parseSeconds(text) {
  if (typeof text !== "string") {
    return null;
  }
  var trimmed = text.trim();
  if (!DECIMAL.test(trimmed)) {
    return null;
  }
  var value = Number(trimmed);
  if (!isFinite(value) || Math.abs(value) > MAX_SECONDS) {
    return null;
  }
  return value;
}

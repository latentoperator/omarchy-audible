.pragma library

// The service's in-memory event log (`recentEvents`), read over IPC with
// `events`. Pure ECMAScript for the Qt JS engine; nothing here throws.

// A copy of `value` with every `lavf_options` value replaced by "[redacted]",
// at any depth. That key travels as an mpv loadfile option and is readable over
// the IPC socket while it is set, so it must never reach the event log (B11,
// SPIKE-RESULTS S7). The input is never mutated.
function redactOptions(value, depth) {
  if (depth > 12 || isNull(value) || typeof value !== "object") {
    return value;
  }
  if (Array.isArray(value)) {
    var items = [];
    for (var index = 0; index < value.length; index++) {
      items.push(redactOptions(value[index], depth + 1));
    }
    return items;
  }
  var copy = {};
  for (var key in value) {
    copy[key] = key === "lavf_options" ? "[redacted]" : redactOptions(value[key], depth + 1);
  }
  return copy;
}

// One short line for the event log.
function summarize(record, maxLength) {
  var text;
  try {
    text = JSON.stringify(redactOptions(record, 0));
  } catch (error) {
    text = String(record);
  }
  if (text.length > maxLength) {
    text = text.slice(0, maxLength) + "…";
  }
  return text;
}

function scrubText(text) {
  return String(text || "")
    .replace(/(["']?lavf_options["']?\s*:\s*)\{[^}]*\}/gi, "$1{[redacted]}")
    .replace(/(["']?(?:activation_bytes|lavf_options|audible_key|audible_iv|access_token|refresh_token|token|password|secret|voucher|aeskey)["']?)(\s*[=:]\s*)(["']?)([^\s&,"']+)/gi, "$1$2$3[redacted]")
    .replace(/(["'](?:key|iv)["']\s*[=:]\s*)(["']?)([^\s&,"']+)/gi, "$1$2[redacted]")
    .replace(/\b(key|iv)(\s*=\s*)(["']?)([^\s&,"']+)/gi, "$1$2$3[redacted]")
    .replace(/\bBearer\s+[A-Za-z0-9._~+\/-]+=*/gi, "Bearer [redacted]");
}

function isNull(value) {
  return value === null || value === undefined;
}

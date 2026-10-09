.pragma library
.import "EventLog.js" as EventLog

// Plain text support bundle for a failed sync. Never include auth/file data or
// doctor details outside the small, fixed tool check set.
var _p = {};
_p.TOOLS = ["python", "mpv", "ffmpeg", "ffprobe"];

function redact(text) {
  return EventLog.scrubText(text);
}

function build(version, command, code, message, hint, checks) {
  var lines = ["Omarchy Audible " + redact(version || "unknown"),
    "Command: " + redact(command || "unknown"), "Error: " + redact(code || "unknown"),
    "Message: " + redact(message || ""), "Hint: " + redact(hint || ""), "Doctor checks:"];
  var items = Array.isArray(checks) ? checks : [];
  for (var i = 0; i < items.length; i++) {
    var check = items[i];
    if (!check || typeof check.name !== "string") continue;
    var line = "- " + redact(check.name) + ": " + (check.ok === true ? "ok" : "missing");
    if (_p.TOOLS.indexOf(check.name) >= 0 && typeof check.detail === "string") line += " (" + redact(check.detail) + ")";
    lines.push(line);
  }
  return lines.join("\n");
}

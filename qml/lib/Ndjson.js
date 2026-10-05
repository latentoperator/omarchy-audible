.pragma library

// NDJSON reader for the backend protocol (ARCHITECTURE 4.2).
//
// The backend writes one JSON object per line to stdout and ends with a single
// `done` or `error` event. Quickshell's `Process` hands QML arbitrary chunks,
// so any chunk may split a line in the middle: feed every chunk through one
// splitter and act only on the records it returns. A line that is not a
// protocol event comes back as a `{type:"_bad_line"}` record so the caller can
// surface it instead of losing the rest of the stream.
//
// Pure ECMAScript for the Qt JS engine: no imports, no Qt types, and nothing
// here throws on bad input.

// Longest raw text kept from a line that could not be parsed.
var MAX_BAD_LINE = 200;

// `done` and `error` end a run; everything else is progress or data.
var TERMINAL_TYPES = ["done", "error"];

// A splitter owns the buffer for one backend process: partial lines wait there
// until the newline arrives, and every accepted record is kept in `events` so
// `finish` can be called with exactly what was seen.
function createSplitter() {
  return { "buffer": "", "events": [] };
}

// Parse one complete line. Returns the event, or null for a blank line.
function parseLine(line) {
  if (isNull(line)) {
    return null;
  }
  var text = String(line);
  if (text.length > 0 && text.charAt(text.length - 1) === "\r") {
    text = text.slice(0, -1);
  }
  if (text.trim().length === 0) {
    return null;
  }
  var value;
  try {
    value = JSON.parse(text);
  } catch (error) {
    return badLine(text);
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return badLine(text);
  }
  if (typeof value.type !== "string" || value.type.length === 0) {
    return badLine(text);
  }
  return value;
}

// The record for a line that is not a protocol event. The raw text is kept,
// sliced to MAX_BAD_LINE characters, so a huge or binary chunk cannot blow up
// the UI.
function badLine(text) {
  var line = String(text);
  if (line.length > MAX_BAD_LINE) {
    line = line.slice(0, MAX_BAD_LINE);
  }
  return { "type": "_bad_line", "line": line };
}

// done | error | progress | other.
function classify(record) {
  if (isNull(record) || typeof record.type !== "string") {
    return "other";
  }
  if (record.type === "progress") {
    return "progress";
  }
  if (TERMINAL_TYPES.indexOf(record.type) !== -1) {
    return record.type;
  }
  return "other";
}

// Append a chunk and return every complete record it contained (also appended
// to splitter.events). An incomplete trailing line stays in the buffer.
function feed(splitter, chunk) {
  var records = [];
  if (isNull(splitter) || isNull(chunk)) {
    return records;
  }
  splitter.buffer += String(chunk);
  var newline = splitter.buffer.indexOf("\n");
  while (newline !== -1) {
    var line = splitter.buffer.slice(0, newline);
    splitter.buffer = splitter.buffer.slice(newline + 1);
    appendRecord(splitter, records, line);
    newline = splitter.buffer.indexOf("\n");
  }
  return records;
}

// The process exited: a final line with no trailing newline is still a line.
function flush(splitter) {
  var records = [];
  if (isNull(splitter)) {
    return records;
  }
  var line = splitter.buffer;
  splitter.buffer = "";
  if (line.length > 0) {
    appendRecord(splitter, records, line);
  }
  return records;
}

// The job outcome from the process exit code and everything it emitted.
//
// A run whose last event is not `done`/`error` is an `internal` error; exit
// code 3, or an `error` whose code is `busy`, is `busy` (the backend lock is
// held by another shell or a hand-run CLI).
function finish(exitCode, events) {
  var list = [];
  if (!isNull(events) && typeof events.length === "number") {
    list = events;
  }
  var terminal = null;
  var terminalIndex = -1;
  var badLines = 0;
  for (var index = 0; index < list.length; index++) {
    var event = list[index];
    if (isNull(event) || typeof event !== "object") {
      continue;
    }
    if (event.type === "done" || event.type === "error") {
      terminal = event;
      terminalIndex = index;
    } else if (event.type === "_bad_line") {
      badLines += 1;
    }
  }

  var busy = exitCode === 3;
  if (!isNull(terminal) && terminal.type === "error" && terminal.code === "busy") {
    busy = true;
  }
  var finalTerminal = !isNull(terminal) && terminalIndex === list.length - 1;

  if (!finalTerminal) {
    if (busy) {
      return outcome(false, true, "busy", "the backend is busy", null, terminal, exitCode, badLines, true);
    }
    var missing = { "type": "error", "code": "internal", "message": "missing terminal done/error event" };
    return outcome(false, false, missing.code, missing.message, null, missing, exitCode, badLines, true);
  }

  if (terminal.type === "error") {
    var code = (typeof terminal.code === "string" && terminal.code.length > 0) ? terminal.code : "internal";
    if (busy) {
      code = "busy";
    }
    var message = typeof terminal.message === "string" ? terminal.message : null;
    var hint = typeof terminal.hint === "string" ? terminal.hint : null;
    return outcome(false, busy, code, message, hint, terminal, exitCode, badLines, exitCode === 0);
  }

  if (exitCode === 0) {
    return outcome(true, busy, null, null, null, terminal, exitCode, badLines, false);
  }
  return outcome(
    false, busy, "internal",
    "the cli exited " + exitCode + " after a done event",
    null, terminal, exitCode, badLines, true
  );
}

function outcome(ok, busy, code, message, hint, terminal, exitCode, badLines, mismatch) {
  return {
    "ok": ok,
    "busy": busy,
    "code": code,
    "message": message,
    "hint": hint,
    "terminal": terminal,
    "exitCode": exitCode,
    "badLines": badLines,
    "mismatch": mismatch
  };
}

function appendRecord(splitter, records, line) {
  var record = parseLine(line);
  if (!isNull(record)) {
    records.push(record);
    splitter.events.push(record);
  }
}

function isNull(value) {
  return value === null || value === undefined;
}

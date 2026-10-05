.pragma library

// The service's in-memory event log (`recentEvents`), read over IPC with
// `events`. Pure ECMAScript for the Qt JS engine; nothing here throws.

// One short line for the event log.
function summarize(record, maxLength) {
  var text;
  try {
    text = JSON.stringify(record);
  } catch (error) {
    text = String(record);
  }
  if (text.length > maxLength) {
    text = text.slice(0, maxLength) + "…";
  }
  return text;
}

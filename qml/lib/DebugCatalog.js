.pragma library

// TEMPORARY (removed in U1): the debug panel's `get` button needs one ASIN.
// Reads `catalog.json` text and returns the first book's ASIN, or "" when the
// text is missing, malformed or empty. Never throws.
function firstAsin(text) {
  var catalog;
  try {
    catalog = JSON.parse(String(text));
  } catch (error) {
    return "";
  }
  if (catalog === null || typeof catalog !== "object" || !Array.isArray(catalog.books)) {
    return "";
  }
  for (var index = 0; index < catalog.books.length; index++) {
    var book = catalog.books[index];
    if (book !== null && typeof book === "object" && typeof book.asin === "string" && book.asin.length > 0) {
      return book.asin;
    }
  }
  return "";
}

// One short line for the debug panel's event log.
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

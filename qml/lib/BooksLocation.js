.pragma library

function displayPath(path, home) {
  var value = String(path || "")
  var root = String(home || "").replace(/\/$/, "")
  if (root && (value === root || value.indexOf(root + "/") === 0))
    return "~" + value.slice(root.length)
  return value
}

function oldBooksText(oldBooks, newDir, home) {
  if (!oldBooks || typeof oldBooks.count !== "number" || oldBooks.count < 1) return ""
  var count = Math.floor(oldBooks.count)
  var noun = count === 1 ? "downloaded book is" : "downloaded books are"
  var followup = count === 1 ? " It shows as not downloaded until you move its folder into "
    : " They show as not downloaded until you move their folders into "
  return count + " " + noun + " still in " + displayPath(oldBooks.dir, home) + "."
    + followup
    + displayPath(newDir, home) + " or change booksDir back."
}

function problemText(problem, booksDir, home) {
  if (typeof problem !== "string" || problem.length === 0) return ""
  return "booksDir was not used: " + problem + ". Books are in "
    + displayPath(booksDir, home) + "."
}

function shouldAck(status, downloadActive, settingsReceived) {
  return settingsReceived === true && downloadActive !== true && !!status
    && status.old_books === null && status.books_location_recorded === false
}

function shouldShowOldBooks(status, settingsReceived) {
  return settingsReceived === true && !!status && status.old_books !== null
}

function shouldShowProblem(status, settingsReceived) {
  return settingsReceived === true && !!status
    && typeof status.books_dir_problem === "string" && status.books_dir_problem.length > 0
}

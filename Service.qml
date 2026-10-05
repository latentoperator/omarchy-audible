import QtQuick
import Quickshell
import Quickshell.Io
import "qml"
import "qml/lib/DebugCatalog.js" as DebugCatalog
import "qml/lib/Playback.js" as Playback

// Headless singleton. Owns the backend, mpv and shared state in later tasks.
// Bar widgets register as surfaces and are views only.
Item {
  id: root

  visible: false
  width: 0
  height: 0

  property var shell: null
  property var manifest: null
  property var pluginRegistry: null

  readonly property string pluginDir: manifest && manifest.__sourceDir
    ? String(manifest.__sourceDir)
    : decodeURIComponent(String(Qt.resolvedUrl(".")).replace(/^file:\/\//, "")).replace(/\/$/, "")

  // The dev flag lives on tmpfs, so a reboot returns to real mode. It is read
  // once, when the service starts.
  readonly property string devFlagPath: Quickshell.env("XDG_RUNTIME_DIR") + "/omarchy-audible-dev-fake"
  readonly property bool fake: devFlag.loaded
  // No backend command runs until the flag has been read: a command that
  // raced ahead of it would go out without OMARCHY_AUDIBLE_FAKE.
  property bool flagKnown: false

  // The latest `status` event. All paths come from here; never recompute them.
  property var status: null
  readonly property string dataDir: status && status.data_dir ? String(status.data_dir) : ""

  property var surfaces: []
  property var recentEvents: []
  readonly property int maxEvents: 40

  readonly property alias runner: runner
  readonly property alias player: player
  readonly property alias library: library
  readonly property alias store: store

  // Failed downloads by ASIN, shown as the row's error state until retried.
  property var failures: ({})

  // The book that is loaded and the last position seen for it. Kept so a
  // switch or a crash can still save where the old book stopped.
  property string snapAsin: ""
  property real snapMs: 0
  readonly property int saveIntervalMs: 10000

  readonly property string runtimeDir: status && status.runtime_dir ? String(status.runtime_dir) : ""
  readonly property string booksDir: status && status.books_dir ? String(status.books_dir) : ""

  function registerSurface(surface) {
    if (surface && surfaces.indexOf(surface) < 0) surfaces = surfaces.concat([surface])
  }

  function unregisterSurface(surface) {
    surfaces = surfaces.filter(function(s) { return s !== surface })
  }

  function primarySurface() {
    return surfaces.length > 0 ? surfaces[0] : null
  }

  function run(command, args) {
    if (!flagKnown) {
      logEvent(command, "refused: dev flag not read yet")
      return
    }
    // TEMPORARY dev guard (removed for G2).
    if (!fake && DebugCatalog.realModeBlocked(command)) {
      logEvent(command, "refused: not allowed in real mode during development")
      return
    }
    runner.run(command, args)
  }

  function markFlagKnown() {
    if (flagKnown) return
    flagKnown = true
    run("status", [])
  }

  // TEMPORARY (removed in U1)
  function firstCatalogAsin() {
    return DebugCatalog.firstAsin(catalogFile.text())
  }

  // The book file for an ASIN, under the books dir from the `status` event.
  // A negative start resumes from the library's merged position.
  function playBook(asin, startSec) {
    if (booksDir.length === 0) return "error: status not read yet"
    // Resuming needs the saved positions, and a position saved before they
    // were read would replace them.
    if (!store.loaded) return "error: state not loaded yet"
    if (!/^[A-Za-z0-9]+$/.test(asin)) return "error: bad asin"
    var row = library.rowFor(asin)
    var start = startSec >= 0 ? startSec : (row ? row.positionMs / 1000 : 0)
    return player.play(booksDir + "/" + asin + "/book.m4b", start) ? "ok" : "error: " + player.lastError
  }

  // TEMPORARY (removed in U1): one line per visible row, for IPC checks.
  function libraryQuery(sort, filter, search) {
    library.sortKey = sort
    library.filterKey = filter
    library.searchText = search
    return library.rows.map(function(row) {
      return row.asin + "|" + row.title + "|" + row.state + "|" + Math.round(row.percent) + "%|" + row.positionMs
    }).join("\n")
  }

  // Saves the position of the loaded book. `book` and `ms` are explicit so a
  // switch can save the book that just ended.
  function savePosition(asin, ms) {
    if (asin.length === 0) return
    store.record(asin, ms)
    store.save()
  }

  function onBookSwitched() {
    var asin = Playback.asinFromPath(player.path)
    var previous = snapAsin
    if (snapAsin.length > 0 && snapAsin !== asin) savePosition(snapAsin, snapMs)
    snapAsin = asin
    // Switching from another book: its position is not this book's, and the
    // new one arrives with its own time-pos. First load or a reattach: mpv
    // already reported the position (before the path), so keep it.
    snapMs = previous.length === 0 && asin.length > 0 && player.derived.hasPosition ? player.positionMs : 0
  }

  function refreshLocal() {
    run("local", [])
  }

  function reloadSync() {
    catalogFile.reload()
    remoteFile.reload()
  }

  function playerSummary() {
    return JSON.stringify({
      "connection": player.connection, "error": player.lastError,
      "loaded": player.loaded, "playing": player.playing,
      "positionMs": player.positionMs, "durationMs": player.durationMs,
      "chapterIndex": player.chapterIndex, "chapters": player.chapters.length,
      "speed": player.speed, "volume": player.volume,
      "sleep": player.sleepTimer ? player.sleepTimer.mode : null
    })
  }

  function logEvent(label, text) {
    var entry = { "label": label, "text": text }
    recentEvents = recentEvents.concat([entry]).slice(-maxEvents)
  }

  PlayerController {
    id: player
    socketPath: root.runtimeDir.length > 0 ? root.runtimeDir + "/mpv.sock" : ""
    // Low in fake mode: the fake book is a sine wave.
    initialVolume: root.fake ? 15 : 100
    // Reattach once the paths are known.
    onSocketPathChanged: if (socketPath.length > 0) attach()
  }

  LibraryModel {
    id: library
    stateDoc: store.doc
    jobs: Playback.jobStates(runner.pendingJobs, runner.activeJob, runner.progress, root.failures)
  }

  StateStore {
    id: store
    path: root.dataDir.length > 0 ? root.dataDir + "/state.json" : ""
  }

  Connections {
    target: player

    function onPathChanged() { root.onBookSwitched() }

    function onPositionMsChanged() {
      // A null time-pos (a file being swapped) is not a position.
      if (player.derived.hasPosition && Playback.asinFromPath(player.path) === root.snapAsin) root.snapMs = player.positionMs
    }

    // Pause, stop or a crash: save where the book stopped.
    function onPlayingChanged() {
      if (!player.playing) root.savePosition(root.snapAsin, root.snapMs)
    }
  }

  Timer {
    interval: root.saveIntervalMs
    repeat: true
    running: player.playing
    onTriggered: root.savePosition(root.snapAsin, root.snapMs)
  }

  // TEMPORARY dev methods; P5 adds the public ones (toggle, openLibrary) and
  // the README section. All arguments and return values are strings.
  IpcHandler {
    target: "latentoperator.audible"

    function play(asin: string): string { return root.playBook(asin, -1) }
    function playAt(asin: string, startSec: string): string { return root.playBook(asin, Number(startSec) || 0) }
    function pause(): string { player.pause(); return "ok" }
    function resume(): string { player.resume(); return "ok" }
    function skip(seconds: string): string { player.skip(Number(seconds) || 0); return "ok" }
    function nextChapter(): string { player.nextChapter(); return "ok" }
    function prevChapter(): string { player.prevChapter(); return "ok" }
    function chapter(index: string): string { player.setChapter(Number(index) || 0); return "ok" }
    function speed(value: string): string { player.setSpeed(Number(value)); return "ok" }
    function volume(value: string): string { player.setVolume(Number(value)); return "ok" }
    function sleepMinutes(minutes: string): string { player.setSleepTimer(Number(minutes) || 0); return "ok" }
    function sleepChapter(): string { player.setSleepEndOfChapter(); return "ok" }
    function sleepCancel(): string { player.cancelSleep(); return "ok" }
    function quitPlayer(): string { player.quit(); return "ok" }
    function playerStatus(): string { return root.playerSummary() }
    function libraryQuery(sort: string, filter: string, search: string): string { return root.libraryQuery(sort, filter, search) }
    function flushState(): string { store.flush(); return "ok" }
  }

  FileView {
    id: devFlag
    path: root.devFlagPath
    blockLoading: true
    printErrors: false
    onLoaded: root.markFlagKnown()
    onLoadFailed: function(error) { root.markFlagKnown() }
  }

  FileView {
    id: catalogFile
    path: root.dataDir.length > 0 ? root.dataDir + "/catalog.json" : ""
    printErrors: false
    onLoaded: library.catalogText = catalogFile.text()
    onLoadFailed: function(error) { library.catalogText = "" }
  }

  FileView {
    id: remoteFile
    path: root.dataDir.length > 0 ? root.dataDir + "/remote.json" : ""
    printErrors: false
    onLoaded: library.remoteText = remoteFile.text()
    onLoadFailed: function(error) { library.remoteText = "" }
  }

  JobRunner {
    id: runner
    launcher: root.pluginDir + "/bin/omarchy-audible"
    environment: root.fake ? ({ "OMARCHY_AUDIBLE_FAKE": "1" }) : ({})

    onEvent: function(record, job) {
      if (record.type === "status") {
        root.status = record
        root.refreshLocal()
      } else if (record.type === "local") {
        library.localBooks = record.books
      }
      root.logEvent(job.command, DebugCatalog.summarize(record, 160))
    }

    onJobFinished: function(job, outcome) {
      var text = outcome.ok ? "ok" : String(outcome.code) + ": " + String(outcome.message || "")
      root.logEvent(job.command + " exit", text)
      root.failures = Playback.updateFailures(root.failures, job, outcome)
      if (job.command === "sync") {
        root.reloadSync()
      } else if (job.command === "position-get") {
        remoteFile.reload()
      } else if (job.command === "get" || job.command === "remove") {
        root.refreshLocal()
      }
    }
  }

  Component.onCompleted: if (devFlag.loaded) markFlagKnown()

  // Shutdown: save where the book is, and wait for the write.
  Component.onDestruction: {
    if (player.playing) store.record(snapAsin, snapMs)
    store.flush()
  }
}

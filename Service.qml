import QtQuick
import Quickshell
import Quickshell.Io
import "qml"
import "qml/lib/DebugCatalog.js" as DebugCatalog
import "qml/lib/Playback.js" as Playback
import "qml/lib/Positions.js" as Positions

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
  // TEMPORARY dev hook (removed for G2): in fake mode only, a file holding the
  // path of a stand-in launcher (scripts/dev-fake-positions) replaces the
  // backend launcher, because the fake backend cannot hold a remote position.
  readonly property string devLauncherPath: Quickshell.env("XDG_RUNTIME_DIR") + "/omarchy-audible-dev-launcher"
  readonly property string devLauncher: fake && devLauncherFile.loaded ? String(devLauncherFile.text()).trim() : ""
  property bool autoRemoveFinished: false
  // No backend command runs until the flag has been read: a command that
  // raced ahead of it would go out without OMARCHY_AUDIBLE_FAKE.
  property bool flagKnown: false
  property bool launcherKnown: false

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
  property string pendingResume: ""
  property string removeCandidate: ""
  property var resumeRemotes: ({})

  // The book that is loaded and the last position seen for it. Kept so a
  // switch or a crash can still save where the old book stopped.
  property string snapAsin: ""
  property real snapMs: 0
  // The loaded book advanced while playing since it was last saved. Only then
  // is there a new listening position to record or push; a paused book that is
  // merely switched away from must keep its old listening time.
  property bool snapDirty: false
  // The same, for the push queue: the book advanced since its position was
  // last queued for write-back. Kept apart from `snapDirty` because the 10 s
  // save clears that one without queuing a push.
  property bool snapUnpushed: false
  readonly property int saveIntervalMs: 10000
  readonly property int pushIntervalMs: 60000

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

  // Returns false when the command was refused and will never report back.
  function run(command, args, purpose) {
    if (!flagsRead()) {
      logEvent(command, "refused: dev flags not read yet")
      return false
    }
    // TEMPORARY dev guard (removed for G2).
    if (!fake && DebugCatalog.realModeBlocked(command)) {
      logEvent(command, "refused: not allowed in real mode during development")
      return false
    }
    runner.run(command, args, purpose)
    return true
  }

  function flagsRead() { return flagKnown && launcherKnown }

  function markFlagKnown() {
    if (flagKnown) return
    flagKnown = true
    startWhenReady()
  }

  function markLauncherKnown() {
    if (launcherKnown) return
    launcherKnown = true
    startWhenReady()
  }

  function startWhenReady() {
    if (flagsRead()) run("status", [])
  }

  // TEMPORARY (removed in U1)
  function firstCatalogAsin() {
    return DebugCatalog.firstAsin(catalogFile.text())
  }

  // The book file for an ASIN, under the books dir from the `status` event.
  // A negative start resumes from the newest of the local and remote
  // positions: the remote one is read again first, and the cached one is used
  // when that read fails.
  function playBook(asin, startSec) {
    if (booksDir.length === 0) return "error: status not read yet"
    // Resuming needs the saved positions, and a position saved before they
    // were read would replace them.
    if (!store.loaded) return "error: state not loaded yet"
    if (!/^[A-Za-z0-9]+$/.test(asin)) return "error: bad asin"
    if (startSec >= 0) {
      pendingResume = ""
      return playNow(asin, startSec)
    }
    pendingResume = asin
    if (!run("position-get", [asin], "resume")) {
      pendingResume = ""
      return playNow(asin, cachedStartSec(asin))
    }
    return "ok"
  }

  function playNow(asin, startSec) {
    return player.play(booksDir + "/" + asin + "/book.m4b", startSec) ? "ok" : "error: " + player.lastError
  }

  function finishResume(asin, remoteEntry) {
    if (pendingResume !== asin) return
    pendingResume = ""
    var local = store.doc.books ? store.doc.books[asin] : null
    var start = remoteEntry ? Positions.resumeMs(local, remoteEntry) / 1000 : cachedStartSec(asin)
    playNow(asin, start)
  }

  // True when the loaded book is `asin` and it is at its end right now. Uses
  // the live player values, not the saved snapshot, and ignores an `eof` flag
  // that has no duration behind it (a load that failed).
  function atEnd(asin) {
    if (asin.length === 0 || !player.loaded || Playback.asinFromPath(player.path) !== asin) return false
    return Positions.isFinished(player.positionMs, player.durationMs, player.derived.eof && player.durationMs > 0)
  }

  // Evaluated on pause, stop and every save tick. Auto-remove waits a moment
  // and checks again, so a transient pause while mpv reloads cannot trigger it.
  function checkFinished(asin) {
    if (!atEnd(asin)) return
    store.markFinished(asin)
    if (autoRemoveFinished) {
      removeCandidate = asin
      autoRemoveTimer.restart()
    }
  }

  // Checked by the job runner just before a queued job starts. An auto-remove
  // that waited behind another job must not run if the book is playing again.
  function jobAllowed(job) {
    if (job.purpose !== "autoremove") return true
    return Positions.autoRemoveAllowed(autoRemoveFinished, atEnd(job.args[0]), player.playing)
  }

  function removeIfStillFinished() {
    var asin = removeCandidate
    removeCandidate = ""
    if (asin.length === 0) return
    if (Positions.autoRemoveAllowed(autoRemoveFinished, atEnd(asin), player.playing)) run("remove", [asin], "autoremove")
  }

  // The saved position for a book: the library's merged one, else the local
  // entry in state.json (the catalog may not have loaded, or lack the book).
  function cachedStartSec(asin) {
    var row = library.rowFor(asin)
    if (row) return row.positionMs / 1000
    var local = store.doc.books ? store.doc.books[asin] : null
    return local && typeof local.ms === "number" ? local.ms / 1000 : 0
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
  function savePosition(asin, ms, push) {
    if (asin.length === 0) return
    if (snapDirty) {
      snapDirty = false
      store.record(asin, ms)
      store.save()
      checkFinished(asin)
    }
    if (push && snapUnpushed) {
      snapUnpushed = false
      sync.notePlayed(asin)
    }
  }

  function onBookSwitched() {
    var asin = Playback.asinFromPath(player.path)
    var previous = snapAsin
    if (snapAsin.length > 0 && snapAsin !== asin) savePosition(snapAsin, snapMs, true)
    snapAsin = asin
    // Switching from another book: its position is not this book's, and the
    // new one arrives with its own time-pos. First load or a reattach: mpv
    // already reported the position (before the path), so keep it.
    snapMs = previous.length === 0 && asin.length > 0 && player.derived.hasPosition ? player.positionMs : 0
    snapDirty = false
    snapUnpushed = false
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

  PositionSync {
    id: sync
    store: store
    service: root
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
      if (!player.derived.hasPosition || Playback.asinFromPath(player.path) !== root.snapAsin) return
      root.snapMs = player.positionMs
      if (player.playing) {
        root.snapDirty = true
        root.snapUnpushed = true
      }
    }

    // Pause, stop or a crash: save where the book stopped.
    function onPlayingChanged() {
      if (!player.playing) root.savePosition(root.snapAsin, root.snapMs, true)
    }
  }

  Timer {
    interval: root.saveIntervalMs
    repeat: true
    running: player.playing
    onTriggered: root.savePosition(root.snapAsin, root.snapMs, false)
  }

  Timer {
    id: autoRemoveTimer
    interval: 2000
    repeat: false
    onTriggered: root.removeIfStillFinished()
  }

  // Push about once a minute while playing.
  Timer {
    interval: root.pushIntervalMs
    repeat: true
    running: player.playing
    onTriggered: root.savePosition(root.snapAsin, root.snapMs, true)
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
    function autoRemove(value: string): string { root.autoRemoveFinished = value === "on"; return "ok" }
    function pushState(): string { return JSON.stringify({ "queue": sync.queue, "flushing": sync.flushing, "last": sync.lastResult }) }
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
    id: devLauncherFile
    path: root.devLauncherPath
    blockLoading: true
    printErrors: false
    onLoaded: root.markLauncherKnown()
    onLoadFailed: function(error) { root.markLauncherKnown() }
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
    gate: root.jobAllowed
    launcher: root.devLauncher.length > 0 ? root.devLauncher : root.pluginDir + "/bin/omarchy-audible"
    environment: root.fake ? ({ "OMARCHY_AUDIBLE_FAKE": "1" }) : ({})

    onEvent: function(record, job) {
      if (record.type === "status") {
        root.status = record
        root.refreshLocal()
      } else if (record.type === "local") {
        library.localBooks = record.books
      } else if (record.type === "positions" && job.purpose === "resume") {
        var resumed = job.args[0]
        var remotes = root.resumeRemotes
        remotes[resumed] = record.items[resumed] || null
        root.resumeRemotes = remotes
      }
      sync.handleEvent(record, job)
      root.logEvent(job.command, DebugCatalog.summarize(record, 160))
    }

    onJobFinished: function(job, outcome) {
      var text = outcome.ok ? "ok" : String(outcome.code) + ": " + String(outcome.message || "")
      root.logEvent(job.command + " exit", text)
      root.failures = Playback.updateFailures(root.failures, job, outcome)
      sync.handleFinished(job, outcome)
      if (job.purpose === "resume") {
        var resumedAsin = job.args[0]
        var remote = outcome.ok ? (root.resumeRemotes[resumedAsin] || null) : null
        delete root.resumeRemotes[resumedAsin]
        root.finishResume(resumedAsin, remote)
      }
      if (job.command === "sync") {
        root.reloadSync()
      } else if (job.command === "position-get") {
        remoteFile.reload()
      } else if (job.command === "get" || job.command === "remove") {
        root.refreshLocal()
      }
    }
  }

  Component.onCompleted: {
    if (devFlag.loaded) markFlagKnown()
    if (devLauncherFile.loaded) markLauncherKnown()
  }

  // Shutdown: save where the book is, and wait for the write.
  Component.onDestruction: {
    if (snapAsin.length > 0 && (snapDirty || snapUnpushed)) {
      if (snapDirty) store.record(snapAsin, snapMs)
      sync.queuePush(snapAsin)
    }
    store.flush()
  }
}

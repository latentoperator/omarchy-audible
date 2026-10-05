import QtQuick
import Quickshell
import Quickshell.Io
import "qml"
import "qml/lib/Drawer.js" as Drawer
import "qml/lib/EventLog.js" as EventLog
import "qml/lib/Format.js" as Format
import "qml/lib/Ipc.js" as Ipc
import "qml/lib/LibraryUi.js" as LibraryUi
import "qml/lib/Panel.js" as Panel
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
  property bool autoRemoveFinished: false
  // No backend command runs until the flag has been read: a command that
  // raced ahead of it would go out without OMARCHY_AUDIBLE_FAKE.
  property bool flagKnown: false

  // The latest `status` event. All paths come from here; never recompute them.
  property var status: null
  readonly property string dataDir: status && status.data_dir ? String(status.data_dir) : ""

  property var surfaces: []
  property var recentEvents: []
  readonly property int maxEvents: 40

  // The panel's current view, shared by every monitor's widget.
  property string view: Panel.VIEW_LIBRARY
  readonly property string loadedAsin: player.loaded ? Playback.asinFromPath(player.path) : ""
  readonly property var loadedRow: loadedAsin.length > 0 ? library.rowFor(loadedAsin) : null
  readonly property string barGlyph: Panel.glyph(player.loaded, player.playing)
  readonly property string tooltipText: {
    if (!player.loaded) return "Omarchy Audible"
    var row = loadedRow
    var text = Format.tooltip(row ? row.title : "", row ? Format.names(row.authors) : "",
      Format.left(player.positionMs, player.durationMs))
    return text.length > 0 ? text : "Omarchy Audible"
  }

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

  // Library view state (U2). `statusAtMs` is when the `status` event
  // arrived, `lastSyncAtMs` when a sync last succeeded this session, and
  // `lastSyncCode` the last sync's error code ("" after a success).
  property real statusAtMs: 0
  property real lastSyncAtMs: 0
  property string lastSyncCode: ""
  readonly property bool syncing: Drawer.syncing(runner.pendingJobs, runner.activeJob)
  readonly property var syncFailure: Drawer.syncFailure(lastSyncCode)
  readonly property var listState: LibraryUi.listState({
    "catalogLoaded": library.catalogLoaded, "syncing": syncing,
    "total": library.allRows.length, "shown": library.count,
    "offline": syncFailure.offline, "errorCode": syncFailure.errorCode
  })
  // A downloaded book plays when its `get` finishes; a finished book far
  // from its end asks first (`askAsin`); a book picked from the drawer
  // reopens the panel on Mini once it is playing (`reopenAsin`).
  property string askAsin: ""
  property string reopenAsin: ""
  // The last book the user chose to play; a finished download plays only
  // if it is still this one.
  property string latestPick: ""
  // Books to remove once the player has unloaded them.
  property var removeAfterUnload: []
  property real lastSyncAttemptAtMs: 0

  // mpv may report playing before the new path, so check on both.
  onLoadedAsinChanged: {
    reopenOnMini()
    flushRemovals()
  }

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
    if (!flagKnown) {
      logEvent(command, "refused: dev flag not read yet")
      return false
    }
    runner.run(command, args, purpose)
    return true
  }

  function markFlagKnown() {
    if (flagKnown) return
    flagKnown = true
    run("status", [])
  }

  // Called by a widget just before its panel opens.
  function viewForOpen() {
    view = Panel.viewOnOpen(player.loaded)
  }

  function showView(name) {
    if (Panel.VIEWS.indexOf(name) !== -1) view = name
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
    // A removal queued before the book was played again must not delete it.
    if (job.command === "remove" && job.purpose === "user") return Drawer.removalAllowed(job.args[0], busyAsins())
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

  // One line per visible row, for IPC checks (a test method, see below).
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

  // Picking a Library row (FR-L6, ARCHITECTURE 6). `LibraryUi` decides what
  // the pick means; a local book resumes, starts over or asks.
  // A new choice of book to play wins over every older one: an open
  // question, a resume still reading its position, a pending removal of
  // this book, and the download-then-play check (`latestPick`).
  function noteIntent(asin) {
    latestPick = asin
    askAsin = ""
    if (pendingResume !== asin) pendingResume = ""
    removeAfterUnload = removeAfterUnload.filter(function(a) { return a !== asin })
    if (removeAfterUnload.length === 0) unloadTimer.stop()
  }

  // Books a removal must not touch: loaded, resuming, or about to load.
  function busyAsins() {
    var load = player.pendingLoad ? Playback.asinFromPath(player.pendingLoad.path) : ""
    return [loadedAsin, pendingResume, load]
  }

  function pick(asin) {
    var row = library.rowFor(asin)
    if (!row) return "error: unknown book"
    noteIntent(asin)
    var action = LibraryUi.primaryAction(row, syncFailure.offline)
    if (action === LibraryUi.ACTION_PLAY) return playPicked(asin, true)
    if (action === LibraryUi.ACTION_DOWNLOAD || action === LibraryUi.ACTION_RETRY) {
      return run("get", [asin], "autoplay") ? "ok" : "error: refused"
    }
    return "error: nothing to do"
  }

  // `hidePanel`: the user picked the book in the open drawer, so the panel
  // hides and reopens on Mini when playback starts. After a download the
  // panel is only switched to Mini if it is still open.
  function playPicked(asin, hidePanel) {
    var row = library.rowFor(asin)
    var choice = LibraryUi.resumeChoice(row, 0)
    if (choice === LibraryUi.CHOICE_ASK) {
      askAsin = asin
      if (anySurfaceOpen()) showView(Panel.VIEW_LIBRARY)
      return "ask"
    }
    return startPicked(asin, choice === LibraryUi.CHOICE_START_OVER ? 0 : -1, hidePanel)
  }

  function dismissAsk() {
    askAsin = ""
  }

  function answerAsk(resume) {
    var asin = askAsin
    askAsin = ""
    if (asin.length === 0) return "error: nothing asked"
    // Removed since the question was asked: pick it again (download).
    var row = library.rowFor(asin)
    if (!row || row.local !== true) return pick(asin)
    return startPicked(asin, resume ? -1 : 0, true)
  }

  function startPicked(asin, startSec, hidePanel) {
    noteIntent(asin)
    var open = anySurfaceOpen()
    if (hidePanel) closeSurfaces()
    reopenAsin = hidePanel || open ? asin : ""
    reopenTimer.restart()
    return playBook(asin, startSec)
  }

  function anySurfaceOpen() {
    return surfaces.some(function(s) { return s.opened === true })
  }

  function closeSurfaces() {
    surfaces.forEach(function(s) { if (s.opened) s.close() })
  }

  // Playback of the picked book began: show it on Mini.
  function reopenOnMini() {
    if (reopenAsin.length === 0 || !player.playing || loadedAsin !== reopenAsin) return
    reopenAsin = ""
    reopenTimer.stop()
    if (anySurfaceOpen()) {
      showView(Panel.VIEW_MINI)
    } else {
      var surface = primarySurface()
      if (surface) surface.open()
    }
  }

  // Opening the drawer on Library syncs when the catalog is old (FR-L2).
  function libraryOpened() {
    var now = Date.now()
    if (syncing || Drawer.autoSyncBlocked(lastSyncAttemptAtMs, now)) return
    var age = Drawer.catalogAgeS(status ? status.catalog_age_s : null, statusAtMs, lastSyncAtMs, now)
    if (LibraryUi.syncDue(age, Drawer.SYNC_HOURS)) startSync("auto")
  }

  function refreshLibrary() {
    if (syncing) return "busy"
    return startSync("manual") ? "ok" : "error: refused"
  }

  function startSync(purpose) {
    lastSyncAttemptAtMs = Date.now()
    return run("sync", [], purpose)
  }

  // Any local book can be removed (FR-S2). The loaded one is unloaded first
  // (the player saves its position) and removed once it is gone.
  function removeBook(asin) {
    if (!Drawer.canRemove(library.rowFor(asin))) return "error: not removable"
    // A question about a book being removed no longer has a file to play.
    if (askAsin === asin) askAsin = ""
    if (asin === loadedAsin) {
      if (removeAfterUnload.indexOf(asin) < 0) removeAfterUnload = removeAfterUnload.concat([asin])
      unloadTimer.restart()
      player.quit()
      return "unloading"
    }
    return run("remove", [asin], "user") ? "ok" : "error: refused"
  }

  function flushRemovals() {
    var busy = busyAsins()
    var ready = removeAfterUnload.filter(function(asin) { return Drawer.removalAllowed(asin, busy) })
    removeAfterUnload = removeAfterUnload.filter(function(asin) { return ready.indexOf(asin) < 0 })
    if (removeAfterUnload.length === 0) unloadTimer.stop()
    ready.forEach(function(asin) { run("remove", [asin], "user") })
  }

  // The player never let go of a book it was asked to unload: give up.
  function abandonRemovals() {
    removeAfterUnload.forEach(function(asin) { logEvent("remove", "skipped " + asin + ": the player did not unload it") })
    removeAfterUnload = []
  }

  function removeAll() {
    var asins = Drawer.removableAsins(library.allRows)
    asins.forEach(function(asin) { removeBook(asin) })
    return String(asins.length)
  }


  function refreshLocal() {
    run("local", [])
  }

  function reloadSync() {
    catalogFile.reload()
    remoteFile.reload()
    library.rescanCovers()
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
    coversDir: root.dataDir.length > 0 ? root.dataDir + "/covers" : ""
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
      else root.reopenOnMini()
    }
  }

  Timer {
    interval: root.saveIntervalMs
    repeat: true
    running: player.playing
    onTriggered: root.savePosition(root.snapAsin, root.snapMs, false)
  }

  Timer {
    id: unloadTimer
    interval: 10000
    repeat: false
    onTriggered: root.abandonRemovals()
  }

  // A pick whose playback never starts stops waiting to reopen the panel.
  Timer {
    id: reopenTimer
    interval: 15000
    repeat: false
    onTriggered: root.reopenAsin = ""
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

  // Shell IPC target (ARCHITECTURE 6). Every argument and return value is a
  // string: "ok", or a short error string. Nothing here throws.
  IpcHandler {
    target: "latentoperator.audible"

    function toggle(): string {
      var surface = root.primarySurface()
      if (!surface) return "error: no surface"
      surface.toggle()
      return "ok"
    }

    function openLibrary(): string {
      var surface = root.primarySurface()
      if (!surface) return "error: no surface"
      surface.open()
      root.showView(Panel.VIEW_LIBRARY)
      return "ok"
    }

    function playPause(): string {
      if (!player.loaded) return "error: nothing loaded"
      player.toggle()
      return "ok"
    }

    function skip(seconds: string): string {
      var value = Ipc.parseSeconds(seconds)
      if (value === null) return "error: bad seconds"
      if (!player.loaded) return "error: nothing loaded"
      player.skip(value)
      return "ok"
    }

    function nextChapter(): string {
      if (!player.loaded) return "error: nothing loaded"
      player.nextChapter()
      return "ok"
    }

    function prevChapter(): string {
      if (!player.loaded) return "error: nothing loaded"
      player.prevChapter()
      return "ok"
    }

    // Test methods so agents can drive the service without input. They stay
    // through M3; R6 documents or removes them.
    function play(asin: string): string { root.noteIntent(asin); return root.playBook(asin, -1) }
    function playAt(asin: string, startSec: string): string { root.noteIntent(asin); return root.playBook(asin, Number(startSec) || 0) }
    function pause(): string { player.pause(); return "ok" }
    function resume(): string { player.resume(); return "ok" }
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
    function syncNow(): string { return root.run("sync", [], "ipc") ? "ok" : "refused" }
    function pick(asin: string): string { return root.pick(asin) }
    function answer(choice: string): string { return root.answerAsk(choice === "resume") }
    function removeBook(asin: string): string { return root.removeBook(asin) }
    function libraryState(): string {
      return JSON.stringify({ "list": root.listState, "ask": root.askAsin, "reopen": root.reopenAsin,
        "syncing": root.syncing, "lastSyncCode": root.lastSyncCode, "count": library.count,
        "total": library.allRows.length, "storage": LibraryUi.storage(library.localBooks) })
    }
    // Fake mode only: a download that fails with a `--fake-fail` mode.
    function fakeFailGet(asin: string, mode: string): string {
      if (!root.fake) return "error: fake mode only"
      return root.run("get", [asin, "--fake-fail", mode], "autoplay") ? "ok" : "refused"
    }
    function autoRemove(value: string): string { root.autoRemoveFinished = value === "on"; return "ok" }
    function pushState(): string { return JSON.stringify({ "queue": sync.queue, "flushing": sync.flushing, "last": sync.lastResult }) }
    function panelState(): string {
      var open = root.surfaces.some(function(s) { return s.opened === true })
      return JSON.stringify({ "open": open, "view": root.view, "glyph": root.barGlyph, "tooltip": root.tooltipText })
    }
    function events(): string {
      return root.recentEvents.map(function(e) { return e.label + "  " + e.text }).join("\n")
    }
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
    gate: root.jobAllowed
    launcher: root.pluginDir + "/bin/omarchy-audible"
    environment: root.fake ? ({ "OMARCHY_AUDIBLE_FAKE": "1" }) : ({})

    onEvent: function(record, job) {
      if (record.type === "status") {
        root.status = record
        root.statusAtMs = Date.now()
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
      root.logEvent(job.command, EventLog.summarize(record, 160))
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
        root.lastSyncCode = outcome.ok ? "" : String(outcome.code || "internal")
        if (outcome.ok) root.lastSyncAtMs = Date.now()
        root.reloadSync()
      } else if (job.command === "position-get") {
        remoteFile.reload()
      } else if (job.command === "get" || job.command === "remove") {
        root.refreshLocal()
      }
      if (job.command === "get" && job.purpose === "autoplay" && outcome.ok
          && Drawer.autoplayAllowed(job.args[0], root.latestPick)) {
        root.playPicked(job.args[0], false)
      }
    }
  }

  Component.onCompleted: {
    if (devFlag.loaded) markFlagKnown()
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

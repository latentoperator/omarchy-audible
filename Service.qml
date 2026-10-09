import QtQuick
import Quickshell
import Quickshell.Io
import "qml"
import "qml/lib/Drawer.js" as Drawer
import "qml/lib/EventLog.js" as EventLog
import "qml/lib/Diagnostic.js" as Diagnostic
import "qml/lib/Format.js" as Format
import "qml/lib/Library.js" as Library
import "qml/lib/LibraryUi.js" as LibraryUi
import "qml/lib/Mpv.js" as Mpv
import "qml/lib/Onboarding.js" as Onboarding
import "qml/lib/Panel.js" as Panel
import "qml/lib/Playback.js" as Playback
import "qml/lib/BooksLocation.js" as BooksLocation
import "qml/lib/Player.js" as Player
import "qml/lib/PlayRequest.js" as PlayRequest
import "qml/lib/Positions.js" as Positions
import "qml/lib/Signin.js" as Signin
import "qml/lib/Settings.js" as Settings
import "qml/lib/Unload.js" as Unload

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
  property int skipSeconds: Settings.DEFAULTS.skipSeconds
  property string defaultSort: Settings.DEFAULTS.defaultSort
  property int syncOnOpenHours: Settings.DEFAULTS.syncOnOpenHours
  property real defaultSpeed: Settings.DEFAULTS.defaultSpeed
  property string showTitleInBar: Settings.DEFAULTS.showTitleInBar
  property string booksDirSetting: Settings.DEFAULTS.booksDir
  property bool settingsReceived: false
  property var booksAckState: ({ "pendingDir": "", "failedDir": "" })
  // No backend command runs until the flag has been read: a command that
  // raced ahead of it would go out without OMARCHY_AUDIBLE_FAKE.
  property bool flagKnown: false

  function applySettings(raw, moduleName) {
    var step = Settings.applyStep({ "settingsReceived": settingsReceived }, moduleName, raw)
    if (!step.accepted) return
    var booksStep = Settings.settingStep(booksDirSetting, step.settings.booksDir, settingsReceived)
    settingsReceived = step.state.settingsReceived
    var next = step.settings
    skipSeconds = next.skipSeconds
    autoRemoveFinished = next.autoRemoveFinished === "On"
    syncOnOpenHours = next.syncOnOpenHours
    showTitleInBar = next.showTitleInBar
    if (defaultSort !== next.defaultSort) {
      defaultSort = next.defaultSort
      library.sortKey = Settings.sortKey(defaultSort)
    }
    defaultSpeed = next.defaultSpeed
    booksDirSetting = booksStep.value
    if (booksStep.rerunStatus && flagKnown) run("status", [])
    if (store.loaded) applyDefaultSpeedSetting()
  }

  function applyDefaultSpeedSetting() {
    if (!Settings.shouldApplySpeed(settingsReceived, store.loaded)) return
    var choice = Settings.speedChoice(store.doc.speed, defaultSpeed, store.doc.default_speed_setting)
    store.applyDefaultSpeed(defaultSpeed, choice.apply, choice.speed)
    if (choice.apply && player.connected) player.setSpeed(choice.speed)
  }

  // The latest `status` event. All paths come from here; never recompute them.
  property var status: null
  readonly property string dataDir: status && status.data_dir ? String(status.data_dir) : ""

  property var surfaces: []
  property var recentEvents: []
  readonly property int maxEvents: 40

  // The panel's current view, shared by every monitor's widget.
  property string view: Panel.VIEW_LIBRARY
  // The Mini view's chapter popup. Closed whenever the panel opens or the view
  // changes.
  property bool chapterListOpen: false
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
  // The book a `play-info` is being read for (B11; PlayRequest.js), or null.
  // Only the newest request plays: a newer intent or a quit drops it, and a
  // reply for an older one is ignored.
  property var playRequest: null
  property int playSerial: 0
  // Why the last `play-info` failed. With the player's own failure, the
  // views' "Couldn't start playback" line.
  property string playError: ""
  readonly property string playFailure: Player.playFailure(player.connection, player.lastError, playError)
  property var resumeRemotes: ({})

  // ⏯ catching up with other devices (qml/CatchupFlow.qml): the book a ⏯
  // waits on an account read for, and the Mini line after a jump.
  readonly property string catchupAsin: catchupFlow.catchupAsin
  readonly property string catchupNote: catchupFlow.catchupNote
  // The Mini line after a run of `stale` pushes (P6, Sync.staleNotice).
  readonly property string staleNotice: sync.staleNotice

  // The book that is loaded and the last position seen for it. Kept so a
  // switch or a crash can still save where the old book stopped.
  property string snapAsin: ""
  property real snapMs: 0
  // The loaded book advanced while playing, or the user moved it (F38), since
  // it was last saved. Only then is there a new listening position to record
  // or push; a paused book that is merely switched away from, or reattached
  // after a shell restart, must keep its old listening time.
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
  property string lastSyncMessage: ""
  property string lastSyncHint: ""
  property var doctorChecks: []
  property real catalogAgeSeconds: 0
  readonly property string diagnosticText: Diagnostic.build(manifest ? manifest.version : "0.0.1",
    "sync", lastSyncCode, lastSyncMessage, lastSyncHint, doctorChecks)
  readonly property bool syncing: Drawer.syncing(runner.pendingJobs, runner.activeJob)
  readonly property var syncFailure: Drawer.syncFailure(lastSyncCode)
  readonly property var listState: LibraryUi.listState({
    "catalogLoaded": library.catalogLoaded, "syncing": syncing,
    "total": library.allRows.length, "shown": library.count,
    "offline": syncFailure.offline,
    "connectionProblem": Drawer.connectionProblem(authFailed ? "auth_failed" : lastSyncCode),
    "errorCode": authFailed ? "auth_failed" : syncFailure.errorCode
  })
  // A downloaded book plays when its `get` finishes; a finished book far
  // from its end asks first (`askAsin`); a book picked from the drawer
  // reopens the panel on Mini once it is playing (`reopenAsin`).
  property string askAsin: ""
  // A cloud book waiting on "Download up to … ?" (G3 finding 3, PR #44). Any
  // other pick, opening the Library, and the book no longer being a
  // downloadable cloud book (downloaded elsewhere, gone, offline) clear it.
  property string confirmAsin: ""
  readonly property bool confirmStillValid: LibraryUi.confirmValid(confirmAsin, library.rowFor(confirmAsin), syncFailure.offline)
  onConfirmStillValidChanged: if (!confirmStillValid) Qt.callLater(dropInvalidConfirm)
  property string reopenAsin: ""
  // The panel that was open when the book was picked (F19); reopenOnMini
  // opens it again rather than the primary one.
  property var reopenSurface: null
  // Volume and speed waiting for settingsTimer (F21).
  property var pendingSettings: null
  // Books to remove once the player has unloaded them (Removals), for the
  // Library's "removing" state.
  readonly property var removeAfterUnload: removals.waiting
  property real lastSyncAttemptAtMs: 0

  // mpv may report playing before the new path, so check on both.
  onLoadedAsinChanged: {
    reopenOnMini()
    removals.flush()
  }

  // Onboarding and sign-in (U3; qml/SigninFlow.qml owns them). The names
  // the views read. `marketplace` and `clipboardNotice` are aliases because
  // the store picker and the notice's dismiss button assign them.
  readonly property bool reconnecting: signinFlow.reconnecting
  readonly property bool authFailed: signinFlow.authFailed
  property alias marketplace: signinFlow.marketplace
  readonly property var onboardingError: signinFlow.onboardingError
  property alias clipboardNotice: signinFlow.clipboardNotice
  readonly property bool pasteRejected: signinFlow.pasteRejected
  readonly property bool pasteEmpty: signinFlow.pasteEmpty
  readonly property string onboardingStep: signinFlow.onboardingStep
  readonly property string loginPhase: signinFlow.loginPhase
  readonly property bool settingUp: signinFlow.settingUp

  onOnboardingStepChanged: view = Onboarding.view(onboardingStep, player.loaded,
    Signin.requestAfterStep(view, clipboardNotice))

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

  function acknowledgeBooksLocation() {
    return run("books-location-ack", [], "books-location-ack-user")
  }

  function markFlagKnown() {
    if (flagKnown) return
    flagKnown = true
    run("status", [])
  }

  // Called by a widget just before its panel opens.
  function viewForOpen() {
    view = Onboarding.view(onboardingStep, player.loaded, null)
    chapterListOpen = false
    sync.resetRetry()
    catchupFlow.prefetchCatchup()
  }

  function showView(name) {
    if (Panel.VIEWS.indexOf(name) === -1) return
    chapterListOpen = false
    view = Onboarding.view(onboardingStep, player.loaded, name)
  }

  // --- Onboarding (U3): SigninFlow does the work -----------------------------
  function checkStatus() { signinFlow.checkStatus() }
  function startSetup() { return signinFlow.startSetup() }
  function startLogin(code) { return signinFlow.startLogin(code) }
  function finishLogin(pasted) { return signinFlow.finishLogin(pasted) }
  function cancelLogin() { signinFlow.cancelLogin() }
  function importCliLogin() { return signinFlow.importCliLogin() }
  function disconnect() { return signinFlow.disconnect() }
  function reconnect() { signinFlow.reconnect() }
  function copyText(text) { signinFlow.copyText(text) }
  function copyDiagnostic() { signinFlow.copyText(diagnosticText) }
  function readClipboard(target) { signinFlow.readClipboard(target) }

  // Re-sent from SigninFlow for the onboarding views: clipboard chunks for
  // the view that asked, and "clear your paste field".
  signal clipboardRead(var target, string text)
  signal clearPaste()

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

  // Every way into playback ends here. The backend says which file to load
  // and with which key (`play-info`, B11); startPlayInfo does the load.
  function playNow(asin, startSec) {
    // Settings still waiting for the debounce are saved first: an mpv this
    // play launches starts from them (F21).
    saveSettings()
    playError = ""
    playSerial += 1
    var request = PlayRequest.create(asin, startSec, playSerial)
    playRequest = request
    if (run(PlayRequest.COMMAND, [asin], request.purpose)) return "ok"
    playRequest = null
    return failPlay(asin, "", "the backend is not ready")
  }

  // `record` is the play_info event. Its `lavf_options` is the book's key: it
  // goes straight to the player and is kept nowhere here.
  function startPlayInfo(job, record) {
    if (!PlayRequest.matches(playRequest, job)) return
    var startSec = playRequest.startSec
    var asin = playRequest.asin
    playRequest = null
    var row = library.rowFor(asin)
    if (!player.play(String(record.path || ""), startSec,
        { "lavf": record.lavf_options, "chaptersFile": record.chapters_file,
          "title": row ? row.title : "" })) failPlay(asin, "", player.lastError)
  }

  // play-info ended without giving this request a file to play.
  function finishPlayInfo(job, outcome) {
    if (!PlayRequest.matches(playRequest, job)) return
    var asin = playRequest.asin
    playRequest = null
    if (outcome.ok) failPlay(asin, "", "the backend sent no book to play")
    else failPlay(asin, String(outcome.code || ""), String(outcome.message || outcome.code || "unknown error"))
  }

  // The message names the book by its title from the catalog (U10c).
  function failPlay(asin, code, text) {
    var row = library.rowFor(asin)
    var message = Player.playErrorText(code, text, asin, row ? row.title : "")
    playError = message
    notifyPlayFailed(message)
    return "error: " + message
  }

  // Every ⏯ (Mini, Space, middle-click, the `playPause` hotkey). Resuming
  // after a long pause first catches up with the account (CatchupFlow).
  function playPause() { return catchupFlow.press() }

  function notifyPlayFailed(message) {
    var text = String(message || "").length > 0 ? String(message) : "the player did not start"
    logEvent("player", "failed: " + text)
    Quickshell.execDetached(["notify-send", "--app-name=Omarchy Audible",
      "Couldn't start playback", text])
  }

  // A fake-mode mpv must not outlive a switch to real mode (G3 finding 1).
  // Never the other way round: fake mode leaves a real player alone.
  function stopOtherModePlayer() {
    if (root.fake) return
    Quickshell.execDetached(["systemctl", "--user", "stop", "omarchy-audible-fake-mpv.scope"])
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

  // Evaluated on pause, stop and every save tick. A finished book may then be
  // auto-removed (Removals).
  function checkFinished(asin) {
    if (!atEnd(asin)) return
    store.markFinished(asin)
    removals.noteFinished(asin)
  }

  // The saved position for a book: the library's merged one, else the local
  // entry in state.json (the catalog may not have loaded, or lack the book).
  function cachedStartSec(asin) {
    var row = library.rowFor(asin)
    if (row) return row.positionMs / 1000
    var local = store.doc.books ? store.doc.books[asin] : null
    return local && typeof local.ms === "number" ? local.ms / 1000 : 0
  }

  // One line per row for a sort, filter and search, for IPC checks (a test
  // method, see below). The rows come from a copy: the drawer's own sort,
  // filter and search are left as they are (U10a).
  function libraryQuery(sort, filter, search) {
    return Library.queryRows(library.allRows, sort, filter, search).map(function(row) {
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

  // The loaded book has a new listening position (Playback.positionCounts).
  function markMoved() {
    snapDirty = true
    snapUnpushed = true
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
  // A new choice of book wins over every older one: an open question, a
  // resume still reading its position, and a pending removal of this book.
  // A download only downloads; the user plays the book when they choose.
  function noteIntent(asin) {
    catchupFlow.noteIntent()
    askAsin = ""
    confirmAsin = ""
    if (pendingResume !== asin) pendingResume = ""
    // A play still waiting for its play-info is overtaken by any new intent.
    playRequest = null
    removals.dropIntent(asin)
  }

  // Books a removal must not touch: loaded, resuming, waiting for play-info,
  // or about to load.
  function busyAsins() {
    var load = player.pendingLoad ? Playback.asinFromPath(player.pendingLoad.path) : ""
    return [loadedAsin, pendingResume, PlayRequest.busyAsin(playRequest), load]
  }

  // Stop: no play that is still on its way may start the player again.
  function quitPlayer() {
    pendingResume = ""
    playRequest = null
    // Nothing is pending after Stop, so an old play failure is gone too (F37).
    playError = ""
    // A volume or speed changed just now is saved before mpv goes, so the
    // next one starts with it (F21).
    saveSettings()
    player.quit()
  }

  function pick(asin) {
    var row = library.rowFor(asin)
    if (!row) return "error: unknown book"
    // Picking the book whose Resume / Start over question is up answers it
    // with the default, Resume (U10b), instead of asking again.
    if (LibraryUi.pickAnswersAsk(row, askAsin)) return answerAsk(true)
    // Decide first: noteIntent clears confirmAsin, and a second pick of the
    // book whose question is up is what confirms it.
    var decision = LibraryUi.pickDecision(row, syncFailure.offline, confirmAsin)
    noteIntent(asin)
    if (decision === LibraryUi.PICK_CONFIRM) {
      confirmAsin = asin
      return "confirm"
    }
    if (decision === LibraryUi.PICK_PLAY) return playPicked(asin, true)
    if (decision === LibraryUi.PICK_DOWNLOAD || decision === LibraryUi.PICK_RETRY) {
      return run("get", [asin], "download") ? "ok" : "error: refused"
    }
    return "error: nothing to do"
  }

  // The question's Download button: the same as picking that book again.
  function confirmDownload() {
    if (confirmAsin.length === 0) return "error: nothing asked"
    return pick(confirmAsin)
  }

  // Runs after the change that made the question invalid, so clearing it
  // never feeds back into the binding that just changed; checks again in case
  // the question was already replaced.
  function dropInvalidConfirm() {
    if (confirmAsin.length > 0
        && !LibraryUi.confirmValid(confirmAsin, library.rowFor(confirmAsin), syncFailure.offline)) confirmAsin = ""
  }

  function cancelConfirm() {
    confirmAsin = ""
    return "ok"
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
    // The panel the book was picked in reopens, on its own monitor (F19).
    reopenSurface = openSurface()
    if (hidePanel) closeSurfaces()
    reopenAsin = hidePanel || open ? asin : ""
    reopenTimer.restart()
    return playBook(asin, startSec)
  }

  function anySurfaceOpen() {
    return surfaces.some(function(s) { return s.opened === true })
  }

  // The open panel, or null.
  function openSurface() {
    for (var i = 0; i < surfaces.length; i++) {
      if (surfaces[i].opened === true) return surfaces[i]
    }
    return null
  }

  function closeSurfaces() {
    chapterListOpen = false
    surfaces.forEach(function(s) { if (s.opened) s.close() })
  }

  // Playback of the picked book began: show it on Mini.
  function reopenOnMini() {
    if (reopenAsin.length === 0 || !player.playing || loadedAsin !== reopenAsin) return
    reopenAsin = ""
    reopenTimer.stop()
    var remembered = reopenSurface
    reopenSurface = null
    if (anySurfaceOpen()) {
      showView(Panel.VIEW_MINI)
    } else {
      // The monitor's widget may have gone since (a monitor unplugged).
      var surface = remembered && surfaces.indexOf(remembered) >= 0 ? remembered : primarySurface()
      if (surface) surface.open()
    }
  }

  // Opening the drawer on Library syncs when the catalog is old (FR-L2).
  function libraryOpened() {
    // A question left from an earlier visit is not one the user sees now.
    confirmAsin = ""
    var now = Date.now()
    if (syncing || Drawer.autoSyncBlocked(lastSyncAttemptAtMs, now)) return
    refreshCatalogAge()
    var age = catalogAgeSeconds
    if (LibraryUi.syncDue(age, syncOnOpenHours)) startSync("auto")
  }

  function refreshCatalogAge() {
    catalogAgeSeconds = Drawer.catalogAgeS(status ? status.catalog_age_s : null,
      statusAtMs, lastSyncAtMs, Date.now())
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
  // (the player saves its position) and removed once it is gone (Removals).
  // `purpose` is Unload.PURPOSE_AUTO for an auto-remove, else the user's.
  function removeBook(asin, purpose) {
    if (!Drawer.canRemove(library.rowFor(asin))) return "error: not removable"
    // A question about a book being removed no longer has a file to play.
    if (askAsin === asin) askAsin = ""
    // Removing is newer than a play of this book still on its way (a resume
    // read or a play-info): drop it, or its reply would start the book again.
    if (PlayRequest.busyAsin(playRequest) === asin) playRequest = null
    if (pendingResume === asin) pendingResume = ""
    if (asin === loadedAsin) return removals.unloadThenRemove(asin, purpose === Unload.PURPOSE_AUTO ? purpose : Unload.PURPOSE_USER)
    return run("remove", [asin], "user") ? "ok" : "error: refused"
  }

  function removeAll() { return removals.removeAll() }


  function refreshLocal() {
    run("local", [])
  }

  function downloadActive() {
    return BooksLocation.hasActiveGet(runner.activeJob, runner.pendingJobs)
  }

  function reloadSync() {
    catalogFile.reload()
    remoteFile.reload()
    library.rescanCovers()
  }

  function playerSummary() {
    return JSON.stringify({
      "connection": player.connection, "error": player.lastError, "playError": root.playError,
      "loaded": player.loaded, "playing": player.playing,
      "positionMs": player.positionMs, "durationMs": player.durationMs,
      "chapterIndex": player.chapterIndex, "chapters": player.chapters.length,
      "speed": player.speed, "volume": player.volume,
      "sleep": player.sleepTimer ? player.sleepTimer.mode : null,
      "catchupNote": root.catchupNote
    })
  }

  // The player's volume (before any sleep fade) and speed, captured now and
  // written to state.json once they have settled for a second (F21).
  function noteSettings() {
    if (!player.connected) return
    pendingSettings = { "volume": Mpv.userVolume(player.volume, player.fadeBaseVolume), "speed": player.speed }
    settingsTimer.restart()
  }

  function saveSettings() {
    settingsTimer.stop()
    if (!pendingSettings) return
    store.setPlayerSettings(pendingSettings.volume, pendingSettings.speed)
    pendingSettings = null
  }

  function logEvent(label, text) {
    var entry = { "label": label, "text": text }
    recentEvents = recentEvents.concat([entry]).slice(-maxEvents)
  }

  PlayerController {
    id: player
    socketPath: root.runtimeDir.length > 0 ? root.runtimeDir + "/mpv.sock" : ""
    mprisScript: root.status && typeof root.status.mpris_script === "string" ? root.status.mpris_script : ""
    // The saved volume and speed (F21). Without a saved volume, low in fake
    // mode: the fake book is a sine wave.
    initialVolume: Mpv.startVolume(store.doc.volume, root.fake ? 15 : 100)
    initialSpeed: Mpv.startSpeed(store.doc.speed, root.defaultSpeed)
    unitName: root.fake ? "omarchy-audible-fake-mpv" : "omarchy-audible-mpv"
    // Reattach once the paths are known.
    onSocketPathChanged: if (socketPath.length > 0) {
      root.stopOtherModePlayer()
      attach()
    }
  }

  LibraryModel {
    id: library
    stateDoc: store.doc
    coversDir: root.dataDir.length > 0 ? root.dataDir + "/covers" : ""
    jobs: Playback.jobStates(runner.pendingJobs, runner.activeJob, runner.progress, root.failures)
  }

  Connections {
    target: store
    function onLoadedChanged() { if (store.loaded) root.applyDefaultSpeedSetting() }
  }

  CatchupFlow {
    id: catchupFlow
    service: root
    player: player
    store: store
    sync: sync
  }

  SigninFlow {
    id: signinFlow
    service: root
    runner: runner
    onClipboardRead: function(target, text) { root.clipboardRead(target, text) }
    onClearPaste: root.clearPaste()
  }

  Removals {
    id: removals
    service: root
    player: player
    library: library
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

    function onExternalUnload() {
      if (!Playback.externalUnload(player.connected, player.wanted, player.loaded,
          player.quitting, player.loadArrived, root.snapAsin)) return
      root.savePosition(root.snapAsin, root.snapMs, true)
      root.quitPlayer()
    }

    function onPathChanged() {
      root.onBookSwitched()
      if (Panel.libraryAfterUnload(player.loaded, player.wanted)) root.showView(root.view)
    }

    function onPositionMsChanged() {
      // A null time-pos (a file being swapped) is not a position, and nothing
      // mpv reports while a load is on its way is the snapshot book's (F39).
      if (!Playback.reportBelongs(player.derived.hasPosition, Playback.asinFromPath(player.path), root.snapAsin,
          Mpv.moveHitsPath(player.path, player.loadPath, player.loadArrived))) return
      root.snapMs = player.positionMs
      if (Playback.positionCounts("report", player.playing)) root.markMoved()
    }

    // A seek, skip or chapter jump made while paused is saved too (F38). The
    // snapshot takes where it lands at once, so a quit or restart before mpv
    // reports it still saves the move; the report then refines it.
    function onUserMoved(targetMs) {
      if (Playback.asinFromPath(player.path) !== root.snapAsin || !Playback.positionCounts("user", player.playing)) return
      if (targetMs >= 0) root.snapMs = targetMs
      root.markMoved()
    }

    // Pause, stop or a crash: save where the book stopped.
    function onPlayingChanged() {
      if (!player.playing) {
        catchupFlow.notePaused()
        root.savePosition(root.snapAsin, root.snapMs, true)
      } else {
        // Something plays again: an earlier play-info failure is old news.
        root.playError = ""
        root.reopenOnMini()
        sync.resetRetry()
      }
    }

    // Volume and speed are saved a moment after they settle (F21). Only an
    // mpv that is connected reports real values; a disconnect resets them to
    // defaults, which must not be saved.
    function onVolumeChanged() { root.noteSettings() }
    function onSpeedChanged() { root.noteSettings() }

    // A play that never started says so (G3 finding 2). lastError is set
    // after the connection changes, so read it a moment later.
    function onConnectionChanged() {
      if (player.connection === "failed") Qt.callLater(function() { root.notifyPlayFailed(player.lastError) })
    }
  }

  Timer {
    interval: root.saveIntervalMs
    repeat: true
    running: player.playing
    onTriggered: root.savePosition(root.snapAsin, root.snapMs, false)
  }

  // A pick whose playback never starts stops waiting to reopen the panel.
  Timer {
    id: reopenTimer
    interval: 15000
    repeat: false
    onTriggered: root.reopenAsin = ""
  }

  Timer {
    id: settingsTimer
    interval: 1000
    repeat: false
    onTriggered: root.saveSettings()
  }

  // Push about once a minute while playing.
  Timer {
    interval: root.pushIntervalMs
    repeat: true
    running: player.playing
    onTriggered: root.savePosition(root.snapAsin, root.snapMs, true)
  }

  // Shell IPC target (ARCHITECTURE 6): the one IpcHandler, a child of the
  // service (qml/ServiceIpc.qml).
  ServiceIpc {
    service: root
    library: library
    player: player
    runner: runner
    store: store
    sync: sync
    signin: signinFlow
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
    gate: removals.jobAllowed
    launcher: root.pluginDir + "/bin/omarchy-audible"
    environment: {
      var values = root.fake ? { "OMARCHY_AUDIBLE_FAKE": "1" } : {}
      if (root.booksDirSetting !== Settings.DEFAULTS.booksDir)
        values.OMARCHY_AUDIBLE_BOOKS_DIR = root.booksDirSetting
      return values
    }

    onEvent: function(record, job) {
      var silentAckFailure = ""
      if (record.type === "status") {
        root.status = record
        root.statusAtMs = Date.now()
        root.refreshCatalogAge()
        root.refreshLocal()
        var ackStep = BooksLocation.ackStep(root.booksAckState, record,
          root.downloadActive(), root.settingsReceived)
        root.booksAckState = ackStep.state
        if (ackStep.log) silentAckFailure = String(record.books_dir || "")
        if (ackStep.ack)
          root.run("books-location-ack", ["--if-no-old-books"], "books-location-ack-silent")
      } else if (record.type === "local") {
        library.localBooks = record.books
      } else if (record.type === "doctor" && job.purpose === "sync-doctor") {
        root.doctorChecks = record.checks || []
      } else if (record.type === "play_info") {
        root.startPlayInfo(job, record)
      } else if (record.type === "positions" && job.purpose === "resume") {
        var resumed = job.args[0]
        var remotes = root.resumeRemotes
        remotes[resumed] = record.items[resumed] || null
        root.resumeRemotes = remotes
      }
      catchupFlow.handleEvent(record, job)
      sync.handleEvent(record, job)
      signinFlow.handleEvent(record, job)
      if (silentAckFailure.length > 0)
        root.logEvent("books-location-ack-silent", "ack did not record " + silentAckFailure)
      root.logEvent(job.command, Signin.logText(job.command, record.type,
        Signin.isOnboardingCommand(job.command) ? "" : EventLog.summarize(record, 160)))
    }

    onJobFinished: function(job, outcome) {
      var text = outcome.ok ? "ok" : String(outcome.code) + (Signin.isOnboardingCommand(job.command)
        ? "" : ": " + String(outcome.message || ""))
      signinFlow.handleFinished(job, outcome)
      root.logEvent(job.command + " exit", text)
      root.failures = Playback.updateFailures(root.failures, job, outcome)
      sync.handleFinished(job, outcome)
      catchupFlow.handleFinished(job, outcome)
      if (job.command === PlayRequest.COMMAND) root.finishPlayInfo(job, outcome)
      if (job.purpose === "resume") {
        var resumedAsin = job.args[0]
        var remote = outcome.ok ? (root.resumeRemotes[resumedAsin] || null) : null
        delete root.resumeRemotes[resumedAsin]
        root.finishResume(resumedAsin, remote)
      }
      if (job.command === "sync") {
        root.lastSyncCode = outcome.ok ? "" : String(outcome.code || "internal")
        root.lastSyncMessage = outcome.ok ? "" : String(outcome.message || "")
        root.lastSyncHint = outcome.ok ? "" : String(outcome.hint || "")
        if (outcome.ok) {
          root.lastSyncAtMs = Date.now()
          root.refreshCatalogAge()
          root.doctorChecks = []
        }
        if (!outcome.ok && Drawer.connectionProblem(root.lastSyncCode)) {
          root.doctorChecks = []
          root.run("doctor", [], "sync-doctor")
        }
        root.reloadSync()
      } else if (job.command === "doctor" && job.purpose === "sync-doctor") {
        if (!outcome.ok) root.doctorChecks = []
      } else if (job.command === "position-get") {
        remoteFile.reload()
      } else if (job.command === "get" || job.command === "remove") {
        root.run("status", [])
      }
      if (job.command === "books-location-ack" && outcome.ok) root.run("status", [])
    }
  }

  Component.onCompleted: {
    if (devFlag.loaded) markFlagKnown()
  }

  // Shutdown: save where the book is, and wait for the write.
  Component.onDestruction: {
    saveSettings()
    if (snapAsin.length > 0 && (snapDirty || snapUnpushed)) {
      if (snapDirty) store.record(snapAsin, snapMs)
      sync.queuePush(snapAsin)
    }
    store.flush()
  }
}

import QtQuick
import Quickshell
import Quickshell.Io
import "qml"
import "qml/lib/Catchup.js" as Catchup
import "qml/lib/Drawer.js" as Drawer
import "qml/lib/EventLog.js" as EventLog
import "qml/lib/Format.js" as Format
import "qml/lib/Ipc.js" as Ipc
import "qml/lib/Library.js" as Library
import "qml/lib/LibraryUi.js" as LibraryUi
import "qml/lib/Mpv.js" as Mpv
import "qml/lib/Onboarding.js" as Onboarding
import "qml/lib/Panel.js" as Panel
import "qml/lib/Playback.js" as Playback
import "qml/lib/Player.js" as Player
import "qml/lib/PlayRequest.js" as PlayRequest
import "qml/lib/Positions.js" as Positions
import "qml/lib/Signin.js" as Signin

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
  property string removeCandidate: ""
  property var resumeRemotes: ({})

  // ⏯ catching up with other devices (Catchup.js). `pausedAtMs` is when the
  // player last paused (0 = unknown, e.g. after a shell restart);
  // `catchupAsin` is the book waiting on an account read before it resumes;
  // `catchupReads` the books with a read queued or running (at most one per
  // book, so overlapping reads never share a result); `prefetched`
  // the last finished read, `{asin, atMs, remote}`.
  property real pausedAtMs: 0
  property string catchupAsin: ""
  property var catchupReads: ({})
  property var prefetched: null
  // Results of catch-up reads still running, by ASIN (like `resumeRemotes`),
  // so overlapping reads of different books never touch each other's result.
  property var catchupResults: ({})
  // The Mini line after a catch-up jump (Catchup.jumpNote), cleared after
  // NOTE_MS or by a new pick.
  property string catchupNote: ""
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
  // The user moved the loaded book and mpv hasn't reported where it landed
  // yet (F38, Playback.moveSentAfter).
  property bool moveSent: false
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
    "offline": syncFailure.offline, "errorCode": authFailed ? "auth_failed" : syncFailure.errorCode
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
  // Books to remove once the player has unloaded them.
  property var removeAfterUnload: []
  property real lastSyncAttemptAtMs: 0

  // mpv may report playing before the new path, so check on both.
  onLoadedAsinChanged: {
    reopenOnMini()
    flushRemovals()
  }

  // Onboarding (U3). `reconnecting` reopens Connect after `auth_failed`;
  // `authFailed` drives the Library's reconnect banner. `loginSession` is
  // the open sign-in session id (not a secret; the pasted text never lands
  // in a property here). `onboardingError` is `Onboarding.errorText` output.
  property bool reconnecting: false
  property bool authFailed: false
  property string loginSession: ""
  property string marketplace: Signin.DEFAULT_MARKETPLACE
  property var onboardingError: null
  property string clipboardNotice: ""
  property bool pasteRejected: false
  property bool pasteEmpty: false
  readonly property string onboardingStep: Signin.effectiveStep(Onboarding.step(status), reconnecting)
  readonly property string loginPhase: Signin.phase(loginSession, loginStarting,
    Signin.jobPending("login-finish", runner.pendingJobs, runner.activeJob))
  property bool loginStarting: false
  readonly property bool settingUp: Signin.jobPending("setup", runner.pendingJobs, runner.activeJob)

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
    prefetchCatchup()
  }

  function showView(name) {
    if (Panel.VIEWS.indexOf(name) === -1) return
    chapterListOpen = false
    view = Onboarding.view(onboardingStep, player.loaded, name)
  }

  // --- Onboarding (U3) -------------------------------------------------------
  function checkStatus() {
    run("status", [])
  }

  function startSetup() {
    onboardingError = null
    return run("setup", [], "setup") ? "ok" : "error: refused"
  }

  function startLogin(code) {
    onboardingError = null
    pasteRejected = false
    loginSession = ""
    marketplace = code
    loginStarting = true
    if (!run("login-start", ["--marketplace", code], "login")) {
      loginStarting = false
      return "error: refused"
    }
    return "ok"
  }

  // The pasted text goes straight to the backend's stdin (never argv, a log,
  // an event or a property) and is dropped by the caller right after.
  function finishLogin(pasted) {
    if (loginSession.length === 0) return "error: no session"
    pasteEmpty = !/\S/.test(pasted || "")
    if (pasteEmpty || !Onboarding.looksLikeRedirect(pasted)) {
      pasteRejected = true
      return "rejected"
    }
    pasteRejected = false
    onboardingError = null
    var sent = runner.runWithInput("login-finish", ["--session", loginSession], "login", pasted)
    clearPaste()
    return sent ? "ok" : "error: refused"
  }

  function cancelLogin() {
    clearPaste()
    loginSession = ""
    pasteRejected = false
    onboardingError = null
  }

  function importCliLogin() {
    onboardingError = null
    return run("login-import-cli", [], "login") ? "ok" : "error: refused"
  }

  function disconnect() {
    return run("logout", [], "logout") ? "ok" : "error: refused"
  }

  function reconnect() {
    reconnecting = true
    cancelLogin()
    showView(Panel.VIEW_ONBOARDING)
  }

  function openUrl(url) {
    opener.command = ["xdg-open", url]
    opener.running = true
  }

  // Clipboard I/O for the onboarding view: copy the install command, and read
  // the clipboard for "Paste from clipboard" (the text goes back to the view
  // through `clipboardRead` in chunks, never into a property). The view
  // clears its field before calling `readClipboard` and appends each chunk.
  // `target` is the view that asked, so another monitor's field never fills.
  signal clipboardRead(var target, string text)
  // Every view clears its paste field: the text was sent, or sign-in ended.
  signal clearPaste()
  property var clipboardTarget: null

  function copyText(text) {
    copier.text = String(text)
    copier.running = true
  }

  function readClipboard(target) {
    clipboardTarget = target
    paster.running = true
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
    if (!player.play(String(record.path || ""), startSec,
        { "lavf": record.lavf_options, "chaptersFile": record.chapters_file })) failPlay(asin, "", player.lastError)
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

  // Every ⏯ (Mini, Space, middle-click, the `playPause` hotkey). Pausing is
  // immediate. Resuming after a long pause first reads the account, so a book
  // listened to on the phone continues from there (SCOPE FR-P4); a second ⏯
  // while that read runs cancels the resume.
  function playPause() {
    var asin = loadedAsin
    var action = Catchup.pressAction({ "loaded": player.loaded, "playing": player.playing,
      "waiting": catchupAsin.length > 0, "pendingResume": pendingResume.length > 0,
      "needsRead": Catchup.needsRead(pausedAtMs, Date.now()),
      "prefetchUsable": Catchup.prefetchUsable(prefetched, asin, Date.now()),
      "reading": catchupReads[asin] === true })
    if (action === Catchup.PRESS_NONE) return "error: nothing loaded"
    if (action === Catchup.PRESS_PAUSE) {
      cancelCatchup()
      player.pause()
      return "ok"
    }
    if (action === Catchup.PRESS_CANCEL) {
      cancelCatchup()
      return "cancelled"
    }
    if (action === Catchup.PRESS_BUSY) return "busy"
    if (action === Catchup.PRESS_RESUME) {
      player.resume()
      return "ok"
    }
    if (action === Catchup.PRESS_PREFETCH) {
      resumeCaughtUp(asin, prefetched.remote)
      return "ok"
    }
    catchupAsin = asin
    catchupTimer.restart()
    if (action === Catchup.PRESS_READ && !readCatchup(asin)) resumeCaughtUp(asin, null)
    return "checking"
  }

  // Drops a waiting ⏯; the read itself finishes and is kept as `prefetched`.
  function cancelCatchup() {
    catchupAsin = ""
    catchupTimer.stop()
  }

  // Opening the drawer on a book paused long enough starts the read early,
  // so ⏯ usually finds it done.
  function prefetchCatchup() {
    if (!player.loaded || player.playing || catchupReads[loadedAsin] === true) return
    var asin = loadedAsin
    if (!Catchup.needsRead(pausedAtMs, Date.now()) || Catchup.prefetchUsable(prefetched, asin, Date.now())) return
    readCatchup(asin)
  }

  function readCatchup(asin) {
    if (!run("position-get", [asin], "catchup")) return false
    var reads = catchupReads
    reads[asin] = true
    catchupReads = reads
    return true
  }

  // Resume `asin`, first jumping to `remote` (an account entry, or null)
  // when it is newer than the position saved here.
  function resumeCaughtUp(asin, remote) {
    cancelCatchup()
    prefetched = null
    // An unread state.json is not "nothing saved here": resume in place.
    var action = Catchup.resumeAction({ "loaded": player.loaded, "sameBook": loadedAsin === asin,
      "playing": player.playing, "storeLoaded": store.loaded, "hasRemote": !!remote })
    if (action === "none") return
    if (action === "compare") {
      var local = store.doc.books ? store.doc.books[asin] : null
      var own = [sync.lastPushed[asin], local ? local.ms : null]
      var target = Catchup.jumpTarget(player.positionMs,
        local ? Positions.parseUpdatedAt(local.updated_at) : null,
        remote.ms, Positions.parseUpdatedAt(remote.updated_at), own)
      if (target >= 0) {
        logEvent("catchup", "jump " + Math.round(player.positionMs) + " -> " + target)
        showCatchupNote(Format.clock(player.positionMs))
        player.jumpToMs(target)
      }
    }
    player.resume()
  }

  function showCatchupNote(was) {
    catchupNote = Catchup.jumpNote(was)
    catchupNoteTimer.restart()
  }

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
    if (!Positions.autoRemoveAllowed(autoRemoveFinished, atEnd(asin), player.playing)) return
    // The loaded book goes the way the user's Remove does: unload first, then
    // remove once mpv has let go of the file (F17).
    if (asin === loadedAsin) removeBook(asin)
    else run("remove", [asin], "autoremove")
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
  // Only the position handler calls this.
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
    moveSent = Playback.moveSentAfter(moveSent, "switch")
  }

  // Picking a Library row (FR-L6, ARCHITECTURE 6). `LibraryUi` decides what
  // the pick means; a local book resumes, starts over or asks.
  // A new choice of book wins over every older one: an open question, a
  // resume still reading its position, and a pending removal of this book.
  // A download only downloads; the user plays the book when they choose.
  function noteIntent(asin) {
    cancelCatchup()
    catchupNote = ""
    askAsin = ""
    confirmAsin = ""
    if (pendingResume !== asin) pendingResume = ""
    // A play still waiting for its play-info is overtaken by any new intent.
    playRequest = null
    removeAfterUnload = removeAfterUnload.filter(function(a) { return a !== asin })
    if (removeAfterUnload.length === 0) unloadTimer.stop()
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
    // Removing is newer than a play of this book still on its way (a resume
    // read or a play-info): drop it, or its reply would start the book again.
    if (PlayRequest.busyAsin(playRequest) === asin) playRequest = null
    if (pendingResume === asin) pendingResume = ""
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


  function onboardingFinished(job, outcome) {
    if (job.command === "login-start") {
      loginStarting = false
      if (!outcome.ok) onboardingError = Onboarding.errorText(outcome.code, outcome.message, outcome.hint)
      return
    }
    if (!outcome.ok && outcome.code !== "skipped") {
      onboardingError = Onboarding.errorText(outcome.code, outcome.message, outcome.hint)
      // An expired or used session can't be retried; start over.
      if (job.command === "login-finish") loginSession = ""
    }
    if (outcome.ok && Signin.isSignIn(job.command)) {
      loginSession = ""
      reconnecting = false
      authFailed = false
      onboardingError = null
      startSync("signin")
    }
    if (outcome.ok && job.command === "logout") {
      clipboardNotice = ""
      reconnecting = false
      authFailed = false
    }
    if (Signin.refreshesStatus(job.command)) checkStatus()
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
    // The saved volume and speed (F21). Without a saved volume, low in fake
    // mode: the fake book is a sine wave.
    initialVolume: Mpv.startVolume(store.doc.volume, root.fake ? 15 : 100)
    initialSpeed: Mpv.startSpeed(store.doc.speed)
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
      if (Playback.positionCounts(player.playing, root.moveSent)) root.markMoved()
      root.moveSent = Playback.moveSentAfter(root.moveSent, "report")
    }

    // A seek, skip or chapter jump made while paused is saved too (F38), once
    // mpv reports where it landed (onPositionMsChanged).
    function onUserMoved() {
      if (Playback.asinFromPath(player.path) === root.snapAsin) root.moveSent = Playback.moveSentAfter(root.moveSent, "user")
    }

    // Pause, stop or a crash: save where the book stopped.
    function onPlayingChanged() {
      if (!player.playing) {
        root.pausedAtMs = Date.now()
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
    id: catchupNoteTimer
    interval: Catchup.NOTE_MS
    repeat: false
    onTriggered: root.catchupNote = ""
  }

  Timer {
    id: catchupTimer
    interval: Catchup.READ_TIMEOUT_MS
    repeat: false
    onTriggered: root.resumeCaughtUp(root.catchupAsin, null)
  }

  Timer {
    interval: root.saveIntervalMs
    repeat: true
    running: player.playing
    onTriggered: root.savePosition(root.snapAsin, root.snapMs, false)
  }

  Process {
    id: opener
  }

  Process {
    id: copier
    property string text: ""
    stdinEnabled: true
    onStarted: {
      write(text)
      text = ""
      stdinEnabled = false
    }
    onExited: stdinEnabled = true
    command: ["wl-copy"]
  }

  Process {
    id: paster
    command: ["wl-paste", "--no-newline"]
    // Chunks go straight to the view's field; nothing here keeps them.
    stdout: SplitParser {
      splitMarker: ""
      onRead: function(chunk) { root.clipboardRead(root.clipboardTarget, chunk) }
    }
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
    id: settingsTimer
    interval: 1000
    repeat: false
    onTriggered: root.saveSettings()
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
      return root.playPause()
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

    // Test methods so agents can drive the service without input. Each one
    // works only in fake mode and returns Ipc.DEV_ONLY otherwise (H1 F27);
    // Ipc.js lists the public and read-only status methods that stay.
    function play(asin: string): string { if (!root.fake) return Ipc.DEV_ONLY; root.noteIntent(asin); return root.playBook(asin, -1) }
    function playAt(asin: string, startSec: string): string { if (!root.fake) return Ipc.DEV_ONLY; root.noteIntent(asin); return root.playBook(asin, Number(startSec) || 0) }
    function pause(): string { if (!root.fake) return Ipc.DEV_ONLY; player.pause(); return "ok" }
    function resume(): string { if (!root.fake) return Ipc.DEV_ONLY; player.resume(); return "ok" }
    function chapter(index: string): string { if (!root.fake) return Ipc.DEV_ONLY; player.setChapter(Number(index) || 0); return "ok" }
    function speed(value: string): string { if (!root.fake) return Ipc.DEV_ONLY; player.setSpeed(Number(value)); return "ok" }
    function volume(value: string): string { if (!root.fake) return Ipc.DEV_ONLY; player.setVolume(Number(value)); return "ok" }
    function sleepMinutes(minutes: string): string { if (!root.fake) return Ipc.DEV_ONLY; player.setSleepTimer(Number(minutes) || 0); return "ok" }
    function sleepChapter(): string { if (!root.fake) return Ipc.DEV_ONLY; player.setSleepEndOfChapter(); return "ok" }
    function sleepCancel(): string { if (!root.fake) return Ipc.DEV_ONLY; player.cancelSleep(); return "ok" }
    function quitPlayer(): string { if (!root.fake) return Ipc.DEV_ONLY; root.quitPlayer(); return "ok" }
    function playerStatus(): string { return root.playerSummary() }
    function libraryQuery(sort: string, filter: string, search: string): string { if (!root.fake) return Ipc.DEV_ONLY; return root.libraryQuery(sort, filter, search) }
    function flushState(): string { if (!root.fake) return Ipc.DEV_ONLY; store.flush(); return "ok" }
    function syncNow(): string { if (!root.fake) return Ipc.DEV_ONLY; return root.run("sync", [], "ipc") ? "ok" : "refused" }
    function pick(asin: string): string { if (!root.fake) return Ipc.DEV_ONLY; return root.pick(asin) }
    function answer(choice: string): string { if (!root.fake) return Ipc.DEV_ONLY; return root.answerAsk(choice === "resume") }
    function confirmDownload(): string { if (!root.fake) return Ipc.DEV_ONLY; return root.confirmDownload() }
    function cancelConfirm(): string { if (!root.fake) return Ipc.DEV_ONLY; return root.cancelConfirm() }
    function removeBook(asin: string): string { if (!root.fake) return Ipc.DEV_ONLY; return root.removeBook(asin) }
    function libraryState(): string {
      return JSON.stringify({ "list": root.listState, "ask": root.askAsin, "confirm": root.confirmAsin, "reopen": root.reopenAsin,
        "syncing": root.syncing, "lastSyncCode": root.lastSyncCode, "count": library.count,
        "total": library.allRows.length, "storage": LibraryUi.storage(library.localBooks) })
    }
    function onboardingState(): string {
      var st = root.status || {}
      return JSON.stringify({ "step": root.onboardingStep, "phase": root.loginPhase,
        "reconnecting": root.reconnecting, "authFailed": root.authFailed, "error": root.onboardingError,
        "pasteRejected": root.pasteRejected, "pasteEmpty": root.pasteEmpty, "notice": root.clipboardNotice.length > 0,
        "authenticated": st.authenticated === true, "venvReady": st.venv_ready, "missing": st.missing || [],
        "account": st.account || null, "marketplace": st.marketplace || null, "view": root.view,
        "heldInputs": Object.keys(runner.inputs).length })
    }
    // Onboarding actions for tests: fake mode only, so IPC can never sign in,
    // sign out or set up the real account.
    function fakeOnboarding(action: string, arg: string): string {
      if (!root.fake) return Ipc.DEV_ONLY
      if (action === "status") { root.checkStatus(); return "ok" }
      if (action === "setup") return root.startSetup()
      if (action === "login") return root.startLogin(arg.length > 0 ? arg : Signin.DEFAULT_MARKETPLACE)
      if (action === "finish") return root.finishLogin(arg)
      if (action === "import") return root.importCliLogin()
      if (action === "logout") return root.disconnect()
      if (action === "reconnect") { root.reconnect(); return "ok" }
      if (action === "authfail") { root.authFailed = true; return "ok" }
      return "error: unknown action"
    }
    // Fake mode only: a download that fails with a `--fake-fail` mode.
    function fakeFailGet(asin: string, mode: string): string {
      if (!root.fake) return Ipc.DEV_ONLY
      return root.run("get", [asin, "--fake-fail", mode], "download") ? "ok" : "refused"
    }
    function autoRemove(value: string): string { if (!root.fake) return Ipc.DEV_ONLY; root.autoRemoveFinished = value === "on"; return "ok" }
    function pushState(): string { return JSON.stringify({ "queue": sync.queue, "flushing": sync.flushing, "last": sync.lastResult,
      "staleCount": sync.consecutiveStale, "staleNotice": sync.staleNotice,
      "failedFlushes": sync.failedFlushes, "retryMs": sync.retryIntervalMs }) }
    // Opens the panel on a view (Onboarding.view still decides: Mini or Full
    // with nothing loaded shows the Library). Returns the view shown. Fake
    // mode only: opening the panel can read positions or start a sync.
    function view(name: string): string {
      if (!root.fake) return Ipc.DEV_ONLY
      if (Panel.VIEWS.indexOf(name) === -1) return "error: unknown view"
      var surface = root.primarySurface()
      if (!surface) return "error: no surface"
      if (!surface.opened) surface.open()
      root.showView(name)
      return root.view
    }
    function chapterList(state: string): string {
      if (!root.fake) return Ipc.DEV_ONLY
      if (state !== "open" && state !== "close") return "error: open or close"
      if (state === "open" && (!player.loaded || player.chapters.length === 0)) return "error: no chapters"
      root.chapterListOpen = state === "open"
      return "ok"
    }
    function panelState(): string {
      var open = root.surfaces.some(function(s) { return s.opened === true })
      return JSON.stringify({ "open": open, "view": root.view, "chapterList": root.chapterListOpen,
        "glyph": root.barGlyph, "tooltip": root.tooltipText })
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
      } else if (record.type === "positions" && job.purpose === "catchup") {
        var read = job.args[0]
        var results = root.catchupResults
        results[read] = { "asin": read, "atMs": Date.now(), "remote": record.items[read] || null }
        root.catchupResults = results
      } else if (record.type === "play_info") {
        root.startPlayInfo(job, record)
      } else if (record.type === "positions" && job.purpose === "resume") {
        var resumed = job.args[0]
        var remotes = root.resumeRemotes
        remotes[resumed] = record.items[resumed] || null
        root.resumeRemotes = remotes
      }
      sync.handleEvent(record, job)
      if (job.command === "login-start" && record.type === "login_url") {
        root.loginStarting = false
        root.loginSession = String(record.session || "")
        // Fake mode's link is a dummy Amazon address: don't open a browser.
        if (root.fake) root.logEvent("login-start", "fake: browser not opened")
        else root.openUrl(String(record.url || ""))
      } else if (job.command === "login-finish" && record.type === "done") {
        root.clipboardNotice = Onboarding.clipboardNotice(record)
      }
      root.logEvent(job.command, Signin.logText(job.command, record.type,
        Signin.isOnboardingCommand(job.command) ? "" : EventLog.summarize(record, 160)))
    }

    onJobFinished: function(job, outcome) {
      var text = outcome.ok ? "ok" : String(outcome.code) + (Signin.isOnboardingCommand(job.command)
        ? "" : ": " + String(outcome.message || ""))
      if (Signin.authFailed(outcome)) root.authFailed = true
      if (Signin.isOnboardingCommand(job.command)) root.onboardingFinished(job, outcome)
      root.logEvent(job.command + " exit", text)
      root.failures = Playback.updateFailures(root.failures, job, outcome)
      sync.handleFinished(job, outcome)
      if (job.purpose === "catchup") {
        var readAsin = job.args[0]
        var reads = root.catchupReads
        delete reads[readAsin]
        root.catchupReads = reads
        var result = outcome.ok ? (root.catchupResults[readAsin] || null) : null
        delete root.catchupResults[readAsin]
        // Only this read's own book: a failed read of A never clears B's.
        if (result) root.prefetched = result
        else if (root.prefetched && root.prefetched.asin === readAsin) root.prefetched = null
        if (Catchup.readResumes(root.catchupAsin, readAsin)) root.resumeCaughtUp(readAsin, result ? result.remote : null)
      }
      if (job.command === PlayRequest.COMMAND) root.finishPlayInfo(job, outcome)
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

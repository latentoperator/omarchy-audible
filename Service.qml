import QtQuick
import Quickshell
import Quickshell.Io
import "qml"
import "qml/lib/DebugCatalog.js" as DebugCatalog
import "qml/lib/Ipc.js" as Ipc

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
  function playBook(asin, startSec) {
    if (booksDir.length === 0) return "error: status not read yet"
    if (!/^[A-Za-z0-9]+$/.test(asin)) return "error: bad asin"
    return player.play(booksDir + "/" + asin + "/book.m4b", startSec) ? "ok" : "error: " + player.lastError
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

    // TEMPORARY dev methods (removed in U1), kept while the debug panel exists.
    function play(asin: string): string { return root.playBook(asin, 0) }
    function playAt(asin: string, startSec: string): string { return root.playBook(asin, Number(startSec) || 0) }
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
  }

  JobRunner {
    id: runner
    launcher: root.pluginDir + "/bin/omarchy-audible"
    environment: root.fake ? ({ "OMARCHY_AUDIBLE_FAKE": "1" }) : ({})

    onEvent: function(record, job) {
      if (record.type === "status") {
        root.status = record
      }
      root.logEvent(job.command, DebugCatalog.summarize(record, 160))
    }

    onJobFinished: function(job, outcome) {
      var text = outcome.ok ? "ok" : String(outcome.code) + ": " + String(outcome.message || "")
      root.logEvent(job.command + " exit", text)
      if (job.command === "sync") {
        catalogFile.reload()
      }
    }
  }

  Component.onCompleted: if (devFlag.loaded) markFlagKnown()
}

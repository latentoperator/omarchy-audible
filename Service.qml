import QtQuick
import Quickshell
import Quickshell.Io
import "qml"
import "qml/lib/DebugCatalog.js" as DebugCatalog

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

  function logEvent(label, text) {
    var entry = { "label": label, "text": text }
    recentEvents = recentEvents.concat([entry]).slice(-maxEvents)
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

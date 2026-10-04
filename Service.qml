import QtQuick
import Quickshell
import Quickshell.Io

// Headless singleton. Owns the backend, mpv and shared state in later tasks.
// S6 spike: bar widgets register as surfaces; the IPC target drives them.
// S5 spike: detached mpv over JSON IPC, reattached after a shell restart.
Item {
  id: root

  visible: false
  width: 0
  height: 0

  property var shell: null
  property var manifest: null
  property var pluginRegistry: null

  property var surfaces: []

  function registerSurface(surface) {
    if (surface && surfaces.indexOf(surface) < 0) surfaces = surfaces.concat([surface])
  }

  function unregisterSurface(surface) {
    surfaces = surfaces.filter(function(s) { return s !== surface })
  }

  function primarySurface() {
    return surfaces.length > 0 ? surfaces[0] : null
  }

  // ---- S5: mpv -------------------------------------------------------------
  readonly property string runtimeDir: Quickshell.env("XDG_RUNTIME_DIR") + "/omarchy-audible"
  readonly property string mpvSocket: runtimeDir + "/mpv.sock"
  property bool mpvWanted: true
  property int reconnects: 0
  property int nextRequest: 1
  property var mpv: ({ "time-pos": null, "pause": null, "chapter": null, "chapter-list": [], "path": null, "duration": null })
  property var lastReply: null

  readonly property bool mpvConnected: socketLoader.item ? socketLoader.item.connected : false

  function send(cmd) {
    if (!socketLoader.item || !socketLoader.item.connected) return false
    socketLoader.item.write(JSON.stringify({ command: cmd, request_id: nextRequest++ }) + "\n")
    socketLoader.item.flush()
    return true
  }

  function handleLine(line) {
    var msg
    try { msg = JSON.parse(line) } catch (e) { return }
    if (msg.event === "property-change") {
      var next = Object.assign({}, mpv)
      next[msg.name] = msg.data === undefined ? null : msg.data
      mpv = next
    } else if (msg.request_id !== undefined) {
      lastReply = msg
    }
  }

  function subscribe() {
    var props = ["time-pos", "pause", "chapter", "chapter-list", "path", "duration"]
    for (var i = 0; i < props.length; i++) send(["observe_property", i + 1, props[i]])
  }

  // mode: "scope" (systemd-run --user --scope) or "plain" (execDetached only)
  function startMpv(mode) {
    var mpvArgs = ["mpv", "--no-config", "--no-video", "--idle=yes", "--keep-open=yes",
      "--no-terminal", "--audio-display=no", "--force-window=no", "--volume=15",
      "--input-ipc-server=" + mpvSocket]
    var cmd = mode === "plain" ? mpvArgs
      : ["systemd-run", "--user", "--scope", "--quiet", "--collect",
         "--unit=omarchy-audible-mpv-" + Date.now()].concat(mpvArgs)
    Quickshell.execDetached(["mkdir", "-p", runtimeDir])
    Quickshell.execDetached(cmd)
  }

  Component {
    id: socketComponent
    Socket {
      path: root.mpvSocket
      connected: true
      parser: SplitParser {
        splitMarker: "\n"
        onRead: function(line) { root.handleLine(line) }
      }
      onConnectionStateChanged: if (connected) root.subscribe()
    }
  }

  Loader {
    id: socketLoader
    active: false
    sourceComponent: socketComponent
  }

  // A failed connect leaves a dead socket object; recreate it on each retry.
  Timer {
    interval: 1000
    repeat: true
    triggeredOnStart: true
    running: root.mpvWanted && !root.mpvConnected
    onTriggered: {
      root.reconnects++
      socketLoader.active = false
      socketLoader.active = true
    }
  }

  IpcHandler {
    target: "latentoperator.audible"

    function ping(): string { return "ok" }

    function toggle(): string {
      var s = root.primarySurface()
      if (!s) return "unavailable"
      s.toggle()
      return s.opened ? "opened" : "closed"
    }

    function isOpen(): string {
      var s = root.primarySurface()
      return s && s.opened ? "true" : "false"
    }

    function surfaceCount(): string { return String(root.surfaces.length) }

    function mpvStart(mode: string): string { root.startMpv(mode); return "started " + mode }
    function load(path: string, start: string): string {
      return root.send(["loadfile", path, "replace", 0, "start=" + start]) ? "ok" : "not-connected"
    }
    function pause(on: string): string { return root.send(["set_property", "pause", on === "yes"]) ? "ok" : "not-connected" }
    function seek(seconds: string, mode: string): string { return root.send(["seek", Number(seconds), mode]) ? "ok" : "not-connected" }
    function chapter(index: string): string { return root.send(["set_property", "chapter", Number(index)]) ? "ok" : "not-connected" }
    function quit(): string { return root.send(["quit"]) ? "ok" : "not-connected" }
    function status(): string {
      return JSON.stringify({
        connected: root.mpvConnected,
        reconnects: root.reconnects,
        timePos: root.mpv["time-pos"],
        pause: root.mpv["pause"],
        chapter: root.mpv["chapter"],
        chapters: (root.mpv["chapter-list"] || []).length,
        path: root.mpv["path"],
        duration: root.mpv["duration"],
        lastReply: root.lastReply
      })
    }
  }
}

import QtQuick
import Quickshell
import Quickshell.Io

// Headless singleton. Owns the backend, mpv and shared state in later tasks.
// S6 spike: bar widgets register as surfaces; the IPC target drives them.
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
  }
}

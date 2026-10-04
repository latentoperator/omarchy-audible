import QtQuick
import Quickshell

// Headless singleton. Owns the backend, mpv and shared state in later tasks.
Item {
  id: root

  visible: false
  width: 0
  height: 0

  property var shell: null
  property var manifest: null
  property var pluginRegistry: null
}

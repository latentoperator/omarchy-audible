import QtQuick
import Quickshell
import Quickshell.Io

import "lib/Store.js" as Store

// The only writer of `state.json` (ARCHITECTURE 4.8). Writes are atomic
// (FileView writes a temp file in the same directory and renames it).
Item {
  id: root

  visible: false
  width: 0
  height: 0

  property string path: ""
  property var reducerState: Store.createState("")
  property var doc: Store.createState("").doc
  property bool loaded: false
  property bool dirty: false
  property var pendingOps: []
  property string lastError: ""
  property var adoptWaiting: null

  // The reducer owns decisions and state transitions. This is its only writer;
  // effects are limited to file/process/timer operations and return as events.
  function apply(event) {
    var transition = Store.step(reducerState, event)
    reducerState = transition.state
    publish()
    transition.effects.forEach(function(effect) {
      if (effect.type === "backup") {
        backup.command = ["cp", "-f", effect.path, effect.destination]
        backup.running = true
      } else if (effect.type === "write") {
        file.setText(effect.text)
      } else if (effect.type === "save_now") {
        root.apply({ "type": "save" })
      } else if (effect.type === "retry_read") {
        readRetry.restart()
      } else if (effect.type === "retry_backup") {
        backupRetry.restart()
      } else if (effect.type === "wait_file") {
        file.waitForJob()
      }
    })
  }

  function publish() {
    // Listeners that mutate the store may react only to `loaded` (published last): write effects are serialized when their transition is computed.
    doc = root.reducerState.doc
    pendingOps = root.reducerState.pendingOps
    dirty = root.reducerState.dirty
    lastError = root.reducerState.lastError
    adoptWaiting = root.reducerState.adoptWaiting
    loaded = root.reducerState.loaded
  }

  // `text` is the file's content, or "" when it does not exist.
  function adopt(text) {
    apply({ "type": "adopt", "text": text, "path": root.path })
  }

  function record(asin, ms) {
    apply({ "type": "record", "asin": asin, "ms": ms, "at": new Date().toISOString() })
  }

  function setQueue(queue) {
    apply({ "type": "set_queue", "queue": queue })
  }

  // The player's volume and speed (F21). Before the file is read the change
  // is not kept; the next change after it is.
  function setPlayerSettings(volume, speed) {
    apply({ "type": "set_player_settings", "volume": volume, "speed": speed })
  }

  function setDefaultSpeedSetting(speed) {
    apply({ "type": "set_default_speed_setting", "speed": speed })
  }

  function markFinished(asin) {
    apply({ "type": "finished", "asin": asin })
    apply({ "type": "save" })
  }

  // Never writes before the file has been read, so a slow start cannot
  // replace saved positions with an empty state.
  function save() {
    apply({ "type": "save" })
  }

  // For shutdown: write and wait.
  function flush() {
    apply({ "type": "flush" })
  }

  onPathChanged: apply({ "type": "path_changed", "path": path })

  Process {
    id: backup
    onExited: function(code, status) { root.apply({ "type": "backup_result", "code": code }) }
  }

  // A read that failed for another reason (permissions, I/O) is tried again.
  Timer {
    id: readRetry
    interval: 30000
    repeat: false
    onTriggered: file.reload()
  }

  Timer {
    id: backupRetry
    interval: 30000
    repeat: false
    onTriggered: root.apply({ "type": "retry_backup" })
  }

  FileView {
    id: file
    path: root.path
    atomicWrites: true
    printErrors: false
    onLoaded: root.adopt(file.text())
    // Only a file that is really absent starts an empty state. Any other
    // failure (permissions, I/O) leaves the store unloaded, so nothing is
    // ever written over a file that could not be read.
    onLoadFailed: function(error) {
      root.apply({ "type": "load_failed", "notFound": error === FileViewError.FileNotFound, "path": root.path })
    }
    onSaved: root.apply({ "type": "saved" })
    onSaveFailed: function(error) { root.apply({ "type": "save_failed" }) }
  }
}

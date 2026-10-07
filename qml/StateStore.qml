import QtQuick
import Quickshell
import Quickshell.Io

import "lib/Library.js" as Library
import "lib/Playback.js" as Playback

// The only writer of `state.json` (ARCHITECTURE 4.8). Writes are atomic
// (FileView writes a temp file in the same directory and renames it).
Item {
  id: root

  visible: false
  width: 0
  height: 0

  property string path: ""
  property var doc: Library.parseState("")
  property bool loaded: false
  property bool dirty: false
  // Changes made before the file was read; replayed on top of what it holds.
  property var pendingOps: []
  property string lastError: ""
  property var adoptWaiting: null

  // `text` is the file's content, or "" when it does not exist.
  function adopt(text) {
    var parsed = Library.parseState(text)
    // A file that exists but cannot be understood is copied aside first, and
    // nothing is written until that copy has succeeded.
    if (text.length > 0 && parsed.recovered === true && root.path.length > 0) {
      root.adoptWaiting = parsed
      backup.command = ["cp", "-f", root.path, root.path + ".corrupt"]
      backup.running = true
      return
    }
    root.finishAdopt(parsed)
  }

  function finishAdopt(parsed) {
    root.doc = parsed
    // Replay first, so anyone reacting to `loaded` already sees the changes
    // that were made while the file was being read.
    var ops = root.pendingOps
    root.pendingOps = []
    for (var i = 0; i < ops.length; i++) root.apply(ops[i])
    root.loaded = true
    if (root.dirty) root.save()
  }

  function apply(op) {
    var next = op.kind === "finished"
      ? Playback.markFinished(root.doc, op.asin)
      : Playback.recordPosition(root.doc, op.asin, op.ms, op.at)
    if (next === root.doc) return
    root.doc = next
    root.dirty = true
  }

  function record(asin, ms) {
    var op = { "kind": "record", "asin": asin, "ms": ms, "at": new Date().toISOString() }
    if (!root.loaded) {
      root.pendingOps = root.pendingOps.concat([op])
      return
    }
    root.apply(op)
  }

  function setQueue(queue) {
    if (!root.loaded) return
    root.doc = Playback.withQueue(root.doc, queue)
    root.dirty = true
    root.save()
  }

  // The player's volume and speed (F21). Before the file is read the change
  // is not kept; the next change after it is.
  function setPlayerSettings(volume, speed) {
    if (!root.loaded) return
    var next = Playback.withPlayerSettings(root.doc, volume, speed)
    if (next === root.doc) return
    root.doc = next
    root.dirty = true
    root.save()
  }

  function markFinished(asin) {
    var op = { "kind": "finished", "asin": asin }
    if (!root.loaded) {
      root.pendingOps = root.pendingOps.concat([op])
      return
    }
    root.apply(op)
    root.save()
  }

  // Never writes before the file has been read, so a slow start cannot
  // replace saved positions with an empty state.
  function save() {
    if (!root.loaded || !root.dirty || root.path.length === 0) return
    root.dirty = false
    file.setText(Library.serializeState(root.doc))
  }

  // For shutdown: write and wait.
  function flush() {
    root.save()
    file.waitForJob()
  }

  Process {
    id: backup
    onExited: function(code, status) {
      var parsed = root.adoptWaiting
      if (code === 0 && parsed) {
        root.adoptWaiting = null
        root.finishAdopt(parsed)
        return
      }
      // Still nothing is written; try the copy again later (a full disk may
      // have been cleared). Positions keep queueing in the meantime.
      root.lastError = "could not back up the unreadable state.json"
      backupRetry.restart()
    }
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
    onTriggered: if (root.adoptWaiting) backup.running = true
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
      if (error === FileViewError.FileNotFound) {
        root.adopt("")
      } else {
        root.lastError = "could not read state.json"
        readRetry.restart()
      }
    }
    onSaved: root.lastError = ""
    onSaveFailed: function(error) {
      root.dirty = true
      root.lastError = "could not save state.json"
    }
  }
}

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

  // `text` is the file's content, or "" when it does not exist.
  function adopt(text) {
    var parsed = Library.parseState(text)
    // A file that exists but cannot be understood is kept aside before the
    // first write replaces it.
    if (text.length > 0 && parsed.recovered === true && root.path.length > 0) {
      Quickshell.execDetached(["cp", "-f", root.path, root.path + ".corrupt"])
    }
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
    var next = Playback.recordPosition(root.doc, op.asin, op.ms, op.at)
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
      if (error === FileViewError.FileNotFound) root.adopt("")
      else root.lastError = "could not read state.json"
    }
    onSaved: root.lastError = ""
    onSaveFailed: function(error) {
      root.dirty = true
      root.lastError = "could not save state.json"
    }
  }
}

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
  property string lastError: ""

  function adopt(text) {
    root.doc = Library.parseState(text)
    root.loaded = true
    if (root.dirty) root.save()
  }

  function record(asin, ms) {
    var next = Playback.recordPosition(root.doc, asin, ms, new Date().toISOString())
    if (next === root.doc) return
    root.doc = next
    root.dirty = true
  }

  function setQueue(queue) {
    root.doc = Playback.withQueue(root.doc, queue)
    root.dirty = true
    root.save()
  }

  function markFinished(asin) {
    var next = Playback.markFinished(root.doc, asin)
    if (next === root.doc) return
    root.doc = next
    root.dirty = true
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

  FileView {
    id: file
    path: root.path
    atomicWrites: true
    printErrors: false
    onLoaded: root.adopt(file.text())
    onLoadFailed: function(error) { root.adopt("") }
    onSaved: root.lastError = ""
    onSaveFailed: function(error) {
      root.dirty = true
      root.lastError = "could not save state.json"
    }
  }
}

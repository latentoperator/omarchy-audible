import QtQuick
import Quickshell.Io

import "lib/Ndjson.js" as Ndjson

// One backend process. Feeds stdout chunks through the NDJSON splitter and
// reports each record, then the outcome once the process has exited.
Item {
  id: root

  visible: false
  width: 0
  height: 0

  property var command: []
  property var environment: ({})
  property var job: null

  property var splitter: Ndjson.createSplitter()
  property int exitCode: -1
  property string stderrText: ""

  signal record(var record)
  signal finished(var outcome)

  function start() {
    process.running = true
  }

  function kill() {
    process.running = false
  }

  function emitRecords(records) {
    for (var index = 0; index < records.length; index++) {
      root.record(records[index])
    }
  }

  // The exit signal can arrive before the last stdout chunk is delivered, so
  // the outcome waits a beat for the stream to drain.
  function settle() {
    emitRecords(Ndjson.flush(splitter))
    var outcome = Ndjson.finish(root.exitCode, splitter.events)
    outcome.stderr = root.stderrText
    root.finished(outcome)
  }

  Process {
    id: process
    command: root.command
    environment: root.environment

    stdout: SplitParser {
      splitMarker: ""
      onRead: function(chunk) {
        root.emitRecords(Ndjson.feed(root.splitter, chunk))
      }
    }

    stderr: SplitParser {
      onRead: function(line) {
        // Scrubbed by the backend; kept short for the debug panel only.
        root.stderrText = (root.stderrText + line + "\n").slice(-400)
      }
    }

    onExited: function(code, status) {
      root.exitCode = code
      drain.restart()
    }
  }

  Timer {
    id: drain
    interval: 60
    repeat: false
    onTriggered: root.settle()
  }
}

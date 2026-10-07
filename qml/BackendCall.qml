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
  // Text for the process's stdin (the pasted sign-in address). Written once
  // the process starts, then cleared and stdin closed so the backend sees
  // end of input. Never logged.
  property string input: ""
  property bool hasInput: false

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
      // play-info's key has now reached the service, which hands it straight
      // to mpv. Don't keep it in `splitter.events` until this call is
      // destroyed (B11); the outcome only needs the terminal event.
      if (records[index].type === "play_info") records[index].lavf_options = ""
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
    stdinEnabled: root.hasInput

    onStarted: {
      if (!root.hasInput) return
      write(root.input)
      root.input = ""
      stdinEnabled = false
    }

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

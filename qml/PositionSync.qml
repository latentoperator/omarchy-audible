import QtQuick

import "lib/Positions.js" as Positions
import "lib/Sync.js" as Sync

// Position write-back (ARCHITECTURE 4.6). Local listening positions are queued
// in `state.json`; a flush re-reads the remote positions, drops any push the
// account has overtaken, and sends the rest one at a time.
Item {
  id: root

  visible: false
  width: 0
  height: 0

  // The StateStore, and the Service (its `run` returns false when it refuses).
  property var store: null
  property var service: null
  property int retryIntervalMs: 60000

  // Last pushed position per ASIN, in memory (state.json has no field for it).
  property var lastPushed: ({})
  property bool flushing: false
  property string lastResult: ""

  property var requested: []
  property var plan: []
  property var current: null
  property bool progressed: false

  readonly property var queue: store && store.doc && store.doc.push_queue ? store.doc.push_queue : []

  // A position was just recorded for `asin` by listening on this machine.
  function notePlayed(asin) {
    if (!store || !asin || asin.length === 0) return
    var book = store.doc.books ? store.doc.books[asin] : null
    if (!book) return
    var candidate = {
      "played_since_download": book.played_since_download,
      "ms": book.ms,
      "last_pushed_ms": lastPushed[asin] === undefined ? null : lastPushed[asin]
    }
    if (!Positions.shouldPush(candidate)) return
    var next = Positions.enqueue(queue.slice(), { "asin": asin, "ms": book.ms, "at": book.last_played_at })
    store.setQueue(next)
    flush()
  }

  function flush() {
    if (flushing || queue.length === 0 || !service) return
    requested = Sync.asinsOf(queue, Sync.BATCH_SIZE)
    progressed = false
    flushing = true
    if (!service.run("position-get", requested, "flush")) finish("refused")
  }

  function finish(result) {
    flushing = false
    lastResult = result
    plan = []
    current = null
    // More entries may have arrived or been beyond one batch; go again only if
    // this round moved something, so an offline queue does not spin.
    if (progressed && queue.length > 0) Qt.callLater(flush)
  }

  function handleEvent(record, job) {
    if (job.purpose !== "flush" || record.type !== "positions") return
    var split = Positions.flushPlan(queue, record.items)
    var next = queue
    for (var i = 0; i < split.drop.length; i++) {
      next = Sync.removeEntry(next, split.drop[i])
      progressed = true
    }
    if (split.drop.length > 0) store.setQueue(next)
    plan = Sync.sendable(split.send, requested)
  }

  function handleFinished(job, outcome) {
    if (job.purpose === "flush") {
      if (!outcome.ok) return finish("offline")
      sendNext()
    } else if (job.purpose === "push") {
      var entry = current
      current = null
      if (outcome.ok || outcome.code === "stale") {
        // Sent, or the account moved past it: either way it leaves the queue.
        store.setQueue(Sync.removeEntry(queue, entry))
        if (outcome.ok) lastPushed[entry.asin] = entry.ms
        progressed = true
        sendNext()
      } else {
        finish(String(outcome.code))
      }
    }
  }

  function sendNext() {
    if (plan.length === 0) return finish("done")
    current = plan[0]
    plan = plan.slice(1)
    if (!service.run("position-push", Sync.pushArgs(current), "push")) finish("refused")
  }

  // Entries saved by an earlier run are flushed once state.json is read.
  Connections {
    target: root.store
    function onLoadedChanged() { if (root.store.loaded) root.flush() }
  }

  Timer {
    interval: root.retryIntervalMs
    repeat: true
    running: root.queue.length > 0 && !root.flushing
    onTriggered: root.flush()
  }
}

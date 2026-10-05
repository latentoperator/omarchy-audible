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

  property var deferred: []
  property var requested: []
  property var plan: []
  property var current: null
  property bool progressed: false

  readonly property var queue: store && store.doc && store.doc.push_queue ? store.doc.push_queue : []

  // A position was just recorded for `asin` by listening on this machine.
  function notePlayed(asin) {
    if (queuePush(asin)) flush()
  }

  // Queue the push without flushing (shutdown has no time to send it; the
  // saved queue is flushed by the next run). True when something was queued.
  function queuePush(asin) {
    if (!store || !asin || asin.length === 0) return false
    if (!store.loaded) {
      // The position is still waiting in the store's pending changes; queue
      // the push once they have been replayed.
      if (deferred.indexOf(asin) === -1) deferred = deferred.concat([asin])
      return false
    }
    var book = store.doc.books ? store.doc.books[asin] : null
    if (!book) return false
    var candidate = {
      "played_since_download": book.played_since_download,
      "ms": book.ms,
      "last_pushed_ms": lastPushed[asin] === undefined ? null : lastPushed[asin]
    }
    // A queued entry that no longer matches the book's latest listening
    // (position or time) must be replaced even when the position equals the
    // last one pushed, or the older entry would be judged and sent instead.
    var queued = queue.filter(function(e) { return e.asin === asin })
    var outdated = queued.length > 0 && (queued[0].ms !== book.ms || queued[0].at !== book.last_played_at)
    if (!Positions.shouldPush(candidate) && !outdated) return false
    var next = Positions.enqueue(queue.slice(), { "asin": asin, "ms": book.ms, "at": book.last_played_at })
    store.setQueue(next)
    return true
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

  // Sends the next planned entry that is still exactly what is queued. A
  // newer listening may have replaced it while an earlier push was running;
  // that one is left for the next flush instead of sending the old position.
  function sendNext() {
    while (plan.length > 0) {
      var candidate = plan[0]
      plan = plan.slice(1)
      var stillQueued = queue.some(function(e) {
        return e.asin === candidate.asin && e.ms === candidate.ms && e.at === candidate.at
      })
      if (!stillQueued) {
        progressed = true
        continue
      }
      current = candidate
      if (!service.run("position-push", Sync.pushArgs(current), "push")) finish("refused")
      return
    }
    finish("done")
  }

  // Entries saved by an earlier run are flushed once state.json is read.
  Connections {
    target: root.store
    function onLoadedChanged() {
      if (!root.store.loaded) return
      var asins = root.deferred
      root.deferred = []
      for (var i = 0; i < asins.length; i++) root.queuePush(asins[i])
      root.flush()
    }
  }

  Timer {
    interval: root.retryIntervalMs
    repeat: true
    running: root.queue.length > 0 && !root.flushing
    onTriggered: root.flush()
  }
}

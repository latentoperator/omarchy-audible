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
  // The reducer state has one writer: apply() assigns each Sync.step result.
  property var reducerState: Sync.createState()
  readonly property int failedFlushes: reducerState.failedFlushes
  readonly property int retryIntervalMs: Sync.retryDelayMs(failedFlushes)
  readonly property var lastPushed: reducerState.lastPushed
  readonly property bool flushing: reducerState.flushing
  readonly property string lastResult: reducerState.lastResult
  readonly property int consecutiveStale: reducerState.staleCount
  readonly property string staleNotice: Sync.staleNotice(consecutiveStale)

  // Positions recorded before state.json loads wait here until the store has
  // replayed them. Queue edits themselves remain the StateStore's contract.
  property var deferred: []

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

  function apply(event) {
    var transition = Sync.step(reducerState, event)
    reducerState = transition.state
    transition.effects.forEach(function(effect) {
      if (effect.type === "run") {
        if (!service.run(effect.command, effect.args, effect.purpose)) {
          apply({ "type": "refused", "purpose": effect.purpose, "queue": queue })
        }
      } else if (effect.type === "setQueue") {
        store.setQueue(effect.queue)
      } else if (effect.type === "flush_later") {
        Qt.callLater(flush)
      } else if (effect.type === "finish") {
        // lastResult and retry scheduling are derived from the assigned state.
      }
    })
  }

  function flush() {
    apply({ "type": "flush", "queue": queue })
  }

  // Play and panel open retry sooner: the user is here, and maybe online.
  function resetRetry() {
    apply({ "type": "reset_retry" })
  }

  function handleEvent(record, job) {
    if (!job || job.purpose !== "flush" || !record || record.type !== "positions") return
    apply({ "type": "positions", "purpose": job.purpose, "queue": queue, "items": record.items })
  }

  function handleFinished(job, outcome) {
    if (!job || (job.purpose !== "flush" && job.purpose !== "push")) return
    apply({ "type": "finished", "job": job, "outcome": outcome, "queue": queue })
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

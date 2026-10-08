import QtQuick

import "lib/Catchup.js" as Catchup
import "lib/Format.js" as Format
import "lib/Positions.js" as Positions

// ⏯ catching up with other devices (SCOPE FR-P4, G3 finding 5, P9): the
// account reads, the ⏯ waiting on one, and the note after a jump. The
// decisions are `Catchup.js`; when a read finishes, `Catchup.finishRead`
// decides what is kept and whether the waiting ⏯ resumes.
Item {
  id: root

  visible: false
  width: 0
  height: 0

  // The Service (its `run`, `logEvent`, `loadedAsin` and `pendingResume`),
  // the PlayerController, the StateStore and the PositionSync.
  property var service: null
  property var player: null
  property var store: null
  property var sync: null

  // `pausedAtMs` is when the player last paused (0 = unknown, e.g. after a
  // shell restart); `catchupAsin` is the book waiting on an account read
  // before it resumes; `catchupReads` the books with a read queued or running
  // (at most one per book, so overlapping reads never share a result);
  // `prefetched` the last finished read, `{asin, atMs, remote}`.
  property real pausedAtMs: 0
  property string catchupAsin: ""
  property var catchupReads: ({})
  property var prefetched: null
  // Results of catch-up reads still running, by ASIN (like the Service's
  // `resumeRemotes`), so overlapping reads of different books never touch
  // each other's result.
  property var catchupResults: ({})
  // The Mini line after a catch-up jump (Catchup.jumpNote), cleared after
  // NOTE_MS or by a new pick.
  property string catchupNote: ""

  // Service.playPause. Pausing is immediate. Resuming after a long pause
  // first reads the account, so a book listened to on the phone continues
  // from there; a second ⏯ while that read runs cancels the resume.
  function press() {
    var asin = service.loadedAsin
    var action = Catchup.pressAction({ "loaded": player.loaded, "playing": player.playing,
      "waiting": catchupAsin.length > 0, "pendingResume": service.pendingResume.length > 0,
      "needsRead": Catchup.needsRead(pausedAtMs, Date.now()),
      "prefetchUsable": Catchup.prefetchUsable(prefetched, asin, Date.now()),
      "reading": catchupReads[asin] === true })
    if (action === Catchup.PRESS_NONE) return "error: nothing loaded"
    if (action === Catchup.PRESS_PAUSE) {
      cancelCatchup()
      player.pause()
      return "ok"
    }
    if (action === Catchup.PRESS_CANCEL) {
      cancelCatchup()
      return "cancelled"
    }
    if (action === Catchup.PRESS_BUSY) return "busy"
    if (action === Catchup.PRESS_RESUME) {
      player.resume()
      return "ok"
    }
    if (action === Catchup.PRESS_PREFETCH) {
      resumeCaughtUp(asin, prefetched.remote)
      return "ok"
    }
    catchupAsin = asin
    catchupTimer.restart()
    if (action === Catchup.PRESS_READ && !readCatchup(asin)) resumeCaughtUp(asin, null)
    return "checking"
  }

  // The player paused, stopped or crashed.
  function notePaused() {
    pausedAtMs = Date.now()
  }

  // A new pick wins over a waiting ⏯ and drops the note.
  function noteIntent() {
    cancelCatchup()
    catchupNote = ""
  }

  // Drops a waiting ⏯; the read itself finishes and is kept as `prefetched`.
  function cancelCatchup() {
    catchupAsin = ""
    catchupTimer.stop()
  }

  // Opening the drawer on a book paused long enough starts the read early,
  // so ⏯ usually finds it done.
  function prefetchCatchup() {
    if (!player.loaded || player.playing || catchupReads[service.loadedAsin] === true) return
    var asin = service.loadedAsin
    if (!Catchup.needsRead(pausedAtMs, Date.now()) || Catchup.prefetchUsable(prefetched, asin, Date.now())) return
    readCatchup(asin)
  }

  function readCatchup(asin) {
    if (!service.run("position-get", [asin], "catchup")) return false
    var reads = catchupReads
    reads[asin] = true
    catchupReads = reads
    return true
  }

  // Resume `asin`, first jumping to `remote` (an account entry, or null)
  // when it is newer than the position saved here.
  function resumeCaughtUp(asin, remote) {
    cancelCatchup()
    prefetched = null
    // An unread state.json is not "nothing saved here": resume in place.
    var action = Catchup.resumeAction({ "loaded": player.loaded, "sameBook": service.loadedAsin === asin,
      "playing": player.playing, "storeLoaded": store.loaded, "hasRemote": !!remote })
    if (action === "none") return
    if (action === "compare") {
      var local = store.doc.books ? store.doc.books[asin] : null
      var own = [sync.lastPushed[asin], local ? local.ms : null]
      var target = Catchup.jumpTarget(player.positionMs,
        local ? Positions.parseUpdatedAt(local.updated_at) : null,
        remote.ms, Positions.parseUpdatedAt(remote.updated_at), own)
      if (target >= 0) {
        service.logEvent("catchup", "jump " + Math.round(player.positionMs) + " -> " + target)
        showCatchupNote(Format.clock(player.positionMs))
        player.jumpToMs(target)
      }
    }
    player.resume()
  }

  function showCatchupNote(was) {
    catchupNote = Catchup.jumpNote(was)
    catchupNoteTimer.restart()
  }

  // A record from the job runner: keep a catch-up read's result for its book.
  function handleEvent(record, job) {
    if (record.type !== "positions" || job.purpose !== "catchup") return
    var read = job.args[0]
    var results = catchupResults
    results[read] = { "asin": read, "atMs": Date.now(), "remote": record.items[read] || null }
    catchupResults = results
  }

  // A job finished: for a catch-up read, apply `Catchup.finishRead`.
  function handleFinished(job, outcome) {
    if (job.purpose !== "catchup") return
    var readAsin = job.args[0]
    var next = Catchup.finishRead({ "reads": catchupReads, "results": catchupResults,
      "prefetched": prefetched, "waitingAsin": catchupAsin }, readAsin, outcome.ok)
    catchupReads = next.reads
    catchupResults = next.results
    prefetched = next.prefetched
    if (next.resume) resumeCaughtUp(readAsin, next.remote)
  }

  Timer {
    id: catchupNoteTimer
    interval: Catchup.NOTE_MS
    repeat: false
    onTriggered: root.catchupNote = ""
  }

  Timer {
    id: catchupTimer
    interval: Catchup.READ_TIMEOUT_MS
    repeat: false
    onTriggered: root.resumeCaughtUp(root.catchupAsin, null)
  }
}

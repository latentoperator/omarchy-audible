import QtQuick

import "lib/Drawer.js" as Drawer
import "lib/Positions.js" as Positions
import "lib/Unload.js" as Unload

// Removing books (FR-S2, F17, P9): the books waiting for the player to unload
// them, and auto-removing a finished book (SCOPE 4.6 `autoRemoveFinished`).
// The pending list's transitions are `Unload.step`; this applies its effects.
Item {
  id: root

  visible: false
  width: 0
  height: 0

  // The Service (its `run`, `logEvent`, `atEnd`, `busyAsins`, `removeBook`,
  // `loadedAsin` and the `autoRemoveFinished` setting), the PlayerController
  // and the LibraryModel.
  property var service: null
  property var player: null
  property var library: null

  // Books to remove once the player has unloaded them: [{asin, purpose}].
  property var pending: []
  readonly property var waiting: Unload.asins(pending)
  // A finished book auto-remove checks again in a moment.
  property string candidate: ""

  function apply(result) {
    pending = result.pending
    result.effects.forEach(function(effect) {
      if (effect.type === "run") service.run("remove", [effect.asin], effect.purpose)
      else if (effect.type === "log") service.logEvent("remove", effect.text)
      else if (effect.type === "timer" && effect.on) unloadTimer.restart()
      else if (effect.type === "timer") unloadTimer.stop()
    })
  }

  // The loaded book: unload it (the player saves its position), and remove
  // it once it is gone.
  function unloadThenRemove(asin, purpose) {
    apply(Unload.step(pending, { "type": "add", "asin": asin, "purpose": purpose }))
    player.quit()
    return "unloading"
  }

  // A new choice of this book wins over its pending removal.
  function dropIntent(asin) {
    apply(Unload.step(pending, { "type": "intent", "asin": asin }))
  }

  // The loaded book changed: remove every waiting book that isn't busy.
  function flush() {
    apply(Unload.step(pending, { "type": "unloaded", "busy": service.busyAsins(), "autoRemove": service.autoRemoveFinished }))
  }

  // The player never let go of a book it was asked to unload: give up.
  function abandon() {
    apply(Unload.step(pending, { "type": "timeout" }))
  }

  function removeAll() {
    var asins = Drawer.removableAsins(library.allRows)
    asins.forEach(function(asin) { service.removeBook(asin) })
    return String(asins.length)
  }

  // The loaded book reached its end (Service.checkFinished). Auto-remove waits
  // a moment and checks again, so a transient pause while mpv reloads cannot
  // trigger it.
  function noteFinished(asin) {
    if (!service.autoRemoveFinished) return
    candidate = asin
    autoRemoveTimer.restart()
  }

  // Checked by the job runner just before a queued job starts.
  function jobAllowed(job) {
    if (!job || job.command !== "remove" || !Array.isArray(job.args)) return true
    return Unload.jobAllowed(job, service.autoRemoveFinished, service.atEnd(String(job.args[0])), player.playing, service.busyAsins())
  }

  function removeIfStillFinished() {
    var asin = candidate
    candidate = ""
    if (asin.length === 0) return
    if (!Positions.autoRemoveAllowed(service.autoRemoveFinished, service.atEnd(asin), player.playing)) return
    // The loaded book goes the way the user's Remove does: unload first, then
    // remove once mpv has let go of the file (F17), still as an auto-remove.
    if (asin === service.loadedAsin) service.removeBook(asin, Unload.PURPOSE_AUTO)
    else service.run("remove", [asin], Unload.PURPOSE_AUTO)
  }

  Timer {
    id: unloadTimer
    interval: 10000
    repeat: false
    onTriggered: root.abandon()
  }

  Timer {
    id: autoRemoveTimer
    interval: 2000
    repeat: false
    onTriggered: root.removeIfStillFinished()
  }
}

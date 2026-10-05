import QtQuick

import "lib/JobQueue.js" as JobQueue

// Spawns backend commands (ARCHITECTURE 4.8). Job commands go through the
// queue one at a time; every other command bypasses it and runs at once.
Item {
  id: root

  visible: false
  width: 0
  height: 0

  // Absolute path of bin/omarchy-audible.
  property string launcher: ""
  // Extra environment for every backend process (the dev fake flag).
  property var environment: ({})
  property int busyDelayMs: 1500

  property var queue: JobQueue.create({ "busyDelayMs": root.busyDelayMs })
  property var activeJob: null
  property int bypassCount: 0
  property int queued: 0
  readonly property bool running: activeJob !== null || bypassCount > 0

  // Latest `progress` event of the running job, and the last failure.
  property var progress: null
  property var lastError: null

  signal event(var record, var job)
  signal jobFinished(var job, var outcome)

  function run(command, args) {
    var job = { "command": String(command), "args": args || [] }
    if (JobQueue.isJobCommand(job.command)) {
      JobQueue.enqueue(root.queue, job)
      root.sync()
      root.pump()
    } else {
      root.spawn(job, false)
    }
  }

  function cancel(asin) {
    var result = JobQueue.cancel(root.queue, asin)
    if (result.action === JobQueue.CANCEL_SEND) {
      root.run("cancel", [asin])
    }
    root.sync()
    return result.action
  }

  function sync() {
    root.queued = JobQueue.size(root.queue) - (root.queue.active ? 1 : 0)
    root.activeJob = root.queue.active
  }

  function pump() {
    // A busy job waits out its retry delay; a newer job must not jump it.
    if (root.retrying) {
      return
    }
    var job = JobQueue.take(root.queue)
    if (!job) {
      return
    }
    root.progress = null
    root.sync()
    root.spawn(job, true)
  }

  function spawn(job, isJob) {
    var argv = [root.launcher, job.command].concat(job.args)
    var call = callComponent.createObject(root, {
      "command": argv,
      "environment": root.environment,
      "job": job
    })
    if (!isJob) {
      root.bypassCount += 1
    }
    call.record.connect(function(record) {
      if (isJob && record.type === "progress") {
        root.progress = record
      }
      root.event(record, job)
    })
    call.finished.connect(function(outcome) {
      call.destroy()
      if (isJob) {
        root.jobDone(job, outcome)
      } else {
        root.bypassCount -= 1
        root.noteFailure(job, outcome)
        root.jobFinished(job, outcome)
      }
    })
    call.start()
  }

  function jobDone(job, outcome) {
    var step = JobQueue.complete(root.queue, outcome)
    root.sync()
    if (step.action === JobQueue.ACTION_RETRY) {
      root.retrying = true
      retryTimer.interval = step.delayMs
      retryTimer.restart()
      return
    }
    root.noteFailure(job, outcome)
    root.progress = null
    root.jobFinished(job, outcome)
    root.pump()
  }

  function noteFailure(job, outcome) {
    if (!outcome.ok) {
      root.lastError = {
        "command": job.command,
        "code": outcome.code,
        "message": outcome.message,
        "hint": outcome.hint
      }
    }
  }

  Component {
    id: callComponent
    BackendCall {}
  }

  Timer {
    id: retryTimer
    repeat: false
    onTriggered: {
      root.retrying = false
      root.pump()
    }
  }
}

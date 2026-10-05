import QtQuick

import "lib/JobQueue.js" as JobQueue
import "lib/Signin.js" as Signin

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
  // Optional `function(job)`: return false to skip a queued job just before it
  // would start (it then reports `code: "skipped"`).
  property var gate: null

  property var queue: JobQueue.create({ "busyDelayMs": root.busyDelayMs })
  property var activeJob: null
  property var pendingJobs: []
  property bool retrying: false
  property int bypassCount: 0
  property int queued: 0
  readonly property bool running: activeJob !== null || bypassCount > 0

  // Stdin text for queued jobs, by `job.inputId`, kept out of the job
  // objects (which are listed in `pendingJobs`). Dropped when the job ends.
  property var inputs: ({})
  property int nextInputId: 1

  // Latest `progress` event of the running job, and the last failure.
  property var progress: null
  property var lastError: null

  signal event(var record, var job)
  signal jobFinished(var job, var outcome)

  // `purpose` is a free tag the caller uses to recognise its own jobs in the
  // `event` and `jobFinished` signals.
  function run(command, args, purpose) {
    var job = { "command": String(command), "args": args || [], "purpose": purpose || "" }
    if (JobQueue.isJobCommand(job.command)) {
      var queued = JobQueue.enqueue(root.queue, job)
      if (queued) queued.purpose = job.purpose
      root.sync()
      root.pump()
    } else {
      root.spawn(job, false)
    }
  }

  // A job command whose input goes to the process's stdin, never argv.
  function runWithInput(command, args, purpose, input) {
    var job = { "command": String(command), "args": args || [], "purpose": purpose || "" }
    var queued = JobQueue.enqueue(root.queue, job)
    if (!queued) return false
    queued.purpose = job.purpose
    queued.inputId = root.nextInputId++
    root.inputs[queued.inputId] = String(input)
    root.sync()
    root.pump()
    return true
  }

  function dropInput(job) {
    if (job && job.inputId) delete root.inputs[job.inputId]
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
    root.pendingJobs = root.queue.pending.slice()
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
    // A job whose stdin input was already handed to a process (a busy retry
    // of login-finish) has nothing to send: fail it instead.
    if (Signin.inputLost(job, root.inputs)) {
      var lost = { "ok": false, "busy": false, "code": "busy", "message": "Audible was busy. Try again.", "hint": null }
      JobQueue.complete(root.queue, lost)
      root.sync()
      root.jobFinished(job, lost)
      root.pump()
      return
    }
    if (root.gate && !root.gate(job)) {
      var outcome = { "ok": false, "busy": false, "code": "skipped", "message": "skipped", "hint": null }
      JobQueue.complete(root.queue, outcome)
      root.dropInput(job)
      root.sync()
      root.jobFinished(job, outcome)
      root.pump()
      return
    }
    root.progress = null
    root.sync()
    root.spawn(job, true)
  }

  function spawn(job, isJob) {
    var argv = [root.launcher, job.command].concat(job.args)
    var hasInput = !!(job.inputId && root.inputs[job.inputId] !== undefined)
    var call = callComponent.createObject(root, {
      "command": argv,
      "environment": root.environment,
      "job": job,
      "hasInput": hasInput,
      "input": hasInput ? root.inputs[job.inputId] : ""
    })
    // The process has its own copy now; drop this one at once.
    root.dropInput(job)
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
    root.dropInput(job)
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

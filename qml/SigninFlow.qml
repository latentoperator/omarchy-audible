import QtQuick
import Quickshell.Io

import "lib/Onboarding.js" as Onboarding
import "lib/Panel.js" as Panel
import "lib/Signin.js" as Signin

// Onboarding and sign-in (U3, P9): setup, the Connect step, Reconnect after
// `auth_failed`, Disconnect, and the clipboard I/O of the onboarding view.
// The decisions are `Onboarding.js` and `Signin.js`. The pasted text goes
// straight to the backend's stdin and never lands in a property here.
Item {
  id: root

  visible: false
  width: 0
  height: 0

  // The Service (its `status`, `fake`, `run`, `logEvent`, `startSync` and
  // `showView`) and the JobRunner.
  property var service: null
  property var runner: null

  // `reconnecting` reopens Connect after `auth_failed`; `authFailed` drives
  // the Library's reconnect banner. `loginSession` is the open sign-in
  // session id (not a secret). `onboardingError` is `Onboarding.errorText`
  // output.
  property bool reconnecting: false
  property bool authFailed: false
  property string loginSession: ""
  property string marketplace: Signin.DEFAULT_MARKETPLACE
  property var onboardingError: null
  property string clipboardNotice: ""
  property bool pasteRejected: false
  property bool pasteEmpty: false
  readonly property string onboardingStep: Signin.effectiveStep(Onboarding.step(service ? service.status : null), reconnecting)
  readonly property string loginPhase: Signin.phase(loginSession, loginStarting,
    Signin.jobPending("login-finish", runner ? runner.pendingJobs : null, runner ? runner.activeJob : null))
  property bool loginStarting: false
  readonly property bool settingUp: Signin.jobPending("setup", runner ? runner.pendingJobs : null, runner ? runner.activeJob : null)

  function checkStatus() {
    service.run("status", [])
  }

  function startSetup() {
    onboardingError = null
    return service.run("setup", [], "setup") ? "ok" : "error: refused"
  }

  function startLogin(code) {
    onboardingError = null
    pasteRejected = false
    loginSession = ""
    marketplace = code
    loginStarting = true
    if (!service.run("login-start", ["--marketplace", code], "login")) {
      loginStarting = false
      return "error: refused"
    }
    return "ok"
  }

  // The pasted text goes straight to the backend's stdin (never argv, a log,
  // an event or a property) and is dropped by the caller right after.
  function finishLogin(pasted) {
    if (loginSession.length === 0) return "error: no session"
    pasteEmpty = !/\S/.test(pasted || "")
    if (pasteEmpty || !Onboarding.looksLikeRedirect(pasted)) {
      pasteRejected = true
      return "rejected"
    }
    pasteRejected = false
    onboardingError = null
    var sent = runner.runWithInput("login-finish", ["--session", loginSession], "login", pasted)
    clearPaste()
    return sent ? "ok" : "error: refused"
  }

  function cancelLogin() {
    clearPaste()
    loginSession = ""
    pasteRejected = false
    onboardingError = null
  }

  function importCliLogin() {
    onboardingError = null
    return service.run("login-import-cli", [], "login") ? "ok" : "error: refused"
  }

  function disconnect() {
    return service.run("logout", [], "logout") ? "ok" : "error: refused"
  }

  function reconnect() {
    reconnecting = true
    cancelLogin()
    service.showView(Panel.VIEW_ONBOARDING)
  }

  // Fake mode only (the `fakeOnboarding authfail` IPC): as if a job had
  // failed with `auth_failed`.
  function noteAuthFailed() {
    authFailed = true
  }

  function openUrl(url) {
    opener.command = ["xdg-open", url]
    opener.running = true
  }

  // Clipboard I/O for the onboarding view: copy the install command, and read
  // the clipboard for "Paste from clipboard" (the text goes back to the view
  // through `clipboardRead` in chunks, never into a property). The view
  // clears its field before calling `readClipboard` and appends each chunk.
  // `target` is the view that asked, so another monitor's field never fills.
  signal clipboardRead(var target, string text)
  // Every view clears its paste field: the text was sent, or sign-in ended.
  signal clearPaste()
  property var clipboardTarget: null

  function copyText(text) {
    copier.text = String(text)
    copier.running = true
  }

  function readClipboard(target) {
    clipboardTarget = target
    paster.running = true
  }

  // A record from the job runner: the sign-in link, and login-finish's
  // clipboard notice.
  function handleEvent(record, job) {
    if (job.command === "login-start" && record.type === "login_url") {
      loginStarting = false
      loginSession = String(record.session || "")
      // Fake mode's link is a dummy Amazon address: don't open a browser.
      if (service.fake) service.logEvent("login-start", "fake: browser not opened")
      else openUrl(String(record.url || ""))
    } else if (job.command === "login-finish" && record.type === "done") {
      clipboardNotice = Onboarding.clipboardNotice(record)
    }
  }

  // A job finished: any job can report `auth_failed`; an onboarding job
  // updates the Connect step.
  function handleFinished(job, outcome) {
    if (Signin.authFailed(outcome)) authFailed = true
    if (Signin.isOnboardingCommand(job.command)) onboardingFinished(job, outcome)
  }

  function onboardingFinished(job, outcome) {
    if (job.command === "login-start") {
      loginStarting = false
      if (!outcome.ok) onboardingError = Onboarding.errorText(outcome.code, outcome.message, outcome.hint)
      return
    }
    if (!outcome.ok && outcome.code !== "skipped") {
      onboardingError = Onboarding.errorText(outcome.code, outcome.message, outcome.hint)
      // An expired or used session can't be retried; start over.
      if (job.command === "login-finish") loginSession = ""
    }
    if (outcome.ok && Signin.isSignIn(job.command)) {
      loginSession = ""
      reconnecting = false
      authFailed = false
      onboardingError = null
      service.startSync("signin")
    }
    if (outcome.ok && job.command === "logout") {
      clipboardNotice = ""
      reconnecting = false
      authFailed = false
    }
    if (Signin.refreshesStatus(job.command)) checkStatus()
  }

  Process {
    id: opener
  }

  Process {
    id: copier
    property string text: ""
    stdinEnabled: true
    onStarted: {
      write(text)
      text = ""
      stdinEnabled = false
    }
    onExited: stdinEnabled = true
    command: ["wl-copy"]
  }

  Process {
    id: paster
    command: ["wl-paste", "--no-newline"]
    // Chunks go straight to the view's field; nothing here keeps them.
    stdout: SplitParser {
      splitMarker: ""
      onRead: function(chunk) { root.clipboardRead(root.clipboardTarget, chunk) }
    }
  }
}

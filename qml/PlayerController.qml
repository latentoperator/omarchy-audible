import QtQuick
import Quickshell
import Quickshell.Io

import "lib/Mpv.js" as Mpv

// mpv under the shell (ARCHITECTURE 5.1, 5.2; S5 pitfalls). mpv is launched in
// its own systemd scope so it survives a shell restart, and this object
// reattaches to it over the JSON IPC socket.
Item {
  id: root

  visible: false
  width: 0
  height: 0

  // $XDG_RUNTIME_DIR/omarchy-audible[-fake]/mpv.sock, from the `status` event.
  property string socketPath: ""
  property int initialVolume: 100

  // A book is supposed to be loaded. Reconnects happen only while this (or a
  // bounded startup attach) holds, so an absent mpv costs nothing.
  property bool wanted: false
  property bool attaching: false
  property bool quitting: false
  // quit() was called while mpv was still starting: quit it once it connects.
  property bool quitPending: false
  // The old mpv is gone but its scope may not be: wait before relaunching.
  property bool relaunchPending: false
  property int scopeChecks: 0
  property bool launching: false
  property int attempt: 0
  property bool useScope: true

  // idle | launching | connecting | connected | lost | failed
  property string connection: "idle"
  property string lastError: ""

  property var mpvState: Mpv.emptyState()
  property var pendingLoad: null
  property int nextRequest: 1

  readonly property bool connected: socketLoader.item ? socketLoader.item.connected : false
  readonly property var derived: Mpv.derive(mpvState)
  readonly property bool loaded: derived.loaded
  readonly property bool playing: derived.playing
  readonly property int positionMs: derived.positionMs
  readonly property int durationMs: derived.durationMs
  readonly property var chapters: derived.chapters
  readonly property int chapterIndex: derived.chapterIndex
  readonly property real speed: derived.speed
  readonly property real volume: derived.volume
  readonly property string path: derived.path

  // Sleep timer: null, or {mode: "minutes"|"chapter", endsAtMs}.
  property var sleepTimer: null
  property real fadeBaseVolume: -1

  // Subscribe on the derived `connected`, not in Socket.onConnectionStateChanged:
  // the socket can connect before Loader.item is assigned (S5 pitfall 1).
  onConnectedChanged: {
    if (connected) {
      attempt = 0
      retryTimer.stop()
      launching = false
      attaching = false
      connection = "connected"
      lastError = ""
      quitting = false
      if (quitPending) {
        // quit() came in during startup; now there is a socket to say it on.
        quitPending = false
        quitting = true
        send(["quit"])
        return
      }
      subscribe()
      flushPending()
    } else if (connection === "connected") {
      mpvState = Mpv.emptyState()
      sleepTimer = null
      if (quitting) {
        quitting = false
        connection = "idle"
        // The old scope may outlive the socket. Wait for it to go before any
        // new mpv, whether or not a play() is already waiting.
        beginRelaunch()
      } else {
        // Not asked for: surface it, and retry only while a book is wanted.
        lastError = "mpv exited unexpectedly"
        connection = wanted ? "lost" : "failed"
        if (wanted) connectNow()
      }
    }
  }

  // ---- connection ----

  function send(command) {
    var socket = socketLoader.item
    if (!socket || !socket.connected) return false
    socket.write(JSON.stringify({ "command": command, "request_id": nextRequest++ }) + "\n")
    socket.flush()
    return true
  }

  function subscribe() {
    var commands = Mpv.observeCommands()
    for (var i = 0; i < commands.length; i++) send(commands[i])
  }

  function handleLine(line) {
    var message = Mpv.parseMessage(line)
    if (!message) return
    if (message.kind === "property") {
      mpvState = Mpv.applyProperty(mpvState, message.name, message.data)
    } else if (message.kind === "reply" && message.error) {
      lastError = "mpv: " + message.error
    }
  }

  // A failed connect leaves a dead Socket, so every try builds a new one
  // (S5 pitfall 2). "Socket file exists" proves nothing; only a connect does
  // (pitfall 3).
  function connectNow() {
    attempt += 1
    socketLoader.active = false
    socketLoader.active = true
    retryTimer.interval = Mpv.backoffMs(attempt)
    retryTimer.restart()
  }

  function giveUp() {
    retryTimer.stop()
    quitPending = false
    // The startup attach found only a stale socket, but a play was waiting.
    if (attaching && pendingLoad) {
      attaching = false
      launchMpv()
      return
    }
    socketLoader.active = false
    if (launching) {
      connection = "failed"
      lastError = "mpv did not start"
    } else if (wanted) {
      connection = "failed"
      lastError = "mpv exited unexpectedly"
    } else {
      connection = "idle"
    }
    wanted = false
    attaching = false
    launching = false
    mpvState = Mpv.emptyState()
    attempt = 0
  }

  // Startup: reattach to an mpv that outlived a shell restart. Tries only when
  // the socket file exists, and only a bounded number of times.
  function attach() {
    if (connected || socketPath.length === 0) return
    probe.command = ["test", "-S", socketPath]
    probe.running = true
  }

  function launchMpv() {
    var mpv = ["mpv", "--no-config", "--no-video", "--idle=yes", "--keep-open=yes",
      "--no-terminal", "--audio-display=no", "--force-window=no",
      "--volume=" + initialVolume, "--input-ipc-server=" + socketPath]
    var command = useScope
      ? ["systemd-run", "--user", "--scope", "--quiet", "--collect",
         "--unit=omarchy-audible-mpv"].concat(mpv)
      : mpv
    var dir = socketPath.replace(/\/[^\/]*$/, "")
    // mkdir and launch in one shell so mpv never starts before its directory.
    Quickshell.execDetached(["sh", "-c", 'mkdir -p "$1" && shift && exec "$@"', "sh", dir].concat(command))
    launching = true
    connection = "launching"
    attempt = 0
    connectNow()
  }

  function flushPending() {
    if (!pendingLoad) return
    var load = pendingLoad
    pendingLoad = null
    send(Mpv.loadCommand(load.path, load.startSec))
    send(Mpv.pauseCommand(false))
  }

  // ---- control ----

  function play(path, startSec) {
    if (socketPath.length === 0) {
      lastError = "player not ready"
      return false
    }
    wanted = true
    pendingLoad = { "path": path, "startSec": startSec }
    // A quit that has not been sent yet is overtaken by this play.
    quitPending = false
    if (connected && !quitting) {
      flushPending()
    } else if (!connected && !launching && !attaching && !relaunchPending) {
      launchMpv()
    }
    return true
  }

  function pause() { send(Mpv.pauseCommand(true)) }
  function resume() { send(Mpv.pauseCommand(false)) }
  function toggle() { send(Mpv.pauseCommand(playing)) }
  function skip(seconds) { send(Mpv.skipCommand(seconds)) }
  function seekMs(ms) { send(Mpv.seekCommand(ms / 1000)) }
  function setChapter(index) { send(Mpv.chapterCommand(index)) }
  function setSpeed(value) { send(Mpv.speedCommand(value)) }
  function setVolume(value) { send(Mpv.volumeCommand(value)) }

  function jumpChapter(delta) {
    var target = Mpv.chapterTarget(chapterIndex, chapters.length, delta)
    if (target >= 0) setChapter(target)
  }
  function nextChapter() { jumpChapter(1) }
  function prevChapter() { jumpChapter(-1) }

  // Stops playback and ends the mpv process.
  function quit() {
    var starting = launching
    wanted = false
    pendingLoad = null
    launching = false
    cancelSleep()
    if (send(["quit"])) {
      attaching = false
      quitting = true
      return
    }
    if (starting || attaching) {
      // mpv is on its way up (or being reattached): keep the bounded connect
      // going and quit it as soon as it answers.
      quitPending = true
      attaching = true
      return
    }
    // Not connected and nothing starting: nothing to quit or retry.
    retryTimer.stop()
    socketLoader.active = false
    connection = "idle"
  }

  // The scope has one fixed name, so a new mpv can start only after the old
  // scope has gone; check it before launching.
  function beginRelaunch() {
    relaunchPending = true
    scopeChecks = 0
    relaunchTimer.restart()
  }

  // ---- sleep timer ----

  function setSleepTimer(minutes) {
    cancelSleep()
    if (minutes > 0) sleepTimer = { "mode": "minutes", "endsAtMs": Date.now() + minutes * 60000 }
  }

  function setSleepEndOfChapter() {
    cancelSleep()
    sleepTimer = Mpv.chapterSleepTimer(chapters, chapterIndex, durationMs)
  }

  function cancelSleep() {
    if (fadeBaseVolume >= 0) {
      setVolume(fadeBaseVolume)
      fadeBaseVolume = -1
    }
    sleepTimer = null
  }

  function sleepTick() {
    var remaining = Mpv.sleepRemainingMs(sleepTimer, Date.now(), positionMs, speed)
    if (remaining < 0 && sleepTimer.mode !== "minutes" && sleepTimer.mode !== "chapter") return
    if (remaining <= 0) {
      pause()
      cancelSleep()
      return
    }
    if (remaining < Mpv.FADE_MS) {
      if (fadeBaseVolume < 0) fadeBaseVolume = volume
      setVolume(Mpv.fadeVolume(fadeBaseVolume, remaining, Mpv.FADE_MS))
    } else if (fadeBaseVolume >= 0) {
      // Seeked back out of the fade window: bring the volume back.
      setVolume(fadeBaseVolume)
      fadeBaseVolume = -1
    }
  }

  // Paused or gone: end a fade in progress and put the volume back.
  onPlayingChanged: {
    if (!playing && sleepTimer !== null && fadeBaseVolume >= 0) cancelSleep()
  }

  Timer {
    interval: 250
    repeat: true
    running: root.sleepTimer !== null && root.playing
    onTriggered: root.sleepTick()
  }

  // ---- plumbing ----

  Component {
    id: socketComponent
    Socket {
      path: root.socketPath
      connected: true
      parser: SplitParser {
        splitMarker: "\n"
        onRead: function(line) { root.handleLine(line) }
      }
    }
  }

  Loader {
    id: socketLoader
    active: false
    sourceComponent: socketComponent
  }

  Timer {
    id: relaunchTimer
    interval: 300
    repeat: false
    onTriggered: scopeActive.running = true
  }

  Process {
    id: scopeActive
    command: ["systemctl", "--user", "is-active", "--quiet", "omarchy-audible-mpv.scope"]
    onExited: function(code, status) {
      var gone = code !== 0
      root.scopeChecks += 1
      if (!gone && root.scopeChecks < 10) {
        relaunchTimer.restart()
        return
      }
      root.relaunchPending = false
      if (!gone) {
        // Starting another mpv under the same unit name would be refused.
        root.wanted = false
        root.pendingLoad = null
        root.connection = "failed"
        root.lastError = "the previous mpv did not exit"
        return
      }
      if (root.wanted && root.pendingLoad && !root.connected) root.launchMpv()
    }
  }

  Timer {
    id: retryTimer
    repeat: false
    onTriggered: {
      if (root.connected) return
      if (Mpv.shouldRetry(root.attempt, root.wanted || root.attaching)) root.connectNow()
      else root.giveUp()
    }
  }

  Process {
    id: probe
    onExited: function(code, status) {
      if (code !== 0 || root.connected) return
      root.attaching = true
      root.connection = "connecting"
      root.attempt = 0
      root.connectNow()
    }
  }

  Process {
    id: scopeProbe
    command: ["sh", "-c", "command -v systemd-run"]
    onExited: function(code, status) { root.useScope = code === 0 }
  }

  Component.onCompleted: scopeProbe.running = true
}

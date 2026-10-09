import QtQuick
import Quickshell
import Quickshell.Io

import "lib/Mpv.js" as Mpv
import "lib/PlayerMachine.js" as PlayerMachine

// mpv under the shell (ARCHITECTURE 5.1, 5.2; S5 pitfalls). mpv is launched in
// its own systemd scope so it survives a shell restart, and this object
// reattaches to it over the JSON IPC socket. Attach, launch, reconnect, quit
// and relaunch are `PlayerMachine.step`; this object applies its effects.
Item {
  id: root

  visible: false
  width: 0
  height: 0

  // $XDG_RUNTIME_DIR/omarchy-audible[-fake]/mpv.sock, from the `status` event.
  property string socketPath: ""
  property int initialVolume: 100
  // The speed a new mpv starts at (F21: the saved one).
  property real initialSpeed: 1
  // The systemd scope mpv runs in. The fixed name refuses a second mpv; each
  // mode has its own, so a fake-mode mpv never blocks the real one.
  property string unitName: "omarchy-audible-mpv"

  // The machine's state has one writer: apply() assigns each PlayerMachine.step
  // result, and publish() copies it to the properties below.
  property var reducerState: PlayerMachine.createState()

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
  // mpv's playback-restart events: one after every seek has landed (and on
  // each load). The scrub bar waits for one before trusting positions again.
  property int restarts: 0
  // The next book to load: {path, startSec, options}. `options.lavf` is the
  // book's key (B11): it lives only here, and only until the load is sent.
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

  // The file of the last loadfile sent to this mpv ("" when none since
  // connecting), and whether mpv has said file-loaded since. A path, never
  // the key (Mpv.moveHitsPath).
  property string loadPath: ""
  property bool loadArrived: true

  // The user moved the position: a seek, skip or chapter jump was sent (F38).
  // `targetMs` is where it lands (Mpv.moveTargetMs), or -1 when unknown.
  signal userMoved(int targetMs)

  // Subscribe on the derived `connected`, not in Socket.onConnectionStateChanged:
  // the socket can connect before Loader.item is assigned (S5 pitfall 1).
  onConnectedChanged: apply({ "type": connected ? "connected" : "disconnected" })

  // The machine's only writer. The new state is published before any effect
  // runs, and an effect whose handlers call back in (a Socket that connects
  // at once, a write that finds mpv gone) is applied there and then, on top of
  // it: nothing is queued. `load` is a play's {path, startSec, options}, for
  // hold_load; it never goes to the machine. Returns the effects.
  function apply(event, load) {
    var transition = PlayerMachine.step(reducerState, event)
    reducerState = transition.state
    publish()
    transition.effects.forEach(function(effect) { perform(effect, load) })
    return transition.effects
  }

  // Plain copies, not bindings. Of these only `connection` has a listener
  // (Service's onConnectionChanged, which reads lastError later, with
  // Qt.callLater), so their order here can't be seen.
  function publish() {
    wanted = reducerState.wanted
    attaching = reducerState.attaching
    quitting = reducerState.quitting
    quitPending = reducerState.quitPending
    relaunchPending = reducerState.relaunchPending
    scopeChecks = reducerState.scopeChecks
    launching = reducerState.launching
    attempt = reducerState.attempt
    connection = reducerState.connection
    lastError = reducerState.lastError
  }

  function perform(effect, load) {
    var type = effect.type
    if (type === "connect") {
      // A failed connect leaves a dead Socket, so every try builds a new one
      // (S5 pitfall 2). "Socket file exists" proves nothing; only a connect
      // does (pitfall 3). One that connects at once has reset `attempt`.
      socketLoader.active = false
      socketLoader.active = true
      retryTimer.interval = Mpv.backoffMs(attempt)
      retryTimer.restart()
    } else if (type === "stop_retry") {
      retryTimer.stop()
    } else if (type === "close_socket") {
      socketLoader.active = false
    } else if (type === "close_quit") {
      socketLoader.active = false
      apply({ "type": "quit_closed" })
    } else if (type === "launch") {
      launchMpv()
    } else if (type === "subscribe") {
      subscribe()
    } else if (type === "clear_key") {
      send(Mpv.clearKeyCommand())
    } else if (type === "hold_load") {
      pendingLoad = load
    } else if (type === "flush_pending") {
      flushPending()
    } else if (type === "drop_load") {
      pendingLoad = null
    } else if (type === "send_quit") {
      send(["quit"])
    } else if (type === "try_quit") {
      apply({ "type": "quit_sent", "sent": send(["quit"]), "starting": effect.starting })
    } else if (type === "cancel_sleep") {
      cancelSleep()
    } else if (type === "reset_state") {
      mpvState = Mpv.emptyState()
      loadPath = ""
      loadArrived = true
    } else if (type === "forget_sleep") {
      sleepTimer = null
      // A fade's base volume belongs to the mpv that is gone; a later
      // cancelSleep() must not send it to a new one (F22).
      fadeBaseVolume = -1
    } else if (type === "begin_relaunch" || type === "recheck_scope") {
      relaunchTimer.restart()
    } else if (type === "probe_socket") {
      probe.command = ["test", "-S", socketPath]
      probe.running = true
    } else if (type === "probe_scope") {
      scopeProbe.running = true
    } else if (type === "use_scope") {
      useScope = effect.value === true
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
    } else if (message.kind === "event" && message.event === "playback-restart") {
      restarts += 1
    } else if (message.kind === "event" && message.event === "file-loaded") {
      loadArrived = true
      // mpv has opened the file, so it no longer needs the key: take it out
      // of the readable option (SPIKE-RESULTS S7). Once per load; harmless
      // for an old `.m4b`, and a quick switch to another book can't leave a
      // key behind, since that book's own file-loaded clears it too.
      send(Mpv.clearKeyCommand())
    } else if (message.kind === "reply" && message.error) {
      apply({ "type": "reply_error", "error": message.error })
    }
  }

  function giveUp() { apply({ "type": "give_up" }) }

  // Startup: reattach to an mpv that outlived a shell restart. Tries only when
  // the socket file exists, and only a bounded number of times.
  function attach() { apply({ "type": "attach", "ready": socketPath.length > 0, "connected": connected }) }

  function launchMpv() {
    var mpv = ["mpv", "--no-config", "--no-video", "--idle=yes", "--keep-open=yes",
      "--no-terminal", "--audio-display=no", "--force-window=no",
      "--volume=" + initialVolume, "--speed=" + initialSpeed, "--input-ipc-server=" + socketPath]
    var command = useScope
      ? ["systemd-run", "--user", "--scope", "--quiet", "--collect",
         "--unit=" + unitName].concat(mpv)
      : mpv
    var dir = socketPath.replace(/\/[^\/]*$/, "")
    // mkdir and launch in one shell so mpv never starts before its directory.
    Quickshell.execDetached(["sh", "-c", 'mkdir -p "$1" && shift && exec "$@"', "sh", dir].concat(command))
  }

  function flushPending() {
    if (!pendingLoad) return
    var load = pendingLoad
    pendingLoad = null
    if (send(Mpv.loadCommand(load.path, load.startSec, load.options))) {
      loadPath = load.path
      loadArrived = false
    }
    send(Mpv.pauseCommand(false))
  }

  // ---- control ----

  // `options` is {lavf, chaptersFile} from `play-info`; both may be empty
  // (an old `.m4b`). The key is never stored anywhere else. False when the
  // player is not ready (no socket path yet).
  function play(path, startSec, options) {
    var load = { "path": path, "startSec": startSec, "options": Mpv.loadOptions(options) }
    return PlayerMachine.holdsLoad(apply({ "type": "play", "ready": socketPath.length > 0, "connected": connected }, load))
  }

  function pause() { send(Mpv.pauseCommand(true)) }
  function resume() { send(Mpv.pauseCommand(false)) }
  function toggle() { send(Mpv.pauseCommand(playing)) }
  // A seek, skip or chapter jump the user asked for says so with `userMoved`
  // and where it lands, so a move made while paused is saved (F38). A move
  // sent while another file is still on its way lands on that file, so it
  // isn't reported. `jumpToMs` is a seek that is not the user's (the catch-up
  // jump).
  function skip(seconds) {
    var target = Mpv.moveTargetMs("skip", Number(seconds), positionMs, durationMs, chapters)
    if (send(Mpv.skipCommand(seconds)) && Mpv.moveHitsPath(path, loadPath, loadArrived)) userMoved(target)
  }
  function seekMs(ms) {
    var target = Mpv.moveTargetMs("seek", Number(ms), positionMs, durationMs, chapters)
    if (send(Mpv.seekCommand(ms / 1000)) && Mpv.moveHitsPath(path, loadPath, loadArrived)) userMoved(target)
  }
  function jumpToMs(ms) { send(Mpv.seekCommand(ms / 1000)) }
  function setChapter(index) {
    var target = Mpv.moveTargetMs("chapter", Number(index), positionMs, durationMs, chapters)
    if (send(Mpv.chapterCommand(index)) && Mpv.moveHitsPath(path, loadPath, loadArrived)) userMoved(target)
  }
  function setSpeed(value) { send(Mpv.speedCommand(value)) }
  function setVolume(value) { send(Mpv.volumeCommand(value)) }

  function jumpChapter(delta) {
    var target = Mpv.chapterTarget(chapterIndex, chapters.length, delta)
    if (target >= 0) setChapter(target)
  }
  function nextChapter() { jumpChapter(1) }
  function prevChapter() { jumpChapter(-1) }

  // Stops playback and ends the mpv process.
  function quit() { apply({ "type": "quit" }) }

  // ---- sleep timer ----

  function setSleepTimer(minutes) {
    cancelSleep()
    sleepTimer = Mpv.minutesSleepTimer(minutes, Date.now(), playing)
  }

  function setSleepEndOfChapter() {
    cancelSleep()
    sleepTimer = Mpv.chapterSleepTimer(chapters, chapterIndex, durationMs)
  }

  function cancelSleep() {
    endFade()
    sleepTimer = null
  }

  // A fade in progress stops and the volume goes back to where it was.
  function endFade() {
    if (fadeBaseVolume >= 0) {
      setVolume(fadeBaseVolume)
      fadeBaseVolume = -1
    }
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
    } else {
      // Seeked back out of the fade window: bring the volume back.
      endFade()
    }
  }

  // Paused or gone: end a fade in progress and put the volume back, but keep
  // the timer. A minutes timer stops counting while paused and goes on from
  // where it was on resume (F23); the fade starts again near its end.
  onPlayingChanged: {
    if (!playing) {
      endFade()
      sleepTimer = Mpv.holdSleepTimer(sleepTimer, Date.now())
    } else {
      sleepTimer = Mpv.resumeSleepTimer(sleepTimer, Date.now())
    }
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

  // The scope has one fixed name, so a new mpv can start only after the old
  // scope has gone; the relaunch checks it before launching.
  Timer {
    id: relaunchTimer
    interval: 300
    repeat: false
    onTriggered: scopeActive.running = true
  }

  Process {
    id: scopeActive
    command: ["systemctl", "--user", "is-active", "--quiet", root.unitName + ".scope"]
    // `is-active --quiet` exits 0 only while the scope is active.
    onExited: function(code, status) {
      root.apply({ "type": code === 0 ? "scope_active" : "scope_gone", "connected": root.connected })
    }
  }

  Timer {
    id: retryTimer
    repeat: false
    onTriggered: root.apply({ "type": "retry_tick", "connected": root.connected })
  }

  Process {
    id: probe
    onExited: function(code, status) { root.apply({ "type": "probe_result", "code": code, "connected": root.connected }) }
  }

  Process {
    id: scopeProbe
    command: ["sh", "-c", "command -v systemd-run"]
    onExited: function(code, status) { root.apply({ "type": "scope_probe_result", "code": code }) }
  }

  Component.onCompleted: apply({ "type": "start" })
}

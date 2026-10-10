.pragma library
.import "Mpv.js" as Mpv

// PlayerController's connection machine (ARCHITECTURE 5.1, 5.2; SPIKE-RESULTS
// S5): whether a book is wanted, the startup attach, the launch, the bounded
// reconnect, the quit and the relaunch that waits for the old scope.
// `step(state, event)` returns the next state and the effects the controller
// applies, in order; the controller owns the socket, the processes, the timers
// and the load itself. Pure ECMAScript for the Qt JS engine: no Qt types, and
// nothing here throws on bad input.
//
// The book's key never comes here. A play's load ({path, startSec, options})
// stays in PlayerController's `pendingLoad`; the machine only knows that one
// is waiting (`loadPending`) and says when to keep, send or drop it.
//
// State:
//   wanted           a book is supposed to be loaded: reconnects happen only
//                    while this (or `attaching`) holds (S5 pitfall 5)
//   attaching        the startup attach to an mpv that outlived the shell
//   launching        mpv was started and has not connected yet
//   quitting         `quit` was sent: the next disconnect is the asked-for one
//   quitPending      quit() came while mpv was starting: quit once it connects
//   relaunchPending  the old mpv is gone but its scope may not be: wait
//   scopeChecks      scope checks made in this wait
//   attempt          connects tried since the last reset (Mpv.backoffMs)
//   connection       idle | launching | connecting | connected | lost | failed
//   lastError        the last failure, for the Mini line and the notification
//   loadPending      a play's load is waiting in PlayerController.pendingLoad
//
// Events:
//   start                     the controller exists: look for systemd-run
//   scope_probe_result {code} `command -v systemd-run` exited
//   attach {ready, connected} reattach at startup (`ready`: a socket path)
//   probe_result {code, connected}  `test -S <socket>` exited
//   load_failed               mpv's end-file(error) for a load sent since the
//                             last file-loaded (F40)
//   play {ready, connected}   play a book; its load goes with the event to
//                             the controller, not to this file
//   quit                      stop playback and end mpv
//   quit_sent {sent, starting}  what try_quit's send did; `starting` is the
//                             effect's own value, handed back
//   quit_closed               close_quit has dropped the Socket
//   connected                 the derived `connected` became true (S5 pitfall 1)
//   disconnected              it became false
//   retry_tick {connected}    the retry timer fired
//   give_up                   stop trying to connect
//   scope_active              the relaunch's scope check: the old scope is
//                             still active
//   scope_gone {connected}    the relaunch's scope check: it has gone
//   reply_error {error}       mpv answered a command with an error
//
// Effects:
//   probe_scope      run the systemd-run probe
//   use_scope {value}  launch through systemd-run (true) or plainly (false)
//   probe_socket     run `test -S` on the socket path
//   launch           start mpv detached (Quickshell.execDetached)
//   connect          build a new Socket (S5 pitfall 2), then restart the retry
//                    timer at Mpv.backoffMs(attempt), reading `attempt` after
//                    the Socket is built: one that connects at once has
//                    already reset it
//   stop_retry       stop the retry timer
//   close_socket     drop the Socket
//   subscribe        send the observe_property commands
//   clear_key        send Mpv.clearKeyCommand()
//   hold_load        keep this play's load as `pendingLoad`
//   flush_pending    send `pendingLoad` (loadfile, then unpause) and forget it
//   drop_load        forget `pendingLoad`: nothing will send it now
//   send_quit        send `quit`
//   try_quit {starting}  send `quit`, then apply quit_sent with whether it went
//   close_quit       drop the Socket, then apply quit_closed
//   cancel_sleep     cancel the sleep timer, ending a fade
//   reset_state      forget the gone mpv: mpvState, loadPath, loadArrived
//   forget_sleep     sleepTimer = null, fadeBaseVolume = -1 (F22)
//   begin_relaunch   start the wait for the old scope (the relaunch timer)
//   recheck_scope    wait and check the scope again

// Scope checks before the relaunch gives up on the old mpv.
var SCOPE_CHECKS = 10;

var CONNECTIONS = ["idle", "launching", "connecting", "connected", "lost", "failed"];

function createState() {
  return {
    "wanted": false,
    "attaching": false,
    "launching": false,
    "quitting": false,
    "quitPending": false,
    "relaunchPending": false,
    "scopeChecks": 0,
    "attempt": 0,
    "connection": "idle",
    "lastError": "",
    "loadPending": false
  };
}

function step(state, event) {
  var current = _machine.cleanState(state);
  var effects = [];
  if (!_machine.isObject(event)) return _machine.result(current, effects);
  var type = event.type;
  if (type === "start") {
    effects.push({ "type": "probe_scope" });
  } else if (type === "scope_probe_result") {
    effects.push({ "type": "use_scope", "value": event.code === 0 });
  } else if (type === "attach") {
    if (event.ready === true && event.connected !== true) effects.push({ "type": "probe_socket" });
  } else if (type === "probe_result") {
    if (event.code === 0 && event.connected !== true) {
      current.attaching = true;
      current.connection = "connecting";
      current.attempt = 0;
      _machine.connect(current, effects);
    }
  } else if (type === "play") {
    _machine.play(current, event, effects);
  } else if (type === "quit") {
    var starting = current.launching;
    current.wanted = false;
    current.loadPending = false;
    effects.push({ "type": "drop_load" });
    current.launching = false;
    effects.push({ "type": "cancel_sleep" });
    effects.push({ "type": "try_quit", "starting": starting });
  } else if (type === "quit_sent") {
    _machine.quitSent(current, event, effects);
  } else if (type === "quit_closed") {
    current.connection = "idle";
  } else if (type === "connected") {
    _machine.connected(current, effects);
  } else if (type === "disconnected") {
    _machine.disconnected(current, effects);
  } else if (type === "retry_tick") {
    if (event.connected !== true) {
      if (Mpv.shouldRetry(current.attempt, current.wanted || current.attaching)) _machine.connect(current, effects);
      else _machine.giveUp(current, effects);
    }
  } else if (type === "give_up") {
    _machine.giveUp(current, effects);
  } else if (type === "scope_active") {
    current.scopeChecks += 1;
    if (current.scopeChecks < SCOPE_CHECKS) {
      effects.push({ "type": "recheck_scope" });
    } else {
      current.relaunchPending = false;
      // Starting another mpv under the same unit name would be refused.
      current.wanted = false;
      current.loadPending = false;
      effects.push({ "type": "drop_load" });
      current.connection = "failed";
      current.lastError = "the previous mpv did not exit";
    }
  } else if (type === "scope_gone") {
    current.scopeChecks += 1;
    current.relaunchPending = false;
    if (current.wanted && current.loadPending && event.connected !== true) _machine.launch(current, effects);
  } else if (type === "reply_error") {
    if (typeof event.error === "string") current.lastError = "mpv: " + event.error;
  } else if (type === "load_failed") {
    // F40: mpv could not open the file it was sent (missing, corrupt, wrong
    // key). It stays up and idle; nothing is wanted any more, and the key
    // the failed load carried comes out of mpv's options.
    current.wanted = false;
    current.loadPending = false;
    current.lastError = "the player could not open the book";
    effects.push({ "type": "drop_load" });
    effects.push({ "type": "clear_key" });
  }
  return _machine.result(current, effects);
}

// Whether a play's effects keep its load, which is whether the play was taken.
function holdsLoad(effects) {
  return Array.isArray(effects) && effects.some(function (effect) {
    return _machine.isObject(effect) && effect.type === "hold_load";
  });
}

var _machine = {};

_machine.isObject = function (value) {
  return value !== null && value !== undefined && typeof value === "object" && !Array.isArray(value);
};
_machine.count = function (value) {
  return typeof value === "number" && isFinite(value) && value > 0 ? Math.floor(value) : 0;
};
_machine.result = function (state, effects) { return { "state": state, "effects": effects }; };
_machine.cleanState = function (state) {
  var base = createState();
  if (!_machine.isObject(state)) return base;
  base.wanted = state.wanted === true;
  base.attaching = state.attaching === true;
  base.launching = state.launching === true;
  base.quitting = state.quitting === true;
  base.quitPending = state.quitPending === true;
  base.relaunchPending = state.relaunchPending === true;
  base.scopeChecks = _machine.count(state.scopeChecks);
  base.attempt = _machine.count(state.attempt);
  if (CONNECTIONS.indexOf(state.connection) !== -1) base.connection = state.connection;
  if (typeof state.lastError === "string") base.lastError = state.lastError;
  base.loadPending = state.loadPending === true;
  return base;
};

// Every try builds a new Socket; "the socket file exists" proves nothing, only
// a connect does (S5 pitfalls 2 and 3).
_machine.connect = function (state, effects) {
  state.attempt += 1;
  effects.push({ "type": "connect" });
};

_machine.launch = function (state, effects) {
  effects.push({ "type": "launch" });
  state.launching = true;
  state.connection = "launching";
  state.attempt = 0;
  _machine.connect(state, effects);
};

_machine.flush = function (state, effects) {
  if (!state.loadPending) return;
  state.loadPending = false;
  effects.push({ "type": "flush_pending" });
};

_machine.play = function (state, event, effects) {
  if (event.ready !== true) {
    state.lastError = "player not ready";
    return;
  }
  state.wanted = true;
  state.loadPending = true;
  effects.push({ "type": "hold_load" });
  // A quit that has not been sent yet is overtaken by this play.
  state.quitPending = false;
  if (event.connected === true && !state.quitting) {
    _machine.flush(state, effects);
  } else if (event.connected !== true && !state.launching && !state.attaching && !state.relaunchPending) {
    _machine.launch(state, effects);
  }
};

_machine.quitSent = function (state, event, effects) {
  if (event.sent === true) {
    state.attaching = false;
    state.quitting = true;
  } else if (event.starting === true || state.attaching) {
    // mpv is on its way up (or being reattached): keep the bounded connect
    // going and quit it as soon as it answers.
    state.quitPending = true;
    state.attaching = true;
  } else {
    // Not connected and nothing starting: nothing to quit or retry. The
    // connection goes idle once the Socket is dropped (quit_closed).
    effects.push({ "type": "stop_retry" });
    effects.push({ "type": "close_quit" });
  }
};

_machine.connected = function (state, effects) {
  state.attempt = 0;
  effects.push({ "type": "stop_retry" });
  state.launching = false;
  state.attaching = false;
  state.connection = "connected";
  state.lastError = "";
  state.quitting = false;
  if (state.quitPending) {
    // quit() came in during startup; now there is a socket to say it on.
    state.quitPending = false;
    state.quitting = true;
    effects.push({ "type": "send_quit" });
    return;
  }
  effects.push({ "type": "subscribe" });
  // An mpv reattached after a shell restart may have been mid-load: make sure
  // no key is left in its options. Harmless when there is none.
  effects.push({ "type": "clear_key" });
  _machine.flush(state, effects);
};

_machine.disconnected = function (state, effects) {
  if (state.connection !== "connected") return;
  effects.push({ "type": "reset_state" });
  effects.push({ "type": "forget_sleep" });
  if (state.quitting) {
    state.quitting = false;
    state.connection = "idle";
    // The old scope may outlive the socket. Wait for it to go before any new
    // mpv, whether or not a play() is already waiting.
    state.relaunchPending = true;
    state.scopeChecks = 0;
    effects.push({ "type": "begin_relaunch" });
    return;
  }
  // Not asked for: surface it, and retry only while a book is wanted.
  state.lastError = "mpv exited unexpectedly";
  state.connection = state.wanted ? "lost" : "failed";
  if (state.wanted) _machine.connect(state, effects);
};

_machine.giveUp = function (state, effects) {
  effects.push({ "type": "stop_retry" });
  state.quitPending = false;
  // The startup attach found only a stale socket, but a play was waiting.
  if (state.attaching && state.loadPending) {
    state.attaching = false;
    _machine.launch(state, effects);
    return;
  }
  effects.push({ "type": "close_socket" });
  if (state.launching) {
    state.connection = "failed";
    state.lastError = "mpv did not start";
  } else if (state.wanted) {
    state.connection = "failed";
    state.lastError = "mpv exited unexpectedly";
  } else {
    state.connection = "idle";
  }
  // Nothing will send it now: don't keep its key.
  state.loadPending = false;
  effects.push({ "type": "drop_load" });
  state.wanted = false;
  state.attaching = false;
  state.launching = false;
  effects.push({ "type": "reset_state" });
  state.attempt = 0;
};

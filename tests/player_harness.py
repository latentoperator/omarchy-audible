"""Load the real ``qml/PlayerController.qml`` in a headless QQmlEngine (P9 PR 9).

``Quickshell`` and ``Quickshell.Io`` are stubs: ``execDetached`` records its
command, a ``Process`` runs only when the test finishes it, and a ``Socket``
connects only when the test says so (at once, the reattach case, or later, a
starting mpv), records what is written to it, and can find mpv gone on its
next send. ``SocketHub`` is the test's handle on them. The controller's own
timers never run on their own: a step fires one by hand.

``Harness.step(action, arg)`` does one thing and returns a snapshot of
everything observable: the controller's public properties, its timers and
processes, and what it wrote, launched and published since the last step.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import shiboken6
    from PySide6.QtCore import (
        Q_ARG,
        Q_RETURN_ARG,
        QCoreApplication,
        QMetaObject,
        QUrl,
        qInstallMessageHandler,
    )
    from PySide6.QtQml import QQmlComponent, QQmlEngine
except ImportError as exc:  # pragma: no cover - required dev dependency
    raise ImportError(
        "PySide6 is required for the PlayerController wiring tests"
    ) from exc

REPO = Path(__file__).resolve().parents[1]

SOCKET = "/tmp/oa-test/omarchy-audible-fake/mpv.sock"
UNIT = "omarchy-audible-fake-mpv"

_APP: QCoreApplication | None = None

_STUBS = {
    "Quickshell/qmldir": "module Quickshell\nsingleton Quickshell 1.0 Quickshell.qml\n",
    "Quickshell/Quickshell.qml": """pragma Singleton
import QtQml
QtObject {
  property var detached: []
  function execDetached(command) { detached = detached.concat([command]) }
}
""",
    "Quickshell/Io/qmldir": (
        "module Quickshell.Io\n"
        "Process 1.0 Process.qml\n"
        "Socket 1.0 Socket.qml\n"
        "SplitParser 1.0 SplitParser.qml\n"
        "singleton SocketHub 1.0 SocketHub.qml\n"
    ),
    "Quickshell/Io/Process.qml": """import QtQml
QtObject {
  property var command: []
  property bool running: false
  signal exited(int code, int status)
  function finish(code) { running = false; exited(code, 0) }
}
""",
    "Quickshell/Io/SplitParser.qml": """import QtQml
QtObject {
  property string splitMarker: ""
  signal read(string data)
}
""",
    # Writing `connected: true` asks a real Socket to connect; the stub
    # answers with what SocketHub says instead. Like QLocalSocket, a write is
    # buffered and goes out on flush, which is where a dead mpv is found: the
    # socket then disconnects there and then, inside the controller's send().
    "Quickshell/Io/Socket.qml": """import QtQml
QtObject {
  id: socket
  property string path: ""
  property QtObject parser: null
  property bool connected: false
  property var buffered: []
  Component.onCompleted: {
    connected = SocketHub.connectAtOnce
    SocketHub.add(socket)
  }
  function write(text) { buffered = buffered.concat([JSON.parse(text).command]) }
  function flush() {
    var out = buffered
    buffered = []
    if (!SocketHub.dropNextSend) {
      SocketHub.writes = SocketHub.writes.concat(out)
      return
    }
    SocketHub.dropNextSend = false
    connected = false
  }
}
""",
    "Quickshell/Io/SocketHub.qml": """pragma Singleton
import QtQml
QtObject {
  property bool connectAtOnce: false
  property bool dropNextSend: false
  property var writes: []
  property int built: 0
  property QtObject current: null
  function add(socket) { built += 1; current = socket }
}
""",
}

_MAIN = """import QtQuick
import Quickshell
import Quickshell.Io
Item {
  id: top
  property var published: []
  property int externalUnloads: 0
  property var loadFailures: []
  property var lastResult: null
  property var loader: null
  property var retryTimer: null
  property var relaunchTimer: null
  property var probe: null
  property var scopeActive: null
  property var scopeProbe: null

  PlayerController {
    id: player
    unitName: "%(unit)s"
    initialVolume: 15
    initialSpeed: 1.25
  }

  Connections {
    target: player
    function onConnectionChanged() { top.published = top.published.concat([player.connection]) }
    function onExternalUnload() { top.externalUnloads += 1; player.quit() }
    function onLoadFailed(path) { top.loadFailures = top.loadFailures.concat([path]) }
  }

  // The controller's children, told apart by what they are before any step.
  Component.onCompleted: {
    for (var i = 0; i < player.data.length; i++) {
      var child = player.data[i]
      if (child.sourceComponent !== undefined) loader = child
      else if (child.triggeredOnStart !== undefined && !child.repeat && child.interval === 300) relaunchTimer = child
      else if (child.triggeredOnStart !== undefined && !child.repeat) retryTimer = child
      else if (child.command !== undefined && child.command.length === 0) probe = child
      else if (child.command !== undefined && child.command[0] === "systemctl") scopeActive = child
      else if (child.command !== undefined && child.command[0] === "sh") scopeProbe = child
    }
  }

  function fire(timer) {
    if (!timer.running) return "not running"
    // A one-shot Timer is no longer running when it triggers.
    timer.stop()
    timer.triggered()
    return null
  }

  function set(socket, connected) {
    socket.connected = connected
    return null
  }

  function read(socket, message) {
    socket.parser.read(JSON.stringify(message))
    return null
  }

  function exit(process, code) {
    if (!process.running) return "not running"
    process.finish(code)
    return null
  }

  function act(name, arg) {
    if (name === "none") return null
    if (name === "socketPath") player.socketPath = arg
    else if (name === "mprisScript") player.mprisScript = arg
    else if (name === "play") return player.play(arg.path, arg.start, { "lavf": arg.key, "chaptersFile": "" })
    else if (name === "quit") player.quit()
    else if (name === "attach") player.attach()
    else if (name === "connectAtOnce") SocketHub.connectAtOnce = arg
    else if (name === "dropNextSend") SocketHub.dropNextSend = true
    else if (name === "up") return SocketHub.current ? set(SocketHub.current, true) : "no socket"
    else if (name === "down") return SocketHub.current ? set(SocketHub.current, false) : "no socket"
    else if (name === "line") return SocketHub.current ? read(SocketHub.current, arg) : "no socket"
    else if (name === "externalStop") {
      if (!SocketHub.current) return "no socket"
      read(SocketHub.current, { "event": "property-change", "name": "path", "data": null })
      read(SocketHub.current, { "event": "property-change", "name": "idle-active", "data": true })
    }
    else if (name === "retry") return fire(retryTimer)
    else if (name === "relaunch") return fire(relaunchTimer)
    else if (name === "probeExit") return exit(probe, arg)
    else if (name === "scopeExit") return exit(scopeActive, arg)
    else if (name === "scopeProbeExit") return exit(scopeProbe, arg)
    else if (name === "sleep") player.setSleepTimer(arg)
    else if (name === "fade") {
      // A sleep fade in progress: the volume it started from is kept.
      player.sleepTimer = { "mode": "minutes", "endsAtMs": Date.now() + 2000 }
      player.fadeBaseVolume = arg
    } else return "unknown step " + name
    return null
  }

  function step(request) {
    var result = act(request.name, request.arg)
    var snapshot = {
      "result": result === undefined ? null : result,
      "externalUnloads": top.externalUnloads,
      "loadFailures": top.loadFailures,
      "connection": player.connection, "lastError": player.lastError,
      "connected": player.connected, "wanted": player.wanted,
      "attaching": player.attaching, "launching": player.launching,
      "quitting": player.quitting, "quitPending": player.quitPending,
      "relaunchPending": player.relaunchPending, "attempt": player.attempt,
      "scopeChecks": player.scopeChecks, "useScope": player.useScope,
      "pendingLoad": player.pendingLoad ? player.pendingLoad.path : null,
      "loadPath": player.loadPath, "loadArrived": player.loadArrived,
      "path": player.path, "loaded": player.loaded, "playing": player.playing,
      "sleepTimer": player.sleepTimer ? player.sleepTimer.mode : null,
      "fadeBaseVolume": player.fadeBaseVolume,
      "retry": retryTimer.running ? retryTimer.interval : null,
      "relaunch": relaunchTimer.running,
      "probe": probe.running ? probe.command : null,
      "scopeCheck": scopeActive.running, "scopeProbe": scopeProbe.running,
      "socket": loader.active, "built": SocketHub.built,
      "writes": SocketHub.writes, "detached": Quickshell.detached,
      "published": top.published
    }
    SocketHub.writes = []
    Quickshell.detached = []
    top.published = []
    return snapshot
  }

  function reducerState() { return player.reducerState }
}
"""

# Reported for every step, then cleared: what happened during it.
EVENTS = ("result", "writes", "detached", "published")


def _application() -> QCoreApplication:
    global _APP
    if _APP is None:
        _APP = QCoreApplication.instance() or QCoreApplication([])
    return _APP


def _variant(value: Any) -> Any:
    return value.toVariant() if hasattr(value, "toVariant") else value


def _plain(value: Any) -> Any:
    """QVariant numbers come back as floats; whole ones become ints."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    return value


class Harness:
    def __init__(self, tmp_path: Path, repo: Path = REPO) -> None:
        _application()
        for relative, text in _STUBS.items():
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        app = tmp_path / "app"
        (app / "lib").mkdir(parents=True)
        shutil.copy2(repo / "qml/PlayerController.qml", app / "PlayerController.qml")
        for source in (repo / "qml/lib").glob("*.js"):
            shutil.copy2(source, app / "lib" / source.name)
        (app / "Main.qml").write_text(_MAIN % {"unit": UNIT}, encoding="utf-8")
        self.warnings: list[str] = []
        self._previous = qInstallMessageHandler(
            lambda mode, context, message: self.warnings.append(message)
        )
        self.engine = QQmlEngine()
        self.engine.addImportPath(str(tmp_path))
        self.component = QQmlComponent(
            self.engine, QUrl.fromLocalFile(str(app / "Main.qml"))
        )
        self.root = self.component.create()
        assert self.root is not None, self.component.errorString()
        self.last = self._call("step", {"name": "none", "arg": None})

    def _call(self, name: str, arg: Any = None) -> Any:
        if arg is None:
            value = QMetaObject.invokeMethod(self.root, name, Q_RETURN_ARG("QVariant"))
        else:
            value = QMetaObject.invokeMethod(
                self.root, name, Q_RETURN_ARG("QVariant"), Q_ARG("QVariant", arg)
            )
        return _plain(_variant(value))

    def step(self, name: str, arg: Any = None) -> dict:
        """Do one step; return the fields that changed, plus what happened."""
        snapshot = self._call("step", {"name": name, "arg": arg})
        changed = {
            key: value
            for key, value in snapshot.items()
            if key in EVENTS
            and value not in (None, [])
            or key not in EVENTS
            and self.last.get(key) != value
        }
        self.last = snapshot
        return changed

    def reducer_state(self) -> dict:
        return self._call("reducerState")

    def close(self) -> None:
        """Delete the engine now: with no event loop a deleteLater never runs,
        and its QQmlThread would take process signals other tests send
        themselves (test_redownload's SIGTERM)."""
        qInstallMessageHandler(self._previous)
        self.root = None
        self.component = None
        engine, self.engine = self.engine, None
        if shiboken6.isValid(engine):
            shiboken6.delete(engine)

"""Drive the real ``qml/components/BoundedTextField.qml`` in a headless window.

Run as a script (``python field_harness.py <stub dir>``) by
``test_bounded_text_field.py``: it needs a ``QGuiApplication`` with real key
and mouse events, which cannot share a process with the suites that create a
``QCoreApplication``. Prints one JSON object of observations.

``qs.Commons``, ``qs.Ui`` and ``Quickshell.Io`` are stubs written by the test.
``qs.Ui.TextField`` is a plain Qt Quick Controls ``TextField`` with the
Omarchy ``password`` property, as in the shell. The stub ``Process`` records
its command and lets the script deliver the helper's output line.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QEvent, QMetaObject, QPointF, Qt, QUrl
from PySide6.QtGui import QGuiApplication, QKeyEvent, QMouseEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem

REPO = Path(__file__).resolve().parents[1]

MAIN = """import QtQuick
import QtQuick.Window
import Quickshell.Io
import qs.Ui as Ui

Window {
  id: window
  width: 400
  height: 120
  visible: true

  Column {
    BoundedTextField {
      id: field
      objectName: "field"
      width: 300
      maxChars: 12
      pasteBytes: 64
      Keys.onPressed: function(event) {
        if (field.editKey(event)) event.accepted = true
      }
    }
    BoundedTextField {
      id: other
      objectName: "other"
      width: 300
      password: true
      Keys.onPressed: function(event) {
        if (other.editKey(event)) event.accepted = true
      }
    }
  }

  // A plain editable field, as before the fix: Qt reads the clipboard for it.
  Ui.TextField {
    id: control
    objectName: "control"
    y: 100
    width: 100
  }

  function processCount() { return Hub.processes.length }
  // The index of the field's own Process: the one that has been started.
  function started() {
    for (var i = 0; i < Hub.processes.length; i++)
      if (Hub.processes[i].command.length > 0) return i
    return -1
  }
  function startedCount() {
    var n = 0
    for (var i = 0; i < Hub.processes.length; i++)
      if (Hub.processes[i].command.length > 0) n++
    return n
  }
  function processCommand(index) { return Hub.processes[index].command.map(String) }
  function processRunning(index) { return Hub.processes[index].running }
  function deliver(index, line) { Hub.processes[index].stdout.read(line); return true }
  function finish(index) { Hub.processes[index].finish(0); return true }
}
"""


def call(target, name, *args):
    """Calls a QML function with plain arguments; returns a plain value."""
    value = QMetaObject.invokeMethod(
        target,
        name,
        Q_RETURN_ARG("QVariant"),
        *[Q_ARG("QVariant", arg) for arg in args],
    )
    return value.toVariant() if hasattr(value, "toVariant") else value


def key(app, window, code, modifiers=Qt.NoModifier, text=""):
    """One key press and release, as the window would receive it."""
    for kind in (QEvent.KeyPress, QEvent.KeyRelease):
        app.sendEvent(window, QKeyEvent(kind, code, modifiers, text))
    app.processEvents()


def keys(app, window, text):
    for char in text:
        key(app, window, ord(char.upper()), Qt.NoModifier, char)


def main() -> None:
    stubs = Path(sys.argv[1])
    app = QGuiApplication([])
    app.clipboard().setText("not from the helper")
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(stubs))
    main_qml = stubs / "Main.qml"
    main_qml.write_text(
        'import "' + (REPO / "qml" / "components").as_uri() + '"\n' + MAIN,
        encoding="utf-8",
    )
    warnings: list[str] = []
    engine.warnings.connect(lambda items: warnings.extend(w.toString() for w in items))
    engine.load(QUrl.fromLocalFile(str(main_qml)))
    window = engine.rootObjects()[0]
    field = window.findChild(QQuickItem, "field")
    other = window.findChild(QQuickItem, "other")
    out: dict[str, object] = {"warnings": warnings}

    def settle() -> None:
        for _ in range(5):
            app.processEvents()

    def text() -> str:
        return field.property("text")

    window.show() if hasattr(window, "show") else None
    field.forceActiveFocus()
    settle()
    out["focused"] = field.property("activeFocus")
    out["readOnly"] = field.property("readOnly")
    out["canPaste_start"] = field.property("canPaste")

    # The clipboard changes: Qt must not consider pasting.
    app.clipboard().setText("changed while focused")
    settle()
    out["canPaste_after_change"] = field.property("canPaste")
    # The control shows the harness can see Qt's own clipboard read.
    out["control_canPaste"] = window.findChild(QQuickItem, "control").property(
        "canPaste"
    )

    keys(app, window, "Dune")
    settle()
    out["typed"] = text()
    key(app, window, Qt.Key_Backspace, Qt.NoModifier, "\x08")
    out["backspace"] = text()
    key(app, window, Qt.Key_Left)
    key(app, window, Qt.Key_Delete, Qt.NoModifier, "\x7f")
    out["left_delete"] = text()
    keys(app, window, "n")
    out["insert_middle"] = text()
    key(app, window, Qt.Key_A, Qt.ControlModifier, "\x01")
    keys(app, window, "x")
    out["select_all_replace"] = text()
    keys(app, window, "abcdefghijklmnop")
    out["capped"] = text()

    # Ctrl+V and Shift+Insert start the helper; Qt pastes nothing itself.
    field.setProperty("text", "x")
    field.setProperty("cursorPosition", 1)
    key(app, window, Qt.Key_V, Qt.ControlModifier, "\x16")
    settle()
    out["after_ctrl_v"] = text()
    out["process_count"] = call(window, "processCount")
    out["started_count"] = call(window, "startedCount")
    index = call(window, "started")
    out["command"] = call(window, "processCommand", index)
    out["running"] = call(window, "processRunning", index)
    key(app, window, Qt.Key_V, Qt.ControlModifier, "\x16")
    settle()
    out["second_paste_while_running"] = text()
    call(window, "deliver", index, json.dumps({"text": "a\nb"}))
    call(window, "finish", index)
    out["pasted"] = text()
    key(app, window, Qt.Key_Insert, Qt.ShiftModifier)
    settle()
    call(window, "deliver", index, json.dumps({"text": "far too long to fit"}))
    call(window, "finish", index)
    out["over_limit_paste"] = text()
    key(app, window, Qt.Key_V, Qt.ControlModifier, "\x16")
    call(window, "deliver", index, "not json")
    call(window, "finish", index)
    out["bad_line"] = text()

    # A middle click pastes the primary selection into an editable field. The
    # offscreen platform has no primary selection, so this only shows the
    # click changes nothing; readOnly is what stops it on Wayland.
    center = QPointF(field.property("width") / 2, field.property("height") / 2)
    point = field.mapToScene(center)
    for kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        event = QMouseEvent(
            kind,
            point,
            point,
            Qt.MiddleButton,
            Qt.MiddleButton if kind == QEvent.MouseButtonPress else Qt.NoButton,
            Qt.NoModifier,
        )
        app.sendEvent(window, event)
    settle()
    out["middle_click"] = text()

    # Cut puts the selection on the clipboard and removes it.
    field.setProperty("text", "keep cut")
    QMetaObject.invokeMethod(field, "select", Q_ARG(int, 4), Q_ARG(int, 8))
    key(app, window, Qt.Key_X, Qt.ControlModifier, "\x18")
    out["cut_text"] = text()
    out["cut_clipboard"] = app.clipboard().text()

    # A password field never puts its text on the clipboard.
    app.clipboard().setText("unchanged")
    other.forceActiveFocus()
    other.setProperty("text", "secret")
    QMetaObject.invokeMethod(other, "selectAll")
    key(app, window, Qt.Key_X, Qt.ControlModifier, "\x18")
    out["password_cut_text"] = other.property("text")
    out["password_cut_clipboard"] = app.clipboard().text()
    out["password_readOnly"] = other.property("readOnly")
    out["password_canPaste"] = other.property("canPaste")

    out["readOnly_end"] = field.property("readOnly")
    print(json.dumps(out))


if __name__ == "__main__":
    main()

import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Ui
import "../lib/Typing.js" as Typing

// A one-line text field that never lets Qt read the clipboard.
//
// Qt reads the clipboard by itself, inside the shared shell and with no size
// limit or deadline, whenever an editable field exists and the clipboard
// changes, and again on every paste. A clipboard owner that keeps streaming
// could stall the shell or use up its memory (marketplace review of 0.1.2).
// So this field is read-only to Qt for its whole life: Qt still moves the
// cursor, selects and copies, but never reads the clipboard, pastes on a
// middle click or offers Paste in its menu. Typing, deleting, cutting and
// pasting go through `editKey` and `Typing.js` instead, and a paste runs
// `bin/omarchy-audible-paste`, which reads the clipboard outside the shell
// with a byte limit and a deadline.
//
// The view's own `Keys.onPressed` handles its keys (Esc, Enter, arrows) and
// passes the rest to `editKey(event)`.
TextField {
  id: root

  // The longest text the field takes, and the largest clipboard a paste
  // reads. A paste that would go past either is dropped whole.
  property int maxChars: Typing.SEARCH_MAX_CHARS
  property int pasteBytes: Typing.SEARCH_PASTE_BYTES
  readonly property bool pasting: paster.running

  readonly property string pasteHelper: decodeURIComponent(
    String(Qt.resolvedUrl("../../bin/omarchy-audible-paste")).replace(/^file:\/\//, ""))

  property bool _blink: true

  // Never false: see above.
  readOnly: true
  maximumLength: maxChars
  selectByMouse: true
  // A read-only field draws no cursor of its own.
  cursorVisible: activeFocus
  cursorDelegate: Rectangle {
    width: Math.max(1, Style.spacing.hairline)
    color: root.color
    visible: root.activeFocus && root._blink
  }

  onCursorPositionChanged: _blink = true

  // Handles an editing key from the view's `Keys.onPressed`: true when it
  // did (the view then accepts the event), false to leave it to Qt.
  function editKey(event) {
    var action = Typing.keyAction(event.key, event.modifiers, event.text)
    if (action === Typing.ACTION_PASS) return false
    if (action === Typing.ACTION_SELECT_ALL) selectAll()
    else if (action === Typing.ACTION_PASTE) pasteClipboard()
    else if (action === Typing.ACTION_CUT) {
      // Like Qt, a password field never puts its text on the clipboard.
      if (echoMode === TextInput.Normal) {
        copy()
        edit(action, "")
      }
    }
    else edit(action, event.text)
    return true
  }

  // Applies one edit at the selection or cursor; false when nothing changed.
  function edit(action, value) {
    var next = Typing.apply({ "text": text, "start": selectionStart, "end": selectionEnd }, action, value, maxChars)
    if (next === null) return false
    text = next.text
    cursorPosition = next.cursor
    return true
  }

  // Pastes the clipboard at the selection or cursor through the bounded
  // helper. One paste at a time; false when one is already running.
  function pasteClipboard() {
    if (paster.running) return false
    paster.command = Typing.pasteCommand(pasteHelper, pasteBytes)
    paster.running = true
    watchdog.restart()
    return true
  }

  Timer {
    interval: 530
    repeat: true
    running: root.activeFocus
    onRunningChanged: root._blink = true
    onTriggered: root._blink = !root._blink
  }

  // The helper keeps its own deadline; this stops it should it ever not.
  Timer {
    id: watchdog
    interval: Typing.PASTE_TIMEOUT_S * 1000 + Typing.PASTE_GRACE_MS
    onTriggered: if (paster.running) paster.running = false
  }

  Process {
    id: paster
    // The helper writes one line, and only after a complete, bounded read.
    // The text goes straight into the field; nothing here keeps it.
    stdout: SplitParser {
      onRead: function(line) {
        var value = Typing.pasteResult(line)
        if (value !== null) root.edit(Typing.ACTION_PASTE, value)
      }
    }
    onExited: watchdog.stop()
  }
}

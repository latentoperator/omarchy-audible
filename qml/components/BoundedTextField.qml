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
  readonly property bool pasting: _pasteActive
  property string pasteError: ""
  property bool _pasteActive: false
  property bool _replacePaste: false
  property var _pasteValue: null
  property bool _pasteInvalid: false
  property bool _pasteTimedOut: false
  property int _pasteExitCode: 0
  property int _pasteExitStatus: 0

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
    if (next === null) {
      if ((action === Typing.ACTION_INSERT || action === Typing.ACTION_PASTE) && Typing.clean(value).length > 0)
        pasteError = "Text is too large for this field. Copy a shorter selection and retry."
      return false
    }
    pasteError = ""
    text = next.text
    cursorPosition = next.cursor
    return true
  }

  // The button may replace the field; keyboard paste keeps its selection.
  // Neither changes the text until the bounded helper finishes successfully.
  function pasteClipboard(replaceAll) {
    if (pasting) return false
    pasteError = ""
    _pasteValue = null
    _pasteInvalid = false
    _pasteTimedOut = false
    _replacePaste = replaceAll === true
    _pasteActive = true
    paster.command = Typing.pasteCommand(pasteHelper, pasteBytes)
    paster.running = true
    watchdog.restart()
    return true
  }

  function finishPaste() {
    if (!_pasteActive) return
    var value = _pasteValue
    _pasteValue = null
    _pasteActive = false
    if (_pasteTimedOut || _pasteExitCode === 4) {
      pasteError = "Clipboard read timed out. Copy the text again and retry."
    } else if (_pasteExitCode === 3) {
      pasteError = "Clipboard text is too large. Copy a shorter selection and retry."
    } else if (_pasteExitCode !== 0 || _pasteExitStatus !== 0 || _pasteInvalid || value === null || Typing.clean(value).length === 0) {
      pasteError = "Clipboard text is unavailable. Copy the text again and retry."
    } else {
      var next = Typing.apply({ "text": text,
        "start": _replacePaste ? 0 : selectionStart,
        "end": _replacePaste ? text.length : selectionEnd }, Typing.ACTION_PASTE, value, maxChars)
      if (next === null) {
        pasteError = "Text is too large for this field. Copy a shorter selection and retry."
      } else {
        pasteError = ""
        text = next.text
        cursorPosition = next.cursor
      }
    }
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
    onTriggered: if (root._pasteActive) {
      root._pasteValue = null
      root._pasteTimedOut = true
      root.pasteError = "Clipboard read timed out. Copy the text again and retry."
      drain.stop()
      paster.running = false
    }
  }

  Process {
    id: paster
    // FailedToStart has runningChanged but no exited signal in Quickshell.
    onRunningChanged: if (!running) Qt.callLater(function() {
      if (root._pasteActive && !root._pasteTimedOut && !paster.running && !drain.running) {
        root._pasteExitCode = 2
        root._pasteExitStatus = 0
        root.finishPaste()
      }
    })
    // One bounded line, held only until exit/stdout draining has completed.
    stdout: SplitParser {
      onRead: function(line) {
        if (!root._pasteActive || root._pasteTimedOut) return
        var value = Typing.pasteResult(line)
        if (root._pasteInvalid || root._pasteValue !== null || value === null) {
          root._pasteInvalid = true
          root._pasteValue = null
        } else root._pasteValue = value
      }
    }
    onExited: function(code, status) {
      watchdog.stop()
      if (!root._pasteActive) return
      root._pasteExitCode = code
      root._pasteExitStatus = status
      if (root._pasteTimedOut) root.finishPaste()
      else drain.restart()
    }
  }

  // As BackendCall: the last stdout signal may follow the exit signal.
  Timer {
    id: drain
    interval: 60
    onTriggered: root.finishPaste()
  }
}

"""G3 finding 3, laptop half: row icons and ask-before-download (PR #44's wiring).

The decisions live in ``LibraryUi.js`` (tested in ``test_library_ui.py``);
these check the QML wiring, which the JS tests can't reach. QML wiring is
grep-checked here and run live, per the repo's convention.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def function_body(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    depth = 0
    for i in range(source.index("{", start), len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
    raise AssertionError(f"unterminated {name}")


# ---- Service.pick ----

def test_pick_decides_before_note_intent():
    # noteIntent clears confirmAsin, so the decision must be captured first,
    # or a second pick would ask again instead of downloading (PR #44).
    body = function_body(read("Service.qml"), "pick")
    decide = body.index("LibraryUi.pickDecision(row, syncFailure.offline, confirmAsin)")
    assert decide < body.index("noteIntent(asin)")
    assert "LibraryUi.primaryAction" not in body


def test_pick_acts_on_the_decision():
    body = function_body(read("Service.qml"), "pick")
    assert "LibraryUi.PICK_CONFIRM" in body
    assert "confirmAsin = asin" in body
    assert 'return "confirm"' in body
    assert "LibraryUi.PICK_DOWNLOAD || decision === LibraryUi.PICK_RETRY" in body
    assert 'run("get", [asin], "autoplay")' in body
    assert "LibraryUi.PICK_PLAY" in body
    assert "playPicked(asin, true)" in body


def test_other_intents_clear_the_question():
    service = read("Service.qml")
    assert 'confirmAsin = ""' in function_body(service, "noteIntent")
    assert 'confirmAsin = ""' in function_body(service, "libraryOpened")
    assert 'confirmAsin = ""' in function_body(service, "cancelConfirm")
    assert "return pick(confirmAsin)" in function_body(service, "confirmDownload")


def test_question_goes_away_when_no_longer_valid():
    # The book got downloaded another way, vanished, or the laptop went offline.
    service = read("Service.qml")
    assert ("readonly property bool confirmStillValid: "
            "LibraryUi.confirmValid(confirmAsin, library.rowFor(confirmAsin), syncFailure.offline)") in service
    # Cleared later, after a fresh check, never from inside the change that
    # its own binding reads (Codex R1 #2: binding-loop warnings).
    assert "onConfirmStillValidChanged: if (!confirmStillValid) Qt.callLater(dropInvalidConfirm)" in service
    body = function_body(service, "dropInvalidConfirm")
    assert "LibraryUi.confirmValid(confirmAsin, library.rowFor(confirmAsin), syncFailure.offline)" in body
    assert 'confirmAsin = ""' in body


def test_ipc_exposes_the_question():
    service = read("Service.qml")
    ipc = service[service.index("IpcHandler {"):]
    assert '"confirm": root.confirmAsin' in ipc
    assert "return root.confirmDownload()" in ipc
    assert "return root.cancelConfirm()" in ipc


# ---- BookRow / LibraryView ----

def test_row_shows_the_action_icon():
    row = read("qml/components/BookRow.qml")
    assert "property string iconGlyph" in row
    assert "property string iconTooltip" in row
    assert "iconText: root.iconGlyph" in row
    library = read("qml/views/LibraryView.qml")
    assert "LibraryUi.rowIcon(modelData, root.offline)" in library


def test_row_shows_the_question_with_buttons():
    row = read("qml/components/BookRow.qml")
    assert "property bool confirming" in row
    assert "signal confirmRequested()" in row
    assert "signal cancelRequested()" in row
    assert 'text: "Download"' in row
    assert 'text: "Cancel"' in row
    library = read("qml/views/LibraryView.qml")
    assert "confirming: root.service ? root.service.confirmAsin === modelData.asin : false" in library
    assert "onConfirmRequested: root.service.confirmDownload()" in library
    assert "onCancelRequested: root.service.cancelConfirm()" in library


def test_question_size_is_guarded():
    library = read("qml/views/LibraryView.qml")
    body = function_body(library, "questionText")
    assert "LibraryUi.estimatedBytes(row)" in body
    assert 'Drawer.downloadQuestion(bytes > 0 ? Format.bytes(bytes) : "")' in body


def test_esc_cancels_the_question_before_closing():
    library = read("qml/views/LibraryView.qml")
    keys = library[library.index("Keys.onPressed"):]
    keys = keys[:keys.index("event.accepted = true")]
    close = keys.index("Drawer.KEY_CLOSE")
    cancel = keys.index("root.service.cancelConfirm()")
    assert close < cancel < keys.index("root.closeRequested()")


def test_space_in_library_goes_through_play_pause():
    # Missed in #41: the search field's toggle skipped the catch-up read.
    library = read("qml/views/LibraryView.qml")
    assert "player.toggle()" not in library
    assert "root.service.playPause()" in library


def test_the_question_scrolls_into_view():
    # Codex R1 #1: a row at the bottom grows past the clipped list; Enter
    # again must never confirm a question the user can't fully see.
    library = read("qml/views/LibraryView.qml")
    assert "onHeightChanged: if (revealQuestion && confirming) books.positionViewAtIndex(index, ListView.Contain)" in library
    # Codex R2: only a question just opened scrolls; a delegate recreated with
    # `confirming` already true starts with revealQuestion false.
    assert "property bool revealQuestion: false" in library
    assert "onConfirmingChanged: revealQuestion = confirming" in library

"""G3 findings 1, 2, 5 and 6: wiring checks on the QML that the JS tests can't reach.

1. A fake-mode mpv must not block the real one: each mode has its own scope
   unit, and real mode stops a leftover fake one.
2. A play that fails must say so (a desktop notification and a Mini line).
5. Every ⏯ goes through ``Service.playPause`` so it can catch up first.
6. Author names use the drawer's text color, not ``Color.muted``.
"""

from __future__ import annotations

import re
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
                return source[start : i + 1]
    raise AssertionError(f"unterminated {name}")


# ---- 1: one scope unit per mode ----


def test_player_unit_name_is_a_property():
    player = read("qml/PlayerController.qml")
    assert 'property string unitName: "omarchy-audible-mpv"' in player
    assert '"--unit=" + unitName' in player
    assert 'root.unitName + ".scope"' in player
    assert '"omarchy-audible-mpv.scope"' not in player
    assert '"--unit=omarchy-audible-mpv"' not in player


def test_service_picks_the_unit_by_mode():
    service = read("Service.qml")
    assert (
        'unitName: root.fake ? "omarchy-audible-fake-mpv" : "omarchy-audible-mpv"'
        in service
    )


def test_real_mode_stops_a_leftover_fake_player():
    service = read("Service.qml")
    assert (
        '["systemctl", "--user", "stop", "omarchy-audible-fake-mpv.scope"]' in service
    )
    body = function_body(service, "stopOtherModePlayer")
    assert "if (root.fake) return" in body


# ---- 2: a failed play is visible ----


def test_failed_play_notifies():
    service = read("Service.qml")
    assert "function onConnectionChanged()" in service
    body = function_body(service, "notifyPlayFailed")
    assert '"notify-send"' in body
    assert "Couldn't start playback" in body


def test_mini_shows_the_player_error():
    # B11: the line covers a failed play-info too, through the service's
    # playFailure (Player.playFailure), which still includes the player's own.
    mini = read("qml/views/MiniView.qml")
    assert "root.service.playFailure" in mini
    service = read("Service.qml")
    assert (
        "Player.playFailure(player.connection, player.lastError, playError)" in service
    )
    # The line goes away once a book plays again, not only on the next play attempt.
    assert 'root.playError = ""' in function_body(service, "onPlayingChanged")


# ---- 5: every play/pause goes through the service ----


def test_no_view_toggles_the_player_directly():
    # Every view, so no ⏯ skips the catch-up (the Library's search Space and
    # now-playing strip were missed in #41).
    for path in sorted((REPO / "qml").rglob("*.qml")) + [REPO / "BarWidget.qml"]:
        assert "player.toggle()" not in path.read_text(encoding="utf-8"), path


def test_play_pause_entry_points_use_the_service():
    bar = read("BarWidget.qml")
    assert bar.count("service.playPause()") == 2  # Space and middle-click
    # Mini's ⏯ is in the shared transport row (U5).
    assert "root.service.playPause()" in read("qml/components/TransportRow.qml")
    assert "TransportRow {" in read("qml/views/MiniView.qml")
    ipc = read("qml/ServiceIpc.qml")
    assert "return service.playPause()" in function_body(ipc, "playPause")


def test_resume_reads_only_after_a_long_pause():
    # P9 PR 5: the catch-up flow lives in qml/CatchupFlow.qml; ⏯ asks it.
    service = read("Service.qml")
    flow = read("qml/CatchupFlow.qml")
    assert "function playPause() { return catchupFlow.press() }" in service
    body = function_body(flow, "press")
    assert "Catchup.needsRead(pausedAtMs, Date.now())" in body
    assert "Catchup.prefetchUsable(prefetched, asin, Date.now())" in body
    assert 'service.run("position-get", [asin], "catchup")' in flow
    # A pause records when it happened.
    assert "pausedAtMs = Date.now()" in function_body(flow, "notePaused")
    assert "catchupFlow.notePaused()" in function_body(service, "onPlayingChanged")


def test_catch_up_falls_back_after_the_timeout():
    flow = read("qml/CatchupFlow.qml")
    assert "interval: Catchup.READ_TIMEOUT_MS" in flow
    assert "onTriggered: root.resumeCaughtUp(root.catchupAsin, null)" in flow
    body = function_body(flow, "resumeCaughtUp")
    assert "Catchup.jumpTarget(" in body
    assert "player.jumpToMs(target)" in body
    assert "player.resume()" in body
    # A switch to another book while reading must not resume the old one.
    assert '"sameBook": service.loadedAsin === asin' in body


def test_a_new_pick_cancels_catch_up():
    # Codex R1 #1: a Library pick (or IPC play) wins over a waiting ⏯.
    service = read("Service.qml")
    flow = read("qml/CatchupFlow.qml")
    assert "catchupFlow.noteIntent()" in function_body(service, "noteIntent")
    assert "cancelCatchup()" in function_body(flow, "noteIntent")
    assert "catchupTimer.stop()" in function_body(flow, "cancelCatchup")
    # ⏯ while a pick is still reading its position leaves that pick alone.
    press = function_body(flow, "press")
    assert "Catchup.PRESS_BUSY" in press
    assert '"pendingResume": service.pendingResume.length > 0' in press


def test_catch_up_needs_loaded_local_state():
    # Codex R1 #3: an unread state.json is not "nothing saved here".
    body = function_body(read("qml/CatchupFlow.qml"), "resumeCaughtUp")
    assert '"storeLoaded": store.loaded' in body
    assert "sync.lastPushed[asin]" in body


def test_library_shows_the_player_error():
    # Codex R1 #4: a failed pick reopens on Library, not Mini.
    library = read("qml/views/LibraryView.qml")
    assert "root.service.playFailure" in library
    assert "Couldn't start playback: " in library


def test_overlapping_reads_keep_their_own_results():
    # Codex R3: a failed read of book A must not clear book B's result. Since
    # P9 PR 5 the finish bookkeeping is `Catchup.finishRead`, whose vectors
    # (test_catchup_js.py, A fails while B is prefetched) replace the greps for
    # `delete root.catchupResults[readAsin]` and the same-book clear; this
    # checks the wiring applies it.
    flow = read("qml/CatchupFlow.qml")
    assert "results[read] = {" in function_body(flow, "handleEvent")
    finished = function_body(flow, "handleFinished")
    assert "Catchup.finishRead(" in finished
    for line in (
        "catchupReads = next.reads",
        "catchupResults = next.results",
        "prefetched = next.prefetched",
        "if (next.resume) resumeCaughtUp(readAsin, next.remote)",
    ):
        assert line in finished, line
    assert "prefetched = null" not in finished


def test_one_read_per_book():
    # Codex R4: two reads of the same book (A -> B -> A) must not overlap.
    flow = read("qml/CatchupFlow.qml")
    assert "catchupReading" not in flow
    assert '"reading": catchupReads[asin] === true' in function_body(flow, "press")
    assert "catchupReads[service.loadedAsin] === true" in function_body(
        flow, "prefetchCatchup"
    )
    assert "reads[asin] = true" in function_body(flow, "readCatchup")
    # The finished read is dropped by `Catchup.finishRead` (its vectors).
    assert "catchupReads = next.reads" in function_body(flow, "handleFinished")


def test_opening_the_drawer_prefetches():
    service = read("Service.qml")
    assert "catchupFlow.prefetchCatchup()" in function_body(service, "viewForOpen")


# ---- 6: author names readable ----


def test_author_names_are_not_muted():
    for rel in ("qml/components/BookRow.qml", "qml/views/MiniView.qml"):
        source = read(rel)
        block = source[: source.index("Format.names(")]
        block = source[block.rindex("Text {") - len("Soft") :]
        block = block[: block.index("}")]
        assert "Color.muted" not in block, rel
        # F26: the names are SoftText, which holds the 75% popup-text colour.
        assert block.startswith("SoftText {"), rel
        assert "color:" not in block, rel
    soft = read("qml/components/SoftText.qml")
    assert re.search(
        r"Qt\.rgba\(Color\.popups\.text\.r, Color\.popups\.text\.g, Color\.popups\.text\.b, 0\.75\)",
        soft,
    )


# ---- the note after a catch-up jump ----


def test_jump_sets_a_short_note():
    service = read("Service.qml")
    flow = read("qml/CatchupFlow.qml")
    body = function_body(flow, "resumeCaughtUp")
    assert "showCatchupNote(Format.clock(player.positionMs))" in body
    assert body.index("showCatchupNote(") < body.index("player.jumpToMs(target)")
    note = function_body(flow, "showCatchupNote")
    assert "catchupNote = Catchup.jumpNote(was)" in note
    assert "catchupNoteTimer.restart()" in note
    assert "interval: Catchup.NOTE_MS" in flow
    # A new pick or a pause drops the note.
    assert 'catchupNote = ""' in function_body(flow, "noteIntent")
    assert "catchupFlow.noteIntent()" in function_body(service, "noteIntent")
    assert '"catchupNote": root.catchupNote' in service
    assert "readonly property string catchupNote: catchupFlow.catchupNote" in service


def test_mini_shows_the_note():
    mini = read("qml/views/MiniView.qml")
    assert "root.service.catchupNote" in mini

"""F38 — a seek, skip or chapter jump made while paused is saved and pushed.

The decisions are ``Playback.positionCounts`` and ``Playback.moveSentAfter``; the rest checks the wiring in the
QML objects, which the QJSEngine tests can't load.
"""

from __future__ import annotations

import json
import pathlib

import pytest

import qjs

REPO = pathlib.Path(__file__).resolve().parent.parent


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
    raise AssertionError(name)


@pytest.fixture(scope="module")
def playback() -> qjs.JsModule:
    return qjs.load("Playback")


@pytest.mark.parametrize(
    "playing,move_sent,counts",
    [
        # The report after a user's move counts paused or playing (the old code
        # dropped it while paused).
        (False, True, True),
        (True, True, True),
        # A plain report counts only while playing: a reattach after a shell
        # restart reports a position while paused, and that is not listening.
        (True, False, True),
        (False, False, False),
        ("yes", None, False),
    ],
)
def test_position_counts(playback, playing, move_sent, counts):
    assert playback.call("positionCounts", playing, move_sent) is counts


@pytest.mark.parametrize(
    "before,event,after",
    [
        (False, "user", True),
        (True, "user", True),
        (True, "report", False),
        (True, "switch", False),
        (False, "report", False),
        (True, "other", True),
        (False, None, False),
        ("yes", None, False),
    ],
)
def test_move_sent_after(playback, before, event, after):
    assert playback.call("moveSentAfter", before, event) is after


# Service's handlers, replayed in the lib: `user` is onUserMoved for the
# loaded book, `report_*` is onPositionMsChanged and `switch` is
# onBookSwitched. Stop, a switch and Component.onDestruction save only when
# the result is dirty.
REPLAY = """
(function(steps) {
  var moveSent = false, dirty = false;
  for (var i = 0; i < steps.length; i++) {
    var step = steps[i];
    if (step === "user") moveSent = moveSentAfter(moveSent, "user");
    else if (step === "switch") { dirty = false; moveSent = moveSentAfter(moveSent, "switch"); }
    else {
      var playing = step === "report_playing";
      if (positionCounts(playing, moveSent)) dirty = true;
      moveSent = moveSentAfter(moveSent, "report");
    }
  }
  return dirty;
})
"""


@pytest.mark.parametrize(
    "steps,dirty",
    [
        # Pause, ⏩, its position arrives: saved at Stop, switch or restart.
        (["user", "report_paused"], True),
        # Codex P1: a restart (or quit) before the position arrives saves
        # nothing, rather than the old position with a new listening time.
        (["user"], False),
        # Codex P2: a skip sent while another book loads is dropped by the
        # switch; the new book's first report while paused isn't listening.
        (["user", "switch", "report_paused"], False),
        # A reattach reports a position while paused: not listening.
        (["switch", "report_paused"], False),
        # One move counts once: a later paused report doesn't count again.
        (["user", "report_paused", "switch", "report_paused"], False),
        # Playing always counts.
        (["report_playing"], True),
    ],
)
def test_handlers_in_order(playback, steps, dirty):
    assert playback.evaluate(REPLAY + "(" + json.dumps(steps) + ")") is dirty


def test_user_moves_say_so_and_the_catchup_jump_does_not():
    player = read("qml/PlayerController.qml")
    assert "signal userMoved()" in player
    for name in ("skip", "seekMs", "setChapter"):
        assert "userMoved()" in function_body(player, name), name
    # Chapter ⏮/⏭ go through setChapter.
    assert "setChapter(target)" in function_body(player, "jumpChapter")
    assert "userMoved" not in function_body(player, "jumpToMs")
    # The catch-up jump is not the user's move.
    resume = function_body(read("Service.qml"), "resumeCaughtUp")
    assert "player.jumpToMs(target)" in resume
    assert "player.seekMs(" not in resume


def test_the_service_marks_a_move_through_the_lib():
    service = read("Service.qml")
    position = function_body(service, "onPositionMsChanged")
    assert "Playback.positionCounts(player.playing, root.moveSent)" in position
    assert "root.markMoved()" in position
    assert 'root.moveSent = Playback.moveSentAfter(root.moveSent, "report")' in position
    # The move counts when its position arrives, not when it is sent.
    moved = function_body(service, "onUserMoved")
    assert 'root.moveSent = Playback.moveSentAfter(root.moveSent, "user")' in moved
    assert "markMoved" not in moved
    # Only a move of the book the snapshot belongs to.
    assert "Playback.asinFromPath(player.path) === root.snapAsin" in moved
    assert 'moveSent = Playback.moveSentAfter(moveSent, "switch")' in function_body(
        service, "onBookSwitched"
    )
    mark = function_body(service, "markMoved")
    assert "snapDirty = true" in mark and "snapUnpushed = true" in mark
    # Nothing else in the service sets the marks.
    assert service.count("snapDirty = true") == 1
    assert service.count("snapUnpushed = true") == 1
    assert service.count("root.markMoved()") == 1

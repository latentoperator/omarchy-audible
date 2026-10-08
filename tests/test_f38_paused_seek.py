"""F38 — a seek, skip or chapter jump made while paused is saved and pushed.

The decision is ``Playback.positionCounts``; the rest checks the wiring in the
QML objects, which the QJSEngine tests can't load.
"""

from __future__ import annotations

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
    "cause,playing,counts",
    [
        # The user's move counts paused or playing (the old code dropped it
        # while paused).
        ("user", False, True),
        ("user", True, True),
        # A reported position counts only while playing: a reattach after a
        # shell restart reports one while paused, and that is not listening.
        ("report", True, True),
        ("report", False, False),
        # Anything else counts for nothing.
        ("other", True, False),
        (None, True, False),
        ("report", "yes", False),
    ],
)
def test_position_counts(playback, cause, playing, counts):
    assert playback.call("positionCounts", cause, playing) is counts


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
    assert 'Playback.positionCounts("report", player.playing)' in position
    assert "root.markMoved()" in position
    moved = function_body(service, "onUserMoved")
    assert 'Playback.positionCounts("user", player.playing)' in moved
    # Only a move of the book the snapshot belongs to.
    assert "Playback.asinFromPath(player.path) === root.snapAsin" in moved
    assert "root.markMoved()" in moved
    mark = function_body(service, "markMoved")
    assert "snapDirty = true" in mark and "snapUnpushed = true" in mark
    # Nothing else in the service sets the marks.
    assert service.count("snapDirty = true") == 1
    assert service.count("snapUnpushed = true") == 1

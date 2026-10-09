"""F38 — a seek, skip or chapter jump made while paused is saved and pushed.

The decisions are ``Playback.positionCounts`` and ``Mpv.moveTargetMs``; the rest checks the wiring in the
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


@pytest.fixture(scope="module")
def mpv() -> qjs.JsModule:
    return qjs.load("Mpv")


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


CHAPTERS = [
    {"title": "1", "startMs": 0},
    {"title": "2", "startMs": 2500},
    {"title": "3"},
]


@pytest.mark.parametrize(
    "kind,value,position,duration,target",
    [
        ("skip", 30, 1000, 600000, 31000),
        ("skip", -10, 30000, 600000, 20000),
        # mpv clamps: before the start is 0; --keep-open stops at the end.
        ("skip", -30, 1000, 600000, 0),
        ("skip", 30, 3647, 6000, 6000),
        ("skip", 0.5, 1000, 6000, 1500),
        ("seek", 4321.4, 0, 6000, 4321),
        ("seek", -5, 0, 6000, 0),
        ("seek", 9000, 0, 6000, 6000),
        ("chapter", 1, 0, 6000, 2500),
        ("chapter", 0, 4000, 6000, 0),
        # Unknown: no such chapter, a chapter with no start, no duration, bad values.
        ("chapter", 3, 0, 6000, -1),
        ("chapter", 2, 0, 6000, -1),
        ("chapter", -1, 0, 6000, -1),
        ("skip", 30, 1000, 0, -1),
        ("skip", None, 1000, 6000, -1),
        ("skip", 30, None, 6000, -1),
        ("seek", "x", 0, 6000, -1),
        ("jump", 1, 0, 6000, -1),
    ],
)
def test_move_target(mpv, kind, value, position, duration, target):
    assert mpv.call("moveTargetMs", kind, value, position, duration, CHAPTERS) == target


A = "/d/books/B0A/book.aaxc"
B = "/d/books/B0B/book.aaxc"
C = "/d/books/B0C/book.aaxc"


@pytest.mark.parametrize(
    "path,load_path,arrived,hits",
    [
        # Nothing sent since connecting (a reattach): the book showing moves.
        (A, "", True, True),
        ("", "", True, True),
        # The last load has arrived.
        (B, B, True, True),
        # Codex round 3: B was sent while A still shows; the move lands on B.
        (A, B, False, False),
        # Codex round 4: C overtook B before B opened; B shows (and said
        # file-loaded), but the move lands on C.
        (B, C, True, False),
        # Codex round 5: Start over sends A again while A shows; until the
        # fresh A says file-loaded, the move lands on it, not where A was.
        (A, A, False, False),
        ("", B, True, False),
        (None, B, True, False),
        (B, B, "yes", False),
        (A, None, False, True),
    ],
)
def test_move_hits_path(mpv, path, load_path, arrived, hits):
    assert mpv.call("moveHitsPath", path, load_path, arrived) is hits


def test_a_move_during_a_load_is_not_the_showing_books():
    player = read("qml/PlayerController.qml")
    flush = function_body(player, "flushPending")
    assert "loadPath = load.path" in flush and "loadArrived = false" in flush
    assert "loadArrived = true" in function_body(player, "handleLine")
    # A gone mpv has no load on its way: the one place that resets mpvState
    # forgets it too. P9 PR 9: that is the handler of PlayerMachine's
    # reset_state effect, which both the disconnect and a give-up emit (the
    # two places before; test_player_machine's vectors, and as behaviour
    # test_player_qml's unexpected-exit and load-write tests).
    reset = player[
        player.index('type === "reset_state"') : player.index('type === "forget_sleep"')
    ]
    assert "mpvState = Mpv.emptyState()" in reset
    assert 'loadPath = ""' in reset and "loadArrived = true" in reset
    assert player.count('loadPath = ""') == 1
    assert player.count("mpvState = Mpv.emptyState()") == 1
    assert player.count("loadPath = ") == 2
    assert player.count("loadArrived = true") == 2
    assert player.count("loadArrived = false") == 1


def test_user_moves_say_so_and_the_catchup_jump_does_not():
    player = read("qml/PlayerController.qml")
    assert "signal userMoved(int targetMs)" in player
    for name, kind in (("skip", "skip"), ("seekMs", "seek"), ("setChapter", "chapter")):
        body = function_body(player, name)
        assert f'Mpv.moveTargetMs("{kind}", ' in body, name
        # Only a move that was sent says so, and only for the file showing.
        assert (
            ") && Mpv.moveHitsPath(path, loadPath, loadArrived)) userMoved(target)"
            in body
        ), name
    # Chapter ⏮/⏭ go through setChapter.
    assert "setChapter(target)" in function_body(player, "jumpChapter")
    assert "userMoved" not in function_body(player, "jumpToMs")
    # The catch-up jump is not the user's move.
    resume = function_body(read("qml/CatchupFlow.qml"), "resumeCaughtUp")
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
    assert "Playback.asinFromPath(player.path) !== root.snapAsin" in moved
    # Where the move lands is kept at once, so a quit or restart before mpv
    # reports it saves the move, not the old position (Codex rounds 1 and 2).
    assert "if (targetMs >= 0) root.snapMs = targetMs" in moved
    assert moved.index("root.snapMs = targetMs") < moved.index("root.markMoved()")
    mark = function_body(service, "markMoved")
    assert "snapDirty = true" in mark and "snapUnpushed = true" in mark
    # Nothing else in the service sets the marks.
    assert service.count("snapDirty = true") == 1
    assert service.count("snapUnpushed = true") == 1

"""F39 — a position mpv reports for the next book never lands in the old book's snapshot.

The decision is ``Playback.reportBelongs``, fed by F38's ``Mpv.moveHitsPath``. The replays below drive
it with both orders mpv could send in a switch from A to B; the rest checks the wiring in the QML,
which the QJSEngine tests can't load.
"""

from __future__ import annotations

import pathlib

import pytest

import qjs

REPO = pathlib.Path(__file__).resolve().parent.parent

A = "/d/books/B0A/book.aaxc"
B = "/d/books/B0B/book.aaxc"


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
    "has_position,report_asin,snap_asin,settled,belongs",
    [
        (True, "B0A", "B0A", True, True),
        # A file being swapped reports a null time-pos.
        (False, "B0A", "B0A", True, False),
        # Another book's position, or no book.
        (True, "B0B", "B0A", True, False),
        (True, "", "", True, False),
        # A load is on its way: whatever mpv reports isn't the snapshot's yet.
        (True, "B0A", "B0A", False, False),
        # Bad values count for nothing.
        (True, None, None, True, False),
        ("yes", "B0A", "B0A", True, False),
        (True, "B0A", "B0A", "yes", False),
    ],
)
def test_report_belongs(
    playback, has_position, report_asin, snap_asin, settled, belongs
):
    assert (
        playback.call("reportBelongs", has_position, report_asin, snap_asin, settled)
        is belongs
    )


class Replay:
    """The snapshot half of Service and the load tracking of PlayerController, driven by
    socket events in order, with the decisions taken by the real libs."""

    def __init__(
        self, playback: qjs.JsModule, mpv: qjs.JsModule, gate: bool = True
    ) -> None:
        self.playback, self.mpv, self.gate = playback, mpv, gate
        self.state = mpv.call("emptyState")
        self.load_path, self.load_arrived = "", True
        self.snap_asin, self.snap_ms = "", 0
        self.saved: dict[str, int] = {}

    def loadfile(self, path: str) -> None:
        self.load_path, self.load_arrived = path, False

    def file_loaded(self) -> None:
        self.load_arrived = True

    def prop(self, name: str, data) -> None:
        self.state = self.mpv.call("applyProperty", self.state, name, data)
        derived = self.mpv.call("derive", self.state)
        if name == "path":
            # Service.onBookSwitched: the old book is saved where it stopped.
            asin = self.playback.call("asinFromPath", derived["path"])
            if self.snap_asin and self.snap_asin != asin:
                self.saved[self.snap_asin] = self.snap_ms
            previous, self.snap_asin = self.snap_asin, asin
            if previous:
                self.snap_ms = 0
        elif name == "time-pos":
            settled = self.mpv.call(
                "moveHitsPath", derived["path"], self.load_path, self.load_arrived
            )
            asin = self.playback.call("asinFromPath", derived["path"])
            if self.playback.call(
                "reportBelongs",
                derived["hasPosition"],
                asin,
                self.snap_asin,
                settled if self.gate else True,
            ):
                self.snap_ms = derived["positionMs"]


def playing_a(replay: Replay, at_s: float) -> None:
    replay.loadfile(A)
    replay.prop("path", A)
    replay.file_loaded()
    replay.prop("pause", False)
    replay.prop("time-pos", at_s)


def observed_order(replay: Replay) -> None:
    # mpv 0.41 on the desktop, all 25 recorded loads (STATE F39): the old file's
    # time-pos and path go null before B's path, and B's time-pos follows file-loaded.
    replay.loadfile(B)
    replay.prop("time-pos", None)
    replay.prop("path", None)
    replay.prop("path", B)
    replay.file_loaded()
    replay.prop("time-pos", 300.0)


def early_report_order(replay: Replay) -> None:
    # The order F39 guards against: B's time-pos (observe id 1) before B's path (id 7).
    replay.loadfile(B)
    replay.prop("time-pos", 300.0)
    replay.prop("path", B)
    replay.file_loaded()
    replay.prop("time-pos", 300.5)


@pytest.mark.parametrize("order", [observed_order, early_report_order])
def test_a_switch_saves_a_where_a_stopped(playback, mpv, order):
    replay = Replay(playback, mpv)
    playing_a(replay, 42.0)
    order(replay)
    assert replay.saved == {"B0A": 42000}
    # B's own reports count once B has arrived.
    assert replay.snap_asin == "B0B"
    assert replay.snap_ms in (300000, 300500)


def test_the_old_check_saved_b_as_a_in_the_early_order(playback, mpv):
    replay = Replay(playback, mpv, gate=False)
    playing_a(replay, 42.0)
    early_report_order(replay)
    assert replay.saved == {"B0A": 300000}


@pytest.mark.parametrize("order", [observed_order, early_report_order])
def test_a_paused_move_survives_a_switch(playback, mpv, order):
    replay = Replay(playback, mpv)
    playing_a(replay, 42.0)
    replay.prop("pause", True)
    # Service.onUserMoved keeps where an F38 move lands; mpv then reports it.
    replay.snap_ms = 72000
    replay.prop("time-pos", 72.0)
    order(replay)
    assert replay.saved == {"B0A": 72000}


def test_a_reattach_reports_count(playback, mpv):
    # After a shell restart nothing has been sent ("", Mpv.moveHitsPath), so the
    # book showing reports for itself.
    replay = Replay(playback, mpv)
    replay.prop("time-pos", 10.0)
    replay.prop("path", A)
    replay.prop("time-pos", 11.0)
    assert (replay.snap_asin, replay.snap_ms) == ("B0A", 11000)


def test_start_over_does_not_keep_the_old_spot(playback, mpv):
    # Start over sends A again while A shows: until the fresh A says
    # file-loaded, a report is the old spot, not a new listening position.
    replay = Replay(playback, mpv)
    playing_a(replay, 42.0)
    replay.loadfile(A)
    replay.prop("time-pos", 43.0)
    assert replay.snap_ms == 42000
    replay.file_loaded()
    replay.prop("time-pos", 0.0)
    assert replay.snap_ms == 0


def test_the_service_gates_reports_on_the_load():
    position = function_body(read("Service.qml"), "onPositionMsChanged")
    assert (
        "Playback.reportBelongs(player.derived.hasPosition, Playback.asinFromPath(player.path), root.snapAsin,"
        in position
    )
    assert (
        "Mpv.moveHitsPath(player.path, player.loadPath, player.loadArrived)" in position
    )
    # The gate comes before anything takes the position.
    assert position.index("Playback.reportBelongs(") < position.index(
        "root.snapMs = player.positionMs"
    )

"""P9 PR 9 — the real PlayerController.qml applying PlayerMachine's effects, headless.

``player_harness`` loads the controller with stub ``Quickshell`` (``execDetached``) and
``Quickshell.Io`` (``Process``, ``Socket``, ``SplitParser``). Each step returns every observable
field that changed (properties, timers, processes, the Socket) plus what was written to mpv,
launched and published as ``connection`` during it, so the wiring is checked end to end: drop an
effect's handler, reorder one, or publish at the wrong time, and a step here changes.

The expected steps were recorded from ``main``'s controller (before the machine) in the same
harness: this PR must not change any of them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from player_harness import REPO, SOCKET, UNIT, Harness

BOOK = "/books/B0FAKE0001/book.aaxc"
# Invented, in play-info's `lavf_options` shape.
KEY = "audible_key=00112233,audible_iv=44556677"
PLAY = {"path": BOOK, "start": 12, "key": KEY}

MPV = [
    "mpv",
    "--no-config",
    "--no-video",
    "--idle=yes",
    "--keep-open=yes",
    "--no-terminal",
    "--audio-display=no",
    "--force-window=no",
    "--volume=15",
    "--speed=1.25",
    f"--input-ipc-server={SOCKET}",
]
SCOPE = ["systemd-run", "--user", "--scope", "--quiet", "--collect", f"--unit={UNIT}"]
LAUNCH = (
    ["sh", "-c", 'mkdir -p "$1" && shift && exec "$@"', "sh", SOCKET.rsplit("/", 1)[0]]
    + SCOPE
    + MPV
)
LAUNCH_PLAIN = LAUNCH[: -len(SCOPE + MPV)] + MPV
OBSERVE = [
    ["observe_property", n, name]
    for n, name in enumerate(
        [
            "time-pos",
            "duration",
            "pause",
            "speed",
            "chapter",
            "chapter-list",
            "path",
            "idle-active",
            "eof-reached",
            "volume",
        ],
        start=1,
    )
]
CLEAR_KEY = ["set_property", "demuxer-lavf-o", ""]
LOAD = ["loadfile", BOOK, "replace", -1, {"demuxer-lavf-o": KEY, "start": "12"}]
UNPAUSE = ["set_property", "pause", False]

READY = [("scopeProbeExit", 0, {"scopeProbe": False}), ("socketPath", SOCKET, {})]
# play() while idle: launch, then the first connect.
PLAYED = {
    "result": True,
    "wanted": True,
    "pendingLoad": BOOK,
    "launching": True,
    "connection": "launching",
    "attempt": 1,
    "detached": [LAUNCH],
    "socket": True,
    "built": 1,
    "retry": 600,
    "published": ["launching"],
}
# mpv connects with a load waiting: subscribe, clear the key, then the load and unpause.
CONNECTED = {
    "connected": True,
    "connection": "connected",
    "attempt": 0,
    "launching": False,
    "retry": None,
    "pendingLoad": None,
    "loadPath": BOOK,
    "loadArrived": False,
    "writes": OBSERVE + [CLEAR_KEY, LOAD, UNPAUSE],
    "published": ["connected"],
}
PLAYING = READY + [("play", PLAY, PLAYED), ("up", None, CONNECTED)]


def retries(first: int, built: int) -> list:
    """Retry ticks that connect again, from attempt `first` up to the cap."""
    return [
        (
            "retry",
            None,
            {
                "attempt": n,
                "built": built + n - first,
                "retry": min(300 + 300 * n, 2000),
            },
        )
        for n in range(first, 7)
    ]


@pytest.fixture
def harness(tmp_path):
    h = Harness(tmp_path)
    yield h
    h.close()


def run(harness: Harness, steps: list) -> None:
    for number, (name, arg, changes) in enumerate(steps, start=1):
        assert harness.step(name, arg) == changes, f"step {number}: {name}"


def connected_loops(harness: Harness) -> list[str]:
    return [
        w
        for w in harness.warnings
        if 'Binding loop detected for property "connected"' in w
    ]


def test_startup_probes_for_systemd_run(harness):
    assert harness.last["scopeProbe"] is True
    assert harness.last["useScope"] is True
    run(harness, [("scopeProbeExit", 1, {"scopeProbe": False, "useScope": False})])
    assert harness.warnings == []


def test_play_while_idle_launches_then_connects_and_sends_the_load(harness):
    run(
        harness,
        PLAYING
        + [
            (
                "line",
                {"event": "file-loaded"},
                {"loadArrived": True, "writes": [CLEAR_KEY]},
            )
        ],
    )
    assert harness.warnings == []


def test_external_mpris_unload_emits_stop_signal_without_relaunch(harness):
    run(harness, PLAYING)
    run(
        harness,
        [
            (
                "line",
                {"event": "property-change", "name": "path", "data": BOOK},
                {"path": BOOK, "loaded": True},
            ),
            (
                "line",
                {"event": "file-loaded"},
                {"loadArrived": True, "writes": [CLEAR_KEY]},
            ),
            (
                "externalStop",
                None,
                {
                    "externalUnloads": 1,
                    "path": "",
                    "loaded": False,
                    "wanted": False,
                    "quitting": True,
                    "writes": [["quit"]],
                },
            ),
        ],
    )
    assert harness.last["wanted"] is False
    assert harness.last["connected"] is True
    assert harness.last["detached"] == []
    assert harness.warnings == []


def _loaded(harness):
    run(harness, PLAYING)
    harness.step("line", {"event": "property-change", "name": "path", "data": BOOK})
    harness.step("line", {"event": "file-loaded"})
    assert harness.last["loaded"] is True and harness.last["loadArrived"] is True


def test_our_own_quit_unloading_the_book_is_not_an_external_stop(harness):
    _loaded(harness)
    harness.step("quit")
    assert harness.last["quitting"] is True
    harness.step("externalStop")
    assert harness.last["externalUnloads"] == 0
    assert harness.warnings == []


def test_a_play_while_our_quit_is_in_flight_is_not_an_external_stop(harness):
    # Stop, then pick a book before mpv has exited: the new play is wanted
    # again while the old mpv is still quitting and drops its file.
    _loaded(harness)
    harness.step("quit")
    harness.step("play", dict(PLAY, start=40))
    assert harness.last["wanted"] is True and harness.last["quitting"] is True
    harness.step("externalStop")
    assert harness.last["externalUnloads"] == 0
    assert harness.last["wanted"] is True
    assert harness.warnings == []


def test_a_book_switch_unloading_the_old_file_is_not_an_external_stop(harness):
    _loaded(harness)
    # A second play while connected sends `loadfile replace` at once; mpv then
    # reports the old file gone (path null) before the new one's file-loaded.
    harness.step("play", dict(PLAY, start=40))
    assert harness.last["loadArrived"] is False
    harness.step("externalStop")
    assert harness.last["externalUnloads"] == 0
    assert harness.last["wanted"] is True
    assert harness.warnings == []


def test_launch_passes_detected_mpris_script(harness):
    script = "/usr/lib/mpv-mpris/mpris.so"
    mpv = MPV + ["--script=" + script]
    launch = LAUNCH[: -len(MPV)] + mpv
    played = dict(PLAYED, detached=[launch])
    run(harness, READY + [("mprisScript", script, {}), ("play", PLAY, played)])


def test_play_before_the_socket_path_is_refused(harness):
    run(harness, [("play", PLAY, {"result": False, "lastError": "player not ready"})])
    assert harness.warnings == []


def test_quit_while_launching_is_sent_once_mpv_connects(harness):
    run(
        harness,
        READY
        + [
            ("play", PLAY, PLAYED),
            (
                "quit",
                None,
                {
                    "wanted": False,
                    "pendingLoad": None,
                    "launching": False,
                    "quitPending": True,
                    "attaching": True,
                },
            ),
            (
                "up",
                None,
                {
                    "connected": True,
                    "connection": "connected",
                    "attempt": 0,
                    "attaching": False,
                    "retry": None,
                    "quitPending": False,
                    "quitting": True,
                    "writes": [["quit"]],
                    "published": ["connected"],
                },
            ),
            (
                "down",
                None,
                {
                    "connected": False,
                    "connection": "idle",
                    "quitting": False,
                    "relaunchPending": True,
                    "relaunch": True,
                    "published": ["idle"],
                },
            ),
            ("relaunch", None, {"relaunch": False, "scopeCheck": True}),
            (
                "scopeExit",
                3,
                {"scopeCheck": False, "scopeChecks": 1, "relaunchPending": False},
            ),
        ],
    )
    assert harness.warnings == []


def test_a_disconnect_after_quit_relaunches_for_a_waiting_play(harness):
    run(
        harness,
        PLAYING
        + [
            ("quit", None, {"wanted": False, "quitting": True, "writes": [["quit"]]}),
            ("play", PLAY, {"result": True, "wanted": True, "pendingLoad": BOOK}),
            (
                "down",
                None,
                {
                    "connected": False,
                    "connection": "idle",
                    "quitting": False,
                    "relaunchPending": True,
                    "relaunch": True,
                    "loadPath": "",
                    "loadArrived": True,
                    "published": ["idle"],
                },
            ),
            ("relaunch", None, {"relaunch": False, "scopeCheck": True}),
            ("scopeExit", 0, {"scopeCheck": False, "scopeChecks": 1, "relaunch": True}),
            ("relaunch", None, {"relaunch": False, "scopeCheck": True}),
            (
                "scopeExit",
                3,
                {
                    "scopeCheck": False,
                    "scopeChecks": 2,
                    "relaunchPending": False,
                    "launching": True,
                    "connection": "launching",
                    "attempt": 1,
                    "detached": [LAUNCH],
                    "built": 2,
                    "retry": 600,
                    "published": ["launching"],
                },
            ),
            ("up", None, CONNECTED),
        ],
    )
    assert harness.warnings == []


def test_an_old_scope_that_never_goes_drops_the_play(harness):
    checks = []
    for n in range(1, 10):
        checks += [
            ("relaunch", None, {"relaunch": False, "scopeCheck": True}),
            ("scopeExit", 0, {"scopeCheck": False, "scopeChecks": n, "relaunch": True}),
        ]
    run(
        harness,
        PLAYING
        + [
            ("quit", None, {"wanted": False, "quitting": True, "writes": [["quit"]]}),
            ("play", PLAY, {"result": True, "wanted": True, "pendingLoad": BOOK}),
            (
                "down",
                None,
                {
                    "connected": False,
                    "connection": "idle",
                    "quitting": False,
                    "relaunchPending": True,
                    "relaunch": True,
                    "loadPath": "",
                    "loadArrived": True,
                    "published": ["idle"],
                },
            ),
        ]
        + checks
        + [
            ("relaunch", None, {"relaunch": False, "scopeCheck": True}),
            (
                "scopeExit",
                0,
                {
                    "scopeCheck": False,
                    "scopeChecks": 10,
                    "relaunchPending": False,
                    "wanted": False,
                    "pendingLoad": None,
                    "connection": "failed",
                    "lastError": "the previous mpv did not exit",
                    "published": ["failed"],
                },
            ),
        ],
    )
    assert harness.warnings == []


# The F22 fade reset (was a source grep in test_p8_service) and the load
# tracking reset (was a count in test_f38_paused_seek), as behaviour.
def test_an_unexpected_exit_with_a_wanted_book_reconnects_and_forgets_the_fade(harness):
    run(
        harness,
        PLAYING
        + [
            (
                "line",
                {"event": "property-change", "name": "path", "data": BOOK},
                {"loaded": True, "path": BOOK},
            ),
            (
                "line",
                {"event": "property-change", "name": "pause", "data": False},
                {"playing": True},
            ),
            ("fade", 80, {"fadeBaseVolume": 80, "sleepTimer": "minutes"}),
            (
                "down",
                None,
                {
                    "connected": False,
                    "connection": "lost",
                    "lastError": "mpv exited unexpectedly",
                    "attempt": 1,
                    "built": 2,
                    "retry": 600,
                    "loaded": False,
                    "playing": False,
                    "path": "",
                    "loadPath": "",
                    "loadArrived": True,
                    "sleepTimer": None,
                    "fadeBaseVolume": -1,
                    "published": ["lost"],
                },
            ),
        ],
    )
    # main's onConnectedChanged rebuilds the Socket inside the update of the
    # `connected` binding, which Qt reports as a loop (unchanged here; see the
    # PR). The retries rebuild it from the timer and are seen again.
    assert harness.warnings == connected_loops(harness)
    assert connected_loops(harness)
    run(
        harness,
        retries(2, 3)[:1]
        + [
            (
                "up",
                None,
                {
                    "connected": True,
                    "connection": "connected",
                    "lastError": "",
                    "attempt": 0,
                    "retry": None,
                    "writes": OBSERVE + [CLEAR_KEY],
                    "published": ["connected"],
                },
            )
        ],
    )


def test_an_unexpected_exit_gives_up_after_the_last_try(harness):
    run(
        harness,
        PLAYING
        + [
            ("sleep", 5, {"sleepTimer": "minutes"}),
            (
                "down",
                None,
                {
                    "connected": False,
                    "connection": "lost",
                    "lastError": "mpv exited unexpectedly",
                    "attempt": 1,
                    "built": 2,
                    "retry": 600,
                    "loadPath": "",
                    "loadArrived": True,
                    "sleepTimer": None,
                    "published": ["lost"],
                },
            ),
        ]
        + retries(2, 3)
        + [
            (
                "retry",
                None,
                {
                    "attempt": 0,
                    "connection": "failed",
                    "wanted": False,
                    "retry": None,
                    "socket": False,
                    "published": ["failed"],
                },
            ),
        ],
    )
    assert harness.warnings == connected_loops(harness)


def test_a_killed_reattached_mpv_fails_without_reconnecting(harness):
    # Reattach after a shell restart: the socket answers at once, inside the
    # connect, which then sets its retry timer from the reset attempt (300 ms).
    run(
        harness,
        [
            ("scopeProbeExit", 0, {"scopeProbe": False}),
            ("connectAtOnce", True, {}),
            ("socketPath", SOCKET, {}),
            ("attach", None, {"probe": ["test", "-S", SOCKET]}),
            (
                "probeExit",
                0,
                {
                    "probe": None,
                    "connected": True,
                    "connection": "connected",
                    "socket": True,
                    "built": 1,
                    "retry": 300,
                    "writes": OBSERVE + [CLEAR_KEY],
                    "published": ["connecting", "connected"],
                },
            ),
            ("retry", None, {"retry": None}),
            ("attach", None, {}),
            (
                "down",
                None,
                {
                    "connected": False,
                    "connection": "failed",
                    "lastError": "mpv exited unexpectedly",
                    "published": ["failed"],
                },
            ),
        ],
    )
    assert harness.warnings == []


def test_a_stale_socket_at_reattach_launches_for_a_waiting_play(harness):
    run(
        harness,
        READY
        + [
            ("attach", None, {"probe": ["test", "-S", SOCKET]}),
            (
                "probeExit",
                0,
                {
                    "probe": None,
                    "attaching": True,
                    "connection": "connecting",
                    "attempt": 1,
                    "socket": True,
                    "built": 1,
                    "retry": 600,
                    "published": ["connecting"],
                },
            ),
            ("play", PLAY, {"result": True, "wanted": True, "pendingLoad": BOOK}),
        ]
        + retries(2, 2)
        + [
            (
                "retry",
                None,
                {
                    "attaching": False,
                    "launching": True,
                    "connection": "launching",
                    "attempt": 1,
                    "detached": [LAUNCH],
                    "built": 7,
                    "retry": 600,
                    "published": ["launching"],
                },
            ),
            ("up", None, CONNECTED),
        ],
    )
    assert harness.warnings == []


def test_an_mpv_that_never_starts_fails_and_keeps_the_sleep_timer(harness):
    # Giving up forgets the load and the gone mpv's state, not the sleep timer.
    run(
        harness,
        [
            ("scopeProbeExit", 1, {"scopeProbe": False, "useScope": False}),
            ("socketPath", SOCKET, {}),
            ("play", PLAY, dict(PLAYED, detached=[LAUNCH_PLAIN])),
            ("sleep", 5, {"sleepTimer": "minutes"}),
        ]
        + retries(2, 2)
        + [
            (
                "retry",
                None,
                {
                    "attempt": 0,
                    "connection": "failed",
                    "lastError": "mpv did not start",
                    "launching": False,
                    "wanted": False,
                    "pendingLoad": None,
                    "retry": None,
                    "socket": False,
                    "published": ["failed"],
                },
            ),
        ],
    )
    assert harness.warnings == []


def test_an_error_reply_is_the_last_error(harness):
    run(
        harness,
        PLAYING
        + [
            (
                "line",
                {"request_id": 9, "error": "property unavailable"},
                {"lastError": "mpv: property unavailable"},
            )
        ],
    )
    assert harness.warnings == []


# A write to an mpv that has just gone disconnects inside send(). quit() then
# sees, at each point, what main's quit() had set by then.
def test_quit_whose_fade_restore_finds_mpv_gone(harness):
    run(
        harness,
        PLAYING
        + [
            ("fade", 80, {"fadeBaseVolume": 80, "sleepTimer": "minutes"}),
            ("dropNextSend", None, {}),
            (
                "quit",
                None,
                {
                    "connected": False,
                    "wanted": False,
                    "connection": "idle",
                    "lastError": "mpv exited unexpectedly",
                    "socket": False,
                    "loadPath": "",
                    "loadArrived": True,
                    "sleepTimer": None,
                    "fadeBaseVolume": -1,
                    "published": ["failed", "idle"],
                },
            ),
        ],
    )
    assert harness.warnings == []


def test_quit_whose_own_write_finds_mpv_gone(harness):
    run(
        harness,
        PLAYING
        + [
            ("dropNextSend", None, {}),
            (
                "quit",
                None,
                {
                    "connected": False,
                    "wanted": False,
                    "connection": "failed",
                    "lastError": "mpv exited unexpectedly",
                    "quitting": True,
                    "loadPath": "",
                    "loadArrived": True,
                    "published": ["failed"],
                },
            ),
        ],
    )
    assert harness.warnings == []


def test_a_load_whose_write_finds_mpv_gone(harness):
    run(
        harness,
        PLAYING
        + [
            ("dropNextSend", None, {}),
            # flushPending: the load's write disconnects; the reconnect starts
            # inside it, and the load's own bookkeeping follows, as on main.
            (
                "play",
                PLAY,
                {
                    "result": True,
                    "connected": False,
                    "connection": "lost",
                    "lastError": "mpv exited unexpectedly",
                    "attempt": 1,
                    "built": 2,
                    "retry": 600,
                    "published": ["lost"],
                },
            ),
        ]
        + retries(2, 3)
        # Giving up forgets that load too.
        + [
            (
                "retry",
                None,
                {
                    "attempt": 0,
                    "connection": "failed",
                    "wanted": False,
                    "retry": None,
                    "socket": False,
                    "loadPath": "",
                    "loadArrived": True,
                    "published": ["failed"],
                },
            ),
        ],
    )
    assert harness.warnings == connected_loops(harness)


# ---- one writer, and nothing of the key in the machine ----

MACHINE = (
    "wanted",
    "attaching",
    "quitting",
    "quitPending",
    "relaunchPending",
    "scopeChecks",
    "launching",
    "attempt",
    "connection",
    "lastError",
)


def test_the_published_properties_are_the_reducer_state(harness):
    steps = PLAYING + [
        ("quit", None, None),
        ("play", PLAY, None),
        ("down", None, None),
        ("relaunch", None, None),
        ("scopeExit", 3, None),
    ]
    for name, arg, _changes in steps:
        harness.step(name, arg)
        reducer = harness.reducer_state()
        assert {key: harness.last[key] for key in MACHINE} == {
            key: reducer[key] for key in MACHINE
        }, name
        assert reducer["loadPending"] is (harness.last["pendingLoad"] is not None), name
        assert KEY not in repr(reducer) and "lavf" not in repr(reducer), name


def test_the_machine_state_has_one_writer():
    source = (REPO / "qml/PlayerController.qml").read_text(encoding="utf-8")
    assert source.count("reducerState = ") == 1
    assert "reducerState = transition.state" in source
    publish = source[source.index("  function publish() {") :]
    publish = publish[: publish.index("\n  }\n")]
    for name in MACHINE:
        # The property is assigned in publish() and nowhere else.
        assert re.search(rf"\b{name} = reducerState\.{name}\b", publish), name
        assert len(re.findall(rf"(?<![.\w]){name} (?:=|\+=|-=) ", source)) == 1, name
        assert len(re.findall(rf"root\.{name} (?:=|\+=|-=) ", source)) == 0, name


def test_the_reset_effects_reset_what_main_reset():
    # Moved with the code (were greps on onConnectedChanged and giveUp in
    # test_p8_service F22 and test_f38_paused_seek): one handler forgets the
    # gone mpv's state and load tracking, another the sleep timer and the
    # fade's base volume, in main's order. Which branch emits which is in the
    # vectors of test_player_machine.py and the behaviour above.
    source = (REPO / "qml/PlayerController.qml").read_text(encoding="utf-8")
    reset = source[
        source.index('type === "reset_state"') : source.index('type === "forget_sleep"')
    ]
    assert (
        reset.index("mpvState = Mpv.emptyState()")
        < reset.index('loadPath = ""')
        < reset.index("loadArrived = true")
    )
    forget = source[source.index('type === "forget_sleep"') :]
    forget = forget[: forget.index("} else if")]
    assert forget.index("sleepTimer = null") < forget.index("fadeBaseVolume = -1")


def test_a_closed_harness_leaves_no_qml_thread(tmp_path):
    # Tests after this one signal their own process (test_redownload's
    # SIGTERM in the commit window): no Qt thread may be left to take it.
    def qml_threads() -> list[str]:
        names = []
        for task in Path("/proc/self/task").iterdir():
            try:
                names.append((task / "comm").read_text().strip())
            except OSError:
                pass
        return [name for name in names if name.startswith("QQml")]

    harness = Harness(tmp_path)
    assert qml_threads()
    harness.close()
    assert qml_threads() == []


# F40: a load mpv cannot open is a failed play, not a silent idle player.
END_FILE_ERROR = {
    "event": "end-file",
    "reason": "error",
    "file_error": "unrecognized file format",
}


def test_a_load_mpv_cannot_open_fails_the_play_and_clears_the_key(harness):
    run(harness, PLAYING)
    assert harness.last["loadArrived"] is False and harness.last["wanted"] is True
    changes = harness.step("line", END_FILE_ERROR)
    assert changes["loadFailures"] == [BOOK]
    assert changes["wanted"] is False
    assert changes["loadArrived"] is True
    assert changes["lastError"] == "the player could not open the book"
    assert changes["writes"] == [CLEAR_KEY]
    # mpv stays up and idle; nothing reconnects or relaunches.
    assert harness.last["connection"] == "connected"
    assert "detached" not in changes
    assert harness.warnings == []


def test_an_error_end_file_after_the_load_arrived_is_not_a_load_failure(harness):
    _loaded(harness)
    changes = harness.step("line", END_FILE_ERROR)
    assert "loadFailures" not in changes
    assert harness.last["wanted"] is True


def test_an_eof_end_file_before_file_loaded_is_not_a_load_failure(harness):
    run(harness, PLAYING)
    changes = harness.step("line", {"event": "end-file", "reason": "stop"})
    assert "loadFailures" not in changes
    assert harness.last["loadArrived"] is False

"""P9 PR 9 — PlayerController's connection machine, ``PlayerMachine.step``, as pure vectors.

Every vector gives the whole state before one event and asserts the whole state after it and the
exact effects, in order. Each is a transition ``PlayerController.qml`` made inline before this PR:
``onConnectedChanged``, ``connectNow``, ``giveUp``, ``attach``, the probe and scope ``Process``
handlers, ``launchMpv``, ``flushPending``, ``play``, ``quit``, ``beginRelaunch``, the relaunch and
retry timers and ``Component.onCompleted``. The scenarios after them chain events the way the
controller feeds them: the S5 pitfalls (SPIKE-RESULTS), quit during startup, play during a quit,
unexpected exits, a stale socket at reattach and F22's fade reset.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import qjs

REPO = Path(__file__).resolve().parents[1]

# Invented: a book path and a key in play-info's `lavf_options` shape.
PATH = "/home/user/.local/share/omarchy-audible-fake/books/B0FAKE0001/book.aaxc"
KEY = "audible_key=00112233445566778899aabbccddeeff,audible_iv=ffeeddccbbaa99887766554433221100"

EXPECTED_API = {
    "CONNECTIONS",
    "SCOPE_CHECKS",
    "_machine",
    "createState",
    "holdsLoad",
    "step",
}


@pytest.fixture(scope="module")
def machine() -> qjs.JsModule:
    return qjs.load("PlayerMachine")


def state(**changes) -> dict:
    out = {
        "wanted": False,
        "attaching": False,
        "launching": False,
        "quitting": False,
        "quitPending": False,
        "relaunchPending": False,
        "scopeChecks": 0,
        "attempt": 0,
        "connection": "idle",
        "lastError": "",
        "loadPending": False,
    }
    assert set(changes) <= set(out), changes
    out.update(changes)
    return out


def fx(*types: str) -> list[dict]:
    return [{"type": name} for name in types]


# Every field away from its default, so a vector shows what an event leaves alone.
BUSY = state(
    wanted=True,
    attaching=True,
    launching=True,
    quitting=True,
    quitPending=True,
    relaunchPending=True,
    scopeChecks=4,
    attempt=3,
    connection="lost",
    lastError="earlier",
    loadPending=True,
)
# mpv started for a play and not connected yet (launchMpv + connectNow).
LAUNCHING = state(
    wanted=True, loadPending=True, launching=True, connection="launching", attempt=1
)
# The startup attach found a socket file and is connecting (the probe handler).
ATTACHING = state(attaching=True, connection="connecting", attempt=1)
# Playing: the load went out when mpv connected.
PLAYING = state(wanted=True, connection="connected")
# A quit was sent and mpv has not gone yet.
QUITTING = state(connection="connected", quitting=True)
# The old mpv is gone; waiting for its scope (beginRelaunch).
RELAUNCHING = state(relaunchPending=True)
# The reset `connected` makes, and every connect's subscription.
CONNECTED = {
    "attempt": 0,
    "launching": False,
    "attaching": False,
    "connection": "connected",
    "lastError": "",
}
GIVE_UP = fx("stop_retry", "close_socket", "drop_load", "reset_state")

# (id, state before, event, state after, effects)
VECTORS = [
    # ---- Component.onCompleted and the systemd-run probe ----
    ("start probes for systemd-run", BUSY, {"type": "start"}, BUSY, fx("probe_scope")),
    (
        "systemd-run found: launch in a scope",
        BUSY,
        {"type": "scope_probe_result", "code": 0},
        BUSY,
        [{"type": "use_scope", "value": True}],
    ),
    (
        "no systemd-run: launch plainly",
        BUSY,
        {"type": "scope_probe_result", "code": 1},
        BUSY,
        [{"type": "use_scope", "value": False}],
    ),
    (
        "a probe exit without a code is no systemd-run",
        BUSY,
        {"type": "scope_probe_result"},
        BUSY,
        [{"type": "use_scope", "value": False}],
    ),
    # ---- attach() and the socket probe ----
    (
        "attach probes the socket file",
        BUSY,
        {"type": "attach", "ready": True, "connected": False},
        BUSY,
        fx("probe_socket"),
    ),
    (
        "attach while connected does nothing",
        BUSY,
        {"type": "attach", "ready": True, "connected": True},
        BUSY,
        [],
    ),
    (
        "attach without a socket path does nothing",
        BUSY,
        {"type": "attach", "ready": False, "connected": False},
        BUSY,
        [],
    ),
    (
        "a socket file starts a bounded attach",
        state(attempt=3),
        {"type": "probe_result", "code": 0, "connected": False},
        state(attaching=True, connection="connecting", attempt=1),
        fx("connect"),
    ),
    (
        "no socket file: nothing to attach",
        BUSY,
        {"type": "probe_result", "code": 1, "connected": False},
        BUSY,
        [],
    ),
    (
        "a probe after connecting does nothing",
        BUSY,
        {"type": "probe_result", "code": 0, "connected": True},
        BUSY,
        [],
    ),
    (
        "a probe exit without a code does nothing",
        BUSY,
        {"type": "probe_result", "connected": False},
        BUSY,
        [],
    ),
    # ---- play() ----
    (
        "play before the socket path is known is refused",
        BUSY,
        {"type": "play", "ready": False, "connected": False},
        dict(BUSY, lastError="player not ready"),
        [],
    ),
    (
        "play while idle launches, then connects",
        state(attempt=2, lastError="mpv did not start"),
        {"type": "play", "ready": True, "connected": False},
        state(
            wanted=True,
            loadPending=True,
            launching=True,
            connection="launching",
            attempt=1,
            lastError="mpv did not start",
        ),
        fx("hold_load", "launch", "connect"),
    ),
    (
        "play while connected sends the load at once",
        state(connection="connected"),
        {"type": "play", "ready": True, "connected": True},
        state(wanted=True, connection="connected"),
        fx("hold_load", "flush_pending"),
    ),
    (
        "play during a quit waits for the relaunch",
        QUITTING,
        {"type": "play", "ready": True, "connected": True},
        dict(QUITTING, wanted=True, loadPending=True),
        fx("hold_load"),
    ),
    (
        "play while mpv is starting only replaces the load",
        LAUNCHING,
        {"type": "play", "ready": True, "connected": False},
        LAUNCHING,
        fx("hold_load"),
    ),
    (
        "play overtakes a quit that has not been sent",
        state(attaching=True, quitPending=True, connection="launching", attempt=2),
        {"type": "play", "ready": True, "connected": False},
        state(
            attaching=True,
            connection="launching",
            attempt=2,
            wanted=True,
            loadPending=True,
        ),
        fx("hold_load"),
    ),
    (
        "play during the startup attach waits for it",
        ATTACHING,
        {"type": "play", "ready": True, "connected": False},
        dict(ATTACHING, wanted=True, loadPending=True),
        fx("hold_load"),
    ),
    (
        "play during the relaunch wait waits for the scope",
        RELAUNCHING,
        {"type": "play", "ready": True, "connected": False},
        dict(RELAUNCHING, wanted=True, loadPending=True),
        fx("hold_load"),
    ),
    (
        "a quitting flag left while disconnected does not block a launch",
        state(quitting=True, attempt=4),
        {"type": "play", "ready": True, "connected": False},
        state(
            quitting=True,
            wanted=True,
            loadPending=True,
            launching=True,
            connection="launching",
            attempt=1,
        ),
        fx("hold_load", "launch", "connect"),
    ),
    # ---- quit() ----
    (
        "quit while playing sends quit",
        PLAYING,
        {"type": "quit"},
        state(connection="connected"),
        [
            {"type": "drop_load"},
            {"type": "cancel_sleep"},
            {"type": "try_quit", "starting": False},
        ],
    ),
    (
        "quit during a quit drops the waiting play",
        dict(QUITTING, wanted=True, loadPending=True),
        {"type": "quit"},
        QUITTING,
        [
            {"type": "drop_load"},
            {"type": "cancel_sleep"},
            {"type": "try_quit", "starting": False},
        ],
    ),
    (
        "quit during startup says mpv was starting",
        LAUNCHING,
        {"type": "quit"},
        state(connection="launching", attempt=1),
        [
            {"type": "drop_load"},
            {"type": "cancel_sleep"},
            {"type": "try_quit", "starting": True},
        ],
    ),
    (
        "the quit went out",
        state(connection="connected", attaching=True),
        {"type": "quit_sent", "sent": True, "starting": True},
        state(connection="connected", quitting=True),
        [],
    ),
    (
        "quit during startup waits for mpv to connect",
        state(connection="launching", attempt=2),
        {"type": "quit_sent", "sent": False, "starting": True},
        state(connection="launching", attempt=2, quitPending=True, attaching=True),
        [],
    ),
    (
        "quit during the startup attach waits for it",
        ATTACHING,
        {"type": "quit_sent", "sent": False, "starting": False},
        dict(ATTACHING, quitPending=True),
        [],
    ),
    (
        "quit with nothing there drops the socket first",
        state(connection="failed", lastError="mpv did not start", attempt=2),
        {"type": "quit_sent", "sent": False, "starting": False},
        state(connection="failed", lastError="mpv did not start", attempt=2),
        fx("stop_retry", "close_quit"),
    ),
    (
        "then goes idle, keeping the error",
        state(connection="failed", lastError="mpv exited unexpectedly"),
        {"type": "quit_closed"},
        state(connection="idle", lastError="mpv exited unexpectedly"),
        [],
    ),
    # ---- onConnectedChanged: connected ----
    (
        "connect subscribes, clears the key, then sends the load",
        dict(LAUNCHING, attempt=3, lastError="mpv: property unavailable"),
        {"type": "connected"},
        state(wanted=True, **CONNECTED),
        fx("stop_retry", "subscribe", "clear_key", "flush_pending"),
    ),
    (
        "a reattach subscribes and clears the key",
        ATTACHING,
        {"type": "connected"},
        state(**CONNECTED),
        fx("stop_retry", "subscribe", "clear_key"),
    ),
    (
        "quit during startup is sent as soon as mpv connects",
        state(attaching=True, quitPending=True, connection="launching", attempt=2),
        {"type": "connected"},
        state(quitting=True, **CONNECTED),
        fx("stop_retry", "send_quit"),
    ),
    (
        "a connect clears a quitting flag left over",
        dict(LAUNCHING, quitting=True),
        {"type": "connected"},
        state(wanted=True, **CONNECTED),
        fx("stop_retry", "subscribe", "clear_key", "flush_pending"),
    ),
    # ---- onConnectedChanged: disconnected ----
    (
        "a disconnect before any connect is ignored",
        BUSY,
        {"type": "disconnected"},
        BUSY,
        [],
    ),
    (
        "a disconnect after a quit waits for the old scope",
        dict(QUITTING, scopeChecks=3),
        {"type": "disconnected"},
        RELAUNCHING,
        fx("reset_state", "forget_sleep", "begin_relaunch"),
    ),
    (
        "a disconnect after a quit keeps a play that came during it",
        dict(QUITTING, wanted=True, loadPending=True, scopeChecks=2),
        {"type": "disconnected"},
        dict(RELAUNCHING, wanted=True, loadPending=True),
        fx("reset_state", "forget_sleep", "begin_relaunch"),
    ),
    (
        "an unexpected exit with a wanted book reconnects",
        PLAYING,
        {"type": "disconnected"},
        state(
            wanted=True,
            connection="lost",
            lastError="mpv exited unexpectedly",
            attempt=1,
        ),
        fx("reset_state", "forget_sleep", "connect"),
    ),
    (
        "an unexpected exit without a wanted book fails",
        state(connection="connected"),
        {"type": "disconnected"},
        state(connection="failed", lastError="mpv exited unexpectedly"),
        fx("reset_state", "forget_sleep"),
    ),
    # ---- the retry timer ----
    (
        "a retry after connecting does nothing",
        LAUNCHING,
        {"type": "retry_tick", "connected": True},
        LAUNCHING,
        [],
    ),
    (
        "a retry while a book is wanted connects again",
        dict(LAUNCHING, attempt=3),
        {"type": "retry_tick", "connected": False},
        dict(LAUNCHING, attempt=4),
        fx("connect"),
    ),
    (
        "a retry while attaching connects again",
        dict(ATTACHING, attempt=5),
        {"type": "retry_tick", "connected": False},
        dict(ATTACHING, attempt=6),
        fx("connect"),
    ),
    (
        "mpv did not start",
        dict(LAUNCHING, attempt=6),
        {"type": "retry_tick", "connected": False},
        state(connection="failed", lastError="mpv did not start"),
        GIVE_UP,
    ),
    (
        "a lost mpv that never answers again",
        state(
            wanted=True,
            connection="lost",
            lastError="mpv exited unexpectedly",
            attempt=6,
        ),
        {"type": "retry_tick", "connected": False},
        state(connection="failed", lastError="mpv exited unexpectedly"),
        GIVE_UP,
    ),
    (
        "a stale socket at reattach with a play waiting launches",
        dict(ATTACHING, wanted=True, loadPending=True, attempt=6),
        {"type": "retry_tick", "connected": False},
        state(
            wanted=True,
            loadPending=True,
            launching=True,
            connection="launching",
            attempt=1,
        ),
        fx("stop_retry", "launch", "connect"),
    ),
    (
        "a stale socket at reattach with nothing waiting goes idle",
        dict(ATTACHING, attempt=6, lastError="earlier"),
        {"type": "retry_tick", "connected": False},
        state(lastError="earlier"),
        GIVE_UP,
    ),
    (
        "quit during startup and mpv never answers",
        state(attaching=True, quitPending=True, connection="launching", attempt=6),
        {"type": "retry_tick", "connected": False},
        state(),
        GIVE_UP,
    ),
    (
        "a retry with nothing wanted gives up at once",
        state(connection="failed", lastError="mpv did not start"),
        {"type": "retry_tick", "connected": False},
        state(lastError="mpv did not start"),
        GIVE_UP,
    ),
    # ---- giveUp() ----
    (
        "a play waiting out the relaunch gives up as an unexpected exit",
        dict(
            RELAUNCHING,
            wanted=True,
            loadPending=True,
            attempt=6,
            lastError="mpv: property unavailable",
        ),
        {"type": "give_up"},
        state(
            relaunchPending=True,
            connection="failed",
            lastError="mpv exited unexpectedly",
        ),
        GIVE_UP,
    ),
    (
        "give up while launching",
        dict(LAUNCHING, quitPending=True, attempt=2),
        {"type": "give_up"},
        state(connection="failed", lastError="mpv did not start"),
        GIVE_UP,
    ),
    (
        "give up with a play waiting at reattach launches",
        dict(ATTACHING, wanted=True, loadPending=True, attempt=2),
        {"type": "give_up"},
        state(
            wanted=True,
            loadPending=True,
            launching=True,
            connection="launching",
            attempt=1,
        ),
        fx("stop_retry", "launch", "connect"),
    ),
    # ---- the relaunch's scope check ----
    (
        "the old scope is still there: check again",
        RELAUNCHING,
        {"type": "scope_active"},
        dict(RELAUNCHING, scopeChecks=1),
        fx("recheck_scope"),
    ),
    (
        "the ninth check still waits",
        dict(RELAUNCHING, scopeChecks=8, wanted=True, loadPending=True),
        {"type": "scope_active"},
        dict(RELAUNCHING, scopeChecks=9, wanted=True, loadPending=True),
        fx("recheck_scope"),
    ),
    (
        "the tenth gives up on the old mpv and drops the play",
        dict(RELAUNCHING, scopeChecks=9, wanted=True, loadPending=True),
        {"type": "scope_active"},
        state(
            scopeChecks=10,
            connection="failed",
            lastError="the previous mpv did not exit",
        ),
        fx("drop_load"),
    ),
    (
        "the old scope has gone and a play is waiting: launch",
        dict(RELAUNCHING, scopeChecks=2, wanted=True, loadPending=True, attempt=3),
        {"type": "scope_gone", "connected": False},
        state(
            scopeChecks=3,
            wanted=True,
            loadPending=True,
            launching=True,
            connection="launching",
            attempt=1,
        ),
        fx("launch", "connect"),
    ),
    (
        "the old scope has gone and nothing is waiting",
        RELAUNCHING,
        {"type": "scope_gone", "connected": False},
        state(scopeChecks=1),
        [],
    ),
    (
        "gone, but connected already: no second mpv",
        dict(RELAUNCHING, wanted=True, loadPending=True),
        {"type": "scope_gone", "connected": True},
        state(scopeChecks=1, wanted=True, loadPending=True),
        [],
    ),
    (
        "gone, wanted, but the load has gone",
        dict(RELAUNCHING, wanted=True),
        {"type": "scope_gone", "connected": False},
        state(scopeChecks=1, wanted=True),
        [],
    ),
    (
        "gone, a load but no book wanted",
        dict(RELAUNCHING, loadPending=True),
        {"type": "scope_gone", "connected": False},
        state(scopeChecks=1, loadPending=True),
        [],
    ),
    # ---- handleLine: an error reply ----
    (
        "mpv's error reply is the last error",
        PLAYING,
        {"type": "reply_error", "error": "property unavailable"},
        dict(PLAYING, lastError="mpv: property unavailable"),
        [],
    ),
    (
        "an error reply without text is ignored",
        BUSY,
        {"type": "reply_error", "error": None},
        BUSY,
        [],
    ),
]


@pytest.mark.parametrize(
    "before,event,after,effects", [v[1:] for v in VECTORS], ids=[v[0] for v in VECTORS]
)
def test_vector(machine, before, event, after, effects):
    result = machine.call("step", before, event)
    assert result == {"state": after, "effects": effects}


def test_vector_ids_are_unique():
    assert len({v[0] for v in VECTORS}) == len(VECTORS)


def test_api(machine):
    assert set(machine.functions) == EXPECTED_API
    assert machine.call("createState") == state()
    assert machine.evaluate("SCOPE_CHECKS") == 10
    assert machine.evaluate("CONNECTIONS") == [
        "idle",
        "launching",
        "connecting",
        "connected",
        "lost",
        "failed",
    ]


# ---- scenarios: events chained the way PlayerController feeds them ----


def run(machine, before: dict, steps: list) -> dict:
    """Each step is (event, state after, effects); the next starts from that state."""
    current = before
    for event, after, effects in steps:
        result = machine.call("step", current, event)
        assert result == {"state": after, "effects": effects}, event
        current = after
    return current


def test_s5_pitfall_1_subscribe_only_once_the_derived_connected_says_so(machine):
    # Building the Socket subscribes nothing; only `connected` (the derived
    # property, whether at once or later) does.
    run(
        machine,
        state(),
        [
            (
                {"type": "play", "ready": True, "connected": False},
                LAUNCHING,
                fx("hold_load", "launch", "connect"),
            ),
            (
                {"type": "connected"},
                state(wanted=True, **CONNECTED),
                fx("stop_retry", "subscribe", "clear_key", "flush_pending"),
            ),
        ],
    )


def test_s5_pitfall_2_every_try_builds_a_new_socket(machine):
    steps = [
        (
            {"type": "retry_tick", "connected": False},
            dict(LAUNCHING, attempt=n),
            fx("connect"),
        )
        for n in range(2, 7)
    ]
    run(machine, LAUNCHING, steps)


def test_s5_pitfall_3_a_socket_file_proves_nothing(machine):
    # The probe found a file; only a connect makes it "connected". A file left
    # by a gone mpv costs six bounded tries, then nothing.
    steps = [
        (
            {"type": "probe_result", "code": 0, "connected": False},
            ATTACHING,
            fx("connect"),
        )
    ]
    steps += [
        (
            {"type": "retry_tick", "connected": False},
            dict(ATTACHING, attempt=n),
            fx("connect"),
        )
        for n in range(2, 7)
    ]
    steps.append(({"type": "retry_tick", "connected": False}, state(), GIVE_UP))
    run(machine, state(), steps)


def test_s5_pitfall_4_a_failed_launch_shows_only_as_no_connection(machine):
    steps = [
        (
            {"type": "play", "ready": True, "connected": False},
            LAUNCHING,
            fx("hold_load", "launch", "connect"),
        )
    ]
    steps += [
        (
            {"type": "retry_tick", "connected": False},
            dict(LAUNCHING, attempt=n),
            fx("connect"),
        )
        for n in range(2, 7)
    ]
    steps.append(
        (
            {"type": "retry_tick", "connected": False},
            state(connection="failed", lastError="mpv did not start"),
            GIVE_UP,
        )
    )
    run(machine, state(), steps)


def test_s5_pitfall_5_nothing_wanted_costs_nothing(machine):
    # No book and no attach: a stray retry stops at once, and a lost mpv is
    # not looked for.
    assert (
        machine.call("step", state(), {"type": "retry_tick", "connected": False})[
            "effects"
        ]
        == GIVE_UP
    )
    lost = machine.call("step", state(connection="connected"), {"type": "disconnected"})
    assert "connect" not in [effect["type"] for effect in lost["effects"]]


def test_quit_during_startup(machine):
    run(
        machine,
        state(),
        [
            (
                {"type": "play", "ready": True, "connected": False},
                LAUNCHING,
                fx("hold_load", "launch", "connect"),
            ),
            (
                {"type": "quit"},
                state(connection="launching", attempt=1),
                [
                    {"type": "drop_load"},
                    {"type": "cancel_sleep"},
                    {"type": "try_quit", "starting": True},
                ],
            ),
            (
                {"type": "quit_sent", "sent": False, "starting": True},
                state(
                    connection="launching", attempt=1, quitPending=True, attaching=True
                ),
                [],
            ),
            # Still bounded: the attach keeps the connect going.
            (
                {"type": "retry_tick", "connected": False},
                state(
                    connection="launching", attempt=2, quitPending=True, attaching=True
                ),
                fx("connect"),
            ),
            (
                {"type": "connected"},
                state(quitting=True, **CONNECTED),
                fx("stop_retry", "send_quit"),
            ),
            (
                {"type": "disconnected"},
                RELAUNCHING,
                fx("reset_state", "forget_sleep", "begin_relaunch"),
            ),
            ({"type": "scope_gone", "connected": False}, state(scopeChecks=1), []),
        ],
    )


def test_play_during_a_quit(machine):
    run(
        machine,
        PLAYING,
        [
            (
                {"type": "quit"},
                state(connection="connected"),
                [
                    {"type": "drop_load"},
                    {"type": "cancel_sleep"},
                    {"type": "try_quit", "starting": False},
                ],
            ),
            ({"type": "quit_sent", "sent": True, "starting": False}, QUITTING, []),
            (
                {"type": "play", "ready": True, "connected": True},
                dict(QUITTING, wanted=True, loadPending=True),
                fx("hold_load"),
            ),
            (
                {"type": "disconnected"},
                dict(RELAUNCHING, wanted=True, loadPending=True),
                fx("reset_state", "forget_sleep", "begin_relaunch"),
            ),
            (
                {"type": "scope_active"},
                dict(RELAUNCHING, wanted=True, loadPending=True, scopeChecks=1),
                fx("recheck_scope"),
            ),
            (
                {"type": "scope_gone", "connected": False},
                state(
                    scopeChecks=2,
                    wanted=True,
                    loadPending=True,
                    launching=True,
                    connection="launching",
                    attempt=1,
                ),
                fx("launch", "connect"),
            ),
            (
                {"type": "connected"},
                state(scopeChecks=2, wanted=True, **CONNECTED),
                fx("stop_retry", "subscribe", "clear_key", "flush_pending"),
            ),
        ],
    )


def test_an_unexpected_exit_with_a_wanted_book(machine):
    lost = state(
        wanted=True, connection="lost", lastError="mpv exited unexpectedly", attempt=1
    )
    # It comes back: subscribed again, nothing to load (the load went out).
    run(
        machine,
        PLAYING,
        [
            (
                {"type": "disconnected"},
                lost,
                fx("reset_state", "forget_sleep", "connect"),
            ),
            (
                {"type": "connected"},
                state(wanted=True, **CONNECTED),
                fx("stop_retry", "subscribe", "clear_key"),
            ),
        ],
    )
    # It doesn't: six tries, then failed.
    steps = [
        ({"type": "disconnected"}, lost, fx("reset_state", "forget_sleep", "connect"))
    ]
    steps += [
        (
            {"type": "retry_tick", "connected": False},
            dict(lost, attempt=n),
            fx("connect"),
        )
        for n in range(2, 7)
    ]
    steps.append(
        (
            {"type": "retry_tick", "connected": False},
            state(connection="failed", lastError="mpv exited unexpectedly"),
            GIVE_UP,
        )
    )
    run(machine, PLAYING, steps)


def test_an_unexpected_exit_without_a_wanted_book(machine):
    # A reattached mpv (nothing played here since the restart) is killed.
    run(
        machine,
        state(),
        [
            (
                {"type": "attach", "ready": True, "connected": False},
                state(),
                fx("probe_socket"),
            ),
            (
                {"type": "probe_result", "code": 0, "connected": False},
                ATTACHING,
                fx("connect"),
            ),
            (
                {"type": "connected"},
                state(**CONNECTED),
                fx("stop_retry", "subscribe", "clear_key"),
            ),
            (
                {"type": "disconnected"},
                state(connection="failed", lastError="mpv exited unexpectedly"),
                fx("reset_state", "forget_sleep"),
            ),
        ],
    )


def test_a_stale_socket_at_reattach_with_a_play_waiting(machine):
    waiting = dict(ATTACHING, wanted=True, loadPending=True)
    steps = [
        (
            {"type": "probe_result", "code": 0, "connected": False},
            ATTACHING,
            fx("connect"),
        ),
        ({"type": "play", "ready": True, "connected": False}, waiting, fx("hold_load")),
    ]
    steps += [
        (
            {"type": "retry_tick", "connected": False},
            dict(waiting, attempt=n),
            fx("connect"),
        )
        for n in range(2, 7)
    ]
    steps += [
        (
            {"type": "retry_tick", "connected": False},
            state(
                wanted=True,
                loadPending=True,
                launching=True,
                connection="launching",
                attempt=1,
            ),
            fx("stop_retry", "launch", "connect"),
        ),
        (
            {"type": "connected"},
            state(wanted=True, **CONNECTED),
            fx("stop_retry", "subscribe", "clear_key", "flush_pending"),
        ),
    ]
    run(machine, state(), steps)


def test_f22_only_a_disconnect_forgets_the_fade(machine):
    # The disconnect forgets the sleep timer and the fade's base volume after
    # the gone mpv's state, in both of its branches.
    for before in (PLAYING, QUITTING, state(connection="connected")):
        effects = machine.call("step", before, {"type": "disconnected"})["effects"]
        types = [effect["type"] for effect in effects]
        assert types[:2] == ["reset_state", "forget_sleep"], before
    # Giving up resets the mpv state only, as before: no forget_sleep.
    for before in (
        LAUNCHING,
        ATTACHING,
        state(wanted=True, connection="lost", attempt=6),
    ):
        assert machine.call("step", before, {"type": "give_up"})["effects"] == GIVE_UP


def test_a_send_that_finds_mpv_gone_during_a_quit(machine):
    # quit() is three steps so a disconnect fired by one of its sends (a write
    # to a dead mpv disconnects at once) sees what main's quit() had set by
    # then: here cancel_sleep's volume write finds mpv gone.
    after_quit = state(connection="connected")
    run(
        machine,
        PLAYING,
        [
            (
                {"type": "quit"},
                after_quit,
                [
                    {"type": "drop_load"},
                    {"type": "cancel_sleep"},
                    {"type": "try_quit", "starting": False},
                ],
            ),
            # Nested in cancel_sleep: not asked for yet, and no book is wanted.
            (
                {"type": "disconnected"},
                state(connection="failed", lastError="mpv exited unexpectedly"),
                fx("reset_state", "forget_sleep"),
            ),
            # try_quit's send then finds no socket.
            (
                {"type": "quit_sent", "sent": False, "starting": False},
                state(connection="failed", lastError="mpv exited unexpectedly"),
                fx("stop_retry", "close_quit"),
            ),
            ({"type": "quit_closed"}, state(lastError="mpv exited unexpectedly"), []),
        ],
    )


# ---- bad input ----


@pytest.mark.parametrize(
    "before,event",
    [
        (None, None),
        ("state", "event"),
        ([], []),
        (5, {"type": "play"}),
        ({}, {}),
        ({}, {"type": None}),
        ({}, {"type": "toString"}),
        ({}, {"type": "constructor"}),
        ({}, {"type": "__proto__"}),
        ({}, ["connected"]),
        ({"connection": None}, {"type": "disconnected"}),
    ],
)
def test_bad_input_never_throws(machine, before, event):
    result = machine.call("step", before, event)
    assert set(result) == {"state", "effects"}
    assert set(result["state"]) == set(state())
    assert isinstance(result["effects"], list)


def test_an_unknown_event_changes_nothing(machine):
    for event in (
        None,
        {},
        {"type": "nope"},
        {"type": "nope", "error": "property unavailable", "ready": True, "code": 0},
        {"type": "toString"},
        ["start"],
        "start",
    ):
        assert machine.call("step", BUSY, event) == {"state": BUSY, "effects": []}


def test_a_bad_state_is_cleaned(machine):
    messy = {
        "wanted": "yes",
        "attaching": 1,
        "launching": None,
        "quitting": "true",
        "quitPending": [],
        "relaunchPending": {},
        "scopeChecks": 2.9,
        "attempt": -3,
        "connection": "weird",
        "lastError": 7,
        "loadPending": "true",
        "pendingLoad": {"path": PATH, "options": {"lavf": KEY}},
    }
    assert machine.call("step", messy, {"type": "nope"}) == {
        "state": state(scopeChecks=2),
        "effects": [],
    }
    assert (
        machine.call("step", {"attempt": "3", "scopeChecks": None}, {})["state"]
        == state()
    )


def test_bad_event_fields_count_as_false(machine):
    # Only `true` and the number 0 count: "yes", 1 and "0" are not them.
    assert machine.call("step", state(), {"type": "play", "ready": "yes"}) == {
        "state": state(lastError="player not ready"),
        "effects": [],
    }
    assert machine.call("step", state(), {"type": "probe_result", "code": "0"}) == {
        "state": state(),
        "effects": [],
    }
    assert machine.call("step", state(), {"type": "attach", "ready": 1}) == {
        "state": state(),
        "effects": [],
    }
    assert machine.call(
        "step", ATTACHING, {"type": "quit_sent", "sent": 1, "starting": "yes"}
    ) == {
        "state": dict(ATTACHING, quitPending=True),
        "effects": [],
    }
    assert machine.call(
        "step",
        state(connection="failed"),
        {"type": "quit_sent", "sent": 1, "starting": "yes"},
    ) == {
        "state": state(connection="failed"),
        "effects": fx("stop_retry", "close_quit"),
    }
    assert machine.call("step", PLAYING, {"type": "reply_error", "error": 5}) == {
        "state": PLAYING,
        "effects": [],
    }


def test_step_never_changes_the_state_it_is_given(machine):
    held = machine.hold("JSON.parse", json.dumps(LAUNCHING))
    machine.call("step", held, {"type": "connected"})
    machine.call("step", held, {"type": "give_up"})
    assert held.read() == LAUNCHING


@pytest.mark.parametrize(
    "effects,held",
    [
        (fx("hold_load"), True),
        (fx("hold_load", "launch", "connect"), True),
        ([None, 5, "hold_load", {"type": "hold_load"}], True),
        (fx("launch", "connect"), False),
        ([], False),
        (None, False),
        ("hold_load", False),
        ({"type": "hold_load"}, False),
        ([None, "hold_load", ["hold_load"]], False),
    ],
)
def test_holds_load(machine, effects, held):
    assert machine.call("holdsLoad", effects) is held


# ---- the key never enters the machine ----

# What the controller has for a play, and what must never come back out.
LOAD = {
    "path": PATH,
    "startSec": 12,
    "options": {"lavf": KEY, "chaptersFile": "/tmp/chapters.txt"},
}
FORBIDDEN = (
    KEY,
    "audible_key",
    "audible_iv",
    "lavf",
    "options",
    "chaptersFile",
    PATH,
    "startSec",
    "pendingLoad",
)


def _every_step():
    """Every (state, event) the vectors and scenarios use."""
    for _id, before, event, _after, _effects in VECTORS:
        yield before, event
    for before in (state(), BUSY, LAUNCHING, ATTACHING, PLAYING, QUITTING, RELAUNCHING):
        for event_type in (
            "start",
            "scope_probe_result",
            "attach",
            "probe_result",
            "play",
            "quit",
            "quit_sent",
            "quit_closed",
            "connected",
            "disconnected",
            "retry_tick",
            "give_up",
            "scope_active",
            "scope_gone",
            "reply_error",
        ):
            for flag in (True, False):
                yield (
                    before,
                    {
                        "type": event_type,
                        "ready": flag,
                        "connected": flag,
                        "sent": flag,
                        "starting": flag,
                        "code": 0 if flag else 1,
                    },
                )


def test_no_state_or_effect_ever_holds_the_key(machine):
    # Even an event that carried the load (the controller never sends one) and
    # a state with a load in it give nothing of it back.
    seen = 0
    for before, event in _every_step():
        if isinstance(event, dict):
            event = dict(event, load=LOAD, pendingLoad=LOAD, **LOAD)
        dirty = dict(before, pendingLoad=LOAD, load=LOAD)
        for start in (before, dirty):
            result = machine.call("step", start, event)
            text = json.dumps(result)
            for word in FORBIDDEN:
                assert word not in text, (
                    event.get("type") if isinstance(event, dict) else event,
                    word,
                )
            seen += 1
    assert seen > 400
    assert KEY not in json.dumps(machine.call("createState"))


def test_the_controller_sends_the_machine_no_load():
    # Every event PlayerController builds names only flags and codes; the load
    # goes to apply() beside the event, for hold_load, and stays in the QML.
    source = (REPO / "qml/PlayerController.qml").read_text(encoding="utf-8")
    events = re.findall(r'apply\(\{ "type": [^}]*\}', source)
    assert len(events) >= 12
    for event in events:
        keys = set(re.findall(r'"(\w+)":', event))
        assert keys <= {
            "type",
            "ready",
            "connected",
            "code",
            "sent",
            "starting",
            "error",
        }, event
    assert source.count("}, load))") == 1

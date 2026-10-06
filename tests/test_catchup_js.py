"""G3 finding 5 — ``qml/lib/Catchup.js``: ⏯ catches up with other devices.

SCOPE FR-P4: on play, resume from the newest of the local and Audible
positions. A Library pick always read the account; ⏯ on a paused book did not,
so after listening on the phone the laptop resumed its own spot.
"""

from __future__ import annotations

import pytest

import qjs

MIN = 60_000


@pytest.fixture(scope="module")
def catchup() -> qjs.JsModule:
    return qjs.load("Catchup")


def test_constants(catchup):
    assert catchup.evaluate("PAUSE_CHECK_MS") == 30_000
    assert catchup.evaluate("READ_TIMEOUT_MS") == 3_000
    assert catchup.evaluate("PREFETCH_FRESH_MS") == 60_000
    assert catchup.evaluate("JUMP_MIN_MS") == 2_000


@pytest.mark.parametrize("paused_at,now,result", [
    (0, 10 * MIN, True),            # unknown pause time (shell restarted): read
    (None, 10 * MIN, True),
    (-5, 10 * MIN, True),
    (10 * MIN, 10 * MIN, False),    # just paused
    (10 * MIN - 29_999, 10 * MIN, False),
    (10 * MIN - 30_000, 10 * MIN, True),
    (10 * MIN - 2 * MIN, 10 * MIN, True),
    (11 * MIN, 10 * MIN, True),     # clock went backwards: read to be safe
    ("x", 10 * MIN, True),
])
def test_needs_read(catchup, paused_at, now, result):
    assert catchup.call("needsRead", paused_at, now) is result


@pytest.mark.parametrize("prefetch,asin,now,result", [
    ({"asin": "B1", "atMs": 10 * MIN, "remote": {"ms": 5}}, "B1", 10 * MIN + 59_000, True),
    ({"asin": "B1", "atMs": 10 * MIN, "remote": None}, "B1", 10 * MIN, True),
    ({"asin": "B1", "atMs": 10 * MIN, "remote": {"ms": 5}}, "B1", 10 * MIN + 60_001, False),
    ({"asin": "B1", "atMs": 10 * MIN, "remote": {"ms": 5}}, "B2", 10 * MIN, False),
    ({"asin": "B1", "atMs": 11 * MIN, "remote": {"ms": 5}}, "B1", 10 * MIN, False),
    ({"asin": "B1", "remote": {"ms": 5}}, "B1", 10 * MIN, False),
    (None, "B1", 10 * MIN, False),
    ({}, "B1", 10 * MIN, False),
])
def test_prefetch_usable(catchup, prefetch, asin, now, result):
    assert catchup.call("prefetchUsable", prefetch, asin, now) is result


@pytest.mark.parametrize("current,local_key,remote_ms,remote_key,target", [
    # The phone listened after the laptop paused: jump.
    (196_688, 1_000, 1_684_289, 2_000, 1_684_289),
    # The phone went back: still newer, so jump back.
    (1_684_289, 1_000, 196_688, 2_000, 196_688),
    # The account holds the laptop's own pause push: same spot, no jump.
    (110_757, 1_000, 110_757, 2_000, -1),
    (110_757, 1_000, 112_000, 2_000, -1),
    (110_757, 1_000, 112_757, 2_000, 112_757),
    # The local position is newer or equal: never jump.
    (196_688, 2_000, 1_684_289, 1_000, -1),
    (196_688, 2_000, 1_684_289, 2_000, -1),
    # No usable remote.
    (196_688, 1_000, 1_684_289, None, -1),
    (196_688, 1_000, None, 2_000, -1),
    (196_688, 1_000, -5, 2_000, -1),
    # Nothing saved locally: the account wins.
    (0, None, 1_684_289, 2_000, 1_684_289),
])
def test_jump_target(catchup, current, local_key, remote_ms, remote_key, target):
    assert catchup.call("jumpTarget", current, local_key, remote_ms, remote_key) == target


def test_jump_target_ignores_a_skip_while_paused(catchup):
    # Skipping while paused moves the player but not the saved entry. The
    # account (the laptop's own older push) must not pull it back.
    assert catchup.call("jumpTarget", 125_757, 2_000, 110_757, 1_500) == -1


@pytest.mark.parametrize("own", [[110_757], [None, 110_757], [111_500], [110_757, 999]])
def test_jump_target_ignores_the_laptops_own_push(catchup, own):
    # Codex R1 #2: the pause push gets the server's (later) timestamp, so the
    # account looks newer than the local entry. After a skip while paused it
    # must still not pull the player back to the laptop's own position.
    assert catchup.call("jumpTarget", 125_757, 1_000, 110_757, 2_000, own) == -1


def test_jump_target_other_device_still_wins_with_own_values(catchup):
    assert catchup.call("jumpTarget", 125_757, 1_000, 1_684_289, 2_000, [110_757]) == 1_684_289
    assert catchup.call("jumpTarget", 125_757, 1_000, 1_684_289, 2_000, "junk") == 1_684_289

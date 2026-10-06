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


@pytest.mark.parametrize("own", [[110_757], [None, 110_757], [110_757, 999]])
def test_jump_target_ignores_the_laptops_own_push(catchup, own):
    # Codex R1 #2: the pause push gets the server's (later) timestamp, so the
    # account looks newer than the local entry. After a skip while paused it
    # must still not pull the player back to the laptop's own position.
    assert catchup.call("jumpTarget", 125_757, 1_000, 110_757, 2_000, own) == -1


def test_jump_target_other_device_still_wins_with_own_values(catchup):
    assert catchup.call("jumpTarget", 125_757, 1_000, 1_684_289, 2_000, [110_757]) == 1_684_289
    assert catchup.call("jumpTarget", 125_757, 1_000, 1_684_289, 2_000, "junk") == 1_684_289


@pytest.mark.parametrize("current,remote,own,target", [
    # Codex R2 #1: a genuine phone position near (not equal to) the laptop's
    # saved one still wins; only the exact pushed value is the laptop's echo.
    (115_000, 101_000, [None, 100_000], 101_000),
    (115_000, 100_001, [100_000], 100_001),
    (115_000, 98_500, [100_000, 100_000], 98_500),
])
def test_jump_target_own_match_is_exact(catchup, current, remote, own, target):
    assert catchup.call("jumpTarget", current, 1_000, remote, 2_000, own) == target


# ---- ⏯ decisions (Codex R2 #2: executable, not just wiring) ----

def press(catchup, **over):
    state = {"loaded": True, "playing": False, "waiting": False, "pendingResume": False,
             "needsRead": True, "prefetchUsable": False, "reading": False}
    state.update(over)
    return catchup.call("pressAction", state)


def test_press_actions(catchup):
    assert catchup.evaluate("[PRESS_NONE, PRESS_PAUSE, PRESS_CANCEL, PRESS_BUSY, PRESS_RESUME, "
                            "PRESS_PREFETCH, PRESS_READ, PRESS_WAIT]") == [
        "none", "pause", "cancel", "busy", "resume", "prefetch", "read", "wait"]
    assert press(catchup, loaded=False) == "none"
    assert press(catchup, playing=True) == "pause"
    assert press(catchup, playing=True, waiting=True) == "pause"
    # A second ⏯ while waiting cancels the resume.
    assert press(catchup, waiting=True) == "cancel"
    # A Library pick still reading its position decides where to play.
    assert press(catchup, pendingResume=True) == "busy"
    assert press(catchup, needsRead=False) == "resume"
    assert press(catchup, needsRead=False, pendingResume=True) == "busy"
    assert press(catchup, prefetchUsable=True) == "prefetch"
    assert press(catchup) == "read"
    # The drawer's prefetch is already in flight: wait for it, don't read twice.
    assert press(catchup, reading=True) == "wait"
    assert press(catchup, loaded=None) == "none"
    assert catchup.call("pressAction", None) == "none"


@pytest.mark.parametrize("waiting,read,result", [
    ("B1", "B1", True),
    # Cancelled (second ⏯, a pause, or a new pick cleared the wait): a late
    # read must not resume anything.
    ("", "B1", False),
    # A newer pick of another book: the old read never resumes the old book.
    ("B2", "B1", False),
    (None, "B1", False),
])
def test_read_done_resumes_only_the_waiting_book(catchup, waiting, read, result):
    assert catchup.call("readResumes", waiting, read) is result


@pytest.mark.parametrize("state,result", [
    ({"loaded": True, "sameBook": True, "playing": False, "storeLoaded": True, "hasRemote": True}, "compare"),
    # Unread state.json: resume in place, never compare (Codex R1 #3).
    ({"loaded": True, "sameBook": True, "playing": False, "storeLoaded": False, "hasRemote": True}, "resume"),
    # Timeout or failed read: resume in place.
    ({"loaded": True, "sameBook": True, "playing": False, "storeLoaded": True, "hasRemote": False}, "resume"),
    # The book changed or already plays: do nothing.
    ({"loaded": True, "sameBook": False, "playing": False, "storeLoaded": True, "hasRemote": True}, "none"),
    ({"loaded": True, "sameBook": True, "playing": True, "storeLoaded": True, "hasRemote": True}, "none"),
    ({"loaded": False, "sameBook": True, "playing": False, "storeLoaded": True, "hasRemote": True}, "none"),
    (None, "none"),
])
def test_resume_action(catchup, state, result):
    assert catchup.call("resumeAction", state) == result


# ---- the note after a jump (Chris, after the G3 hand check) ----

def test_note_constants(catchup):
    assert catchup.evaluate("NOTE_MS") == 5_000


@pytest.mark.parametrize("was,text", [
    ("16:24", "Continued from your other device (was 16:24)"),
    ("1:02:03", "Continued from your other device (was 1:02:03)"),
    ("", "Continued from your other device"),
    (None, "Continued from your other device"),
    (7, "Continued from your other device"),
])
def test_jump_note(catchup, was, text):
    assert catchup.call("jumpNote", was) == text

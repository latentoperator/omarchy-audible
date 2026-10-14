"""0.1.5 — the drawer's side of Audible's refusal: the held list and the banner.

``qml/lib/Held.js`` owns what a ``throttled`` ``get`` does to the shell's list
of waiting downloads, ``LibraryUi`` the ``paused`` row, and ``Drawer`` the
banner with the resume time. Pure logic, so it is tested here through
``tests/qjs.py``; ``Service.qml`` only wires them to the runner. The resume
clock is pinned to a timezone and a fixed ``now`` so "today" and "tomorrow" are
not decided by when the suite runs.
"""

from __future__ import annotations

import pathlib
import time

import pytest

import qjs
from omarchy_audible.catalog import build_catalog, fixture_items

REPO = pathlib.Path(__file__).resolve().parent.parent

A2 = "B0FAKE0002"
A3 = "B0FAKE0003"
A4 = "B0FAKE0004"

# The sentence the drawer shows, verbatim (0.1.5, ARCHITECTURE 4.2). The
# backend's `pause.THROTTLED_MESSAGE` is the same text; `tests/test_throttle.py`
# keeps the two in step.
THROTTLED_TEXT = "Audible is limiting downloads. Downloaded books still play."

UNTIL = "2027-01-15T12:00:00Z"
UNTIL_MS = 1_800_014_400_000  # the same instant, 2027-01-15T12:00:00Z
NOW_MS = UNTIL_MS - 3 * 3600 * 1000
# 2027-01-15T18:00:00Z, which is noon in America/Chicago: the clock the resume
# helper compares its day against.
CHICAGO_NOON_MS = 1_800_036_000_000

HELD_API = {
    "_p",
    "EFFECT_RELEASE",
    "EVENT_DROP",
    "EVENT_HOLD",
    "EVENT_NOW",
    "EVENT_STATUS",
    "EVENT_THROTTLED",
    "create",
    "has",
    "paused",
    "same",
    "step",
    "until",
    "wakeInMs",
}


@pytest.fixture(scope="module")
def held() -> qjs.JsModule:
    return qjs.load("Held")


@pytest.fixture(scope="module")
def ui() -> qjs.JsModule:
    return qjs.load("LibraryUi")


@pytest.fixture(scope="module")
def library() -> qjs.JsModule:
    return qjs.load("Library")


@pytest.fixture(scope="module")
def playback() -> qjs.JsModule:
    return qjs.load("Playback")


@pytest.fixture(scope="module")
def catalog() -> dict:
    built, _covers = build_catalog(
        fixture_items(), marketplace="us", synced_at="2026-10-05T00:00:00Z"
    )
    return built


@pytest.fixture
def chicago(monkeypatch):
    """``America/Chicago`` for the whole test, restored afterwards."""
    monkeypatch.setenv("TZ", "America/Chicago")
    time.tzset()
    yield "America/Chicago"
    time.tzset()


def _row(library: qjs.JsModule, catalog: dict, asin: str, state: str) -> dict:
    """A catalog row in `state`, the way the service builds it (§5.3)."""
    job_states = ("queued", "downloading", "converting", "error", "paused")
    jobs = [{"asin": asin, "state": state}] if state in job_states else None
    # `local` is the filesystem scan, not a job.
    local = (
        [{"asin": asin, "size": 100, "downloaded_at": "2026-01-01T00:00:00Z"}]
        if state == "local"
        else None
    )
    rows = library.call("buildRows", catalog, None, None, local, jobs)
    return next(row for row in rows if row["asin"] == asin)


# --- Held.js: what waits, and when it goes (ARCHITECTURE 4.8) -----------------


def test_the_held_module_exports_its_surface(held):
    assert set(held.functions) == HELD_API
    assert held.evaluate("EVENT_THROTTLED") == "throttled"
    assert held.evaluate("EFFECT_RELEASE") == "release"


def test_a_fresh_held_list_is_empty_and_not_paused(held):
    state = held.call("create")
    assert state == {"asins": [], "until": ""}
    assert held.call("has", state, A2) is False
    assert held.call("until", state) == ""
    assert held.call("paused", state, NOW_MS) is False
    assert held.call("wakeInMs", state, NOW_MS) == 0
    assert held.call("same", state, {"asins": [], "until": ""}) is True


@pytest.mark.parametrize(
    ("state", "now", "expected"),
    [
        ({"asins": [A2], "until": UNTIL}, UNTIL_MS - 1, True),
        ({"asins": [A2], "until": UNTIL}, UNTIL_MS, False),
        ({"asins": [A2], "until": UNTIL}, UNTIL_MS + 1, False),
        # An unusable instant is not a pause: downloads run, and Audible says
        # no again if it must.
        ({"asins": [A2], "until": "nonsense"}, NOW_MS, False),
        ({"asins": [A2], "until": ""}, NOW_MS, False),
        ({"asins": [A2]}, NOW_MS, False),
        (None, NOW_MS, False),
    ],
)
def test_paused_is_only_true_before_the_deadline(held, state, now, expected):
    assert held.call("paused", state, now) is expected


def test_a_pick_while_paused_holds_the_book(held):
    out = held.call(
        "step", held.call("create"), {"type": "hold", "asins": [A2], "until": UNTIL}
    )
    assert out == {"state": {"asins": [A2], "until": UNTIL}, "effects": []}

    # Holding again (or the same book twice) keeps one entry and the order.
    again = held.call(
        "step", out["state"], {"type": "hold", "asins": [A2, A3], "until": UNTIL}
    )
    assert again["state"]["asins"] == [A2, A3]
    assert held.call("has", again["state"], A2) is True
    assert held.call("has", again["state"], A4) is False


def test_a_throttled_refusal_holds_the_book_and_everything_queued(held):
    """The refused book first, then the `get`s that were waiting behind it."""
    out = held.call(
        "step",
        held.call("create"),
        {"type": "throttled", "asin": A4, "queued": [A2, A3], "until": UNTIL},
    )
    assert out["state"] == {"asins": [A4, A2, A3], "until": UNTIL}
    assert out["effects"] == []

    # A second refusal keeps the order it already had.
    more = held.call(
        "step",
        out["state"],
        {"type": "throttled", "asin": A3, "queued": [], "until": UNTIL},
    )
    assert more["state"]["asins"] == [A4, A2, A3]


def test_a_held_books_cancel_drops_only_that_book(held):
    state = {"asins": [A2, A3], "until": UNTIL}
    out = held.call("step", state, {"type": "drop", "asin": A2})
    assert out == {"state": {"asins": [A3], "until": UNTIL}, "effects": []}
    # Dropping one that is not held changes nothing, and keeps the pause.
    assert (
        held.call("step", out["state"], {"type": "drop", "asin": A2})["state"]
        == out["state"]
    )


def test_the_pause_is_the_authority_a_status_release_and_one_that_holds(held):
    state = {"asins": [A2, A3], "until": UNTIL}

    # Still running: nothing moves.
    running = held.call(
        "step", state, {"type": "status", "until": UNTIL, "now": NOW_MS}
    )
    assert running == {"state": state, "effects": []}

    # The backend no longer reports a pause — the timeout passed, or a
    # successful get cleared it — so the held books go, in order, once.
    over = held.call("step", state, {"type": "status", "until": None, "now": NOW_MS})
    assert over["state"] == {"asins": [], "until": ""}
    assert over["effects"] == [{"kind": "release", "asins": [A2, A3]}]

    # A `status` with a fresh, later time holds them again.
    extended = held.call(
        "step", over["state"], {"type": "status", "until": UNTIL, "now": NOW_MS}
    )
    assert extended["effects"] == []
    assert extended["state"]["asins"] == []


def test_the_deadlines_own_wake_releases_the_held_downloads(held):
    state = {"asins": [A2, A3], "until": UNTIL}
    # The wake fired while the `status` read was still in flight.
    out = held.call("step", state, {"type": "now", "now": UNTIL_MS + 1})
    assert out["effects"] == [{"kind": "release", "asins": [A2, A3]}]
    assert out["state"] == {"asins": [], "until": ""}

    # An instant before the deadline changes nothing.
    early = held.call("step", state, {"type": "now", "now": UNTIL_MS - 1})
    assert early == {"state": state, "effects": []}

    # Nothing held, nothing to release.
    empty = held.call(
        "step", held.call("create"), {"type": "now", "now": UNTIL_MS + 10**9}
    )
    assert empty["effects"] == []


def test_the_wake_timer_lands_just_past_the_deadline(held):
    state = {"asins": [A2], "until": UNTIL}
    assert held.call("wakeInMs", state, NOW_MS) == UNTIL_MS - NOW_MS + 1000
    # A deadline that has just gone by wakes in a second rather than never.
    assert held.call("wakeInMs", state, UNTIL_MS + 5 * 60 * 1000) == 1000
    assert held.call("wakeInMs", {"asins": [A2], "until": "nonsense"}, NOW_MS) == 0
    assert held.call("wakeInMs", {"asins": [A2], "until": ""}, NOW_MS) == 0


def test_same_compares_the_books_in_order_and_the_deadline(held):
    one = {"asins": [A2, A3], "until": UNTIL}
    assert held.call("same", one, {"asins": [A2, A3], "until": UNTIL}) is True
    assert held.call("same", one, {"asins": [A3, A2], "until": UNTIL}) is False
    assert held.call("same", one, {"asins": [A2], "until": UNTIL}) is False
    assert held.call("same", one, {"asins": [A2, A3], "until": ""}) is False
    assert held.call("same", None, held.call("create")) is True


def test_an_unknown_or_broken_event_changes_nothing(held):
    state = {"asins": [A2], "until": UNTIL}
    assert held.call("step", state, {"type": "mystery"}) == {
        "state": state,
        "effects": [],
    }
    assert held.call("step", state, None) == {"state": state, "effects": []}
    assert held.call("step", state, "hold") == {"state": state, "effects": []}
    assert held.call("step", None, {"type": "hold", "asins": [A2], "until": UNTIL})[
        "state"
    ] == {
        "asins": [A2],
        "until": UNTIL,
    }


# --- the rows and their badge (ARCHITECTURE 5.3) ------------------------------


def test_a_held_download_is_a_paused_row(library, ui, catalog):
    row = _row(library, catalog, A2, "paused")
    assert row["state"] == "paused"
    assert ui.call("badge", row, None, False) == {"kind": "paused", "label": "Waiting"}
    assert ui.evaluate("BADGE_PAUSED") == "paused"
    # A held download can still be cancelled, and picking it does nothing: it
    # is already on its way, as soon as the pause passes.
    assert ui.call("canCancel", row) is True
    assert ui.call("primaryAction", row, False) == "none"
    assert ui.call("pickDecision", row, False, "") == "none"
    # Held is not failed, even with the network down.
    assert ui.call("badge", row, None, True)["kind"] == "paused"


def test_a_held_book_is_a_paused_job_and_not_a_failure(playback):
    pending = [{"command": "get", "asin": A3}, {"command": "sync", "asin": None}]
    active = {"command": "get", "asin": A2}
    out = playback.call("jobStates", pending, active, {"stage": "download"}, {}, [A4])
    assert out == [
        {"asin": A3, "state": "queued"},
        {"asin": A2, "state": "downloading"},
        {"asin": A4, "state": "paused"},
    ]

    # A held book never shows as failed, even if an earlier attempt failed.
    failures = {A4: "boom"}
    assert playback.call("jobStates", [], None, None, failures, [A4]) == [
        {"asin": A4, "state": "paused"}
    ]
    # And a throttled outcome clears a remembered failure instead of setting
    # one: the book is waiting, not broken (0.1.5).
    job = {"command": "get", "asin": A4}
    assert (
        playback.call(
            "updateFailures",
            failures,
            job,
            {"ok": False, "code": "throttled", "message": "x"},
        )
        == {}
    )
    assert playback.call(
        "updateFailures", {}, job, {"ok": False, "code": "network", "message": "x"}
    ) == {A4: "x"}


def test_a_paused_row_does_not_change_the_other_states(library, ui, catalog):
    for state in ("queued", "downloading", "converting", "local", "error", "cloud"):
        row = _row(library, catalog, A2, state)
        assert row["state"] == state
        assert ui.call("canCancel", row) is (state in ("queued", "downloading"))


# --- the banner (ARCHITECTURE 6) ----------------------------------------------


def test_the_paused_banner_outranks_the_offline_and_syncing_notes(ui):
    base = {
        "catalogLoaded": True,
        "total": 5,
        "shown": 5,
        "offline": True,
        "syncing": True,
        "paused": True,
    }
    assert ui.call("listState", base) == {"state": "list", "banner": "paused"}
    # Reconnect and the connection problem still come first: those are why
    # nothing is loading at all.
    assert (
        ui.call("listState", {**base, "connectionProblem": True})["banner"]
        == "connection"
    )
    assert (
        ui.call("listState", {**base, "errorCode": "auth_failed"})["banner"]
        == "reconnect"
    )
    # Not paused: the usual order.
    assert ui.call("listState", {**base, "paused": False})["banner"] == "offline"
    assert (
        ui.call("listState", {**base, "paused": False, "offline": False})["banner"]
        == "syncing"
    )


def test_the_paused_banner_is_urgent():
    drawer = qjs.load("Drawer")
    assert drawer.call("bannerUrgent", "paused") is True
    assert drawer.call("bannerUrgent", "connection") is True
    assert drawer.call("bannerUrgent", "offline") is False
    assert drawer.call("bannerUrgent", "syncing") is False


@pytest.mark.parametrize(
    ("iso", "expected"),
    [
        # Noon in Chicago, and a pause that ends at 21:40 the same day.
        ("2027-01-16T03:40:00Z", "at 9:40 PM"),
        # The next calendar day, just after midnight.
        ("2027-01-16T06:05:00Z", "tomorrow at 12:05 AM"),
        ("2027-01-16T15:40:00Z", "tomorrow at 9:40 AM"),
        # Noon and half past, so the AM/PM boundary is covered.
        ("2027-01-15T18:00:00Z", "at 12:00 PM"),
        ("2027-01-15T18:30:00Z", "at 12:30 PM"),
    ],
)
def test_the_resume_clock_says_the_day_it_falls_on(chicago, iso, expected):
    assert qjs.load("Format").call("resumeAt", iso, CHICAGO_NOON_MS) == expected


@pytest.mark.parametrize("value", ["", None, "nonsense", 7, "2027-13-45T99:99:99Z"])
def test_the_resume_clock_is_empty_for_an_unusable_instant(chicago, value):
    assert qjs.load("Format").call("resumeAt", value, CHICAGO_NOON_MS) == ""


@pytest.mark.parametrize(
    "until,when",
    [
        ("2027-01-15T20:00:00Z", "at 2:00 PM"),
        ("2027-01-16T03:40:00Z", "at 9:40 PM"),
        ("2027-01-16T15:40:00Z", "tomorrow at 9:40 AM"),
        ("2027-01-16T06:00:00Z", "tomorrow at 12:00 AM"),
    ],
)
def test_the_paused_banner_has_one_deadline_derived_retry(chicago, until, when):
    text = qjs.load("Drawer").call("pausedBanner", until, CHICAGO_NOON_MS)
    assert text == (
        THROTTLED_TEXT
        + " Waiting downloads will retry automatically "
        + when
        + ". Audible may still limit the retry."
    )
    assert "Try again tomorrow" not in text
    assert "Downloads resume" not in text
    assert "restart" not in text


@pytest.mark.parametrize("until", ["", None, "nonsense", 7])
def test_unknown_retry_deadline_has_safe_fallback(chicago, until):
    assert qjs.load("Drawer").call("pausedBanner", until, CHICAGO_NOON_MS) == (
        THROTTLED_TEXT
        + " Waiting downloads will retry automatically when the pause ends."
        + " Retry time is unavailable. Audible may still limit the retry."
    )


def test_the_throttled_error_text_is_exact():
    onboarding = qjs.load("Onboarding")
    assert onboarding.evaluate("THROTTLED_TEXT") == THROTTLED_TEXT
    assert onboarding.call("errorText", "throttled") == {
        "title": "Audible is limiting downloads",
        "body": THROTTLED_TEXT,
        "reconnect": False,
    }

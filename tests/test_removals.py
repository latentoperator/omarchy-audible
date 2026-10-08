"""P9 PR 4 — `qml/Removals.qml` and the pending-unload reducer `Unload.step` (F17, P8 nit 3).

The reducer and the job gate are tested through QJSEngine; the rest checks the wiring in the QML,
which the QJSEngine tests can't load.
"""

from __future__ import annotations

import pathlib
import re

import pytest

import qjs

REPO = pathlib.Path(__file__).resolve().parent.parent
USER, AUTO, AUTO_UNLOADED = "user", "autoremove", "autoremove-unloaded"
TIMER_ON = {"type": "timer", "on": True}
TIMER_OFF = {"type": "timer", "on": False}


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
def unload() -> qjs.JsModule:
    return qjs.load("Unload")


def step(unload, pending, event):
    return unload.call("step", pending, event)


def entry(asin, purpose=USER):
    return {"asin": asin, "purpose": purpose}


def test_the_api(unload):
    assert unload.functions == sorted(
        [
            "PURPOSE_AUTO",
            "PURPOSE_AUTO_UNLOADED",
            "PURPOSE_USER",
            "_p",
            "asins",
            "jobAllowed",
            "step",
        ]
    )
    assert unload.evaluate("[PURPOSE_USER, PURPOSE_AUTO, PURPOSE_AUTO_UNLOADED]") == [
        USER,
        AUTO,
        AUTO_UNLOADED,
    ]


# ---- add ----


def test_add_waits_and_starts_the_timer(unload):
    out = step(unload, [], {"type": "add", "asin": "A", "purpose": USER})
    assert out == {"pending": [entry("A")], "effects": [TIMER_ON]}
    assert unload.call("asins", out["pending"]) == ["A"]


def test_add_twice_keeps_one_entry_and_restarts_the_timer(unload):
    out = step(unload, [entry("A")], {"type": "add", "asin": "A", "purpose": USER})
    assert out == {"pending": [entry("A")], "effects": [TIMER_ON]}


def test_a_users_remove_wins_over_a_waiting_auto_one(unload):
    out = step(
        unload, [entry("A", AUTO)], {"type": "add", "asin": "A", "purpose": USER}
    )
    assert out["pending"] == [entry("A")]
    # ...but an auto-remove never downgrades a user's.
    out = step(unload, [entry("A")], {"type": "add", "asin": "A", "purpose": AUTO})
    assert out["pending"] == [entry("A")]


@pytest.mark.parametrize(
    "event",
    [
        {"type": "add", "asin": "", "purpose": USER},
        {"type": "add", "asin": None, "purpose": USER},
        {"type": "add", "asin": "A", "purpose": "other"},
        {"type": "add", "asin": "A", "purpose": AUTO_UNLOADED},
    ],
)
def test_a_bad_add_changes_nothing(unload, event):
    assert step(unload, [entry("B")], event) == {"pending": [entry("B")], "effects": []}


# ---- intent ----


def test_a_new_intent_drops_the_book(unload):
    out = step(unload, [entry("A"), entry("B")], {"type": "intent", "asin": "A"})
    assert out == {"pending": [entry("B")], "effects": []}
    out = step(unload, [entry("B")], {"type": "intent", "asin": "B"})
    assert out == {"pending": [], "effects": [TIMER_OFF]}


# ---- unloaded ----


def test_unloaded_removes_what_is_no_longer_busy(unload):
    out = step(
        unload,
        [entry("A"), entry("B")],
        {"type": "unloaded", "busy": ["B", ""], "autoRemove": False},
    )
    assert out == {
        "pending": [entry("B")],
        "effects": [{"type": "run", "asin": "A", "purpose": USER}],
    }
    out = step(
        unload, [entry("B")], {"type": "unloaded", "busy": [""], "autoRemove": False}
    )
    assert out == {
        "pending": [],
        "effects": [TIMER_OFF, {"type": "run", "asin": "B", "purpose": USER}],
    }


def test_nit3_an_auto_remove_stays_an_auto_remove_after_the_unload(unload):
    out = step(
        unload, [entry("A", AUTO)], {"type": "unloaded", "busy": [], "autoRemove": True}
    )
    assert out == {
        "pending": [],
        "effects": [
            TIMER_OFF,
            {"type": "log", "text": "auto-remove A"},
            {"type": "run", "asin": "A", "purpose": AUTO_UNLOADED},
        ],
    }


def test_nit3_turning_auto_remove_off_before_the_flush_cancels_it(unload):
    pending = [entry("A", AUTO), entry("B")]
    out = step(unload, pending, {"type": "unloaded", "busy": [], "autoRemove": False})
    assert out == {
        "pending": [],
        "effects": [
            TIMER_OFF,
            {"type": "log", "text": "auto-remove of A cancelled: the setting is off"},
            # A user's Remove is not affected.
            {"type": "run", "asin": "B", "purpose": USER},
        ],
    }


# ---- timeout ----


def test_timeout_gives_up_on_every_book(unload):
    out = step(unload, [entry("A"), entry("B", AUTO)], {"type": "timeout"})
    assert out == {
        "pending": [],
        "effects": [
            {"type": "log", "text": "skipped A: the player did not unload it"},
            {"type": "log", "text": "skipped B: the player did not unload it"},
        ],
    }


@pytest.mark.parametrize("pending", [None, "x", [None, {"asin": 3}, {"asin": "A"}]])
@pytest.mark.parametrize("event", [None, {}, {"type": "nope"}, "add"])
def test_bad_input_never_throws(unload, pending, event):
    assert step(unload, pending, event) == {"pending": [], "effects": []}


# ---- the job gate ----


def remove_job(purpose, asin="A"):
    return {"command": "remove", "args": [asin], "purpose": purpose}


@pytest.mark.parametrize(
    "job,auto,at_end,playing,busy,allowed",
    [
        # Not a removal: always runs.
        (
            {"command": "sync", "args": [], "purpose": ""},
            False,
            False,
            True,
            ["A"],
            True,
        ),
        (None, False, False, False, [], True),
        # A user's removal: not while the book is busy again.
        (remove_job(USER), False, False, False, [], True),
        (remove_job(USER), False, False, False, ["A"], False),
        # An auto-remove of the loaded book: setting, at its end, stopped.
        (remove_job(AUTO), True, True, False, [], True),
        (remove_job(AUTO), False, True, False, [], False),
        (remove_job(AUTO), True, False, False, [], False),
        (remove_job(AUTO), True, True, True, [], False),
        # After the unload `atEnd` is false: the setting and not busy (nit 3).
        (remove_job(AUTO_UNLOADED), True, False, False, [], True),
        (remove_job(AUTO_UNLOADED), False, False, False, [], False),
        (remove_job(AUTO_UNLOADED), True, False, False, ["A"], False),
        # A remove with no known purpose runs as before.
        (remove_job(""), False, False, False, ["A"], True),
    ],
)
def test_job_allowed(unload, job, auto, at_end, playing, busy, allowed):
    assert unload.call("jobAllowed", job, auto, at_end, playing, busy) is allowed


# ---- wiring ----


def test_removals_owns_the_list_and_its_timers():
    removals = read("qml/Removals.qml")
    service = read("Service.qml")
    # The pending list changes only through Unload.step.
    assert removals.count("pending = ") == 1
    assert "pending = result.pending" in function_body(removals, "apply")
    for name in ("unloadThenRemove", "dropIntent", "flush", "abandon"):
        assert "apply(Unload.step(pending, " in function_body(removals, name), name
    assert "id: unloadTimer" in removals and "id: autoRemoveTimer" in removals
    for gone in (
        "unloadTimer",
        "autoRemoveTimer",
        "removeCandidate",
        "flushRemovals",
        "abandonRemovals",
        "removeIfStillFinished",
        "function jobAllowed",
    ):
        assert gone not in service, gone
    assert service.count("Removals {") == 1
    block = service[service.index("  Removals {") :]
    block = block[: block.index("\n  }\n") + 1]
    for line in ("id: removals", "service: root", "player: player", "library: library"):
        assert f"    {line}\n" in block, line
    assert "gate: removals.jobAllowed" in service


def test_service_keeps_the_names_views_use():
    service = read("Service.qml")
    assert "readonly property var removeAfterUnload: removals.waiting" in service
    assert "function removeAll() { return removals.removeAll() }" in service
    body = function_body(service, "removeBook")
    assert (
        "if (asin === loadedAsin) return removals.unloadThenRemove(asin, "
        "purpose === Unload.PURPOSE_AUTO ? purpose : Unload.PURPOSE_USER)"
    ) in body
    # Everyone else's removeBook is the user's.
    assert 'return run("remove", [asin], "user")' in body
    for view in (
        "qml/views/LibraryView.qml",
        "qml/views/FullView.qml",
        "qml/ServiceIpc.qml",
    ):
        calls = re.findall(r"removeBook\(([^)]*)\)", read(view))
        assert calls and all("," not in c for c in calls), view


def test_the_service_hands_over_at_the_right_moments():
    service = read("Service.qml")
    assert "removals.flush()" in service[service.index("onLoadedAsinChanged") :][:120]
    assert "removals.dropIntent(asin)" in function_body(service, "noteIntent")
    finished = function_body(service, "checkFinished")
    assert finished.index("store.markFinished(asin)") < finished.index(
        "removals.noteFinished(asin)"
    )
    removals = read("qml/Removals.qml")
    assert "if (!service.autoRemoveFinished) return" in function_body(
        removals, "noteFinished"
    )

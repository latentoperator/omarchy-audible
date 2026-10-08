"""P9 PR 7 — PositionSync's sequencing decisions are `Sync.step` vectors."""

from __future__ import annotations

import pathlib

import pytest

import qjs

REPO = pathlib.Path(__file__).resolve().parents[1]
AT = "2026-10-05T14:00:00Z"


@pytest.fixture(scope="module")
def sync() -> qjs.JsModule:
    return qjs.load("Sync")


def entry(asin: str, ms: int = 1000, at: str = AT) -> dict:
    return {"asin": asin, "ms": ms, "at": at}


def step(sync, state, **event):
    out = sync.call("step", state, event)
    return out["state"], out["effects"]


def test_batch_drops_remote_newer_entry_and_sends_remaining_entries(sync):
    queue = [entry("A"), entry("B"), entry("C")]
    state, effects = step(sync, sync.call("createState"), type="flush", queue=queue)
    assert effects == [
        {
            "type": "run",
            "command": "position-get",
            "args": ["A", "B", "C"],
            "purpose": "flush",
        }
    ]

    state, effects = step(
        sync,
        state,
        type="positions",
        purpose="flush",
        queue=queue,
        items={"B": {"ms": 1500, "updated_at": "2026-10-05T15:00:00Z"}},
    )
    assert effects == [{"type": "setQueue", "queue": [entry("A"), entry("C")]}]
    state, effects = step(
        sync,
        state,
        type="finished",
        job={"purpose": "flush"},
        outcome={"ok": True},
        queue=[entry("A"), entry("C")],
    )
    assert effects == [
        {
            "type": "run",
            "command": "position-push",
            "args": ["A", "1000", "--at", AT],
            "purpose": "push",
        }
    ]
    state, effects = step(
        sync,
        state,
        type="finished",
        job={"purpose": "push"},
        outcome={"ok": True},
        queue=[entry("A"), entry("C")],
    )
    assert effects[0] == {"type": "setQueue", "queue": [entry("C")]}
    assert effects[1]["args"] == ["C", "1000", "--at", AT]
    state, effects = step(
        sync,
        state,
        type="finished",
        job={"purpose": "push"},
        outcome={"ok": True},
        queue=[entry("C")],
    )
    assert effects == [
        {"type": "setQueue", "queue": []},
        {"type": "finish", "result": "done"},
    ]
    assert state["failedFlushes"] == 0
    assert state["lastPushed"] == {"A": 1000, "C": 1000}


def test_newer_listening_replaces_old_plan_entry_before_any_push(sync):
    old, newer, other = (
        entry("A", 1000),
        entry("A", 2500, "2026-10-05T14:05:00Z"),
        entry("B"),
    )
    state, _ = step(sync, sync.call("createState"), type="flush", queue=[old, other])
    state, effects = step(
        sync,
        state,
        type="positions",
        purpose="flush",
        queue=[old, other],
        items={},
    )
    assert effects == []
    state, effects = step(
        sync,
        state,
        type="finished",
        job={"purpose": "flush"},
        outcome={"ok": True},
        queue=[newer, other],
    )
    assert effects == [
        {
            "type": "run",
            "command": "position-push",
            "args": ["B", "1000", "--at", AT],
            "purpose": "push",
        }
    ]
    assert state["progressed"] is True


def test_stale_count_increments_and_success_resets_it(sync):
    state = sync.call("createState")
    for expected in (1, 2):
        state, _ = step(sync, state, type="flush", queue=[entry("A")])
        state, _ = step(
            sync, state, type="positions", purpose="flush", queue=[entry("A")], items={}
        )
        state, effects = step(
            sync,
            state,
            type="finished",
            job={"purpose": "flush"},
            outcome={"ok": True},
            queue=[entry("A")],
        )
        assert effects[0]["type"] == "run"
        state, effects = step(
            sync,
            state,
            type="finished",
            job={"purpose": "push"},
            outcome={"ok": False, "code": "stale"},
            queue=[entry("A")],
        )
        assert state["staleCount"] == expected
        assert effects[0]["type"] == "setQueue"
    state, _ = step(sync, state, type="flush", queue=[entry("A")])
    state, _ = step(
        sync, state, type="positions", purpose="flush", queue=[entry("A")], items={}
    )
    state, _ = step(
        sync,
        state,
        type="finished",
        job={"purpose": "flush"},
        outcome={"ok": True},
        queue=[entry("A")],
    )
    state, _ = step(
        sync,
        state,
        type="finished",
        job={"purpose": "push"},
        outcome={"ok": True},
        queue=[entry("A")],
    )
    assert state["staleCount"] == 0


def test_offline_backoff_and_reset(sync):
    state, _ = step(sync, sync.call("createState"), type="flush", queue=[entry("A")])
    state, effects = step(
        sync,
        state,
        type="finished",
        job={"purpose": "flush"},
        outcome={"ok": False, "code": "network"},
        queue=[entry("A")],
    )
    assert effects == [{"type": "finish", "result": "offline"}]
    assert state["failedFlushes"] == 1
    assert sync.call("retryDelayMs", state["failedFlushes"]) == 120000
    state, _ = step(sync, state, type="reset_retry")
    assert state["failedFlushes"] == 0
    assert sync.call("retryDelayMs", state["failedFlushes"]) == 60000


def test_refused_run_finishes_without_removing_the_queued_position(sync):
    queue = [entry("A")]
    state, _ = step(sync, sync.call("createState"), type="flush", queue=queue)
    state, effects = step(sync, state, type="refused", purpose="flush", queue=queue)
    assert effects == [{"type": "finish", "result": "refused"}]
    assert state["lastResult"] == "refused"
    assert state["failedFlushes"] == 1
    assert queue == [entry("A")]


def test_batch_boundary_reads_only_25_and_schedules_the_remaining_entry(sync):
    queue = [entry(f"B{i:02d}") for i in range(26)]
    state, effects = step(sync, sync.call("createState"), type="flush", queue=queue)
    assert len(effects[0]["args"]) == 25
    state, _ = step(
        sync, state, type="positions", purpose="flush", queue=queue, items={}
    )
    state, effects = step(
        sync,
        state,
        type="finished",
        job={"purpose": "flush"},
        outcome={"ok": True},
        queue=queue,
    )
    assert effects[0]["args"] == ["B00", "1000", "--at", AT]
    remaining = queue
    state, effects = step(
        sync,
        state,
        type="finished",
        job={"purpose": "push"},
        outcome={"ok": True},
        queue=remaining,
    )
    while any(effect["type"] == "run" for effect in effects):
        queue_effect = next(
            (effect for effect in effects if effect["type"] == "setQueue"), None
        )
        if queue_effect is not None:
            remaining = queue_effect["queue"]
        # Model the caller applying setQueue before the next finished event.
        state, effects = step(
            sync,
            state,
            type="finished",
            job={"purpose": "push"},
            outcome={"ok": True},
            queue=remaining,
        )
    assert effects == [
        {"type": "setQueue", "queue": [entry("B25")]},
        {"type": "finish", "result": "done"},
        {"type": "flush_later"},
    ]


@pytest.mark.parametrize(
    "state,event",
    [
        (None, None),
        ("bad", {}),
        ({}, "flush"),
        ({"flushing": True}, {"type": "flush", "queue": []}),
        ([], {"type": "finished"}),
    ],
)
def test_bad_input_never_throws(sync, state, event):
    assert isinstance(sync.call("step", state, event), dict)


def test_step_does_not_mutate_its_input_state(sync):
    state = sync.call("createState")
    before = dict(state)
    next_state, _ = step(sync, state, type="flush", queue=[entry("A")])
    assert state == before
    assert next_state["flushing"] is True


def test_positionsync_applies_every_effect_type():
    source = (REPO / "qml" / "PositionSync.qml").read_text(encoding="utf-8")
    body = source[source.index("function apply(") : source.index("\n  function flush(")]
    assert "var transition = Sync.step(reducerState, event)" in body
    assert body.count("reducerState = transition.state") == 1
    for effect in ("run", "setQueue", "flush_later", "finish"):
        assert f'effect.type === "{effect}"' in body
    assert 'apply({ "type": "refused"' in body

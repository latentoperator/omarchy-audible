"""P4a — ``qml/lib/Positions.js`` in PySide6's ``QJSEngine``.

The same shared vector file as ``test_position_vectors.py`` (the Python side),
plus the push rules: ``resumeMs``, ``shouldPush``, ``enqueue``, ``flushPlan``,
``isFinished`` and ``autoRemoveAllowed`` (ARCHITECTURE 4.6, PLAN P4a).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import qjs

VECTORS_PATH = Path(__file__).resolve().parent / "fixtures" / "position-vectors.json"
VECTORS = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
PARSE_CASES = VECTORS["parse_updated_at"]
MERGE_CASES = VECTORS["merge"]

ASIN = "B00FAKE01"
OTHER = "B00FAKE02"

EXPECTED_API = {
    "FINISH_TRAILING_MS",
    "_p",
    "autoRemoveAllowed",
    "enqueue",
    "flushPlan",
    "isFinished",
    "merge",
    "parseUpdatedAt",
    "resumeMs",
    "shouldPush",
}


@pytest.fixture(scope="module")
def module() -> qjs.JsModule:
    return qjs.load("Positions")


def entry(ms: int, updated_at: str | None) -> dict:
    return {"ms": ms, "updated_at": updated_at}


def push(asin: str, ms: int, at: str | None) -> dict:
    return {"asin": asin, "ms": ms, "at": at}


# --- API ---------------------------------------------------------------------
def test_exports_the_expected_api(module: qjs.JsModule) -> None:
    assert set(module.functions) == EXPECTED_API


def test_finish_trailing_constant(module: qjs.JsModule) -> None:
    assert module.evaluate("FINISH_TRAILING_MS") == 30000


# --- the shared vectors (both engines must agree) ----------------------------
@pytest.mark.parametrize("case", PARSE_CASES, ids=[case["name"] for case in PARSE_CASES])
def test_parse_updated_at_matches_the_vector(module: qjs.JsModule, case: dict) -> None:
    assert module.call("parseUpdatedAt", case["value"]) == case["epoch_ms"]


@pytest.mark.parametrize("case", MERGE_CASES, ids=[case["name"] for case in MERGE_CASES])
def test_merge_matches_the_vector(module: qjs.JsModule, case: dict) -> None:
    assert module.call("merge", case["local"], case["remote"]) == case["expected"]


# --- resumeMs (ARCHITECTURE 4.6 merge rule) ----------------------------------
def test_resume_takes_the_newer_remote(module: qjs.JsModule) -> None:
    local = entry(1000, "2026-01-01 00:00:00.0")
    remote = entry(2000, "2026-01-02 00:00:00.0")
    assert module.call("resumeMs", local, remote) == 2000
    assert module.call("resumeMs", remote, local) == 2000


def test_resume_keeps_the_newer_local(module: qjs.JsModule) -> None:
    local = entry(2000, "2026-01-02 00:00:00.0")
    remote = entry(1000, "2026-01-01 00:00:00.0")
    assert module.call("resumeMs", local, remote) == 2000


def test_resume_survives_missing_entries(module: qjs.JsModule) -> None:
    local = entry(1500, "2026-01-01T00:00:00Z")
    assert module.call("resumeMs", local, None) == 1500
    assert module.call("resumeMs", None, local) == 1500
    assert module.call("resumeMs", None, None) == 0
    assert module.call("resumeMs", "junk", "junk") == 0


# --- shouldPush (D4: local listening only, ARCHITECTURE 4.6) -----------------
def test_should_push_false_for_a_book_never_played_locally(module: qjs.JsModule) -> None:
    book = {
        "ms": 5000,
        "updated_at": "2026-02-01 00:00:00.0",
        "last_played_at": None,
        "played_since_download": False,
        "finished": False,
    }
    assert module.call("shouldPush", book) is False


def test_should_push_false_without_a_position(module: qjs.JsModule) -> None:
    assert module.call("shouldPush", {"played_since_download": True, "ms": 0}) is False
    assert module.call("shouldPush", {"played_since_download": True}) is False
    assert module.call("shouldPush", {"played_since_download": True, "ms": "nope"}) is False
    assert module.call("shouldPush", None) is False
    assert module.call("shouldPush", "junk") is False


def test_should_push_true_when_played_and_never_pushed(module: qjs.JsModule) -> None:
    book = {"ms": 5000, "played_since_download": True, "updated_at": "2026-02-01 00:00:00.0"}
    assert module.call("shouldPush", book) is True


def test_should_push_true_when_the_position_moved_since_the_last_push(
    module: qjs.JsModule,
) -> None:
    book = {"ms": 9000, "last_pushed_ms": 5000, "played_since_download": True}
    assert module.call("shouldPush", book) is True


def test_should_push_false_when_the_position_is_unchanged(module: qjs.JsModule) -> None:
    book = {"ms": 5000, "last_pushed_ms": 5000, "played_since_download": True}
    assert module.call("shouldPush", book) is False
    # A never-pushed marker of 0 does not block a real position.
    assert (
        module.call(
            "shouldPush",
            {"ms": 5000, "last_pushed_ms": 0, "played_since_download": True},
        )
        is True
    )


# --- enqueue (one newest entry per asin, ARCHITECTURE 3 push_queue) ----------
def test_enqueue_adds_an_entry(module: qjs.JsModule) -> None:
    queue = module.call("enqueue", [], push(ASIN, 1000, "2026-01-01T00:00:00Z"))
    assert queue == [{"asin": ASIN, "ms": 1000, "at": "2026-01-01T00:00:00Z"}]


def test_enqueue_keeps_the_newest_per_asin(module: qjs.JsModule) -> None:
    queue = []
    queue = module.call("enqueue", queue, push(ASIN, 1000, "2026-01-01T00:00:00Z"))
    queue = module.call("enqueue", queue, push(OTHER, 10, "2026-01-01T00:00:00Z"))
    queue = module.call("enqueue", queue, push(ASIN, 2000, "2026-01-02T00:00:00Z"))
    queue = module.call("enqueue", queue, push(ASIN, 3000, "2026-01-03T00:00:00Z"))
    assert queue == [
        {"asin": ASIN, "ms": 3000, "at": "2026-01-03T00:00:00Z"},
        {"asin": OTHER, "ms": 10, "at": "2026-01-01T00:00:00Z"},
    ]


def test_enqueue_offline_pushes_accumulate_one_per_asin(module: qjs.JsModule) -> None:
    queue: list[dict] = []
    for index in range(1, 6):
        queue = module.call(
            "enqueue",
            queue,
            push(ASIN, index * 1000, f"2026-01-0{index}T00:00:00Z"),
        )
    assert len(queue) == 1
    assert queue[0]["ms"] == 5000
    assert queue[0]["at"] == "2026-01-05T00:00:00Z"


def test_enqueue_ignores_an_older_position(module: qjs.JsModule) -> None:
    queue = [push(ASIN, 5000, "2026-01-05T00:00:00Z")]
    queue = module.call("enqueue", queue, push(ASIN, 1000, "2026-01-01T00:00:00Z"))
    assert queue == [{"asin": ASIN, "ms": 5000, "at": "2026-01-05T00:00:00Z"}]


def test_enqueue_ignores_garbage(module: qjs.JsModule) -> None:
    assert module.call("enqueue", [], {"ms": 1}) == []
    assert module.call("enqueue", [], None) == []
    assert module.call("enqueue", None, push(ASIN, 1, None)) == [
        {"asin": ASIN, "ms": 1, "at": None}
    ]


# --- flushPlan (drop a queued push the remote has beaten, 4.6) ---------------
def remote_now(items: dict) -> dict:
    return {asin: entry(ms, updated_at) for asin, (ms, updated_at) in items.items()}


def test_flush_plan_sends_fresh_entries(module: qjs.JsModule) -> None:
    queue = [push(ASIN, 1000, "2026-02-01T00:00:00Z")]
    remote = remote_now({ASIN: (500, "2026-01-01T00:00:00Z")})
    plan = module.call("flushPlan", queue, remote)
    assert plan["drop"] == []
    assert plan["send"] == [{"asin": ASIN, "ms": 1000, "at": "2026-02-01T00:00:00Z"}]


def test_flush_plan_drops_a_stale_queued_push(module: qjs.JsModule) -> None:
    queue = [
        push(ASIN, 1000, "2026-01-01T00:00:00Z"),
        push(OTHER, 2000, "2026-02-02T00:00:00Z"),
    ]
    remote = remote_now(
        {
            ASIN: (9000, "2026-03-01T00:00:00Z"),
            OTHER: (10, "2026-01-01T00:00:00Z"),
        }
    )
    plan = module.call("flushPlan", queue, remote)
    assert plan["drop"] == [{"asin": ASIN, "ms": 1000, "at": "2026-01-01T00:00:00Z"}]
    assert plan["send"] == [{"asin": OTHER, "ms": 2000, "at": "2026-02-02T00:00:00Z"}]


def test_flush_plan_sends_when_the_remote_is_older_or_unknown(module: qjs.JsModule) -> None:
    queue = [
        push(ASIN, 1000, "2026-01-01T00:00:00Z"),
        push(OTHER, 2000, "2026-02-02T00:00:00Z"),
    ]
    remote = remote_now({ASIN: (500, "2025-01-01T00:00:00Z")})
    plan = module.call("flushPlan", queue, remote)
    assert plan["drop"] == []
    assert [item["asin"] for item in plan["send"]] == [ASIN, OTHER]


def test_flush_plan_equal_timestamp_is_not_stale(module: qjs.JsModule) -> None:
    queue = [push(ASIN, 1000, "2026-01-01T00:00:00Z")]
    remote = remote_now({ASIN: (1000, "2026-01-01T00:00:00Z")})
    plan = module.call("flushPlan", queue, remote)
    assert plan["drop"] == []
    assert len(plan["send"]) == 1


def test_flush_plan_without_a_remote_keeps_everything(module: qjs.JsModule) -> None:
    queue = [push(ASIN, 1000, "2026-01-01T00:00:00Z")]
    plan = module.call("flushPlan", queue, None)
    assert plan["drop"] == []
    assert len(plan["send"]) == 1
    assert module.call("flushPlan", None, None) == {"send": [], "drop": []}


# --- isFinished (ARCHITECTURE 5.2) -------------------------------------------
def test_is_finished_on_eof(module: qjs.JsModule) -> None:
    assert module.call("isFinished", 0, 600000, True) is True
    assert module.call("isFinished", None, None, True) is True


def test_is_finished_within_30_seconds_of_the_end(module: qjs.JsModule) -> None:
    assert module.call("isFinished", 600000, 600000, False) is True
    assert module.call("isFinished", 570000, 600000, False) is True
    assert module.call("isFinished", 569999, 600000, False) is False


def test_is_finished_without_a_duration(module: qjs.JsModule) -> None:
    assert module.call("isFinished", 10, 0, False) is False
    assert module.call("isFinished", 10, None, False) is False
    assert module.call("isFinished", 10, "600000", False) is False


# --- autoRemoveAllowed (PLAN P4, default off) --------------------------------
def test_auto_remove_requires_the_setting_on(module: qjs.JsModule) -> None:
    assert module.call("autoRemoveAllowed", False, True, False) is False
    assert module.call("autoRemoveAllowed", None, True, False) is False


def test_auto_remove_never_fires_while_playing(module: qjs.JsModule) -> None:
    assert module.call("autoRemoveAllowed", True, True, True) is False


def test_auto_remove_fires_when_enabled_finished_and_stopped(
    module: qjs.JsModule,
) -> None:
    assert module.call("autoRemoveAllowed", True, True, False) is True
    assert module.call("autoRemoveAllowed", True, False, False) is False

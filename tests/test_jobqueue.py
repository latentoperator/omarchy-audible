"""P1a — ``qml/lib/JobQueue.js``: single-at-a-time FIFO, bypass, busy, cancel."""

from __future__ import annotations

import pytest

import qjs
from omarchy_audible.commands import JOB_COMMANDS as BACKEND_JOB_COMMANDS
from omarchy_audible.commands import REGISTRY

EXPECTED_API = {
    "ACTION_FAIL",
    "ACTION_IDLE",
    "ACTION_OK",
    "ACTION_RETRY",
    "CANCEL_DROPPED",
    "CANCEL_NONE",
    "CANCEL_SEND",
    "DEFAULT_BUSY_DELAY_MS",
    "JOB_COMMANDS",
    "action",
    "cancel",
    "complete",
    "create",
    "enqueue",
    "isJobCommand",
    "isNull",
    "jobAsin",
    "size",
    "take",
}

NON_JOB_COMMANDS = sorted(
    name for name, command in REGISTRY.items() if not command.is_job
)
JOB_COMMAND_NAMES = sorted(BACKEND_JOB_COMMANDS)


@pytest.fixture(scope="module")
def jobqueue() -> qjs.JsModule:
    return qjs.load("JobQueue")


def queue(module: qjs.JsModule, **options) -> qjs.JsRef:
    return module.hold("create", options) if options else module.hold("create")


def test_exports_the_expected_api(jobqueue: qjs.JsModule) -> None:
    assert set(jobqueue.functions) == EXPECTED_API


def test_job_commands_match_the_backend_registry(jobqueue: qjs.JsModule) -> None:
    assert sorted(jobqueue.evaluate("JOB_COMMANDS")) == JOB_COMMAND_NAMES


@pytest.mark.parametrize("command", JOB_COMMAND_NAMES)
def test_job_commands_are_queued(jobqueue: qjs.JsModule, command: str) -> None:
    assert jobqueue.call("isJobCommand", command) is True


@pytest.mark.parametrize("command", NON_JOB_COMMANDS)
def test_non_job_commands_bypass_the_queue(
    jobqueue: qjs.JsModule, command: str
) -> None:
    state = queue(jobqueue)
    assert jobqueue.call("isJobCommand", command) is False
    assert jobqueue.call("enqueue", state, {"command": command, "args": []}) is None
    assert state.read() == {
        "pending": [],
        "active": None,
        "busyDelayMs": jobqueue.evaluate("DEFAULT_BUSY_DELAY_MS"),
    }


def test_unknown_commands_bypass_the_queue(jobqueue: qjs.JsModule) -> None:
    state = queue(jobqueue)
    assert (
        jobqueue.call("enqueue", state, {"command": "not_a_command", "args": []})
        is None
    )
    assert state.read()["pending"] == []


def test_jobs_run_one_at_a_time_in_fifo_order(jobqueue: qjs.JsModule) -> None:
    state = queue(jobqueue)
    jobqueue.call("enqueue", state, {"command": "setup", "args": []})
    jobqueue.call("enqueue", state, {"command": "get", "args": ["B00FAKE01"]})
    jobqueue.call("enqueue", state, {"command": "remove", "args": ["B00FAKE01"]})
    assert state.read()["pending"] == [
        {"command": "setup", "args": [], "asin": None, "retried": False},
        {
            "command": "get",
            "args": ["B00FAKE01"],
            "asin": "B00FAKE01",
            "retried": False,
        },
        {"command": "remove", "args": ["B00FAKE01"], "asin": None, "retried": False},
    ]

    first = jobqueue.call("take", state)
    assert first["command"] == "setup"
    assert jobqueue.call("take", state) is None, (
        "a second job must not start while one is active"
    )

    assert (
        jobqueue.call("complete", state, {"ok": True, "busy": False})["action"] == "ok"
    )
    second = jobqueue.call("take", state)
    assert second["command"] == "get"

    assert (
        jobqueue.call("complete", state, {"ok": False, "busy": False})["action"]
        == "fail"
    )
    third = jobqueue.call("take", state)
    assert third["command"] == "remove"

    assert (
        jobqueue.call("complete", state, {"ok": True, "busy": False})["action"] == "ok"
    )
    assert jobqueue.call("take", state) is None
    assert jobqueue.call("size", state) == 0


def test_complete_without_an_active_job_is_idle(jobqueue: qjs.JsModule) -> None:
    state = queue(jobqueue)
    result = jobqueue.call("complete", state, {"ok": True})
    assert result["action"] == "idle"
    assert result["job"] is None


def test_the_caller_supplies_the_busy_delay(jobqueue: qjs.JsModule) -> None:
    assert jobqueue.call("create", {"busyDelayMs": 250})["busyDelayMs"] == 250
    assert jobqueue.call("create")["busyDelayMs"] == jobqueue.evaluate(
        "DEFAULT_BUSY_DELAY_MS"
    )
    assert jobqueue.call("create", {"busyDelayMs": -1})[
        "busyDelayMs"
    ] == jobqueue.evaluate("DEFAULT_BUSY_DELAY_MS")


def test_a_busy_outcome_retries_once_then_fails(jobqueue: qjs.JsModule) -> None:
    state = queue(jobqueue, busyDelayMs=250)
    jobqueue.call("enqueue", state, {"command": "sync", "args": []})
    assert jobqueue.call("take", state)["command"] == "sync"

    retry = jobqueue.call(
        "complete", state, {"ok": False, "busy": True, "code": "busy"}
    )
    assert retry["action"] == "retry"
    assert retry["delayMs"] == 250
    assert retry["job"]["command"] == "sync"
    assert state.read()["pending"] == [
        {"command": "sync", "args": [], "asin": None, "retried": True}
    ]

    assert jobqueue.call("take", state)["retried"] is True
    failed = jobqueue.call(
        "complete", state, {"ok": False, "busy": True, "code": "busy"}
    )
    assert failed["action"] == "fail"
    assert failed["delayMs"] == 0
    assert state.read()["pending"] == []
    assert jobqueue.call("size", state) == 0


def test_a_busy_retry_keeps_the_head_of_the_queue(jobqueue: qjs.JsModule) -> None:
    state = queue(jobqueue, busyDelayMs=10)
    jobqueue.call("enqueue", state, {"command": "sync", "args": []})
    jobqueue.call("enqueue", state, {"command": "setup", "args": []})

    assert jobqueue.call("take", state)["command"] == "sync"
    assert (
        jobqueue.call("complete", state, {"ok": False, "busy": True})["action"]
        == "retry"
    )

    assert jobqueue.call("take", state)["command"] == "sync", (
        "the retry goes back to the head"
    )
    assert jobqueue.call("complete", state, {"ok": True})["action"] == "ok"
    assert jobqueue.call("take", state)["command"] == "setup"


def test_a_non_busy_failure_does_not_retry(jobqueue: qjs.JsModule) -> None:
    state = queue(jobqueue)
    jobqueue.call("enqueue", state, {"command": "sync", "args": []})
    jobqueue.call("take", state)
    result = jobqueue.call(
        "complete", state, {"ok": False, "busy": False, "code": "network"}
    )
    assert result["action"] == "fail"
    assert state.read()["pending"] == []


# --- cancel ------------------------------------------------------------------
def test_cancel_drops_a_queued_get(jobqueue: qjs.JsModule) -> None:
    state = queue(jobqueue)
    jobqueue.call("enqueue", state, {"command": "get", "args": ["B00FAKE01"]})
    result = jobqueue.call("cancel", state, "B00FAKE01")
    assert result["action"] == "dropped"
    assert result["job"]["command"] == "get"
    assert state.read()["pending"] == []


def test_cancel_drops_only_the_matching_queued_get(jobqueue: qjs.JsModule) -> None:
    state = queue(jobqueue)
    jobqueue.call("enqueue", state, {"command": "get", "args": ["B00FAKE01"]})
    jobqueue.call("enqueue", state, {"command": "get", "args": ["B00FAKE02"]})
    assert jobqueue.call("cancel", state, "B00FAKE01")["action"] == "dropped"
    assert [job["asin"] for job in state.read()["pending"]] == ["B00FAKE02"]


def test_cancel_of_the_running_get_sends_the_cancel_command(
    jobqueue: qjs.JsModule,
) -> None:
    state = queue(jobqueue)
    jobqueue.call("enqueue", state, {"command": "get", "args": ["B00FAKE01"]})
    assert jobqueue.call("take", state)["asin"] == "B00FAKE01"
    result = jobqueue.call("cancel", state, "B00FAKE01")
    assert result["action"] == "send_cancel"
    assert result["job"]["command"] == "get"
    assert state.read()["active"]["asin"] == "B00FAKE01", (
        "the caller still owns the active job"
    )


def test_cancel_uses_the_asin_derived_from_a_gets_arguments(
    jobqueue: qjs.JsModule,
) -> None:
    state = queue(jobqueue)
    jobqueue.call(
        "enqueue",
        state,
        {"command": "get", "args": ["--fake-fail", "network", "B00FAKE09"]},
    )
    assert state.read()["pending"][0]["asin"] == "B00FAKE09"
    assert jobqueue.call("cancel", state, "B00FAKE09")["action"] == "dropped"


def test_cancel_of_a_running_non_get_job_returns_none(jobqueue: qjs.JsModule) -> None:
    state = queue(jobqueue)
    jobqueue.call("enqueue", state, {"command": "sync", "args": []})
    jobqueue.call("take", state)
    assert jobqueue.call("cancel", state, "B00FAKE01")["action"] == "none"
    assert state.read()["active"]["command"] == "sync"


def test_cancel_never_drops_a_queued_non_get(jobqueue: qjs.JsModule) -> None:
    state = queue(jobqueue)
    jobqueue.call("enqueue", state, {"command": "remove", "args": ["B00FAKE01"]})
    assert jobqueue.call("cancel", state, "B00FAKE01")["action"] == "none"
    assert [job["command"] for job in state.read()["pending"]] == ["remove"]


def test_cancel_of_an_unknown_asin_returns_none(jobqueue: qjs.JsModule) -> None:
    state = queue(jobqueue)
    assert jobqueue.call("cancel", state, "B00FAKE01")["action"] == "none"
    jobqueue.call("enqueue", state, {"command": "get", "args": ["B00FAKE02"]})
    assert jobqueue.call("cancel", state, "B00FAKE01")["action"] == "none"
    assert state.read()["pending"][0]["asin"] == "B00FAKE02"


def test_cancel_after_a_busy_retry_drops_the_delayed_get(
    jobqueue: qjs.JsModule,
) -> None:
    state = queue(jobqueue)
    jobqueue.call("enqueue", state, {"command": "get", "args": ["B00FAKE01"]})
    jobqueue.call("take", state)
    assert (
        jobqueue.call("complete", state, {"ok": False, "busy": True})["action"]
        == "retry"
    )
    assert jobqueue.call("cancel", state, "B00FAKE01")["action"] == "dropped"
    assert state.read()["pending"] == []


def test_cancel_with_bad_arguments_returns_none(jobqueue: qjs.JsModule) -> None:
    state = queue(jobqueue)
    jobqueue.call("enqueue", state, {"command": "get", "args": ["B00FAKE01"]})
    assert jobqueue.call("cancel", state, "")["action"] == "none"
    assert jobqueue.call("cancel", state, 42)["action"] == "none"
    assert jobqueue.call("cancel", None, "B00FAKE01")["action"] == "none"
    assert state.read()["pending"][0]["asin"] == "B00FAKE01"


def test_size_counts_pending_and_the_active_job(jobqueue: qjs.JsModule) -> None:
    state = queue(jobqueue)
    assert jobqueue.call("size", state) == 0
    jobqueue.call("enqueue", state, {"command": "sync", "args": []})
    jobqueue.call("enqueue", state, {"command": "setup", "args": []})
    assert jobqueue.call("size", state) == 2
    jobqueue.call("take", state)
    assert jobqueue.call("size", state) == 2
    jobqueue.call("complete", state, {"ok": True})
    assert jobqueue.call("size", state) == 1

"""S03: empty/expired pause settlement and bounded status refreshes."""

import pytest
from test_held_lifecycle import REPO, UNTIL, A, B, status_event
from test_held_lifecycle import service as service  # noqa: PLC0414

import qjs

DEADLINE = "2027-01-15T12:00:01Z"


def set_pause(service, asins=()):
    service.call("run", "status", [])
    job = service.evaluate("commands[commands.length-1]")
    status_event(service, job, until=DEADLINE)
    service.call("onJobFinished", job, {"ok": True})
    if asins:
        service.call(
            "applyHeld", {"type": "hold", "asins": list(asins), "until": DEADLINE}
        )
    service.evaluate("(commands = [], NOW += 2000)")


@pytest.mark.parametrize("event", ["now", "status"])
def test_empty_expired_pause_clears_timestamp_and_wake(event):
    held = qjs.load("Held")
    now = held.evaluate("Date.parse('2027-01-15T12:00:02Z')")
    result = held.call(
        "step",
        {"asins": [], "until": DEADLINE},
        {"type": event, "until": DEADLINE, "now": now},
    )
    assert result == {"state": {"asins": [], "until": ""}, "effects": []}
    assert held.call("wakeInMs", result["state"], now) == 0


@pytest.mark.parametrize("cancel_last", [False, True])
def test_startup_or_cancel_last_clears_expired_banner_and_timer(service, cancel_last):
    set_pause(service, [A] if cancel_last else [])
    if cancel_last:
        assert service.call("cancelDownload", A) == "dropped"
    service.call("onPauseElapsed")
    assert service.evaluate("held") == {"asins": [], "until": ""}
    assert service.evaluate("downloadsPaused") is False
    assert service.evaluate("pauseTimer.running") is False
    assert service.evaluate("commands.map(function(j){return j.command;})") == [
        "status"
    ]


def test_hanging_refresh_never_spawns_a_one_second_stream(service):
    set_pause(service)
    for _ in range(10):
        service.call("onPauseElapsed")
        service.call("run", "status", [], "pause-refresh")
        service.evaluate("NOW += 1000")
    assert service.evaluate("commands.length") == 1
    assert service.evaluate("downloadsPaused") is False
    assert service.evaluate("pauseTimer.running") is False
    assert service.evaluate("statusRetryTimer.running") is False


@pytest.mark.parametrize("outcome", [{"ok": False, "code": "internal"}, {"ok": True}])
def test_missing_status_record_uses_bounded_failure_backoff(service, outcome):
    set_pause(service)
    service.call("onPauseElapsed")
    intervals = []
    for _ in range(7):
        job = service.evaluate("commands[commands.length-1]")
        service.call("onJobFinished", job, outcome)
        assert service.evaluate("pauseTimer.running") is False
        assert service.evaluate("statusRetryTimer.running") is True
        intervals.append(service.evaluate("statusRetryTimer.interval"))
        service.call("run", "status", [], "pause-refresh")
    assert intervals == [30000, 60000, 120000, 240000, 300000, 300000, 300000]
    assert service.evaluate("downloadsPaused") is False


def test_delayed_record_after_expiry_cannot_restore_expired_banner(service):
    set_pause(service)
    service.call("onPauseElapsed")
    job = service.evaluate("commands[commands.length-1]")
    status_event(service, job, until=DEADLINE)
    service.call("onJobFinished", job, {"ok": True})
    assert service.evaluate("held.until") == ""
    assert service.evaluate("statusRetryTimer.running") is False
    assert service.evaluate("pauseTimer.running") is False
    assert service.evaluate("downloadsPaused") is False


def test_fresh_extended_deadline_rearms_once_and_resets_backoff(service):
    set_pause(service)
    service.call("onPauseElapsed")
    old = service.evaluate("commands[commands.length-1]")
    service.call("onJobFinished", old, {"ok": False, "code": "internal"})
    service.call("run", "status", [], "pause-refresh")
    new = service.evaluate("commands[commands.length-1]")
    status_event(service, new, until=UNTIL)
    service.call("onJobFinished", new, {"ok": True})
    assert service.evaluate("downloadsPaused") is True
    assert service.evaluate("pauseTimer.running") is True
    assert service.evaluate("pauseTimer.interval") > 1000
    assert service.evaluate("statusRetryTimer.running") is False
    assert service.evaluate("statusRetryMs") == 30000
    before = service.evaluate("held")
    status_event(service, old, until=None)
    assert service.evaluate("held") == before


@pytest.mark.parametrize("clock_delta,paused", [(-10000, True), (10000, False)])
def test_clock_jump_settles_against_current_time(service, clock_delta, paused):
    set_pause(service, [A, B])
    service.evaluate(f"NOW += {clock_delta}")
    service.call("onPauseElapsed")
    assert service.evaluate("downloadsPaused") is paused
    assert service.evaluate("pauseTimer.running") is paused
    gets = service.evaluate("commands.filter(function(j){return j.command==='get';})")
    assert [j["args"][0] for j in gets] == ([] if paused else [A, B])


def test_disconnect_invalidates_pending_refresh_and_retry(service):
    set_pause(service)
    service.call("onPauseElapsed")
    job = service.evaluate("commands[commands.length-1]")
    service.call("disconnect")
    service.call("onJobFinished", job, {"ok": False, "code": "internal"})
    assert service.evaluate("statusRetryTimer.running") is False
    assert service.evaluate("statusRequest") == ""


def test_ordinary_status_checks_coalesce_without_losing_followup(service):
    service.call("run", "status", [])
    first = service.evaluate("commands[0]")
    for _ in range(5):
        service.call("run", "status", [])
    assert service.evaluate("commands.length") == 1
    status_event(service, first, until=None)
    service.call("onJobFinished", first, {"ok": True})
    assert service.evaluate("commands.length") == 2
    current = service.evaluate("statusRequest")
    service.call("onJobFinished", first, {"ok": False, "code": "internal"})
    assert service.evaluate("statusRequest") == current
    assert service.evaluate("statusRetryTimer.running") is False


def test_status_retry_timer_uses_deduplicated_refresh_path():
    source = (REPO / "Service.qml").read_text()
    assert "id: statusRetryTimer" in source
    assert 'onTriggered: root.run("status", [], "pause-refresh")' in source

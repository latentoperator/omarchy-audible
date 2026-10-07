"""Job lock semantics (ARCHITECTURE 4.8) and the job.json record."""

from __future__ import annotations

import fcntl
import os

from omarchy_audible import joblock
from omarchy_audible.commands import JOB_COMMANDS, KNOWN_COMMANDS, REGISTRY


def _hold_lock(paths):
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(paths.job_lock, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def test_second_job_command_is_busy(run_cli, events, fake_paths):
    fd = _hold_lock(fake_paths)
    try:
        result = run_cli("sync", fake=True)
    finally:
        os.close(fd)
    assert result.returncode != 0
    last = events(result)[-1]
    assert last["type"] == "error"
    assert last["code"] == "busy"


def test_status_succeeds_while_lock_is_held(run_cli, events, fake_paths):
    fd = _hold_lock(fake_paths)
    try:
        result = run_cli("status", fake=True)
    finally:
        os.close(fd)
    assert result.returncode == 0, result.stderr
    assert events(result)[-1]["type"] == "done"


def test_lock_is_released_when_context_exits(paths):
    with joblock.job_lock(paths):
        assert joblock.try_acquire(paths.job_lock) is None
    fd = joblock.try_acquire(paths.job_lock)
    assert fd is not None
    joblock.release(fd)


def test_job_json_roundtrip(paths):
    assert joblock.read_job_json(paths.job_json) is None
    joblock.write_job_json(paths.job_json, 4321, "get", "B00FAKE")
    assert joblock.read_job_json(paths.job_json) == {
        "pid": 4321,
        "command": "get",
        "asin": "B00FAKE",
    }
    joblock.remove_job_json(paths.job_json)
    assert joblock.read_job_json(paths.job_json) is None


def test_job_lock_writes_and_clears_record(paths):
    with joblock.job_lock(paths, write_record=True, command="get", asin="B00FAKE"):
        assert joblock.read_job_json(paths.job_json) is not None
    assert joblock.read_job_json(paths.job_json) is None


def test_registry_classifies_job_and_non_job_commands():
    expected_jobs = {
        "setup",
        "sync",
        "get",
        "remove",
        "login-finish",
        "login-import-cli",
        "logout",
    }
    expected_plain = {
        "status",
        "doctor",
        "local",
        "play-info",
        "position-get",
        "position-push",
        "login-start",
        "cancel",
    }
    assert JOB_COMMANDS == expected_jobs
    for name in expected_plain:
        assert name in KNOWN_COMMANDS
        assert REGISTRY[name].is_job is False

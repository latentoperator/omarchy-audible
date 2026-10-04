"""`status` and `doctor` output, and the NDJSON-only stdout contract."""

from __future__ import annotations

import json

DOCTOR_CHECKS = (
    "mpv",
    "ffmpeg",
    "ffprobe",
    "python",
    "wl-paste",
    "xdg-open",
    "systemd-run",
    "venv",
    "auth",
)


def test_status_fake_validates_against_schema(run_cli, validate_stream):
    result = run_cli("status", fake=True)
    assert result.returncode == 0, result.stderr
    parsed = validate_stream(result, expect_last="done")
    status = next(event for event in parsed if event["type"] == "status")
    assert status["ready"] is True
    assert status["authenticated"] is True
    assert status["missing"] == []


def test_doctor_fake_validates_against_schema(run_cli, validate_stream):
    result = run_cli("doctor", fake=True)
    assert result.returncode == 0, result.stderr
    parsed = validate_stream(result, expect_last="done")
    doctor = next(event for event in parsed if event["type"] == "doctor")
    names = [check["name"] for check in doctor["checks"]]
    for expected in DOCTOR_CHECKS:
        assert expected in names
    for check in doctor["checks"]:
        assert isinstance(check["ok"], bool)


def test_status_real_mode_works_without_venv(run_cli, validate_stream, paths):
    assert not paths.venv_python.exists()
    result = run_cli("status")
    assert result.returncode == 0, result.stderr
    parsed = validate_stream(result, expect_last="done")
    status = next(event for event in parsed if event["type"] == "status")
    assert status["authenticated"] is False
    assert status["account"] is None


def test_doctor_real_mode_works_without_venv(run_cli, validate_stream, paths):
    assert not paths.venv_python.exists()
    result = run_cli("doctor")
    assert result.returncode == 0, result.stderr
    parsed = validate_stream(result, expect_last="done")
    doctor = next(event for event in parsed if event["type"] == "doctor")
    venv = next(check for check in doctor["checks"] if check["name"] == "venv")
    assert venv["ok"] is False


def test_stdout_is_only_ndjson(run_cli):
    result = run_cli("doctor", fake=True)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, "expected at least one event"
    for line in lines:
        json.loads(line)

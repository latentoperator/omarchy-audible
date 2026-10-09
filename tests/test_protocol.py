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
    "mpris_script",
)


def test_status_fake_validates_against_schema(run_cli, validate_stream):
    result = run_cli("status", fake=True)
    assert result.returncode == 0, result.stderr
    parsed = validate_stream(result, expect_last="done")
    status = next(event for event in parsed if event["type"] == "status")
    assert status["ready"] is True
    assert status["authenticated"] is True
    assert status["missing"] == []
    assert status["mpris_script"] is None or status["mpris_script"].startswith("/")


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
    mpris = next(check for check in doctor["checks"] if check["name"] == "mpris_script")
    assert mpris["ok"] is True
    assert mpris["detail"] == "not installed (optional)" or mpris["detail"].startswith(
        "/"
    )


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


def test_a_non_ascii_message_survives_a_c_locale(run_cli, paths, events):
    """F14: a C-locale stdout must not raise on a non-ASCII message.

    The account name comes from ``account.json``, so it is a real character, not
    a surrogate-escaped byte from argv. ``LC_ALL=C`` alone is not enough —
    Python 3.7+ switches on UTF-8 mode for the C locale — so coercion and UTF-8
    mode are turned off too: that is what a plain C shell looks like.
    """
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    (paths.config_dir / "account.json").write_text(
        '{"account": "Jos\\u00e9 Fake", "marketplace": "us"}', encoding="utf-8"
    )

    result = run_cli(
        "status",
        extra_env={
            "LC_ALL": "C",
            "PYTHONUTF8": "0",
            "PYTHONCOERCECLOCALE": "0",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    parsed = events(result)
    assert parsed and parsed[-1]["type"] == "done", parsed
    status = next(event for event in parsed if event["type"] == "status")
    assert status["account"] == "Jos\u00e9 Fake"

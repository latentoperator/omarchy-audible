"""B2 — `setup` builds and verifies the plugin virtualenv (ARCHITECTURE 4.1).

The subprocess seam is injected, so the control flow is tested offline: venv
creation, the two pinned `pip install` steps, the import verification, the ready
marker, idempotency, cleanup on failure, and recovery after a killed run.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from omarchy_audible import bootstrap
from omarchy_audible.errors import PipelineError
from omarchy_audible.paths import Paths


class RecordingRunner:
    """A Runner that records argv and simulates venv/pip/import steps."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(
        self, argv, env=None
    ) -> subprocess.CompletedProcess[str]:
        tokens = [str(token) for token in argv]
        self.calls.append(tokens)
        if tokens[1:3] == ["-m", "venv"]:
            venv_dir = Path(tokens[3])
            (venv_dir / "bin").mkdir(parents=True, exist_ok=True)
            (venv_dir / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")
        returncode = 1 if (self.fail_on and self.fail_on in tokens) else 0
        stderr = "simulated failure\n" if returncode else ""
        return subprocess.CompletedProcess(tokens, returncode, stdout="", stderr=stderr)


def _collect():
    events: list[dict] = []

    def emit(event_type: str, **fields) -> None:
        events.append({"type": event_type, **fields})

    return events, emit


def _digest() -> str:
    return bootstrap.requirements_digest(bootstrap.requirements_path())


def test_requirements_lock_pins_the_spike_versions():
    text = bootstrap.requirements_path().read_text(encoding="utf-8")
    assert "audible-cli==0.6.0" in text
    assert "audible[cryptography]==0.12.0" in text


def test_setup_runs_venv_two_pips_and_the_import_check(paths: Paths):
    runner = RecordingRunner()
    events, emit = _collect()
    bootstrap.run_setup(paths, base_python="/usr/bin/python3", run=runner, emit=emit)

    assert runner.calls[0] == ["/usr/bin/python3", "-m", "venv", str(paths.venv_dir)]

    pip_calls = [call for call in runner.calls if "pip" in call]
    assert len(pip_calls) == 2
    assert "-r" in pip_calls[0]
    assert str(bootstrap.requirements_path()) in pip_calls[0]
    assert str(bootstrap.backend_dir()) in pip_calls[1]

    # The last step is the real import verification, run by the venv interpreter.
    assert runner.calls[-1][0] == str(paths.venv_python)
    assert bootstrap.IMPORT_CHECK in runner.calls[-1]

    assert [event["stage"] for event in events] == list(bootstrap.PROGRESS_STAGES)
    assert bootstrap.is_ready(paths.venv_dir, _digest())


def test_setup_second_run_is_a_noop(paths: Paths):
    runner = RecordingRunner()
    bootstrap.run_setup(paths, run=runner)
    assert len(runner.calls) == 4

    events, emit = _collect()
    bootstrap.run_setup(paths, run=runner, emit=emit)
    # No new subprocesses: the venv was left exactly as it was.
    assert len(runner.calls) == 4
    assert [event["stage"] for event in events] == [bootstrap.UP_TO_DATE_STAGE]


def test_setup_rebuilds_a_venv_without_the_ready_marker(paths: Paths):
    """A run killed midway leaves no marker; the next run starts clean."""
    venv_dir = paths.venv_dir
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / "bin" / "python").write_text("# half-written\n", encoding="utf-8")
    (venv_dir / "leftover").write_text("junk", encoding="utf-8")

    runner = RecordingRunner()
    bootstrap.run_setup(paths, run=runner)

    assert runner.calls[0][1:3] == ["-m", "venv"]  # rebuilt from scratch
    assert not (venv_dir / "leftover").exists()
    assert bootstrap.is_ready(venv_dir, _digest())


def test_setup_cleans_up_on_failure_and_can_be_retried(paths: Paths):
    failing = RecordingRunner(fail_on="pip")
    with pytest.raises(PipelineError) as info:
        bootstrap.run_setup(paths, run=failing)
    assert info.value.code == "setup_failed"
    assert not paths.venv_dir.exists()

    bootstrap.run_setup(paths, run=RecordingRunner())
    assert bootstrap.is_ready(paths.venv_dir, _digest())


def test_is_ready_ignores_a_stale_requirements_digest(paths: Paths):
    bootstrap.run_setup(paths, run=RecordingRunner())
    assert bootstrap.is_ready(paths.venv_dir, _digest())
    assert not bootstrap.is_ready(paths.venv_dir, "0" * 64)


class _RealVenvRunner:
    """Runs a real `python -m venv`, stubs the pip installs, runs the real check."""

    def __call__(self, argv, env=None) -> subprocess.CompletedProcess[str]:
        tokens = [str(token) for token in argv]
        if tokens[1:3] == ["-m", "venv"]:
            return subprocess.run(tokens, capture_output=True, text=True, check=False)
        if "install" in tokens:
            site = _site_packages(Path(tokens[0]).parent.parent)
            for name in ("audible", "omarchy_audible"):
                module = site / name
                module.mkdir(exist_ok=True)
                (module / "__init__.py").write_text("", encoding="utf-8")
            return subprocess.CompletedProcess(tokens, 0, stdout="", stderr="")
        return subprocess.run(tokens, capture_output=True, text=True, check=False)


def _site_packages(venv_dir: Path) -> Path:
    for lib in sorted(venv_dir.glob("lib*")):
        for python in sorted(lib.glob("python3.*")):
            candidate = python / "site-packages"
            if candidate.is_dir():
                return candidate
    raise AssertionError(f"no site-packages under {venv_dir}")


def test_setup_builds_a_real_usable_venv(paths: Paths):
    """End to end with a real venv (offline): the venv really can import."""
    probe = subprocess.run(
        [sys.executable, "-m", "venv", "--help"], capture_output=True, check=False
    )
    if probe.returncode != 0:
        pytest.skip("python -m venv is unavailable on this machine")

    def runner(argv, env=None):
        tokens = [str(token) for token in argv]
        if tokens[1:3] == ["-m", "venv"]:
            result = subprocess.run(tokens, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                pytest.skip("python -m venv failed on this machine")
            return result
        return _RealVenvRunner()(tokens, env)

    bootstrap.run_setup(paths, run=runner)
    result = subprocess.run(
        [str(paths.venv_python), "-c", bootstrap.IMPORT_CHECK],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert bootstrap.is_ready(paths.venv_dir, _digest())


def test_setup_steps_do_not_inherit_pythonpath(paths: Paths, monkeypatch):
    """A stale PYTHONPATH must not let the verify import the repo source."""
    monkeypatch.setenv("PYTHONPATH", str(bootstrap.backend_dir()))
    seen: list[dict] = []

    def runner(argv, env=None):
        seen.append(dict(env or {}))
        tokens = [str(token) for token in argv]
        if tokens[1:3] == ["-m", "venv"]:
            (paths.venv_dir / "bin").mkdir(parents=True, exist_ok=True)
            paths.venv_python.write_text("#!/bin/sh\n", encoding="utf-8")
        return subprocess.CompletedProcess(tokens, 0, stdout="", stderr="")

    bootstrap.run_setup(paths, run=runner)
    assert len(seen) == len(bootstrap.PROGRESS_STAGES)
    assert all("PYTHONPATH" not in env for env in seen)


def test_setup_is_a_job_command():
    from omarchy_audible.commands import JOB_COMMANDS

    assert "setup" in JOB_COMMANDS


def test_setup_cli_fake_streams_progress_and_is_idempotent(
    run_cli, validate_stream, fake_paths: Paths
):
    first = run_cli("setup", fake=True)
    assert first.returncode == 0, first.stderr
    parsed = validate_stream(first, expect_last="done")
    stages = [event["stage"] for event in parsed if event["type"] == "progress"]
    assert stages == list(bootstrap.PROGRESS_STAGES)

    marker = bootstrap.marker_path(fake_paths.venv_dir)
    assert marker.is_file()
    sentinel = fake_paths.venv_dir / "sentinel"
    sentinel.write_text("keep me", encoding="utf-8")

    second = run_cli("setup", fake=True)
    assert second.returncode == 0, second.stderr
    parsed_second = validate_stream(second, expect_last="done")
    assert any(
        event.get("stage") == bootstrap.UP_TO_DATE_STAGE
        for event in parsed_second
        if event["type"] == "progress"
    )
    # The no-op must not have rebuilt the venv.
    assert sentinel.read_text(encoding="utf-8") == "keep me"

"""B04 regressions: synthetic offline venvs, never pip or account traffic."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from omarchy_audible import bootstrap, commands
from omarchy_audible.errors import PipelineError


@pytest.fixture
def offline_env(paths, env, monkeypatch, tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    for key, value in {**env, "TMPDIR": str(scratch)}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("OMARCHY_AUDIBLE_FAKE", raising=False)
    run = subprocess.run

    def no_network_installs(argv, **kw):
        assert "pip" not in argv, "regression tests must never run pip"
        return run(argv, **kw)

    monkeypatch.setattr(subprocess, "run", no_network_installs)
    result = subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(paths.venv_dir)],
        env=dict(os.environ),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    site = next(paths.venv_dir.glob("lib/python*/site-packages"))
    for name in ("audible", "audible_cli", "omarchy_audible", "cryptography"):
        package = site / name
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
    for name, version in (("audible", "0.12.0"), ("audible_cli", "0.6.0")):
        metadata = site / f"{name}-{version}.dist-info"
        metadata.mkdir()
        (metadata / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name.replace('_', '-')}\nVersion: {version}\n",
            encoding="utf-8",
        )
        (metadata / "RECORD").write_text(
            f"{metadata.name}/METADATA,,\n", encoding="utf-8"
        )
    bootstrap.marker_path(paths.venv_dir).write_text(
        json.dumps(
            {
                "schema": 1,
                "requirements": bootstrap.requirements_digest(
                    bootstrap.requirements_path()
                ),
            }
        ),
        encoding="utf-8",
    )
    return paths, site


def offline_failure(argv, env=None):
    tokens = list(argv)
    if tokens[1:3] == ["-m", "venv"]:
        directory = Path(tokens[3])
        (directory / "bin").mkdir(parents=True)
        (directory / "bin/python").write_text("partial", encoding="utf-8")
        return subprocess.CompletedProcess(tokens, 1, "", "offline rebuild")
    return subprocess.run(
        tokens, env=env, capture_output=True, text=True, timeout=10, check=False
    )


def status(paths, monkeypatch):
    output = []
    monkeypatch.setattr(
        commands.protocol,
        "emit",
        lambda kind, **kw: output.append({"type": kind, **kw}),
    )
    commands.cmd_status([], command="status", fake=False, paths=paths)
    return next(event for event in output if event["type"] == "status")


@pytest.mark.parametrize(
    "damage", ["missing", "import_failure", "non_executable", "broken_interpreter"]
)
def test_marked_broken_environment_never_noops(offline_env, damage):
    paths, site = offline_env
    if damage == "missing":
        (site / "audible/__init__.py").unlink()
        (site / "audible").rmdir()
    elif damage == "import_failure":
        (site / "audible/__init__.py").write_text("raise ImportError('synthetic')\n")
    else:
        paths.venv_python.unlink()
        paths.venv_python.write_text("#!/does/not/exist\n")
        paths.venv_python.chmod(0o644 if damage == "non_executable" else 0o755)
    output = []
    with pytest.raises(PipelineError, match="virtualenv"):
        bootstrap.run_setup(
            paths, run=offline_failure, emit=lambda kind, **kw: output.append(kw)
        )
    assert not any(event.get("stage") == "up_to_date" for event in output)
    assert not bootstrap.venv_ready(paths.venv_dir)


def test_changed_pins_are_not_status_ready(offline_env, monkeypatch):
    paths, _ = offline_env
    marker = bootstrap.read_marker(paths.venv_dir)
    marker["requirements"] = "0" * 64
    bootstrap.marker_path(paths.venv_dir).write_text(json.dumps(marker))
    with pytest.raises(PipelineError):
        bootstrap.run_setup(paths, run=offline_failure)
    report = status(paths, monkeypatch)
    assert report["venv_ready"] is False
    assert report["venv_state"] == "usable_old"
    assert bootstrap.venv_ready(paths.venv_dir)
    check = subprocess.run(
        [str(paths.venv_python), "-I", "-c", "import audible"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert check.returncode == 0


def test_python_abi_mismatch_is_not_ready(offline_env, monkeypatch):
    paths, _ = offline_env
    bootstrap.run_setup(paths, run=offline_failure)  # compatible legacy marker upgraded
    marker = bootstrap.read_marker(paths.venv_dir)
    marker["python"] = ["cpython", "cpython-000", 0, 0]
    bootstrap.marker_path(paths.venv_dir).write_text(json.dumps(marker))
    assert bootstrap.is_ready(paths.venv_dir, marker["requirements"]) is False
    assert status(paths, monkeypatch)["venv_ready"] is False


def test_health_snapshot_detects_deleted_dependency_without_poll_subprocesses(
    offline_env, monkeypatch
):
    paths, site = offline_env
    bootstrap.run_setup(paths, run=offline_failure)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("poll spawned"))
    assert status(paths, monkeypatch)["venv_ready"] is True
    (site / "audible/__init__.py").unlink()
    assert status(paths, monkeypatch)["venv_ready"] is False


def test_setup_checks_import_even_when_snapshot_is_unchanged(offline_env):
    paths, site = offline_env
    bootstrap.run_setup(paths, run=offline_failure)
    broken = site / "audible/__init__.py"
    # Health can change without changing already loaded files: a new optional
    # dependency imported at runtime is not an excuse for a marker-only no-op.
    broken.write_text(
        "import os\nif os.environ.get('B04_BREAK'): raise ImportError()\n"
    )
    bootstrap.run_setup(paths, run=offline_failure)
    os.environ["B04_BREAK"] = "1"
    try:
        with pytest.raises(PipelineError):
            bootstrap.run_setup(paths, run=offline_failure)
    finally:
        os.environ.pop("B04_BREAK", None)


def test_wrong_installed_pin_cannot_noop(offline_env):
    paths, site = offline_env
    metadata = site / "audible-0.12.0.dist-info/METADATA"
    metadata.write_text("Metadata-Version: 2.1\nName: audible\nVersion: 0.0.0\n")
    with pytest.raises(PipelineError):
        bootstrap.run_setup(paths, run=offline_failure)
    assert not bootstrap.is_ready(
        paths.venv_dir, bootstrap.requirements_digest(bootstrap.requirements_path())
    )


def test_probe_timeout_is_bounded_and_secret_free(offline_env, monkeypatch):
    paths, _ = offline_env
    original = subprocess.run

    def timeout(argv, **kw):
        if "-c" in argv:
            assert 0 < kw["timeout"] <= 10
            raise subprocess.TimeoutExpired(
                argv, kw["timeout"], stderr="private payload"
            )
        return original(argv, **kw)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(PipelineError) as failure:

        def runner(argv, env=None):
            if "-c" in argv:
                return bootstrap._subprocess_run(argv, env)
            return offline_failure(argv, env)

        bootstrap.run_setup(paths, run=runner)
    assert failure.value.code == "setup_failed"
    assert "private payload" not in str(failure.value)


def test_failed_marker_write_restores_usable_old_environment(offline_env, monkeypatch):
    paths, _ = offline_env
    bootstrap.run_setup(paths, run=offline_failure)
    old = bootstrap.marker_path(paths.venv_dir).read_bytes()
    monkeypatch.setattr(
        bootstrap.fsutil,
        "atomic_write_json",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("synthetic disk failure")),
    )
    with pytest.raises(PipelineError):
        bootstrap.run_setup(paths, run=offline_failure)
    assert bootstrap.marker_path(paths.venv_dir).read_bytes() == old
    assert bootstrap.venv_ready(paths.venv_dir)


def offline_repair(argv, env=None):
    from test_setup import _RealVenvRunner

    tokens = list(argv)
    if tokens[1:3] == ["-m", "venv"]:
        return subprocess.run(
            [*tokens[:3], "--without-pip", *tokens[3:]],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    if "pip" in tokens:
        return _RealVenvRunner()(tokens, env)
    return subprocess.run(
        tokens, env=env, capture_output=True, text=True, timeout=10, check=False
    )


@pytest.mark.parametrize(
    "damage",
    ["missing", "import_failure", "non_executable", "broken_interpreter", "pins"],
)
def test_setup_really_repairs_offline_environment(offline_env, damage):
    paths, site = offline_env
    if damage in ("missing", "import_failure"):
        (site / "audible/__init__.py").write_text("raise ImportError()\n")
        if damage == "missing":
            (site / "audible/__init__.py").unlink()
            (site / "audible").rmdir()
    elif damage == "pins":
        (site / "audible-0.12.0.dist-info/METADATA").write_text(
            "Metadata-Version: 2.1\nName: audible\nVersion: 0.0.0\n"
        )
    else:
        paths.venv_python.unlink()
        paths.venv_python.write_text("#!/does/not/exist\n")
        paths.venv_python.chmod(0o644 if damage == "non_executable" else 0o755)
    stages = []
    bootstrap.run_setup(
        paths, run=offline_repair, emit=lambda kind, **kw: stages.append(kw["stage"])
    )
    assert stages == list(bootstrap.PROGRESS_STAGES)
    assert bootstrap.is_ready(
        paths.venv_dir, bootstrap.requirements_digest(bootstrap.requirements_path())
    )
    check = subprocess.run(
        [str(paths.venv_python), "-I", "-c", bootstrap.IMPORT_CHECK],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert check.returncode == 0, check.stderr


@pytest.mark.parametrize("rebuild_ok", [True, False])
def test_actual_incompatible_probe_forces_repair_not_fallback(offline_env, rebuild_ok):
    paths, _ = offline_env
    calls = []

    def runner(argv, env=None):
        calls.append(list(argv))
        if len(calls) == 1 and "-c" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps(
                    {
                        "python": ["cpython", "cpython-000", 0, 0],
                        "versions": {"audible": "0.12.0", "audible-cli": "0.6.0"},
                        "files": ["pyvenv.cfg"],
                    }
                ),
                "",
            )
        return (offline_repair if rebuild_ok else offline_failure)(argv, env)

    if rebuild_ok:
        bootstrap.run_setup(paths, run=runner)
        assert bootstrap.venv_state(paths.venv_dir) == "current_ready"
    else:
        with pytest.raises(PipelineError):
            bootstrap.run_setup(paths, run=runner)
        assert not paths.venv_dir.exists()
    assert any(call[1:3] == ["-m", "venv"] for call in calls)


@pytest.mark.parametrize(
    "failure_stage", ["requirements", "backend", "verify", "marker"]
)
def test_failed_rebuild_at_each_stage_keeps_usable_fallback(
    offline_env, monkeypatch, failure_stage
):
    paths, _ = offline_env
    bootstrap.run_setup(paths, run=offline_failure)
    bootstrap._write_marker(paths.venv_dir, "0" * 64)
    sentinel = paths.venv_dir / "sentinel"
    sentinel.write_text("keep the usable fallback")
    old_python = paths.venv_python.resolve()
    write = bootstrap.fsutil.atomic_write_json
    writes = []

    def marker_write(*args, **kw):
        writes.append(args)
        if len(writes) == 2 and failure_stage == "marker":
            raise OSError("synthetic disk failure")
        return write(*args, **kw)

    monkeypatch.setattr(bootstrap.fsutil, "atomic_write_json", marker_write)
    calls = []

    def runner(argv, env=None):
        calls.append(list(argv))
        fail = (
            (failure_stage == "requirements" and "-r" in argv)
            or (failure_stage == "backend" and "pip" in argv and "-r" not in argv)
            or (failure_stage == "verify" and "-c" in argv and len(calls) > 1)
        )
        if fail:
            return subprocess.CompletedProcess(argv, 1, "", "synthetic failure")
        return offline_repair(argv, env)

    with pytest.raises(PipelineError):
        bootstrap.run_setup(paths, run=runner)
    assert sentinel.read_text() == "keep the usable fallback"
    assert paths.venv_python.resolve() == old_python
    assert bootstrap.venv_state(paths.venv_dir) == "usable_old"
    check = subprocess.run(
        [str(paths.venv_python), "-I", "-c", "import audible"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert check.returncode == 0


@pytest.mark.parametrize(
    "damage",
    ["legacy", "missing", "mode", "abi", "metadata", "malformed", "path_escape", "nul"],
)
def test_launcher_and_backend_reject_same_unusable_health(offline_env, damage):
    from test_launcher import _load_launcher

    paths, site = offline_env
    bootstrap.run_setup(paths, run=offline_failure)
    marker = bootstrap.read_marker(paths.venv_dir)
    if damage == "legacy":
        marker["schema"] = 1
    elif damage == "missing":
        (site / "audible/__init__.py").unlink()
    elif damage == "mode":
        paths.venv_python.unlink()
        paths.venv_python.write_text("#!/bin/sh\nexit 0\n")
        paths.venv_python.chmod(0o644)
    elif damage == "abi":
        marker["python"] = ["cpython", "cpython-000", 0, 0]
    elif damage == "metadata":
        (site / "audible-0.12.0.dist-info/METADATA").unlink()
    elif damage == "malformed":
        marker["files"] = []
    else:
        name = "nul\0" if damage == "nul" else "../outside"
        marker.setdefault("files", {})[name] = [0] * 5
    bootstrap.marker_path(paths.venv_dir).write_text(json.dumps(marker))
    assert bootstrap.venv_ready(paths.venv_dir) is False
    assert _load_launcher()._venv_ready(paths.venv_python) is False


def test_usable_old_environment_remains_launcher_dispatchable(offline_env):
    from test_launcher import _load_launcher

    paths, _ = offline_env
    bootstrap.run_setup(paths, run=offline_failure)
    bootstrap._write_marker(paths.venv_dir, "0" * 64)
    assert bootstrap.venv_state(paths.venv_dir) == "usable_old"
    assert _load_launcher()._venv_ready(paths.venv_python) is True


def test_real_hanging_import_is_terminated(offline_env, monkeypatch):
    paths, site = offline_env
    (site / "audible/__init__.py").write_text("import time\ntime.sleep(60)\n")
    monkeypatch.setattr(bootstrap, "PROBE_TIMEOUT", 0.1, raising=False)

    def runner(argv, env=None):
        if "-c" in argv:
            return bootstrap._subprocess_run(argv, env)
        return offline_failure(argv, env)

    with pytest.raises(PipelineError):
        bootstrap.run_setup(paths, run=runner)
    assert not paths.venv_dir.exists()


def test_interrupted_current_environment_is_restored_without_reinstall(offline_env):
    paths, _ = offline_env
    previous = paths.venv_dir.with_name("venv.previous")
    paths.venv_dir.rename(previous)
    stages = []
    bootstrap.run_setup(
        paths, run=offline_failure, emit=lambda kind, **kw: stages.append(kw["stage"])
    )
    assert stages == ["up_to_date"]
    assert bootstrap.venv_state(paths.venv_dir) == "current_ready"
    assert not previous.exists()

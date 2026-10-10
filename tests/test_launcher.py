"""Launcher dispatch, fake-mode switch, and hygiene (stdlib-only, lazy `audible`)."""

from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
import json
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from omarchy_audible import joblock

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "bin" / "omarchy-audible"
BACKEND_DIR = REPO_ROOT / "backend"


def _load_launcher():
    loader = importlib.machinery.SourceFileLoader(
        "omarchy_audible_launcher", str(LAUNCHER)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_unknown_command_exits_nonzero_with_error(run_cli, events):
    result = run_cli("frobnicate", fake=True)
    assert result.returncode != 0
    last = events(result)[-1]
    assert last["type"] == "error"
    assert last["code"] == "unknown_command"


def test_no_command_exits_nonzero_with_error(run_cli, events):
    result = run_cli(fake=True)
    assert result.returncode != 0
    last = events(result)[-1]
    assert last["type"] == "error"
    assert last["code"] == "invalid_args"


def test_known_command_without_venv_reports_no_venv(run_cli, events):
    # `sync` needs the pinned dependency and the virtualenv does not exist.
    result = run_cli("sync")
    assert result.returncode != 0
    last = events(result)[-1]
    assert last["type"] == "error"
    assert last["code"] == "no_venv"


def test_fake_flag_and_env_produce_the_same_status(run_cli, events):
    by_flag = run_cli("status", fake=True)
    by_env = run_cli("status", extra_env={"OMARCHY_AUDIBLE_FAKE": "1"})
    flag_status = next(event for event in events(by_flag) if event["type"] == "status")
    env_status = next(event for event in events(by_env) if event["type"] == "status")
    assert flag_status == env_status
    assert flag_status["account"] == "fake@example.com"


def test_launcher_known_commands_match_backend_registry():
    from omarchy_audible.commands import KNOWN_COMMANDS

    launcher = _load_launcher()
    assert set(launcher.KNOWN_COMMANDS) == set(KNOWN_COMMANDS)


def test_launcher_imports_only_stdlib():
    tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    non_stdlib = imported - set(sys.stdlib_module_names)
    assert not non_stdlib, f"launcher imports non-stdlib modules: {sorted(non_stdlib)}"
    # The backend is re-exec'ed (ARCHITECTURE 4.1), not spawned as a child.
    assert "subprocess" not in imported


def test_backend_does_not_import_audible_eagerly(env):
    code = (
        "import sys;"
        f"sys.path.insert(0, r'{BACKEND_DIR}');"
        "import omarchy_audible.cli;"
        "import omarchy_audible.commands;"
        "assert 'audible' not in sys.modules, 'audible was imported eagerly'"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _write_fake_backend(directory: Path) -> Path:
    """Create an importable ``omarchy_audible`` package for a launcher run.

    ``python -m`` puts the working directory first on ``sys.path``, so running
    the launcher with this directory as its cwd shadows the real backend. The
    fake reports its own PID, holds ``job.lock`` like a real job, then blocks.
    """
    package = directory / "omarchy_audible"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "__main__.py").write_text(
        "import fcntl, json, os, sys, time\n"
        "from pathlib import Path\n"
        "runtime = Path(os.environ['XDG_RUNTIME_DIR']) / 'omarchy-audible'\n"
        "runtime.mkdir(parents=True, exist_ok=True)\n"
        "fd = os.open(runtime / 'job.lock', os.O_CREAT | os.O_RDWR, 0o600)\n"
        "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "sys.stdout.write(json.dumps({'type': 'done', 'pid': os.getpid()}) + '\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    return directory


def test_launcher_re_execs_the_backend_in_the_same_process(env, tmp_path):
    """The launcher must *become* the backend, so the PID the UI spawns is the
    PID that holds ``job.lock`` and that killing stops the job (4.1, 4.8)."""
    cwd = _write_fake_backend(tmp_path / "fake-backend")
    lock_path = Path(env["XDG_RUNTIME_DIR"]) / "omarchy-audible" / "job.lock"
    process = subprocess.Popen(
        [sys.executable, str(LAUNCHER), "sync", "--fake"],
        env=env,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        event = json.loads(process.stdout.readline())
        assert event["type"] == "done", event
        # Same PID proves the launcher exec'ed the backend instead of forking it.
        assert event["pid"] == process.pid
        proc_cmdline = Path(f"/proc/{process.pid}/cmdline")
        if proc_cmdline.exists():
            assert b"omarchy_audible" in proc_cmdline.read_bytes()
        # The re-exec'ed process is the one holding job.lock.
        assert joblock.try_acquire(lock_path) is None
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=10) == -signal.SIGTERM
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    # Killing the spawned PID released the lock: nothing is left orphaned.
    fd = joblock.try_acquire(lock_path)
    assert fd is not None
    joblock.release(fd)


def test_run_backend_reports_internal_when_exec_fails(monkeypatch, capsys, env):
    launcher = _load_launcher()

    def _boom(*args, **kwargs):
        raise OSError("no such interpreter")

    monkeypatch.setattr(launcher.os, "execve", _boom)
    code = launcher._run_backend(["status"], dict(env), True, "/nonexistent/python")
    assert code == 1
    event = json.loads(capsys.readouterr().out.strip())
    assert event["type"] == "error"
    assert event["code"] == "internal"
    assert "could not start the backend" in event["message"]


def _fake_venv(env: dict[str, str]) -> Path:
    venv_dir = Path(env["XDG_DATA_HOME"]) / "omarchy-audible" / "venv"
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")
    return venv_dir


def test_launcher_requires_the_ready_marker(monkeypatch, capsys, env):
    """A venv without the marker is a killed `setup`; do not dispatch into it."""
    _fake_venv(env)  # interpreter present, marker absent
    monkeypatch.setenv("XDG_DATA_HOME", env["XDG_DATA_HOME"])
    launcher = _load_launcher()
    assert launcher.main(["sync"]) == 1
    event = json.loads(capsys.readouterr().out.strip())
    assert event["type"] == "error"
    assert event["code"] == "no_venv"


def test_launcher_dispatches_into_a_ready_venv(monkeypatch, env):
    venv_dir = _fake_venv(env)
    (venv_dir / "omarchy-audible.setup.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("XDG_DATA_HOME", env["XDG_DATA_HOME"])
    launcher = _load_launcher()
    captured: list[str] = []

    def _fake_execve(path, argv, child_env):
        captured.extend([str(path), *[str(token) for token in argv]])

    monkeypatch.setattr(launcher.os, "execve", _fake_execve)
    assert launcher.main(["sync"]) == 1  # unreachable after a real execve
    assert captured[0] == str(venv_dir / "bin" / "python")
    assert captured[2:4] == ["-m", "omarchy_audible"]


def test_launcher_keeps_bytecode_out_of_the_plugin_folder(monkeypatch, env):
    """.pyc files next to the source land in the shell's watched plugins
    folder, and each one makes the shell reload the plugin (a crash on
    Quickshell 0.3.1). They go to ~/.cache instead."""
    launcher = _load_launcher()
    captured: dict[str, str] = {}

    def _fake_execve(path, argv, child_env):
        captured.update(child_env)

    monkeypatch.setattr(launcher.os, "execve", _fake_execve)
    monkeypatch.delenv("PYTHONPYCACHEPREFIX", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", "/x/cache")
    launcher.main(["status", "--fake"])
    assert captured["PYTHONPYCACHEPREFIX"] == "/x/cache/omarchy-audible/pycache"

    # A relative XDG_CACHE_HOME is ignored (XDG spec).
    captured.clear()
    monkeypatch.setenv("XDG_CACHE_HOME", "rel/cache")
    monkeypatch.setenv("HOME", "/x/home")
    launcher.main(["status", "--fake"])
    assert captured["PYTHONPYCACHEPREFIX"] == "/x/home/.cache/omarchy-audible/pycache"

    captured.clear()
    monkeypatch.delenv("XDG_CACHE_HOME")
    monkeypatch.setenv("HOME", "/x/home")
    launcher.main(["status", "--fake"])
    assert captured["PYTHONPYCACHEPREFIX"] == "/x/home/.cache/omarchy-audible/pycache"

    captured.clear()
    monkeypatch.setenv("PYTHONPYCACHEPREFIX", "/mine")
    launcher.main(["status", "--fake"])
    assert captured["PYTHONPYCACHEPREFIX"] == "/mine"

    # An empty or relative inherited prefix would put bytecode back next to
    # the source (empty) or under the spawner's cwd (relative): replaced.
    for value in ("", "rel"):
        captured.clear()
        monkeypatch.setenv("PYTHONPYCACHEPREFIX", value)
        launcher.main(["status", "--fake"])
        assert (
            captured["PYTHONPYCACHEPREFIX"] == "/x/home/.cache/omarchy-audible/pycache"
        )


def test_a_backend_run_writes_no_bytecode_into_the_repo(env, tmp_path):
    """End to end: a backend run leaves no __pycache__ under the plugin
    folder. (The download wrapper is checked in test_argv_privacy.)"""
    repo = tmp_path / "plugin"
    shutil.copytree(
        LAUNCHER.parent.parent,
        repo,
        ignore=shutil.ignore_patterns(
            "__pycache__", ".venv", ".git", ".worktrees", ".pytest_cache", "*.pyc"
        ),
        symlinks=True,
    )
    cache = tmp_path / "cache"
    run_env = {**env, "XDG_CACHE_HOME": str(cache)}
    run_env.pop("PYTHONDONTWRITEBYTECODE", None)
    run_env.pop("PYTHONPYCACHEPREFIX", None)
    result = subprocess.run(
        [sys.executable, str(repo / "bin" / "omarchy-audible"), "status", "--fake"],
        env=run_env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not list(repo.rglob("__pycache__")), list(repo.rglob("__pycache__"))
    assert list(cache.rglob("*.pyc")), "bytecode should still be cached"


def test_launcher_marker_name_matches_the_backend():
    from omarchy_audible import bootstrap

    assert _load_launcher().VENV_MARKER == bootstrap.MARKER_NAME

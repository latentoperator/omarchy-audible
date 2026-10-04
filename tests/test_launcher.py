"""Launcher dispatch, fake-mode switch, and hygiene (stdlib-only, lazy `audible`)."""

from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
import json
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
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False
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

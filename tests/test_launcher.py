"""Launcher dispatch, fake-mode switch, and hygiene (stdlib-only, lazy `audible`)."""

from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
import sys
from pathlib import Path

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


def test_backend_does_not_import_audible_eagerly(env):
    code = (
        "import sys;"
        f"sys.path.insert(0, r'{BACKEND_DIR}');"
        "import omarchy_audible.cli;"
        "import omarchy_audible.commands;"
        "assert 'audible' not in sys.modules, 'audible was imported eagerly'"
    )
    import subprocess

    result = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr

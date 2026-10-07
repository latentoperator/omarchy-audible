"""Shared fixtures for the backend test suite.

Every test that runs the CLI gets XDG dirs, HOME and the books dir pointed at a
temporary directory, so no test can read or write the real user's files.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "bin" / "omarchy-audible"
BACKEND_DIR = REPO_ROOT / "backend"
SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"

# Where ffmpeg/ffprobe live on the Hopebox when they are not on PATH.
FFMPEG_FALLBACK_DIR = Path("/home/hopewell/.hermes/tools/ffmpeg-9.0.1-linux-x64/bin")

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from omarchy_audible.paths import Paths


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    config = tmp_path / "config"
    data = tmp_path / "data"
    runtime = tmp_path / "runtime"
    books = tmp_path / "books"
    for directory in (home, config, data, runtime, books):
        directory.mkdir()
    result = dict(os.environ)
    result.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(config),
            "XDG_DATA_HOME": str(data),
            "XDG_RUNTIME_DIR": str(runtime),
            "OMARCHY_AUDIBLE_BOOKS_DIR": str(books),
        }
    )
    result.pop("OMARCHY_AUDIBLE_FAKE", None)
    return result


@pytest.fixture
def paths(env: dict[str, str]) -> Paths:
    return Paths.from_env(env)


@pytest.fixture
def fake_paths(env: dict[str, str]) -> Paths:
    """The separate fake-mode tree (B8), pre-created for tests that write books."""
    resolved = Paths.from_env(env, fake=True)
    for directory in (
        resolved.config_dir,
        resolved.data_dir,
        resolved.runtime_dir,
        resolved.books_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return resolved


@pytest.fixture
def run_cli(env: dict[str, str]):
    def _run(
        *args: str,
        fake: bool = False,
        extra_env=None,
        timeout: int = 60,
        stdin: str | None = None,
    ):
        child_env = dict(env)
        if extra_env:
            child_env.update(extra_env)
        argv = [str(arg) for arg in args]
        if fake:
            argv.append("--fake")
        return subprocess.run(
            [sys.executable, str(LAUNCHER), *argv],
            env=child_env,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    return _run


def _ensure_tool(env: dict[str, str], name: str) -> bool:
    """Put the fallback dir ahead on ``env["PATH"]`` when ``name`` is missing."""
    if shutil.which(name, path=env.get("PATH")):
        return True
    if (FFMPEG_FALLBACK_DIR / name).is_file():
        env["PATH"] = os.pathsep.join([str(FFMPEG_FALLBACK_DIR), env.get("PATH", "")])
        return True
    return False


@pytest.fixture
def ffmpeg_bin(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Make ``ffmpeg``/``ffprobe`` reachable, or skip a test that needs them.

    Prepends the Hopebox fallback directory to the shared ``env`` fixture (so
    ``run_cli`` subprocesses see it) **and** to ``os.environ`` (so in-process
    ``run_get()`` calls resolve ffmpeg via ``shutil.which``); pytest restores
    both. Skips cleanly on a machine without ffmpeg (ARCHITECTURE 8).
    """
    if not (_ensure_tool(env, "ffmpeg") and _ensure_tool(env, "ffprobe")):
        pytest.skip("ffmpeg and ffprobe are required for the conversion pipeline")
    monkeypatch.setenv("PATH", env["PATH"])
    return env


@pytest.fixture
def schemas_dir() -> Path:
    return SCHEMAS_DIR


@pytest.fixture
def events():
    def _events(result):
        return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]

    return _events


@pytest.fixture
def validate_event():
    jsonschema = pytest.importorskip("jsonschema")

    def _validate(event):
        schema_path = SCHEMAS_DIR / f"{event['type']}.json"
        assert schema_path.is_file(), f"no schema for event type {event['type']!r}"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(instance=event, schema=schema)

    return _validate


@pytest.fixture
def validate_stream(events, validate_event):
    def _validate(result, *, expect_last=None):
        parsed = events(result)
        assert parsed, f"no events on stdout; stderr={result.stderr!r}"
        for event in parsed:
            validate_event(event)
        if expect_last is not None:
            assert parsed[-1]["type"] == expect_last
        return parsed

    return _validate

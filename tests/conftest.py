"""Shared fixtures for the backend test suite.

Every test that runs the CLI gets XDG dirs, HOME and the books dir pointed at a
temporary directory, so no test can read or write the real user's files.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "bin" / "omarchy-audible"
BACKEND_DIR = REPO_ROOT / "backend"
SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"

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


@pytest.fixture
def schemas_dir() -> Path:
    return SCHEMAS_DIR


@pytest.fixture
def events():
    def _events(result):
        return [
            json.loads(line) for line in result.stdout.splitlines() if line.strip()
        ]

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

"""``setup``: build the plugin virtualenv (ARCHITECTURE 4.1).

This module runs from the repository source with the system Python — the
launcher handles ``setup`` itself, before any dependency exists. It builds
``<data>/omarchy-audible/venv`` in four steps:

1. ``python -m venv <venv>`` using the interpreter running ``setup``.
2. ``pip install -r backend/requirements.lock`` — the pinned ``audible-cli`` and
   ``audible[cryptography]``.
3. ``pip install <repo>/backend`` — this repo's package, so that
   ``venv/bin/python -m omarchy_audible`` resolves without ``PYTHONPATH``.
4. ``venv/bin/python -c "import audible, omarchy_audible"`` — prove the venv is
   usable.

A ready marker is written last. That makes the command idempotent (a second run
is a no-op) and makes a run killed midway recoverable: the partial venv has no
marker, so the next run removes it and starts clean. Any failure removes the
venv, so a retry never inherits half an install.

The ``audible`` library is never imported here (it is only installed), so the
test suite runs without it.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from . import fsutil, protocol
from .errors import PipelineError
from .library import iso_now
from .log import log
from .paths import Paths

REQUIREMENTS_NAME = "requirements.lock"
MARKER_NAME = "omarchy-audible.setup.json"
MARKER_SCHEMA = 1
IMPORT_CHECK = "import audible, omarchy_audible"

# Stages streamed as `progress` events, in order. Reported with `n`/`of`.
PROGRESS_STAGES = ("venv", "requirements", "backend", "verify")
# The stage a no-op run reports instead.
UP_TO_DATE_STAGE = "up_to_date"

_PIP_FLAGS = (
    "--no-input",
    "--disable-pip-version-check",
    "--no-warn-script-location",
)

Emitter = Callable[..., None]


class Runner(Protocol):
    """One subprocess step of ``setup`` (the injectable seam for tests)."""

    def __call__(
        self, argv: Sequence[str], env: Mapping[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]: ...


def backend_dir() -> Path:
    """The repository's ``backend/`` directory (this package's parent)."""
    return Path(__file__).resolve().parent.parent


def requirements_path() -> Path:
    """The single place the pinned versions live (``backend/requirements.lock``)."""
    return backend_dir() / REQUIREMENTS_NAME


def requirements_digest(path: Path) -> str:
    """A stable hash of the requirements file, stored in the ready marker."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker_path(venv_dir: Path) -> Path:
    """The ready marker written last by a successful ``setup``."""
    return venv_dir / MARKER_NAME


def read_marker(venv_dir: Path) -> dict[str, object] | None:
    """Read the ready marker, or ``None`` when it is absent or unreadable."""
    try:
        data = json.loads(marker_path(venv_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def venv_ready(venv_dir: Path) -> bool:
    """True when a completed virtualenv (interpreter plus ready marker) exists."""
    return (venv_dir / "bin" / "python").is_file() and marker_path(venv_dir).is_file()


def is_ready(venv_dir: Path, digest: str) -> bool:
    """True when ``venv_dir`` was built from the requirements ``digest``."""
    marker = read_marker(venv_dir)
    if marker is None or marker.get("schema") != MARKER_SCHEMA:
        return False
    return marker.get("requirements") == digest and venv_ready(venv_dir)


def _subprocess_run(
    argv: Sequence[str], env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a step with its output captured, so only NDJSON reaches stdout."""
    return subprocess.run(
        [str(token) for token in argv],
        env=dict(env) if env is not None else None,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )


class FakeRunner:
    """Simulate the venv/pip/import steps for fake mode (no network, no pip).

    It creates a skeleton ``venv/bin/python`` so the ready marker and the
    idempotent second run behave the same way they do in real mode.
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(
        self, argv: Sequence[str], env: Mapping[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        tokens = [str(token) for token in argv]
        self.calls.append(tokens)
        if len(tokens) >= 4 and tokens[1:3] == ["-m", "venv"]:
            venv_dir = Path(tokens[3])
            (venv_dir / "bin").mkdir(parents=True, exist_ok=True)
            python = venv_dir / "bin" / "python"
            python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            python.chmod(0o755)
        return subprocess.CompletedProcess(tokens, 0, stdout="", stderr="")


def _clean_env() -> dict[str, str]:
    """The environment for setup steps, without the launcher's ``PYTHONPATH``.

    The launcher re-execs the backend with ``PYTHONPATH`` pointing at the repo
    ``backend/``. Leaving that in place would let the verify step import the
    repo source instead of the freshly installed package, hiding a failed
    install. The plugin config dir is dropped too: setup touches no account.
    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("AUDIBLE_CONFIG_DIR", None)
    return env


def _remove_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _check(result: subprocess.CompletedProcess[str], message: str) -> None:
    if result.returncode == 0:
        return
    detail = (result.stderr or "").strip().splitlines()
    if detail:
        # Logged (scrubbed) for the human; stdout stays NDJSON-only.
        log(f"setup step failed: {detail[-1]}")
    raise PipelineError(
        protocol.ErrorCode.SETUP_FAILED,
        message,
        hint="fix the cause and run setup again",
    )


def _write_marker(venv_dir: Path, digest: str) -> None:
    fsutil.atomic_write_json(
        marker_path(venv_dir),
        {
            "schema": MARKER_SCHEMA,
            "requirements": digest,
            "requirements_file": REQUIREMENTS_NAME,
            "created_at": iso_now(),
        },
    )


def run_setup(
    paths: Paths,
    *,
    base_python: str | None = None,
    fake: bool = False,
    emit: Emitter = protocol.emit,
    run: Runner | None = None,
) -> None:
    """Create and verify the plugin venv (ARCHITECTURE 4.1).

    ``run`` is the subprocess seam: the real implementation captures output,
    fake mode uses :class:`FakeRunner`, and tests inject their own. Raises
    :class:`PipelineError` (code ``setup_failed``) after removing the venv.
    """
    runner: Runner = run or (FakeRunner() if fake else _subprocess_run)
    base = base_python or sys.executable or "python3"
    requirements = requirements_path()
    if not requirements.is_file():
        raise PipelineError(
            protocol.ErrorCode.SETUP_FAILED,
            "the requirements file is missing",
            hint=f"expected {requirements}",
        )
    digest = requirements_digest(requirements)

    venv_dir = paths.venv_dir
    venv_python = paths.venv_python
    if is_ready(venv_dir, digest):
        emit("progress", stage=UP_TO_DATE_STAGE)
        return

    total = len(PROGRESS_STAGES)
    step_env = _clean_env()
    # F43: a working venv (one with a marker, even for older pins) is moved
    # aside, not deleted, and comes back if the rebuild fails, so an update
    # run offline cannot leave the plugin with no venv at all. It is moved
    # rather than the new one built elsewhere because a venv's scripts carry
    # its absolute path. A venv with no marker is a killed run: start clean.
    previous = venv_dir.with_name(venv_dir.name + ".previous")
    if not venv_ready(venv_dir) and venv_ready(previous):
        # A rebuild killed outright (SIGKILL, a shell restart) never reached
        # the restore below: the aside copy is the working venv.
        _remove_tree(venv_dir)
        previous.rename(venv_dir)
    _remove_tree(previous)
    if read_marker(venv_dir) is not None and venv_ready(venv_dir):
        venv_dir.rename(previous)
    try:
        _remove_tree(venv_dir)

        emit("progress", stage="venv", n=1, of=total)
        _check(
            runner([base, "-m", "venv", str(venv_dir)], step_env),
            "could not create the virtualenv",
        )
        if not venv_python.is_file():
            raise PipelineError(
                protocol.ErrorCode.SETUP_FAILED,
                "the virtualenv has no interpreter",
                hint="python -m venv did not produce bin/python",
            )

        emit("progress", stage="requirements", n=2, of=total)
        _check(
            runner(
                [
                    str(venv_python),
                    "-m",
                    "pip",
                    "install",
                    *_PIP_FLAGS,
                    "-r",
                    str(requirements),
                ],
                step_env,
            ),
            "could not install the pinned dependencies",
        )

        emit("progress", stage="backend", n=3, of=total)
        _check(
            runner(
                [
                    str(venv_python),
                    "-m",
                    "pip",
                    "install",
                    *_PIP_FLAGS,
                    str(backend_dir()),
                ],
                step_env,
            ),
            "could not install the backend package",
        )

        emit("progress", stage="verify", n=4, of=total)
        _check(
            runner([str(venv_python), "-c", IMPORT_CHECK], step_env),
            "the virtualenv cannot import its dependencies",
        )
    except BaseException:
        _remove_tree(venv_dir)
        if previous.is_dir():
            previous.rename(venv_dir)
        raise

    _write_marker(venv_dir, digest)
    _remove_tree(previous)

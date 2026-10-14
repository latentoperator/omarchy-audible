"""``setup``: build the plugin virtualenv (ARCHITECTURE 4.1).

This module runs from the repository source with the system Python — the
launcher handles ``setup`` itself, before any dependency exists. It builds
``<data>/omarchy-audible/venv`` in four steps:

1. ``python -m venv <venv>`` using the interpreter running ``setup``.
2. ``pip install -r backend/requirements.lock`` — the pinned ``audible-cli`` and
   ``audible[cryptography]``.
3. ``pip install <repo>/backend`` — this repo's package, so that
   ``venv/bin/python -m omarchy_audible`` resolves without ``PYTHONPATH``.
4. An isolated, bounded offline probe checks imports, interpreter ABI and pins.

A health marker is written last. A second run probes before reporting a no-op;
status migrates legacy markers once, then status and dispatch only check the
saved file fingerprints. Interrupted or broken installs are rebuilt, while a
verified usable old environment is kept
as a fallback and restored if the replacement fails. The ``audible`` library
is imported only in the venv subprocess, never by this bootstrap module.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import sysconfig
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
MARKER_SCHEMA = 2
PROBE_TIMEOUT = 10
IMPORT_CHECK = """import audible, audible_cli, cryptography, omarchy_audible
import importlib.metadata as metadata
import json, sys, sysconfig
from pathlib import Path
root = Path(sys.prefix)
files = {str(Path(m.__file__).relative_to(root))
         for m in list(sys.modules.values())
         if getattr(m, '__file__', None) and Path(m.__file__).is_relative_to(root)}
versions = {}
for name in ('audible', 'audible-cli'):
    distribution = metadata.distribution(name)
    versions[name] = distribution.version
    for file in distribution.files or ():
        if file.name == 'METADATA':
            files.add(str(Path(distribution.locate_file(file)).relative_to(root)))
print(json.dumps({'python': [sys.implementation.name, sys.implementation.cache_tag,
                            sys.version_info.major, sys.version_info.minor,
                            sysconfig.get_config_var("SOABI")],
                  'versions': versions, 'files': sorted(files)}))
"""

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


def is_legacy_marker(marker: dict[str, object] | None) -> bool:
    """Recognize the complete schema-1 marker written by 0.1.4/0.1.5."""
    digest = marker.get("requirements") if marker else None
    return bool(
        marker
        and set(marker) == {"schema", "requirements", "requirements_file", "created_at"}
        and type(marker.get("schema")) is int
        and marker["schema"] == 1
        and isinstance(digest, str)
        and len(digest) == 64
        and all(c in "0123456789abcdef" for c in digest)
        and marker.get("requirements_file") == REQUIREMENTS_NAME
        and isinstance(marker.get("created_at"), str)
        and marker["created_at"]
    )


def migrate_legacy_marker(venv_dir: Path) -> None:
    """Probe a legacy install once; persist success or failure atomically.

    Failed probes also become schema 2 (without usable health evidence), so
    subsequent status polls and dispatch fail closed until setup repairs it.
    """
    marker = read_marker(venv_dir)
    if marker is None or not is_legacy_marker(marker):
        return
    health = _probe(venv_dir, _subprocess_run, _clean_env())
    # Another status or setup may have finished while the probe was running.
    if read_marker(venv_dir) != marker:
        return
    try:
        _write_marker(venv_dir, str(marker["requirements"]), health or {})
    except OSError:
        # Atomic writes leave the legacy marker intact; status stays broken,
        # but the pre-migration launcher compatibility path is not destroyed.
        return


def python_identity() -> list[object]:
    return [
        sys.implementation.name,
        sys.implementation.cache_tag,
        sys.version_info.major,
        sys.version_info.minor,
        sysconfig.get_config_var("SOABI"),
    ]


def _fingerprint(path: Path) -> list[int]:
    stat = path.stat()
    return [stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_mode]


def venv_ready(venv_dir: Path) -> bool:
    """Cheap validation of saved offline health evidence; never spawn Python."""
    marker = read_marker(venv_dir)
    python = venv_dir / "bin" / "python"
    if (
        not marker
        or marker.get("schema") != MARKER_SCHEMA
        or marker.get("python") != python_identity()
        or not python.is_file()
        or not os.access(python, os.X_OK)
    ):
        return False
    versions = marker.get("versions")
    files = marker.get("files")
    if (
        not isinstance(versions, dict)
        or not all(
            isinstance(versions.get(name), str) and versions[name]
            for name in ("audible", "audible-cli")
        )
        or not isinstance(files, dict)
        or not {"bin/python", "pyvenv.cfg"}.issubset(files)
    ):
        return False
    try:
        return all(
            isinstance(name, str)
            and not Path(name).is_absolute()
            and ".." not in Path(name).parts
            and _fingerprint(venv_dir / name) == saved
            for name, saved in files.items()
        )
    except (OSError, ValueError):
        return False


def requirement_pins() -> dict[str, str]:
    pins = {}
    for line in requirements_path().read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            name, version = line.split("==", 1)
            pins[name.split("[", 1)[0]] = version
    return pins


def is_ready(venv_dir: Path, digest: str) -> bool:
    """Current requirements and compatible, unchanged health evidence."""
    marker = read_marker(venv_dir)
    return bool(
        marker
        and marker.get("requirements") == digest
        and marker.get("versions") == requirement_pins()
        and venv_ready(venv_dir)
    )


def venv_state(venv_dir: Path) -> str:
    if not venv_dir.exists():
        return "missing"
    if not venv_ready(venv_dir):
        return "broken"
    try:
        digest = requirements_digest(requirements_path())
        return "current_ready" if is_ready(venv_dir, digest) else "usable_old"
    except (OSError, ValueError):
        return "usable_old"


def _probe(venv_dir: Path, runner: Runner, env: Mapping[str, str]) -> dict | None:
    python = venv_dir / "bin" / "python"
    if not python.is_file() or not os.access(python, os.X_OK):
        return None
    try:
        result = runner([str(python), "-I", "-c", IMPORT_CHECK], env)
        if result.returncode:
            return None
        health = json.loads(result.stdout)
        if (
            not isinstance(health, dict)
            or health.get("python") != python_identity()
            or not isinstance(health.get("versions"), dict)
            or not all(
                isinstance(health["versions"].get(name), str)
                and health["versions"][name]
                for name in ("audible", "audible-cli")
            )
            or not isinstance(health.get("files"), list)
            or not health["files"]
        ):
            return None
        names = set(health["files"]) | {"bin/python", "pyvenv.cfg"}
        if any(
            not isinstance(name, str)
            or Path(name).is_absolute()
            or ".." in Path(name).parts
            for name in names
        ):
            return None
        health["files"] = {name: _fingerprint(venv_dir / name) for name in names}
        return health
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return None


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
        timeout=PROBE_TIMEOUT if "-c" in argv else None,
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
            (venv_dir / "pyvenv.cfg").write_text("fake = true\n", encoding="utf-8")
        if "-c" in tokens:
            return subprocess.CompletedProcess(
                tokens,
                0,
                stdout=json.dumps(
                    {
                        "python": python_identity(),
                        "versions": requirement_pins(),
                        "files": ["pyvenv.cfg"],
                    }
                ),
                stderr="",
            )
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


def _write_marker(venv_dir: Path, digest: str, health: dict | None = None) -> None:
    if health is None:
        existing = read_marker(venv_dir) or {}
        health = {key: existing.get(key) for key in ("python", "versions", "files")}
    fsutil.atomic_write_json(
        marker_path(venv_dir),
        {
            "schema": MARKER_SCHEMA,
            "requirements": digest,
            "requirements_file": REQUIREMENTS_NAME,
            "created_at": iso_now(),
            **health,
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
    :class:`PipelineError` (code ``setup_failed``) on failure; restores any
    usable fallback after a failed rebuild.
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
    total = len(PROGRESS_STAGES)
    step_env = _clean_env()
    previous = venv_dir.with_name(venv_dir.name + ".previous")
    marker = read_marker(venv_dir)
    health = _probe(venv_dir, runner, step_env) if marker else None
    if health is None and read_marker(previous) is not None:
        # Restore to its original path before probing: venv scripts contain
        # absolute paths. Never discard the interrupted rebuild's fallback.
        _remove_tree(venv_dir)
        previous.rename(venv_dir)
        marker = read_marker(venv_dir)
        health = _probe(venv_dir, runner, step_env)
    if health is not None:
        saved_digest = str((marker or {}).get("requirements", ""))
        try:
            _write_marker(venv_dir, saved_digest, health)
        except OSError:
            raise PipelineError(
                protocol.ErrorCode.SETUP_FAILED,
                "could not record virtualenv health",
                hint="fix disk access and run setup again",
            ) from None
        if saved_digest == digest and health["versions"] == requirement_pins():
            _remove_tree(previous)
            emit("progress", stage=UP_TO_DATE_STAGE)
            return
    _remove_tree(previous)
    if health is not None:
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
        health = _probe(venv_dir, runner, step_env)
        if health is None or health["versions"] != requirement_pins():
            raise PipelineError(
                protocol.ErrorCode.SETUP_FAILED,
                "the virtualenv cannot import compatible pinned dependencies",
                hint="run setup again to repair the environment",
            )
        _write_marker(venv_dir, digest, health)
    except BaseException as exc:
        _remove_tree(venv_dir)
        if previous.is_dir():
            previous.rename(venv_dir)
        if isinstance(exc, (OSError, subprocess.SubprocessError)):
            raise PipelineError(
                protocol.ErrorCode.SETUP_FAILED,
                "could not rebuild the virtualenv",
                hint="fix disk access or Python and run setup again",
            ) from None
        raise

    _remove_tree(previous)

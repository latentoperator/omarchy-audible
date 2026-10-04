"""Command registry and the commands implemented in B1.

``status`` and ``doctor`` are real. Every other documented command exists in the
registry with the correct job/non-job classification and reports
``error(code=not_implemented)`` until its task lands. Keeping the registry
complete lets the job lock and unknown-command handling be exercised now.
"""

from __future__ import annotations

import shutil
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import protocol
from .paths import Paths

# Tools required to play a book, and the extra tools checked by ``doctor``.
REQUIRED_TOOLS = ("mpv", "ffmpeg", "ffprobe")
DOCTOR_TOOLS = (
    "python",
    "mpv",
    "ffmpeg",
    "ffprobe",
    "wl-paste",
    "xdg-open",
    "systemd-run",
)

# Fake account shown by ``status`` in fake mode. Invented, never a real user.
FAKE_ACCOUNT = "fake@example.com"
DEFAULT_MARKETPLACE = "us"

Handler = Callable[..., int]


@dataclass(frozen=True)
class Command:
    handler: Handler
    is_job: bool


def _missing_required_tools() -> list[str]:
    return [name for name in REQUIRED_TOOLS if shutil.which(name) is None]


def _catalog_age_s(paths: Paths) -> int | None:
    try:
        stat = paths.catalog_file.stat()
    except OSError:
        return None
    return max(0, int(time.time() - stat.st_mtime))


def cmd_status(
    args: Sequence[str], *, command: str, fake: bool, paths: Paths
) -> int:
    """Report readiness (ARCHITECTURE 4.2)."""
    if fake:
        # Fake mode pretends the environment is fully ready so the UI can run
        # with no account, no network and no virtualenv.
        protocol.emit(
            "status",
            ready=True,
            missing=[],
            authenticated=True,
            marketplace=DEFAULT_MARKETPLACE,
            account=FAKE_ACCOUNT,
            catalog_age_s=None,
        )
        protocol.done()
        return protocol.EXIT_OK

    missing = _missing_required_tools()
    authenticated = paths.auth_file.is_file()
    ready = authenticated and not missing and paths.venv_python.is_file()
    # ``marketplace``/``account`` are populated by B3 from the account record;
    # until then they stay at the documented defaults.
    protocol.emit(
        "status",
        ready=ready,
        missing=missing,
        authenticated=authenticated,
        marketplace=DEFAULT_MARKETPLACE,
        account=None,
        catalog_age_s=_catalog_age_s(paths),
    )
    protocol.done()
    return protocol.EXIT_OK


def _tool_check(name: str) -> dict[str, object]:
    if name == "python":
        found = sys.executable
        ok = bool(found) and Path(found).is_file()
        return {"name": name, "ok": ok, "detail": found}
    found = shutil.which(name)
    return {"name": name, "ok": found is not None, "detail": found or f"{name} not found on PATH"}


def cmd_doctor(
    args: Sequence[str], *, command: str, fake: bool, paths: Paths
) -> int:
    """Report the state of every external dependency (ARCHITECTURE 4.2).

    ``doctor`` always exits 0 once it has produced its report; the ``ok`` flags
    carry the findings so a caller can render them.
    """
    checks = [_tool_check(name) for name in DOCTOR_TOOLS]
    checks.append(
        {
            "name": "venv",
            "ok": paths.venv_python.is_file(),
            "detail": str(paths.venv_dir),
        }
    )
    auth_ok = paths.auth_file.is_file()
    checks.append(
        {
            "name": "auth",
            "ok": auth_ok,
            "detail": str(paths.auth_file) if auth_ok else "no auth.json; run login",
        }
    )
    protocol.emit("doctor", checks=checks)
    protocol.done()
    return protocol.EXIT_OK


def cmd_unimplemented(
    args: Sequence[str], *, command: str, fake: bool, paths: Paths
) -> int:
    protocol.error(
        protocol.ErrorCode.NOT_IMPLEMENTED,
        f"command not implemented yet: {command}",
        hint="this command lands in a later milestone",
    )
    return protocol.EXIT_ERROR


def _registry() -> dict[str, Command]:
    job = Command(cmd_unimplemented, True)
    plain = Command(cmd_unimplemented, False)
    return {
        "status": Command(cmd_status, False),
        "doctor": Command(cmd_doctor, False),
        "setup": job,
        "sync": job,
        "get": job,
        "remove": job,
        "login-finish": job,
        "login-import-cli": job,
        "logout": job,
        "local": plain,
        "position-get": plain,
        "position-push": plain,
        "login-start": plain,
        "cancel": plain,
    }


REGISTRY: dict[str, Command] = _registry()
KNOWN_COMMANDS = frozenset(REGISTRY)
JOB_COMMANDS = frozenset(name for name, cmd in REGISTRY.items() if cmd.is_job)

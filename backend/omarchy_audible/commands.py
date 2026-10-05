"""Command registry and the implemented backend commands.

``status`` and ``doctor`` (B1), ``get``/``cancel``/``local``/``remove`` (B5) and
the fake-mode failure switch are real. Every other documented command exists in
the registry with the correct job/non-job classification and reports
``error(code=not_implemented)`` until its task lands, so the job lock and
unknown-command handling stay exercisable.
"""

from __future__ import annotations

import os
import shutil
import signal
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from . import joblock, protocol
from .download import FAKE_FAIL_MODES, run_get
from .errors import Cancelled, PipelineError
from .library import remove_book, scan_local
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


def split_get_args(args: Sequence[str]) -> tuple[str | None, str | None]:
    """Split ``get`` arguments into ``(asin, fake_fail)``.

    Tolerates an unknown flag by returning the tokens it could read; validation
    is the caller's job.
    """
    asin: str | None = None
    fake_fail: str | None = None
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--fake-fail":
            if index + 1 < len(args):
                fake_fail = args[index + 1]
            index += 2
            continue
        if token.startswith("--fake-fail="):
            fake_fail = token.split("=", 1)[1]
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        if asin is None:
            asin = token
        index += 1
    return asin, fake_fail


def job_asin(command: str, args: Sequence[str]) -> str | None:
    """The ASIN a job command will record in ``job.json`` (ARCHITECTURE 4.8)."""
    if command == "get":
        return split_get_args(args)[0]
    return None


class _sigterm_cancels:
    """Turn SIGTERM into :class:`Cancelled` for the duration of a ``get``."""

    def __enter__(self) -> Self:
        self._previous = signal.signal(signal.SIGTERM, self._raise)
        return self

    def __exit__(self, *_exc: object) -> bool:
        signal.signal(signal.SIGTERM, self._previous)
        return False

    @staticmethod
    def _raise(_signum: int, _frame: object) -> None:
        raise Cancelled()


def cmd_get(args: Sequence[str], *, command: str, fake: bool, paths: Paths) -> int:
    """Download and convert one book (ARCHITECTURE 4.3)."""
    asin, fake_fail = split_get_args(args)
    if asin is None:
        protocol.error(
            protocol.ErrorCode.INVALID_ARGS,
            "get needs an ASIN",
            hint="try: omarchy-audible get <asin>",
        )
        return protocol.EXIT_USAGE
    if fake_fail is not None and (not fake or fake_fail not in FAKE_FAIL_MODES):
        protocol.error(
            protocol.ErrorCode.INVALID_ARGS,
            f"unknown --fake-fail mode: {fake_fail}",
            hint=f"choose one of: {', '.join(FAKE_FAIL_MODES)} (fake mode only)",
        )
        return protocol.EXIT_USAGE

    path: Path | None = None
    try:
        with _sigterm_cancels():
            path = run_get(asin, paths, fake=fake, fake_fail=fake_fail)
    except Cancelled:
        protocol.error(
            protocol.ErrorCode.CANCELLED,
            f"download cancelled: {asin}",
            hint="the partial download was removed",
        )
        return protocol.EXIT_ERROR
    except PipelineError as exc:
        protocol.error(exc.code, exc.message, exc.hint)
        return protocol.EXIT_ERROR
    else:
        protocol.done(path=str(path))
        return protocol.EXIT_OK


def cmd_cancel(args: Sequence[str], *, command: str, fake: bool, paths: Paths) -> int:
    """Signal the running ``get`` for ``asin`` (ARCHITECTURE 4.8)."""
    asin = args[0] if args else None
    if not asin:
        protocol.error(
            protocol.ErrorCode.INVALID_ARGS,
            "cancel needs an ASIN",
            hint="try: omarchy-audible cancel <asin>",
        )
        return protocol.EXIT_USAGE

    record = joblock.read_job_json(paths.job_json)
    pid = record.get("pid") if record else None
    if (
        not record
        or record.get("command") != "get"
        or record.get("asin") != asin
        or not isinstance(pid, int)
    ):
        protocol.error(
            protocol.ErrorCode.NOT_RUNNING,
            f"no download is running for {asin}",
            hint="nothing to cancel",
        )
        return protocol.EXIT_ERROR

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        joblock.remove_job_json(paths.job_json)
        protocol.error(
            protocol.ErrorCode.NOT_RUNNING,
            f"no download is running for {asin}",
            hint="nothing to cancel",
        )
        return protocol.EXIT_ERROR
    except OSError as exc:
        protocol.error(
            protocol.ErrorCode.INTERNAL,
            f"could not cancel the download: {exc}",
            hint="stop it manually if it is stuck",
        )
        return protocol.EXIT_ERROR

    protocol.done()
    return protocol.EXIT_OK


def cmd_local(args: Sequence[str], *, command: str, fake: bool, paths: Paths) -> int:
    """List the books downloaded on this machine (ARCHITECTURE 4.2)."""
    protocol.emit("local", books=scan_local(paths.books_dir))
    protocol.done()
    return protocol.EXIT_OK


def cmd_remove(args: Sequence[str], *, command: str, fake: bool, paths: Paths) -> int:
    """Delete one local book; never touches the Audible account (4.4)."""
    asin = args[0] if args else None
    if not asin:
        protocol.error(
            protocol.ErrorCode.INVALID_ARGS,
            "remove needs an ASIN",
            hint="try: omarchy-audible remove <asin>",
        )
        return protocol.EXIT_USAGE

    try:
        freed = remove_book(paths.books_dir, asin)
    except PipelineError as exc:
        protocol.error(exc.code, exc.message, exc.hint)
        return protocol.EXIT_ERROR

    protocol.done(freed_bytes=freed)
    return protocol.EXIT_OK


def _registry() -> dict[str, Command]:
    job = Command(cmd_unimplemented, True)
    plain = Command(cmd_unimplemented, False)
    return {
        "status": Command(cmd_status, False),
        "doctor": Command(cmd_doctor, False),
        "setup": job,
        "sync": job,
        "get": Command(cmd_get, True),
        "remove": Command(cmd_remove, True),
        "login-finish": job,
        "login-import-cli": job,
        "logout": job,
        "local": Command(cmd_local, False),
        "position-get": plain,
        "position-push": plain,
        "login-start": plain,
        "cancel": Command(cmd_cancel, False),
    }


REGISTRY: dict[str, Command] = _registry()
KNOWN_COMMANDS = frozenset(REGISTRY)
JOB_COMMANDS = frozenset(name for name, cmd in REGISTRY.items() if cmd.is_job)

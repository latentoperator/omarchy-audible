"""Command registry and the implemented backend commands.

Every command in ARCHITECTURE 4.2 is implemented: ``status``/``doctor`` (B1),
``setup`` (B2), the auth commands (B3), ``sync`` (B4),
``get``/``cancel``/``local``/``remove`` (B5), ``play-info`` (B11), and
``position-get``/``position-push`` (B6). Each registry entry carries its
job/non-job classification (ARCHITECTURE 4.8), which is what the job lock uses.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from . import fakestate, joblock, protocol
from .auth import (
    account_from_auth_file,
    login_finish,
    login_import_cli,
    login_start,
    logout,
    read_account_record,
    valid_session_id,
)
from .bootstrap import run_setup, venv_ready
from .catalog import open_client, run_sync
from .download import FAKE_FAIL_MODES, parse_fake_chapters, run_get
from .errors import Cancelled, PipelineError
from .library import play_info_payload, remove_book, scan_local, validate_asin
from .paths import Paths
from .positions import (
    FakePositions,
    RealPositions,
    fetch_positions,
    load_pushed,
    load_remote,
    mark_own_echoes,
    push_position,
    write_remote,
)

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


def _status_dirs(paths: Paths) -> dict[str, str]:
    """The resolved roots reported by ``status`` (B8), so QML never recomputes them."""
    return {
        "config_dir": str(paths.config_dir),
        "data_dir": str(paths.data_dir),
        "runtime_dir": str(paths.runtime_dir),
        "books_dir": str(paths.books_dir),
    }


def cmd_status(args: Sequence[str], *, command: str, fake: bool, paths: Paths) -> int:
    """Report readiness (ARCHITECTURE 4.2)."""
    if fake:
        # Fake mode pretends the tools and the venv are ready so the UI can run
        # with no account, no network and no virtualenv. Its sign-in state and
        # an optional tester override live in the fake tree, never the real one
        # (B9). The dirs are the fake tree too.
        overrides = fakestate.read_overrides(paths)
        missing = overrides.get("missing", [])
        venv = overrides.get("venv_ready", True)
        authenticated = not fakestate.signed_out(paths)
        protocol.emit(
            "status",
            ready=authenticated and not missing and venv,
            missing=missing,
            authenticated=authenticated,
            venv_ready=venv,
            marketplace=DEFAULT_MARKETPLACE,
            account=FAKE_ACCOUNT,
            catalog_age_s=None,
            **_status_dirs(paths),
        )
        protocol.done()
        return protocol.EXIT_OK

    missing = _missing_required_tools()
    authenticated = paths.auth_file.is_file()
    venv = venv_ready(paths.venv_dir)
    record = read_account_record(paths)
    account = record.get("account")
    if not (isinstance(account, str) and account):
        # ``login-finish`` registers with ``with_username=False``, so an email
        # is not always present; fall back to the saved login's customer_info
        # first name, read from auth.json as plain JSON (B9).
        account = account_from_auth_file(paths.auth_file)
    marketplace = record.get("marketplace") or DEFAULT_MARKETPLACE
    protocol.emit(
        "status",
        ready=authenticated and not missing and venv,
        missing=missing,
        authenticated=authenticated,
        venv_ready=venv,
        marketplace=marketplace,
        account=account if isinstance(account, str) else None,
        catalog_age_s=_catalog_age_s(paths),
        **_status_dirs(paths),
    )
    protocol.done()
    return protocol.EXIT_OK


def _tool_check(name: str) -> dict[str, object]:
    if name == "python":
        found = sys.executable
        ok = bool(found) and Path(found).is_file()
        return {"name": name, "ok": ok, "detail": found}
    found = shutil.which(name)
    return {
        "name": name,
        "ok": found is not None,
        "detail": found or f"{name} not found on PATH",
    }


def cmd_doctor(args: Sequence[str], *, command: str, fake: bool, paths: Paths) -> int:
    """Report the state of every external dependency (ARCHITECTURE 4.2).

    ``doctor`` always exits 0 once it has produced its report; the ``ok`` flags
    carry the findings so a caller can render them.
    """
    checks = [_tool_check(name) for name in DOCTOR_TOOLS]
    checks.append(
        {
            "name": "venv",
            "ok": venv_ready(paths.venv_dir),
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


def cmd_setup(args: Sequence[str], *, command: str, fake: bool, paths: Paths) -> int:
    """Create and verify the plugin virtualenv (ARCHITECTURE 4.1)."""
    try:
        run_setup(paths, fake=fake)
    except PipelineError as exc:
        protocol.error(exc.code, exc.message, exc.hint)
        return protocol.EXIT_ERROR
    if fake:
        # A successful ``setup --fake`` clears a tester's venv_ready override,
        # so the UI can leave the setup screen (B9).
        fakestate.clear_venv_ready_override(paths)
    protocol.done()
    return protocol.EXIT_OK


def cmd_sync(args: Sequence[str], *, command: str, fake: bool, paths: Paths) -> int:
    """Page the library and refresh ``catalog.json``/``remote.json`` (4.5, 4.6)."""
    record = read_account_record(paths)
    marketplace = record.get("marketplace")
    if not isinstance(marketplace, str) or not marketplace:
        marketplace = DEFAULT_MARKETPLACE
    try:
        run_sync(
            paths,
            fake=fake,
            full="--full" in args,
            marketplace=marketplace,
        )
    except PipelineError as exc:
        protocol.error(exc.code, exc.message, exc.hint)
        return _error_exit(exc)
    protocol.done()
    return protocol.EXIT_OK


def split_get_args(args: Sequence[str]) -> tuple[str | None, str | None, str | None]:
    """Split ``get`` arguments into ``(asin, fake_fail, fake_chapters)``.

    Tolerates an unknown flag by returning the tokens it could read; validation
    is the caller's job.
    """
    asin: str | None = None
    fake_fail: str | None = None
    fake_chapters: str | None = None
    index = 0
    while index < len(args):
        token = args[index]
        if token in ("--fake-fail", "--fake-chapters"):
            if index + 1 < len(args):
                if token == "--fake-fail":
                    fake_fail = args[index + 1]
                else:
                    fake_chapters = args[index + 1]
            index += 2
            continue
        if token.startswith("--fake-fail="):
            fake_fail = token.split("=", 1)[1]
            index += 1
            continue
        if token.startswith("--fake-chapters="):
            fake_chapters = token.split("=", 1)[1]
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        if asin is None:
            asin = token
        index += 1
    return asin, fake_fail, fake_chapters


def split_push_args(
    args: Sequence[str],
) -> tuple[str | None, str | None, str | None]:
    """Split ``position-push`` arguments into ``(asin, ms, local_updated_at)``.

    The local timestamp is the ``--at`` option: the time the listening that
    produced the position happened (ARCHITECTURE 4.6). It is required — without
    it the stale check cannot fire (F3), so the caller refuses a missing or
    empty value as ``invalid_args``.
    """
    asin: str | None = None
    ms_text: str | None = None
    local_updated_at: str | None = None
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--at":
            value = args[index + 1] if index + 1 < len(args) else ""
            # An empty or blank value is the same as no --at (F3).
            local_updated_at = value.strip() or None
            index += 2
            continue
        if token.startswith("--at="):
            local_updated_at = token.split("=", 1)[1].strip() or None
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        if asin is None:
            asin = token
        elif ms_text is None:
            ms_text = token
        index += 1
    return asin, ms_text, local_updated_at


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
    """Download one book, keeping the locked original (ARCHITECTURE 4.3)."""
    asin, fake_fail, fake_chapters_text = split_get_args(args)
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
    fake_chapters: int | None = None
    if fake_chapters_text is not None and fake:
        # Real mode ignores the flag; only fake mode has a chapter count to set.
        try:
            fake_chapters = parse_fake_chapters(fake_chapters_text)
        except PipelineError as exc:
            protocol.error(exc.code, exc.message, exc.hint)
            return protocol.EXIT_USAGE

    try:
        validate_asin(paths.books_dir, asin)
    except PipelineError as exc:
        protocol.error(exc.code, exc.message, exc.hint)
        return protocol.EXIT_USAGE

    path: Path | None = None
    try:
        with _sigterm_cancels():
            path = run_get(
                asin,
                paths,
                fake=fake,
                fake_fail=fake_fail,
                fake_chapters=fake_chapters,
            )
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

    try:
        validate_asin(paths.books_dir, asin)
    except PipelineError as exc:
        protocol.error(exc.code, exc.message, exc.hint)
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


def cmd_play_info(
    args: Sequence[str], *, command: str, fake: bool, paths: Paths
) -> int:
    """Describe how to play a local book (ARCHITECTURE 4.2, D7).

    A non-job command: it never takes ``job.lock``, so the drawer can ask about
    a book while another one is downloading. The ``lavf_options`` value it emits
    is a secret; it is the only event that carries one.
    """
    positional = _positional_args(args)
    asin = positional[0] if positional else None
    if not asin:
        protocol.error(
            protocol.ErrorCode.INVALID_ARGS,
            "play-info needs an ASIN",
            hint="try: omarchy-audible play-info <asin>",
        )
        return protocol.EXIT_USAGE

    try:
        payload = play_info_payload(paths, asin)
    except PipelineError as exc:
        protocol.error(exc.code, exc.message, exc.hint)
        return _error_exit(exc)

    protocol.write_event(payload)
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


def _positional_args(args: Sequence[str]) -> list[str]:
    """The non-flag tokens of ``args`` (ASIN lists)."""
    return [token for token in args if not token.startswith("-")]


@contextlib.contextmanager
def _positions_port(
    fake: bool, paths: Paths
) -> Iterator[FakePositions | RealPositions]:
    """A positions port over the fake fixture or an authenticated client.

    The real client is closed on the way out, like ``sync`` does.
    """
    if fake:
        yield FakePositions(paths.fake_positions_file)
        return
    with open_client(paths) as client:
        yield RealPositions(client)


def cmd_position_get(
    args: Sequence[str], *, command: str, fake: bool, paths: Paths
) -> int:
    """Read positions for the given ASINs and refresh ``remote.json`` (4.6)."""
    asins = _positional_args(args)
    if not asins:
        protocol.error(
            protocol.ErrorCode.INVALID_ARGS,
            "position-get needs at least one ASIN",
            hint="try: omarchy-audible position-get <asin> [<asin> ...]",
        )
        return protocol.EXIT_USAGE
    for asin in asins:
        try:
            validate_asin(paths.books_dir, asin)
        except PipelineError as exc:
            protocol.error(exc.code, exc.message, exc.hint)
            return protocol.EXIT_USAGE

    try:
        with _positions_port(fake, paths) as port:
            items = fetch_positions(asins, port)
    except PipelineError as exc:
        protocol.error(exc.code, exc.message, exc.hint)
        return _error_exit(exc)

    # Refresh the requested entries in place so the other cached books survive.
    cached = load_remote(paths.remote_file)
    cached.update(items)
    write_remote(paths.remote_file, cached)

    # Mark this device's own echo so the service can tell it from a phone
    # position with the same ms (P6, F1); `remote.json` keeps no `own` key.
    protocol.emit(
        "positions", items=mark_own_echoes(items, load_pushed(paths.pushed_file))
    )
    protocol.done()
    return protocol.EXIT_OK


def cmd_position_push(
    args: Sequence[str], *, command: str, fake: bool, paths: Paths
) -> int:
    """Write one local position back to the account (ARCHITECTURE 4.6)."""
    asin, ms_text, local_updated_at = split_push_args(args)
    if not asin or ms_text is None:
        protocol.error(
            protocol.ErrorCode.INVALID_ARGS,
            "position-push needs an ASIN and a position in milliseconds",
            hint="try: omarchy-audible position-push <asin> <ms> --at <iso-8601>",
        )
        return protocol.EXIT_USAGE
    if local_updated_at is None:
        # F3: without the local listening time the stale check can never fire,
        # so a push without --at (or with an empty one) is invalid, not "now".
        protocol.error(
            protocol.ErrorCode.INVALID_ARGS,
            "position-push needs --at <iso-8601>: the local listening time",
            hint="pass the listening time, e.g. --at 2026-01-01T00:00:00Z",
        )
        return protocol.EXIT_USAGE
    try:
        position_ms = int(ms_text)
    except ValueError:
        position_ms = -1
    if position_ms < 0:
        protocol.error(
            protocol.ErrorCode.INVALID_ARGS,
            f"invalid position: {ms_text!r}",
            hint="the position is a non-negative whole number of milliseconds",
        )
        return protocol.EXIT_USAGE

    try:
        validate_asin(paths.books_dir, asin)
    except PipelineError as exc:
        protocol.error(exc.code, exc.message, exc.hint)
        return protocol.EXIT_USAGE

    try:
        with _positions_port(fake, paths) as port:
            push_position(
                asin,
                position_ms,
                books_dir=paths.books_dir,
                port=port,
                local_updated_at=local_updated_at,
                pushed_path=paths.pushed_file,
            )
    except PipelineError as exc:
        protocol.error(exc.code, exc.message, exc.hint)
        return _error_exit(exc)
    protocol.done()
    return protocol.EXIT_OK


def _option(args: Sequence[str], name: str) -> str | None:
    """The value of ``--name value`` or ``--name=value``, else ``None``."""
    for index, token in enumerate(args):
        if token == name:
            return args[index + 1] if index + 1 < len(args) else None
        if token.startswith(name + "="):
            value = token.split("=", 1)[1]
            return value or None
    return None


def cmd_login_start(
    args: Sequence[str], *, command: str, fake: bool, paths: Paths
) -> int:
    """Build the sign-in URL and a pending session (ARCHITECTURE 4.7)."""
    marketplace = _option(args, "--marketplace") or DEFAULT_MARKETPLACE
    try:
        login_start(paths, marketplace=marketplace, fake=fake)
    except PipelineError as exc:
        protocol.error(exc.code, exc.message, exc.hint)
        return _error_exit(exc)
    protocol.done()
    return protocol.EXIT_OK


def cmd_login_finish(
    args: Sequence[str], *, command: str, fake: bool, paths: Paths
) -> int:
    """Redeem the pasted redirect URL, read from stdin, never argv (4.7)."""
    session_id = _option(args, "--session")
    if not session_id:
        protocol.error(
            protocol.ErrorCode.INVALID_ARGS,
            "login-finish needs --session <id>",
            hint="use the session id from login-start",
        )
        return protocol.EXIT_USAGE
    if not valid_session_id(session_id):
        protocol.error(
            protocol.ErrorCode.INVALID_ARGS,
            "invalid session id",
            hint="use the session id from login-start",
        )
        return protocol.EXIT_USAGE

    # The URL must never reach argv (/proc/<pid>/cmdline is world-readable),
    # so it is read from stdin and dropped as soon as it has been used.
    pasted = sys.stdin.read()
    try:
        contains = login_finish(
            paths, session_id=session_id, pasted_url=pasted, fake=fake
        )
    except PipelineError as exc:
        protocol.error(exc.code, exc.message, exc.hint)
        return _error_exit(exc)
    finally:
        pasted = ""
    protocol.done(clipboard_history_contains_code=contains)
    return protocol.EXIT_OK


def cmd_login_import_cli(
    args: Sequence[str], *, command: str, fake: bool, paths: Paths
) -> int:
    """Import an existing audible-cli login (ARCHITECTURE 4.7)."""
    source = _option(args, "--dir")
    source_dir = Path(source).expanduser() if source else None
    try:
        login_import_cli(paths, source_dir=source_dir, fake=fake)
    except PipelineError as exc:
        protocol.error(exc.code, exc.message, exc.hint)
        return _error_exit(exc)
    protocol.done()
    return protocol.EXIT_OK


def cmd_logout(args: Sequence[str], *, command: str, fake: bool, paths: Paths) -> int:
    """Deregister this device when we created it, then delete the auth files."""
    try:
        logout(paths, fake=fake)
    except PipelineError as exc:
        protocol.error(exc.code, exc.message, exc.hint)
        return _error_exit(exc)
    protocol.done()
    return protocol.EXIT_OK


def _error_exit(exc: PipelineError) -> int:
    """Usage problems exit 2; every other domain failure exits 1."""
    return (
        protocol.EXIT_USAGE
        if exc.code == protocol.ErrorCode.INVALID_ARGS
        else protocol.EXIT_ERROR
    )


def _registry() -> dict[str, Command]:
    return {
        "status": Command(cmd_status, False),
        "doctor": Command(cmd_doctor, False),
        "setup": Command(cmd_setup, True),
        "sync": Command(cmd_sync, True),
        "get": Command(cmd_get, True),
        "remove": Command(cmd_remove, True),
        "login-finish": Command(cmd_login_finish, True),
        "login-import-cli": Command(cmd_login_import_cli, True),
        "logout": Command(cmd_logout, True),
        "local": Command(cmd_local, False),
        "play-info": Command(cmd_play_info, False),
        "position-get": Command(cmd_position_get, False),
        "position-push": Command(cmd_position_push, False),
        "login-start": Command(cmd_login_start, False),
        "cancel": Command(cmd_cancel, False),
    }


REGISTRY: dict[str, Command] = _registry()
KNOWN_COMMANDS = frozenset(REGISTRY)
JOB_COMMANDS = frozenset(name for name, cmd in REGISTRY.items() if cmd.is_job)

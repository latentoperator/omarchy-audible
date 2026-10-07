"""Backend command-line entry point.

``main`` is what both ``bin/omarchy-audible`` and ``python -m omarchy_audible``
call. It resolves fake mode, builds the paths, classifies the command as a job
or not, and runs it. Job commands hold the non-blocking job lock; a held lock is
reported as ``error(code=busy)``. No other output reaches stdout.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence

from . import protocol
from .commands import REGISTRY, job_asin
from .joblock import JobBusy, job_lock
from .log import log
from .paths import Paths

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def env_is_fake(env: Mapping[str, str]) -> bool:
    return str(env.get("OMARCHY_AUDIBLE_FAKE", "")).strip().lower() in _TRUTHY


def strip_fake_flag(argv: Sequence[str]) -> tuple[list[str], bool]:
    """Return ``argv`` without ``--fake`` and whether the flag was present."""
    found = "--fake" in argv
    return [token for token in argv if token != "--fake"], found


def main(argv: Sequence[str] | None = None) -> int:
    # A C-locale shell would otherwise raise UnicodeEncodeError the moment an
    # event carried a non-ASCII character (an ASIN echo, an account name);
    # stdout is the NDJSON channel, so replace the character instead of failing
    # (F14). Guarded because a test harness may swap in a non-TextIOWrapper.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")

    argv = list(sys.argv[1:] if argv is None else argv)
    env = dict(os.environ)
    argv, flag_fake = strip_fake_flag(argv)
    fake = flag_fake or env_is_fake(env)
    paths = Paths.from_env(env, fake=fake)

    if not argv:
        protocol.error(
            protocol.ErrorCode.INVALID_ARGS,
            "no command given",
            hint="try: omarchy-audible status",
        )
        return protocol.EXIT_USAGE

    command, args = argv[0], argv[1:]
    spec = REGISTRY.get(command)
    if spec is None:
        protocol.error(
            protocol.ErrorCode.UNKNOWN_COMMAND,
            f"unknown command: {command}",
            hint="try: omarchy-audible doctor",
        )
        return protocol.EXIT_USAGE

    try:
        if spec.is_job:
            try:
                with job_lock(
                    paths,
                    write_record=command == "get",
                    pid=os.getpid(),
                    command=command,
                    asin=job_asin(command, args),
                ):
                    return spec.handler(args, command=command, fake=fake, paths=paths)
            except JobBusy:
                protocol.error(
                    protocol.ErrorCode.BUSY,
                    "another job is already running",
                    hint="wait for it to finish, or cancel the running download",
                )
                return protocol.EXIT_BUSY
        return spec.handler(args, command=command, fake=fake, paths=paths)
    except Exception as exc:  # noqa: BLE001
        # Top-level guard: a bug must still produce a valid NDJSON error event
        # rather than a traceback on stdout.
        log(f"{command} failed unexpectedly: {exc!r}", level="error")
        protocol.error(
            protocol.ErrorCode.INTERNAL,
            "internal error",
            hint="see stderr for details",
        )
        return protocol.EXIT_ERROR

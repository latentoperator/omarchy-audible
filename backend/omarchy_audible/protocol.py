"""NDJSON protocol writer (ARCHITECTURE 4.2).

Every subcommand writes one JSON object per line to stdout and ends with a
single ``done`` or ``error`` event. Nothing else may reach stdout.
"""

from __future__ import annotations

import json
import sys
from typing import Any

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_BUSY = 3


class ErrorCode:
    """Stable error codes used in ``error`` events."""

    INVALID_ARGS = "invalid_args"
    UNKNOWN_COMMAND = "unknown_command"
    NOT_IMPLEMENTED = "not_implemented"
    NO_VENV = "no_venv"
    BUSY = "busy"
    INTERNAL = "internal"

    # get / cancel / remove (B5, ARCHITECTURE 4.3, 4.4, 4.8)
    DISK_SPACE = "disk_space"
    NETWORK = "network"
    DECRYPT = "decrypt"
    CONVERT = "convert"
    NO_VOUCHER = "no_voucher"
    CANCELLED = "cancelled"
    NOT_RUNNING = "not_running"
    NOT_LOCAL = "not_local"
    UNSAFE_PATH = "unsafe_path"
    AUTH_FAILED = "auth_failed"


def write_event(event: dict[str, Any]) -> None:
    """Write one already-formed event as a single NDJSON line."""
    sys.stdout.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n")
    sys.stdout.flush()


def emit(event_type: str, **fields: Any) -> None:
    """Emit an event of ``event_type`` carrying ``fields``."""
    event: dict[str, Any] = {"type": event_type}
    event.update(fields)
    write_event(event)


def done(**fields: Any) -> None:
    """Emit the terminal ``done`` event of a successful run."""
    emit("done", **fields)


def error(code: str, message: str, hint: str | None = None) -> None:
    """Emit the terminal ``error`` event of a failed run."""
    event: dict[str, Any] = {"type": "error", "code": code, "message": message}
    if hint:
        event["hint"] = hint
    write_event(event)

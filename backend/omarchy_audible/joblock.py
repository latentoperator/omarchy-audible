"""Job lock and ``job.json`` record (ARCHITECTURE 4.8).

Job commands take an exclusive, non-blocking ``flock`` on ``job.lock`` for the
duration of the run. If the lock is already held they fail with
``error(code=busy)``. Non-job commands never touch the lock, so ``status``,
``position-get`` and pushes keep working during a download.

Only ``get`` writes ``job.json`` (so ``cancel`` can find its pid); the helpers
here are shared by the command layer.
"""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import fsutil


class JobBusy(RuntimeError):
    """Raised when another process already holds the job lock."""


def try_acquire(lock_path: Path) -> int | None:
    """Try to take the exclusive lock without waiting.

    Returns an open file descriptor that holds the lock, or ``None`` when it is
    already held.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def release(fd: int) -> None:
    """Release a lock returned by :func:`try_acquire` and close it."""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@contextmanager
def job_lock(
    paths: Any,
    *,
    write_record: bool = False,
    pid: int | None = None,
    command: str | None = None,
    asin: str | None = None,
) -> Iterator[None]:
    """Hold the job lock for the body, raising :class:`JobBusy` if it is held.

    With ``write_record`` the ``job.json`` record is written on entry and
    removed on exit, on both the success and failure paths.
    """
    fd = try_acquire(paths.job_lock)
    if fd is None:
        raise JobBusy(str(paths.job_lock))
    record_written = False
    try:
        if write_record:
            write_job_json(paths.job_json, pid or os.getpid(), command or "", asin)
            record_written = True
        yield
    finally:
        if record_written:
            remove_job_json(paths.job_json)
        release(fd)


def write_job_json(path: Path, pid: int, command: str, asin: str | None = None) -> None:
    """Atomically write ``{pid, command, asin}`` for the running job."""
    data: dict[str, Any] = {"pid": int(pid), "command": str(command)}
    if asin is not None:
        data["asin"] = str(asin)
    fsutil.atomic_write_json(path, data)


def read_job_json(path: Path) -> dict[str, Any] | None:
    """Read the running-job record, or ``None`` when it is absent or unreadable."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def remove_job_json(path: Path) -> None:
    """Remove the running-job record if present."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass

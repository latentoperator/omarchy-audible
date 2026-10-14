"""Small filesystem helpers shared by the backend."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file in the same dir, then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, data: Any) -> None:
    """Serialise ``data`` as compact JSON and write it atomically."""
    atomic_write_text(
        path, json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n"
    )


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically (temp file in the same dir, then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def ensure_private_dir(path: Path) -> None:
    """Create ``path`` as ``0700`` (best effort on a pre-existing directory)."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path, 0o700)
    except OSError:  # pragma: no cover - a directory we cannot chmod
        pass


_ACL_XATTRS = ("system.posix_acl_default", "system.posix_acl_access")


class StagingDirError(OSError):
    """A private staging directory could not be set up; nothing may write there."""


def make_private_staging_dir(path: Path) -> None:
    """Create ``path`` fresh as a ``0700`` directory with no POSIX ACLs.

    It fails closed: anything already at ``path`` (a directory a cleanup could
    not remove, a symlink, a file), a parent that is not a directory of ours,
    or a mode that does not come out ``0700`` raises :class:`StagingDirError`
    instead of reusing what is there. A parent of ours that group or others
    can write to (a ``002`` umask) loses those bits first, so nobody else can
    swap ``path`` for a directory of their own.

    A directory inherits its parent's default ACL, and a default ACL makes the
    kernel ignore the umask for every file created inside, so a child's
    ``0666`` open could still grant access to the users the ACL names. Both
    ACLs are removed, so the ``0700`` mode and the child's umask decide.
    """
    parent = path.parent
    parent_stat = os.lstat(parent)
    if not stat.S_ISDIR(parent_stat.st_mode) or parent_stat.st_uid != os.geteuid():
        raise StagingDirError(f"{parent.name} is not a directory of ours")
    shared_write = stat.S_IWGRP | stat.S_IWOTH
    if parent_stat.st_mode & shared_write:
        os.chmod(parent, stat.S_IMODE(parent_stat.st_mode) & ~shared_write)
    try:
        os.mkdir(path, 0o700)
    except FileExistsError as exc:
        raise StagingDirError(f"{path.name} already exists") from exc
    for name in _ACL_XATTRS:
        try:
            os.removexattr(path, name)
        except OSError:  # no ACL there, or a filesystem without ACL support
            pass
    os.chmod(path, 0o700)
    made = os.lstat(path)
    if (
        not stat.S_ISDIR(made.st_mode)
        or made.st_uid != os.geteuid()
        or stat.S_IMODE(made.st_mode) != 0o700
    ):
        raise StagingDirError(f"{path.name} is not a private directory")


def write_private_text(path: Path, text: str) -> None:
    """Create ``path`` as ``0600`` and write ``text``.

    The mode is set at creation (``os.open``), so the file never exists at a
    wider mode for even an instant (B11 ``key.json``, ARCHITECTURE 3).
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = text.encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def write_private_json(path: Path, data: Any) -> None:
    """Serialise ``data`` as compact JSON and write it ``0600``."""
    write_private_text(
        path, json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n"
    )


def atomic_replace(src: Path, dst: Path) -> None:
    """Move ``src`` onto ``dst`` in one step (ARCHITECTURE 4.3 step 5).

    ``os.replace`` is atomic within a filesystem, so ``dst`` never exists in a
    half-written state; callers write to a sibling ``*.tmp`` first.
    """
    os.replace(src, dst)

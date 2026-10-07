"""Small filesystem helpers shared by the backend."""

from __future__ import annotations

import json
import os
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
    atomic_write_text(path, json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n")


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

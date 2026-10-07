"""F13 — the runtime-dir fallback under the system temp dir is private (0700).

``XDG_RUNTIME_DIR`` has no standard fallback, so the backend uses
``<temp>/omarchy-audible-<uid>``. It holds the job lock and the mpv socket, so
it must not be world- or group-readable, and an existing directory of ours that
is looser is tightened.
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from omarchy_audible import joblock
from omarchy_audible.paths import PLUGIN_DIR_NAME, Paths


def _fallback(root: Path) -> Path:
    return root / f"{PLUGIN_DIR_NAME}-{os.getuid()}"


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _env(tmp_path: Path) -> dict[str, str]:
    # No XDG_RUNTIME_DIR: the fallback is the one under test.
    return {"HOME": str(tmp_path / "home")}


def test_the_fallback_is_created_0700(tmp_path, monkeypatch):
    root = tmp_path / "tmp"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))

    resolved = Paths.from_env(_env(tmp_path))

    fallback = _fallback(root)
    assert resolved.runtime_dir.parent == fallback
    assert _mode(fallback) == 0o700


def test_the_fallback_is_tightened_when_it_already_exists_looser(tmp_path, monkeypatch):
    root = tmp_path / "tmp"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    fallback = _fallback(root)
    fallback.mkdir(mode=0o755)
    os.chmod(fallback, 0o755)

    Paths.from_env(_env(tmp_path))

    assert _mode(fallback) == 0o700


def test_the_runtime_dir_under_the_fallback_is_private_too(tmp_path, monkeypatch):
    root = tmp_path / "tmp"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    resolved = Paths.from_env(_env(tmp_path))

    fd = joblock.try_acquire(resolved.job_lock)  # creates the runtime dir

    assert fd is not None
    joblock.release(fd)
    assert _mode(resolved.runtime_dir) == 0o700
    assert resolved.runtime_dir.parent == _fallback(root)

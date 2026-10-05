"""Filesystem layout for the plugin (ARCHITECTURE 3).

Every path derives from ``XDG_CONFIG_HOME``, ``XDG_DATA_HOME`` and
``XDG_RUNTIME_DIR`` (standard defaults when unset) and ``OMARCHY_AUDIBLE_BOOKS_DIR``.
Nothing here touches a user's own ``~/.audible`` or other tools' directories.

Fake mode resolves to separate roots (``omarchy-audible-fake``) so testing with
``--fake`` never reads or writes the real login, catalog or books, and ignores
``OMARCHY_AUDIBLE_BOOKS_DIR``.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PLUGIN_DIR_NAME = "omarchy-audible"
FAKE_DIR_NAME = f"{PLUGIN_DIR_NAME}-fake"


def _xdg_dir(env: Mapping[str, str], var: str, default: Path) -> Path:
    value = env.get(var)
    return Path(value) if value else default


def _runtime_dir(env: Mapping[str, str], home: Path) -> Path:
    value = env.get("XDG_RUNTIME_DIR")
    if value:
        return Path(value)
    # XDG_RUNTIME_DIR has no standard fallback; use a per-user directory under
    # the system temp dir so jobs and the mpv socket still have a place to live.
    return Path(tempfile.gettempdir()) / f"{PLUGIN_DIR_NAME}-{os.getuid()}"


@dataclass(frozen=True)
class Paths:
    """Resolved on-disk locations for one invocation of the backend."""

    config_dir: Path
    data_dir: Path
    runtime_dir: Path
    books_dir: Path

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None, *, fake: bool = False
    ) -> Paths:
        env = dict(os.environ) if env is None else env
        home = Path(env.get("HOME") or Path.home())
        config_root = _xdg_dir(env, "XDG_CONFIG_HOME", home / ".config")
        data_root = _xdg_dir(env, "XDG_DATA_HOME", home / ".local" / "share")
        if fake:
            # Fake mode owns a parallel tree so it can never clobber the real
            # plugin folders (ARCHITECTURE 3).
            data_dir = data_root / FAKE_DIR_NAME
            return cls(
                config_dir=config_root / FAKE_DIR_NAME,
                data_dir=data_dir,
                runtime_dir=_runtime_dir(env, home) / FAKE_DIR_NAME,
                books_dir=data_dir / "books",
            )
        books = env.get("OMARCHY_AUDIBLE_BOOKS_DIR")
        return cls(
            config_dir=config_root / PLUGIN_DIR_NAME,
            data_dir=data_root / PLUGIN_DIR_NAME,
            runtime_dir=_runtime_dir(env, home) / PLUGIN_DIR_NAME,
            books_dir=Path(books) if books else home / "Audiobooks" / "Audible",
        )

    # --- plugin-owned files (ARCHITECTURE 3) -------------------------------
    @property
    def venv_dir(self) -> Path:
        return self.data_dir / "venv"

    @property
    def venv_python(self) -> Path:
        return self.venv_dir / "bin" / "python"

    @property
    def auth_file(self) -> Path:
        return self.config_dir / "auth.json"

    @property
    def activation_bytes_file(self) -> Path:
        return self.config_dir / "activation_bytes"

    @property
    def config_toml(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def account_file(self) -> Path:
        return self.config_dir / "account.json"

    @property
    def catalog_file(self) -> Path:
        return self.data_dir / "catalog.json"

    @property
    def remote_file(self) -> Path:
        return self.data_dir / "remote.json"

    @property
    def state_file(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def covers_dir(self) -> Path:
        return self.data_dir / "covers"

    @property
    def mpv_socket(self) -> Path:
        return self.runtime_dir / "mpv.sock"

    @property
    def job_lock(self) -> Path:
        return self.runtime_dir / "job.lock"

    @property
    def job_json(self) -> Path:
        return self.runtime_dir / "job.json"

    def login_session(self, session_id: str) -> Path:
        return self.runtime_dir / f"login-{session_id}.json"

"""Filesystem layout for the plugin (ARCHITECTURE 3).

Every path derives from ``XDG_CONFIG_HOME``, ``XDG_DATA_HOME`` and
``XDG_RUNTIME_DIR`` (standard defaults when unset) and ``OMARCHY_AUDIBLE_BOOKS_DIR``.
Nothing here touches a user's own ``~/.audible`` or other tools' directories.

Fake mode resolves to separate roots (``omarchy-audible-fake``) so testing with
``--fake`` never reads or writes the real login, catalog or books. It accepts a
books-folder override only when it resolves inside the fake data directory.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PLUGIN_DIR_NAME = "omarchy-audible"
FAKE_DIR_NAME = f"{PLUGIN_DIR_NAME}-fake"
# Fake mode's kept positions (B10); it exists only under the fake data dir.
FAKE_POSITIONS_FILE = "fake-account-positions.json"
# This device's own successful pushes, ``{asin: {ms, at}}`` (P6, F1).
PUSHED_FILE = "pushed.json"
BOOKS_LOCATION_FILE = "books-location.json"


def requested_books_dir(value: str | None, home: Path) -> Path:
    """Parse the setting without shell expansion; empty values select default."""
    raw = (value or "").strip()
    if not raw:
        return home / "Audiobooks" / "Audible"
    if raw == "~":
        return home
    if raw.startswith("~/"):
        return home / raw[2:].lstrip("/")
    return Path(raw)


def books_dir_problem(path: Path, paths: Paths, home: Path) -> str | None:
    """Return why a requested books path is unsafe or unusable."""
    try:
        raw = str(path)
        if "\0" in raw:
            return "path contains a NUL character"
        if not path.is_absolute():
            return "path must be absolute (or start with ~/)"
        resolved = path.resolve()
        home_resolved = home.resolve()
        if resolved == Path("/"):
            return "path cannot be /"
        if resolved == home_resolved:
            return "path cannot be your home folder"
        forbidden_roots = (
            paths.config_dir,
            paths.data_dir,
            paths.runtime_dir,
            paths.venv_dir,
        )
        for root in forbidden_roots:
            target = root.resolve()
            if resolved == target or target.is_relative_to(resolved):
                return "path cannot contain plugin data or runtime files"
        for root in (
            paths.config_dir,
            paths.runtime_dir,
            paths.venv_dir,
            home / ".audible",
        ):
            if resolved == root.resolve() or resolved.is_relative_to(root.resolve()):
                return "path cannot be inside plugin configuration, runtime, venv, or ~/.audible"
        system_roots = tuple(
            Path(value)
            for value in (
                "/proc",
                "/sys",
                "/dev",
                "/boot",
                "/etc",
                "/usr",
                "/bin",
                "/sbin",
                "/lib",
                "/lib64",
            )
        )
        if any(
            resolved == root or resolved.is_relative_to(root) for root in system_roots
        ):
            return "path cannot be inside a system directory"
        if resolved.exists() and not resolved.is_dir():
            return "path exists and is not a directory"
        ancestor = resolved
        while not ancestor.exists() and ancestor != ancestor.parent:
            ancestor = ancestor.parent
        if ancestor.exists() and not ancestor.is_dir():
            return "nearest existing ancestor is not a directory"
    except (OSError, RuntimeError, ValueError):
        return "path cannot be resolved"
    return None


def _xdg_dir(env: Mapping[str, str], var: str, default: Path) -> Path:
    value = env.get(var)
    return Path(value) if value else default


def _runtime_dir(env: Mapping[str, str], home: Path) -> Path:
    value = env.get("XDG_RUNTIME_DIR")
    if value:
        return Path(value)
    # XDG_RUNTIME_DIR has no standard fallback; use a per-user directory under
    # the system temp dir so jobs and the mpv socket still have a place to live.
    # It holds the job lock and the mpv socket, so it is created ``0700`` — and
    # tightened when it already exists looser and is ours (F13).
    fallback = Path(tempfile.gettempdir()) / f"{PLUGIN_DIR_NAME}-{os.getuid()}"
    _ensure_private_owned_dir(fallback)
    return fallback


def _ensure_private_owned_dir(path: Path) -> None:
    """Create ``path`` as ``0700``, or tighten it when it is ours (F13).

    Anything that is not a directory we own (a symlink, another user's file) is
    left alone.
    """
    try:
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            return
        path.mkdir(mode=0o700, exist_ok=True)
        stat_result = path.stat()
        if stat_result.st_uid == os.getuid() and stat_result.st_mode & 0o077:
            os.chmod(path, 0o700)
    except OSError:  # pragma: no cover - a temp dir we cannot create or chmod
        pass


@dataclass(frozen=True)
class Paths:
    """Filesystem locations for one invocation of the backend."""

    config_dir: Path
    data_dir: Path
    runtime_dir: Path
    books_dir: Path
    default_books_dir: Path
    home_dir: Path
    fake_mode: bool = False
    books_dir_problem: str | None = None

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
            result = cls(
                config_dir=config_root / FAKE_DIR_NAME,
                data_dir=data_dir,
                runtime_dir=_runtime_dir(env, home) / FAKE_DIR_NAME,
                books_dir=data_dir / "books",
                default_books_dir=data_dir / "books",
                home_dir=home,
                fake_mode=True,
            )
            override = env.get("OMARCHY_AUDIBLE_BOOKS_DIR")
            if not (override or "").strip():
                return result
            requested = requested_books_dir(override, home)
            real_default = home / "Audiobooks" / "Audible"
            try:
                if requested.resolve() == real_default.resolve():
                    return result
            except (OSError, RuntimeError, ValueError):
                pass
            try:
                inside = (
                    requested.resolve().is_relative_to(data_dir.resolve())
                    and requested.resolve() != data_dir.resolve()
                )
            except (OSError, RuntimeError, ValueError):
                inside = False
            if not inside:
                return cls(
                    **{
                        **result.__dict__,
                        "books_dir_problem": "fake mode only allows paths inside its data directory",
                    }
                )
            problem = books_dir_problem(requested, result, home)
            return cls(
                **{
                    **result.__dict__,
                    "books_dir": requested if problem is None else result.books_dir,
                    "books_dir_problem": problem,
                }
            )
        books = env.get("OMARCHY_AUDIBLE_BOOKS_DIR")
        result = cls(
            config_dir=config_root / PLUGIN_DIR_NAME,
            data_dir=data_root / PLUGIN_DIR_NAME,
            runtime_dir=_runtime_dir(env, home) / PLUGIN_DIR_NAME,
            books_dir=home / "Audiobooks" / "Audible",
            default_books_dir=home / "Audiobooks" / "Audible",
            home_dir=home,
        )
        requested = requested_books_dir(books, home)
        problem = books_dir_problem(requested, result, home)
        return cls(
            **{
                **result.__dict__,
                "books_dir": requested if problem is None else result.default_books_dir,
                "books_dir_problem": problem,
            }
        )

    @property
    def books_location_file(self) -> Path:
        return self.data_dir / BOOKS_LOCATION_FILE

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
    def pushed_file(self) -> Path:
        """This device's own successful pushes, ``{asin: {ms, at}}`` (P6, F1).

        ``position-push`` writes it and ``position-get`` reads it, so an echo
        of our own push is never taken for a newer position. Fake mode resolves
        to the fake data dir, like ``remote.json``.
        """
        return self.data_dir / PUSHED_FILE

    @property
    def state_file(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def fake_positions_file(self) -> Path:
        """Fake mode's kept positions (B10): ``position-push`` writes it.

        ``position-get --fake`` and ``sync --fake`` read it back. It lives only
        under the fake data dir; real mode never constructs the fake port.
        """
        return self.data_dir / FAKE_POSITIONS_FILE

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

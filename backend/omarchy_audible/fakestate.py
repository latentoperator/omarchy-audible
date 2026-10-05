"""Fake-mode onboarding state (B9, ARCHITECTURE 4.2).

Fake mode pretends the tools and the virtualenv are ready, so the UI can run
with no account. It also carries its own sign-in state and an optional tester
override, so the onboarding view's "connect", "run setup" and "missing tools"
screens can be exercised without a real account. Every file here lives in the
*fake* config directory; real mode never reads any of them.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import fsutil
from .paths import Paths

# Presence of this marker means ``logout --fake`` signed the fake account out.
# A fresh fake tree has no marker, so it starts signed in.
SIGNED_OUT_MARKER = "fake-signed-out"
# Optional override written by a tester: {"missing": [...], "venv_ready": bool}.
STATUS_OVERRIDES_FILE = "fake-status.json"


def marker_path(paths: Paths) -> Path:
    """The fake signed-out marker for this tree."""
    return paths.config_dir / SIGNED_OUT_MARKER


def overrides_path(paths: Paths) -> Path:
    """The optional fake ``status`` override file for this tree."""
    return paths.config_dir / STATUS_OVERRIDES_FILE


def signed_out(paths: Paths) -> bool:
    """True when the fake account has been signed out (B9)."""
    return marker_path(paths).is_file()


def mark_signed_out(paths: Paths) -> None:
    """``logout --fake``: sign the fake account out."""
    marker = marker_path(paths)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()


def mark_signed_in(paths: Paths) -> None:
    """``login-finish --fake`` / ``login-import-cli --fake``: sign back in."""
    try:
        marker_path(paths).unlink()
    except FileNotFoundError:
        pass


def read_overrides(paths: Paths) -> dict[str, object]:
    """The valid keys of ``fake-status.json``, or ``{}`` when absent or bad.

    Only the documented keys with the documented types are returned, so a
    malformed file cannot make ``status`` emit a schema violation.
    """
    try:
        data = json.loads(overrides_path(paths).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    overrides: dict[str, object] = {}
    missing = data.get("missing")
    if isinstance(missing, list) and all(isinstance(item, str) for item in missing):
        overrides["missing"] = list(missing)
    venv_ready = data.get("venv_ready")
    if isinstance(venv_ready, bool):
        overrides["venv_ready"] = venv_ready
    return overrides


def clear_venv_ready_override(paths: Paths) -> None:
    """``setup --fake``: report ``venv_ready`` true again (B9).

    Only the ``venv_ready`` key is dropped; a tester's ``missing`` override
    stays, so the missing-tools screen can survive a setup run.
    """
    path = overrides_path(paths)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    data.pop("venv_ready", None)
    try:
        if data:
            fsutil.atomic_write_json(path, data)
        else:
            path.unlink()
    except OSError:
        pass

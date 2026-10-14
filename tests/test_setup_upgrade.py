"""B04b: offline 0.1.5 upgrades must not require another Set up click."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from test_launcher import _load_launcher
from test_setup_repair import offline_env, offline_repair, status  # noqa: F401

import qjs
from omarchy_audible import bootstrap

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def legacy_env(offline_env):  # noqa: F811 — shared pytest fixture
    paths, site = offline_env
    # Exact _write_marker shape from d82b252 (0.1.5).
    marker = {
        "schema": 1,
        "requirements": bootstrap.requirements_digest(bootstrap.requirements_path()),
        "requirements_file": "requirements.lock",
        "created_at": "2026-10-01T12:00:00Z",
    }
    bootstrap.fsutil.atomic_write_json(bootstrap.marker_path(paths.venv_dir), marker)
    return paths, site, marker


def launch(command):
    result = subprocess.run(
        [sys.executable, str(ROOT / "bin/omarchy-audible"), command],
        env=dict(os.environ),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return result, [json.loads(line) for line in result.stdout.splitlines()]


def test_legacy_launcher_dispatches_before_status_then_migrates_once(
    legacy_env, monkeypatch
):
    paths, _, legacy = legacy_env
    assert _load_launcher()._venv_ready(paths.venv_python)
    before, events = launch("local")
    assert before.returncode == 0, before.stdout + before.stderr
    assert events == [{"type": "local", "books": []}, {"type": "done"}]
    assert bootstrap.read_marker(paths.venv_dir) == legacy

    first, events = launch("status")
    assert first.returncode == 0, first.stdout + first.stderr
    assert events[0]["venv_state"] == "current_ready"
    assert events[0]["venv_ready"] is True
    marker = bootstrap.read_marker(paths.venv_dir)
    assert marker["schema"] == 2
    assert marker["requirements"] == legacy["requirements"]
    assert stat.S_IMODE(bootstrap.marker_path(paths.venv_dir).stat().st_mode) == 0o600

    with monkeypatch.context() as scoped:
        scoped.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("poll spawned"))
        assert status(paths, scoped)["venv_state"] == "current_ready"
        assert bootstrap.read_marker(paths.venv_dir) == marker
    after, events = launch("local")
    assert after.returncode == 0, after.stdout + after.stderr
    assert events == [{"type": "local", "books": []}, {"type": "done"}]


def test_legacy_first_status_probes_exactly_once(legacy_env, monkeypatch):
    paths, _, _ = legacy_env
    original = subprocess.run
    calls = []

    def counted(argv, **kwargs):
        assert argv[0] == str(paths.venv_python)
        assert "-I" in argv and kwargs["timeout"] == bootstrap.PROBE_TIMEOUT
        assert "PYTHONPATH" not in kwargs["env"]
        assert "AUDIBLE_CONFIG_DIR" not in kwargs["env"]
        calls.append(argv)
        return original(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", counted)
    assert status(paths, monkeypatch)["venv_state"] == "current_ready"
    assert status(paths, monkeypatch)["venv_state"] == "current_ready"
    assert len(calls) == 1


def test_failed_legacy_probe_is_cached_refuses_dispatch_and_setup_repairs(
    legacy_env, monkeypatch
):
    paths, site, _ = legacy_env
    (site / "audible/__init__.py").write_text("raise ImportError('synthetic')\n")
    assert status(paths, monkeypatch)["venv_state"] == "broken"
    assert bootstrap.read_marker(paths.venv_dir)["schema"] == 2
    refused, events = launch("local")
    assert refused.returncode != 0
    assert events[-1]["code"] == "no_venv"
    with monkeypatch.context() as scoped:
        scoped.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("poll spawned"))
        assert status(paths, scoped)["venv_state"] == "broken"
    bootstrap.run_setup(paths, run=offline_repair)
    assert status(paths, monkeypatch)["venv_state"] == "current_ready"
    assert _load_launcher()._venv_ready(paths.venv_python)


def test_legacy_stale_digest_preserved_and_dispatchable(legacy_env, monkeypatch):
    paths, _, marker = legacy_env
    marker["requirements"] = "0" * 64
    bootstrap.fsutil.atomic_write_json(bootstrap.marker_path(paths.venv_dir), marker)
    report = status(paths, monkeypatch)
    assert report["venv_state"] == "usable_old"
    assert report["venv_ready"] is False
    assert bootstrap.read_marker(paths.venv_dir)["requirements"] == "0" * 64
    result, events = launch("local")
    assert result.returncode == 0, events


def test_legacy_stale_installed_pin_is_usable_old(legacy_env, monkeypatch):
    paths, site, _ = legacy_env
    (site / "audible-0.12.0.dist-info/METADATA").write_text(
        "Metadata-Version: 2.1\nName: audible\nVersion: 0.0.0\n"
    )
    report = status(paths, monkeypatch)
    assert report["venv_state"] == "usable_old"
    assert report["venv_ready"] is False
    assert _load_launcher()._venv_ready(paths.venv_python)


def test_concurrent_legacy_status_writes_are_atomic_and_private(
    legacy_env, monkeypatch
):
    paths, _, _ = legacy_env
    original = subprocess.run
    barrier = Barrier(2)

    def racing(argv, **kwargs):
        if "-c" in argv:
            barrier.wait(timeout=10)
        return original(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", racing)
    # Force both probes to overlap before either can publish its result.
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(
            pool.map(
                lambda _: bootstrap.migrate_legacy_marker(paths.venv_dir), range(2)
            )
        )
    assert status(paths, monkeypatch)["venv_state"] == "current_ready"
    assert bootstrap.venv_ready(paths.venv_dir)
    assert _load_launcher()._venv_ready(paths.venv_python)
    assert stat.S_IMODE(bootstrap.marker_path(paths.venv_dir).stat().st_mode) == 0o600
    assert not list(paths.venv_dir.glob(".*.tmp"))


@pytest.mark.parametrize(
    "payload",
    ["{", "[]", "null", '{"schema":1}', '{"schema":true}', '{"schema":3}'],
)
def test_garbled_marker_never_probed_or_dispatched(legacy_env, monkeypatch, payload):
    paths, _, _ = legacy_env
    bootstrap.marker_path(paths.venv_dir).write_text(payload)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("poll spawned"))
    assert status(paths, monkeypatch)["venv_state"] == "broken"
    assert not _load_launcher()._venv_ready(paths.venv_python)
    assert bootstrap.marker_path(paths.venv_dir).read_text() == payload


def test_failed_migration_write_keeps_legacy_marker_intact(legacy_env, monkeypatch):
    paths, _, legacy = legacy_env

    def fail(*args, **kwargs):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(bootstrap.fsutil, "atomic_write_json", fail)
    assert status(paths, monkeypatch)["venv_state"] == "broken"
    assert bootstrap.read_marker(paths.venv_dir) == legacy
    assert _load_launcher()._venv_ready(paths.venv_python)


@pytest.mark.parametrize(
    "state,word",
    [("missing", "not installed yet"), ("broken", "repair"), ("usable_old", "updat")],
)
def test_setup_copy_describes_environment_state(state, word):
    onboarding = qjs.load("Onboarding")
    text = onboarding.call("setupText", {"venv_state": state})
    assert word in text.lower()
    if state != "missing":
        assert "not installed yet" not in text


def test_setup_view_uses_state_aware_copy_without_changing_progress():
    source = (ROOT / "qml/views/OnboardingView.qml").read_text()
    assert "Onboarding.setupText(root.status)" in source
    assert "Signin.setupLine(true," in source

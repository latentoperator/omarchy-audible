"""Offline reviewer probes. All data is synthetic and kept under scratch.
Run with the clone's .venv Python and PYTHONDONTWRITEBYTECODE=1.
Set TMPDIR to a disposable scratch directory. Outputs describe baseline bugs,
not product-test success; fault injection and API stubs are intentional.
No real credentials, audio, Audible network, or repo writes.
"""

import contextlib
import errno
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[3]
SCRATCH = Path(tempfile.gettempdir())
sys.path.insert(0, str(REPO / "backend"))
from omarchy_audible import auth, bootstrap, catalog, commands, download, library
from omarchy_audible.audible_download import MODELS_LOGGER, LicenseDenialWatch
from omarchy_audible.paths import Paths


def paths(root, fake=False):
    env = {
        "HOME": str(root / "home"),
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_DATA_HOME": str(root / "data"),
        "XDG_RUNTIME_DIR": str(root / "runtime"),
    }
    return Paths.from_env(env, fake=fake)


def emit_result(name, **fields):
    print(json.dumps({"probe": name, **fields}, sort_keys=True))


def repro_backup_failure(root):
    p = paths(root, fake=True)
    directory = p.books_dir / "B00FAKE01"
    directory.mkdir(parents=True)
    (directory / "book.aaxc").write_bytes(b"old synthetic audio")
    (directory / "key.json").write_text(
        json.dumps({"format": "aaxc", "key": "FAKE", "iv": "FAKE"})
    )
    before_local = library.local_audio_file(directory) is not None
    original_replace = os.replace

    def fail_second_backup(src, dst):
        if Path(src) == directory / "key.json" and Path(dst).parent.name == "old":
            raise OSError(errno.EIO, "injected second backup rename failure")
        return original_replace(src, dst)

    def fake_fetch(asin, partial, *args):
        source = partial / "synthetic.aaxc"
        source.write_bytes(b"new synthetic audio")
        return download.RawDownload(source, "aaxc", [], "FAKE", "FAKE")

    failure = None
    with (
        patch.object(download, "_fake_fetch", fake_fetch),
        patch.object(download, "_verify_duration", lambda *a: None),
        patch.object(download.os, "replace", fail_second_backup),
    ):
        try:
            download.run_get("B00FAKE01", p, fake=True, emit=lambda *a, **k: None)
        except OSError as exc:
            failure = type(exc).__name__
    emit_result(
        "backup_rename_failure",
        exception=failure,
        old_book_local_before=before_local,
        old_audio_exists_after=(directory / "book.aaxc").exists(),
        local_after=library.local_audio_file(directory) is not None,
        recovery_partial_exists=(directory / ".partial").exists(),
    )


def repro_fake_default_symlink(root):
    real = paths(root)
    fake = paths(root, fake=True)
    target = real.books_dir / "B00FAKE01"
    target.mkdir(parents=True)
    (target / "book.m4b").write_bytes(b"synthetic real-tree sentinel")
    fake.data_dir.mkdir(parents=True)
    fake.books_dir.symlink_to(real.books_dir, target_is_directory=True)
    resolved = paths(root, fake=True)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        result = commands.cmd_remove(
            ["B00FAKE01"], command="remove", fake=True, paths=resolved
        )
    emit_result(
        "fake_default_symlink",
        books_dir_problem=resolved.books_dir_problem,
        resolved_books_outside_fake_data=not resolved.books_dir.resolve().is_relative_to(
            resolved.data_dir.resolve()
        ),
        fake_remove_exit=result,
        synthetic_real_tree_book_exists=target.exists(),
        terminal_event=json.loads(stdout.getvalue()),
    )


def repro_unsafe_real_default(root):
    p = paths(root)
    p.default_books_dir.parent.mkdir(parents=True)
    p.data_dir.mkdir(parents=True)
    p.default_books_dir.symlink_to(p.data_dir, target_is_directory=True)
    (p.venv_dir / "sentinel").mkdir(parents=True)
    resolved = paths(root)
    library.remove_book(resolved.books_dir, "venv")
    emit_result(
        "unsafe_real_default",
        books_dir_problem=resolved.books_dir_problem,
        retained_rejected_default=resolved.books_dir == p.default_books_dir,
        synthetic_venv_exists_after_remove=p.venv_dir.exists(),
    )


def repro_readiness(root):
    p = paths(root)
    p.data_dir.mkdir(parents=True)
    result = subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(p.venv_dir)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    # Simulates a venv whose old minor-version site-packages no longer match
    # the interpreter after an OS Python upgrade. No real dependency installed.
    oldsite = p.venv_dir / "lib" / "python3.10" / "site-packages" / "audible"
    oldsite.mkdir(parents=True)
    (oldsite / "__init__.py").write_text("# synthetic old-interpreter dependency\n")
    digest = bootstrap.requirements_digest(bootstrap.requirements_path())
    bootstrap._write_marker(p.venv_dir, digest)
    probe = subprocess.run(
        [str(p.venv_python), "-I", "-c", "import audible"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    events, runs = [], []
    bootstrap.run_setup(
        p,
        run=lambda *a, **k: runs.append(a),
        emit=lambda event, **fields: events.append({"type": event, **fields}),
    )
    out = io.StringIO()
    with (
        patch.object(commands, "_missing_required_tools", list),
        patch.object(commands, "find_mpris_script", lambda: None),
        contextlib.redirect_stdout(out),
    ):
        commands.cmd_status([], command="status", fake=False, paths=p)
    status = json.loads(out.getvalue().splitlines()[0])
    emit_result(
        "broken_venv_still_ready",
        dependency_import_exit=probe.returncode,
        dependency_import_error=probe.stderr.strip().splitlines()[-1],
        is_ready=bootstrap.is_ready(p.venv_dir, digest),
        status_venv_ready=status["venv_ready"],
        setup_events=events,
        setup_subprocess_calls=len(runs),
    )
    bootstrap._write_marker(p.venv_dir, "0" * 64)
    out = io.StringIO()
    with (
        patch.object(commands, "_missing_required_tools", list),
        patch.object(commands, "find_mpris_script", lambda: None),
        contextlib.redirect_stdout(out),
    ):
        commands.cmd_status([], command="status", fake=False, paths=p)
    emit_result(
        "old_pins_status",
        matches_current_pins=bootstrap.is_ready(p.venv_dir, digest),
        status_venv_ready=json.loads(out.getvalue().splitlines()[0])["venv_ready"],
    )


def repro_import_provenance(root):
    p = paths(root)
    p.config_dir.mkdir(parents=True)
    p.auth_file.write_text(json.dumps({"device": "plugin-created-synthetic-device"}))
    p.account_file.write_text(json.dumps({"origin": "login"}))
    source = root / "invented-cli-source"
    source.mkdir()
    (source / "auth.json").write_text(
        json.dumps({"device": "imported-synthetic-device"})
    )
    (source / "config.toml").write_text(
        '[APP]\nprimary_profile = "test"\n[profile.test]\nauth_file = "auth.json"\ncountry_code = "us"\n'
    )
    deregistrations = []

    class FakeAPI:
        def authenticator_from_file(self, path):
            device = json.loads(path.read_text())["device"]
            return SimpleNamespace(
                activation_bytes=None,
                customer_info={},
                deregister_device=lambda **kw: deregistrations.append(
                    {"device": device, **kw}
                ),
            )

    with patch.object(
        auth,
        "_write_private_json",
        side_effect=OSError(errno.ENOSPC, "injected metadata write failure"),
    ):
        try:
            auth.login_import_cli(p, source_dir=source, fake=False, api=FakeAPI())
        except OSError:
            pass
    origin = auth.read_account_record(p).get("origin")
    imported = json.loads(p.auth_file.read_text())["device"]
    auth.logout(p, fake=False, api=FakeAPI())
    emit_result(
        "failed_import_provenance",
        auth_device_after_failed_import=imported,
        origin_after_failed_import=origin,
        logout_calls=deregistrations,
    )


def repro_cover_path(root):
    p = paths(root, fake=True)
    asin = "../../outside/sentinel"
    outside = p.data_dir.parent / "outside" / "sentinel.jpg"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"original synthetic picture")
    counts = catalog.run_sync(
        p,
        fake=True,
        full=True,
        library=catalog.FakeLibrary(
            [
                {
                    "asin": asin,
                    "title": "Invented",
                    "product_images": {"252": "https://example.invalid/cover.jpg"},
                }
            ]
        ),
        cover_fetch=lambda url: b"synthetic replacement",
        emit=lambda *a, **k: None,
    )
    emit_result(
        "cover_path_traversal",
        covers_written=counts["covers"],
        write_outside_plugin_data=not outside.resolve().is_relative_to(
            p.data_dir.resolve()
        ),
        outside_file_overwritten=outside.read_bytes() == b"synthetic replacement",
    )


def repro_multiline_denial():
    watch = LicenseDenialWatch()
    watch.install()
    try:
        logging.getLogger(MODELS_LOGGER).debug(
            "License denied message for %s: %s.Reason: %s.Type: %s",
            "B00FAKE01",
            "License denied.\nPlease wait.",
            "CustomerThrottled",
            "validation",
        )
    finally:
        watch.uninstall()
    emit_result(
        "multiline_throttle_reason",
        denied=watch.denied,
        throttled=watch.throttled,
        reasons=watch.reasons,
    )


def main():
    with tempfile.TemporaryDirectory(prefix="oa-backend-probes-", dir=SCRATCH) as temp:
        root = Path(temp)
        for name, func in [
            ("backup", repro_backup_failure),
            ("fake-symlink", repro_fake_default_symlink),
            ("real-default", repro_unsafe_real_default),
            ("venv", repro_readiness),
            ("auth", repro_import_provenance),
            ("cover", repro_cover_path),
        ]:
            (root / name).mkdir()
            func(root / name)
        repro_multiline_denial()


if __name__ == "__main__":
    main()

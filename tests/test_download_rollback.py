"""B01: injected commit failures must not destroy synthetic existing books.

All paths and process environments are isolated. The fake fetch writes invented
bytes; no account, network, real library, or external media tools are needed.
"""

from __future__ import annotations

import errno
import json
import os
import signal
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from omarchy_audible import commands, fsutil
from omarchy_audible import download as dl
from omarchy_audible.errors import PipelineError
from omarchy_audible.library import local_audio_file, play_info_payload
from omarchy_audible.paths import Paths

ASIN = "B00FAKE01"
LAYOUT_FILES = {
    "legacy": ("book.m4b", "chapters.txt", "meta.json"),
    "locked": ("book.aaxc", "key.json", "chapters.txt", "meta.json"),
    "aax": ("book.aax", "key.json", "chapters.txt", "meta.json"),
}
BACKUP_CASES = [
    (layout, name) for layout, names in LAYOUT_FILES.items() for name in names
]
INSTALL_CASES = [
    (layout, container, name)
    for layout in LAYOUT_FILES
    for container in ("aaxc", "aax")
    for name in ("key.json", "chapters.txt", f"book.{container}", "meta.json")
]
ROLLBACK_CASES = [
    (layout, "backup", name, restored)
    for layout, names in LAYOUT_FILES.items()
    for index, name in enumerate(names)
    for restored in names[:index]
] + [
    (layout, "install", name, restored)
    for layout, container, name in INSTALL_CASES
    if container == "aaxc"
    for restored in LAYOUT_FILES[layout]
]


def _snapshot(directory: Path) -> dict[str, tuple[bytes, int, int]]:
    return {
        str(path.relative_to(directory)): (
            path.read_bytes(),
            path.stat().st_mtime_ns,
            stat.S_IMODE(path.stat().st_mode),
        )
        for path in directory.rglob("*")
        if path.is_file()
    }


def _seed(paths: Paths, layout: str) -> Path:
    directory = paths.books_dir / ASIN
    directory.mkdir(parents=True)
    for name in LAYOUT_FILES[layout]:
        (directory / name).write_bytes(f"old synthetic {name}".encode())
        (directory / name).chmod(0o640)
    if layout != "legacy":
        payload = {"format": "aax"}
        if layout == "locked":
            payload = dl._key_payload(
                dl.RawDownload(
                    directory / "book.aaxc",
                    "aaxc",
                    [],
                    dl.FAKE_VOUCHER_KEY,
                    dl.FAKE_VOUCHER_IV,
                )
            )
        fsutil.write_private_json(directory / "key.json", payload)
    if layout == "aax":
        fsutil.write_private_text(paths.activation_bytes_file, "00112233")
    return directory


@pytest.fixture
def isolated_env(env, tmp_path, monkeypatch):
    temporary = tmp_path / "tmp"
    temporary.mkdir()
    env.update({"TMPDIR": str(temporary), "XDG_CACHE_HOME": str(tmp_path / "cache")})
    for name in (
        "HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_RUNTIME_DIR",
        "XDG_CACHE_HOME",
        "TMPDIR",
    ):
        monkeypatch.setenv(name, env[name])
    monkeypatch.setenv("OMARCHY_AUDIBLE_FAKE", "1")
    return env


@pytest.fixture
def fast_get(isolated_env, fake_paths, monkeypatch):
    def fetch(asin, partial, emit, children, fake_fail, chapter_count):
        container = "aax" if fake_fail == "novoucher" else "aaxc"
        raw = partial / f"synthetic.{container}"
        raw.write_bytes(b"new synthetic audio")
        return dl.RawDownload(
            raw,
            container,
            dl.parse_chapters(dl.fake_chapters_spec(chapter_count)),
            dl.FAKE_VOUCHER_KEY,
            dl.FAKE_VOUCHER_IV,
        )

    monkeypatch.setattr(dl, "_fake_fetch", fetch)
    monkeypatch.setattr(dl, "_verify_duration", lambda *args: None)
    return fake_paths


def _fail_at(directory, phase, name, real_replace):
    partial = directory / dl.PARTIAL_DIRNAME
    aside = partial / dl._OLD_DIRNAME
    hits = []

    def replace(src, dst):
        source, target = Path(src), Path(dst)
        backup = phase == "backup" and target == aside / name
        install = (
            phase == "install" and target == directory / name and source.parent != aside
        )
        if backup or install:
            hits.append(name)
            raise OSError(errno.EIO, "synthetic commit failure")
        return real_replace(src, dst)

    return replace, hits


@pytest.mark.parametrize(("layout", "name"), BACKUP_CASES)
def test_each_backup_failure_restores_old_files(layout, name, fast_get, monkeypatch):
    directory = _seed(fast_get, layout)
    before = _snapshot(directory)
    replace, hits = _fail_at(directory, "backup", name, os.replace)
    monkeypatch.setattr(dl.os, "replace", replace)

    with pytest.raises(OSError):
        dl.run_get(ASIN, fast_get, fake=True, emit=lambda *args, **kwargs: None)

    assert hits == [name]
    assert _snapshot(directory) == before
    assert local_audio_file(directory) == directory / LAYOUT_FILES[layout][0]
    assert play_info_payload(fast_get, ASIN)["path"] == str(local_audio_file(directory))
    assert not (directory / dl.PARTIAL_DIRNAME).exists()


@pytest.mark.parametrize(("layout", "container", "name"), INSTALL_CASES)
def test_each_install_failure_restores_old_files(
    layout, container, name, fast_get, monkeypatch
):
    directory = _seed(fast_get, layout)
    before = _snapshot(directory)
    replace, hits = _fail_at(directory, "install", name, os.replace)
    monkeypatch.setattr(dl.os, "replace", replace)

    with pytest.raises(OSError):
        dl.run_get(
            ASIN,
            fast_get,
            fake=True,
            fake_fail="novoucher" if container == "aax" else None,
            emit=lambda *args, **kwargs: None,
        )

    assert hits == [name]
    assert _snapshot(directory) == before
    assert play_info_payload(fast_get, ASIN)["path"] == str(local_audio_file(directory))
    assert not (directory / dl.PARTIAL_DIRNAME).exists()


@pytest.mark.parametrize(("layout", "phase", "name", "restored"), ROLLBACK_CASES)
def test_failed_rollback_preserves_recovery_and_retry_refuses(
    layout, phase, name, restored, fast_get, monkeypatch, capsys, validate_event
):
    directory = _seed(fast_get, layout)
    before = _snapshot(directory)
    partial = directory / dl.PARTIAL_DIRNAME
    aside = partial / dl._OLD_DIRNAME
    real_replace = os.replace
    replace, hits = _fail_at(directory, phase, name, real_replace)
    rollback_hits = []

    def fail_rollback(src, dst):
        if Path(src) == aside / restored:
            rollback_hits.append(restored)
            raise OSError(errno.EIO, "synthetic rollback failure")
        return replace(src, dst)

    monkeypatch.setattr(dl.os, "replace", fail_rollback)
    with pytest.raises((OSError, PipelineError)) as error:
        dl.run_get(ASIN, fast_get, fake=True, emit=lambda *args, **kwargs: None)

    assert hits == [name]
    assert rollback_hits == [restored]
    assert aside.is_dir()
    assert stat.S_IMODE(partial.stat().st_mode) == 0o700
    assert stat.S_IMODE(aside.stat().st_mode) == 0o700
    for old_name, snapshot in before.items():
        copies = [
            path
            for path in (directory / old_name, aside / old_name)
            if path.is_file() and path.read_bytes() == snapshot[0]
        ]
        assert len(copies) == 1
        assert _snapshot(copies[0].parent)[old_name] == snapshot
    assert isinstance(error.value, PipelineError)
    assert "recovery" in error.value.message
    if local_audio_file(directory) is not None and layout != "legacy":
        assert _snapshot(directory)["key.json"] == before["key.json"]
    preserved = _snapshot(directory)
    monkeypatch.setattr(dl.os, "replace", real_replace)

    def no_fetch(*args, **kwargs):
        pytest.fail("retry must refuse before starting another download")

    monkeypatch.setattr(dl, "_fake_fetch", no_fetch)
    assert commands.cmd_get([ASIN], command="get", fake=True, paths=fast_get) != 0
    event = json.loads(capsys.readouterr().out.splitlines()[-1])
    validate_event(event)
    assert event["type"] == "error"
    assert "recovery" in event["message"]
    diagnostics = json.dumps(event)
    assert ASIN not in diagnostics
    assert dl.FAKE_VOUCHER_KEY not in diagnostics
    assert dl.FAKE_VOUCHER_IV not in diagnostics
    assert _snapshot(directory) == preserved
    assert dl._reclaimable_bytes(partial) == 0
    with pytest.raises(PipelineError):
        dl._make_partial(partial)
    assert _snapshot(directory) == preserved


@pytest.mark.parametrize("marker", ["directory", "file", "broken_symlink"])
def test_staging_with_recovery_marker_is_never_wiped(marker, fast_get):
    partial = fast_get.books_dir / ASIN / dl.PARTIAL_DIRNAME
    partial.mkdir(parents=True, mode=0o700)
    aside = partial / dl._OLD_DIRNAME
    if marker == "directory":
        aside.mkdir(mode=0o700)
    elif marker == "file":
        aside.write_bytes(b"synthetic recovery marker")
    else:
        aside.symlink_to(partial / "missing")
    sentinel = partial / "book.m4b"
    sentinel.write_bytes(b"sole synthetic recovery copy")

    with pytest.raises(PipelineError) as error:
        dl._make_partial(partial)

    assert "recovery" in error.value.message
    assert sentinel.read_bytes() == b"sole synthetic recovery copy"
    assert aside.exists() or aside.is_symlink()


@pytest.mark.parametrize("name", ["key.json", "chapters.txt", "book.aaxc"])
def test_failed_rollback_unlink_keeps_backups(name, fast_get, monkeypatch):
    directory = _seed(fast_get, "legacy")
    before = _snapshot(directory)
    partial = directory / dl.PARTIAL_DIRNAME
    aside = partial / dl._OLD_DIRNAME
    replace, hits = _fail_at(directory, "install", "meta.json", os.replace)
    real_unlink = dl._unlink

    def unlink(path):
        if path == directory / name:
            raise OSError(errno.EIO, "synthetic cleanup failure")
        real_unlink(path)

    monkeypatch.setattr(dl.os, "replace", replace)
    monkeypatch.setattr(dl, "_unlink", unlink)
    with pytest.raises((OSError, PipelineError)) as error:
        dl.run_get(ASIN, fast_get, fake=True, emit=lambda *args, **kwargs: None)

    assert hits == ["meta.json"]
    assert _snapshot(aside) == before
    assert isinstance(error.value, PipelineError)
    assert "recovery" in error.value.message
    preserved = _snapshot(directory)
    with pytest.raises(PipelineError):
        dl.run_get(ASIN, fast_get, fake=True, emit=lambda *args, **kwargs: None)
    assert _snapshot(directory) == preserved


def test_sigterm_does_not_hide_a_failed_rollback(fast_get, monkeypatch, capsys):
    directory = _seed(fast_get, "locked")
    before = _snapshot(directory)
    aside = directory / dl.PARTIAL_DIRNAME / dl._OLD_DIRNAME
    real_replace = os.replace

    def replace(src, dst):
        if Path(dst) == aside / "key.json":
            os.kill(os.getpid(), signal.SIGTERM)
            raise OSError(errno.EIO, "synthetic backup failure")
        if Path(src) == aside / "book.aaxc":
            raise OSError(errno.EIO, "synthetic restore failure")
        real_replace(src, dst)

    monkeypatch.setattr(dl.os, "replace", replace)
    code = commands.cmd_get([ASIN], command="get", fake=True, paths=fast_get)

    assert code != 0
    event = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert event["code"] == "internal"
    assert "recovery" in event["message"]
    assert _snapshot(aside)["book.aaxc"] == before["book.aaxc"]


def test_recovery_refuses_before_content_metadata(fast_get, monkeypatch):
    directory = _seed(fast_get, "locked")
    partial = directory / dl.PARTIAL_DIRNAME
    partial.mkdir(mode=0o700)
    (partial / dl._OLD_DIRNAME).mkdir(mode=0o700)
    before = _snapshot(directory)

    def no_metadata(*args):
        pytest.fail("an unresolved backup must stop before any metadata request")

    monkeypatch.setattr(dl, "_real_content_metadata", no_metadata)
    with pytest.raises(PipelineError) as error:
        dl.run_get(ASIN, fast_get, fake=False, emit=lambda *args, **kwargs: None)
    assert "recovery" in error.value.message
    assert _snapshot(directory) == before


KILL_CHILD = """
import os
import signal
from pathlib import Path
from omarchy_audible import download as dl
from omarchy_audible.paths import Paths

paths = Paths.from_env(os.environ, fake=True)
directory = paths.books_dir / "B00FAKE01"
partial = directory / dl.PARTIAL_DIRNAME
aside = partial / dl._OLD_DIRNAME
phase = os.environ["KILL_PHASE"]
name = os.environ["KILL_NAME"]
real_replace = os.replace

def fetch(asin, partial, *args):
    raw = partial / "synthetic.aaxc"
    raw.write_bytes(b"new synthetic audio")
    return dl.RawDownload(raw, "aaxc", dl.parse_chapters(dl.fake_chapters_spec(5)),
                          dl.FAKE_VOUCHER_KEY, dl.FAKE_VOUCHER_IV)

def replace(src, dst):
    real_replace(src, dst)
    target = Path(dst)
    if ((phase == "backup" and target == aside / name)
            or (phase == "install" and target == directory / name)):
        os.kill(os.getpid(), signal.SIGKILL)

dl._fake_fetch = fetch
dl._verify_duration = lambda *args: None
os.replace = replace
dl.run_get("B00FAKE01", paths, fake=True, emit=lambda *args, **kwargs: None)
"""
KILL_CASES = [(layout, "backup", name) for layout, name in BACKUP_CASES] + [
    (layout, "install", name)
    for layout, container, name in INSTALL_CASES
    if container == "aaxc"
]


@pytest.mark.parametrize(("layout", "phase", "name"), KILL_CASES)
def test_terminated_commit_retry_refuses_without_losing_old_files(
    layout, phase, name, fast_get, isolated_env, run_cli, monkeypatch
):
    directory = _seed(fast_get, layout)
    before = _snapshot(directory)
    env = {
        **isolated_env,
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "backend"),
        "KILL_PHASE": phase,
        "KILL_NAME": name,
    }
    result = subprocess.run(
        [sys.executable, "-c", KILL_CHILD],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == -signal.SIGKILL, result.stderr
    preserved = _snapshot(directory)

    result = run_cli("get", ASIN, fake=True)

    assert result.returncode != 0
    event = json.loads(result.stdout.splitlines()[-1])
    assert event["type"] == "error"
    assert "recovery" in event["message"]
    assert _snapshot(directory) == preserved
    aside = directory / dl.PARTIAL_DIRNAME / dl._OLD_DIRNAME
    for old_name, snapshot in before.items():
        assert any(
            path.is_file() and _snapshot(path.parent)[old_name] == snapshot
            for path in (directory / old_name, aside / old_name)
        )

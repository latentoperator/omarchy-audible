"""B14 — a re-download keeps the working copy until the new one is ready.

F7: a failed or cancelled ``get`` of an already-local book must leave the old
book byte-identical (same files, sizes, mtimes and modes) and still listed by
``local`` — the previous copy is only replaced once the new download has been
built and verified in ``.partial/``. F10/F34: the free-space pre-flight counts
an abandoned ``.partial/`` (removed before the fetch), never the old copy, which
stays on disk until the commit. F35: the commit itself is cancel-safe.

Fake mode only: no account, no network.
"""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from omarchy_audible import commands, fsutil
from omarchy_audible import download as dl
from omarchy_audible.errors import Cancelled, PipelineError
from omarchy_audible.library import local_audio_file

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "bin" / "omarchy-audible"
ASIN = "B00FAKE01"

# Obviously fake material, invented for the fixtures.
LEGACY_BYTES = b"old decrypted audio"
LOCKED_BYTES = b"old locked aaxc bytes"
FAKE_KEY = {
    "format": "aaxc",
    "key": "00112233445566778899aabbccddeeff",
    "iv": "aabbccdd00112233",
}
FAKE_CHAPTERS = "[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=1000\ntitle=Old chapter\n"

# (``--fake-fail`` mode, expected error code). ``novoucher`` is absent: in fake
# mode it is the successful aax path (covered below), not a failure.
FAILURES = (("disk", "disk_space"), ("network", "network"), ("decrypt", "decrypt"))


def _seed(layout: str, books_dir: Path, asin: str = ASIN) -> Path:
    """An already-local book: an old unlocked ``book.m4b``, or a locked one."""
    directory = books_dir / asin
    directory.mkdir(parents=True, exist_ok=True)
    if layout == "legacy":
        (directory / "book.m4b").write_bytes(LEGACY_BYTES)
        (directory / "chapters.txt").write_text(FAKE_CHAPTERS, encoding="utf-8")
        (directory / "meta.json").write_text(
            json.dumps({"asin": asin, "format": "m4b"}), encoding="utf-8"
        )
        return directory
    assert layout == "locked"
    (directory / "book.aaxc").write_bytes(LOCKED_BYTES)
    fsutil.write_private_json(directory / "key.json", FAKE_KEY)
    (directory / "chapters.txt").write_text(FAKE_CHAPTERS, encoding="utf-8")
    (directory / "meta.json").write_text(
        json.dumps({"asin": asin, "format": "aaxc", "locked": True}),
        encoding="utf-8",
    )
    return directory


def _snapshot(directory: Path) -> dict[str, tuple[int, int, int, bytes]]:
    """Every file under ``directory``: its size, mtime, mode and content."""
    return {
        str(path.relative_to(directory)): (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            stat.S_IMODE(path.stat().st_mode),
            path.read_bytes(),
        )
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _names(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.iterdir())


def _local_asins(run_cli) -> list[str]:
    result = run_cli("local", fake=True)
    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    books = next(event["books"] for event in events if event["type"] == "local")
    return sorted(book["asin"] for book in books)


@pytest.mark.parametrize("layout", ["legacy", "locked"])
@pytest.mark.parametrize(("mode", "code"), FAILURES)
def test_failed_redownload_keeps_the_old_book(
    layout, mode, code, run_cli, events, ffmpeg_bin, fake_paths
):
    directory = _seed(layout, fake_paths.books_dir)
    before = _snapshot(directory)

    result = run_cli("get", ASIN, "--fake-fail", mode, fake=True)

    assert result.returncode != 0
    last = events(result)[-1]
    assert last["type"] == "error", last
    assert last["code"] == code, last
    assert _snapshot(directory) == before
    assert not (directory / ".partial").exists()
    assert not list(directory.glob("*.tmp"))
    assert _local_asins(run_cli) == [ASIN]


@pytest.mark.parametrize("layout", ["legacy", "locked"])
def test_cancelled_redownload_keeps_the_old_book(layout, env, ffmpeg_bin, fake_paths):
    directory = _seed(layout, fake_paths.books_dir)
    before = _snapshot(directory)

    proc = subprocess.Popen(
        [sys.executable, str(LAUNCHER), "get", ASIN, "--fake"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        partial = directory / ".partial"
        deadline = time.time() + 20
        while time.time() < deadline and not partial.exists():
            time.sleep(0.02)
        assert partial.exists(), "the download never started"
        time.sleep(0.05)  # into the middle of the download

        cancelled = subprocess.run(
            [sys.executable, str(LAUNCHER), "cancel", ASIN, "--fake"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert cancelled.returncode == 0, cancelled.stderr
        out, _err = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    assert proc.returncode != 0
    last = json.loads([line for line in out.splitlines() if line.strip()][-1])
    assert last["type"] == "error"
    assert last["code"] == "cancelled"
    assert _snapshot(directory) == before
    assert not (directory / ".partial").exists()
    assert not list(directory.glob("*.tmp"))


def test_successful_redownload_over_a_legacy_book_leaves_only_the_locked_layout(
    run_cli, events, ffmpeg_bin, fake_paths
):
    directory = _seed("legacy", fake_paths.books_dir)

    result = run_cli("get", ASIN, fake=True)

    assert result.returncode == 0, result.stderr
    assert events(result)[-1]["type"] == "done"
    assert _names(directory) == ["book.aaxc", "chapters.txt", "key.json", "meta.json"]
    assert json.loads((directory / "key.json").read_text(encoding="utf-8")) == FAKE_KEY
    assert stat.S_IMODE((directory / "key.json").stat().st_mode) == 0o600
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    assert meta["format"] == "aaxc" and meta["locked"] is True
    assert "Chapter 1" in (directory / "chapters.txt").read_text(encoding="utf-8")
    assert "Old chapter" not in (directory / "chapters.txt").read_text(encoding="utf-8")
    assert _local_asins(run_cli) == [ASIN]


def test_successful_redownload_over_a_locked_book_installs_the_new_key_and_audio(
    run_cli, events, ffmpeg_bin, fake_paths
):
    """The no-voucher path replaces a locked book with the new aax reference."""
    directory = _seed("locked", fake_paths.books_dir)

    result = run_cli("get", ASIN, "--fake-fail", "novoucher", fake=True)

    assert result.returncode == 0, result.stderr
    assert events(result)[-1]["type"] == "done"
    assert _names(directory) == ["book.aax", "chapters.txt", "key.json", "meta.json"]
    assert json.loads((directory / "key.json").read_text(encoding="utf-8")) == {
        "format": "aax"
    }
    assert stat.S_IMODE((directory / "key.json").stat().st_mode) == 0o600
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    assert meta["format"] == "aax" and meta["locked"] is True
    assert _local_asins(run_cli) == [ASIN]


def test_real_redownload_that_fails_keeps_the_old_book(paths, monkeypatch):
    """The aaxc attempt offers no voucher and the aax fallback fails (F7/F8)."""
    directory = _seed("locked", paths.books_dir)
    before = _snapshot(directory)

    def fake_download(cli, env, partial, asin, fmt, emit, children, total):
        if fmt == "aax":
            raise PipelineError(dl.protocol.ErrorCode.NETWORK, "simulated aax failure")

    monkeypatch.setattr(dl, "_wrapper_python", lambda: "audible")
    monkeypatch.setattr(dl, "_audible_env", lambda paths: {})
    monkeypatch.setattr(dl, "_audible_download", fake_download)
    monkeypatch.setattr(dl, "_real_content_metadata", lambda asin, paths: {})

    with pytest.raises(PipelineError) as excinfo:
        dl.run_get(ASIN, paths, fake=False, emit=lambda *a, **k: None)

    assert excinfo.value.code == "network"
    assert _snapshot(directory) == before
    assert not (directory / ".partial").exists()
    assert not list(directory.glob("*.tmp"))


def test_a_failed_sanity_check_keeps_the_old_book(monkeypatch, ffmpeg_bin, fake_paths):
    """An exception in the key-free duration check happens before the commit."""
    directory = _seed("locked", fake_paths.books_dir)
    before = _snapshot(directory)

    def boom(path, container, expected_duration_ms):
        raise PipelineError(
            dl.protocol.ErrorCode.CONVERT, "simulated duration mismatch"
        )

    monkeypatch.setattr(dl, "_verify_duration", boom)

    with pytest.raises(PipelineError) as excinfo:
        dl.run_get(ASIN, fake_paths, fake=True, emit=lambda *a, **k: None)

    assert excinfo.value.code == "convert"
    assert _snapshot(directory) == before
    assert not (directory / ".partial").exists()
    assert not list(directory.glob("*.tmp"))


def test_reclaimable_bytes_counts_only_the_abandoned_partial(tmp_path):
    """F34: only an abandoned ``.partial/`` counts; the old copy does not."""
    target = tmp_path / ASIN
    partial = target / ".partial"
    partial.mkdir(parents=True)
    (target / "book.m4b").write_bytes(b"x" * 1000)
    (target / "key.json").write_bytes(b"not audio")
    (partial / "chunk").write_bytes(b"y" * 250)

    assert dl._reclaimable_bytes(partial) == 250


def test_free_space_does_not_count_the_old_copy(monkeypatch, fake_paths):
    """F34: 1.0 MB free plus a 1.5 MB old book cannot cover the 2.0 MB download.

    The old copy stays on disk until the commit, which runs after the fetch, so
    its bytes are not free while the fetch runs: the pre-flight must refuse and
    leave the old book alone.
    """
    directory = fake_paths.books_dir / ASIN
    directory.mkdir(parents=True)
    (directory / "book.m4b").write_bytes(b"x" * 1_500_000)
    before = _snapshot(directory)
    monkeypatch.setattr(dl, "_free_bytes", lambda path: 1_000_000)

    with pytest.raises(PipelineError) as excinfo:
        dl.run_get(ASIN, fake_paths, fake=True, emit=lambda *a, **k: None)

    assert excinfo.value.code == "disk_space"
    assert _snapshot(directory) == before
    assert not (directory / ".partial").exists()


def test_free_space_counts_an_abandoned_partial(monkeypatch, ffmpeg_bin, fake_paths):
    """F34: an abandoned ``.partial/`` is rmtree'd before the fetch, so it counts."""
    directory = fake_paths.books_dir / ASIN
    partial = directory / ".partial"
    partial.mkdir(parents=True)
    (partial / "chunk").write_bytes(b"y" * 1_500_000)
    monkeypatch.setattr(dl, "_free_bytes", lambda path: 1_000_000)

    # 1.0 MB free + 1.5 MB of abandoned staging covers the 2.2 MB the fake needs.
    final = dl.run_get(ASIN, fake_paths, fake=True, emit=lambda *a, **k: None)

    assert final.name == "book.aaxc"
    assert not (directory / ".partial").exists()


def test_free_space_still_refuses_when_nothing_is_freed(monkeypatch, fake_paths):
    monkeypatch.setattr(dl, "_free_bytes", lambda path: 1_000_000)

    with pytest.raises(PipelineError) as excinfo:
        dl.run_get(ASIN, fake_paths, fake=True, emit=lambda *a, **k: None)

    assert excinfo.value.code == "disk_space"


# --- F35: the commit is cancel-safe -----------------------------------------


def test_a_cancel_on_the_audio_move_keeps_a_playable_copy(
    monkeypatch, ffmpeg_bin, fake_paths
):
    """F35: a ``Cancelled`` raised inside the commit leaves the old book whole."""
    directory = _seed("locked", fake_paths.books_dir)
    before = _snapshot(directory)
    real_replace = os.replace

    def replace_or_cancel(src, dst):
        # Only the commit's own audio move: `_restore_local` moves the old audio
        # back out of `.partial/old/` and that must be allowed to run.
        if Path(src) == directory / dl.PARTIAL_DIRNAME / "book.aaxc":
            raise Cancelled()
        real_replace(src, dst)

    monkeypatch.setattr(dl.os, "replace", replace_or_cancel)

    with pytest.raises(Cancelled):
        dl.run_get(ASIN, fake_paths, fake=True, emit=lambda *a, **k: None)

    assert _snapshot(directory) == before
    assert local_audio_file(directory) is not None
    assert not (directory / ".partial").exists()


def test_a_sigterm_in_the_commit_window_is_reported_as_done(
    monkeypatch, ffmpeg_bin, fake_paths, capsys
):
    """F35: SIGTERM is blocked for the commit; the run still ends ``done``.

    The signal is sent for real from inside the commit (a patched
    ``_clear_local``). It stays pending while the book is being put together and
    is delivered at the unblock, after which the new book is already local, so
    the download counts as a success rather than a cancel.
    """
    directory = _seed("locked", fake_paths.books_dir)
    real_clear = dl._clear_local
    sent: list[int] = []

    def clear_and_sigterm(*args):
        sent.append(1)
        os.kill(os.getpid(), signal.SIGTERM)  # lands inside the commit window
        return real_clear(*args)

    monkeypatch.setattr(dl, "_clear_local", clear_and_sigterm)

    code = commands.cmd_get([ASIN], command="get", fake=True, paths=fake_paths)

    assert sent == [1]
    assert code == 0
    events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    assert events, "the run produced no events"
    assert events[-1]["type"] == "done", events[-1]
    assert Path(events[-1]["path"]).is_file()
    assert not (directory / ".partial").exists()
    assert local_audio_file(directory) == directory / "book.aaxc"
    assert json.loads((directory / "key.json").read_text(encoding="utf-8")) == FAKE_KEY


def test_a_second_sigterm_cannot_abort_the_cleanup(monkeypatch, ffmpeg_bin, fake_paths):
    """F6: the cancel handler ignores every SIGTERM after the first one."""
    directory = _seed("locked", fake_paths.books_dir)
    before = _snapshot(directory)
    real_rmtree = dl._rmtree
    calls: list[str] = []

    def rmtree_and_second_sigterm(path):
        calls.append(str(path))
        if len([call for call in calls if call.endswith(".partial")]) == 2:
            os.kill(os.getpid(), signal.SIGTERM)  # during the first one's cleanup
        real_rmtree(path)

    monkeypatch.setattr(dl, "_rmtree", rmtree_and_second_sigterm)

    def first_sigterm_mid_download():
        partial = directory / ".partial"
        deadline = time.time() + 20
        while time.time() < deadline and not partial.exists():
            time.sleep(0.01)
        time.sleep(0.05)  # into the middle of the fake download
        os.kill(os.getpid(), signal.SIGTERM)

    thread = threading.Thread(target=first_sigterm_mid_download, daemon=True)
    with pytest.raises(Cancelled), commands._sigterm_cancels():
        thread.start()
        dl.run_get(ASIN, fake_paths, fake=True, emit=lambda *a, **k: None)

    # The cleanup finished: `.partial/` is gone and the old copy is untouched.
    assert not (directory / ".partial").exists()
    assert _snapshot(directory) == before

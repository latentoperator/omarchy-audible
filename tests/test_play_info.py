"""B11 — ``play-info``: how the player loads one local book (ARCHITECTURE 4.2, D7).

``play-info <asin>`` emits one ``play_info`` event with the audio path, the
ffmetadata chapter file (or null) and the ready-made mpv ``demuxer-lavf-o``
value. It is a non-job command: it never takes ``job.lock``. The aax case stores
a reference to the account's activation bytes, not a copy (D7).
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

from omarchy_audible import fakestate

ASIN = "B00FAKE01"


def _play_info(result, events) -> dict:
    parsed = events(result)
    assert parsed[-1]["type"] == "done", result.stderr
    return next(event for event in parsed if event["type"] == "play_info")


def _hold_lock(paths):
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(paths.job_lock, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def test_play_info_aaxc_returns_the_key_and_chapter_file(
    run_cli, validate_stream, events, ffmpeg_bin, fake_paths
):
    assert run_cli("get", ASIN, fake=True).returncode == 0

    result = run_cli("play-info", ASIN, fake=True)
    assert result.returncode == 0, result.stderr
    validate_stream(result, expect_last="done")

    payload = _play_info(result, events)
    book_dir = fake_paths.books_dir / ASIN
    assert payload["path"] == str(book_dir / "book.aaxc")
    assert payload["chapters_file"] == str(book_dir / "chapters.txt")
    key = json.loads((book_dir / "key.json").read_text(encoding="utf-8"))
    assert payload["lavf_options"] == (
        f"audible_key={key['key']},audible_iv={key['iv']}"
    )
    assert Path(payload["path"]).is_file()


def test_play_info_aax_returns_activation_bytes_from_the_config_dir(
    run_cli, events, ffmpeg_bin, fake_paths
):
    assert run_cli("get", ASIN, "--fake-fail", "novoucher", fake=True).returncode == 0

    result = run_cli("play-info", ASIN, fake=True)
    assert result.returncode == 0, result.stderr
    payload = _play_info(result, events)

    assert payload["path"] == str(fake_paths.books_dir / ASIN / "book.aax")
    assert payload["chapters_file"] == str(fake_paths.books_dir / ASIN / "chapters.txt")
    assert payload["lavf_options"] == f"activation_bytes={fakestate.FAKE_ACTIVATION_BYTES}"
    # The key file is a reference, not a copy: no activation bytes in it.
    assert json.loads(
        (fake_paths.books_dir / ASIN / "key.json").read_text(encoding="utf-8")
    ) == {"format": "aax"}
    assert (
        fake_paths.activation_bytes_file.read_text(encoding="utf-8").strip()
        == fakestate.FAKE_ACTIVATION_BYTES
    )


def test_play_info_aax_without_activation_bytes_is_a_decrypt_error(
    run_cli, events, ffmpeg_bin, fake_paths
):
    assert run_cli("get", ASIN, "--fake-fail", "novoucher", fake=True).returncode == 0
    fake_paths.activation_bytes_file.unlink()

    result = run_cli("play-info", ASIN, fake=True)
    assert result.returncode != 0
    last = events(result)[-1]
    assert last["type"] == "error"
    assert last["code"] == "decrypt"


def test_play_info_old_m4b_has_no_key_and_no_chapter_file(
    run_cli, events, fake_paths
):
    book_dir = fake_paths.books_dir / ASIN
    book_dir.mkdir(parents=True)
    (book_dir / "book.m4b").write_bytes(b"old audio")
    (book_dir / "meta.json").write_text("{}", encoding="utf-8")

    result = run_cli("play-info", ASIN, fake=True)
    assert result.returncode == 0, result.stderr
    payload = _play_info(result, events)
    assert payload["path"] == str(book_dir / "book.m4b")
    assert payload["chapters_file"] is None
    assert payload["lavf_options"] == ""


def test_play_info_requires_the_book_to_be_local(run_cli, events, fake_paths):
    result = run_cli("play-info", "B00NOPE01", fake=True)
    assert result.returncode != 0
    assert events(result)[-1]["code"] == "not_local"


def test_play_info_locked_file_without_a_key_is_not_local(
    run_cli, events, fake_paths
):
    book_dir = fake_paths.books_dir / "B00NOKEY1"
    book_dir.mkdir(parents=True)
    (book_dir / "book.aaxc").write_bytes(b"locked")
    (book_dir / "chapters.txt").write_text(";FFMETADATA1\n", encoding="utf-8")

    result = run_cli("play-info", "B00NOKEY1", fake=True)
    assert result.returncode != 0
    assert events(result)[-1]["code"] == "not_local"


def test_play_info_rejects_a_bad_asin(run_cli, events):
    result = run_cli("play-info", "../outside", fake=True)
    assert result.returncode != 0
    assert events(result)[-1]["code"] == "bad_asin"


def test_play_info_requires_an_asin(run_cli, events):
    result = run_cli("play-info", fake=True)
    assert result.returncode != 0
    assert events(result)[-1]["code"] == "invalid_args"


def test_play_info_takes_no_job_lock(run_cli, events, ffmpeg_bin, fake_paths):
    """Like ``local``, it works while a download holds ``job.lock``."""
    assert run_cli("get", ASIN, fake=True).returncode == 0

    fd = _hold_lock(fake_paths)
    try:
        result = run_cli("play-info", ASIN, fake=True)
    finally:
        os.close(fd)

    assert result.returncode == 0, result.stderr
    assert _play_info(result, events)["path"].endswith("book.aaxc")


def test_play_info_after_a_long_chapter_fake_book(
    run_cli, events, ffmpeg_bin, fake_paths
):
    """``--fake-chapters 120`` → ``play-info`` → a 120-chapter chapter file."""
    assert run_cli("get", ASIN, "--fake-chapters", "120", fake=True).returncode == 0

    result = run_cli("play-info", ASIN, fake=True)
    assert result.returncode == 0, result.stderr
    payload = _play_info(result, events)

    chapter_file = Path(payload["chapters_file"])
    assert chapter_file.is_file()
    text = chapter_file.read_text(encoding="utf-8")
    assert text.count("[CHAPTER]") == 120
    assert "Chapter 120" in text


def test_play_info_never_writes_into_the_real_tree(
    env, run_cli, ffmpeg_bin, fake_paths
):
    """The whole flow stays in the fake tree (B8)."""
    from omarchy_audible.paths import Paths

    real = Paths.from_env(env)
    before = sorted(p.name for p in real.books_dir.iterdir()) if real.books_dir.exists() else []
    assert run_cli("get", ASIN, fake=True).returncode == 0
    assert run_cli("play-info", ASIN, fake=True).returncode == 0
    after = sorted(p.name for p in real.books_dir.iterdir()) if real.books_dir.exists() else []
    assert after == before

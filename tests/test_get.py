"""B5 — the ``get`` pipeline in fake mode (ARCHITECTURE 4.3).

Covers the atomic rename, cleanup of ``.partial/`` and the raw file on success
and on every failure mode, the free-space pre-flight, the aax fallback when no
voucher is offered, and that the output chapter list equals the flat list in the
fake ``chapters.json`` (which differs from the raw file's embedded chapters).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from omarchy_audible import download as dl
from omarchy_audible.chapters import parse_chapters
from omarchy_audible.errors import PipelineError

ASIN = "B00FAKE01"

# The fake chapters.json flat list, by title, in order. Invented titles only.
EXPECTED_TITLES = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon"]


def _chapter_titles(path: Path, name: str = "ffprobe") -> list[str]:
    result = subprocess.run(
        [name, "-v", "error", "-show_chapters", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    data = json.loads(result.stdout or "{}")
    return [
        str((chapter.get("tags") or {}).get("title", ""))
        for chapter in data.get("chapters", [])
    ]


def _meta(paths, asin: str = ASIN) -> dict:
    return json.loads((paths.books_dir / asin / "meta.json").read_text(encoding="utf-8"))


def test_fake_chapters_json_differs_from_the_raw_file():
    chapters = parse_chapters(dl.FAKE_CHAPTERS_SPEC)
    assert [c.title for c in chapters] == EXPECTED_TITLES
    assert len(chapters) == 5
    assert dl.FAKE_RAW_CHAPTERS == 3


def test_get_success_builds_the_book_and_cleans_up(
    run_cli, validate_stream, ffmpeg_bin, paths
):
    result = run_cli("get", ASIN, fake=True)
    assert result.returncode == 0, result.stderr
    parsed = validate_stream(result, expect_last="done")

    book_dir = paths.books_dir / ASIN
    book = book_dir / "book.m4b"
    assert Path(parsed[-1]["path"]) == book
    assert book.is_file()

    # Success leaves only the book and its meta: no .partial/, no raw file, no
    # half-written .tmp.
    assert sorted(p.name for p in book_dir.iterdir()) == ["book.m4b", "meta.json"]

    stages = {event["stage"] for event in parsed if event["type"] == "progress"}
    assert {"download", "convert"} <= stages

    assert _chapter_titles(book) == EXPECTED_TITLES
    meta = _meta(paths)
    assert meta["acr"] == dl.FAKE_ACR
    assert meta["chapter_count"] == len(EXPECTED_TITLES)
    assert meta["container"] == "aaxc"
    assert meta["duration_ms"] == dl.FAKE_AUDIO_MS


def test_get_writes_a_tmp_file_then_atomically_renames(
    ffmpeg_bin, paths, monkeypatch
):
    """The final ``book.m4b`` only ever appears through the rename of the tmp."""
    from omarchy_audible import download

    renames: list[tuple[str, str]] = []

    def spy(src, dst):
        renames.append((Path(src).name, Path(dst).name))
        os.replace(src, dst)

    monkeypatch.setattr(download.fsutil, "atomic_replace", spy)
    final = download.run_get(ASIN, paths, fake=True, emit=lambda *a, **k: None)

    assert renames == [("book.m4b.tmp", "book.m4b")]
    assert final.is_file()
    assert sorted(p.name for p in final.parent.iterdir()) == ["book.m4b", "meta.json"]


@pytest.mark.parametrize(
    "mode,code", [("network", "network"), ("decrypt", "decrypt")]
)
def test_get_failure_removes_partial_and_never_leaves_a_book(
    mode, code, run_cli, events, ffmpeg_bin, paths
):
    result = run_cli("get", ASIN, "--fake-fail", mode, fake=True)
    assert result.returncode != 0
    last = events(result)[-1]
    assert last["type"] == "error"
    assert last["code"] == code

    book_dir = paths.books_dir / ASIN
    assert not (book_dir / "book.m4b").exists()
    assert not (book_dir / ".partial").exists()
    assert not list(book_dir.glob("*.tmp"))


def test_get_disk_failure_refuses_before_writing(
    run_cli, events, ffmpeg_bin, paths
):
    result = run_cli("get", ASIN, "--fake-fail", "disk", fake=True)
    assert result.returncode != 0
    assert events(result)[-1]["code"] == "disk_space"
    assert not (paths.books_dir / ASIN / "book.m4b").exists()
    assert not list(paths.books_dir.glob("*/.partial"))


def test_free_space_preflight_requires_2_1x():
    dl.check_free_space(210, 100)  # exactly 2.1x is enough
    with pytest.raises(PipelineError) as excinfo:
        dl.check_free_space(209, 100)  # one byte short
    assert excinfo.value.code == "disk_space"


def test_get_novoucher_falls_back_to_aax(
    run_cli, events, ffmpeg_bin, paths
):
    result = run_cli("get", ASIN, "--fake-fail", "novoucher", fake=True)
    assert result.returncode == 0, result.stderr
    assert events(result)[-1]["type"] == "done"
    assert _meta(paths)["container"] == "aax"
    assert _chapter_titles(paths.books_dir / ASIN / "book.m4b") == EXPECTED_TITLES


def test_get_rejects_an_unknown_fake_fail_mode(run_cli, events):
    result = run_cli("get", ASIN, "--fake-fail", "explode", fake=True)
    assert result.returncode != 0
    assert events(result)[-1]["code"] == "invalid_args"


def test_get_requires_an_asin(run_cli, events):
    result = run_cli("get", fake=True)
    assert result.returncode != 0
    assert events(result)[-1]["code"] == "invalid_args"

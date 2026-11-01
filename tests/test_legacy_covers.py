"""0.1.9: covers kept from before 0.1.8 never reach the shell unchecked.

Marketplace review of 0.1.8 (#12516): the shell listed and loaded
``covers/<asin>.jpg`` by name, and the only check of an old cached cover ran
inside a ``sync`` that a failed sign-in, a network error or a recent catalog
could skip. The shell now reads ``covers-v2/``, which only the sanitiser
writes, and the legacy folder is converted by ``status`` (offline, every shell
start) as well as by ``sync``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

import qjs
from omarchy_audible import catalog, coverimage
from omarchy_audible.errors import PipelineError
from omarchy_audible.paths import COVERS_DIR_NAME

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "cover-jpeg"
BASELINE = (FIXTURES / "baseline.jpg").read_bytes()
PROGRESSIVE = (FIXTURES / "progressive.jpg").read_bytes()
# A PNG with a large compressed text chunk header: the shape the finding names.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x10\x00zTXt" + b"\x00" * 64
COMMENT = b"\xff\xfe\x00\x05old"


def legacy(paths, files: dict[str, bytes]) -> Path:
    paths.legacy_covers_dir.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (paths.legacy_covers_dir / name).write_bytes(data)
    return paths.legacy_covers_dir


def test_names_differ_and_match_the_shell():
    assert COVERS_DIR_NAME == "covers-v2"
    parts = qjs.load("Parts")
    assert parts.evaluate("COVERS_DIR") == COVERS_DIR_NAME
    assert (
        parts.call("coverUrl", "/d", "B0FAKE0001")
        == f"file:///d/{COVERS_DIR_NAME}/B0FAKE0001.jpg"
    )


def test_service_lists_only_the_sanitised_folder():
    service = (REPO / "Service.qml").read_text(encoding="utf-8")
    assert re.search(r'coversDir:.*"/" \+ Parts\.COVERS_DIR', service)
    assert '"/covers"' not in service
    for path in [
        *REPO.glob("*.qml"),
        *(REPO / "qml").rglob("*.qml"),
        *(REPO / "qml").rglob("*.js"),
    ]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"[\"'/]covers/", text), path


def test_clean_and_dirty_jpegs_are_carried_over_sanitised(paths):
    folder = legacy(
        paths,
        {
            "B0FAKE0001.jpg": BASELINE,
            "B0FAKE0002.jpg": PROGRESSIVE[:2] + COMMENT + PROGRESSIVE[2:] + b"tail",
        },
    )
    assert catalog.migrate_legacy_covers(paths) == 2
    assert not folder.exists()
    assert (
        paths.covers_dir / "B0FAKE0001.jpg"
    ).read_bytes() == coverimage.sanitize_jpeg(BASELINE)
    assert (
        paths.covers_dir / "B0FAKE0002.jpg"
    ).read_bytes() == coverimage.sanitize_jpeg(PROGRESSIVE)


@pytest.mark.parametrize(
    "data",
    [PNG, b"GIF89a", b"", b"\xff\xd8garbage"],
    ids=["png", "gif", "empty", "broken"],
)
def test_an_unusable_legacy_cover_is_dropped(paths, data):
    folder = legacy(paths, {"B0FAKE0001.jpg": data})
    assert catalog.migrate_legacy_covers(paths) == 0
    assert not folder.exists()
    assert not (paths.covers_dir / "B0FAKE0001.jpg").exists()


def test_an_oversized_legacy_cover_is_dropped_without_reading_it(paths, monkeypatch):
    folder = legacy(paths, {"B0FAKE0001.jpg": b""})
    with (folder / "B0FAKE0001.jpg").open("wb") as handle:
        handle.truncate(coverimage.MAX_COVER_BYTES + 1)
    monkeypatch.setattr(
        coverimage, "sanitize_jpeg", lambda _data: pytest.fail("must not be decoded")
    )
    assert catalog.migrate_legacy_covers(paths) == 0
    assert not folder.exists()


def test_other_names_are_not_carried_over(paths):
    folder = legacy(
        paths,
        {
            "notes.txt": b"x",
            "B0FAKE0001.png": BASELINE,
            ".B0FAKE0001.jpg.tmp": BASELINE,
            "B0-FAKE-01.jpg": BASELINE,
        },
    )
    (folder / "sub").mkdir()
    (folder / "sub" / "B0FAKE0002.jpg").write_bytes(BASELINE)
    assert catalog.migrate_legacy_covers(paths) == 0
    assert not folder.exists()
    assert not paths.covers_dir.exists() or list(paths.covers_dir.iterdir()) == []


def test_a_sanitised_cover_already_there_wins(paths):
    paths.covers_dir.mkdir(parents=True)
    current = coverimage.sanitize_jpeg(PROGRESSIVE)
    (paths.covers_dir / "B0FAKE0001.jpg").write_bytes(current)
    legacy(paths, {"B0FAKE0001.jpg": BASELINE})
    assert catalog.migrate_legacy_covers(paths) == 0
    assert (paths.covers_dir / "B0FAKE0001.jpg").read_bytes() == current


def test_nothing_to_do_is_a_no_op(paths):
    assert catalog.migrate_legacy_covers(paths) == 0
    assert not paths.data_dir.exists() or not paths.covers_dir.exists()


def test_symlinks_are_never_followed(paths, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "B0FAKE0001.jpg"
    sentinel.write_bytes(BASELINE)
    folder = legacy(paths, {})
    (folder / "B0FAKE0001.jpg").symlink_to(sentinel)
    assert catalog.migrate_legacy_covers(paths) == 0
    assert sentinel.read_bytes() == BASELINE
    assert not (paths.covers_dir / "B0FAKE0001.jpg").exists()
    assert not folder.exists()


def test_a_symlinked_legacy_folder_is_unlinked_not_followed(paths, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "B0FAKE0001.jpg").write_bytes(BASELINE)
    paths.data_dir.mkdir(parents=True)
    paths.legacy_covers_dir.symlink_to(outside, target_is_directory=True)
    assert catalog.migrate_legacy_covers(paths) == 0
    assert not paths.legacy_covers_dir.is_symlink()
    assert (outside / "B0FAKE0001.jpg").read_bytes() == BASELINE
    assert not (paths.covers_dir / "B0FAKE0001.jpg").exists()


def test_a_symlinked_sanitised_folder_is_not_written_through(paths, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    paths.data_dir.mkdir(parents=True)
    paths.covers_dir.symlink_to(outside, target_is_directory=True)
    legacy(paths, {"B0FAKE0001.jpg": BASELINE})
    assert catalog.migrate_legacy_covers(paths) == 0
    assert list(outside.iterdir()) == []


def test_status_converts_without_network_or_sign_in(run_cli, paths):
    legacy(paths, {"B0FAKE0001.jpg": BASELINE, "B0FAKE0002.jpg": PNG})
    result = run_cli("status")
    assert result.returncode == 0, result.stderr
    assert not paths.legacy_covers_dir.exists()
    assert (
        paths.covers_dir / "B0FAKE0001.jpg"
    ).read_bytes() == coverimage.sanitize_jpeg(BASELINE)
    assert not (paths.covers_dir / "B0FAKE0002.jpg").exists()
    status = json.loads(result.stdout.splitlines()[0])
    assert status["authenticated"] is False


def test_a_sync_that_fails_before_the_library_still_converts(paths):
    legacy(paths, {"B0FAKE0001.jpg": PNG})

    class Broken:
        def pages(self):
            raise OSError("offline")

    with pytest.raises(PipelineError):
        catalog.run_sync(
            paths,
            fake=True,
            library=Broken(),
            positions_port=object(),
            cover_fetch=None,
            emit=lambda *_a, **_k: None,
        )
    assert not paths.legacy_covers_dir.exists()


def test_catalog_points_at_the_sanitised_folder():
    built, covers = catalog.build_catalog(
        [
            {
                "asin": "B0FAKE0001",
                "title": "Invented",
                "product_images": {"252": "https://x.invalid/c.jpg"},
            }
        ],
        marketplace="us",
        synced_at="2026-11-01T00:00:00Z",
    )
    assert built["books"][0]["cover"] == f"{COVERS_DIR_NAME}/B0FAKE0001.jpg"
    assert covers == {"B0FAKE0001": "https://x.invalid/c.jpg"}


def test_unreadable_legacy_folder_does_not_fail_status(run_cli, paths):
    folder = legacy(paths, {"B0FAKE0001.jpg": BASELINE})
    os.chmod(folder, 0)
    try:
        result = run_cli("status")
    finally:
        if folder.exists():
            os.chmod(folder, 0o700)
    assert result.returncode == 0, result.stderr
    assert not (paths.covers_dir / "B0FAKE0001.jpg").exists()

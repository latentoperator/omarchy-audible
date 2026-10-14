"""B05: malformed catalog identifiers never become filesystem or network input."""

from __future__ import annotations

import json

import pytest

from omarchy_audible import catalog


@pytest.fixture(autouse=True)
def isolated_environment(env, tmp_path, monkeypatch):
    for name in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR"):
        monkeypatch.setenv(name, env[name])
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setenv("TMPDIR", str(scratch))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


class SpyPositions:
    def __init__(self):
        self.asins = []

    def fetch_batch(self, asins):
        self.asins.extend(asins)
        return {asin: {"ms": 0, "updated_at": None} for asin in asins}


def sync(paths, asin, fetch, *, full=False):
    port = SpyPositions()
    counts = catalog.run_sync(
        paths,
        fake=True,
        full=full,
        library=catalog.FakeLibrary(
            [{"asin": asin, "product_images": {"252": "https://example.invalid/c.jpg"}}]
        ),
        positions_port=port,
        cover_fetch=fetch,
        emit=lambda *_args, **_kwargs: None,
    )
    return counts, port.asins


@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize(
    "invalid",
    [
        "../../outside/sentinel",
        "../../new-parent/sentinel",
        "absolute",
        "nested/cover",
        r"nested\cover",
        "B00FAKE01\n",
        "B00FAKE01\r\n",
        " B00FAKE01",
        "B00FAKE01 ",
        "B00FAKÉ01",
        "A" * 33,
        "ABC",
        "",
        None,
        1234567890,
        True,
        ["B00FAKE01"],
        {"asin": "B00FAKE01"},
    ],
)
def test_sync_rejects_invalid_asins_before_cover_or_positions_io(
    paths, tmp_path, invalid, full
):
    outside = paths.data_dir.parent / "outside" / "sentinel.jpg"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"original synthetic cover")
    if invalid == "absolute":
        invalid = str(tmp_path / "absolute-parent" / "cover")
    fetched = []

    def fetch(url):
        fetched.append(url)
        return b"replacement"

    counts, asins = sync(paths, invalid, fetch, full=full)

    assert counts == {"books": 0, "covers": 0, "positions": 0}
    assert asins == []
    assert fetched == []
    assert outside.read_bytes() == b"original synthetic cover"
    assert not (paths.data_dir.parent / "new-parent").exists()
    assert not (tmp_path / "absolute-parent").exists()
    assert not paths.covers_dir.exists()
    assert json.loads(paths.catalog_file.read_text())["books"] == []


@pytest.mark.parametrize(
    "invalid", ["../../new-parent/cover", "/absolute/cover", "B00FAKE01\n", None, 1234]
)
def test_fetch_covers_independently_rejects_invalid_identifiers(
    paths, tmp_path, invalid
):
    if invalid == "/absolute/cover":
        invalid = str(tmp_path / "absolute-parent" / "cover")
    fetched = []
    count = catalog.fetch_covers(
        paths,
        {invalid: "https://example.invalid/c.jpg"},
        fetch=lambda url: fetched.append(url) or b"replacement",
        full=True,
    )
    assert count == 0
    assert fetched == []
    assert not paths.data_dir.exists()


@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize(
    "escape",
    ["directory", "dangling-directory", "sibling", "file", "dangling-file", "loop"],
)
def test_cover_destination_rejects_symlink_escapes(paths, tmp_path, escape, full):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "B00FAKE01.jpg"
    sentinel.write_bytes(b"original synthetic cover")
    paths.data_dir.mkdir(parents=True)
    if escape == "directory":
        paths.covers_dir.symlink_to(outside, target_is_directory=True)
    elif escape == "dangling-directory":
        paths.covers_dir.symlink_to(outside / "new-parent", target_is_directory=True)
    elif escape == "sibling":
        paths.covers_dir.symlink_to(paths.data_dir / "other", target_is_directory=True)
    else:
        paths.covers_dir.mkdir()
        target = paths.covers_dir / "B00FAKE01.jpg"
        destination = {
            "file": sentinel,
            "dangling-file": outside / "new-parent" / "cover.jpg",
            "loop": target,
        }[escape]
        target.symlink_to(destination)
    fetched = []
    count = catalog.fetch_covers(
        paths,
        {"B00FAKE01": "https://example.invalid/c.jpg"},
        fetch=lambda url: fetched.append(url) or b"replacement",
        full=full,
    )
    assert count == 0
    assert fetched == []
    assert sentinel.read_bytes() == b"original synthetic cover"
    assert not (outside / "new-parent").exists()
    assert not (paths.data_dir / "other").exists()


def test_cover_destination_is_rechecked_after_fetch(paths, tmp_path):
    paths.data_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "B00FAKE01.jpg"
    sentinel.write_bytes(b"original synthetic cover")

    def fetch(_url):
        paths.covers_dir.symlink_to(outside, target_is_directory=True)
        return b"replacement"

    assert (
        catalog.fetch_covers(
            paths,
            {"B00FAKE01": "https://example.invalid/c.jpg"},
            fetch=fetch,
            full=True,
        )
        == 0
    )
    assert sentinel.read_bytes() == b"original synthetic cover"


@pytest.mark.parametrize(
    "asin", ["B0FAKE0002", "B00FAKE01", "B0FAKELONG", "0123456789", "abcd", "A" * 32]
)
def test_valid_identifiers_keep_missing_and_full_cover_refresh(paths, asin):
    fetched = []

    def fetch(url):
        fetched.append(url)
        return f"synthetic cover {len(fetched)}".encode()

    assert sync(paths, asin, fetch)[0] == {"books": 1, "covers": 1, "positions": 1}
    assert sync(paths, asin, fetch)[0]["covers"] == 0
    assert sync(paths, asin, fetch, full=True)[0]["covers"] == 1
    assert len(fetched) == 2
    assert (paths.covers_dir / f"{asin}.jpg").read_bytes() == b"synthetic cover 2"
    assert json.loads(paths.catalog_file.read_text())["books"][0]["asin"] == asin

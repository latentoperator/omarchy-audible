"""Covers are fetched with a byte cap and rebuilt as plain JPEGs before the shell
decodes them (marketplace review of ``26ef679``: unbounded body, unchanged bytes
published to Qt Image)."""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from omarchy_audible import catalog, coverimage

FIXTURES = Path(__file__).parent / "fixtures" / "cover-jpeg"
BASELINE = (FIXTURES / "baseline.jpg").read_bytes()
PROGRESSIVE = (FIXTURES / "progressive.jpg").read_bytes()


@pytest.fixture(autouse=True)
def isolated_environment(env, tmp_path, monkeypatch):
    for name in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR"):
        monkeypatch.setenv(name, env[name])
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


def segment(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + (len(payload) + 2).to_bytes(2, "big") + payload


def markers(data: bytes) -> list[int]:
    """Top-level markers of a sanitised JPEG, skipping scan data."""
    found = []
    i = 2
    while data[i : i + 2] != b"\xff\xd9":
        marker = data[i + 1]
        found.append(marker)
        i += 2 + int.from_bytes(data[i + 2 : i + 4], "big")
        if marker == 0xDA:
            i = coverimage._entropy_end(data, i)
    return found


def with_segment_after_soi(data: bytes, extra: bytes) -> bytes:
    return data[:2] + extra + data[2:]


def replace_frame(data: bytes, height: int, width: int, marker: int = 0xC0) -> bytes:
    i = 2
    while True:
        m = data[i + 1]
        end = i + 2 + int.from_bytes(data[i + 2 : i + 4], "big")
        if m in (0xC0, 0xC2):
            payload = bytearray(data[i + 4 : end])
            payload[1:3] = height.to_bytes(2, "big")
            payload[3:5] = width.to_bytes(2, "big")
            return (
                data[:i]
                + bytes([0xFF, marker])
                + data[i + 2 : i + 4]
                + payload
                + data[end:]
            )
        i = end


# --- sanitize_jpeg -------------------------------------------------------------
@pytest.mark.parametrize(
    "source", [BASELINE, PROGRESSIVE], ids=["baseline", "progressive"]
)
def test_real_jpegs_keep_their_decoding_segments(source):
    clean = coverimage.sanitize_jpeg(source)
    assert clean.startswith(b"\xff\xd8") and clean.endswith(b"\xff\xd9")
    assert 0xE0 not in markers(clean)  # the JFIF header is ancillary
    assert {0xDB, 0xC4, 0xDA} <= set(markers(clean))
    # Sanitising is idempotent, so a clean cache is never rewritten.
    assert coverimage.sanitize_jpeg(clean) == clean


def test_sanitised_cover_decodes_to_the_same_pixels():
    qtgui = pytest.importorskip("PySide6.QtGui")
    for source in (BASELINE, PROGRESSIVE):
        before = qtgui.QImage.fromData(source)
        after = qtgui.QImage.fromData(coverimage.sanitize_jpeg(source))
        assert not after.isNull()
        assert (after.width(), after.height()) == (8, 8)
        assert after == before


@pytest.mark.parametrize(
    "extra",
    [
        segment(0xE1, b"Exif\x00\x00" + b"\x00" * 4000),
        segment(0xE2, b"ICC_PROFILE\x00" + b"\x00" * 4000),
        segment(0xED, b"Photoshop 3.0\x00" + b"\x00" * 100),
        segment(0xFE, b"synthetic comment"),
        segment(0xEE, b"Adobe-but-the-wrong-length"),
    ],
    ids=["exif", "icc", "app13", "comment", "malformed-app14"],
)
def test_ancillary_segments_are_dropped(extra):
    clean = coverimage.sanitize_jpeg(with_segment_after_soi(BASELINE, extra))
    assert clean == coverimage.sanitize_jpeg(BASELINE)


def test_a_well_formed_adobe_segment_is_kept():
    adobe = segment(0xEE, b"Adobe" + b"\x00\x64\x00\x00\x00\x00\x01")
    clean = coverimage.sanitize_jpeg(with_segment_after_soi(BASELINE, adobe))
    assert adobe in clean


def test_bytes_after_end_of_image_are_dropped():
    clean = coverimage.sanitize_jpeg(BASELINE + b"\x89PNG trailing payload" * 100)
    assert clean == coverimage.sanitize_jpeg(BASELINE)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
        b"GIF89a" + b"\x00" * 64,
        b"RIFF\x00\x00\x00\x00WEBP",
        b"<svg xmlns='http://www.w3.org/2000/svg'/>",
        b"\xff\xd8",
        b"\xff\xd8\xff\xd9",
        BASELINE[: len(BASELINE) // 2],
        b"\xff\xd8\xff\xe0\x00",
        b"\xff\xd8\xff\xe0\xff\xff",
        "not bytes",
        None,
    ],
    ids=[
        "empty",
        "png",
        "gif",
        "webp",
        "svg",
        "soi-only",
        "no-frame",
        "truncated",
        "short-length",
        "length-past-end",
        "str",
        "none",
    ],
)
def test_non_jpeg_or_broken_data_is_rejected(data):
    with pytest.raises(coverimage.CoverRejected):
        coverimage.sanitize_jpeg(data)


@pytest.mark.parametrize(
    ("height", "width"),
    [
        (coverimage.MAX_DIMENSION + 1, 8),
        (8, coverimage.MAX_DIMENSION + 1),
        (0, 8),
        (65535, 65535),
    ],
)
def test_oversized_or_empty_frames_are_rejected(height, width):
    with pytest.raises(coverimage.CoverRejected):
        coverimage.sanitize_jpeg(replace_frame(BASELINE, height, width))


def test_frames_at_the_limit_are_accepted():
    side = coverimage.MAX_DIMENSION
    coverimage.sanitize_jpeg(replace_frame(BASELINE, side, side))


@pytest.mark.parametrize("marker", [0xC3, 0xC5, 0xC9, 0xCA, 0xCB, 0xCF])
def test_lossless_arithmetic_and_hierarchical_coding_is_rejected(marker):
    with pytest.raises(coverimage.CoverRejected):
        coverimage.sanitize_jpeg(replace_frame(BASELINE, 8, 8, marker=marker))


def test_unknown_markers_are_rejected():
    with pytest.raises(coverimage.CoverRejected):
        coverimage.sanitize_jpeg(with_segment_after_soi(BASELINE, segment(0xF0, b"x")))


def test_too_many_segments_are_rejected():
    padding = segment(0xFE, b"") * coverimage.MAX_SEGMENTS
    with pytest.raises(coverimage.CoverRejected):
        coverimage.sanitize_jpeg(with_segment_after_soi(BASELINE, padding))


def test_oversized_input_is_rejected_before_parsing():
    with pytest.raises(coverimage.CoverRejected):
        coverimage.sanitize_jpeg(BASELINE + b"\x00" * coverimage.MAX_COVER_BYTES)


# --- fetch_bounded ---------------------------------------------------------------
class FakeResponse(io.BytesIO):
    def __init__(
        self,
        body: bytes,
        *,
        length: str | None = None,
        url: str = "https://x.invalid/c.jpg",
    ):
        super().__init__(body)
        self.headers = {} if length is None else {"Content-Length": length}
        self.url = url
        self.reads: list[int] = []

    def read(self, size: int | None = -1) -> bytes:
        self.reads.append(-1 if size is None else size)
        return super().read(size)

    def geturl(self) -> str:
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


@pytest.fixture
def serve(monkeypatch):
    served = {}

    def install(response):
        def urlopen(request, timeout):
            served["request"] = request
            served["timeout"] = timeout
            return response

        monkeypatch.setattr(coverimage.urllib.request, "urlopen", urlopen)
        return served

    return install


def test_fetch_returns_a_small_body(serve):
    served = serve(FakeResponse(BASELINE, length=str(len(BASELINE))))
    assert coverimage.fetch_bounded("https://x.invalid/c.jpg", "ua") == BASELINE
    assert served["request"].get_header("User-agent") == "ua"
    assert served["timeout"] == coverimage.FETCH_TIMEOUT_S


def test_fetch_stops_reading_past_the_cap_without_a_length(serve):
    response = FakeResponse(b"\xff" * (coverimage.MAX_COVER_BYTES * 4))
    serve(response)
    with pytest.raises(coverimage.CoverRejected):
        coverimage.fetch_bounded("https://x.invalid/c.jpg", "ua")
    assert response.tell() <= coverimage.MAX_COVER_BYTES + 1
    assert all(0 < size <= 64 * 1024 for size in response.reads)


def test_fetch_refuses_a_declared_oversized_body_before_reading(serve):
    response = FakeResponse(b"", length=str(coverimage.MAX_COVER_BYTES + 1))
    serve(response)
    with pytest.raises(coverimage.CoverRejected):
        coverimage.fetch_bounded("https://x.invalid/c.jpg", "ua")
    assert response.reads == []


def test_fetch_accepts_exactly_the_cap(serve):
    body = b"\x00" * coverimage.MAX_COVER_BYTES
    serve(FakeResponse(body, length="not-a-number"))
    assert coverimage.fetch_bounded("https://x.invalid/c.jpg", "ua") == body


@pytest.mark.parametrize(
    "url", ["http://x.invalid/c.jpg", "file:///etc/passwd", "ftp://x/c"]
)
def test_fetch_requires_https(serve, url):
    served = serve(FakeResponse(BASELINE))
    with pytest.raises(coverimage.CoverRejected):
        coverimage.fetch_bounded(url, "ua")
    assert "request" not in served


def test_fetch_refuses_a_redirect_off_https(serve):
    serve(FakeResponse(BASELINE, url="http://x.invalid/c.jpg"))
    with pytest.raises(coverimage.CoverRejected):
        coverimage.fetch_bounded("https://x.invalid/c.jpg", "ua")


def test_fetch_enforces_an_overall_deadline(serve, monkeypatch):
    serve(FakeResponse(b"\x00" * 1000))
    clock = iter([0.0, coverimage.FETCH_DEADLINE_S + 1])
    monkeypatch.setattr(coverimage.time, "monotonic", lambda: next(clock))
    with pytest.raises(coverimage.CoverRejected):
        coverimage.fetch_bounded("https://x.invalid/c.jpg", "ua")


def test_real_mode_sync_uses_the_bounded_fetch(monkeypatch):
    seen = []
    monkeypatch.setattr(
        coverimage, "fetch_bounded", lambda url, ua: seen.append((url, ua)) or BASELINE
    )
    assert catalog.http_fetch_cover("https://x.invalid/c.jpg") == BASELINE
    assert seen == [("https://x.invalid/c.jpg", catalog.COVER_USER_AGENT)]


# --- fetch_covers ----------------------------------------------------------------
COVERS = {"B00FAKE01": "https://x.invalid/c.jpg"}


def test_only_the_sanitised_cover_is_published(paths):
    dirty = with_segment_after_soi(
        BASELINE, segment(0xE1, b"Exif\x00\x00" + b"\x00" * 64)
    )
    assert catalog.fetch_covers(paths, COVERS, fetch=lambda _url: dirty + b"tail") == 1
    target = paths.covers_dir / "B00FAKE01.jpg"
    assert target.read_bytes() == coverimage.sanitize_jpeg(BASELINE)


@pytest.mark.parametrize("full", [False, True])
def test_a_rejected_cover_is_not_published_and_keeps_the_old_one(paths, full):
    target = paths.covers_dir / "B00FAKE01.jpg"
    assert catalog.fetch_covers(paths, COVERS, fetch=lambda _url: BASELINE) == 1
    before = target.read_bytes()
    count = catalog.fetch_covers(
        paths, COVERS, fetch=lambda _url: b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, full=full
    )
    assert count == 0
    assert target.read_bytes() == before
    assert [p.name for p in paths.covers_dir.iterdir()] == ["B00FAKE01.jpg"]


def test_a_legacy_cached_cover_is_sanitised_in_place_without_a_fetch(paths):
    paths.covers_dir.mkdir(parents=True)
    target = paths.covers_dir / "B00FAKE01.jpg"
    target.write_bytes(
        with_segment_after_soi(BASELINE, segment(0xFE, b"old")) + b"tail"
    )
    fetched = []
    assert (
        catalog.fetch_covers(paths, COVERS, fetch=lambda url: fetched.append(url)) == 0
    )
    assert fetched == []
    assert target.read_bytes() == coverimage.sanitize_jpeg(BASELINE)


def test_a_clean_cached_cover_is_left_untouched(paths):
    paths.covers_dir.mkdir(parents=True)
    target = paths.covers_dir / "B00FAKE01.jpg"
    target.write_bytes(coverimage.sanitize_jpeg(BASELINE))
    os.utime(target, (1_000_000, 1_000_000))
    assert catalog.fetch_covers(paths, COVERS, fetch=lambda _url: pytest.fail()) == 0
    assert target.stat().st_mtime == 1_000_000


@pytest.mark.parametrize(
    "cached",
    [b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, b"", None],
    ids=["png", "empty", "oversized"],
)
def test_an_unusable_cached_cover_is_replaced(paths, cached):
    paths.covers_dir.mkdir(parents=True)
    target = paths.covers_dir / "B00FAKE01.jpg"
    if cached is None:
        with target.open("wb") as handle:
            handle.truncate(coverimage.MAX_COVER_BYTES + 1)
    else:
        target.write_bytes(cached)
    assert catalog.fetch_covers(paths, COVERS, fetch=lambda _url: PROGRESSIVE) == 1
    assert target.read_bytes() == coverimage.sanitize_jpeg(PROGRESSIVE)


def test_an_unusable_cached_cover_is_removed_when_the_refetch_fails(paths):
    paths.covers_dir.mkdir(parents=True)
    target = paths.covers_dir / "B00FAKE01.jpg"
    target.write_bytes(b"GIF89a")

    def fail(_url):
        raise OSError("no network")

    assert catalog.fetch_covers(paths, COVERS, fetch=fail) == 0
    assert not target.exists()

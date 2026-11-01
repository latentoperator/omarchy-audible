"""Covers are fetched with a byte cap and rebuilt as plain JPEGs before the shell
decodes them (marketplace review of ``26ef679``: unbounded body, unchanged bytes
published to Qt Image).

The fetch tests run urllib for real against a local HTTP server, so redirect
handling and blocking reads are exercised rather than replaced.
"""

from __future__ import annotations

import http.server
import os
import threading
import time
from pathlib import Path

import pytest

from omarchy_audible import catalog, coverimage, fsutil

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


def segments(data: bytes) -> list[tuple[int, int, int]]:
    """``(marker, start, end)`` of each top-level segment of a plain JPEG."""
    found = []
    i = 2
    while data[i : i + 2] != b"\xff\xd9":
        marker = data[i + 1]
        end = i + 2 + int.from_bytes(data[i + 2 : i + 4], "big")
        found.append((marker, i, end))
        i = coverimage._entropy_end(data, end) if marker == 0xDA else end
    return found


def markers(data: bytes) -> list[int]:
    return [marker for marker, _start, _end in segments(data)]


def without(data: bytes, marker: int) -> bytes:
    for m, start, end in segments(data):
        if m == marker:
            return data[:start] + data[end:]
    return data


def with_segment_after_soi(data: bytes, extra: bytes) -> bytes:
    return data[:2] + extra + data[2:]


def edit_payload(data: bytes, marker: int, edit) -> bytes:
    for m, start, end in segments(data):
        if m == marker:
            payload = bytearray(data[start + 4 : end])
            edit(payload)
            return data[: start + 4] + bytes(payload) + data[end:]
    raise AssertionError(f"no marker {marker:02X}")


def replace_frame(data: bytes, height: int, width: int, marker: int = 0xC0) -> bytes:
    def edit(payload):
        payload[1:3] = height.to_bytes(2, "big")
        payload[3:5] = width.to_bytes(2, "big")

    sof = 0xC2 if 0xC2 in markers(data) else 0xC0
    out = edit_payload(data, sof, edit)
    start = next(s for m, s, _e in segments(out) if m == sof)
    return out[: start + 1] + bytes([marker]) + out[start + 2 :]


def decoded(data: bytes):
    qtgui = pytest.importorskip("PySide6.QtGui")
    image = qtgui.QImage.fromData(data)
    assert not image.isNull()
    return image


# --- sanitize_jpeg -------------------------------------------------------------
@pytest.mark.parametrize(
    "source", [BASELINE, PROGRESSIVE], ids=["baseline", "progressive"]
)
def test_real_jpegs_keep_their_decoding_segments(source):
    clean = coverimage.sanitize_jpeg(source)
    assert clean.startswith(b"\xff\xd8") and clean.endswith(b"\xff\xd9")
    assert markers(clean)[0] == 0xE0  # JFIF stays: it picks the colour space
    assert {0xDB, 0xC4, 0xDA} <= set(markers(clean))
    # Sanitising is idempotent, so a clean cache is never rewritten.
    assert coverimage.sanitize_jpeg(clean) == clean


def test_sanitised_cover_decodes_to_the_same_pixels():
    for source in (BASELINE, PROGRESSIVE):
        after = decoded(coverimage.sanitize_jpeg(source))
        assert (after.width(), after.height()) == (8, 8)
        assert after == decoded(source)


def relabel_rgb(data: bytes) -> bytes:
    """Give the three components the ids 'R', 'G', 'B' in the frame and scans.

    With such ids libjpeg reads the image as RGB unless a JFIF header says
    YCbCr, so dropping JFIF would change the colours.
    """
    ids = {1: ord("R"), 2: ord("G"), 3: ord("B")}

    def frame(payload):
        for k in range(payload[5]):
            payload[6 + 3 * k] = ids[payload[6 + 3 * k]]

    def scan(payload):
        for k in range(payload[0]):
            payload[1 + 2 * k] = ids[payload[1 + 2 * k]]

    out = edit_payload(data, 0xC0, frame)
    return edit_payload(out, 0xDA, scan)


def test_jfif_is_kept_so_colours_do_not_change():
    source = relabel_rgb(BASELINE)
    before = decoded(source)
    # The edge case is real: without JFIF the same bytes decode differently.
    assert decoded(without(source, 0xE0)) != before
    assert decoded(coverimage.sanitize_jpeg(source)) == before


def test_a_jfif_thumbnail_is_dropped():
    app0 = next((s, e) for m, s, e in segments(BASELINE) if m == 0xE0)
    jfif = bytearray(BASELINE[app0[0] + 4 : app0[1]])
    jfif[12:14] = b"\x02\x02"
    thumbed = BASELINE[:2] + segment(0xE0, bytes(jfif) + b"\x7f" * 12)
    thumbed += BASELINE[app0[1] :]
    clean = coverimage.sanitize_jpeg(thumbed)
    assert clean == coverimage.sanitize_jpeg(BASELINE)
    assert b"\x7f" * 12 not in clean


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
    # After the JFIF header, which must stay first.
    _m, _s, end = segments(BASELINE)[0]
    dirty = BASELINE[:end] + extra + BASELINE[end:]
    assert coverimage.sanitize_jpeg(dirty) == coverimage.sanitize_jpeg(BASELINE)


def test_a_second_app0_is_dropped():
    _m, _s, end = segments(BASELINE)[0]
    jfxx = segment(0xE0, b"JFXX\x00\x10" + b"\x00" * 3000)
    dirty = BASELINE[:end] + jfxx + BASELINE[end:]
    assert coverimage.sanitize_jpeg(dirty) == coverimage.sanitize_jpeg(BASELINE)


def test_a_well_formed_adobe_segment_is_kept():
    adobe = segment(0xEE, b"Adobe" + b"\x00\x64\x00\x00\x00\x00\x01")
    clean = coverimage.sanitize_jpeg(with_segment_after_soi(BASELINE, adobe))
    assert adobe in clean


def test_bytes_after_end_of_image_are_dropped():
    clean = coverimage.sanitize_jpeg(BASELINE + b"\x89PNG trailing payload" * 100)
    assert clean == coverimage.sanitize_jpeg(BASELINE)


@pytest.mark.parametrize("where", ["before-dqt", "before-eoi", "both-runs"])
def test_marker_fill_bytes_are_accepted(where):
    out = BASELINE
    dqt = next(s for m, s, _e in segments(out) if m == 0xDB)
    eoi = len(out) - 2
    if where in ("before-eoi", "both-runs"):
        out = out[:eoi] + b"\xff" * 3 + out[eoi:]
    if where in ("before-dqt", "both-runs"):
        out = out[:dqt] + b"\xff\xff" + out[dqt:]
    clean = coverimage.sanitize_jpeg(out)
    assert decoded(clean) == decoded(BASELINE)
    assert clean == coverimage.sanitize_jpeg(BASELINE)


def test_scan_data_keeps_stuffing_and_restart_markers_with_fill():
    scan = b"\x12\xff\x00\x34\xff\xd0\x56\xff\xff\xd1\x78"
    data = scan + b"\xff\xff\xd9"
    assert coverimage._entropy_end(data, 0) == len(scan)


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
        b"\xff\xd8\xff\xff\xff",
        b"\xff\xd8\xff\x00",
        b"\xff\xd8\xff\xd8\xff\xd9",
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
        "fill-to-end",
        "ff00-marker",
        "second-soi",
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


def test_random_corruption_never_raises_anything_but_cover_rejected():
    import random

    rng = random.Random(140)
    sources = (BASELINE, PROGRESSIVE)
    for _ in range(5000):
        data = bytearray(rng.choice(sources))
        for _ in range(rng.randint(1, 6)):
            pos = rng.randrange(len(data))
            action = rng.randrange(3)
            if action == 0:
                data[pos] = rng.randrange(256)
            elif action == 1:
                del data[pos]
            else:
                data.insert(pos, rng.choice((0xFF, 0x00, rng.randrange(256))))
        try:
            coverimage.sanitize_jpeg(bytes(data))
        except coverimage.CoverRejected:
            pass


# --- fetch_bounded, against a real local server --------------------------------
class Server:
    """A local HTTP server whose routes are ``path -> handler(request)``."""

    def __init__(self):
        self.routes = {}
        self.release = threading.Event()
        routes = self.routes

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                try:
                    routes[self.path](self)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, format, *args):
                del format, args

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, path: str) -> str:
        return self.base + path

    def close(self):
        self.release.set()
        self.httpd.shutdown()
        self.httpd.server_close()


def body(data: bytes, *, length: bool = True):
    def handler(request):
        request.send_response(200)
        if length:
            request.send_header("Content-Length", str(len(data)))
        else:
            request.send_header("Connection", "close")
        request.end_headers()
        request.wfile.write(data)

    return handler


@pytest.fixture
def server(monkeypatch):
    for name in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("no_proxy", "*")
    # The fetch is https-only; the local server speaks plain http, so the tests
    # allow http and use https as the scheme to refuse.
    monkeypatch.setattr(coverimage, "ALLOWED_SCHEMES", ("http",))
    monkeypatch.setattr(coverimage, "FETCH_TIMEOUT_S", 5)
    srv = Server()
    yield srv
    srv.close()


def fetch(url: str) -> bytes:
    return coverimage.fetch_bounded(url, "omaudible-test")


def test_fetch_returns_a_small_body_and_sends_the_user_agent(server):
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["User-Agent"]
        body(BASELINE)(request)

    server.routes["/c.jpg"] = handler
    assert fetch(server.url("/c.jpg")) == BASELINE
    assert seen["ua"] == "omaudible-test"


def test_fetch_stops_at_the_cap_without_a_length(server):
    server.routes["/big"] = body(
        b"\x00" * (coverimage.MAX_COVER_BYTES * 4), length=False
    )
    with pytest.raises(coverimage.CoverRejected, match="too large"):
        fetch(server.url("/big"))


def test_fetch_accepts_exactly_the_cap(server):
    data = b"\x00" * coverimage.MAX_COVER_BYTES
    server.routes["/cap"] = body(data, length=False)
    assert fetch(server.url("/cap")) == data


def test_fetch_refuses_a_declared_oversized_body_before_reading(server):
    def handler(request):
        request.send_response(200)
        request.send_header("Content-Length", str(coverimage.MAX_COVER_BYTES + 1))
        request.end_headers()
        request.wfile.flush()
        server.release.wait(10)

    server.routes["/declared"] = handler
    started = time.monotonic()
    with pytest.raises(coverimage.CoverRejected, match="too large"):
        fetch(server.url("/declared"))
    assert time.monotonic() - started < 2


def redirect(location: str, *, junk: int = 0, stall: Server | None = None):
    def handler(request):
        request.send_response(302)
        request.send_header("Location", location)
        request.send_header("Content-Length", str(max(junk, 1) * 64))
        request.end_headers()
        request.wfile.write(b"\x00" * 1024 if junk else b"\x00" * 64)
        request.wfile.flush()
        if stall is not None:
            stall.release.wait(10)

    return handler


def test_a_redirect_body_is_not_read(server):
    # urllib's stock handler drains this 64 MiB body before following the
    # redirect; it stalls after 1 KiB, so draining would block until timeout.
    server.routes["/start"] = redirect(
        server.url("/c.jpg"), junk=1024 * 1024, stall=server
    )
    server.routes["/c.jpg"] = body(BASELINE)
    started = time.monotonic()
    assert fetch(server.url("/start")) == BASELINE
    assert time.monotonic() - started < 2


def test_a_redirect_to_a_refused_scheme_is_not_followed(server):
    hits = []
    server.routes["/start"] = redirect("https://127.0.0.1:1/c.jpg")
    server.routes["/c.jpg"] = lambda request: hits.append(1) or body(BASELINE)(request)
    with pytest.raises(coverimage.CoverRejected, match="not https"):
        fetch(server.url("/start"))
    assert hits == []


def test_every_hop_is_checked(server):
    server.routes["/a"] = redirect("https://127.0.0.1:1/b")
    with pytest.raises(coverimage.CoverRejected):
        fetch(server.url("/a"))


def test_redirect_chains_are_bounded(server):
    for n in range(10):
        server.routes[f"/r{n}"] = redirect(server.url(f"/r{n + 1}"))
    server.routes["/r10"] = body(BASELINE)
    with pytest.raises(coverimage.CoverRejected, match="too many cover redirects"):
        fetch(server.url("/r0"))


def test_redirect_cycles_count_every_hop(server):
    hits = []

    def bounce(target):
        def handler(request):
            hits.append(request.path)
            redirect(server.url(target))(request)

        return handler

    server.routes["/a"] = bounce("/b")
    server.routes["/b"] = bounce("/a")
    with pytest.raises(coverimage.CoverRejected, match="too many cover redirects"):
        fetch(server.url("/a"))
    assert len(hits) == coverimage.MAX_REDIRECTS + 1


def test_the_last_allowed_hop_is_followed(server):
    for n in range(coverimage.MAX_REDIRECTS):
        server.routes[f"/r{n}"] = redirect(server.url(f"/r{n + 1}"))
    server.routes[f"/r{coverimage.MAX_REDIRECTS}"] = body(BASELINE)
    assert fetch(server.url("/r0")) == BASELINE


def test_a_slow_drip_is_cut_off_by_the_wall_clock(server, monkeypatch):
    monkeypatch.setattr(coverimage, "FETCH_DEADLINE_S", 0.5)
    monkeypatch.setattr(coverimage, "FETCH_TIMEOUT_S", 0.3)

    def handler(request):
        request.send_response(200)
        request.send_header("Content-Length", "1000")
        request.end_headers()
        for _ in range(1000):
            if server.release.wait(0.05):
                return
            request.wfile.write(b"\x00")
            request.wfile.flush()

    server.routes["/drip"] = handler
    started = time.monotonic()
    with pytest.raises(coverimage.CoverRejected, match="too long"):
        fetch(server.url("/drip"))
    assert time.monotonic() - started < 2


def test_the_wall_clock_restores_the_alarm_handler(server):
    import signal

    before = signal.getsignal(signal.SIGALRM)
    server.routes["/c.jpg"] = body(BASELINE)
    fetch(server.url("/c.jpg"))
    assert signal.getsignal(signal.SIGALRM) == before
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


@pytest.mark.parametrize(
    "url", ["http://x.invalid/c.jpg", "file:///etc/passwd", "ftp://x/c"]
)
def test_production_fetch_requires_https(url, monkeypatch):
    monkeypatch.setattr(
        coverimage, "_opener", lambda: pytest.fail("must not open a connection")
    )
    with pytest.raises(coverimage.CoverRejected, match="not https"):
        coverimage.fetch_bounded(url, "ua")


def test_real_mode_sync_uses_the_bounded_fetch(monkeypatch):
    seen = []
    monkeypatch.setattr(
        coverimage, "fetch_bounded", lambda url, ua: seen.append((url, ua)) or BASELINE
    )
    assert catalog.http_fetch_cover("https://x.invalid/c.jpg") == BASELINE
    assert seen == [("https://x.invalid/c.jpg", catalog.COVER_USER_AGENT)]


# --- fetch_covers ----------------------------------------------------------------
COVERS = {"B00FAKE01": "https://x.invalid/c.jpg"}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def cached(paths, data: bytes) -> Path:
    paths.covers_dir.mkdir(parents=True, exist_ok=True)
    target = paths.covers_dir / "B00FAKE01.jpg"
    target.write_bytes(data)
    return target


def test_only_the_sanitised_cover_is_published(paths):
    dirty = with_segment_after_soi(
        BASELINE, segment(0xE1, b"Exif\x00\x00" + b"\x00" * 64)
    )
    assert catalog.fetch_covers(paths, COVERS, fetch=lambda _url: dirty + b"tail") == 1
    target = paths.covers_dir / "B00FAKE01.jpg"
    assert target.read_bytes() == coverimage.sanitize_jpeg(BASELINE)


@pytest.mark.parametrize("full", [False, True])
def test_a_rejected_download_keeps_a_good_old_cover(paths, full):
    target = paths.covers_dir / "B00FAKE01.jpg"
    assert catalog.fetch_covers(paths, COVERS, fetch=lambda _url: BASELINE) == 1
    before = target.read_bytes()
    count = catalog.fetch_covers(paths, COVERS, fetch=lambda _url: PNG, full=full)
    assert count == 0
    assert target.read_bytes() == before
    assert [p.name for p in paths.covers_dir.iterdir()] == ["B00FAKE01.jpg"]


@pytest.mark.parametrize("full", [False, True])
def test_a_legacy_cached_cover_is_sanitised_in_place(paths, full):
    target = cached(
        paths, with_segment_after_soi(BASELINE, segment(0xFE, b"old")) + b"tail"
    )
    fetched = []

    def fail(url):
        fetched.append(url)
        raise OSError("no network")

    assert catalog.fetch_covers(paths, COVERS, fetch=fail, full=full) == 0
    assert fetched == ([COVERS["B00FAKE01"]] if full else [])
    assert target.read_bytes() == coverimage.sanitize_jpeg(BASELINE)


def test_cached_covers_are_checked_without_a_fetcher(paths):
    target = cached(paths, PNG)
    assert catalog.fetch_covers(paths, COVERS, fetch=None) == 0
    assert not target.exists()


def test_a_clean_cached_cover_is_left_untouched(paths):
    target = cached(paths, coverimage.sanitize_jpeg(BASELINE))
    os.utime(target, (1_000_000, 1_000_000))
    assert catalog.fetch_covers(paths, COVERS, fetch=lambda _url: pytest.fail()) == 0
    assert target.stat().st_mtime == 1_000_000


@pytest.mark.parametrize(
    "contents", [PNG, b"", None], ids=["png", "empty", "oversized"]
)
def test_an_unusable_cached_cover_is_replaced(paths, contents):
    if contents is None:
        target = cached(paths, b"")
        with target.open("wb") as handle:
            handle.truncate(coverimage.MAX_COVER_BYTES + 1)
    else:
        target = cached(paths, contents)
    assert catalog.fetch_covers(paths, COVERS, fetch=lambda _url: PROGRESSIVE) == 1
    assert target.read_bytes() == coverimage.sanitize_jpeg(PROGRESSIVE)


@pytest.mark.parametrize("full", [False, True])
def test_an_unusable_cached_cover_is_removed_when_the_refetch_fails(paths, full):
    target = cached(paths, PNG)

    def fail(_url):
        raise OSError("no network")

    assert catalog.fetch_covers(paths, COVERS, fetch=fail, full=full) == 0
    assert not target.exists()


@pytest.mark.parametrize("full", [False, True])
def test_an_unusable_cached_cover_is_removed_when_the_refetch_is_rejected(paths, full):
    target = cached(paths, b"GIF89a")
    assert catalog.fetch_covers(paths, COVERS, fetch=lambda _url: PNG, full=full) == 0
    assert not target.exists()


def test_a_failed_cache_rewrite_drops_the_cover_without_failing(paths, monkeypatch):
    target = cached(paths, with_segment_after_soi(BASELINE, segment(0xFE, b"old")))

    def broken_write(_path, _data):
        raise OSError("disk full")

    monkeypatch.setattr(fsutil, "atomic_write_bytes", broken_write)
    assert catalog.fetch_covers(paths, COVERS, fetch=None) == 0
    assert not target.exists()


def test_a_failed_cover_write_does_not_fail_the_sync(paths, monkeypatch):
    def broken_write(_path, _data):
        raise OSError("disk full")

    monkeypatch.setattr(fsutil, "atomic_write_bytes", broken_write)
    assert catalog.fetch_covers(paths, COVERS, fetch=lambda _url: BASELINE) == 0

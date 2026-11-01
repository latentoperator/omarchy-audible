"""Bounded cover download and JPEG sanitising (standard library only).

Covers are the only remote bytes the shell renders: ``Cover.qml`` hands
``covers/<asin>.jpg`` to Qt's image decoder inside ``omarchy-shell``. So a cover
is fetched with a byte cap and a wall-clock deadline, redirects are followed
without reading their bodies and only to https, and the file is published only
after :func:`sanitize_jpeg` has rebuilt it from the segments a baseline or
progressive Huffman JPEG needs to decode. Everything else is refused or
dropped: other image formats, arithmetic/lossless/hierarchical JPEG, more than
three components, frames larger than :data:`MAX_DIMENSION`, too many scans or
segments, and ancillary data (EXIF/XMP/ICC in ``APPn``, comments, thumbnails,
bytes after ``EOI``). A leading JFIF header is kept without its thumbnail,
because libjpeg uses its presence to choose the colour space; a well-formed
Adobe ``APP14`` is kept for its colour transform flag. Pixel data is untouched.

Audible serves 252 px progressive JPEGs of about 6-25 KB with ``image_sizes=252``,
so the limits leave wide headroom for real covers.
"""

from __future__ import annotations

import contextlib
import signal
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any

MAX_COVER_BYTES = 1024 * 1024
MAX_DIMENSION = 1024
MAX_SCANS = 32
MAX_SEGMENTS = 256
MAX_REDIRECTS = 3
FETCH_TIMEOUT_S = 20
FETCH_DEADLINE_S = 30
ALLOWED_SCHEMES = ("https",)
_CHUNK = 64 * 1024

_SOI = 0xD8
_EOI = 0xD9
# Huffman baseline, extended sequential and progressive frames only.
_SOF_ALLOWED = {0xC0, 0xC1, 0xC2}
# Tables and parameters that decoding needs; copied through unchanged.
_TABLES = {0xC4, 0xDB, 0xDD}
_SOS = 0xDA
_APP0 = 0xE0
_APP14 = 0xEE
# Adobe APP14's payload (after the length field) is fixed at 12 bytes.
_ADOBE_APP14_PAYLOAD = 12


class CoverRejected(ValueError):
    """The cover is not something the shell should be asked to decode."""


# --- fetching ------------------------------------------------------------------
def _require_allowed(url: str) -> None:
    if urllib.parse.urlsplit(url).scheme not in ALLOWED_SCHEMES:
        raise CoverRejected("cover URL is not https")


class _BoundedRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a few redirects, to allowed schemes only, without reading bodies.

    urllib's own handler drains each redirect body (``fp.read()``) before
    following it. ``redirect_request`` runs first, so closing the response here
    leaves nothing to drain.
    """

    max_redirections = MAX_REDIRECTS

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        fp.close()
        _require_allowed(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_BoundedRedirects())


@contextlib.contextmanager
def _wall_clock(seconds: float) -> Iterator[None]:
    """Interrupt the block after ``seconds``, even inside a blocking read.

    A socket timeout bounds each wait only, so a server that trickles bytes can
    hold one read open far longer. Backend commands run in the main thread,
    where a real-time timer can interrupt them; anywhere else the per-chunk
    deadline check in :func:`fetch_bounded` still applies.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def expire(_signum: int, _frame: Any) -> None:
        raise CoverRejected("cover download took too long")

    previous = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, signal.SIG_DFL if previous is None else previous)


def _declared_length(response: Any) -> int:
    """The response's Content-Length, or 0 when it is missing or unreadable."""
    try:
        return int(response.headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        return 0


def fetch_bounded(url: str, user_agent: str) -> bytes:
    """Download at most :data:`MAX_COVER_BYTES` over https within the deadline."""
    _require_allowed(url)
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    deadline = time.monotonic() + FETCH_DEADLINE_S
    with (
        _wall_clock(FETCH_DEADLINE_S),
        _opener().open(request, timeout=FETCH_TIMEOUT_S) as response,
    ):
        _require_allowed(response.geturl())
        if _declared_length(response) > MAX_COVER_BYTES:
            raise CoverRejected("cover is too large")
        data = bytearray()
        while True:
            if time.monotonic() > deadline:
                raise CoverRejected("cover download took too long")
            chunk = response.read(min(_CHUNK, MAX_COVER_BYTES + 1 - len(data)))
            if not chunk:
                return bytes(data)
            data += chunk
            if len(data) > MAX_COVER_BYTES:
                raise CoverRejected("cover is too large")


# --- sanitising ----------------------------------------------------------------
def _marker_at(data: bytes, i: int) -> tuple[int, int]:
    """Return ``(marker, index after it)`` for the marker at ``i``.

    Any number of ``0xFF`` fill bytes may precede a marker (T.81 B.1.1.2).
    """
    n = len(data)
    if i >= n or data[i] != 0xFF:
        raise CoverRejected("malformed JPEG marker")
    while i < n and data[i] == 0xFF:
        i += 1
    if i >= n or data[i] == 0x00:
        raise CoverRejected("malformed JPEG marker")
    return data[i], i + 1


def _payload(data: bytes, i: int) -> tuple[bytes, int]:
    """Return ``(payload, end)`` for the length-prefixed segment body at ``i``."""
    if i + 2 > len(data):
        raise CoverRejected("malformed JPEG segment length")
    length = int.from_bytes(data[i : i + 2], "big")
    end = i + length
    if length < 2 or end > len(data):
        raise CoverRejected("malformed JPEG segment length")
    return data[i + 2 : end], end


def _segment(marker: int, payload: bytes) -> bytes:
    return bytes((0xFF, marker)) + (len(payload) + 2).to_bytes(2, "big") + payload


def _check_frame(payload: bytes) -> None:
    if len(payload) < 6:
        raise CoverRejected("malformed JPEG frame header")
    precision = payload[0]
    height = int.from_bytes(payload[1:3], "big")
    width = int.from_bytes(payload[3:5], "big")
    components = payload[5]
    if precision != 8:
        raise CoverRejected("unsupported JPEG precision")
    if not (0 < width <= MAX_DIMENSION and 0 < height <= MAX_DIMENSION):
        raise CoverRejected("JPEG dimensions out of range")
    if components not in (1, 3) or len(payload) != 6 + 3 * components:
        raise CoverRejected("unsupported JPEG components")


def _jfif(payload: bytes) -> bytes | None:
    """A JFIF APP0 payload without its thumbnail, or None if it is not JFIF."""
    if len(payload) < 14 or not payload.startswith(b"JFIF\x00"):
        return None
    return payload[:12] + b"\x00\x00"


def _entropy_end(data: bytes, i: int) -> int:
    """Index of the marker (with any fill bytes) that ends scan data at ``i``.

    Stuffed ``FF 00`` and restart markers ``FF D0``-``FF D7``, with or without
    fill bytes before them, belong to the scan and are copied unchanged.
    """
    n = len(data)
    while i < n:
        if data[i] != 0xFF:
            i += 1
            continue
        start = i
        while i < n and data[i] == 0xFF:
            i += 1
        if i >= n:
            break
        following = data[i]
        if following == 0x00 or 0xD0 <= following <= 0xD7:
            i += 1
            continue
        return start
    raise CoverRejected("JPEG ends inside scan data")


def sanitize_jpeg(data: bytes) -> bytes:
    """Rebuild ``data`` from its decoding segments, or raise :class:`CoverRejected`."""
    if not isinstance(data, (bytes, bytearray)):
        raise CoverRejected("cover is not bytes")
    data = bytes(data)
    if len(data) > MAX_COVER_BYTES:
        raise CoverRejected("cover is too large")
    if data[:2] != b"\xff\xd8":
        raise CoverRejected("cover is not a JPEG")
    out = [b"\xff\xd8"]
    i = 2
    frame = False
    scans = 0
    segments = 0
    while True:
        segments += 1
        if segments > MAX_SEGMENTS:
            raise CoverRejected("too many JPEG segments")
        marker, i = _marker_at(data, i)
        if marker == _EOI:
            break
        if marker == _SOI or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            raise CoverRejected("unexpected JPEG marker")
        payload, end = _payload(data, i)
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if marker not in _SOF_ALLOWED:
                raise CoverRejected("unsupported JPEG coding")
            if frame:
                raise CoverRejected("more than one JPEG frame")
            _check_frame(payload)
            frame = True
            out.append(_segment(marker, payload))
        elif marker == _SOS:
            if not frame:
                raise CoverRejected("JPEG scan before frame")
            scans += 1
            if scans > MAX_SCANS:
                raise CoverRejected("too many JPEG scans")
            scan_end = _entropy_end(data, end)
            out.append(_segment(marker, payload) + data[end:scan_end])
            end = scan_end
        elif marker in _TABLES:
            out.append(_segment(marker, payload))
        elif marker == _APP0:
            kept = _jfif(payload)
            # Only a JFIF header straight after SOI counts (JFIF 1.02).
            if kept is not None and len(out) == 1:
                out.append(_segment(marker, kept))
        elif marker == _APP14:
            if len(payload) == _ADOBE_APP14_PAYLOAD and payload.startswith(b"Adobe"):
                out.append(_segment(marker, payload))
        elif 0xE1 <= marker <= 0xEF or marker == 0xFE:
            pass  # other APPn and COM: ancillary, dropped
        else:
            raise CoverRejected("unsupported JPEG marker")
        i = end
    if not frame or scans == 0:
        raise CoverRejected("JPEG has no image data")
    out.append(b"\xff\xd9")
    return b"".join(out)

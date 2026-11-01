"""Bounded cover download and JPEG sanitising (standard library only).

Covers are the only remote bytes the shell renders: ``Cover.qml`` hands
``covers/<asin>.jpg`` to Qt's image decoder inside ``omarchy-shell``. So a cover
is fetched with a byte cap and an overall deadline, and is published only after
:func:`sanitize_jpeg` has rebuilt it from the segments a baseline or progressive
Huffman JPEG needs to decode. Everything else is refused or dropped: other image
formats, arithmetic/lossless/hierarchical JPEG, more than three components,
frames larger than :data:`MAX_DIMENSION`, too many scans or segments, and all
ancillary data (EXIF/XMP/ICC/JFIF thumbnails in ``APPn``, comments, bytes after
``EOI``). The pixels are untouched; only the container is rebuilt.

Audible serves 252 px progressive JPEGs of about 6-25 KB with ``image_sizes=252``,
so the limits leave wide headroom for real covers.
"""

from __future__ import annotations

import time
import urllib.parse
import urllib.request

MAX_COVER_BYTES = 1024 * 1024
MAX_DIMENSION = 1024
MAX_SCANS = 32
MAX_SEGMENTS = 256
FETCH_TIMEOUT_S = 20
FETCH_DEADLINE_S = 30
_CHUNK = 64 * 1024

_SOI = b"\xff\xd8"
_EOI = b"\xff\xd9"
# Huffman baseline, extended sequential and progressive frames only.
_SOF_ALLOWED = {0xC0, 0xC1, 0xC2}
# Tables and parameters that decoding needs; copied through unchanged.
_TABLES = {0xC4, 0xDB, 0xDD}
_SOS = 0xDA
_APP14 = 0xEE
# Adobe APP14 is the one ancillary segment that changes decoded colours (its
# transform flag), so a well-formed one is kept. Its payload is fixed at 12 bytes.
_ADOBE_APP14_LENGTH = 14


class CoverRejected(ValueError):
    """The cover is not something the shell should be asked to decode."""


def fetch_bounded(url: str, user_agent: str) -> bytes:
    """Download at most :data:`MAX_COVER_BYTES` over HTTPS within the deadline."""
    if urllib.parse.urlsplit(url).scheme != "https":
        raise CoverRejected("cover URL is not https")
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    deadline = time.monotonic() + FETCH_DEADLINE_S
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_S) as response:
        if urllib.parse.urlsplit(response.geturl()).scheme != "https":
            raise CoverRejected("cover redirected away from https")
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


def _declared_length(response: object) -> int:
    """The response's Content-Length, or 0 when it is missing or unreadable."""
    try:
        return int(response.headers.get("Content-Length") or 0)  # type: ignore[attr-defined]
    except (TypeError, ValueError):
        return 0


def _segment(data: bytes, i: int) -> tuple[int, int]:
    """Return ``(marker, end)`` for the length-prefixed segment at ``i``."""
    if i + 4 > len(data) or data[i] != 0xFF:
        raise CoverRejected("malformed JPEG segment")
    marker = data[i + 1]
    length = int.from_bytes(data[i + 2 : i + 4], "big")
    end = i + 2 + length
    if length < 2 or end > len(data):
        raise CoverRejected("malformed JPEG segment length")
    return marker, end


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


def _entropy_end(data: bytes, i: int) -> int:
    """Index of the first marker after entropy-coded data starting at ``i``."""
    n = len(data)
    while i < n - 1:
        if data[i] == 0xFF:
            following = data[i + 1]
            if following != 0x00 and not 0xD0 <= following <= 0xD7:
                return i
            i += 2
        else:
            i += 1
    raise CoverRejected("JPEG ends inside scan data")


def sanitize_jpeg(data: bytes) -> bytes:
    """Rebuild ``data`` from its decoding segments, or raise :class:`CoverRejected`."""
    if not isinstance(data, (bytes, bytearray)):
        raise CoverRejected("cover is not bytes")
    data = bytes(data)
    if len(data) > MAX_COVER_BYTES:
        raise CoverRejected("cover is too large")
    if not data.startswith(_SOI):
        raise CoverRejected("cover is not a JPEG")
    out = [_SOI]
    i = 2
    frame = False
    scans = 0
    segments = 0
    while True:
        segments += 1
        if segments > MAX_SEGMENTS:
            raise CoverRejected("too many JPEG segments")
        if data[i : i + 2] == _EOI:
            break
        marker, end = _segment(data, i)
        payload = data[i + 4 : end]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if marker not in _SOF_ALLOWED:
                raise CoverRejected("unsupported JPEG coding")
            if frame:
                raise CoverRejected("more than one JPEG frame")
            _check_frame(payload)
            frame = True
            out.append(data[i:end])
        elif marker == _SOS:
            if not frame:
                raise CoverRejected("JPEG scan before frame")
            scans += 1
            if scans > MAX_SCANS:
                raise CoverRejected("too many JPEG scans")
            scan_end = _entropy_end(data, end)
            out.append(data[i:scan_end])
            end = scan_end
        elif marker in _TABLES:
            out.append(data[i:end])
        elif marker == _APP14:
            if end - i - 2 == _ADOBE_APP14_LENGTH and payload.startswith(b"Adobe"):
                out.append(data[i:end])
        elif 0xE0 <= marker <= 0xEF or marker == 0xFE:
            pass  # APPn and COM: ancillary, dropped
        else:
            raise CoverRejected("unsupported JPEG marker")
        i = end
    if not frame or scans == 0:
        raise CoverRejected("JPEG has no image data")
    out.append(_EOI)
    return b"".join(out)

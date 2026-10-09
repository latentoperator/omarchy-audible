"""Local books: the filesystem scan, removal and playback info (ARCHITECTURE 3, 4.4).

The filesystem is the source of truth for "is this book local". A book is a
directory ``<booksDir>/<asin>/`` holding either the old decrypted
``book.m4b``, or the locked original ``book.aaxc``/``book.aax`` **plus** a
readable ``key.json`` (B11, D7). In progress work lives in ``.partial/`` and a
half-written book in a ``*.tmp`` file, none of which counts as local.

Removal only ever deletes one ASIN directory inside ``booksDir``. It refuses a
path that escapes ``booksDir`` and refuses a symlink, and it makes no network
call of any kind (ARCHITECTURE 4.4).
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import fsutil
from .errors import PipelineError
from .paths import Paths
from .protocol import ErrorCode

# Every audio file a book directory may hold. ``book.m4b`` is an old, unlocked
# download; the other two are the locked originals (B11).
BOOK_FILENAME = "book.m4b"
AUDIO_FILENAMES: tuple[str, ...] = ("book.m4b", "book.aaxc", "book.aax")
# The locked originals: local only together with a readable ``key.json``.
LOCKED_AUDIO_FILENAMES: tuple[str, ...] = ("book.aaxc", "book.aax")
KEY_FILENAME = "key.json"
CHAPTERS_FILENAME = "chapters.txt"
META_FILENAME = "meta.json"
PARTIAL_DIRNAME = ".partial"

# An ASIN becomes exactly one directory name. Real ASINs are ten upper-case
# letters and digits; allow a little slack around that, but the character class
# alone already excludes ``.``/``..``, NUL and both path separators.
_ASIN_RE = re.compile(r"^[A-Za-z0-9]{4,32}$")


def dir_size(path: Path) -> int:
    """Sum the sizes of every regular file under ``path`` (symlinks not followed)."""
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                continue
    return total


def book_dir(books_dir: Path, asin: str) -> Path:
    return books_dir / asin


def read_meta(directory: Path) -> dict[str, Any]:
    """Read ``meta.json``, or an empty dict when it is absent or unreadable."""
    try:
        data = json.loads((directory / META_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_meta(directory: Path, data: dict[str, Any]) -> None:
    fsutil.atomic_write_json(directory / META_FILENAME, data)


def read_key(directory: Path) -> dict[str, Any]:
    """Read ``key.json``, or an empty dict when it is absent or unreadable.

    A locked book is local only when this returns a dict, so "readable" here
    means "parses as a JSON object" (B11, ARCHITECTURE 3).
    """
    try:
        data = json.loads((directory / KEY_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def local_audio_file(directory: Path) -> Path | None:
    """The audio file that makes ``directory`` a local book, or ``None``.

    An old ``book.m4b`` is local on its own; a locked ``book.aaxc``/``book.aax``
    needs a readable ``key.json`` beside it (B11).
    """
    legacy = directory / BOOK_FILENAME
    if legacy.is_file():
        return legacy
    if read_key(directory):
        for name in LOCKED_AUDIO_FILENAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def read_activation_bytes(paths: Paths) -> str | None:
    """The account-wide legacy AAX key, read from disk only (no network call)."""
    try:
        value = paths.activation_bytes_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _iso_from_mtime(path: Path) -> str:
    try:
        stamp = path.stat().st_mtime
    except OSError:
        stamp = 0.0
    return datetime.fromtimestamp(stamp, tz=UTC).isoformat().replace("+00:00", "Z")


def iso_now() -> str:
    """Current UTC time as an ISO 8601 string with a trailing ``Z``."""
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def _meta_duration_ms(meta: dict[str, Any]) -> int | None:
    value = meta.get("duration_ms")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def scan_local(books_dir: Path) -> list[dict[str, Any]]:
    """Every downloaded book under ``books_dir``, sorted by ASIN."""
    if not books_dir.is_dir():
        return []
    books: list[dict[str, Any]] = []
    for entry in sorted(books_dir.iterdir()):
        if entry.is_symlink() or not entry.is_dir():
            continue
        if not _ASIN_RE.fullmatch(entry.name):
            continue
        audio = local_audio_file(entry)
        if audio is None:
            continue
        meta = read_meta(entry)
        downloaded_at = meta.get("downloaded_at")
        if not isinstance(downloaded_at, str) or not downloaded_at:
            downloaded_at = _iso_from_mtime(audio)
        books.append(
            {
                "asin": entry.name,
                "size": dir_size(entry),
                "downloaded_at": downloaded_at,
                "title": meta.get("title")
                if isinstance(meta.get("title"), str)
                else None,
                "duration_ms": _meta_duration_ms(meta),
                "authors": [
                    name for name in meta.get("authors", []) if isinstance(name, str)
                ]
                if isinstance(meta.get("authors", []), list)
                else [],
            }
        )
    return books


def play_info_payload(
    paths: Paths,
    asin: str,
    *,
    fetch_activation: Callable[[], str | None] | None = None,
) -> dict[str, Any]:
    """The ``play_info`` event payload for a local book (ARCHITECTURE 4.2, D7).

    ``lavf_options`` is the ready-made mpv ``demuxer-lavf-o`` value: the aaxc
    voucher key/iv, the account activation bytes for a legacy aax, or ``""``
    for an old ``book.m4b``. It is a secret; it is emitted only here, and only
    after validating the ASIN.

    A legacy aax with no activation bytes on disk calls ``fetch_activation``
    once (B13: real mode's lazy fill, a single network call that writes the key
    ``0600`` and returns it); if that returns nothing the error stays
    ``decrypt``. aaxc and old ``book.m4b`` books never call it.
    """
    target = validate_asin(paths.books_dir, asin)
    audio = local_audio_file(target)
    if audio is None:
        raise PipelineError(
            ErrorCode.NOT_LOCAL,
            f"no local book for {asin}",
            hint="it is not downloaded on this machine",
        )
    chapters = target / CHAPTERS_FILENAME
    lavf = ""
    if audio.name in LOCKED_AUDIO_FILENAMES:
        key = read_key(target)
        if audio.name == "book.aaxc":
            voucher_key = key.get("key")
            iv = key.get("iv")
            if (
                not isinstance(voucher_key, str)
                or not voucher_key
                or not isinstance(iv, str)
                or not iv
            ):
                raise PipelineError(
                    ErrorCode.DECRYPT,
                    "the book's key file is unreadable",
                    hint="download the book again",
                )
            lavf = f"audible_key={voucher_key},audible_iv={iv}"
        else:
            activation = read_activation_bytes(paths)
            if not activation and fetch_activation is not None:
                activation = fetch_activation()
            if not activation:
                raise PipelineError(
                    ErrorCode.DECRYPT,
                    "the account's activation bytes are missing",
                    hint="check the network connection and try again",
                )
            lavf = f"activation_bytes={activation}"
    return {
        "type": "play_info",
        "path": str(audio),
        "chapters_file": str(chapters) if chapters.is_file() else None,
        "lavf_options": lavf,
    }


def validate_asin(
    books_dir: Path, asin: str, *, code: str = ErrorCode.BAD_ASIN
) -> Path:
    """Resolve ``<booksDir>/<asin>`` or refuse it (ARCHITECTURE 4.4).

    The one ASIN check shared by every command that turns an ASIN into a path:
    the value must be a single path component of letters and digits (which
    already excludes ``.``/``..``, NUL and both separators), its resolved target
    must stay inside ``booksDir``, and the target must not be a symlink.
    ``code`` is the protocol error code to raise: ``bad_asin`` for ``get`` and
    ``cancel``, ``unsafe_path`` for ``remove`` (its documented safety code).
    """
    if not isinstance(asin, str) or not _ASIN_RE.match(asin):
        raise PipelineError(
            code,
            f"invalid ASIN: {asin!r}",
            hint="an ASIN is 4-32 letters or digits, for example B00FAKE01",
        )
    target = books_dir / asin
    books_real = books_dir.resolve()
    target_real = target.resolve()
    if target_real == books_real or books_real not in target_real.parents:
        raise PipelineError(
            code,
            f"refusing {target}: outside the books directory",
            hint=f"only paths inside {books_dir} are allowed",
        )
    if target.is_symlink():
        raise PipelineError(
            code,
            f"refusing symlink: {target}",
            hint="only a real book directory is allowed",
        )
    return target


def ensure_safe_target(books_dir: Path, asin: str) -> Path:
    """Resolve ``<booksDir>/<asin>`` for ``remove`` (ARCHITECTURE 4.4)."""
    return validate_asin(books_dir, asin, code=ErrorCode.UNSAFE_PATH)


def remove_book(books_dir: Path, asin: str) -> int:
    """Delete ``<booksDir>/<asin>`` and return the bytes freed.

    Local only: nothing here touches the network or the Audible account.
    """
    target = ensure_safe_target(books_dir, asin)
    if not target.is_dir():
        raise PipelineError(
            ErrorCode.NOT_LOCAL,
            f"no local book for {asin}",
            hint="it is not downloaded on this machine",
        )
    freed = dir_size(target)
    shutil.rmtree(target)
    return freed

"""Local books: the filesystem scan and the safe removal (ARCHITECTURE 3, 4.4).

The filesystem is the source of truth for "is this book local". A book is a
directory ``<booksDir>/<asin>/`` holding ``book.m4b`` and ``meta.json``; in
progress work lives in ``.partial/`` and a half-written book in
``book.m4b.tmp``, neither of which counts as local.

Removal only ever deletes one ASIN directory inside ``booksDir``. It refuses a
path that escapes ``booksDir`` and refuses a symlink, and it makes no network
call of any kind (ARCHITECTURE 4.4).
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import fsutil
from .errors import PipelineError
from .protocol import ErrorCode

BOOK_FILENAME = "book.m4b"
META_FILENAME = "meta.json"
PARTIAL_DIRNAME = ".partial"


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


def _iso_from_mtime(path: Path) -> str:
    try:
        stamp = path.stat().st_mtime
    except OSError:
        stamp = 0.0
    return datetime.fromtimestamp(stamp, tz=UTC).isoformat().replace("+00:00", "Z")


def iso_now() -> str:
    """Current UTC time as an ISO 8601 string with a trailing ``Z``."""
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def scan_local(books_dir: Path) -> list[dict[str, Any]]:
    """Every downloaded book under ``books_dir``, sorted by ASIN."""
    if not books_dir.is_dir():
        return []
    books: list[dict[str, Any]] = []
    for entry in sorted(books_dir.iterdir()):
        if entry.is_symlink() or not entry.is_dir():
            continue
        book = entry / BOOK_FILENAME
        if not book.is_file():
            continue
        meta = read_meta(entry)
        downloaded_at = meta.get("downloaded_at")
        if not isinstance(downloaded_at, str) or not downloaded_at:
            downloaded_at = _iso_from_mtime(book)
        books.append(
            {"asin": entry.name, "size": dir_size(entry), "downloaded_at": downloaded_at}
        )
    return books


def ensure_safe_target(books_dir: Path, asin: str) -> Path:
    """Resolve ``<booksDir>/<asin>`` or refuse it (ARCHITECTURE 4.4).

    An ASIN is a single path component: a value with a separator, ``.``/``..``,
    or one that resolves outside ``booksDir`` is refused. A symlink is refused
    by :func:`remove_book`, after this check.
    """
    if not asin or asin in {".", ".."} or "\0" in asin or "/" in asin or "\\" in asin:
        raise PipelineError(
            ErrorCode.UNSAFE_PATH,
            f"refusing to remove {asin!r}: not a plain ASIN",
            hint="remove takes a single ASIN",
        )
    target = books_dir / asin
    books_real = books_dir.resolve()
    target_real = target.resolve()
    if target_real == books_real or books_real not in target_real.parents:
        raise PipelineError(
            ErrorCode.UNSAFE_PATH,
            f"refusing to remove {target}: outside the books directory",
            hint=f"only directories inside {books_dir} can be removed",
        )
    return target


def remove_book(books_dir: Path, asin: str) -> int:
    """Delete ``<booksDir>/<asin>`` and return the bytes freed.

    Local only: nothing here touches the network or the Audible account.
    """
    target = ensure_safe_target(books_dir, asin)
    if target.is_symlink():
        raise PipelineError(
            ErrorCode.UNSAFE_PATH,
            f"refusing to remove symlink: {target}",
            hint="remove only deletes a real book directory",
        )
    if not target.is_dir():
        raise PipelineError(
            ErrorCode.NOT_LOCAL,
            f"no local book for {asin}",
            hint="it is not downloaded on this machine",
        )
    freed = dir_size(target)
    shutil.rmtree(target)
    return freed

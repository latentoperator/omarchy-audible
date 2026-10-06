"""``get``: download, decrypt and apply Audible's chapters (ARCHITECTURE 4.3).

Pipeline, in order:

1. Pre-flight: require 2.1x the content size in free space (S2 measured a 2.0x
   peak) before anything is written.
2. ``<booksDir>/<asin>/.partial/`` is created for the raw download.
3. Download with audible-cli, aaxc first and aax if no voucher is offered. A
   zero byte count is reported by polling the partial directory.
4. Decrypt with ffmpeg (aaxc: voucher ``key``/``iv``; aax: activation bytes) and
   rebuild the chapter list from Audible's ``chapters.json`` in the same
   ``-c copy`` pass.
5. ``ffprobe`` sanity check, then an atomic rename onto ``book.m4b``.
6. Write ``meta.json`` (including the cached ``acr``) and delete ``.partial/``;
   the raw ``.aax``/``.aaxc`` is never kept.

Any failure or SIGTERM deletes ``.partial/`` and the half-written
``book.m4b.tmp`` and leaves no ``book.m4b`` (ARCHITECTURE 4.3 step 7, 4.8).

The ``audible`` library is imported lazily, inside real-mode code paths only,
so the test suite runs without it installed.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import fsutil, protocol
from .chapters import Chapter, build_ffmetadata, parse_chapters
from .errors import Cancelled, PipelineError
from .library import (
    BOOK_FILENAME,
    PARTIAL_DIRNAME,
    book_dir,
    dir_size,
    iso_now,
    validate_asin,
    write_meta,
)
from .log import log
from .paths import Paths

FREE_SPACE_FACTOR = 2.1

# --- fake mode (ARCHITECTURE 4.2) --------------------------------------------
FAKE_FAIL_MODES = ("disk", "network", "decrypt", "novoucher")
FAKE_RAW_CHAPTERS = 3
FAKE_AUDIO_MS = 6000
FAKE_CONTENT_SIZE = 2_000_000
FAKE_ACR = "FAKEACR0"
_FAKE_TICKS = 10
_FAKE_TICK_SECONDS = 0.08

# The fake ``chapters.json``: a flat list with a different count from the raw
# m4b (3), so a passing chapter check proves the list was actually applied.
# Invented titles only.
FAKE_CHAPTERS_SPEC: dict[str, Any] = {
    "content_metadata": {
        "chapter_info": {
            "chapter_titles_type": "Flat",
            "runtime_length_ms": FAKE_AUDIO_MS,
            "chapters": [
                {"title": "Alpha", "start_offset_ms": 0, "length_ms": 1200},
                {"title": "Beta", "start_offset_ms": 1200, "length_ms": 1200},
                {"title": "Gamma", "start_offset_ms": 2400, "length_ms": 1200},
                {"title": "Delta", "start_offset_ms": 3600, "length_ms": 1200},
                {"title": "Epsilon", "start_offset_ms": 4800, "length_ms": 1200},
            ],
        }
    }
}

_REAL_POLL_SECONDS = 0.5
_M4B_TMP = "book.m4b.tmp"
_Emit = Callable[..., None]


@dataclass
class RawDownload:
    """The undecrypted audio plus everything needed to decrypt and chapter it."""

    raw_path: Path
    container: str  # "aaxc" | "aax"
    chapters: list[Chapter]
    key_args: list[str]


class ChildTracker:
    """Owns every subprocess spawned by one ``get`` so SIGTERM can stop them."""

    def __init__(self) -> None:
        self._children: list[subprocess.Popen[bytes]] = []

    def spawn(
        self, argv: list[str], *, env: dict[str, str] | None = None, quiet: bool = False
    ) -> subprocess.Popen[bytes]:
        stderr = subprocess.DEVNULL if quiet else subprocess.PIPE
        proc = subprocess.Popen(
            argv,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=stderr,
        )
        self._children.append(proc)
        return proc

    def terminate_all(self) -> None:
        for proc in self._children:
            if proc.poll() is None:
                proc.terminate()
        for proc in self._children:
            if proc.poll() is None:
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


# --- small filesystem helpers ------------------------------------------------
def _rmtree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _free_bytes(path: Path) -> int:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def check_free_space(free_bytes: int, content_size: int) -> None:
    """Refuse when the download cannot fit with headroom (ARCHITECTURE 4.3)."""
    required = math.ceil(content_size * FREE_SPACE_FACTOR)
    if required > free_bytes:
        raise PipelineError(
            protocol.ErrorCode.DISK_SPACE,
            f"needs about {required} bytes free, {free_bytes} available",
            hint="free some disk space and retry",
        )


def _tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise PipelineError(
            protocol.ErrorCode.INTERNAL,
            f"{name} is not installed",
            hint=f"install {name} (see: omarchy-audible doctor)",
        )
    return found


def _run(
    argv: list[str], children: ChildTracker, code: str, hint: str | None = None
) -> None:
    proc = children.spawn(argv)
    try:
        _out, err = proc.communicate()
    except Cancelled:
        proc.terminate()
        raise
    if proc.returncode != 0:
        text = (err or b"").decode("utf-8", "replace").strip().splitlines()
        log(f"{Path(argv[0]).name} exit {proc.returncode}: {text[-1] if text else ''}")
        raise PipelineError(code, f"{Path(argv[0]).name} failed", hint)


def probe_duration_ms(path: Path) -> int | None:
    result = subprocess.run(
        [
            _tool("ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return round(float(result.stdout.strip()) * 1000)
    except ValueError:
        return None


def probe_chapter_titles(path: Path) -> list[str]:
    result = subprocess.run(
        [_tool("ffprobe"), "-v", "error", "-show_chapters", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout or "{}")
    except ValueError:
        return []
    return [
        str((chapter.get("tags") or {}).get("title", ""))
        for chapter in data.get("chapters", [])
    ]


def _verify(tmp: Path, chapters: list[Chapter], expected_duration_ms: int | None) -> None:
    if chapters:
        titles = probe_chapter_titles(tmp)
        if len(titles) != len(chapters):
            raise PipelineError(
                protocol.ErrorCode.CONVERT,
                f"chapter count {len(titles)} does not match Audible's list ({len(chapters)})",
                hint="retry the download",
            )
    if expected_duration_ms:
        actual = probe_duration_ms(tmp)
        if actual is not None and abs(actual - expected_duration_ms) > max(
            1000, expected_duration_ms * 0.01
        ):
            raise PipelineError(
                protocol.ErrorCode.CONVERT,
                "the converted duration differs from the catalog",
                hint="retry the download",
            )


def _decrypt(raw: RawDownload, tmp: Path, children: ChildTracker) -> None:
    argv = [
        _tool("ffmpeg"),
        "-nostdin",
        "-v",
        "error",
        "-y",
        *raw.key_args,
        "-i",
        str(raw.raw_path),
    ]
    if raw.chapters:
        chapter_file = raw.raw_path.parent / "chapters-ffmetadata.txt"
        chapter_file.write_text(build_ffmetadata(raw.chapters), encoding="utf-8")
        argv += [
            "-i",
            str(chapter_file),
            "-map",
            "0:a",
            "-map_metadata",
            "1",
            "-map_chapters",
            "1",
        ]
    else:
        argv += ["-map", "0:a"]
    argv += ["-c", "copy", "-f", "ipod", str(tmp)]
    _run(argv, children, protocol.ErrorCode.DECRYPT, hint="retry the download")


# --- fake mode ---------------------------------------------------------------
def _fake_content_size(fake_fail: str | None, books_dir: Path) -> int:
    if fake_fail == "disk":
        # Anything above this cannot fit under the 2.1x rule.
        return _free_bytes(books_dir)
    return FAKE_CONTENT_SIZE


def _fake_fetch(
    asin: str,
    partial: Path,
    emit: _Emit,
    children: ChildTracker,
    fake_fail: str | None,
) -> RawDownload:
    container = "aax" if fake_fail == "novoucher" else "aaxc"
    suffix = "aaxc" if container == "aaxc" else "aax"
    raw = partial / f"{asin}-fake.{suffix}"

    step = max(1, FAKE_CONTENT_SIZE // _FAKE_TICKS)
    written = 0
    for tick in range(_FAKE_TICKS):
        written = min(FAKE_CONTENT_SIZE, written + step)
        with open(raw, "ab") as handle:
            handle.write(b"\0" * 256)
        emit("progress", stage="download", bytes=written, total=FAKE_CONTENT_SIZE)
        time.sleep(_FAKE_TICK_SECONDS)
        if fake_fail == "network" and tick >= 1:
            raise PipelineError(
                protocol.ErrorCode.NETWORK,
                "simulated network failure",
                hint="retry the download",
            )

    _fake_generate_raw(raw, children)
    (partial / f"{asin}-chapters.json").write_text(
        json.dumps(FAKE_CHAPTERS_SPEC, indent=2), encoding="utf-8"
    )
    return RawDownload(
        raw_path=raw,
        container=container,
        chapters=parse_chapters(FAKE_CHAPTERS_SPEC),
        key_args=[],
    )


def _fake_generate_raw(raw_path: Path, children: ChildTracker) -> None:
    """Write a short sine m4b carrying ``FAKE_RAW_CHAPTERS`` embedded chapters."""
    chapter_file = raw_path.parent / "fake-raw-chapters.txt"
    step = FAKE_AUDIO_MS // FAKE_RAW_CHAPTERS
    source_chapters = [
        Chapter(title=f"Source {index + 1}", start_ms=index * step, length_ms=step)
        for index in range(FAKE_RAW_CHAPTERS)
    ]
    chapter_file.write_text(build_ffmetadata(source_chapters), encoding="utf-8")
    argv = [
        _tool("ffmpeg"),
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=300:duration={FAKE_AUDIO_MS / 1000}",
        "-i",
        str(chapter_file),
        "-map",
        "0:a",
        "-map_metadata",
        "1",
        "-map_chapters",
        "1",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-f",
        "ipod",
        str(raw_path),
    ]
    _run(argv, children, protocol.ErrorCode.CONVERT, hint="ffmpeg is required in fake mode")


# --- real mode ---------------------------------------------------------------
def _audible_cli(paths: Paths) -> str:
    candidate = Path(paths.venv_python).with_name("audible")
    if candidate.is_file():
        return str(candidate)
    found = shutil.which("audible")
    if found:
        return found
    raise PipelineError(
        protocol.ErrorCode.NO_VENV,
        "audible-cli is not installed",
        hint="run: omarchy-audible setup",
    )


def _audible_env(paths: Paths) -> dict[str, str]:
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["AUDIBLE_CONFIG_DIR"] = str(paths.config_dir)
    return env


def _real_content_metadata(asin: str, paths: Paths) -> dict[str, Any]:
    try:
        import audible
    except ImportError as exc:
        raise PipelineError(
            protocol.ErrorCode.NO_VENV,
            "the audible library is not installed",
            hint="run: omarchy-audible setup",
        ) from exc
    if not paths.auth_file.is_file():
        raise PipelineError(
            protocol.ErrorCode.AUTH_FAILED,
            "no Audible login",
            hint="sign in from the drawer",
        )
    try:
        auth = audible.Authenticator.from_file(paths.auth_file)
        with audible.Client(auth=auth) as client:
            return client.get(
                f"1.0/content/{asin}/metadata",
                response_groups="content_reference,chapter_info",
                quality="High",
                chapter_titles_type="Flat",
            )
    except Exception as exc:
        log(f"content metadata request failed: {exc!r}")
        raise PipelineError(
            protocol.ErrorCode.NETWORK,
            "could not read the book's metadata",
            hint="check the network and retry",
        ) from exc


def _content_size(metadata: dict[str, Any]) -> int:
    """The download size from ``1.0/content/{asin}/metadata``, or 0 if unknown.

    Audible returns it as ``content_metadata.content_reference
    .content_size_in_bytes`` (checked against the real account; the S4 spike
    read the same field). The other two places are fallbacks for other
    response shapes. It feeds the free-space pre-flight and the ``total`` of
    every ``get`` progress event, so 0 disables both.
    """
    content = metadata.get("content_metadata") or {}
    for source in (
        content.get("content_reference") or {},
        content,
        content.get("content_url") or {},
    ):
        size = source.get("content_size_in_bytes") if isinstance(source, dict) else None
        if isinstance(size, int) and not isinstance(size, bool) and size > 0:
            return size
    return 0  # unknown: let the download proceed rather than block it


def _metadata_duration_ms(metadata: dict[str, Any]) -> int | None:
    content = metadata.get("content_metadata") or {}
    info = content.get("chapter_info") or {}
    value = info.get("runtime_length_ms")
    if isinstance(value, (int, float)) and value > 0:
        return round(value)
    return None


def _metadata_acr(metadata: dict[str, Any]) -> str | None:
    content = metadata.get("content_metadata") or {}
    reference = content.get("content_reference") or {}
    acr = reference.get("acr")
    return acr if isinstance(acr, str) and acr else None


def _audible_download(
    cli: str,
    env: dict[str, str],
    partial: Path,
    asin: str,
    fmt: str,
    emit: _Emit,
    children: ChildTracker,
    total: int,
) -> None:
    argv = [
        cli,
        "download",
        "-a",
        asin,
        f"--{fmt}",
        "--chapter",
        "--chapter-type",
        "flat",
        "-q",
        "best",
        "-y",
        "--no-progress",
        "-f",
        "asin_only",
        "-o",
        str(partial),
    ]
    proc = children.spawn(argv, env=env, quiet=True)
    while proc.poll() is None:
        emit("progress", stage="download", bytes=dir_size(partial), total=total)
        time.sleep(_REAL_POLL_SECONDS)
    if proc.returncode != 0:
        raise PipelineError(
            protocol.ErrorCode.NETWORK,
            f"audible download ({fmt}) failed",
            hint="check the network and retry",
        )


def _find_raw(partial: Path, container: str) -> Path | None:
    candidates = sorted(partial.glob(f"*{'aaxc' if container == 'aaxc' else 'aax'}"))
    if container == "aaxc":
        candidates += sorted(partial.glob("*.mp3"))
    return candidates[0] if candidates else None


def _find_voucher(partial: Path) -> Path | None:
    vouchers = sorted(partial.glob("*.voucher"))
    return vouchers[0] if vouchers else None


def _read_chapters(partial: Path, asin: str) -> list[Chapter]:
    candidates = sorted(partial.glob("*-chapters.json"))
    if not candidates:
        return []  # fall back to the chapters embedded in the audio file
    try:
        data = json.loads(candidates[0].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return parse_chapters(data)


def _voucher_key_args(voucher_path: Path) -> list[str]:
    try:
        data = json.loads(voucher_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PipelineError(
            protocol.ErrorCode.NO_VOUCHER, "the voucher could not be read"
        ) from exc
    response = (data.get("content_license") or {}).get("license_response") or {}
    key = response.get("key")
    iv = response.get("iv")
    if not key or not iv:
        raise PipelineError(
            protocol.ErrorCode.NO_VOUCHER, "the aaxc voucher has no key/iv"
        )
    return ["-audible_key", str(key), "-audible_iv", str(iv)]


def _activation_bytes(paths: Paths, cli: str, env: dict[str, str]) -> str:
    try:
        value = paths.activation_bytes_file.read_text(encoding="utf-8").strip()
    except OSError:
        value = ""
    if value:
        return value
    result = subprocess.run(
        [cli, "activation-bytes"], env=env, capture_output=True, text=True, check=False
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if result.returncode != 0 or not lines:
        raise PipelineError(
            protocol.ErrorCode.DECRYPT,
            "could not read the activation bytes",
            hint="run: omarchy-audible login-import-cli",
        )
    return lines[-1]


def _real_fetch(
    asin: str,
    partial: Path,
    paths: Paths,
    emit: _Emit,
    children: ChildTracker,
    total: int,
) -> RawDownload:
    cli = _audible_cli(paths)
    env = _audible_env(paths)
    try:
        _audible_download(cli, env, partial, asin, "aaxc", emit, children, total)
        raw_path = _find_raw(partial, "aaxc")
        voucher = _find_voucher(partial)
        if raw_path is None or voucher is None:
            raise PipelineError(
                protocol.ErrorCode.NO_VOUCHER, "the aaxc download offered no voucher"
            )
        return RawDownload(
            raw_path=raw_path,
            container="aaxc",
            chapters=_read_chapters(partial, asin),
            key_args=_voucher_key_args(voucher),
        )
    except PipelineError as exc:
        # aaxc first, aax fallback (G0 decision): an aaxc failure, including a
        # book that offers no voucher, is retried as aax.
        log(f"aaxc download failed ({exc.code}); retrying as aax")
    _rmtree(partial)
    partial.mkdir(parents=True, exist_ok=True)
    _audible_download(cli, env, partial, asin, "aax", emit, children, total)
    raw_path = _find_raw(partial, "aax")
    if raw_path is None:
        raise PipelineError(
            protocol.ErrorCode.NETWORK,
            "the aax download produced no audio file",
            hint="retry the download",
        )
    return RawDownload(
        raw_path=raw_path,
        container="aax",
        chapters=_read_chapters(partial, asin),
        key_args=["-activation_bytes", _activation_bytes(paths, cli, env)],
    )


# --- meta.json ---------------------------------------------------------------
def _catalog_entry(paths: Paths, asin: str) -> dict[str, Any]:
    try:
        data = json.loads(paths.catalog_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    for book in data.get("books", []):
        if isinstance(book, dict) and book.get("asin") == asin:
            return book
    return {}


def _meta_payload(
    asin: str,
    paths: Paths,
    raw: RawDownload,
    final: Path,
    duration_ms: int | None,
    acr: str | None,
) -> dict[str, Any]:
    entry = _catalog_entry(paths, asin)
    return {
        "asin": asin,
        "title": entry.get("title"),
        "authors": entry.get("authors") or [],
        "duration_ms": duration_ms,
        "size": final.stat().st_size,
        "downloaded_at": iso_now(),
        "acr": acr,
        "container": raw.container,
        "chapter_count": len(raw.chapters),
    }


# --- pipeline ----------------------------------------------------------------
def run_get(
    asin: str,
    paths: Paths,
    *,
    fake: bool,
    fake_fail: str | None = None,
    emit: _Emit = protocol.emit,
    children: ChildTracker | None = None,
) -> Path:
    """Download and convert one book; return the path to ``book.m4b``.

    ``.partial/`` and ``book.m4b.tmp`` are removed on success and on every
    failure path, and ``book.m4b`` only ever appears through an atomic rename.
    """
    tracker = children if children is not None else ChildTracker()
    # ``cmd_get`` validates before calling; guard direct callers too, so an
    # unvalidated ASIN can never reach the ``book_dir``/``rmtree`` below.
    validate_asin(paths.books_dir, asin)
    target_dir = book_dir(paths.books_dir, asin)
    partial = target_dir / PARTIAL_DIRNAME
    tmp = target_dir / _M4B_TMP
    final = target_dir / BOOK_FILENAME

    if fake:
        content_size = _fake_content_size(fake_fail, paths.books_dir)
        duration_ms: int | None = FAKE_AUDIO_MS
        acr: str | None = FAKE_ACR
    else:
        metadata = _real_content_metadata(asin, paths)
        content_size = _content_size(metadata)
        duration_ms = _metadata_duration_ms(metadata)
        acr = _metadata_acr(metadata)

    check_free_space(_free_bytes(target_dir), content_size)

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        _rmtree(partial)
        _unlink(tmp)
        partial.mkdir(parents=True, exist_ok=True)

        if fake:
            raw = _fake_fetch(asin, partial, emit, tracker, fake_fail)
        else:
            raw = _real_fetch(asin, partial, paths, emit, tracker, content_size)

        emit("progress", stage="convert", bytes=0, total=content_size)
        if fake and fake_fail == "decrypt":
            tmp.write_bytes(b"not a real book\n")
            raise PipelineError(
                protocol.ErrorCode.DECRYPT,
                "simulated decrypt failure",
                hint="retry the download",
            )
        _decrypt(raw, tmp, tracker)
        _verify(tmp, raw.chapters, duration_ms)
        fsutil.atomic_replace(tmp, final)
        write_meta(target_dir, _meta_payload(asin, paths, raw, final, duration_ms, acr))
    finally:
        tracker.terminate_all()
        _rmtree(partial)
        _unlink(tmp)
    return final

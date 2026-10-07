"""``get``: download the locked original and keep its key material (4.3, D7).

Pipeline, in order:

1. Pre-flight: require 1.1x the content size in free space (B11: there is no
   decrypt pass, so the peak is the book itself, not twice it). A re-download
   may count an abandoned ``.partial/``, which is removed before the fetch;
   the old copy stays on disk until the commit, so its bytes are *not* free
   during the fetch and do not count (F34, B14). The peak for a re-download is
   therefore the old copy plus 1.1x the new one.
2. ``<booksDir>/<asin>/.partial/`` is created and the whole book is built
   there: the raw download, a ``0600`` ``key.json``, ``chapters.txt`` and the
   audio renamed to its final ``book.aaxc``/``book.aax`` name.
3. Download with audible-cli, aaxc first and aax only if no voucher is offered
   (F8). Its stderr is staged as ``.partial/audible.stderr`` so a real failure
   has a reason to log, and that reason is the scrubbed last line only (F9). A
   byte count is reported by polling the partial directory.
4. No decrypt (D7). The book directory ends up with the original audio moved
   out of ``.partial/`` unchanged as ``book.aaxc``/``book.aax``, a ``0600``
   ``key.json``, ``chapters.txt`` (ffmetadata built from Audible's
   ``chapters.json`` when it is there) and ``meta.json``.
5. A ``ffprobe`` duration check with **no key argument**, run inside
   ``.partial/``: the header opens without one (S7). An aax whose duration
   cannot be read without activation bytes is skipped and logged.
6. Only once everything in ``.partial/`` checks out, the commit: the previous
   copy's audio, ``key.json``, ``chapters.txt`` and ``meta.json`` are moved
   aside, the new files are moved in (the audio last, so "local" flips at one
   moment) and ``meta.json`` is written. SIGTERM is blocked for the whole
   commit, so a cancel that lands in it is delivered only once the book is
   whole (F35). An old ``book.m4b`` therefore never sits beside a locked file
   (B14).
7. On any failure or SIGTERM, ``.partial/`` and every temp file are removed and
   the book directory is left exactly as it was: nothing new reaches it before
   the commit, and a failure inside the commit puts the old files back, so a
   failed or cancelled re-download never costs the user a playable book
   (ARCHITECTURE 4.3, 4.8).

No ``ffmpeg`` or ``ffprobe`` argv here ever contains a key, iv or activation
bytes: the key is written to ``key.json`` and only read again by ``play-info``.

The ``audible`` library is imported lazily, inside real-mode code paths only,
so the test suite runs without it installed.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import signal
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from . import fakestate, fsutil, protocol
from .chapters import Chapter, build_ffmetadata, parse_chapters
from .errors import Cancelled, PipelineError
from .library import (
    AUDIO_FILENAMES,
    CHAPTERS_FILENAME,
    KEY_FILENAME,
    META_FILENAME,
    PARTIAL_DIRNAME,
    book_dir,
    dir_size,
    iso_now,
    validate_asin,
    write_meta,
)
from .log import log
from .paths import Paths

FREE_SPACE_FACTOR = 1.1

# --- fake mode (ARCHITECTURE 4.2) --------------------------------------------
FAKE_FAIL_MODES = ("disk", "network", "decrypt", "novoucher")
FAKE_RAW_CHAPTERS = 3
# The fake sine's shortest length; ``--fake-chapters`` grows it by a second per
# chapter so every chapter has room (B11).
FAKE_AUDIO_MS = 6000
FAKE_CHAPTERS_DEFAULT = 5
FAKE_CHAPTERS_MAX = 500
FAKE_CHAPTERS_ENV = "OMARCHY_AUDIBLE_FAKE_CHAPTERS"
FAKE_CONTENT_SIZE = 2_000_000
FAKE_ACR = "FAKEACR0"
# Obviously fake key material for the fake tree's ``key.json``.
FAKE_VOUCHER_KEY = "00112233445566778899aabbccddeeff"
FAKE_VOUCHER_IV = "aabbccdd00112233"
_FAKE_TICKS = 10
_FAKE_TICK_SECONDS = 0.08

_REAL_POLL_SECONDS = 0.5
# A temp name inside ``.partial/``: the audio is moved here, checked, then
# renamed onto ``book.<ext>`` there in one step.
_AUDIO_TMP = "book.audio.tmp"
# audible-cli's stderr is staged here, inside ``.partial/``, so its reason for a
# failure has somewhere to live that goes away with the rest of the staging
# directory (F9).
AUDIBLE_STDERR = "audible.stderr"
# The commit moves the previous copy in here before installing the new one, so
# a failure partway through can put the old files back (F35).
_OLD_DIRNAME = "old"
_Emit = Callable[..., None]


def fake_audio_ms(chapter_count: int) -> int:
    """The fake sine's length: at least 6 s, one second per chapter."""
    return max(FAKE_AUDIO_MS, max(1, chapter_count) * 1000)


def fake_chapters_spec(chapter_count: int) -> dict[str, Any]:
    """An Audible-shaped ``chapters.json`` with ``chapter_count`` chapters.

    Invented titles only, evenly spaced across the fake sine.
    """
    count = max(1, chapter_count)
    total = fake_audio_ms(count)
    step = max(1, total // count)
    chapters = []
    for index in range(count):
        start = index * step
        length = step if index < count - 1 else max(1, total - start)
        chapters.append(
            {
                "title": f"Chapter {index + 1}",
                "start_offset_ms": start,
                "length_ms": length,
            }
        )
    return {
        "content_metadata": {
            "chapter_info": {
                "chapter_titles_type": "Flat",
                "runtime_length_ms": total,
                "chapters": chapters,
            }
        }
    }


def parse_fake_chapters(text: str | None) -> int | None:
    """The ``--fake-chapters`` value as an int, or ``None`` when unset.

    Raises ``invalid_args`` for anything outside 1-500.
    """
    if text is None:
        return None
    try:
        value = int(text)
    except (TypeError, ValueError):
        value = -1
    if not 1 <= value <= FAKE_CHAPTERS_MAX:
        raise PipelineError(
            protocol.ErrorCode.INVALID_ARGS,
            f"invalid --fake-chapters: {text!r}",
            hint=f"choose a whole number from 1 to {FAKE_CHAPTERS_MAX}",
        )
    return value


def _resolve_chapter_count(override: int | None) -> int:
    """The fake book's chapter count: the flag, else the env var, else 5."""
    if override is not None:
        return override
    raw = os.environ.get(FAKE_CHAPTERS_ENV)
    if raw is None:
        return FAKE_CHAPTERS_DEFAULT
    try:
        value = int(str(raw).strip())
    except ValueError:
        return FAKE_CHAPTERS_DEFAULT
    return value if 1 <= value <= FAKE_CHAPTERS_MAX else FAKE_CHAPTERS_DEFAULT


@dataclass
class RawDownload:
    """The original audio plus everything needed to finish the book."""

    raw_path: Path
    container: str  # "aaxc" | "aax"
    chapters: list[Chapter]
    voucher_key: str | None = None
    voucher_iv: str | None = None


class ChildTracker:
    """Owns every subprocess spawned by one ``get`` so SIGTERM can stop them."""

    def __init__(self) -> None:
        self._children: list[subprocess.Popen[bytes]] = []

    def spawn(
        self,
        argv: list[str],
        *,
        env: dict[str, str] | None = None,
        quiet: bool = False,
        stderr: int | BinaryIO | None = None,
    ) -> subprocess.Popen[bytes]:
        if stderr is None:
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


def _clear_local(directory: Path, aside: Path) -> list[str]:
    """Move a previous copy's audio, key, chapters and meta into ``aside``.

    Called only at the commit step of a download, once everything in
    ``.partial/`` has been built and checked, so a directory never holds a
    ``.m4b`` beside a locked file (B11, B14). The files are renamed, not
    deleted, so :func:`_restore_local` can put the previous copy back byte for
    byte when the commit fails partway; ``aside`` lives inside ``.partial/``,
    so it goes away with the rest of the staging directory (F35).

    Returns the names that were moved.
    """
    moved: list[str] = []
    for name in (*AUDIO_FILENAMES, KEY_FILENAME, CHAPTERS_FILENAME, META_FILENAME):
        source = directory / name
        if source.is_file():
            os.replace(source, aside / name)
            moved.append(name)
    return moved


def _restore_local(directory: Path, aside: Path, moved: Iterable[str]) -> None:
    """Put back exactly what :func:`_clear_local` moved aside (F35).

    Anything the failed commit installed is removed first, then the previous
    files are renamed back, so the directory is left as it was: same files,
    sizes, mtimes and modes (B14).
    """
    for name in (*AUDIO_FILENAMES, KEY_FILENAME, CHAPTERS_FILENAME, META_FILENAME):
        if name not in moved:
            _unlink(directory / name)
    for name in moved:
        os.replace(aside / name, directory / name)


def _reclaimable_bytes(partial: Path) -> int:
    """The bytes the pre-flight may count as free: an abandoned ``.partial/``.

    ``.partial/`` is removed before the fetch, so its bytes are genuinely
    reclaimable by the download about to start. The old copy's audio is not:
    since B14 it stays on disk until the commit, which runs after the whole new
    download has been staged, so those bytes are not free while the fetch runs
    (F34).
    """
    return dir_size(partial) if partial.is_dir() else 0


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
    """The audio duration in ms, or ``None`` when ffprobe cannot read it.

    No key argument is ever passed: S7 showed the header opens without one.
    """
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


def _verify_duration(
    path: Path, container: str, expected_duration_ms: int | None
) -> None:
    """Check the downloaded duration against the catalog, with no key."""
    if not expected_duration_ms:
        return
    actual = probe_duration_ms(path)
    if actual is None:
        if container == "aax":
            # A legacy aax needs activation bytes for ffprobe to read its
            # duration; the file is otherwise fine, so skip the check (B11).
            log(
                "ffprobe could not read the aax duration without activation bytes; skipped"
            )
        return
    if abs(actual - expected_duration_ms) > max(1000, expected_duration_ms * 0.01):
        raise PipelineError(
            protocol.ErrorCode.CONVERT,
            "the downloaded duration differs from the catalog",
            hint="retry the download",
        )


def _key_payload(raw: RawDownload) -> dict[str, Any]:
    """The ``key.json`` content: aaxc key/iv, or an aax reference (D7)."""
    if raw.container == "aaxc":
        if not raw.voucher_key or not raw.voucher_iv:
            raise PipelineError(
                protocol.ErrorCode.DECRYPT,
                "the aaxc voucher has no key/iv",
                hint="retry the download",
            )
        return {"format": "aaxc", "key": raw.voucher_key, "iv": raw.voucher_iv}
    # An aax book carries no key here: ``key.json`` only records the format and
    # ``play-info`` reads the account's activation bytes at play time.
    return {"format": "aax"}


# --- fake mode ---------------------------------------------------------------
def _fake_content_size(fake_fail: str | None, books_dir: Path) -> int:
    if fake_fail == "disk":
        # Anything above this cannot fit under the 1.1x rule.
        return _free_bytes(books_dir)
    return FAKE_CONTENT_SIZE


def _fake_fetch(
    asin: str,
    partial: Path,
    emit: _Emit,
    children: ChildTracker,
    fake_fail: str | None,
    chapter_count: int,
) -> RawDownload:
    container = "aax" if fake_fail == "novoucher" else "aaxc"
    raw = partial / f"{asin}-fake.{container}"

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

    spec = fake_chapters_spec(chapter_count)
    _fake_generate_raw(raw, children, fake_audio_ms(chapter_count))
    (partial / f"{asin}-chapters.json").write_text(
        json.dumps(spec, indent=2), encoding="utf-8"
    )
    # ``decrypt`` simulates a voucher that carries no key/iv.
    broken = fake_fail == "decrypt"
    return RawDownload(
        raw_path=raw,
        container=container,
        chapters=parse_chapters(spec),
        voucher_key=None if broken else FAKE_VOUCHER_KEY,
        voucher_iv=None if broken else FAKE_VOUCHER_IV,
    )


def _fake_generate_raw(raw_path: Path, children: ChildTracker, audio_ms: int) -> None:
    """Write the fake sine, still carrying ``FAKE_RAW_CHAPTERS`` embedded ones.

    The book is served as ``book.aaxc`` (an ordinary unencrypted MP4 under that
    name) or ``book.aax``; the embedded chapters differ from ``chapters.txt``
    so a passing chapter check proves the external list was used.
    """
    chapter_file = raw_path.parent / "fake-raw-chapters.txt"
    step = max(1, audio_ms // FAKE_RAW_CHAPTERS)
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
        f"sine=frequency=300:duration={audio_ms / 1000}",
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
    _run(
        argv,
        children,
        protocol.ErrorCode.CONVERT,
        hint="ffmpeg is required in fake mode",
    )


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
        # The exception type only: a repr could carry the request URL, and the
        # message could echo credentials back (F4).
        log(f"content metadata request failed: {type(exc).__name__}")
        raise PipelineError(
            protocol.ErrorCode.NETWORK,
            "could not read the book's metadata",
            hint="check the network and retry",
        ) from exc


# Larger than any audiobook; a bigger value is treated as unknown rather than
# fed to the free-space arithmetic.
_MAX_CONTENT_SIZE = 1 << 40


def _content_size(metadata: Any) -> int:
    """The aaxc download size from ``1.0/content/{asin}/metadata``, or 0.

    Audible returns it as ``content_metadata.content_reference
    .content_size_in_bytes`` (checked against the real account; the S4 spike
    read the same field). The other two places are fallbacks for other
    response shapes. It feeds the free-space pre-flight and the ``total`` of
    the aaxc download's progress events. 0 means unknown, which skips the
    pre-flight and lets the download proceed. Never raises.
    """
    content = metadata.get("content_metadata") if isinstance(metadata, dict) else None
    if not isinstance(content, dict):
        return 0
    for source in (
        content.get("content_reference"),
        content,
        content.get("content_url"),
    ):
        size = source.get("content_size_in_bytes") if isinstance(source, dict) else None
        if (
            isinstance(size, int)
            and not isinstance(size, bool)
            and 0 < size <= _MAX_CONTENT_SIZE
        ):
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


def _last_stderr_line(path: Path) -> str:
    """The last non-empty line of a staged stderr file, or ``""`` (F9)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


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
    # audible-cli's stderr is the only record of *why* a download failed, so it
    # is staged as ``.partial/audible.stderr``; only its scrubbed last line is
    # logged. It disappears with ``.partial/`` (F9).
    stderr_path = partial / AUDIBLE_STDERR
    with open(stderr_path, "wb") as handle:
        proc = children.spawn(argv, env=env, stderr=handle)
        while proc.poll() is None:
            emit("progress", stage="download", bytes=dir_size(partial), total=total)
            time.sleep(_REAL_POLL_SECONDS)
    if proc.returncode != 0:
        detail = _last_stderr_line(stderr_path)
        log(f"audible download ({fmt}) failed: {detail}")
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
        return []
    try:
        data = json.loads(candidates[0].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return parse_chapters(data)


def _voucher_key_iv(voucher_path: Path) -> tuple[str, str]:
    """The aaxc voucher's key and iv (SPIKE-RESULTS S2). Never logged."""
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
    return str(key), str(iv)


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
        key, iv = _voucher_key_iv(voucher)
        return RawDownload(
            raw_path=raw_path,
            container="aaxc",
            chapters=_read_chapters(partial, asin),
            voucher_key=key,
            voucher_iv=iv,
        )
    except PipelineError as exc:
        # aaxc first, aax fallback (G0 decision). Only a book that offers no
        # voucher is retried as aax: any other aaxc failure (a network error,
        # say) is the real problem and is reported as it is (F8).
        if exc.code != protocol.ErrorCode.NO_VOUCHER:
            raise
        log("the aaxc download offered no voucher; retrying as aax")
    _rmtree(partial)
    partial.mkdir(parents=True, exist_ok=True)
    # The metadata size is the aaxc file's; the aax file's size is not known
    # in advance, so its progress events carry no total (the UI then shows no
    # percent rather than a wrong one).
    _audible_download(cli, env, partial, asin, "aax", emit, children, 0)
    raw_path = _find_raw(partial, "aax")
    if raw_path is None:
        raise PipelineError(
            protocol.ErrorCode.NETWORK,
            "the aax download produced no audio file",
            hint="retry the download",
        )
    # No activation bytes are read here: the aax path stores a reference only
    # (D7), and nothing at download time needs them.
    return RawDownload(
        raw_path=raw_path, container="aax", chapters=_read_chapters(partial, asin)
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
        "format": raw.container,
        "locked": True,
        "chapter_count": len(raw.chapters),
    }


# --- pipeline ----------------------------------------------------------------
def run_get(
    asin: str,
    paths: Paths,
    *,
    fake: bool,
    fake_fail: str | None = None,
    fake_chapters: int | None = None,
    emit: _Emit = protocol.emit,
    children: ChildTracker | None = None,
) -> Path:
    """Download one book as-is; return the path to ``book.aaxc``/``book.aax``.

    The whole book is built in ``.partial/`` and only moved into the book
    directory once it has been verified there, so a failure or a cancel leaves
    a previous copy untouched. ``.partial/`` and every temp file are removed on
    success and on every failure path, and the final audio only ever appears
    through an atomic rename. ``fake_chapters`` (and
    ``OMARCHY_AUDIBLE_FAKE_CHAPTERS``) only affects fake mode.
    """
    tracker = children if children is not None else ChildTracker()
    # ``cmd_get`` validates before calling; guard direct callers too, so an
    # unvalidated ASIN can never reach the ``book_dir``/rmtree below.
    validate_asin(paths.books_dir, asin)
    target_dir = book_dir(paths.books_dir, asin)
    partial = target_dir / PARTIAL_DIRNAME

    if fake:
        chapter_count = _resolve_chapter_count(fake_chapters)
        content_size = _fake_content_size(fake_fail, paths.books_dir)
        duration_ms: int | None = fake_audio_ms(chapter_count)
        acr: str | None = FAKE_ACR
    else:
        chapter_count = FAKE_CHAPTERS_DEFAULT
        metadata = _real_content_metadata(asin, paths)
        content_size = _content_size(metadata)
        duration_ms = _metadata_duration_ms(metadata)
        acr = _metadata_acr(metadata)

    # The free-space pre-flight: 1.1x the new audio must fit. A re-download may
    # also count an abandoned ``.partial/``, which is removed before the fetch;
    # the old copy's bytes are not free until the commit, after the fetch, so
    # they do not count (F34, B14).
    check_free_space(
        _free_bytes(target_dir) + _reclaimable_bytes(partial), content_size
    )

    final: Path | None = None
    committed = False
    try:
        # The book directory is untouched from here until the commit below: a
        # failure at any earlier step leaves the previous copy exactly as it was.
        target_dir.mkdir(parents=True, exist_ok=True)
        _rmtree(partial)
        partial.mkdir(parents=True, exist_ok=True)

        if fake:
            raw = _fake_fetch(asin, partial, emit, tracker, fake_fail, chapter_count)
        else:
            raw = _real_fetch(asin, partial, paths, emit, tracker, content_size)

        # Stage the whole book in ``.partial/``: key.json (0600) and
        # chapters.txt first, then the audio, then the sanity check.
        staged_key = partial / KEY_FILENAME
        fsutil.write_private_json(staged_key, _key_payload(raw))
        staged_chapters = partial / CHAPTERS_FILENAME
        if raw.chapters:
            staged_chapters.write_text(build_ffmetadata(raw.chapters), encoding="utf-8")
        else:
            _unlink(staged_chapters)

        # A temp name in the same directory, then one atomic rename onto the
        # final audio name inside ``.partial/`` (ARCHITECTURE 4.3). The duration
        # check runs with no key argument, before the final name exists.
        staged_tmp = partial / _AUDIO_TMP
        os.replace(raw.raw_path, staged_tmp)
        _verify_duration(staged_tmp, raw.container, duration_ms)
        staged_audio = partial / f"book.{raw.container}"
        fsutil.atomic_replace(staged_tmp, staged_audio)

        # Everything checked out: the commit. SIGTERM is blocked for the whole
        # window, so a cancel that lands in it stays pending and is delivered
        # at the unblock, once the book is whole (F35). The previous copy is
        # moved aside rather than deleted, so a failure inside the commit puts
        # it back byte for byte (B14).
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
        try:
            aside = partial / _OLD_DIRNAME
            aside.mkdir(parents=True, exist_ok=True)
            moved = _clear_local(target_dir, aside)
            try:
                os.replace(staged_key, target_dir / KEY_FILENAME)
                if raw.chapters:
                    os.replace(staged_chapters, target_dir / CHAPTERS_FILENAME)
                final = target_dir / f"book.{raw.container}"
                os.replace(staged_audio, final)
                if fake:
                    fakestate.ensure_activation_bytes(paths)
                write_meta(
                    target_dir,
                    _meta_payload(asin, paths, raw, final, duration_ms, acr),
                )
                committed = True
            except BaseException:
                _restore_local(target_dir, aside, moved)
                raise
        finally:
            signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM})
    except Cancelled:
        if not committed:
            raise
        # The SIGTERM was pending across the commit and was delivered at the
        # unblock above. The new book is already whole and local, so the run is
        # a success, not a cancel (F35).
    finally:
        tracker.terminate_all()
        _rmtree(partial)
    assert final is not None
    return final

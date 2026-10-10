"""B11 — the ``get`` pipeline keeps the locked original (ARCHITECTURE 4.3, D7).

Covers the on-disk layout (``book.aaxc``/``book.aax`` + a ``0600`` ``key.json``
+ ``chapters.txt`` + ``meta.json``, and no decrypted copy), the atomic rename,
cleanup of ``.partial/`` and the temp file on success and on every failure mode,
the 1.1x free-space pre-flight, the aax fallback when no voucher is offered, and
that **no subprocess argv** ever carries key material.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from omarchy_audible import download as dl
from omarchy_audible import fakestate
from omarchy_audible.errors import PipelineError

ASIN = "B00FAKE01"

# The fake ``chapters.json`` titles, by order. Invented titles only.
EXPECTED_TITLES = [f"Chapter {index + 1}" for index in range(dl.FAKE_CHAPTERS_DEFAULT)]


def _meta(paths, asin: str = ASIN) -> dict:
    return json.loads(
        (paths.books_dir / asin / "meta.json").read_text(encoding="utf-8")
    )


def _layout(paths, asin: str = ASIN) -> list[str]:
    return sorted(p.name for p in (paths.books_dir / asin).iterdir())


def _fake_chapter_titles(count: int) -> list[str]:
    spec = dl.fake_chapters_spec(count)
    chapters = spec["content_metadata"]["chapter_info"]["chapters"]
    return [chapter["title"] for chapter in chapters]


def test_fake_chapters_json_has_the_requested_count_and_differs_from_the_raw_file():
    chapters = dl.fake_chapters_spec(dl.FAKE_CHAPTERS_DEFAULT)
    nodes = chapters["content_metadata"]["chapter_info"]["chapters"]
    assert [node["title"] for node in nodes] == EXPECTED_TITLES
    assert len(nodes) == dl.FAKE_CHAPTERS_DEFAULT
    assert dl.FAKE_RAW_CHAPTERS == 3


def test_fake_audio_grows_with_the_chapter_count():
    assert dl.fake_audio_ms(5) == dl.FAKE_AUDIO_MS
    assert dl.fake_audio_ms(120) == 120_000


def test_get_success_keeps_the_locked_file_and_cleans_up(
    run_cli, validate_stream, ffmpeg_bin, fake_paths
):
    result = run_cli("get", ASIN, fake=True)
    assert result.returncode == 0, result.stderr
    parsed = validate_stream(result, expect_last="done")

    book_dir = fake_paths.books_dir / ASIN
    audio = book_dir / "book.aaxc"
    assert Path(parsed[-1]["path"]) == audio
    assert audio.is_file()

    # The locked layout, and nothing else: no .m4b, no .partial/, no temp file.
    assert _layout(fake_paths) == ["book.aaxc", "chapters.txt", "key.json", "meta.json"]
    assert not list(book_dir.glob("*.tmp"))
    assert not (book_dir / ".partial").exists()

    # A locked download has no convert stage.
    stages = [event["stage"] for event in parsed if event["type"] == "progress"]
    assert set(stages) == {"download"}

    key = json.loads((book_dir / "key.json").read_text(encoding="utf-8"))
    assert key == {
        "format": "aaxc",
        "key": dl.FAKE_VOUCHER_KEY,
        "iv": dl.FAKE_VOUCHER_IV,
    }
    # 0600 from creation: no group or other permission bit.
    assert stat.S_IMODE((book_dir / "key.json").stat().st_mode) == 0o600

    chapter_file = (book_dir / "chapters.txt").read_text(encoding="utf-8")
    assert chapter_file.count("[CHAPTER]") == len(EXPECTED_TITLES)
    assert "Chapter 1" in chapter_file

    meta = _meta(fake_paths)
    assert meta["acr"] == dl.FAKE_ACR
    assert meta["chapter_count"] == len(EXPECTED_TITLES)
    assert meta["format"] == "aaxc"
    assert meta["container"] == "aaxc"
    assert meta["locked"] is True
    assert meta["duration_ms"] == dl.FAKE_AUDIO_MS


def test_get_writes_a_tmp_file_then_atomically_renames(ffmpeg_bin, paths, monkeypatch):
    """The final audio only ever appears through the rename of the temp file."""
    from omarchy_audible import download

    renames: list[tuple[str, str]] = []

    def spy(src, dst):
        renames.append((Path(src).name, Path(dst).name))
        os.replace(src, dst)

    monkeypatch.setattr(download.fsutil, "atomic_replace", spy)
    final = download.run_get(ASIN, paths, fake=True, emit=lambda *a, **k: None)

    assert renames == [("book.audio.tmp", "book.aaxc")]
    assert final.is_file()
    assert sorted(p.name for p in final.parent.iterdir()) == [
        "book.aaxc",
        "chapters.txt",
        "key.json",
        "meta.json",
    ]
    assert not list(final.parent.glob("*.tmp"))


def test_get_redownload_replaces_an_old_m4b(ffmpeg_bin, fake_paths):
    """A directory holding an old ``book.m4b`` never keeps it beside a locked file."""
    from omarchy_audible import download

    book_dir = fake_paths.books_dir / ASIN
    book_dir.mkdir(parents=True)
    (book_dir / "book.m4b").write_bytes(b"old decrypted audio")
    (book_dir / "meta.json").write_text('{"asin": "B00FAKE01"}', encoding="utf-8")

    final = download.run_get(ASIN, fake_paths, fake=True, emit=lambda *a, **k: None)

    assert final.name == "book.aaxc"
    assert not (book_dir / "book.m4b").exists()
    assert _layout(fake_paths) == ["book.aaxc", "chapters.txt", "key.json", "meta.json"]


@pytest.mark.parametrize(
    "mode,code",
    [("network", "network"), ("decrypt", "decrypt")],
)
def test_get_failure_removes_everything_and_never_leaves_a_book(
    mode, code, run_cli, events, ffmpeg_bin, fake_paths
):
    result = run_cli("get", ASIN, "--fake-fail", mode, fake=True)
    assert result.returncode != 0
    last = events(result)[-1]
    assert last["type"] == "error"
    assert last["code"] == code

    book_dir = fake_paths.books_dir / ASIN
    for name in (
        "book.m4b",
        "book.aaxc",
        "book.aax",
        "key.json",
        "chapters.txt",
        ".partial",
    ):
        assert not (book_dir / name).exists(), name
    assert not list(book_dir.glob("*.tmp"))


def test_get_disk_failure_refuses_before_writing(
    run_cli, events, ffmpeg_bin, fake_paths
):
    result = run_cli("get", ASIN, "--fake-fail", "disk", fake=True)
    assert result.returncode != 0
    assert events(result)[-1]["code"] == "disk_space"
    assert not (fake_paths.books_dir / ASIN / "book.aaxc").exists()
    assert not list(fake_paths.books_dir.glob("*/.partial"))


def test_free_space_preflight_requires_1_1x():
    assert dl.FREE_SPACE_FACTOR == 1.1
    dl.check_free_space(1100, 1000)  # exactly 1.1x is enough
    with pytest.raises(PipelineError) as excinfo:
        dl.check_free_space(1099, 1000)  # one byte short
    assert excinfo.value.code == "disk_space"


@pytest.mark.parametrize(
    ("metadata", "size"),
    [
        # The shape the real account returns (G3 finding 4: total was 0).
        (
            {
                "content_metadata": {
                    "content_reference": {"content_size_in_bytes": 779090696}
                }
            },
            779090696,
        ),
        ({"content_metadata": {"content_size_in_bytes": 1234}}, 1234),
        ({"content_metadata": {"content_url": {"content_size_in_bytes": 99}}}, 99),
        (
            {
                "content_metadata": {
                    "content_reference": {"content_size_in_bytes": 5},
                    "content_size_in_bytes": 7,
                }
            },
            5,
        ),
        ({"content_metadata": {"content_reference": {"content_size_in_bytes": 0}}}, 0),
        (
            {
                "content_metadata": {
                    "content_reference": {"content_size_in_bytes": "779"}
                }
            },
            0,
        ),
        (
            {
                "content_metadata": {
                    "content_reference": {"content_size_in_bytes": True}
                }
            },
            0,
        ),
        ({"content_metadata": {"content_reference": None}}, 0),
        ({"content_metadata": {"content_reference": []}}, 0),
        ({}, 0),
        ({"content_metadata": "x"}, 0),
        ({"content_metadata": [1]}, 0),
        ({"content_metadata": True}, 0),
        ({"content_metadata": None}, 0),
        ("x", 0),
        (None, 0),
        ([], 0),
        (
            {
                "content_metadata": {
                    "content_reference": {"content_size_in_bytes": 10**400}
                }
            },
            0,
        ),
        ({"content_metadata": {"content_reference": {"content_size_in_bytes": -5}}}, 0),
        (
            {
                "content_metadata": {
                    "content_reference": {"content_size_in_bytes": 1.5e9}
                }
            },
            0,
        ),
    ],
)
def test_content_size_reads_content_reference(metadata, size):
    assert dl._content_size(metadata) == size


def test_aax_fallback_progress_has_no_aaxc_total(monkeypatch, tmp_path):
    """The aaxc size must not become the aax download's progress total."""
    totals: list[tuple[str, int]] = []

    def fake_download(cli, env, partial, asin, fmt, emit, children, total):
        totals.append((fmt, total))
        if fmt == "aax":
            (partial / f"{asin}.aax").write_bytes(b"x")

    monkeypatch.setattr(dl, "_wrapper_python", lambda: "audible")
    monkeypatch.setattr(dl, "_audible_env", lambda paths: {})
    monkeypatch.setattr(dl, "_audible_download", fake_download)
    monkeypatch.setattr(
        dl,
        "_find_raw",
        lambda partial, fmt: (partial / "x.aax") if fmt == "aax" else None,
    )
    monkeypatch.setattr(dl, "_find_voucher", lambda partial: None)
    monkeypatch.setattr(dl, "_read_chapters", lambda partial, asin: [])
    partial = tmp_path / ".partial"
    partial.mkdir()
    raw = dl._real_fetch(
        "B0FAKE0001", partial, None, lambda *a, **k: None, None, 779090696
    )
    assert raw.container == "aax"
    # The aax path stores a reference, not a copy of the activation bytes (D7).
    assert raw.voucher_key is None and raw.voucher_iv is None
    assert totals == [("aaxc", 779090696), ("aax", 0)]


def test_aax_fallback_only_happens_on_no_voucher(monkeypatch, tmp_path):
    """F8: any aaxc failure other than ``no_voucher`` is reported as it is."""
    attempts: list[str] = []

    def fake_download(cli, env, partial, asin, fmt, emit, children, total):
        attempts.append(fmt)
        raise PipelineError(dl.protocol.ErrorCode.NETWORK, "simulated network failure")

    monkeypatch.setattr(dl, "_wrapper_python", lambda: "audible")
    monkeypatch.setattr(dl, "_audible_env", lambda paths: {})
    monkeypatch.setattr(dl, "_audible_download", fake_download)
    partial = tmp_path / ".partial"
    partial.mkdir()

    with pytest.raises(PipelineError) as excinfo:
        dl._real_fetch(ASIN, partial, None, lambda *a, **k: None, None, 0)

    assert excinfo.value.code == "network"
    assert attempts == ["aaxc"], "aaxc was not retried as aax"


def _stderr_script(tmp_path: Path) -> Path:
    """A fake ``audible`` that writes two stderr lines and fails."""
    script = tmp_path / "fake-audible"
    script.write_text(
        "#!/bin/sh\n"
        "echo 'earlier line' >&2\n"
        "echo 'download failed: store_authentication_cookie=FAKE-COOKIE-VALUE' >&2\n"
        "exit 3\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def test_audible_cli_stderr_is_staged_inside_the_partial_dir(tmp_path):
    """F9: audible-cli's stderr lands in ``.partial/audible.stderr``."""
    partial = tmp_path / ".partial"
    partial.mkdir()
    script = _stderr_script(tmp_path)

    with pytest.raises(PipelineError) as excinfo:
        dl._audible_download(
            str(script),
            {},
            partial,
            ASIN,
            "aaxc",
            lambda *a, **k: None,
            dl.ChildTracker(),
            0,
        )

    assert excinfo.value.code == "network"
    staged = partial / dl.AUDIBLE_STDERR
    assert staged.is_file()
    assert "download failed" in staged.read_text(encoding="utf-8")


def test_only_the_scrubbed_last_stderr_line_is_logged(tmp_path, capsys):
    """F9: one log line, the last one, and scrubbed."""
    partial = tmp_path / ".partial"
    partial.mkdir()
    script = _stderr_script(tmp_path)

    with pytest.raises(PipelineError):
        dl._audible_download(
            str(script),
            {},
            partial,
            ASIN,
            "aaxc",
            lambda *a, **k: None,
            dl.ChildTracker(),
            0,
        )

    err = capsys.readouterr().err
    assert "download failed" in err
    assert "store_authentication_cookie" in err
    assert "FAKE-COOKIE-VALUE" not in err, "the cookie value reached the log"
    assert "earlier line" not in err, "more than the last line was logged"


def test_get_novoucher_stores_a_reference_only(run_cli, events, ffmpeg_bin, fake_paths):
    result = run_cli("get", ASIN, "--fake-fail", "novoucher", fake=True)
    assert result.returncode == 0, result.stderr
    assert events(result)[-1]["type"] == "done"

    book_dir = fake_paths.books_dir / ASIN
    assert (book_dir / "book.aax").is_file()
    assert not (book_dir / "book.aaxc").exists()
    assert json.loads((book_dir / "key.json").read_text(encoding="utf-8")) == {
        "format": "aax"
    }
    meta = _meta(fake_paths)
    assert meta["format"] == "aax"
    assert meta["locked"] is True
    chapters = (book_dir / "chapters.txt").read_text(encoding="utf-8")
    assert chapters.count("[CHAPTER]") == len(EXPECTED_TITLES)


# --- long chapter lists (B11) -----------------------------------------------


def test_fake_chapters_flag_and_env(run_cli, events, ffmpeg_bin, fake_paths):
    result = run_cli("get", ASIN, "--fake-chapters", "120", fake=True)
    assert result.returncode == 0, result.stderr
    assert events(result)[-1]["type"] == "done"

    book_dir = fake_paths.books_dir / ASIN
    chapters = (book_dir / "chapters.txt").read_text(encoding="utf-8")
    assert chapters.count("[CHAPTER]") == 120
    assert "Chapter 120" in chapters
    assert _meta(fake_paths)["duration_ms"] == 120_000


def test_fake_chapters_env_var_is_honoured(
    run_cli, events, ffmpeg_bin, fake_paths, env
):
    result = run_cli(
        "get", ASIN, fake=True, extra_env={"OMARCHY_AUDIBLE_FAKE_CHAPTERS": "7"}
    )
    assert result.returncode == 0, result.stderr
    chapters = (fake_paths.books_dir / ASIN / "chapters.txt").read_text(
        encoding="utf-8"
    )
    assert chapters.count("[CHAPTER]") == 7


@pytest.mark.parametrize("value", ["0", "501", "-1", "abc", ""])
def test_fake_chapters_flag_rejects_out_of_range(run_cli, events, value):
    result = run_cli("get", ASIN, "--fake-chapters", value, fake=True)
    assert result.returncode != 0
    assert events(result)[-1]["code"] == "invalid_args"


def test_fake_chapters_is_ignored_in_real_mode(env, monkeypatch, capsys):
    """The flag only exists in fake mode; a real run ignores it (never invalid_args)."""
    for key in (
        "HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_RUNTIME_DIR",
        "OMARCHY_AUDIBLE_BOOKS_DIR",
    ):
        monkeypatch.setenv(key, env[key])
    monkeypatch.delenv("OMARCHY_AUDIBLE_FAKE", raising=False)

    from omarchy_audible.cli import main

    code = main(["get", ASIN, "--fake-chapters", "10"])
    assert code != 0
    parsed = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    last = json.loads(parsed[-1])
    assert last["type"] == "error"
    assert last["code"] != "invalid_args"


def test_get_rejects_an_unknown_fake_fail_mode(run_cli, events):
    result = run_cli("get", ASIN, "--fake-fail", "explode", fake=True)
    assert result.returncode != 0
    assert events(result)[-1]["code"] == "invalid_args"


def test_get_requires_an_asin(run_cli, events):
    result = run_cli("get", fake=True)
    assert result.returncode != 0
    assert events(result)[-1]["code"] == "invalid_args"


# --- no key material in any subprocess argv (the point of B11) ---------------


class _RecordingTracker(dl.ChildTracker):
    """A ChildTracker that records every argv and spawns nothing itself."""

    def __init__(self, spawn: bool = False) -> None:
        super().__init__()
        self.argvs: list[list[str]] = []
        self._spawn = spawn

    def spawn(self, argv, *, env=None, quiet=False, stderr=None, cwd=None):  # type: ignore[override]
        self.argvs.append(list(argv))
        if not self._spawn:
            raise AssertionError(f"unexpected subprocess: {argv}")
        return super().spawn(argv, env=env, quiet=quiet, stderr=stderr, cwd=cwd)


def _assert_no_key_material(argvs: list[list[str]], secrets: tuple[str, ...]) -> None:
    for argv in argvs:
        joined = " ".join(argv)
        for secret in secrets:
            assert secret not in joined, f"key material in argv: {argv[0]}"
        for name in ("audible_key", "audible_iv", "activation_bytes", "demuxer-lavf-o"):
            assert name not in joined, f"key option in argv: {argv[0]}"


def test_fake_get_never_puts_key_material_in_an_argv(ffmpeg_bin, fake_paths):
    tracker = _RecordingTracker(spawn=True)
    dl.run_get(ASIN, fake_paths, fake=True, emit=lambda *a, **k: None, children=tracker)

    assert tracker.argvs, "the fake sine generation should have spawned ffmpeg"
    _assert_no_key_material(
        tracker.argvs,
        (dl.FAKE_VOUCHER_KEY, dl.FAKE_VOUCHER_IV, fakestate.FAKE_ACTIVATION_BYTES),
    )


class _FakeProc:
    """The minimum Popen surface the download loop touches."""

    returncode = 0

    def poll(self) -> int:
        return 0

    def terminate(self) -> None:
        pass

    def wait(self, timeout: int | None = None) -> int:
        return 0

    def communicate(self) -> tuple[bytes, bytes]:
        return (b"", b"")


class _AudibleTracker(dl.ChildTracker):
    """Records every argv, and fabricates what audible-cli would download."""

    def __init__(self, asin: str, key: str, iv: str) -> None:
        super().__init__()
        self.argvs: list[list[str]] = []
        self._asin = asin
        self._key = key
        self._iv = iv

    def spawn(self, argv, *, env=None, quiet=False, stderr=None, cwd=None):  # type: ignore[override]
        self.argvs.append(list(argv))
        output = Path(cwd) / argv[argv.index("-o") + 1]
        (output / f"{self._asin}.aaxc").write_bytes(b"aaxc-bytes")
        (output / f"{self._asin}.voucher").write_text(
            json.dumps(
                {
                    "content_license": {
                        "license_response": {"key": self._key, "iv": self._iv}
                    }
                }
            ),
            encoding="utf-8",
        )
        return _FakeProc()


def test_real_get_never_puts_key_material_in_a_subprocess_argv(paths, monkeypatch):
    """A stubbed real download: every argv (audible-cli and ffprobe) is recorded."""
    import subprocess

    key = "cafebabecafebabe0011223344556677"
    iv = "deadbeefdeadbeef0011223344556677"
    metadata = {
        "content_metadata": {
            "content_reference": {"content_size_in_bytes": 1000, "acr": "ACR00001"},
            "chapter_info": {"runtime_length_ms": 60_000},
        }
    }
    runs: list[list[str]] = []

    def fake_run(argv, **kwargs):
        runs.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="60.0\n", stderr="")

    monkeypatch.setattr(dl.subprocess, "run", fake_run)
    monkeypatch.setattr(dl, "_wrapper_python", lambda: "audible")
    monkeypatch.setattr(dl, "_audible_env", lambda paths: {})
    monkeypatch.setattr(dl, "_real_content_metadata", lambda asin, paths: metadata)

    tracker = _AudibleTracker("B0REAL0001", key, iv)
    final = dl.run_get(
        "B0REAL0001", paths, fake=False, emit=lambda *a, **k: None, children=tracker
    )

    assert final.name == "book.aaxc"
    assert tracker.argvs, "the audible-cli download argv should have been recorded"
    assert runs, "the ffprobe argv should have been recorded"
    _assert_no_key_material(tracker.argvs + runs, (key, iv))
    # key.json holds the key (0600); the key is never an argv entry.
    key_file = final.parent / "key.json"
    assert key_file.is_file()
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "error_name,expected", [("Unauthorized", "auth_failed"), ("BadRequest", "internal")]
)
def test_real_get_classifies_metadata_errors_before_creating_partial(
    paths, monkeypatch, error_name, expected
):
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.auth_file.write_text("stub", encoding="utf-8")
    error_type = type(error_name, (Exception,), {})

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, *_args, **_kwargs):
            raise error_type("stub response")

    audible = SimpleNamespace(
        Authenticator=SimpleNamespace(from_file=lambda _path: object()), Client=Client
    )
    monkeypatch.setitem(sys.modules, "audible", audible)
    with pytest.raises(PipelineError) as info:
        dl.run_get("B0REAL0001", paths, fake=False, emit=lambda *a, **k: None)
    assert info.value.code == expected
    assert not (paths.books_dir / "B0REAL0001").exists()


def test_real_get_reports_an_unreadable_login_as_auth_failed(paths, monkeypatch):
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.auth_file.write_text("stub", encoding="utf-8")

    def broken(_path):
        raise ValueError("corrupt auth file")

    audible = SimpleNamespace(
        Authenticator=SimpleNamespace(from_file=broken), Client=object
    )
    monkeypatch.setitem(sys.modules, "audible", audible)
    with pytest.raises(PipelineError) as info:
        dl.run_get("B0REAL0001", paths, fake=False, emit=lambda *a, **k: None)
    assert info.value.code == dl.protocol.ErrorCode.AUTH_FAILED
    assert not (paths.books_dir / "B0REAL0001").exists()


# --- ASIN validation (ARCHITECTURE 4.4; shared library.validate_asin) --------
# These mirror the traversal and symlink refusals in test_local_remove.py: an
# ASIN is a single path component and `get` must never write or delete outside
# booksDir. `get` reports a rejected ASIN as error(code=bad_asin).


def test_get_refuses_a_path_outside_books_dir(
    run_cli, validate_stream, paths, tmp_path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")

    result = run_cli("get", "../outside", fake=True)
    assert result.returncode != 0
    parsed = validate_stream(result, expect_last="error")
    assert parsed[-1]["code"] == "bad_asin"
    assert (outside / "keep.txt").is_file()
    assert not (outside / "book.aaxc").exists()


def test_get_dotdot_never_deletes_the_parent_partial(
    run_cli, validate_stream, fake_paths
):
    # `get ..` must not rmtree `<booksRoot>/../.partial/`, a directory the
    # command does not own (the review's F1 reproduction).
    parent_partial = fake_paths.books_dir.parent / ".partial"
    parent_partial.mkdir()
    (parent_partial / "keep.txt").write_text("keep", encoding="utf-8")

    result = run_cli("get", "..", fake=True)
    assert result.returncode != 0
    parsed = validate_stream(result, expect_last="error")
    assert parsed[-1]["code"] == "bad_asin"
    assert (parent_partial / "keep.txt").is_file()
    assert not (fake_paths.books_dir.parent / "book.aaxc").exists()


def test_get_refuses_an_absolute_path(run_cli, validate_stream, paths, tmp_path):
    absolute = tmp_path / "absolute"
    result = run_cli("get", str(absolute), fake=True)
    assert result.returncode != 0
    parsed = validate_stream(result, expect_last="error")
    assert parsed[-1]["code"] == "bad_asin"
    assert not absolute.exists()


def test_get_refuses_a_symlink_inside_books_dir(run_cli, validate_stream, fake_paths):
    real = fake_paths.books_dir / "B00FAKE03"
    real.mkdir()
    (real / "book.m4b").write_bytes(b"x")
    link = fake_paths.books_dir / "B00FAKE04"
    link.symlink_to(real)

    result = run_cli("get", "B00FAKE04", fake=True)
    assert result.returncode != 0
    parsed = validate_stream(result, expect_last="error")
    assert parsed[-1]["code"] == "bad_asin"
    assert link.is_symlink()
    assert (real / "book.m4b").is_file()


def test_get_refuses_a_symlink_pointing_outside(
    run_cli, validate_stream, fake_paths, tmp_path
):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("keep", encoding="utf-8")
    link = fake_paths.books_dir / "B00LINK01"
    link.symlink_to(victim)

    result = run_cli("get", "B00LINK01", fake=True)
    assert result.returncode != 0
    parsed = validate_stream(result, expect_last="error")
    assert parsed[-1]["code"] == "bad_asin"
    assert (victim / "keep.txt").is_file()

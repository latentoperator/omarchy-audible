"""0.1.5 — Audible's ``CustomerThrottled`` refusal, and the download pause.

Audible sometimes answers a license request with ``status_code: Denied`` and a
``rejectionReason`` of ``CustomerThrottled``: downloads stop for a day or two
while the phone app still downloads. audible-cli only logs the machine-readable
reason at DEBUG on ``audible_cli.models`` and then raises the generic
``LicenseDenied``, so the wrapper captures that record, keeps the reason codes
and nothing else, and ``get`` ends ``throttled`` instead of ``network``.

These tests cover the whole path with stand-ins only — a stand-in
``audible_cli`` for the wrapper, monkeypatched metadata for the real pipeline —
and pin the clock everywhere the pause doubles: 4, 8, 16, 24 h, then a day.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import qjs
from omarchy_audible import audible_download as aud
from omarchy_audible import download as dl
from omarchy_audible import pause, protocol
from omarchy_audible.errors import PipelineError

ASIN = "B00FAKE01"
TITLE = "The Lighthouse Ledger"
# Something Audible's own human text could say, planted so a leak is visible.
MESSAGE = f"License not granted for {ASIN} ({TITLE})"
# What the stand-in writes to stderr, as audible-cli does. Generic on purpose:
# nothing here should be able to reach a log line or the notes file.
STDERR_LINE = "LicenseDenied: license not granted to customer"

DENIED = "license-denied.json"
# The wrapper's line, exactly as audible-cli 0.6.0 logs it: the record's args
# are ``(asin, message, rejectionReason, validationType)``.
DENIAL_LINE = "License denied message for %s: %s.Reason: %s.Type: %s"


def _write_catalog(paths) -> None:
    paths.catalog_file.parent.mkdir(parents=True, exist_ok=True)
    paths.catalog_file.write_text(
        json.dumps({"books": [{"asin": ASIN, "title": TITLE, "authors": []}]}),
        encoding="utf-8",
    )


def _metadata() -> dict:
    return {
        "content_metadata": {
            "content_reference": {"content_size_in_bytes": 1000, "acr": "ACR00001"},
            "chapter_info": {"runtime_length_ms": 60_000},
        }
    }


# A fake pasted login URL, shaped as the sign-in tests use.
CODE = "AUTHCODE1234567890"
URL = (
    "https://www.amazon.com/ap/maplanding"
    f"?openid.oa2.authorization_code={CODE}&openid.mode=checkid_setup"
)


def _status(events, result) -> dict:
    """The ``status`` event of a run: the ``done`` event follows it."""
    return next(event for event in events(result) if event["type"] == "status")


# --- the pause itself (ARCHITECTURE 4.3) --------------------------------------


def test_the_pause_doubles_from_four_hours_and_stops_at_a_day():
    assert pause.FIRST_PAUSE_HOURS == 4
    assert pause.MAX_PAUSE_HOURS == 24
    assert [pause.hours_for(count) for count in (1, 2, 3, 4, 5, 9)] == [
        4,
        8,
        16,
        24,
        24,
        24,
    ]
    # A nonsense count is a first refusal, not a crash.
    assert pause.hours_for(0) == 4


def test_each_refusal_doubles_the_pause_and_a_success_clears_it(paths):
    start = datetime(2027, 1, 15, 8, 0, 0, tzinfo=UTC)

    first = pause.record_refusal(paths, now=start)
    assert first.count == 1
    assert pause.iso(first.until) == "2027-01-15T12:00:00Z"
    assert (
        pause.until_iso(paths, now=start + timedelta(hours=3)) == "2027-01-15T12:00:00Z"
    )
    assert pause.paused(paths, now=start + timedelta(hours=3)) is not None
    # Exactly at the deadline the pause is over.
    assert pause.paused(paths, now=start + timedelta(hours=4)) is None

    second = pause.record_refusal(paths, now=start + timedelta(hours=4))
    assert second.count == 2
    assert pause.iso(second.until) == "2027-01-15T20:00:00Z"  # 4 h + 8 h
    assert second.since == first.since

    third = pause.record_refusal(paths, now=start + timedelta(hours=12))
    assert third.count == 3
    assert pause.iso(third.until) == "2027-01-16T12:00:00Z"  # 20:00 Z + 16 h

    fourth = pause.record_refusal(paths, now=start + timedelta(hours=28))
    assert fourth.count == 4
    assert pause.iso(fourth.until) == "2027-01-17T12:00:00Z"  # + 24 h, the cap

    fifth = pause.record_refusal(paths, now=start + timedelta(hours=52))
    assert fifth.count == 5
    assert fifth.until - (start + timedelta(hours=52)) == timedelta(hours=24)

    # A book that came down means the account is not throttled any more.
    pause.clear(paths)
    assert pause.read(paths) is None
    assert pause.paused(paths, now=start) is None
    assert pause.until_iso(paths, now=start) is None
    # Clearing twice is fine: there is no file left to remove.
    pause.clear(paths)


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not json",
        "[]",
        '{"count": 2}',
        '{"until": "tomorrow", "count": 2}',
        "null",
    ],
)
def test_a_broken_pause_file_never_blocks_downloads(paths, content):
    """A bad file reads as "not paused": it must not stop downloads for good."""
    paths.download_pause_file.parent.mkdir(parents=True, exist_ok=True)
    paths.download_pause_file.write_text(content, encoding="utf-8")
    assert pause.read(paths) is None
    assert pause.paused(paths) is None
    assert pause.until_iso(paths) is None


def test_the_pause_file_keeps_only_its_own_fields(paths):
    pause.record_refusal(paths, now=datetime(2027, 1, 15, 8, 0, 0, tzinfo=UTC))
    assert json.loads(paths.download_pause_file.read_text(encoding="utf-8")) == {
        "until": "2027-01-15T12:00:00Z",
        "since": "2027-01-15T08:00:00Z",
        "count": 1,
    }


# --- the wrapper's denial capture (ARCHITECTURE 4.3 step 3) -------------------


def _standin(
    tmp_path: Path,
    *,
    reason: str,
    message: str = MESSAGE,
    stderr_line: str = STDERR_LINE,
) -> tuple[Path, Path]:
    """A stand-in ``audible_cli``: logs the real denial record, then fails.

    It logs the record the way audible-cli 0.6.0 does — DEBUG on
    ``audible_cli.models``, with ``(asin, message, rejectionReason, type)`` as
    the record's arguments — writes audible-cli's own line to stderr and exits
    nonzero without downloading anything. It appends its arguments to
    ``$STANDIN_LOG`` so a test can see how many runs it got.
    """
    root = tmp_path / "stand-in"
    package = root / "audible_cli"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(
        "import logging\n"
        "import os\n"
        "import sys\n"
        "\n"
        "\n"
        "class LicenseDenied(Exception):\n"
        "    pass\n"
        "\n"
        "\n"
        "def main(args=None, prog_name=None):\n"
        "    logging.basicConfig(level=logging.INFO, stream=sys.stderr)\n"
        '    with open(os.environ["STANDIN_LOG"], "a", encoding="utf-8") as log:\n'
        '        log.write(" ".join(args) + "\\n")\n'
        f"    logger = logging.getLogger({aud.MODELS_LOGGER!r})\n"
        f"    message = {message!r}\n"
        "    logger.debug(\n"
        f"        {DENIAL_LINE!r},\n"
        f"        {ASIN!r},\n"
        "        message,\n"
        f"        {reason!r},\n"
        "        'validation',\n"
        "    )\n"
        f'    sys.stderr.write({stderr_line!r} + "\\n")\n'
        "    raise SystemExit(1)\n",
        encoding="utf-8",
    )
    return root, tmp_path / "standin-runs.log"


def _wrapper_env(tmp_path: Path, root: Path, log: Path) -> dict[str, str]:
    return dl._wrapper_env(
        {**os.environ, "PYTHONPATH": str(root), "STANDIN_LOG": str(log)}, ASIN
    )


def _run_wrapper(tmp_path: Path, **kwargs) -> tuple[subprocess.CompletedProcess, Path]:
    """Run the real wrapper in a fresh ``.partial/`` against the stand-in."""
    root, log = _standin(tmp_path, **kwargs)
    workdir = tmp_path / "partial"
    workdir.mkdir()
    result = subprocess.run(
        [sys.executable, "-P", "-m", dl.AUDIBLE_WRAPPER, "--aaxc", "-o", "."],
        env=_wrapper_env(tmp_path, root, log),
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, workdir


@pytest.mark.parametrize(
    ("reason", "throttled", "reasons"),
    [
        ("CustomerThrottled", True, ["CustomerThrottled"]),
        ("customerthrottled", True, ["customerthrottled"]),
        ("NotOwned", False, ["NotOwned"]),
        # A reason that is not a bare code is dropped, never written down.
        ("not a code!", False, []),
        ("x" * 65, False, []),
    ],
)
def test_the_wrapper_writes_only_the_reason_codes(tmp_path, reason, throttled, reasons):
    result, workdir = _run_wrapper(tmp_path, reason=reason)

    assert result.returncode != 0
    assert json.loads((workdir / DENIED).read_text(encoding="utf-8")) == {
        "reasons": reasons,
        "throttled": throttled,
    }
    # The DEBUG record never reaches the console: audible-cli's stderr is what
    # it always was, and the denial line is not in it.
    assert "License denied message for" not in result.stderr
    assert "Reason:" not in result.stderr
    assert STDERR_LINE in result.stderr


def test_the_denial_file_carries_no_asin_title_or_message_text(tmp_path):
    """Everything but the code stays out: the record's own message names the
    book, and the file is written from that record."""
    _result, workdir = _run_wrapper(tmp_path, reason="CustomerThrottled")
    text = (workdir / DENIED).read_text(encoding="utf-8")

    assert json.loads(text) == {"reasons": ["CustomerThrottled"], "throttled": True}
    for leak in (ASIN, TITLE, MESSAGE, "License not granted"):
        assert leak not in text, leak


def test_a_denial_only_in_the_message_still_reads_as_throttled(tmp_path):
    """Some refusals only say so in Audible's text, not in the reason code: the
    wrapper's flag is what carries that, since the codes stay clean."""
    message = f"The customer id is being throttled ({ASIN})"
    result, workdir = _run_wrapper(tmp_path, reason="OtherReason", message=message)

    assert result.returncode != 0
    assert json.loads((workdir / DENIED).read_text(encoding="utf-8")) == {
        "reasons": ["OtherReason"],
        "throttled": True,
    }
    assert ASIN not in (workdir / DENIED).read_text(encoding="utf-8")


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\n\t \n"])
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize(
    "reason,message_tail,throttled,reasons",
    [
        ("CustomerThrottled", "Please wait.", True, ["CustomerThrottled"]),
        ("OtherReason", "The customer is being throttled.", True, ["OtherReason"]),
        ("NotOwned", "Not available.", False, ["NotOwned"]),
        ("not a code!", "Not available.", False, []),
    ],
)
def test_multiline_denial_records_keep_only_codes(
    tmp_path, newline, structured, reason, message_tail, throttled, reasons, capsys
):
    message = f"{MESSAGE}{newline}{message_tail} key=INVENTEDKEY iv=INVENTEDIV"
    args = (ASIN, message, f"\t{reason}{newline}", "validation")
    record = logging.LogRecord(
        aud.MODELS_LOGGER,
        logging.DEBUG,
        __file__,
        0,
        DENIAL_LINE if structured else DENIAL_LINE % args,
        args if structured else (),
        None,
    )
    watch = aud.LicenseDenialWatch()
    assert watch.filter(record) is False
    assert watch.denied is True
    assert watch.throttled is throttled
    assert watch.reasons == reasons
    target = tmp_path / DENIED
    watch.save(target)
    text = target.read_text()
    assert json.loads(text) == {"reasons": reasons, "throttled": throttled}
    for leak in (ASIN, TITLE, MESSAGE, message_tail, "INVENTEDKEY", "INVENTEDIV"):
        assert leak not in text
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\n\t \n"])
def test_multiline_throttling_is_captured_by_the_wrapper(
    tmp_path, env, monkeypatch, newline
):
    for name in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR"):
        monkeypatch.setenv(name, env[name])
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    message = f"{MESSAGE}{newline}Please wait. key=INVENTEDKEY iv=INVENTEDIV"
    result, workdir = _run_wrapper(
        tmp_path, reason="CustomerThrottled", message=message
    )
    assert result.returncode != 0
    text = (workdir / DENIED).read_text()
    assert json.loads(text) == {"reasons": ["CustomerThrottled"], "throttled": True}
    diagnostics = text + result.stderr + result.stdout
    for leak in (ASIN, TITLE, MESSAGE, "Please wait.", "INVENTEDKEY", "INVENTEDIV"):
        assert leak not in diagnostics
    assert result.stdout == ""
    assert result.stderr == STDERR_LINE + "\n"


def test_no_denial_means_no_file(tmp_path):
    """A wrapper run that is not a denial writes nothing extra."""
    root = tmp_path / "stand-in"
    package = root / "audible_cli"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "def main(args=None, prog_name=None):\n    raise SystemExit(0)\n",
        encoding="utf-8",
    )
    workdir = tmp_path / "partial"
    workdir.mkdir()
    result = subprocess.run(
        [sys.executable, "-P", "-m", dl.AUDIBLE_WRAPPER, "--aaxc", "-o", "."],
        env=_wrapper_env(tmp_path, root, tmp_path / "runs.log"),
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert not (workdir / DENIED).exists()


def test_the_notes_reader_drops_anything_that_is_not_a_code(tmp_path):
    partial = tmp_path / "partial"
    partial.mkdir()
    (partial / DENIED).write_text(
        json.dumps({"reasons": ["CustomerThrottled", "not a code", "", 7, None]}),
        encoding="utf-8",
    )
    assert dl._denial(partial) == (["CustomerThrottled"], False)
    assert dl._denial(tmp_path / "elsewhere") == ([], False)
    (partial / DENIED).write_text("not json", encoding="utf-8")
    assert dl._denial(partial) == ([], False)
    (partial / DENIED).write_text(json.dumps(["CustomerThrottled"]), encoding="utf-8")
    assert dl._denial(partial) == ([], False)


def test_throttled_classification_reads_codes_the_flag_and_the_stderr_line():
    assert dl._throttled(["CustomerThrottled"], "") is True
    assert dl._throttled(["customerthrottled"], "") is True
    assert dl._throttled([], "", True) is True
    assert dl._throttled([], "error: Customer id being throttled") is True
    assert dl._throttled(["NotOwned"], "License not granted to customer") is False
    assert dl._throttled([], "") is False


# --- the real pipeline, with a stand-in audible-cli ---------------------------


def _real_get(
    paths, tmp_path: Path, monkeypatch, *, reason: str, message: str = MESSAGE
):
    """Run a real-mode ``get`` against the stand-in; return what it raised."""
    root, log = _standin(tmp_path, reason=reason, message=message)
    _write_catalog(paths)
    monkeypatch.setattr(dl, "_wrapper_python", lambda: sys.executable)
    monkeypatch.setattr(
        dl,
        "_audible_env",
        lambda paths: {
            "AUDIBLE_CONFIG_DIR": str(tmp_path / "audible-config"),
            "PYTHONPATH": str(root),
            "STANDIN_LOG": str(log),
        },
    )
    monkeypatch.setattr(dl, "_real_content_metadata", lambda asin, paths: _metadata())
    with pytest.raises(PipelineError) as excinfo:
        dl.run_get(ASIN, paths, fake=False, emit=lambda *a, **k: None)
    return excinfo.value, log


def test_a_throttled_refusal_ends_the_get_as_throttled(
    paths, tmp_path, monkeypatch, capsys
):
    exc, log = _real_get(paths, tmp_path, monkeypatch, reason="CustomerThrottled")

    assert exc.code == protocol.ErrorCode.THROTTLED == "throttled"
    assert exc.message == pause.THROTTLED_MESSAGE
    # The error carries the instant the file holds, so the drawer can say when.
    assert exc.until == pause.until_iso(paths)
    assert pause.read(paths).count == 1
    assert pause.read(paths).until > datetime.now(tz=UTC)

    # Exactly one audible-cli run, and it was the aaxc attempt: a throttled
    # refusal is not a missing voucher, so there is no aax retry.
    runs = log.read_text(encoding="utf-8").splitlines()
    assert len(runs) == 1
    assert runs[0].split()[:3] == ["download", "-a", ASIN]
    assert "--aaxc" in runs[0].split()

    # Nothing is left behind, and no log line names the book or repeats
    # Audible's message: only the reason code is logged.
    assert not (paths.books_dir / ASIN / ".partial").exists()
    assert not (paths.books_dir / ASIN / "book.aaxc").exists()
    logged = capsys.readouterr().err
    assert "audible refused the license (aaxc): CustomerThrottled" in logged
    for leak in (ASIN, TITLE, MESSAGE, "License not granted"):
        assert leak not in logged, leak


def test_another_denial_reason_keeps_its_current_path(paths, tmp_path, monkeypatch):
    exc, log = _real_get(paths, tmp_path, monkeypatch, reason="NotOwned")

    assert exc.code == protocol.ErrorCode.NETWORK
    assert exc.hint == "check the network and retry"
    assert exc.until is None
    # No pause: this is not a throttle, so nothing about it waits.
    assert pause.read(paths) is None
    assert pause.until_iso(paths) is None
    # Still one run, still aaxc: no aax retry for a denial.
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1


def test_a_message_only_denial_is_read_as_throttled(paths, tmp_path, monkeypatch):
    """The second signal: a reason code that is not CustomerThrottled, whose
    own message says the customer is being throttled."""
    exc, _log = _real_get(
        paths,
        tmp_path,
        monkeypatch,
        reason="Denied",
        message=f"Customer id being throttled ({ASIN})",
    )
    assert exc.code == protocol.ErrorCode.THROTTLED
    assert pause.read(paths).count == 1


def test_a_paused_get_makes_no_network_call_and_leaves_nothing(paths, monkeypatch):
    """The gate is ahead of the content metadata and the license request."""
    recorded = pause.record_refusal(paths)
    calls: list[str] = []

    def never(*args, **kwargs):
        calls.append("called")
        raise AssertionError("a paused get reached the network")

    monkeypatch.setattr(dl, "_real_content_metadata", never)
    monkeypatch.setattr(dl, "_audible_download", never)
    monkeypatch.setattr(dl, "check_free_space", never)

    with pytest.raises(PipelineError) as excinfo:
        dl.run_get(ASIN, paths, fake=False, emit=lambda *a, **k: None)

    exc = excinfo.value
    assert calls == []
    assert exc.code == protocol.ErrorCode.THROTTLED
    assert exc.until == pause.iso(recorded.until)
    # No ``.partial/`` and no book directory at all.
    assert not (paths.books_dir / ASIN).exists()
    assert not list(paths.books_dir.glob("*/.partial"))


def test_a_paused_get_makes_no_fetch_in_fake_mode_too(fake_paths, monkeypatch):
    pause.record_refusal(fake_paths)
    monkeypatch.setattr(
        dl, "_fake_fetch", lambda *a, **k: pytest.fail("a paused get fetched")
    )
    with pytest.raises(PipelineError) as excinfo:
        dl.run_get(ASIN, fake_paths, fake=True, emit=lambda *a, **k: None)
    assert excinfo.value.code == protocol.ErrorCode.THROTTLED
    assert not (fake_paths.books_dir / ASIN).exists()


# --- the commands (fake mode, ARCHITECTURE 4.2) -------------------------------


def test_a_fake_throttled_get_reports_throttled_and_writes_the_pause(
    run_cli, validate_stream, fake_paths
):
    result = run_cli("get", ASIN, "--fake-fail", "throttled", fake=True)

    assert result.returncode != 0
    parsed = validate_stream(result, expect_last="error")
    last = parsed[-1]
    assert last["code"] == "throttled"
    assert last["message"] == pause.THROTTLED_MESSAGE
    assert last["until"] == pause.until_iso(fake_paths)
    assert pause.read(fake_paths).count == 1
    # The refusal came after a progress tick, so the row showed work first.
    assert {event["stage"] for event in parsed if event["type"] == "progress"} == {
        "download"
    }
    # Nothing is left staged: the refusal ends the download like any failure.
    assert not (fake_paths.books_dir / ASIN / ".partial").exists()
    assert not (fake_paths.books_dir / ASIN / "book.aaxc").exists()


def test_a_second_get_while_paused_is_refused_before_anything(
    run_cli, validate_stream, fake_paths
):
    first = run_cli("get", ASIN, "--fake-fail", "throttled", fake=True)
    assert first.returncode != 0
    until = pause.until_iso(fake_paths)

    second = run_cli("get", ASIN, fake=True)
    assert second.returncode != 0
    parsed = validate_stream(second, expect_last="error")
    # Not one event before the refusal: no metadata, no progress, no .partial.
    assert [event["type"] for event in parsed] == ["error"]
    assert parsed[-1]["code"] == "throttled"
    assert parsed[-1]["until"] == until
    # Extending the pause is a refusal's job, not the gate's.
    assert pause.read(fake_paths).count == 1
    # The refusal came before the staging directory existed, so nothing was
    # made and no book was left behind.
    assert not (fake_paths.books_dir / ASIN / ".partial").exists()
    assert not (fake_paths.books_dir / ASIN / "book.aaxc").exists()


def test_a_successful_get_clears_the_pause(run_cli, ffmpeg_bin, fake_paths, events):
    refused = run_cli("get", ASIN, "--fake-fail", "throttled", fake=True)
    assert refused.returncode != 0
    assert pause.read(fake_paths).count == 1

    # A while later the pause has run out: downloads may run again, so the
    # next `get` really asks and really succeeds.
    expired = datetime.now(tz=UTC) - timedelta(hours=1)
    fake_paths.download_pause_file.write_text(
        json.dumps(
            {
                "until": pause.iso(expired),
                "since": pause.iso(expired - timedelta(hours=4)),
                "count": 1,
            }
        ),
        encoding="utf-8",
    )
    assert pause.read(fake_paths) is not None
    assert pause.paused(fake_paths) is None

    good = run_cli("get", ASIN, fake=True)
    assert good.returncode == 0, good.stderr
    assert pause.read(fake_paths) is None
    assert pause.until_iso(fake_paths) is None
    assert (
        _status(events, run_cli("status", fake=True))["downloads_paused_until"] is None
    )


def test_logout_clears_the_pause(run_cli, fake_paths):
    pause.record_refusal(fake_paths)
    assert pause.read(fake_paths) is not None

    result = run_cli("logout", fake=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert pause.read(fake_paths) is None


def test_login_import_clears_the_pause(run_cli, fake_paths):
    pause.record_refusal(fake_paths)
    assert pause.read(fake_paths) is not None

    result = run_cli("login-import-cli", fake=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert pause.read(fake_paths) is None


def test_signing_in_again_clears_the_pause(run_cli, fake_paths, events):
    """A new sign-in registers a new device: the FAQ's second step."""
    session = events(run_cli("login-start", "--marketplace", "us", fake=True))[0][
        "session"
    ]
    pause.record_refusal(fake_paths)
    assert pause.read(fake_paths) is not None

    result = run_cli("login-finish", "--session", session, fake=True, stdin=URL)

    assert result.returncode == 0, result.stdout + result.stderr
    assert pause.read(fake_paths) is None


def test_status_reports_the_pause_in_fake_mode(
    run_cli, events, validate_event, fake_paths
):
    before = _status(events, run_cli("status", fake=True))
    validate_event(before)
    assert before["downloads_paused_until"] is None

    run_cli("get", ASIN, "--fake-fail", "throttled", fake=True)
    after = _status(events, run_cli("status", fake=True))
    validate_event(after)
    assert after["downloads_paused_until"] == pause.until_iso(fake_paths)


def test_status_reports_the_pause_in_real_mode(run_cli, events, validate_event, paths):
    before = _status(events, run_cli("status"))
    validate_event(before)
    assert before["downloads_paused_until"] is None

    recorded = pause.record_refusal(paths)
    after = _status(events, run_cli("status"))
    validate_event(after)
    assert after["downloads_paused_until"] == pause.iso(recorded.until)


def test_the_fake_pause_and_the_real_pause_are_separate_files(fake_paths, paths):
    assert fake_paths.download_pause_file != paths.download_pause_file
    pause.record_refusal(fake_paths)
    assert pause.until_iso(fake_paths) is not None
    assert pause.until_iso(paths) is None


# --- the wording the drawer shows --------------------------------------------


def test_the_drawer_uses_the_backend_sentence_exactly():
    onboarding = qjs.load("Onboarding")
    assert onboarding.evaluate("THROTTLED_TEXT") == pause.THROTTLED_MESSAGE
    entry = onboarding.call("errorText", "throttled")
    assert entry["body"] == pause.THROTTLED_MESSAGE
    assert entry["title"] == "Audible is limiting downloads"
    # Nothing about the network is offered for this code.
    assert entry["reconnect"] is False

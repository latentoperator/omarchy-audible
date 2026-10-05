"""B6 — positions: the merge, the cache and the write-back.

ARCHITECTURE 4.6 (read/write, batches of at most 25, push rules) and 4.8
(``remote.json`` is written by the backend; ``state.json`` never is). Covers the
acceptance list: merge edge cases (equal timestamps, missing remote, remote
newer), the stale refusal, ``lastpositions`` batching at most 25, ``acr`` from
``meta.json`` else the content metadata, and that ``sync`` never pushes.
"""

from __future__ import annotations

import contextlib
import json

import pytest
from omarchy_audible import commands, positions, protocol
from omarchy_audible.errors import PipelineError
from omarchy_audible.paths import Paths

ASIN = "B00FAKE01"


def _book(paths: Paths, asin: str, *, acr: str | None = None) -> None:
    directory = paths.books_dir / asin
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "book.m4b").write_bytes(b"x")
    meta = {"asin": asin, "downloaded_at": "2026-01-02T03:04:05Z"}
    if acr is not None:
        meta["acr"] = acr
    (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


class _RecordingPort:
    """A ``PushPort`` that records reads and writes and returns canned values."""

    def __init__(self, remote=None, acr: str | None = "STOREACR") -> None:
        self.remote = {ASIN: remote} if remote else {}
        self.acr = acr
        self.fetched: list[list[str]] = []
        self.acr_calls: list[str] = []
        self.pushed: list[tuple[str, str, int]] = []

    def fetch_batch(self, asins):
        self.fetched.append(list(asins))
        return {a: dict(self.remote.get(a, positions.empty_entry())) for a in asins}

    def fetch_acr(self, asin):
        self.acr_calls.append(asin)
        return self.acr

    def push(self, asin, acr, position_ms):
        self.pushed.append((asin, acr, position_ms))


# --- the pure merge (ARCHITECTURE 4.6) ---------------------------------------
def test_merge_takes_the_newer_remote():
    local = {"ms": 1000, "updated_at": "2026-01-01 00:00:00.0"}
    remote = {"ms": 2000, "updated_at": "2026-01-02 00:00:00.0"}
    assert positions.merge(local, remote) == remote
    assert positions.merge(remote, local) == remote


def test_merge_keeps_the_newer_local():
    local = {"ms": 2000, "updated_at": "2026-01-02 00:00:00.0"}
    remote = {"ms": 1000, "updated_at": "2026-01-01 00:00:00.0"}
    assert positions.merge(local, remote) == local


def test_merge_equal_timestamps_prefer_local():
    local = {"ms": 1500, "updated_at": "2026-01-01T00:00:00Z"}
    remote = {"ms": 1500, "updated_at": "2026-01-01 00:00:00.0"}
    assert positions.merge(local, remote) == local


def test_merge_missing_remote_or_local():
    local = {"ms": 10, "updated_at": "2026-01-01T00:00:00Z"}
    assert positions.merge(local, None) == local
    assert positions.merge(None, local) == local
    assert positions.merge(None, None) == positions.empty_entry()


def test_merge_treats_a_missing_timestamp_as_the_oldest():
    stamped = {"ms": 10, "updated_at": "2026-01-01T00:00:00Z"}
    unstamped = {"ms": 99, "updated_at": None}
    assert positions.merge(unstamped, stamped) == stamped
    assert positions.merge(stamped, unstamped) == stamped


def test_parse_updated_at_accepts_the_remote_and_iso_forms():
    remote = positions.parse_updated_at("2026-10-04 12:00:00.5")
    iso = positions.parse_updated_at("2026-10-04T12:00:00.500000Z")
    assert remote is not None and remote == iso
    assert positions.parse_updated_at("nonsense") is None
    assert positions.parse_updated_at(None) is None


# --- the stale guard (ARCHITECTURE 4.6 push rules) ---------------------------
def test_is_remote_newer_only_when_strictly_newer():
    newer = {"ms": 1, "updated_at": "2026-02-01 00:00:00.0"}
    same = {"ms": 1, "updated_at": "2026-01-01T00:00:00Z"}
    assert positions.is_remote_newer(newer, "2026-01-01T00:00:00Z")
    assert not positions.is_remote_newer(same, "2026-01-01T00:00:00Z")
    assert not positions.is_remote_newer(
        {"ms": 1, "updated_at": None}, "2026-01-01T00:00:00Z"
    )
    assert not positions.is_remote_newer(newer, None)


def test_push_refuses_when_the_remote_is_newer(paths):
    port = _RecordingPort(remote={"ms": 5000, "updated_at": "2026-02-01 00:00:00.0"})
    with pytest.raises(PipelineError) as info:
        positions.push_position(
            ASIN,
            1000,
            books_dir=paths.books_dir,
            port=port,
            local_updated_at="2026-01-01T00:00:00Z",
        )
    assert info.value.code == protocol.ErrorCode.STALE
    assert port.pushed == []
    # The remote position is re-read before the write (ARCHITECTURE 4.6).
    assert port.fetched == [[ASIN]]


def test_push_writes_when_the_local_position_is_newer(paths):
    _book(paths, ASIN, acr="METAACR")
    port = _RecordingPort(remote={"ms": 1000, "updated_at": "2026-01-01 00:00:00.0"})
    positions.push_position(
        ASIN,
        2000,
        books_dir=paths.books_dir,
        port=port,
        local_updated_at="2026-02-01T00:00:00Z",
    )
    assert port.pushed == [(ASIN, "METAACR", 2000)]
    # acr came from meta.json, so the content metadata was never read.
    assert port.acr_calls == []


def test_push_falls_back_to_the_content_metadata_for_acr(paths):
    _book(paths, ASIN)  # local, but meta.json carries no acr
    port = _RecordingPort(remote=None, acr="NETWORKACR")
    positions.push_position(
        ASIN,
        2000,
        books_dir=paths.books_dir,
        port=port,
        local_updated_at="2026-02-01T00:00:00Z",
    )
    assert port.acr_calls == [ASIN]
    assert port.pushed == [(ASIN, "NETWORKACR", 2000)]


def test_push_is_unsupported_without_an_acr(paths):
    port = _RecordingPort(remote=None, acr=None)
    with pytest.raises(PipelineError) as info:
        positions.push_position(
            ASIN,
            2000,
            books_dir=paths.books_dir,
            port=port,
            local_updated_at="2026-02-01T00:00:00Z",
        )
    assert info.value.code == protocol.ErrorCode.UNSUPPORTED
    assert port.pushed == []


# --- batching (SPIKE-RESULTS S3) ---------------------------------------------
def test_fetch_positions_never_batches_more_than_25():
    asins = [f"B0{index:08d}" for index in range(60)]
    calls: list[list[str]] = []

    class _Port:
        def fetch_batch(self, batch):
            calls.append(list(batch))
            return {a: {"ms": 1, "updated_at": "2026-01-01 00:00:00.0"} for a in batch}

    result = positions.fetch_positions(asins, _Port())
    assert [len(batch) for batch in calls] == [25, 25, 10]
    assert set(result) == set(asins)


# --- argument parsing --------------------------------------------------------
def test_split_push_args_reads_the_local_timestamp():
    assert commands.split_push_args(["B00FAKE01", "1000"]) == ("B00FAKE01", "1000", None)
    expected = ("B00FAKE01", "1000", "2026-01-01T00:00:00Z")
    assert commands.split_push_args(["B00FAKE01", "1000", "--at", "2026-01-01T00:00:00Z"]) == expected
    assert commands.split_push_args(["B00FAKE01", "1000", "--at=2026-01-01T00:00:00Z"]) == expected


# --- the CLI in fake mode ----------------------------------------------------
def test_fake_position_get_writes_remote_and_emits_positions(
    run_cli, validate_stream, fake_paths
):
    result = run_cli("position-get", "B00FAKE01", "B00FAKE02", fake=True)
    assert result.returncode == 0, result.stderr
    parsed = validate_stream(result, expect_last="done")

    event = next(event for event in parsed if event["type"] == "positions")
    assert set(event["items"]) == {"B00FAKE01", "B00FAKE02"}
    assert event["items"]["B00FAKE01"] == {"ms": 0, "updated_at": None}

    remote = json.loads(fake_paths.remote_file.read_text(encoding="utf-8"))
    assert set(remote) == {"B00FAKE01", "B00FAKE02"}


def test_position_get_keeps_the_other_cached_books(run_cli, fake_paths):
    fake_paths.data_dir.mkdir(parents=True, exist_ok=True)
    fake_paths.remote_file.write_text(
        json.dumps({"B0KEEPCACH": {"ms": 42, "updated_at": "2026-01-01 00:00:00.0"}}),
        encoding="utf-8",
    )
    assert run_cli("position-get", "B00FAKE01", fake=True).returncode == 0
    remote = json.loads(fake_paths.remote_file.read_text(encoding="utf-8"))
    assert remote["B0KEEPCACH"] == {"ms": 42, "updated_at": "2026-01-01 00:00:00.0"}
    assert "B00FAKE01" in remote


def test_fake_position_push_succeeds(run_cli, validate_stream):
    parsed = validate_stream(
        run_cli("position-push", "B00FAKE01", "1234", fake=True), expect_last="done"
    )
    assert [event["type"] for event in parsed] == ["done"]


def test_position_get_needs_an_asin(run_cli, validate_stream):
    result = run_cli("position-get", fake=True)
    assert result.returncode == protocol.EXIT_USAGE
    parsed = validate_stream(result, expect_last="error")
    assert parsed[-1]["code"] == protocol.ErrorCode.INVALID_ARGS


def test_position_push_validates_its_arguments(run_cli, validate_stream):
    bad_ms = run_cli("position-push", "B00FAKE01", "not-a-number", fake=True)
    assert bad_ms.returncode == protocol.EXIT_USAGE
    assert validate_stream(bad_ms, expect_last="error")[-1]["code"] == (
        protocol.ErrorCode.INVALID_ARGS
    )

    missing = run_cli("position-push", "B00FAKE01", fake=True)
    assert missing.returncode == protocol.EXIT_USAGE


def test_position_push_refuses_a_stale_local_position(monkeypatch, capsys, paths):
    """The whole command path refuses a push older than the remote position."""
    port = _RecordingPort(remote={"ms": 5000, "updated_at": "2026-02-01 00:00:00.0"})
    monkeypatch.setattr(commands, "RealPositions", lambda client: port)
    monkeypatch.setattr(
        commands, "open_client", lambda paths: contextlib.nullcontext(object())
    )

    code = commands.cmd_position_push(
        [ASIN, "1000", "--at", "2026-01-01T00:00:00Z"],
        command="position-push",
        fake=False,
        paths=paths,
    )
    events = [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()
    ]
    assert code == protocol.EXIT_ERROR
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == protocol.ErrorCode.STALE
    assert port.pushed == []

"""B10 — fake mode keeps pushed positions in its own tree.

PLAN.md B10, ARCHITECTURE 4.6. Fake mode's position store used to be stateless:
``position-push --fake`` was a no-op and ``position-get --fake`` always returned
0. Now a fake push writes ``{ms, updated_at}`` (``updated_at`` is ``--at``, else
now) to ``<fake data dir>/fake-account-positions.json``, and ``position-get
--fake`` / ``sync --fake`` read it back, so the stale check and
resume-from-the-account are testable end to end. Real mode is unchanged and
never touches the fake file.

Every fixture name is invented. ``conftest`` points HOME and every XDG variable
at temporary dirs, so nothing here reads a real login or library.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import pytest
from omarchy_audible import commands, positions, protocol
from omarchy_audible.errors import PipelineError
from omarchy_audible.paths import Paths
from test_sync import FIXTURE_ASINS

ASIN = "B0FAKE0001"  # a fixture ASIN, so ``sync`` asks for it too
OTHER = "B0FAKE0002"
FAKE_FILE = "fake-account-positions.json"
NEWER = "2026-03-01T10:00:00Z"
OLDER = "2026-01-01T00:00:00Z"


def _store(fake_paths: Paths) -> Path:
    return fake_paths.data_dir / FAKE_FILE


def _read_store(fake_paths: Paths) -> dict:
    return json.loads(_store(fake_paths).read_text(encoding="utf-8"))


def _book(paths: Paths, asin: str, *, acr: str | None = None) -> None:
    directory = paths.books_dir / asin
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "book.m4b").write_bytes(b"x")
    meta = {"asin": asin}
    if acr is not None:
        meta["acr"] = acr
    (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


class _RecordingPort:
    """A real-mode-shaped port that records the calls the push path makes."""

    def __init__(self, remote=None, acr: str | None = "STOREACR") -> None:
        self.remote = {ASIN: remote} if remote else {}
        self.acr = acr
        self.fetched: list[list[str]] = []
        self.acr_calls: list[str] = []
        self.pushed: list[tuple[str, str, int]] = []
        self.updated_at: str | None = None

    def fetch_batch(self, asins):
        self.fetched.append(list(asins))
        return {a: dict(self.remote.get(a, positions.empty_entry())) for a in asins}

    def fetch_acr(self, asin):
        self.acr_calls.append(asin)
        return self.acr

    def push(self, asin, acr, position_ms, *, updated_at=None):
        self.pushed.append((asin, acr, position_ms))
        self.updated_at = updated_at


# --- the CLI in fake mode ----------------------------------------------------
def test_push_then_get_returns_the_pushed_position(
    run_cli, validate_stream, fake_paths: Paths
):
    result = run_cli("position-push", ASIN, "1200", "--at", NEWER, fake=True)
    assert result.returncode == 0, result.stderr
    validate_stream(result, expect_last="done")

    assert _read_store(fake_paths) == {ASIN: {"ms": 1200, "updated_at": NEWER}}

    fetched = validate_stream(
        run_cli("position-get", ASIN, fake=True), expect_last="done"
    )
    items = next(event for event in fetched if event["type"] == "positions")["items"]
    # The exact ms match with our own push is marked as our echo (P6, F1).
    assert items[ASIN] == {"ms": 1200, "updated_at": NEWER, "own": True}

    # `own` is a protocol marker only: remote.json keeps the plain entry.
    remote = json.loads(fake_paths.remote_file.read_text(encoding="utf-8"))
    assert remote[ASIN] == {"ms": 1200, "updated_at": NEWER}


def test_push_without_at_is_refused(run_cli, validate_stream, fake_paths: Paths):
    """F3: the old "default to now" made the stale check a no-op."""
    result = run_cli("position-push", ASIN, "77", fake=True)
    assert result.returncode == protocol.EXIT_USAGE
    parsed = validate_stream(result, expect_last="error")
    assert parsed[-1]["code"] == protocol.ErrorCode.INVALID_ARGS
    assert not _store(fake_paths).exists()


def test_push_keeps_the_other_stored_books(run_cli, fake_paths: Paths):
    assert (
        run_cli("position-push", OTHER, "10", "--at", OLDER, fake=True).returncode == 0
    )
    assert (
        run_cli("position-push", ASIN, "20", "--at", NEWER, fake=True).returncode == 0
    )

    stored = _read_store(fake_paths)
    assert stored[OTHER] == {"ms": 10, "updated_at": OLDER}
    assert stored[ASIN] == {"ms": 20, "updated_at": NEWER}


def test_a_push_older_than_the_stored_one_is_refused_as_stale(
    run_cli, validate_stream, fake_paths: Paths
):
    assert (
        run_cli("position-push", ASIN, "5000", "--at", NEWER, fake=True).returncode == 0
    )
    # Another device moves further on: a different ms with a newer stamp, so it
    # is not this device's own echo (F1).
    _store(fake_paths).write_text(
        json.dumps({ASIN: {"ms": 9000, "updated_at": NEWER}}), encoding="utf-8"
    )

    stale = run_cli("position-push", ASIN, "1000", "--at", OLDER, fake=True)
    assert stale.returncode == protocol.EXIT_ERROR
    parsed = validate_stream(stale, expect_last="error")
    assert parsed[-1]["code"] == protocol.ErrorCode.STALE

    # The refused push left the stored position alone.
    assert _read_store(fake_paths)[ASIN] == {"ms": 9000, "updated_at": NEWER}


def test_our_own_echo_does_not_lock_us_out(run_cli, validate_stream, fake_paths: Paths):
    """F1: with the server's clock ahead, our previous push looks newer."""
    assert (
        run_cli("position-push", ASIN, "1000", "--at", NEWER, fake=True).returncode == 0
    )
    # The account keeps our pushed ms but stamps it with a clock ahead of us.
    ahead = "2026-03-01T11:00:00Z"
    stored = _read_store(fake_paths)
    stored[ASIN] = {"ms": 1000, "updated_at": ahead}
    _store(fake_paths).write_text(json.dumps(stored), encoding="utf-8")

    again = run_cli("position-push", ASIN, "2000", "--at", NEWER, fake=True)
    assert again.returncode == 0, again.stderr
    validate_stream(again, expect_last="done")
    assert _read_store(fake_paths)[ASIN]["ms"] == 2000


# --- pushed.json remembers our own writes (P6, F1) ---------------------------
def test_pushed_json_survives_across_cli_processes(run_cli, fake_paths: Paths):
    assert (
        run_cli("position-push", ASIN, "1200", "--at", NEWER, fake=True).returncode == 0
    )
    pushed = fake_paths.pushed_file
    assert json.loads(pushed.read_text(encoding="utf-8")) == {
        ASIN: {"ms": 1200, "at": NEWER}
    }

    # A second, separate process (a `position-get`) reads the same record back.
    fetched = run_cli("position-get", ASIN, fake=True)
    assert fetched.returncode == 0, fetched.stderr
    items = json.loads(fetched.stdout.splitlines()[0])["items"]
    assert items[ASIN]["own"] is True
    # ...and the record is still exactly what the first process wrote.
    assert json.loads(pushed.read_text(encoding="utf-8")) == {
        ASIN: {"ms": 1200, "at": NEWER}
    }


def test_a_failed_push_does_not_update_pushed_json(
    run_cli, validate_stream, fake_paths: Paths
):
    assert (
        run_cli("position-push", ASIN, "5000", "--at", NEWER, fake=True).returncode == 0
    )
    before = fake_paths.pushed_file.read_text(encoding="utf-8")

    # Another device moves further on: a different ms with a newer stamp, so
    # the push is refused as stale.
    _store(fake_paths).write_text(
        json.dumps({ASIN: {"ms": 9000, "updated_at": NEWER}}), encoding="utf-8"
    )
    stale = run_cli(
        "position-push", ASIN, "1000", "--at", "2026-01-01T00:00:00Z", fake=True
    )
    assert stale.returncode == protocol.EXIT_ERROR
    assert validate_stream(stale, expect_last="error")[-1]["code"] == (
        protocol.ErrorCode.STALE
    )
    assert fake_paths.pushed_file.read_text(encoding="utf-8") == before


def test_position_get_marks_own_only_for_an_exact_ms_match(
    run_cli, validate_stream, fake_paths: Paths
):
    assert (
        run_cli("position-push", ASIN, "1200", "--at", NEWER, fake=True).returncode == 0
    )
    # The account holds our push and, for the other book, a phone position.
    _store(fake_paths).write_text(
        json.dumps(
            {
                ASIN: {"ms": 1200, "updated_at": NEWER},
                OTHER: {"ms": 1201, "updated_at": NEWER},
            }
        ),
        encoding="utf-8",
    )

    parsed = validate_stream(
        run_cli("position-get", ASIN, OTHER, fake=True), expect_last="done"
    )
    items = next(event for event in parsed if event["type"] == "positions")["items"]
    assert items[ASIN] == {"ms": 1200, "updated_at": NEWER, "own": True}
    # One millisecond off is not our echo, and a never-pushed book is not either.
    assert items[OTHER] == {"ms": 1201, "updated_at": NEWER}
    assert "own" not in items[OTHER]


def test_sync_fake_writes_the_stored_positions_into_remote_json(
    run_cli, fake_paths: Paths
):
    assert (
        run_cli("position-push", ASIN, "4321", "--at", NEWER, fake=True).returncode == 0
    )
    assert run_cli("sync", fake=True).returncode == 0

    remote = json.loads(fake_paths.remote_file.read_text(encoding="utf-8"))
    assert remote[ASIN] == {"ms": 4321, "updated_at": NEWER}
    # A fixture book with no stored position still gets an empty entry.
    empty = next(asin for asin in FIXTURE_ASINS if asin != ASIN)
    assert remote[empty] == {"ms": 0, "updated_at": None}


def test_a_fresh_fake_tree_has_no_stored_positions_file(run_cli, fake_paths: Paths):
    assert run_cli("position-get", ASIN, fake=True).returncode == 0
    assert not _store(fake_paths).exists()


def test_the_store_lives_only_in_the_fake_tree(run_cli, env, fake_paths: Paths):
    assert run_cli("position-push", ASIN, "9", "--at", NEWER, fake=True).returncode == 0
    real = Paths.from_env(env)
    assert _store(fake_paths).is_file()
    assert not (real.data_dir / FAKE_FILE).exists()
    # Our own-push record stays in the fake tree too (P6).
    assert fake_paths.pushed_file.is_file()
    assert not real.pushed_file.exists()


# --- real mode is unchanged --------------------------------------------------
def test_real_mode_push_uses_the_real_port_and_no_fake_store(
    monkeypatch, capsys, paths: Paths
):
    _book(paths, ASIN, acr="METAACR")
    port = _RecordingPort()
    monkeypatch.setattr(commands, "RealPositions", lambda client: port)
    monkeypatch.setattr(
        commands, "open_client", lambda paths: contextlib.nullcontext(object())
    )

    code = commands.cmd_position_push(
        [ASIN, "2000", "--at", NEWER],
        command="position-push",
        fake=False,
        paths=paths,
    )
    events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    assert code == protocol.EXIT_OK
    assert events[-1]["type"] == "done"
    assert port.pushed == [(ASIN, "METAACR", 2000)]
    assert port.updated_at == NEWER
    assert not (paths.data_dir / FAKE_FILE).exists()
    # Real mode records its own successful push in its own data dir (P6, F1).
    assert json.loads(paths.pushed_file.read_text(encoding="utf-8")) == {
        ASIN: {"ms": 2000, "at": NEWER}
    }


# --- the port directly -------------------------------------------------------
def test_fake_positions_round_trips_through_its_file(tmp_path: Path):
    port = positions.FakePositions(tmp_path / FAKE_FILE)
    assert port.fetch_batch([ASIN])[ASIN] == {"ms": 0, "updated_at": None}

    port.push(ASIN, positions.FAKE_ACR, 850, updated_at=NEWER)
    assert port.fetch_batch([ASIN])[ASIN] == {"ms": 850, "updated_at": NEWER}
    # A second port over the same file sees the same state.
    again = positions.FakePositions(tmp_path / FAKE_FILE)
    assert again.fetch_batch([ASIN])[ASIN] == {"ms": 850, "updated_at": NEWER}


def test_fake_positions_tolerates_a_corrupt_file(tmp_path: Path):
    path = tmp_path / FAKE_FILE
    path.write_text("not json", encoding="utf-8")
    port = positions.FakePositions(path)
    assert port.fetch_batch([ASIN])[ASIN] == {"ms": 0, "updated_at": None}

    port.push(ASIN, positions.FAKE_ACR, 3, updated_at=NEWER)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        ASIN: {"ms": 3, "updated_at": NEWER}
    }


def test_fake_positions_without_a_path_keeps_state_in_memory():
    port = positions.FakePositions()
    port.push(ASIN, positions.FAKE_ACR, 5, updated_at=NEWER)
    assert port.fetch_batch([ASIN])[ASIN] == {"ms": 5, "updated_at": NEWER}


def test_push_position_against_the_fake_store_honours_staleness(tmp_path: Path):
    port = positions.FakePositions(tmp_path / FAKE_FILE)
    books_dir = tmp_path / "books"

    positions.push_position(
        ASIN, 5000, books_dir=books_dir, port=port, local_updated_at=NEWER
    )
    assert port.fetch_batch([ASIN])[ASIN] == {"ms": 5000, "updated_at": NEWER}

    with pytest.raises(PipelineError) as info:
        positions.push_position(
            ASIN, 1, books_dir=books_dir, port=port, local_updated_at=OLDER
        )
    assert info.value.code == protocol.ErrorCode.STALE
    assert port.fetch_batch([ASIN])[ASIN] == {"ms": 5000, "updated_at": NEWER}

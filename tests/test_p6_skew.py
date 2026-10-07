"""P6 — the clock-skew lockout and this device's own echo (F1, F3).

Audible stamps a push with the **server** clock (ARCHITECTURE 4.6). When this
computer's clock is behind the server by more than the push interval, the
account's copy of our own previous push looks newer than the next listening,
``position-push`` refuses it as ``stale`` and the phone never follows again.
The fix is ``pushed.json``: after a successful write we remember ``{ms, at}``
for that ASIN, and a remote entry whose ``ms`` equals it is our own echo, never
newer. Nothing else changes: another device's position with a different ms and
a newer stamp is still ``stale``.

``--at`` is required (F3); without it the stale check can never fire. The
shared vectors live in ``tests/fixtures/position-vectors.json`` under
``push_decision`` and are asserted here and in ``test_positions_js.py``.

Fake port only; no book, no account and no network. ``conftest`` points HOME
and every XDG variable at temporary dirs, and these tests pass explicit
``tmp_path`` paths.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from omarchy_audible import positions, protocol
from omarchy_audible.errors import PipelineError

ASIN = "B00FAKE01"
OTHER = "B00FAKE02"
# The server clock runs this far ahead of this computer's clock.
SERVER_AHEAD = timedelta(minutes=10)
OWN_ACR = "SKEWACR"


class _SkewPort:
    """A ``PushPort`` whose account clock is ahead of this machine's.

    Every successful push is stored with the account's own stamp, ``at`` plus
    ``SERVER_AHEAD`` — it never passes ``at`` through unchanged.
    """

    def __init__(self, ahead: timedelta = SERVER_AHEAD, acr: str | None = OWN_ACR):
        self.ahead = ahead
        self.acr = acr
        self._store: dict[str, dict] = {}
        self.pushes: list[tuple[str, int]] = []

    def fetch_batch(self, asins):
        return {a: dict(self._store.get(a, positions.empty_entry())) for a in asins}

    def fetch_acr(self, asin):
        return self.acr

    def push(self, asin, acr, position_ms, *, updated_at=None):
        self.pushes.append((asin, position_ms))
        self.store(asin, position_ms, updated_at)

    def store(self, asin: str, ms: int, at: str | None) -> None:
        """Write a position as the account would: stamped with the server clock."""
        listening = positions.parse_updated_at(at) or datetime(2026, 2, 1, tzinfo=UTC)
        stamp = (listening + self.ahead).strftime("%Y-%m-%d %H:%M:%S.0")
        self._store[asin] = {"ms": ms, "updated_at": stamp}

    def remote(self, asin: str) -> dict:
        return dict(self._store.get(asin, positions.empty_entry()))

    def stamp_ms(self, asin: str) -> int | None:
        key = positions.parse_updated_at(self._store[asin]["updated_at"])
        assert key is not None
        return int(key.timestamp() * 1000)


class _FailingPort(_SkewPort):
    """A port whose write always fails, so nothing may be remembered."""

    def push(self, asin, acr, position_ms, *, updated_at=None):
        raise PipelineError(
            protocol.ErrorCode.NETWORK,
            f"could not write the position for {asin}",
            hint="check the network and retry",
        )


def _at(seconds: int) -> str:
    base = datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)
    return (base + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- the acceptance case: the device clock is 10 minutes behind --------------


def test_skew_behind_the_server_keeps_pushing(tmp_path: Path) -> None:
    """Five pushes 60 s apart, each refused-by-old-code, all succeed (F1)."""
    books_dir = tmp_path / "books"
    pushed_path = tmp_path / "pushed.json"
    port = _SkewPort()

    for index in range(5):
        listening_at = _at(60 * index)
        # No exception means no `stale` refusal: the acceptance criterion.
        positions.push_position(
            ASIN,
            1000 * (index + 1),
            books_dir=books_dir,
            port=port,
            local_updated_at=listening_at,
            pushed_path=pushed_path,
        )
        # The account's stamp really is ahead of the listening we just sent.
        assert (
            port.stamp_ms(ASIN)
            > positions.parse_updated_at(listening_at).timestamp() * 1000
        )

    assert port.pushes == [
        (ASIN, 1000),
        (ASIN, 2000),
        (ASIN, 3000),
        (ASIN, 4000),
        (ASIN, 5000),
    ]
    # The last push is what we remember, and it is the account's position.
    assert positions.load_pushed(pushed_path)[ASIN] == {"ms": 5000, "at": _at(240)}
    assert port.remote(ASIN)["ms"] == 5000


def test_a_phone_position_with_a_different_ms_is_still_stale(tmp_path: Path) -> None:
    """The echo rule is narrow: a real other-device position still refuses."""
    books_dir = tmp_path / "books"
    pushed_path = tmp_path / "pushed.json"
    port = _SkewPort()

    positions.push_position(
        ASIN,
        1000,
        books_dir=books_dir,
        port=port,
        local_updated_at=_at(0),
        pushed_path=pushed_path,
    )
    # The phone listened afterwards: a different ms and a newer stamp.
    port.store(ASIN, 5000, "2026-02-01T13:00:00Z")

    with pytest.raises(PipelineError) as info:
        positions.push_position(
            ASIN,
            2000,
            books_dir=books_dir,
            port=port,
            local_updated_at=_at(1800),
            pushed_path=pushed_path,
        )
    assert info.value.code == protocol.ErrorCode.STALE
    assert port.pushes == [(ASIN, 1000)]
    # The refused push left the record alone.
    assert positions.load_pushed(pushed_path)[ASIN]["ms"] == 1000


def test_a_failed_write_records_nothing(tmp_path: Path) -> None:
    books_dir = tmp_path / "books"
    pushed_path = tmp_path / "pushed.json"

    with pytest.raises(PipelineError) as info:
        positions.push_position(
            ASIN,
            1000,
            books_dir=books_dir,
            port=_FailingPort(),
            local_updated_at=_at(0),
            pushed_path=pushed_path,
        )
    assert info.value.code == protocol.ErrorCode.NETWORK
    assert not pushed_path.exists()

    # An older record survives a failed push untouched.
    positions.record_pushed(pushed_path, ASIN, 700, _at(0))
    with pytest.raises(PipelineError):
        positions.push_position(
            ASIN,
            1000,
            books_dir=books_dir,
            port=_FailingPort(),
            local_updated_at=_at(60),
            pushed_path=pushed_path,
        )
    assert positions.load_pushed(pushed_path)[ASIN] == {"ms": 700, "at": _at(0)}


# --- the pure rule -----------------------------------------------------------


@pytest.mark.parametrize(
    ("remote_ms", "own_ms", "expected"),
    [
        (1000, 1000, True),
        (1000, 999, False),
        (1000, 1001, False),
        (0, 0, True),
        (1000, None, False),
    ],
)
def test_own_echo_is_an_exact_ms_match(
    remote_ms: int, own_ms: int | None, expected: bool
) -> None:
    remote = {"ms": remote_ms, "updated_at": "2026-02-01 12:10:00.0"}
    assert positions.is_own_echo(remote, own_ms) is expected


def test_own_echo_rejects_garbage() -> None:
    assert positions.is_own_echo("junk", 1) is False
    assert positions.is_own_echo(None, 1) is False
    assert positions.is_own_echo({"ms": "1000"}, 1000) is False
    assert positions.is_own_echo({"ms": True}, 1) is False


def test_own_echo_never_masks_a_newer_phone_stamp() -> None:
    """Equal ms is ours; a different ms keeps the newest-wins stale rule."""
    remote = {"ms": 1000, "updated_at": "2026-02-01 12:10:00.0"}
    assert positions.push_is_stale(remote, _at(0), 1000) is False
    assert positions.push_is_stale(remote, _at(0), 2000) is True
    assert positions.push_is_stale(remote, _at(0), None) is True


# --- pushed.json itself ------------------------------------------------------


def test_load_pushed_tolerates_a_corrupt_or_foreign_file(tmp_path: Path) -> None:
    path = tmp_path / "pushed.json"
    assert positions.load_pushed(path) == {}

    path.write_text("not json", encoding="utf-8")
    assert positions.load_pushed(path) == {}

    path.write_text(
        json.dumps({"B00FAKE01": {"ms": "x"}, "B00FAKE0 2": 5}), encoding="utf-8"
    )
    assert positions.load_pushed(path) == {}


def test_record_pushed_keeps_the_other_books(tmp_path: Path) -> None:
    path = tmp_path / "pushed.json"
    positions.record_pushed(path, OTHER, 10, _at(0))
    positions.record_pushed(path, ASIN, 20, _at(60))

    assert json.loads(path.read_text(encoding="utf-8")) == {
        ASIN: {"ms": 20, "at": _at(60)},
        OTHER: {"ms": 10, "at": _at(0)},
    }


def test_mark_own_echoes_sets_the_flag_only_where_it_is_true() -> None:
    pushed = {ASIN: {"ms": 1000, "at": _at(0)}}
    items = {
        ASIN: {"ms": 1000, "updated_at": "2026-02-01 12:10:00.0"},
        OTHER: {"ms": 1000, "updated_at": "2026-02-01 12:10:00.0"},
    }
    marked = positions.mark_own_echoes(items, pushed)
    assert marked[ASIN] == {
        "ms": 1000,
        "updated_at": "2026-02-01 12:10:00.0",
        "own": True,
    }
    assert marked[OTHER] == {"ms": 1000, "updated_at": "2026-02-01 12:10:00.0"}
    assert "own" not in marked[OTHER]
    # The input is not modified.
    assert "own" not in items[ASIN]

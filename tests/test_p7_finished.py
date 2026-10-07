"""P7 — F16: the ``finished`` flag stops being sticky.

The ``finished_sequence`` vectors in ``tests/fixtures/position-vectors.json``
pin ``Playback.recordPosition``; the same sequence is then driven through
``Library.buildRows``/``filterRows`` and ``LibraryUi.resumeChoice``, so a book
that was finished and then Started over and listened to returns to In progress
and stops asking Resume / Start over. Both test groups fail on the old
sticky-flag code.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import qjs

VECTORS_PATH = Path(__file__).resolve().parent / "fixtures" / "position-vectors.json"
VECTORS = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
SEQUENCE = VECTORS["finished_sequence"]

ASIN = "B0FAKE0001"
DURATION_MS = SEQUENCE["duration_ms"]
NOW = "2026-10-05T14:00:00.000Z"

CATALOG = [
    {
        "asin": ASIN,
        "title": "The Lighthouse Ledger",
        "runtime_min": DURATION_MS // 60000,
        "percent_complete": 100,
        "is_finished": False,
    }
]


@pytest.fixture(scope="module")
def playback() -> qjs.JsModule:
    return qjs.load("Playback")


@pytest.fixture(scope="module")
def library() -> qjs.JsModule:
    return qjs.load("Library")


@pytest.fixture(scope="module")
def library_ui() -> qjs.JsModule:
    return qjs.load("LibraryUi")


def entry(ms: int, finished: bool) -> dict:
    """A ``state.json`` book entry for the fake book."""
    return {
        "ms": ms,
        "updated_at": NOW,
        "last_played_at": NOW,
        "played_since_download": True,
        "finished": finished,
    }


def record(playback: qjs.JsModule, previous: dict, recorded_ms: int) -> dict:
    state = {"schema": 1, "books": {ASIN: previous}}
    return playback.call("recordPosition", state, ASIN, recorded_ms, NOW)["books"][ASIN]


def rows_for(library: qjs.JsModule, book: dict) -> list[dict]:
    state = {"schema": 1, "books": {ASIN: book}}
    return library.call("buildRows", CATALOG, None, state, None, None)


def in_progress(library: qjs.JsModule, rows: list[dict]) -> list[str]:
    return [row["asin"] for row in library.call("filterRows", rows, "in-progress")]


@pytest.mark.parametrize(
    "case", SEQUENCE["steps"], ids=[case["name"] for case in SEQUENCE["steps"]]
)
def test_record_position_finish_start_over_listen_sequence(
    playback: qjs.JsModule, case: dict
) -> None:
    """F16: finish -> start over -> listen -> pause clears ``finished``."""
    after = record(
        playback,
        entry(case["previous_ms"], case["previous_finished"]),
        case["recorded_ms"],
    )
    assert after["finished"] is case["finished"]
    assert after["ms"] == case["recorded_ms"]


@pytest.mark.parametrize(
    "case", SEQUENCE["trailing"], ids=[case["name"] for case in SEQUENCE["trailing"]]
)
def test_record_position_finish_trailing_boundary(
    playback: qjs.JsModule, case: dict
) -> None:
    """F16: clearing a finished book respects ``FINISH_TRAILING_MS``."""
    after = record(
        playback,
        entry(case["previous_ms"], case["previous_finished"]),
        case["recorded_ms"],
    )
    assert after["finished"] is case["finished"]


def test_a_restarted_book_returns_to_in_progress_and_resumes(
    playback: qjs.JsModule, library: qjs.JsModule, library_ui: qjs.JsModule
) -> None:
    """F16 end to end: the manual-test finding (b) sequence."""
    finished = entry(DURATION_MS, True)
    assert rows_for(library, finished)[0]["isFinished"] is True
    assert in_progress(library, rows_for(library, finished)) == []

    started_over = record(playback, finished, SEQUENCE["steps"][1]["recorded_ms"])
    listened = record(playback, started_over, SEQUENCE["steps"][2]["recorded_ms"])
    assert listened["finished"] is False

    current = rows_for(library, listened)[0]
    assert current["isFinished"] is False
    assert 0 < current["percent"] < 100
    assert in_progress(library, rows_for(library, listened)) == [ASIN]
    assert library_ui.call("resumeChoice", current, DURATION_MS) == "resume"

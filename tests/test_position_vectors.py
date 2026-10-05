"""P4a — the shared position vectors, Python side (ARCHITECTURE 4.6).

``tests/fixtures/position-vectors.json`` is asserted here against
``backend/omarchy_audible/positions.py`` and in ``test_positions_js.py`` against
``qml/lib/Positions.js``. The two implementations must agree case for case, so
this file is the contract that keeps the port honest (PLAN P4a).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from omarchy_audible import positions

VECTORS_PATH = Path(__file__).resolve().parent / "fixtures" / "position-vectors.json"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

VECTORS = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
PARSE_CASES = VECTORS["parse_updated_at"]
MERGE_CASES = VECTORS["merge"]


def to_ms(parsed: datetime | None) -> int | None:
    """A parsed datetime as integer epoch milliseconds, truncating the micros."""
    if parsed is None:
        return None
    delta = parsed - EPOCH
    return delta.days * 86400000 + delta.seconds * 1000 + delta.microseconds // 1000


def test_vector_file_covers_the_required_categories() -> None:
    kinds = {case["kind"] for case in PARSE_CASES}
    assert len(PARSE_CASES) >= 20, "P4a wants at least 20 parse vectors"
    assert {"audible-no-timezone", "utc-z", "offset", "null", "garbage"} <= kinds
    assert any("equal" in case["name"] for case in MERGE_CASES)


def test_merge_vectors_exercise_real_entries() -> None:
    """Guard against hollow vectors where both sides of a case are missing."""
    decided = [case for case in MERGE_CASES if case["expected"]["ms"] > 0]
    assert len(decided) >= 10, "most merge cases must pick a real position"
    both = [case for case in MERGE_CASES if case["local"] and case["remote"]]
    assert len(both) >= 5


@pytest.mark.parametrize("case", PARSE_CASES, ids=[case["name"] for case in PARSE_CASES])
def test_parse_updated_at_matches_the_vector(case: dict) -> None:
    assert to_ms(positions.parse_updated_at(case["value"])) == case["epoch_ms"]


@pytest.mark.parametrize("case", MERGE_CASES, ids=[case["name"] for case in MERGE_CASES])
def test_merge_matches_the_vector(case: dict) -> None:
    assert positions.merge(case["local"], case["remote"]) == case["expected"]

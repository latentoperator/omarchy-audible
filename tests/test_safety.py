"""ARCHITECTURE 4.4: the backend must never mutate the Audible account.

A grep test over the backend package and the stdlib launcher. The single
permitted mutating call is the position write-back (``PUT 1.0/lastpositions/``,
B6); everything else — delete/return endpoints, ``.post``/``.put``/``.patch``
calls — is a build failure.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend" / "omarchy_audible"
LAUNCHER = REPO_ROOT / "bin" / "omarchy-audible"

_MUTATING_METHOD = re.compile(r"\.(put|post|delete|patch)\s*\(", re.IGNORECASE)
_MUTATING_ENDPOINT = re.compile(r"[\"']1\.0/[^\"']*(delete|return|remove)", re.IGNORECASE)
_ALLOWED_MUTATION = "1.0/lastpositions"


def _sources() -> Iterator[Path]:
    yield from sorted(BACKEND_DIR.glob("*.py"))
    yield LAUNCHER


def test_no_mutating_audible_api_calls():
    offenders: list[str] = []
    for path in _sources():
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if _MUTATING_METHOD.search(line) and _ALLOWED_MUTATION not in line:
                offenders.append(f"{path.name}:{number}: {stripped}")
            if _MUTATING_ENDPOINT.search(line):
                offenders.append(f"{path.name}:{number}: {stripped}")
    assert not offenders, "mutating Audible API call(s) found:\n" + "\n".join(offenders)


def test_the_grep_allows_only_the_position_write_back():
    """The allow-list is real: an unrelated mutation in the same shape is caught."""
    assert _MUTATING_METHOD.search(f'client.put("{_ALLOWED_MUTATION}/B00FAKE")')
    offender = 'client.delete("1.0/library/B00FAKE")'
    assert _MUTATING_METHOD.search(offender)
    assert _ALLOWED_MUTATION not in offender

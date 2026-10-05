"""EventLog.js: one-line summaries for the service's event log."""

from __future__ import annotations

import pytest

import qjs


@pytest.fixture(scope="module")
def lib():
    return qjs.load("EventLog")


def test_summarize_truncates(lib):
    out = lib.call("summarize", {"type": "x", "pad": "y" * 500}, 40)
    assert len(out) == 41 and out.endswith("…")


def test_summarize_keeps_short_records(lib):
    assert lib.call("summarize", {"type": "done"}, 40) == '{"type":"done"}'

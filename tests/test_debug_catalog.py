"""DebugCatalog.js: the temporary debug-panel helpers (removed in U1)."""

from __future__ import annotations

import json

import pytest

import qjs


@pytest.fixture(scope="module")
def lib():
    return qjs.load("DebugCatalog")


def test_first_asin(lib):
    text = json.dumps({"books": [{"asin": "B0A"}, {"asin": "B0B"}]})
    assert lib.call("firstAsin", text) == "B0A"


@pytest.mark.parametrize(
    "text",
    ["", "not json", "[]", "{}", '{"books": []}', '{"books": [{"title": "x"}, null]}'],
)
def test_first_asin_is_empty_for_bad_input(lib, text):
    assert lib.call("firstAsin", text) == ""


def test_summarize_truncates(lib):
    out = lib.call("summarize", {"type": "x", "pad": "y" * 500}, 40)
    assert len(out) == 41 and out.endswith("…")

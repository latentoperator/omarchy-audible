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


# ---- B11: the key in a play_info record never reaches the log ----


def test_summarize_redacts_the_lavf_options_value(lib):
    record = {
        "type": "play_info",
        "path": "/b/book.aaxc",
        "chapters_file": "/b/chapters.txt",
        "lavf_options": "audible_key=feedface1234,audible_iv=beefcafe5678",
    }
    out = lib.call("summarize", record, 500)
    assert "feedface1234" not in out
    assert "beefcafe5678" not in out
    assert '"lavf_options":"[redacted]"' in out
    assert '"type":"play_info"' in out


def test_summarize_redacts_lavf_options_at_any_depth(lib):
    record = {"type": "x", "a": {"b": [{"lavf_options": "activation_bytes=00ff00ff"}]}}
    out = lib.call("summarize", record, 500)
    assert "00ff00ff" not in out
    assert out.count("[redacted]") == 1


def test_summarize_redacts_an_empty_lavf_options_too(lib):
    out = lib.call("summarize", {"type": "play_info", "lavf_options": ""}, 500)
    assert '"[redacted]"' in out


def test_summarize_never_throws_on_odd_records(lib):
    for record in (None, 5, "text", [], {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}}):
        assert isinstance(lib.call("summarize", record, 40), str)

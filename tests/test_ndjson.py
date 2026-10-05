"""P1a — ``qml/lib/Ndjson.js``: chunk splitting, parsing, bad lines, outcome.

These run in PySide6's ``QJSEngine`` (the engine Quickshell uses) through the
loader in ``tests/qjs.py``. The backend contract half lives in
``tests/test_ndjson_backend.py``.
"""

from __future__ import annotations

import json

import pytest

import qjs
from omarchy_audible.protocol import ErrorCode

EXPECTED_API = {
    "MAX_BAD_LINE",
    "TERMINAL_TYPES",
    "appendRecord",
    "badLine",
    "classify",
    "createSplitter",
    "feed",
    "finish",
    "flush",
    "isNull",
    "outcome",
    "parseLine",
}

ERROR_CODES = sorted(
    value
    for name, value in vars(ErrorCode).items()
    if not name.startswith("__") and isinstance(value, str)
)


@pytest.fixture(scope="module")
def ndjson() -> qjs.JsModule:
    return qjs.load("Ndjson")


def collect(module: qjs.JsModule, chunks: list[str]) -> tuple[dict, list]:
    """Feed ``chunks`` through one splitter and flush it, like the caller does."""
    splitter = module.hold("createSplitter")
    returned: list = []
    for chunk in chunks:
        returned.extend(module.call("feed", splitter, chunk))
    returned.extend(module.call("flush", splitter))
    return splitter.read(), returned


def test_exports_the_expected_api(ndjson: qjs.JsModule) -> None:
    assert set(ndjson.functions) == EXPECTED_API


def test_blank_and_null_input_never_throws(ndjson: qjs.JsModule) -> None:
    splitter = ndjson.hold("createSplitter")
    assert ndjson.call("feed", splitter, None) == []
    assert ndjson.call("feed", None, "x") == []
    assert ndjson.call("flush", None) == []
    assert ndjson.call("parseLine", None) is None
    assert ndjson.call("parseLine", "   ") is None
    assert collect(ndjson, ["\n", "  \n", "\t\r\n"])[1] == []


# --- chunk boundaries --------------------------------------------------------
def test_a_line_split_across_three_chunks(ndjson: qjs.JsModule) -> None:
    line = json.dumps({"type": "progress", "stage": "download", "bytes": 1, "total": 2}) + "\n"
    parts = [line[:5], line[5:17], line[17:]]
    assert all(parts), "the three parts must all be non-empty"

    state, returned = collect(ndjson, parts)

    assert returned == [{"type": "progress", "stage": "download", "bytes": 1, "total": 2}]
    assert state["events"] == returned
    assert state["buffer"] == ""


def test_partial_chunk_stays_buffered_until_the_newline(ndjson: qjs.JsModule) -> None:
    splitter = ndjson.hold("createSplitter")
    assert ndjson.call("feed", splitter, '{"type":') == []
    assert splitter.read()["buffer"] == '{"type":'
    assert ndjson.call("feed", splitter, '"done"') == []
    assert splitter.read()["buffer"] == '{"type":"done"'
    assert ndjson.call("feed", splitter, "}\n") == [{"type": "done"}]
    assert splitter.read()["buffer"] == ""


def test_several_lines_in_one_chunk(ndjson: qjs.JsModule) -> None:
    chunk = (
        '{"type":"progress","stage":"library","n":1,"of":2}\n'
        '{"type":"progress","stage":"library","n":2,"of":2}\n'
        '{"type":"done"}\n'
    )
    state, returned = collect(ndjson, [chunk])
    assert [record["type"] for record in returned] == ["progress", "progress", "done"]
    assert state["events"] == returned


def test_a_trailing_line_without_a_newline_is_flushed(ndjson: qjs.JsModule) -> None:
    state, returned = collect(ndjson, ['{"type":"done","path":"/tmp/book.m4b"}'])
    assert returned == [{"type": "done", "path": "/tmp/book.m4b"}]
    assert state["events"] == returned
    assert state["buffer"] == ""


def test_flushing_an_empty_buffer_adds_nothing(ndjson: qjs.JsModule) -> None:
    splitter = ndjson.hold("createSplitter")
    ndjson.call("feed", splitter, '{"type":"done"}\n')
    assert ndjson.call("flush", splitter) == []
    assert ndjson.read(splitter)["events"] == [{"type": "done"}]


def test_carriage_return_line_endings_are_tolerated(ndjson: qjs.JsModule) -> None:
    state, returned = collect(ndjson, ['{"type":"done"}\r\n'])
    assert returned == [{"type": "done"}]
    assert state["buffer"] == ""


def test_character_by_character_feed_matches_a_single_chunk(ndjson: qjs.JsModule) -> None:
    stream = (
        '{"type":"status","ready":true,"missing":[],"authenticated":true,'
        '"marketplace":"us","account":"fake@example.com","catalog_age_s":null,'
        '"config_dir":"/tmp/c","data_dir":"/tmp/d","runtime_dir":"/tmp/r",'
        '"books_dir":"/tmp/b"}\n'
        '{"type":"progress","stage":"library","n":1,"of":1}\n'
        '{"type":"done"}\n'
    )
    expected = [json.loads(line) for line in stream.splitlines()]
    assert collect(ndjson, [stream])[1] == expected
    assert collect(ndjson, list(stream))[1] == expected


# --- bad lines ---------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    ["not json at all", '{"type":"do', '{"unterminated":', "}{", "\x00\x01"],
)
def test_non_json_lines_become_a_bad_line(ndjson: qjs.JsModule, text: str) -> None:
    state, returned = collect(ndjson, [text + "\n"])
    assert returned == [{"type": "_bad_line", "line": text}]
    assert state["events"] == returned


@pytest.mark.parametrize("text", ["42", "[1,2]", '"just a string"', "null", "true", '{"nope":1}'])
def test_json_that_is_not_an_event_is_also_a_bad_line(ndjson: qjs.JsModule, text: str) -> None:
    _, returned = collect(ndjson, [text + "\n"])
    assert returned == [{"type": "_bad_line", "line": text}]


def test_a_bad_line_is_truncated_to_two_hundred_characters(ndjson: qjs.JsModule) -> None:
    text = "x" * 500
    _, returned = collect(ndjson, [text + "\n"])
    assert returned == [{"type": "_bad_line", "line": "x" * 200}]
    assert len(returned[0]["line"]) == 200


def test_a_bad_line_does_not_stop_the_stream(ndjson: qjs.JsModule) -> None:
    state, returned = collect(ndjson, ["garbage\n", '{"type":"done"}\n'])
    assert [record["type"] for record in returned] == ["_bad_line", "done"]
    assert state["events"] == returned


# --- classify ----------------------------------------------------------------
@pytest.mark.parametrize(
    "record,expected",
    [
        ({"type": "done"}, "done"),
        ({"type": "error", "code": "network"}, "error"),
        ({"type": "progress", "stage": "download"}, "progress"),
        ({"type": "status", "ready": True}, "other"),
        ({"type": "positions", "items": {}}, "other"),
        ({"type": "_bad_line", "line": "x"}, "other"),
        ({"nope": 1}, "other"),
        (None, "other"),
    ],
)
def test_classify(ndjson: qjs.JsModule, record, expected: str) -> None:
    assert ndjson.call("classify", record) == expected


# --- finish ------------------------------------------------------------------
def test_finish_done(ndjson: qjs.JsModule) -> None:
    outcome = ndjson.call(
        "finish", 0, [{"type": "progress", "stage": "library"}, {"type": "done", "path": "/x"}]
    )
    assert outcome["ok"] is True
    assert outcome["busy"] is False
    assert outcome["code"] is None
    assert outcome["message"] is None
    assert outcome["hint"] is None
    assert outcome["terminal"] == {"type": "done", "path": "/x"}
    assert outcome["exitCode"] == 0
    assert outcome["badLines"] == 0
    assert outcome["mismatch"] is False


def test_finish_error_keeps_code_message_and_hint(ndjson: qjs.JsModule) -> None:
    terminal = {"type": "error", "code": "network", "message": "boom", "hint": "retry"}
    outcome = ndjson.call("finish", 1, [terminal])
    assert outcome["ok"] is False
    assert outcome["busy"] is False
    assert outcome["code"] == "network"
    assert outcome["message"] == "boom"
    assert outcome["hint"] == "retry"
    assert outcome["terminal"] == terminal
    assert outcome["mismatch"] is False


def test_finish_error_without_a_code_falls_back_to_internal(ndjson: qjs.JsModule) -> None:
    outcome = ndjson.call("finish", 1, [{"type": "error", "message": "m"}])
    assert outcome["code"] == "internal"
    assert outcome["message"] == "m"
    assert outcome["hint"] is None


def test_finish_missing_a_terminal_is_internal(ndjson: qjs.JsModule) -> None:
    outcome = ndjson.call("finish", 0, [{"type": "progress", "stage": "library"}])
    assert outcome["ok"] is False
    assert outcome["busy"] is False
    assert outcome["code"] == "internal"
    assert outcome["terminal"] == {
        "type": "error",
        "code": "internal",
        "message": "missing terminal done/error event",
    }
    assert outcome["mismatch"] is True


def test_finish_on_an_empty_stream_is_internal(ndjson: qjs.JsModule) -> None:
    outcome = ndjson.call("finish", 0, [])
    assert outcome["ok"] is False
    assert outcome["code"] == "internal"
    assert outcome["mismatch"] is True


def test_finish_requires_the_terminal_to_be_last(ndjson: qjs.JsModule) -> None:
    outcome = ndjson.call("finish", 0, [{"type": "done"}, {"type": "progress", "stage": "library"}])
    assert outcome["ok"] is False
    assert outcome["code"] == "internal"


def test_finish_exit_three_is_busy(ndjson: qjs.JsModule) -> None:
    outcome = ndjson.call("finish", 3, [{"type": "error", "code": "internal", "message": "held"}])
    assert outcome["busy"] is True
    assert outcome["ok"] is False
    assert outcome["code"] == "busy"


def test_finish_error_code_busy_is_busy(ndjson: qjs.JsModule) -> None:
    outcome = ndjson.call("finish", 1, [{"type": "error", "code": "busy", "message": "held"}])
    assert outcome["busy"] is True
    assert outcome["code"] == "busy"
    assert outcome["mismatch"] is False


def test_finish_exit_three_without_a_terminal_is_busy(ndjson: qjs.JsModule) -> None:
    outcome = ndjson.call("finish", 3, [])
    assert outcome["busy"] is True
    assert outcome["ok"] is False
    assert outcome["code"] == "busy"
    assert outcome["mismatch"] is True


def test_finish_done_with_a_nonzero_exit_is_internal(ndjson: qjs.JsModule) -> None:
    outcome = ndjson.call("finish", 1, [{"type": "done"}])
    assert outcome["ok"] is False
    assert outcome["code"] == "internal"
    assert outcome["mismatch"] is True


def test_finish_error_with_a_zero_exit_is_a_mismatch(ndjson: qjs.JsModule) -> None:
    outcome = ndjson.call("finish", 0, [{"type": "error", "code": "network", "message": "m"}])
    assert outcome["ok"] is False
    assert outcome["code"] == "network"
    assert outcome["mismatch"] is True


def test_finish_counts_bad_lines(ndjson: qjs.JsModule) -> None:
    outcome = ndjson.call(
        "finish",
        0,
        [
            {"type": "_bad_line", "line": "x"},
            {"type": "_bad_line", "line": "y"},
            {"type": "done"},
        ],
    )
    assert outcome["badLines"] == 2
    assert outcome["mismatch"] is False


def test_finish_rejects_a_bad_line_after_the_terminal(ndjson: qjs.JsModule) -> None:
    outcome = ndjson.call("finish", 0, [{"type": "done"}, {"type": "_bad_line", "line": "x"}])
    assert outcome["ok"] is False
    assert outcome["code"] == "internal"
    assert outcome["mismatch"] is True
    assert outcome["badLines"] == 1


def test_finish_ignores_events_that_are_not_objects(ndjson: qjs.JsModule) -> None:
    outcome = ndjson.call("finish", 0, [None, 1, "x", {"type": "done"}])
    assert outcome["ok"] is True


@pytest.mark.parametrize("code", ERROR_CODES)
def test_every_error_code_survives_finish(ndjson: qjs.JsModule, code: str) -> None:
    terminal = {"type": "error", "code": code, "message": "m", "hint": "h"}
    outcome = ndjson.call("finish", 1, [terminal])
    assert outcome["code"] == code
    assert outcome["message"] == "m"
    assert outcome["hint"] == "h"
    assert outcome["ok"] is False
    assert outcome["busy"] is (code == "busy")
    assert outcome["mismatch"] is False

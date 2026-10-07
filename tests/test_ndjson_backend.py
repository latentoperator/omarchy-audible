"""P1a — every fake-mode backend command fed through ``Ndjson.js``.

This is the end-to-end half of the acceptance: it runs every command in the
backend registry in fake mode exactly like ``tests/test_contract.py`` does,
feeds the recorded stdout through a real ``Ndjson.js`` splitter in awkward
chunks, and asserts the parsed stream and the job outcome reproduce the B7
contract (one terminal event, last event terminal, exit code agrees, the error
code survives).
"""

from __future__ import annotations

import json

import pytest

import qjs
from test_contract import CASE_IDS, COMMAND_CASES

# Deliberately uneven, including single characters, so lines are split at
# arbitrary points.
CHUNK_SIZES = (5, 1, 3, 17, 2, 11, 1, 7)
TERMINAL_TYPES = ("done", "error")


def chunked(text: str, sizes: tuple[int, ...] = CHUNK_SIZES) -> list[str]:
    chunks = []
    index = 0
    step = 0
    while index < len(text):
        size = sizes[step % len(sizes)]
        chunks.append(text[index : index + size])
        index += size
        step += 1
    return chunks


@pytest.fixture(scope="module")
def ndjson() -> qjs.JsModule:
    return qjs.load("Ndjson")


@pytest.mark.parametrize("command,args,stdin", COMMAND_CASES, ids=CASE_IDS)
def test_recorded_fake_output_reproduces_the_b7_contract(
    command, args, stdin, run_cli, ndjson: qjs.JsModule
) -> None:
    result = run_cli(command, *args, fake=True, stdin=stdin)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    expected = [json.loads(line) for line in lines]
    assert expected, f"{command}: no events on stdout; stderr={result.stderr!r}"

    # The same bytes parsed as one chunk, as whole lines, and as ragged chunks
    # must produce the same records.
    whole_lines = [line + "\n" for line in lines]
    for strategy in ([result.stdout], whole_lines, chunked(result.stdout)):
        splitter = ndjson.hold("createSplitter")
        for chunk in strategy:
            ndjson.call("feed", splitter, chunk)
        ndjson.call("flush", splitter)
        parsed = ndjson.read(splitter)["events"]
        assert parsed == expected, (
            f"{command}: parsing differed for {len(strategy)} chunks"
        )

    outcome = ndjson.call("finish", result.returncode, expected)

    terminals = [event for event in expected if event["type"] in TERMINAL_TYPES]
    assert len(terminals) == 1, f"{command}: expected exactly one terminal event"
    assert expected[-1]["type"] in TERMINAL_TYPES, (
        f"{command}: last event is not terminal"
    )
    assert outcome["mismatch"] is False
    assert outcome["busy"] is False

    if result.returncode == 0:
        assert expected[-1]["type"] == "done"
        assert outcome["ok"] is True
        assert outcome["code"] is None
    else:
        assert expected[-1]["type"] == "error"
        assert outcome["ok"] is False
        assert outcome["code"] == expected[-1]["code"]

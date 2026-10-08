"""P9 PR 5 — `qml/CatchupFlow.qml` and the read bookkeeping `Catchup.finishRead`.

The reducer is tested through QJSEngine; the rest checks the wiring in the QML, which the QJSEngine
tests can't load. `Service.qml` used to do this bookkeeping inline in its job-finished handler.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

import qjs

REPO = pathlib.Path(__file__).resolve().parent.parent
NOW = 1_000_000


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def function_body(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    depth = 0
    for i in range(source.index("{", start), len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    raise AssertionError(name)


@pytest.fixture(scope="module")
def catchup() -> qjs.JsModule:
    return qjs.load("Catchup")


def result(asin, ms=5_000):
    remote = None if ms is None else {"ms": ms, "updated_at": "2026-10-08T10:00:00Z"}
    return {"asin": asin, "atMs": NOW, "remote": remote}


def state(reads=None, results=None, prefetched=None, waiting=""):
    return {
        "reads": reads or {},
        "results": results or {},
        "prefetched": prefetched,
        "waitingAsin": waiting,
    }


def finish(catchup, st, asin, ok):
    return catchup.call("finishRead", st, asin, ok)


# ---- finishRead ----


def test_a_read_that_finishes_becomes_prefetched(catchup):
    out = finish(catchup, state({"A": True}, {"A": result("A")}), "A", True)
    assert out == {
        "reads": {},
        "results": {},
        "prefetched": result("A"),
        "resume": False,
        "remote": None,
    }


def test_the_waiting_play_pause_resumes_with_the_reads_remote(catchup):
    out = finish(
        catchup, state({"A": True}, {"A": result("A")}, waiting="A"), "A", True
    )
    assert out["resume"] is True
    assert out["remote"] == result("A")["remote"]
    # resumeCaughtUp clears `prefetched` itself; the reducer keeps the result.
    assert out["prefetched"] == result("A")


def test_a_read_with_no_account_position_resumes_in_place(catchup):
    out = finish(
        catchup, state({"A": True}, {"A": result("A", None)}, waiting="A"), "A", True
    )
    assert out["prefetched"] == result("A", None)
    assert out["resume"] is True and out["remote"] is None


def test_a_failed_read_resumes_in_place_and_drops_its_own_stale_result(catchup):
    old = result("A", 1_000)
    out = finish(
        catchup,
        state({"A": True}, {"A": result("A")}, prefetched=old, waiting="A"),
        "A",
        False,
    )
    assert out == {
        "reads": {},
        "results": {},
        "prefetched": None,
        "resume": True,
        "remote": None,
    }


def test_a_fails_while_b_is_prefetched(catchup):
    # Codex R3: a failed read of A never clears B's result, and a ⏯ waiting on
    # B is not resumed by A's read.
    b = result("B", 9_000)
    out = finish(
        catchup,
        state({"A": True}, {"A": result("A")}, prefetched=b, waiting="B"),
        "A",
        False,
    )
    assert out == {
        "reads": {},
        "results": {},
        "prefetched": b,
        "resume": False,
        "remote": None,
    }


def test_a_succeeds_while_b_reads_keeps_bs_read_and_result(catchup):
    b = result("B", 9_000)
    out = finish(
        catchup,
        state({"A": True, "B": True}, {"A": result("A"), "B": b}, waiting="B"),
        "A",
        True,
    )
    assert out["reads"] == {"B": True}
    assert out["results"] == {"B": b}
    assert out["prefetched"] == result("A")
    assert out["resume"] is False


def test_a_read_that_sent_no_positions_record_keeps_nothing(catchup):
    # ok, but no `positions` record arrived: nothing to keep, and B's stays.
    b = result("B")
    out = finish(catchup, state({"A": True}, {}, prefetched=b), "A", True)
    assert out["prefetched"] == b
    out = finish(
        catchup, state({"A": True}, {}, prefetched=result("A"), waiting="A"), "A", True
    )
    assert out["prefetched"] is None
    assert out["resume"] is True and out["remote"] is None


def test_a_cancelled_wait_resumes_nothing(catchup):
    out = finish(catchup, state({"A": True}, {"A": result("A")}, waiting=""), "A", True)
    assert out["resume"] is False and out["prefetched"] == result("A")


def test_the_inputs_are_not_changed(catchup):
    st = state(
        {"A": True, "B": True}, {"A": result("A"), "B": result("B")}, waiting="A"
    )
    out = catchup.evaluate(
        "(function () { var s = "
        + json.dumps(st)
        + "; finishRead(s, 'A', true); return s; })()"
    )
    assert out == st


@pytest.mark.parametrize(
    "st,asin,ok",
    [
        (None, "A", True),
        ("x", "A", True),
        ({}, None, True),
        ({"reads": [1], "results": "x", "prefetched": 3, "waitingAsin": 5}, "A", True),
        (state({"A": True}, {"A": None}), "A", True),
        (state({"A": True}, {"A": "x"}, waiting="A"), "A", True),
    ],
)
def test_bad_input_never_throws(catchup, st, asin, ok):
    out = finish(catchup, st, asin, ok)
    assert set(out) == {"reads", "results", "prefetched", "resume", "remote"}
    assert out["remote"] is None


# ---- wiring ----

MOVED = (
    "pausedAtMs",
    "catchupReads",
    "catchupResults",
    "prefetched",
    "catchupTimer",
    "catchupNoteTimer",
    "function cancelCatchup",
    "function prefetchCatchup",
    "function readCatchup",
    "function resumeCaughtUp",
    "function showCatchupNote",
    "Catchup.",
)


def test_the_service_holds_no_catch_up_state():
    # Fails on the pre-PR-5 Service, which held all of this inline.
    service = read("Service.qml")
    for name in MOVED:
        assert name not in service, name
    assert service.count("CatchupFlow {") == 1
    block = service[service.index("  CatchupFlow {") :]
    block = block[: block.index("\n  }\n") + 1]
    for line in (
        "id: catchupFlow",
        "service: root",
        "player: player",
        "store: store",
        "sync: sync",
    ):
        assert f"    {line}\n" in block, line


def test_the_flow_is_the_only_writer_of_its_state():
    flow = read("qml/CatchupFlow.qml")
    for name in (
        "pausedAtMs",
        "catchupAsin",
        "catchupReads",
        "catchupResults",
        "prefetched",
        "catchupNote",
    ):
        assert re.search(rf"property \w+ {name}:", flow), name
    # Nothing outside the flow assigns its state.
    pattern = re.compile(
        r"\b(?:pausedAtMs|catchupAsin|catchupReads|catchupResults|prefetched|catchupNote)\s*=[^=]"
    )
    others = sorted(REPO.glob("*.qml")) + [
        p for p in (REPO / "qml").rglob("*.qml") if p.name != "CatchupFlow.qml"
    ]
    for path in others:
        assert not pattern.search(path.read_text(encoding="utf-8")), path


def test_the_service_keeps_the_names_views_use():
    service = read("Service.qml")
    assert "readonly property string catchupAsin: catchupFlow.catchupAsin" in service
    assert "readonly property string catchupNote: catchupFlow.catchupNote" in service
    assert "function playPause() { return catchupFlow.press() }" in service
    for view in ("qml/views/MiniView.qml", "qml/views/FullView.qml"):
        text = read(view)
        assert "service.catchupAsin.length > 0" in text, view
        assert "root.service.catchupNote" in text, view
        assert "catchupFlow" not in text, view


def test_the_runner_hands_every_record_and_finish_to_the_flow():
    service = read("Service.qml")
    events = service[service.index("onEvent: function(record, job)") :]
    events = events[: events.index("onJobFinished:")]
    assert "catchupFlow.handleEvent(record, job)" in events
    assert events.index("catchupFlow.handleEvent(") < events.index("sync.handleEvent(")
    finished = service[service.index("onJobFinished: function(job, outcome)") :]
    assert "catchupFlow.handleFinished(job, outcome)" in finished
    assert finished.index("sync.handleFinished(") < finished.index(
        "catchupFlow.handleFinished("
    )
    assert finished.index("catchupFlow.handleFinished(") < finished.index(
        "root.finishPlayInfo("
    )
    flow = read("qml/CatchupFlow.qml")
    event = function_body(flow, "handleEvent")
    assert (
        'if (record.type !== "positions" || job.purpose !== "catchup") return' in event
    )
    assert 'if (job.purpose !== "catchup") return' in function_body(
        flow, "handleFinished"
    )

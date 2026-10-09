"""P5 — ``qml/lib/Ipc.js``: parsing the IPC ``skip`` argument."""

from __future__ import annotations

import pathlib
import re

import pytest

import qjs


@pytest.fixture(scope="module")
def ipc() -> qjs.JsModule:
    return qjs.load("Ipc")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("30", 30),
        ("-15", -15),
        ("+10", 10),
        ("1.5", 1.5),
        ("0", 0),
        (".5", 0.5),
        ("  30  ", 30),
        ("\t-15\n", -15),
        ("008", 8),
    ],
)
def test_good_input(ipc, text, expected):
    assert ipc.call("parseSeconds", text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "abc",
        "NaN",
        "Infinity",
        "-Infinity",
        "0x10",
        "0b10",
        "1.2.3",
        "30s",
        "1e3",
        "+",
        ".",
        None,
        30,
    ],
)
def test_bad_input_is_null(ipc, text):
    assert ipc.call("parseSeconds", text) is None


@pytest.mark.parametrize(
    "text,expected",
    [("86400", 86400), ("-86400", -86400), ("86400.0", 86400.0)],
)
def test_bounds_are_allowed(ipc, text, expected):
    assert ipc.call("parseSeconds", text) == expected


@pytest.mark.parametrize("text", ["86401", "-86401", "86400.5", "-86400.0001"])
def test_over_the_bound_is_null(ipc, text):
    assert ipc.call("parseSeconds", text) is None


# --- H1 F27: test-only methods work only in fake mode -----------------------
REPO = pathlib.Path(__file__).resolve().parent.parent
GATE = "if (!service.fake) return Ipc.DEV_ONLY"


def ipc_methods() -> dict[str, str]:
    """Each IpcHandler method in qml/ServiceIpc.qml and the text of its body."""
    text = (REPO / "qml" / "ServiceIpc.qml").read_text(encoding="utf-8")
    start = text.index("  IpcHandler {")
    end = text.index("\n  }\n", start)
    block = text[start:end]
    found = list(
        re.finditer(r"^    function (\w+)\([^)]*\): string \{", block, re.MULTILINE)
    )
    methods = {}
    for index, match in enumerate(found):
        stop = found[index + 1].start() if index + 1 < len(found) else len(block)
        methods[match.group(1)] = block[match.end() : stop]
    return methods


def test_the_public_and_status_lists(ipc):
    assert ipc.evaluate("DEV_ONLY") == "error: dev only"
    assert ipc.evaluate("PUBLIC_METHODS") == [
        "toggle",
        "openLibrary",
        "playPause",
        "skip",
        "nextChapter",
        "prevChapter",
        "stop",
    ]
    assert ipc.call("isRealModeMethod", "toggle") is True
    assert ipc.call("isRealModeMethod", "stop") is True
    assert ipc.call("isRealModeMethod", "playerStatus") is True
    assert ipc.call("isRealModeMethod", "removeBook") is False
    assert ipc.call("isRealModeMethod", None) is False


def test_every_listed_method_exists(ipc):
    methods = ipc_methods()
    for name in ipc.evaluate("PUBLIC_METHODS") + ipc.evaluate("STATUS_METHODS"):
        assert name in methods, name


def test_stop_is_public_and_uses_the_service_quit_path():
    body = ipc_methods()["stop"]
    assert "Ipc.stopAllowed(player.loaded, player.wanted, player.pendingLoad," in body
    assert 'return "error: nothing loaded"' in body
    assert "service.quitPlayer()" in body
    assert 'return "ok"' in body


@pytest.mark.parametrize(
    "loaded,wanted,pending_load,pending_resume,play_request,allowed",
    [
        (True, False, False, "", None, True),
        (False, True, False, "", None, True),
        (False, False, True, "", None, True),
        (False, False, False, "ASIN", None, True),
        (False, False, False, "", {"asin": "ASIN"}, True),
        (False, False, False, "", None, False),
    ],
)
def test_stop_allowed_covers_loaded_and_pending_playback(
    ipc, loaded, wanted, pending_load, pending_resume, play_request, allowed
):
    assert (
        ipc.call(
            "stopAllowed", loaded, wanted, pending_load, pending_resume, play_request
        )
        is allowed
    )


def test_test_only_methods_are_gated_first(ipc):
    methods = ipc_methods()
    assert len(methods) > 30
    for name, body in methods.items():
        first = body.strip().splitlines()[0].strip().rstrip(";")
        first = first.split(";")[0].strip()
        if ipc.call("isRealModeMethod", name):
            assert GATE not in body, name
        else:
            assert first == GATE, name


def test_the_readme_documents_exactly_the_public_methods(ipc):
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Hotkeys and IPC", 1)[1].split("\n## ", 1)[0]
    documented = re.findall(r"^\| `(\w+)", section, re.MULTILINE)
    assert documented == ipc.evaluate("PUBLIC_METHODS")


def test_library_query_leaves_the_drawer_alone():
    # U10a: the query used to set the drawer's sort, filter and search.
    text = (REPO / "Service.qml").read_text(encoding="utf-8")
    start = text.index("  function libraryQuery(sort, filter, search) {")
    body = text[start : text.index("\n  }\n", start)]
    assert "Library.queryRows(library.allRows, sort, filter, search)" in body
    for name in ("sortKey", "filterKey", "searchText"):
        assert f"library.{name} =" not in body


def test_the_handler_is_the_services_one_child():
    # P9 PR 3: the whole IpcHandler lives in qml/ServiceIpc.qml, declared once
    # in Service.qml with `service: root`. A second handler, or one in the
    # per-monitor widget, would be a duplicate target (SPIKE-RESULTS S6).
    files = sorted(REPO.glob("*.qml")) + sorted((REPO / "qml").rglob("*.qml"))
    handlers = {
        str(p.relative_to(REPO)): p.read_text(encoding="utf-8").count("IpcHandler {")
        for p in files
    }
    assert {name: n for name, n in handlers.items() if n} == {"qml/ServiceIpc.qml": 1}
    text = (REPO / "qml" / "ServiceIpc.qml").read_text(encoding="utf-8")
    assert text.count('target: "latentoperator.audible"') == 1
    service = (REPO / "Service.qml").read_text(encoding="utf-8")
    assert service.count("ServiceIpc {") == 1
    start = service.index("  ServiceIpc {")
    block = service[start : service.index("\n  }\n", start) + 1]
    assert "service: root" in block
    for child in ("library", "player", "runner", "store", "sync"):
        assert f"    {child}: {child}\n" in block, child
    assert "    signin: signinFlow\n" in block
    # No other file declares a second instance (a view or the widget would be
    # created once per monitor).
    instances = {
        str(p.relative_to(REPO)): p.read_text(encoding="utf-8").count("ServiceIpc {")
        for p in files
    }
    assert {name: n for name, n in instances.items() if n} == {"Service.qml": 1}


def test_the_handler_keeps_no_state():
    # Each method calls the service or a child; the only properties are the
    # references Service hands it.
    text = (REPO / "qml" / "ServiceIpc.qml").read_text(encoding="utf-8")
    properties = re.findall(
        r"^\s*(?:readonly\s+)?property\s+\w+\s+(\w+)", text, re.MULTILINE
    )
    assert sorted(properties) == [
        "library",
        "player",
        "runner",
        "service",
        "signin",
        "store",
        "sync",
    ]
    assert "Timer {" not in text and "Process {" not in text
    assert re.search(r"(?<![\w.])root\.", text) is None

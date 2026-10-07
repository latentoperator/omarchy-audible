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
GATE = "if (!root.fake) return Ipc.DEV_ONLY"


def ipc_methods() -> dict[str, str]:
    """Each IpcHandler method in Service.qml and the text of its body."""
    text = (REPO / "Service.qml").read_text(encoding="utf-8")
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
    ]
    assert ipc.call("isRealModeMethod", "toggle") is True
    assert ipc.call("isRealModeMethod", "playerStatus") is True
    assert ipc.call("isRealModeMethod", "removeBook") is False
    assert ipc.call("isRealModeMethod", None) is False


def test_every_listed_method_exists(ipc):
    methods = ipc_methods()
    for name in ipc.evaluate("PUBLIC_METHODS") + ipc.evaluate("STATUS_METHODS"):
        assert name in methods, name


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

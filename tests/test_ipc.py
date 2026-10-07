"""P5 — ``qml/lib/Ipc.js``: parsing the IPC ``skip`` argument."""

from __future__ import annotations

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

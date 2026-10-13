"""``qml/lib/Typing.js``: editing for the bounded text fields.

The plugin's text fields are read-only to Qt so Qt never reads the clipboard
on its own (marketplace review of 0.1.2). Typing, deleting, cutting and
pasting are decided here instead.
"""

from __future__ import annotations

import json

import pytest

import qjs

SHIFT = 0x02000000
CONTROL = 0x04000000
ALT = 0x08000000
META = 0x10000000

KEY_A = 0x41
KEY_C = 0x43
KEY_V = 0x56
KEY_X = 0x58
KEY_Z = 0x5A
KEY_BACKSPACE = 0x01000003
KEY_INSERT = 0x01000006
KEY_DELETE = 0x01000007
KEY_LEFT = 0x01000012
KEY_HOME = 0x01000010
KEY_ESCAPE = 0x01000000
KEY_RETURN = 0x01000004


@pytest.fixture(scope="module")
def typing() -> qjs.JsModule:
    return qjs.load("Typing")


@pytest.mark.parametrize(
    "key,modifiers,text,action",
    [
        # Typing, with and without Shift; AltGr (Control+Alt) types too.
        (0x61, 0, "a", "insert"),
        (0x41, SHIFT, "A", "insert"),
        (0x20, 0, " ", "insert"),
        (0x45, CONTROL | ALT, "€", "insert"),
        # Every paste gesture goes through the bounded helper.
        (KEY_V, CONTROL, "\x16", "paste"),
        (KEY_V, CONTROL | SHIFT, "\x16", "paste"),
        (KEY_V, META, "", "paste"),
        (KEY_INSERT, SHIFT, "", "paste"),
        (KEY_A, CONTROL, "\x01", "select-all"),
        (KEY_X, CONTROL, "\x18", "cut"),
        (KEY_BACKSPACE, 0, "\x08", "backspace"),
        (KEY_DELETE, 0, "\x7f", "delete"),
        # Left to Qt (copy, cursor movement) or the view (Esc, Enter).
        (KEY_C, CONTROL, "\x03", "pass"),
        (KEY_Z, CONTROL, "\x1a", "pass"),
        (KEY_LEFT, 0, "", "pass"),
        (KEY_LEFT, SHIFT, "", "pass"),
        (KEY_HOME, 0, "", "pass"),
        (KEY_ESCAPE, 0, "\x1b", "pass"),
        (KEY_RETURN, 0, "\r", "pass"),
        (KEY_INSERT, 0, "", "pass"),
        (KEY_BACKSPACE, CONTROL, "", "pass"),
        (0x61, ALT, "a", "pass"),
        (0x61, META, "a", "pass"),
        (0x61, 0, "", "pass"),
        (0x61, "bad", None, "pass"),
    ],
)
def test_key_action(typing, key, modifiers, text, action):
    assert typing.call("keyAction", key, modifiers, text) == action


@pytest.mark.parametrize(
    "state,action,value,limit,result",
    [
        # Insert at the cursor, or over the selection.
        ({"text": "ab", "start": 1, "end": 1}, "insert", "x", 10, ("axb", 2)),
        ({"text": "abcd", "start": 1, "end": 3}, "insert", "x", 10, ("axd", 2)),
        ({"text": "abcd", "start": 3, "end": 1}, "insert", "x", 10, ("axd", 2)),
        # Too long is refused whole, never cut short.
        ({"text": "abc", "start": 3, "end": 3}, "insert", "d", 3, None),
        ({"text": "abc", "start": 0, "end": 3}, "paste", "wxyz", 3, None),
        ({"text": "abc", "start": 0, "end": 3}, "paste", "xyz", 3, ("xyz", 3)),
        # Pasted text is made one line.
        (
            {"text": "", "start": 0, "end": 0},
            "paste",
            "\na\r\nb\tc\n",
            20,
            ("a b c", 5),
        ),
        ({"text": "", "start": 0, "end": 0}, "paste", "a\x00\x07b", 20, ("ab", 2)),
        ({"text": "", "start": 0, "end": 0}, "paste", "\n\n", 20, None),
        ({"text": "", "start": 0, "end": 0}, "paste", None, 20, None),
        # Backspace and Delete, at the edges, and over a selection.
        ({"text": "abc", "start": 2, "end": 2}, "backspace", "", 10, ("ac", 1)),
        ({"text": "abc", "start": 0, "end": 0}, "backspace", "", 10, None),
        ({"text": "abc", "start": 1, "end": 1}, "delete", "", 10, ("ac", 1)),
        ({"text": "abc", "start": 3, "end": 3}, "delete", "", 10, None),
        ({"text": "abcd", "start": 1, "end": 3}, "backspace", "", 10, ("ad", 1)),
        ({"text": "abcd", "start": 1, "end": 3}, "delete", "", 10, ("ad", 1)),
        # Cut needs a selection.
        ({"text": "abcd", "start": 1, "end": 3}, "cut", "", 10, ("ad", 1)),
        ({"text": "abcd", "start": 2, "end": 2}, "cut", "", 10, None),
        # Positions out of range are clamped; a bad state is an empty field.
        ({"text": "ab", "start": -5, "end": 99}, "insert", "x", 10, ("x", 1)),
        (None, "insert", "x", 10, ("x", 1)),
        ({"text": "ab", "start": 1, "end": 1}, "nonsense", "x", 10, None),
    ],
)
def test_apply(typing, state, action, value, limit, result):
    got = typing.call("apply", state, action, value, limit)
    if result is None:
        assert got is None
    else:
        assert got == {"text": result[0], "cursor": result[1]}


def test_backspace_and_delete_keep_emoji_whole(typing):
    book = "a\U0001f4dab"  # "a📚b": the emoji is two UTF-16 units
    assert typing.call(
        "apply", {"text": book, "start": 3, "end": 3}, "backspace", "", 9
    ) == {
        "text": "ab",
        "cursor": 1,
    }
    assert typing.call(
        "apply", {"text": book, "start": 1, "end": 1}, "delete", "", 9
    ) == {
        "text": "ab",
        "cursor": 1,
    }


@pytest.mark.parametrize(
    "output,text",
    [
        (json.dumps({"text": "Dune"}), "Dune"),
        (
            json.dumps({"text": "caf\u00e9 \U0001f4da"}, ensure_ascii=True),
            "caf\u00e9 \U0001f4da",
        ),
        (json.dumps({"text": ""}), None),
        (json.dumps({"text": 5}), None),
        (json.dumps(["Dune"]), None),
        ("Dune", None),
        ("", None),
        (None, None),
    ],
)
def test_paste_result(typing, output, text):
    assert typing.call("pasteResult", output) == text


def test_paste_result_ignores_output_past_its_bound(typing):
    limit = typing.evaluate("PASTE_OUTPUT_MAX")
    padded = json.dumps({"text": "x"}) + " " * limit
    assert typing.call("pasteResult", padded) is None


def test_paste_command_and_limits(typing):
    assert typing.call("pasteCommand", "/p/bin/omarchy-audible-paste", 1024) == [
        "/p/bin/omarchy-audible-paste",
        "--max-bytes",
        "1024",
        "--timeout",
        "2",
    ]
    # The sign-in field fits Amazon's page address (about 1,500 characters).
    assert typing.evaluate("SIGNIN_MAX_CHARS") >= 4096
    assert typing.evaluate("SIGNIN_PASTE_BYTES") >= typing.evaluate("SIGNIN_MAX_CHARS")
    assert typing.evaluate("SEARCH_PASTE_BYTES") >= typing.evaluate("SEARCH_MAX_CHARS")
    # Every limit stays under the helper's own ceiling (64 KiB, 5 s).
    for name in ("SEARCH_PASTE_BYTES", "SIGNIN_PASTE_BYTES"):
        assert typing.evaluate(name) <= 65536
    assert typing.evaluate("PASTE_TIMEOUT_S") <= 5

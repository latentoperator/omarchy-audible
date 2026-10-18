"""The plugin's text fields never let Qt read the clipboard.

Marketplace review of 0.1.2: Qt 6.12 reads the clipboard by itself, inside the
shared shell and with no size limit or deadline, whenever an editable text
field exists and the clipboard changes, and on every paste. A clipboard owner
that keeps streaming could stall the shell or use up its memory.

The fix: every field is ``components/BoundedTextField.qml``, read-only to Qt
for its whole life, with typing done by ``Typing.js`` and pasting by the
bounded ``bin/omarchy-audible-paste``. The source checks keep it that way; the
harness drives the real component in a headless Qt window.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIELD = REPO / "qml" / "components" / "BoundedTextField.qml"
HELPER = REPO / "bin" / "omarchy-audible-paste"

# Editable Qt text types, as a QML object declaration.
EDITORS = re.compile(
    r"^\s*(?:[\w.]+\.)?(TextField|TextInput|TextArea|TextEdit)\s*\{", re.MULTILINE
)

_STUBS = {
    "qs/Commons/qmldir": "module qs.Commons\nsingleton Style 1.0 Style.qml\n",
    "qs/Commons/Style.qml": """pragma Singleton
import QtQml
QtObject {
  readonly property QtObject spacing: QtObject { readonly property int hairline: 1 }
}
""",
    "qs/Ui/qmldir": "module qs.Ui\nTextField 1.0 TextField.qml\n",
    # As the shell's qs.Ui.TextField: a Controls TextField with `password`.
    "qs/Ui/TextField.qml": """import QtQuick
import QtQuick.Controls.Basic as Basic
Basic.TextField {
  property bool password: false
  echoMode: password ? TextInput.Password : TextInput.Normal
}
""",
    "Quickshell/Io/qmldir": (
        "module Quickshell.Io\n"
        "Process 1.0 Process.qml\n"
        "SplitParser 1.0 SplitParser.qml\n"
        "singleton Hub 1.0 Hub.qml\n"
    ),
    "Quickshell/Io/Hub.qml": """pragma Singleton
import QtQml
QtObject { property var processes: [] }
""",
    "Quickshell/Io/Process.qml": """import QtQml
QtObject {
  id: process
  property var command: []
  property bool running: false
  property QtObject stdout: null
  signal exited(int code, int status)
  function finish(code) { running = false; exited(code, 0) }
  Component.onCompleted: Hub.processes = Hub.processes.concat([process])
}
""",
    "Quickshell/Io/SplitParser.qml": """import QtQml
QtObject {
  property string splitMarker: "\\n"
  signal read(string data)
}
""",
}


def qml_sources() -> list[Path]:
    return [
        REPO / "Service.qml",
        REPO / "BarWidget.qml",
        *sorted((REPO / "qml").rglob("*.qml")),
    ]


def test_the_only_editable_text_type_is_the_bounded_field():
    # `qs.Ui.TextField` and Qt's own types, anywhere in the plugin's QML.
    found = {}
    for path in qml_sources():
        for match in EDITORS.finditer(path.read_text(encoding="utf-8")):
            found.setdefault(str(path.relative_to(REPO)), []).append(match.group(1))
    assert found == {"qml/components/BoundedTextField.qml": ["TextField"]}


def test_both_fields_are_bounded_and_pass_keys_through_edit_key():
    for rel, name, chars, paste in (
        (
            "qml/views/LibraryView.qml",
            "search",
            "SEARCH_MAX_CHARS",
            "SEARCH_PASTE_BYTES",
        ),
        (
            "qml/views/OnboardingView.qml",
            "paste",
            "SIGNIN_MAX_CHARS",
            "SIGNIN_PASTE_BYTES",
        ),
    ):
        view = (REPO / rel).read_text(encoding="utf-8")
        assert view.count("BoundedTextField {") == 1, rel
        block = view[view.index("BoundedTextField {") :]
        block = block[: block.index("Keys.onPressed")]
        assert f"id: {name}\n" in block, rel
        assert f"maxChars: Typing.{chars}\n" in block, rel
        assert f"pasteBytes: Typing.{paste}\n" in block, rel
        assert f"else if (!{name}.editKey(event)) return" in view, rel
        assert "readOnly" not in view, rel


def test_the_field_is_never_editable_to_qt():
    field = FIELD.read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", field)
    assert re.findall(r"\breadOnly\b[^\n]*", code) == ["readOnly: true"]
    # No code path pastes through Qt or makes the field editable.
    assert ".paste()" not in code and "paste()" not in code.replace(
        "pasteClipboard()", ""
    )
    assert "Typing.pasteCommand(pasteHelper, pasteBytes)" in code
    assert '"../../bin/omarchy-audible-paste"' in code
    assert HELPER.is_file()


@pytest.fixture(scope="module")
def observed(tmp_path_factory) -> dict:
    stubs = tmp_path_factory.mktemp("field-stubs")
    for relative, text in _STUBS.items():
        target = stubs / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("field_harness.py")), str(stubs)],
        env={
            **os.environ,
            "HOME": str(stubs),
            "XDG_CONFIG_HOME": str(stubs / "config"),
            "XDG_DATA_HOME": str(stubs / "data"),
            "TMPDIR": str(stubs),
            "OMARCHY_AUDIBLE_FAKE": "1",
            "QT_QPA_PLATFORM": "offscreen",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_field_loads_cleanly(observed):
    assert observed["warnings"] == []
    assert observed["focused"] is True


def test_qt_never_sees_an_editable_field(observed):
    # Qt computes canPaste, reading the clipboard, only for an editable field.
    assert observed["readOnly"] is True
    assert observed["readOnly_end"] is True
    assert observed["canPaste_start"] is False
    assert observed["canPaste_after_change"] is False
    # An ordinary editable field in the same window did read the clipboard.
    assert observed["control_canPaste"] is True
    assert observed["password_readOnly"] is True
    assert observed["password_canPaste"] is False


def test_typing_still_works(observed):
    assert observed["typed"] == "Dune"
    assert observed["backspace"] == "Dun"
    assert observed["left_delete"] == "Du"
    # Left puts the cursor before "n"; Delete removes it; "n" goes back.
    assert observed["insert_middle"] == "Dun"
    assert observed["select_all_replace"] == "x"
    # maxChars is 12: the key that would make 13 is refused.
    assert observed["capped"] == "xabcdefghijk"


def test_paste_goes_only_through_the_bounded_helper(observed):
    # Ctrl+V pasted nothing from Qt's clipboard; it started the helper.
    assert observed["after_ctrl_v"] == "x"
    # One Process per field; only the focused field's was started.
    assert observed["process_count"] == 2
    assert observed["started_count"] == 1
    assert observed["command"] == [
        str(HELPER),
        "--max-bytes",
        "64",
        "--timeout",
        "2",
    ]
    assert observed["running"] is True
    # A second paste while one runs starts nothing.
    assert observed["second_paste_while_running"] == "x"
    # The helper's text is inserted at the cursor, made one line.
    assert observed["pasted"] == "xa b"
    # A paste that would pass maxChars is dropped whole; a bad line is ignored.
    assert observed["over_limit_paste"] == "xa b"
    assert observed["bad_line"] == "xa b"


@pytest.mark.parametrize(
    "name,reason",
    [
        ("no_owner", "unavailable"),
        ("failed_start", "unavailable"),
        ("missing_tool", "unavailable"),
        ("too_large", "too large"),
        ("timeout", "timed out"),
        ("malformed", "unavailable"),
        ("empty", "unavailable"),
        ("over_chars", "too large"),
        ("failed_with_output", "unavailable"),
        ("multiple", "unavailable"),
        ("watchdog", "timed out"),
        ("watchdog_pending", "timed out"),
    ],
)
def test_failed_replacement_keeps_input_and_explains_without_secrets(
    observed, name, reason
):
    result = observed["paste_cases"][name]
    assert result["started_text"] == result["before_exit"] == result["text"] == "keep"
    assert reason in result["error"].lower()
    assert "retry" in result["error"].lower()
    assert "SYNTHETIC_PRIVATE_INPUT" not in result["error"]
    assert result["pending_cleared"]
    assert result["pasting"] is False
    if name.startswith("watchdog"):
        assert result["stopped"]
        assert result["overlapping_paste"] is False


@pytest.mark.parametrize("name", ["success", "late_success"])
def test_success_replaces_only_after_valid_helper_exit(observed, name):
    result = observed["paste_cases"][name]
    assert result["started_text"] == result["before_exit"] == "keep"
    assert result["text"] == "new"
    assert result["error"] == ""
    assert result["pending_cleared"]


def test_oversized_edit_explains_without_erasing(observed):
    assert observed["edit_limit_text"] == "abcdefghijkl"
    assert "too large" in observed["edit_limit_error"].lower()


def test_paste_button_requests_atomic_replacement_and_views_display_errors():
    onboarding = (REPO / "qml/views/OnboardingView.qml").read_text()
    button = onboarding.split('text: "Paste from clipboard"', 1)[1].split(
        "Button {", 1
    )[0]
    assert 'paste.text = ""' not in button
    assert "paste.pasteClipboard(true)" in button
    for relative, name in (
        ("qml/views/OnboardingView.qml", "paste"),
        ("qml/views/LibraryView.qml", "search"),
    ):
        source = (REPO / relative).read_text()
        blocks = re.findall(r"Text\s*\{[^{}]*" + name + r"\.pasteError[^{}]*\}", source)
        assert len(blocks) == 1
        assert "textFormat: Text.PlainText" in blocks[0]
        assert "wrapMode: Text.WordWrap" in blocks[0]
        assert "color: Commons.Color.urgent" in blocks[0]


def test_middle_click_pastes_nothing(observed):
    assert observed["middle_click"] == "xa b"


def test_cut_copies_except_from_a_password_field(observed):
    assert observed["cut_text"] == "keep"
    assert observed["cut_clipboard"] == " cut"
    assert observed["password_cut_text"] == "secret"
    assert observed["password_cut_clipboard"] == "unchanged"

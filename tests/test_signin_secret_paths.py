"""U3 — the pasted sign-in text never reaches a log line, an event, a file,
a service property or ``recentEvents`` (brief M3-laptop §4 U3, ARCHITECTURE 4.7).

The paste goes: the view's password field → ``service.finishLogin(pasted)``
(a one-line forwarder) → ``signinFlow.finishLogin(pasted)`` in
``qml/SigninFlow.qml`` (P9 PR 6) → ``Onboarding.looksLikeRedirect`` (a
boolean) and
``runner.runWithInput(...)`` → ``JobRunner.inputs`` (in memory, by id) →
``BackendCall.input`` → the process's stdin, which is then closed. These
checks read the QML and fail if any other use of those names appears.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def function_body(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    depth = 0
    for index in range(source.index("{", start), len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unbalanced {name}")


def test_view_uses_the_field_text_only_to_send_or_clear():
    view = read("qml/views/OnboardingView.qml")
    uses = re.findall(r"paste\.text[^\n]*", view)
    allowed = {
        'paste.text = ""',
        'paste.text = "" }',
        "paste.text)",
    }
    assert uses, "the paste field is gone?"
    for use in uses:
        assert use.strip() in allowed, f"unexpected use of the pasted text: {use!r}"
    assert "password: true" in view
    # The field pastes into itself through its bounded helper, so another
    # monitor's field never holds the text, and every view clears on
    # clearPaste.
    assert 'function onClearPaste() { paste.text = "" }' in view
    assert "paste.pasteClipboard(true)" in view
    assert "readClipboard" not in view and "onClipboardRead" not in view


def test_service_passes_the_paste_only_to_the_check_and_stdin():
    service = read("qml/SigninFlow.qml")
    body = function_body(service, "finishLogin")
    uses = re.findall(r"\bpasted\b", body)
    # parameter, the blank check, looksLikeRedirect(pasted), runWithInput(..., pasted)
    assert len(uses) == 4, body
    assert 'pasteEmpty = !/\\S/.test(pasted || "")' in body
    assert "Onboarding.looksLikeRedirect(pasted)" in body
    assert (
        'runner.runWithInput("login-finish", ["--session", loginSession], "login", pasted)'
        in body
    )
    assert "logEvent" not in body
    # Sending clears every view's field at once.
    assert "clearPaste()" in body
    assert "clearPaste()" in function_body(service, "cancelLogin")
    # The paste never becomes a property of the service.
    assert not re.search(r"property \w+ pasted", service)


def test_clipboard_text_goes_only_into_the_field():
    # The bounded paste (BoundedTextField.qml) hands the helper's line to
    # Typing.pasteResult and holds one bounded value in this field until
    # helper exit. It is never logged or passed to another object.
    field = read("qml/components/BoundedTextField.qml")
    paster = field[field.index("id: paster") :]
    paster = paster[: paster.index("\n  }\n")]
    assert "SplitParser" in paster and "StdioCollector" not in paster
    handler = paster[paster.index("onRead: function(line)") :]
    assert re.findall(r"\bline\b", handler)[:2] == ["line", "line"]
    assert "var value = Typing.pasteResult(line)" in handler
    assert "else root._pasteValue = value" in handler
    assert "root.edit(" not in handler
    assert "property var _pasteValue: null" in field
    finish = function_body(field, "finishPaste")
    assert finish.index("var value = _pasteValue") < finish.index("_pasteValue = null")
    assert finish.index("_pasteValue = null") < finish.index("text = next.text")
    assert "_pasteValue = null" in function_body(field, "pasteClipboard")
    watchdog = field.split("id: watchdog", 1)[1].split("Process {", 1)[0]
    assert "root._pasteValue = null" in watchdog
    # The bounded temporary value has no other sink or property copy.
    uses = re.findall(r"[^\n]*_pasteValue[^\n]*", field)
    assert all(
        line.strip()
        in {
            "property var _pasteValue: null",
            "var value = _pasteValue",
            "_pasteValue = null",
            "root._pasteValue = null",
            "if (root._pasteInvalid || root._pasteValue !== null || value === null) {",
            "} else root._pasteValue = value",
        }
        for line in uses
    ), uses
    assert "console." not in field and "logEvent" not in field
    assert not re.search(r"property \w+ (pasted|clip|value)", field)
    # Nothing else reads the clipboard: the old shared `paster` is gone.
    for rel in ("Service.qml", "qml/SigninFlow.qml", "qml/views/OnboardingView.qml"):
        text = read(rel)
        for name in ("wl-paste", "readClipboard", "clipboardRead", "clipboardTarget"):
            assert name not in text, (rel, name)


def test_no_log_line_mentions_the_input():
    for rel in (
        "Service.qml",
        "qml/SigninFlow.qml",
        "qml/ServiceIpc.qml",
        "qml/JobRunner.qml",
        "qml/BackendCall.qml",
    ):
        source = read(rel)
        for line in re.findall(r"logEvent\([^\n]*", source):
            assert "pasted" not in line and "input" not in line, (rel, line)


def test_onboarding_events_are_logged_by_type_only():
    service = read("Service.qml")
    assert "Signin.logText(job.command, record.type," in service
    assert (
        'Signin.isOnboardingCommand(job.command) ? "" : EventLog.summarize(record, 160)'
        in service
    )


def test_runner_keeps_input_out_of_job_objects():
    runner = read("qml/JobRunner.qml")
    uses = re.findall(r"inputs\[[^\n]*", runner)
    assert len(uses) == 4, uses  # store, presence check, read on spawn, delete
    spawn = function_body(runner, "spawn")
    # The runner's copy is dropped as soon as the process has its own.
    assert spawn.index('"input": hasInput') < spawn.index("root.dropInput(job)")
    # A busy retry whose input is gone fails instead of sending nothing.
    assert "Signin.inputLost(job, root.inputs)" in function_body(runner, "pump")
    body = function_body(runner, "runWithInput")
    assert "queued.inputId = root.nextInputId++" in body
    assert "queued.input " not in body and "job.input " not in runner


def test_backend_call_writes_then_clears_and_closes_stdin():
    call = read("qml/BackendCall.qml")
    started = call[call.index("onStarted: {") :]
    started = started[: started.index("\n    }\n")]
    assert "write(root.input)" in started
    assert (
        started.index("write(root.input)")
        < started.index('root.input = ""')
        < started.index("stdinEnabled = false")
    )
    # The input is never handed to the record/stderr paths.
    assert len(re.findall(r"root\.input\b", call)) == 2


def test_login_finish_text_never_in_argv():
    for rel in ("Service.qml", "qml/SigninFlow.qml", "qml/ServiceIpc.qml"):
        source = read(rel)
        for call in re.findall(r'run\("login-finish"[^\n]*', source):
            raise AssertionError(
                f"login-finish must go through runWithInput: {rel}: {call}"
            )


# ---- the Service / SigninFlow boundary (P9 PR 6) ----


def test_service_forwarders_hand_the_paste_straight_to_the_flow():
    service = read("Service.qml")
    # The one place the pasted text crosses the boundary: an argument passed
    # on unchanged, never stored, logged or put in argv.
    assert (
        "function finishLogin(pasted) { return signinFlow.finishLogin(pasted) }"
        in service
    )
    assert len(re.findall(r"\bpasted\b", service)) == 2
    assert not re.search(r"property \w+ pasted", service)
    # Nothing on the Service runs login-finish or reads the clipboard itself.
    for name in ("runWithInput", "wl-paste", "SplitParser", "clipboardTarget"):
        assert name not in service, name


def test_service_re_sends_only_the_clear_signal():
    service = read("Service.qml")
    assert "signal clearPaste()" in service
    block = service[service.index("  SigninFlow {") :]
    block = block[: block.index("\n  }\n") + 1]
    assert "onClearPaste: root.clearPaste()" in block
    assert "Clipboard" not in block


KEPT = {
    "reconnecting",
    "authFailed",
    "marketplace",
    "onboardingError",
    "clipboardNotice",
    "pasteRejected",
    "pasteEmpty",
    "onboardingStep",
    "loginPhase",
    "settingUp",
}


def test_no_service_property_copies_paste_or_clipboard_text():
    # Every sign-in property the Service keeps is a binding or alias to one of
    # the flow's own; none of them holds text from the field or the clipboard.
    service = read("Service.qml")
    kept = re.findall(
        r"^  (?:readonly )?property (?:\w+) (\w+): signinFlow\.(\w+)$",
        service,
        re.MULTILINE,
    )
    assert {name for name, _ in kept} == KEPT
    assert all(name == target for name, target in kept), kept
    flow = read("qml/SigninFlow.qml")
    # The copier's `text` is the install command the view copies, cleared as
    # soon as wl-copy has it; it is not the paste.
    assert flow.count('property string text: ""') == 1
    assert "copier.text = String(text)" in function_body(flow, "copyText")
    assert not re.search(
        r"property \w+ (?:pasted|text|chunk)\b",
        flow.replace('property string text: ""', ""),
    )
    # Only booleans describe the paste in the flow.
    assert "property bool pasteRejected: false" in flow
    assert "property bool pasteEmpty: false" in flow

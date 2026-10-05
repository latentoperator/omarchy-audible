"""U3 — the pasted sign-in text never reaches a log line, an event, a file,
a property or ``recentEvents`` (brief M3-laptop §4 U3, ARCHITECTURE 4.7).

The paste goes: the view's password field → ``service.finishLogin(pasted)``
→ ``Onboarding.looksLikeRedirect`` (a boolean) and
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
                return source[start:index + 1]
    raise AssertionError(f"unbalanced {name}")


def test_view_uses_the_field_text_only_to_send_or_clear():
    view = read("qml/views/OnboardingView.qml")
    uses = re.findall(r"paste\.text[^\n]*", view)
    allowed = {
        'paste.text = ""',
        "paste.text += chunk }",
        'paste.text) === "ok") paste.text = ""',
    }
    assert uses, "the paste field is gone?"
    for use in uses:
        assert use.strip() in allowed, f"unexpected use of the pasted text: {use!r}"
    assert "password: true" in view


def test_service_passes_the_paste_only_to_the_check_and_stdin():
    service = read("Service.qml")
    body = function_body(service, "finishLogin")
    uses = re.findall(r"\bpasted\b", body)
    # parameter, looksLikeRedirect(pasted), runWithInput(..., pasted)
    assert len(uses) == 3, body
    assert "Onboarding.looksLikeRedirect(pasted)" in body
    assert 'runner.runWithInput("login-finish", ["--session", loginSession], "login", pasted)' in body
    assert "logEvent" not in body
    # The paste never becomes a property of the service.
    assert not re.search(r"property \w+ pasted", service)


def test_clipboard_text_is_streamed_not_stored():
    service = read("Service.qml")
    paster = service[service.index("id: paster"):]
    paster = paster[:paster.index("\n  }\n")]
    assert "SplitParser" in paster and "StdioCollector" not in paster
    assert "root.clipboardRead(chunk)" in paster
    assert re.search(r"signal clipboardRead\(string text\)", service)


def test_no_log_line_mentions_the_input():
    for rel in ("Service.qml", "qml/JobRunner.qml", "qml/BackendCall.qml"):
        source = read(rel)
        for line in re.findall(r"logEvent\([^\n]*", source):
            assert "pasted" not in line and "input" not in line, (rel, line)


def test_onboarding_events_are_logged_by_type_only():
    service = read("Service.qml")
    assert "Signin.logText(job.command, record.type," in service
    assert 'Signin.isOnboardingCommand(job.command) ? "" : EventLog.summarize(record, 160)' in service


def test_runner_keeps_input_out_of_job_objects():
    runner = read("qml/JobRunner.qml")
    uses = re.findall(r"inputs\[[^\n]*", runner)
    assert len(uses) == 4, uses  # store, presence check, read on spawn, delete
    body = function_body(runner, "runWithInput")
    assert "queued.inputId = root.nextInputId++" in body
    assert "queued.input " not in body and "job.input " not in runner


def test_backend_call_writes_then_clears_and_closes_stdin():
    call = read("qml/BackendCall.qml")
    started = call[call.index("onStarted: {"):]
    started = started[:started.index("\n    }\n")]
    assert "write(root.input)" in started
    assert started.index("write(root.input)") < started.index('root.input = ""') < started.index("stdinEnabled = false")
    # The input is never handed to the record/stderr paths.
    assert len(re.findall(r"root\.input\b", call)) == 2


def test_login_finish_text_never_in_argv():
    service = read("Service.qml")
    for call in re.findall(r'run\("login-finish"[^\n]*', service):
        raise AssertionError(f"login-finish must go through runWithInput: {call}")

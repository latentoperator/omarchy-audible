"""P9 PR 6 — `qml/SigninFlow.qml`: onboarding, sign-in and the clipboard.

A move with no new behaviour, so these check the wiring: the flow owns the
state and is its only writer, the Service keeps the names the views use, and
the job runner hands records and finishes to the flow. The pasted text's path
is `test_signin_secret_paths.py`.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent


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


STATE = (
    "reconnecting",
    "authFailed",
    "loginSession",
    "marketplace",
    "onboardingError",
    "clipboardNotice",
    "pasteRejected",
    "pasteEmpty",
    "loginStarting",
    "clipboardTarget",
)

MOVED = (
    "loginSession",
    "loginStarting",
    "clipboardTarget",
    "id: opener",
    "id: copier",
    "id: paster",
    "xdg-open",
    "wl-copy",
    "wl-paste",
    "function openUrl",
    "function onboardingFinished",
    "Onboarding.errorText",
    "Onboarding.clipboardNotice",
    "Onboarding.looksLikeRedirect",
    "browser not opened",
)


def test_the_service_holds_no_sign_in_state():
    # Fails on the pre-PR-6 Service, which held all of this inline.
    service = read("Service.qml")
    for name in MOVED:
        assert name not in service, name
    assert service.count("SigninFlow {") == 1
    block = service[service.index("  SigninFlow {") :]
    block = block[: block.index("\n  }\n") + 1]
    for line in ("id: signinFlow", "service: root", "runner: runner"):
        assert f"    {line}\n" in block, line


def test_the_flow_declares_its_state_and_processes():
    flow = read("qml/SigninFlow.qml")
    for name in STATE:
        assert re.search(rf"property \w+ {name}:", flow), name
    for name in ("onboardingStep", "loginPhase", "settingUp"):
        assert re.search(rf"readonly property \w+ {name}:", flow), name
    for name in ("opener", "copier", "paster"):
        assert f"id: {name}" in flow, name
    for name in (
        "checkStatus",
        "startSetup",
        "startLogin",
        "finishLogin",
        "cancelLogin",
        "importCliLogin",
        "disconnect",
        "reconnect",
        "openUrl",
        "copyText",
        "readClipboard",
        "onboardingFinished",
        "handleEvent",
        "handleFinished",
    ):
        assert f"function {name}(" in flow, name


def test_the_flow_is_the_only_writer_of_its_state():
    names = "|".join(STATE)
    pattern = re.compile(rf"\b(?:{names})\s*=[^=]")
    others = sorted(REPO.glob("*.qml")) + [
        p for p in (REPO / "qml").rglob("*.qml") if p.name != "SigninFlow.qml"
    ]
    # The views assign two of them through the Service's aliases, as they
    # did before the split: the store picker and the notice's dismiss.
    allowed = {
        "OnboardingView.qml": "root.service.marketplace = value",
        "LibraryView.qml": 'root.service.clipboardNotice = ""',
    }
    for path in others:
        text = path.read_text(encoding="utf-8")
        if path.name in allowed:
            assert text.count(allowed[path.name]) == 1, path
            text = text.replace(allowed[path.name], "")
        assert not pattern.search(text), (path, pattern.search(text))
    service = read("Service.qml")
    assert "property alias marketplace: signinFlow.marketplace" in service
    assert "property alias clipboardNotice: signinFlow.clipboardNotice" in service


def test_the_service_keeps_the_names_views_use():
    service = read("Service.qml")
    for name, kind in (
        ("reconnecting", "bool"),
        ("authFailed", "bool"),
        ("onboardingError", "var"),
        ("pasteRejected", "bool"),
        ("pasteEmpty", "bool"),
        ("onboardingStep", "string"),
        ("loginPhase", "string"),
        ("settingUp", "bool"),
    ):
        assert f"readonly property {kind} {name}: signinFlow.{name}\n" in service, name
    for line in (
        "function checkStatus() { signinFlow.checkStatus() }",
        "function startSetup() { return signinFlow.startSetup() }",
        "function startLogin(code) { return signinFlow.startLogin(code) }",
        "function finishLogin(pasted) { return signinFlow.finishLogin(pasted) }",
        "function cancelLogin() { signinFlow.cancelLogin() }",
        "function importCliLogin() { return signinFlow.importCliLogin() }",
        "function disconnect() { return signinFlow.disconnect() }",
        "function reconnect() { signinFlow.reconnect() }",
        "function copyText(text) { signinFlow.copyText(text) }",
        "function readClipboard(target) { signinFlow.readClipboard(target) }",
    ):
        assert line in service, line
    # The views still read and call the Service, never the flow.
    for rel in (
        "qml/views/OnboardingView.qml",
        "qml/views/LibraryView.qml",
        "BarWidget.qml",
    ):
        assert "signinFlow" not in read(rel), rel
    view = read("qml/views/OnboardingView.qml")
    for use in (
        "service.onboardingStep",
        "service.loginPhase",
        "service.onboardingError",
        "root.service.reconnecting",
        "root.service.settingUp",
        "root.service.pasteRejected",
        "root.service.pasteEmpty",
        "root.service.marketplace",
        "root.service.startLogin(",
        "root.service.cancelLogin()",
        "root.service.importCliLogin()",
        "root.service.copyText(",
        "root.service.checkStatus()",
        "root.service.startSetup()",
    ):
        assert use in view, use
    library = read("qml/views/LibraryView.qml")
    for use in (
        "root.service.reconnect()",
        "root.service.disconnect()",
        "root.service.clipboardNotice",
    ):
        assert use in library, use


def test_the_step_still_switches_the_view_on_the_service():
    service = read("Service.qml")
    assert (
        "onOnboardingStepChanged: view = Onboarding.view(onboardingStep, player.loaded,"
        in service
    )
    assert "Signin.requestAfterStep(view, clipboardNotice))" in service
    # Reconnect asks the Service to show Connect; the flow never writes `view`.
    flow = read("qml/SigninFlow.qml")
    assert "service.showView(Panel.VIEW_ONBOARDING)" in function_body(flow, "reconnect")
    assert not re.search(r"\bview\s*=[^=]", flow)


def test_the_runner_hands_every_record_and_finish_to_the_flow():
    service = read("Service.qml")
    events = service[service.index("onEvent: function(record, job)") :]
    events = events[: events.index("onJobFinished:")]
    assert "signinFlow.handleEvent(record, job)" in events
    # Same order as before the split: after the sync, before the log line, so
    # "fake: browser not opened" still comes before the login_url entry.
    assert events.index("sync.handleEvent(") < events.index("signinFlow.handleEvent(")
    assert events.index("signinFlow.handleEvent(") < events.index("root.logEvent(")
    finished = service[service.index("onJobFinished: function(job, outcome)") :]
    assert "signinFlow.handleFinished(job, outcome)" in finished
    assert finished.index("signinFlow.handleFinished(") < finished.index(
        'root.logEvent(job.command + " exit", text)'
    )
    flow = read("qml/SigninFlow.qml")
    handled = function_body(flow, "handleFinished")
    assert handled.index("Signin.authFailed(outcome)") < handled.index(
        "Signin.isOnboardingCommand(job.command)"
    )
    assert "onboardingFinished(job, outcome)" in handled


def test_fake_mode_never_opens_the_sign_in_link():
    flow = read("qml/SigninFlow.qml")
    event = function_body(flow, "handleEvent")
    assert (
        'if (service.fake) service.logEvent("login-start", "fake: browser not opened")'
        in event
    )
    assert 'else openUrl(String(record.url || ""))' in event
    # openUrl is reached only from that branch.
    assert flow.count("openUrl(") == 2


def test_the_auth_fail_ipc_goes_through_the_flow():
    ipc = read("qml/ServiceIpc.qml")
    assert 'if (action === "authfail") { signin.noteAuthFailed(); return "ok" }' in ipc
    assert "service.authFailed =" not in ipc
    service = read("Service.qml")
    block = service[service.index("  ServiceIpc {") :]
    block = block[: block.index("\n  }\n") + 1]
    assert "    signin: signinFlow\n" in block

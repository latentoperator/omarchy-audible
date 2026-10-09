"""U3 — ``qml/lib/Signin.js``: onboarding view decisions not in Onboarding.js."""

from __future__ import annotations

import pytest

import qjs


@pytest.fixture(scope="module")
def signin() -> qjs.JsModule:
    return qjs.load("Signin")


@pytest.mark.parametrize(
    "step,reconnecting,result",
    [
        ("ready", True, "connect"),
        ("ready", False, "ready"),
        ("ready", None, "ready"),
        ("setup", True, "setup"),
        ("missing", True, "missing"),
        ("connect", False, "connect"),
        (None, False, "loading"),
        ("", True, "loading"),
    ],
)
def test_effective_step(signin, step, reconnecting, result):
    assert signin.call("effectiveStep", step, reconnecting) == result


@pytest.mark.parametrize(
    "session,starting,finishing,phase",
    [
        ("", False, False, "pick"),
        (None, False, False, "pick"),
        ("", True, False, "starting"),
        ("abc", False, False, "paste"),
        ("abc", True, False, "paste"),
        ("abc", False, True, "finishing"),
        ("", False, True, "finishing"),
    ],
)
def test_phase(signin, session, starting, finishing, phase):
    assert signin.call("phase", session, starting, finishing) == phase


def test_command_sets(signin):
    for cmd in ("setup", "login-start", "login-finish", "login-import-cli", "logout"):
        assert signin.call("isOnboardingCommand", cmd) is True
    for cmd in ("sync", "get", "status", None):
        assert signin.call("isOnboardingCommand", cmd) is False
    assert signin.call("refreshesStatus", "login-start") is False
    assert signin.call("refreshesStatus", "logout") is True
    assert signin.call("isSignIn", "login-import-cli") is True
    assert signin.call("isSignIn", "logout") is False


def test_job_pending(signin):
    assert (
        signin.call("jobPending", "login-finish", [{"command": "login-finish"}], None)
        is True
    )
    assert (
        signin.call("jobPending", "login-finish", [], {"command": "login-finish"})
        is True
    )
    assert (
        signin.call(
            "jobPending", "login-finish", [{"command": "sync"}], {"command": "get"}
        )
        is False
    )
    assert signin.call("jobPending", "login-finish", None, None) is False


@pytest.mark.parametrize(
    "command,type_,summary,text",
    [
        (
            "login-start",
            "login_url",
            '{"type":"login_url","url":"https://x"}',
            "login_url",
        ),
        ("login-finish", "done", '{"type":"done"}', "done"),
        ("logout", None, "x", "event"),
        ("sync", "progress", '{"type":"progress"}', '{"type":"progress"}'),
        ("get", "done", None, ""),
    ],
)
def test_log_text(signin, command, type_, summary, text):
    assert signin.call("logText", command, type_, summary) == text


@pytest.mark.parametrize(
    "progress,text",
    [
        (
            {"stage": "requirements", "n": 2, "of": 4},
            "Setting up (2 of 4): requirements",
        ),
        ({"stage": "up-to-date"}, "Setting up: up-to-date"),
        ({"stage": "venv", "n": 1, "of": 0}, "Setting up: venv"),
        ({}, "Setting up…"),
        (None, "Setting up…"),
    ],
)
def test_setup_text(signin, progress, text):
    assert signin.call("setupText", progress) == text


def test_marketplace_label(signin):
    onboarding = qjs.load("Onboarding")
    stores = onboarding.call("marketplaces")
    assert signin.call("marketplaceLabel", "us", stores) == next(
        s["label"] for s in stores if s["code"] == "us"
    )
    assert signin.call("marketplaceLabel", "zz", stores) == "zz"
    assert signin.call("marketplaceLabel", "", stores) == ""
    assert signin.call("marketplaceLabel", None, None) == ""
    assert any(s["code"] == signin.evaluate("DEFAULT_MARKETPLACE") for s in stores)


@pytest.mark.parametrize(
    "account,where,line",
    [
        ("Chris", "United States", "Chris · United States"),
        (" j***@gmail.com ", "United States", "j***@gmail.com · United States"),
        (None, "United States", "Signed in · United States"),
        ("Chris", "", "Chris"),
        ("", None, "Signed in"),
    ],
)
def test_account_line(signin, account, where, line):
    assert signin.call("accountLine", account, where) == line


@pytest.mark.parametrize(
    "outcome,result",
    [
        ({"ok": False, "code": "auth_failed"}, True),
        ({"ok": False, "code": "network"}, False),
        ({"ok": True, "code": "auth_failed"}, False),
        (None, False),
    ],
)
def test_auth_failed(signin, outcome, result):
    assert signin.call("authFailed", outcome) is result


def test_bad_paste_text(signin):
    assert (
        signin.evaluate("BAD_PASTE") == "That doesn't look like the Amazon page address"
    )


def test_empty_paste_text(signin):
    assert signin.evaluate("EMPTY_PASTE") == "Paste the address first"


@pytest.mark.parametrize(
    "empty,text",
    [
        (True, "Paste the address first"),
        (False, "That doesn't look like the Amazon page address"),
        (None, "That doesn't look like the Amazon page address"),
    ],
)
def test_paste_message(signin, empty, text):
    assert signin.call("pasteMessage", empty) == text


def test_store_options(signin):
    stores = qjs.load("Onboarding").call("marketplaces")
    options = signin.call("storeOptions", stores)
    assert [o["value"] for o in options] == [s["code"] for s in stores]
    assert [o["label"] for o in options] == [s["label"] for s in stores]
    assert signin.call("storeOptions", [None, {"code": ""}, {"code": "x"}]) == [
        {"value": "x", "label": "x"}
    ]
    assert signin.call("storeOptions", None) == []


@pytest.mark.parametrize(
    "step,reconnecting,text",
    [
        ("missing", False, "A few tools are missing"),
        ("setup", False, "Set up Omaudible"),
        ("connect", False, "Connect Audible"),
        ("connect", True, "Reconnect Audible"),
        ("loading", False, "Checking your setup…"),
        (None, None, "Checking your setup…"),
    ],
)
def test_heading(signin, step, reconnecting, text):
    assert signin.call("heading", step, reconnecting) == text


def test_setup_line(signin):
    assert (
        signin.call("setupLine", True, {"stage": "venv", "n": 1, "of": 4})
        == "Setting up (1 of 4): venv"
    )
    assert "about a minute" in signin.call("setupLine", False, {"stage": "venv"})


@pytest.mark.parametrize(
    "phase,blank",
    [("starting", False), ("finishing", False), ("pick", True), ("paste", True)],
)
def test_phase_text(signin, phase, blank):
    assert (signin.call("phaseText", phase) == "") is blank


@pytest.mark.parametrize(
    "key,action",
    [
        (0x01000000, "close"),
        (0x01000004, "send"),
        (0x01000005, "send"),
        (0x41, "type"),
        (0x20, "type"),
        (None, "type"),
    ],
)
def test_paste_key(signin, key, action):
    assert signin.call("pasteKey", key) == action


@pytest.mark.parametrize(
    "view,notice,wanted",
    [
        ("onboarding", "", None),
        ("onboarding", "Clear it", "library"),
        ("mini", "", "mini"),
        ("mini", "Clear it", "library"),
        ("library", "", "library"),
        ("", "", None),
        (None, None, None),
    ],
)
def test_request_after_step(signin, view, notice, wanted):
    assert signin.call("requestAfterStep", view, notice) == wanted


def test_input_lost(signin):
    assert signin.call("inputLost", {"inputId": 3}, {"3": "x"}) is False
    assert signin.call("inputLost", {"inputId": 3}, {}) is True
    assert signin.call("inputLost", {"inputId": 3}, None) is True
    assert signin.call("inputLost", {"command": "sync"}, {}) is False
    assert signin.call("inputLost", None, {}) is False

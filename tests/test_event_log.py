"""EventLog.js: one-line summaries for the service's event log."""

from __future__ import annotations

import pytest

import qjs


@pytest.fixture(scope="module")
def lib():
    return qjs.load("EventLog")


def test_summarize_truncates(lib):
    out = lib.call("summarize", {"type": "x", "pad": "y" * 500}, 40)
    assert len(out) == 41 and out.endswith("…")


def test_summarize_keeps_short_records(lib):
    assert lib.call("summarize", {"type": "done"}, 40) == '{"type":"done"}'


# ---- B11: the key in a play_info record never reaches the log ----


def test_summarize_redacts_the_lavf_options_value(lib):
    record = {
        "type": "play_info",
        "path": "/b/book.aaxc",
        "chapters_file": "/b/chapters.txt",
        "lavf_options": "audible_key=feedface1234,audible_iv=beefcafe5678",
    }
    out = lib.call("summarize", record, 500)
    assert "feedface1234" not in out
    assert "beefcafe5678" not in out
    assert '"lavf_options":"[redacted]"' in out
    assert '"type":"play_info"' in out


def test_summarize_redacts_lavf_options_at_any_depth(lib):
    record = {"type": "x", "a": {"b": [{"lavf_options": "activation_bytes=00ff00ff"}]}}
    out = lib.call("summarize", record, 500)
    assert "00ff00ff" not in out
    assert out.count("[redacted]") == 1


def test_summarize_redacts_an_empty_lavf_options_too(lib):
    out = lib.call("summarize", {"type": "play_info", "lavf_options": ""}, 500)
    assert '"[redacted]"' in out


def test_summarize_never_throws_on_odd_records(lib):
    for record in (None, 5, "text", [], {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}}):
        assert isinstance(lib.call("summarize", record, 40), str)


def test_diagnostic_redacts_secret_options_and_limits_doctor_details(lib):
    diagnostic = qjs.load("Diagnostic")
    text = diagnostic.call(
        "build",
        "0.0.1",
        "sync",
        "internal",
        "bad lavf_options=activation_bytes=beefcafefeed and access_token=tokenvalue",
        "check key=deadbeef",
        [
            {"name": "mpv", "ok": False, "detail": "mpv not found on PATH"},
            {"name": "auth", "ok": True, "detail": "/private/auth.json"},
            {"name": "venv", "ok": False, "detail": "/private/venv"},
        ],
    )
    assert "0.0.1" in text and "Command: sync" in text and "Error: internal" in text
    assert (
        "beefcafefeed" not in text
        and "tokenvalue" not in text
        and "deadbeef" not in text
    )
    assert "mpv not found on PATH" in text
    assert "/private/auth.json" not in text and "/private/venv" not in text


@pytest.mark.parametrize(
    "value,secret",
    [
        ('{"key": "cafefeed"}', "cafefeed"),
        ("{'iv': 'aabbccdd'}", "aabbccdd"),
        ('{"audible_key":"deadbeef"}', "deadbeef"),
        ("{lavf_options: {audible_key: feedface}}", "feedface"),
        ("voucher=0123456789", "0123456789"),
        ("aeskey=0123456789", "0123456789"),
    ],
)
def test_diagnostic_scrubs_key_value_forms(lib, value, secret):
    diagnostic = qjs.load("Diagnostic")
    result = diagnostic.call("build", "0.0.1", "sync", "internal", value, "", [])
    assert secret not in result


@pytest.mark.parametrize(
    "value", ["could not read the library", "The Key: A Novel", "IV: Part Four"]
)
def test_event_log_keeps_ordinary_text(lib, value):
    assert lib.call("redactOptions", value) == value


def test_diagnostic_keeps_ordinary_library_error_text():
    diagnostic = qjs.load("Diagnostic")
    text = diagnostic.call(
        "build", "0.0.1", "sync", "internal", "could not read the library", "", []
    )
    assert "Message: could not read the library" in text


def test_service_runs_doctor_and_copies_diagnostic_through_stdin():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    service = (root / "Service.qml").read_text(encoding="utf-8")
    signin = (root / "qml" / "SigninFlow.qml").read_text(encoding="utf-8")
    ipc = (root / "qml" / "ServiceIpc.qml").read_text(encoding="utf-8")
    assert 'root.run("doctor", [], "sync-doctor")' in service
    assert "Drawer.connectionProblem(root.lastSyncCode)" in service
    assert "if (!outcome.ok && Drawer.connectionProblem(root.lastSyncCode))" in service
    assert 'authFailed ? "auth_failed" : syncFailure.errorCode' in service
    assert (
        "function copyDiagnostic() { signinFlow.copyText(diagnosticText) }" in service
    )
    assert "function diagnostic(): string { if (!service.fake)" in ipc
    assert 'command: ["wl-copy"]' in signin and "write(text)" in signin

"""L3 — ``qml/lib/Onboarding.js`` in PySide6's ``QJSEngine``.

The onboarding drawer's decisions (PLAN L3, ARCHITECTURE §6, SCOPE FR-A1–A4):
which step a ``status`` event calls for, the install command for the missing
tools, which view a request opens, the human text for an error, the redirect
check, the marketplace list and the clipboard notice.

``marketplaces()`` is asserted against the backend's own ``MARKETPLACES`` and
``errorText`` against every ``protocol.ErrorCode`` member, so the two sides
cannot drift apart.
"""

from __future__ import annotations

import pytest

import qjs
from omarchy_audible.auth import MARKETPLACES
from omarchy_audible.protocol import ErrorCode

EXPECTED_API = {
    "_p",
    "STEP_CONNECT",
    "STEP_LOADING",
    "STEP_MISSING",
    "STEP_READY",
    "STEP_SETUP",
    "clipboardNotice",
    "errorText",
    "installCommand",
    "looksLikeRedirect",
    "marketplaces",
    "step",
    "view",
}

# A redirect URL carrying the one-time code. Invented; never a real account.
REDIRECT = (
    "https://www.amazon.com/ap/register?openid.oa2.authorization_code=INVENTEDCODE123"
)

# Every code `errorText` must cover, read from the backend itself.
ERROR_CODES = sorted(
    value for value in vars(ErrorCode).values() if isinstance(value, str)
)

MARKETPLACE_LABELS = {
    "us": "United States",
    "uk": "United Kingdom",
    "de": "Germany",
    "fr": "France",
    "ca": "Canada",
    "it": "Italy",
    "au": "Australia",
    "in": "India",
    "jp": "Japan",
    "es": "Spain",
    "br": "Brazil",
}


@pytest.fixture(scope="module")
def onboarding() -> qjs.JsModule:
    return qjs.load("Onboarding")


def ready_status(**overrides) -> dict:
    """A fully ready ``status`` event, with fields overridden as needed."""
    status = {
        "ready": True,
        "missing": [],
        "authenticated": True,
        "venv_ready": True,
        "marketplace": "us",
        "account": "Chris",
    }
    status.update(overrides)
    return status


# --- API ---------------------------------------------------------------------
def test_exports_the_expected_api(onboarding: qjs.JsModule) -> None:
    assert set(onboarding.functions) == EXPECTED_API


def test_constant_values(onboarding: qjs.JsModule) -> None:
    assert onboarding.evaluate("STEP_LOADING") == "loading"
    assert onboarding.evaluate("STEP_MISSING") == "missing"
    assert onboarding.evaluate("STEP_SETUP") == "setup"
    assert onboarding.evaluate("STEP_CONNECT") == "connect"
    assert onboarding.evaluate("STEP_READY") == "ready"
    assert onboarding.evaluate("Panel.VIEW_ONBOARDING") == "onboarding"
    assert onboarding.evaluate("Panel.VIEW_LIBRARY") == "library"
    assert onboarding.evaluate("Panel.VIEW_MINI") == "mini"
    assert onboarding.evaluate("Panel.VIEW_FULL") == "full"


# --- step --------------------------------------------------------------------
@pytest.mark.parametrize("status", [None, "garbage", 42, [], True])
def test_step_loading_for_a_missing_status(onboarding: qjs.JsModule, status) -> None:
    assert onboarding.call("step", status) == "loading"


def test_step_missing_when_a_tool_is_missing(onboarding: qjs.JsModule) -> None:
    assert onboarding.call("step", ready_status(missing=["mpv"])) == "missing"
    assert (
        onboarding.call("step", ready_status(missing=["mpv", "ffprobe"])) == "missing"
    )


def test_step_setup_when_the_venv_is_not_ready(onboarding: qjs.JsModule) -> None:
    assert onboarding.call("step", ready_status(venv_ready=False)) == "setup"


def test_step_connect_when_not_authenticated(onboarding: qjs.JsModule) -> None:
    assert onboarding.call("step", ready_status(authenticated=False)) == "connect"


def test_step_ready(onboarding: qjs.JsModule) -> None:
    assert onboarding.call("step", ready_status()) == "ready"


def test_step_precedence(onboarding: qjs.JsModule) -> None:
    # Missing tools win over an unbuilt venv and a signed-out account; an unbuilt
    # venv wins over a signed-out account.
    assert (
        onboarding.call(
            "step",
            ready_status(missing=["mpv"], venv_ready=False, authenticated=False),
        )
        == "missing"
    )
    assert (
        onboarding.call("step", ready_status(venv_ready=False, authenticated=False))
        == "setup"
    )


def test_step_derives_from_the_fields_not_the_ready_flag(
    onboarding: qjs.JsModule,
) -> None:
    assert onboarding.call("step", ready_status(ready=False)) == "ready"
    assert (
        onboarding.call("step", ready_status(ready=True, authenticated=False))
        == "connect"
    )


def test_step_ignores_a_non_array_missing(onboarding: qjs.JsModule) -> None:
    # `status.missing` is always an array (schema); anything else is not a list
    # of missing tools.
    assert onboarding.call("step", ready_status(missing="mpv")) == "ready"
    assert onboarding.call("step", ready_status(missing=[])) == "ready"


# --- installCommand ----------------------------------------------------------
@pytest.mark.parametrize(
    "missing,expected",
    [
        ([], ""),
        (["mpv"], "omarchy pkg add mpv"),
        (["ffmpeg"], "omarchy pkg add ffmpeg"),
        (["ffprobe"], "omarchy pkg add ffmpeg"),
        (["mpv", "ffmpeg"], "omarchy pkg add mpv ffmpeg"),
        (["mpv", "ffmpeg", "ffprobe"], "omarchy pkg add mpv ffmpeg"),
        (["ffprobe", "mpv"], "omarchy pkg add ffmpeg mpv"),
        (["mpv", "mpv"], "omarchy pkg add mpv"),
        (["ffprobe", "ffmpeg"], "omarchy pkg add ffmpeg"),
        (["ffmpeg", "mpv", "ffmpeg"], "omarchy pkg add ffmpeg mpv"),
    ],
)
def test_install_command(onboarding: qjs.JsModule, missing, expected: str) -> None:
    assert onboarding.call("installCommand", missing) == expected


@pytest.mark.parametrize("missing", [None, "garbage", 42, {}, True])
def test_install_command_with_no_list(onboarding: qjs.JsModule, missing) -> None:
    assert onboarding.call("installCommand", missing) == ""


def test_install_command_skips_unusable_entries(onboarding: qjs.JsModule) -> None:
    assert (
        onboarding.call("installCommand", [None, "", "   ", 42, "mpv", [], "ffprobe"])
        == "omarchy pkg add mpv ffmpeg"
    )


# --- view --------------------------------------------------------------------
@pytest.mark.parametrize(
    "step", ["loading", "missing", "setup", "connect", "garbage", None]
)
@pytest.mark.parametrize("requested", [None, "library", "mini", "full", "garbage"])
@pytest.mark.parametrize("loaded", [True, False])
def test_view_onboarding_until_ready(
    onboarding: qjs.JsModule, step, requested, loaded: bool
) -> None:
    assert onboarding.call("view", step, loaded, requested) == "onboarding"


def test_view_bar_click_opens_mini_or_library(onboarding: qjs.JsModule) -> None:
    assert onboarding.call("view", "ready", True, None) == "mini"
    assert onboarding.call("view", "ready", False, None) == "library"


def test_view_bar_click_is_a_missing_or_unknown_request(
    onboarding: qjs.JsModule,
) -> None:
    for request in (None, "", "   ", "bar", "toggle", "garbage"):
        assert onboarding.call("view", "ready", True, request) == "mini"
        assert onboarding.call("view", "ready", False, request) == "library"


def test_view_full_only_with_a_loaded_book(onboarding: qjs.JsModule) -> None:
    assert onboarding.call("view", "ready", True, "full") == "full"
    assert onboarding.call("view", "ready", False, "full") == "library"


def test_view_mini_needs_a_loaded_book(onboarding: qjs.JsModule) -> None:
    assert onboarding.call("view", "ready", True, "mini") == "mini"
    assert onboarding.call("view", "ready", False, "mini") == "library"


def test_view_library_is_always_library(onboarding: qjs.JsModule) -> None:
    assert onboarding.call("view", "ready", True, "library") == "library"
    assert onboarding.call("view", "ready", False, "library") == "library"


@pytest.mark.parametrize("loaded", [None, "yes", 1, 0, {}, []])
def test_view_player_loaded_must_be_true(onboarding: qjs.JsModule, loaded) -> None:
    assert onboarding.call("view", "ready", loaded, None) == "library"
    assert onboarding.call("view", "ready", loaded, "mini") == "library"
    assert onboarding.call("view", "ready", loaded, "full") == "library"


# --- errorText ---------------------------------------------------------------
@pytest.mark.parametrize("code", ERROR_CODES)
def test_error_text_covers_every_error_code(
    onboarding: qjs.JsModule, code: str
) -> None:
    text = onboarding.call("errorText", code, None, None)
    assert isinstance(text, dict)
    assert set(text) == {"title", "body", "reconnect"}
    assert isinstance(text["title"], str) and text["title"]
    assert isinstance(text["body"], str) and text["body"]
    assert isinstance(text["reconnect"], bool)


def test_error_text_covers_no_venv(onboarding: qjs.JsModule) -> None:
    # `no_venv` ships in `ErrorCode` and must have its own entry.
    assert ErrorCode.NO_VENV == "no_venv"
    assert ErrorCode.NO_VENV in ERROR_CODES
    text = onboarding.call("errorText", ErrorCode.NO_VENV, None, None)
    assert text["title"] == "Setup needed"
    assert text["reconnect"] is False


def test_error_text_unknown_code_falls_back(onboarding: qjs.JsModule) -> None:
    text = onboarding.call("errorText", "made_up_code", None, None)
    assert set(text) == {"title", "body", "reconnect"}
    assert text["title"] and text["body"]
    # The fallback matches the internal-error copy.
    assert text == onboarding.call("errorText", ErrorCode.INTERNAL, None, None)


@pytest.mark.parametrize("value", [None, "", "garbage", 42, {}, []])
def test_error_text_missing_code_falls_back(onboarding: qjs.JsModule, value) -> None:
    assert onboarding.call("errorText", value, None, None) == onboarding.call(
        "errorText", ErrorCode.INTERNAL, None, None
    )


def test_error_text_reconnect_only_for_auth_failed(onboarding: qjs.JsModule) -> None:
    assert (
        onboarding.call("errorText", ErrorCode.AUTH_FAILED, None, None)["reconnect"]
        is True
    )
    for code in ERROR_CODES:
        if code != ErrorCode.AUTH_FAILED:
            assert onboarding.call("errorText", code, None, None)["reconnect"] is False


def test_error_text_uses_the_backend_message_and_hint(
    onboarding: qjs.JsModule,
) -> None:
    text = onboarding.call(
        "errorText",
        ErrorCode.NETWORK,
        "Could not reach Audible.",
        "Check the connection.",
    )
    assert text["body"] == "Could not reach Audible. Check the connection."


def test_error_text_uses_the_message_alone(onboarding: qjs.JsModule) -> None:
    text = onboarding.call("errorText", ErrorCode.NETWORK, "Custom detail.", None)
    assert text["body"] == "Custom detail."


def test_error_text_uses_the_hint_alone(onboarding: qjs.JsModule) -> None:
    text = onboarding.call(
        "errorText", ErrorCode.NETWORK, None, "Check the connection."
    )
    default = onboarding.call("errorText", ErrorCode.NETWORK, None, None)["body"]
    assert text["body"] == default + " Check the connection."


def test_error_text_ignores_blank_message_and_hint(
    onboarding: qjs.JsModule,
) -> None:
    default = onboarding.call("errorText", ErrorCode.NETWORK, None, None)
    assert onboarding.call("errorText", ErrorCode.NETWORK, "", "   ") == default
    assert onboarding.call("errorText", ErrorCode.NETWORK, None, 42) == default


def test_error_text_never_echoes_a_pasted_redirect(
    onboarding: qjs.JsModule,
) -> None:
    text = onboarding.call("errorText", ErrorCode.BAD_URL, REDIRECT, REDIRECT)
    assert "INVENTEDCODE123" not in text["body"]
    assert "openid.oa2.authorization_code" not in text["body"]
    # The code's own safe copy is used instead.
    assert text["body"]
    assert text["title"] == "That doesn't look like the Amazon page address"


def test_error_text_drops_only_the_redirect_message(
    onboarding: qjs.JsModule,
) -> None:
    text = onboarding.call(
        "errorText", ErrorCode.AUTH_FAILED, REDIRECT, "Start the login again."
    )
    assert "INVENTEDCODE123" not in text["body"]
    assert text["body"].endswith("Start the login again.")


def test_error_text_drops_only_the_redirect_hint(
    onboarding: qjs.JsModule,
) -> None:
    text = onboarding.call(
        "errorText", ErrorCode.AUTH_FAILED, "Audible rejected the sign-in.", REDIRECT
    )
    assert "INVENTEDCODE123" not in text["body"]
    assert text["body"] == "Audible rejected the sign-in."


# --- looksLikeRedirect -------------------------------------------------------
def test_looks_like_redirect_true(onboarding: qjs.JsModule) -> None:
    assert onboarding.call("looksLikeRedirect", REDIRECT) is True
    assert (
        onboarding.call(
            "looksLikeRedirect", "junk openid.oa2.authorization_code=abc junk"
        )
        is True
    )


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "   ",
        42,
        {},
        [],
        True,
        "https://www.amazon.com/ap/signin?x=1",
        "openid.oa2.authorization_code",
        "openid.oa2.authorization_code=",
    ],
)
def test_looks_like_redirect_false(onboarding: qjs.JsModule, text) -> None:
    expected = isinstance(text, str) and "openid.oa2.authorization_code=" in text
    assert onboarding.call("looksLikeRedirect", text) is expected


def test_looks_like_redirect_returns_only_a_boolean(
    onboarding: qjs.JsModule,
) -> None:
    # The function cannot echo the text: it returns a boolean, never the input.
    assert type(onboarding.call("looksLikeRedirect", REDIRECT)) is bool
    assert onboarding.evaluate("typeof looksLikeRedirect('x')") == "boolean"


# --- marketplaces ------------------------------------------------------------
def test_marketplaces_codes_match_the_backend_in_order(
    onboarding: qjs.JsModule,
) -> None:
    items = onboarding.call("marketplaces")
    assert [item["code"] for item in items] == list(MARKETPLACES)


def test_marketplaces_labels(onboarding: qjs.JsModule) -> None:
    items = onboarding.call("marketplaces")
    assert {item["code"]: item["label"] for item in items} == MARKETPLACE_LABELS


def test_marketplaces_shape(onboarding: qjs.JsModule) -> None:
    items = onboarding.call("marketplaces")
    assert len(items) == len(MARKETPLACES)
    for item in items:
        assert set(item) == {"code", "label"}
        assert isinstance(item["code"], str) and item["code"]
        assert isinstance(item["label"], str) and item["label"]


# --- clipboardNotice ---------------------------------------------------------
def test_clipboard_notice_when_the_code_is_in_history(
    onboarding: qjs.JsModule,
) -> None:
    notice = onboarding.call(
        "clipboardNotice",
        {"type": "done", "clipboard_history_contains_code": True},
    )
    assert isinstance(notice, str) and notice
    assert "clipboard" in notice.lower()


@pytest.mark.parametrize(
    "done",
    [
        None,
        "",
        "garbage",
        42,
        {},
        {"type": "done"},
        {"type": "done", "clipboard_history_contains_code": False},
        {"type": "done", "clipboard_history_contains_code": "true"},
        {"type": "done", "clipboard_history_contains_code": 1},
    ],
)
def test_clipboard_notice_otherwise_is_empty(onboarding: qjs.JsModule, done) -> None:
    assert onboarding.call("clipboardNotice", done) == ""

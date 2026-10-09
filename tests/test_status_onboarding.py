"""B9 — ``status`` fields and fake sign-in states for onboarding.

Three behaviors (PLAN.md B9, ARCHITECTURE 4.2/4.7):

1. the account label falls back to the saved login's ``customer_info`` first
   name when ``account.json`` has no email, read from ``auth.json`` as plain
   JSON (no network, no ``audible`` import, never ``user_id``);
2. ``status`` reports ``venv_ready`` so the UI can tell "run setup" apart from
   "connect";
3. fake mode carries its own sign-in state and an optional ``fake-status.json``
   override, and real mode reads neither.

Every fixture name is invented. The suite never reads ``~/.audible`` or a real
account: ``conftest`` points HOME and every XDG variable at temporary dirs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_auth import ACCOUNT, URL, FakeAudible, _make_cli_login

from omarchy_audible import auth, bootstrap
from omarchy_audible.commands import find_mpris_script
from omarchy_audible.paths import Paths

FAKE_STATUS_FILENAME = "fake-status.json"
SIGNED_OUT_MARKER = "fake-signed-out"

INVENTED_NAME = "Zelda"
INVENTED_FULL_NAME = "Zelda Fitzgerald"


def test_mpris_script_detection_prefers_fixed_system_paths_and_user_fallback(tmp_path):
    system = tmp_path / "usr" / "lib" / "mpris.so"
    other = tmp_path / "etc" / "scripts" / "mpris.so"
    user = tmp_path / "config" / "mpv" / "scripts" / "mpris.so"
    for candidate in (system, other, user):
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(b"fixture")
    assert find_mpris_script([system, other], tmp_path / "config") == str(system)
    system.unlink()
    assert find_mpris_script([system, other], tmp_path / "config") == str(other)
    other.unlink()
    assert find_mpris_script([system, other], tmp_path / "config") == str(user)
    user.unlink()
    assert find_mpris_script([system, other], tmp_path / "config") is None


def _status_event(result, events) -> dict:
    return next(event for event in events(result) if event["type"] == "status")


def _make_ready_venv(paths: Paths) -> None:
    (paths.venv_dir / "bin").mkdir(parents=True, exist_ok=True)
    paths.venv_python.write_text("#!/bin/sh\n", encoding="utf-8")
    bootstrap.marker_path(paths.venv_dir).write_text("{}", encoding="utf-8")


def _write_fake_status(fake_paths: Paths, payload: object) -> None:
    fake_paths.config_dir.mkdir(parents=True, exist_ok=True)
    (fake_paths.config_dir / FAKE_STATUS_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _write_auth_json(paths: Paths, customer_info: object) -> None:
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.auth_file.write_text(
        json.dumps({"customer_info": customer_info}), encoding="utf-8"
    )


# --- 1. the account-label resolver ------------------------------------------
@pytest.mark.parametrize(
    "info,expected",
    [
        ({"email": ACCOUNT}, "f***@example.com"),
        ({"email_address": ACCOUNT}, "f***@example.com"),
        ({"email": "not-an-email", "name": INVENTED_FULL_NAME}, "Zelda"),
        ({"given_name": "Zelda"}, "Zelda"),
        ({"name": INVENTED_FULL_NAME}, "Zelda"),
        ({"given_name": "Zelda", "name": INVENTED_FULL_NAME}, "Zelda"),
        ({"email": ACCOUNT, "given_name": "Zelda"}, "f***@example.com"),
        ({"user_id": "amzn1.account.FAKEUSER"}, None),
        ({"name": INVENTED_FULL_NAME, "user_id": "amzn1.account.FAKEUSER"}, "Zelda"),
        ({}, None),
        ({"given_name": "   "}, None),
        ({"given_name": 5, "name": None}, None),
        (None, None),
        ("garbage", None),
        ([1, 2], None),
    ],
)
def test_account_from_info_covers_every_shape(info, expected):
    assert auth.account_from_info(info) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"customer_info": {"email": "ada@example.com"}}', "a***@example.com"),
        ('{"customer_info": {"given_name": "Zelda"}}', "Zelda"),
        ('{"customer_info": {"name": "Zelda Fitzgerald"}}', "Zelda"),
        ('{"customer_info": {"user_id": "amzn1.account.FAKEUSER"}}', None),
        ('{"customer_info": {"name": "Zelda", "user_id": "amzn1.account.X"}}', "Zelda"),
        ('{"customer_info": {}}', None),
        ('{"customer_info": "garbage"}', None),
        ('{"customer_info": [1, 2]}', None),
        ('{"other": 1}', None),
        ("not json at all", None),
        ("[1, 2]", None),
        ("", None),
    ],
)
def test_account_from_auth_file_covers_every_shape(tmp_path: Path, text, expected):
    path = tmp_path / "auth.json"
    path.write_text(text, encoding="utf-8")
    assert auth.account_from_auth_file(path) == expected


def test_account_from_auth_file_missing_and_unreadable(tmp_path: Path):
    assert auth.account_from_auth_file(tmp_path / "absent.json") is None

    directory = tmp_path / "auth.json"
    directory.mkdir()
    assert auth.account_from_auth_file(directory) is None  # read_text raises OSError


@pytest.mark.parametrize(
    "info,expected",
    [
        ({"email": ACCOUNT}, "f***@example.com"),
        ({"given_name": "Zelda"}, "Zelda"),
        ({"name": INVENTED_FULL_NAME}, "Zelda"),
        ({"user_id": "amzn1.account.FAKEUSER"}, None),
        ({}, None),
        ("garbage", None),
    ],
)
def test_login_finish_stores_the_account_fallback(paths: Paths, info, expected):
    port = FakeAudible(customer_info=info)
    session_id = auth.login_start(paths, marketplace="us", fake=False, api=port)
    auth.login_finish(
        paths, session_id=session_id, pasted_url=URL, fake=False, api=port
    )
    record = json.loads(paths.account_file.read_text(encoding="utf-8"))
    assert record["account"] == expected
    assert "amzn1.account" not in json.dumps(record)


@pytest.mark.parametrize(
    "info,expected",
    [
        ({"email": ACCOUNT}, "f***@example.com"),
        ({"given_name": "Zelda"}, "Zelda"),
        ({"name": INVENTED_FULL_NAME}, "Zelda"),
        ({"user_id": "amzn1.account.FAKEUSER"}, None),
        ({}, None),
    ],
)
def test_login_import_cli_stores_the_account_fallback(
    tmp_path: Path, paths: Paths, info, expected
):
    source = _make_cli_login(tmp_path / "audible-cli")
    auth.login_import_cli(
        paths,
        source_dir=source.parent,
        fake=False,
        api=FakeAudible(customer_info=info),
    )
    record = json.loads(paths.account_file.read_text(encoding="utf-8"))
    assert record["account"] == expected


# --- 1b. status reports the account label ------------------------------------
@pytest.mark.parametrize(
    "info,expected",
    [
        ({"email": "ada@example.com"}, "a***@example.com"),
        ({"given_name": "Zelda"}, "Zelda"),
        ({"name": INVENTED_FULL_NAME}, "Zelda"),
        ({"user_id": "amzn1.account.FAKEUSER"}, None),
        ({}, None),
        ("garbage", None),
    ],
)
def test_status_reads_the_name_fallback_from_auth_json(
    run_cli, events, validate_event, paths: Paths, info, expected
):
    _write_auth_json(paths, info)
    status = _status_event(run_cli("status"), events)
    validate_event(status)
    assert status["authenticated"] is True
    assert status["account"] == expected


def test_status_prefers_the_stored_account_over_the_fallback(
    run_cli, events, paths: Paths
):
    _write_auth_json(paths, {"given_name": "Zelda"})
    paths.account_file.write_text(
        json.dumps({"account": "b***@example.com"}), encoding="utf-8"
    )
    status = _status_event(run_cli("status"), events)
    assert status["account"] == "b***@example.com"


def test_status_falls_back_when_account_json_has_no_account(
    run_cli, events, paths: Paths
):
    _write_auth_json(paths, {"name": INVENTED_FULL_NAME})
    paths.account_file.write_text(
        json.dumps({"origin": "login", "account": None}), encoding="utf-8"
    )
    status = _status_event(run_cli("status"), events)
    assert status["account"] == "Zelda"


def test_the_account_name_never_reaches_a_log_line(run_cli, paths: Paths):
    _write_auth_json(paths, {"given_name": INVENTED_NAME})
    result = run_cli("status")
    assert result.returncode == 0, result.stderr
    assert f'"account":"{INVENTED_NAME}"' in result.stdout
    assert INVENTED_NAME not in result.stderr


# --- 2. venv_ready -----------------------------------------------------------
def test_status_reports_venv_ready_true_and_false(
    run_cli, events, validate_event, paths: Paths
):
    _write_auth_json(paths, {"given_name": "Zelda"})

    before = _status_event(run_cli("status"), events)
    validate_event(before)
    assert before["venv_ready"] is False

    _make_ready_venv(paths)
    after = _status_event(run_cli("status"), events)
    validate_event(after)
    assert after["venv_ready"] is True


def test_status_schema_requires_venv_ready(schemas_dir: Path):
    schema = json.loads((schemas_dir / "status.json").read_text(encoding="utf-8"))
    assert "venv_ready" in schema["required"]
    assert schema["properties"]["venv_ready"]["type"] == "boolean"


# --- 3. fake sign-in states --------------------------------------------------
def test_fake_tree_starts_signed_in(run_cli, events, validate_event):
    status = _status_event(run_cli("status", fake=True), events)
    validate_event(status)
    assert status["authenticated"] is True
    assert status["ready"] is True


def test_fake_logout_then_login_finish_signs_back_in(
    run_cli, events, validate_stream, fake_paths: Paths
):
    assert run_cli("logout", fake=True).returncode == 0
    logged_out = _status_event(run_cli("status", fake=True), events)
    assert logged_out["authenticated"] is False
    assert logged_out["ready"] is False
    assert (fake_paths.config_dir / SIGNED_OUT_MARKER).is_file()

    started = validate_stream(
        run_cli("login-start", "--marketplace", "us", fake=True), expect_last="done"
    )
    session_id = started[0]["session"]
    finish = run_cli("login-finish", "--session", session_id, fake=True, stdin=URL)
    assert finish.returncode == 0, finish.stderr

    signed_in = _status_event(run_cli("status", fake=True), events)
    assert signed_in["authenticated"] is True
    assert signed_in["ready"] is True
    assert not (fake_paths.config_dir / SIGNED_OUT_MARKER).exists()


def test_fake_import_cli_signs_back_in(run_cli, events):
    assert run_cli("logout", fake=True).returncode == 0
    assert _status_event(run_cli("status", fake=True), events)["authenticated"] is False

    result = run_cli("login-import-cli", fake=True)
    assert result.returncode == 0, result.stderr
    assert _status_event(run_cli("status", fake=True), events)["authenticated"] is True


def test_fake_onboarding_state_lives_only_in_the_fake_tree(
    run_cli, events, fake_paths: Paths, env
):
    run_cli("logout", fake=True)
    real = Paths.from_env(env)
    assert (fake_paths.config_dir / SIGNED_OUT_MARKER).is_file()
    assert not (real.config_dir / SIGNED_OUT_MARKER).exists()


# --- 3b. fake-status.json overrides ------------------------------------------
def test_fake_status_overrides_missing_tools(run_cli, events, fake_paths: Paths):
    _write_fake_status(fake_paths, {"missing": ["mpv", "ffmpeg"]})
    status = _status_event(run_cli("status", fake=True), events)
    assert status["missing"] == ["mpv", "ffmpeg"]
    assert status["venv_ready"] is True
    assert status["authenticated"] is True
    assert status["ready"] is False


def test_fake_status_overrides_venv_ready(run_cli, events, fake_paths: Paths):
    _write_fake_status(fake_paths, {"venv_ready": False})
    status = _status_event(run_cli("status", fake=True), events)
    assert status["venv_ready"] is False
    assert status["missing"] == []
    assert status["ready"] is False


def test_fake_status_garbage_and_wrong_types_are_ignored(
    run_cli, events, fake_paths: Paths
):
    fake_paths.config_dir.mkdir(parents=True, exist_ok=True)
    (fake_paths.config_dir / FAKE_STATUS_FILENAME).write_text(
        "not json", encoding="utf-8"
    )
    garbage = _status_event(run_cli("status", fake=True), events)
    assert garbage["missing"] == []
    assert garbage["venv_ready"] is True

    _write_fake_status(fake_paths, {"missing": "mpv", "venv_ready": "no"})
    wrong_types = _status_event(run_cli("status", fake=True), events)
    assert wrong_types["missing"] == []
    assert wrong_types["venv_ready"] is True


def test_setup_fake_clears_the_venv_override_but_keeps_missing(
    run_cli, events, fake_paths: Paths
):
    _write_fake_status(fake_paths, {"missing": ["mpv"], "venv_ready": False})
    before = _status_event(run_cli("status", fake=True), events)
    assert before["venv_ready"] is False

    result = run_cli("setup", fake=True)
    assert result.returncode == 0, result.stderr

    after = _status_event(run_cli("status", fake=True), events)
    assert after["venv_ready"] is True
    assert after["missing"] == ["mpv"]  # the tester's other override survives


# --- real mode ignores the fake files ----------------------------------------
def test_real_mode_never_reads_the_fake_files(
    run_cli, events, validate_event, paths: Paths
):
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.auth_file.write_text("{}", encoding="utf-8")
    paths.account_file.write_text(
        json.dumps({"account": "f***@example.com"}), encoding="utf-8"
    )
    (paths.config_dir / FAKE_STATUS_FILENAME).write_text(
        json.dumps({"missing": ["not-a-real-tool"], "venv_ready": False}),
        encoding="utf-8",
    )
    (paths.config_dir / SIGNED_OUT_MARKER).write_text("", encoding="utf-8")
    _make_ready_venv(paths)

    status = _status_event(run_cli("status"), events)
    validate_event(status)
    assert status["authenticated"] is True
    assert status["venv_ready"] is True
    assert "not-a-real-tool" not in status["missing"]
    assert status["account"] == "f***@example.com"


def test_fake_status_in_the_real_tree_is_not_read(run_cli, events, paths: Paths):
    """A ``fake-status.json`` under the real config dir must not change status."""
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.auth_file.write_text("{}", encoding="utf-8")
    (paths.config_dir / FAKE_STATUS_FILENAME).write_text(
        json.dumps({"missing": ["not-a-real-tool"]}), encoding="utf-8"
    )
    status = _status_event(run_cli("status"), events)
    assert "not-a-real-tool" not in status["missing"]

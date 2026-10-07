"""B3 — auth commands: ``login-start`` / ``login-finish`` / ``login-import-cli`` / ``logout``.

The ``audible`` library is not installed for the suite, so the commands are
driven through an injected :class:`AudiblePort` fake; the CLI tests run in fake
mode. The suite covers the ARCHITECTURE 4.7 acceptance list: file modes, a
``0644`` import source, expired/bad URLs, the "code never leaks" contract, and
the rule that only a login we created is ever deregistered.
"""

from __future__ import annotations

import io
import json
import stat
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from omarchy_audible import auth, commands, protocol
from omarchy_audible.errors import PipelineError
from omarchy_audible.paths import Paths

CODE = "AUTHCODE1234567890"
DECOY_CODE = "ARGVCODE0987654321"
URL = (
    "https://www.amazon.com/ap/maplanding"
    f"?openid.oa2.authorization_code={CODE}&openid.mode=checkid_setup"
)
DECOY_URL = (
    f"https://www.amazon.com/ap/maplanding?openid.oa2.authorization_code={DECOY_CODE}"
)
ACCOUNT = "fake@example.com"
DEFAULT_INFO = {"email": ACCOUNT, "user_id": "amzn1.account.FAKEUSER"}
FAKE_BYTES = "FAKEAB12"


class FakeAuth:
    """Stand-in for ``audible.Authenticator`` with recorded calls."""

    def __init__(
        self,
        *,
        activation_bytes: str = FAKE_BYTES,
        customer_info: dict | None = None,
        deregister_error: Exception | None = None,
    ) -> None:
        self.locale: object | None = None
        self.activation_bytes = activation_bytes
        self.customer_info = customer_info
        self.with_username: bool | None = None
        self.deregister_error = deregister_error
        self.deregister_calls: list[bool] = []
        self.to_file_calls: list[tuple[Path, object]] = []

    def _update_attrs(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)

    def get_activation_bytes(self) -> str:
        return self.activation_bytes

    def to_file(self, path, encryption=False, **kwargs) -> None:
        self.to_file_calls.append((Path(path), encryption))
        Path(path).write_text(
            json.dumps(
                {
                    "fake": True,
                    "locale_code": getattr(self.locale, "country_code", None),
                }
            ),
            encoding="utf-8",
        )

    def deregister_device(self, deregister_all: bool = False) -> None:
        if self.deregister_error is not None:
            raise self.deregister_error
        self.deregister_calls.append(deregister_all)


class FakeAudible:
    """Stand-in for the ``audible`` library's login/register/authenticator API."""

    def __init__(
        self,
        *,
        register_error: Exception | None = None,
        activation_bytes: str = FAKE_BYTES,
        customer_info: dict | None = None,
        deregister_error: Exception | None = None,
    ) -> None:
        self.register_error = register_error
        self.activation_bytes = activation_bytes
        self.customer_info = (
            dict(DEFAULT_INFO) if customer_info is None else customer_info
        )
        self.deregister_error = deregister_error
        self.oauth_calls: list[dict] = []
        self.register_calls: list[dict] = []
        self.authenticators: list[FakeAuth] = []
        self.loaded_files: list[Path] = []
        self.last_loaded: FakeAuth | None = None

    def create_code_verifier(self) -> bytes:
        return b"FAKEVERIFIER"

    def build_oauth_url(
        self, *, country_code, domain, market_place_id, code_verifier
    ) -> tuple[str, str]:
        self.oauth_calls.append(
            {
                "country_code": country_code,
                "domain": domain,
                "market_place_id": market_place_id,
            }
        )
        return (f"https://www.amazon.{domain}/ap/signin?fake=1", "FAKESERIAL01")

    def locale(self, marketplace: str) -> SimpleNamespace:
        return SimpleNamespace(
            country_code=marketplace, domain="com", market_place_id="AF2M0KC94RCEA"
        )

    def register(self, *, authorization_code, code_verifier, domain, serial) -> dict:
        self.register_calls.append(
            {
                "authorization_code": authorization_code,
                "code_verifier": code_verifier,
                "domain": domain,
                "serial": serial,
            }
        )
        if self.register_error is not None:
            raise self.register_error
        return {
            "access_token": "fake-access",
            "refresh_token": "fake-refresh",
            "device_info": {"device_serial_number": serial},
            "customer_info": self.customer_info,
        }

    def authenticator(self) -> FakeAuth:
        instance = FakeAuth(activation_bytes=self.activation_bytes)
        self.authenticators.append(instance)
        return instance

    def authenticator_from_file(self, path: Path) -> FakeAuth:
        self.loaded_files.append(Path(path))
        self.last_loaded = FakeAuth(
            activation_bytes=self.activation_bytes,
            customer_info=self.customer_info,
            deregister_error=self.deregister_error,
        )
        return self.last_loaded


def _collect():
    events: list[dict] = []

    def emit(event_type: str, **fields) -> None:
        events.append({"type": event_type, **fields})

    return events, emit


def _write_session(paths: Paths, session_id: str, **overrides) -> Path:
    payload = {
        "schema": 1,
        "verifier": "FAKEVERIFIER",
        "serial": "FAKESERIAL01",
        "marketplace": "us",
        "created": time.time(),
    }
    payload.update(overrides)
    path = paths.login_session(session_id)
    auth._write_private_json(path, payload)
    return path


def _files_under(root: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for path in root.rglob("*"):
        if path.is_file():
            try:
                found[str(path)] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:  # pragma: no cover - unreadable scratch file
                continue
    return found


def _mode(path: Path) -> str:
    return oct(stat.S_IMODE(path.stat().st_mode))


# --- login-start -------------------------------------------------------------
def test_login_start_builds_the_url_offline_and_stores_a_0600_session(paths: Paths):
    port = FakeAudible()
    events, emit = _collect()
    session_id = auth.login_start(
        paths, marketplace="us", fake=False, api=port, emit=emit
    )

    assert events == [
        {"type": "login_url", "url": events[0]["url"], "session": session_id}
    ]
    assert events[0]["url"].startswith("https://www.amazon.com/ap/signin")
    assert port.oauth_calls[0]["domain"] == "com"

    session = paths.login_session(session_id)
    assert _mode(session) == "0o600"
    payload = json.loads(session.read_text(encoding="utf-8"))
    assert payload["marketplace"] == "us"
    assert payload["serial"] == "FAKESERIAL01"
    assert "verifier" in payload
    assert port.register_calls == []  # login-start makes no network call


def test_login_start_rejects_an_unknown_marketplace(paths: Paths):
    with pytest.raises(PipelineError) as info:
        auth.login_start(paths, marketplace="zz", fake=False, api=FakeAudible())
    assert info.value.code == "invalid_args"


def test_login_start_purges_expired_sessions(paths: Paths):
    stale = _write_session(paths, "stalestale", created=time.time() - 700)
    auth.login_start(paths, marketplace="us", fake=False, api=FakeAudible())
    assert not stale.exists()


# --- login-finish ------------------------------------------------------------
def test_login_finish_registers_and_writes_private_files(paths: Paths):
    port = FakeAudible()
    session_id = auth.login_start(paths, marketplace="us", fake=False, api=port)

    outcome = auth.login_finish(
        paths, session_id=session_id, pasted_url=URL, fake=False, api=port
    )
    assert outcome.clipboard_contains_code is False
    assert outcome.warning is None

    assert not paths.login_session(session_id).exists()
    for path in (
        paths.auth_file,
        paths.activation_bytes_file,
        paths.config_toml,
        paths.account_file,
    ):
        assert path.is_file(), path
        assert _mode(path) == "0o600", path
    assert _mode(paths.config_dir) == "0o700"

    assert paths.activation_bytes_file.read_text(encoding="utf-8") == FAKE_BYTES
    config = paths.config_toml.read_text(encoding="utf-8")
    assert 'auth_file = "auth.json"' in config
    assert 'country_code = "us"' in config

    record = json.loads(paths.account_file.read_text(encoding="utf-8"))
    assert record["origin"] == "login"
    assert record["marketplace"] == "us"
    assert record["account"] == "f***@example.com"  # masked, never the raw address

    call = port.register_calls[0]
    assert call["authorization_code"] == CODE
    assert call["code_verifier"] == b"FAKEVERIFIER"
    assert call["serial"] == "FAKESERIAL01"
    assert call["domain"] == "com"
    assert port.authenticators[0].to_file_calls[0][1] is False


def test_login_finish_reads_the_url_from_stdin_not_argv(
    paths: Paths, monkeypatch: pytest.MonkeyPatch, capsys
):
    port = FakeAudible()
    monkeypatch.setattr(auth, "RealAudible", lambda: port)
    session_id = auth.login_start(paths, marketplace="us", fake=False, api=port)
    monkeypatch.setattr(sys, "stdin", io.StringIO(URL))

    code = commands.cmd_login_finish(
        ["--session", session_id, "--url", DECOY_URL],
        command="login-finish",
        fake=False,
        paths=paths,
    )
    assert code == protocol.EXIT_OK
    # The code in argv was ignored; the one on stdin was redeemed.
    assert port.register_calls[0]["authorization_code"] == CODE
    output = capsys.readouterr()
    assert DECOY_CODE not in output.out
    assert DECOY_CODE not in output.err


def test_login_finish_rejects_a_bad_url_and_keeps_the_session(paths: Paths):
    port = FakeAudible()
    session_id = auth.login_start(paths, marketplace="us", fake=False, api=port)

    with pytest.raises(PipelineError) as info:
        auth.login_finish(
            paths, session_id=session_id, pasted_url="not-a-url", fake=False, api=port
        )
    assert info.value.code == "bad_url"
    assert paths.login_session(session_id).exists()
    assert port.register_calls == []


def test_login_finish_rejects_an_expired_session(paths: Paths):
    session = _write_session(paths, "stalesession1", created=time.time() - 700)
    with pytest.raises(PipelineError) as info:
        auth.login_finish(
            paths,
            session_id="stalesession1",
            pasted_url=URL,
            fake=False,
            api=FakeAudible(),
        )
    assert info.value.code == "expired"
    assert not session.exists()


def test_login_finish_with_no_session_is_expired(paths: Paths):
    with pytest.raises(PipelineError) as info:
        auth.login_finish(
            paths,
            session_id="nosuchsession",
            pasted_url=URL,
            fake=False,
            api=FakeAudible(),
        )
    assert info.value.code == "expired"


def test_login_finish_auth_failure_deletes_the_session(paths: Paths):
    port = FakeAudible(register_error=RuntimeError("rejected"))
    session_id = auth.login_start(paths, marketplace="us", fake=False, api=port)

    with pytest.raises(PipelineError) as info:
        auth.login_finish(
            paths, session_id=session_id, pasted_url=URL, fake=False, api=port
        )
    assert info.value.code == "auth_failed"
    assert not paths.login_session(session_id).exists()
    assert not paths.auth_file.exists()


# --- login-import-cli --------------------------------------------------------
def _make_cli_login(root: Path, *, mode: int = 0o644) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.toml").write_text(
        'title = "Audible Config File"\n\n[APP]\nprimary_profile = "primary"\n\n'
        '[profile.primary]\nauth_file = "auth.json"\ncountry_code = "de"\n',
        encoding="utf-8",
    )
    source = root / "auth.json"
    source.write_text(
        json.dumps({"locale_code": "de", "activation_bytes": "ABCD1234"}),
        encoding="utf-8",
    )
    source.chmod(mode)
    return source


def test_import_copies_a_0644_source_as_0600(tmp_path: Path, paths: Paths):
    source = _make_cli_login(tmp_path / "audible-cli", mode=0o644)
    assert _mode(source) == "0o644"

    auth.login_import_cli(
        paths, source_dir=source.parent, fake=False, api=FakeAudible()
    )

    assert _mode(paths.auth_file) == "0o600"
    assert paths.auth_file.read_text(encoding="utf-8") == source.read_text(
        encoding="utf-8"
    )
    assert _mode(paths.activation_bytes_file) == "0o600"
    assert _mode(paths.config_toml) == "0o600"
    assert _mode(paths.account_file) == "0o600"
    record = json.loads(paths.account_file.read_text(encoding="utf-8"))
    assert record["origin"] == "import"
    assert record["marketplace"] == "de"
    assert 'country_code = "de"' in paths.config_toml.read_text(encoding="utf-8")


def test_import_without_a_cli_login_reports_no_auth_file(tmp_path: Path, paths: Paths):
    with pytest.raises(PipelineError) as info:
        auth.login_import_cli(
            paths, source_dir=tmp_path / "missing", fake=False, api=FakeAudible()
        )
    assert info.value.code == "no_auth_file"


def test_import_with_a_config_but_no_auth_file_reports_no_auth_file(
    tmp_path: Path, paths: Paths
):
    source_dir = tmp_path / "audible-cli"
    source_dir.mkdir()
    (source_dir / "config.toml").write_text(
        '[APP]\nprimary_profile = "primary"\n\n'
        '[profile.primary]\nauth_file = "auth.json"\ncountry_code = "us"\n',
        encoding="utf-8",
    )
    with pytest.raises(PipelineError) as info:
        auth.login_import_cli(
            paths, source_dir=source_dir, fake=False, api=FakeAudible()
        )
    assert info.value.code == "no_auth_file"


# --- logout ------------------------------------------------------------------
def test_logout_after_login_deregisters_only_this_device(paths: Paths):
    port = FakeAudible()
    session_id = auth.login_start(paths, marketplace="us", fake=False, api=port)
    auth.login_finish(
        paths, session_id=session_id, pasted_url=URL, fake=False, api=port
    )

    logout_port = FakeAudible()
    auth.logout(paths, fake=False, api=logout_port)

    assert logout_port.loaded_files == [paths.auth_file]
    assert logout_port.last_loaded is not None
    assert logout_port.last_loaded.deregister_calls == [False]
    for path in (
        paths.auth_file,
        paths.activation_bytes_file,
        paths.config_toml,
        paths.account_file,
    ):
        assert not path.exists(), path


def test_logout_after_import_never_deregisters(tmp_path: Path, paths: Paths):
    source = _make_cli_login(tmp_path / "audible-cli")
    auth.login_import_cli(
        paths, source_dir=source.parent, fake=False, api=FakeAudible()
    )

    logout_port = FakeAudible()
    auth.logout(paths, fake=False, api=logout_port)

    # An imported file is the user's existing device: no load, no deregister.
    assert logout_port.loaded_files == []
    assert not paths.auth_file.exists()


def test_logout_with_no_recorded_origin_never_deregisters(paths: Paths):
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.auth_file.write_text("{}", encoding="utf-8")

    logout_port = FakeAudible()
    auth.logout(paths, fake=False, api=logout_port)

    assert logout_port.loaded_files == []
    assert not paths.auth_file.exists()


def test_logout_deregister_failure_is_best_effort(paths: Paths):
    port = FakeAudible()
    session_id = auth.login_start(paths, marketplace="us", fake=False, api=port)
    auth.login_finish(
        paths, session_id=session_id, pasted_url=URL, fake=False, api=port
    )

    failing = FakeAudible(deregister_error=RuntimeError("offline"))
    auth.logout(paths, fake=False, api=failing)  # must not raise

    assert not paths.auth_file.exists()


def test_deregister_all_true_never_appears():
    root = Path(__file__).resolve().parents[1]
    sources = sorted((root / "backend" / "omarchy_audible").glob("*.py")) + [
        root / "bin" / "omarchy-audible"
    ]
    offenders: list[str] = []
    for path in sources:
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            compact = line.replace(" ", "")
            if "deregister_all=True" in compact:
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, "deregister_all=True found:\n" + "\n".join(offenders)
    # And the one legitimate call really is the False form.
    assert "deregister_device(deregister_all=False)" in (
        root / "backend" / "omarchy_audible" / "auth.py"
    ).read_text(encoding="utf-8")


# --- the code must never leak ------------------------------------------------
def test_pasted_url_and_code_never_reach_logs_events_or_files(
    tmp_path: Path, paths: Paths, capsys
):
    port = FakeAudible()
    events, emit = _collect()
    session_id = auth.login_start(
        paths, marketplace="us", fake=False, api=port, emit=emit
    )
    auth.login_finish(
        paths, session_id=session_id, pasted_url=URL, fake=False, api=port
    )
    captured = capsys.readouterr()

    # The code really was redeemed (the test is not passing by doing nothing).
    assert port.register_calls[0]["authorization_code"] == CODE

    blob = json.dumps(events) + captured.out + captured.err
    assert CODE not in blob
    assert URL not in blob
    for name, text in _files_under(tmp_path).items():
        assert CODE not in text, name
        assert URL not in text, name

    # The documented invocation carries only the session id, never the URL.
    argv = ["login-finish", "--session", session_id]
    assert CODE not in " ".join(argv)


def test_cli_fake_login_round_trip_keeps_the_code_out_of_output(
    tmp_path: Path, run_cli, events, validate_stream
):
    start = run_cli("login-start", "--marketplace", "us", fake=True)
    started = validate_stream(start, expect_last="done")
    session_id = started[0]["session"]

    finish = run_cli("login-finish", "--session", session_id, fake=True, stdin=URL)
    validate_stream(finish, expect_last="done")
    assert CODE not in finish.stdout
    assert CODE not in finish.stderr
    for name, text in _files_under(tmp_path).items():
        assert CODE not in text, name


def test_fake_login_never_writes_into_the_plugin_config_dir(
    run_cli, events, validate_stream, paths: Paths
):
    start = run_cli("login-start", "--marketplace", "us", fake=True)
    session_id = validate_stream(start, expect_last="done")[0]["session"]
    run_cli("login-finish", "--session", session_id, fake=True, stdin=URL)

    assert not paths.auth_file.exists()
    assert not paths.account_file.exists()
    assert not paths.config_toml.exists()


# --- status ------------------------------------------------------------------
def test_status_reports_authentication_marketplace_and_account(
    run_cli, events, validate_event, paths: Paths
):
    before = events(run_cli("status"))
    assert before[0]["authenticated"] is False
    assert before[0]["marketplace"] == "us"
    assert before[0]["account"] is None
    validate_event(before[0])

    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.auth_file.write_text("{}", encoding="utf-8")
    paths.account_file.write_text(
        json.dumps(
            {"origin": "login", "marketplace": "de", "account": "f***@example.com"}
        ),
        encoding="utf-8",
    )

    after = events(run_cli("status"))
    assert after[0]["authenticated"] is True
    assert after[0]["marketplace"] == "de"
    assert after[0]["account"] == "f***@example.com"
    validate_event(after[0])


def test_auth_commands_have_the_documented_job_classification():
    assert commands.REGISTRY["login-start"].is_job is False
    assert commands.REGISTRY["login-finish"].is_job is True
    assert commands.REGISTRY["login-import-cli"].is_job is True
    assert commands.REGISTRY["logout"].is_job is True

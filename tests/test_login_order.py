"""B13 — ``login-finish`` saves before fetching activation bytes (F5).

Two behaviours are pinned here:

* ``login-finish`` persists ``auth.json``, ``config.toml`` and ``account.json``
  before the activation-bytes fetch, and a failed fetch still returns ``done``
  (with a ``warning``) — never an error that would tell the user to sign in
  again and register another device.
* ``play-info`` lazily fetches the account-wide AAX key for a legacy aax book
  when it is missing, writes it ``0600`` and continues; a failed fetch stays
  ``error(decrypt)``. aaxc and old ``book.m4b`` books never fetch.

Every port below is a stub holding invented values; no real Audible call is
made and no real credential directory is touched.
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
from omarchy_audible.paths import Paths

CODE = "AUTHCODE1234567890"
URL = (
    "https://www.amazon.com/ap/maplanding"
    f"?openid.oa2.authorization_code={CODE}&openid.mode=checkid_setup"
)
ACCOUNT = "fake@example.com"
FAKE_BYTES = "FAKEAB12"
# An invented sentinel, standing in for key material an exception message might
# carry: it must never reach stdout or stderr.
LEAK = "PRETENDKEY0123456789"
ASIN = "B00FAKE01"


def _mode(path: Path) -> str:
    return oct(stat.S_IMODE(path.stat().st_mode))


def _events(output: str) -> list[dict]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


class StubAuth:
    """Stand-in for ``audible.Authenticator`` with recorded calls."""

    def __init__(
        self,
        *,
        activation: str | None = FAKE_BYTES,
        activation_error: Exception | None = None,
    ) -> None:
        self.locale: object | None = None
        self.activation_bytes = activation
        self.activation_error = activation_error
        self.customer_info: dict | None = {"email": ACCOUNT}
        self.with_username: bool | None = None
        self.deregister_calls: list[bool] = []
        self.to_file_calls: list[tuple[Path, object]] = []

    def _update_attrs(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)

    def get_activation_bytes(self) -> str | None:
        if self.activation_error is not None:
            raise self.activation_error
        return self.activation_bytes

    def to_file(self, path, encryption=False, **kwargs) -> None:
        self.to_file_calls.append((Path(path), encryption))
        Path(path).write_text(json.dumps({"fake": True}), encoding="utf-8")

    def deregister_device(self, deregister_all: bool = False) -> None:
        self.deregister_calls.append(deregister_all)


class StubAudible:
    """Stand-in for the ``audible`` login/register/authenticator API."""

    def __init__(
        self,
        *,
        activation: str | None = FAKE_BYTES,
        activation_error: Exception | None = None,
    ) -> None:
        self.activation = activation
        self.activation_error = activation_error
        self.register_calls: list[str] = []
        self.authenticators: list[StubAuth] = []
        self.loaded_files: list[Path] = []

    def create_code_verifier(self) -> bytes:
        return b"FAKEVERIFIER"

    def build_oauth_url(
        self, *, country_code, domain, market_place_id, code_verifier
    ) -> tuple[str, str]:
        return (f"https://www.amazon.{domain}/ap/signin?fake=1", "FAKESERIAL01")

    def locale(self, marketplace: str) -> SimpleNamespace:
        return SimpleNamespace(
            country_code=marketplace, domain="com", market_place_id="AF2M0KC94RCEA"
        )

    def register(self, *, authorization_code, code_verifier, domain, serial) -> dict:
        self.register_calls.append(authorization_code)
        return {
            "access_token": "fake-access",
            "refresh_token": "fake-refresh",
            "device_info": {"device_serial_number": serial},
            "customer_info": {"email": ACCOUNT},
        }

    def authenticator(self) -> StubAuth:
        instance = StubAuth(
            activation=self.activation, activation_error=self.activation_error
        )
        self.authenticators.append(instance)
        return instance

    def authenticator_from_file(self, path: Path) -> StubAuth:
        self.loaded_files.append(Path(path))
        return StubAuth(
            activation=self.activation, activation_error=self.activation_error
        )


def _write_session(paths: Paths, session_id: str = "session1234") -> None:
    auth._write_private_json(
        paths.login_session(session_id),
        {
            "schema": 1,
            "verifier": "FAKEVERIFIER",
            "serial": "FAKESERIAL01",
            "marketplace": "us",
            "created": time.time(),
        },
    )


def _write_aax_book(paths: Paths, asin: str = ASIN) -> Path:
    """A legacy aax book: ``book.aax`` plus a reference ``key.json``."""
    directory = paths.books_dir / asin
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "book.aax").write_bytes(b"locked audio")
    (directory / "key.json").write_text(json.dumps({"format": "aax"}), encoding="utf-8")
    (directory / "chapters.txt").write_text(";FFMETADATA1\n", encoding="utf-8")
    return directory


def _write_aaxc_book(paths: Paths, asin: str = ASIN) -> Path:
    directory = paths.books_dir / asin
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "book.aaxc").write_bytes(b"locked audio")
    (directory / "key.json").write_text(
        json.dumps({"format": "aaxc", "key": "0011223344", "iv": "aabbccddee"}),
        encoding="utf-8",
    )
    (directory / "chapters.txt").write_text(";FFMETADATA1\n", encoding="utf-8")
    return directory


def _with_login(paths: Paths) -> None:
    """A saved login: ``auth.json`` exists so the lazy fill has something to use."""
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.auth_file.write_text("{}", encoding="utf-8")


# --- login-finish ordering ---------------------------------------------------
def test_login_finish_keeps_the_login_when_activation_bytes_fail(paths: Paths, capsys):
    port = StubAudible(activation_error=RuntimeError(f"backend said {LEAK}"))
    session_id = auth.login_start(paths, marketplace="us", fake=False, api=port)

    outcome = auth.login_finish(
        paths,
        session_id=session_id,
        pasted_url=URL,
        fake=False,
        api=port,
        clipboard_check=False,
    )

    assert outcome.warning == auth.WARNING_ACTIVATION_BYTES
    assert outcome.clipboard_contains_code is False
    # The three credential files exist 0600 before the fetch is even attempted.
    for path in (paths.auth_file, paths.config_toml, paths.account_file):
        assert path.is_file(), path
        assert _mode(path) == "0o600", path
    # The key was simply not fetched; no half-written file is left.
    assert not paths.activation_bytes_file.exists()
    # Exactly one registration, and the device is never deregistered.
    assert len(port.register_calls) == 1
    assert port.authenticators[0].deregister_calls == []
    assert not paths.login_session(session_id).exists()

    # Only the exception type is logged: not its message, not the advice to
    # start the login again (which would register another device).
    err = capsys.readouterr().err
    assert "RuntimeError" in err
    assert LEAK not in err
    assert "login again" not in err.lower()
    assert "sign in again" not in err.lower()


def test_login_finish_happy_path_still_saves_the_activation_bytes(paths: Paths):
    port = StubAudible()
    session_id = auth.login_start(paths, marketplace="us", fake=False, api=port)

    outcome = auth.login_finish(
        paths,
        session_id=session_id,
        pasted_url=URL,
        fake=False,
        api=port,
        clipboard_check=False,
    )

    assert outcome.warning is None
    assert paths.activation_bytes_file.read_text(encoding="utf-8") == FAKE_BYTES
    assert _mode(paths.activation_bytes_file) == "0o600"


def test_login_finish_done_carries_the_warning_and_never_advises_a_restart(
    tmp_path: Path,
    paths: Paths,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    validate_event,
):
    port = StubAudible(activation_error=ConnectionError("offline"))
    monkeypatch.setattr(auth, "RealAudible", lambda: port)
    monkeypatch.setenv("HOME", str(tmp_path))  # never read the real clipboard history
    _write_session(paths)
    monkeypatch.setattr(sys, "stdin", io.StringIO(URL))

    code = commands.cmd_login_finish(
        ["--session", "session1234"],
        command="login-finish",
        fake=False,
        paths=paths,
    )
    assert code == protocol.EXIT_OK

    captured = capsys.readouterr()
    parsed = _events(captured.out)
    assert parsed[-1]["type"] == "done"
    assert parsed[-1]["warning"] == "activation_bytes"
    assert parsed[-1]["clipboard_history_contains_code"] is False
    validate_event(parsed[-1])  # the schema knows the warning field
    for text in (captured.out, captured.err):
        assert "login again" not in text.lower()
        assert "sign in again" not in text.lower()


# --- play-info lazy fill -----------------------------------------------------
def test_play_info_aax_lazily_fetches_and_writes_the_key(paths: Paths, capsys):
    _write_aax_book(paths)
    _with_login(paths)
    port = StubAudible(activation="AABBCCDD")

    code = commands.cmd_play_info(
        [ASIN], command="play-info", fake=False, paths=paths, api=port
    )
    assert code == protocol.EXIT_OK

    assert paths.activation_bytes_file.read_text(encoding="utf-8") == "AABBCCDD"
    assert _mode(paths.activation_bytes_file) == "0o600"
    assert port.loaded_files == [paths.auth_file]

    parsed = _events(capsys.readouterr().out)
    assert parsed[-1]["type"] == "done"
    info = next(event for event in parsed if event["type"] == "play_info")
    assert info["lavf_options"] == "activation_bytes=AABBCCDD"


def test_play_info_aax_lazy_fetch_failure_stays_a_decrypt_error(paths: Paths, capsys):
    _write_aax_book(paths)
    _with_login(paths)
    port = StubAudible(activation_error=RuntimeError(f"{LEAK}"))

    code = commands.cmd_play_info(
        [ASIN], command="play-info", fake=False, paths=paths, api=port
    )
    assert code == protocol.EXIT_ERROR

    captured = capsys.readouterr()
    parsed = _events(captured.out)
    assert parsed[-1]["type"] == "error"
    assert parsed[-1]["code"] == "decrypt"
    assert parsed[-1]["hint"]
    assert not any(event["type"] == "play_info" for event in parsed)
    assert not paths.activation_bytes_file.exists()
    # No key value and no exception text anywhere in the output.
    assert LEAK not in captured.out + captured.err
    assert "login again" not in (captured.out + captured.err).lower()
    assert "sign in again" not in (captured.out + captured.err).lower()


def test_play_info_aaxc_never_touches_the_activation_bytes(paths: Paths, capsys):
    _write_aaxc_book(paths)
    _with_login(paths)

    class Exploding(StubAudible):
        def authenticator_from_file(self, path: Path) -> StubAuth:  # pragma: no cover
            raise AssertionError("aaxc must not fetch activation bytes")

    code = commands.cmd_play_info(
        [ASIN], command="play-info", fake=False, paths=paths, api=Exploding()
    )
    assert code == protocol.EXIT_OK
    info = next(
        event
        for event in _events(capsys.readouterr().out)
        if event["type"] == "play_info"
    )
    assert info["lavf_options"] == "audible_key=0011223344,audible_iv=aabbccddee"


def test_play_info_aax_without_a_login_does_not_fetch(paths: Paths, capsys):
    _write_aax_book(paths)  # no auth.json: nothing to fetch with
    port = StubAudible()

    code = commands.cmd_play_info(
        [ASIN], command="play-info", fake=False, paths=paths, api=port
    )
    assert code == protocol.EXIT_ERROR
    assert port.loaded_files == []
    assert not paths.activation_bytes_file.exists()
    assert _events(capsys.readouterr().out)[-1]["code"] == "decrypt"

"""Auth commands: ``login-start``, ``login-finish``, ``login-import-cli``, ``logout``.

Implements ARCHITECTURE 4.7. The sign-in URL is built locally (no network
call); the user signs in in their browser and pastes the redirect URL on
**stdin** — never on the command line, so the one-time authorization code can
never be read from ``/proc/<pid>/cmdline``. The code is single-use and is never
logged, emitted, or written anywhere; the URL and the code are dropped as soon
as they have been used.

Every file written here lives in the plugin config directory (``0700``) and is
created ``0600`` under a ``077`` umask:

* ``auth.json`` — the device credentials (written by ``Authenticator.to_file``)
* ``activation_bytes`` — the account-wide legacy AAX key
* ``config.toml`` — an audible-cli profile pointing at ``auth.json``
* ``account.json`` — ``{origin, marketplace, account}``; ``origin`` records
  whether this login was created here (``login``) or imported from an existing
  audible-cli login (``import``)

``logout`` deregisters the device **only** when ``origin`` is ``login``: an
imported auth file is the user's existing device, so deregistering it would
break their audible-cli. A missing or unknown origin never deregisters, and
``deregister_all`` is never passed ``True``.

The ``audible`` library is imported lazily, inside real-mode code paths only,
so the test suite runs without it installed. Tests inject an
:class:`AudiblePort` implementation instead.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit

from . import fakestate, protocol
from .errors import PipelineError
from .library import iso_now
from .log import log
from .paths import Paths

# The marketplaces the plugin offers (SPIKE-RESULTS S1; audible's Locale
# templates). ``Locale(marketplace)`` accepts exactly these country codes.
MARKETPLACES: tuple[str, ...] = (
    "us",
    "uk",
    "de",
    "fr",
    "ca",
    "it",
    "au",
    "in",
    "jp",
    "es",
    "br",
)
DEFAULT_MARKETPLACE = "us"
SESSION_TTL_S = 600
ACCOUNT_SCHEMA = 1
ACCOUNT_FILENAME = "account.json"

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_AUTH_CODE_KEY = "openid.oa2.authorization_code"

Emitter = Callable[..., None]


class AudiblePort(Protocol):
    """The slice of the ``audible`` library the auth commands need.

    ``RealAudible`` wraps the library with lazy imports; tests pass a fake.
    """

    def create_code_verifier(self) -> bytes: ...

    def build_oauth_url(
        self,
        *,
        country_code: str,
        domain: str,
        market_place_id: str,
        code_verifier: bytes,
    ) -> tuple[str, str]: ...

    def locale(self, marketplace: str) -> Any: ...

    def register(
        self,
        *,
        authorization_code: str,
        code_verifier: bytes,
        domain: str,
        serial: str,
    ) -> dict[str, Any]: ...

    def authenticator(self) -> Any: ...

    def authenticator_from_file(self, path: Path) -> Any: ...


class RealAudible:
    """``AudiblePort`` backed by the ``audible`` library, imported on demand.

    Nothing imports ``audible`` at module import time, so every command that
    does not need it (including the whole fake-mode suite) runs without it
    installed.
    """

    def create_code_verifier(self) -> bytes:
        from audible.login import create_code_verifier

        return create_code_verifier()

    def build_oauth_url(
        self,
        *,
        country_code: str,
        domain: str,
        market_place_id: str,
        code_verifier: bytes,
    ) -> tuple[str, str]:
        from audible.login import build_oauth_url

        return build_oauth_url(
            country_code=country_code,
            domain=domain,
            market_place_id=market_place_id,
            code_verifier=code_verifier,
        )

    def locale(self, marketplace: str) -> Any:
        from audible.localization import Locale

        return Locale(marketplace)

    def register(
        self,
        *,
        authorization_code: str,
        code_verifier: bytes,
        domain: str,
        serial: str,
    ) -> dict[str, Any]:
        from audible.register import register

        return register(
            authorization_code=authorization_code,
            code_verifier=code_verifier,
            domain=domain,
            serial=serial,
        )

    def authenticator(self) -> Any:
        import audible

        return audible.Authenticator()

    def authenticator_from_file(self, path: Path) -> Any:
        import audible

        return audible.Authenticator.from_file(path)


# --- private files -----------------------------------------------------------
def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path, 0o700)
    except OSError:  # pragma: no cover - a pre-existing dir we cannot chmod
        pass


def _write_private_text(path: Path, text: str) -> None:
    """Create ``path`` as ``0600`` and write ``text`` to it."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = text.encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def _write_private_json(path: Path, data: Any) -> None:
    _write_private_text(
        path, json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n"
    )


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def config_toml(marketplace: str) -> str:
    """The audible-cli profile that points at the plugin's ``auth.json``."""
    return (
        'title = "Audible Config File"\n'
        "\n"
        "[APP]\n"
        'primary_profile = "plugin"\n'
        "\n"
        "[profile.plugin]\n"
        'auth_file = "auth.json"\n'
        f'country_code = "{marketplace}"\n'
    )


def _default_audible_dir() -> Path:
    return Path(os.environ.get("HOME") or Path.home()) / ".audible"


def _clipboard_history_path() -> Path:
    home = Path(os.environ.get("HOME") or Path.home())
    return home / ".local" / "state" / "omarchy" / "clipboard-history.json"


def mask_account(value: Any) -> str | None:
    """Mask an account address for ``status`` (``j***@gmail.com``)."""
    if not isinstance(value, str) or "@" not in value:
        return None
    local, _, domain = value.partition("@")
    if not local or not domain:
        return None
    return f"{local[0]}***@{domain}"


def account_from_info(info: Any) -> str | None:
    """The account label for a ``customer_info`` mapping (ARCHITECTURE 4.7).

    A masked email wins when there is one; otherwise the first name, from
    ``given_name`` then ``name`` (B9). ``user_id`` is never used.
    """
    if not isinstance(info, dict):
        return None
    for key in ("email", "email_address"):
        masked = mask_account(info.get(key))
        if masked:
            return masked
    for key in ("given_name", "name"):
        value = info.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().split()[0]
    return None


def account_from_auth_file(path: Path) -> str | None:
    """The fallback account label read from a saved ``auth.json`` (B9).

    Plain JSON only: no network call and no ``audible`` import. Returns ``None``
    when the file is missing, unreadable, or has no usable ``customer_info``.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return account_from_info(data.get("customer_info"))


def _account_payload(origin: str, marketplace: str, account: str | None) -> dict[str, Any]:
    return {
        "schema": ACCOUNT_SCHEMA,
        "origin": origin,
        "marketplace": marketplace,
        "account": account,
        "created_at": iso_now(),
    }


def read_account_record(paths: Paths) -> dict[str, Any]:
    """Read ``account.json``, or ``{}`` when it is absent or unreadable."""
    try:
        data = json.loads(paths.account_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _persist_login(
    paths: Paths,
    auth: Any,
    activation_bytes: Any,
    marketplace: str,
    account: str | None,
) -> None:
    _ensure_private_dir(paths.config_dir)
    previous = os.umask(0o077)
    try:
        # ``Authenticator.to_file`` writes with the process umask; force the
        # mode afterwards too, so the file is 0600 whatever the umask was.
        auth.to_file(paths.auth_file, encryption=False)
    finally:
        os.umask(previous)
    os.chmod(paths.auth_file, 0o600)
    if isinstance(activation_bytes, str) and activation_bytes:
        _write_private_text(paths.activation_bytes_file, activation_bytes)
    _write_private_text(paths.config_toml, config_toml(marketplace))
    _write_private_json(
        paths.account_file, _account_payload("login", marketplace, account)
    )


def _persist_import(
    paths: Paths, text: str, marketplace: str, account: str | None, auth: Any
) -> None:
    _ensure_private_dir(paths.config_dir)
    # Written 0600 regardless of the source mode (audible-cli leaves it 0644).
    _write_private_text(paths.auth_file, text)
    activation = getattr(auth, "activation_bytes", None)
    if isinstance(activation, str) and activation:
        _write_private_text(paths.activation_bytes_file, activation)
    _write_private_text(paths.config_toml, config_toml(marketplace))
    _write_private_json(
        paths.account_file, _account_payload("import", marketplace, account)
    )


# --- login session -----------------------------------------------------------
def valid_session_id(session_id: Any) -> bool:
    """A session id becomes exactly one file name (no separators, no ``..``)."""
    return isinstance(session_id, str) and bool(_SESSION_ID_RE.match(session_id))


def _read_session(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if not all(key in data for key in ("verifier", "serial", "marketplace", "created")):
        return None
    return data


def _expired(payload: dict[str, Any], now: float | None = None) -> bool:
    created = payload.get("created")
    if not isinstance(created, (int, float)):
        return True
    moment = time.time() if now is None else float(now)
    return moment - created > SESSION_TTL_S


def purge_expired_sessions(paths: Paths, *, now: float | None = None) -> None:
    """Remove stale ``login-*.json`` sessions from the runtime directory."""
    try:
        entries = sorted(paths.runtime_dir.glob("login-*.json"))
    except OSError:
        return
    for entry in entries:
        payload = _read_session(entry)
        if payload is None or _expired(payload, now):
            _unlink(entry)


def extract_authorization_code(raw: str) -> str:
    """Pull ``openid.oa2.authorization_code`` out of a pasted redirect URL."""
    if not raw or not raw.strip():
        raise ValueError("empty input")
    query = urlsplit(raw.strip()).query
    values = parse_qs(query).get(_AUTH_CODE_KEY)
    if not values or not values[0]:
        raise ValueError("no authorization code")
    return values[0]


def _clipboard_contains(code: str) -> bool:
    """True when Omarchy's clipboard history holds ``code`` (ARCHITECTURE 4.7)."""
    try:
        text = _clipboard_history_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return code in text


# --- commands ----------------------------------------------------------------
def login_start(
    paths: Paths,
    *,
    marketplace: str = DEFAULT_MARKETPLACE,
    fake: bool,
    api: AudiblePort | None = None,
    emit: Emitter = protocol.emit,
    now: float | None = None,
) -> str:
    """Build the sign-in URL and store the pending session; return its id.

    Makes no network call: it only builds the URL and writes
    ``login-<id>.json`` (0600, tmpfs) for ``login-finish`` (ARCHITECTURE 4.7).
    """
    marketplace = str(marketplace)
    if marketplace not in MARKETPLACES:
        raise PipelineError(
            protocol.ErrorCode.INVALID_ARGS,
            f"unknown marketplace: {marketplace}",
            hint="one of: " + ", ".join(MARKETPLACES),
        )
    purge_expired_sessions(paths, now=now)
    session_id = secrets.token_urlsafe(12)

    if fake:
        url = f"https://www.amazon.com/ap/signin?audible_fake=1&marketplace={marketplace}"
        serial = "FAKESERIAL01"
        verifier = b"fake-code-verifier"
    else:
        port = api or RealAudible()
        try:
            locale = port.locale(marketplace)
        except Exception as exc:  # the marketplace was validated
            raise PipelineError(
                protocol.ErrorCode.INVALID_ARGS,
                f"unknown marketplace: {marketplace}",
                hint="one of: " + ", ".join(MARKETPLACES),
            ) from exc
        verifier = port.create_code_verifier()
        url, serial = port.build_oauth_url(
            country_code=locale.country_code,
            domain=locale.domain,
            market_place_id=locale.market_place_id,
            code_verifier=verifier,
        )

    _write_private_json(
        paths.login_session(session_id),
        {
            "schema": 1,
            "verifier": verifier.decode("ascii"),
            "serial": serial,
            "marketplace": marketplace,
            "created": time.time() if now is None else float(now),
        },
    )
    emit("login_url", url=url, session=session_id)
    return session_id


def login_finish(
    paths: Paths,
    *,
    session_id: str,
    pasted_url: str,
    fake: bool,
    api: AudiblePort | None = None,
    clipboard_check: bool = True,
    now: float | None = None,
) -> bool:
    """Redeem the pasted redirect URL and save the credentials.

    Returns whether Omarchy's clipboard history still holds the (already
    redeemed) code, so the UI can tell the user to clear it
    (ARCHITECTURE 4.7). The session file is deleted on success and on any
    auth failure; a malformed URL keeps it, so the user can paste again.
    """
    session_path = paths.login_session(session_id)
    payload = _read_session(session_path)
    if payload is None:
        raise PipelineError(
            protocol.ErrorCode.EXPIRED,
            "no pending login session",
            hint="start the login again",
        )
    if _expired(payload, now):
        _unlink(session_path)
        raise PipelineError(
            protocol.ErrorCode.EXPIRED,
            "the login session has expired",
            hint="start the login again",
        )
    try:
        code = extract_authorization_code(pasted_url)
    except ValueError as exc:
        raise PipelineError(
            protocol.ErrorCode.BAD_URL,
            "the pasted URL has no authorization code",
            hint="copy the address of the Amazon 'page not found' page",
        ) from exc

    if fake:
        _unlink(session_path)
        fakestate.mark_signed_in(paths)
        return False

    port = api or RealAudible()
    try:
        locale = port.locale(str(payload["marketplace"]))
    except Exception as exc:
        _unlink(session_path)
        raise PipelineError(
            protocol.ErrorCode.EXPIRED,
            "the pending login used an unknown marketplace",
            hint="start the login again",
        ) from exc

    try:
        registration = port.register(
            authorization_code=code,
            code_verifier=str(payload["verifier"]).encode("ascii"),
            domain=locale.domain,
            serial=str(payload["serial"]),
        )
    except Exception as exc:  # any library failure is auth_failed
        _unlink(session_path)
        log(f"audible registration failed: {type(exc).__name__}")
        raise PipelineError(
            protocol.ErrorCode.AUTH_FAILED,
            "Audible rejected the sign-in",
            hint="start the login again",
        ) from exc
    _unlink(session_path)

    try:
        auth = port.authenticator()
        auth.locale = locale
        auth._update_attrs(with_username=False, **registration)
        activation = auth.get_activation_bytes()
        account = account_from_info(getattr(auth, "customer_info", None))
        _persist_login(paths, auth, activation, str(payload["marketplace"]), account)
    except Exception as exc:
        log(f"saving the login failed: {type(exc).__name__}")
        raise PipelineError(
            protocol.ErrorCode.AUTH_FAILED,
            "the sign-in succeeded but the credentials could not be saved",
            hint="start the login again",
        ) from exc

    contains = _clipboard_contains(code) if clipboard_check else False
    del code
    return contains


def _read_cli_profile(source_dir: Path) -> dict[str, Any]:
    config_path = source_dir / "config.toml"
    if not config_path.is_file():
        raise PipelineError(
            protocol.ErrorCode.NO_AUTH_FILE,
            "no audible-cli config found",
            hint=f"expected {config_path}; run 'audible quickstart' in a terminal",
        )
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PipelineError(
            protocol.ErrorCode.NO_AUTH_FILE,
            "the audible-cli config could not be read",
            hint="run 'audible quickstart' in a terminal",
        ) from exc
    app = data.get("APP") or {}
    profiles = data.get("profile") or {}
    primary = app.get("primary_profile")
    profile = profiles.get(primary) if primary else None
    if not isinstance(profile, dict) or not profile.get("auth_file"):
        raise PipelineError(
            protocol.ErrorCode.NO_AUTH_FILE,
            "the audible-cli config has no primary profile",
            hint="run 'audible quickstart' in a terminal",
        )
    return {
        "auth_file": str(profile["auth_file"]),
        "country_code": profile.get("country_code"),
    }


def _locale_code(text: str) -> str | None:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("locale_code")
    return value if isinstance(value, str) and value else None


def login_import_cli(
    paths: Paths,
    *,
    source_dir: Path | str | None = None,
    fake: bool,
    api: AudiblePort | None = None,
) -> None:
    """Import an existing audible-cli login into the plugin config dir.

    The source is validated with ``Authenticator.from_file`` and copied
    verbatim, written ``0600`` whatever the source mode was. The recorded
    ``origin`` is ``import`` so ``logout`` never deregisters the user's device
    (ARCHITECTURE 4.7).
    """
    if fake:
        fakestate.mark_signed_in(paths)
        return
    src_dir = Path(source_dir).expanduser() if source_dir else _default_audible_dir()
    profile = _read_cli_profile(src_dir)
    src = src_dir / profile["auth_file"]
    if not src.is_file():
        raise PipelineError(
            protocol.ErrorCode.NO_AUTH_FILE,
            "no audible-cli auth file found",
            hint=f"expected {src}; run 'audible quickstart' in a terminal",
        )
    port = api or RealAudible()
    try:
        auth = port.authenticator_from_file(src)
        text = src.read_text(encoding="utf-8")
    except Exception as exc:
        raise PipelineError(
            protocol.ErrorCode.NO_AUTH_FILE,
            "the audible-cli auth file could not be read",
            hint="it may be encrypted or not a valid audible-cli login",
        ) from exc
    marketplace = profile.get("country_code") or _locale_code(text) or DEFAULT_MARKETPLACE
    _persist_import(
        paths,
        text,
        str(marketplace),
        account_from_info(getattr(auth, "customer_info", None)),
        auth,
    )


def logout(paths: Paths, *, fake: bool, api: AudiblePort | None = None) -> None:
    """Deregister this device only when we created it, then delete the files.

    Never touches books, and never passes the ``True`` form of
    ``deregister_all``. An imported (or unrecorded) origin means no deregister
    call at all: that auth file is the user's existing device (ARCHITECTURE
    4.7).
    """
    if fake:
        fakestate.mark_signed_out(paths)
        return
    record = read_account_record(paths)
    if record.get("origin") == "login" and paths.auth_file.is_file():
        try:
            port = api or RealAudible()
            auth = port.authenticator_from_file(paths.auth_file)
            auth.deregister_device(deregister_all=False)
        except Exception as exc:  # noqa: BLE001 - best effort, e.g. offline
            log(f"device deregistration failed (best effort): {type(exc).__name__}")
    for path in (
        paths.auth_file,
        paths.activation_bytes_file,
        paths.config_toml,
        paths.account_file,
    ):
        _unlink(path)

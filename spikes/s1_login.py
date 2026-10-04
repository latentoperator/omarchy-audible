"""S1: in-drawer login prototype, split into the two steps the backend will use.

  start                 -> prints the sign-in URL; keeps {verifier, serial} in a 0600
                           session file under $XDG_RUNTIME_DIR (tmpfs, never on disk)
  finish <outdir>       -> reads the pasted redirect URL from a hidden prompt (never
                           argv), registers a device, writes auth.json / activation_bytes /
                           config.toml (0600), then scans likely leak sites for the code
  verify <outdir>       -> library + activation bytes through audible-cli and the library
  import <outdir>       -> copies the primary ~/.audible auth file (validated) into outdir
  cleanup <outdir>      -> deregisters ONLY the device created by `finish`, deletes outdir

Prints booleans, counts and error types only. Never prints tokens, codes or the URL.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import audible
from audible.localization import Locale
from audible.login import build_oauth_url, create_code_verifier
from audible.register import register

COUNTRY = os.environ.get("OA_COUNTRY", "us")
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "omarchy-audible-s1"
SESSION = RUNTIME / "session.json"
TTL_S = 600


def emit(**kw: object) -> None:
    print(json.dumps(kw), flush=True)


def write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(path, 0o600)


def dotaudible_auth() -> Path:
    src_dir = Path.home() / ".audible"
    cfg = tomllib.loads((src_dir / "config.toml").read_text())
    return src_dir / cfg["profile"][cfg["APP"]["primary_profile"]]["auth_file"]


def config_toml(country: str) -> str:
    return (
        'title = "Audible Config File"\n\n[APP]\nprimary_profile = "plugin"\n\n'
        f'[profile.plugin]\nauth_file = "auth.json"\ncountry_code = "{country}"\n'
    )


def cmd_start() -> int:
    loc = Locale(COUNTRY)
    verifier = create_code_verifier()
    url, serial = build_oauth_url(
        country_code=loc.country_code, domain=loc.domain,
        market_place_id=loc.market_place_id, code_verifier=verifier,
    )
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    write_private(SESSION, json.dumps({
        "verifier": verifier.decode(), "serial": serial,
        "country": COUNTRY, "created": time.time(),
    }))
    print(url)
    return 0


def scan_for(needle: str) -> dict[str, bool]:
    home = Path.home()
    files = [
        home / ".local/state/omarchy/clipboard-history.json",
        home / ".bash_history",
        home / ".local/share/fish/fish_history",
        home / ".zsh_history",
    ]
    out: dict[str, bool] = {}
    for f in files:
        if f.exists():
            out[f.name] = needle in f.read_text(errors="replace")
    for name, argv in {
        "journal_user": ["journalctl", "--user", "--since", "-30min", "--no-pager", "-o", "cat"],
        "journal_system": ["journalctl", "--since", "-30min", "--no-pager", "-o", "cat"],
    }.items():
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=60)
            out[name] = needle in r.stdout
        except Exception as e:  # noqa: BLE001
            out[name] = f"scan_failed:{type(e).__name__}"  # type: ignore[assignment]
    return out


def cmd_finish(outdir: Path) -> int:
    try:
        sess = json.loads(SESSION.read_text())
    except FileNotFoundError:
        emit(type="error", code="no_session")
        return 2
    if time.time() - sess["created"] > TTL_S:
        SESSION.unlink(missing_ok=True)
        emit(type="error", code="expired")
        return 2

    raw = getpass.getpass("Paste the address from the browser (hidden), then press Enter: ").strip()
    try:
        code = parse_qs(urlsplit(raw).query)["openid.oa2.authorization_code"][0]
    except Exception:  # noqa: BLE001  (never echo the input)
        emit(type="error", code="bad_url", length=len(raw))
        return 2
    url_len = len(raw)
    del raw

    loc = Locale(sess["country"])
    t = time.time()
    try:
        reg = register(
            authorization_code=code, code_verifier=sess["verifier"].encode(),
            domain=loc.domain, serial=sess["serial"],
        )
    except Exception as e:  # noqa: BLE001
        emit(type="error", code="auth_failed", exc=type(e).__name__)
        return 3
    finally:
        SESSION.unlink(missing_ok=True)
    reg_s = round(time.time() - t, 2)

    auth = audible.Authenticator()
    auth.locale = loc
    auth._update_attrs(with_username=False, **reg)
    ab = auth.get_activation_bytes()

    outdir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(outdir, 0o700)
    auth.to_file(outdir / "auth.json", encryption=False)
    os.chmod(outdir / "auth.json", 0o600)
    write_private(outdir / "activation_bytes", ab)
    write_private(outdir / "config.toml", config_toml(sess["country"]))

    leaks = scan_for(code)
    leaks["outdir"] = any(code in p.read_text(errors="replace") for p in outdir.iterdir())
    del code
    emit(
        type="done", url_length=url_len, register_s=reg_s,
        modes={p.name: oct(stat.S_IMODE(p.stat().st_mode)) for p in outdir.iterdir()},
        dir_mode=oct(stat.S_IMODE(outdir.stat().st_mode)),
        session_file_removed=not SESSION.exists(),
        code_found_in=leaks,
    )
    return 0


def cmd_import(outdir: Path) -> int:
    src_dir = Path.home() / ".audible"
    cfg = tomllib.loads((src_dir / "config.toml").read_text())
    prof = cfg["profile"][cfg["APP"]["primary_profile"]]
    src = src_dir / prof["auth_file"]
    audible.Authenticator.from_file(src)  # validates; raises on bad/encrypted file
    outdir.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_private(outdir / "auth.json", src.read_text())
    write_private(outdir / "config.toml", config_toml(prof.get("country_code", "us")))
    emit(type="done", src_mode=oct(stat.S_IMODE(src.stat().st_mode)))
    return 0


def cmd_verify(outdir: Path) -> int:
    env = {**os.environ, "AUDIBLE_CONFIG_DIR": str(outdir)}
    cli = shutil.which("audible") or str(Path.home() / ".local/bin/audible")
    r = subprocess.run([cli, "-P", "plugin", "library", "list"], env=env, capture_output=True, text=True)
    a = audible.Authenticator.from_file(outdir / "auth.json")
    with audible.Client(auth=a) as c:
        n = 0
        page = 1
        while True:
            items = c.get("1.0/library", num_results=50, page=page, response_groups="product_attrs")["items"]
            n += len(items)
            if len(items) < 50:
                break
            page += 1
    ref = (Path.home() / ".audible/activation_bytes")
    same_ab = None
    if ref.exists() and (outdir / "activation_bytes").exists():
        h = lambda p: hashlib.sha256(p.read_text().strip().encode()).digest()  # noqa: E731
        same_ab = h(ref) == h(outdir / "activation_bytes")
    emit(
        type="done", cli_rc=r.returncode, cli_library_lines=len(r.stdout.splitlines()),
        api_library_items=n, activation_bytes_match_existing=same_ab,
        device_type=(a.device_info or {}).get("device_type"),
        new_serial_differs=(a.device_info or {}).get("device_serial_number") != json.loads(
            dotaudible_auth().read_text()).get("device_info", {}).get("device_serial_number"),
    )
    return 0


def cmd_cleanup(outdir: Path) -> int:
    a = audible.Authenticator.from_file(outdir / "auth.json")
    old = json.loads(dotaudible_auth().read_text())
    if (a.device_info or {}).get("device_serial_number") == old.get("device_info", {}).get("device_serial_number"):
        emit(type="error", code="refusing_same_device_as_dotaudible")
        return 2
    try:
        a.deregister_device(deregister_all=False)
        dereg = True
    except Exception as e:  # noqa: BLE001
        dereg = f"failed:{type(e).__name__}"
    shutil.rmtree(outdir)
    ref = audible.Authenticator.from_file(dotaudible_auth())
    with audible.Client(auth=ref) as c:
        still_ok = "items" in c.get("1.0/library", num_results=1, response_groups="product_attrs")
    emit(type="done", deregistered=dereg, outdir_removed=not outdir.exists(), dotaudible_still_works=still_ok)
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "start":
        return cmd_start()
    if cmd in {"finish", "verify", "import", "cleanup"} and len(argv) == 3:
        return {"finish": cmd_finish, "verify": cmd_verify, "import": cmd_import,
                "cleanup": cmd_cleanup}[cmd](Path(argv[2]).expanduser())
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    os.umask(0o077)
    sys.exit(main(sys.argv))

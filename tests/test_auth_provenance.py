"""B02: synthetic credential replacement, write faults and killed writers only."""

from __future__ import annotations

import io
import json
import os
import signal
import stat
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from omarchy_audible import auth, commands, protocol
from omarchy_audible.paths import Paths

PLUGIN_DEVICE = "synthetic-plugin-device"
EXTERNAL_DEVICE = "synthetic-cli-device"
LEAK = "invented-sensitive-exception-text"
URL = "https://example.invalid/?openid.oa2.authorization_code=INVENTEDCODE"


class StubAuth:
    def __init__(self, device: str, calls: list[str], *, activation: str | None):
        self.device_info = {"device_serial_number": device}
        self.customer_info = {}
        self.activation_bytes = activation
        self.calls = calls

    def _update_attrs(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def to_file(self, path, encryption=False):
        Path(path).write_text(json.dumps(self.payload()), encoding="utf-8")

    def payload(self):
        return {
            "device_info": self.device_info,
            "activation_bytes": self.activation_bytes,
            "locale_code": "us",
        }

    def get_activation_bytes(self):
        return self.activation_bytes

    def deregister_device(self, *, deregister_all):
        assert deregister_all is False
        self.calls.append(self.device_info["device_serial_number"])


class StubAPI:
    def __init__(self):
        self.calls: list[str] = []

    def authenticator_from_file(self, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        instance = StubAuth("", self.calls, activation=data.get("activation_bytes"))
        instance.device_info = data.get("device_info")
        return instance

    def authenticator(self):
        return StubAuth(PLUGIN_DEVICE, self.calls, activation="SYNTHETICNEW")

    def locale(self, marketplace):
        return SimpleNamespace(country_code=marketplace, domain="invalid")

    def register(self, **kwargs):
        return {"device_info": {"device_serial_number": PLUGIN_DEVICE}}


@pytest.fixture(autouse=True)
def isolated_environment(env, tmp_path, monkeypatch):
    for name in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR"):
        monkeypatch.setenv(name, env[name])
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("TMPDIR", str(tmp_path))


def source_login(tmp_path, device=EXTERNAL_DEVICE, activation="SYNTHETICOLD"):
    source = tmp_path / "invented-cli"
    source.mkdir(exist_ok=True)
    (source / "config.toml").write_text(auth.config_toml("us"), encoding="utf-8")
    instance = StubAuth(device, [], activation=activation)
    instance.to_file(source / "auth.json")
    (source / "auth.json").chmod(0o644)
    return source


def replace_login(paths, source, target, api):
    if target == "import":
        auth.login_import_cli(paths, source_dir=source, fake=False, api=api)
    else:
        auth._write_private_json(
            paths.login_session("synthetic-session"),
            {"verifier": "FAKE", "serial": "FAKE", "marketplace": "us", "created": 1},
        )
        auth.login_finish(
            paths,
            session_id="synthetic-session",
            pasted_url=URL,
            fake=False,
            api=api,
            clipboard_check=False,
            now=1,
        )


def seed(paths: Paths, source: Path, origin: str, api: StubAPI):
    replace_login(paths, source, origin, api)
    return {
        path.name: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        for path in paths.config_dir.iterdir()
        if path.is_file()
    }


def assert_private(paths):
    assert stat.S_IMODE(paths.config_dir.stat().st_mode) == 0o700
    for path in paths.config_dir.rglob("*"):
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)


def test_failed_import_metadata_preserves_old_credentials_and_external_device(
    paths, tmp_path, monkeypatch
):
    api = StubAPI()
    source = source_login(tmp_path)
    old = seed(paths, source, "login", api)

    def fail_metadata(*args, **kwargs):
        raise OSError(LEAK)

    with monkeypatch.context() as fault:
        fault.setattr(auth, "_write_private_json", fail_metadata)
        with pytest.raises((OSError, auth.PipelineError)):
            auth.login_import_cli(paths, source_dir=source, fake=False, api=api)

    assert {
        path.name: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        for path in paths.config_dir.iterdir()
        if path.is_file()
    } == old
    auth.logout(paths, fake=False, api=api)
    assert EXTERNAL_DEVICE not in api.calls


@pytest.mark.parametrize("record_serial", [None, "", 7, EXTERNAL_DEVICE])
def test_unknown_or_mismatched_device_never_authorizes_logout(
    paths, tmp_path, record_serial
):
    api = StubAPI()
    source = source_login(tmp_path)
    seed(paths, source, "login", api)
    record = auth.read_account_record(paths)
    record["device_serial_number"] = record_serial
    auth._write_private_json(paths.account_file, record)
    auth.logout(paths, fake=False, api=api)
    assert api.calls == []


@pytest.mark.parametrize("device_info", [None, {}, {"device_serial_number": 7}])
def test_missing_loaded_device_identity_never_authorizes_logout(
    paths, tmp_path, device_info
):
    api = StubAPI()
    source = source_login(tmp_path)
    seed(paths, source, "login", api)
    data = json.loads(paths.auth_file.read_text(encoding="utf-8"))
    data["device_info"] = device_info
    auth._write_private_json(paths.auth_file, data)
    auth.logout(paths, fake=False, api=api)
    assert api.calls == []


def install_write_observer(monkeypatch, observe):
    for name in ("_write_private_text", "_write_private_json"):
        original = getattr(auth, name)

        def wrapped(path, value, original=original):
            original(path, value)
            # Session creation and the later lazy activation fetch are not
            # credential replacement writes.
            if not Path(path).name.startswith("login-"):
                observe(Path(path))

        monkeypatch.setattr(auth, name, wrapped)
    original_save = StubAuth.to_file

    def save(instance, path, **kwargs):
        original_save(instance, path, **kwargs)
        observe(Path(path))

    monkeypatch.setattr(StubAuth, "to_file", save)
    original_replace = os.replace

    def move(src, dst):
        original_replace(src, dst)
        observe(Path(dst))

    monkeypatch.setattr(auth.os, "replace", move)
    original_unlink = auth._unlink

    def unlink(path):
        existed = path.exists()
        original_unlink(path)
        if path.name == "activation_bytes" and existed:
            observe(path)

    monkeypatch.setattr(auth, "_unlink", unlink)


# Includes every staged write, provenance invalidation and installed file.
# The lazy activation fetch happens after the replacement and is tested in B13.
@pytest.mark.parametrize(
    "old_origin,target,stop",
    [("login", "import", stop) for stop in range(1, 11)]
    + [("import", "login", stop) for stop in range(1, 10)],
)
@pytest.mark.parametrize("failure", ["exception", "sigkill"])
def test_every_replacement_write_fails_closed(
    paths, tmp_path, monkeypatch, old_origin, target, stop, failure
):
    api = StubAPI()
    source = source_login(tmp_path)
    old = seed(paths, source, old_origin, api)
    count = 0

    def observe(path):
        nonlocal count
        count += 1
        if count == stop:
            if failure == "sigkill":
                os.kill(os.getpid(), signal.SIGKILL)
            raise OSError(LEAK)

    if failure == "sigkill":
        pid = os.fork()
        if pid == 0:
            try:
                install_write_observer(monkeypatch, observe)
                replace_login(paths, source, target, api)
            except BaseException:  # noqa: BLE001 - child must not run pytest cleanup
                os._exit(2)
            os._exit(3)
        _, status = os.waitpid(pid, 0)
        assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
    else:
        with monkeypatch.context() as fault:
            install_write_observer(fault, observe)
            with pytest.raises((OSError, auth.PipelineError)):
                replace_login(paths, source, target, api)
        assert count == stop

    assert_private(paths)
    # A failed preparation retains the complete previous set byte-for-byte.
    staged_writes = 5 if target == "import" else 4
    if stop <= staged_writes:
        assert all(
            (paths.config_dir / name).read_bytes() == content
            for name, (content, mode) in old.items()
        )
    auth.logout(paths, fake=False, api=api)
    assert EXTERNAL_DEVICE not in api.calls


def test_readers_observe_complete_credentials_and_fail_closed_provenance(
    paths, tmp_path, monkeypatch
):
    api = StubAPI()
    source = source_login(tmp_path)
    seed(paths, source, "login", api)
    observations = []

    def observe(path):
        saved = json.loads(paths.auth_file.read_text(encoding="utf-8"))
        loaded = api.authenticator_from_file(paths.auth_file)
        record = auth.read_account_record(paths)
        serial = loaded.device_info["device_serial_number"]
        observations.append(serial)
        assert saved["device_info"]["device_serial_number"] == serial
        if serial == EXTERNAL_DEVICE:
            assert record.get("origin") != "login"
        assert_private(paths)

    with monkeypatch.context() as fault:
        install_write_observer(fault, observe)
        auth.login_import_cli(paths, source_dir=source, fake=False, api=api)
    assert PLUGIN_DEVICE in observations and EXTERNAL_DEVICE in observations


def test_concurrent_reader_keeps_old_login_during_partial_staged_write(
    paths, tmp_path, monkeypatch
):
    api = StubAPI()
    source = source_login(tmp_path)
    seed(paths, source, "import", api)
    writing = Event()
    resume = Event()
    original = StubAuth.to_file

    def slow_save(instance, path, **kwargs):
        Path(path).write_text('{"device_info":', encoding="utf-8")
        writing.set()
        assert resume.wait(5)
        original(instance, path, **kwargs)

    monkeypatch.setattr(StubAuth, "to_file", slow_save)
    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(
            auth._persist_login, paths, api.authenticator(), "us", None
        )
        try:
            assert writing.wait(5)
            loaded = api.authenticator_from_file(paths.auth_file)
            assert loaded.device_info["device_serial_number"] == EXTERNAL_DEVICE
        finally:
            resume.set()
            writer.result(timeout=5)


def test_logout_checks_the_loaded_snapshot_not_a_separate_file_read(paths, tmp_path):
    api = StubAPI()
    source = source_login(tmp_path)
    seed(paths, source, "login", api)

    class SwappingAPI(StubAPI):
        def authenticator_from_file(self, path):
            # A replacement lands between account read and auth load.
            auth._write_private_text(path, (source / "auth.json").read_text())
            return super().authenticator_from_file(path)

    swapping = SwappingAPI()
    auth.logout(paths, fake=False, api=swapping)
    assert swapping.calls == []


@pytest.mark.parametrize("target", ["import", "login"])
def test_persistence_errors_are_secret_free(
    paths, tmp_path, monkeypatch, capsys, target
):
    api = StubAPI()
    source = source_login(tmp_path)
    seed(paths, source, "login", api)
    monkeypatch.setattr(auth, "RealAudible", lambda: api)
    monkeypatch.setattr(sys, "stdin", io.StringIO(URL))
    if target == "login":
        auth._write_private_json(
            paths.login_session("synthetic-session"),
            {
                "verifier": "FAKE",
                "serial": "FAKE",
                "marketplace": "us",
                "created": time.time(),
            },
        )

    def fail(*args, **kwargs):
        raise OSError(LEAK)

    monkeypatch.setattr(auth, "_write_private_json", fail)
    if target == "import":
        result = commands.cmd_login_import_cli(
            ["--dir", str(source)], command="login-import-cli", fake=False, paths=paths
        )
    else:
        result = commands.cmd_login_finish(
            ["--session", "synthetic-session"],
            command="login-finish",
            fake=False,
            paths=paths,
        )
    assert result == protocol.EXIT_ERROR
    captured = capsys.readouterr()
    assert LEAK not in captured.out + captured.err
    assert URL not in captured.out + captured.err
    assert json.loads(captured.out.splitlines()[-1])["type"] == "error"


@pytest.mark.parametrize("target", ["import", "login"])
@pytest.mark.parametrize("barrier", ["staged-file", "invalidation-directory"])
def test_failed_durability_barrier_does_not_replace_credentials(
    paths, tmp_path, monkeypatch, target, barrier
):
    api = StubAPI()
    source = source_login(tmp_path)
    old = seed(paths, source, "login" if target == "import" else "import", api)
    original = os.fsync

    def fail_sync(fd):
        is_dir = stat.S_ISDIR(os.fstat(fd).st_mode)
        if is_dir == (barrier == "invalidation-directory"):
            raise OSError(LEAK)
        original(fd)

    with monkeypatch.context() as fault:
        fault.setattr(auth.os, "fsync", fail_sync)
        with pytest.raises(auth.PipelineError):
            replace_login(paths, source, target, api)
    for name in ("auth.json", "activation_bytes", "config.toml"):
        assert (paths.config_dir / name).read_bytes() == old[name][0]
    auth.logout(paths, fake=False, api=api)
    assert EXTERNAL_DEVICE not in api.calls


def test_interrupted_import_of_same_serial_does_not_keep_login_ownership(
    paths, tmp_path, monkeypatch
):
    api = StubAPI()
    source = source_login(tmp_path, device=PLUGIN_DEVICE)
    seed(paths, source, "login", api)
    original_replace = os.replace

    def fail_after_auth_install(src, dst):
        original_replace(src, dst)
        if Path(dst) == paths.auth_file:
            raise OSError(LEAK)

    with monkeypatch.context() as fault:
        fault.setattr(auth.os, "replace", fail_after_auth_install)
        with pytest.raises(auth.PipelineError):
            auth.login_import_cli(paths, source_dir=source, fake=False, api=api)
    auth.logout(paths, fake=False, api=api)
    assert api.calls == []


@pytest.mark.parametrize("activation", [None, "SYNTHETICOLD"])
def test_repeated_imports_keep_external_ownership_and_clear_stale_activation(
    paths, tmp_path, activation
):
    api = StubAPI()
    source = source_login(tmp_path, activation=activation)
    seed(paths, source, "login", api)
    for _ in range(2):
        auth.login_import_cli(paths, source_dir=source, fake=False, api=api)
        assert_private(paths)
        if activation is None:
            assert not paths.activation_bytes_file.exists()
    auth.logout(paths, fake=False, api=api)
    assert api.calls == []
    assert (source / "auth.json").exists()

"""No launched process carries a book's title or ASIN in its argv (0.1.1).

``/proc/<pid>/cmdline`` is readable by every local user, so an argv that names
a book tells them what you listen to (marketplace review of 0.1.0). The
environment is readable only by the same user, so ASINs travel there:

* the shell's backend commands: ``qml/JobRunner.qml`` takes the ASINs out of a
  job's arguments (``qml/lib/Launch.js``) and passes them in
  ``OMARCHY_AUDIBLE_ASIN``; the backend puts them back (``cli.py``);
* the audible-cli download runs through ``omarchy_audible.audible_download``,
  which reads the ASIN from the same variable;
* ffmpeg and ffprobe run inside the book's ``.partial/`` with relative names;
* the play-failure notification is generic; the reason stays in the drawer.

Keys never go through argv: they reach mpv over its socket (``test_mpv.py``,
``test_get.py``).

These tests fail if any of that regresses: the real ``JobRunner``/
``BackendCall`` wiring under a recording ``Process``, every launch site in the
QML, every argv the download pipeline spawns (in process, and logged by
``ffmpeg``/``ffprobe`` shims under a real ``get``), and the live backend's own
``/proc`` command line.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

import qjs
from omarchy_audible import cli, joblock
from omarchy_audible import download as dl
from omarchy_audible.audible_download import ASIN_ENV, download_args
from omarchy_audible.commands import REGISTRY

REPO = Path(__file__).resolve().parents[1]
LAUNCHER = REPO / "bin" / "omarchy-audible"
ASIN = "B0FAKE0001"
OTHER = "B0FAKE0002"
TITLE = "The Lighthouse Ledger"


def _named(argv: list[str], *needles: str) -> list[str]:
    return [token for token in argv for needle in needles if needle in token]


# ---- Launch.js ---------------------------------------------------------------


@pytest.fixture(scope="module")
def launch() -> qjs.JsModule:
    return qjs.load("Launch")


@pytest.mark.parametrize(
    "command,args,rest,asins",
    [
        ("get", [ASIN], [], [ASIN]),
        ("get", [ASIN, "--fake-fail", "network"], ["--fake-fail", "network"], [ASIN]),
        ("get", ["--fake-fail", "network", ASIN], ["--fake-fail", "network"], [ASIN]),
        ("remove", [ASIN], [], [ASIN]),
        ("cancel", [ASIN], [], [ASIN]),
        ("play-info", [ASIN], [], [ASIN]),
        ("position-get", [ASIN, OTHER], [], [ASIN, OTHER]),
        (
            "position-push",
            [ASIN, "1234", "--at", "2026-10-09T12:00:00Z"],
            ["1234", "--at", "2026-10-09T12:00:00Z"],
            [ASIN],
        ),
        ("sync", ["--fake-hide", ASIN], [], [ASIN]),
        ("sync", ["--fake-fail", "network"], ["--fake-fail", "network"], []),
        ("status", [], [], []),
        ("login-finish", ["--session", "abc"], ["--session", "abc"], []),
        ("books-location-ack", ["--if-no-old-books"], ["--if-no-old-books"], []),
    ],
)
def test_split_takes_the_asins_out(launch, command, args, rest, asins):
    assert launch.call("split", command, args) == {"args": rest, "asins": asins}


def test_environment_adds_the_asins_and_keeps_the_base(launch):
    base = {"OMARCHY_AUDIBLE_FAKE": "1"}
    assert launch.call("environment", base, [ASIN, OTHER]) == {
        "OMARCHY_AUDIBLE_FAKE": "1",
        ASIN_ENV: f"{ASIN} {OTHER}",
    }
    assert launch.call("environment", base, []) == base
    assert launch.call("environment", None, None) == {}
    assert launch.evaluate("ASIN_ENV") == ASIN_ENV == cli.ASIN_ENV


def test_the_backend_puts_back_what_the_shell_took_out(launch):
    """Launch.split then cli.env_asin_args gives the command-line form back."""
    cases = [
        ("get", [ASIN, "--fake-fail", "network"]),
        ("get", [ASIN, "--fake-chapters", "120"]),
        ("remove", [ASIN]),
        ("cancel", [ASIN]),
        ("play-info", [ASIN]),
        ("position-get", [ASIN, OTHER]),
        ("position-push", [ASIN, "1234", "--at", "2026-10-09T12:00:00Z"]),
        ("sync", ["--fake-hide", ASIN]),
        ("sync", []),
        ("status", []),
    ]
    for command, args in cases:
        split = launch.call("split", command, args)
        env = launch.call("environment", {}, split["asins"])
        assert cli.env_asin_args(command, split["args"], env) == args, command


def test_backend_and_shell_agree_on_the_asin_commands(launch):
    single = set(launch.evaluate("SINGLE_ASIN_COMMANDS"))
    assert single | {"sync"} == set(cli.SINGLE_ASIN_COMMANDS)
    assert set(cli.ASIN_COMMANDS) == single | {"sync", "position-get"}
    assert set(cli.ASIN_COMMANDS) <= set(REGISTRY)


def test_cli_form_still_works_by_hand():
    assert cli.env_asin_args("get", [ASIN], {}) == [ASIN]
    assert cli.env_asin_args("get", [], {ASIN_ENV: ASIN}) == [ASIN]
    # A single-ASIN command given two is refused, not guessed.
    assert cli.env_asin_args("get", [], {ASIN_ENV: f"{ASIN} {OTHER}"}) is None
    # Commands that take no ASIN ignore the variable.
    assert cli.env_asin_args("status", [], {ASIN_ENV: ASIN}) == []


@pytest.mark.parametrize(
    "command,args",
    [
        ("remove", [OTHER]),
        ("get", [OTHER, "--fake-fail", "network"]),
        ("cancel", [OTHER]),
        ("play-info", [OTHER]),
        ("position-push", [OTHER, "1234"]),
        ("position-get", [OTHER]),
        ("sync", ["--fake-hide", OTHER]),
        ("sync", [f"--fake-hide={OTHER}"]),
    ],
)
def test_a_leftover_variable_never_picks_the_book_for_a_typed_command(command, args):
    """``remove <typed>`` with the variable set must not act on the variable's
    book: both is refused."""
    assert cli.env_asin_args(command, args, {ASIN_ENV: ASIN}) is None


def test_cli_refuses_two_asins_for_one(run_cli, events):
    result = run_cli("play-info", fake=True, extra_env={ASIN_ENV: f"{ASIN} {OTHER}"})
    assert result.returncode != 0
    assert events(result)[-1]["code"] == "invalid_args"


def test_a_command_reads_its_asin_from_the_environment(run_cli, events):
    by_env = run_cli("cancel", fake=True, extra_env={ASIN_ENV: ASIN})
    by_arg = run_cli("cancel", ASIN, fake=True)
    assert events(by_env)[-1] == events(by_arg)[-1]
    assert events(by_env)[-1]["code"] == "not_running"


# ---- the real JobRunner / BackendCall wiring --------------------------------

_STUBS = {
    "Quickshell/Io/qmldir": (
        "module Quickshell.Io\n"
        "Process 1.0 Process.qml\n"
        "SplitParser 1.0 SplitParser.qml\n"
        "singleton Launches 1.0 Launches.qml\n"
    ),
    "Quickshell/Io/Process.qml": """import QtQml
QtObject {
  property var command: []
  property var environment: ({})
  property bool stdinEnabled: false
  property bool running: false
  property QtObject stdout: null
  property QtObject stderr: null
  signal started()
  signal exited(int code, int status)
  function write(text) {}
  onRunningChanged: if (running) Launches.add(command, environment)
}
""",
    "Quickshell/Io/SplitParser.qml": """import QtQml
QtObject {
  property string splitMarker: ""
  signal read(string data)
}
""",
    "Quickshell/Io/Launches.qml": """pragma Singleton
import QtQml
QtObject {
  property var all: []
  function add(command, environment) {
    all = all.concat([{ "argv": command.slice(), "env": environment }])
  }
}
""",
}

_MAIN = """import QtQuick
import Quickshell.Io
Item {
  id: top
  Component { id: runnerComponent; JobRunner {} }

  // A fresh runner per call, so a job command spawns at once instead of
  // waiting behind the previous one.
  function launch(request) {
    Launches.all = []
    var runner = runnerComponent.createObject(top, {
      "launcher": "/plugin/bin/omarchy-audible",
      "environment": { "OMARCHY_AUDIBLE_FAKE": "1" }
    })
    // Plain JS arrays, as the shell's own call sites pass.
    var args = JSON.parse(JSON.stringify(request.args))
    if (request.input) runner.runWithInput(request.command, args, "t", "pasted")
    else runner.run(request.command, args, "t")
    if (request.cancel) runner.cancel(request.cancel)
    return Launches.all
  }
}
"""

# Every way the shell calls the backend (the `run(...)` sites in the QML).
SHELL_CALLS: list[tuple[str, list[str]]] = [
    ("status", []),
    ("doctor", []),
    ("setup", []),
    ("local", []),
    ("sync", []),
    ("sync", ["--fake-fail", "network"]),
    ("sync", ["--fake-hide", ASIN]),
    ("get", [ASIN]),
    ("get", [ASIN, "--fake-fail", "network"]),
    ("remove", [ASIN]),
    ("play-info", [ASIN]),
    ("position-get", [ASIN]),
    ("position-get", [ASIN, OTHER]),
    ("position-push", [ASIN, "61000", "--at", "2026-10-09T12:00:00Z"]),
    ("books-location-ack", []),
    ("books-location-ack", ["--if-no-old-books"]),
    ("login-start", ["--marketplace", "us"]),
    ("login-import-cli", []),
    ("logout", []),
]


class _Runner:
    def __init__(self, tmp_path: Path) -> None:
        from PySide6.QtCore import QCoreApplication, QUrl
        from PySide6.QtQml import QQmlComponent, QQmlEngine

        self._app = QCoreApplication.instance() or QCoreApplication([])
        for relative, text in _STUBS.items():
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        app = tmp_path / "app"
        (app / "lib").mkdir(parents=True)
        for name in ("JobRunner.qml", "BackendCall.qml"):
            shutil.copy2(REPO / "qml" / name, app / name)
        for source in (REPO / "qml/lib").glob("*.js"):
            shutil.copy2(source, app / "lib" / source.name)
        (app / "Main.qml").write_text(_MAIN, encoding="utf-8")
        self.engine = QQmlEngine()
        self.engine.addImportPath(str(tmp_path))
        self.component = QQmlComponent(
            self.engine, QUrl.fromLocalFile(str(app / "Main.qml"))
        )
        self.root = self.component.create()
        assert self.root is not None, self.component.errorString()

    def launch(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QMetaObject

        value = QMetaObject.invokeMethod(
            self.root, "launch", Q_RETURN_ARG("QVariant"), Q_ARG("QVariant", request)
        )
        return value.toVariant() if hasattr(value, "toVariant") else value

    def close(self) -> None:
        import shiboken6

        self.root = None
        self.component = None
        engine, self.engine = self.engine, None
        if shiboken6.isValid(engine):
            shiboken6.delete(engine)


@pytest.fixture
def runner(tmp_path):
    harness = _Runner(tmp_path)
    yield harness
    harness.close()


@pytest.mark.parametrize(
    "command,args", SHELL_CALLS, ids=[f"{c} {' '.join(a)}" for c, a in SHELL_CALLS]
)
def test_the_shell_never_puts_an_asin_in_a_backend_argv(runner, command, args):
    launches = runner.launch({"command": command, "args": args})
    assert len(launches) == 1
    argv, env = launches[0]["argv"], launches[0]["env"]
    assert argv[:2] == ["/plugin/bin/omarchy-audible", command]
    assert not _named(argv, ASIN, OTHER, TITLE), argv
    expected = [token for token in args if token in (ASIN, OTHER)]
    assert env.get(ASIN_ENV, "").split() == expected
    assert env["OMARCHY_AUDIBLE_FAKE"] == "1"
    # What the backend rebuilds is exactly what the caller asked for.
    assert cli.env_asin_args(command, argv[2:], env) == args


def test_cancel_sends_the_asin_in_the_environment(runner):
    launches = runner.launch({"command": "get", "args": [ASIN], "cancel": ASIN})
    assert [launch["argv"][1] for launch in launches] == ["get", "cancel"]
    for launch in launches:
        assert not _named(launch["argv"], ASIN), launch["argv"]
        assert launch["env"][ASIN_ENV] == ASIN


def test_login_finish_keeps_its_input_off_argv(runner):
    launches = runner.launch(
        {"command": "login-finish", "args": ["--session", "abc"], "input": True}
    )
    assert launches[0]["argv"][1:] == ["login-finish", "--session", "abc"]
    assert ASIN_ENV not in launches[0]["env"]


_RUN_SITE = re.compile(r'\b(?:run|runWithInput)\(\s*"([a-z-]+)"')


def test_every_backend_call_in_the_qml_is_covered():
    """A new `run("<command>", ...)` must get a SHELL_CALLS row."""
    covered = {command for command, _args in SHELL_CALLS} | {"login-finish", "cancel"}
    sources = [REPO / "Service.qml", *sorted((REPO / "qml").rglob("*.qml"))]
    found = set()
    for path in sources:
        found |= set(_RUN_SITE.findall(path.read_text(encoding="utf-8")))
    # PositionSync runs what Sync.js's effects name.
    sync = (REPO / "qml/lib/Sync.js").read_text(encoding="utf-8")
    found |= set(re.findall(r'"command": "([a-z-]+)"', sync))
    # PlayRequest.COMMAND is play-info.
    found.add("play-info")
    assert found, "the scan found no backend calls"
    assert found <= covered, sorted(found - covered)
    assert covered <= set(REGISTRY)


# ---- every other process the shell launches ----------------------------------

# Every process launch in the QML and what its argv is built from. None of
# them may take a book's title, ASIN or path; a new launch site fails here
# until it is reviewed and added.
LAUNCH_SITES = {
    (
        "Service.qml",
        (
            'Quickshell.execDetached(["notify-send", "--app-name=Omaudible",\n'
            '      "Omaudible couldn\'t start playback", "Open the drawer for details."])'
        ),
    ),
    (
        "Service.qml",
        (
            'Quickshell.execDetached(["systemctl", "--user", "stop", '
            '"omarchy-audible-fake-mpv.scope"])'
        ),
    ),
    (
        "qml/PlayerController.qml",
        (
            'Quickshell.execDetached(["sh", "-c", \'mkdir -p "$1" && shift && exec "$@"\', '
            '"sh", dir].concat(command))'
        ),
    ),
    ("qml/PlayerController.qml", 'probe.command = ["test", "-S", socketPath]'),
    (
        "qml/PlayerController.qml",
        (
            'command: ["systemctl", "--user", "is-active", "--quiet", '
            'root.unitName + ".scope"]'
        ),
    ),
    ("qml/PlayerController.qml", 'command: ["sh", "-c", "command -v systemd-run"]'),
    (
        "qml/StateStore.qml",
        'backup.command = ["cp", "-f", effect.path, effect.destination]',
    ),
    ("qml/SigninFlow.qml", 'opener.command = ["xdg-open", url]'),
    ("qml/SigninFlow.qml", 'command: ["wl-copy"]'),
    ("qml/SigninFlow.qml", 'command: ["wl-paste", "--no-newline"]'),
    ("qml/BackendCall.qml", "command: root.command"),
}

_LAUNCH = re.compile(
    r"Quickshell\.execDetached\((?:[^()]|\([^()]*\))*\)"
    r"|\b\w+\.command = [^\n]*"
    r"|^\s*command: [^\n]*",
    re.MULTILINE,
)
# Anything else that could start a process (Process.exec([...]) or ({...}),
# startDetached, a bare `command = ...` in a handler); none exists, so any
# hit fails. RegExp.exec(text) and a local `var command` are not launches.
_OTHER_LAUNCH = re.compile(
    r"\bexecDetached\b|\.exec\(\s*[\[{]|\bstartDetached\("
    r"|(?<![.\w])(?<!var )(?<!let )(?<!const )command\s*=[^=]"
)


def test_every_launch_site_is_reviewed():
    sources = [REPO / "Service.qml", REPO / "BarWidget.qml"]
    sources += sorted((REPO / "qml").rglob("*.qml"))
    found = set()
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for match in _LAUNCH.finditer(text):
            found.add((str(path.relative_to(REPO)), match.group(0).strip()))
    assert found == LAUNCH_SITES


def test_no_other_way_to_start_a_process():
    sources = [REPO / "Service.qml", REPO / "BarWidget.qml"]
    sources += sorted((REPO / "qml").rglob("*.qml"))
    sources += sorted((REPO / "qml/lib").glob("*.js"))
    stray = []
    for path in sources:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("//"):
                continue
            hits = _OTHER_LAUNCH.findall(line)
            if hits and "Quickshell.execDetached(" not in line:
                stray.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")
    assert stray == []


def test_mpv_is_launched_with_no_book():
    mpv = qjs.load("Mpv")
    args = mpv.call(
        "launchArgs",
        {"volume": 50, "speed": 1, "socketPath": "/run/x/mpv.sock", "mprisScript": ""},
    )
    assert not [token for token in args if "book" in token or ASIN in token]
    assert "--input-ipc-server=/run/x/mpv.sock" in args


# ---- the download pipeline ---------------------------------------------------


class _Recorder:
    """Records every ``subprocess.Popen`` (``subprocess.run`` goes through it)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[dict[str, Any]] = []
        real_popen = subprocess.Popen

        def popen(argv, **kwargs):
            self.calls.append({"argv": list(argv), **kwargs})
            return real_popen(argv, **kwargs)

        monkeypatch.setattr(subprocess, "Popen", popen)


def _write_catalog(paths) -> None:
    paths.catalog_file.parent.mkdir(parents=True, exist_ok=True)
    paths.catalog_file.write_text(
        json.dumps({"books": [{"asin": ASIN, "title": TITLE, "authors": []}]}),
        encoding="utf-8",
    )


def test_fake_get_spawns_nothing_that_names_the_book(
    ffmpeg_bin, fake_paths, monkeypatch
):
    _write_catalog(fake_paths)
    recorder = _Recorder(monkeypatch)
    final = dl.run_get(ASIN, fake_paths, fake=True, emit=lambda *a, **k: None)

    argvs = [call["argv"] for call in recorder.calls]
    tools = sorted(Path(argv[0]).name for argv in argvs)
    assert tools == ["ffmpeg", "ffprobe"], tools
    books = str(fake_paths.books_dir)
    for call in recorder.calls:
        assert not _named(call["argv"], ASIN, TITLE, books), call["argv"]
        # Relative names only work from inside the staging directory.
        assert Path(call["cwd"]) == final.parent / ".partial"
    assert json.loads((final.parent / "meta.json").read_text())["title"] == TITLE


class _FakeAudibleProc:
    returncode = 0

    def poll(self) -> int:
        return 0

    def terminate(self) -> None:
        pass

    def wait(self, timeout: int | None = None) -> int:
        return 0


def test_real_get_runs_audible_cli_without_the_asin_in_argv(paths, monkeypatch):
    """A stubbed real download: the audible-cli and ffprobe launches."""
    metadata = {
        "content_metadata": {
            "content_reference": {"content_size_in_bytes": 1000, "acr": "ACR00001"},
            "chapter_info": {"runtime_length_ms": 60_000},
        }
    }
    _write_catalog(paths)
    calls: list[dict[str, Any]] = []

    def popen(argv, **kwargs):
        calls.append({"argv": list(argv), **kwargs})
        out = Path(kwargs["cwd"]) / argv[argv.index("-o") + 1]
        (out / f"{ASIN}.aaxc").write_bytes(b"aaxc-bytes")
        (out / f"{ASIN}.voucher").write_text(
            json.dumps(
                {"content_license": {"license_response": {"key": "k" * 32, "iv": "i"}}}
            ),
            encoding="utf-8",
        )
        return _FakeAudibleProc()

    def run(argv, **kwargs):
        calls.append({"argv": list(argv), **kwargs})
        return subprocess.CompletedProcess(argv, 0, stdout="60.0\n", stderr="")

    monkeypatch.setattr(dl.subprocess, "Popen", popen)
    monkeypatch.setattr(dl.subprocess, "run", run)
    monkeypatch.setattr(dl, "_wrapper_python", lambda: "/venv/bin/python")
    monkeypatch.setattr(dl, "_audible_env", lambda paths: {"AUDIBLE_CONFIG_DIR": "c"})
    monkeypatch.setattr(dl, "_real_content_metadata", lambda asin, paths: metadata)

    final = dl.run_get(ASIN, paths, fake=False, emit=lambda *a, **k: None)

    assert final.name == "book.aaxc"
    download, probe = calls
    assert download["argv"][:4] == ["/venv/bin/python", "-P", "-m", dl.AUDIBLE_WRAPPER]
    assert download["env"][ASIN_ENV] == ASIN
    assert download["env"]["AUDIBLE_CONFIG_DIR"] == "c"
    assert Path(probe["argv"][0]).name == "ffprobe"
    books = str(paths.books_dir)
    for call in calls:
        assert not _named(call["argv"], ASIN, TITLE, books), call["argv"]
        assert Path(call["cwd"]) == final.parent / ".partial"


def test_the_wrapper_hands_the_asin_to_audible_cli(tmp_path):
    """The wrapper, run for real, against a stand-in ``audible_cli``."""
    stand_in = tmp_path / "stand-in"
    (stand_in / "audible_cli").mkdir(parents=True)
    (stand_in / "audible_cli" / "__init__.py").write_text(
        "import json, os, sys\n"
        "def main(args=None, prog_name=None):\n"
        "    print(json.dumps({'args': args, 'prog': prog_name,\n"
        "                      'argv': sys.argv, 'cwd': os.getcwd()}))\n"
        "    sys.exit(0)\n",
        encoding="utf-8",
    )
    workdir = tmp_path / "partial"
    workdir.mkdir()
    env = dl._wrapper_env({**os.environ, "PYTHONPATH": str(stand_in)}, ASIN)
    argv = [sys.executable, "-P", "-m", dl.AUDIBLE_WRAPPER, "--aaxc", "-o", "."]
    result = subprocess.run(
        argv, env=env, cwd=workdir, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    seen = json.loads(result.stdout)
    assert seen["args"] == ["download", "-a", ASIN, "--aaxc", "-o", "."]
    assert seen["prog"] == "audible"
    assert ASIN not in " ".join(seen["argv"])
    assert Path(seen["cwd"]) == workdir


def test_the_wrapper_refuses_a_missing_or_odd_asin():
    assert download_args(["--aaxc"], {}) is None
    assert download_args(["--aaxc"], {ASIN_ENV: "../x"}) is None
    assert download_args(["--aaxc"], {ASIN_ENV: f"{ASIN} {OTHER}"}) is None
    assert download_args(["--aaxc"], {ASIN_ENV: ASIN}) == [
        "download",
        "-a",
        ASIN,
        "--aaxc",
    ]


# ---- the live backend, launched the way the shell launches it ----------------


def _descendants(pid: int) -> list[int]:
    children: dict[int, list[int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        ppid = int(stat.rsplit(")", 1)[1].split()[1])
        children.setdefault(ppid, []).append(int(entry.name))
    found, queue = [], [pid]
    while queue:
        current = queue.pop()
        for child in children.get(current, []):
            found.append(child)
            queue.append(child)
    return found


def _cmdline(pid: int) -> list[str] | None:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    return [token.decode("utf-8", "replace") for token in raw.split(b"\0") if token]


@pytest.mark.skipif(not Path("/proc/self/cmdline").exists(), reason="needs /proc")
def test_a_shell_launched_get_is_cancelled_by_its_environment(
    env, ffmpeg_bin, fake_paths
):
    """F41 with the new launch shape: the ``get`` process's own command line
    names no book, and ``cancel`` finds it by its environment. (Its tools are
    checked by the shim test below.)"""
    _write_catalog(fake_paths)
    child_env = {**env, "OMARCHY_AUDIBLE_FAKE": "1", ASIN_ENV: ASIN}
    proc = subprocess.Popen(
        [sys.executable, str(LAUNCHER), "get"],
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    seen: dict[int, list[str]] = {}
    try:
        partial = fake_paths.books_dir / ASIN / ".partial"
        deadline = time.time() + 20
        while time.time() < deadline and not partial.exists():
            for pid in [proc.pid, *_descendants(proc.pid)]:
                argv = _cmdline(pid)
                if argv:
                    seen[pid] = argv
            time.sleep(0.005)
        assert partial.exists(), "the download never started"
        time.sleep(0.05)
        for pid in [proc.pid, *_descendants(proc.pid)]:
            argv = _cmdline(pid)
            if argv:
                seen[pid] = argv

        cancelled = subprocess.run(
            [sys.executable, str(LAUNCHER), "cancel"],
            env=child_env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert cancelled.returncode == 0, cancelled.stdout + cancelled.stderr
        out, _err = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    assert seen[proc.pid][-2:] == ["omarchy_audible", "get"]
    for argv in seen.values():
        assert not _named(argv, ASIN, TITLE, str(fake_paths.books_dir)), argv
    last = json.loads(out.strip().splitlines()[-1])
    assert last["code"] == "cancelled"
    assert joblock.read_job_json(fake_paths.job_json) is None


def _shim_tools(tmp_path: Path, env: dict[str, str]) -> tuple[dict[str, str], Path]:
    """``ffmpeg``/``ffprobe`` shims that log their cwd and argv, then exec the
    real tool; first on PATH."""
    shims, log = tmp_path / "shims", tmp_path / "tools.log"
    shims.mkdir()
    for name in ("ffmpeg", "ffprobe"):
        real = shutil.which(name, path=env["PATH"])
        assert real, name
        shim = shims / name
        shim.write_text(
            "#!/bin/sh\n"
            f'printf "%s\\0" "$PWD" "$0" "$@" >> "{log}"\n'
            f'printf "\\n" >> "{log}"\n'
            f'exec "{real}" "$@"\n',
            encoding="utf-8",
        )
        shim.chmod(0o755)
    return {**env, "PATH": f"{shims}{os.pathsep}{env['PATH']}"}, log


def test_a_shell_launched_get_runs_its_tools_without_naming_the_book(
    env, ffmpeg_bin, fake_paths, tmp_path
):
    """Every ffmpeg/ffprobe a real ``get`` process starts, logged by a shim:
    no ASIN, title or books path in argv, run from the staging directory."""
    _write_catalog(fake_paths)
    shimmed, log = _shim_tools(tmp_path, env)
    result = subprocess.run(
        [sys.executable, str(LAUNCHER), "get"],
        env={**shimmed, "OMARCHY_AUDIBLE_FAKE": "1", ASIN_ENV: ASIN},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1])["type"] == "done"
    runs = [line.split("\0")[:-1] for line in log.read_text().splitlines() if line]
    assert sorted(Path(run[1]).name for run in runs) == ["ffmpeg", "ffprobe"]
    partial = fake_paths.books_dir / ASIN / ".partial"
    for cwd, _tool, *argv in runs:
        assert Path(cwd) == partial
        assert not _named(argv, ASIN, TITLE, str(fake_paths.books_dir)), argv
    assert (fake_paths.books_dir / ASIN / "book.aaxc").is_file()


def test_cancel_does_not_stop_another_books_get(env, ffmpeg_bin, fake_paths):
    """A get for one book must not be cancelled by a cancel naming another."""
    child_env = {**env, "OMARCHY_AUDIBLE_FAKE": "1", ASIN_ENV: OTHER}
    proc = subprocess.Popen(
        [sys.executable, str(LAUNCHER), "get"],
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        partial = fake_paths.books_dir / OTHER / ".partial"
        deadline = time.time() + 20
        while time.time() < deadline and not partial.exists():
            time.sleep(0.01)
        assert partial.exists(), "the download never started"
        # A forged record naming ASIN with the running get's pid.
        joblock.write_job_json(fake_paths.job_json, proc.pid, "get", ASIN)
        cancelled = subprocess.run(
            [sys.executable, str(LAUNCHER), "cancel"],
            env={**child_env, ASIN_ENV: ASIN},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert json.loads(cancelled.stdout.splitlines()[-1])["code"] == "not_running"
        out, _err = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert proc.returncode == 0, out
    assert json.loads(out.strip().splitlines()[-1])["type"] == "done"

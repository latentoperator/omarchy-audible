"""``bin/omarchy-audible-paste``: the bounded clipboard read.

A fake ``wl-paste`` on ``PATH`` plays every kind of clipboard owner: a normal
one, one that is too large, one that never stops streaming, one that trickles
a byte at a time, one that sends nothing and never closes, and one that sends
something that is not text. The helper must answer within its deadline with
at most its byte limit read, and print only a complete text.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / "bin" / "omarchy-audible-paste"

# The fake wl-paste: what it does comes from FAKE_CLIPBOARD; it records its
# own argv and how many bytes it managed to write.
FAKE = """#!{python}
import os, sys, time
mode = os.environ["FAKE_CLIPBOARD"]
record = os.environ["FAKE_RECORD"]
with open(record, "w") as handle:
    handle.write(" ".join(sys.argv[1:]))
out = sys.stdout.buffer
written = 0
def send(data):
    global written
    out.write(data)
    out.flush()
    written += len(data)
    with open(record + ".bytes", "w") as handle:
        handle.write(str(written))
try:
    if mode == "text":
        send("Dune \\u2014 Frank Herbert \\U0001f4da".encode("utf-8"))
    elif mode == "url":
        send(os.environ["FAKE_TEXT"].encode("utf-8"))
    elif mode == "big":
        send(b"x" * 4096)
    elif mode == "stream":
        while True:
            send(b"y" * 65536)
    elif mode == "trickle":
        while True:
            send(b"z")
            time.sleep(0.05)
    elif mode == "silent":
        time.sleep(60)
    elif mode == "binary":
        send(b"\\xff\\xfe\\x00bad")
    elif mode == "empty":
        pass
    elif mode == "fail":
        sys.exit(1)
except BrokenPipeError:
    pass
"""


@pytest.fixture
def clipboard(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "wl-paste"
    fake.write_text(FAKE.format(python=sys.executable), encoding="utf-8")
    fake.chmod(0o755)
    record = tmp_path / "record"

    def run(mode, *args, text="", path=None):
        env = {
            **os.environ,
            "PATH": str(bin_dir) if path is None else path,
            "FAKE_CLIPBOARD": mode,
            "FAKE_RECORD": str(record),
            "FAKE_TEXT": text,
        }
        started = time.monotonic()
        result = subprocess.run(
            [sys.executable, str(HELPER), *args],
            env=env,
            capture_output=True,
            timeout=15,
            check=False,
        )
        elapsed = time.monotonic() - started
        sent = (
            int(Path(f"{record}.bytes").read_text())
            if Path(f"{record}.bytes").exists()
            else 0
        )
        argv = record.read_text() if record.exists() else None
        return result, elapsed, sent, argv

    return run


def answer(result) -> str:
    assert result.returncode == 0, result
    lines = result.stdout.decode("ascii").splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])["text"]


def test_a_normal_clipboard_is_pasted_as_one_json_line(clipboard):
    result, elapsed, _, argv = clipboard("text")
    assert answer(result) == "Dune \u2014 Frank Herbert \U0001f4da"
    # Non-ASCII is escaped, so the shell's line reader never splits a character.
    assert result.stdout.isascii()
    assert argv == "--no-newline --type text"
    assert elapsed < 5


def test_amazons_page_address_fits_the_sign_in_limit(clipboard):
    url = "https://www.amazon.com/ap/maplanding?" + "openid.x=" + "a" * 1500
    result, *_ = clipboard("url", "--max-bytes", "16384", text=url)
    assert answer(result) == url


def test_too_large_is_refused_after_one_byte_past_the_limit(clipboard):
    result, *_ = clipboard("big", "--max-bytes", "1024")
    assert result.returncode == 3
    assert result.stdout == b""


def test_a_clipboard_that_never_stops_is_cut_off_by_size(clipboard):
    result, elapsed, _, _ = clipboard("stream", "--max-bytes", "1024", "--timeout", "2")
    assert result.returncode == 3
    assert result.stdout == b""
    assert elapsed < 4


def test_a_trickling_clipboard_is_cut_off_by_the_total_deadline(clipboard):
    # One byte every 50 ms never trips the size limit; the deadline is total,
    # not per read, so it still ends on time.
    result, elapsed, _, _ = clipboard(
        "trickle", "--max-bytes", "65536", "--timeout", "1"
    )
    assert result.returncode == 4
    assert result.stdout == b""
    assert 0.9 < elapsed < 3


def test_a_silent_clipboard_is_cut_off_by_the_deadline(clipboard):
    result, elapsed, _, _ = clipboard("silent", "--timeout", "0.5")
    assert result.returncode == 4
    assert result.stdout == b""
    assert elapsed < 2.5


@pytest.mark.parametrize("mode", ["binary", "empty", "fail"])
def test_not_text_pastes_nothing(clipboard, mode):
    result, *_ = clipboard(mode)
    assert result.returncode == 5
    assert result.stdout == b""


def test_no_wl_paste_pastes_nothing(clipboard, tmp_path):
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    result, *_ = clipboard("text", path=str(empty))
    assert result.returncode == 2
    assert result.stdout == b""


def test_arguments_cannot_lift_the_bounds(clipboard):
    # Asking for more than the ceiling gets the ceiling: 64 KiB and 5 s.
    result, elapsed, _, _ = clipboard(
        "stream", "--max-bytes", "999999999", "--timeout", "1"
    )
    assert result.returncode == 3
    assert elapsed < 7
    result, elapsed, _, _ = clipboard("silent", "--timeout", "999")
    assert result.returncode == 4
    assert elapsed < 8


def test_sigterm_stops_wl_paste_too(clipboard, tmp_path):
    bin_dir = tmp_path / "bin"
    env = {
        **os.environ,
        "PATH": str(bin_dir),
        "FAKE_CLIPBOARD": "silent",
        "FAKE_RECORD": str(tmp_path / "record"),
    }
    process = subprocess.Popen(
        [sys.executable, str(HELPER), "--timeout", "5"],
        env=env,
        stdout=subprocess.PIPE,
    )
    deadline = time.monotonic() + 5
    while not (tmp_path / "record").exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    children = subprocess.run(
        ["pgrep", "-P", str(process.pid)], capture_output=True, text=True, check=False
    ).stdout.split()
    assert children, "wl-paste did not start"
    process.terminate()
    assert process.wait(timeout=5) == 4
    assert process.stdout.read() == b""
    for pid in children:
        assert not Path(f"/proc/{pid}").exists() or "zombie" in (
            Path(f"/proc/{pid}/status").read_text().lower()
        )


def test_standard_library_only_and_never_the_backend():
    tree = ast.parse(HELPER.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}
    assert "omarchy_audible" not in imported


def test_helper_is_executable_with_a_python_shebang():
    assert os.access(HELPER, os.X_OK)
    assert HELPER.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3\n")

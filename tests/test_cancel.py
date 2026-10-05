"""B5 — ``cancel`` stops a running ``get`` and cleans up (ARCHITECTURE 4.8).

``cancel <asin>`` reads ``job.json`` and SIGTERMs the matching pid; ``get``
catches SIGTERM, deletes ``.partial/`` and emits ``error(code=cancelled)``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from omarchy_audible import joblock

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "bin" / "omarchy-audible"
ASIN = "B00FAKE01"


def test_cancel_mid_download_stops_the_job_and_cleans_up(env, ffmpeg_bin, fake_paths):
    proc = subprocess.Popen(
        [sys.executable, str(LAUNCHER), "get", ASIN, "--fake"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        partial = fake_paths.books_dir / ASIN / ".partial"
        deadline = time.time() + 20
        while time.time() < deadline and not partial.exists():
            time.sleep(0.02)
        assert partial.exists(), "the download never started"
        time.sleep(0.05)  # let it get to the middle of the download

        cancelled = subprocess.run(
            [sys.executable, str(LAUNCHER), "cancel", ASIN, "--fake"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert cancelled.returncode == 0, cancelled.stderr
        out, _err = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    assert proc.returncode != 0
    lines = [line for line in out.splitlines() if line.strip()]
    last = json.loads(lines[-1])
    assert last["type"] == "error"
    assert last["code"] == "cancelled"

    book_dir = fake_paths.books_dir / ASIN
    assert not (book_dir / ".partial").exists()
    assert not (book_dir / "book.m4b").exists()
    assert not list(book_dir.glob("*.tmp"))
    assert joblock.read_job_json(fake_paths.job_json) is None


def test_cancel_without_a_running_job(run_cli, events):
    result = run_cli("cancel", ASIN, fake=True)
    assert result.returncode != 0
    last = events(result)[-1]
    assert last["type"] == "error"
    assert last["code"] == "not_running"


def test_cancel_without_an_asin_is_invalid(run_cli, events):
    result = run_cli("cancel", fake=True)
    assert result.returncode != 0
    assert events(result)[-1]["code"] == "invalid_args"


def test_cancel_rejects_a_traversing_asin(run_cli, events):
    result = run_cli("cancel", "../nope", fake=True)
    assert result.returncode != 0
    assert events(result)[-1]["code"] == "bad_asin"

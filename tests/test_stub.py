from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STUB = REPO_ROOT / "bin" / "omarchy-audible"


def test_stub_emits_single_error_and_exits_nonzero() -> None:
    result = subprocess.run([str(STUB)], capture_output=True, text=True)

    assert result.returncode == 1
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1

    event = json.loads(lines[0])
    assert event["type"] == "error"
    assert event["code"] == "not_implemented"
    assert event["message"]

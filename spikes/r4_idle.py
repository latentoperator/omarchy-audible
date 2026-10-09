"""R4 idle-cost probe (read-only). Run as root on the desktop.

Usage: python3 r4_idle.py <seconds> <quickshell pid> [<mpv pid>,...]

For the given time it records:
- the shell's CPU ticks and context switches, and its RSS every 30 s;
- each mpv's CPU ticks and context switches (a paused, silent mpv has none);
- every process whose parent chain reaches the shell (polled every 50 ms),
  grouped by plugin folder, with any audible/mpv/wl-/systemctl ones listed;
- every file whose mtime changed under the plugin's real and fake config,
  data and runtime dirs (skipping venv, books and covers).
"""

import collections
import json
import os
import re
import sys
import time
from pathlib import Path

HOME = "/home/chrisgray"
WATCH = [
    f"{HOME}/.local/share/omarchy-audible",
    f"{HOME}/.config/omarchy-audible",
    "/run/user/1000/omarchy-audible",
    f"{HOME}/.local/share/omarchy-audible-fake",
    f"{HOME}/.config/omarchy-audible-fake",
    "/run/user/1000/omarchy-audible-fake",
]
SKIP_DIRS = {"venv", "books", "covers"}
OURS = ("audible", "mpv", "wl-", "systemctl")
SWITCHES = ("voluntary_ctxt_switches", "nonvoluntary_ctxt_switches")


def read(path, mode="r"):
    try:
        with open(path, mode) as handle:
            return handle.read()
    except OSError:
        return None


def stat_fields(pid):
    text = read(f"/proc/{pid}/stat")
    return text.rsplit(")", 1)[1].split() if text else None


def ticks(pid):
    fields = stat_fields(pid)
    return int(fields[11]) + int(fields[12]) if fields else None


def status_value(pid, *keys):
    text = read(f"/proc/{pid}/status") or ""
    total = None
    for line in text.splitlines():
        if line.split(":", 1)[0] in keys:
            total = (total or 0) + int(line.split()[1])
    return total


def parent(pid):
    fields = stat_fields(pid)
    return int(fields[1]) if fields else None


def under(pid, ancestor):
    for _ in range(10):
        pid = parent(pid)
        if pid is None or pid <= 1:
            return False
        if pid == ancestor:
            return True
    return False


def pids():
    return {int(name) for name in os.listdir("/proc") if name.isdigit()}


def mtimes():
    out = {}
    for root in WATCH:
        if not os.path.isdir(root):
            continue
        for folder, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
            for name in files:
                path = Path(folder, name)
                try:
                    out[str(path)] = path.stat().st_mtime_ns
                except OSError:
                    continue
    return out


def source(cmd):
    match = re.search(r"plugins/([^/ ]+)", cmd)
    return match.group(1) if match else cmd[:50]


def main():
    duration = float(sys.argv[1])
    shell = int(sys.argv[2])
    players = [int(x) for x in sys.argv[3].split(",") if x] if len(sys.argv) > 3 else []

    seen = pids()
    start = time.time()
    shell_ticks = ticks(shell)
    shell_switches = status_value(shell, *SWITCHES)
    player_ticks = {pid: ticks(pid) for pid in players}
    player_switches = {pid: status_value(pid, *SWITCHES) for pid in players}
    files_before = mtimes()
    rss = [status_value(shell, "VmRSS")]
    spawns = []
    last_rss = start
    while time.time() - start < duration:
        now = pids()
        for pid in now - seen:
            raw = read(f"/proc/{pid}/cmdline", "rb")
            cmd = raw.replace(b"\0", b" ").decode(errors="replace")[:160] if raw else "?"
            if under(pid, shell):
                spawns.append({"t": round(time.time() - start, 2), "pid": pid, "cmd": cmd})
        seen |= now
        if time.time() - last_rss > 30:
            rss.append(status_value(shell, "VmRSS"))
            last_rss = time.time()
        time.sleep(0.05)
    files_after = mtimes()
    result = {
        "duration_s": duration,
        "qs_cpu_ticks": ticks(shell) - shell_ticks,
        "qs_ctxsw": status_value(shell, *SWITCHES) - shell_switches,
        "qs_rss_kb_samples": [*rss, status_value(shell, "VmRSS")],
        "mpv": {
            pid: {
                "cpu_ticks": ticks(pid) - player_ticks[pid],
                "ctxsw": status_value(pid, *SWITCHES) - player_switches[pid],
                "rss_kb": status_value(pid, "VmRSS"),
            }
            for pid in players
        },
        "spawn_count": len(spawns),
        "spawns_by_source": collections.Counter(source(s["cmd"]) for s in spawns).most_common(15),
        "audible_spawns": [s for s in spawns if any(mark in s["cmd"] for mark in OURS)],
        "files_changed": sorted(p for p in files_after if files_before.get(p) != files_after[p]),
    }
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()

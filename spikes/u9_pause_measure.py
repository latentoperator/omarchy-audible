"""U9: measure mpv pause → silence on a PipeWire sink.
# Needs sine.wav next to it: ffmpeg -f lavfi -i "sine=frequency=440:duration=120" -ac 2 -ar 48000 sine.wav

Starts a standalone mpv with the plugin's launch args (plus extra args), plays
a sine, and five times: resume, wait, send `set pause yes`, note when mpv
reports pause=true, and find when the sink monitor goes silent.
Usage: measure.py <sink node.name> <label> [extra mpv args...]
"""
import json, os, socket, subprocess, sys, threading, time, struct, math

sink, label, extra = sys.argv[1], sys.argv[2], sys.argv[3:]
here = os.path.dirname(os.path.abspath(__file__))
sock = os.path.join(here, f"mpv-{os.getpid()}.sock")
RATE = 48000
args = ["mpv", "--no-config", "--no-video", "--idle=yes", "--keep-open=yes", "--no-terminal",
        "--audio-display=no", "--force-window=no", "--volume=30", f"--input-ipc-server={sock}",
        f"--audio-device=pipewire/{sink}", f"--log-file={here}/mpv-{label}.log", "--msg-level=ao=v"] + extra
mpv = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(100):
    if os.path.exists(sock): break
    time.sleep(0.05)
s = socket.socket(socket.AF_UNIX); s.connect(sock)
events = []  # (time, name, data)
def reader():
    buf = b""
    while True:
        try: d = s.recv(4096)
        except OSError: return
        if not d: return
        t = time.monotonic(); buf += d
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            m = json.loads(line)
            if m.get("event") == "property-change": events.append((t, m["name"], m.get("data")))
threading.Thread(target=reader, daemon=True).start()
def cmd(*c): s.sendall((json.dumps({"command": list(c)}) + "\n").encode())

# Record the sink monitor; each read is stamped when it arrives.
rec = subprocess.Popen(["parec", "-d", sink + ".monitor", "--format=s16le", "--rate=48000", "--channels=1",
                        "--raw", "--latency-msec=10"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
blocks = []  # (arrival time, samples)
def recorder():
    while True:
        d = rec.stdout.read(960)  # 10 ms
        if not d: return
        blocks.append((time.monotonic(), struct.unpack(f"<{len(d)//2}h", d)))
threading.Thread(target=recorder, daemon=True).start()

cmd("observe_property", 1, "pause")
cmd("loadfile", os.path.join(here, "sine.wav"), "replace")
time.sleep(1.0)
rows = []
for i in range(5):
    cmd("set_property", "pause", False)
    time.sleep(1.5)
    t0 = time.monotonic(); cmd("set_property", "pause", True)
    time.sleep(2.0)
    t1 = next((t for t, n, d in events if n == "pause" and d is True and t >= t0), None)
    # last 10 ms block above threshold after t0
    loud = [t for t, smp in blocks if t >= t0 - 0.05 and math.sqrt(sum(x*x for x in smp)/len(smp)) > 10]
    t2 = max(loud) if loud else None
    rows.append((t1 - t0 if t1 else None, (t2 - t1) if (t1 and t2) else None, (t2 - t0) if t2 else None))
cmd("quit"); time.sleep(0.3); rec.terminate(); mpv.wait(timeout=5)
try: os.unlink(sock)
except OSError: pass
fmt = lambda v: "  n/a " if v is None else f"{v*1000:6.0f}"
print(f"{label}: send→pause-event | pause-event→silence | send→silence  (ms)")
for r in rows: print("   " + " | ".join(fmt(v) for v in r))
ok = [r[2] for r in rows if r[2] is not None]
if ok: print(f"   median send→silence {sorted(ok)[len(ok)//2]*1000:.0f} ms")

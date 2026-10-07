"""U9: public playPause IPC → fake mpv's pause event → silence on the sink, five times.

Run in fake mode with nothing else playing. Records the default sink's monitor
in 10 ms blocks stamped on arrival; "silence" is the last block with signal.
"""
import json, math, socket, struct, subprocess, threading, time
sock = "/run/user/1000/omarchy-audible-fake/mpv.sock"
s = socket.socket(socket.AF_UNIX); s.connect(sock)
ev = []
def rd():
    buf = b""
    while True:
        d = s.recv(4096)
        if not d: return
        t = time.monotonic(); buf += d
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            m = json.loads(line)
            if m.get("event") == "property-change" and m.get("name") == "pause": ev.append((t, m["data"]))
threading.Thread(target=rd, daemon=True).start()
s.sendall(b'{"command":["observe_property",77,"pause"]}\n')

rec = subprocess.Popen(["parec", "-d", "@DEFAULT_MONITOR@", "--format=s16le", "--rate=48000", "--channels=1",
                        "--raw", "--latency-msec=10"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
blocks = []  # (arrival time, rms)
def recorder():
    while True:
        d = rec.stdout.read(960)  # 10 ms
        if not d: return
        smp = struct.unpack(f"<{len(d)//2}h", d)
        blocks.append((time.monotonic(), math.sqrt(sum(x*x for x in smp) / len(smp))))
threading.Thread(target=recorder, daemon=True).start()

ipc = lambda *a: subprocess.run(["omarchy-shell", "latentoperator.audible", *a], capture_output=True, text=True).stdout.strip()
rows = []
for i in range(5):
    ipc("playAt", "B0FAKE0004", "0"); time.sleep(1.5)
    t0 = time.monotonic(); out = ipc("playPause")
    time.sleep(1.0)
    tp = next((t for t, d in ev if d is True and t >= t0), None)
    playing = [r for t, r in blocks if t0 - 0.5 <= t < t0]
    loud = [t for t, r in blocks if t >= t0 - 0.05 and r > 1]
    ts = max(loud) if loud else None
    ms = lambda a, b: (b - a) * 1000 if (a and b) else None
    rows.append((out, ms(t0, tp), ms(tp, ts), ms(t0, ts), max(playing, default=0)))
rec.terminate()
fmt = lambda v: "  n/a" if v is None else f"{v:5.0f}"
print("playPause | send→pause event | pause event→silence | send→silence (ms) | rms before")
for r in rows: print(f"{r[0]:>9} | {fmt(r[1])} | {fmt(r[2])} | {fmt(r[3])} | {r[4]:.0f}")

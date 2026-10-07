"""U9: public playPause IPC → fake mpv's pause event, five times."""
import json, socket, subprocess, threading, time
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
ipc = lambda *a: subprocess.run(["omarchy-shell", "latentoperator.audible", *a], capture_output=True, text=True).stdout.strip()
rows = []
for i in range(5):
    ipc("playAt", "B0FAKE0004", "0"); time.sleep(1.5)
    t0 = time.monotonic(); out = ipc("playPause"); t1 = time.monotonic()
    time.sleep(0.8)
    tp = next((t for t, d in ev if d is True and t >= t0), None)
    rows.append((out, (t1 - t0) * 1000, (tp - t0) * 1000 if tp else None))
for r in rows: print(f"playPause={r[0]}  IPC call {r[1]:5.0f} ms   send→pause event {r[2]:5.0f} ms")

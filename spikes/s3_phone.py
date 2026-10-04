"""S3 phone check: move ONE book back a known amount, Chris confirms in the phone app,
then restore the exact original position and confirm again.

Runs interactively in a terminal on the laptop. The title and times are shown on that
screen only. The machine-readable result ($XDG_RUNTIME_DIR/omarchy-audible-s3/result.json)
holds deltas and yes/no answers, no titles or ASINs.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
import tomllib
from pathlib import Path

import audible

SHIFT_MS = 10 * 60 * 1000


def dotaudible_auth() -> Path:
    d = Path.home() / ".audible"
    cfg = tomllib.loads((d / "config.toml").read_text())
    return d / cfg["profile"][cfg["APP"]["primary_profile"]]["auth_file"]


AUTH = Path(os.environ["OA_AUTH_FILE"]) if "OA_AUTH_FILE" in os.environ else dotaudible_auth()
OUT = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "omarchy-audible-s3"


def hms(ms: int) -> str:
    s = ms // 1000
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def ts(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def positions(c: audible.Client, asins: list[str]) -> dict[str, tuple]:
    r = c.get("1.0/annotations/lastpositions", asins=",".join(asins))
    out = {}
    for a in r.get("asin_last_position_heard_annots", []):
        lp = a.get("last_position_heard", {})
        out[a["asin"]] = (lp.get("status"), lp.get("position_ms"), lp.get("last_updated"))
    return out


def ask(prompt: str) -> bool:
    return input(f"{prompt} [y/n] ").strip().lower().startswith("y")


def main() -> int:
    log: dict[str, object] = {"shift_ms": SHIFT_MS}
    auth = audible.Authenticator.from_file(AUTH)
    with audible.Client(auth=auth) as c:
        items, page = [], 1
        while True:
            b = c.get("1.0/library", num_results=50, page=page,
                      response_groups="product_desc,product_attrs,is_finished").get("items", [])
            items += b
            if len(b) < 50:
                break
            page += 1
        meta = {it["asin"]: it for it in items if it.get("content_type") == "Product"}
        allpos: dict[str, tuple] = {}
        asins = list(meta)
        for i in range(0, len(asins), 25):
            allpos.update(positions(c, asins[i:i + 25]))
        now = dt.datetime.now(dt.timezone.utc)
        cands = sorted(
            ((a, v) for a, v in allpos.items()
             if v[0] == "Exists" and v[1] and v[1] > SHIFT_MS + 60_000 and not meta[a].get("is_finished")
             and ts(v[2]) and (now - ts(v[2])).total_seconds() > 3600),
            key=lambda kv: ts(kv[1][2]), reverse=True)
        if not cands:
            print("No suitable book found.")
            return 1
        asin, (_, orig_ms, _) = cands[0]
        title = meta[asin].get("title", "?")
        acr = c.get(f"1.0/content/{asin}/metadata",
                    response_groups="content_reference")["content_metadata"]["content_reference"]["acr"]
        target = orig_ms - SHIFT_MS

        print(f"\n  Book:              {title}")
        print(f"  Current position:  {hms(orig_ms)}")
        print(f"  Test position:     {hms(target)}   (10 minutes earlier)\n")
        print("  Before you continue: on the phone, make sure this book is NOT playing.")
        if not ask("  Move it to the test position now?"):
            print("Nothing changed.")
            return 0

        c.put(f"1.0/lastpositions/{asin}", body={"acr": acr, "asin": asin, "position_ms": target})
        time.sleep(2)
        log["write_readback_delta_ms"] = positions(c, [asin])[asin][1] - target
        print(f"\n  Done. Audible now has {hms(target)} for this book.")
        print("  On the phone: fully close the Audible app (swipe it away), reopen it, and open")
        print("  this book WITHOUT pressing play. It may offer to jump to the newer position.")
        log["phone_saw_test_position"] = ask(f"\n  Does the phone show about {hms(target)} (or offer to jump there)?")
        log["phone_offered_jump_prompt"] = ask("  Did it ask/offer to jump, rather than move silently?")

        c.put(f"1.0/lastpositions/{asin}", body={"acr": acr, "asin": asin, "position_ms": orig_ms})
        time.sleep(2)
        log["restore_readback_delta_ms"] = positions(c, [asin])[asin][1] - orig_ms
        print(f"\n  Restored. Audible has {hms(orig_ms)} again.")
        print("  On the phone: close and reopen the app and open the book again (still no play).")
        log["phone_saw_restored_position"] = ask(f"\n  Does the phone show about {hms(orig_ms)} again?")

    OUT.mkdir(mode=0o700, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(log))
    print("\n  All done. Press Enter to close.")
    input()
    return 0


if __name__ == "__main__":
    os.umask(0o077)
    sys.exit(main())

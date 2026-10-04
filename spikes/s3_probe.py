"""S3: position write-back round trip on ONE book, then exact restore.
Picks the most recently updated position (so 'recent' order is unchanged), skipping
anything updated in the last hour (could be playing on the phone). Prints numbers only."""
import os
import datetime as dt
import json
import sys
import time
from pathlib import Path

import audible

auth = audible.Authenticator.from_file(Path(os.environ["OA_AUTH_FILE"]))
log = {}


def positions(c, asins):
    r = c.get("1.0/annotations/lastpositions", asins=",".join(asins))
    out = {}
    for a in r.get("asin_last_position_heard_annots", []):
        lp = a.get("last_position_heard", {})
        out[a["asin"]] = (lp.get("status"), lp.get("position_ms"), lp.get("last_updated"))
    return out


with audible.Client(auth=auth) as c:
    items, page = [], 1
    while True:
        b = c.get("1.0/library", num_results=50, page=page, response_groups="product_attrs").get("items", [])
        items += b
        if len(b) < 50:
            break
        page += 1
    asins = [it["asin"] for it in items if it["content_type"] == "Product"]
    allpos = {}
    for i in range(0, len(asins), 25):
        allpos.update(positions(c, asins[i:i + 25]))
    log["positions_read"] = len(allpos)
    log["status_counts"] = {s: sum(1 for v in allpos.values() if v[0] == s) for s in {v[0] for v in allpos.values()}}
    now = dt.datetime.now(dt.timezone.utc)

    def ts(s):
        if not s:
            return None
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)

    sample = next((v[2] for v in allpos.values() if v[2]), "")
    log["timestamp_shape"] = "".join("9" if ch.isdigit() else ch for ch in sample)

    cands = sorted(((a, v) for a, v in allpos.items() if v[0] == "Exists" and v[1] and v[1] > 120000
                    and ts(v[2]) and (now - ts(v[2])).total_seconds() > 3600),
                   key=lambda kv: ts(kv[1][2]), reverse=True)
    asin, (st, orig_ms, orig_upd) = cands[0]
    log["picked_rank_by_recency"] = 1 + [a for a, v in sorted(
        ((a, v) for a, v in allpos.items() if v[0] == "Exists" and v[2]), key=lambda kv: ts(kv[1][2]), reverse=True)].index(asin)
    log["orig_age_hours"] = round((now - ts(orig_upd)).total_seconds() / 3600, 1)

    md = c.get(f"1.0/content/{asin}/metadata", response_groups="content_reference")
    acr = md["content_metadata"]["content_reference"].get("acr")
    log["acr_from_metadata"] = bool(acr)
    if not acr:
        lr = c.post(f"1.0/content/{asin}/licenserequest",
                    body={"consumption_type": "Streaming", "drm_type": "Adrm", "quality": "High"})
        acr = lr["content_license"].get("acr")
        log["acr_from_licenserequest"] = bool(acr)

    def put(ms):
        try:
            r = c.put(f"1.0/lastpositions/{asin}", body={"acr": acr, "asin": asin, "position_ms": ms})
            return {"ok": True, "resp_keys": sorted(r.keys()) if isinstance(r, dict) else type(r).__name__}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": type(e).__name__, "status": getattr(getattr(e, "response", None), "status_code", None)}

    target = orig_ms - 60000
    log["put_test"] = put(target)
    time.sleep(2)
    s1 = positions(c, [asin])[asin]
    log["readback_delta_ms"] = None if s1[1] is None else s1[1] - target
    log["readback_updated_changed"] = s1[2] != orig_upd
    log["restore"] = put(orig_ms)
    time.sleep(2)
    s2 = positions(c, [asin])[asin]
    log["restored_exact"] = s2[1] == orig_ms
    log["restored_delta_ms"] = None if s2[1] is None else s2[1] - orig_ms
    log["still_most_recent"] = sorted(
        ((a, v) for a, v in {**allpos, asin: s2}.items() if v[0] == "Exists" and v[2]),
        key=lambda kv: ts(kv[1][2]), reverse=True)[0][0] == asin

json.dump(log, sys.stdout, indent=1)


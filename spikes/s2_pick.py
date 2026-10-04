"""S2 helper: pick the smallest MultiPartBook and smallest SinglePartBook.
Writes ASINs and runtimes to a private file; prints nothing identifying."""
import os
import json
import sys
from pathlib import Path

import audible

AUTH = Path(os.environ["OA_AUTH_FILE"])
out = Path(sys.argv[1])

auth = audible.Authenticator.from_file(AUTH)
with audible.Client(auth=auth) as c:
    items, page = [], 1
    while True:
        b = c.get("1.0/library", num_results=50, page=page,
                  response_groups="product_attrs,media,relationships").get("items", [])
        items += b
        if len(b) < 50:
            break
        page += 1
    picks = {}
    for kind in ("MultiPartBook", "SinglePartBook"):
        cands = [it for it in items if it["content_delivery_type"] == kind and it["content_type"] == "Product"]
        cands.sort(key=lambda it: it.get("runtime_length_min") or 10**9)
        it = cands[0]
        m = c.get(f"1.0/content/{it['asin']}/metadata", response_groups="chapter_info",
                  quality="High", chapter_titles_type="Tree")["content_metadata"]["chapter_info"]
        picks[kind] = {"asin": it["asin"], "runtime_ms": m["runtime_length_ms"],
                       "chapters": len(m.get("chapters") or [])}
out.write_text(json.dumps(picks))
print(json.dumps({k: {"runtime_min": round(v["runtime_ms"] / 60000), "chapters": v["chapters"]}
                  for k, v in picks.items()}))

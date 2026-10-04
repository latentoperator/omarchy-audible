"""Compare API chapter counts (flat vs tree, top-level vs total) across the library. Numbers only."""
import os
import json
from pathlib import Path

import audible

auth = audible.Authenticator.from_file(Path(os.environ["OA_AUTH_FILE"]))


def count(chs):
    return sum(1 + count(c.get("chapters") or []) for c in chs)


rows = []
with audible.Client(auth=auth) as c:
    items, page = [], 1
    while True:
        b = c.get("1.0/library", num_results=50, page=page, response_groups="product_attrs").get("items", [])
        items += b
        if len(b) < 50:
            break
        page += 1
    for it in items:
        if it["content_type"] != "Product":
            continue
        r = {"kind": it["content_delivery_type"]}
        for t in ("Flat", "Tree"):
            ci = c.get(f"1.0/content/{it['asin']}/metadata", response_groups="chapter_info",
                       quality="High", chapter_titles_type=t)["content_metadata"]["chapter_info"]
            top = ci.get("chapters") or []
            r[t] = (len(top), count(top))
        rows.append(r)
nested = [r for r in rows if r["Tree"][0] != r["Tree"][1]]
print(json.dumps({
    "books": len(rows),
    "flat_equals_tree_total": sum(r["Flat"][0] == r["Tree"][1] for r in rows),
    "books_with_nested_chapters": len(nested),
    "nested_by_kind": {k: sum(1 for r in nested if r["kind"] == k) for k in ("MultiPartBook", "SinglePartBook")},
    "example_nested_top_vs_total": [r["Tree"] for r in nested[:8]],
}))

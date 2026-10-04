"""S4 probe: runs on the laptop. Prints only structure, counts and timings.
Never prints titles, authors, ASINs or account data."""
import os
import collections
import json
import sys
import time
from pathlib import Path

import audible

AUTH = Path(os.environ["OA_AUTH_FILE"])
GROUPS_SETS = {
    "arch_doc": "product_desc,media,contributors,series,product_attrs,listening_status,percent_complete,is_finished",
    "plus_relationships": "product_desc,media,contributors,series,product_attrs,listening_status,percent_complete,is_finished,relationships",
}


def shape(v, depth=0):
    if isinstance(v, dict):
        if depth > 2:
            return "{…}"
        return {k: shape(x, depth + 1) for k, x in sorted(v.items())}
    if isinstance(v, list):
        return [shape(v[0], depth + 1)] if v else []
    return type(v).__name__


def fetch_all(client, groups, page_size=50):
    items, pages, t0 = [], 0, time.time()
    page = 1
    while True:
        r = client.get("1.0/library", num_results=page_size, page=page, response_groups=groups,
                       sort_by="-PurchaseDate")
        batch = r.get("items", [])
        items.extend(batch)
        pages += 1
        if len(batch) < page_size:
            break
        page += 1
    return items, pages, time.time() - t0


def main():
    auth = audible.Authenticator.from_file(AUTH)
    out = {}
    with audible.Client(auth=auth) as client:
        for name, groups in GROUPS_SETS.items():
            try:
                items, pages, secs = fetch_all(client, groups)
                out[name] = {"items": len(items), "pages": pages, "seconds": round(secs, 2)}
            except Exception as e:  # noqa: BLE001
                out[name] = {"error": type(e).__name__ + ": " + str(e)[:200]}
        items, _, _ = fetch_all(client, GROUPS_SETS["plus_relationships"])

    keys = collections.Counter(k for it in items for k in it.keys())
    nonnull = collections.Counter(k for it in items for k, v in it.items() if v not in (None, [], {}, ""))
    ct = collections.Counter(it.get("content_type") for it in items)
    cdt = collections.Counter(it.get("content_delivery_type") for it in items)
    fmt = collections.Counter(
        tuple(sorted({c.get("name") for c in (it.get("available_codecs") or [])})) for it in items)
    rel_types = collections.Counter(
        (r.get("relationship_type"), r.get("relationship_to_product"))
        for it in items for r in (it.get("relationships") or []))
    status_shapes = collections.Counter(json.dumps(shape(it.get("listening_status")), sort_keys=True) for it in items)
    multipart = [it for it in items if it.get("content_delivery_type") == "MultiPartBook"]
    mp_children = [
        sum(1 for r in (it.get("relationships") or []) if r.get("relationship_to_product") == "child")
        for it in multipart]
    one = next((it for it in items if it.get("content_type") == "Product"), items[0])

    report = {
        "fetch": out,
        "total_items": len(items),
        "key_presence": dict(keys),
        "key_nonempty": dict(nonnull),
        "content_type": dict(ct),
        "content_delivery_type": dict(cdt),
        "codec_sets": {"|".join(k) or "(none)": v for k, v in fmt.items()},
        "relationship_types": {f"{a}/{b}": v for (a, b), v in rel_types.items()},
        "listening_status_shapes": dict(status_shapes),
        "multipart_count": len(multipart),
        "multipart_child_counts": mp_children,
        "example_item_shape": shape(one),
        "runtime_min_present": sum(1 for it in items if it.get("runtime_length_min")),
        "series_present": sum(1 for it in items if it.get("series")),
        "subtitle_present": sum(1 for it in items if it.get("subtitle")),
        "cover_keys": sorted({k for it in items for k in (it.get("product_images") or {}).keys()}),
    }
    json.dump(report, sys.stdout, indent=1, default=str)


if __name__ == "__main__":
    main()

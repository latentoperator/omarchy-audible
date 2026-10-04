"""S4 part 2: multi-part structure via read-only GETs. Prints numbers only."""
import os
import collections
import json
import sys
from pathlib import Path

import audible

AUTH = Path(os.environ["OA_AUTH_FILE"])
GROUPS = "product_desc,media,contributors,series,product_attrs,listening_status,percent_complete,is_finished,relationships"


def all_items(client):
    items, page = [], 1
    while True:
        b = client.get("1.0/library", num_results=50, page=page, response_groups=GROUPS).get("items", [])
        items += b
        if len(b) < 50:
            return items
        page += 1


def meta(client, asin):
    try:
        r = client.get(f"1.0/content/{asin}/metadata", response_groups="chapter_info,content_reference",
                       quality="High", chapter_titles_type="Tree")
        cm = r.get("content_metadata", {})
        ci = cm.get("chapter_info", {}) or {}
        cr = cm.get("content_reference", {}) or {}
        return {
            "chapters": len(ci.get("chapters") or []),
            "runtime_ms": ci.get("runtime_length_ms"),
            "is_accurate": ci.get("is_accurate"),
            "codec": cr.get("codec"),
            "content_format": cr.get("content_format"),
            "size": cr.get("content_size_in_bytes"),
            "ok": True,
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": type(e).__name__ + ": " + str(e)[:120]}


def main():
    auth = audible.Authenticator.from_file(AUTH)
    with audible.Client(auth=auth) as c:
        items = all_items(c)
        by_asin = {it["asin"]: it for it in items}
        mp = [it for it in items if it["content_delivery_type"] == "MultiPartBook"]
        rows = []
        for it in mp:
            m = meta(c, it["asin"])
            cat_ms = (it.get("runtime_length_min") or 0) * 60000
            children = [r for r in (it.get("relationships") or []) if r.get("relationship_to_product") == "child"]
            child_in_lib = sum(1 for r in children if r.get("asin") in by_asin)
            rows.append({
                "children": len(children),
                "children_in_library": child_in_lib,
                "meta_ok": m["ok"],
                "chapters": m.get("chapters"),
                "runtime_ratio": round(m["runtime_ms"] / cat_ms, 3) if m.get("runtime_ms") and cat_ms else None,
                "codec": m.get("codec"),
                "format": m.get("content_format"),
                "error": m.get("error"),
            })
        # Library items that are themselves parts of a parent
        parts = [it for it in items if any(r.get("relationship_to_product") == "parent" and r.get("relationship_type") == "component"
                                         for r in (it.get("relationships") or []))]
        part_rows = []
        for it in parts:
            parent = next(r for r in it["relationships"] if r.get("relationship_type") == "component" and r.get("relationship_to_product") == "parent")
            part_rows.append({"delivery": it["content_delivery_type"], "content_type": it["content_type"],
                              "parent_in_library": parent.get("asin") in by_asin,
                              "meta": meta(c, it["asin"])})
        single = [it for it in items if it["content_delivery_type"] == "SinglePartBook"][:5]
        single_rows = [{"meta": meta(c, it["asin"]),
                        "ratio": None} for it in single]
        lect = [{"delivery": it["content_delivery_type"], "meta": meta(c, it["asin"])}
                for it in items if it["content_type"] != "Product"]

    summary = {
        "multipart_total": len(rows),
        "multipart_meta_ok": sum(r["meta_ok"] for r in rows),
        "multipart_children_in_library": collections.Counter(r["children_in_library"] for r in rows),
        "runtime_ratio_out_of_1pct": [r["runtime_ratio"] for r in rows if r["runtime_ratio"] and abs(r["runtime_ratio"] - 1) > 0.01],
        "runtime_ratio_min_max": [min(r["runtime_ratio"] for r in rows if r["runtime_ratio"]), max(r["runtime_ratio"] for r in rows if r["runtime_ratio"])],
        "multipart_chapter_counts_min_max": [min(r["chapters"] or 0 for r in rows), max(r["chapters"] or 0 for r in rows)],
        "multipart_codec_format": collections.Counter(f"{r['codec']}/{r['format']}" for r in rows),
        "multipart_errors": [r["error"] for r in rows if r["error"]],
        "parts_in_library": part_rows,
        "single_sample": single_rows,
        "lectures": lect,
    }
    json.dump(summary, sys.stdout, indent=1, default=str)


if __name__ == "__main__":
    main()

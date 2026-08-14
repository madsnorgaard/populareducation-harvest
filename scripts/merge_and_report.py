#!/usr/bin/env python3
"""Merge the two Wayback harvests and generate MISSING-CONTENT.md.

Run after ``python harvest.py all``:

  python scripts/merge_and_report.py

Outputs (under output/populareducation/):
  items/merged/*.json   one item per legacy path, .co.za capture wins conflicts
                        unless its body is drastically shorter
  MISSING-CONTENT.md    tables of pages/files/images with no successful capture
"""
from __future__ import annotations

import json
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from peh import config  # noqa: E402
from peh.schema import slugify, dumps  # noqa: E402

OUT = config.OUTPUT
PREFERRED = "wayback_coza"          # later mirror wins
FALLBACK = "wayback_org"


def load_items(source: str) -> dict[str, dict]:
    d = {}
    src_dir = OUT / "items" / source
    if not src_dir.exists():
        return d
    for jp in sorted(src_dir.glob("*.json")):
        item = json.loads(jp.read_text(encoding="utf-8"))
        key = item["identifiers"].get("legacy_path") or item["source_id"]
        d[key] = item
    return d


def merge() -> list[dict]:
    org = load_items(FALLBACK)
    coza = load_items(PREFERRED)
    keys = sorted(set(org) | set(coza))
    merged = []

    def has_audio(item: dict) -> bool:
        return any((m.get("kind") == "audio" and m.get("downloaded"))
                   for m in item.get("files", []))

    for k in keys:
        a, b = coza.get(k), org.get(k)
        if a and b:
            # prefer the later mirror unless its body collapsed
            pick, other = (a, b)
            if len(a.get("body") or "") < 0.5 * len(b.get("body") or ""):
                pick, other = (b, a)
            pick = dict(pick)
            pick["extra"] = dict(pick.get("extra") or {})
            pick["extra"]["merged_from"] = [a["source"], b["source"]]
            # union of media by origin_url
            for bucket in ("images", "files"):
                seen = {m.get("origin_url") or m.get("url")
                        for m in pick.get(bucket, [])}
                for m in other.get(bucket, []):
                    mk = m.get("origin_url") or m.get("url")
                    if mk not in seen:
                        pick.setdefault(bucket, []).append(m)
                        seen.add(mk)
            merged.append(pick)
        else:
            merged.append(dict(a or b))
    # Pages carrying recordings are audio items (the D7 site had no audio
    # node type; the PEN 2018 archive lives on plain pages).
    for item in merged:
        if item["kind"] == "page" and has_audio(item):
            item["kind"] = "audio_item"
    return merged


def write_merged(items: list[dict]):
    dest = OUT / "items" / "merged"
    dest.mkdir(parents=True, exist_ok=True)
    for old in dest.glob("*.json"):
        old.unlink()
    for it in items:
        name = slugify(it["source_id"], 100) + ".json"
        (dest / name).write_text(dumps(it), encoding="utf-8")
    return dest


def load_index(domain: str) -> dict:
    p = OUT / "cdx" / f"{domain}-index.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {
        "pages": {}, "assets": {}, "never_ok": {}}


def build_report(items: list[dict]) -> str:
    org = load_index("populareducation.org.za")
    coza = load_index("populareducation.co.za")
    captured_pages = set(org["pages"]) | set(coza["pages"])
    captured_assets = set(org["assets"]) | set(coza["assets"])

    # 1. pages that only ever errored in the archive (both domains)
    never_pages = {}
    for idx in (org, coza):
        for k, (status, url) in idx["never_ok"].items():
            if k in captured_pages or k in captured_assets:
                continue
            if any(k.endswith(e) for e in (".css", ".js", ".txt", ".ico")):
                continue
            never_pages.setdefault(k, (status, url))

    # 2/3. media referenced by harvested pages but never captured
    missing_media: dict[str, dict] = {}
    referenced_missing_pages: dict[str, set] = defaultdict(set)
    for it in items:
        page = it["identifiers"].get("legacy_path", it["source_id"])
        for m in it.get("extra", {}).get("missing_assets", []):
            e = missing_media.setdefault(m["url"], {
                "bucket": m["bucket"], "caption": m.get("caption"),
                "pages": set()})
            e["pages"].add(page)
        for ln in it.get("extra", {}).get("internal_links", []):
            p = ln.get("path", "")
            if p and p not in captured_pages and p not in captured_assets \
                    and not p.startswith(("/user", "/search", "/taxonomy",
                                          "/category", "/popular", "/comment",
                                          "/media-gallery", "/gallery-collections")) \
                    and p not in ("/", "/rss.xml"):
                referenced_missing_pages[p].add(page)

    lines = [
        "# Missing content - populareducation.org.za rebuild",
        "",
        "Content the Wayback Machine never successfully captured, found while",
        "harvesting both archived domains. Work through the tables and record",
        "the outcome in the Resolution column (e.g. \"Shirley has original\",",
        "\"re-scan\", \"gone for good\").",
        "",
        f"Harvested pages: {len(items)}  |  archived assets: "
        f"{len(captured_assets)}",
        "",
        "## 1. Pages in the archive index that never returned 200",
        "",
        "| Path | Last status | Example URL | Resolution |",
        "|---|---|---|---|",
    ]
    for k in sorted(never_pages):
        status, url = never_pages[k]
        lines.append(f"| `{k}` | {status} | {url} | |")

    lines += [
        "",
        "## 2. Pages linked from harvested content but never captured",
        "",
        "| Path | Linked from | Resolution |",
        "|---|---|---|",
    ]
    for p in sorted(referenced_missing_pages):
        refs = sorted(referenced_missing_pages[p])
        shown = ", ".join(f"`{r}`" for r in refs[:3])
        more = f" +{len(refs) - 3} more" if len(refs) > 3 else ""
        lines.append(f"| `{p}` | {shown}{more} | |")

    for bucket, heading in (("file", "3. Documents/audio referenced but not "
                                     "archived"),
                            ("image", "4. Images referenced but not archived")):
        lines += ["", f"## {heading}", "",
                  "| File | Caption | Referenced by | Resolution |",
                  "|---|---|---|---|"]
        for u in sorted(missing_media):
            e = missing_media[u]
            if e["bucket"] != bucket:
                continue
            refs = sorted(e["pages"])
            shown = ", ".join(f"`{r}`" for r in refs[:2])
            more = f" +{len(refs) - 2} more" if len(refs) > 2 else ""
            cap = (e.get("caption") or "").replace("|", "/")[:60]
            lines.append(f"| `{u}` | {cap} | {shown}{more} | |")

    return "\n".join(lines) + "\n"


def main():
    items = merge()
    dest = write_merged(items)
    report = build_report(items)
    rp = OUT / "MISSING-CONTENT.md"
    rp.write_text(report, encoding="utf-8")
    kinds = defaultdict(int)
    for it in items:
        kinds[it["kind"]] += 1
    print(f"merged items: {len(items)} -> {dest}")
    print("by kind:", dict(sorted(kinds.items(), key=lambda x: -x[1])))
    print(f"report: {rp}")


if __name__ == "__main__":
    main()

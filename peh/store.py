"""Output layout, manifest, and rights/provenance report."""
from __future__ import annotations

import csv
import json
import logging
import pathlib
from datetime import datetime, timezone

from .schema import Item, dumps

log = logging.getLogger("peh.store")


class Store:
    def __init__(self, root: pathlib.Path):
        self.root = root
        self.items_dir = root / "items"
        self.media_dir = root / "media"
        self.items_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = root / "manifest.jsonl"
        self.rights_path = root / "rights-report.csv"

    def write_item(self, item: Item) -> pathlib.Path:
        path = self.root / item.rel_json_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps(item.to_dict()), encoding="utf-8")
        self._append_manifest(item)
        return path

    def _append_manifest(self, item: Item):
        row = {
            "source": item.source,
            "source_id": item.source_id,
            "kind": item.kind,
            "title": item.title,
            "url": item.source_url,
            "date": item.display_date or item.date_iso,
            "images": len(item.images),
            "files": len(item.files),
            "downloaded": sum(1 for m in item.all_media() if m.downloaded),
            "rights": item.rights,
            "json": item.rel_json_path(),
        }
        with self.manifest_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def write_rights_report(self):
        """Rebuild the media-level rights/provenance CSV from all item JSON."""
        rows = []
        for jp in sorted(self.items_dir.rglob("*.json")):
            try:
                d = json.loads(jp.read_text(encoding="utf-8"))
            except Exception:
                continue
            for bucket in ("images", "files"):
                for m in d.get(bucket, []):
                    rows.append({
                        "source": d.get("source"),
                        "item": d.get("title"),
                        "item_url": d.get("source_url"),
                        "media_url": m.get("url"),
                        "kind": m.get("kind"),
                        "downloaded": m.get("downloaded"),
                        "local_path": m.get("local_path"),
                        "rights": m.get("rights"),
                        "credit": m.get("credit"),
                    })
        with self.rights_path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=[
                "source", "item", "item_url", "media_url", "kind",
                "downloaded", "local_path", "rights", "credit"])
            w.writeheader()
            w.writerows(rows)
        return len(rows)

    def summary(self) -> dict:
        by_source: dict[str, int] = {}
        n = 0
        if self.manifest_path.exists():
            for line in self.manifest_path.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                n += 1
                by_source[r["source"]] = by_source.get(r["source"], 0) + 1
        return {"items": n, "by_source": by_source}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

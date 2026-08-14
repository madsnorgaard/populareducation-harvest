"""Drive an adapter: harvest items, download their media, write JSON + manifest."""
from __future__ import annotations

import logging
import pathlib
import traceback

from . import config, sources
from .http import Fetcher
from .media import Downloader
from .schema import Item
from .sources._base import Ctx
from .store import Store

log = logging.getLogger("peh.runner")


def make_fetcher(cfg: dict) -> Fetcher:
    d = cfg["download"]
    return Fetcher(
        respect_robots=d.get("respect_robots", True),
        robots_bypass=tuple(d.get("robots_bypass", [])),
    )


def run_source(slug: str, *, cfg: dict, store: Store, fetcher: Fetcher,
               limit: int | None = None, download: bool = True) -> dict:
    mod = sources.get(slug)
    if not mod:
        raise SystemExit(f"unknown source: {slug} (have {sources.slugs()})")
    dl = Downloader(fetcher, store.media_dir,
                    policy=cfg["download"]["policy"] if download else "none",
                    max_file_mb=cfg["download"].get("max_file_mb", 75))
    ctx = Ctx(f=fetcher, cfg=cfg, limit=limit)
    stats = {"source": slug, "items": 0, "images": 0, "files": 0, "errors": 0}
    log.info("=== harvest %s (limit=%s, download=%s) ===", slug, limit, download)
    try:
        for item in mod.harvest(ctx):
            try:
                for m in item.all_media():
                    dl.fetch(m)
                store.write_item(item)
                stats["items"] += 1
                stats["images"] += len(item.images)
                stats["files"] += len(item.files)
                if stats["items"] % 10 == 0:
                    log.info("  %s: %s items", slug, stats["items"])
            except Exception:
                stats["errors"] += 1
                log.warning("item error in %s:\n%s", slug, traceback.format_exc())
    except Exception:
        stats["errors"] += 1
        log.error("source %s crashed:\n%s", slug, traceback.format_exc())
    stats["media"] = dl.stats
    log.info("=== %s done: %s items, %s img, %s files, dl=%s ===",
             slug, stats["items"], stats["images"], stats["files"],
             dl.stats["downloaded"])
    return stats

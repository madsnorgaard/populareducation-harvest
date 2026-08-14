"""Harvest configuration: domains, filters, download policy.

Defaults live here. Override any key by creating ``config.local.json`` in the
project root (a shallow-merged JSON object).
"""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output" / "populareducation"

DEFAULTS = {
    "download": {
        "policy": "all",            # all | open | none
        "max_file_mb": 120,
        "respect_robots": True,
        # web.archive.org robots is not meaningful for replay URLs; stay polite
        # via per-host pacing instead.
        "robots_bypass": ["web.archive.org"],
    },
    "wayback": {
        # First path segment prefixes that are never content pages.
        "exclude_prefixes": [
            "sites", "misc", "modules", "themes", "cgi-sys", ".well-known",
            "users", "user", "comment", "search", "taxonomy", "filter",
            "ads.txt", "app-ads.txt", "CHANGELOG.txt", "robots.txt",
            "favicon.ico", "xmlrpc.php", "install.php", "update.php",
            "cron.php", "rss.xml", "sitemap.xml",
        ],
        # Listing/view paths (harvested for reference, kind = "listing").
        "listing_prefixes": [
            "tools", "library", "organisations", "energy", "popular",
            "gallery-collections", "blogs", "blog", "archive",
        ],
        "rights": "© Popular Education South Africa (rebuilt from the Internet Archive)",
        "credit": "Popular Education South Africa",
    },
    "wayback_org": {"domain": "populareducation.org.za"},
    "wayback_coza": {"domain": "populareducation.co.za"},
}


def load() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))   # deep copy
    local = ROOT / "config.local.json"
    if local.exists():
        override = json.loads(local.read_text(encoding="utf-8"))
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg

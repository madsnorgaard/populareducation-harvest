"""Source-agnostic schema for harvested Popular Education South Africa material.

Every adapter yields Item objects. The runner downloads their media (subject to
policy), then writes one JSON file per item to
``output/populareducation/items/<source>/<source_id>.json`` plus a row in the
manifest and the rights report. The JSON is the hand-off format for the
pe_migrate migration into the populareducation.org.za Drupal 11 content model.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from typing import Optional


def slugify(value: str, maxlen: int = 80) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:maxlen] or "item"


def stable_id(*parts: str) -> str:
    """Deterministic short id from arbitrary parts (e.g. a URL)."""
    h = hashlib.sha1("\x1f".join(p or "" for p in parts).encode("utf-8")).hexdigest()
    return h[:16]


@dataclass
class MediaRef:
    """An image, PDF, audio, or video attached to an item."""
    url: str                            # fetch URL (Wayback snapshot for archived media)
    kind: str = "file"                  # image | file | pdf | audio | video
    filename: Optional[str] = None
    mime: Optional[str] = None
    size: Optional[int] = None
    sha256: Optional[str] = None
    local_path: Optional[str] = None    # relative to output root; set after download
    downloaded: bool = False
    hotlink_only: bool = False          # never download (e.g. asset lost from archive)
    origin_url: Optional[str] = None    # original URL on the dead site
    rights: str = "review-required"     # honest default; adapters override when known
    credit: Optional[str] = None
    caption: Optional[str] = None
    source_url: Optional[str] = None    # page the media was found on


@dataclass
class Item:
    """A normalized harvested record from the archived site."""
    source: str                         # adapter slug, e.g. "wayback_org"
    source_id: str                      # canonical id within the source (legacy path)
    source_url: str                     # canonical URL on the original site
    title: str

    # Maps onto the Drupal 11 bundles; editorial triage decides finally.
    kind: str = "page"                  # tool | organisation | library_item | gallery |
                                        # gallery_media | audio_item | blog_post |
                                        # page | listing

    summary: Optional[str] = None
    body: str = ""                      # cleaned HTML of the content region

    display_date: Optional[str] = None  # human string, e.g. "October 2014"
    date_iso: Optional[str] = None      # yyyy[-mm[-dd]] when parseable

    creators: list[str] = field(default_factory=list)
    publishers: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    subjects: list[str] = field(default_factory=list)   # taxonomy term labels
    identifiers: dict = field(default_factory=dict)     # legacy_path, legacy_nid,
                                                        # wayback_timestamp, wayback_url

    rights: str = "review-required"
    credit: Optional[str] = None

    images: list[MediaRef] = field(default_factory=list)
    files: list[MediaRef] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)     # {url,title,rel}

    provenance: dict = field(default_factory=dict)      # harvested_at, via, query
    extra: dict = field(default_factory=dict)           # node_type, internal_links,
                                                        # missing_assets

    def all_media(self):
        return [*self.images, *self.files]

    def to_dict(self) -> dict:
        return asdict(self)

    def rel_json_path(self) -> str:
        return f"items/{self.source}/{slugify(self.source_id, 100)}.json"


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False)

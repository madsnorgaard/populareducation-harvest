"""Shared helpers for source adapters."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..http import Fetcher
from ..schema import Item, MediaRef
from ..store import now_iso


@dataclass
class Ctx:
    f: Fetcher
    cfg: dict
    limit: Optional[int] = None
    query_extra: Optional[str] = None


def provenance(via: str, query: str | None = None, **extra) -> dict:
    d = {"harvested_at": now_iso(), "via": via}
    if query:
        d["query"] = query
    d.update(extra)
    return d


def media_from_extract(entry: dict, *, kind: str, rights: str,
                       credit: str | None, source_url: str) -> MediaRef:
    return MediaRef(
        url=entry["url"],
        kind=kind,
        caption=entry.get("caption"),
        rights=rights,
        credit=credit,
        source_url=source_url,
    )


def limited(it, limit):
    if not limit:
        yield from it
        return
    n = 0
    for x in it:
        yield x
        n += 1
        if n >= limit:
            return

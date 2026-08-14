"""Adapter registry. Order = default 'harvest all' order."""
from . import wayback_org, wayback_coza

REGISTRY = {m.SLUG: m for m in (wayback_org, wayback_coza)}


def get(slug: str):
    return REGISTRY.get(slug)


def slugs():
    return list(REGISTRY.keys())

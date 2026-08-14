"""populareducation.org.za via the Wayback Machine (captures to Aug 2023)."""
from ._base import Ctx
from . import _wayback

SLUG = "wayback_org"
LABEL = "Wayback: populareducation.org.za"


def harvest(ctx: Ctx):
    yield from _wayback.harvest_domain(ctx, SLUG, ctx.cfg[SLUG]["domain"])

"""populareducation.co.za via the Wayback Machine (later mirror, to Nov 2025).

Wins over wayback_org on merge conflicts (see scripts/merge_and_report.py).
"""
from ._base import Ctx
from . import _wayback

SLUG = "wayback_coza"
LABEL = "Wayback: populareducation.co.za (later mirror)"


def harvest(ctx: Ctx):
    yield from _wayback.harvest_domain(ctx, SLUG, ctx.cfg[SLUG]["domain"])

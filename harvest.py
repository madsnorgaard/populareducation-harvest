#!/usr/bin/env python3
"""Popular Education South Africa - Wayback Machine harvester.

Usage:
  python harvest.py list
  python harvest.py run <source> [<source> ...] [--limit N] [--no-download]
  python harvest.py all [--limit N] [--no-download]
  python harvest.py report

Sources: wayback_org wayback_coza
Output:  output/populareducation/  (items/*.json, media/, raw/, cdx/,
         manifest.jsonl, rights-report.csv)

After harvesting both sources, run:
  python scripts/merge_and_report.py
to produce items/merged/ and MISSING-CONTENT.md.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from peh import config, sources
from peh.runner import make_fetcher, run_source
from peh.store import Store


def _setup_logging(verbose: bool):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def cmd_list(_):
    for slug, mod in sources.REGISTRY.items():
        print(f"  {slug:14} {mod.LABEL}")


def _run(slugs, limit, download, verbose):
    cfg = config.load()
    store = Store(config.OUTPUT)
    fetcher = make_fetcher(cfg)
    allstats = []
    try:
        for slug in slugs:
            allstats.append(run_source(slug, cfg=cfg, store=store,
                                       fetcher=fetcher, limit=limit,
                                       download=download))
    finally:
        fetcher.close()
    store.write_rights_report()
    print("\n=== harvest summary ===")
    tot_i = tot_dl = 0
    for s in allstats:
        m = s["media"]
        print(f"  {s['source']:14} items={s['items']:4}  img={s['images']:4}  "
              f"files={s['files']:4}  downloaded={m['downloaded']:4}  "
              f"hotlinked={m['hotlinked']:4}  err={s['errors']}")
        tot_i += s["items"]
        tot_dl += m["downloaded"]
    print(f"  {'TOTAL':14} items={tot_i}  downloaded_media={tot_dl}")
    print(f"\noutput: {config.OUTPUT}")


def cmd_run(args):
    bad = [s for s in args.sources if s not in sources.REGISTRY]
    if bad:
        sys.exit(f"unknown source(s): {bad}\navailable: {sources.slugs()}")
    _run(args.sources, args.limit, not args.no_download, args.verbose)


def cmd_all(args):
    _run(sources.slugs(), args.limit, not args.no_download, args.verbose)


def cmd_report(_):
    store = Store(config.OUTPUT)
    n = store.write_rights_report()
    summ = store.summary()
    print(json.dumps(summ, indent=2))
    print(f"rights rows: {n}  ->  {store.rights_path}")


def main():
    ap = argparse.ArgumentParser(
        description="Popular Education SA Wayback harvester")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list sources").set_defaults(fn=cmd_list)

    pr = sub.add_parser("run", help="harvest one or more sources")
    pr.add_argument("sources", nargs="+")
    pr.add_argument("--limit", type=int, default=None, help="max items per source")
    pr.add_argument("--no-download", action="store_true", help="catalog only")
    pr.set_defaults(fn=cmd_run)

    pa = sub.add_parser("all", help="harvest every source")
    pa.add_argument("--limit", type=int, default=None)
    pa.add_argument("--no-download", action="store_true")
    pa.set_defaults(fn=cmd_all)

    sub.add_parser("report",
                   help="rebuild rights report + summary").set_defaults(fn=cmd_report)

    args = ap.parse_args()
    _setup_logging(args.verbose)
    args.fn(args)


if __name__ == "__main__":
    main()

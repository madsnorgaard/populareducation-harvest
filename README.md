# populareducation-harvest

Recovers the full content of **populareducation.org.za** (Popular Education
South Africa, "Looking back to go forward together") from the Wayback Machine.
The original Drupal 7 site is offline; this pipeline rebuilds its content as
normalized JSON + media files, consumed by the `pe_migrate` module in the
[populareducation.org.za](https://github.com/madsnorgaard/populareducation.org.za)
Drupal 11 rebuild.

Two archived domains are harvested and merged: `populareducation.org.za`
(captures to Aug 2023) and `populareducation.co.za` (later mirror, captures to
Nov 2025 - wins on conflicts).

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python harvest.py all            # both domains, resumable
.venv/bin/python scripts/merge_and_report.py
```

Useful variants:

```bash
python harvest.py list                     # show sources
python harvest.py run wayback_org --limit 20
python harvest.py all --no-download        # catalog only, no media
python harvest.py report                   # rebuild rights-report.csv
```

## Output

```
output/populareducation/
  cdx/                  cached CDX enumerations + per-domain indexes
  raw/<source>/         fetched snapshot HTML (cache; delete to force refetch)
  items/<source>/*.json one normalized Item per page
  items/merged/*.json   merged corpus - what pe_migrate imports
  media/<aa>/<bb>/      sha256 content-addressed PDFs/MP3s/images
  manifest.jsonl        one row per harvested item
  rights-report.csv     one row per media file
  MISSING-CONTENT.md    what the archive never captured - work through with
                        the project owners, record outcomes in Resolution
```

`output/` is never committed.

## How it works

1. **CDX enumeration** - all captures per domain, cached.
2. **Latest 200 snapshot per URL**, split into pages and assets; URLs that
   never returned 200 feed the missing report.
3. **Raw page fetch** via the `id_` replay suffix (original bytes, no Wayback
   toolbar), ~1 req/s, resumable.
4. **Drupal 7 parsing** - node type from body classes, title, clean body HTML,
   taxonomy terms, attachments, legacy nid/path.
5. **Asset download** - each PDF/MP3/image via its own best snapshot,
   deduplicated by sha256 across both domains.
6. **Merge + report** - one item per legacy path; MISSING-CONTENT.md lists
   every page, document, and image with no successful capture.

Item schema: `peh/schema.py`. Adapter contract: a module in `peh/sources/`
exposing `SLUG`, `LABEL`, `harvest(ctx)`, registered in
`peh/sources/__init__.py`.

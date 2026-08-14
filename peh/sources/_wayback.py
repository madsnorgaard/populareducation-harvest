"""Shared Wayback Machine harvesting for the two archived domains.

Pipeline per domain:
  1. CDX enumeration (cached to output/cdx/<domain>.json)
  2. Latest 200-status snapshot per normalized URL, split into pages / assets
  3. Raw page fetch via the ``id_`` replay suffix (unrewritten HTML), cached
  4. Drupal 7 markup parsing into Item records
Assets referenced by pages are resolved against the domain's asset index; refs
with no successful capture are recorded in ``extra.missing_assets`` and become
rows in MISSING-CONTENT.md.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from urllib.parse import urlsplit, unquote, urljoin

from bs4 import BeautifulSoup

from .. import config
from ..schema import Item, MediaRef, stable_id
from ._base import Ctx, provenance, limited

log = logging.getLogger("peh.wayback")

CDX_API = "https://web.archive.org/cdx/search/cdx"
SITE_TITLE_RE = re.compile(r"\s*\|\s*Popular\s?[Ee]ducation.*$")
FILE_EXT = (".pdf", ".doc", ".docx", ".odt", ".ppt", ".pptx", ".xls", ".xlsx",
            ".mp3", ".wav", ".m4a", ".mp4", ".mov", ".webm", ".zip", ".epub")
IMG_EXT = (".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".webp", ".bmp")
SUBMITTED_RE = re.compile(
    r"on\s+\w{3},\s+(\d{2})/(\d{2})/(\d{4})")   # D7: "on Thu, 10/25/2012 - 21:14"

KIND_MAP = {
    "tools": "tool", "tool": "tool",
    "organisation": "organisation", "organization": "organisation",
    "library": "library_item", "library-item": "library_item",
    "library-items": "library_item",
    "media-gallery": "gallery", "gallery": "gallery",
    "blog": "blog_post", "article": "page", "story": "page",
    "audio": "audio_item", "page": "page",
}


# ---- URL normalization ----------------------------------------------------

def norm_key(url: str) -> str:
    """Host- and scheme-independent key for a URL on the archived site."""
    p = urlsplit(url)
    path = unquote(p.path or "/")
    path = re.sub(r"/{2,}", "/", path)
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return path.lower()


def first_segment(path_key: str) -> str:
    parts = path_key.strip("/").split("/")
    return parts[0] if parts and parts[0] else ""


# ---- CDX ------------------------------------------------------------------

def cdx_rows(ctx: Ctx, domain: str) -> list[list[str]]:
    cache = config.OUTPUT / "cdx" / f"{domain}.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    data = ctx.f.get_json(CDX_API, params={
        "url": domain, "matchType": "domain", "output": "json",
        "fl": "original,timestamp,mimetype,statuscode",
    })
    if not data:
        raise RuntimeError(f"CDX enumeration failed for {domain}")
    rows = data[1:]  # drop header row
    cache.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def build_indexes(rows: list[list[str]], cfg: dict) -> dict:
    """Split CDX rows into page/asset indexes of the latest 200 capture each."""
    excl = tuple(cfg["wayback"]["exclude_prefixes"])
    pages: dict[str, tuple[str, str]] = {}      # key -> (ts, original)
    assets: dict[str, tuple[str, str, str]] = {}  # key -> (ts, original, mime)
    seen_ok: set[str] = set()
    last_status: dict[str, tuple[str, str]] = {}  # key -> (status, original)

    for orig, ts, mime, status in rows:
        p = urlsplit(orig)
        if "?" in orig and mime == "text/html":
            continue                     # pagination/tracking variants
        key = norm_key(orig)
        if status and status.isdigit():
            last_status.setdefault(key, (status, orig))
            if status != "200":
                last_status[key] = (status, orig)
        if status != "200":
            continue
        seen_ok.add(key)
        seg = first_segment(key)
        if mime in ("text/css", "application/javascript", "text/javascript",
                    "application/x-javascript"):
            continue
        is_asset = seg == "sites" or (mime or "").split("/")[0] in (
            "image", "audio", "video") or mime == "application/pdf"
        if is_asset:
            cur = assets.get(key)
            if not cur or ts > cur[0]:
                assets[key] = (ts, orig, mime or "")
        elif mime == "text/html":
            if seg in excl or key.endswith((".css", ".js", ".txt")):
                continue
            cur = pages.get(key)
            if not cur or ts > cur[0]:
                pages[key] = (ts, orig)

    never_ok = {k: v for k, v in last_status.items() if k not in seen_ok}
    return {"pages": pages, "assets": assets, "never_ok": never_ok}


# ---- page fetch (cached) --------------------------------------------------

def fetch_page(ctx: Ctx, slug: str, key: str, ts: str, orig: str) -> str | None:
    cache_dir = config.OUTPUT / "raw" / slug
    cache_dir.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1(key.encode()).hexdigest()[:20]
    cache = cache_dir / f"{name}_{ts}.html"
    if cache.exists():
        return cache.read_text(encoding="utf-8", errors="replace")
    snap = f"https://web.archive.org/web/{ts}id_/{orig}"
    text = ctx.f.get_text(snap, check_robots=False)
    if text is None:
        log.warning("page fetch failed %s", snap)
        return None
    cache.write_text(text, encoding="utf-8")
    return text


# ---- D7 parsing -----------------------------------------------------------

STRIP_SELECTORS = [
    "script", "style", "noscript", "form", "iframe",
    ".comment-wrapper", "#comments", ".comment-form", "ul.links", ".links",
    ".breadcrumb", "#breadcrumbs", ".feed-icon", ".pager", ".action-links",
    "ul.tabs", ".messages", ".contextual-links-wrapper", ".book-navigation",
    ".region-sidebar-first", ".region-sidebar-second", "#sidebar-first",
    "#sidebar-second", ".meta.submitted", ".submitted", ".rdf-meta",
    ".element-invisible", "h1.page-title", "h1#page-title",
]
ICON_HINTS = ("icon", "logo", "avatar", "/misc/", "blank.gif", "spinner",
              "button", "/panels/", "wysiwyg", "/sites/all/themes/",
              "/sites/all/modules/")


def _clean_title(soup: BeautifulSoup) -> str:
    h1 = soup.select_one("h1.page-title, h1#page-title, #post-content h1, "
                         "#content h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    if soup.title and soup.title.string:
        return SITE_TITLE_RE.sub("", soup.title.string).strip()
    return ""


def _content_node(soup: BeautifulSoup):
    for sel in ("#post-content .node", "#content .node",
                ".region-content .node", "#post-content", "#content",
                ".region-content", "#main", "body"):
        node = soup.select_one(sel)
        if node:
            return node
    return soup


def _relativize(url: str) -> str:
    """Turn absolute links to the archived site into site-relative paths."""
    p = urlsplit(url)
    if p.netloc and "populareducation" in p.netloc:
        return p.path + (f"?{p.query}" if p.query else "")
    return url


def parse_page(cfg: dict, slug: str, key: str, ts: str, orig: str, html: str,
               assets: dict) -> Item | None:
    soup = BeautifulSoup(html, "lxml")
    wb = cfg["wayback"]

    body_el = soup.body
    body_classes = (body_el.get("class") or []) if body_el else []
    node_type = next((c[len("node-type-"):] for c in body_classes
                      if c.startswith("node-type-")), None)

    seg = first_segment(key)
    if key in ("/", ""):
        kind = "listing"                 # front page shows a promoted node
    elif node_type:
        kind = KIND_MAP.get(node_type, "page")
    elif seg == "media-gallery":
        kind = "gallery_media"
    elif key in ("/", "") or seg in wb["listing_prefixes"]:
        kind = "listing"
    else:
        kind = "page"

    title = _clean_title(soup)
    if not title:
        return None

    nid = None
    short = soup.find("link", rel="shortlink")
    if short and short.get("href"):
        m = re.search(r"/node/(\d+)", short["href"])
        if m:
            nid = int(m.group(1))

    # date from the D7 submitted line, before it is stripped
    display_date = date_iso = None
    sub = soup.select_one(".submitted")
    if sub:
        m = SUBMITTED_RE.search(sub.get_text(" ", strip=True))
        if m:
            mm, dd, yyyy = m.groups()
            date_iso = f"{yyyy}-{mm}-{dd}"
            display_date = f"{yyyy}-{mm}-{dd}"

    # taxonomy terms + field_active before content cleanup
    subjects = []
    for a in soup.select(".field-type-taxonomy-term-reference a, "
                         ".field-name-field-category a, .terms a"):
        t = a.get_text(strip=True)
        if t and t.lower() not in ("more",) and t not in subjects:
            subjects.append(t)
    extra: dict = {"node_type": node_type}
    active = soup.select_one(".field-name-field-active .field-item")
    if active:
        extra["field_active"] = active.get_text(strip=True)

    content = _content_node(soup)
    for sel in STRIP_SELECTORS:
        for el in content.select(sel):
            el.decompose()

    canonical_page = f"https://www.populareducation.org.za{key}"

    # media refs from the whole document
    images: list[MediaRef] = []
    files: list[MediaRef] = []
    missing: list[dict] = []
    seen: set[str] = set()

    def add_media(raw_url: str, caption: str | None, bucket: str):
        rel = _relativize(urljoin(orig, raw_url))
        if rel.startswith("http"):
            # external media: never in the archive index, keep as hotlink ref
            if rel in seen:
                return
            seen.add(rel)
            ref = MediaRef(url=rel, origin_url=rel, caption=caption or None,
                           hotlink_only=True, rights="review-required",
                           source_url=canonical_page)
            (images if bucket == "image" else files).append(ref)
            return
        akey = norm_key(f"http://x{rel}")
        if akey in seen:
            return
        seen.add(akey)
        hit = assets.get(akey)
        origin = f"https://www.populareducation.org.za{akey}"
        ref = MediaRef(
            url=(f"https://web.archive.org/web/{hit[0]}id_/{hit[1]}"
                 if hit else origin),
            origin_url=origin, caption=caption or None,
            hotlink_only=hit is None,
            rights=wb["rights"], credit=wb["credit"], source_url=canonical_page,
        )
        if hit is None:
            missing.append({"url": akey, "bucket": bucket,
                            "caption": caption or None})
        (images if bucket == "image" else files).append(ref)

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src or src.startswith("data:"):
            continue
        low = src.lower()
        if any(x in low for x in ICON_HINTS):
            continue
        if "/sites/" not in low and not low.endswith(IMG_EXT):
            continue
        add_media(src, (img.get("alt") or img.get("title") or "").strip(),
                  "image")

    internal_links: list[dict] = []
    for a in soup.find_all("a", href=True):
        href = _relativize(urljoin(orig, a["href"]))
        low = href.lower().split("?")[0]
        text = a.get_text(strip=True)
        if low.endswith(FILE_EXT):
            add_media(a["href"], text, "file")
        elif low.endswith(IMG_EXT):
            add_media(a["href"], text, "image")
        elif href.startswith("/") and not href.startswith("//"):
            internal_links.append({"path": norm_key(f"http://x{href}"),
                                   "title": text[:120]})

    # cleaned body HTML with internal links made relative
    for a in content.find_all("a", href=True):
        a["href"] = _relativize(urljoin(orig, a["href"]))
    for img in content.find_all("img"):
        if img.get("src"):
            img["src"] = _relativize(urljoin(orig, img["src"]))
    # attachments are carried as MediaRefs; drop the field wrapper from body
    for el in content.select(".field-name-field-resource-file-attachement"):
        el.decompose()
    # prefer the bare D7 body field over region/block wrappers
    body_field = content.select_one(".field-name-body")
    body_root = body_field if body_field is not None else content
    body_html = "".join(str(c) for c in body_root.children).strip()
    text = re.sub(r"\n{3,}", "\n\n", content.get_text("\n", strip=True))

    extra["internal_links"] = internal_links[:200]
    if missing:
        extra["missing_assets"] = missing

    identifiers = {"legacy_path": key, "wayback_timestamp": ts,
                   "wayback_url": f"https://web.archive.org/web/{ts}/{orig}"}
    if nid:
        identifiers["legacy_nid"] = nid

    return Item(
        source=slug,
        source_id=key.strip("/") or "home",
        source_url=canonical_page,
        title=title,
        kind=kind,
        summary=(text[:280] or None),
        body=body_html,
        display_date=display_date,
        date_iso=date_iso,
        languages=["en"],
        subjects=subjects,
        identifiers=identifiers,
        rights=wb["rights"],
        credit=wb["credit"],
        images=images,
        files=files,
        provenance=provenance(f"wayback:{ts}", query=orig),
        extra=extra,
    )


# ---- adapter entry --------------------------------------------------------

def harvest_domain(ctx: Ctx, slug: str, domain: str):
    cfg = ctx.cfg
    rows = cdx_rows(ctx, domain)
    idx = build_indexes(rows, cfg)
    log.info("%s: %s pages, %s assets, %s never-ok URLs",
             domain, len(idx["pages"]), len(idx["assets"]), len(idx["never_ok"]))

    # side files for merge_and_report.py
    side = config.OUTPUT / "cdx" / f"{domain}-index.json"
    side.write_text(json.dumps({
        "pages": {k: list(v) for k, v in idx["pages"].items()},
        "assets": {k: list(v) for k, v in idx["assets"].items()},
        "never_ok": {k: list(v) for k, v in idx["never_ok"].items()},
    }, indent=1), encoding="utf-8")

    def gen():
        for key in sorted(idx["pages"]):
            ts, orig = idx["pages"][key]
            html = fetch_page(ctx, slug, key, ts, orig)
            if html is None:
                continue
            try:
                item = parse_page(cfg, slug, key, ts, orig, html, idx["assets"])
            except Exception:
                log.exception("parse failed %s", key)
                continue
            if item:
                yield item

    yield from limited(gen(), ctx.limit)

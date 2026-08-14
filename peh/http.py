"""Polite synchronous HTTP with per-host pacing, retry-on-429/5xx, and a
robots.txt gate.
"""
from __future__ import annotations

import logging
import time
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, urlencode, parse_qsl
from urllib.robotparser import RobotFileParser

import httpx

log = logging.getLogger("peh.http")

UA = (
    "PopularEducationRebuildBot/1.0 "
    "(+https://github.com/madsnorgaard/populareducation-harvest; "
    "rebuilding populareducation.org.za from the Internet Archive) httpx"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-ZA,en;q=0.9",
}

# Per-host minimum gap between requests (ms). Generous to stay welcome.
HOST_DELAYS = {
    "archive.org": 1200,
    "web.archive.org": 1200,
}


def canonicalize(url: str) -> str:
    if not url or "?" not in url:
        return url
    p = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
         if not (k.startswith("utm_") or k in ("fbclid", "gclid", "mc_cid", "mc_eid"))]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), p.fragment))


def host_of(url: str) -> str:
    return urlsplit(url).netloc.lower()


def _retry_after(resp: httpx.Response, default: float) -> float:
    ra = resp.headers.get("retry-after", "").strip()
    if not ra:
        return default
    if ra.isdigit():
        return min(120.0, float(ra))
    try:
        target = parsedate_to_datetime(ra)
        return min(120.0, max(1.0, (target - datetime.now(timezone.utc)).total_seconds()))
    except Exception:
        return default


class Fetcher:
    def __init__(self, *, default_delay_ms: int = 800, max_retries: int = 4,
                 timeout: float = 45.0, respect_robots: bool = True,
                 robots_bypass: tuple[str, ...] = ()):
        self.default_delay_ms = default_delay_ms
        self.max_retries = max_retries
        self.respect_robots = respect_robots
        self.robots_bypass = tuple(h.lower() for h in robots_bypass)
        self._last: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self.client = httpx.Client(
            headers=HEADERS, follow_redirects=True, timeout=timeout,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )

    # ---- pacing ----------------------------------------------------------
    def _pace(self, host: str):
        gap = HOST_DELAYS.get(host, self.default_delay_ms) / 1000.0
        last = self._last.get(host)
        if last is not None:
            wait = gap - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last[host] = time.monotonic()

    # ---- robots ----------------------------------------------------------
    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        host = host_of(url)
        if host in self.robots_bypass:
            return True
        rp = self._robots.get(host)
        if rp is None and host not in self._robots:
            rp = RobotFileParser()
            robots_url = f"{urlsplit(url).scheme}://{host}/robots.txt"
            try:
                self._pace(host)
                r = self.client.get(robots_url)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                else:
                    rp = None            # no robots -> allow
            except Exception:
                rp = None
            self._robots[host] = rp
        if rp is None:
            return True
        return rp.can_fetch(UA, url)

    # ---- requests --------------------------------------------------------
    def get(self, url: str, *, params=None, headers=None, check_robots: bool = True):
        url = canonicalize(url)
        if check_robots and not self.allowed(url):
            log.info("robots-disallow %s", url)
            return None
        host = host_of(url)
        attempt = 0
        while True:
            self._pace(host)
            try:
                r = self.client.get(url, params=params, headers=headers)
            except httpx.HTTPError as e:
                attempt += 1
                if attempt > self.max_retries:
                    log.warning("giving up %s: %s", url, e)
                    return None
                time.sleep(min(30.0, 2 ** attempt))
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                attempt += 1
                if attempt > self.max_retries:
                    log.warning("giving up %s after %s (%s)", url, attempt, r.status_code)
                    return r
                time.sleep(_retry_after(r, min(30.0, 2 ** attempt)))
                continue
            return r

    def get_json(self, url: str, *, params=None, headers=None):
        r = self.get(url, params=params, headers=headers, check_robots=False)
        if r is None or r.status_code != 200:
            return None
        try:
            return r.json()
        except Exception:
            return None

    def get_text(self, url: str, *, params=None, check_robots: bool = True):
        r = self.get(url, params=params, check_robots=check_robots)
        if r is None or r.status_code != 200:
            return None
        return r.text

    def stream(self, url: str, *, max_bytes: int):
        """Yield (ok, status, content_bytes_or_none, headers). Caps at max_bytes."""
        url = canonicalize(url)
        host = host_of(url)
        self._pace(host)
        try:
            with self.client.stream("GET", url) as r:
                if r.status_code != 200:
                    return False, r.status_code, None, r.headers
                chunks, total = [], 0
                for chunk in r.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        return False, 200, None, r.headers   # too large
                    chunks.append(chunk)
                return True, 200, b"".join(chunks), r.headers
        except httpx.HTTPError as e:
            log.warning("stream fail %s: %s", url, e)
            return False, 0, None, {}

    def close(self):
        self.client.close()

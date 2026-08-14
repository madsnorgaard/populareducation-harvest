"""Content-addressed media downloading with size caps and rights-aware policy."""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import pathlib
from urllib.parse import urlsplit, unquote

from .http import Fetcher
from .schema import MediaRef

log = logging.getLogger("peh.media")

OPEN_RIGHTS_HINTS = ("cc", "public domain", "pd", "cc0", "cc-by", "creativecommons",
                     "open", "popular education")

EXT_KIND = {
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".gif": "image",
    ".tif": "image", ".tiff": "image", ".webp": "image", ".bmp": "image",
    ".pdf": "pdf", ".mp3": "audio", ".wav": "audio", ".m4a": "audio",
    ".mp4": "video", ".mov": "video", ".webm": "video",
    ".doc": "file", ".docx": "file", ".odt": "file", ".txt": "file",
}


def guess_kind(url: str, mime: str | None) -> str:
    ext = pathlib.Path(urlsplit(url).path).suffix.lower()
    if ext in EXT_KIND:
        return EXT_KIND[ext]
    if mime:
        if mime.startswith("image/"):
            return "image"
        if mime == "application/pdf":
            return "pdf"
        if mime.startswith("audio/"):
            return "audio"
        if mime.startswith("video/"):
            return "video"
    return "file"


def filename_for(url: str, mime: str | None) -> str:
    name = unquote(pathlib.Path(urlsplit(url).path).name) or "file"
    if "." not in name and mime:
        ext = mimetypes.guess_extension(mime.split(";")[0].strip()) or ""
        name += ext
    return name[:150]


def _should_download(m: MediaRef, policy: str) -> bool:
    if m.hotlink_only:
        return False
    if policy == "none":
        return False
    if policy == "all":
        return True
    # policy == "open": only clearly-open or owned material
    r = (m.rights or "").lower()
    return any(h in r for h in OPEN_RIGHTS_HINTS)


class Downloader:
    def __init__(self, fetcher: Fetcher, media_root: pathlib.Path, *,
                 policy: str = "all", max_file_mb: int = 60):
        self.f = fetcher
        self.media_root = media_root
        self.policy = policy
        self.max_bytes = max_file_mb * 1024 * 1024
        self.stats = {"downloaded": 0, "hotlinked": 0, "skipped": 0, "failed": 0,
                      "bytes": 0, "cached": 0}
        self._cache_path = media_root / "url-cache.json"
        try:
            import json as _json
            self._url_cache = _json.loads(self._cache_path.read_text("utf-8"))
        except Exception:
            self._url_cache = {}

    def _cache_put(self, m: MediaRef):
        import json as _json
        self._url_cache[m.url] = {
            "sha256": m.sha256, "mime": m.mime, "size": m.size,
            "local_path": m.local_path, "kind": m.kind,
        }
        self._cache_path.write_text(
            _json.dumps(self._url_cache), encoding="utf-8")

    def fetch(self, m: MediaRef) -> MediaRef:
        m.kind = m.kind or guess_kind(m.url, m.mime)
        if not _should_download(m, self.policy):
            self.stats["hotlinked"] += 1
            return m
        cached = self._url_cache.get(m.url)
        if cached and cached.get("local_path") and \
                (self.media_root.parent / cached["local_path"]).exists():
            m.sha256 = cached["sha256"]
            m.mime = cached["mime"]
            m.size = cached["size"]
            m.local_path = cached["local_path"]
            m.kind = cached.get("kind") or m.kind
            m.downloaded = True
            self.stats["cached"] += 1
            return m
        ok, status, data, headers = self.f.stream(m.url, max_bytes=self.max_bytes)
        if not ok or data is None:
            self.stats["failed" if status else "skipped"] += 1
            log.info("no-download (%s) %s", status, m.url)
            return m
        sha = hashlib.sha256(data).hexdigest()
        mime = (headers.get("content-type") or m.mime or "").split(";")[0].strip() or None
        m.mime = mime
        m.kind = guess_kind(m.url, mime)
        m.sha256 = sha
        m.size = len(data)
        fname = m.filename or filename_for(m.url, mime)
        sub = self.media_root / sha[:2] / sha[2:4]
        sub.mkdir(parents=True, exist_ok=True)
        dest = sub / f"{sha[:16]}_{fname}"
        if not dest.exists():
            dest.write_bytes(data)
        m.local_path = str(dest.relative_to(self.media_root.parent))
        m.downloaded = True
        self.stats["downloaded"] += 1
        self.stats["bytes"] += len(data)
        self._cache_put(m)
        return m

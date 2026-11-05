"""Static serving of the landing site (repo `site/`) from the scan app's origin.

stdlib only. `serve(handler, path)` answers GET/HEAD (public_app routes only those here) for one URL path:
  - resolves under SITE_DIR only (realpath + prefix check; dot-segments and NUL rejected)
  - directory -> index.html (`/scan` -> 301 `/scan/` so relative links resolve)
  - missing -> site/404.html with status 404; never a directory listing
  - html / js / css: `Cache-Control: no-cache` (+ Last-Modified, If-Modified-Since → 304: a deploy reaches returning
    visitors at once, script tags carry no version); other assets: `public, max-age=86400`
  - one `Range: bytes=a-b` → 206 (+ Accept-Ranges): Safari plays <video> only with it, and seeking needs it
Returns False only when SITE_DIR is missing (caller falls back to its own routes).
"""
import email.utils
import os
import re
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.realpath(os.environ.get("SITE_DIR") or os.path.join(HERE, os.pardir, "site"))

TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".xml": "application/xml; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".woff2": "font/woff2",
    ".webmanifest": "application/manifest+json",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}

_warned = False


def enabled():
    global _warned
    if os.path.isdir(SITE_DIR):
        return True
    if not _warned:
        _warned = True
        print(f"[site_static] SITE_DIR {SITE_DIR} missing: landing site disabled", file=sys.stderr, flush=True)
    return False


def _resolve(path):
    """URL path -> absolute file under SITE_DIR, a redirect target, or None (404)."""
    rel = urllib.parse.unquote(path)
    if "\x00" in rel or "\\" in rel:
        return None, None
    parts = [p for p in rel.split("/") if p]
    if any(p.startswith(".") for p in parts):  # .., ., dotfiles (.env, .git)
        return None, None
    full = os.path.realpath(os.path.join(SITE_DIR, *parts))
    if not (full == SITE_DIR or full.startswith(SITE_DIR + os.sep)):
        return None, None
    if os.path.isdir(full):
        if not path.endswith("/"):
            return None, path + "/"
        full = os.path.join(full, "index.html")
    return (full if os.path.isfile(full) else None), None


def _range(h, size):
    """(start, end) for one satisfiable `bytes=` range, False if unsatisfiable, None for a full response."""
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", (h.headers.get("Range") or "").strip())
    if not m or not (m[1] or m[2]):
        return None
    if m[1]:
        start, end = int(m[1]), min(int(m[2]) if m[2] else size - 1, size - 1)
    else:
        start, end = max(0, size - int(m[2])), size - 1
    return (start, end) if start <= end and start < size else False


def _send(h, code, full, cache):
    ctype = TYPES.get(os.path.splitext(full)[1].lower(), "application/octet-stream")
    size, mtime = os.path.getsize(full), int(os.path.getmtime(full))
    try:
        since = email.utils.parsedate_to_datetime(h.headers.get("If-Modified-Since")).timestamp()
    except (TypeError, ValueError, IndexError):
        since = None
    if code == 200 and since is not None and mtime <= since:
        return _plain(h, 304, "", {"Cache-Control": cache, "Last-Modified": email.utils.formatdate(mtime, usegmt=True)})
    rng = _range(h, size) if code == 200 else None
    if rng is False:
        return _plain(h, 416, "Range not satisfiable", {"Content-Range": f"bytes */{size}"})
    start, end = rng or (0, size - 1)
    try:
        h.send_response(206 if rng else code)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(end - start + 1))
        if code == 200:
            h.send_header("Accept-Ranges", "bytes")
        if rng:
            h.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        h.send_header("Cache-Control", cache)
        h.send_header("Last-Modified", email.utils.formatdate(mtime, usegmt=True))
        h.send_header("X-Content-Type-Options", "nosniff")
        h.end_headers()
        if h.command != "HEAD":
            with open(full, "rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    buf = fh.read(min(65536, left))
                    if not buf:
                        break
                    h.wfile.write(buf)
                    left -= len(buf)
    except (BrokenPipeError, ConnectionResetError):
        pass


def _plain(h, code, msg, extra=None):
    body = msg.encode("utf-8")
    try:
        h.send_response(code)
        h.send_header("Content-Type", "text/plain; charset=utf-8")
        h.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            h.send_header(k, v)
        h.end_headers()
        if h.command != "HEAD":
            h.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        pass


def serve(h, path):
    if not enabled():
        return False
    full, redirect = _resolve(path)
    if redirect:
        q = urllib.parse.urlsplit(h.path).query
        _plain(h, 301, "Moved", {"Location": redirect + ("?" + q if q else "")})
    elif full:
        _send(h, 200, full, "no-cache" if full.endswith((".html", ".js", ".css")) else "public, max-age=86400")
    elif os.path.isfile(os.path.join(SITE_DIR, "404.html")):
        _send(h, 404, os.path.join(SITE_DIR, "404.html"), "no-cache")
    else:
        _plain(h, 404, "Not found")
    return True

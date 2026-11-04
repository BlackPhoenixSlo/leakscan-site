"""Static serving of the landing site (repo `site/`) from the scan app's origin.

stdlib only. `serve(handler, path)` answers GET/HEAD (public_app routes only those here) for one URL path:
  - resolves under SITE_DIR only (realpath + prefix check; dot-segments and NUL rejected)
  - directory -> index.html (`/scan` -> 301 `/scan/` so relative links resolve)
  - missing -> site/404.html with status 404; never a directory listing
  - html: `Cache-Control: no-cache`; assets: `public, max-age=86400`
Returns False only when SITE_DIR is missing (caller falls back to its own routes).
"""
import os
import shutil
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


def _send(h, code, full, cache):
    ctype = TYPES.get(os.path.splitext(full)[1].lower(), "application/octet-stream")
    try:
        h.send_response(code)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(os.path.getsize(full)))
        h.send_header("Cache-Control", cache)
        h.send_header("X-Content-Type-Options", "nosniff")
        h.end_headers()
        if h.command != "HEAD":
            with open(full, "rb") as fh:
                shutil.copyfileobj(fh, h.wfile, length=65536)
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
        html = full.endswith(".html")
        _send(h, 200, full, "no-cache" if html else "public, max-age=86400")
    elif os.path.isfile(os.path.join(SITE_DIR, "404.html")):
        _send(h, 404, os.path.join(SITE_DIR, "404.html"), "no-cache")
    else:
        _plain(h, 404, "Not found")
    return True

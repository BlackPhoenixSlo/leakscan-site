"""One file for a saved report's thumbs: GET /api/thumb-sheet/<slug> replaces its dozens of /api/thumb requests.

Body: 8 ASCII digits = the manifest's length, the manifest JSON {"cells": [[src, content type, bytes], ...], "dead": [src, ...]},
then every cell's bytes back to back, in manifest order. The bytes are the thumbs' originals (no re-encode): site/js/scan-engine.js
makes one blob URL per cell, so what E.isPhoto reads is what /api/thumb would have given.

dead: what /api/thumb would refuse for good (upstream 4xx or redirect, not an image). A thumb in neither list (upstream 5xx / timeout,
too big for a cell, past the caps) goes through /api/thumb in the client. Own bucket; upstream fetches share one bounded pool; one build
per list at a time, the rest wait for it; built sheets sit on disk under a size and age bound (one with gaps only briefly): sweep(),
from every write and public_app.run_retention. A complete sheet's mtime is its row's created_at, so it goes with the row's photos."""
import calendar
import concurrent.futures as cf
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import db
import ratelimit
import web_common as wc

MAX_CELLS = int(os.environ.get("THUMB_SHEET_MAX_CELLS", "120"))
MAX_CELL_BYTES = int(os.environ.get("THUMB_SHEET_MAX_CELL_BYTES", "500000"))
MAX_BYTES = int(os.environ.get("THUMB_SHEET_MAX_BYTES", "4000000"))
POOL = int(os.environ.get("THUMB_SHEET_POOL", "8"))
BUILD_S = float(os.environ.get("THUMB_SHEET_BUILD_S", "12"))   # then what came is the sheet; the rest stays per-thumb
FULL_S, GAPS_S = db.RETAIN_BIG_DAYS * 86400, 300               # how long a sheet is served: complete (by its row's age), with gaps
CACHE_MAX_BYTES = int(os.environ.get("THUMB_SHEET_CACHE_BYTES", "500000000"))

LIMITER = ratelimit.Limiter(rate_per_min=30, burst=20, max_concurrent=1000)
_pool = cf.ThreadPoolExecutor(POOL, thread_name_prefix="thumb-sheet")
_lock = threading.Lock()
_flights = {}


def thumbs_of(row, hosts):
    """The thumbs the client would ask /api/thumb for, in its order (E.imageItems: images[], then results' thumbs), up to MAX_CELLS."""
    results = row.get("results") or [] if row.get("level", "low") == "low" else []   # api_scan_result: only low scans have results
    out = {}
    for u in list(row.get("images") or [])[:200] + [r.get("thumb") for r in results[:200] if isinstance(r, dict)]:
        if isinstance(u, str) and len(u) <= 600 and u not in out:
            p = urllib.parse.urlparse(u)
            h = (p.hostname or "").lower()
            if p.scheme == "https" and any(h == x or h.endswith("." + x) for x in hosts):
                out[u] = 1
    return list(out)[:MAX_CELLS]


def fetch(u, opener, max_bytes):
    """api_thumb's upstream fetch → (ctype, bytes), "dead" or None (not known dead: try again later; too big for a cell: /api/thumb has its own limit)."""
    limit = min(max_bytes, MAX_CELL_BYTES)
    try:
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*"})
        with opener.open(req, timeout=8) as r:
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if not ctype.startswith("image/"):
                return "dead"
            data = r.read(limit + 1)
    except urllib.error.HTTPError as e:
        return None if e.code >= 500 or e.code == 429 else "dead"
    except Exception:
        return None
    return None if len(data) > limit else (ctype, data)


def pack(cells, dead):
    """cells [(src, ctype, bytes)], dead [src] → the response body."""
    head = json.dumps({"cells": [[s, t, len(d)] for s, t, d in cells], "dead": dead}, separators=(",", ":")).encode()
    return b"%08d" % len(head) + head + b"".join(d for _, _, d in cells)


def _build(urls, opener, max_bytes):
    """→ (body, complete: every thumb of urls has its answer)."""
    futs = [_pool.submit(fetch, u, opener, max_bytes) for u in urls]
    cf.wait(futs, timeout=BUILD_S)
    cells, dead, total, complete = [], [], 0, True
    for u, f in zip(urls, futs):
        got = f.result() if f.done() and not f.cancelled() else None
        f.cancel()
        if got == "dead":
            dead.append(u)
        elif got is None:
            complete = False
        elif total + len(got[1]) <= MAX_BYTES:
            cells.append((u, got[0], got[1]))
            total += len(got[1])
    return pack(cells, dead), complete


def cache_dir():
    return os.path.join(os.environ.get("DATA_DIR") or os.path.dirname(os.path.abspath(db.DB_PATH)), "thumb-sheets")


def _read(key):
    for ext, ttl in ((".full", FULL_S), (".gaps", GAPS_S)):
        p = os.path.join(cache_dir(), key + ext)
        try:
            if time.time() - os.path.getmtime(p) < ttl:
                with open(p, "rb") as f:
                    return f.read(), ext == ".full"
        except OSError:
            pass
    return None


def _write(key, body, complete, born=None):
    d = cache_dir()
    try:
        os.makedirs(d, exist_ok=True)
        tmp = os.path.join(d, f"{key}.{threading.get_ident()}.tmp")
        with open(tmp, "wb") as f:
            f.write(body)
        final = os.path.join(d, key + (".full" if complete else ".gaps"))
        os.replace(tmp, final)
        if complete and born:
            os.utime(final, (born, born))
    except OSError:
        pass   # a full or read-only disk: served from memory, built again next time
    sweep()


def sweep():
    """Past its age: gone; then the oldest down to the size bound -> files removed. Never raises: a file another thread replaced or
    removed meanwhile is skipped (a build's body is in its memory: that request still gets it, the next one builds again)."""
    d, now, n, files = cache_dir(), time.time(), 0, []
    try:
        names = os.listdir(d)
    except OSError:
        return 0
    for name in names:
        p = os.path.join(d, name)
        try:
            st = os.stat(p)
            if now - st.st_mtime > (GAPS_S if name.endswith((".gaps", ".tmp")) else FULL_S):
                os.remove(p)
                n += 1
            else:
                files.append((st.st_mtime, st.st_size, p))
        except OSError:
            pass
    over = sum(f[1] for f in files) - CACHE_MAX_BYTES
    for _, size, p in sorted(files):   # oldest first
        if over <= 0:
            break
        try:
            os.remove(p)
            n += 1
        except OSError:
            pass
        over -= size
    return n


class _Flight:
    def __init__(self):
        self.done, self.result = threading.Event(), None


def sheet(urls, opener, max_bytes, born=None):
    """→ (body, complete), or None: another request's build did not end in time. One build per list at a time. born: its row's created_at, epoch."""
    key = hashlib.sha256("\n".join(urls).encode()).hexdigest()
    hit = _read(key)
    if hit:
        return hit
    with _lock:
        fl = _flights.get(key)
        mine = fl is None
        if mine:
            fl = _flights[key] = _Flight()
    if not mine:
        fl.done.wait(BUILD_S + 10)
        return fl.result
    try:
        fl.result = _read(key)   # a build that ended between the read and the lock
        if not fl.result:
            fl.result = _build(urls, opener, max_bytes)
            _write(key, *fl.result, born)
        return fl.result
    finally:
        with _lock:
            del _flights[key]
        fl.done.set()


def _born(row):
    """A row's created_at → epoch, None if it has none."""
    try:
        return calendar.timegm(time.strptime(row["created_at"], "%Y-%m-%dT%H:%M:%SZ"))
    except (KeyError, TypeError, ValueError):
        return None


def serve(h, slug, scan_row, opener, hosts, max_bytes):
    """h: the request's public_app.Handler. No sheet (404, 429, 503) = the client's per-thumb path, same as an old server."""
    if not LIMITER.allow(wc.client_ip(h), concurrency=False):
        return h._json({"error": "rate_limited"}, 429)
    row = scan_row(slug) if db.SLUG_RE.match(slug) else None
    urls = thumbs_of(row, hosts) if row and row["status"] != "running" else []
    born = _born(row) if row else None
    if not urls or (born and time.time() - born >= FULL_S):   # past big, its retention run still to come: no new file for it
        return h._json({"error": "not_found"}, 404)
    got = sheet(urls, opener, max_bytes, born)
    if not got:
        return h._json({"error": "busy"}, 503)
    body, complete = got
    h.send_response(200)
    h.send_header("Content-Type", "application/octet-stream")
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Cache-Control", f"public, max-age={86400 if complete else GAPS_S}")
    h.send_header("X-Content-Type-Options", "nosniff")
    h.send_header("X-Robots-Tag", "noindex, nofollow")
    h.send_header("Referrer-Policy", "no-referrer")
    if not h._cors_origin():   # as api_thumb: end_headers adds it for an allowed origin
        h.send_header("Vary", "Origin")
    h.end_headers()
    try:
        h.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        pass

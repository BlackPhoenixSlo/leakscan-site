"""Quick-scan SFW media: a few NON-nude photos of the creator for the landing's mock
"official website", gathered in a background thread after a quick scan's DB insert.

Sources (official only, every byte from an official CDN host, nothing from the scan's
leak results), in this order:
  (a) Instagram profile embed page (instagram.com/<handle>/embed/, anonymous, no browser):
      latest posts' image URLs from its server-rendered contextJSON;
  (b) Google image search, SafeSearch on (safe=active), restricted to the creator's
      official-account sites — up to GOOGLE_QUERIES CSE calls, ONLY with GOOGLE_CSE_ID_WEB
      (a whole-web engine; the leak-only GOOGLE_CSE_ID never returns official photos);
  (c) fallback: the public Instagram post grid via ONE Browserbase session (only when (a)
      added < BB_FALLBACK_BELOW images and a gather slot is free).
SFW limitation: there is NO NSFW classifier. Safety relies on Instagram/TikTok/YouTube/X
content policy + Google SafeSearch + official-source-only.

Layout: <DATA_DIR>/media/<slug>/{index.json, 0.jpg, 1.jpg..}; per-handle cache
<DATA_DIR>/media-cache/<platform>-<handle>.json (7 days) points at an earlier slug's files.
`playwright` and Pillow are imported lazily: the app runs without them (gather -> fewer/no images).
"""
import hashlib
import html
import io
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

import cse_scanner
import db
from netloc import registrable_domain


def _flag(name, default):
    return os.environ.get(name, default).lower() in ("1", "true", "yes")


MEDIA_ENABLED = _flag("MEDIA_ENABLED", "1")
MEDIA_BROWSERBASE = _flag("MEDIA_BROWSERBASE", "1")
MEDIA_BUDGET = float(os.environ.get("MEDIA_BUDGET", "90"))
MEDIA_MAX = max(1, min(int(os.environ.get("MEDIA_MAX", "12")), 12))
# Residential proxies ON by default: without them Instagram serves the login wall to
# Browserbase's datacenter IPs (0 images after ~19s, a billed session wasted); with them 12
# grid images in ~11s (measured 2026-11-04). Proxy bandwidth is billed extra, but the
# session only runs as the fallback when the free embed step comes up short.
BB_PROXIES = _flag("BROWSERBASE_PROXIES", "1")
# "" -> relative src ("/api/media/<slug>/<n>.jpg"); unset -> the VPS origin.
PUBLIC_ORIGIN = os.environ.get("PUBLIC_ORIGIN", "https://scan.srv1395798.hstgr.cloud").rstrip("/")
BB_API = "https://api.browserbase.com/v1"
MAX_GATHERS = 2               # concurrent full gathers (Browserbase); when busy -> Google step only
CACHE_TTL = 7 * 86400
GOOGLE_QUERIES = 2
MIN_SIDE, MAX_SIDE, MAX_BYTES = 200, 1200, 300 * 1024
FETCH_CAP = 8 * 1024 * 1024
FETCH_TIMEOUT = 8
IG_GRID_WAIT_MS = 15000
IG_EMBED_TIMEOUT = 10
IG_EMBED_CAP = 2 * 1024 * 1024
BB_FALLBACK_BELOW = 4         # Browserbase only when the embed step added fewer images
HANDLE_RE = re.compile(r"^[A-Za-z0-9._-]{1,60}$")
SLUG_RE = db.SLUG_RE
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

# Official-account sites (Google step: query restriction + accepted page context).
OFFICIAL_SITES = ("instagram.com", "tiktok.com", "youtube.com", "x.com")
_NOT_LEAK = frozenset(OFFICIAL_SITES + ("twitter.com", "youtu.be"))
# Official image CDNs: the ONLY hosts image bytes are ever fetched from.
# lookaside.instagram.com = IG's Google-images crawler endpoint; twimg.com = x.com media.
_CDN_RE = re.compile(r"(?:^|\.)(?:cdninstagram\.com|fbcdn\.net|tiktokcdn(?:-[a-z]{2})?\.com|"
                     r"ytimg\.com|twimg\.com|lookaside\.instagram\.com)$")
GRID_SEL = 'main a[href*="/p/"] img, main a[href*="/reel/"] img'
# Embed page fetch: with a bare desktop-Chrome UA Instagram returns a ~500 KB JS app shell
# with NO posts; with the fetch metadata a browser sends when loading the embed iframe it
# returns the server-rendered page whose contextJSON holds the latest posts (measured).
_EMBED_HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml",
                  "Accept-Language": "en-US,en;q=0.9", "Sec-Fetch-Mode": "navigate",
                  "Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "cross-site"}
# IG profile-picture renditions: "-19" image category in the path, 150px stp, explicit name.
_PROFILE_PIC_RE = re.compile(r"/t51\.\d+-19/|s150x150|profile_pic", re.I)

log = lambda msg: (sys.stderr.write(msg + "\n"), sys.stderr.flush())   # public_app sets _event

_LOCK = threading.Lock()
_RUNNING = set()
_SEM = threading.BoundedSemaphore(MAX_GATHERS)


# ── paths / index ────────────────────────────────────────────────────────────
def data_dir():
    return os.environ.get("DATA_DIR") or os.path.dirname(os.path.abspath(db.DB_PATH))


def media_dir(slug):
    return os.path.join(data_dir(), "media", slug)


def _atomic_write(path, data):
    tmp = f"{path}.{threading.get_ident()}.tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def _write_index(slug, status, images):
    d = media_dir(slug)
    os.makedirs(d, exist_ok=True)
    obj = {"slug": slug, "status": status, "images": images, "updated_at": int(time.time())}
    _atomic_write(os.path.join(d, "index.json"), json.dumps(obj).encode())


def _read_index(slug):
    try:
        with open(os.path.join(media_dir(slug), "index.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def public_view(slug):
    """-> {slug, status, images:[{src,w,h,source}], updated_at}. Slug must be SLUG_RE-valid."""
    idx = _read_index(slug) if MEDIA_ENABLED else None
    if not idx:
        return {"slug": slug, "status": "none", "images": [], "updated_at": None}
    imgs, status = idx.get("images") or [], idx.get("status")
    with _LOCK:
        running = slug in _RUNNING
    if status == "pending" and not running and time.time() - (idx.get("updated_at") or 0) > MEDIA_BUDGET + 60:
        status = None                      # orphaned by a restart: settle with what's on disk
    if status not in ("pending", "ready", "none"):
        status = "ready" if imgs else "none"
    order = sorted(imgs, key=lambda i: i.get("source") != "instagram")    # IG grid first
    return {"slug": slug, "status": status, "updated_at": idx.get("updated_at"),
            "images": [{"src": f"{PUBLIC_ORIGIN}/api/media/{slug}/{i['n']}.jpg", "w": i["w"],
                        "h": i["h"], "source": i["source"]} for i in order]}


def image_path(slug, n):
    """Existing jpg for a valid slug + index, else None."""
    if not SLUG_RE.match(slug or "") or not isinstance(n, int) or not 0 <= n < MEDIA_MAX:
        return None
    p = os.path.join(media_dir(slug), f"{n}.jpg")
    return p if os.path.isfile(p) else None


# ── host policy ──────────────────────────────────────────────────────────────
def official_cdn(host):
    return bool(host) and bool(_CDN_RE.search(host.lower()))


def official_url(url):
    try:
        u = urlparse(url or "")
    except ValueError:
        return False
    return u.scheme == "https" and official_cdn(u.hostname or "")


def _leak_sets(items):
    """URLs and registrable domains of the scan's own results (never used as media)."""
    urls, doms = set(), set()
    for it in items or []:
        for k in ("link", "image", "full"):
            if it.get(k):
                urls.add(it[k])
        d = registrable_domain(it.get("host") or it.get("link") or "")
        if d and d not in _NOT_LEAK and not official_cdn(d):
            doms.add(d)
    return urls, doms


def google_ok(item, leak):
    """Image host must be an official CDN; page context must not be one of the scan's leak
    domains. (Context on an official site OR official-CDN image is the spec's acceptance; the
    'official CDN only' byte rule makes the CDN check mandatory.)"""
    urls, doms = leak
    img = item.get("full") or ""
    if not official_url(img) or img in urls:
        return False
    return registrable_domain(item.get("host") or "") not in doms


# ── fetch + normalize ───────────────────────────────────────────────────────
class _OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, newurl) if official_url(newurl) else None


urlopen = urllib.request.build_opener(_OfficialRedirect).open   # tests patch this (CDN wire)


def fetch_image(url, timeout=FETCH_TIMEOUT):
    if not official_url(url):
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/*"})
        with urlopen(req, timeout=timeout) as r:
            if (getattr(r, "status", None) or r.getcode()) != 200:
                return None
            if not (r.headers.get("Content-Type") or "").lower().startswith("image/"):
                return None
            data = r.read(FETCH_CAP + 1)
        return data if 0 < len(data) <= FETCH_CAP else None
    except Exception:
        return None


def normalize(data):
    """-> (jpeg_bytes, w, h) | None. RGB JPEG, EXIF/ICC stripped, max side MAX_SIDE,
    <= MAX_BYTES, min side MIN_SIDE."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(data)) as src:
            if src.format not in ("JPEG", "PNG", "WEBP") or min(src.size) < MIN_SIDE:
                return None
            if src.size[0] * src.size[1] > 40_000_000:
                return None
            im = ImageOps.exif_transpose(src)
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
            while min(im.size) >= MIN_SIDE:
                for q in (85, 75, 65, 55):
                    buf = io.BytesIO()
                    im.save(buf, "JPEG", quality=q, optimize=True)   # no exif=/icc_profile= -> stripped
                    if buf.tell() <= MAX_BYTES:
                        return buf.getvalue(), im.size[0], im.size[1]
                im = im.resize((int(im.size[0] * 0.8), int(im.size[1] * 0.8)), Image.LANCZOS)
    except Exception:
        return None
    return None


class _Gallery:
    """Accumulates normalized images for one slug; every add rewrites index.json (pending)."""

    def __init__(self, slug):
        self.slug, self.images, self.shas = slug, [], set()
        self.dir = media_dir(slug)

    @property
    def full(self):
        return len(self.images) >= MEDIA_MAX

    def add(self, data, source):
        if self.full or not data:
            return False
        raw = hashlib.sha1(data).hexdigest()
        if raw in self.shas:
            return False
        self.shas.add(raw)
        norm = normalize(data)
        if not norm:
            return False
        jpeg, w, h = norm
        sha = hashlib.sha1(jpeg).hexdigest()
        if sha in self.shas:
            return False
        self.shas.add(sha)
        n = len(self.images)
        os.makedirs(self.dir, exist_ok=True)
        _atomic_write(os.path.join(self.dir, f"{n}.jpg"), jpeg)
        self.images.append({"n": n, "w": w, "h": h, "source": source, "sha1": sha})
        _write_index(self.slug, "pending", self.images)
        return True

    def from_cache(self, key):
        c = _cache_load(key)
        if c is None:
            return False
        src = media_dir(c["slug"])
        os.makedirs(self.dir, exist_ok=True)
        for i in c["images"]:
            s, d = os.path.join(src, f"{i['n']}.jpg"), os.path.join(self.dir, f"{i['n']}.jpg")
            if not os.path.isfile(s):
                self.images = []
                return False
            try:
                if os.path.exists(d):
                    os.remove(d)
                os.link(s, d)
            except OSError:
                shutil.copyfile(s, d)
            self.images.append(i)
        return True

    def finish(self):
        _write_index(self.slug, "ready" if self.images else "none", self.images)


# ── per-handle cache ────────────────────────────────────────────────────────
def cache_key(platform, handle):
    plat = re.sub(r"[^a-z0-9]", "", (platform or "").split(".")[0].lower()) or "web"
    return f"{plat}-{handle.lower()}"


def _cache_path(key):
    return os.path.join(data_dir(), "media-cache", key + ".json")


def _cache_load(key):
    try:
        with open(_cache_path(key), encoding="utf-8") as fh:
            c = json.load(fh)
        if time.time() - float(c["ts"]) > CACHE_TTL or not SLUG_RE.match(c["slug"]):
            return None
        return c
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _cache_save(key, slug, images):
    try:
        os.makedirs(os.path.dirname(_cache_path(key)), exist_ok=True)
        _atomic_write(_cache_path(key), json.dumps({"ts": time.time(), "slug": slug,
                                                    "images": images}).encode())
    except OSError as e:
        log(f"media cache save failed: {type(e).__name__}")


# ── Google (CSE image search, SafeSearch) ───────────────────────────────────
def google_queries(handle, profile):
    sites = " OR ".join(f"site:{d}" for d in OFFICIAL_SITES)
    qs = [f"{handle} {sites}"]
    name = ((profile or {}).get("display_name") or "").strip()
    if name and len(name) <= 60 and name.lower() != handle.lower() and '"' not in name:
        qs.append(f'"{name}" {sites}')
    return qs[:GOOGLE_QUERIES]


def google_images(handle, profile, leak, timeout=FETCH_TIMEOUT):
    """-> accepted official-CDN image URLs (deduped). <= GOOGLE_QUERIES CSE calls, whole-web
    engine GOOGLE_CSE_ID_WEB only (never the leak-domain GOOGLE_CSE_ID)."""
    key, cx = os.environ.get("GOOGLE_API_KEY", ""), os.environ.get("GOOGLE_CSE_ID_WEB", "")
    if not key or not cx:
        log("media google skipped: GOOGLE_CSE_ID_WEB/GOOGLE_API_KEY unset")
        return []
    out, seen = [], set()
    for q in google_queries(handle, profile):
        try:
            d = cse_scanner._call(q, key, cx, timeout=timeout, search_type="image", safe="active")
        except Exception as e:
            log(f"media google failed: {type(e).__name__}")
            continue
        for it in cse_scanner._parse_image_items(d):
            u = it.get("full")
            if u not in seen and google_ok(it, leak):
                seen.add(u)
                out.append(u)
    return out


def ig_handle(platform, handle, profile):
    for a in (profile or {}).get("accounts") or []:
        if isinstance(a, dict) and a.get("platform") == "instagram" and HANDLE_RE.match(a.get("handle") or ""):
            return a["handle"]
    return handle if platform == "instagram.com" and HANDLE_RE.match(handle or "") else None


def _strip_q(u):
    return (u or "").split("?", 1)[0]


def is_profile_pic(url):
    return bool(_PROFILE_PIC_RE.search(url or ""))


def pick_grid(items, og_image=None, cap=MEDIA_MAX):
    """Grid <img> dicts {src,w,h} -> <= cap official-CDN srcs; drops og:image/avatar and <MIN_SIDE."""
    og, out = _strip_q(og_image), []
    for it in items or []:
        src = (it or {}).get("src") or ""
        if not official_url(src) or src in out or (og and _strip_q(src) == og):
            continue
        if is_profile_pic(src):
            continue
        if (it.get("w") or 0) < MIN_SIDE or (it.get("h") or 0) < MIN_SIDE:
            continue
        out.append(src)
    return out[:cap]


# ── Instagram grid via the public profile embed page (no browser) ──────────
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None                          # login redirect -> HTTPError 3xx -> "not found"


page_open = urllib.request.build_opener(_NoRedirect).open   # tests patch this (instagram.com wire)
_CTX_KEY = '"contextJSON":'
_IMG_SRC_RE = re.compile(r'<img\b[^>]*?\bsrc="(https://[^"]+)"', re.I)
_OG_RE = re.compile(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', re.I)


def _embed_candidates(page):
    """-> (image URLs in page order, avatar URL|None). Server-rendered contextJSON: post tiles
    then their carousel children; else plain <img> tiles (HTML-rendered variant)."""
    i = page.find(_CTX_KEY)
    if i < 0:
        og = _OG_RE.search(page)
        return _IMG_SRC_RE.findall(page), og.group(1) if og else None
    try:
        raw = json.JSONDecoder().raw_decode(page, i + len(_CTX_KEY))[0]
        ctx = json.loads(raw)["context"] if isinstance(raw, str) else None   # null = login/Sorry shell
        posts = [m["shortcode_media"] for m in ctx.get("graphql_media") or []] if ctx else []
        urls = [p.get("display_url") for p in posts]
        urls += [e["node"].get("display_url") for p in posts
                 for e in (p.get("edge_sidecar_to_children") or {}).get("edges") or []]
        return [u for u in urls if isinstance(u, str)], ctx.get("profile_pic_url") if ctx else None
    except (ValueError, KeyError, TypeError, AttributeError):
        return [], None


def parse_embed(page, cap=MEDIA_MAX):
    """Embed page HTML -> <= cap official-CDN grid image URLs: avatar dropped, &amp; unescaped,
    deduped by path (query ignored), page order kept."""
    cands, avatar = _embed_candidates(page or "")
    av, out, seen = _strip_q(html.unescape(avatar or "")), [], set()
    for u in cands:
        u = html.unescape(u)
        p = _strip_q(u)
        if not official_url(u) or p in seen or p == av or is_profile_pic(u):
            continue
        seen.add(p)
        out.append(u)
    return out[:cap]


def ig_embed_grid(handle, timeout=IG_EMBED_TIMEOUT):
    """GET instagram.com/<handle>/embed/ -> grid image URLs. [] = not found (login/"Sorry" shell,
    no posts, 3xx/404). Transport errors raise (caller: transient, don't cache)."""
    if not HANDLE_RE.match(handle or ""):
        return []
    req = urllib.request.Request(f"https://www.instagram.com/{handle}/embed/", headers=_EMBED_HEADERS)
    try:
        with page_open(req, timeout=timeout) as r:
            page = r.read(IG_EMBED_CAP + 1)
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400 or e.code == 404:
            log(f"media ig embed not found: http {e.code}")
            return []
        raise
    if len(page) > IG_EMBED_CAP:
        log("media ig embed not found: page over cap")
        return []
    urls = parse_embed(page.decode("utf-8", "replace"))
    if not urls:
        log("media ig embed not found")
    return urls


# ── Instagram grid via Browserbase (fallback) ───────────────────────────────
_GRID_JS = """async (sel) => {
  const t0 = Date.now();
  const imgs = () => Array.from(document.querySelectorAll(sel));
  while (Date.now() - t0 < 5000 && !imgs().slice(0, 12).every(i => i.complete && i.naturalWidth)) {
    await new Promise(r => setTimeout(r, 250));
  }
  const og = document.querySelector('meta[property="og:image"]');
  return {og: og ? og.content : null,
          items: imgs().map(e => ({src: e.currentSrc || e.src, w: e.naturalWidth, h: e.naturalHeight}))};
}"""


def grid_from_cdp(connect_url, handle, deadline):
    """Connect to a CDP browser, open the public IG profile, return grid image bytes."""
    from playwright.sync_api import sync_playwright
    ms = lambda cap: max(1000, min(cap, int((deadline - time.monotonic()) * 1000)))
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(connect_url, timeout=ms(15000))
        try:
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            resp = {}
            page.on("response", lambda r: resp.setdefault(r.url, r)
                    if r.request.resource_type == "image" else None)
            page.goto(f"https://www.instagram.com/{handle}/", wait_until="domcontentloaded",
                      timeout=ms(30000))
            try:
                page.wait_for_selector(GRID_SEL, timeout=ms(IG_GRID_WAIT_MS))
            except Exception:
                log("media ig grid not found")
                return []
            got = page.evaluate(_GRID_JS, GRID_SEL)
            out = []
            for src in pick_grid(got.get("items"), got.get("og")):
                data = None
                if src in resp:
                    try:
                        data = resp[src].body()
                    except Exception:
                        data = None
                out.append(data or fetch_image(src))
            return [d for d in out if d]
        finally:
            try:
                browser.close()
            except Exception:
                pass


def _bb(method, path, key, body, timeout=15):
    req = urllib.request.Request(BB_API + path, data=json.dumps(body).encode(), method=method,
                                 headers={"X-BB-API-Key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def _bb_create(key, proj, timeout, deadline):
    body = {"projectId": proj, "browserSettings": {"solveCaptchas": True}, "timeout": timeout}
    if BB_PROXIES:
        body["proxies"] = True
    for attempt in (0, 1):
        try:
            d = _bb("POST", "/sessions", key, body)
            return {"id": d["id"], "connectUrl": d["connectUrl"]}
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:   # 25 creates/min shared with other tools: retry once
                try:
                    wait = float(e.headers.get("Retry-After") or 10)
                except ValueError:
                    wait = 10.0
                wait = min(wait, deadline - time.monotonic() - 30)
                if wait >= 0:
                    time.sleep(wait)
                    continue
            log(f"media browserbase create failed: {e.code}")
            return None
        except Exception as e:
            log(f"media browserbase create failed: {type(e).__name__}")
            return None
    return None


def _bb_release(key, proj, sid):
    for _ in range(2):
        try:
            _bb("POST", f"/sessions/{sid}", key, {"projectId": proj, "status": "REQUEST_RELEASE"})
            return True
        except Exception:
            pass
    log("media browserbase release failed")
    return False


def grab_ig_grid(handle, budget):
    """ONE Browserbase session -> public IG profile grid -> list of image bytes. [] on any failure."""
    key, proj = os.environ.get("BROWSERBASE_API_KEY", ""), os.environ.get("BROWSERBASE_PROJECT_ID", "")
    if not key or not proj or not HANDLE_RE.match(handle or ""):
        return []
    try:
        import playwright.sync_api  # noqa: F401  (lazy: the app runs without playwright)
    except ImportError:
        log("media: playwright not installed, skipping instagram")
        return []
    deadline = time.monotonic() + budget
    sess = _bb_create(key, proj, int(max(60, min(90, budget))), deadline)
    if not sess:
        return []
    try:
        return grid_from_cdp(sess["connectUrl"], handle, deadline)
    finally:
        _bb_release(key, proj, sess["id"])


# ── orchestration ───────────────────────────────────────────────────────────
def gather(slug, platform, handle, profile, cse_items, *, budget=MEDIA_BUDGET, browser=True):
    """Fill <DATA_DIR>/media/<slug>/. Never raises. -> final status ('ready'|'none')."""
    t0 = time.monotonic()
    deadline = t0 + budget
    g, key, cacheable, n_google, n_ig = _Gallery(slug), cache_key(platform, handle), False, 0, 0
    n_tiles = n_embed = 0
    try:
        if g.from_cache(key):
            log(f"media done cache=hit n={len(g.images)}")
            return "ready" if g.images else "none"
        leak = _leak_sets(cse_items)
        ig, ig_ok = ig_handle(platform, handle, profile), True
        if ig:
            try:
                tiles = ig_embed_grid(ig, max(1, min(IG_EMBED_TIMEOUT, deadline - time.monotonic())))
                n_tiles = len(tiles)
                for u in tiles:
                    if g.full or time.monotonic() > deadline:
                        break
                    n_embed += g.add(fetch_image(u), "instagram")
            except Exception as e:
                ig_ok = False
                log(f"media ig embed failed: {type(e).__name__}")
        try:
            for u in google_images(handle, profile, leak):
                if g.full or time.monotonic() > deadline:
                    break
                n_google += g.add(fetch_image(u), "google")
        except Exception as e:
            log(f"media google step failed: {type(e).__name__}")
        bb_wanted = bool(MEDIA_BROWSERBASE and ig and n_embed < BB_FALLBACK_BELOW and not g.full)
        if browser and bb_wanted and deadline - time.monotonic() > 20:
            try:
                for data in grab_ig_grid(ig, deadline - time.monotonic()) or []:
                    n_ig += g.add(data, "instagram")
            except Exception as e:
                ig_ok = False
                log(f"media instagram step failed: {type(e).__name__}")
        # not cached: transient IG failure, embed tiles found but none downloaded, or the
        # Browserbase fallback was wanted but no slot was free
        cacheable = ig_ok and not (n_tiles and not n_embed) and (browser or not bb_wanted)
    except Exception as e:
        log(f"media gather failed: {type(e).__name__}")
    finally:
        try:
            g.finish()
        except OSError as e:
            log(f"media index write failed: {type(e).__name__}")
    if cacheable:
        _cache_save(key, slug, g.images)
    log(f"media done cache=miss embed={n_embed}/{n_tiles} google={n_google} instagram={n_ig} browser={browser} "
        f"secs={time.monotonic() - t0:.1f}")
    return "ready" if g.images else "none"


def _run(slug, platform, handle, profile, cse_items):
    full = _SEM.acquire(blocking=False)
    try:
        gather(slug, platform, handle, profile, cse_items, browser=full)
    finally:
        if full:
            _SEM.release()
        with _LOCK:
            _RUNNING.discard(slug)


def start(slug, platform, handle, profile, cse_items):
    """Kick off the background gather for a fresh quick scan -> 'pending' | 'none'. Never raises."""
    if not MEDIA_ENABLED or not SLUG_RE.match(slug or "") or not HANDLE_RE.match(handle or ""):
        return "none"
    try:
        _write_index(slug, "pending", [])
        with _LOCK:
            _RUNNING.add(slug)
        threading.Thread(target=_run, args=(slug, platform, handle, profile, list(cse_items or [])),
                         daemon=True).start()
        return "pending"
    except Exception as e:
        with _LOCK:
            _RUNNING.discard(slug)
        log(f"media start failed: {type(e).__name__}")
        try:
            _write_index(slug, "none", [])
        except OSError:
            pass
        return "none"


def prune(days=30):
    """Drop media dirs older than `days` and stale cache entries. -> count removed."""
    n, now = 0, time.time()
    root = os.path.join(data_dir(), "media")
    for name in os.listdir(root) if os.path.isdir(root) else []:
        p = os.path.join(root, name)
        try:
            if SLUG_RE.match(name) and now - os.path.getmtime(p) > days * 86400:
                shutil.rmtree(p)
                n += 1
        except OSError:
            pass
    croot = os.path.join(data_dir(), "media-cache")
    for name in os.listdir(croot) if os.path.isdir(croot) else []:
        p = os.path.join(croot, name)
        try:
            if now - os.path.getmtime(p) > CACHE_TTL:
                os.remove(p)
                n += 1
        except OSError:
            pass
    return n

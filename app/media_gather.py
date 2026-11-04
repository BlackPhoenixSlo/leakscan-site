"""Quick-scan SFW media: a few NON-nude photos of the creator for the landing's mock
"official website", gathered in a background thread after a quick scan's DB insert.

Sources (official only, nothing from the scan's leak results), in this order:
  (a) Instagram profile embed page (instagram.com/<handle>/embed/, anonymous, no browser):
      latest posts' image URLs from its server-rendered contextJSON;
  (b) ONE Browserbase session per scan (only when (a) left room, keys set, a gather slot is
      free and >= 20 s budget left), each sub-step time-boxed and failing alone:
        1. Google Images (MEDIA_GOOGLE=browser, default): tbm=isch&safe=active for
           google_queries() (<= 2, official-account sites); tiles on official sites are
           clicked to read the full-size URL (must be an official CDN, same google_ok policy
           as CSE); last resort: Google's own SafeSearch thumbnail of an official-site tile;
        2. Google web text: top <= 10 organic {title,url,snippet} for "<handle>" (+ display
           name), leak/hit domains dropped, <= 4000 chars -> media/<slug>/web_snippets.json,
           then ONE extra DeepSeek call refines the scan's profile (profile_extract.refine_profile);
        3. Instagram grid fallback (only when (a) added < BB_FALLBACK_BELOW images).
      EU consent: SOCS/CONSENT cookies pre-set, "Accept all" clicked as fallback. Google's
      /sorry captcha is left to Browserbase's solveCaptchas (~8 s measured). Order: google.com is
      opened once first (warmup: consent + captcha settle, <= CAPTCHA_WAIT s) so the web-text query
      does not run into an unsolved captcha (prod: solved=False -> raw=0 -> no refine); a web-text
      query that still came back raw=0 is retried ONCE after the Images step.
  MEDIA_GOOGLE=cse: the old CSE image search (GOOGLE_CSE_ID_WEB, a whole-web engine) instead
  of 1-2; MEDIA_GOOGLE=off: no Google at all (session only for 3).
SFW limitation: there is NO NSFW classifier. Safety relies on Instagram/TikTok/YouTube/X
content policy + Google SafeSearch + official-source-only.

Layout: <DATA_DIR>/media/<slug>/{index.json, web_snippets.json, 0.jpg, 1.jpg..}; per-handle cache
<DATA_DIR>/media-cache/<platform>-<handle>.json (7 days) points at an earlier slug's files.
`playwright` and Pillow are imported lazily: the app runs without them (gather -> fewer/no images).
"""
import base64
import contextlib
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
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import cse_scanner
import db
from netloc import registrable_domain


def _flag(name, default):
    return os.environ.get(name, default).lower() in ("1", "true", "yes")


MEDIA_ENABLED = _flag("MEDIA_ENABLED", "1")
MEDIA_BROWSERBASE = _flag("MEDIA_BROWSERBASE", "1")
MEDIA_BUDGET = float(os.environ.get("MEDIA_BUDGET", "90"))
MEDIA_MAX = max(1, min(int(os.environ.get("MEDIA_MAX", "12")), 12))
# Google step: "browser" = Google Images + web text in the Browserbase session (default),
# "cse" = CSE image search with GOOGLE_CSE_ID_WEB (opt-in), "off" = no Google.
MEDIA_GOOGLE = os.environ.get("MEDIA_GOOGLE", "browser").strip().lower()
if MEDIA_GOOGLE not in ("browser", "cse", "off"):
    MEDIA_GOOGLE = "browser"
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
BB_FALLBACK_BELOW = 4         # IG grid in the session only when the embed step added fewer images
BB_CREATE_GAP = 2.5           # s between session creates, process-wide (25 creates/min org limit)
GOOGLE_IMG_BOX = 35           # s for the Images sub-step (first query includes the captcha solve)
GOOGLE_WEB_BOX = 20           # s for the web-text sub-step
CAPTCHA_WAIT = 25             # s to let Browserbase solve a /sorry captcha (measured ~8 s)
CLICKS_PER_QUERY = 6          # tiles clicked per Images query to read the full-size URL
CLICK_WAIT_MS = 1500
THUMB_BELOW = 3               # Google thumbnails only when < this many full-size images came
WEB_MAX, WEB_TEXT_CAP = 10, 4000
REFINE_RESERVE = 12           # s of the budget kept for the profile-refine DeepSeek call
SNIPPETS_FILE = "web_snippets.json"
# Pre-set EU consent ("Accept all") so Google serves results, not the consent interstitial.
CONSENT_COOKIES = [
    {"name": "SOCS", "value": "CAISHAgBEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmVuIAEaBgiAo_CmBg",
     "domain": ".google.com", "path": "/"},
    {"name": "CONSENT", "value": "YES+cb.20230810-00-p0.en+FX+410", "domain": ".google.com", "path": "/"},
]
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
_BB_GATE = threading.Lock()   # serializes session creates (BB_CREATE_GAP apart)
_BB_LAST = [0.0]


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


def _write_index(slug, status, images, profile_updated_at=None):
    d = media_dir(slug)
    os.makedirs(d, exist_ok=True)
    obj = {"slug": slug, "status": status, "images": images, "updated_at": int(time.time()),
           "profile_updated_at": profile_updated_at}
    _atomic_write(os.path.join(d, "index.json"), json.dumps(obj).encode())


def _read_index(slug):
    try:
        with open(os.path.join(media_dir(slug), "index.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def public_view(slug):
    """-> {slug, status, images:[{src,w,h,source}], updated_at, profile_updated_at}.
    profile_updated_at (ISO) is set once the profile was refined from web text: refetch it.
    Slug must be SLUG_RE-valid."""
    idx = _read_index(slug) if MEDIA_ENABLED else None
    if not idx:
        return {"slug": slug, "status": "none", "images": [], "updated_at": None,
                "profile_updated_at": None}
    imgs, status = idx.get("images") or [], idx.get("status")
    with _LOCK:
        running = slug in _RUNNING
    if status == "pending" and not running and time.time() - (idx.get("updated_at") or 0) > MEDIA_BUDGET + 60:
        status = None                      # orphaned by a restart: settle with what's on disk
    if status not in ("pending", "ready", "none"):
        status = "ready" if imgs else "none"
    order = sorted(imgs, key=lambda i: i.get("source") != "instagram")    # IG grid first
    return {"slug": slug, "status": status, "updated_at": idx.get("updated_at"),
            "profile_updated_at": idx.get("profile_updated_at"),
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
        self.profile_updated_at = self.cache_slug = None

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
        _write_index(self.slug, "pending", self.images, self.profile_updated_at)
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
        self.cache_slug = c["slug"]
        return True

    def finish(self):
        _write_index(self.slug, "ready" if self.images else "none", self.images, self.profile_updated_at)


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


def ig_handle(platform, handle, profile, socials=None):
    """User-declared Instagram handle first, then profile.accounts, then the scanned IG handle."""
    dec = (socials or {}).get("instagram")
    if isinstance(dec, str) and HANDLE_RE.match(dec):
        return dec
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


# ── Browserbase session (one per scan) ───────────────────────────────────────
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


def _ms(deadline, cap):
    return max(1000, min(cap, int((deadline - time.monotonic()) * 1000)))


@contextlib.contextmanager
def _cdp_page(connect_url, deadline):
    """Connect to the session's CDP browser -> its first page (tests patch this: browser wire)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(connect_url, timeout=_ms(deadline, 15000))
        try:
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            yield ctx.pages[0] if ctx.pages else ctx.new_page()
        finally:
            try:
                browser.close()
            except Exception:
                pass


def grid_from_page(page, handle, deadline):
    """Open the public IG profile in the session's page -> grid image bytes."""
    resp = {}
    page.on("response", lambda r: resp.setdefault(r.url, r)
            if r.request.resource_type == "image" else None)
    page.goto(f"https://www.instagram.com/{handle}/", wait_until="domcontentloaded",
              timeout=_ms(deadline, 30000))
    try:
        page.wait_for_selector(GRID_SEL, timeout=_ms(deadline, IG_GRID_WAIT_MS))
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


def _bb_create_gated(key, proj, timeout, deadline):
    """Process-wide: one create at a time, >= BB_CREATE_GAP s apart (no 429 bursts)."""
    with _BB_GATE:
        wait = _BB_LAST[0] + BB_CREATE_GAP - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            return _bb_create(key, proj, timeout, deadline)
        finally:
            _BB_LAST[0] = time.monotonic()


def bb_keys():
    return os.environ.get("BROWSERBASE_API_KEY", ""), os.environ.get("BROWSERBASE_PROJECT_ID", "")


# ── Google in the browser: consent, captcha, parsers ─────────────────────────
_CONSENT_RE = re.compile(r"consent\.google\.|Before you continue to Google", re.I)
_ACCEPT_JS = """() => {
  const b = Array.from(document.querySelectorAll('button, input[type=submit], div[role=button]'))
    .find(e => /^(accept all|i agree|alle akzeptieren|tout accepter|accetta tutto|aceptar todo|sprejmi vse)$/i
      .test((e.innerText || e.value || e.getAttribute('aria-label') || '').trim()));
  if (b) { b.click(); return true; }
  return false;
}"""
_CLICK_JS = """async (a) => {
  const ext = (s) => { try { const h = new URL(s).hostname;
    return /^https:/.test(s) && !/(^|\\.)(gstatic|google|googleusercontent)\\.com$/.test(h); } catch (e) { return false; } };
  const out = {};
  for (const id of a.ids) {
    const t = document.querySelector('[data-lpage][data-docid="' + id + '"]');
    if (!t) continue;
    const old = new Set(Array.from(document.querySelectorAll('img[jsname="kn3ccd"]')).map(i => i.currentSrc || i.src));
    (t.querySelector('[role=button]') || t.querySelector('a') || t).click();
    const t0 = Date.now();
    while (Date.now() - t0 < a.wait && !out[id]) {
      await new Promise(r => setTimeout(r, 150));
      for (const i of document.querySelectorAll('img[jsname="kn3ccd"]')) {
        const s = i.currentSrc || i.src;
        if (ext(s) && !old.has(s)) { out[id] = {src: s, w: i.naturalWidth, h: i.naturalHeight}; break; }
      }
    }
  }
  return out;
}"""
_TAG_RE = re.compile(r"<[^>]+>")
_ATTR_RE = re.compile(r'([a-zA-Z:_-]+)\s*=\s*"([^"]*)"')
_TILE_RE = re.compile(r'<div\b[^>]*\bdata-lpage="[^"]*"[^>]*>', re.I)
_THUMB_RE = re.compile(r'<img\b[^>]*?\bsrc="(data:image/(?:jpeg|png|webp);base64,[A-Za-z0-9+/=]+|'
                       r'https://encrypted-tbn\d\.gstatic\.com/images\?[^"]+)"', re.I)
_H3_RE = re.compile(r"<h3\b[^>]*>(.*?)</h3>", re.I | re.S)
_CITE_RE = re.compile(r"<cite\b[^>]*>(.*?)</cite>", re.I | re.S)
_SNIP_RE = re.compile(r'<div\b[^>]*class="[^"]*\bVwiC3b\b[^"]*"[^>]*>(.*?)</div>', re.I | re.S)
_HREF_RE = re.compile(r'<a\b[^>]*\bhref="([^"]+)"', re.I)
_SOURCE_RE = re.compile(r'<span\b[^>]*class="[^"]*\bVuuXrf\b[^"]*"[^>]*>(.*?)</span>', re.I | re.S)
_SOCIAL_URL = {"instagram": "https://www.instagram.com/{}/", "x": "https://x.com/{}",
               "x (formerly twitter)": "https://x.com/{}", "tiktok": "https://www.tiktok.com/@{}",
               "youtube": "https://www.youtube.com/@{}", "facebook": "https://www.facebook.com/{}",
               "threads": "https://www.threads.net/@{}"}
_TBN_RE = re.compile(r"^https://encrypted-tbn\d\.gstatic\.com/images\?")
THUMB_CAP = 200 * 1024


def _text(frag):
    t = re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", frag or ""))).strip()
    return re.sub(r" ([,.;:!?])", r"\1", t)


def parse_google_images(page_html):
    """Google Images result page -> [{docid, context, host, title, thumb}] in page order.
    Tiles are <div data-lpage=<context page> data-docid=..>; thumb = the tile's inline base64
    (or encrypted-tbn) image. Full-size URLs are NOT in the page (read by clicking a tile)."""
    h, out, seen = page_html or "", [], set()
    starts = [m for m in _TILE_RE.finditer(h)]
    for i, m in enumerate(starts):
        a = {k.lower(): html.unescape(v) for k, v in _ATTR_RE.findall(m.group(0))}
        ctx, docid = a.get("data-lpage") or "", a.get("data-docid") or ""
        if not docid or docid in seen or not ctx.startswith(("https://", "http://")):
            continue
        seen.add(docid)
        seg = h[m.end():starts[i + 1].start() if i + 1 < len(starts) else m.end() + 200_000]
        th = _THUMB_RE.search(seg)
        alt = re.search(r'<img\b[^>]*\balt="([^"]*)"', seg)
        out.append({"docid": docid, "context": ctx, "host": (urlparse(ctx).hostname or "").lower(),
                    "title": html.unescape(alt.group(1)) if alt else "",
                    "thumb": html.unescape(th.group(1)) if th else None})
    return out


def _result_url(seg_before, seg_after):
    """Organic result URL: a direct/`/url?q=` href, else rebuilt from the <cite> breadcrumb
    ('https://www.instagram.com › p › X' -> https://www.instagram.com/p/X) — Google now
    wraps result links in opaque /goto?url= tokens."""
    hrefs = _HREF_RE.findall(seg_before[-1500:])
    for href in reversed(hrefs):
        href = html.unescape(href)
        if href.startswith("/url?"):
            q = parse_qs(urlparse(href).query)
            href = unquote((q.get("q") or q.get("url") or [""])[0])
        host = (urlparse(href).hostname or "") if href.startswith("http") else ""
        if host and not re.search(r"(^|\.)(google|gstatic)\.[a-z.]+$", host):
            return href
        break                                   # nearest anchor is the title link
    for c in _CITE_RE.findall(seg_after[:3000]):
        parts = [p.strip() for p in re.split(r"\s*[›>]\s*", _text(c.replace("&rsaquo;", "›")))]
        if parts and re.match(r"^https?://[A-Za-z0-9.-]+$", parts[0]):
            path = []
            for p in parts[1:]:                 # stop at a display label ('Wall Art') or an ellipsis
                if "..." in p or not re.match(r"^[A-Za-z0-9._~%@+=:-]+$", p):
                    break
                path.append(p)
            return parts[0] + "/" + "/".join(path)
    # social results show no URL, only a source label 'Instagram · natgeo'
    lab = _SOURCE_RE.search(seg_after[:3000])
    if lab:
        site, _, who = _text(lab.group(1)).partition("·")
        tpl, who = _SOCIAL_URL.get(site.strip().lower()), who.strip().lstrip("@")
        if tpl:                                 # label names a page, not a handle -> site root
            return tpl.format(who) if HANDLE_RE.match(who) else tpl.split("{}")[0].rstrip("@")
    return None


def parse_google_web(page_html):
    """Google web results page -> organic [{title, url, snippet}] (sitelinks/ads skipped:
    an organic title <h3> is followed by a <cite>)."""
    h, out = page_html or "", []
    ms = list(_H3_RE.finditer(h))
    for i, m in enumerate(ms):
        nxt = ms[i + 1].start() if i + 1 < len(ms) else len(h)
        after = h[m.end():nxt]
        if not _CITE_RE.search(after[:3000]):
            continue
        title, url = _text(m.group(1)), _result_url(h[:m.start()], after)
        if not title or not url:
            continue
        sn = _SNIP_RE.search(after)
        out.append({"title": title[:200], "url": url[:300], "snippet": _text(sn.group(1))[:400] if sn else ""})
    return out


def _official_ctx(item, leak):
    urls, doms = leak
    d = registrable_domain(item.get("context") or "")
    return d in _NOT_LEAK and d not in doms and item.get("context") not in urls


# Measured (real Google, Browserbase): /watch, /shorts tiles open a preview with the full-size
# i.ytimg.com URL in ~1 s; IG /p/ and channel/profile tiles mostly never expose one -> click those last.
_CLICK_FIRST = re.compile(r"youtube\.com/(?:watch|shorts)|youtu\.be/|/status/|tiktok\.com/@[^/]+/video/")


def _click_rank(t):
    return 0 if _CLICK_FIRST.search(t.get("context") or "") else 1


def thumb_bytes(src):
    """Google's own SafeSearch thumbnail: inline base64 or encrypted-tbn*.gstatic.com only."""
    try:
        if src.startswith("data:image/"):
            data = base64.b64decode(src.split(",", 1)[1])
            return data if len(data) <= THUMB_CAP else None
        if not _TBN_RE.match(src):
            return None
        req = urllib.request.Request(src, headers={"User-Agent": UA, "Accept": "image/*"})
        with urlopen(req, timeout=FETCH_TIMEOUT) as r:
            if (getattr(r, "status", None) or r.getcode()) != 200:
                return None
            data = r.read(THUMB_CAP + 1)
        return data if 0 < len(data) <= THUMB_CAP else None
    except Exception:
        return None


def _accept_consent(page):
    """Fallback when the cookies didn't stick: click Google's 'Accept all'. -> clicked?"""
    try:
        return bool(page.evaluate(_ACCEPT_JS))
    except Exception:
        return False


def _set_consent(page):
    try:
        page.context.add_cookies(CONSENT_COOKIES)
        return True
    except Exception as e:
        log(f"media google consent cookies failed: {type(e).__name__}")
        return False


def _wait(page, ms):
    try:
        page.wait_for_timeout(ms)
    except Exception:
        time.sleep(ms / 1000)


def google_page(page, url, box_deadline, ready):
    """Navigate, let Browserbase solve a /sorry captcha, click consent if shown.
    -> page HTML (or '' when walled). `ready(html)` says whether results are present."""
    page.goto(url, wait_until="domcontentloaded", timeout=_ms(box_deadline, 30000))
    if "/sorry/" in (page.url or ""):
        t0 = time.monotonic()
        while "/sorry/" in (page.url or "") and time.monotonic() < box_deadline - 2:
            _wait(page, 1000)
        solved = "/sorry/" not in (page.url or "")
        log(f"media google captcha solved={solved} secs={time.monotonic() - t0:.1f}")
        if not solved:
            return ""
    _wait(page, 800)
    h = page.content()
    # EU: a redirect to consent.google.com, OR (measured) an in-page dialog over parseable results
    # that blocks image clicks -> click 'Accept all' whenever one is present
    if _CONSENT_RE.search(page.url or "") or _CONSENT_RE.search(h):
        clicked = _accept_consent(page)
        if clicked or not ready(h):
            log(f"media google consent interstitial clicked={clicked}")
        if clicked:
            _wait(page, 1500)
            h = page.content()
    return h if ready(h) else ""


GOOGLE_HOME = "https://www.google.com/?safe=active&hl=en&gl=us"


def google_warmup(page, box_deadline):
    """Open google.com once and let the consent click / Browserbase captcha solve finish before the
    first query (same helpers as every query). -> settled?"""
    t0 = time.monotonic()
    try:
        ok = bool(google_page(page, GOOGLE_HOME, box_deadline, lambda h: bool(h)))
    except Exception as e:
        ok = False
        log(f"media google warmup failed: {type(e).__name__}")
    log(f"media google warmup ok={ok} secs={time.monotonic() - t0:.1f}")
    return ok


def _google_url(q, images):
    return ("https://www.google.com/search?" + ("tbm=isch&" if images else "")
            + "safe=active&hl=en&gl=us&q=" + quote_plus(q))


def google_images_step(page, g, handle, profile, leak, box_deadline):
    """Google Images in the session -> images added. Full-size URLs (official CDN, google_ok)
    first; thumbnails of official-site tiles only as last resort."""
    t0, added, thumbs, n_tiles, n_full, n_click, n_res = time.monotonic(), 0, [], 0, 0, 0, 0
    resolved = set()
    for q in google_queries(handle, profile):
        if g.full or box_deadline - time.monotonic() < 5:
            break
        tiles = parse_google_images(google_page(page, _google_url(q, True), box_deadline,
                                                lambda h: "data-lpage=" in h))
        n_tiles += len(tiles)
        cand = sorted((t for t in tiles if _official_ctx(t, leak)), key=_click_rank)
        ids = [t["docid"] for t in cand[:CLICKS_PER_QUERY]]
        n_click += len(ids)
        wait = min(CLICK_WAIT_MS, max(300, int((box_deadline - time.monotonic()) * 1000 / max(1, len(ids)))))
        full = page.evaluate(_CLICK_JS, {"ids": ids, "wait": wait}) if ids and box_deadline - time.monotonic() > 3 else {}
        n_res += len(full or {})
        for t in cand:
            f = (full or {}).get(t["docid"]) or {}
            item = {"full": f.get("src") or "", "host": t["host"], "w": f.get("w"), "h": f.get("h")}
            if item["full"] and google_ok(item, leak) and not g.full:
                n_full += 1
                if g.add(fetch_image(item["full"]), "google"):
                    added += 1
                    resolved.add(t["docid"])
                    continue
            if t["thumb"] and t["docid"] not in resolved:
                thumbs.append(t["thumb"])
    n_thumb = 0
    if added < THUMB_BELOW:
        for src in thumbs:
            if g.full or n_thumb >= THUMB_BELOW:
                break
            n_thumb += g.add(thumb_bytes(src), "google")
    log(f"media google images tiles={n_tiles} clicked={n_click} resolved={n_res} full={n_full} added={added} thumbs={n_thumb} "
        f"secs={time.monotonic() - t0:.1f}")
    return added + n_thumb


def web_queries(handle, profile, ig=None):
    qs = [f'"{handle}"']
    name = ((profile or {}).get("display_name") or "").strip()
    if name and len(name) <= 60 and name.lower() != handle.lower() and '"' not in name:
        qs.append(f'"{name}"')
    elif ig and ig.lower() != handle.lower():
        qs.append(f'"{ig}"')
    return qs[:2]


def clean_snippets(results, leak):
    """Drop leak/hit domains, Google's own pages and unsafe wording; dedupe; cap 10 / 4000 chars."""
    import profile_extract                          # lazy: SFW word filter lives there
    urls, doms = leak
    out, seen, total = [], set(), 0
    for r in results:
        u, d = r.get("url") or "", registrable_domain(r.get("url") or "")
        if not d or d in doms or u in urls or (u, r.get("title")) in seen or re.match(r"^(google|gstatic)\.", d):
            continue
        if profile_extract._UNSAFE_RE.search(f"{r.get('title')} {r.get('snippet')} {u}"):
            continue
        size = len(r["title"]) + len(r["snippet"]) + len(u)
        if total + size > WEB_TEXT_CAP:
            room = WEB_TEXT_CAP - total - len(r["title"]) - len(u)
            if room < 40:
                break
            r = {**r, "snippet": r["snippet"][:room]}
            size = len(r["title"]) + len(r["snippet"]) + len(u)
        seen.add((u, r["title"]))
        out.append({"title": r["title"], "url": u, "snippet": r["snippet"]})
        total += size
        if len(out) >= WEB_MAX:
            break
    return out


def google_web_step(page, handle, profile, ig, leak, box_deadline):
    """-> (kept snippets, raw result count)."""
    t0, raw, nq = time.monotonic(), [], 0
    for q in web_queries(handle, profile, ig):
        if box_deadline - time.monotonic() < 4:
            break
        nq += 1
        raw += parse_google_web(google_page(page, _google_url(q, False), box_deadline,
                                            lambda h: bool(_CITE_RE.search(h))))
    out = clean_snippets(raw, leak)
    log(f"media google web queries={nq} raw={len(raw)} kept={len(out)} "
        f"chars={sum(len(r['title']) + len(r['snippet']) + len(r['url']) for r in out)} "
        f"secs={time.monotonic() - t0:.1f}")
    return out, len(raw)


def browser_steps(g, *, handle, ig, profile, leak, deadline, want_google, want_grid):
    """ONE Browserbase session for this scan: (b) Google web text, (a) Google Images,
    (c) IG grid fallback — each time-boxed, each failing alone. Session released in finally.
    -> {session, google, instagram, snippets, ok}"""
    st = {"session": False, "google": 0, "instagram": 0, "snippets": [], "ok": True}
    key, proj = bb_keys()
    if not key or not proj:
        return st
    try:
        import playwright.sync_api  # noqa: F401  (lazy: the app runs without playwright)
    except ImportError:
        log("media: playwright not installed, skipping browser steps")
        return st
    t0 = time.monotonic()
    sess = _bb_create_gated(key, proj, int(max(60, min(120, deadline - t0 + 15))), deadline)
    if not sess:
        st["ok"] = False
        return st
    st["session"] = True
    log(f"media browserbase session created secs={time.monotonic() - t0:.1f}")
    try:
        with _cdp_page(sess["connectUrl"], deadline) as page:
            if want_google:
                _set_consent(page)
                google_warmup(page, min(deadline, time.monotonic() + CAPTCHA_WAIT + 3))
                raw = 0
                try:   # web text first: ~3 s, and it is what feeds the profile refine
                    st["snippets"], raw = google_web_step(page, handle, profile, ig, leak,
                                                          min(deadline, time.monotonic() + GOOGLE_WEB_BOX))
                except Exception as e:
                    st["ok"] = False
                    log(f"media google web failed: {type(e).__name__}")
                try:
                    st["google"] = google_images_step(page, g, handle, profile, leak,
                                                      min(deadline, time.monotonic() + GOOGLE_IMG_BOX))
                except Exception as e:
                    st["ok"] = False
                    log(f"media google images failed: {type(e).__name__}")
                if not raw and deadline - time.monotonic() > 6:
                    try:   # once: the Images step usually leaves the captcha solved
                        log("media google web retry")
                        st["snippets"], raw = google_web_step(page, handle, profile, ig, leak,
                                                              min(deadline, time.monotonic() + GOOGLE_WEB_BOX))
                    except Exception as e:
                        st["ok"] = False
                        log(f"media google web retry failed: {type(e).__name__}")
            if want_grid and not g.full and deadline - time.monotonic() > 8:
                t1 = time.monotonic()
                try:
                    for data in grid_from_page(page, ig, deadline):
                        st["instagram"] += g.add(data, "instagram")
                except Exception as e:
                    st["ok"] = False
                    log(f"media instagram step failed: {type(e).__name__}")
                log(f"media instagram grid added={st['instagram']} secs={time.monotonic() - t1:.1f}")
    except Exception as e:
        st["ok"] = False
        log(f"media browser session failed: {type(e).__name__}")
    finally:
        _bb_release(key, proj, sess["id"])
        log(f"media browserbase session released secs={time.monotonic() - t0:.1f}")
    return st


# ── web snippets + profile refine ───────────────────────────────────────────
def snippets_path(slug):
    return os.path.join(media_dir(slug), SNIPPETS_FILE)


def save_snippets(slug, snippets):
    os.makedirs(media_dir(slug), exist_ok=True)
    _atomic_write(snippets_path(slug), json.dumps(snippets, ensure_ascii=False).encode())


def load_snippets(slug):
    try:
        with open(snippets_path(slug), encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def refine(slug, platform, handle, profile, sources, snippets, socials, deadline):
    """ONE extra DeepSeek call with the web snippets -> scan's stored profile. -> ISO ts | None."""
    if not snippets:
        return None
    timeout = deadline - time.monotonic() - 0.5
    if timeout < 3:
        log("media profile refine skipped: budget")
        return None
    t0 = time.monotonic()
    try:
        import profile_extract
        new = profile_extract.refine_profile(profile, sources, snippets, platform=platform, handle=handle,
                                             socials=socials, timeout=min(profile_extract.LLM_TIMEOUT, timeout))
        if not new:
            log(f"media profile refine kept original secs={time.monotonic() - t0:.1f}")
            return None
        if not db.update_extra(slug, {"profile": new}):
            return None
    except Exception as e:
        log(f"media profile refine failed: {type(e).__name__}")
        return None
    log(f"media profile refined snippets={len(snippets)} secs={time.monotonic() - t0:.1f}")
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── orchestration ───────────────────────────────────────────────────────────
def gather(slug, platform, handle, profile, cse_items, *, budget=MEDIA_BUDGET, browser=True,
           sources=None, socials=None):
    """Fill <DATA_DIR>/media/<slug>/. Never raises. -> final status ('ready'|'none')."""
    t0 = time.monotonic()
    deadline = t0 + budget
    g, key, cacheable, n_google = _Gallery(slug), cache_key(platform, handle), False, 0
    n_tiles = n_embed = 0
    st = {"session": False, "google": 0, "instagram": 0, "snippets": [], "ok": True}
    snippets = []
    try:
        if g.from_cache(key):
            snippets = load_snippets(g.cache_slug)
            if snippets:
                save_snippets(slug, snippets)
                g.profile_updated_at = refine(slug, platform, handle, profile, sources, snippets, socials,
                                              deadline)
            log(f"media done cache=hit n={len(g.images)} snippets={len(snippets)}")
            return "ready" if g.images else "none"
        leak = _leak_sets(cse_items)
        ig, ig_ok = ig_handle(platform, handle, profile, socials), True
        if ig:
            t1 = time.monotonic()
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
            log(f"media ig embed added={n_embed}/{n_tiles} secs={time.monotonic() - t1:.1f}")
        if MEDIA_GOOGLE == "cse":
            try:
                for u in google_images(handle, profile, leak):
                    if g.full or time.monotonic() > deadline:
                        break
                    n_google += g.add(fetch_image(u), "google")
            except Exception as e:
                log(f"media google step failed: {type(e).__name__}")
        want_grid = bool(ig and n_embed < BB_FALLBACK_BELOW and not g.full)
        want_google = MEDIA_GOOGLE == "browser" and not g.full
        k, p = bb_keys()
        bb_wanted = bool(MEDIA_BROWSERBASE and k and p and (want_grid or want_google))
        if browser and bb_wanted and deadline - time.monotonic() > 20:
            st = browser_steps(g, handle=handle, ig=ig, profile=profile, leak=leak,
                               deadline=deadline - (REFINE_RESERVE if want_google else 0),
                               want_google=want_google, want_grid=want_grid)
            snippets = st["snippets"]
            if snippets:
                try:
                    save_snippets(slug, snippets)
                except OSError as e:
                    log(f"media snippets save failed: {type(e).__name__}")
                g.profile_updated_at = refine(slug, platform, handle, profile, sources, snippets, socials,
                                              deadline)
        # not cached: transient IG/browser failure, embed tiles found but none downloaded, or
        # the browser session was wanted but no slot was free
        cacheable = (ig_ok and st["ok"] and not (n_tiles and not n_embed) and (browser or not bb_wanted))
    except Exception as e:
        log(f"media gather failed: {type(e).__name__}")
    finally:
        try:
            g.finish()
        except OSError as e:
            log(f"media index write failed: {type(e).__name__}")
    if cacheable:
        _cache_save(key, slug, g.images)
    log(f"media done cache=miss embed={n_embed}/{n_tiles} google={n_google + st['google']} "
        f"instagram={st['instagram']} snippets={len(snippets)} session={st['session']} browser={browser} "
        f"mode={MEDIA_GOOGLE} secs={time.monotonic() - t0:.1f}")
    return "ready" if g.images else "none"


def _run(slug, platform, handle, profile, cse_items, sources, socials):
    full = _SEM.acquire(blocking=False)
    try:
        gather(slug, platform, handle, profile, cse_items, browser=full, sources=sources, socials=socials)
    finally:
        if full:
            _SEM.release()
        with _LOCK:
            _RUNNING.discard(slug)


def start(slug, platform, handle, profile, cse_items, sources=None, socials=None):
    """Kick off the background gather for a fresh quick scan -> 'pending' | 'none'. Never raises."""
    if not MEDIA_ENABLED or not SLUG_RE.match(slug or "") or not HANDLE_RE.match(handle or ""):
        return "none"
    try:
        _write_index(slug, "pending", [])
        with _LOCK:
            _RUNNING.add(slug)
        threading.Thread(target=_run, args=(slug, platform, handle, profile, list(cse_items or []),
                                            sources, socials), daemon=True).start()
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

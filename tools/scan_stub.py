#!/usr/bin/env python3
"""Local stand-in for Jaka's scan API + a static server for site/. Stdlib only; for tests and previews.

    python3 tools/scan_stub.py [--port 8930] [--omit-results] [--omit-profile] [--media normal|relative|scanhost|none|404] [--delay 0.15]
    → open http://127.0.0.1:8930/  (or http://127.0.0.1:8930/scan/?r=demoR3port01, /?r=demoR3port01, /showcase/?r=demoR3port01)

Serves site/ and the API routes of the contract the scan page talks to:
- POST /api/public-scan  {platform, handle, level, instagram?, x?} → SSE over the response body: several `progress`, one
  `result` (tools/fixtures/scan-sample.json with handle/platform/slug swapped in, plus `socials: {instagram?, x?}` echoed
  when sent; a bad instagram / x value → 400 bad_handle), `done`. Magic handles drive the error paths:
  stub-fail → `failed` + `done`; stub-429 → 429 rate_limited; stub-busy → 429 busy; stub-empty → status empty;
  stub-mixed → 3 hits (live true / false / missing) + the results; stub-huge → huge_result(): 1000 hit links on 100
  domains (deterministic, long-tail counts), 80 Google results, 30 images (report-view scale test); stub-videos →
  videos_result(): 45 results (34 video), 18 images[] (12 = video stills), 33 unique thumbs (video stills in the image views).
- GET /api/scan-result/<slug> → the stored result, 404 {"error":"not_found"} otherwise. Preloaded: demoR3port01 (the
  fixture, with its synthetic `profile`), demoHuge0001 (huge_result()), demoVideos01 (videos_result()), demoNoProf01 (same, `profile` null: scan-only personalization, no leak-page
  Instagram), demoFoundIG1 (`profile` null, leak-page Instagram fills the IG rows) and evilR3port01
  (fixture overlaid with tools/fixtures/scan-evil.json: script tags, javascript: urls, oversized strings).
  `aliases` {declared, discovered, socials} (alias enrichment) comes from the fixture: discovered handles + the
  socials read off leak pages; stub-mixed / stub-empty carry none.
  Every result carries a top-level `mega` list (mega.nz folders shared via an aggregator: url / host / via / title / size
  bytes / images / videos / age ISO UTC / status; synthetic, [] when none); demoRemove1 = demoR3port01 + one x.com / reddit.com / mega.nz hit (the #removals panels); evilR3port01's
  `mega` is hostile (markup, javascript: url, oversized size). demoNoProf01 / demoFoundIG1 have [] (demo fallback).
- GET /api/profile/<slug> → {slug, profile}; GET /api/avatar/<slug> → a generated PNG when profile.avatar is true, else 404.
- GET /api/media/<slug> (demo photos, arrive after the scan) → polls 1-2: {status:"pending", images:[2]}, then
  {status:"ready", images:[6]}; srcs are <this API origin>/api/media/<slug>/<n>.jpg (mode relative: /api/media/…;
  scanhost: https://scan.srv1395798.hstgr.cloud/api/media/…, the VPS layout; the page must load it from its own API) (the portrait
  showcase people photos in site/showcase/imgs, served as webp; the e2e checks the swap by src). evilR3port01
  also lists off-origin / javascript: srcs (must be dropped). --media none → {status:"none", images:[]}; --media 404 → 404.
  POST /__stub/media?slug=<slug>[&mode=normal|relative|scanhost|none|404] resets that slug's poll counter (and mode) for a test.
- GET /api/thumb?u=<https url> → one of those photos (picked by a hash of u, webp), never fetches u. A u containing
  DEAD → 404 (a thumb Google no longer serves); BLANK → a 1×1 GIF (what a hotlink-blocked thumb comes back as); LOGO →
  logo_png(): a flat site-logo PNG (no person photo: the image views must drop it).
- demoBrokenT1: the fixture with three page-result thumbs swapped for DEAD / BLANK ones (images[] too), page result #7's
  for a LOGO one, a LOGO thumb no result has third in images[], a video result's still put first in images[] (the
  image views put it after the real images) and the 2nd video result's still a LOGO (Videos rows: grey box, row kept):
  the broken-thumb / logo removal check.
- POST /api/chat  {kb: "landing", messages: [{role, content}], slug?} → SSE: `token` events (data = JSON-encoded text
  chunk) streaming CHAT_ANSWER (markdown with an anchor, allowed + forbidden links, bold, bullets), then `done`. A last
  user message containing stub-fail → some tokens then `failed`; stub-429 → 429 rate_limited. Each request body is
  kept in order and GET /api/_chat-log returns them (test hook, not part of the contract).
- CORS on every API response (echoes Origin), OPTIONS preflight answered.

Bypass (declared): every served .html gets `data-api="<stub origin>"` added to its <body> tag, the override the scan
page reads instead of the production API host. The origin is the *other* loopback name (127.0.0.1 <-> localhost),
so the page → API calls are cross-origin and exercise CORS like production. --omit-results drops `results` from the
result (break-it run); --omit-profile sets `profile` to null everywhere (break-it run for the personalization checks).
"""
import argparse, hashlib, json, pathlib, random, re, string, struct, sys, time, zlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
FIXTURE = json.loads((ROOT / "tools" / "fixtures" / "scan-sample.json").read_text())
EVIL = json.loads((ROOT / "tools" / "fixtures" / "scan-evil.json").read_text())
HANDLE_RE = re.compile(r"^[A-Za-z0-9._-]{1,60}$")
PLATFORMS = {"onlyfans.com", "instagram.com", "fansly.com", "tiktok.com", "patreon.com"}
STORE = {}
OPTS = argparse.Namespace(omit_results=False, omit_profile=False, delay=0.15, media="normal")
MEDIA_POLLS, MEDIA_MODE = {}, {}
SCAN_HOST = "https://scan.srv1395798.hstgr.cloud"   # only ever a string in JSON; the stub never contacts it
CHAT_LOG = []
CHAT_ANSWER = (
    "Short answer: it's **€250/month** or **€500 one-time**, and the scan plus one removal come first, free. "
    "Details: [Pricing](#pricing).\n\n"
    "- Message Jaka on [Telegram](https://t.me/jakabasej)\n"
    "- Monthly plan: **weekly re-scans**\n"
    "- Don't click [x](javascript:alert(1)) or [this deal](https://evil.example/phish) or https://evil.example/raw\n\n"
    "Questions about your case? See #contact.")


# `mega` (top-level, added by the backend for mega.nz folders) + one hit each on x.com / reddit.com / mega.nz, so the
# #removals panels have something to personalize from. Synthetic: fake folder ids / paths, the url is never rendered.
# Contract (backend PR #36): always present, [] when none; host = the aggregator that shares the (captcha-gated) mega.nz
# folder, url = its share page (here a fake .example path), size in bytes, age = ISO UTC timestamp, status "live".
MEGA = [{"url": "https://leakshaven.example/share/DEMOfake0", "host": "leakshaven.com", "via": "leakvault.example",
         "title": "demo.creator MEGA pack 2026", "size": 6657199309, "images": 412, "videos": 88,
         "age": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3 * 86400 - 600)), "status": "live"}]
SOCIAL_HITS = [
    {"domain": "x.com", "url": "https://x.com/demo_reposter/status/1000000000000000001", "occurrences": 2, "method": "google",
     "alias": None, "live": True, "title": "Mira Example leaked full set / X"},
    {"domain": "reddit.com", "url": "https://www.reddit.com/r/demo_leaksub/comments/abc123/mira_example/", "occurrences": 1,
     "method": "google", "alias": None, "live": True, "title": "Mira Example new pack in comments : r/demo_leaksub"},
    {"domain": "mega.nz", "url": "https://mega.nz/folder/DEMOfake0#synthetic", "occurrences": 1, "method": "google",
     "alias": None, "live": True, "title": "demo.creator pack - MEGA"}]


EVIL_MEGA = [{"url": "javascript:alert(1)", "host": "mega.nz", "title": "<img src=x onerror=alert(1)>", "size": "x" * 500,
              "images": "<b>", "videos": -5, "age": "https://evil.example/age", "status": "live"}]


LONG = "free-full-gallery-all-photos-and-videos-download/"   # some huge-fixture links are long: the handle sits in the tail


def huge_result(handle, n_links=1000, n_domains=100):
    """1000 links on 100 domains, same every run: long-tail counts (domain i ~ 1/(i+1)^0.9, each >= 1, sum exact),
    every 3rd link long (handle in its tail), 80 Google results on the top domains (every 8th a video), 30 images. Report-view scale fixture (stub-huge)."""
    pre = ["leak", "fan", "only", "nude", "pic", "vid", "clip", "mirror", "dump", "thot"]
    suf = ["vault", "zone", "base", "stash", "hoard", "drop", "rip", "bay", "flood", "board"]
    doms = [f"{pre[i % 10]}{suf[(i // 10 + i) % 10]}.example" for i in range(n_domains)]
    w = [1 / (i + 1) ** 0.9 for i in range(n_domains)]
    cnt = [1 + int((n_links - n_domains) * x / sum(w)) for x in w]
    for i in range(n_links - sum(cnt)):
        cnt[i % n_domains] += 1
    kinds = ["gallery", "model", "album", "thread", "set", "video", "post", "tag"]
    hits = [{"domain": d, "url": f"https://{'www.' if i % 7 == 3 else ''}{d}/{kinds[(i + k) % 8]}/{1000 + i * 37 + k}/{LONG if k % 3 == 1 else ''}{handle}-{k + 1}",
             "occurrences": max(1, 12 - k // 3 - i // 10), "method": "google", "alias": None, "live": k % 5 != 4,
             "title": f"{handle} {kinds[(i + k) % 8]} {k + 1} - {d.split('.')[0].title()}"}
            for i, (d, c) in enumerate(zip(doms, cnt)) for k in range(c)]
    results = []
    for j in range(80):
        d = doms[j % 25]
        video = j % 8 == 7
        results.append({"title": f"{handle} {'Video' if video else 'Gallery'} {j + 1} - {d.split('.')[0].title()}",
                        "link": f"https://{d}/{'watch' if video else 'free'}/{5000 + j}/{handle}",
                        "snippet": f"{handle} on {d.split('.')[0].title()}. Browse {10 + j} posts uploaded by fans. Synthetic fixture text.",
                        "thumb": f"https://encrypted-tbn0.gstatic.com/images?q=tbn:DEMO{j + 1:04d}huge",
                        "domain": d, "kind": "video" if video else "page"})
    images = [f"https://encrypted-tbn0.gstatic.com/images?q=tbn:DEMO{200 + j:04d}huge" for j in range(30)]
    return {"hits": hits, "results": results, "images": images, "hit_count": len(hits), "domain_count": n_domains,
            "google_total": 48200, "status": "complete"}


def make_result(handle, platform, empty=False):
    r = json.loads(json.dumps(FIXTURE))
    r.update(handle=handle, platform=platform,
             slug="".join(random.choice(string.ascii_letters + string.digits) for _ in range(12)))
    r["aliases"]["declared"] = [handle]
    if handle == "stub-mixed":   # badge coverage: hits live true / false / missing, then the Google results
        r["aliases"] = {"declared": [handle], "discovered": [], "socials": []}   # no "Also found as"
        r["hits"] = r["hits"][:3]
        r["hits"][1]["live"] = False
        r["hits"][2].pop("live")
        r["hit_count"] = 3
    r["mega"] = json.loads(json.dumps(MEGA))
    if handle == "stub-huge":
        r.update(huge_result(handle))
    if handle == "stub-videos":
        r.update(videos_result(handle))
    if empty:
        r["mega"] = []
        r.update(status="empty", hit_count=0, domain_count=0, google_total=0, images=[], hits=[], results=[],
                 aliases={"declared": [handle], "discovered": [], "socials": []})
    if OPTS.omit_results:
        r.pop("results", None)
    if OPTS.omit_profile:
        r["profile"] = None
    return r


# the showcase people photos already in the repo (portrait ones, 1067-1400 px wide): no extra binary fixtures
MEDIA_FILES = [ROOT / "site" / "showcase" / "imgs" / f"{n}.webp" for n in (   # 0 = the demo hero: a face with room around it
    "editorial-02", "editorial-01", "behind-the-scenes", "editorial-03", "editorial-04")]


# Google thumbs: every showcase photo (not the og card / favicons), so a 16-tile grid shows 16 different pictures
THUMB_FILES = sorted(f for f in (ROOT / "site" / "showcase" / "imgs").glob("*.webp") if f.stem != "og")


BLANK_GIF = bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b")


def videos_result(handle):
    """stub-videos / demoVideos01, shaped like a real report (2_YPj7TbK4rm): 45 Google results, 34 video + 11 page, 5 without a
    thumb; 40 result thumbs on 27 unique (Google reuses video stills); 18 images[], 12 of them a video result's still.
    33 unique thumbs: 6 image-only + 12 shared with videos + 6 video-only + 9 page. Video-sourced: 18."""
    g = lambda tag: f"https://encrypted-tbn0.gstatic.com/images?q=tbn:VID{tag}"
    vstill = [g(f"S{k:02d}") for k in range(12)] + [g(f"V{k:02d}") for k in range(6)]   # 18 unique video stills
    results = []
    for j in range(34):
        d = ["tubeleak", "clipdump", "vidhoard"][j % 3] + ".example"
        results.append({"title": f"{handle} video {j + 1} - {d.split('.')[0].title()}", "link": f"https://{d}/watch/{7000 + j}/{handle}",
                        "snippet": f"{handle} clip on {d.split('.')[0].title()}. Synthetic fixture text.", "domain": d, "kind": "video",
                        "thumb": None if j in (30, 32, 33) else vstill[j % 18]})
    for j in range(11):
        d = ["leakvault", "fanzone", "onlybase", "picstash"][j % 4] + ".example"
        results.append({"title": f"{handle} gallery {j + 1} - {d.split('.')[0].title()}", "link": f"https://{d}/free/{8000 + j}/{handle}",
                        "snippet": f"{handle} on {d.split('.')[0].title()}. Synthetic fixture text.", "domain": d, "kind": "page",
                        "thumb": None if j in (3, 8) else g(f"P{j:02d}")})
    images = [g(f"I{k:02d}") for k in range(6)]
    images = [images[0], vstill[0], vstill[1], images[1], *vstill[2:6], images[2], *vstill[6:9], images[3], images[4], *vstill[9:12], images[5]]
    return {"results": results, "images": images}


def broken_thumbs(fx):
    """demoBrokenT1: page results #2, #3, #5 (with a thumb) get DEAD / BLANK / DEAD thumbs, in images[] too; the first
    video result's still goes first in images[]; the 2nd video result's still is a LOGO."""
    r = json.loads(json.dumps(fx))
    pages = [x for x in r["results"] if x.get("thumb") and x.get("kind") != "video"]
    for x, tag in zip((pages[1], pages[2], pages[4], pages[6]), ("DEAD0901", "BLANK0902", "DEAD0903", "LOGO0904")):
        u = f"https://encrypted-tbn0.gstatic.com/images?q=tbn:{tag}placeholder"
        r["images"] = [u if i == x["thumb"] else i for i in r["images"]]
        x["thumb"] = u
    v = [x for x in r["results"] if x.get("thumb") and x.get("kind") == "video"][1]   # 2nd video's still: a LOGO
    u = "https://encrypted-tbn0.gstatic.com/images?q=tbn:LOGO0906placeholder"
    r["images"] = [u if i == v["thumb"] else i for i in r["images"]]
    v["thumb"] = u
    r["images"].insert(2, "https://encrypted-tbn0.gstatic.com/images?q=tbn:LOGO0905placeholder")
    r["images"].insert(0, next(x["thumb"] for x in r["results"] if x.get("kind") == "video" and x.get("thumb")))
    return r


def stand_in(key, pool=MEDIA_FILES):
    """A people photo standing in for a Google thumb / a gathered media photo (bytes). The fixture's thumb ids are
    numbered (…DEMO0001…): the number walks the pool, so neighbours never repeat; else a hash of key picks."""
    n = re.search(r"DEMO(\d+)", key)
    i = int(n.group(1)) if n else hashlib.sha256(key.encode()).digest()[0]
    return pool[i % len(pool)].read_bytes()


def avatar_png(seed, w=48, h=48, cell=12):
    """A two-tone checker PNG, colours derived from seed (stdlib only, never a real photo)."""
    d = hashlib.sha256(seed.encode()).digest()
    a, b = bytes(d[0:3]), bytes(d[3:6])
    return png(w, h, lambda x, y: a if (x // cell + y // cell) % 2 else b)


def logo_png(seed, w=120, h=120):
    """A site-logo stand-in: a flat disc in a colour from seed on white (what Google Images mixes into a handle's images)."""
    d = hashlib.sha256(seed.encode()).digest()
    a = bytes((d[0] | 128, d[1] & 127, d[2] | 64))
    return png(w, h, lambda x, y: a if (x - w / 2) ** 2 + (y - h / 2) ** 2 < (w / 3) ** 2 else b"\xff\xff\xff")


def png(w, h, px):
    """px(x, y) → 3 RGB bytes; → PNG bytes (stdlib only)."""
    rows = b"".join(b"\x00" + b"".join(px(x, y) for x in range(w)) for y in range(h))
    chunk = lambda t, data: struct.pack(">I", len(data)) + t + data + struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def media_answer(slug, origin):
    mode = MEDIA_MODE.get(slug, OPTS.media)
    if mode == "404" or slug not in STORE:
        return None
    if mode == "none":
        return {"slug": slug, "status": "none", "images": []}
    n = MEDIA_POLLS[slug] = MEDIA_POLLS.get(slug, 0) + 1
    count, status = (2, "pending") if n <= 2 else (6, "ready")
    # relative = same-origin "/api/media/..." srcs (site served by the API host); scanhost = srcs on the production scan
    # host, as its backend emits them (PUBLIC_ORIGIN) while the VPS serves the site on another name: never fetched as is
    pre = {"relative": "", "scanhost": SCAN_HOST}.get(mode, origin)
    imgs = [{"src": f"{pre}/api/media/{slug}/{i}.jpg", "w": 300, "h": 400, "source": "google"} for i in range(count)]
    if slug == EVIL["slug"]:
        imgs = [{"src": "javascript:alert(1)"}, {"src": "https://evil.example/api/media/x/1.jpg"},
                {"src": "//evil.example/api/media/x/1.jpg"},
                {"src": f"{origin}.evil.example/api/media/{slug}/1.jpg"}, {"src": f"{origin}/api/media/{slug}/../x.jpg"}] + imgs
    return {"slug": slug, "status": status, "images": imgs}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SITE), **kw)

    def log_message(self, fmt, *args):
        sys.stderr.write("stub: " + fmt % args + "\n")

    def cors(self):
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin") or "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")
        self.send_header("Vary", "Origin")

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self):
        u = urlsplit(self.path)
        if u.path.startswith("/api/scan-result/"):
            slug = u.path.rsplit("/", 1)[1]
            return self.send_json(200, STORE[slug]) if slug in STORE else self.send_json(404, {"error": "not_found"})
        if u.path.startswith("/api/profile/"):
            slug = u.path.rsplit("/", 1)[1]
            if slug not in STORE:
                return self.send_json(404, {"error": "not_found"})
            return self.send_json(200, {"slug": slug, "profile": STORE[slug].get("profile")})
        if u.path.startswith("/api/media/"):
            parts = u.path.split("/")[3:]
            if len(parts) == 1:
                ans = media_answer(parts[0], f"http://{self.headers.get('Host')}")
                return self.send_json(200, ans) if ans else self.send_json(404, {"error": "not_found"})
            if len(parts) == 2 and parts[0] in STORE and re.fullmatch(r"\d{1,2}\.jpg", parts[1]):
                body = MEDIA_FILES[int(parts[1].split(".")[0]) % len(MEDIA_FILES)].read_bytes()
                self.send_response(200)
                self.cors()
                self.send_header("Content-Type", "image/webp")
                self.send_header("Cache-Control", "max-age=3600")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            return self.send_json(404, {"error": "not_found"})
        if u.path.startswith("/api/avatar/"):
            slug = u.path.rsplit("/", 1)[1]
            prof = (STORE.get(slug) or {}).get("profile")
            if not isinstance(prof, dict) or prof.get("avatar") is not True:
                return self.send_json(404, {"error": "not_found"})
            body = avatar_png(slug)
            self.send_response(200)
            self.cors()
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if u.path == "/api/thumb":
            src = parse_qs(u.query).get("u", [""])[0]
            if not src.startswith("https://"):
                return self.send_json(400, {"error": "bad_url"})
            if "DEAD" in src:
                return self.send_json(404, {"error": "not_found"})
            blank, logo = "BLANK" in src, "LOGO" in src
            body = BLANK_GIF if blank else logo_png(src) if logo else stand_in(src, THUMB_FILES)
            self.send_response(200)
            self.cors()
            self.send_header("Content-Type", "image/gif" if blank else "image/png" if logo else "image/webp")
            self.send_header("Cache-Control", "max-age=3600")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if u.path == "/api/_chat-log":
            return self.send_json(200, CHAT_LOG)
        if u.path.startswith("/api/"):
            return self.send_json(404, {"error": "not_found"})
        path = pathlib.Path(self.translate_path(u.path))
        if path.is_dir():
            path = path / "index.html"
        if path.suffix == ".html" and path.is_file():
            host = (self.headers.get("Host") or "").split(":")[0]
            port = self.server.server_address[1]
            api = f"http://{'localhost' if host == '127.0.0.1' else '127.0.0.1'}:{port}"
            body = re.sub(r"<body\b", f'<body data-api="{api}"', path.read_text(encoding="utf-8"), count=1).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return self.wfile.write(body)
        return super().do_GET()

    def sse_start(self):
        self.send_response(200)
        self.cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

    def ev(self, name, data):
        self.wfile.write(f"event: {name}\ndata: {data}\n\n".encode())
        self.wfile.flush()

    def chat(self):
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self.send_json(400, {"error": "bad_json"})
        msgs = req.get("messages")
        if req.get("kb") != "landing" or not isinstance(msgs, list) or not msgs or not all(
                isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)
                for m in msgs) or msgs[-1]["role"] != "user":
            return self.send_json(400, {"error": "bad_request"})
        CHAT_LOG.append(req)
        last = msgs[-1]["content"]
        if "stub-429" in last:
            return self.send_json(429, {"error": "rate_limited"})
        self.sse_start()
        for i in range(0, len(CHAT_ANSWER), 9):
            time.sleep(0.02)
            self.ev("token", json.dumps(CHAT_ANSWER[i:i + 9]))
            if "stub-fail" in last and i >= 27:
                return self.ev("failed", "model provider error")
        self.ev("done", "end")

    def do_POST(self):
        if urlsplit(self.path).path == "/__stub/media":
            q = parse_qs(urlsplit(self.path).query)
            slug = q.get("slug", [""])[0]
            MEDIA_POLLS.pop(slug, None)
            MEDIA_MODE[slug] = q.get("mode", [OPTS.media])[0]
            return self.send_json(200, {"ok": True})
        if urlsplit(self.path).path == "/api/chat":
            return self.chat()
        if urlsplit(self.path).path != "/api/public-scan":
            return self.send_json(404, {"error": "not_found"})
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self.send_json(400, {"error": "bad_json"})
        handle, platform = str(req.get("handle", "")), req.get("platform")
        if not HANDLE_RE.match(handle) or platform not in PLATFORMS or req.get("level") != "low":
            return self.send_json(400, {"error": "bad_handle"})
        socials = {k: str(req[k]) for k in ("instagram", "x") if k in req}
        if any(not HANDLE_RE.match(v) for v in socials.values()):
            return self.send_json(400, {"error": "bad_handle"})
        if handle == "stub-429":
            return self.send_json(429, {"error": "rate_limited"})
        if handle == "stub-busy":
            return self.send_json(429, {"error": "busy"})
        self.send_response(200)
        self.cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def ev(name, data):
            self.wfile.write(f"event: {name}\ndata: {data}\n\n".encode())
            self.wfile.flush()

        queries = [handle, f"leaks {handle}", f"porn {handle}"]
        for i in range(8):
            time.sleep(OPTS.delay)
            ev("progress", f"call {i + 1}/8 [{queries[i % 3]}]: +{max(0, 10 - i)} results, +{max(0, 4 - i // 2)} domains")
            if handle == "stub-fail" and i == 3:
                ev("failed", "Google search quota reached, try again later")
                return ev("done", "end")
        r = make_result(handle, platform, empty=handle == "stub-empty")
        if socials:
            r["socials"] = socials
            r["aliases"]["declared"] += list(socials.values())
        STORE[r["slug"]] = r
        ev("result", json.dumps(r))
        ev("done", "end")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8930)
    ap.add_argument("--omit-results", action="store_true")
    ap.add_argument("--omit-profile", action="store_true")
    ap.add_argument("--media", choices=("normal", "relative", "scanhost", "none", "404"), default="normal")
    ap.add_argument("--delay", type=float, default=0.15)
    ap.parse_args(namespace=OPTS)
    no_ig = {**FIXTURE["aliases"], "socials": [x for x in FIXTURE["aliases"]["socials"] if x["platform"] != "instagram"]}
    for slug, overlay in (("demoR3port01", {"mega": MEGA}), ("demoNoProf01", {"profile": None, "aliases": no_ig, "mega": []}),
                          ("demoFoundIG1", {"profile": None, "mega": []}), (EVIL["slug"], {**EVIL, "mega": EVIL_MEGA}),
                          ("demoBrokenT1", {**broken_thumbs(FIXTURE), "mega": []}),
                          ("demoRemove1", {"mega": MEGA, "hits": FIXTURE["hits"] + SOCIAL_HITS}),
                          ("demoHuge0001", {**huge_result(FIXTURE["handle"]), "mega": []}),
                          ("demoVideos01", {**videos_result(FIXTURE["handle"]), "mega": []})):
        seed = {**json.loads(json.dumps(FIXTURE)), **json.loads(json.dumps(overlay)), "slug": slug}
        if OPTS.omit_results:
            seed.pop("results", None)
        if OPTS.omit_profile:
            seed["profile"] = None
        STORE[slug] = seed
    srv = ThreadingHTTPServer(("127.0.0.1", OPTS.port), Handler)
    print(f"scan stub on http://127.0.0.1:{srv.server_address[1]}/", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()

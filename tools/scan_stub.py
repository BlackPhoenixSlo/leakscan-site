#!/usr/bin/env python3
"""Local stand-in for Jaka's scan API + a static server for site/. Stdlib only; for tests and previews.

    python3 tools/scan_stub.py [--port 8930] [--omit-results] [--omit-profile] [--media normal|none|404] [--delay 0.15]
    → open http://127.0.0.1:8930/  (or http://127.0.0.1:8930/scan/?r=demoR3port01, /?r=demoR3port01, /showcase/?r=demoR3port01)

Serves site/ and the API routes of the contract the scan page talks to:
- POST /api/public-scan  {platform, handle, level, instagram?, x?} → SSE over the response body: several `progress`, one
  `result` (tools/fixtures/scan-sample.json with handle/platform/slug swapped in, plus `socials: {instagram?, x?}` echoed
  when sent; a bad instagram / x value → 400 bad_handle), `done`. Magic handles drive the error paths:
  stub-fail → `failed` + `done`; stub-429 → 429 rate_limited; stub-busy → 429 busy; stub-empty → status empty;
  stub-mixed → 3 hits (live true / false / missing) + the results.
- GET /api/scan-result/<slug> → the stored result, 404 {"error":"not_found"} otherwise. Preloaded: demoR3port01 (the
  fixture, with its synthetic `profile`), demoNoProf01 (same, `profile` null: scan-only personalization, no leak-page
  Instagram), demoFoundIG1 (`profile` null, leak-page Instagram fills the IG rows) and evilR3port01
  (fixture overlaid with tools/fixtures/scan-evil.json: script tags, javascript: urls, oversized strings).
  `aliases` {declared, discovered, socials} (alias enrichment) comes from the fixture: discovered handles + the
  socials read off leak pages; stub-mixed / stub-empty carry none.
- GET /api/profile/<slug> → {slug, profile}; GET /api/avatar/<slug> → a generated PNG when profile.avatar is true, else 404.
- GET /api/media/<slug> (demo photos, arrive after the scan) → polls 1-2: {status:"pending", images:[2]}, then
  {status:"ready", images:[6]}; srcs are <this API origin>/api/media/<slug>/<n>.jpg (the portrait
  showcase people photos in site/showcase/imgs, served as webp; the e2e checks the swap by src). evilR3port01
  also lists off-origin / javascript: srcs (must be dropped). --media none → {status:"none", images:[]}; --media 404 → 404.
  POST /__stub/media?slug=<slug>[&mode=normal|relative|none|404] resets that slug's poll counter (and mode) for a test.
- GET /api/thumb?u=<https url> → one of those photos (picked by a hash of u, webp), never fetches u.
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
CHAT_LOG = []
CHAT_ANSWER = (
    "Short answer: it's **€250/month** or **€500 one-time**, and the scan plus one removal come first, free. "
    "Details: [Pricing](#pricing).\n\n"
    "- Message Jaka on [Telegram](https://t.me/jakabasej)\n"
    "- Monthly plan: **weekly re-scans**\n"
    "- Don't click [x](javascript:alert(1)) or [this deal](https://evil.example/phish) or https://evil.example/raw\n\n"
    "Questions about your case? See #contact.")


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
    if empty:
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
    rows = b"".join(b"\x00" + b"".join(a if (x // cell + y // cell) % 2 else b for x in range(w)) for y in range(h))
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
    pre = "" if mode == "relative" else origin   # relative = same-origin "/api/media/..." srcs (site served by the API host)
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
            body = stand_in(src, THUMB_FILES)
            self.send_response(200)
            self.cors()
            self.send_header("Content-Type", "image/webp")
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
    ap.add_argument("--media", choices=("normal", "relative", "none", "404"), default="normal")
    ap.add_argument("--delay", type=float, default=0.15)
    ap.parse_args(namespace=OPTS)
    no_ig = {**FIXTURE["aliases"], "socials": [x for x in FIXTURE["aliases"]["socials"] if x["platform"] != "instagram"]}
    for slug, overlay in (("demoR3port01", {}), ("demoNoProf01", {"profile": None, "aliases": no_ig}),
                          ("demoFoundIG1", {"profile": None}), (EVIL["slug"], EVIL)):
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

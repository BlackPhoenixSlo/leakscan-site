#!/usr/bin/env python3
"""Local stand-in for Jaka's scan API + a static server for site/. Stdlib only; for tests and previews.

    python3 tools/scan_stub.py [--port 8930] [--omit-results] [--delay 0.15]
    → open http://127.0.0.1:8930/  (or http://127.0.0.1:8930/scan/?r=demoR3port01)

Serves site/ and the API routes of the contract the scan page talks to:
- POST /api/public-scan  {platform, handle, level} → SSE over the response body: several `progress`, one `result`
  (tools/fixtures/scan-sample.json with handle/platform/slug swapped in), `done`. Magic handles drive the error paths:
  stub-fail → `failed` + `done`; stub-429 → 429 rate_limited; stub-busy → 429 busy; stub-empty → status empty.
- GET /api/scan-result/<slug> → the stored result, 404 {"error":"not_found"} otherwise (fixture slug preloaded).
- GET /api/thumb?u=<https url> → a generated SVG placeholder (size/colour derived from u), never fetches u.
- CORS on every API response (echoes Origin), OPTIONS preflight answered.

Bypass (declared): every served .html gets `data-api="<stub origin>"` added to its <body> tag, the override the scan
page reads instead of the production API host. The origin is the *other* loopback name (127.0.0.1 <-> localhost),
so the page → API calls are cross-origin and exercise CORS like production. --omit-results drops `results` from the
result (break-it run).
"""
import argparse, hashlib, json, pathlib, random, re, string, sys, time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
FIXTURE = json.loads((ROOT / "tools" / "fixtures" / "scan-sample.json").read_text())
HANDLE_RE = re.compile(r"^[A-Za-z0-9._-]{1,60}$")
PLATFORMS = {"onlyfans.com", "instagram.com", "fansly.com", "tiktok.com", "patreon.com"}
STORE = {}
OPTS = argparse.Namespace(omit_results=False, delay=0.15)


def make_result(handle, platform, empty=False):
    r = json.loads(json.dumps(FIXTURE))
    r.update(handle=handle, platform=platform,
             slug="".join(random.choice(string.ascii_letters + string.digits) for _ in range(12)))
    if empty:
        r.update(status="empty", hit_count=0, domain_count=0, google_total=0, images=[], hits=[], results=[])
    if OPTS.omit_results:
        r.pop("results", None)
    return r


def placeholder_svg(u):
    h = hashlib.sha256(u.encode()).digest()
    w, ht = 300, [220, 300, 400, 450, 260, 380][h[0] % 6]
    c1, c2 = f"hsl({h[1] * 360 // 256} 45% 55%)", f"hsl({h[2] * 360 // 256} 50% 28%)"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{ht}" viewBox="0 0 {w} {ht}">'
            f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{c1}"/>'
            f'<stop offset="1" stop-color="{c2}"/></linearGradient></defs><rect width="100%" height="100%" fill="url(#g)"/>'
            f'<circle cx="{w * (30 + h[3] % 40) // 100}" cy="{ht * 2 // 5}" r="{w // 6}" fill="rgb(255 255 255 / .35)"/>'
            f'<rect x="{w // 4}" y="{ht * 3 // 5}" width="{w // 2}" height="{ht // 4}" rx="20" fill="rgb(255 255 255 / .2)"/>'
            f'</svg>').encode()


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
        if u.path == "/api/thumb":
            src = parse_qs(u.query).get("u", [""])[0]
            if not src.startswith("https://"):
                return self.send_json(400, {"error": "bad_url"})
            body = placeholder_svg(src)
            self.send_response(200)
            self.cors()
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Cache-Control", "max-age=3600")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
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

    def do_POST(self):
        if urlsplit(self.path).path != "/api/public-scan":
            return self.send_json(404, {"error": "not_found"})
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self.send_json(400, {"error": "bad_json"})
        handle, platform = str(req.get("handle", "")), req.get("platform")
        if not HANDLE_RE.match(handle) or platform not in PLATFORMS or req.get("level") != "low":
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
        STORE[r["slug"]] = r
        ev("result", json.dumps(r))
        ev("done", "end")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8930)
    ap.add_argument("--omit-results", action="store_true")
    ap.add_argument("--delay", type=float, default=0.15)
    ap.parse_args(namespace=OPTS)
    seed = json.loads(json.dumps(FIXTURE))
    if OPTS.omit_results:
        seed.pop("results", None)
    STORE[seed["slug"]] = seed
    srv = ThreadingHTTPServer(("127.0.0.1", OPTS.port), Handler)
    print(f"scan stub on http://127.0.0.1:{srv.server_address[1]}/", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()

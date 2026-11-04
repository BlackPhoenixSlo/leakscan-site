"""Local HTTP stand-in for paid upstreams (Google CSE + DeepSeek), used by
tests/test_profile.py, tests/test_media.py, tests/test_chat_landing.py (stream:true SSE)
and the local real-path run. Callers point
cse_scanner.CSE_ENDPOINT / chat_proxy.DEEPSEEK_URL at it (declared bypass).
All data is synthetic.

  python3 tests/upstream_stub.py PORT [valid|dirty|timeout|echo]
"""
import hashlib
import io
import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HANDLE = "mira.example"
CSE_ITEMS = [
    {"title": "Mira Example (@mira.example) • Instagram photos and videos",
     "link": "https://www.instagram.com/mira.example/",
     "snippet": "12.5K Followers, 310 Following, 214 Posts - See Instagram photos and videos from Mira Example"},
    {"title": "Mira Example (@mira.example) | TikTok",
     "link": "https://www.tiktok.com/@mira.example", "snippet": "Watch the latest videos from Mira Example."},
    {"title": "mira.example | Linktree", "link": "https://linktr.ee/mira.example",
     "snippet": "Ceramics, travel diaries and studio vlogs."},
] + [{"title": f"mira.example page {i}", "link": f"https://site{i}.example/models/mira.example",
      "snippet": "synthetic result"} for i in range(1, 25)]

# Google IMAGE search (searchType=image) items: only the official-CDN + non-leak ones may pass.
IG_CDN = "https://scontent-fra5-1.cdninstagram.com/v/t51.29350-15/"
IG_CTX = "https://www.instagram.com/p/"
GOOD_IMAGE_URLS = [IG_CDN + "good1.jpg", IG_CDN + "good2.jpg", "https://i.ytimg.com/vi/xyz/maxresdefault.jpg"]
REJECT_IMAGE_URLS = [
    IG_CDN + "leakctx.jpg",                       # context page on a scan leak domain (site1.example)
    "https://site2.example/img/mira.jpg",         # image host not an official CDN
    "http://scontent.cdninstagram.com/plain.jpg",  # not https
    "https://cdninstagram.com.evil.example/a.jpg",  # suffix trick
]
DROP_IMAGE_URLS = [IG_CDN + "dup.jpg", IG_CDN + "tiny.jpg"]   # same bytes as good1 / 120px


def _img_item(link, ctx):
    return {"title": "Mira Example", "link": link, "displayLink": ctx.split("/")[2],
            "image": {"contextLink": ctx, "thumbnailLink": "https://encrypted-tbn0.gstatic.com/images?q="
                      + hashlib.sha1(link.encode()).hexdigest()[:12]}}


IMAGE_ITEMS = [
    _img_item(GOOD_IMAGE_URLS[0], IG_CTX + "AAA/"),
    _img_item(GOOD_IMAGE_URLS[1], IG_CTX + "BBB/"),
    _img_item(GOOD_IMAGE_URLS[2], "https://www.youtube.com/watch?v=xyz"),
    _img_item(DROP_IMAGE_URLS[0], IG_CTX + "DDD/"),
    _img_item(DROP_IMAGE_URLS[1], IG_CTX + "EEE/"),
    _img_item(REJECT_IMAGE_URLS[0], "https://site1.example/models/mira.example"),
    _img_item(REJECT_IMAGE_URLS[1], IG_CTX + "CCC/"),
    _img_item(REJECT_IMAGE_URLS[2], IG_CTX + "FFF/"),
    _img_item(REJECT_IMAGE_URLS[3], IG_CTX + "GGG/"),
]


def synth(w, h, seed=0, noise=False, exif=False, fmt="JPEG"):
    """Synthetic image bytes (Pillow). noise=True defeats JPEG compression (size-cap tests)."""
    from PIL import Image
    if noise:
        import random
        rnd = random.Random(seed)
        im = Image.frombytes("RGB", (w, h), bytes(rnd.getrandbits(8) for _ in range(w * h * 3)))
    else:
        im = Image.new("RGB", (w, h), ((seed * 53) % 256, (seed * 97) % 256, (seed * 31) % 256))
        im.paste(((seed * 7) % 256, 200, 90), (w // 4, h // 4, w // 2, h // 2))
    buf = io.BytesIO()
    kw = {}
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "SecretCam"          # Make
        ex[0x8825] = {2: (46.0, 3.0, 0.0)}  # GPS IFD
        kw["exif"] = ex.tobytes()
    im.save(buf, fmt, **kw)
    return buf.getvalue()


def cdn_bodies():
    """url -> image bytes for every synthetic CDN url above."""
    good1 = synth(800, 1000, 1, exif=True)
    return {GOOD_IMAGE_URLS[0]: good1, GOOD_IMAGE_URLS[1]: synth(2400, 1800, 2, noise=True),
            GOOD_IMAGE_URLS[2]: synth(1280, 720, 3), DROP_IMAGE_URLS[0]: good1,
            DROP_IMAGE_URLS[1]: synth(120, 120, 4), **{u: synth(600, 600, 9 + i)
                                                     for i, u in enumerate(REJECT_IMAGE_URLS)}}


def ig_grid(n=6):
    return [synth(640, 640, 20 + i) for i in range(n)]


class _CdnResp(io.BytesIO):
    status = 200
    headers = {"Content-Type": "image/jpeg"}

    def getcode(self):
        return 200


class FakeCDN:
    """media_gather.urlopen stand-in (official-CDN wire): url -> synthetic bytes; records urls."""
    def __init__(self, bodies=None):
        self.bodies, self.seen = bodies if bodies is not None else cdn_bodies(), []
        self.lock = threading.Lock()

    def __call__(self, req, timeout=None):
        with self.lock:
            self.seen.append(req.full_url)
        if req.full_url not in self.bodies:
            raise OSError("unreachable " + req.full_url)
        return _CdnResp(self.bodies[req.full_url])


FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
EMBED_SHELL = (b'<!DOCTYPE html><html><head><title id="pageTitle">Instagram</title></head><body>'
               b'<script>requireLazy([],function(){s.handle({"require":[["PolarisEmbedSimple","init",[],'
               b'[{"isRichEmbed":false,"isProfileEmbed":false,"contextJSON":null}]]]});});</script>'
               b'</body></html>')                         # login/"Sorry" shell: no posts


def embed_page(name="ig_embed_profile.html"):
    with open(os.path.join(FIXTURES, name), "rb") as fh:
        return fh.read()


class FakeEmbed:
    """media_gather.page_open stand-in (instagram.com wire): handle -> embed page bytes
    (default: login shell); records (url, headers)."""
    def __init__(self, pages=None):
        self.pages, self.seen = pages or {}, []

    def __call__(self, req, timeout=None):
        self.seen.append((req.full_url, dict(req.header_items())))
        handle = req.full_url.split("/")[3]
        page = self.pages.get(handle, EMBED_SHELL)
        if isinstance(page, BaseException):
            raise page
        return io.BytesIO(page)


VALID = {
    "display_name": "Mira Example", "first_name": "Mira",
    "tagline": "Ceramics, travel diaries and studio vlogs",
    "profession": None, "location": None,
    "bio": "Mira Example shares ceramics, travel diaries and studio vlogs.",
    "about_short": "Mira Example is a creator who shares ceramics work, travel diaries and studio vlogs "
                   "with an audience of about 12.5K followers on Instagram.",
    "followers": 12500,
    "accounts": [{"platform": "instagram", "handle": "mira.example", "url": "https://www.instagram.com/mira.example/"},
                 {"platform": "tiktok", "handle": "mira.example", "url": "https://www.tiktok.com/@mira.example"}],
    "site_domain": "miraexample.com", "confidence": 0.86,
}
DIRTY = {
    "display_name": "M" * 200, "first_name": ["not", "a", "string"],
    "tagline": "Exclusive leaked content and nudes",          # unsafe -> null
    "profession": "Pilot", "location": {"city": "Nowhere"},   # dict -> null
    "bio": "x " * 400, "about_short": 12345,
    "followers": 99999999,                                    # invented -> replaced by source value
    "accounts": [
        {"platform": "instagram", "handle": "mira.example", "url": "http://www.instagram.com/mira.example/"},
        {"platform": "instagram", "handle": "someone.else", "url": "https://www.instagram.com/someone.else/"},
        {"platform": "x", "handle": "mira.example", "url": "https://evil.example/mira.example"},
        {"platform": "myspace", "handle": "mira.example", "url": "https://myspace.com/mira.example"},
        {"platform": "tiktok", "handle": "../../etc", "url": "https://www.tiktok.com/@../../etc"},
        "junk", 7,
    ] + [{"platform": "tiktok", "handle": f"h{i}", "url": f"https://www.tiktok.com/@h{i}"} for i in range(20)],
    "site_domain": "Evil Domain!.net", "confidence": 7, "age": 23, "real_name": "Invented Person",
    "avatar": True, "generated_by": "me", "sources": ["https://evil.example"],
}


class Stub(ThreadingHTTPServer):
    daemon_threads = True
    mode = "valid"
    calls = None
    timeout_sleep = 3.0

    def __init__(self, port=0, mode="valid"):
        super().__init__(("127.0.0.1", port), _H)
        self.mode, self.calls = mode, []
        self.lock = threading.Lock()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server_address[1]}"

    def start(self):
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self


class _H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):  # Google CSE
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        g = lambda k: q.get(k, [""])[0]
        if g("searchType") == "image":
            with self.server.lock:
                self.server.calls.append(("cse_image", g("q"), g("safe"), g("cx")))
            return self._send({"searchInformation": {"totalResults": "9"}, "items": IMAGE_ITEMS})
        with self.server.lock:
            self.server.calls.append(("cse", g("q")))
        self._send({"searchInformation": {"totalResults": "1234"}, "items": CSE_ITEMS})

    def _stream_chat(self, body):
        """DeepSeek stream:true wire shape: role chunk, keepalive, content deltas, [DONE].
        Reply text depends only on which system prompt arrived (landing vs scan app)."""
        landing = "LeakScan landing page" in body["messages"][0]["content"]
        parts = (["Both plans come after the free scan: ", "€250/month or €500 one-time.", "\n",
                  "See [Pricing](#pricing) or ask on [Telegram](https://t.me/jakabasej)."]
                 if landing else ["Your scan ", "is grounded in kb.json."])
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        lines = ['data: {"choices":[{"delta":{"role":"assistant"}}]}', ": keepalive"]
        lines += ["data: " + json.dumps({"choices": [{"delta": {"content": t}}]}) for t in parts]
        lines.append("data: [DONE]")
        for ln in lines:
            self.wfile.write((ln + "\n\n").encode())
            self.wfile.flush()
        self.close_connection = True

    def do_POST(self):  # DeepSeek chat/completions
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        with self.server.lock:
            self.server.calls.append(("llm", body))
        if body.get("stream"):   # chat proxy (chat_proxy.stream_chat); profile calls are stream:false
            return self._stream_chat(body)
        mode = self.server.mode
        if mode == "timeout":
            time.sleep(self.server.timeout_sleep)
            return self._send({"error": "late"}, 504)
        if mode == "echo":   # local run: name/bio from whatever IG data the prompt carried
            src = json.loads(body["messages"][1]["content"].split("\n", 1)[1])
            ig, h = src.get("instagram") or {}, src["scanned_account"]["handle"]
            name = ig.get("full_name")
            out = {"display_name": name, "first_name": (name or "").split(" ")[0] or None,
                   "tagline": None, "bio": ig.get("biography"),
                   "about_short": f"{name or h} is a creator on Instagram." if ig else None,
                   "accounts": [{"platform": "instagram", "handle": h,
                                 "url": f"https://www.instagram.com/{h}/"}] if ig else [],
                   "site_domain": None, "confidence": 0.7 if ig else 0.2}
        else:
            out = VALID if mode == "valid" else DIRTY
        self._send({"choices": [{"message": {"role": "assistant", "content": json.dumps(out)}}],
                    "usage": {"prompt_tokens": len(json.dumps(body)) // 4, "completion_tokens": 200}})


if __name__ == "__main__":
    s = Stub(int(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "valid")
    print(f"stub on {s.base} mode={s.mode}", flush=True)
    s.serve_forever()

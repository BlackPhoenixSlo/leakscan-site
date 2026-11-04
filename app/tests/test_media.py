"""Quick-scan SFW media gather + /api/media endpoints.
Declared bypasses (all synthetic data):
  - Google CSE -> tests/upstream_stub.py HTTP stub (cse_scanner.CSE_ENDPOINT patched)
  - official-CDN image fetches -> stub.FakeCDN at media_gather.urlopen (wire boundary)
  - Instagram embed page -> stub.FakeEmbed at media_gather.page_open (wire boundary), serving
    synthetic fixtures (tests/fixtures/ig_embed_*.html; default: login shell)
  - Browserbase/Instagram -> media_gather.grab_ig_grid monkeypatched (function boundary),
    returns synthetic Pillow images
  - profile page fetches -> profile_extract.urlopen raises (profile falls back / LLM stub)."""
import http.client
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
from PIL import Image  # noqa: E402

import chat_proxy  # noqa: E402
import cse_scanner  # noqa: E402
import db  # noqa: E402
import media_gather as mg  # noqa: E402
import profile_extract as pe  # noqa: E402
import public_app  # noqa: E402
import ratelimit  # noqa: E402
import upstream_stub as stub  # noqa: E402

H = stub.HANDLE
ORIGIN = "https://blackphoenixslo.github.io"
PUB = "https://scan.example.test"


SCAN_ITEMS = [{**it, "host": cse_scanner._host(it["link"])} for it in stub.CSE_ITEMS]


def _no_fetch(req, timeout=None):
    raise OSError("offline")


class _Env(unittest.TestCase):
    """Temp DB/DATA_DIR, CSE stub, fake CDN, gated fake grab_ig_grid."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.saved = (db.DB_PATH, cse_scanner.CSE_ENDPOINT, chat_proxy.DEEPSEEK_URL, public_app.SCAN_LIMITER,
                     public_app.RESULT_LIMITER, pe.urlopen, mg.urlopen, mg.grab_ig_grid, mg.PUBLIC_ORIGIN,
                     mg.MEDIA_ENABLED, mg.MEDIA_BROWSERBASE, mg.page_open, dict(os.environ))
        db.DB_PATH = os.path.join(cls.tmp.name, "t.db")
        db.init_db()
        cls.up = stub.Stub().start()
        cse_scanner.CSE_ENDPOINT = cls.up.base + "/customsearch/v1"
        chat_proxy.DEEPSEEK_URL = cls.up.base + "/chat/completions"
        os.environ.update(GOOGLE_API_KEY="fake", GOOGLE_CSE_ID="fake", GOOGLE_CSE_ID_WEB="fakeweb",
                          DEEPSEEK_API_KEY="fake")
        os.environ.pop("DATA_DIR", None)
        public_app.SCAN_LIMITER = ratelimit.Limiter(rate_per_min=1000, burst=1000, max_concurrent=100)
        public_app.RESULT_LIMITER = ratelimit.Limiter(rate_per_min=10000, burst=1000, max_concurrent=1000)
        pe.urlopen = _no_fetch
        mg.PUBLIC_ORIGIN = PUB

    @classmethod
    def tearDownClass(cls):
        (db.DB_PATH, cse_scanner.CSE_ENDPOINT, chat_proxy.DEEPSEEK_URL, public_app.SCAN_LIMITER,
         public_app.RESULT_LIMITER, pe.urlopen, mg.urlopen, mg.grab_ig_grid, mg.PUBLIC_ORIGIN,
         mg.MEDIA_ENABLED, mg.MEDIA_BROWSERBASE, mg.page_open, env) = cls.saved
        os.environ.clear()
        os.environ.update(env)
        cls.up.shutdown()
        cls.tmp.cleanup()

    def setUp(self):
        self.up.mode = "valid"
        mg.MEDIA_ENABLED, mg.MEDIA_BROWSERBASE = True, True
        self.cdn = stub.FakeCDN()
        mg.urlopen = self.cdn
        self.embed = stub.FakeEmbed()
        mg.page_open = self.embed
        self.gate = threading.Event()
        self.gate.set()
        self.ig_calls = []

        def fake_grab(handle, budget):
            self.ig_calls.append((handle, budget))
            self.gate.wait(20)
            return stub.ig_grid(6)
        mg.grab_ig_grid = fake_grab
        for d in ("media", "media-cache"):
            shutil.rmtree(os.path.join(self.tmp.name, d), ignore_errors=True)


class TestNormalize(unittest.TestCase):
    def test_caps_and_format(self):
        jpeg, w, h = mg.normalize(stub.synth(2400, 1800, 2, noise=True))
        self.assertLessEqual(max(w, h), 1200)
        self.assertLessEqual(len(jpeg), 300 * 1024)
        im = Image.open(io.BytesIO(jpeg))
        self.assertEqual((im.format, im.mode, im.size), ("JPEG", "RGB", (w, h)))
        self.assertGreaterEqual(min(w, h), 200)

    def test_exif_stripped(self):
        src = stub.synth(800, 1000, 1, exif=True)
        self.assertIn(b"SecretCam", src)
        jpeg, _, _ = mg.normalize(src)
        self.assertNotIn(b"SecretCam", jpeg)
        self.assertNotIn(b"Exif\x00\x00", jpeg)
        self.assertEqual(dict(Image.open(io.BytesIO(jpeg)).getexif()), {})

    def test_tiny_and_junk_dropped(self):
        self.assertIsNone(mg.normalize(stub.synth(120, 120)))
        self.assertIsNone(mg.normalize(stub.synth(1000, 150)))
        self.assertIsNone(mg.normalize(b"<html>not an image</html>"))
        self.assertIsNotNone(mg.normalize(stub.synth(300, 300, fmt="PNG")))


class TestPolicy(unittest.TestCase):
    def test_official_cdn(self):
        for ok in ("scontent.cdninstagram.com", "x.fbcdn.net", "p16-sign.tiktokcdn-us.com",
                   "i.ytimg.com", "pbs.twimg.com", "lookaside.instagram.com"):
            self.assertTrue(mg.official_cdn(ok), ok)
        for bad in ("cdninstagram.com.evil.example", "evilcdninstagram.com", "instagram.com",
                    "site1.example", "encrypted-tbn0.gstatic.com", ""):
            self.assertFalse(mg.official_cdn(bad), bad)

    def test_google_rejects_leak_and_non_official(self):
        leak = mg._leak_sets(SCAN_ITEMS)
        items = cse_scanner._parse_image_items({"items": stub.IMAGE_ITEMS})
        ok = [it["full"] for it in items if mg.google_ok(it, leak)]
        for u in stub.REJECT_IMAGE_URLS:
            self.assertNotIn(u, ok)
        self.assertEqual(ok, stub.GOOD_IMAGE_URLS + stub.DROP_IMAGE_URLS)   # dropped later by dedupe/size
        # an image the scan itself returned is never media, even on an official CDN
        leak2 = mg._leak_sets([{"link": stub.GOOD_IMAGE_URLS[0], "host": "site9.example"}])
        self.assertFalse(mg.google_ok(items[0], leak2))

    def test_pick_grid(self):
        cdn = stub.IG_CDN
        items = ([{"src": cdn + "og.jpg?x=1", "w": 640, "h": 640},
                  {"src": "https://scontent.cdninstagram.com/v/t51.2885-19/avatar.jpg", "w": 320, "h": 320},
                  {"src": cdn + "small.jpg", "w": 150, "h": 150},
                  {"src": "https://leak.example/p.jpg", "w": 640, "h": 640}]
                 + [{"src": f"{cdn}g{i}.jpg", "w": 640, "h": 800} for i in range(15)])
        got = mg.pick_grid(items, og_image=cdn + "og.jpg?x=2")
        self.assertEqual(got, [f"{cdn}g{i}.jpg" for i in range(12)])

    def test_ig_handle_and_queries(self):
        prof = {"display_name": "Mira Example",
                "accounts": [{"platform": "tiktok", "handle": "t"}, {"platform": "instagram", "handle": "mira.ig"}]}
        self.assertEqual(mg.ig_handle("onlyfans.com", H, prof), "mira.ig")
        self.assertEqual(mg.ig_handle("instagram.com", H, None), H)
        self.assertIsNone(mg.ig_handle("onlyfans.com", H, None))
        qs = mg.google_queries(H, prof)
        self.assertEqual(len(qs), 2)
        self.assertTrue(all("site:instagram.com OR site:tiktok.com OR site:youtube.com OR site:x.com" in q
                            for q in qs))
        self.assertEqual(len(mg.google_queries(H, {"display_name": "MIRA.EXAMPLE"})), 1)


class TestEmbedParse(unittest.TestCase):
    def test_context_json_tiles_in_order_dedupe_by_path(self):
        got = mg.parse_embed(stub.embed_page().decode())
        names = [u.split("?")[0].rsplit("/", 1)[1] for u in got]
        # covers in post order (tile1 repost + carousel child == cover deduped), then children
        self.assertEqual(names, ["tile0.jpg", "tile1.jpg", "tile2.jpg", "tile4.jpg", "tile5.jpg", "kid0b.jpg"])
        self.assertTrue(all(mg.official_url(u) and not mg.is_profile_pic(u) for u in got))
        self.assertIn("oh=00_1d&", got[1])                 # first occurrence's query kept

    def test_html_tiles_avatar_excluded(self):
        got = mg.parse_embed(stub.embed_page("ig_embed_tiles.html").decode())
        self.assertFalse([u for u in got if "mira_pp" in u or "og_avatar" in u], got)

    def test_html_tiles_unescaped_deduped_official_only(self):
        got = mg.parse_embed(stub.embed_page("ig_embed_tiles.html").decode())
        self.assertFalse([u for u in got if "&amp;" in u])
        grid = [u for u in got if "/grid" in u]
        self.assertEqual([u.split("?")[0].rsplit("/", 1)[1] for u in grid],
                         ["gridA.jpg", "gridC.jpg", "gridF.jpg", "gridG.jpg"])
        self.assertTrue(grid[0].endswith("?stp=dst-jpg_e35&_nc_cat=1&oh=00_A"))
        self.assertEqual(len(mg.parse_embed(stub.embed_page().decode(), cap=2)), 2)

    def test_shells_and_errors_are_not_found(self):
        for page in (stub.EMBED_SHELL.decode(), "<html>app shell, no data</html>",
                     '<script>{"contextJSON":"{\\"context\\":7}"}</script>', '"contextJSON":"{bad', ""):
            self.assertEqual(mg.parse_embed(page), [], page[:40])
        saved = mg.page_open
        try:
            fe = mg.page_open = stub.FakeEmbed({"mira.example": stub.embed_page()})
            self.assertEqual(len(mg.ig_embed_grid("mira.example")), 6)
            url, hdrs = fe.seen[0]
            self.assertEqual(url, "https://www.instagram.com/mira.example/embed/")
            self.assertEqual((hdrs.get("Sec-fetch-mode"), hdrs.get("User-agent")), ("navigate", mg.UA))
            self.assertEqual(mg.ig_embed_grid("nobody"), [])                     # login shell
            self.assertEqual(mg.ig_embed_grid("bad/handle"), [])
            self.assertEqual(len(fe.seen), 2)                                    # invalid handle: no request
            mg.page_open = stub.FakeEmbed({"big": stub.embed_page() + b" " * mg.IG_EMBED_CAP})
            self.assertEqual(mg.ig_embed_grid("big"), [])
            for code in (302, 404):
                mg.page_open = stub.FakeEmbed({"h": urllib.error.HTTPError("u", code, "x", {}, None)})
                self.assertEqual(mg.ig_embed_grid("h"), [])
            mg.page_open = stub.FakeEmbed({"h": urllib.error.HTTPError("u", 503, "x", {}, None)})
            with self.assertRaises(urllib.error.HTTPError):                      # transient: caller won't cache
                mg.ig_embed_grid("h")
        finally:
            mg.page_open = saved


class TestGather(_Env):
    def embed_tiles(self, n):
        """FakeEmbed serves the fixture; FakeCDN gets bytes for its first n tile URLs."""
        self.embed.pages[H] = stub.embed_page()
        urls = mg.parse_embed(stub.embed_page().decode())[:n]
        for i, u in enumerate(urls):
            self.cdn.bodies[u] = stub.synth(640, 800, 40 + i)
        return urls

    def test_embed_first_no_browserbase_when_4_plus(self):
        urls = self.embed_tiles(6)
        self.assertEqual(mg.gather("slugEMB001", "instagram.com", H, stub.VALID, SCAN_ITEMS, budget=60), "ready")
        idx = mg._read_index("slugEMB001")
        self.assertEqual([i["source"] for i in idx["images"]], ["instagram"] * 6 + ["google"] * 3)
        self.assertEqual(self.ig_calls, [])
        self.assertEqual([u for u in self.cdn.seen if u in urls], urls)          # fetched in tile order
        self.assertTrue(os.path.exists(mg._cache_path(mg.cache_key("instagram.com", H))))

    def test_login_shell_or_few_tiles_falls_back_to_browserbase(self):
        mg.gather("slugSHELL1", "instagram.com", H, None, [], budget=60)         # default page: login shell
        self.assertEqual(len(self.ig_calls), 1)
        self.assertEqual([i["source"] for i in mg._read_index("slugSHELL1")["images"]].count("instagram"), 6)
        shutil.rmtree(os.path.join(self.tmp.name, "media-cache"), ignore_errors=True)
        self.embed_tiles(3)                                                      # 3 of 6 downloadable
        mg.gather("slugFEW001", "instagram.com", H, None, [], budget=60)
        self.assertEqual(len(self.ig_calls), 2)
        srcs = [i["source"] for i in mg._read_index("slugFEW001")["images"]]
        self.assertEqual((srcs[:3], len(srcs)), (["instagram"] * 3, mg.MEDIA_MAX))  # 3 embed, google, BB fill

    def test_embed_tiles_all_downloads_failed_not_cached(self):
        self.embed.pages[H] = stub.embed_page()                                  # tiles, CDN has none
        mg.grab_ig_grid = lambda h, b: []
        self.assertEqual(mg.gather("slugDLF001", "instagram.com", H, None, [], budget=60), "ready")  # google
        self.assertFalse(os.path.exists(mg._cache_path(mg.cache_key("instagram.com", H))))
        mg.gather("slugDLF002", "instagram.com", H, None, [], budget=60)
        self.assertEqual(len(self.embed.seen), 2)                                # embed retried, not cached

    def test_google_uses_web_engine_only(self):
        mg.gather("slugWEB001", "onlyfans.com", H, stub.VALID, SCAN_ITEMS, budget=60)
        img = [c for c in self.up.calls if c[0] == "cse_image"]
        self.assertTrue(img)
        self.assertEqual({c[3] for c in img}, {"fakeweb"})
        n = len(img)
        os.environ.pop("GOOGLE_CSE_ID_WEB")
        try:
            shutil.rmtree(os.path.join(self.tmp.name, "media-cache"), ignore_errors=True)
            mg.gather("slugWEB002", "onlyfans.com", H, stub.VALID, SCAN_ITEMS, budget=60)
            self.assertEqual(len([c for c in self.up.calls if c[0] == "cse_image"]), n)   # no CSE image call
            self.assertNotIn("google", {i["source"] for i in mg._read_index("slugWEB002")["images"]})
        finally:
            os.environ["GOOGLE_CSE_ID_WEB"] = "fakeweb"

    def test_public_origin_empty_is_relative(self):
        mg.gather("slugREL001", "instagram.com", H, None, [], budget=60)
        saved = mg.PUBLIC_ORIGIN
        try:
            mg.PUBLIC_ORIGIN = ""
            srcs = [i["src"] for i in mg.public_view("slugREL001")["images"]]
        finally:
            mg.PUBLIC_ORIGIN = saved
        self.assertEqual(sorted(srcs), sorted(f"/api/media/slugREL001/{n}.jpg" for n in range(len(srcs))))
        self.assertGreaterEqual(len(srcs), 6)
        code = "import media_gather as mg; print(repr(mg.PUBLIC_ORIGIN))"
        env = {**os.environ, "PUBLIC_ORIGIN": "", "PYTHONPATH": os.pathsep.join([ROOT, os.path.join(ROOT, "version2site")])}
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.stdout.strip(), "''", out.stderr[-500:])

    def test_google_then_instagram_dedupe_caps(self):
        st = mg.gather("slugAAAA01", "onlyfans.com", H, stub.VALID, SCAN_ITEMS, budget=60)
        self.assertEqual(st, "ready")
        idx = mg._read_index("slugAAAA01")
        srcs = [i["source"] for i in idx["images"]]
        self.assertEqual(srcs, ["google"] * 3 + ["instagram"] * 6)   # dup + tiny dropped
        self.assertEqual(len({i["sha1"] for i in idx["images"]}), 9)
        for i in idx["images"]:
            p = mg.image_path("slugAAAA01", i["n"])
            self.assertLessEqual(os.path.getsize(p), 300 * 1024)
            self.assertLessEqual(max(Image.open(p).size), 1200)
        self.assertEqual(self.ig_calls[0][0], H)
        img_calls = [c for c in self.up.calls if c[0] == "cse_image"][-2:]
        self.assertEqual(len(img_calls), 2)
        self.assertTrue(all(c[2] == "active" for c in img_calls))
        for u in stub.REJECT_IMAGE_URLS:
            self.assertNotIn(u, self.cdn.seen)          # never even fetched

    def test_max_images(self):
        mg.grab_ig_grid = lambda h, b: stub.ig_grid(20)
        mg.gather("slugMAX001", "instagram.com", H, None, [], budget=60)
        self.assertEqual(len(mg._read_index("slugMAX001")["images"]), mg.MEDIA_MAX)

    def test_cache_reuse_skips_browserbase(self):
        mg.gather("slugCACHE1", "onlyfans.com", H, stub.VALID, SCAN_ITEMS, budget=60)
        n_img_calls = len([c for c in self.up.calls if c[0] == "cse_image"])
        self.assertEqual(len(self.ig_calls), 1)
        st = mg.gather("slugCACHE2", "onlyfans.com", H, stub.VALID, SCAN_ITEMS, budget=60)
        self.assertEqual(st, "ready")
        self.assertEqual(len(self.ig_calls), 1)                      # no second session
        self.assertEqual(len([c for c in self.up.calls if c[0] == "cse_image"]), n_img_calls)
        a, b = mg._read_index("slugCACHE1"), mg._read_index("slugCACHE2")
        self.assertEqual(a["images"], b["images"])
        self.assertEqual(open(mg.image_path("slugCACHE2", 0), "rb").read(),
                         open(mg.image_path("slugCACHE1", 0), "rb").read())

    def test_busy_does_google_only_and_failures_are_partial(self):
        self.assertEqual(mg.gather("slugBUSY01", "onlyfans.com", H, stub.VALID, SCAN_ITEMS, budget=60, browser=False),
                         "ready")
        self.assertEqual(self.ig_calls, [])
        self.assertFalse(os.path.exists(mg._cache_path(mg.cache_key("onlyfans.com", H))))  # not cached

        def boom(h, b):
            raise RuntimeError("bb down")
        mg.grab_ig_grid = boom
        self.assertEqual(mg.gather("slugPART01", "onlyfans.com", H, stub.VALID, SCAN_ITEMS, budget=60), "ready")
        self.assertEqual({i["source"] for i in mg._read_index("slugPART01")["images"]}, {"google"})
        mg.urlopen = stub.FakeCDN({})                                   # nothing fetchable
        mg.grab_ig_grid = lambda h, b: []
        self.assertEqual(mg.gather("slugNONE01", "web.com", "nobody", None, [], budget=60), "none")
        self.assertEqual(mg._read_index("slugNONE01")["status"], "none")


class TestHTTP(_Env):
    """Real Handler over HTTP."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), public_app.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        super().tearDownClass()

    def req(self, method, path, body=None, origin=ORIGIN):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        hdrs = {"Origin": origin} if origin else {}
        if body is not None:
            hdrs["Content-Type"] = "application/json"
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=hdrs)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r, data

    def scan(self, platform="onlyfans.com"):
        _, data = self.req("POST", "/api/public-scan", {"handle": H, "platform": platform})
        for block in data.decode().split("\n\n"):
            lines = block.strip().split("\n")
            if lines and lines[0] == "event: result":
                return json.loads("\n".join(l[6:] for l in lines[1:] if l.startswith("data: ")))
        self.fail(data[:500])

    def media(self, slug):
        r, d = self.req("GET", f"/api/media/{slug}")
        return r, json.loads(d)

    def wait_status(self, slug, want, timeout=20):
        t0 = time.time()
        while time.time() - t0 < timeout:
            _, m = self.media(slug)
            if m["status"] == want:
                return m
            time.sleep(0.05)
        self.fail(f"{slug} never reached {want}: {m}")

    def test_pending_then_ready_and_files(self):
        self.gate.clear()                                  # hold the Instagram step
        res = self.scan()
        slug = res["slug"]
        self.assertEqual(res["media"], {"status": "pending"})
        r, m = self.media(slug)
        self.assertEqual((r.status, m["status"], m["slug"]), (200, "pending", slug))
        self.assertEqual(r.getheader("Access-Control-Allow-Origin"), ORIGIN)
        # Google images appear progressively while the IG step is still running
        t0 = time.time()
        while len(m["images"]) < 3 and time.time() - t0 < 10:
            time.sleep(0.05)
            m = self.media(slug)[1]
        self.assertEqual((m["status"], [i["source"] for i in m["images"]]), ("pending", ["google"] * 3))
        _, sr = self.req("GET", f"/api/scan-result/{slug}")
        self.assertEqual(json.loads(sr)["media"], {"status": "pending"})
        self.gate.set()
        m = self.wait_status(slug, "ready")
        self.assertEqual([i["source"] for i in m["images"]], ["instagram"] * 6 + ["google"] * 3)
        self.assertEqual(set(m), {"slug", "status", "images", "updated_at"})
        for im in m["images"]:
            self.assertEqual(set(im), {"src", "w", "h", "source"})
            self.assertRegex(im["src"], rf"^{PUB}/api/media/{slug}/\d+\.jpg$")
            r, d = self.req("GET", im["src"][len(PUB):])
            self.assertEqual(r.status, 200)
            self.assertEqual(r.getheader("Content-Type"), "image/jpeg")
            self.assertEqual(r.getheader("Cache-Control"), "public, max-age=86400")
            self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
            self.assertEqual(r.getheader("Access-Control-Allow-Origin"), ORIGIN)
            self.assertEqual(Image.open(io.BytesIO(d)).size, (im["w"], im["h"]))
        r, _ = self.req("GET", m["images"][0]["src"][len(PUB):], origin="https://evil.example")
        self.assertIsNone(r.getheader("Access-Control-Allow-Origin"))
        _, sr = self.req("GET", f"/api/scan-result/{slug}")
        self.assertEqual(json.loads(sr)["media"], {"status": "ready"})

    def test_disabled_is_none(self):
        mg.MEDIA_ENABLED = False
        res = self.scan()
        self.assertEqual(res["media"], {"status": "none"})
        r, m = self.media(res["slug"])
        self.assertEqual((r.status, m["status"], m["images"]), (200, "none", []))
        self.assertFalse(os.path.exists(mg.media_dir(res["slug"])))
        self.assertEqual(self.ig_calls, [])

    def test_invalid_paths_404(self):
        slug = self.scan()["slug"]
        self.wait_status(slug, "ready")
        for path in ("/api/media/nosuchslug1", "/api/media/bad!slug", "/api/media/", "/api/media/abc",
                     f"/api/media/{slug}/99.jpg", f"/api/media/{slug}/12.jpg", f"/api/media/{slug}/01.jpg",
                     f"/api/media/{slug}/-1.jpg", f"/api/media/{slug}/0.png", f"/api/media/{slug}/index.json",
                     f"/api/media/{slug}/../{slug}/0.jpg", f"/api/media/{slug}/..%2F..%2Ft.db",
                     "/api/media/..%2F..%2Fetc/0.jpg", f"/api/media/{slug}/0.jpg/x", "/api/media/nosuchslug1/0.jpg"):
            r, _ = self.req("GET", path)
            self.assertEqual(r.status, 404, path)
        r, _ = self.req("GET", f"/api/media/{slug}/0.jpg")
        self.assertEqual(r.status, 200)

    def test_deep_scan_never_gathers(self):
        started = []
        saved = (public_app._deep_worker, mg.start)
        mg.start = lambda *a, **k: started.append(a) or "pending"
        public_app._deep_worker = lambda slug, h, p, al, ip, plus=False: (
            public_app.SCAN_LIMITER.release(ip), public_app.GLOBAL_SCANS.release())
        try:
            r, d = self.req("POST", "/api/public-scan", {"handle": H, "level": "deep"})
            self.assertEqual((r.status, json.loads(d)["level"]), (200, "deep"))
            time.sleep(0.3)
            self.assertEqual(started, [])
        finally:
            public_app._deep_worker, mg.start = saved


class TestNoPlaywright(unittest.TestCase):
    def test_app_imports_and_serves_without_playwright(self):
        code = r"""
import os, sys, threading, json, urllib.request, tempfile
sys.modules['playwright'] = None; sys.modules['playwright.sync_api'] = None
os.environ.update(BROWSERBASE_API_KEY='x', BROWSERBASE_PROJECT_ID='y')
import db, public_app, media_gather as mg
from http.server import ThreadingHTTPServer
db.DB_PATH = os.path.join(tempfile.mkdtemp(), 't.db'); db.init_db()
assert mg.grab_ig_grid('mira.example', 60) == []
s = ThreadingHTTPServer(('127.0.0.1', 0), public_app.Handler)
threading.Thread(target=s.serve_forever, daemon=True).start()
print(urllib.request.urlopen(f'http://127.0.0.1:{s.server_address[1]}/healthz').status)
"""
        env = {**os.environ, "PYTHONPATH": os.pathsep.join([ROOT, os.path.join(ROOT, "version2site")])}
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True,
                             text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        self.assertEqual(out.stdout.strip().splitlines()[-1], "200")
        self.assertIn("playwright not installed", out.stderr)


if __name__ == "__main__":
    unittest.main()

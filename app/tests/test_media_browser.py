"""Browserbase Google step (images + web text, one session per scan), profile refine, declared
socials. Declared bypasses (all synthetic data):
  - Browserbase REST -> media_gather._bb_create/_bb_release faked (counts creates/releases)
  - Browserbase CDP -> media_gather._cdp_page yields FakePage (goto/content/evaluate/url/
    context.add_cookies/wait_for_timeout/wait_for_selector/on), serving tests/fixtures/
    google_images.html, google_web.html, google_consent.html; tile clicks and the IG grid
    come back through evaluate(), like the real page
  - official-CDN + Google-thumbnail fetches -> stub.FakeCDN at media_gather.urlopen
  - Instagram embed page -> stub.FakeEmbed at media_gather.page_open
  - Google CSE + DeepSeek -> tests/upstream_stub.py HTTP stub (CSE_ENDPOINT / DEEPSEEK_URL)
  - profile page fetches -> profile_extract.urlopen (offline, or a recording fake)."""
import contextlib
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
import types
import unittest
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import chat_proxy  # noqa: E402
import cse_scanner  # noqa: E402
import db  # noqa: E402
import media_gather as mg  # noqa: E402
import profile_extract as pe  # noqa: E402
import public_app  # noqa: E402
import ratelimit  # noqa: E402
import upstream_stub as stub  # noqa: E402

H = stub.HANDLE
FIX = stub.FIXTURES
SCAN_ITEMS = [{**it, "host": cse_scanner._host(it["link"])} for it in stub.CSE_ITEMS]
LEAK_IMG = "https://leakimg.example/mira.jpg"
CLICKS = {  # docid -> what the preview panel shows after a click
    "D1": {"src": stub.GOOD_IMAGE_URLS[0], "w": 800, "h": 1000},
    "D2": {"src": stub.GOOD_IMAGE_URLS[2], "w": 1280, "h": 720},
    "D3": {"src": stub.REJECT_IMAGE_URLS[0], "w": 600, "h": 600},     # leak-domain tile: never clicked
    "D4": {"src": LEAK_IMG, "w": 600, "h": 600},                       # not an official CDN
    "D7": {"src": stub.IG_CDN + "scanresult.jpg", "w": 600, "h": 600},  # an image the scan returned
}
GRID = [f"{stub.IG_CDN}grid{i}.jpg" for i in range(6)]


def _read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def _no_fetch(req, timeout=None):
    raise OSError("offline")


OVERLAY = '<div role="dialog"><h1>Before you continue to Google</h1><button>Accept all</button></div>'


class FakePage:
    """Playwright page stand-in at the browser wire."""

    def __init__(self, *, cookies_work=True, sorry=0, web=None, images=None, slow=0.0, fail=None, overlay=False):
        self.url, self.html = "about:blank", ""
        self.cookies, self.gotos, self.evals = [], [], []
        self.cookies_work, self.sorry, self.slow, self.fail = cookies_work, sorry, slow, fail
        self.web = _read("google_web.html") if web is None else web
        self.images = _read("google_images.html") if images is None else images
        self.accepted, self.pending = False, None
        self.clicked = []
        self.overlay = overlay      # measured EU shape: in-page dialog over parseable results, blocks clicks
        self.context = types.SimpleNamespace(add_cookies=self._add_cookies)

    def _add_cookies(self, cookies):
        self.cookies += cookies

    def _consented(self):
        socs = any(c["name"] == "SOCS" and c["domain"].endswith("google.com") for c in self.cookies)
        return self.accepted or (socs and self.cookies_work)

    def _serve(self, url):
        if url.startswith("https://www.instagram.com/"):
            return "<html><main>grid</main></html>"
        return self.images if "tbm=isch" in url else self.web

    def goto(self, url, wait_until=None, timeout=None):
        self.gotos.append(url)
        if self.fail and self.fail in url:
            raise RuntimeError("navigation failed")
        if self.slow:
            time.sleep(self.slow)
        if "google.com" in url and self.sorry:
            self.url, self.html, self.pending = "https://www.google.com/sorry/index?continue=x", "sorry", url
            return
        if "google.com" in url and not self._consented() and self.overlay:
            self.url, self.html = url, self._serve(url) + OVERLAY
            return
        if "google.com" in url and not self._consented():
            self.url, self.html, self.pending = "https://consent.google.com/ml?continue=x", _read("google_consent.html"), url
            return
        self.url, self.html = url, self._serve(url)

    def wait_for_timeout(self, ms):
        if self.sorry and "/sorry/" in self.url:
            self.sorry -= 1
            if not self.sorry:                         # Browserbase solved it
                self.goto(self.pending)

    def content(self):
        return self.html

    def evaluate(self, js, arg=None):
        self.evals.append(js)
        if js is mg._ACCEPT_JS:
            if "consent.google.com" in self.url or OVERLAY in self.html:
                self.accepted = True
                self.goto(self.pending)
                return True
            return False
        if js is mg._CLICK_JS:
            self.clicked += arg["ids"]
            if OVERLAY in self.html:
                return {}
            return {i: CLICKS[i] for i in arg["ids"] if i in CLICKS}
        if js is mg._GRID_JS:
            return {"og": None, "items": [{"src": u, "w": 640, "h": 640} for u in GRID]}
        raise AssertionError("unexpected evaluate")

    def wait_for_selector(self, sel, timeout=None):
        return True

    def on(self, event, fn):
        pass


class _Env(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.saved = (db.DB_PATH, cse_scanner.CSE_ENDPOINT, chat_proxy.DEEPSEEK_URL, public_app.SCAN_LIMITER,
                     public_app.RESULT_LIMITER, pe.urlopen, mg.urlopen, mg.page_open, mg.PUBLIC_ORIGIN,
                     mg.MEDIA_ENABLED, mg.MEDIA_BROWSERBASE, mg.MEDIA_GOOGLE, mg._bb_create, mg._bb_release,
                     mg._cdp_page, mg.BB_CREATE_GAP, mg._set_consent, mg._accept_consent, dict(os.environ))
        db.DB_PATH = os.path.join(cls.tmp.name, "t.db")
        db.init_db()
        cls.up = stub.Stub().start()
        cse_scanner.CSE_ENDPOINT = cls.up.base + "/customsearch/v1"
        chat_proxy.DEEPSEEK_URL = cls.up.base + "/chat/completions"
        os.environ.update(GOOGLE_API_KEY="fake", GOOGLE_CSE_ID="fake", GOOGLE_CSE_ID_WEB="fakeweb",
                          DEEPSEEK_API_KEY="fake", BROWSERBASE_API_KEY="fake", BROWSERBASE_PROJECT_ID="fake")
        os.environ.pop("DATA_DIR", None)
        public_app.SCAN_LIMITER = ratelimit.Limiter(rate_per_min=1000, burst=1000, max_concurrent=100)
        public_app.RESULT_LIMITER = ratelimit.Limiter(rate_per_min=10000, burst=1000, max_concurrent=1000)
        pe.urlopen = _no_fetch
        mg.PUBLIC_ORIGIN = "https://scan.example.test"

    @classmethod
    def tearDownClass(cls):
        (db.DB_PATH, cse_scanner.CSE_ENDPOINT, chat_proxy.DEEPSEEK_URL, public_app.SCAN_LIMITER,
         public_app.RESULT_LIMITER, pe.urlopen, mg.urlopen, mg.page_open, mg.PUBLIC_ORIGIN,
         mg.MEDIA_ENABLED, mg.MEDIA_BROWSERBASE, mg.MEDIA_GOOGLE, mg._bb_create, mg._bb_release,
         mg._cdp_page, mg.BB_CREATE_GAP, mg._set_consent, mg._accept_consent, env) = cls.saved
        os.environ.clear()
        os.environ.update(env)
        cls.up.shutdown()
        cls.tmp.cleanup()

    def setUp(self):
        self.up.mode, self.up.alias_items = "valid", {}
        self.n0 = len(self.up.calls)
        mg.MEDIA_ENABLED, mg.MEDIA_BROWSERBASE, mg.MEDIA_GOOGLE, mg.BB_CREATE_GAP = True, True, "browser", 0
        mg._set_consent, mg._accept_consent = self.saved[16], self.saved[17]
        bodies = stub.cdn_bodies()
        bodies.update({u: stub.synth(640, 640, 70 + i) for i, u in enumerate(GRID)})
        bodies[LEAK_IMG] = stub.synth(600, 600, 90)
        bodies[stub.IG_CDN + "scanresult.jpg"] = stub.synth(600, 600, 91)
        self.cdn = mg.urlopen = stub.FakeCDN(bodies)
        self.embed = mg.page_open = stub.FakeEmbed()
        self.creates, self.releases, self.pages, self.lock = [], [], [], threading.Lock()
        self.page_factory = FakePage
        self.hold = threading.Event()
        self.hold.set()

        def create(key, proj, timeout, deadline):
            with self.lock:
                self.creates.append(time.monotonic())
                return {"id": f"s{len(self.creates)}", "connectUrl": "wss://fake"}

        def release(key, proj, sid):
            with self.lock:
                self.releases.append(sid)
            return True

        @contextlib.contextmanager
        def cdp(url, deadline):
            self.hold.wait(20)
            page = self.page_factory()
            with self.lock:
                self.pages.append(page)
            yield page
        mg._bb_create, mg._bb_release, mg._cdp_page = create, release, cdp
        for d in ("media", "media-cache"):
            shutil.rmtree(os.path.join(self.tmp.name, d), ignore_errors=True)

    def llm_calls(self):
        return [c[1] for c in self.up.calls[self.n0:] if c[0] == "llm" and not c[1].get("stream")]

    def new_scan(self, profile=None, socials=None):
        return db.insert_scan([], handle=H, platform="instagram.com",
                              extra={"profile": profile, "results": [], "socials": socials or {}})

    def sources(self):
        return {"handle": H, "platform": "instagram", "instagram": {"full_name": "Mira Example", "followers": 12500,
                "avatar_url": None, "biography": "Ceramics.", "bio_links": []}, "og": None, "google": []}


class TestParsers(unittest.TestCase):
    def test_images_tiles(self):
        tiles = mg.parse_google_images(_read("google_images.html"))
        self.assertEqual([t["docid"] for t in tiles], ["D1", "D2", "D3", "D4", "D5", "D6", "D7"])   # dup dropped
        self.assertTrue(all(t["thumb"].startswith("data:image/jpeg;base64,") for t in tiles))
        self.assertEqual(tiles[1]["host"], "www.youtube.com")

    def test_breadcrumb_labels_cut(self):
        # measured on real Google: breadcrumbs mix path segments with display labels
        cite = '<cite>https://www.redbubble.com &rsaquo; Wall Art &rsaquo; Poster</cite>'
        self.assertEqual(mg._result_url("", cite), "https://www.redbubble.com/")
        cite = '<cite>https://www.cnet.com &rsaquo; culture &rsaquo; kurz-gesagt &rsaquo; ...</cite>'
        self.assertEqual(mg._result_url("", cite), "https://www.cnet.com/culture/kurz-gesagt")

    def test_click_order_resolvable_first(self):
        # measured: video/status previews expose a full-size URL, IG /p/ + channel tiles mostly don't
        ctx = ["https://www.instagram.com/p/A/", "https://www.youtube.com/@chan",
               "https://www.youtube.com/watch?v=x", "https://x.com/a/status/1"]
        ranked = sorted(({"context": c} for c in ctx), key=mg._click_rank)
        self.assertEqual([t["context"] for t in ranked][:2], ctx[2:])

    def test_web_organic_only(self):
        r = mg.parse_google_web(_read("google_web.html"))
        urls = [x["url"] for x in r]
        self.assertEqual(urls[:3], ["https://www.instagram.com/mira.example", "https://miraexample.com/about",
                                    "https://www.youtube.com/@miraexample"])       # cite / direct / /url?q=
        self.assertIn("https://x.com/mira_example", urls)                          # social label
        self.assertNotIn("Reels", [x["title"] for x in r])                         # sitelink (no cite)
        self.assertIn("ceramic artist in Lisbon", r[0]["snippet"])


class TestBrowserGather(_Env):
    def test_default_mode_is_browser(self):
        code = "import media_gather as mg; print(mg.MEDIA_GOOGLE)"
        for val, want in ((None, "browser"), ("bogus", "browser"), ("cse", "cse"), ("OFF", "off")):
            env = {k: v for k, v in os.environ.items() if k != "MEDIA_GOOGLE"}
            if val:
                env["MEDIA_GOOGLE"] = val
            env["PYTHONPATH"] = ROOT
            out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True,
                                 text=True, timeout=60)
            self.assertEqual(out.stdout.strip(), want, out.stderr[-300:])

    def test_one_session_images_text_grid_and_refine(self):
        orig = {"display_name": "Mira Example", "bio": "Old bio.", "avatar": True, "accounts": [], "confidence": 0.6}
        slug = self.new_scan(orig)
        st = mg.gather(slug, "instagram.com", H, orig, SCAN_ITEMS, budget=60, sources=self.sources())
        self.assertEqual(st, "ready")
        self.assertEqual((len(self.creates), self.releases, len(self.pages)), (1, ["s1"], 1))
        page = self.pages[0]
        kinds = ["isch" if "tbm=isch" in u else "web" if "google.com" in u else "ig" for u in page.gotos]
        self.assertEqual(kinds, ["web", "web", "isch", "isch", "ig"])              # b (feeds refine), a, c: one session
        self.assertTrue(all("safe=active" in u for u in page.gotos if "google" in u))
        idx = mg._read_index(slug)
        srcs = [i["source"] for i in idx["images"]]
        self.assertEqual(srcs[:2], ["google", "google"])                          # D1 + D2 full-size
        self.assertEqual(srcs.count("instagram"), 6)
        # snippets: stored, leak/hit/unsafe/google dropped, deduped across the 2 queries
        sn = mg.load_snippets(slug)
        urls = [s["url"] for s in sn]
        self.assertIn("https://miraexample.com/about", urls)
        for bad in ("site2.example", "site7.example", "unsafe-words.example", "google.com"):
            self.assertFalse([u for u in urls if bad in u], bad)
        self.assertEqual(len(urls), len(set(urls)))
        # one refine call carrying the snippets; stored profile is the refined one
        calls = self.llm_calls()
        self.assertEqual(len(calls), 1)
        payload = json.loads(calls[0]["messages"][1]["content"].split("\n", 1)[1])
        self.assertEqual(payload["web_results"], sn)
        prof = db.get_scan(slug) and public_app._scan_extra(slug, "profile")
        self.assertTrue(prof["refined"])
        self.assertEqual(prof["generated_by"], "deepseek")
        self.assertTrue(prof["avatar"])                                           # avatar kept
        self.assertEqual(prof["confidence"], stub.VALID["confidence"])
        self.assertRegex(mg.public_view(slug)["profile_updated_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_leak_and_hit_domains_never_downloaded(self):
        slug = self.new_scan()
        mg.gather(slug, "instagram.com", H, None, SCAN_ITEMS, budget=60)
        page = self.pages[0]
        self.assertNotIn("D3", page.clicked)                     # leak-domain tile not even clicked
        self.assertNotIn("D6", page.clicked)                     # non-official context
        for u in (LEAK_IMG, stub.REJECT_IMAGE_URLS[0]):
            self.assertNotIn(u, self.cdn.seen)
        leak2 = SCAN_ITEMS + [{"link": stub.IG_CDN + "scanresult.jpg", "host": "x.com"}]
        shutil.rmtree(os.path.join(self.tmp.name, "media-cache"), ignore_errors=True)
        self.cdn.seen.clear()
        mg.gather(self.new_scan(), "instagram.com", H, None, leak2, budget=60)
        self.assertNotIn(stub.IG_CDN + "scanresult.jpg", self.cdn.seen)   # a scan result is never media

    def test_thumbnails_only_as_last_resort(self):
        saved = dict(CLICKS)
        CLICKS.clear()                                           # no tile resolves to a full-size URL
        try:
            slug = self.new_scan()
            self.embed.pages[H] = stub.embed_page()             # embed adds 6 -> no grid
            for i, u in enumerate(mg.parse_embed(stub.embed_page().decode())):
                self.cdn.bodies[u] = stub.synth(640, 800, 40 + i)
            mg.gather(slug, "instagram.com", H, None, SCAN_ITEMS, budget=60)
        finally:
            CLICKS.update(saved)
        srcs = [i["source"] for i in mg._read_index(slug)["images"]]
        # official-site tiles' thumbs (D1, D2, D4, D5; D7 is 246x139 < MIN_SIDE), capped at THUMB_BELOW
        self.assertEqual(srcs.count("google"), mg.THUMB_BELOW)
        self.assertEqual(srcs.count("instagram"), 6)
        self.assertEqual(len(self.pages[0].gotos), 2)            # 1 images + 1 web query (no name), no grid

    def test_consent_cookie_then_click_fallback(self):
        mg.gather(self.new_scan(), "instagram.com", H, None, SCAN_ITEMS, budget=60)
        page = self.pages[0]
        self.assertIn("SOCS", [c["name"] for c in page.cookies])
        self.assertNotIn(mg._ACCEPT_JS, page.evals)              # cookie was enough
        self.page_factory = lambda: FakePage(cookies_work=False)
        shutil.rmtree(os.path.join(self.tmp.name, "media-cache"), ignore_errors=True)
        slug = self.new_scan()
        mg.gather(slug, "instagram.com", H, None, SCAN_ITEMS, budget=60)
        page = self.pages[1]
        self.assertIn(mg._ACCEPT_JS, page.evals)
        self.assertTrue(page.accepted)
        self.assertIn("google", [i["source"] for i in mg._read_index(slug)["images"]])
        self.assertTrue(mg.load_snippets(slug))

    def test_consent_overlay_over_results_clicked(self):
        # measured (EU IP): google.com keeps the URL, shows a dialog over results; clicks are blocked
        self.page_factory = lambda: FakePage(cookies_work=False, overlay=True)
        slug = self.new_scan()
        mg.gather(slug, "instagram.com", H, None, SCAN_ITEMS, budget=60)
        page = self.pages[0]
        self.assertTrue(page.accepted)
        self.assertTrue(set(c["src"] for c in CLICKS.values()) & set(self.cdn.seen))   # full-size fetched

    def test_break_consent_noop_only_google_goes_empty(self):
        self.page_factory = lambda: FakePage(cookies_work=False)
        mg._set_consent = lambda page: False
        mg._accept_consent = lambda page: False
        self.embed.pages[H] = stub.embed_page()
        for i, u in enumerate(mg.parse_embed(stub.embed_page().decode())):
            self.cdn.bodies[u] = stub.synth(640, 800, 40 + i)
        slug = self.new_scan()
        self.assertEqual(mg.gather(slug, "instagram.com", H, None, SCAN_ITEMS, budget=60), "ready")
        srcs = [i["source"] for i in mg._read_index(slug)["images"]]
        self.assertEqual(srcs, ["instagram"] * 6)                # embed images still arrive
        self.assertEqual(mg.load_snippets(slug), [])
        self.assertEqual(self.llm_calls(), [])                   # no snippets -> no refine
        self.assertIsNone(mg.public_view(slug)["profile_updated_at"])

    def test_captcha_waits_for_browserbase_solver(self):
        self.page_factory = lambda: FakePage(sorry=3)
        slug = self.new_scan()
        mg.gather(slug, "instagram.com", H, None, SCAN_ITEMS, budget=60)
        self.assertIn("google", [i["source"] for i in mg._read_index(slug)["images"]])

    def test_snippets_capped_and_pruned(self):
        long = "".join(
            f'<div class="MjjYud"><a href="https://site{i}.real/x"><h3 class="LC20lb">Result {i} about Mira</h3>'
            f'<cite>https://site{i}.real &rsaquo; x</cite></a><div class="VwiC3b"><span>{"word " * 120}</span></div></div>'
            for i in range(30))
        self.page_factory = lambda: FakePage(web=f"<html><body>{long}</body></html>")
        slug = self.new_scan()
        mg.gather(slug, "instagram.com", H, None, SCAN_ITEMS, budget=60)
        sn = mg.load_snippets(slug)
        self.assertLessEqual(len(sn), mg.WEB_MAX)
        self.assertLessEqual(sum(len(s["title"]) + len(s["snippet"]) + len(s["url"]) for s in sn), mg.WEB_TEXT_CAP)
        self.assertGreaterEqual(len(sn), 5)
        old = time.time() - 31 * 86400
        os.utime(mg.media_dir(slug), (old, old))
        mg.prune(30)
        self.assertFalse(os.path.exists(mg.snippets_path(slug)))

    def test_no_refine_without_snippets_and_deepseek_down_keeps_profile(self):
        self.page_factory = lambda: FakePage(web="<html><body>no results</body></html>")
        orig = {"display_name": "Mira Example", "bio": "Old bio.", "avatar": False, "accounts": []}
        slug = self.new_scan(orig)
        mg.gather(slug, "instagram.com", H, orig, SCAN_ITEMS, budget=60)
        self.assertEqual(self.llm_calls(), [])
        self.assertEqual(public_app._scan_extra(slug, "profile"), orig)
        self.page_factory = FakePage
        self.up.mode = "timeout"
        self.up.timeout_sleep = 0.2
        shutil.rmtree(os.path.join(self.tmp.name, "media-cache"), ignore_errors=True)
        slug = self.new_scan(orig)
        mg.gather(slug, "instagram.com", H, orig, SCAN_ITEMS, budget=60)
        self.assertEqual(len(self.llm_calls()), 1)
        self.assertEqual(public_app._scan_extra(slug, "profile"), orig)     # DeepSeek failed: kept
        self.assertIsNone(mg.public_view(slug)["profile_updated_at"])
        self.up.timeout_sleep = 3.0

    def test_empty_fields_never_overwrite_good_ones(self):
        self.up.mode = "sparse"
        orig = {"display_name": "Mira Example", "first_name": "Mira", "tagline": "Ceramics", "bio": "Old bio.",
                "about_short": "About.", "location": "Lisbon", "followers": 12500, "site_domain": "miraexample.com",
                "avatar": True, "confidence": 0.7,
                "accounts": [{"platform": "tiktok", "handle": H, "url": f"https://www.tiktok.com/@{H}"}]}
        slug = self.new_scan(orig)
        mg.gather(slug, "instagram.com", H, orig, SCAN_ITEMS, budget=60)
        prof = public_app._scan_extra(slug, "profile")
        for k in ("display_name", "first_name", "tagline", "bio", "about_short", "location", "followers",
                  "site_domain"):
            self.assertEqual(prof[k], orig[k], k)
        self.assertIn({"platform": "tiktok", "handle": H, "url": f"https://www.tiktok.com/@{H}"}, prof["accounts"])
        self.assertEqual((prof["refined"], prof["avatar"], prof["confidence"]), (True, True, 0.4))

    def test_cse_and_off_modes(self):
        mg.MEDIA_GOOGLE = "cse"
        slug = self.new_scan()
        mg.gather(slug, "instagram.com", H, stub.VALID, SCAN_ITEMS, budget=60)
        self.assertEqual([u for u in self.pages[0].gotos if "google" in u], [])   # session: grid only
        self.assertTrue([c for c in self.up.calls if c[0] == "cse_image"])
        self.assertEqual(mg.load_snippets(slug), [])
        mg.MEDIA_GOOGLE = "off"
        n_img = len([c for c in self.up.calls if c[0] == "cse_image"])
        shutil.rmtree(os.path.join(self.tmp.name, "media-cache"), ignore_errors=True)
        self.embed.pages[H] = stub.embed_page()                  # embed >= 4 -> no grid wanted
        for i, u in enumerate(mg.parse_embed(stub.embed_page().decode())):
            self.cdn.bodies[u] = stub.synth(640, 800, 40 + i)
        slug = self.new_scan()
        mg.gather(slug, "instagram.com", H, stub.VALID, SCAN_ITEMS, budget=60)
        self.assertEqual(len(self.creates), 1)                   # off + embed enough: no session at all
        self.assertEqual(len([c for c in self.up.calls if c[0] == "cse_image"]), n_img)
        self.assertEqual({i["source"] for i in mg._read_index(slug)["images"]}, {"instagram"})

    def test_budget_respected(self):
        slug = self.new_scan()
        mg.gather(slug, "instagram.com", H, None, SCAN_ITEMS, budget=15)         # < 20 s left: no session
        self.assertEqual(self.creates, [])
        self.page_factory = lambda: FakePage(slow=1.5)
        t0 = time.monotonic()
        shutil.rmtree(os.path.join(self.tmp.name, "media-cache"), ignore_errors=True)
        mg.gather(self.new_scan(), "instagram.com", H, None, SCAN_ITEMS, budget=22)
        self.assertLess(time.monotonic() - t0, 22 + 2)
        self.assertEqual(self.releases, ["s1"])

    def test_session_released_on_exceptions(self):
        self.page_factory = lambda: FakePage(fail="google.com")   # every Google navigation raises
        slug = self.new_scan()
        self.assertEqual(mg.gather(slug, "instagram.com", H, None, SCAN_ITEMS, budget=60), "ready")
        self.assertEqual(self.releases, ["s1"])
        self.assertEqual({i["source"] for i in mg._read_index(slug)["images"]}, {"instagram"})  # grid still ran
        self.assertFalse(os.path.exists(mg._cache_path(mg.cache_key("instagram.com", H))))      # transient

        @contextlib.contextmanager
        def broken(url, deadline):
            raise RuntimeError("cdp connect failed")
            yield
        mg._cdp_page = broken
        self.assertEqual(mg.gather(self.new_scan(), "instagram.com", H, None, SCAN_ITEMS, budget=60), "none")
        self.assertEqual(self.releases, ["s1", "s2"])                # released although connect failed

    def test_cache_semantics_unchanged(self):
        a = self.new_scan()
        mg.gather(a, "instagram.com", H, None, SCAN_ITEMS, budget=60)
        b = self.new_scan()
        mg.gather(b, "instagram.com", H, None, SCAN_ITEMS, budget=60)
        self.assertEqual(len(self.creates), 1)                    # cache hit: no second session
        self.assertEqual(mg._read_index(a)["images"], mg._read_index(b)["images"])
        self.assertEqual(mg.load_snippets(a), mg.load_snippets(b))   # snippets travel with the cache
        self.assertEqual(len(self.llm_calls()), 2)                # each scan's profile refined once

    def test_concurrent_scans_respect_session_cap(self):
        self.hold.clear()
        mg.BB_CREATE_GAP = 0.2
        slugs = [self.new_scan() for _ in range(3)]
        for i, s in enumerate(slugs):
            self.assertEqual(mg.start(s, "instagram.com", f"{H}{i}", None, SCAN_ITEMS), "pending")
        t0 = time.time()
        while len(self.creates) < 2 and time.time() - t0 < 10:
            time.sleep(0.02)
        time.sleep(0.5)
        self.assertEqual(len(self.creates), 2)                    # MAX_GATHERS sessions, third ran browserless
        self.assertGreaterEqual(self.creates[1] - self.creates[0], 0.19)   # creates serialized
        self.hold.set()
        t0 = time.time()
        while any(mg.public_view(s)["status"] == "pending" for s in slugs) and time.time() - t0 < 30:
            time.sleep(0.05)
        self.assertEqual(sorted(self.releases), ["s1", "s2"])


class TestSocials(_Env):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), public_app.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        super().tearDownClass()

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=60)
        c.request(method, path, body=json.dumps(body) if body is not None else None,
                  headers={"Content-Type": "application/json"} if body is not None else {})
        r = c.getresponse()
        d = r.read()
        c.close()
        return r, d

    def scan(self, body):
        _, data = self.req("POST", "/api/public-scan", body)
        for block in data.decode().split("\n\n"):
            lines = block.strip().split("\n")
            if lines and lines[0] == "event: result":
                return json.loads("\n".join(l[6:] for l in lines[1:] if l.startswith("data: ")))
        self.fail(data[:500])

    def wait_ready(self, slug):
        t0 = time.time()
        while time.time() - t0 < 30:
            m = json.loads(self.req("GET", f"/api/media/{slug}")[1])
            if m["status"] != "pending":
                return m
            time.sleep(0.05)
        self.fail("media never settled")

    def test_clean_socials_forms(self):
        c = public_app.clean_socials
        self.assertEqual(c({"instagram": "@mira.ig", "x": "https://twitter.com/mira_x?s=20"}),
                         {"instagram": "mira.ig", "x": "mira_x"})
        self.assertEqual(c({"instagram": "https://www.instagram.com/mira.ig/", "x": "x.com/@mira_x"}),
                         {"instagram": "mira.ig", "x": "mira_x"})
        self.assertEqual(c({"instagram": "bad handle!", "x": 7}), {})
        self.assertEqual(c({"instagram": "https://evil.example/mira"}), {})
        self.assertEqual(public_app.quick_aliases([H], {"instagram": H.upper(), "x": "mira_x"}), [H, "mira_x"])

    def test_declared_socials_widen_scan_and_feed_profile_and_media(self):
        self.up.mode = "echo"
        self.up.alias_items = {"mira.ig": [{"title": "mira.ig leaks", "link": "https://aliasleak.example/mira.ig"}],
                               "mira_x": [{"title": "mira_x", "link": "https://xleak.example/mira_x"}]}
        seen = []

        def fetch(req, timeout=None):
            seen.append((req.full_url, req.get_header("User-agent")))
            if req.full_url == "https://www.instagram.com/mira.ig/":
                body = (b'<meta property="og:title" content="Mira IG (@mira.ig) &bull; Instagram photos and videos">'
                        b'<meta property="og:description" content="9K Followers, 10 Following - mira.ig">')
                return stub._CdnResp(body)
            raise OSError("offline")
        pe.urlopen = fetch
        try:
            res = self.scan({"handle": H, "platform": "onlyfans.com", "level": "low",
                             "instagram": "https://instagram.com/mira.ig", "x": "@mira_x"})
        finally:
            pe.urlopen = _no_fetch
        self.assertEqual(res["socials"], {"instagram": "mira.ig", "x": "mira_x"})
        q = [c[1] for c in self.up.calls if c[0] == "cse"]
        self.assertIn("mira.ig", [x.split(" -site:")[0] for x in q])
        self.assertIn("mira_x", [x.split(" -site:")[0] for x in q])
        alias = {h["domain"]: h["alias"] for h in res["hits"]}
        self.assertEqual((alias["aliasleak.example"], alias["xleak.example"]), ("mira.ig", "mira_x"))
        self.assertEqual(alias["site1.example"], H)
        self.assertEqual(res["hit_count"], len(res["hits"]))
        self.assertIn(("https://www.instagram.com/mira.ig/", pe.CRAWLER_UA), seen)   # declared IG og first
        accs = res["profile"]["accounts"]
        self.assertEqual(accs[0], {"platform": "instagram", "handle": "mira.ig",
                                   "url": "https://instagram.com/mira.ig"})
        self.assertIn({"platform": "x", "handle": "mira_x", "url": "https://x.com/mira_x"}, accs[:2])
        self.assertEqual(res["profile"]["display_name"], "Mira IG")
        sr = json.loads(self.req("GET", f"/api/scan-result/{res['slug']}")[1])
        self.assertEqual(sr["socials"], {"instagram": "mira.ig", "x": "mira_x"})
        m = self.wait_ready(res["slug"])
        self.assertIn("mira.ig/embed/", " ".join(u for u, _ in self.embed.seen))   # OF scan ran the IG steps
        self.assertTrue(any(u == "https://www.instagram.com/mira.ig/" for p in self.pages for u in p.gotos))
        # refined profile visible through the API, flagged, declared account still first
        self.assertTrue(m["profile_updated_at"])
        prof = json.loads(self.req("GET", f"/api/profile/{res['slug']}")[1])["profile"]
        self.assertTrue(prof["refined"])
        self.assertEqual(prof["accounts"][0]["handle"], "mira.ig")
        self.assertEqual(json.loads(self.req("GET", f"/api/scan-result/{res['slug']}")[1])["profile"], prof)

    def test_ig_handle_prefers_declared(self):
        prof = {"accounts": [{"platform": "instagram", "handle": "llm.guess"}]}
        self.assertEqual(mg.ig_handle("onlyfans.com", H, prof, {"instagram": "mira.ig"}), "mira.ig")
        self.assertEqual(mg.ig_handle("onlyfans.com", H, prof, {"instagram": "bad/x"}), "llm.guess")

    def test_invalid_socials_ignored_and_single_alias(self):
        res = self.scan({"handle": H, "platform": "onlyfans.com", "instagram": "not valid!", "x": ""})
        self.assertEqual(res["socials"], {})
        self.assertEqual({h["alias"] for h in res["hits"]}, {H})


if __name__ == "__main__":
    unittest.main()

"""One-origin routing: landing site (site_static) + legacy UI at /app/ + API untouched."""
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db
import public_app
import site_static


class TestSiteRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = cls.tmp.name
        site = os.path.join(root, "site")
        os.makedirs(os.path.join(site, "scan"))
        os.makedirs(os.path.join(site, "css"))
        os.makedirs(os.path.join(site, "video"))
        for rel, body in {"index.html": "<h1>landing LeakScan</h1>", "scan/index.html": "scan page",
                          "404.html": "custom 404", "css/a.css": "b{}", "video/p.png": "png", ".env": "SECRET=1",
                          "scan/v.mp4": "0123456789", "video/jack.webm": "abcdefghij"}.items():
            with open(os.path.join(site, rel), "w") as f:
                f.write(body)
        with open(os.path.join(root, "outside.txt"), "w") as f:
            f.write("outside")
        os.symlink(os.path.join(root, "outside.txt"), os.path.join(site, "link.txt"))
        cls.saved = (site_static.SITE_DIR, db.DB_PATH)
        site_static.SITE_DIR = os.path.realpath(site)
        db.DB_PATH = os.path.join(root, "t.db")
        db.init_db()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), public_app.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        site_static.SITE_DIR, db.DB_PATH = cls.saved
        cls.tmp.cleanup()

    def req(self, path, method="GET", headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=5)
        c.request(method, path, headers=headers or {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r, body

    def test_landing_at_root(self):
        r, b = self.req("/")
        self.assertEqual((r.status, b), (200, b"<h1>landing LeakScan</h1>"))
        self.assertEqual(r.getheader("Content-Type"), "text/html; charset=utf-8")
        self.assertEqual(r.getheader("Cache-Control"), "no-cache")

    def test_dir_index_and_slash_redirect(self):
        self.assertEqual(self.req("/scan/")[1], b"scan page")
        r, _ = self.req("/scan?r=abc")
        self.assertEqual((r.status, r.getheader("Location")), (301, "/scan/?r=abc"))

    def test_asset_cache(self):   # js / css revalidate (a deploy reaches returning visitors at once), images cache a day
        r, b = self.req("/css/a.css")
        self.assertEqual((r.status, b), (200, b"b{}"))
        self.assertEqual(r.getheader("Cache-Control"), "no-cache")
        self.assertTrue(r.getheader("Content-Type").startswith("text/css"))
        lm = r.getheader("Last-Modified")
        r, b = self.req("/css/a.css", headers={"If-Modified-Since": lm})
        self.assertEqual((r.status, b, r.getheader("Cache-Control")), (304, b"", "no-cache"))
        r, b = self.req("/css/a.css", headers={"If-Modified-Since": "Thu, 01 Jan 1970 00:00:00 GMT"})
        self.assertEqual((r.status, b), (200, b"b{}"))
        self.assertEqual(self.req("/video/p.png")[0].getheader("Cache-Control"), "public, max-age=86400")

    def test_video_ranges(self):   # site/video/: Safari plays <video> only with 206 ranges; seeking needs them
        r, b = self.req("/scan/v.mp4")
        self.assertEqual((r.status, b, r.getheader("Content-Type"), r.getheader("Accept-Ranges")), (200, b"0123456789", "video/mp4", "bytes"))
        for rng, part, cr in (("bytes=2-4", b"234", "bytes 2-4/10"), ("bytes=7-", b"789", "bytes 7-9/10"),
                              ("bytes=-2", b"89", "bytes 8-9/10"), ("bytes=5-99", b"56789", "bytes 5-9/10")):
            r, b = self.req("/scan/v.mp4", headers={"Range": rng})
            self.assertEqual((r.status, b, r.getheader("Content-Range"), r.getheader("Content-Length")), (206, part, cr, str(len(part))), rng)
        r, _ = self.req("/scan/v.mp4", headers={"Range": "bytes=10-"})
        self.assertEqual((r.status, r.getheader("Content-Range")), (416, "bytes */10"))
        r, b = self.req("/scan/v.mp4", headers={"Range": "bytes=1-2,4-5"})   # multi-range: full body
        self.assertEqual((r.status, b), (200, b"0123456789"))
        r, b = self.req("/video/jack.webm")   # the video page's take (WebM only)
        self.assertEqual((r.status, b, r.getheader("Content-Type"), r.getheader("Accept-Ranges")), (200, b"abcdefghij", "video/webm", "bytes"))
        r, b = self.req("/video/jack.webm", headers={"Range": "bytes=3-5"})
        self.assertEqual((r.status, b, r.getheader("Content-Type"), r.getheader("Content-Range")), (206, b"def", "video/webm", "bytes 3-5/10"))
        r, b = self.req("/nope.mp4", headers={"Range": "bytes=0-1"})          # 404 page ignores Range
        self.assertEqual((r.status, b), (404, b"custom 404"))

    def test_missing_is_custom_404(self):
        r, b = self.req("/nope.html")
        self.assertEqual((r.status, b), (404, b"custom 404"))

    def test_no_traversal_dotfiles_or_symlink_escape(self):
        for p in ("/..%2foutside.txt", "/../outside.txt", "/scan/../../outside.txt", "/.env",
                  "/%2e%2e/outside.txt", "/link.txt", "/..%5coutside.txt", "/app/../db.py",
                  "/static/../db.py", "/static/..%2fdb.py", "/a%00.html"):
            r, b = self.req(p)
            self.assertEqual(r.status, 404, p)
            self.assertNotIn(b"outside", b, p)
            self.assertNotIn(b"SECRET", b, p)
            self.assertNotIn(b"import", b, p)

    def test_head(self):
        r, b = self.req("/", "HEAD")
        self.assertEqual((r.status, b), (200, b""))
        self.assertEqual(r.getheader("Content-Length"), str(len("<h1>landing LeakScan</h1>")))
        r, b = self.req("/app/", "HEAD")
        self.assertEqual((r.status, b), (200, b""))

    def test_legacy_ui_under_app(self):
        r, b = self.req("/app/")
        self.assertEqual(r.status, 200)
        self.assertIn(b'id="app-config"', b)          # config injected like the old /
        self.assertIn(b'src="/static/app.js"', b)
        r, _ = self.req("/app?go=1")
        self.assertEqual((r.status, r.getheader("Location")), (301, "/app/?go=1"))
        r, b = self.req("/app/styles.css")
        self.assertEqual(r.status, 200)

    def test_prefill_redirect(self):
        r, _ = self.req("/?p=instagram&h=jane&go=1")
        self.assertEqual((r.status, r.getheader("Location")), (302, "/app/?p=instagram&h=jane&go=1"))
        r, _ = self.req("/?utm_source=x")
        self.assertEqual(r.status, 200)                 # other queries stay on the landing

    def test_api_paths_unchanged(self):
        r, b = self.req("/healthz")
        self.assertEqual((r.status, json.loads(b)["ok"]), (200, True))
        r, b = self.req("/api/scan-result/nonexistent")
        self.assertEqual(r.status, 404)
        self.assertTrue(r.getheader("Content-Type").startswith("application/json"))
        r, _ = self.req("/static/app.js")
        self.assertEqual(r.status, 200)
        r, _ = self.req("/api/unknown")
        self.assertEqual(r.status, 404)
        self.assertEqual(self.req("/healthz", "HEAD")[0].status, 501)   # as before

    def test_post_to_site_path_rejected(self):
        self.assertEqual(self.req("/", "POST")[0].status, 404)
        self.assertEqual(self.req("/", "PUT")[0].status, 501)

    def test_site_dir_missing_falls_back_to_legacy_root(self):
        saved = site_static.SITE_DIR
        site_static.SITE_DIR = os.path.join(self.tmp.name, "missing")
        try:
            r, b = self.req("/")
            self.assertEqual(r.status, 200)
            self.assertIn(b'id="app-config"', b)
            self.assertEqual(self.req("/scan/")[0].status, 404)
        finally:
            site_static.SITE_DIR = saved


if __name__ == "__main__":
    unittest.main()

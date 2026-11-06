import http.client
import io
import os
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cse_scanner
import db
import public_app

ORIGIN = "https://blackphoenixslo.github.io"
THUMB = "https://encrypted-tbn0.gstatic.com/images?q=tbn:abc"


def item(link, title="", video=False, image=None, host=None):
    return {"link": link, "title": title, "snippet": "s", "video": video,
            "image": image, "host": host or cse_scanner._host(link)}


class TestKind(unittest.TestCase):
    def test_video(self):
        for it in (item("https://a.com/p/1", video=True),
                   item("https://a.com/video/123"),
                   item("https://a.com/videos/x"),
                   item("https://a.com/watch?v=1"),
                   item("https://cdn.a.com/f.mp4"),
                   item("https://cdn.a.com/f.m3u8?t=1"),
                   item("https://a.com/embed/9"),
                   item("https://a.com/clip-7"),
                   item("https://a.com/vod/x"),
                   item("https://a.com/p", title="Leaked Video of x"),
                   item("https://a.com/p", title="new clips")):
            self.assertEqual(public_app.result_kind(it), "video", it)

    def test_page(self):
        for it in (item("https://a.com/models/x", title="x onlyfans leaks"),
                   item("https://a.com/videography", title="Videographer"),
                   item("https://a.com/watchlist/x", title="list"),
                   item("https://a.com/embedded-gallery", title="x")):
            self.assertEqual(public_app.result_kind(it), "page", it)

    def test_parse_items_keeps_video_flag(self):
        d = {"items": [
            {"link": "https://a.com/1", "title": "t", "pagemap": {"videoobject": [{"name": "v"}],
             "cse_thumbnail": [{"src": THUMB}]}},
            {"link": "https://b.com/2", "title": "t"}]}
        got = cse_scanner._parse_items(d)
        self.assertEqual([g["video"] for g in got], [True, False])
        self.assertEqual(got[0]["image"], THUMB)


class TestShapeResults(unittest.TestCase):
    def test_shape(self):
        out = public_app.shape_results([
            item("https://cdn.leak.co.uk/a/b", title="T" * 300, image=THUMB),
            item("https://cdn.leak.co.uk/a/b"),                       # dup link dropped
            item("https://x.com/v/1", image="http://encrypted-tbn0.gstatic.com/x"),
            item("https://y.com/1", image="https://evil.example/x.jpg", video=True),
            {"title": "no link"},
        ])
        self.assertEqual(len(out), 3)
        self.assertEqual(set(out[0]), {"title", "link", "snippet", "thumb", "domain", "kind"})
        self.assertEqual(out[0]["domain"], "leak.co.uk")
        self.assertEqual(out[0]["thumb"], THUMB)
        self.assertEqual(len(out[0]["title"]), 200)
        self.assertIsNone(out[1]["thumb"])                           # http -> null
        self.assertIsNone(out[2]["thumb"])                           # non-gstatic -> null
        self.assertEqual([o["kind"] for o in out], ["page", "page", "video"])

    def test_cap(self):
        many = [item(f"https://s{i}.com/p") for i in range(200)]
        self.assertEqual(len(public_app.shape_results(many)), 80)
        self.assertEqual(public_app.shape_results(None), [])


class TestCors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.tmp.name, "t.db")
        db.init_db()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), public_app.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.tmp.cleanup()

    def req(self, method, path, origin):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=5)
        c.request(method, path, headers={"Origin": origin} if origin else {})
        r = c.getresponse()
        r.read()
        c.close()
        return r

    def test_preflight_allowed(self):
        r = self.req("OPTIONS", "/api/public-scan", ORIGIN)
        self.assertEqual(r.status, 204)
        self.assertEqual(r.getheader("Access-Control-Allow-Origin"), ORIGIN)
        self.assertIn("POST", r.getheader("Access-Control-Allow-Methods"))
        self.assertEqual(r.getheader("Access-Control-Allow-Headers"), "Content-Type")

    def test_preflight_unknown_origin(self):
        r = self.req("OPTIONS", "/api/public-scan", "https://evil.example")
        self.assertEqual(r.status, 204)
        self.assertIsNone(r.getheader("Access-Control-Allow-Origin"))
        self.assertIsNone(r.getheader("Access-Control-Allow-Methods"))

    def test_json_carries_cors(self):
        r = self.req("GET", "/api/scan-result/nonexistent", ORIGIN)
        self.assertEqual(r.status, 404)
        self.assertEqual(r.getheader("Access-Control-Allow-Origin"), ORIGIN)
        self.assertEqual(r.getheader("Vary"), "Origin")

    def test_thumb_cors_and_vary(self):
        # the report reads thumb pixels (people-photo check) via a CORS load: allowed origin gets ACAO, and every
        # thumb response varies on Origin so a plain (no-Origin) cached copy never answers the CORS load
        class Resp(io.BytesIO):
            headers = {"Content-Type": "image/jpeg"}
            def __enter__(self): return self
            def __exit__(self, *a): pass
        class Opener:
            def open(self, req, timeout=None): return Resp(b"\xff\xd8jpeg")
        old, public_app._THUMB_OPENER = public_app._THUMB_OPENER, Opener()
        try:
            path = "/api/thumb?u=" + urllib.parse.quote(THUMB, safe="")
            r = self.req("GET", path, ORIGIN)
            self.assertEqual(r.status, 200)
            self.assertEqual(r.getheader("Access-Control-Allow-Origin"), ORIGIN)
            self.assertEqual(r.getheaders().count(("Vary", "Origin")), 1)
            r = self.req("GET", path, None)
            self.assertEqual(r.status, 200)
            self.assertIsNone(r.getheader("Access-Control-Allow-Origin"))
            self.assertEqual(r.getheader("Vary"), "Origin")
        finally:
            public_app._THUMB_OPENER = old


if __name__ == "__main__":
    unittest.main()

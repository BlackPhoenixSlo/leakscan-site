"""/api/thumb-sheet/<slug> on the real Handler; upstream faked at the opener (the wire boundary of api_thumb's fetch)."""
import http.client
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db
import public_app
import thumb_sheet

G = "https://encrypted-tbn0.gstatic.com/images?q=tbn:"


class Up:
    """Stands in for _THUMB_OPENER: url → bytes / an exception; counts every fetch."""
    def __init__(self):
        self.calls, self.lock, self.delay, self.answers = [], threading.Lock(), 0, {}

    def open(self, req, timeout=None):
        u = req.full_url
        with self.lock:
            self.calls.append(u)
        time.sleep(self.delay)
        a = self.answers.get(u, b"img:" + u.encode())
        if isinstance(a, Exception):
            raise a
        ctype, body = a if isinstance(a, tuple) else ("image/jpeg; x=1", a)
        r = io.BytesIO(body)
        r.headers = {"Content-Type": ctype}
        r.__enter__ = lambda: r
        return _Ctx(r)


class _Ctx:
    def __init__(self, r):
        self.r = r

    def __enter__(self):
        return self.r

    def __exit__(self, *a):
        return False


def http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, None)


def parse(body):
    n = int(body[:8])
    m = json.loads(body[8:8 + n])
    at, got = 8 + n, {}
    for src, t, size in m["cells"]:
        got[src] = (t, body[at:at + size])
        at += size
    assert at == len(body)
    return m, got


class TestThumbSheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.saved = (db.DB_PATH, public_app._THUMB_OPENER, public_app.CORS_ORIGINS, os.environ.get("DATA_DIR"))
        db.DB_PATH = os.path.join(cls.tmp.name, "t.db")
        os.environ["DATA_DIR"] = cls.tmp.name
        db.init_db()
        public_app.CORS_ORIGINS = {"https://site.example"}
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), public_app.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        db.DB_PATH, public_app._THUMB_OPENER, public_app.CORS_ORIGINS, d = cls.saved
        if d is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = d
        cls.tmp.cleanup()

    def setUp(self):
        self.up = public_app._THUMB_OPENER = Up()
        self.saved_row, self.rows = public_app.scan_row, {}
        public_app.scan_row = lambda slug: self.rows.get(slug)
        thumb_sheet.LIMITER = thumb_sheet.ratelimit.Limiter(rate_per_min=6000, burst=1000, max_concurrent=1000)
        for n in os.listdir(thumb_sheet.cache_dir()) if os.path.isdir(thumb_sheet.cache_dir()) else []:
            os.remove(os.path.join(thumb_sheet.cache_dir(), n))

    def tearDown(self):
        public_app.scan_row = self.saved_row

    def row(self, slug, images=(), results=(), status="complete", level="low"):
        self.rows[slug] = {"slug": slug, "status": status, "level": level, "images": list(images), "results": list(results)}

    def get(self, slug, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        c.request("GET", "/api/thumb-sheet/" + slug, headers=headers or {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r, body

    def test_cells_are_the_original_bytes_in_the_clients_order(self):
        self.up.answers[G + "b"] = ("image/png", b"\x89PNG-original")
        self.row("slug0001", [G + "a", G + "b", G + "a"], [{"thumb": G + "c"}, {"thumb": G + "b"}, {"thumb": None}, {"thumb": "http://x.gstatic.com/h"}, {"thumb": "https://evil.example/x"}])
        r, body = self.get("slug0001", {"Origin": "https://site.example"})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.getheader("Access-Control-Allow-Origin"), "https://site.example")
        self.assertEqual(r.getheader("Cache-Control"), "public, max-age=86400")
        m, got = parse(body)
        self.assertEqual([c[0] for c in m["cells"]], [G + "a", G + "b", G + "c"])
        self.assertEqual(got[G + "b"], ("image/png", b"\x89PNG-original"))
        self.assertEqual(got[G + "a"][0], "image/jpeg")
        self.assertEqual(sorted(self.up.calls), [G + "a", G + "b", G + "c"])   # the allowlist as api_thumb's: nothing else fetched

    def test_dead_only_what_api_thumb_refuses_for_good(self):
        self.up.answers.update({G + "404": http_error(404), G + "html": ("text/html", b"<html>"), G + "big": b"x" * (public_app.THUMB_MAX_BYTES + 1),
                                G + "500": http_error(500), G + "429": http_error(429), G + "net": OSError("reset")})
        self.row("slug0002", [G + k for k in ("ok", "404", "html", "big", "500", "429", "net")])
        r, body = self.get("slug0002")
        m, got = parse(body)
        self.assertEqual(list(got), [G + "ok"])
        self.assertEqual(sorted(m["dead"]), sorted(G + k for k in ("404", "html", "big")))   # 500 / 429 / net: per-thumb in the client
        self.assertEqual(r.getheader("Cache-Control"), "public, max-age=300")   # gaps: briefly
        self.assertEqual(self.get("slug0002")[1], body)
        self.assertEqual(len(self.up.calls), 7)                                 # served from disk

    def test_gaps_are_not_kept_past_their_ttl(self):
        self.up.answers[G + "x"] = http_error(503)
        self.row("slug0003", [G + "x", G + "y"])
        self.assertEqual(len(parse(self.get("slug0003")[1])[1]), 1)
        key = [n for n in os.listdir(thumb_sheet.cache_dir()) if n.endswith(".gaps")][0]
        old = time.time() - thumb_sheet.GAPS_S - 1
        os.utime(os.path.join(thumb_sheet.cache_dir(), key), (old, old))
        del self.up.answers[G + "x"]
        r, body = self.get("slug0003")
        self.assertEqual(len(parse(body)[1]), 2)
        self.assertEqual(r.getheader("Cache-Control"), "public, max-age=86400")

    def test_deadline_what_came_is_the_sheet_the_rest_per_thumb(self):
        self.addCleanup(setattr, thumb_sheet, "BUILD_S", thumb_sheet.BUILD_S)
        thumb_sheet.BUILD_S, self.up.delay = 0.2, 0.5
        self.row("slug0009", [G + str(i) for i in range(40)])   # at the deadline: POOL running, the rest queued
        r, body = self.get("slug0009")
        m, got = parse(body)
        self.assertEqual((r.status, got, m["dead"], r.getheader("Cache-Control")), (200, {}, [], "public, max-age=300"))
        self.assertEqual(len(self.up.calls), thumb_sheet.POOL)  # the queued ones never went out

    def test_caps_past_them_nothing_said_so_the_client_goes_per_thumb(self):
        urls = [G + str(i) for i in range(thumb_sheet.MAX_CELLS + 5)]
        self.row("slug0004", urls)
        m, got = parse(self.get("slug0004")[1])
        self.assertEqual(list(got), urls[:thumb_sheet.MAX_CELLS])
        self.assertEqual(m["dead"], [])
        self.up.answers[G + "huge"] = b"x" * (thumb_sheet.MAX_CELL_BYTES + 1)
        self.row("slug0005", [G + "huge", G + "fine"])
        m, got = parse(self.get("slug0005")[1])
        self.assertEqual((list(got), m["dead"]), ([G + "fine"], []))

    def test_no_sheet_cases(self):
        self.row("slug0006", [], [])
        self.row("slug0007", [G + "a"], status="running")
        for slug in ("slug0006", "slug0007", "nosuchslug1", "a/../b", "x"):
            self.assertEqual(self.get(slug)[0].status, 404, slug)
        self.assertEqual(self.up.calls, [])

    def test_deep_scan_results_are_not_thumbs(self):
        self.row("slug0008", [G + "a"], [{"thumb": G + "r"}], level="deep")
        self.assertEqual(list(parse(self.get("slug0008")[1])[1]), [G + "a"])

    def test_single_flight(self):
        urls = [G + str(i) for i in range(30)]
        self.row("slug0009", urls)
        self.up.delay = 0.05
        out, ts = [], []
        for _ in range(12):
            t = threading.Thread(target=lambda: out.append(self.get("slug0009")))
            t.start()
            ts.append(t)
        for t in ts:
            t.join()
        self.assertEqual([r.status for r, _ in out], [200] * 12)
        self.assertEqual(len({b for _, b in out}), 1)
        self.assertEqual(sorted(self.up.calls), sorted(urls))

    def test_own_bucket(self):
        thumb_sheet.LIMITER = thumb_sheet.ratelimit.Limiter(rate_per_min=1, burst=1, max_concurrent=1000)
        self.row("slug0010", [G + "a"])
        self.assertEqual(self.get("slug0010")[0].status, 200)
        self.assertEqual(self.get("slug0010")[0].status, 429)

    def test_disk_bound(self):
        saved = thumb_sheet.CACHE_MAX_BYTES
        thumb_sheet.CACHE_MAX_BYTES = 300
        try:
            for i in range(4):
                self.up.answers[G + str(i)] = b"x" * 150
                self.row(f"slug001{i}x", [G + str(i)])
                self.get(f"slug001{i}x")
                time.sleep(0.02)
            size = sum(os.path.getsize(os.path.join(thumb_sheet.cache_dir(), n)) for n in os.listdir(thumb_sheet.cache_dir()))
            self.assertLessEqual(size, 300)
        finally:
            thumb_sheet.CACHE_MAX_BYTES = saved


if __name__ == "__main__":
    unittest.main()

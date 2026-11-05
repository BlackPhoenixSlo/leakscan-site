"""leakshaven.com step: matching, pack parsing, failure modes, per-handle cache, and the scan wiring
(SSE result + /api/scan-result carry mega[]; pack links counted as hits). CSE is faked by
tests/upstream_stub.py, leakshaven by tests/leakshaven_stub.py (declared bypass). All data synthetic."""
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import cse_scanner
import db
import leakshaven
import leakshaven_stub as ls
import media_gather
import public_app
import ratelimit
import upstream_stub

FIELDS = {"url", "host", "via", "title", "size", "images", "videos", "age", "status"}


class TestPure(unittest.TestCase):
    def test_match_handle_and_name(self):
        self.assertEqual(leakshaven.match(ls.SUGGEST, ["@Demo_Creator_X"]), ls.TITLE)
        self.assertIsNone(leakshaven.match(ls.SUGGEST, ["demo_creator"]))            # no prefix match
        self.assertEqual(leakshaven.match(ls.SUGGEST, ["nobody"], names=["demo creator x"]), ls.TITLE)
        name_src = [dict(ls.SUGGEST[1], matchedSource="name", title="Someone Else")]
        self.assertIsNone(leakshaven.match(name_src, [ls.HANDLE]))                   # name hit != handle
        for junk in (None, {}, [None, 1, {"title": ""}, {"title": 5}]):
            self.assertIsNone(leakshaven.match(junk, [ls.HANDLE]))

    def test_packs(self):
        out = leakshaven.packs(ls.CONTENT)
        self.assertEqual([o["url"] for o in out], [f"{leakshaven.SHARE}/fk0001", f"{leakshaven.SHARE}/fk0002",
                                                  f"{leakshaven.SHARE}/fk0005"])
        self.assertTrue(all(set(o) == FIELDS for o in out))
        self.assertEqual(out[0], {"url": f"{leakshaven.SHARE}/fk0001", "host": "leakshaven.com",
                                  "via": "leakshaven.com", "title": "Demo pack 1", "size": 4_000_000_001,
                                  "images": 101, "videos": 301, "age": "2026-11-01T12:00:00Z",
                                  "status": "live"})
        self.assertEqual({k: out[2][k] for k in ("size", "images", "videos", "age")},
                         {"size": None, "images": None, "videos": None, "age": None})
        self.assertEqual(leakshaven.packs({"content": [ls._pack(i % 9 + 1, id=f"p{i}") for i in range(50)]})
                         .__len__(), leakshaven.MAX_PACKS)
        for junk in (None, [], {"content": None}, {"content": [1, None]}):
            self.assertEqual(leakshaven.packs(junk), [])

    def test_hit_rows(self):
        rows = leakshaven.hit_rows(leakshaven.packs(ls.CONTENT), "h")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], {"domain": "leakshaven.com", "url": f"{leakshaven.SHARE}/fk0001",
                                   "occurrences": 1, "method": "leakshaven", "evidence": "aggregator",
                                   "alias": "h", "live": True})


class TestLookup(unittest.TestCase):
    def setUp(self):
        self.up = ls.Stub().start()
        self.saved = (leakshaven.BASE, leakshaven.TIMEOUT)
        leakshaven.BASE = self.up.base

    def tearDown(self):
        leakshaven.BASE, leakshaven.TIMEOUT = self.saved
        self.up.shutdown()

    def test_ok_two_requests(self):
        items, reason = leakshaven.lookup(ls.HANDLE, [])
        self.assertEqual((reason, len(items)), ("ok", 3))
        self.assertEqual([c[0] for c in self.up.calls], ["/content/suggest", "/content"])
        self.assertEqual(self.up.calls[0][1], {"term": ls.HANDLE, "take": "8"})
        self.assertEqual(self.up.calls[1][1], {"search": ls.TITLE, "count": "30", "sorting": "NEWEST"})

    def test_failures_silent(self):
        for mode, want in (("nomatch", "nomatch"), ("404", "http404"), ("403", "http403")):
            self.up.mode = mode
            self.assertEqual(leakshaven.lookup(ls.HANDLE, []), ([], want))
        self.assertEqual(leakshaven.lookup("ab", []), ([], "short"))

    def test_timeout(self):
        self.up.mode, self.up.slow, leakshaven.TIMEOUT = "slow", 2.0, 0.6
        t0 = time.monotonic()
        self.assertEqual(leakshaven.lookup(ls.HANDLE, []), ([], "timeout"))
        self.assertLess(time.monotonic() - t0, 1.5)

    def test_unreachable(self):
        leakshaven.BASE = "http://127.0.0.1:9"
        items, reason = leakshaven.lookup(ls.HANDLE, [])
        self.assertEqual(items, [])
        self.assertIn(reason, ("net", "timeout"))


class TestScanWiring(unittest.TestCase):
    """Real Handler over HTTP: quick scan -> SSE result + /api/scan-result carry mega[]."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.saved = (db.DB_PATH, cse_scanner.CSE_ENDPOINT, public_app.SCAN_LIMITER, public_app.PROFILE_ENABLED,
                     public_app.ALIAS_ENRICH, media_gather.MEDIA_ENABLED, leakshaven.BASE, leakshaven.ENABLED,
                     dict(os.environ))
        db.DB_PATH = os.path.join(cls.tmp.name, "t.db")
        db.init_db()
        cls.cse = upstream_stub.Stub().start()
        cls.up = ls.Stub().start()
        cse_scanner.CSE_ENDPOINT = cls.cse.base + "/customsearch/v1"
        leakshaven.BASE = cls.up.base
        os.environ.update(GOOGLE_API_KEY="fake", GOOGLE_CSE_ID="fake")
        public_app.SCAN_LIMITER = ratelimit.Limiter(rate_per_min=1000, burst=1000, max_concurrent=100)
        public_app.PROFILE_ENABLED = public_app.ALIAS_ENRICH = media_gather.MEDIA_ENABLED = False
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), public_app.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.cse.shutdown()
        cls.up.shutdown()
        (db.DB_PATH, cse_scanner.CSE_ENDPOINT, public_app.SCAN_LIMITER, public_app.PROFILE_ENABLED,
         public_app.ALIAS_ENRICH, media_gather.MEDIA_ENABLED, leakshaven.BASE, leakshaven.ENABLED, env) = cls.saved
        os.environ.clear()
        os.environ.update(env)
        cls.tmp.cleanup()

    def setUp(self):
        self.up.mode, self.up.calls = "ok", []
        leakshaven.ENABLED = True
        with db._db() as c:
            c.execute("DELETE FROM scans")

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        c.request(method, path, body=json.dumps(body) if body is not None else None,
                  headers={"Content-Type": "application/json"} if body is not None else {})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r, data

    def scan(self, handle=ls.HANDLE):
        _, data = self.req("POST", "/api/public-scan", {"handle": handle, "platform": "onlyfans.com"})
        ev = {}
        for block in data.decode().split("\n\n"):
            lines = block.strip().split("\n")
            if lines and lines[0].startswith("event: "):
                ev.setdefault(lines[0][7:], []).append("\n".join(l[6:] for l in lines[1:] if l.startswith("data: ")))
        return ev

    def stored(self, slug):
        r, d = self.req("GET", f"/api/scan-result/{slug}")
        self.assertEqual(r.status, 200)
        return json.loads(d)

    def test_mega_in_sse_and_result(self):
        ev = self.scan()
        self.assertIn("Checking leak aggregators…", ev["progress"])
        res = json.loads(ev["result"][0])
        self.assertEqual(len(res["mega"]), 3)
        self.assertTrue(all(set(m) == FIELDS for m in res["mega"]))
        cse_domains = {h["domain"] for h in res["hits"] if h["domain"] != "leakshaven.com"}
        self.assertEqual(sum(h["domain"] == "leakshaven.com" for h in res["hits"]), 3)
        self.assertEqual(res["hit_count"], len(res["hits"]))
        self.assertEqual(res["domain_count"], len(cse_domains) + 1)
        got = self.stored(res["slug"])
        self.assertEqual(got["mega"], res["mega"])
        self.assertEqual((got["hit_count"], got["domain_count"]), (res["hit_count"], res["domain_count"]))
        self.assertEqual({m["url"] for m in got["mega"]},
                         {h["url"] for h in got["hits"] if h["domain"] == "leakshaven.com"})
        self.assertNotIn("mega_ok", got)

    def test_cached_per_handle(self):
        self.scan()
        n = len(self.up.calls)
        res = json.loads(self.scan(ls.HANDLE.upper())["result"][0])
        self.assertEqual(len(self.up.calls), n)                  # no new leakshaven request
        self.assertEqual(len(res["mega"]), 3)
        with db._db() as c:                                      # 6 h old source -> refetch
            c.execute("UPDATE scans SET created_at = '2000-01-01T00:00:00Z'")
        self.scan()
        self.assertEqual(len(self.up.calls), n + 2)

    def test_cache_hit_does_not_extend_ttl(self):
        self.scan()
        with db._db() as c:
            c.execute("UPDATE scans SET created_at = '2000-01-01T00:00:00Z'")
        self.assertIsNone(db.recent_extra(ls.HANDLE, "mega_ok", leakshaven.CACHE_TTL))
        self.scan()
        self.scan()                                              # served from the 2nd scan's fresh fetch
        self.assertEqual(len(self.up.calls), 4)

    def test_failure_is_silent_and_not_cached(self):
        for mode in ("404", "403"):
            self.up.mode = mode
            ev = self.scan()
            self.assertNotIn("error", ev)
            res = json.loads(ev["result"][0])
            self.assertEqual((res["status"], res["mega"]), ("complete", []))
            self.assertFalse(any(h["domain"] == "leakshaven.com" for h in res["hits"]))
            self.assertEqual(self.stored(res["slug"])["mega"], [])
        self.up.mode = "ok"
        self.assertEqual(len(json.loads(self.scan()["result"][0])["mega"]), 3)   # failures weren't cached

    def test_disabled(self):
        leakshaven.ENABLED = False
        ev = self.scan()
        self.assertNotIn("Checking leak aggregators…", ev["progress"])
        self.assertEqual(json.loads(ev["result"][0])["mega"], [])
        self.assertEqual(self.up.calls, [])

    def test_old_rows_get_empty_mega(self):
        slug = db.insert_scan([{"domain": "a.example", "url": "https://a.example/x"}], handle="old_h")
        self.assertEqual(self.stored(slug)["mega"], [])


if __name__ == "__main__":
    unittest.main()

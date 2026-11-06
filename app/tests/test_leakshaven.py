"""leakshaven.com step: matching (creator by modelId), pack parsing, failure modes, the cache (keyed on the lookup's
inputs), and the scan wiring (SSE result + /api/scan-result carry mega[]; packs never become hit rows). CSE is faked
by tests/upstream_stub.py, leakshaven by tests/leakshaven_stub.py (declared bypass). All data synthetic."""
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

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

def lookup(term, aliases, names=()):
    return leakshaven.result(leakshaven.start(term, aliases, names), leakshaven.TIMEOUT)


FIELDS = {"url", "host", "via", "title", "size", "images", "videos", "age", "status"}
KEPT = [f"{leakshaven.SHARE}/fk0001", f"{leakshaven.SHARE}/fk0002", f"{leakshaven.SHARE}/fk0007",
        f"{leakshaven.SHARE}/fk0005"]


class TestPure(unittest.TestCase):
    def test_match_handle_and_name(self):
        her = {"title": ls.TITLE, "modelId": ls.MODEL}
        self.assertEqual(leakshaven.match(ls.SUGGEST, ["@Demo_Creator_X"]), her)
        self.assertIsNone(leakshaven.match(ls.SUGGEST, ["demo_creator"]))            # no prefix match
        # name only: two creators share the title -> can't tell which -> no match
        self.assertIsNone(leakshaven.match(ls.SUGGEST, ["nobody"], names=["demo creator x"]))
        self.assertEqual(leakshaven.match([ls.SUGGEST[2]], ["nobody"], names=["demo creator x"]), her)
        name_src = [dict(ls.SUGGEST[2], matchedSource="name", title="Someone Else")]
        self.assertIsNone(leakshaven.match(name_src, [ls.HANDLE]))                   # name hit != handle
        no_id = [dict(ls.SUGGEST[2], modelId=None)]
        self.assertIsNone(leakshaven.match(no_id, [ls.HANDLE]))                      # unattributable
        for junk in (None, {}, [None, 1, {"title": ""}, {"title": 5}]):
            self.assertIsNone(leakshaven.match(junk, [ls.HANDLE]))

    def test_packs(self):
        out = leakshaven.packs(ls.CONTENT, ls.WHO)
        self.assertEqual([o["url"] for o in out], KEPT)                              # other creator's pack 6 dropped
        self.assertTrue(all(set(o) == FIELDS for o in out))
        self.assertEqual(out[0], {"url": f"{leakshaven.SHARE}/fk0001", "host": "leakshaven.com",
                                  "via": "leakshaven.com", "title": "Demo Creator X pack 1", "size": 4_000_000_001,
                                  "images": 101, "videos": 301, "age": "2026-11-01T12:00:00Z",
                                  "status": "live"})
        self.assertEqual({k: out[2][k] for k in ("size", "images", "videos")},       # "12" / 5e9 / 3.0 -> ints
                         {"size": 5_000_000_000, "images": 12, "videos": 3})
        self.assertTrue(all(type(out[2][k]) is int for k in ("size", "images", "videos")))
        self.assertEqual({k: out[3][k] for k in ("size", "images", "videos", "age")},
                         {"size": None, "images": None, "videos": None, "age": None})
        many = {"content": [ls._pack(i % 9 + 1, id=f"p{i}") for i in range(50)], "richProfileId": ls.MODEL}
        self.assertEqual(len(leakshaven.packs(many, ls.WHO)), leakshaven.MAX_PACKS)
        for junk in (None, [], {"content": None}, {"content": [1, None]}):
            self.assertEqual(leakshaven.packs(junk, ls.WHO), [])

    def test_packs_of_another_creator_are_excluded(self):
        namesake = {"title": ls.TITLE, "modelId": ls.OTHER}
        self.assertEqual([o["url"] for o in leakshaven.packs(ls.CONTENT, namesake)], [f"{leakshaven.SHARE}/fk0006"])
        self.assertEqual(leakshaven.packs(ls.CONTENT_OTHER, ls.WHO), [])              # search resolved to her namesake
        self.assertEqual(leakshaven.packs({"content": [ls._pack(1)]}, ls.WHO), [])    # nothing says whose -> []
        for junk in (None, {}, {"title": ls.TITLE}, ls.MODEL):
            self.assertEqual(leakshaven.packs(ls.CONTENT, junk), [])

    def test_mixed_creator_response(self):
        """B2: a free-text search answer mixing creators -> only the matched creator's packs."""
        mixed = {"richProfileId": ls.MODEL, "content": [
            ls._pack(1),                                         # no modelId, her name in the title -> hers
            ls._pack(2, title="Other Demo leaked pack"),         # no modelId, another name -> dropped
            ls._pack(3, modelId=ls.OTHER),                       # the namesake's own modelId -> dropped
            ls._pack(4, modelId=ls.MODEL, title="untitled"),     # her own modelId -> hers, whatever the title
            ls._pack(5, title="Demo X pack 5")]}                 # part of her name only -> dropped
        url = lambda d: [o["url"] for o in leakshaven.packs(d, ls.WHO)]
        self.assertEqual(url(mixed), [f"{leakshaven.SHARE}/fk0001", f"{leakshaven.SHARE}/fk0004"])
        # the response scoped to someone else: only a pack carrying her own modelId stays
        self.assertEqual(url({**mixed, "richProfileId": ls.OTHER}), [f"{leakshaven.SHARE}/fk0004"])
        self.assertEqual(url({**mixed, "richProfileId": None}), [f"{leakshaven.SHARE}/fk0004"])

    def test_int(self):
        for raw, want in ((5, 5), (5.9, 5), ("7", 7), (" 8.0 ", 8), (True, None), (-1, None), ("x", None),
                          (float("nan"), None), (float("inf"), None), (None, None), ([], None)):
            self.assertEqual(leakshaven._int(raw), want, raw)

    def test_env_timeout(self):
        for raw, want in (("3", 3.0), ("20", 8.0), ("abc", 8.0), ("", 8.0), ("-1", 8.0), ("nan", 8.0), (None, 8.0)):
            self.assertEqual(leakshaven._env_timeout(raw), want, raw)

    def test_cache_key(self):
        k = leakshaven.cache_key("onlyfans.com", "x_h", ["x_h", "@Y"], ["Mira"])
        self.assertEqual(k, leakshaven.cache_key("OnlyFans.com", "@X_H", ["y", "x_h"], ["mira", " Mira "]))
        for other in (leakshaven.cache_key("fansly.com", "x_h", ["x_h", "y"], ["mira"]),      # platform
                      leakshaven.cache_key("onlyfans.com", "y", ["x_h", "y"], ["mira"]),      # instagram=Y term
                      leakshaven.cache_key("onlyfans.com", "x_h", ["x_h"], ["mira"]),         # alias set
                      leakshaven.cache_key("onlyfans.com", "x_h", ["x_h", "y"], [])):         # names
            self.assertNotEqual(k, other)
        self.assertNotIn("x_h", k)                                                            # opaque


class TestLookup(unittest.TestCase):
    def setUp(self):
        self.up = ls.Stub().start()
        self.patch = mock.patch.multiple(leakshaven, BASE=self.up.base, MIN_GAP=0.0)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.up.shutdown()

    def test_ok_two_requests(self):
        items, reason = lookup(ls.HANDLE, [])
        self.assertEqual((reason, [i["url"] for i in items]), ("ok", KEPT))
        self.assertEqual([c[0] for c in self.up.calls], ["/content/suggest", "/content"])
        self.assertEqual(self.up.calls[0][1], {"term": ls.HANDLE, "take": "8"})
        self.assertEqual(self.up.calls[1][1], {"search": ls.TITLE, "count": "30", "sorting": "NEWEST"})

    def test_same_title_other_creator_excluded(self):
        self.up.mode = "other"                       # the free-text search resolved to her namesake
        self.assertEqual(lookup(ls.HANDLE, []), ([], "ok"))
        self.up.mode = "ok"
        items, _ = lookup(ls.HANDLE, [])
        self.assertNotIn(f"{leakshaven.SHARE}/fk0006", [i["url"] for i in items])

    def test_failures_silent(self):
        for mode, want in (("nomatch", "nomatch"), ("404", "http404"), ("403", "http403")):
            self.up.mode = mode
            self.assertEqual(lookup(ls.HANDLE, []), ([], want))
        self.assertEqual(lookup("ab", []), ([], "short"))

    def test_timeout_is_wall_clock(self):
        with mock.patch.object(leakshaven, "TIMEOUT", 0.6):
            self.up.mode, self.up.slow = "slow", 2.0
            t0 = time.monotonic()
            self.assertEqual(lookup(ls.HANDLE, []), ([], "timeout"))
            self.assertLess(time.monotonic() - t0, 0.9)

    def test_unreachable(self):
        with mock.patch.object(leakshaven, "BASE", "http://127.0.0.1:9"):
            items, reason = lookup(ls.HANDLE, [])
        self.assertEqual(items, [])
        self.assertIn(reason, ("net", "timeout"))

    def test_rate_limited_per_process(self):
        with mock.patch.multiple(leakshaven, MIN_GAP=0.3, _next_at=0.0):
            t0 = time.monotonic()
            for _ in range(2):
                self.assertEqual(lookup(ls.HANDLE, [])[1], "ok")
            self.assertGreaterEqual(time.monotonic() - t0, 0.85)    # 4 requests, >= 3 gaps of 0.3 s
            with mock.patch.object(leakshaven, "TIMEOUT", 0.25):    # next slot past this lookup's deadline
                leakshaven._next_at = time.monotonic() + 5
                self.assertEqual(lookup(ls.HANDLE, []), ([], "busy"))


class TestScanWiring(unittest.TestCase):
    """Real Handler over HTTP: quick scan -> SSE result + /api/scan-result carry mega[]; packs are not hits."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cse = upstream_stub.Stub().start()
        cls.up = ls.Stub().start()
        cls.patches = [
            mock.patch.object(db, "DB_PATH", os.path.join(cls.tmp.name, "t.db")),
            mock.patch.object(cse_scanner, "CSE_ENDPOINT", cls.cse.base + "/customsearch/v1"),
            mock.patch.multiple(public_app, PROFILE_ENABLED=False, ALIAS_ENRICH=False,
                                SCAN_LIMITER=ratelimit.Limiter(rate_per_min=1000, burst=1000, max_concurrent=100)),
            mock.patch.object(media_gather, "MEDIA_ENABLED", False),
            mock.patch.multiple(leakshaven, BASE=cls.up.base, ENABLED=True, MIN_GAP=0.0),
            mock.patch.dict(os.environ, GOOGLE_API_KEY="fake", GOOGLE_CSE_ID="fake"),
        ]
        for p in cls.patches:
            p.start()
        db.init_db()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), public_app.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.cse.shutdown()
        cls.up.shutdown()
        for p in reversed(cls.patches):
            p.stop()
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

    def scan(self, handle=ls.HANDLE, **extra):
        _, data = self.req("POST", "/api/public-scan", {"handle": handle, "platform": "onlyfans.com", **extra})
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

    def test_mega_in_sse_and_result_never_in_hits(self):
        ev = self.scan()
        self.assertIn("Checking leak aggregators…", ev["progress"])
        res = json.loads(ev["result"][0])
        self.assertEqual([m["url"] for m in res["mega"]], KEPT)
        self.assertTrue(all(set(m) == FIELDS for m in res["mega"]))
        # packs are mega[] only: no aggregator row / url in hits, counts are the CSE rows' own
        blob = json.dumps(res["hits"])
        self.assertNotIn("leakshaven", blob)
        self.assertEqual(res["hit_count"], len(res["hits"]))
        self.assertEqual(res["domain_count"], len({h["domain"] for h in res["hits"]}))
        leakshaven.ENABLED = False
        off = json.loads(self.scan()["result"][0])
        self.assertEqual((off["hit_count"], off["domain_count"], off["google_total"]),
                         (res["hit_count"], res["domain_count"], res["google_total"]))
        got = self.stored(res["slug"])
        self.assertEqual(got["mega"], res["mega"])
        self.assertEqual((got["hit_count"], got["domain_count"]), (res["hit_count"], res["domain_count"]))
        self.assertNotIn("leakshaven", json.dumps(got.get("hits", [])))
        self.assertNotIn(leakshaven.CACHE_FIELD, got)

    def test_cache_keyed_on_lookup_inputs(self):
        self.scan()
        n = len(self.up.calls)
        res = json.loads(self.scan(ls.HANDLE.upper())["result"][0])
        self.assertEqual(len(self.up.calls), n)                  # same inputs: no new leakshaven request
        self.assertEqual(len(res["mega"]), len(KEPT))
        self.scan(instagram="someone_else_x")                    # other search term: not served from X's row
        self.assertEqual(len(self.up.calls), n + 2)
        self.scan(platform="fansly.com")                         # other platform: not served either
        self.assertEqual(len(self.up.calls), n + 4)
        with db._db() as c:                                      # 6 h old source -> refetch
            c.execute("UPDATE scans SET created_at = '2000-01-01T00:00:00Z'")
        self.scan()
        self.assertEqual(len(self.up.calls), n + 6)

    def test_cache_hit_does_not_extend_ttl(self):
        self.scan()
        with db._db() as c:
            c.execute("UPDATE scans SET created_at = '2000-01-01T00:00:00Z'")
            key = json.loads(c.execute("SELECT extra_json FROM scans").fetchone()[0])[leakshaven.CACHE_FIELD]
        self.assertTrue(key)
        self.assertIsNone(db.recent_extra(ls.HANDLE, leakshaven.CACHE_FIELD, key, leakshaven.CACHE_TTL))
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
            self.assertEqual(self.stored(res["slug"])["mega"], [])
        self.up.mode = "ok"
        self.assertEqual(len(json.loads(self.scan()["result"][0])["mega"]), len(KEPT))   # failures weren't cached

    def test_disabled(self):
        leakshaven.ENABLED = False
        ev = self.scan()
        self.assertNotIn("Checking leak aggregators…", ev["progress"])
        self.assertEqual(json.loads(ev["result"][0])["mega"], [])
        self.assertEqual(self.up.calls, [])

    def test_old_rows_get_empty_mega(self):
        slug = db.insert_scan([{"domain": "a.example", "url": "https://a.example/x"}], handle="old_h")
        self.assertEqual(self.stored(slug)["mega"], [])

    def test_google_hits_on_a_pack_host_dropped(self):
        """S21: Google results on a pack's host (subdomain, port, www / case forms) leave results AND hits, in the SSE
        result and in /api/scan-result; counts and google_total are those of a scan that never saw them."""
        agg = [{"title": "Mira Example pack", "link": u, "snippet": "synthetic"} for u in (
            f"{leakshaven.SHARE}/fk0001", "https://s.leakshaven.com:8443/fk0002", "https://WWW.LeakShaven.com:443/p",
            "https://leakshaven.com/x")]
        with mock.patch.object(public_app, "FALLBACK_EXTRA_PAGES", 0):     # same CSE calls for both scans
            with mock.patch.object(upstream_stub, "CSE_ITEMS", upstream_stub.CSE_ITEMS[:5]):
                base = json.loads(self.scan()["result"][0])
            with mock.patch.object(upstream_stub, "CSE_ITEMS", upstream_stub.CSE_ITEMS[:5] + agg):
                res = json.loads(self.scan()["result"][0])
        self.assertEqual(len(res["mega"]), len(KEPT))
        for got in (res, self.stored(res["slug"])):
            self.assertNotIn("leakshaven", json.dumps([got["hits"], got["results"]]).lower())
            self.assertEqual([r["link"] for r in got["results"]], [r["link"] for r in base["results"]])
            self.assertEqual((got["hits"], got["hit_count"], got["domain_count"], got["google_total"]),
                             (base["hits"], base["hit_count"], base["domain_count"], base["google_total"]))

    def test_pack_host_thumb_never_stored_shown_or_gathered(self):
        """S33 / C21: a Google result on a pack's host that has a thumb: the thumb is in neither images[] (SSE result,
        /api/scan-result) nor counted, the images are those of a scan that never saw that result, and media_gather
        gets only the results left. An old row that stored such a thumb in images[] serves without it."""
        tb = lambda k: {"pagemap": {"cse_thumbnail": [{"src": f"https://encrypted-tbn0.gstatic.com/images?q=tbn:{k}"}]}}
        own = [{**it, **tb(f"OWN{i:02d}")} for i, it in enumerate(upstream_stub.CSE_ITEMS[3:9])]
        agg = [{"title": "mira.example pack", "link": f"{leakshaven.SHARE}/fk0001", "snippet": "synthetic", **tb("PACK01")},
               {"title": "mira.example pack", "link": "https://s.leakshaven.com:8443/fk0002", "snippet": "synthetic", **tb("PACK02")}]
        gathered = []
        start = lambda slug, platform, handle, profile, cse_items, **kw: gathered.append(list(cse_items)) or "none"
        with mock.patch.object(public_app, "FALLBACK_EXTRA_PAGES", 0), mock.patch.object(media_gather, "start", start):
            with mock.patch.object(upstream_stub, "CSE_ITEMS", own):
                base = json.loads(self.scan()["result"][0])
            with mock.patch.object(upstream_stub, "CSE_ITEMS", agg[:1] + own + agg[1:]):
                res = json.loads(self.scan()["result"][0])
        self.assertEqual(len(base["images"]), len(own))
        for got in (res, self.stored(res["slug"])):
            self.assertNotIn("PACK0", json.dumps(got))
            self.assertEqual(got["images"], base["images"])
        self.assertNotIn("leakshaven", json.dumps(gathered[-1]).lower())
        self.assertEqual(len(gathered[-1]), len(own))
        # a row stored before the rule: its images[] holds the pack result's thumb
        mega = [{"url": f"{leakshaven.SHARE}/fk0001", "host": "leakshaven.com", "via": "leakshaven.com"}]
        pack_t, own_t = (f"https://encrypted-tbn0.gstatic.com/images?q=tbn:{k}" for k in ("PACK03", "OWN99"))
        rows = [{"link": f"{leakshaven.SHARE}/fk0003", "domain": "leakshaven.com", "thumb": pack_t},
                {"link": "https://a.example/x", "domain": "a.example", "thumb": own_t}]
        slug = db.insert_scan([{"domain": "a.example", "url": "https://a.example/x"}], handle="old_t", level="low",
                              status="complete", extra={"mega": mega, "images": [pack_t, own_t], "results": rows})
        got = self.stored(slug)
        self.assertEqual((got["images"], got["results"]), ([own_t], rows[1:]))

    def test_old_row_pack_hits_dropped_and_recounted(self):
        """S12/M4/C14/S21: a scan stored before packs left the hit rows -> /api/scan-result serves its hits and results
        without them (by domain or URL host, subdomains, ports and case included) and counts recomputed from what is
        left; a google_total at the GOOGLE_INDEX_MAX cap stands."""
        mega = [{"url": f"{leakshaven.SHARE}/fk0001", "host": "leakshaven.com", "via": "leakshaven.com"}]
        own = [{"domain": "a.example", "url": "https://a.example/x", "occurrences": 3},
               {"domain": "b.example", "url": "https://www.b.example/y", "occurrences": 1}]
        packs = [{"domain": "leakshaven.com", "url": f"{leakshaven.SHARE}/fk0001", "occurrences": 99},
                 {"domain": "s.leakshaven.com", "url": f"{leakshaven.SHARE}/fk0002", "occurrences": 1},
                 {"domain": "WWW.LeakShaven.com", "url": "https://www.leakshaven.com/p", "occurrences": 1},
                 {"domain": "mirror.example", "url": "https://S.LEAKSHAVEN.COM/fk0003", "occurrences": 1}]
        res = [{"link": "https://a.example/x", "domain": "a.example"},
               {"link": "https://s.leakshaven.com:8443/fk0004", "domain": "leakshaven.com"},
               {"link": "https://cdn.LEAKSHAVEN.com/i.jpg", "domain": ""}]
        total = round(3 * public_app.ESTIMATE_URL_MULT + 6 * public_app.ESTIMATE_SITES_MULT)
        slug = db.insert_scan(own[:1] + packs + own[1:], handle="old_h", level="low", status="complete",
                              extra={"mega": mega, "google_total": total, "results": res})
        got = self.stored(slug)
        self.assertEqual((got["hits"], got["results"]), (own, res[:1]))
        self.assertEqual((got["hit_count"], got["domain_count"], got["status"]), (2, 2, "complete"))
        self.assertEqual(got["google_total"],
                         total - round(4 * public_app.ESTIMATE_SITES_MULT + 2 * public_app.ESTIMATE_URL_MULT))
        with mock.patch.object(public_app, "GOOGLE_INDEX_MAX", total):
            self.assertEqual(self.stored(slug)["google_total"], total)      # capped: the uncapped figure is gone
        self.assertNotIn("leakshaven", json.dumps(got["hits"]).lower())
        only = db.insert_scan(packs[:2], handle="old_h2", status="complete", extra={"mega": mega, "google_total": 60})
        got = self.stored(only)
        self.assertEqual((got["hits"], got["hit_count"], got["domain_count"], got["status"], got["google_total"]),
                         ([], 0, 0, "empty", max(0, 60 - round(2 * public_app.ESTIMATE_SITES_MULT))))
        self.assertEqual(db.get_scan(slug)["google_total"], total)          # the DB reader serves the row as stored
        clean = db.insert_scan(own, handle="old_h3", extra={"mega": mega, "google_total": 7})
        self.assertEqual((self.stored(clean)["hits"], self.stored(clean)["google_total"]), (own, 7))


if __name__ == "__main__":
    unittest.main()

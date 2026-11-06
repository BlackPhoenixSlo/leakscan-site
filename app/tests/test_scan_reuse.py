"""Whole-scan reuse (public_app.scan_reuse_serve): real Handler over HTTP. CSE + DeepSeek are tests/upstream_stub.py,
leakshaven tests/leakshaven_stub.py, profile pages / Instagram embed / CDN fakes at their urlopen wires (declared
bypass). Every assertion on "no external call" counts what those wires received. All data synthetic."""
import http.client
import json
import os
import shutil
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
import chat_proxy
import cse_scanner
import db
import leakshaven
import leakshaven_stub as ls
import media_gather as mg
import profile_extract as pe
import public_app
import ratelimit
import upstream_stub as stub
from test_profile import FakeFetch, ig_routes

H = stub.HANDLE
OLD = "2000-01-01T00:00:00Z"


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.up, cls.ls = stub.Stub().start(), ls.Stub().start()
        cls.patches = [
            mock.patch.object(db, "DB_PATH", os.path.join(cls.tmp.name, "t.db")),
            mock.patch.object(cse_scanner, "CSE_ENDPOINT", cls.up.base + "/customsearch/v1"),
            mock.patch.object(chat_proxy, "DEEPSEEK_URL", cls.up.base + "/chat/completions"),
            mock.patch.multiple(public_app, PROFILE_ENABLED=True, ALIAS_ENRICH=False, SCAN_REUSE_TTL=21600),
            mock.patch.multiple(leakshaven, BASE=cls.ls.base, ENABLED=True, MIN_GAP=0.0),
            mock.patch.multiple(mg, MEDIA_ENABLED=True, MEDIA_BROWSERBASE=False, MEDIA_GOOGLE="off", ADOPT_POLL=0.01,
                                ADOPT_NO_INDEX=0.05),
            mock.patch.object(pe, "LLM_TIMEOUT", 15),
            mock.patch.dict(os.environ, GOOGLE_API_KEY="fake", GOOGLE_CSE_ID="fake", DEEPSEEK_API_KEY="fake", DATA_DIR=""),
        ]
        for p in cls.patches:
            p.start()
        db.init_db()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), public_app.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.up.shutdown()
        cls.ls.shutdown()
        for p in reversed(cls.patches):
            p.stop()
        cls.tmp.cleanup()

    def setUp(self):
        self.up.mode, self.up.cse_limit, self.up.calls, self.up.alias_items = "valid", None, [], {}
        self.up.timeout_sleep = 0
        self.ls.mode, self.ls.calls = "ok", []
        tiles = mg.parse_embed(stub.embed_page().decode())[:3]
        self.embed = stub.FakeEmbed({H: stub.embed_page()})
        self.cdn = stub.FakeCDN({u: stub.synth(640, 640, 30 + i) for i, u in enumerate(tiles)})
        self.pages = FakeFetch(ig_routes())
        self.wires = [mock.patch.object(mg, "page_open", self.embed), mock.patch.object(mg, "urlopen", self.cdn),
                      mock.patch.object(pe, "urlopen", self.pages),
                      mock.patch.object(public_app, "SCAN_LIMITER",
                                        ratelimit.Limiter(rate_per_min=1000, burst=1000, max_concurrent=100)),
                      mock.patch.object(public_app, "RESULT_LIMITER",
                                        ratelimit.Limiter(rate_per_min=10000, burst=1000, max_concurrent=1000))]
        for p in self.wires:
            p.start()
            self.addCleanup(p.stop)
        with db._db() as c:
            c.execute("DELETE FROM scans")
        shutil.rmtree(os.path.join(mg.data_dir(), "media-cache"), ignore_errors=True)

    def calls(self):
        """External calls so far, per upstream."""
        return {"cse": sum(c[0] == "cse" for c in self.up.calls), "llm": sum(c[0] == "llm" for c in self.up.calls),
                "leakshaven": len(self.ls.calls), "pages": len(self.pages.seen), "embed": len(self.embed.seen),
                "cdn": len(self.cdn.seen)}

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        c.request(method, path, body=json.dumps(body) if body is not None else None,
                  headers={**({"Content-Type": "application/json"} if body is not None else {}), **(headers or {})})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r, data

    def stream(self, handle=H, headers=None, **extra):
        r, data = self.req("POST", "/api/public-scan", {"handle": handle, "platform": "onlyfans.com", **extra}, headers)
        self.assertEqual(r.status, 200, data[:200])
        ev = {}
        for block in data.decode().split("\n\n"):
            lines = block.strip().split("\n")
            if lines and lines[0].startswith("event: "):
                ev.setdefault(lines[0][7:], []).append("\n".join(l[6:] for l in lines[1:] if l.startswith("data: ")))
        return ev

    def scan(self, handle=H, **extra):
        res = json.loads(self.stream(handle, **extra)["result"][0])
        self.settle(res["slug"])
        return res

    def settle(self, slug):
        for _ in range(500):
            if json.loads(self.req("GET", f"/api/media/{slug}")[1])["status"] != "pending":
                return
            time.sleep(0.01)
        self.fail("media never settled")

    def extra(self, slug):
        return db.scan_extra(slug)

    def assertHit(self, res, source):
        self.assertEqual(self.extra(res["slug"]).get("reused_from"), source["slug"])

    def assertFresh(self, res):
        self.assertNotIn("reused_from", self.extra(res["slug"]))


class TestReuse(Base):
    def test_repeat_makes_no_external_call_and_mirrors_a_fresh_scan(self):
        a = self.scan()
        n = self.calls()
        self.assertTrue(all(n[k] for k in ("cse", "llm", "leakshaven", "pages", "embed", "cdn")), n)
        ev = self.stream()
        self.assertEqual(self.calls(), n)
        self.assertEqual(sorted(ev), ["done", "progress", "result"])
        b = json.loads(ev["result"][0])
        self.settle(b["slug"])
        self.assertEqual(self.calls(), n)                         # the media step too
        self.assertNotEqual(b["slug"], a["slug"])
        self.assertEqual(set(b), set(a))                          # same result shape
        for k in set(a) - {"slug", "media"}:
            self.assertEqual(b[k], a[k], k)
        self.assertEqual(b["media"], {"status": "pending"})

    def test_own_row_and_own_per_slug_state(self):
        a = self.scan(headers={"X-Real-IP": "203.0.113.1"})
        b = self.scan(headers={"X-Real-IP": "203.0.113.2"})
        self.assertHit(b, a)
        db.mark_verified(a["slug"])
        got, src = db.get_scan(b["slug"]), db.get_scan(a["slug"])
        self.assertEqual((got["status"], got["level"], got["hit_count"], got["domain_count"], got["hits"]),
                         (src["status"], src["level"], src["hit_count"], src["domain_count"], src["hits"]))
        self.assertNotEqual(got["client_ip_hash"], src["client_ip_hash"])
        self.assertEqual(got["client_ip_hash"], public_app._ip_hash("203.0.113.2"))
        self.assertEqual((got["ownership_verified"], got["verify_code"], got["verify_platform"]), (False, None, None))
        with db._db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM scans").fetchone()[0], 2)
        # avatar, media, profile answer under B's own slug
        r, d = self.req("GET", f"/api/avatar/{b['slug']}")
        self.assertEqual((r.status, d), (200, self.req("GET", f"/api/avatar/{a['slug']}")[1]))
        ma, mb = (json.loads(self.req("GET", f"/api/media/{x['slug']}")[1]) for x in (a, b))
        self.assertEqual((mb["status"], len(mb["images"])), ("ready", len(ma["images"])))
        self.assertGreater(len(mb["images"]), 0)
        self.assertTrue(all(f"/api/media/{b['slug']}/" in i["src"] for i in mb["images"]))
        self.assertEqual(self.req("GET", f"/api/media/{b['slug']}/0.jpg")[1], self.req("GET", f"/api/media/{a['slug']}/0.jpg")[1])
        self.assertEqual(json.loads(self.req("GET", f"/api/profile/{b['slug']}")[1])["profile"], b["profile"])
        self.assertTrue(b["profile"]["avatar"])

    def test_source_and_keys_never_served(self):
        a = self.scan()
        b = self.scan()
        for path in (f"/api/scan-result/{b['slug']}", f"/api/profile/{b['slug']}"):
            body = self.req("GET", path)[1].decode()
            self.assertNotIn(a["slug"], body)
            self.assertNotIn("reused_from", body)
            self.assertNotIn(public_app.SCAN_REUSE_FIELD, body)
        self.assertNotIn(a["slug"], json.dumps(b))

    def test_case_and_at_are_the_same_scan_but_her_typing_stands(self):
        a = self.scan()
        b = self.scan(H.upper())
        self.assertHit(b, a)
        self.assertEqual(b["handle"], H.upper())
        self.assertEqual(db.get_scan(b["slug"])["handle"], H.upper())
        self.assertEqual(b["aliases"]["declared"], [H.upper()])
        a = self.scan(instagram="Some_IG", fresh=True)
        b = self.scan(instagram="@some_ig")
        self.assertHit(b, a)
        self.assertEqual(b["socials"], {"instagram": "some_ig"})

    def test_other_inputs_miss(self):
        self.scan()
        n = self.calls()["cse"]
        for extra in ({"platform": "fansly.com"}, {"instagram": "y_y_y"}, {"x": "y_y_y"}, {"instagram": "z_z_z"}):
            res = self.scan(**extra)
            self.assertFresh(res)
            self.assertGreater(self.calls()["cse"], n, extra)
            n = self.calls()["cse"]
            self.assertHit(self.scan(**extra), res)                # each has its own source now
        self.assertFresh(self.scan("another.handle"))

    def test_ttl_expiry_and_off(self):
        self.scan()
        with db._db() as c:
            c.execute("UPDATE scans SET created_at = ?", (OLD,))
        n = self.calls()["cse"]
        self.assertFresh(self.scan())
        self.assertGreater(self.calls()["cse"], n)
        with mock.patch.object(public_app, "SCAN_REUSE_TTL", 0):
            off = self.scan()
            self.assertFresh(off)
            self.assertIsNone(self.extra(off["slug"]).get(public_app.SCAN_REUSE_FIELD))    # off stores no key either

    def test_no_roll_forward(self):
        a = self.scan()
        b = self.scan()
        self.assertHit(b, a)
        ex = self.extra(b["slug"])
        self.assertNotIn(public_app.SCAN_REUSE_FIELD, ex)             # a reused row is no source
        self.assertNotIn(leakshaven.CACHE_FIELD, ex)                  # ... of the leakshaven lookup either
        with db._db() as c:                                           # B is minutes old, its source expired
            c.execute("UPDATE scans SET created_at = ? WHERE slug = ?", (OLD, a["slug"]))
        n = self.calls()
        c2 = self.scan()
        self.assertFresh(c2)
        self.assertGreater(self.calls()["cse"], n["cse"])
        self.assertGreater(self.calls()["leakshaven"], n["leakshaven"])

    def test_many_reused_rows_do_not_hide_the_source(self):
        a = self.scan()
        for _ in range(12):
            self.assertHit(self.scan(), a)

    def test_force_fresh(self):
        a = self.scan()
        n = self.calls()
        f = self.scan(fresh=True)
        self.assertFresh(f)
        now = self.calls()
        self.assertEqual(now["cse"] - n["cse"], n["cse"])             # all of Google again
        self.assertEqual(now["llm"] - n["llm"], n["llm"])
        self.assertEqual(now["leakshaven"] - n["leakshaven"], n["leakshaven"])   # the aggregator lookup again, not its cache
        self.assertTrue(self.extra(f["slug"]).get(public_app.SCAN_REUSE_FIELD))
        self.assertHit(self.scan(), f)                                # newest source wins
        self.assertNotEqual(f["slug"], a["slug"])
        self.assertHit(self.scan(fresh="yes"), f)                     # only JSON true asks for it

    def test_log_line_has_no_handle(self):
        self.scan()
        with mock.patch.object(public_app, "_event") as ev:
            self.scan()
        lines = [c.args[0] for c in ev.call_args_list]
        self.assertEqual([l for l in lines if l.startswith("scan reuse hit")], lines[:1])
        self.assertFalse([l for l in lines if l.startswith(("scan start", "scan done"))])
        self.assertNotIn(H, " ".join(lines))

    def test_rate_limit_consumed_and_released(self):
        lim = ratelimit.Limiter(rate_per_min=1, burst=2, max_concurrent=1)
        with mock.patch.object(public_app, "SCAN_LIMITER", lim):
            self.scan()
            self.assertHit(self.scan(), {"slug": db_first_slug()})     # token 2: allowed, and released (concurrency 1)
            r, d = self.req("POST", "/api/public-scan", {"handle": H})
            self.assertEqual((r.status, json.loads(d)), (429, {"error": "rate_limited"}))
            self.assertEqual(lim._b["127.0.0.1"]["inflight"], 0)

    def test_failure_falls_back_to_a_scan(self):
        self.scan()
        n = self.calls()["cse"]
        real, tries = db.insert_scan, []

        def first_insert_fails(*a, **k):
            tries.append(1)
            if len(tries) == 1:
                raise OSError("disk")
            return real(*a, **k)
        with mock.patch.object(db, "insert_scan", first_insert_fails), mock.patch.object(public_app, "_event") as ev:
            res = self.scan()
        self.assertFresh(res)
        self.assertGreater(self.calls()["cse"], n)
        self.assertIn("scan reuse failed: OSError", [c.args[0] for c in ev.call_args_list])


def db_first_slug():
    with db._db() as c:
        return c.execute("SELECT slug FROM scans ORDER BY rowid LIMIT 1").fetchone()[0]


class TestOnlyWholeResultsAreSources(Base):
    def stored_key(self, res):
        return self.extra(res["slug"]).get(public_app.SCAN_REUSE_FIELD)

    def test_whole_result_is_a_source(self):
        self.assertTrue(self.stored_key(self.scan()))

    def test_empty_is_not_reused(self):
        self.up.alias_items = {H: []}                                 # Google really has nothing
        e = self.scan()
        self.assertEqual(e["status"], "empty")
        self.assertIsNone(self.stored_key(e))
        n = self.calls()["cse"]
        self.assertFresh(self.scan())
        self.assertGreater(self.calls()["cse"], n)

    def test_quota_gone_is_not_a_false_no_leaks_for_6h(self):
        self.up.cse_limit = 0
        e = self.scan()
        self.assertEqual((e["status"], e["hit_count"]), ("empty", 0))
        self.up.cse_limit = None
        ok = self.scan()
        self.assertFresh(ok)
        self.assertGreater(ok["hit_count"], 0)

    def test_quota_gone_midway_is_partial(self):
        self.up.cse_limit = 1
        p = self.scan()
        self.assertEqual(p["status"], "complete")                     # few rows passing as a whole result
        self.assertIsNone(self.stored_key(p))
        self.up.cse_limit = None
        self.assertFresh(self.scan())

    def test_failed_google_calls_are_reported(self):
        self.up.cse_limit = 0
        for fn in (lambda e: cse_scanner.cse_paginate("q", errors=e),
                   lambda e: public_app._alias_cse("alias_x", time.monotonic() + 5, e)):
            errors = []
            fn(errors)
            self.assertEqual(errors, ["HTTPError"])
        self.assertEqual(cse_scanner.cse_paginate("q"), [])           # upstream's callers: as before

    def test_leakshaven_failed_or_from_its_cache_is_not_a_source(self):
        self.ls.mode = "404"
        f = self.scan()
        self.assertIsNone(self.stored_key(f))
        self.ls.mode = "ok"
        ok = self.scan()
        self.assertFresh(ok)
        self.assertTrue(self.stored_key(ok))
        # a partial scan fetched the packs; the next scan takes them from the leakshaven cache: their age would add to the TTL
        with db._db() as c:
            c.execute("DELETE FROM scans")
        self.up.cse_limit = 1
        p = self.scan()
        self.assertIsNone(self.stored_key(p))
        self.assertTrue(self.extra(p["slug"]).get(leakshaven.CACHE_FIELD))
        self.up.cse_limit, n = None, len(self.ls.calls)
        cached = self.scan()
        self.assertEqual(len(self.ls.calls), n)
        self.assertIsNone(self.stored_key(cached))

    def test_profile_fallback_or_none_is_not_a_source(self):
        self.up.mode = "timeout"                                      # the LLM answers 504
        f = self.scan()
        self.assertEqual(f["profile"]["generated_by"], "fallback")
        self.assertIsNone(self.stored_key(f))
        self.up.mode = "valid"
        with mock.patch.object(public_app, "_quick_profile", return_value=(None, None, None)):
            self.assertIsNone(self.stored_key(self.scan()))
        with db._db() as c:
            c.execute("DELETE FROM scans")                            # (the leakshaven cache)
        with mock.patch.object(public_app, "PROFILE_ENABLED", False):
            self.assertTrue(self.stored_key(self.scan()))             # off is whole: nothing was missed

    def test_alias_step_skipped_is_not_a_source(self):
        errors = []
        with mock.patch.multiple(public_app, ALIAS_ENRICH=True, ALIAS_SKIP_AFTER=0):
            public_app.enrich_aliases([H], [{"domain": "a.example"}], [], lambda m: None, time.monotonic() - 1, errors)
        self.assertEqual(errors, ["alias_budget"])
        self.assertIsNone(public_app.scan_reuse_value("k", "complete", errors, "m", {"generated_by": "deepseek"}))


class TestMediaAdoption(Base):
    def test_source_still_gathering(self):
        """B comes while A's gather runs: B stays pending, gets A's photos when it ends, nothing is gathered twice."""
        gate = threading.Event()
        real = self.cdn

        def held(req, timeout=None):
            gate.wait(10)
            return real(req, timeout)
        with mock.patch.object(mg, "urlopen", held):
            a = json.loads(self.stream()["result"][0])
            b = json.loads(self.stream()["result"][0])
            self.assertHit(b, a)
            self.assertEqual(json.loads(self.req("GET", f"/api/media/{b['slug']}")[1])["status"], "pending")
            gate.set()
            self.settle(a["slug"])
            self.settle(b["slug"])
        ma, mb = (json.loads(self.req("GET", f"/api/media/{x['slug']}")[1]) for x in (a, b))
        self.assertEqual((mb["status"], len(mb["images"])), ("ready", len(ma["images"])))
        self.assertEqual(len(self.embed.seen), 1)

    def test_refined_profile_follows(self):
        a = self.scan()
        slug = db.insert_scan([{"domain": "a.example"}], handle=H, extra={"profile": {"bio": "old"}})
        db.update_extra(a["slug"], {"profile": {"bio": "refined"}})
        mg._write_index(a["slug"], "ready", [], "2026-11-06T00:00:00Z")
        self.assertEqual(mg.adopt(slug, a["slug"]), "pending")
        self.settle(slug)
        self.assertEqual(db.scan_extra(slug)["profile"], {"bio": "refined"})
        self.assertEqual(mg.public_view(slug)["profile_updated_at"], "2026-11-06T00:00:00Z")

    def test_source_files_gone(self):
        a = self.scan()
        shutil.rmtree(mg.media_dir(a["slug"]))
        b = self.scan()
        self.assertHit(b, a)
        self.assertEqual(json.loads(self.req("GET", f"/api/media/{b['slug']}")[1])["status"], "none")

    def test_media_off(self):
        self.scan()
        with mock.patch.object(mg, "MEDIA_ENABLED", False):
            self.assertEqual(json.loads(self.stream()["result"][0])["media"], {"status": "none"})

    def test_avatar_gone_is_said(self):
        a = self.scan()
        os.remove(public_app._avatar_path(a["slug"]))
        b = self.scan()
        self.assertFalse(b["profile"]["avatar"])
        self.assertEqual(self.req("GET", f"/api/avatar/{b['slug']}")[0].status, 404)

    def test_mega_carried(self):
        a = self.scan(ls.HANDLE)
        self.assertTrue(a["mega"])
        self.assertEqual(self.scan(ls.HANDLE)["mega"], a["mega"])


if __name__ == "__main__":
    unittest.main()

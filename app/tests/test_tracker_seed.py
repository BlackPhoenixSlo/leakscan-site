"""Seed + the Quick scan's private candidate step (ticket 03) (Seam 5). Google CSE -> upstream_stub, the Mega
aggregator -> leakshaven_stub, probes -> tracker_stub_fetch; no real network. All data synthetic."""
import contextlib
import http.client
import json
import os
import queue
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

from tracker_fixture import Base, tdb, tracker_scheduler, tracker_seed, tracker_stub_fetch
import alias_enrich
import cse_scanner
import db
import leakshaven
import leakshaven_stub as ls
import media_gather
import profile_extract
import public_app
import upstream_stub

H = ls.HANDLE
GOOGLE = [
    {"title": "demo creator x videos", "link": f"https://leaksite.example/models/{H}/"},
    {"title": "Demo-Creator-X pics", "link": "https://tube.example/v/Demo.Creator.X?ref=1"},
    {"title": "Demo Creator X (@demo_creator_x)", "link": f"https://www.instagram.com/{H}/"},
    {"title": f"{H} leaked folder", "link": "https://forum.example/thread/991"},
    {"title": "mega", "link": f"https://t.me/{H}_leaks"},
    {"title": "unrelated", "link": "https://other.example/page/1"},
    {"title": "agg", "link": f"https://onlyfans.com/{H}"},
]


class Stubs(Base):
    @classmethod
    def setUpClass(cls):
        cls.cse, cls.up = upstream_stub.Stub().start(), ls.Stub().start()

    @classmethod
    def tearDownClass(cls):
        cls.cse.shutdown()
        cls.up.shutdown()

    def setUp(self):
        super().setUp()
        self.cse.calls, self.cse.cse_fault, self.up.mode, self.up.calls = [], None, "ok", []
        self.cse.alias_items = {H: GOOGLE}
        never = mock.Mock(side_effect=AssertionError("not on the private path"))
        for p in (mock.patch.object(db, "DB_PATH", os.path.join(self.tmp.name, "public.db")),
                  mock.patch.object(cse_scanner, "CSE_ENDPOINT", self.cse.base + "/customsearch/v1"),
                  mock.patch.multiple(public_app, PROFILE_ENABLED=True, ALIAS_ENRICH=True),
                  mock.patch.object(media_gather, "MEDIA_ENABLED", True),
                  mock.patch.object(media_gather, "start", never),
                  mock.patch.object(profile_extract, "build_profile", never),
                  mock.patch.object(alias_enrich, "discover", never),
                  mock.patch.object(db, "insert_scan", never),
                  mock.patch.multiple(leakshaven, BASE=self.up.base, ENABLED=True, MIN_GAP=0.0),
                  mock.patch.dict(os.environ, GOOGLE_API_KEY="fake", GOOGLE_CSE_ID="fake")):
            p.start()
            self.addCleanup(p.stop)
        db.init_db()

    def scans(self):
        with db._db() as c:
            return c.execute("SELECT count(*) FROM scans").fetchone()[0]


class TestQuickCandidates(Stubs):
    def test_private_step_items_and_mega_match_source(self):
        r = public_app.quick_candidates(H, ["Demo Creator X"])
        self.assertEqual(r["errors"], [])
        self.assertIn(f"https://leaksite.example/models/{H}/", [i["link"] for i in r["google"]])
        self.assertTrue(r["mega"])
        self.assertEqual({(m["match_source"], m["match_term"]) for m in r["mega"]}, {("handle", H)})
        self.assertEqual(self.scans(), 0)

    def test_public_lookup_keeps_its_shape(self):
        items, reason = leakshaven.result(leakshaven.start(H, []), leakshaven.TIMEOUT)
        self.assertEqual(reason, "ok")
        self.assertTrue(items and all("match_source" not in i and "match_term" not in i for i in items))
        self.assertEqual(leakshaven.match(ls.SUGGEST, [H]), ls.WHO)
        self.assertEqual(leakshaven.match_source(ls.SUGGEST, [H]), (ls.WHO, "handle", H))
        self.assertEqual(leakshaven.match_source([{"title": "Demo Creator X", "modelId": ls.MODEL}], [H, "zzz"],
                                                 ["Demo Creator X"])[1], "name")
        self.assertEqual(leakshaven.match_source([], [H]), (None, None, None))

    def test_unavailable(self):
        with mock.patch.dict(os.environ, GOOGLE_API_KEY=""):
            self.assertEqual(public_app.quick_candidates(H, []), {"google": [], "mega": [], "errors": ["unavailable"]})
        self.assertEqual(self.cse.calls, [])
        self.assertEqual(self.up.calls, [])


class TestSeed(Stubs):
    def leaks(self, wid):
        return {r["url"]: r for r in self.rows("SELECT * FROM leaks WHERE watch_id = ?", wid)}

    def test_admission_host_rules_and_pending(self):
        w = self.watch(self.tenant(), username=H, seeded=False)
        r = tracker_seed.run(w)
        leaks, pending = self.leaks(w), {p["url"] for p in self.rows("SELECT url FROM pending_hits")}
        google = {u for u, l in leaks.items() if l["kind"] != "mega"}
        self.assertEqual(google, {f"https://leaksite.example/models/{H}/", "https://tube.example/v/Demo.Creator.X?ref=1",
                                  f"https://t.me/{H}_leaks"})
        self.assertEqual(leaks[f"https://t.me/{H}_leaks"]["kind"], "telegram")
        self.assertEqual(leaks[f"https://leaksite.example/models/{H}/"]["leak_site"], "leaksite.example")
        self.assertEqual(pending, {"https://forum.example/thread/991"})
        mega = [l for l in leaks.values() if l["kind"] == "mega"]
        self.assertTrue(mega and all(l["leak_site"] == "leakshaven.com" for l in mega))
        self.assertEqual((r["admitted"], r["pending"], r["outcome"]), (3 + len(mega), 1, "ok"))
        page = leaks[f"https://leaksite.example/models/{H}/"]["leak_id"]
        self.assertEqual([(e["type"], e["data"]) for e in self.events(page)],
                         [("seen", {"source": "google_web", "first_scan": True}), ("google_seen", {}),
                          ("status", {"from": None, "to": "live", "dead_since": None})])
        self.assertEqual([e["data"]["source"] for e in self.events(mega[0]["leak_id"])], ["mega_index"])
        self.assertEqual(self.scans(), 0)
        w_row = self.rows("SELECT * FROM watches WHERE watch_id = ?", w)[0]
        self.assertEqual(w_row["seeded_at"], self.T0)
        self.assertEqual(sorted(tracker_stub_fetch.CALLS), sorted(u.partition("#")[0] for u, l in leaks.items()
                                                                  if l["kind"] == "page"))
        self.assertEqual(self.rows("SELECT outcome FROM daily_scans")[0]["outcome"], "ok")
        self.assertEqual(self.rows("SELECT lane, state, last_success_at FROM lane_state WHERE watch_id = ?", w),
                         [{"lane": "origin_probe", "state": "ok", "last_success_at": self.T0}])

    def test_short_needles_and_mega_match_source(self):
        def cand(handle, aliases):
            return {"errors": [], "google": [
                {"title": "x", "link": "https://a.example/abc/1"},
                {"title": "abcd set", "link": "https://b.example/2"},
                {"title": "y", "link": "https://c.example/abcd/3"},
                {"title": "z", "link": "https://d.example/a_b-c.d.e/4"},
            ], "mega": [
                {"url": "https://s.leakshaven.com/fk0001", "title": "m1", "match_source": "alias", "match_term": "abcde"},
                {"url": "https://s.leakshaven.com/fk0002", "title": "m2", "match_source": "alias", "match_term": "abcd"},
                {"url": "https://s.leakshaven.com/fk0003", "title": "m3", "match_source": "name", "match_term": "abcde"},
                {"url": "https://s.leakshaven.com/fk0004", "title": "m4", "match_source": "handle", "match_term": "abc"},
            ]}
        w = self.watch(self.tenant(), username="abc", aliases=["abcd", "A.B-C_D.E"], seeded=False)
        with mock.patch.object(tracker_seed, "_quick_candidates", return_value=cand):
            r = tracker_seed.run(w)
        self.assertEqual(set(self.leaks(w)), {"https://d.example/a_b-c.d.e/4", "https://s.leakshaven.com/fk0001"})
        self.assertEqual({p["url"] for p in self.rows("SELECT url FROM pending_hits")},
                         {"https://b.example/2", "https://c.example/abcd/3", "https://s.leakshaven.com/fk0002",
                          "https://s.leakshaven.com/fk0003", "https://s.leakshaven.com/fk0004"})
        self.assertEqual((r["admitted"], r["pending"]), (2, 5))

    def test_failed_seed_retried_by_the_next_daily_pass(self):
        self.cse.cse_fault = "429"
        self.clock("2026-11-02T02:00:00Z")
        w = self.watch(self.tenant(), username=H, seeded=False)
        self.assertEqual(tracker_seed.run(w)["outcome"], "failed")
        self.assertIsNone(self.rows("SELECT seeded_at FROM watches")[0]["seeded_at"])
        self.assertEqual(self.rows("SELECT * FROM leaks"), [])
        self.assertEqual(self.rows("SELECT outcome FROM daily_scans")[0]["outcome"], "failed")
        calls = len(self.cse.calls)
        self.clock("2026-11-02T04:30:00Z")
        self.assertEqual(tracker_scheduler.daily_pass()["seeded"], 1)
        self.assertGreater(len(self.cse.calls), calls)
        self.assertEqual(self.rows("SELECT outcome FROM daily_scans")[0]["outcome"], "failed")
        calls = len(self.cse.calls)
        self.clock("2026-11-02T04:31:00Z")
        self.assertEqual(tracker_scheduler.daily_pass()["seeded"], 0)
        self.assertEqual(len(self.cse.calls), calls)
        self.cse.cse_fault = None
        self.clock("2026-11-03T04:01:00Z")
        self.assertEqual(tracker_scheduler.daily_pass()["seeded"], 1)
        self.assertEqual(self.rows("SELECT seeded_at FROM watches")[0]["seeded_at"], "2026-11-03T04:01:00Z")
        self.assertTrue(self.leaks(w))
        self.assertEqual([(r["day"], r["outcome"]) for r in self.rows("SELECT * FROM daily_scans ORDER BY day")],
                         [("2026-11-02", "failed"), ("2026-11-03", "ok")])

    def test_seed_failed_after_daily_at_waits_for_the_next_day(self):
        self.cse.cse_fault = "429"
        self.clock("2026-11-02T10:00:00Z")
        w = self.watch(self.tenant(), username=H, seeded=False)
        self.assertEqual(tracker_seed.run(w)["outcome"], "failed")
        calls = len(self.cse.calls)
        self.cse.cse_fault = None
        self.clock("2026-11-02T10:01:00Z")
        self.assertEqual(tracker_scheduler.daily_pass()["seeded"], 0)
        self.assertEqual(len(self.cse.calls), calls)
        self.clock("2026-11-03T04:00:00Z")
        self.assertEqual(tracker_scheduler.daily_pass()["seeded"], 1)
        self.assertTrue(self.leaks(w))

    def test_seed_raising_after_the_candidate_step_finishes_failed_and_the_pass_goes_on(self):
        calls = []
        t = self.tenant()
        x = self.watch(t, username=H, seeded=False)
        y, z = self.watch(t), self.watch(self.tenant("B"))
        self.leak(y, "https://leaksite.example/mia_vale/1")
        self.leak(z, "https://tube.example/v/mia_vale")
        real = tracker_seed.tracker_probe.run

        def probe(ids):
            if ids == [z]:
                raise RuntimeError("boom")
            return real(ids)

        with mock.patch.object(tracker_seed, "_quick_candidates",
                               return_value=lambda h, a: calls.append(h) or {"errors": [], "google": GOOGLE, "mega": []}), \
                mock.patch.object(tracker_seed.rules, "host_class", side_effect=RuntimeError("boom")), \
                mock.patch.object(tracker_scheduler.tracker_probe, "run", side_effect=probe):
            r = tracker_scheduler.daily_pass()
            self.clock("2026-11-02T05:01:00Z")
            tracker_scheduler.daily_pass()
        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(r["purged"])
        self.assertEqual(tracker_stub_fetch.CALLS, ["https://leaksite.example/mia_vale/1"])
        self.assertEqual({d["watch_id"]: d["outcome"] for d in self.rows("SELECT * FROM daily_scans")},
                         {x: "failed", y: "ok", z: "failed"})

    def test_concurrent_passes_seed_a_watch_once(self):
        entered, release, calls = threading.Event(), threading.Event(), []

        def cand(h, a):
            calls.append(h)
            entered.set()
            release.wait(5)
            return {"errors": [], "google": GOOGLE, "mega": []}

        @contextlib.contextmanager
        def no_lock(ids):
            yield list(ids)

        w = self.watch(self.tenant(), username=H, seeded=False)
        with mock.patch.object(tracker_seed, "_quick_candidates", return_value=cand), \
                mock.patch.object(tracker_seed, "claim_all", no_lock):
            first = threading.Thread(target=tracker_scheduler.daily_pass)
            first.start()
            self.assertTrue(entered.wait(5))
            second = tracker_scheduler.daily_pass()
            release.set()
            first.join(10)
        self.assertEqual(len(calls), 1)
        self.assertEqual(second["seeded"], 0)
        self.assertTrue(self.leaks(w))
        self.assertEqual(self.rows("SELECT outcome FROM daily_scans")[0]["outcome"], "ok")

    def test_unavailable_google_fails_the_seed(self):
        w = self.watch(self.tenant(), username=H, seeded=False)
        with mock.patch.dict(os.environ, GOOGLE_API_KEY=""):
            self.assertEqual(tracker_seed.run(w)["outcome"], "failed")
        self.assertEqual(self.up.calls, [])

    def test_post_daily_at_enrolment_probed_once_that_day(self):
        self.clock("2026-11-02T10:00:00Z")
        w = self.watch(self.tenant(), username=H, seeded=False)
        tracker_seed.run(w)
        first = len(tracker_stub_fetch.CALLS)
        self.assertEqual(first, 2)
        self.clock("2026-11-02T10:01:00Z")
        self.assertEqual(tracker_scheduler.daily_pass()["fetched"], 0)
        self.clock("2026-11-02T23:59:00Z")
        tracker_scheduler.daily_pass()
        self.assertEqual(len(tracker_stub_fetch.CALLS), first)
        self.clock("2026-11-03T04:00:00Z")
        tracker_scheduler.daily_pass()
        self.assertEqual(len(tracker_stub_fetch.CALLS), 2 * first)

    def test_skips_paused_deleted_seeded_and_busy(self):
        t = self.tenant()
        for kw in ({"paused": True}, {"deleted_at": self.T0}, {}):
            w = self.watch(t, username=H, seeded=not kw, **kw)
            self.assertIsNone(tracker_seed.run(w))
        w = self.watch(t, username=H, seeded=False)
        with tracker_seed.claim_all([w]):
            self.assertIsNone(tracker_seed.run(w))
        self.assertEqual(self.cse.calls, [])

    def test_inline_start(self):
        w = self.watch(self.tenant(), username=H, seeded=False)
        with mock.patch.dict(os.environ, TRACKER_SEED_INLINE="1"):
            self.assertEqual(tracker_seed.start(w)["outcome"], "ok")


def until(cond, timeout=10):
    end = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > end:
            return False
        time.sleep(0.01)
    return True


class TestPool(Stubs):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.api = ThreadingHTTPServer(("127.0.0.1", 0), public_app.Handler)
        threading.Thread(target=cls.api.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.api.shutdown()
        cls.api.server_close()

    def setUp(self):
        super().setUp()
        self.running, self.peak, self.calls, self.release = 0, 0, [], threading.Event()
        self.addCleanup(self.release.set)
        for p in (mock.patch.multiple(tracker_seed, _Q=queue.Queue(), _workers=[], _pending=set()),
                  mock.patch.object(tracker_seed, "_quick_candidates", return_value=self.cand)):
            p.start()
            self.addCleanup(p.stop)
        self.t = self.tenant()
        self.key = tdb.new_key()
        with tdb.db() as c:
            c.execute("UPDATE tenants SET creators_max = 50 WHERE tenant_id = ?", (self.t,))
            c.execute("INSERT INTO tenant_keys (key_hash, tenant_id, issued_at) VALUES (?,?,?)",
                      (tdb.key_hash(self.key), self.t, tdb.now()))

    def cand(self, h, a):
        with tracker_seed._LOCK:
            self.calls.append(h)
            self.running += 1
            self.peak = max(self.peak, self.running)
        self.release.wait(10)
        with tracker_seed._LOCK:
            self.running -= 1
        return {"errors": [], "google": GOOGLE, "mega": []}

    def put(self, i):
        c = http.client.HTTPConnection("127.0.0.1", self.api.server_address[1], timeout=10)
        body = {"account_id": f"acc-{i}", "platform": "onlyfans", "username": f"rowan_ash{i}", "verified": True,
                "paused": False}
        c.request("PUT", f"/v1/watches/w_rowan_{i:05d}", body=json.dumps(body),
                  headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        r = c.getresponse()
        out = r.status, json.loads(r.read())
        c.close()
        return out

    def seeded(self):
        return self.rows("SELECT COUNT(*) AS n FROM watches WHERE seeded_at IS NOT NULL")[0]["n"]

    def test_put_burst_runs_at_most_k_seeds_at_once_and_all_seed(self):
        with mock.patch.dict(os.environ, TRACKER_SEED_WORKERS="3", TRACKER_UNCAPPED_TENANTS=self.t):
            for i in range(10):
                self.assertEqual(self.put(i), (200, {"watch_id": f"w_rowan_{i:05d}", "created": True,
                                                     "seeded": False}))
            self.assertTrue(until(lambda: self.running == 3))
            time.sleep(0.2)
            self.assertEqual((self.running, self.peak, tracker_seed._Q.qsize()), (3, 3, 7))
            tracker_seed.start("w_rowan_00009")
            self.assertEqual(tracker_seed._Q.qsize(), 7)
            self.release.set()
            self.assertTrue(until(lambda: self.seeded() == 10))
        self.assertEqual(self.peak, 3)
        self.assertEqual(sorted(self.calls), sorted(f"rowan_ash{i}" for i in range(10)))
        self.assertEqual(len(tracker_seed._workers), 3)
        self.assertTrue(until(lambda: not tracker_seed._pending))

    def test_worker_survives_a_raising_seed(self):
        self.release.set()
        bad, good = (self.watch(self.t, username=f"rowan_ash{i}", seeded=False) for i in (1, 2))
        real = tracker_seed._run
        with mock.patch.object(tracker_seed, "_run",
                               side_effect=lambda w, c: (_ for _ in ()).throw(RuntimeError) if w == bad else real(w, c)):
            tracker_seed.start(bad)
            tracker_seed.start(good)
            self.assertTrue(until(lambda: self.seeded() == 1))
        self.assertEqual(len(tracker_seed._workers), 2)
        self.assertTrue(all(t.is_alive() for t in tracker_seed._workers))
        self.assertEqual(self.rows("SELECT watch_id FROM watches WHERE seeded_at IS NOT NULL"), [{"watch_id": good}])

    def test_inline_runs_in_the_caller_and_starts_no_worker(self):
        self.release.set()
        w = self.watch(self.t, username=H, seeded=False)
        with mock.patch.dict(os.environ, TRACKER_SEED_INLINE="1"):
            self.assertEqual(tracker_seed.start(w)["outcome"], "ok")
        self.assertEqual(tracker_seed._workers, [])

    def test_pool_seed_and_daily_pass_never_double_run(self):
        w = self.watch(self.t, username=H, seeded=False)
        tracker_seed.start(w)
        self.assertTrue(until(lambda: self.running == 1))
        self.assertEqual(tracker_scheduler.daily_pass()["seeded"], 0)
        self.release.set()
        self.assertTrue(until(lambda: self.seeded() == 1))
        self.assertEqual(self.calls, [H])
        self.assertEqual(self.rows("SELECT outcome FROM daily_scans WHERE watch_id = ?", w), [{"outcome": "ok"}])

    def test_daily_pass_seeds_what_the_pool_lost(self):
        self.release.set()
        w = self.watch(self.t, username=H, seeded=False)
        self.assertEqual(tracker_scheduler.daily_pass()["seeded"], 1)
        tracker_seed.start(w)
        self.assertTrue(until(lambda: not tracker_seed._pending))
        self.assertEqual(self.calls, [H])


if __name__ == "__main__":
    unittest.main()

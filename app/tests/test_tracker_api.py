"""Tracker API v1 over HTTP (spec Seam 5, API part): the real public_app.Handler on loopback, temp TRACKER_DB + PUBLIC_DB,
fixed clock, tracker_seed.start stubbed. Goldens: tests/contract/v1/*.json (UPDATE_GOLDEN=1 rewrites them). All data fictional."""
import http.client
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from unittest import mock

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
import db
import public_app
import tracker_db
import tracker_judge
import tracker_lanes
import tracker_plan
import tracker_seed
import tracker_view

GOLDEN = os.path.join(os.path.dirname(APP), "tests", "contract", "v1")
ORIGIN = "https://blackphoenixslo.github.io"
NOW = datetime(2026, 11, 27, 12, 0, 0, tzinfo=timezone.utc)
DROP = object()


def ts(dt):
    return tracker_db.fmt(dt)


def body(**over):
    b = {"account_id": "acc-1001", "platform": "onlyfans", "username": "miavale", "verified": True, "display_name": "Mia Vale",
         "aliases": ["mia.vale.x"], "instagram": "miavale", "x": "miavale", "paused": False}
    b.update(over)
    return {k: v for k, v in b.items() if v is not DROP}


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.ctmp.name, "public.db")
        db.init_db()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), public_app.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.ctmp.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = {k: v for k, v in os.environ.items() if k not in ("TRACKER_DAILY_AT", "TRACKER_BRAND", "TRACKER_CONTACT_URL")}
        env["TRACKER_DB"] = os.path.join(self.tmp.name, "tracker.db")
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.seeds = []
        p = mock.patch.object(tracker_seed, "start", side_effect=self.seeds.append)
        p.start()
        self.addCleanup(p.stop)
        self.clock = NOW
        tracker_db.set_clock(lambda: self.clock)
        self.addCleanup(tracker_db.set_clock, None)
        tracker_db.init()
        self.a = self.tenant("tn_tenant_a", "Agency A")
        self.b = self.tenant("tn_tenant_b", "Agency B")

    def tenant(self, tid, label, cap=5):
        key = tracker_db.new_key()
        with tracker_db.db() as c:
            c.execute("INSERT INTO tenants (tenant_id, label, creators_max, created_at) VALUES (?,?,?,?)", (tid, label, cap, ts(NOW)))
            c.execute("INSERT INTO tenant_keys (key_hash, tenant_id, issued_at) VALUES (?,?,?)", (tracker_db.key_hash(key), tid, ts(NOW)))
        return key

    def req(self, method, path, data=None, key=None, headers=None, raw=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        h = dict(headers or {})
        if key:
            h["Authorization"] = f"Bearer {key}"
        payload = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
        if payload is not None:
            h["Content-Type"] = "application/json"
        c.request(method, path, body=payload, headers=h)
        r = c.getresponse()
        text = r.read()
        c.close()
        return r.status, r, (json.loads(text) if text and "json" in (r.getheader("Content-Type") or "") else None)

    def put(self, wid, key=None, **over):
        return self.req("PUT", f"/v1/watches/{wid}", body(**over), key or self.a)

    def leak(self, wid, lid, url, kind="page", site="example-leaks.test", seen=None, source="google_web", first_scan=True,
             google=False, statuses=(), probe=None, title=None):
        seen = seen or ts(NOW - timedelta(days=7))
        with tracker_db.db() as c:
            c.execute("INSERT INTO leaks (leak_id, watch_id, url_key, url, leak_site, kind, title, created_at) VALUES (?,?,?,?,?,?,?,?)",
                      (lid, wid, url.lower(), url, site, kind, title, seen))
            tracker_db.add_event(c, lid, "seen", {"source": source, "first_scan": first_scan}, at=seen)
            if google:
                tracker_db.add_event(c, lid, "google_seen", {}, at=seen)
            for at, fr, to, dead in statuses:
                tracker_db.add_event(c, lid, "status", {"from": fr, "to": to, "dead_since": dead}, at=at)
            if probe:
                c.execute("INSERT INTO probe_state (leak_id, last_probe_at, last_live_at, consecutive_dead, last_status, origin_status, probes) "
                          "VALUES (?,?,?,?,?,?,?)", (lid, probe.get("at"), probe.get("live_at"), 2 if probe["origin"] == "gone" else 0,
                                                     probe.get("last", "dead" if probe["origin"] == "gone" else "live"), probe["origin"], 3))

    def watch(self, wid):
        with tracker_db.db() as c:
            return c.execute("SELECT * FROM watches WHERE watch_id = ?", (wid,)).fetchone()


class TestAuth(Base):
    def test_bearer(self):
        self.assertEqual(self.req("GET", "/v1/me", key=self.a)[0], 200)
        for key, hdr in ((None, None), ("ltk_" + "x" * 40, None), (None, {"Authorization": self.a}), (None, {"Authorization": "Basic " + self.a})):
            st, r, b = self.req("GET", "/v1/me", key=key, headers=hdr)
            self.assertEqual((st, b), (401, {"error": "unauthorized"}))
            self.assertEqual(r.getheader("WWW-Authenticate"), "Bearer")

    def test_revoked(self):
        with tracker_db.db() as c:
            c.execute("UPDATE tenant_keys SET revoked_at = ? WHERE tenant_id = 'tn_tenant_a'", (ts(NOW),))
        for m, p in (("GET", "/v1/me"), ("GET", "/v1/creators"), ("PUT", "/v1/watches/w_mia_00001"), ("DELETE", "/v1/watches/w_mia_00001")):
            self.assertEqual(self.req(m, p, body(), self.a)[0], 401, p)
        self.assertEqual(self.req("GET", "/v1/me", key=self.b)[0], 200)

    def test_me(self):
        self.put("w_mia_00001")
        self.put("w_ash_00002", account_id="acc-2", username="rowanash", aliases=[])
        self.put("w_bee_00003", self.b, account_id="acc-3")
        self.assertEqual(self.req("DELETE", "/v1/watches/w_ash_00002", key=self.a)[0], 204)
        st, r, b = self.req("GET", "/v1/me", key=self.a)
        self.assertEqual(b, {"tenant_id": "tn_tenant_a", "label": "Agency A", "brand": None, "contact_url": None, "creators_max": 5,
                             "creators_used": 1, "accepting_new": True})
        self.assertEqual(r.getheader("Cache-Control"), "no-store")
        with mock.patch.dict(os.environ, TRACKER_BRAND="Example Removal", TRACKER_CONTACT_URL="https://removal.example/contact"):
            b = self.req("GET", "/v1/me", key=self.a)[2]
        self.assertEqual((b["brand"], b["contact_url"]), ("Example Removal", "https://removal.example/contact"))

    def test_routes(self):
        self.assertEqual(self.req("GET", "/v1/nope", key=self.a)[::2], (404, {"error": "not_found"}))
        self.assertEqual(self.req("GET", "/v1", key=self.a)[::2], (404, {"error": "not_found"}))
        self.assertEqual(self.req("GET", "/v1/creators/", key=self.a)[::2], (404, {"error": "not_found"}))
        for m, p in (("POST", "/v1/me"), ("DELETE", "/v1/me"), ("GET", "/v1/watches/w_mia_00001"), ("POST", "/v1/watches/w_mia_00001"),
                     ("PUT", "/v1/creators"), ("POST", "/v1/leaks")):
            self.assertEqual(self.req(m, p, {}, self.a)[::2], (405, {"error": "method_not_allowed"}), (m, p))
        self.assertEqual(self.req("PUT", "/api/whatever", {}, self.a)[0], 501)
        self.assertEqual(self.req("GET", "/healthz")[0], 200)


class TestWatches(Base):
    def test_create_update_seed(self):
        st, _, b = self.put("w_mia_00001")
        self.assertEqual((st, b), (200, {"watch_id": "w_mia_00001", "created": True, "seeded": False}))
        self.assertEqual(self.seeds, ["w_mia_00001"])
        self.clock = NOW + timedelta(hours=1)
        st, _, b = self.put("w_mia_00001", display_name=None, aliases=["mia.vale.x", "miavaleofficial"], instagram=None, x=None, unknown_field=1)
        self.assertEqual(b, {"watch_id": "w_mia_00001", "created": False, "seeded": False})
        self.assertEqual(self.seeds, ["w_mia_00001"])
        w = self.watch("w_mia_00001")
        self.assertEqual((w["display_name"], json.loads(w["aliases_json"]), w["created_at"], w["updated_at"], w["verified"]),
                         (None, ["mia.vale.x", "miavaleofficial"], ts(NOW), ts(NOW + timedelta(hours=1)), 1))
        with tracker_db.db() as c:
            c.execute("UPDATE watches SET seeded_at = ? WHERE watch_id = 'w_mia_00001'", (ts(NOW),))
        self.assertTrue(self.put("w_mia_00001")[2]["seeded"])

    def test_seed_failure_still_creates(self):
        with mock.patch.object(tracker_seed, "start", side_effect=RuntimeError("boom")):
            self.assertEqual(self.put("w_mia_00001")[2], {"watch_id": "w_mia_00001", "created": True, "seeded": False})
        self.assertIsNotNone(self.watch("w_mia_00001"))

    def test_paused(self):
        self.put("w_mia_00001", paused=True)
        self.assertEqual(self.seeds, [])
        row = self.req("GET", "/v1/creators/w_mia_00001", key=self.a)[2]
        self.assertEqual((row["paused"], row["paused_since"]), (True, ts(NOW)))
        self.clock = NOW + timedelta(hours=2)
        self.put("w_mia_00001", paused=True)
        self.assertEqual(self.req("GET", "/v1/creators/w_mia_00001", key=self.a)[2]["paused_since"], ts(NOW))
        self.put("w_mia_00001", paused=False)
        row = self.req("GET", "/v1/creators/w_mia_00001", key=self.a)[2]
        self.assertEqual((row["paused"], row["paused_since"]), (False, None))
        self.assertEqual(self.seeds, [])
        self.clock = NOW + timedelta(hours=3)
        self.put("w_mia_00001", paused=True)
        self.assertEqual(self.req("GET", "/v1/creators", key=self.a)[2]["creators"][0]["paused_since"], ts(NOW + timedelta(hours=3)))

    def test_creator_cap(self):
        with tracker_db.db() as c:
            c.execute("UPDATE tenants SET creators_max = 2 WHERE tenant_id = 'tn_tenant_a'")
        self.put("w_one_00001", account_id="1")
        self.put("w_two_00002", account_id="2")
        self.assertEqual(self.put("w_three_0003", account_id="3")[::2], (409, {"error": "creator_cap", "creators_max": 2}))
        self.assertEqual(self.put("w_two_00002", account_id="2", paused=True)[0], 200)
        self.put("w_bee_00001", self.b, account_id="1")
        self.req("DELETE", "/v1/watches/w_one_00001", key=self.a)
        self.assertEqual(self.put("w_three_0003", account_id="3")[2]["created"], True)

    def test_waitlist_only_on_create(self):
        self.put("w_one_00001", account_id="1", paused=True)
        self.put("w_bee_00001", self.b, account_id="1")
        self.assertEqual([self.req("GET", "/v1/me", key=k)[2]["accepting_new"] for k in (self.a, self.b)], [True, True])
        with tracker_db.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 15")
        self.assertEqual([self.req("GET", "/v1/me", key=k)[2]["accepting_new"] for k in (self.a, self.b)], [False, False])
        self.assertEqual(self.put("w_two_00002", account_id="2")[::2], (409, {"error": "waitlist"}))
        self.assertIsNone(self.watch("w_two_00002"))
        self.assertEqual(self.seeds, ["w_bee_00001"])
        self.assertEqual(self.put("w_one_00001", account_id="1", paused=False)[::2],
                         (200, {"watch_id": "w_one_00001", "created": False, "seeded": False}))
        self.assertEqual(self.put("w_bee_00001", self.b, account_id="1", aliases=["mia.vale.x", "miavaleofficial"])[0], 200)
        with tracker_db.db() as c:
            c.execute("UPDATE tenants SET creators_max = 1 WHERE tenant_id = 'tn_tenant_a'")
        self.assertEqual(self.put("w_two_00002", account_id="2")[::2], (409, {"error": "creator_cap", "creators_max": 1}))
        with tracker_db.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 300")
        self.assertEqual(self.put("w_bee_00002", self.b, account_id="2")[2]["created"], True)
        self.assertEqual([(w["weekly_slot"], w["plan_loads"]) for w in map(self.watch, ("w_one_00001", "w_bee_00001", "w_bee_00002"))],
                         [(0, 13), (1, 17), (2, 13)])

    def test_public_cap(self):
        os.environ.update(TRACKER_PUBLIC_PER_HOUR="2", TRACKER_UNCAPPED_TENANTS="tn_owner")
        own = self.tenant("tn_owner", "Owner")
        self.put("w_one_00001", account_id="1")
        self.req("DELETE", "/v1/watches/w_one_00001", key=self.a)
        self.clock = NOW + timedelta(minutes=30)
        self.put("w_bee_00001", self.b, account_id="1")
        self.assertEqual(self.put("w_two_00002", account_id="2")[::2], (429, {"error": "rate_limited"}))
        with tracker_db.db() as c:
            self.assertIsNone(c.execute("SELECT 1 FROM watches WHERE watch_id = 'w_two_00002'").fetchone())
        self.assertEqual(self.seeds, ["w_one_00001", "w_bee_00001"])
        self.assertEqual(self.put("w_bee_00001", self.b, account_id="1", paused=True)[0], 200)
        self.assertEqual([self.put(f"w_own_0000{i}", own, account_id=str(i))[0] for i in range(3)], [200] * 3)
        self.clock = NOW + timedelta(minutes=61)
        self.assertEqual(self.put("w_two_00002", account_id="2")[2]["created"], True)

    def test_account_taken(self):
        self.put("w_mia_00001")
        self.assertEqual(self.put("w_dup_00002")[::2], (409, {"error": "account_taken", "watch_id": "w_mia_00001"}))
        self.put("w_ash_00002", account_id="acc-2", username="rowanash")
        self.assertEqual(self.put("w_ash_00002", account_id="acc-1001")[::2], (409, {"error": "account_taken", "watch_id": "w_mia_00001"}))
        self.assertEqual(self.put("w_bee_00003", self.b)[0], 200)
        self.req("DELETE", "/v1/watches/w_mia_00001", key=self.a)
        self.assertEqual(self.put("w_new_00004")[2]["created"], True)

    def test_tenant_isolation(self):
        self.put("w_bee_00001", self.b)
        self.leak("w_bee_00001", "lk_b1", "https://example-leaks.test/miavale")
        for p in ("/v1/creators/w_bee_00001", "/v1/creators/w_bee_00001/leaks"):
            self.assertEqual(self.req("GET", p, key=self.a)[::2], (404, {"error": "not_found"}), p)
        self.assertEqual(self.put("w_bee_00001", account_id="acc-9")[::2], (404, {"error": "not_found"}))
        self.assertEqual(self.req("GET", "/v1/creators", key=self.a)[2]["creators"], [])
        st, _, b = self.req("DELETE", "/v1/watches/w_bee_00001", key=self.a)
        self.assertEqual((st, b), (204, None))
        self.assertIsNone(self.watch("w_bee_00001")["deleted_at"])
        self.assertEqual([c["watch_id"] for c in self.req("GET", "/v1/creators", key=self.b)[2]["creators"]], ["w_bee_00001"])
        self.assertEqual(len(self.req("GET", "/v1/creators/w_bee_00001/leaks", key=self.b)[2]["leaks"]), 1)

    def test_410(self):
        self.put("w_mia_00001")
        self.assertEqual(self.req("DELETE", "/v1/watches/w_mia_00001", key=self.a)[0], 204)
        for m, p, d in (("GET", "/v1/creators/w_mia_00001", None), ("GET", "/v1/creators/w_mia_00001/leaks", None),
                        ("PUT", "/v1/watches/w_mia_00001", body())):
            self.assertEqual(self.req(m, p, d, self.a)[::2], (410, {"error": "watch_deleted"}), (m, p))
        self.assertEqual(self.req("DELETE", "/v1/watches/w_unseen_001", key=self.a)[0], 204)
        self.assertEqual(self.put("w_unseen_001")[::2], (410, {"error": "watch_deleted"}))
        self.assertEqual(self.req("GET", "/v1/creators/w_unseen_001", key=self.a)[0], 410)
        self.assertEqual(self.put("w_unseen_001", self.b)[::2], (404, {"error": "not_found"}))
        with tracker_db.db() as c:
            c.execute("INSERT INTO deleted_ids (watch_id, tenant_id, deleted_at) VALUES ('w_purged_01', 'tn_tenant_a', ?)", (ts(NOW),))
        self.assertEqual(self.put("w_purged_01")[0], 410)
        self.assertEqual(self.req("DELETE", "/v1/watches/w_purged_01", key=self.b)[0], 204)
        with tracker_db.db() as c:
            self.assertEqual(c.execute("SELECT tenant_id FROM deleted_ids WHERE watch_id = 'w_purged_01'").fetchone()[0], "tn_tenant_a")

    def test_delete_hides_and_clamps(self):
        created = NOW - timedelta(days=10)
        self.clock = created
        for i, wid in enumerate(("w_before_01", "w_future_02", "w_mid_00003", "w_none_0004", "w_bad_00005")):
            self.put(wid, account_id=f"acc-{i}")
            self.leak(wid, f"lk_{i}", f"https://example-leaks.test/miavale/{i}")
        self.clock = NOW
        ids = "&".join(f"watch_id={w}" for w in ("w_before_01", "w_future_02", "w_mid_00003", "w_none_0004", "w_bad_00005"))
        self.assertEqual(len(self.req("GET", f"/v1/leaks?{ids}", key=self.a)[2]["leaks"]), 5)
        q = urllib.parse.quote
        cases = {"w_before_01": (f"?requested_at={q(ts(created - timedelta(days=3)))}", created),
                 "w_future_02": (f"?requested_at={q(ts(NOW + timedelta(days=3)))}", NOW),
                 "w_mid_00003": (f"?requested_at={q('2026-11-20T08:30:00+00:00')}", datetime(2026, 11, 20, 8, 30, tzinfo=timezone.utc)),
                 "w_none_0004": ("", NOW),
                 "w_bad_00005": ("?requested_at=yesterday", NOW)}
        for wid, (qs, at) in cases.items():
            self.assertEqual(self.req("DELETE", f"/v1/watches/{wid}{qs}", key=self.a)[0], 204)
            w = self.watch(wid)
            self.assertEqual((w["deleted_at"], w["purge_after"]), (ts(NOW), ts(at + timedelta(days=30))), wid)
        self.assertEqual(self.req("GET", "/v1/creators", key=self.a)[2]["creators"], [])
        self.assertEqual(self.req("GET", f"/v1/leaks?{ids}", key=self.a)[2], {"leaks": [], "next_cursor": None})
        self.clock = NOW + timedelta(days=2)
        self.assertEqual(self.req("DELETE", "/v1/watches/w_none_0004", key=self.a)[0], 204)
        self.assertEqual(self.watch("w_none_0004")["purge_after"], ts(NOW + timedelta(days=30)))
        self.assertEqual(self.req("DELETE", "/v1/watches/bad", key=self.a)[0], 204)

    def test_422_fields(self):
        st, _, b = self.req("PUT", "/v1/watches/short", body(), self.a)
        self.assertEqual((st, b), (422, {"error": "invalid", "field": "watch_id"}))
        self.assertEqual(self.req("PUT", "/v1/watches/has.dot.123", body(), self.a)[2]["field"], "watch_id")
        bad = [("account_id", v) for v in ("", "   ", 5, "a" * 65, DROP)] + \
              [("platform", v) for v in ("instagram", None, DROP)] + \
              [("username", v) for v in ("a", "a" * 65, "mia vale", 5, DROP)] + \
              [("verified", v) for v in ("true", 1, None, DROP)] + \
              [("display_name", v) for v in (5, "a" * 65)] + \
              [("aliases", v) for v in ("mia.vale.x", ["abc"], ["a" * 65], [f"alias{i}" for i in range(6)], ["Mia.Vale.X", "mia.vale.x"],
                                        ["MIAVALE"], [5], ["m.i.a"], ["a-b_c"], ["%61%62%63"])] + \
              [("instagram", v) for v in ("", "a" * 31, "mia-vale", 5)] + \
              [("x", v) for v in ("", "a" * 16, "mia.vale")] + \
              [("paused", v) for v in ("no", 0, DROP)]
        for field, v in bad:
            st, _, b = self.put("w_mia_00001", **{field: v})
            self.assertEqual((st, b), (422, {"error": "invalid", "field": field}), (field, v))
        self.assertIsNone(self.watch("w_mia_00001"))
        ok = body(display_name=DROP, aliases=DROP, instagram=DROP, x=DROP, platform="fansly", username="mia.vale-x_2")
        self.assertEqual(self.req("PUT", "/v1/watches/w_mia_00001", ok, self.a)[0], 200)
        self.assertEqual(self.put("w_mia_00001", aliases=[f"alias{i}" for i in range(5)], display_name="a" * 64, instagram="a" * 30,
                                  x="a" * 15)[0], 200)
        self.assertEqual(self.put("w_mia_00001", aliases=["v.e.e.x"])[0], 200)

    def test_transfer_encoding_refused(self):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        c.putrequest("PUT", "/v1/watches/w_mia_00001")
        for k, v in (("Authorization", f"Bearer {self.a}"), ("Content-Type", "application/json"), ("Transfer-Encoding", "chunked")):
            c.putheader(k, v)
        c.endheaders()
        c.send(b"5\r\nhello\r\n0\r\n\r\n")
        r = c.getresponse()
        self.assertEqual((r.status, json.loads(r.read()), r.getheader("Connection")), (411, {"error": "length_required"}, "close"))
        c.close()
        self.assertIsNone(self.watch("w_mia_00001"))

    def test_invalid_json_and_cap(self):
        for raw in (b"{nope", b"[1,2]", b"", b"\xff\xfe", b"null"):
            st, _, b = self.req("PUT", "/v1/watches/w_mia_00001", key=self.a, raw=raw)
            self.assertEqual((st, b), (422, {"error": "invalid_json", "field": None}), raw)
        st, _, b = self.req("PUT", "/v1/watches/w_mia_00001", key=self.a, raw=b" " * (64 * 1024 + 1))
        self.assertEqual((st, b), (413, {"error": "payload_too_large"}))
        self.assertEqual(self.req("PUT", "/v1/watches/w_mia_00001", key=self.a,
                                  raw=json.dumps(body()).encode() + b" " * (64 * 1024 - 300))[0], 200)


class TestLeaks(Base):
    def setUp(self):
        super().setUp()
        self.put("w_mia_00001")
        self.put("w_ash_00002", account_id="acc-2", username="rowanash", aliases=[])
        self.put("w_old_00003", account_id="acc-3", username="oldone", aliases=[])
        self.put("w_bee_00001", self.b)
        day = NOW - timedelta(days=5)
        self.leak("w_mia_00001", "lk_a", "https://example-leaks.test/a", seen=ts(day))
        self.leak("w_mia_00001", "lk_c", "https://example-leaks.test/c", seen=ts(day))
        self.leak("w_ash_00002", "lk_b", "https://example-leaks.test/b", seen=ts(day))
        self.leak("w_ash_00002", "lk_d", "https://example-leaks.test/d", seen=ts(day + timedelta(hours=3)))
        self.leak("w_mia_00001", "lk_e", "https://example-leaks.test/e", seen=ts(day - timedelta(days=1)))
        self.leak("w_old_00003", "lk_old", "https://example-leaks.test/old", seen=ts(NOW))
        self.leak("w_bee_00001", "lk_bee", "https://example-leaks.test/bee", seen=ts(NOW))
        self.req("DELETE", "/v1/watches/w_old_00003", key=self.a)
        self.req("DELETE", "/v1/watches/w_unseen_01", key=self.a)
        self.ids = "watch_id=w_mia_00001&watch_id=w_ash_00002&watch_id=w_old_00003&watch_id=w_bee_00001&watch_id=w_unseen_01" \
                   "&watch_id=w_never_001&watch_id=bad!&watch_id=w_mia_00001"
        self.order = ["lk_d", "lk_a", "lk_b", "lk_c", "lk_e"]

    def test_order_skip_and_fields(self):
        st, _, b = self.req("GET", f"/v1/leaks?{self.ids}", key=self.a)
        self.assertEqual(st, 200)
        self.assertEqual([x["leak_id"] for x in b["leaks"]], self.order)
        self.assertIsNone(b["next_cursor"])
        self.assertEqual(set(b["leaks"][0]), {"watch_id", "leak_id", "url", "leak_site", "kind", "sources", "title", "pill", "came_back",
                                              "found_on_first_scan", "first_seen_at", "last_up_at", "last_probe_at", "origin_status"})
        self.assertEqual(b["leaks"][0]["watch_id"], "w_ash_00002")
        st, _, b = self.req("GET", "/v1/leaks?watch_id=w_old_00003&watch_id=w_bee_00001", key=self.a)
        self.assertEqual((st, b), (200, {"leaks": [], "next_cursor": None}))

    def test_cursor_paging(self):
        got, cur, pages = [], "", 0
        while True:
            st, _, b = self.req("GET", f"/v1/leaks?{self.ids}&limit=2" + (f"&cursor={cur}" if cur else ""), key=self.a)
            self.assertEqual(st, 200)
            got += [x["leak_id"] for x in b["leaks"]]
            pages += 1
            if not b["next_cursor"]:
                break
            cur = b["next_cursor"]
            self.assertRegex(cur, r"^[A-Za-z0-9_-]+$")
        self.assertEqual((got, pages), (self.order, 3))
        b = self.req("GET", "/v1/creators/w_mia_00001/leaks?limit=1", key=self.a)[2]
        self.assertEqual([x["leak_id"] for x in b["leaks"]], ["lk_a"])
        b = self.req("GET", f"/v1/creators/w_mia_00001/leaks?limit=200&cursor={b['next_cursor']}", key=self.a)[2]
        self.assertEqual(([x["leak_id"] for x in b["leaks"]], b["next_cursor"]), (["lk_c", "lk_e"], None))
        self.assertNotIn("watch_id", b["leaks"][0])
        self.assertEqual(b["leaks"][0]["events"][0]["type"], "seen")

    def test_422(self):
        many = "&".join(f"watch_id=w_{i:08d}" for i in range(501))
        five_hundred = "&".join(f"watch_id=w_{i:08d}" for i in range(500))
        for qs, field in (("", "watch_id"), ("watch_id=", "watch_id"), (many, "watch_id"), (f"{self.ids}&limit=201", "limit"),
                          (f"{self.ids}&limit=0", "limit"), (f"{self.ids}&limit=ten", "limit"), (f"{self.ids}&limit=-1", "limit"),
                          (f"{self.ids}&cursor=!!!", "cursor"), (f"{self.ids}&cursor=Zm9v", "cursor")):
            st, _, b = self.req("GET", f"/v1/leaks?{qs}", key=self.a)
            self.assertEqual((st, b), (422, {"error": "invalid", "field": field}), qs[:60])
        self.assertEqual(self.req("GET", f"/v1/leaks?{five_hundred}&limit=200", key=self.a)[0], 200)
        for qs, field in (("limit=201", "limit"), ("cursor=Zm9v", "cursor")):
            self.assertEqual(self.req("GET", f"/v1/creators/w_mia_00001/leaks?{qs}", key=self.a)[2], {"error": "invalid", "field": field})


class TestPill(Base):
    def test_rule(self):
        ev = lambda *types: [{"at": ts(NOW), "type": t, "data": d} for t, d in types]
        gone, live, g = ("status", {"from": "live", "to": "gone"}), ("status", {"from": "gone", "to": "live"}), ("google_seen", {})
        for kind, origin, events, want in (("page", None, [], "not_checked"), ("page", "live", [], "live"), ("page", "gone", [], "gone"),
                                           ("page", "gone", ev(g), "cached"), ("mega", None, [], "listed"), ("filehost", None, ev(g), "listed"),
                                           ("mega", None, ev(gone), "gone"), ("mega", None, ev(g, gone), "cached"),
                                           ("telegram", None, ev(gone, live), "listed")):
            self.assertEqual(tracker_view.pill(kind, origin, events), want, (kind, origin, events))

    def test_google_visibility(self):
        ev = lambda *vis: [{"at": ts(NOW), "type": "google_seen", "data": {} if v is ... else {"visible": v}} for v in vis]
        gone = {"at": ts(NOW), "type": "status", "data": {"from": "live", "to": "gone"}}
        for events, want in ((ev(...), "cached"), (ev(True), "cached"), (ev(False), "gone"), (ev(None), "gone"),
                             (ev(True, False), "gone"), (ev(False, True), "cached"), (ev(True, None), "gone")):
            self.assertEqual(tracker_view.pill("page", "gone", events), want, events)
            self.assertEqual(tracker_view.pill("mega", None, events + [gone]), want, events)

    def test_over_http(self):
        self.put("w_mia_00001")
        d = lambda n: ts(NOW - timedelta(days=n))
        self.leak("w_mia_00001", "lk_nc", "https://example-leaks.test/nc", seen=d(1), probe={"origin": None, "at": d(0), "last": "blocked"})
        self.leak("w_mia_00001", "lk_live", "https://example-leaks.test/live", seen=d(2), probe={"origin": "live", "at": d(0), "live_at": d(0)})
        self.leak("w_mia_00001", "lk_gone", "https://example-leaks.test/gone", seen=d(3), probe={"origin": "gone", "at": d(0), "live_at": d(3)},
                  statuses=[(d(3), None, "live", None), (d(1), "live", "gone", d(2))])
        self.leak("w_mia_00001", "lk_cached", "https://example-leaks.test/cached", seen=d(4), google=True,
                  probe={"origin": "gone", "at": d(0), "live_at": d(4)})
        self.leak("w_mia_00001", "lk_mega", "https://mega.example-index.test/f/1", kind="mega", site="example-index.test", seen=d(5),
                  source="mega_index")
        self.leak("w_mia_00001", "lk_fh", "https://files.example-host.test/x", kind="filehost", site="example-host.test", seen=d(6))
        self.leak("w_mia_00001", "lk_megagone", "https://mega.example-index.test/f/2", kind="mega", site="example-index.test", seen=d(7),
                  statuses=[(d(1), None, "gone", None)])
        self.leak("w_mia_00001", "lk_back", "https://example-leaks.test/back", seen=d(40), first_scan=False,
                  probe={"origin": "live", "at": d(0), "live_at": d(0)},
                  statuses=[(d(40), None, "live", None), (d(35), "live", "gone", d(36)), (d(29), "gone", "live", None)])
        self.leak("w_mia_00001", "lk_old_back", "https://example-leaks.test/oldback", seen=d(50), first_scan=False,
                  probe={"origin": "live", "at": d(0), "live_at": d(0)},
                  statuses=[(d(50), None, "live", None), (d(45), "live", "gone", d(46)), (d(31), "gone", "live", None)])
        self.leak("w_mia_00001", "lk_back_gone", "https://example-leaks.test/backgone", seen=d(60), first_scan=False,
                  probe={"origin": "gone", "at": d(0), "live_at": d(5)},
                  statuses=[(d(60), None, "gone", d(61)), (d(10), "gone", "live", None), (d(3), "live", "gone", d(4))])
        b = self.req("GET", "/v1/creators/w_mia_00001/leaks", key=self.a)[2]
        got = {x["leak_id"]: (x["pill"], x["came_back"]) for x in b["leaks"]}
        self.assertEqual(got, {"lk_nc": ("not_checked", False), "lk_live": ("live", False), "lk_gone": ("gone", False),
                               "lk_cached": ("cached", False), "lk_mega": ("listed", False), "lk_fh": ("listed", False),
                               "lk_megagone": ("gone", False), "lk_back": ("live", True), "lk_old_back": ("live", False),
                               "lk_back_gone": ("gone", False)})
        gone = next(x for x in b["leaks"] if x["leak_id"] == "lk_gone")
        self.assertEqual((gone["last_up_at"], gone["last_probe_at"], gone["origin_status"], gone["sources"], gone["first_seen_at"]),
                         (d(3), d(0), "gone", ["google_web"], d(3)))
        self.assertEqual([e["data"].get("to") for e in gone["events"] if e["type"] == "status"], ["live", "gone"])
        with tracker_db.db() as c:
            c.execute("INSERT INTO daily_scans (watch_id, day, started_at, finished_at, outcome) VALUES ('w_mia_00001', '2026-11-26', ?, ?, 'ok')",
                      (d(1), d(1)))
            c.execute("INSERT INTO daily_scans (watch_id, day, started_at, finished_at, outcome) VALUES ('w_mia_00001', '2026-11-27', ?, ?, 'failed')",
                      (d(0), d(0)))
        self.leak("w_mia_00001", "lk_today", "https://example-leaks.test/today", seen=ts(NOW.replace(hour=4)), first_scan=False)
        self.leak("w_mia_00001", "lk_today_seed", "https://example-leaks.test/today-seed", seen=ts(NOW.replace(hour=9)))
        with mock.patch.dict(os.environ, TRACKER_DAILY_AT="13:30"):
            row = self.req("GET", "/v1/creators/w_mia_00001", key=self.a)[2]
        self.assertEqual(row["counts"], {"live": 3, "cached": 1, "gone": 3, "listed": 2, "not_checked": 3, "new_today": 1,
                                         "found_on_first_scan": 8, "came_back_30d": 1})
        self.assertEqual((row["last_checked_at"], row["next_check_at"], row["seeded"]), (d(1), "2026-11-27T13:30:00Z", False))
        self.assertEqual(self.req("GET", "/v1/creators/w_mia_00001", key=self.a)[2]["next_check_at"], "2026-11-28T04:00:00Z")
        self.clock = NOW.replace(hour=3, minute=59)
        self.assertEqual(self.req("GET", "/v1/creators/w_mia_00001", key=self.a)[2]["next_check_at"], "2026-11-27T04:00:00Z")
        self.clock = NOW.replace(hour=4, minute=0)
        self.assertEqual(self.req("GET", "/v1/creators/w_mia_00001", key=self.a)[2]["next_check_at"], "2026-11-28T04:00:00Z")


class TestLanes(Base):
    LANES = [("origin_probe", "daily"), ("mega_lookup", "daily"), ("listing_recheck", "daily"), ("google_fresh", "daily"),
             ("google_full", "weekly"), ("registry_crawl", "weekly")]

    def lane_row(self, wid, lane, state="ok", reason=None):
        with tracker_db.db() as c:
            c.execute("INSERT INTO lane_state (watch_id, lane, state, reason, last_attempt_at, last_success_at, next_attempt_on) "
                      "VALUES (?,?,?,?,?,?,?)", (wid, lane, state, reason, ts(NOW), ts(NOW - timedelta(days=1)), "2026-11-28"))

    def lanes(self, wid, key=None):
        st, _, b = self.req("GET", f"/v1/creators/{wid}", key=key or self.a)
        self.assertEqual(st, 200)
        return b["lanes"]

    def test_shape_never_ok_failed(self):
        self.put("w_mia_00001")
        never = {"state": "never", "reason": None, "last_success_at": None, "last_attempt_at": None, "next_attempt_on": None,
                 "trimmed": []}
        self.assertEqual(self.lanes("w_mia_00001"), [{"lane": n, "cadence": c, **never} for n, c in self.LANES])
        self.lane_row("w_mia_00001", "origin_probe")
        self.lane_row("w_mia_00001", "mega_lookup", "failed", "lane_failed")
        got = {x["lane"]: x for x in self.lanes("w_mia_00001")}
        self.assertEqual(got["mega_lookup"], {"lane": "mega_lookup", "cadence": "daily", "state": "failed", "reason": "lane_failed",
                                              "last_success_at": ts(NOW - timedelta(days=1)), "last_attempt_at": ts(NOW),
                                              "next_attempt_on": "2026-11-28", "trimmed": []})
        self.assertEqual(got["origin_probe"]["state"], "ok")
        self.assertNotIn("lanes", self.req("GET", "/v1/creators", key=self.a)[2]["creators"][0])

    def test_trimmed(self):
        self.put("w_mia_00001")
        self.lane_row("w_mia_00001", "google_full", "reduced", "cap_global")
        trimmed = [{"field": "alias:0", "value": "mia.vale.x"}, {"field": "instagram", "value": "mia.vale"},
                   {"field": "x", "value": "miavale"}]
        with tracker_db.db() as c:
            c.execute("UPDATE lane_state SET trimmed_json = ? WHERE lane = 'google_full'", (json.dumps(trimmed),))
        got = {x["lane"]: x for x in self.lanes("w_mia_00001")}
        self.assertEqual({k: got["google_full"][k] for k in ("cadence", "state", "reason", "trimmed")},
                         {"cadence": "weekly", "state": "reduced", "reason": "cap_global", "trimmed": trimmed})
        self.assertEqual({x["lane"]: x["trimmed"] for x in got.values() if x["lane"] != "google_full"},
                         dict.fromkeys([n for n, _ in self.LANES if n != "google_full"], []))

    def test_paused(self):
        self.put("w_mia_00001")
        self.lane_row("w_mia_00001", "mega_lookup")
        self.put("w_mia_00001", paused=True)
        got = self.lanes("w_mia_00001")
        self.assertEqual({x["state"] for x in got}, {"paused"})
        self.assertEqual([x["last_success_at"] for x in got], [None, ts(NOW - timedelta(days=1)), None, None, None, None])
        self.assertEqual({x["next_attempt_on"] for x in got}, {None})

    def test_tenant_isolation(self):
        self.put("w_mia_00001")
        self.put("w_rowan_0001", key=self.b, account_id="acc-2001", username="rowanash", display_name="Rowan Ash", aliases=[])
        self.lane_row("w_mia_00001", "mega_lookup")
        self.assertEqual(self.req("GET", "/v1/creators/w_mia_00001", key=self.b)[:3:2], (404, {"error": "not_found"}))
        self.assertEqual({x["state"] for x in self.lanes("w_rowan_0001", key=self.b)}, {"never"})
        self.assertEqual(next(x for x in self.lanes("w_mia_00001") if x["lane"] == "mega_lookup")["state"], "ok")


class TestToday(Base):
    DAY = "2026-11-27"

    def scan(self, wid, finished=True, outcome="ok", day=DAY):
        with tracker_db.db() as c:
            c.execute("INSERT OR REPLACE INTO daily_scans (watch_id, day, started_at, finished_at, outcome) VALUES (?,?,?,?,?)",
                      (wid, day, f"{day}T04:00:00Z", f"{day}T04:05:00Z" if finished else None, outcome if finished else None))

    def lane_day(self, wid, lane, outcome, reason=None, day=DAY):
        with tracker_db.db() as c:
            c.execute("INSERT OR REPLACE INTO lane_day (watch_id, day, lane, outcome, reason) VALUES (?,?,?,?,?)",
                      (wid, day, lane, outcome, reason))

    def today(self, wid="w_mia_00001", key=None):
        one = self.req("GET", f"/v1/creators/{wid}", key=key or self.a)[2]
        row = next(x for x in self.req("GET", "/v1/creators", key=key or self.a)[2]["creators"] if x["watch_id"] == wid)
        self.assertEqual(one["today"], row["today"])
        return row["today"]

    def state(self, wid="w_mia_00001"):
        return self.today(wid)["state"]

    def test_shape_and_counts(self):
        self.put("w_mia_00001")
        self.assertEqual(self.today(), {"day": self.DAY, "state": "pending", "new": 0, "first_scan": 0, "came_back": 0, "gone": 0})
        h = lambda hour, days=0: ts(NOW.replace(hour=hour) - timedelta(days=days))
        self.leak("w_mia_00001", "lk_new", "https://example-leaks.test/new", seen=h(4), first_scan=False)
        self.leak("w_mia_00001", "lk_new2", "https://example-leaks.test/new2", seen=h(0), first_scan=False)
        self.leak("w_mia_00001", "lk_first", "https://example-leaks.test/first", seen=h(4))
        self.leak("w_mia_00001", "lk_old_new", "https://example-leaks.test/oldnew", seen=h(23, 1), first_scan=False)
        self.leak("w_mia_00001", "lk_old_first", "https://example-leaks.test/oldfirst", seen=h(23, 1))
        self.leak("w_mia_00001", "lk_back", "https://example-leaks.test/back", seen=h(4, 9),
                  statuses=[(h(4, 9), None, "live", None), (h(4, 3), "live", "gone", h(4, 4)), (h(4), "gone", "live", None)])
        self.leak("w_mia_00001", "lk_back_old", "https://example-leaks.test/backold", seen=h(4, 9),
                  statuses=[(h(4, 5), "live", "gone", None), (h(4, 1), "gone", "live", None)])
        self.leak("w_mia_00001", "lk_gone", "https://example-leaks.test/gone", seen=h(4, 9),
                  statuses=[(h(4, 8), None, "live", None), (h(4), "live", "gone", h(4, 1))])
        self.leak("w_mia_00001", "lk_mega_gone", "https://mega.example-index.test/f/1", kind="mega", site="example-index.test",
                  seen=h(4, 9), source="mega_index", statuses=[(h(5), "live", "gone", None)])
        self.leak("w_mia_00001", "lk_gone_unseen", "https://example-leaks.test/goneunseen", seen=h(4, 2),
                  statuses=[(h(4), None, "gone", h(4, 1))])
        self.leak("w_mia_00001", "lk_gone_old", "https://example-leaks.test/goneold", seen=h(4, 9),
                  statuses=[(h(4, 1), "live", "gone", h(4, 2))])
        self.scan("w_mia_00001")
        t = self.today()
        self.assertEqual(t, {"day": self.DAY, "state": "complete", "new": 2, "first_scan": 1, "came_back": 1, "gone": 3})
        counts = self.req("GET", "/v1/creators/w_mia_00001", key=self.a)[2]["counts"]
        self.assertEqual(t["new"], counts["new_today"])
        self.clock = NOW + timedelta(days=1)
        self.assertEqual(self.today(), {"day": "2026-11-28", "state": "pending", "new": 0, "first_scan": 0, "came_back": 0,
                                        "gone": 0})

    def test_states(self):
        self.put("w_mia_00001")
        self.assertEqual(self.state(), "pending")
        self.scan("w_mia_00001", finished=False)
        self.lane_day("w_mia_00001", "mega_lookup", "failed", "lane_failed")
        self.assertEqual(self.state(), "pending")
        self.scan("w_mia_00001")
        self.assertEqual(self.state(), "partial")
        self.lane_day("w_mia_00001", "mega_lookup", "ok")
        self.assertEqual(self.state(), "complete")
        self.lane_day("w_mia_00001", "google_fresh", "partial", "google_failed")
        self.assertEqual(self.state(), "coverage_reduced")
        self.lane_day("w_mia_00001", "google_full", "partial", "google_failed")
        self.assertEqual(self.state(), "coverage_reduced")
        self.lane_day("w_mia_00001", "google_full", "partial", "cap_global")
        self.assertEqual(self.state(), "partial")
        self.lane_day("w_mia_00001", "google_full", "ok")
        self.lane_day("w_mia_00001", "listing_recheck", "partial", "listing_rotated")
        self.assertEqual(self.state(), "partial")
        self.lane_day("w_mia_00001", "listing_recheck", "ok")
        self.lane_day("w_mia_00001", "google_fresh", "ok")
        self.lane_day("w_mia_00001", "mega_lookup", "failed", "lane_failed", day="2026-11-26")
        self.assertEqual(self.state(), "complete")
        self.scan("w_mia_00001", outcome="failed")
        self.assertEqual(self.state(), "partial")
        self.scan("w_mia_00001", outcome="skipped")
        self.assertEqual(self.state(), "partial")
        self.put("w_mia_00001", paused=True)
        self.assertEqual(self.state(), "paused")
        self.put("w_mia_00001", paused=False)
        self.assertEqual(self.state(), "partial")

    def test_zero_leaks_failed_lane_partial(self):
        self.put("w_mia_00001")
        self.scan("w_mia_00001", outcome="partial")
        self.lane_day("w_mia_00001", "mega_lookup", "failed", "lane_failed")
        self.assertEqual(self.today(), {"day": self.DAY, "state": "partial", "new": 0, "first_scan": 0, "came_back": 0, "gone": 0})

    def test_tenant_isolation(self):
        self.put("w_mia_00001")
        self.put("w_rowan_0001", key=self.b, account_id="acc-2001", username="rowanash", display_name="Rowan Ash", aliases=[])
        self.leak("w_mia_00001", "lk_new", "https://example-leaks.test/new", seen=ts(NOW.replace(hour=4)), first_scan=False)
        self.scan("w_mia_00001")
        self.lane_day("w_mia_00001", "mega_lookup", "failed", "lane_failed")
        self.scan("w_rowan_0001")
        self.assertEqual(self.req("GET", "/v1/creators/w_mia_00001", key=self.b)[:3:2], (404, {"error": "not_found"}))
        self.assertEqual([x["watch_id"] for x in self.req("GET", "/v1/creators", key=self.b)[2]["creators"]], ["w_rowan_0001"])
        self.assertEqual(self.today("w_rowan_0001", key=self.b),
                         {"day": self.DAY, "state": "complete", "new": 0, "first_scan": 0, "came_back": 0, "gone": 0})
        t = self.today()
        self.assertEqual((t["state"], t["new"]), ("partial", 1))


class TestCors(Base):
    def test_no_cors_on_v1(self):
        self.put("w_mia_00001")
        with mock.patch.object(public_app, "PARTNER_KEY", "pk-example"):
            h = {"Origin": ORIGIN}
            for m, p, key in (("GET", "/v1/me", self.a), ("GET", "/v1/me?key=pk-example", self.a), ("GET", "/v1/me?key=pk-example", None),
                              ("GET", "/v1/creators", self.a), ("GET", "/v1/nope?key=pk-example", self.a),
                              ("PUT", "/v1/watches/w_mia_00001?key=pk-example", self.a), ("POST", "/v1/me", self.a),
                              ("DELETE", "/v1/watches/w_x_000001?key=pk-example", self.a), ("OPTIONS", "/v1/me", None),
                              ("OPTIONS", "/v1/watches/w_mia_00001?key=pk-example", None)):
                st, r, _ = self.req(m, p, body() if m == "PUT" else None, key, h)
                self.assertIsNone(r.getheader("Access-Control-Allow-Origin"), (m, p))
                self.assertIsNone(r.getheader("Access-Control-Allow-Methods"), (m, p))
                if m != "OPTIONS":
                    self.assertEqual(r.getheader("Cache-Control"), "no-store", (m, p))
            r = self.req("OPTIONS", "/api/public-scan", headers=h)[1]
            self.assertEqual(r.getheader("Access-Control-Allow-Origin"), ORIGIN)
            self.assertEqual(self.req("GET", "/healthz", headers=h)[1].getheader("Access-Control-Allow-Origin"), ORIGIN)
            other = {"Origin": "https://other.example"}
            self.assertIsNone(self.req("GET", "/healthz", headers=other)[1].getheader("Access-Control-Allow-Origin"))
            self.assertEqual(self.req("GET", "/healthz?key=pk-example", headers=other)[1].getheader("Access-Control-Allow-Origin"),
                             "https://other.example")


class TestCli(Base):
    def cli(self, *args, ok=True):
        p = subprocess.run([sys.executable, os.path.join(APP, "tracker_cli.py"), *args], capture_output=True, text=True, timeout=30,
                           env=dict(os.environ))
        if ok:
            self.assertEqual(p.returncode, 0, p.stderr)
        return p

    def test_tenant_and_keys(self):
        tid = self.cli("tenant", "add", "Example Agency", "--max", "3").stdout.strip()
        self.assertRegex(tid, r"^tn_[0-9a-f]{16}$")
        key = self.cli("key", "issue", tid).stdout.strip()
        self.assertRegex(key, r"^ltk_[A-Za-z0-9]{40}$")
        with tracker_db.db() as c:
            rows = [tuple(r) for r in c.execute("SELECT * FROM tenant_keys WHERE tenant_id = ?", (tid,))]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], tracker_db.key_hash(key))
        self.assertNotIn(key, repr(rows))
        b = self.req("GET", "/v1/me", key=key)[2]
        self.assertEqual((b["tenant_id"], b["label"], b["creators_max"]), (tid, "Example Agency", 3))
        self.cli("tenant", "cap", tid, "4")
        self.assertEqual(self.req("GET", "/v1/me", key=key)[2]["creators_max"], 4)
        self.assertIn(f"{tid}\tExample Agency\tmax=4\tused=0\tkeys=1", self.cli("tenant", "list").stdout)
        key2 = self.cli("key", "issue", tid).stdout.strip()
        self.assertEqual(self.cli("key", "revoke", tid).stdout.strip(), "revoked 2")
        for k in (key, key2):
            self.assertEqual(self.req("GET", "/v1/me", key=k)[0], 401)
        self.assertEqual(self.req("GET", "/v1/me", key=self.a)[0], 200)
        self.assertNotEqual(self.cli("key", "issue", "tn_missing", ok=False).returncode, 0)
        self.assertNotEqual(self.cli("tenant", "cap", "tn_missing", "2", ok=False).returncode, 0)


class TestContract(Base):
    """Golden bodies of every /v1 response; the CRM side's fakes are built from these files."""

    def scenario(self):
        out = {}
        key = self.tenant("tn_example0001", "Example Agency")

        def call(name, method, path, data=None, k=key):
            st, _, b = self.req(method, path, data, k)
            out[name] = {"method": method, "path": path, "request": data, "status": st, "response": b}

        with mock.patch.dict(os.environ, TRACKER_BRAND="Example Removal", TRACKER_CONTACT_URL="https://removal.example/contact"):
            self.clock = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
            mia = body(account_id="acc-1001")
            call("put_created", "PUT", "/v1/watches/w_miavale_0001", mia)
            call("put_updated", "PUT", "/v1/watches/w_miavale_0001", {**mia, "display_name": "Mia V."})
            self.req("PUT", "/v1/watches/w_rowanash_0002", body(account_id="acc-1002", username="rowanash", display_name="Rowan Ash",
                                                                aliases=[], instagram=None, x=None, verified=False, paused=True), key)
            self.clock = NOW
            d = lambda day, h=4, m=0: f"2026-11-{day:02d}T{h:02d}:{m:02d}:00Z"
            self.leak("w_miavale_0001", "lk_0001", "https://example-leaks.test/miavale-onlyfans-leak", seen=d(20, 9, 5), google=True,
                      title="miavale onlyfans leak", probe={"origin": "live", "at": d(27, 4, 1), "live_at": d(27, 4, 1)},
                      statuses=[(d(21, 4, 1), None, "live", None), (d(23, 4, 1), "live", "gone", d(22, 4, 1)),
                                (d(25, 4, 1), "gone", "live", None)])
            self.leak("w_miavale_0001", "lk_0002", "https://forum.example-leaks.test/t/mia.vale.x", seen=d(20, 9, 5), google=True,
                      title="mia.vale.x thread", probe={"origin": "gone", "at": d(27, 4, 1), "live_at": d(24, 4, 1)},
                      statuses=[(d(21, 4, 1), None, "live", None), (d(26, 4, 1), "live", "gone", d(25, 4, 1))])
            self.leak("w_miavale_0001", "lk_0003", "https://mega.example-index.test/folder/miavale", kind="mega",
                      site="example-index.test", seen=d(20, 9, 6), source="mega_index", title="miavale folder")
            self.leak("w_miavale_0001", "lk_0004", "https://pics.example-leaks.test/miavale/set-2", seen=d(27, 4, 2), first_scan=False,
                      google=True, title="miavale set 2")
            with tracker_db.db() as c:
                c.execute("INSERT INTO daily_scans (watch_id, day, started_at, finished_at, outcome) VALUES (?,?,?,?, 'ok')",
                          ("w_miavale_0001", "2026-11-27", d(27, 4, 0), d(27, 4, 5)))
                c.execute("UPDATE watches SET seeded_at = ? WHERE watch_id = 'w_miavale_0001'", (d(20, 9, 6),))
            call("me", "GET", "/v1/me")
            call("creators", "GET", "/v1/creators")
            with tracker_db.db() as c:
                c.executemany("INSERT INTO lane_state (watch_id, lane, state, reason, last_attempt_at, last_success_at, "
                              "next_attempt_on) VALUES ('w_miavale_0001',?,?,?,?,?,'2026-11-28')",
                              [("origin_probe", "ok", None, d(27, 4, 1), d(27, 4, 1)),
                               ("mega_lookup", "failed", "lane_failed", d(27, 4, 2), d(26, 4, 2))])
                c.execute("INSERT INTO lane_day (watch_id, day, lane, outcome, reason) VALUES "
                          "('w_miavale_0001', '2026-11-27', 'mega_lookup', 'failed', 'lane_failed')")
                c.execute("UPDATE daily_scans SET outcome = 'partial' WHERE watch_id = 'w_miavale_0001'")
            call("creator_one", "GET", "/v1/creators/w_miavale_0001")
            call("creator_leaks", "GET", "/v1/creators/w_miavale_0001/leaks")
            call("leaks", "GET", "/v1/leaks?watch_id=w_miavale_0001&watch_id=w_rowanash_0002&limit=2")
            call("leaks_page2", "GET", "/v1/leaks?watch_id=w_miavale_0001&watch_id=w_rowanash_0002&limit=2&cursor="
                 + out["leaks"]["response"]["next_cursor"])
            call("err_401", "GET", "/v1/me", k="ltk_" + "0" * 40)
            call("err_404", "GET", "/v1/creators/w_unknown_0009")
            call("err_405", "POST", "/v1/me", {})
            call("err_409_account_taken", "PUT", "/v1/watches/w_other_0003", body(account_id="acc-1001"))
            with tracker_db.db() as c:
                c.execute("UPDATE tenants SET creators_max = 2 WHERE tenant_id = 'tn_example0001'")
            call("err_409_creator_cap", "PUT", "/v1/watches/w_other_0003", body(account_id="acc-1003", username="example_three"))
            call("delete", "DELETE", "/v1/watches/w_rowanash_0002?requested_at=2026-11-27T11:00:00Z")
            with tracker_db.db() as c:
                c.execute("UPDATE tracker_limits SET daily_loads = 14")
            call("err_409_waitlist", "PUT", "/v1/watches/w_other_0003", body(account_id="acc-1003", username="example_three"))
            with tracker_db.db() as c:
                c.execute("UPDATE tracker_limits SET daily_loads = 300")
            with mock.patch.dict(os.environ, TRACKER_PUBLIC_PER_HOUR="0"):
                call("err_429", "PUT", "/v1/watches/w_other_0003", body(account_id="acc-1003", username="example_three"))
            call("err_410", "GET", "/v1/creators/w_rowanash_0002")
            call("err_422", "PUT", "/v1/watches/w_other_0003", body(account_id="acc-1003", username="m"))
            call("err_422_invalid_json", "PUT", "/v1/watches/w_other_0003", None)
        self.coverage_scenario(out)
        return out

    def coverage_scenario(self, out):
        """A second tenant (so the goldens above keep their rows): Coverage lanes and Google visibility as the lane
        writers leave them, full passes on slot days only."""
        key = self.tenant("tn_example0002", "Example Agency Two")

        def call(name, path):
            st, _, b = self.req("GET", path, None, key)
            out[name] = {"method": "GET", "path": path, "request": None, "status": st, "response": b}

        def put(wid, at, **over):
            self.clock = at
            self.assertEqual(self.req("PUT", f"/v1/watches/{wid}", body(**over), key)[0], 200)
            with tracker_db.db() as c:
                c.execute("UPDATE watches SET seeded_at = COALESCE(seeded_at, ?) WHERE watch_id = ?", (iso(at.date(), 9, 5), wid))
                return c.execute("SELECT * FROM watches WHERE watch_id = ?", (wid,)).fetchone()

        iso = lambda day, h=4, m=0: f"{day.isoformat()}T{h:02d}:{m:02d}:00Z"
        last_slot = lambda w: NOW.date() - timedelta(days=(NOW.weekday() - w["weekly_slot"]) % 7 or 7)
        at9 = lambda day: datetime(2026, 11, day, 9, 0, tzinfo=timezone.utc)
        rec, fresh, full = tracker_lanes._record, tracker_lanes.FRESH, tracker_lanes.FULL
        nov = lambda day: NOW.date().replace(day=day)

        w = put("w_miavale_0101", at9(20), account_id="acc-2001", instagram="mia.vale.official", x="itsmiavale")
        slot = last_slot(w)
        self.assertTrue(nov(21) < slot < nov(27), slot)
        plan = tracker_plan.build(w, w["platform"])
        tr = plan.trim(plan.loads - 6)
        self.assertEqual([x["field"] for x in tr.dropped], ["alias:0", "x", "instagram"])
        before = slot - timedelta(days=1)
        rec("w_miavale_0101", before.isoformat(), fresh, iso(before, 4, 3))
        rec("w_miavale_0101", slot.isoformat(), full, iso(slot, 4, 10), "reduced", "cap_tenant_month", next_on="2026-12-01",
            trimmed=tr.dropped, carry=json.dumps({"on": "2026-12-01", "reason": "cap_tenant_month", "first": True, "pages": [
                list(tracker_lanes._page_key(q)) for q in tracker_lanes._pages(tr.cut)]}))
        rec("w_miavale_0101", "2026-11-26", "mega_lookup", iso(nov(26), 4, 2))
        rec("w_miavale_0101", "2026-11-26", fresh, iso(nov(26), 4, 3), "waiting", "cap_tenant_month", next_on="2026-12-01")
        rec("w_miavale_0101", "2026-11-27", "origin_probe", iso(nov(27), 4, 1), ledger=False)
        rec("w_miavale_0101", "2026-11-27", "mega_lookup", iso(nov(27), 4, 2), "failed")
        rec("w_miavale_0101", "2026-11-27", "listing_recheck", iso(nov(27), 4, 2))
        rec("w_miavale_0101", "2026-11-27", fresh, iso(nov(27), 4, 3), "waiting", "cap_tenant_month", next_on="2026-12-01")

        rowan = dict(account_id="acc-2002", username="rowanash", display_name="Rowan Ash", aliases=[], instagram=None, x=None)
        put("w_rowanash_0102", at9(10), **rowan)
        for lane, m in (("origin_probe", 1), ("mega_lookup", 2), ("listing_recheck", 2)):
            rec("w_rowanash_0102", "2026-11-26", lane, iso(nov(26), 4, m), ledger=lane != "origin_probe")
        with tracker_db.db() as c:
            c.executemany("INSERT INTO daily_scans (watch_id, day, started_at, finished_at, outcome) VALUES (?,?,?,?,?)",
                          [("w_miavale_0101", "2026-11-26", iso(nov(26)), iso(nov(26), 4, 5), "partial"),
                           ("w_miavale_0101", "2026-11-27", iso(nov(27)), iso(nov(27), 4, 5), "partial"),
                           ("w_rowanash_0102", "2026-11-26", iso(nov(26)), iso(nov(26), 4, 5), "ok")])
        put("w_rowanash_0102", at9(26), paused=True, **rowan)

        vis = dict(account_id="acc-2003", platform="fansly", instagram=None, x=None)
        w = put("w_miavale_0103", at9(11), **vis)
        s = last_slot(w)
        passes = [s - timedelta(days=14), s - timedelta(days=7), s]
        self.assertTrue(nov(11) < passes[0] <= nov(18), passes)
        urls = {"true": "https://example-leaks.test/miavale-set-1", "false": "https://example-leaks.test/miavale-set-2",
                "null": "https://forum.example-leaks.test/t/mia.vale.x"}
        keys = {k: tracker_judge.leak_key(u) for k, u in urls.items()}
        handle, alias = ("web", "handle"), ("web", "alias:miavalex")

        def full_pass(w, day, returned):
            with tracker_db.db() as c:
                plan = tracker_plan.build(w, w["platform"])
                pairs = {tracker_lanes._pair(q, plan.values) for q in plan.queries}
                if day == passes[0]:
                    self.assertLessEqual({handle, alias}, pairs)
                    ids = iter(["lk_0201", "lk_0202", "lk_0203"])
                    with mock.patch.object(tracker_db, "new_id", lambda prefix: next(ids)):
                        self.assertEqual([tracker_judge.admit_hit(c, w, u, "set", "google_web", iso(day, 4, 10), first_scan=True)
                                          for u in urls.values()], ["leak"] * 3)
                tracker_lanes._visibility(c, w, plan, {keys[k]: v for k, v in returned.items()}, pairs, iso(day, 4, 10), True)
            rec(w["watch_id"], day.isoformat(), full, iso(day, 4, 10), next_on=(day + timedelta(days=7)).isoformat())

        def status(day, fr, to, dead=None):
            with tracker_db.db() as c:
                for k in keys:
                    lid = c.execute("SELECT leak_id FROM leaks WHERE url_key = ?", (keys[k],)).fetchone()[0]
                    tracker_db.add_event(c, lid, "status", {"from": fr, "to": to, "dead_since": dead}, iso(day, 4, 1))

        full_pass(w, passes[0], {"true": {handle}, "false": {handle}, "null": {alias}})
        status(passes[0] + timedelta(days=1), None, "live")
        full_pass(w, passes[1], {"null": {alias}})
        dead = passes[1] + timedelta(days=1)
        status(dead + timedelta(days=1), "live", "gone", iso(dead, 4, 1))
        w = put("w_miavale_0103", at9(passes[2].day - 1), aliases=[], **vis)
        full_pass(w, passes[2], {"true": {handle}})
        with tracker_db.db() as c:
            c.execute("INSERT INTO probe_state (leak_id, last_probe_at, last_live_at, consecutive_dead, last_status, origin_status, "
                      "probes) SELECT leak_id, ?, ?, ?, 'dead', 'gone', ? FROM leaks WHERE watch_id = 'w_miavale_0103'",
                      (iso(nov(27), 4, 1), iso(dead - timedelta(days=1), 4, 1), (nov(27) - dead).days + 1,
                       (nov(27) - passes[0]).days))
        self.clock = NOW
        call("creator_one_coverage", "/v1/creators/w_miavale_0101")
        call("creator_one_coverage_paused", "/v1/creators/w_rowanash_0102")
        call("creator_leaks_visibility", "/v1/creators/w_miavale_0103/leaks")

    def test_goldens(self):
        out = self.scenario()
        if os.environ.get("UPDATE_GOLDEN") == "1":
            os.makedirs(GOLDEN, exist_ok=True)
            for name in os.listdir(GOLDEN):
                os.remove(os.path.join(GOLDEN, name))
            for name, v in out.items():
                with open(os.path.join(GOLDEN, f"{name}.json"), "w", encoding="utf-8") as f:
                    f.write(json.dumps(v, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        self.assertEqual(sorted(os.listdir(GOLDEN)), sorted(f"{n}.json" for n in out))
        for name, v in out.items():
            with open(os.path.join(GOLDEN, f"{name}.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f), json.loads(json.dumps(v)), name)
        self.assertFalse(re.search(r"ltk_[A-Za-z0-9]{32,}", json.dumps(out).replace("0" * 40, "")))


if __name__ == "__main__":
    unittest.main()

"""Leak lanes (Phase 2 ticket 19): Phase 1's daily scheduler tick on a controlled UTC clock over a temp TRACKER_DB runs
run_daily (origin probe lane state, then the Mega lookup) against the Mega index wire stub (leakshaven_stub) and the
stub fetcher; every case reads the API's `lanes` over HTTP too. No real network. Fictional creators only."""
import http.client
import json
import os
import threading
from http.server import ThreadingHTTPServer
from unittest import mock

from tracker_fixture import Base, tdb, tracker_scheduler, tracker_stub_fetch
import db
import leakshaven
import leakshaven_stub as ls
import public_app
import tracker_purge

MODEL = "00000000-0000-4000-8000-0000000000a1"
TRAP = "00000000-0000-4000-8000-0000000000a2"
TITLE = "MiaVale"
REAL = {"title": TITLE, "modelId": MODEL, "matchedSearch": "mia_vale", "matchedSource": "instagram"}
NAME_ONLY = {"title": "Mia Vale", "modelId": TRAP, "matchedSearch": "mia vale", "matchedSource": "name"}
LANES = ["origin_probe", "mega_lookup", "listing_recheck", "google_fresh", "google_full", "registry_crawl"]


def pack(i, deleted=False):
    return {"id": f"mv-pack-{i}", "shortCode": f"mv{i:04d}", "title": f"{TITLE} set {i}", "modelId": MODEL,
            "deleted": deleted, "createdAt": "2026-11-01T10:00:00.000Z", "info": {}}


def url(i):
    return f"{leakshaven.SHARE}/mv{i:04d}"


def at(d):
    return f"2026-11-{d:02d}T05:00:00Z"


class Lanes(Base):
    @classmethod
    def setUpClass(cls):
        cls.mega = ls.Stub().start()
        cls.api = ThreadingHTTPServer(("127.0.0.1", 0), public_app.Handler)
        threading.Thread(target=cls.api.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.mega.shutdown()
        cls.api.shutdown()
        cls.api.server_close()

    def setUp(self):
        super().setUp()
        for p in (mock.patch.object(db, "DB_PATH", os.path.join(self.tmp.name, "public.db")),
                  mock.patch.multiple(leakshaven, BASE=self.mega.base, ENABLED=True, MIN_GAP=0.0)):
            p.start()
            self.addCleanup(p.stop)
        db.init_db()
        self.mega.mode, self.mega.calls, self.mega.suggest, self.mega.title = "ok", [], [REAL, NAME_ONLY], TITLE
        self.index()
        self.t = self.tenant("Agency A")
        self.key = self.issue(self.t)
        self.w = self.watch(self.t, username="mia_vale", aliases=("miavale_x", "miav"), display_name="Mia Vale")

    def issue(self, tenant_id):
        key = tdb.new_key()
        with tdb.db() as c:
            c.execute("INSERT INTO tenant_keys (key_hash, tenant_id, issued_at) VALUES (?,?,?)",
                      (tdb.key_hash(key), tenant_id, tdb.now()))
        return key

    def index(self, *packs):
        self.mega.content = {"content": list(packs), "count": len(packs), "richProfileId": MODEL,
                             "richProfileName": TITLE}

    def day(self, d, *packs):
        self.index(*packs)
        self.mega.calls = []
        tracker_scheduler.daily_pass(at(d))
        self.clock(at(d))

    def get(self, path, key=None):
        c = http.client.HTTPConnection("127.0.0.1", self.api.server_address[1], timeout=10)
        c.request("GET", path, headers={"Authorization": f"Bearer {key or self.key}"})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, json.loads(body) if body else None

    def lanes(self, wid=None):
        st, b = self.get(f"/v1/creators/{wid or self.w}")
        self.assertEqual(st, 200)
        self.assertEqual([x["lane"] for x in b["lanes"]], LANES)
        return {x["lane"]: x for x in b["lanes"]}

    def pills(self):
        b = self.get(f"/v1/creators/{self.w}/leaks")[1]
        return {x["url"]: x["pill"] for x in b["leaks"]}

    def mega_leak(self, i):
        r = self.rows("SELECT leak_id FROM leaks WHERE watch_id = ? AND url = ?", self.w, url(i))
        return r[0]["leak_id"] if r else None

    def dead(self, i):
        return (self.state(self.mega_leak(i)) or {}).get("consecutive_dead", 0)


class TestMegaLookup(Lanes):
    def test_deleted_once_twice_live_again_absent(self):
        self.day(2, pack(1), pack(2), pack(3, deleted=True))
        leaks = self.rows("SELECT url, kind, leak_site FROM leaks WHERE watch_id = ? ORDER BY url", self.w)
        self.assertEqual(leaks, [{"url": url(i), "kind": "mega", "leak_site": "leakshaven.com"} for i in (1, 2)])
        self.assertEqual(self.pills(), {url(1): "listed", url(2): "listed"})
        b = self.get(f"/v1/creators/{self.w}/leaks")[1]
        self.assertEqual({x["sources"][0] for x in b["leaks"]}, {"mega_index"})
        lanes = self.lanes()
        self.assertEqual({k: lanes["mega_lookup"][k] for k in ("cadence", "state", "reason", "last_success_at",
                                                                "last_attempt_at", "next_attempt_on", "trimmed")},
                         {"cadence": "daily", "state": "ok", "reason": None, "last_success_at": at(2),
                          "last_attempt_at": at(2), "next_attempt_on": "2026-11-03", "trimmed": []})
        self.assertEqual((lanes["origin_probe"]["state"], lanes["origin_probe"]["last_success_at"]), ("ok", at(2)))
        self.assertEqual({k: lanes[k]["state"] for k in LANES[2:]}, dict.fromkeys(LANES[2:], "never"))

        self.day(3, pack(1, deleted=True), pack(2, deleted=True))
        self.assertEqual(self.pills(), {url(1): "listed", url(2): "listed"})
        self.assertEqual((self.dead(1), self.dead(2)), (1, 1))
        self.assertEqual(self.events(self.mega_leak(1), "status"), [])

        self.day(4, pack(1, deleted=True), pack(2))
        self.assertEqual(self.pills(), {url(1): "gone", url(2): "listed"})
        self.assertEqual(self.events(self.mega_leak(1), "status"),
                         [{"at": at(4), "type": "status",
                           "data": {"from": "listed", "to": "gone", "dead_since": at(3), "source": "mega_index"}}])
        self.assertEqual((self.dead(2), self.events(self.mega_leak(2), "status")), (0, []))

        self.day(5, pack(2))
        self.assertEqual(self.pills(), {url(1): "gone", url(2): "listed"})
        self.assertEqual(self.dead(1), 2)
        self.assertEqual(len(self.events(self.mega_leak(1), "status")), 1)

        self.day(6, pack(1), pack(2, deleted=True))
        self.assertEqual(self.pills(), {url(1): "listed", url(2): "listed"})
        self.assertEqual(self.events(self.mega_leak(1), "status")[-1]["data"],
                         {"from": "gone", "to": "listed", "dead_since": None, "source": "mega_index"})
        self.assertEqual(self.dead(1), 0)

        self.day(7, pack(1))
        self.assertEqual((self.dead(2), self.pills()[url(2)]), (1, "listed"))

        self.assertEqual(self.rows("SELECT day, lane, outcome, reason FROM lane_day WHERE watch_id = ? ORDER BY day",
                                   self.w),
                         [{"day": f"2026-11-0{d}", "lane": "mega_lookup", "outcome": "ok", "reason": None}
                          for d in range(2, 8)])
        self.assertEqual(self.rows("SELECT * FROM load_reservation"), [])
        self.assertEqual(self.lanes()["mega_lookup"]["last_success_at"], at(7))

    def test_display_name_never_sent(self):
        with mock.patch.object(leakshaven, "start", wraps=leakshaven.start) as start:
            self.day(2, pack(1))
        start.assert_called_once_with("mia_vale", ["miavale_x"], (), source=True, deleted=True)
        self.assertEqual([p for p, _ in self.mega.calls], ["/content/suggest", "/content"])
        self.assertEqual(self.mega.calls[0][1]["term"], "mia_vale")
        sent = json.dumps(self.mega.calls).lower()
        self.assertNotIn("mia vale", sent)
        self.assertNotIn("miav\"", sent)
        self.assertEqual(list(self.pills()), [url(1)])

        self.mega.suggest = [NAME_ONLY]
        self.mega.title = "Mia Vale"
        self.day(3, pack(1), pack(2))
        self.assertEqual([p for p, _ in self.mega.calls], ["/content/suggest"])
        self.assertEqual(list(self.pills()), [url(1)])
        self.assertEqual(self.lanes()["mega_lookup"]["state"], "ok")

    def test_failed_lookup_keeps_last_success(self):
        self.day(2, pack(1))
        self.mega.mode = "404"
        self.day(3, pack(1, deleted=True))
        m = self.lanes()["mega_lookup"]
        self.assertEqual((m["state"], m["reason"], m["last_success_at"], m["last_attempt_at"], m["next_attempt_on"]),
                         ("failed", "lane_failed", at(2), at(3), "2026-11-04"))
        self.assertEqual(self.dead(1), 0)
        self.assertEqual(self.rows("SELECT outcome, reason FROM lane_day WHERE day = '2026-11-03'"),
                         [{"outcome": "failed", "reason": "lane_failed"}])
        self.assertEqual(self.rows("SELECT outcome FROM daily_scans WHERE day = '2026-11-03'"), [{"outcome": "ok"}])

    def test_one_lookup_per_day(self):
        self.day(2, pack(1, deleted=True))
        self.mega.calls = []
        tracker_scheduler.daily_pass(tdb.plus(at(2), hours=3))
        self.assertEqual(self.mega.calls, [])


class TestPaused(Lanes):
    def test_paused_runs_nothing_and_keeps_last_success(self):
        self.leak(self.w, "https://leaksite.example/models/mia_vale/")
        self.day(2, pack(1))
        before = self.rows("SELECT * FROM lane_state ORDER BY lane")
        with tdb.db() as c:
            c.execute("UPDATE watches SET paused = 1, paused_at = ? WHERE watch_id = ?", (at(2), self.w))
        tracker_stub_fetch.CALLS.clear()
        self.day(3, pack(1, deleted=True))
        self.assertEqual((self.mega.calls, tracker_stub_fetch.CALLS), ([], []))
        self.assertEqual(self.rows("SELECT * FROM lane_state ORDER BY lane"), before)
        self.assertEqual(self.rows("SELECT day FROM lane_day"), [{"day": "2026-11-02"}])
        lanes = self.lanes()
        self.assertEqual({k: v["state"] for k, v in lanes.items()}, dict.fromkeys(LANES, "paused"))
        self.assertEqual({k: v["last_success_at"] for k, v in lanes.items()},
                         {**dict.fromkeys(LANES), "origin_probe": at(2), "mega_lookup": at(2)})
        self.assertEqual({v["next_attempt_on"] for v in lanes.values()}, {None})


class TestPurge(Lanes):
    def test_purged_watch_leaves_no_lane_row(self):
        keep = self.watch(self.t, username="rowan_ash", account_id="acc-rowan")
        self.day(2, pack(1))
        with tdb.db() as c:
            c.execute("UPDATE watches SET deleted_at = ?, purge_after = ? WHERE watch_id = ?", (at(2), at(3), self.w))
        tracker_purge.run(tdb.plus(at(3), hours=1))
        for t in ("lane_state", "lane_day"):
            self.assertEqual(self.rows(f"SELECT * FROM {t} WHERE watch_id = ?", self.w), [], t)
        self.assertTrue(self.rows("SELECT * FROM lane_state WHERE watch_id = ?", keep))
        self.assertTrue(self.rows("SELECT * FROM lane_day WHERE watch_id = ?", keep))


if __name__ == "__main__":
    import unittest
    unittest.main()

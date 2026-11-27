"""Leak lanes (Phase 2 tickets 19, 25): Phase 1's daily scheduler tick on a controlled UTC clock over a temp TRACKER_DB
runs run_daily (origin probe lane state, the Mega lookup, the listing recheck) against the Mega index wire stub
(leakshaven_stub) and the stub fetcher (its table serves the fake listing pages) over a test detection map; every case
reads the API's `lanes` over HTTP too. No real network. Fictional creators only."""
import http.client
import json
import os
import threading
from http.server import ThreadingHTTPServer
from unittest import mock

from tracker_fixture import Base, tdb, tracker_scheduler, tracker_stub_fetch
import db
import leak_crawler
import leakshaven
import leakshaven_stub as ls
import public_app
import tracker_lanes
import tracker_probe
import tracker_purge

MODEL = "00000000-0000-4000-8000-0000000000a1"
TRAP = "00000000-0000-4000-8000-0000000000a2"
TITLE = "MiaVale"
REAL = {"title": TITLE, "modelId": MODEL, "matchedSearch": "mia_vale", "matchedSource": "instagram"}
NAME_ONLY = {"title": "Mia Vale", "modelId": TRAP, "matchedSearch": "mia vale", "matchedSource": "name"}
SITE = "https://leaksite.example"
MAP = {"leaksite.example": {"method": "profile", "check_url": SITE + "/models/{name}/"},
       "tube.example": {"method": "search", "check_url": "https://tube.example/search?q={name}",
                        "content_url": "https://tube.example/{name}/{idx}/", "idx_type": "seq"}}
LANES = ["origin_probe", "mega_lookup", "listing_recheck", "google_fresh", "google_full", "registry_crawl"]


def pack(i, deleted=False):
    return {"id": f"mv-pack-{i}", "shortCode": f"mv{i:04d}", "title": f"{TITLE} set {i}", "modelId": MODEL,
            "deleted": deleted, "createdAt": "2026-11-01T10:00:00.000Z", "info": {}}


def url(i):
    return f"{leakshaven.SHARE}/mv{i:04d}"


def at(d):
    return f"2026-11-{d:02d}T05:00:00Z"


def listing(i):
    return f"{SITE}/models/mia_vale-{i}/"


def page(*links):
    return [200, "<html><body>" + "".join(f'<a class="p" href="{h}"><span>{t}</span></a>' for h, t in links)
            + "</body></html>"]


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
        dmap = os.path.join(self.tmp.name, "map.json")
        with open(dmap, "w", encoding="utf-8") as fh:
            json.dump(MAP, fh)
        for p in (mock.patch.object(tracker_lanes, "MAP_FILE", dmap), mock.patch.object(tracker_lanes, "LISTING_GAP", 0.0)):
            p.start()
            self.addCleanup(p.stop)
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
        self.assertEqual(lanes["listing_recheck"]["state"], "ok")
        self.assertEqual({k: lanes[k]["state"] for k in LANES[3:]}, dict.fromkeys(LANES[3:], "never"))

        self.day(3, pack(1, deleted=True), pack(2, deleted=True))
        self.assertEqual(self.pills(), {url(1): "listed", url(2): "listed"})
        self.assertEqual((self.dead(1), self.dead(2)), (1, 1))
        self.assertEqual(self.events(self.mega_leak(1), "status"), [])

        self.day(4, pack(1, deleted=True), pack(2))
        self.assertEqual(self.pills(), {url(1): "gone", url(2): "listed"})
        self.assertEqual(self.events(self.mega_leak(1), "status"),
                         [{"at": at(4), "type": "status",
                           "data": {"from": None, "to": "gone", "dead_since": at(3), "source": "mega_index"}}])
        self.assertEqual(self.dead(2), 0)
        self.assertEqual([e["data"] for e in self.events(self.mega_leak(2), "status")],
                         [{"from": None, "to": "live", "dead_since": None, "source": "mega_index"}])

        self.day(5, pack(2))
        self.assertEqual(self.pills(), {url(1): "gone", url(2): "listed"})
        self.assertEqual(self.dead(1), 2)
        self.assertEqual(len(self.events(self.mega_leak(1), "status")), 1)

        self.day(6, pack(1), pack(2, deleted=True))
        self.assertEqual(self.pills(), {url(1): "listed", url(2): "listed"})
        self.assertEqual(self.events(self.mega_leak(1), "status")[-1]["data"],
                         {"from": "gone", "to": "live", "dead_since": None, "source": "mega_index"})
        self.assertEqual(self.dead(1), 0)

        self.day(7, pack(1))
        self.assertEqual((self.dead(2), self.pills()[url(2)]), (1, "listed"))

        self.assertEqual(self.rows("SELECT day, lane, outcome, reason FROM lane_day WHERE watch_id = ? AND "
                                   "lane = 'mega_lookup' ORDER BY day", self.w),
                         [{"day": f"2026-11-0{d}", "lane": "mega_lookup", "outcome": "ok", "reason": None}
                          for d in range(2, 8)])
        self.assertEqual(self.rows("SELECT * FROM load_reservation"), [])
        self.assertEqual(self.rows("SELECT data_json FROM leak_events WHERE type = 'status' AND (data_json LIKE '%listed%' "
                                   "OR data_json NOT LIKE '%\"source\":\"mega_index\"%')"), [])
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
        self.assertEqual(self.rows("SELECT outcome, reason FROM lane_day WHERE day = '2026-11-03' AND lane = 'mega_lookup'"),
                         [{"outcome": "failed", "reason": "lane_failed"}])
        self.assertEqual(self.rows("SELECT outcome FROM daily_scans WHERE day = '2026-11-03'"), [{"outcome": "ok"}])

    def test_one_lookup_per_day(self):
        self.day(2, pack(1))
        self.day(3, pack(1, deleted=True))
        with tdb.db() as c:
            c.execute("UPDATE daily_scans SET finished_at = NULL, outcome = NULL WHERE day = '2026-11-03'")
        self.mega.calls = []
        self.assertEqual(tracker_scheduler.daily_pass(tdb.plus(at(3), hours=3))["probed"], 1)
        self.assertEqual(self.mega.calls, [])
        self.assertEqual(self.dead(1), 1)
        self.assertEqual(self.rows("SELECT outcome FROM daily_scans WHERE day = '2026-11-03'"), [{"outcome": "ok"}])


class TestListingRecheck(Lanes):
    def test_creator_listing_from_the_detection_map(self):
        names = ["miavale", "miavalex"]
        for u in (f"{SITE}/models/mia_vale/", f"{SITE}/models/Mia.Vale", f"https://www.leaksite.example/models/miavale_x-2/?page=1",
                  "https://tube.example/search?q=mia_vale", "https://tube.example/mia_vale/", "https://tube.example/mia_vale"):
            self.assertTrue(tracker_lanes.is_listing(u, names), u)
        for u in (f"{SITE}/models/rowan_ash/", f"{SITE}/video/mia_vale-1", f"{SITE}/models/mia_vale/12/", f"{SITE}/",
                  "https://tube.example/mia_vale/3/", "https://tube.example/search?q=rowan_ash",
                  "https://tube.example/search", "https://other.example/models/mia_vale/"):
            self.assertFalse(tracker_lanes.is_listing(u, names), u)
        with mock.patch.object(tracker_lanes, "MAP_FILE", public_app.MAP_FILE):
            self.assertTrue(tracker_lanes.is_listing("https://nudostar.tv/models/mia_vale/", names))
            self.assertTrue(tracker_lanes.is_listing("https://picazor.com/mia_vale/", names))
            self.assertFalse(tracker_lanes.is_listing("https://nudostar.tv/models/rowan_ash/", names))

    def test_21_listings_20_fetched_oldest_first_and_reduced(self):
        ids = [self.leak(self.w, listing(i)) for i in range(21)]
        self.leak(self.w, f"{SITE}/video/mia_vale-clip-1")
        with tdb.db() as c:
            c.executemany("UPDATE leaks SET recheck_at = ? WHERE leak_id = ?",
                          [(f"2026-10-{30 - i:02d}T00:00:00Z", lid) for i, lid in enumerate(ids)])
            c.execute("UPDATE tracker_limits SET daily_loads = 0, daily_judge = 0")
            c.execute("UPDATE tenants SET month_loads = 0")
        with mock.patch.object(leak_crawler, "_throttle", wraps=leak_crawler._throttle) as throttle:
            self.day(2)
        calls = tracker_stub_fetch.CALLS
        self.assertEqual((len(calls), calls[-20:]), (22 + 20, [listing(i) for i in range(20, 0, -1)]))
        self.assertEqual(throttle.call_args_list, [mock.call("leaksite.example", 0.0)] * 20)
        lane = self.lanes()["listing_recheck"]
        self.assertEqual({k: lane[k] for k in ("state", "reason", "last_success_at", "last_attempt_at", "next_attempt_on")},
                         {"state": "reduced", "reason": "listing_rotated", "last_success_at": at(2),
                          "last_attempt_at": at(2), "next_attempt_on": "2026-11-03"})
        self.assertEqual(self.rows("SELECT outcome, reason FROM lane_day WHERE lane = 'listing_recheck'"),
                         [{"outcome": "partial", "reason": "listing_rotated"}])
        self.assertEqual(self.rows("SELECT * FROM load_reservation"), [])
        self.assertEqual([r["recheck_at"] for r in self.rows("SELECT recheck_at FROM leaks WHERE url LIKE '%/models/%' "
                                                             "ORDER BY rowid")], ["2026-10-30T00:00:00Z"] + [at(2)] * 20)

        tracker_stub_fetch.CALLS.clear()
        self.day(3)
        self.assertEqual(tracker_stub_fetch.CALLS[-20:], [listing(i) for i in range(20)])
        self.assertEqual(self.lanes()["listing_recheck"]["state"], "reduced")
        self.assertEqual(self.rows("SELECT * FROM load_reservation"), [])

    def test_recheck_admits_site_search_leaks_new_today_and_hides_title_only_hits(self):
        home = f"{SITE}/models/mia_vale/"
        self.leak(self.w, home)
        posts = [("/video/mia_vale-beach-101", "Beach set"), ("/video/miavale_x-102", "Pool"),
                 ("/video/miav-103", "Mia_Vale gym"), ("/video/miav-104", "gym"), ("/video/105", "new mia_vale shower"),
                 ("/video/106", "Mia Vale"), ("https://onlyfans.com/mia_vale", "mia_vale"),
                 ("https://other.example/mia_vale-1", "mia_vale"), ("?page=2", "2"), (home, "mia_vale"),
                 ("/tags/mia-vale/", "mia_vale"), ("/img/mia_vale-1.jpg", "mia_vale")]
        self.answers({home: page(*posts)})
        self.day(2)
        b = self.get(f"/v1/creators/{self.w}/leaks")[1]
        found = {x["url"]: x for x in b["leaks"] if x["url"] != home}
        self.assertEqual(sorted(found), [f"{SITE}/video/mia_vale-beach-101", f"{SITE}/video/miav-103",
                                         f"{SITE}/video/miavale_x-102"])
        self.assertEqual({(x["sources"][0], x["kind"], x["leak_site"], x["found_on_first_scan"]) for x in found.values()},
                         {("site_search", "page", "leaksite.example", True)})
        self.assertEqual(found[f"{SITE}/video/miav-103"]["title"], "Mia_Vale gym")
        counts = self.get(f"/v1/creators/{self.w}")[1]["counts"]
        self.assertEqual((counts["new_today"], counts["found_on_first_scan"]), (0, 4))
        self.assertEqual(self.rows("SELECT url, title, source FROM pending_hits"),
                         [{"url": f"{SITE}/video/105", "title": "new mia_vale shower", "source": "site_search"}])

        self.answers({home: page(*posts, ("/video/mia_vale-pool-107", "Pool 2"))})
        self.day(3)
        b = self.get(f"/v1/creators/{self.w}/leaks")[1]
        new = [x for x in b["leaks"] if x["url"] == f"{SITE}/video/mia_vale-pool-107"]
        self.assertEqual([(x["sources"], x["found_on_first_scan"], x["first_seen_at"][:10]) for x in new],
                         [(["site_search"], False, "2026-11-03")])
        self.assertEqual(self.get("/v1/creators")[1]["creators"][0]["counts"]["new_today"], 1)
        self.assertEqual(self.lanes()["listing_recheck"]["state"], "ok")
        every = json.dumps([b, self.get(f"/v1/leaks?watch_id={self.w}")[1], self.get(f"/v1/creators/{self.w}")[1]])
        self.assertNotIn("/video/105", every)
        self.assertNotIn("shower", every)
        self.assertEqual(len(self.rows("SELECT * FROM pending_hits")), 1)
        self.assertEqual(self.rows("SELECT * FROM load_reservation"), [])

    def test_listing_fetch_uses_the_probe_bounds_and_destination_rule(self):
        self.leak(self.w, f"{SITE}/models/mia_vale/")
        with mock.patch.object(tracker_probe, "fetcher", wraps=tracker_probe.fetcher) as fetcher:
            self.day(2)
        self.assertEqual(fetcher.call_args_list, [mock.call(), mock.call(max_body=2 * 1024 * 1024)])
        tracker_probe.set_fetcher(None)
        with mock.patch.dict(os.environ, {"TRACKER_FETCHER": ""}):
            f = tracker_probe.fetcher(max_body=tracker_lanes.LISTING_BODY)
        self.assertEqual((f.total, f.max_redirects, f.max_body, f.allow), (15.0, 5, 2 * 1024 * 1024, tracker_probe.ip_ok))

    def test_unanswered_listings_fail_the_lane(self):
        self.leak(self.w, f"{SITE}/models/mia_vale/")
        self.answers({"*": 0})
        self.day(2)
        lane = self.lanes()["listing_recheck"]
        self.assertEqual((lane["state"], lane["reason"], lane["last_success_at"]), ("failed", "lane_failed", None))


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
        self.assertEqual(self.rows("SELECT DISTINCT day FROM lane_day"), [{"day": "2026-11-02"}])
        lanes = self.lanes()
        self.assertEqual({k: v["state"] for k, v in lanes.items()}, dict.fromkeys(LANES, "paused"))
        self.assertEqual({k: v["last_success_at"] for k, v in lanes.items()},
                         {**dict.fromkeys(LANES), "origin_probe": at(2), "mega_lookup": at(2), "listing_recheck": at(2)})
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

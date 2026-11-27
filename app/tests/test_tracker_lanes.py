"""Leak lanes (Phase 2 tickets 19, 25, 26): Phase 1's daily scheduler tick on a controlled UTC clock over a temp
TRACKER_DB runs run_daily (origin probe lane state, the Mega lookup, the listing recheck) against the Mega index wire
stub (leakshaven_stub) and the stub fetcher (its table serves the fake listing pages) over a test detection map, then
run_fresh_batch (the Google fresh pass) against a local Browserbase REST stub and a fake Playwright that records every
navigation; every case reads the API's `lanes` over HTTP too. No real network, no paid call. Fictional creators only."""
import contextlib
import http.client
import io
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from tracker_fixture import Base, tdb, tracker_scheduler, tracker_stub_fetch
import bb_client
import db
import leak_crawler
import leakshaven
import leakshaven_stub as ls
import public_app
import cse_scanner
import tracker_cli
import tracker_lanes
import tracker_plan
import tracker_probe
import tracker_purge
import tracker_serp

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

    def watch(self, tenant_id, username="mia_vale", aliases=(), **kw):
        """Slotted on Sunday unless a test says otherwise, so the weekly lanes stay out of the daily-lane cases."""
        kw.setdefault("weekly_slot", 6)
        kw.setdefault("plan_loads", tracker_plan.build({"username": username, "aliases_json": json.dumps(list(aliases)),
                                                        "instagram": kw.get("instagram"), "x": kw.get("x")},
                                                       "onlyfans").loads)
        return super().watch(tenant_id, username, aliases, **kw)

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
        self.assertEqual(self.rows("SELECT outcome FROM daily_scans WHERE day = '2026-11-03'"), [{"outcome": "partial"}])

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


class TestToday(Lanes):
    def today(self, wid=None):
        one = self.get(f"/v1/creators/{wid or self.w}")[1]["today"]
        self.assertEqual([x["today"] for x in self.get("/v1/creators")[1]["creators"] if x["watch_id"] == (wid or self.w)], [one])
        return one

    def test_first_run_finds_stay_out_of_new(self):
        self.day(2, pack(1), pack(2))
        self.assertEqual(self.today(), {"day": "2026-11-02", "state": "complete", "new": 0, "first_scan": 2, "came_back": 0,
                                        "gone": 0})
        self.day(3, pack(1), pack(2), pack(3))
        self.assertEqual(self.today(), {"day": "2026-11-03", "state": "complete", "new": 1, "first_scan": 0, "came_back": 0,
                                        "gone": 0})
        self.day(4, pack(1, deleted=True), pack(2), pack(3))
        self.day(5, pack(1, deleted=True), pack(2), pack(3))
        self.assertEqual(self.pills()[url(1)], "gone")
        self.assertEqual(self.today(), {"day": "2026-11-05", "state": "complete", "new": 0, "first_scan": 0, "came_back": 0,
                                        "gone": 1})
        self.day(6, pack(1), pack(2), pack(3))
        t = self.today()
        self.assertEqual((t["gone"], t["came_back"]), (0, 1))

    def test_zero_leaks_failed_lane_reads_partial(self):
        self.mega.mode = "404"
        self.day(2)
        self.assertEqual(self.rows("SELECT * FROM leaks"), [])
        self.assertEqual(self.rows("SELECT lane, outcome, reason FROM lane_day WHERE watch_id = ? ORDER BY lane", self.w),
                         [{"lane": "listing_recheck", "outcome": "ok", "reason": None},
                          {"lane": "mega_lookup", "outcome": "failed", "reason": "lane_failed"}])
        self.assertEqual(self.today(), {"day": "2026-11-02", "state": "partial", "new": 0, "first_scan": 0, "came_back": 0,
                                        "gone": 0})


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
            c.executemany("UPDATE leaks SET created_at = ? WHERE leak_id = ?",
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
                                                             "ORDER BY rowid")], [None] + [at(2)] * 20)

        tracker_stub_fetch.CALLS.clear()
        self.answers({listing(0): page(("/video/mia_vale-201", "a")), listing(20): page(("/video/mia_vale-202", "b"))})
        self.day(3)
        self.assertEqual(tracker_stub_fetch.CALLS[-20:], [listing(0)] + [listing(i) for i in range(20, 1, -1)])
        self.assertEqual(self.lanes()["listing_recheck"]["state"], "reduced")
        self.assertEqual(self.rows("SELECT * FROM load_reservation"), [])
        found = {x["url"]: x["found_on_first_scan"] for x in self.get(f"/v1/creators/{self.w}/leaks")[1]["leaks"]
                 if x["sources"] == ["site_search"]}
        self.assertEqual(found, {f"{SITE}/video/mia_vale-201": True, f"{SITE}/video/mia_vale-202": False})
        self.assertEqual(self.get(f"/v1/creators/{self.w}")[1]["counts"]["new_today"], 1)

    def test_listing_added_after_the_first_run_finds_first_scan_posts(self):
        old, new = listing(1), listing(2)
        self.leak(self.w, old)
        self.day(2)
        self.assertEqual(self.lanes()["listing_recheck"]["last_success_at"], at(2))
        self.leak(self.w, new)
        self.answers({old: page(("/video/mia_vale-301", "a")), new: page(("/video/mia_vale-302", "b"))})
        self.day(3)
        found = {x["url"]: x["found_on_first_scan"] for x in self.get(f"/v1/creators/{self.w}/leaks")[1]["leaks"]
                 if x["sources"] == ["site_search"]}
        self.assertEqual(found, {f"{SITE}/video/mia_vale-301": False, f"{SITE}/video/mia_vale-302": True})
        self.assertEqual(self.get(f"/v1/creators/{self.w}")[1]["counts"]["new_today"], 1)

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


HOST_KEY, HOST_PROJECT, OWN_KEY = "bb-host-key-fake", "prj-host", "bb-own-key-fake"
RESULTS = '<html><body><div id="search"><div id="rso">{}</div></div></body></html>'
EMPTY = '<html><body><div id="search">Your search did not match any documents.</div></body></html>'
WALL = '<html><body><form id="captcha-form"></form></body></html>'
SHELL = '<html><body><div id="search"><div id="center_col"></div></div></body></html>'
CREATE = {"projectId": HOST_PROJECT, "timeout": 300, "browserSettings": {"solveCaptchas": True}}


class BBStub(ThreadingHTTPServer):
    """Browserbase REST on loopback: POST /sessions -> {id, connectUrl}; POST /sessions/<id> = a release."""

    def __init__(self):
        self.creates, self.releases, self.lock, self.fail = [], [], threading.Lock(), False
        stub = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if stub.fail and self.path == "/sessions":
                    stub.creates.append((self.headers["X-BB-API-Key"], body))
                    self.send_error(500)
                    return
                with stub.lock:
                    if self.path == "/sessions":
                        stub.creates.append((self.headers["X-BB-API-Key"], body))
                        n = len(stub.creates)
                        out = {"id": f"bb{n}", "connectUrl": f"wss://bb.stub/{n}"}
                    else:
                        stub.releases.append((self.headers["X-BB-API-Key"], self.path, body))
                        out = {}
                b = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def log_message(self, *a):
                pass

        super().__init__(("127.0.0.1", 0), H)
        threading.Thread(target=self.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server_address[1]}"


class FakePW:
    """Started sync Playwright stand-in: chromium.connect_over_cdp -> a browser whose pages record every goto as
    (connectUrl, url) in navs and the page's route handler in blocks. script: per-navigation overrides ("wall",
    "fail", "shell" = a bare #search), else a results page with links[(vertical, q)], or links[q] on web (no links: the empty-result page).
    page_fail: new_page raises."""

    def __init__(self):
        self.navs, self.routes, self.script, self.links, self.closed, self.page_fail = [], [], [], {}, [], False
        self.blocks = []
        self.chromium = self

    def connect_over_cdp(self, url, **kw):
        pw = self

        class Page:
            url = "about:blank"

            def route(self, pattern, handler):
                pw.routes.append((pattern, handler))
                self.handler = handler

            def goto(self, u, **kw):
                pw.navs.append((url, u))
                pw.blocks.append(self.handler)
                step = pw.script.pop(0) if pw.script else None
                if step == "fail":
                    raise RuntimeError("net::ERR_TIMED_OUT")
                if step == "wall":
                    self.url, self.html = "https://www.google.com/sorry/index?continue=x", WALL
                    return
                if step == "shell":
                    self.url, self.html = u, SHELL
                    return
                qs = parse_qs(urlsplit(u).query)
                v = {"isch": "images", "vid": "videos"}.get(qs.get("tbm", [""])[0], "web")
                links = pw.links.get((v, qs["q"][0]), pw.links.get(qs["q"][0], []) if v == "web" else [])
                self.url = u
                self.html = RESULTS.format("".join(f'<div><a href="{h}"><h3>{t}</h3></a></div>' for h, t in links)) \
                    if links else EMPTY

            def content(self):
                return self.html

            def evaluate(self, js, arg):
                return True

            def wait_for_timeout(self, ms):
                pass

            def close(self):
                pass

        class Ctx:
            def new_page(self):
                if pw.page_fail:
                    raise RuntimeError("Target closed")
                return Page()

        class Browser:
            contexts = [Ctx()]

            def close(self):
                pw.closed.append(url)

        return Browser()

    def stop(self):
        pass

    def sessions(self):
        return list(dict.fromkeys(c for c, _ in self.navs))


class Fresh(Lanes):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bb = BBStub()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.bb.shutdown()
        cls.bb.server_close()

    def setUp(self):
        super().setUp()
        self.bb.creates.clear()
        self.bb.releases.clear()
        self.pw = FakePW()
        self.bb.fail = False
        for p in (mock.patch.object(bb_client, "BB_API", self.bb.base),
                  mock.patch.object(tracker_serp, "_playwright", lambda: self.pw),
                  mock.patch.dict(os.environ, TRACKER_PAID_TENANTS=self.t, TRACKER_UNCAPPED_TENANTS=self.t,
                                  BROWSERBASE_API_KEY=HOST_KEY, BROWSERBASE_PROJECT_ID=HOST_PROJECT)):
            p.start()
            self.addCleanup(p.stop)

    def q(self, wid=None):
        with tdb.db() as c:
            return tracker_plan.fresh(c.execute("SELECT * FROM watches WHERE watch_id = ?", (wid or self.w,)).fetchone())

    def used(self, wid=None):
        sql = "SELECT COALESCE(SUM(used), 0) AS n FROM load_reservation WHERE unit = 'load'"
        return self.rows(sql + " AND watch_id = ?", wid)[0]["n"] if wid else self.rows(sql)[0]["n"]

    def assert_charged(self):
        self.assertEqual(len(self.pw.navs), self.used())
        self.assertEqual(self.rows("SELECT * FROM load_reservation WHERE state != 'settled'"), [])
        for _, body in self.bb.creates:
            self.assertNotIn("proxies", body)
        self.assertEqual({urlsplit(u).netloc for _, u in self.pw.navs} - {"www.google.com"}, set())

    def fresh(self, wid=None):
        return self.lanes(wid)["google_fresh"]

    def lane_day(self, wid=None):
        return self.rows("SELECT outcome, reason FROM lane_day WHERE lane = 'google_fresh' AND watch_id = ?",
                         wid or self.w)

    def scan(self, wid=None, d=2):
        return self.rows("SELECT outcome FROM daily_scans WHERE watch_id = ? AND day = ?", wid or self.w,
                         f"2026-11-{d:02d}")[0]["outcome"]


REAL_LOAD = tracker_serp.Session.load


class TestFreshPass(Fresh):
    def test_session_settings_blocking_and_admission(self):
        q = self.q()
        self.assertEqual((q.text, q.since, q.vertical, q.pages), ('"mia_vale" OR "miavale_x"', "d", "web", 1))
        self.pw.links[q.text] = [(f"{SITE}/video/mia_vale-g1", "Mia set"), ("https://other.example/x", "Mia_Vale pics"),
                                 ("https://www.google.com/goto?url=x", "mia_vale")]
        self.day(2)
        self.assertEqual(self.bb.creates, [(HOST_KEY, CREATE)])
        self.assertEqual(self.pw.navs, [("wss://bb.stub/1", q.urls()[0])])
        self.assertIn("tbs=qdr%3Ad", q.urls()[0])
        self.assertEqual([(p, h.func, h.keywords) for p, h in self.pw.routes],
                         [("**/*", tracker_serp.block_assets, {"types": tracker_serp.BLOCKED_TYPES})])
        self.assertEqual(self.bb.releases, [(HOST_KEY, "/sessions/bb1", {"projectId": HOST_PROJECT, "status": "REQUEST_RELEASE"})])
        self.assertEqual(self.pw.closed, ["wss://bb.stub/1"])
        self.assert_charged()
        self.assertEqual(self.used(), 1)
        b = self.get(f"/v1/creators/{self.w}/leaks")[1]
        self.assertEqual([(x["url"], x["sources"], x["found_on_first_scan"]) for x in b["leaks"]],
                         [(f"{SITE}/video/mia_vale-g1", ["google_web"], True)])
        self.assertEqual(self.rows("SELECT url, source FROM pending_hits"),
                         [{"url": "https://other.example/x", "source": "google_web"}])
        lane = self.fresh()
        self.assertEqual({k: lane[k] for k in ("cadence", "state", "reason", "last_success_at", "next_attempt_on")},
                         {"cadence": "daily", "state": "ok", "reason": None, "last_success_at": at(2),
                          "next_attempt_on": "2026-11-03"})
        self.assertEqual(self.rows("SELECT outcome, reason FROM lane_day WHERE lane = 'google_fresh'"),
                         [{"outcome": "ok", "reason": None}])
        self.assertEqual(self.scan(), "ok")
        self.assertEqual(self.get(f"/v1/creators/{self.w}")[1]["last_checked_at"], at(2))

    def test_route_blocker_aborts_image_font_media(self):
        class Route:
            def __init__(self, t):
                self.request, self.done = mock.Mock(resource_type=t), None

            def abort(self):
                self.done = "abort"

            def continue_(self):
                self.done = "continue"

        got = {}
        for t in ("image", "font", "media", "stylesheet", "document", "script", "xhr", "fetch"):
            r = Route(t)
            tracker_serp.block_assets(r)
            got[t] = r.done
        self.assertEqual(got, {"image": "abort", "font": "abort", "media": "abort", "stylesheet": "abort",
                               "document": "continue", "script": "continue", "xhr": "continue", "fetch": "continue"})

    def test_wall_then_success_two_loads(self):
        q = self.q()
        self.pw.links[q.text] = [(f"{SITE}/video/mia_vale-g2", "Mia")]
        self.pw.script = ["wall"]
        self.day(2)
        self.assertEqual(self.pw.navs, [("wss://bb.stub/1", q.urls()[0]), ("wss://bb.stub/2", q.urls()[0])])
        self.assertEqual([k for k, _ in self.bb.creates], [HOST_KEY, HOST_KEY])
        self.assertEqual([p for _, p, _ in self.bb.releases], ["/sessions/bb1", "/sessions/bb2"])
        self.assert_charged()
        self.assertEqual(self.used(), 2)
        self.assertEqual(self.fresh()["state"], "ok")
        self.assertEqual(len(self.get(f"/v1/creators/{self.w}/leaks")[1]["leaks"]), 1)

    def test_wall_with_hold_used_up_incomplete_one_navigation(self):
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 1")
        self.pw.script = ["wall"]
        self.day(2)
        self.assertEqual(len(self.pw.navs), 1)
        self.assertEqual(len(self.bb.creates), 1)
        self.assert_charged()
        self.assertEqual(self.rows("SELECT held, used FROM load_reservation"), [{"held": 1, "used": 1}])
        lane = self.fresh()
        self.assertEqual((lane["state"], lane["reason"], lane["last_success_at"], lane["last_attempt_at"]),
                         ("reduced", "google_failed", None, at(2)))
        self.assertEqual(self.rows("SELECT outcome, reason FROM lane_day WHERE lane = 'google_fresh'"),
                         [{"outcome": "partial", "reason": "google_failed"}])
        self.assertEqual(self.scan(), "partial")
        self.assertEqual(self.rows("SELECT * FROM serp_cache"), [])

    def test_two_walls_end_the_query_incomplete(self):
        self.pw.script = ["wall", "wall"]
        self.day(2)
        self.assertEqual(len(self.pw.navs), 2)
        self.assertEqual(len(self.pw.sessions()), 2)
        self.assert_charged()
        self.assertEqual((self.fresh()["state"], self.fresh()["reason"]), ("reduced", "google_failed"))
        self.assertEqual(self.scan(), "partial")
        self.assertEqual(self.lane_day(), [{"outcome": "partial", "reason": "google_failed"}])

    def test_failed_load_coverage_reduced_no_other_engine(self):
        self.leak(self.w, f"{SITE}/models/mia_vale/")
        self.pw.script = ["fail"]
        with mock.patch.object(cse_scanner, "_call", side_effect=AssertionError("CSE called")) as cse:
            self.day(2)
        cse.assert_not_called()
        self.assertEqual(len(self.pw.navs), 1)
        self.assert_charged()
        self.assertEqual(len(self.bb.creates), 1)
        self.assertTrue(all(not re.search(r"google|bing|duckduckgo|serper", u) for u in tracker_stub_fetch.CALLS))
        lane = self.fresh()
        self.assertEqual((lane["state"], lane["reason"]), ("reduced", "google_failed"))
        self.assertEqual(self.rows("SELECT outcome, reason FROM lane_day WHERE lane = 'google_fresh'"),
                         [{"outcome": "partial", "reason": "google_failed"}])
        self.assertEqual(self.scan(), "partial")
        self.assertEqual(self.lanes()["listing_recheck"]["state"], "ok")
        self.assertEqual(self.get(f"/v1/creators/{self.w}")[1]["today"]["state"], "coverage_reduced")

    def test_zero_leaks_under_a_cap_reads_partial(self):
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 0")
        self.day(2)
        self.assert_charged()
        self.assertEqual(self.pw.navs, [])
        self.assertEqual(self.rows("SELECT * FROM leaks"), [])
        self.assertEqual(self.rows("SELECT lane, outcome, reason FROM lane_day WHERE watch_id = ? ORDER BY lane", self.w),
                         [{"lane": "google_fresh", "outcome": "partial", "reason": "cap_global"},
                          {"lane": "listing_recheck", "outcome": "ok", "reason": None},
                          {"lane": "mega_lookup", "outcome": "ok", "reason": None}])
        self.assertEqual(self.get("/v1/creators")[1]["creators"][0]["today"],
                         {"day": "2026-11-02", "state": "partial", "new": 0, "first_scan": 0, "came_back": 0, "gone": 0})

    def test_two_tenants_same_handle_one_request_charged_to_first(self):
        self.clock(tdb.plus(Base.T0, seconds=1))
        t2 = self.tenant("Agency B")
        key2 = self.issue(t2)
        w2 = self.watch(t2, username="mia_vale", aliases=("miavale_x", "miav"), account_id="acc-b")
        with tdb.db() as c:
            c.execute("UPDATE tenants SET bb_key = ?, bb_project = 'prj-b' WHERE tenant_id = ?", (OWN_KEY, t2))
        self.assertEqual(self.q(w2), self.q())
        hit = f"{SITE}/video/mia_vale-g3"
        self.pw.links[self.q().text] = [(hit, "Mia")]
        with mock.patch.dict(os.environ, TRACKER_PAID_TENANTS=f"{self.t},{t2}"):
            self.day(2)
            self.assertEqual(self.pw.navs, [("wss://bb.stub/1", self.q().urls()[0])])
            self.assertEqual([k for k, _ in self.bb.creates], [HOST_KEY])
            self.assert_charged()
            self.assertEqual((self.used(self.w), self.used(w2)), (1, 0))
            self.assertEqual(self.rows("SELECT watch_id FROM load_reservation"), [{"watch_id": self.w}])
            self.assertEqual(len(self.rows("SELECT * FROM serp_cache")), 1)
            for wid, key in ((self.w, self.key), (w2, key2)):
                b = self.get(f"/v1/creators/{wid}/leaks", key)[1]
                self.assertEqual([(x["url"], x["sources"]) for x in b["leaks"]], [(hit, ["google_web"])])
                st, one = self.get(f"/v1/creators/{wid}", key)
                self.assertEqual({x["lane"]: x["state"] for x in one["lanes"]}["google_fresh"], "ok")
            self.assertEqual(len(self.rows("SELECT leak_id FROM leaks WHERE url = ?", hit)), 2)

            self.day(3)
            self.assertEqual(len(self.pw.navs), 2)
            self.assertEqual(self.rows("SELECT DISTINCT day FROM serp_cache"), [{"day": "2026-11-03"}])
            self.assert_charged()
            self.assertEqual((self.used(self.w), self.used(w2)), (2, 0))

    def test_12_packed_into_one_session_13_into_two(self):
        with tdb.db() as c:
            c.execute("UPDATE tenants SET creators_max = 20")
        self.watch(self.t, username="rowan_ash", account_id="acc-0")
        names = [f"rowan_ash{i}" for i in range(1, 11)]
        for i, n in enumerate(names):
            self.watch(self.t, username=n, account_id=f"acc-{i + 1}")
        self.day(2)
        self.assertEqual(len(self.pw.navs), 12)
        self.assertEqual(len(self.pw.sessions()), 1)
        self.assertEqual(len(self.bb.creates), 1)
        self.assert_charged()
        self.watch(self.t, username="rowan_ash99", account_id="acc-99")
        self.day(3)
        self.assertEqual(len(self.pw.navs), 25)
        self.assertEqual([sum(1 for c, _ in self.pw.navs if c == s) for s in self.pw.sessions()], [12, 12, 1])
        self.assertEqual(len(self.bb.creates), 3)
        self.assert_charged()

    def test_over_the_cap_fresh_waits_while_zero_cost_lanes_run(self):
        self.leak(self.w, f"{SITE}/models/mia_vale/")
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 0")
        self.day(2, pack(1))
        self.assertEqual((self.pw.navs, self.bb.creates), ([], []))
        self.assertEqual(self.rows("SELECT * FROM load_reservation"), [])
        self.assertTrue(self.mega.calls)
        self.assertIn(f"{SITE}/models/mia_vale/", tracker_stub_fetch.CALLS)
        lanes = self.lanes()
        self.assertEqual({k: lanes[k]["state"] for k in ("mega_lookup", "listing_recheck")},
                         {"mega_lookup": "ok", "listing_recheck": "ok"})
        f = lanes["google_fresh"]
        self.assertEqual((f["state"], f["reason"], f["next_attempt_on"], f["last_success_at"]),
                         ("waiting", "cap_global", "2026-11-03", None))
        self.assertEqual(self.rows("SELECT outcome, reason FROM lane_day WHERE lane = 'google_fresh'"),
                         [{"outcome": "partial", "reason": "cap_global"}])
        self.assertEqual(self.rows("SELECT paused FROM watches WHERE watch_id = ?", self.w), [{"paused": 0}])
        self.assertEqual(self.scan(), "partial")
        self.assertFalse(self.get(f"/v1/creators/{self.w}")[1]["paused"])

        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 300")
            c.execute("UPDATE tenants SET month_loads = 0")
        self.day(3)
        f = self.fresh()
        self.assertEqual((f["state"], f["reason"], f["next_attempt_on"]), ("waiting", "cap_tenant_month", "2026-12-01"))
        self.assertEqual(self.pw.navs, [])

    def test_gate_no_allowlist_zero_navigations(self):
        for env in ({"TRACKER_PAID_TENANTS": ""}, {"TRACKER_PAID_TENANTS": "tn_someone_else"}):
            with mock.patch.dict(os.environ, env):
                self.day(2)
        os.environ.pop("TRACKER_PAID_TENANTS")
        self.day(3)
        self.assertEqual((self.pw.navs, self.bb.creates), ([], []))
        self.assertEqual(self.rows("SELECT * FROM load_reservation"), [])
        self.assertEqual(self.rows("SELECT * FROM lane_state WHERE lane = 'google_fresh'"), [])
        self.assertEqual(self.fresh()["state"], "never")
        self.assertEqual(self.scan(d=3), "ok")

    def test_missing_browserbase_creds_waits(self):
        with mock.patch.dict(os.environ, TRACKER_UNCAPPED_TENANTS=""):
            self.day(2)
        f = self.fresh()
        self.assertEqual((f["state"], f["reason"], f["next_attempt_on"]),
                         ("waiting", "no_browserbase_key", "2026-11-03"))
        with mock.patch.dict(os.environ, BROWSERBASE_API_KEY=""):
            self.day(3)
        self.assertEqual((self.fresh()["state"], self.fresh()["reason"]), ("waiting", "no_browserbase_key"))
        self.assertEqual((self.pw.navs, self.bb.creates), ([], []))
        self.assertEqual(self.rows("SELECT * FROM load_reservation"), [])
        self.assertEqual(self.rows("SELECT * FROM lane_day WHERE lane = 'google_fresh'"), [])

    def test_own_creds_from_the_cli_never_mix_in_a_session(self):
        self.clock(tdb.plus(Base.T0, seconds=1))
        t2 = self.tenant("Agency B")
        w2 = self.watch(t2, username="rowan_ash", account_id="acc-b")
        kf = os.path.join(self.tmp.name, "bb.key")
        with open(kf, "w", encoding="utf-8") as fh:
            fh.write(OWN_KEY + "\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            tracker_cli.main(["tenant", "bb", t2, "--key-file", kf, "--project", "prj-b"])
            tracker_cli.main(["tenant", "list"])
        self.assertNotIn(OWN_KEY, out.getvalue())
        self.assertEqual(self.rows("SELECT bb_key, bb_project FROM tenants WHERE tenant_id = ?", t2),
                         [{"bb_key": OWN_KEY, "bb_project": "prj-b"}])
        with self.assertRaises(SystemExit):
            tracker_cli.main(["tenant", "bb", "tn_nope", "--key-file", kf, "--project", "p"])
        log = io.StringIO()
        with mock.patch.dict(os.environ, TRACKER_PAID_TENANTS=f"{self.t},{t2}"), \
                mock.patch.object(tracker_probe, "log", side_effect=lambda m: log.write(m + "\n")):
            self.pw.script = ["fail", "fail"]
            self.day(2)
        self.assertEqual([(k, b["projectId"]) for k, b in self.bb.creates], [(HOST_KEY, HOST_PROJECT), (OWN_KEY, "prj-b")])
        self.assertEqual([q for _, q in self.pw.navs], [self.q().urls()[0], self.q(w2).urls()[0]])
        self.assertEqual(len(self.pw.sessions()), 2)
        self.assertNotIn(OWN_KEY, log.getvalue())
        self.assertNotIn(HOST_KEY, log.getvalue())
        self.assert_charged()

    def test_known_leak_only_ever_set_visible(self):
        known = self.leak(self.w, f"{SITE}/video/mia_vale-k1", google=False)
        with tdb.db() as c:
            tdb.add_event(c, known, "google_seen", {"visible": False})
        self.pw.links[self.q().text] = [(f"{SITE}/video/mia_vale-k1", "Mia")]
        self.day(2)
        self.day(3)
        self.assertEqual([e["data"] for e in self.events(known, "google_seen")], [{"visible": False}, {"visible": True}])
        self.assertEqual(len(self.pw.navs), 2)
        self.pw.links.clear()
        self.day(4)
        self.assertEqual(len(self.events(known, "google_seen")), 2)

    def many(self, n):
        with tdb.db() as c:
            c.execute("UPDATE tenants SET creators_max = 20")
        for i in range(n):
            self.clock(tdb.plus(Base.T0, seconds=i + 1))
            self.watch(self.t, username=f"rowan_ash{i}", account_id=f"acc-{i}")
        return self.rows("SELECT watch_id FROM watches ORDER BY created_at, watch_id")

    def test_breaker_three_failed_queries_end_the_group(self):
        ws = self.many(4)
        self.pw.script = ["wall", "wall", "fail", "wall", "wall"]
        self.day(2)
        self.assertEqual(len(self.pw.navs), 5)
        self.assertEqual(len(self.bb.creates), 5)
        self.assert_charged()
        self.assertEqual(len(self.rows("SELECT * FROM load_reservation")), 3)
        for r in ws:
            self.assertEqual(self.lane_day(r["watch_id"]), [{"outcome": "partial", "reason": "google_failed"}])
            self.assertEqual(self.scan(r["watch_id"]), "partial")

    def test_breaker_success_resets_the_count(self):
        ws = self.many(4)
        self.pw.script = ["fail", "fail", None, "fail", "fail"]
        self.day(2)
        self.assertEqual(len(self.pw.navs), 5)
        self.assert_charged()
        self.assertEqual([self.lane_day(r["watch_id"])[0]["outcome"] for r in ws],
                         ["partial", "partial", "ok", "partial", "partial"])

    def test_breaker_counts_errors_outside_the_search(self):
        ws = self.many(4)
        with mock.patch.object(tracker_lanes.tracker_budget, "reserve", side_effect=RuntimeError("db")) as reserve:
            self.day(2)
        self.assertEqual(reserve.call_count, 3)
        self.assertEqual(self.pw.navs, [])
        for r in ws:
            self.assertEqual(self.lane_day(r["watch_id"]), [{"outcome": "partial", "reason": "google_failed"}])

    def test_breaker_failed_create_no_more_sessions(self):
        self.many(3)
        self.bb.fail = True
        self.day(2)
        self.assertEqual((len(self.bb.creates), self.pw.navs), (1, []))
        self.assertEqual(self.used(), 0)
        self.assert_charged()
        self.assertEqual(self.rows("SELECT DISTINCT outcome, reason FROM lane_day WHERE lane = 'google_fresh'"),
                         [{"outcome": "partial", "reason": "google_failed"}])
        self.assertEqual(len(self.rows("SELECT * FROM lane_day WHERE lane = 'google_fresh'")), 4)

    def test_broken_playwright_bills_nothing(self):
        self.many(1)
        with mock.patch.object(tracker_serp, "_playwright", side_effect=ImportError("No module named 'playwright'")):
            self.day(2)
        self.assertEqual((self.bb.creates, self.pw.navs, self.bb.releases), ([], [], []))
        self.assertEqual(self.used(), 0)
        self.assert_charged()
        self.assertEqual(len(self.rows("SELECT * FROM load_reservation")), 1)
        self.assertEqual((self.fresh()["state"], self.fresh()["reason"]), ("reduced", "google_failed"))

    def test_page_prep_failure_burns_no_unit(self):
        self.pw.page_fail = True
        self.day(2)
        self.assertEqual((len(self.bb.creates), self.pw.navs, self.used()), (1, [], 0))
        self.assert_charged()
        self.assertEqual(self.lane_day(), [{"outcome": "partial", "reason": "google_failed"}])

    def test_session_rotates_by_age(self):
        ws = self.many(2)
        t = [1000.0]
        with mock.patch.object(tracker_serp, "_clock", lambda: t[0]), \
                mock.patch.object(tracker_serp.Session, "load", autospec=True,
                                  side_effect=lambda sess, page, url: (t.__setitem__(0, t[0] + 100),
                                                                       REAL_LOAD(sess, page, url))[1]):
            self.day(2)
        self.assertLess(tracker_serp.ROTATE_S, tracker_serp.SESSION_S)
        self.assertEqual(len(self.pw.navs), 3)
        self.assertEqual([sum(1 for c, _ in self.pw.navs if c == s) for s in self.pw.sessions()], [2, 1])
        self.assert_charged()
        self.assertEqual({self.fresh(r["watch_id"])["state"] for r in ws}, {"ok"})

    def test_missing_tenant_row_skips_only_that_watch(self):
        t2 = self.tenant("Agency B")
        w2 = self.watch(t2, username="rowan_ash", account_id="acc-b")
        with tdb.db() as c:
            c.execute("DELETE FROM tenants WHERE tenant_id = ?", (t2,))
        with mock.patch.dict(os.environ, TRACKER_PAID_TENANTS=f"{self.t},{t2}"):
            tracker_lanes.run_fresh_batch([w2, self.w], "2026-11-02")
        self.assertEqual([q for _, q in self.pw.navs], [self.q().urls()[0]])
        self.assertEqual(self.rows("SELECT watch_id, state FROM lane_state WHERE lane = 'google_fresh'"),
                         [{"watch_id": self.w, "state": "ok"}])
        self.assert_charged()

    def test_gone_records_nothing(self):
        gone = tracker_lanes.tracker_budget.Refused("gone", None)
        with mock.patch.object(tracker_lanes.tracker_budget, "reserve", return_value=gone):
            self.day(2)
        self.assertEqual((self.pw.navs, self.bb.creates), ([], []))
        self.assertEqual(self.rows("SELECT * FROM lane_state WHERE lane = 'google_fresh'"), [])
        self.assertEqual(self.lane_day(), [])

    def test_no_cse_or_serper_in_the_phase_2_tracker_modules(self):
        mods = ("tracker_plan", "tracker_budget", "tracker_admission", "tracker_lanes", "tracker_judge", "tracker_serp")
        for f in (os.path.join(os.path.dirname(tracker_lanes.__file__), m + ".py") for m in mods):
            with open(f, encoding="utf-8") as fh:
                self.assertIsNone(re.search(r"cse_scanner|serper|customsearch", fh.read(), re.I), f)



def wd(d):
    return tdb.parse(at(d)).weekday()


class Full(Fresh):
    """The weekly full Google pass (ticket 27): self.w's plan is 14 loads (handle 9, strong alias miavale_x 4, weak
    alias miav 1); every daily tick runs the fresh pass's one load first."""

    def setUp(self):
        super().setUp()
        self.slot(2)

    def slot(self, d, wid=None):
        with tdb.db() as c:
            c.execute("UPDATE watches SET weekly_slot = ? WHERE watch_id = ?", (wd(d), wid or self.w))

    def row(self, wid=None):
        return self.rows("SELECT * FROM watches WHERE watch_id = ?", wid or self.w)[0]

    def plan(self, wid=None):
        return tracker_plan.build(self.row(wid), "onlyfans")

    def full_navs(self):
        return [u for _, u in self.pw.navs if "qdr" not in u]

    def full(self, wid=None):
        return self.lanes(wid)["google_full"]

    def lanes_of(self, wid, key):
        return {x["lane"]: x for x in self.get(f"/v1/creators/{wid}", key)[1]["lanes"]}

    def full_day(self, wid=None):
        return self.rows("SELECT day, outcome, reason FROM lane_day WHERE lane = 'google_full' AND watch_id = ? "
                         "ORDER BY day", wid or self.w)

    def carry(self, wid=None):
        return json.loads(self.row(wid)["carry_json"] or "null")

    def lane_view(self, wid=None):
        f = self.full(wid)
        return {k: f[k] for k in ("cadence", "state", "reason", "next_attempt_on", "trimmed")}

    def assert_day_within_cap(self, d, cap):
        spent = self.rows("SELECT COALESCE(SUM(used), 0) AS n FROM load_reservation WHERE day = ?", f"2026-11-{d:02d}")
        self.assertLessEqual(spent[0]["n"], cap)



class TestFullPass(Full):
    def test_session_settings_and_blocking_per_vertical(self):
        plan = self.plan()
        self.assertEqual(plan.loads, 14)
        web, img, vid = f"{SITE}/video/mia_vale-w1", f"{SITE}/gallery/mia_vale-i1", f"{SITE}/clip/mia_vale-v1"
        self.pw.links.update({("web", '"mia_vale"'): [(web, "Mia")], ("images", '"mia_vale"'): [(img, "Mia pics")],
                              ("videos", '"mia_vale"'): [(vid, "Mia clip")]})
        self.day(2)
        urls = [u for q in plan.queries for u in q.urls()]
        self.assertEqual(self.full_navs(), urls)
        self.assertEqual(len(self.bb.creates), 3)
        self.assertEqual({k for k, _ in self.bb.creates}, {HOST_KEY})
        self.assertEqual([b for _, b in self.bb.creates], [CREATE] * 3)
        self.assertEqual(len(self.bb.releases), 3)
        blocks = dict(zip((u for _, u in self.pw.navs), self.pw.blocks))
        for u in urls:
            self.assertIs(blocks[u].func, tracker_serp.block_assets)
            want = {"media", "font"} if "tbm=isch" in u else {"image", "media", "font", "stylesheet"}
            self.assertEqual(blocks[u].keywords, {"types": want}, u)
        self.assert_charged()
        self.assertEqual(self.used(), 15)
        self.assertEqual(self.lane_view(), {"cadence": "weekly", "state": "ok", "reason": None,
                                            "next_attempt_on": "2026-11-09", "trimmed": []})
        self.assertEqual(self.full()["last_success_at"], at(2))
        self.assertEqual(self.full_day(), [{"day": "2026-11-02", "outcome": "ok", "reason": None}])
        b = self.get(f"/v1/creators/{self.w}/leaks")[1]
        self.assertEqual(sorted((x["url"], x["sources"], x["found_on_first_scan"]) for x in b["leaks"]),
                         sorted((u, ["google_web"], True) for u in (web, img, vid)))
        self.assertEqual({r["url"]: json.loads(r["google_fields_json"]) for r in self.rows(
            "SELECT url, google_fields_json FROM leaks")}, {web: [["web", "handle"]], img: [["images", "handle"]],
                                                            vid: [["videos", "handle"]]})
        self.assertEqual(len(self.rows("SELECT * FROM serp_cache WHERE since = ''")), 14)

    def test_images_blocker_keeps_images(self):
        class Route:
            def __init__(self, t):
                self.request, self.done = mock.Mock(resource_type=t), None

            def abort(self):
                self.done = "abort"

            def continue_(self):
                self.done = "continue"

        got = {}
        for t in ("image", "font", "media", "stylesheet", "document", "script"):
            r = Route(t)
            tracker_serp.block_assets(r, tracker_serp.BLOCKED["images"])
            got[t] = r.done
        self.assertEqual(got, {"image": "continue", "font": "abort", "media": "abort", "stylesheet": "continue",
                               "document": "continue", "script": "continue"})
        self.assertEqual(tracker_serp.BLOCKED, {"web": tracker_serp.BLOCKED_TYPES, "videos": tracker_serp.BLOCKED_TYPES,
                                                "images": {"media", "font"}})

    def test_slot_weekday_runs_other_weekdays_dont(self):
        self.slot(3)
        w2 = self.watch(self.t, username="rowan_ash", account_id="acc-r", weekly_slot=wd(4))
        self.day(2)
        self.assertEqual(self.full_navs(), [])
        self.assertEqual((self.full()["state"], self.full(w2)["state"]), ("never", "never"))
        self.day(3)
        self.assertEqual(len(self.full_navs()), 14)
        self.assertEqual((self.full()["state"], self.full(w2)["state"]), ("ok", "never"))
        self.assertEqual(self.full()["next_attempt_on"], "2026-11-10")
        self.day(4)
        self.assertEqual(len(self.full_navs()), 14 + 9)
        self.assertEqual(self.full(w2)["state"], "ok")
        self.day(5)
        self.assertEqual(len(self.full_navs()), 23)
        self.assertEqual(self.full_day(), [{"day": "2026-11-03", "outcome": "ok", "reason": None}])
        self.assert_charged()

    def test_paused_gate_and_missing_creds(self):
        with tdb.db() as c:
            c.execute("UPDATE watches SET paused = 1, paused_at = ? WHERE watch_id = ?", (at(2), self.w))
        self.day(2)
        self.assertEqual((self.pw.navs, self.full()["state"]), ([], "paused"))
        with tdb.db() as c:
            c.execute("UPDATE watches SET paused = 0, paused_at = NULL WHERE watch_id = ?", (self.w,))
        self.slot(3)
        with mock.patch.dict(os.environ, TRACKER_PAID_TENANTS=""):
            self.day(3)
        self.assertEqual(self.pw.navs, [])
        self.assertEqual(self.full()["state"], "never")
        self.slot(4)
        with mock.patch.dict(os.environ, TRACKER_UNCAPPED_TENANTS=""):
            self.day(4)
        self.assertEqual((self.pw.navs, self.bb.creates), ([], []))
        self.assertEqual({k: self.full()[k] for k in ("state", "reason", "next_attempt_on")},
                         {"state": "waiting", "reason": "no_browserbase_key", "next_attempt_on": "2026-11-11"})
        self.assertEqual(self.full_day(), [])
        self.assertEqual(self.rows("SELECT * FROM load_reservation"), [])

    def test_partial_grant_trims_carries_and_the_carry_runs_once(self):
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 10")
        self.day(2)
        cut = [q for q in self.plan().queries if q.field.startswith("alias:") or "mega.nz" in q.text
               or "site:t.me" in q.text]
        kept = [u for q in self.plan().queries if q not in cut for u in q.urls()]
        self.assertEqual(self.full_navs(), kept)
        self.assertEqual(len(kept), 7)
        self.assert_charged()
        self.assert_day_within_cap(2, 10)
        trimmed = [{"field": "alias:1", "value": "miav"}, {"field": "alias:0", "value": "miavale_x"}]
        self.assertEqual(self.lane_view(), {"cadence": "weekly", "state": "reduced", "reason": "cap_global",
                                            "next_attempt_on": "2026-11-03", "trimmed": trimmed})
        self.assertEqual(self.full_day(), [{"day": "2026-11-02", "outcome": "partial", "reason": "cap_global"}])
        self.assertEqual(self.scan(), "partial")
        carry = self.carry()
        self.assertEqual((carry["on"], carry["reason"], carry["first"]), ("2026-11-03", "cap_global", True))
        self.assertEqual(sorted(map(tuple, carry["pages"])), sorted((q.vertical, q.text, 0) for q in cut))

        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 6")
        self.day(3)
        carried = [u for u in self.full_navs()[7:]]
        self.assertEqual(sorted(carried), sorted(q.urls()[0] for q in cut if q.field == "handle"))
        self.assert_charged()
        self.assert_day_within_cap(3, 6)
        self.assertIsNone(self.carry())
        self.assertEqual(self.lane_view(), {"cadence": "weekly", "state": "reduced", "reason": "cap_global",
                                            "next_attempt_on": "2026-11-09", "trimmed": trimmed})
        self.assertEqual(self.full_day()[1], {"day": "2026-11-03", "outcome": "partial", "reason": "cap_global"})

        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 300")
        self.day(4)
        self.day(5)
        self.assertEqual(len(self.full_navs()), 9)
        self.assertEqual(len(self.full_day()), 2)
        self.assert_charged()

    def test_carry_runs_whole_inside_the_next_days_room(self):
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 10")
        self.day(2)
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 300")
        self.day(3)
        self.assertEqual(len(self.full_navs()), 14)
        self.assertEqual(sorted(self.full_navs()), sorted(u for q in self.plan().queries for u in q.urls()))
        self.assertEqual(self.lane_view(), {"cadence": "weekly", "state": "ok", "reason": None,
                                            "next_attempt_on": "2026-11-09", "trimmed": []})
        self.assertIsNone(self.carry())
        self.day(4)
        self.assertEqual(len(self.full_navs()), 14)
        self.assert_charged()

    def test_identity_grown_after_admission_trimmed_never_over_the_cap(self):
        with tdb.db() as c:
            c.execute("UPDATE watches SET plan_loads = 9, instagram = 'mia.vale.ig', x = 'miavale_xx' WHERE watch_id = ?",
                      (self.w,))
            c.execute("UPDATE tracker_limits SET daily_loads = 12")
        self.assertEqual(self.plan().loads, 16)
        self.day(2)
        self.assert_charged()
        self.assert_day_within_cap(2, 12)
        self.assertEqual(len(self.full_navs()), 9)
        self.assertEqual([t["field"] for t in self.full()["trimmed"]], ["alias:1", "alias:0", "x", "instagram"])

    def test_month_cap_waits_until_the_1st(self):
        with tdb.db() as c:
            c.execute("UPDATE tenants SET month_loads = 1")
        self.day(2)
        self.assertEqual(self.full_navs(), [])
        self.assertEqual(self.lane_view(), {"cadence": "weekly", "state": "waiting", "reason": "cap_tenant_month",
                                            "next_attempt_on": "2026-12-01", "trimmed": []})
        self.assertEqual(self.full_day(), [{"day": "2026-11-02", "outcome": "partial", "reason": "cap_tenant_month"}])
        carry = self.carry()
        self.assertEqual((carry["on"], carry["reason"], len(carry["pages"])), ("2026-12-01", "cap_tenant_month", 14))
        for d in (3, 4, 30):
            self.day(d)
        self.assertEqual(self.full_navs(), [])
        self.assertEqual(self.full()["next_attempt_on"], "2026-12-01")
        with tdb.db() as c:
            c.execute("UPDATE tenants SET month_loads = 300")
        tracker_scheduler.daily_pass("2026-12-01T05:00:00Z")
        self.assertEqual(len(self.full_navs()), 14)
        self.assertIsNone(self.carry())
        self.clock("2026-12-01T05:00:00Z")
        self.assertEqual({k: self.full()[k] for k in ("state", "next_attempt_on")},
                         {"state": "ok", "next_attempt_on": "2026-12-07"})
        self.assert_charged()

    def test_month_cap_partial_cut_waits_until_the_1st(self):
        with tdb.db() as c:
            c.execute("UPDATE tenants SET month_loads = 8")
        self.day(2)
        self.assertEqual(len(self.full_navs()), 5)
        f = self.full()
        self.assertEqual((f["state"], f["reason"], f["next_attempt_on"]), ("reduced", "cap_tenant_month", "2026-12-01"))
        self.assertEqual(self.carry()["on"], "2026-12-01")
        self.assert_charged()

    def test_wall_retries_once_and_a_second_wall_ends_the_query_incomplete(self):
        self.pw.script = [None, "wall", None, "wall", "wall"]
        self.day(2)
        urls = [u for q in self.plan().queries for u in q.urls()]
        self.assertEqual(self.full_navs(), [urls[0], urls[0], urls[1], urls[1], *urls[2:]])
        self.assertEqual(len(self.pw.sessions()), 1 + 3 + 1)
        self.assert_charged()
        self.assertEqual(self.used(), 1 + 16)
        self.assertEqual(self.rows("SELECT held, used FROM load_reservation ORDER BY created_at, held"),
                         [{"held": 2, "used": 1}, {"held": 16, "used": 16}])
        f = self.full()
        self.assertEqual((f["state"], f["reason"], f["last_success_at"]), ("reduced", "google_failed", at(2)))
        self.assertEqual(self.full_day(), [{"day": "2026-11-02", "outcome": "partial", "reason": "google_failed"}])
        self.assertEqual(self.rows("SELECT page FROM serp_cache WHERE text = '\"mia_vale\"' AND vertical = 'web'"),
                         [{"page": 0}])
        self.assertIsNone(self.carry())

    def test_wall_with_the_hold_used_up_ends_incomplete_one_navigation(self):
        self.pw.script = [None, "wall", None, None, None, "wall"] + [None] * 10 + ["wall"]
        self.day(2)
        urls = [u for q in self.plan().queries for u in q.urls()]
        self.assertEqual(self.full_navs(), [urls[0], urls[0], urls[1], urls[2], urls[3], urls[3], *urls[4:]])
        self.assert_charged()
        self.assertEqual(self.rows("SELECT held, used FROM load_reservation WHERE held > 2"), [{"held": 16, "used": 16}])
        self.assertEqual((self.full()["state"], self.full()["reason"]), ("reduced", "google_failed"))

    def test_breaker_failed_create_ends_the_pass(self):
        self.day(2)
        n = len(self.bb.creates)
        self.slot(3)
        self.bb.fail = True
        self.day(3)
        self.assertEqual(len(self.bb.creates), n + 1)
        self.assertEqual(len(self.pw.navs), 15)
        self.assert_charged()
        self.assertEqual((self.full()["state"], self.full()["reason"]), ("reduced", "google_failed"))

    def test_breaker_carries_across_the_ticks_weekly_watches(self):
        w2 = self.watch(self.t, username="rowan_ash", account_id="acc-r", weekly_slot=wd(2))
        self.pw.script = ["wall"] * 100
        self.day(2)
        self.assert_charged()
        self.assertLessEqual(self.used(), 6)
        self.assertEqual(self.used(), 6)
        self.assertEqual(sorted(self.used(w) for w in (self.w, w2)), [2, 4])
        self.assertEqual({(self.full(w)["state"], self.full(w)["reason"]) for w in (self.w, w2)},
                         {("reduced", "google_failed")})
        self.assertEqual(self.rows("SELECT * FROM serp_cache"), [])

    def test_empty_shell_page_is_incomplete_on_the_full_pass_only(self):
        self.pw.script = ["shell", "shell"]
        self.day(2)
        self.assert_charged()
        self.assertEqual(len(self.full_navs()), 14)
        self.assertEqual(self.fresh()["state"], "ok")
        self.assertEqual((self.full()["state"], self.full()["reason"]), ("reduced", "google_failed"))
        cached = {(r["vertical"], r["text"], r["page"], r["since"]) for r in self.rows("SELECT * FROM serp_cache")}
        self.assertNotIn(("web", '"mia_vale"', 0, ""), cached)
        self.assertIn(("web", '"mia_vale"', 1, ""), cached)
        self.assertEqual(len(cached), 1 + 13)

    def test_restart_after_the_daily_rows_reticks_weekly_once(self):
        with mock.patch.object(tracker_lanes, "run_weekly_batch"):
            self.day(2)
        self.assertEqual((self.full_navs(), self.full()["state"]), ([], "never"))
        self.assertEqual(self.scan(), "ok")
        tracker_scheduler.daily_pass(tdb.plus(at(2), hours=1))
        self.assertEqual(len(self.full_navs()), 14)
        tracker_scheduler.daily_pass(tdb.plus(at(2), hours=2))
        self.assertEqual(len(self.full_navs()), 14)
        self.assertEqual(self.full_day(), [{"day": "2026-11-02", "outcome": "ok", "reason": None}])
        self.assert_charged()

    def test_watch_seeded_today_runs_its_due_full_pass(self):
        import tracker_seed
        w2 = self.watch(self.t, username="rowan_ash", account_id="acc-r", seeded=False, weekly_slot=wd(2))
        cand = {"google": [], "mega": [], "errors": []}
        with mock.patch.object(tracker_seed, "_quick_candidates", return_value=lambda *a: cand):
            self.day(2)
        self.assertEqual(self.full(w2)["state"], "ok")
        self.assertEqual(sum('rowan_ash' in u for u in self.full_navs()), tracker_plan.build(self.row(w2), "onlyfans").loads)
        self.assert_charged()

    def test_trimmed_slot_keeps_first_scan_for_the_carry(self):
        mega_hit, later = f"{SITE}/video/mia_vale-c1", f"{SITE}/video/mia_vale-c2"
        self.pw.links[("web", '"mia_vale" mega.nz')] = [(mega_hit, "Mia")]
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 10")
        self.day(2)
        self.assertEqual(self.full()["state"], "reduced")
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 300")
        self.day(3)
        self.assertEqual(self.full()["state"], "ok")
        self.pw.links[("web", '"mia_vale"')] = [(later, "Mia")]
        self.day(9)
        b = self.get(f"/v1/creators/{self.w}/leaks")[1]
        self.assertEqual({x["url"]: x["found_on_first_scan"] for x in b["leaks"]}, {mega_hit: True, later: False})
        self.assert_charged()

    def test_walled_slot_still_ends_the_first_scan_baseline(self):
        first, later = f"{SITE}/video/mia_vale-f1", f"{SITE}/video/mia_vale-f2"
        self.pw.links[("web", '"mia_vale" onlyfans')] = [(first, "Mia")]
        self.pw.script = [None, "wall", "wall"]
        self.day(2)
        self.assertEqual((self.full()["state"], self.full()["reason"]), ("reduced", "google_failed"))
        self.pw.links[("web", '"mia_vale" leaked')] = [(later, "Mia")]
        self.day(9)
        b = self.get(f"/v1/creators/{self.w}/leaks")[1]
        self.assertEqual({x["url"]: x["found_on_first_scan"] for x in b["leaks"]}, {first: True, later: False})
        self.assert_charged()

    def test_crash_mid_carry_keeps_the_carry_for_a_retick(self):
        self.pw.links[("web", '"mia_vale" mega.nz')] = [(f"{SITE}/video/mia_vale-c1", "Mia")]
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 10")
        self.day(2)
        carry = self.carry()
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 300")
        with mock.patch.object(tracker_lanes.tracker_judge, "admit_hit", side_effect=RuntimeError("boom")):
            self.day(3)
        self.assertEqual(self.carry(), carry)
        self.assertEqual(self.full()["state"], "failed")
        n = len(self.full_navs())
        tracker_scheduler.daily_pass(tdb.plus(at(3), hours=1))
        self.assertEqual(len(self.full_navs()), n)
        self.assertIsNone(self.carry())
        self.assertEqual(self.full()["state"], "ok")
        self.assertEqual(len(self.rows("SELECT * FROM leaks WHERE url = ?", f"{SITE}/video/mia_vale-c1")), 1)
        self.assert_charged()

    def test_two_tenants_same_handle_reuse_the_cache(self):
        self.clock(tdb.plus(Base.T0, seconds=1))
        t2 = self.tenant("Agency B")
        key2 = self.issue(t2)
        w2 = self.watch(t2, username="mia_vale", aliases=("miavale_x", "miav"), account_id="acc-b", weekly_slot=wd(2))
        hit = f"{SITE}/gallery/mia_vale-i9"
        self.pw.links[("images", '"miavale_x"')] = [(hit, "Mia")]
        with mock.patch.dict(os.environ, TRACKER_PAID_TENANTS=f"{self.t},{t2}", TRACKER_UNCAPPED_TENANTS=f"{self.t},{t2}"):
            self.day(2)
            self.assertEqual(len(self.full_navs()), 14)
            self.assert_charged()
            self.assertEqual((self.used(self.w), self.used(w2)), (15, 0))
            self.assertEqual(self.lanes_of(w2, key2)["google_full"]["state"], "ok")
            b = self.get(f"/v1/creators/{w2}/leaks", key2)[1]
            self.assertEqual([x["url"] for x in b["leaks"]], [hit])
        self.assertEqual(self.rows("SELECT google_fields_json FROM leaks WHERE watch_id = ?", w2),
                         [{"google_fields_json": '[["images","alias:miavalex"]]'}])


class TestVisibility(Full):
    URL = f"{SITE}/video/mia_vale-k1"

    def setUp(self):
        super().setUp()
        tracker_probe.set_fetcher(lambda u: (404, ""))

    def known(self, fields, url=None, gone=True):
        lid = self.leak(self.w, url or self.URL)
        with tdb.db() as c:
            c.execute("UPDATE leaks SET google_fields_json = ? WHERE leak_id = ?", (json.dumps(fields), lid))
            if gone:
                c.execute("INSERT INTO probe_state (leak_id, origin_status, last_status) VALUES (?, 'gone', 'dead')",
                          (lid,))
        return lid

    def vis(self, lid):
        return [e["data"].get("visible", True) for e in self.events(lid, "google_seen")]

    def pill(self, url=None):
        return self.pills()[url or self.URL]

    def fields(self, lid):
        return json.loads(self.rows("SELECT google_fields_json FROM leaks WHERE leak_id = ?", lid)[0]["google_fields_json"])

    def test_false_only_when_every_planned_pair_completed(self):
        lid = self.known([["web", "handle"], ["images", "alias:miavalex"]])
        self.assertEqual(self.pill(), "cached")
        qs = self.plan().queries
        alias_img = next(i for i, q in enumerate(qs) if q.vertical == "images" and q.field == "alias:0")
        self.pw.script = [None] * (1 + sum(q.pages for q in qs[:alias_img])) + ["fail"]
        self.day(2)
        self.assertEqual(self.vis(lid), [True])
        self.assertEqual(self.pill(), "cached")
        self.assertEqual((self.full()["state"], self.full()["reason"]), ("reduced", "google_failed"))
        self.day(9)
        self.assertEqual(self.vis(lid), [True, False])
        self.assertEqual(self.pill(), "gone")
        self.assertEqual(sorted(self.fields(lid)), [["images", "alias:miavalex"], ["web", "handle"]])
        self.pw.links[("images", '"miavale_x"')] = [(self.URL, "Mia")]
        self.day(16)
        self.assertEqual(self.vis(lid), [True, False, True])
        self.assertEqual(self.pill(), "cached")
        self.assert_charged()

    def test_trimmed_pair_never_counts_as_a_miss(self):
        lid = self.known([["web", "handle"], ["web", "alias:miavalex"]])
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 10")
        self.day(2)
        self.assertEqual(self.vis(lid), [True])
        self.assert_charged()

    def test_removed_alias_pair_dropped_and_an_emptied_set_is_unknown(self):
        only_alias = self.known([["images", "alias:miavalex"]])
        both = self.known([["web", "handle"], ["web", "alias:miavalex"]], url=f"{SITE}/video/mia_vale-k2", gone=False)
        fresh_only = self.known([], url=f"{SITE}/video/mia_vale-k3")
        mega = self.leak(self.w, leakshaven.SHARE + "/mv0009", kind="mega", google=False)
        with tdb.db() as c:
            c.execute("UPDATE watches SET aliases_json = '[\"miav\"]' WHERE watch_id = ?", (self.w,))
        self.pw.links[("web", '"mia_vale"')] = [(f"{SITE}/video/mia_vale-k2", "Mia")]
        self.day(2)
        self.assertEqual(self.fields(only_alias), [])
        self.assertEqual(self.vis(only_alias), [True, None])
        self.assertEqual(self.pill(), "gone")
        self.assertEqual(self.fields(both), [["web", "handle"]])
        self.assertEqual(self.vis(both), [True])
        self.assertEqual(self.vis(fresh_only), [True])
        self.assertEqual(self.pill(f"{SITE}/video/mia_vale-k3"), "cached")
        self.assertEqual(self.vis(mega), [])
        self.assertIsNone(self.rows("SELECT google_fields_json FROM leaks WHERE leak_id = ?", mega)[0]["google_fields_json"])
        self.assert_charged()

    def test_refused_or_failed_pass_writes_no_google_seen(self):
        lid = self.known([["images", "alias:miavalex"]])
        with tdb.db() as c:
            c.execute("UPDATE watches SET aliases_json = '[\"miav\"]' WHERE watch_id = ?", (self.w,))
            c.execute("UPDATE tenants SET month_loads = 1")
        self.day(2)
        self.assertEqual((self.full()["state"], self.full()["reason"]), ("waiting", "cap_tenant_month"))
        self.assertEqual(self.vis(lid), [True])
        self.assertEqual(self.fields(lid), [["images", "alias:miavalex"]])
        with tdb.db() as c:
            c.execute("UPDATE tenants SET month_loads = 1000")
        self.slot(3)
        self.pw.script = ["fail"] * 100
        self.day(3)
        self.assertEqual((self.full()["state"], self.full()["reason"]), ("reduced", "google_failed"))
        self.assertEqual(self.vis(lid), [True])
        self.slot(4)
        self.pw.script = []
        self.day(4)
        self.assertEqual(self.vis(lid), [True, None])
        self.assert_charged()

    def test_shell_page_never_counts_toward_false(self):
        lid = self.known([["web", "handle"]])
        self.pw.script = [None, None, None, None, None, None, None, None, None, "shell"]
        self.day(2)
        self.assertEqual(self.vis(lid), [True])
        self.day(9)
        self.assertEqual(self.vis(lid), [True, False])
        self.assert_charged()

    def test_tripped_breaker_adds_pairs_but_never_nulls_or_falses(self):
        hit = f"{SITE}/video/mia_vale-b1"
        only_alias = self.known([["images", "alias:miavalex"]])
        handle = self.known([["web", "handle"]], url=f"{SITE}/video/mia_vale-k2")
        with tdb.db() as c:
            c.execute("UPDATE watches SET aliases_json = '[\"miav\"]' WHERE watch_id = ?", (self.w,))
        self.pw.links[("web", '"mia_vale"')] = [(hit, "Mia")]
        self.pw.script = [None, None] + ["wall"] * 100
        self.day(2)
        self.assertEqual(self.rows("SELECT google_fields_json FROM leaks WHERE url = ?", hit),
                         [{"google_fields_json": '[["web","handle"]]'}])
        self.assertEqual((self.vis(only_alias), self.vis(handle)), ([True], [True]))
        self.assertEqual(self.fields(only_alias), [["images", "alias:miavalex"]])
        self.slot(3)
        self.pw.script = []
        self.day(3)
        self.assertEqual((self.vis(only_alias), self.vis(handle)), ([True, None], [True, False]))
        self.assert_charged()

    def test_seed_google_leaks_hold_web_handle(self):
        import tracker_seed
        w2 = self.watch(self.t, username="rowan_ash", account_id="acc-r", seeded=False)
        cand = {"google": [{"link": f"{SITE}/video/rowan_ash-1", "title": "Rowan"}], "mega": [], "errors": []}
        with mock.patch.object(tracker_seed, "_quick_candidates", return_value=lambda *a: cand):
            tracker_seed.run(w2)
        self.assertEqual(self.rows("SELECT google_fields_json FROM leaks WHERE watch_id = ?", w2),
                         [{"google_fields_json": '[["web","handle"]]'}])
        old = self.leak(self.w, self.URL)
        site = self.leak(self.w, f"{SITE}/models/mia_vale/", google=False)
        with tdb.db() as c:
            c.execute("ALTER TABLE leaks DROP COLUMN google_fields_json")
        tdb.init()
        got = {r["leak_id"]: r["google_fields_json"] for r in self.rows("SELECT leak_id, google_fields_json FROM leaks")}
        self.assertEqual((got[old], got[site]), ('[["web","handle"]]', None))


if __name__ == "__main__":
    import unittest
    unittest.main()

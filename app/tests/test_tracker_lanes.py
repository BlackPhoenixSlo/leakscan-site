"""Leak lanes (Phase 2 tickets 19, 25, 26): Phase 1's daily scheduler tick on a controlled UTC clock over a temp
TRACKER_DB runs run_daily (origin probe lane state, the Mega lookup, the listing recheck) against the Mega index wire
stub (leakshaven_stub) and the stub fetcher (its table serves the fake listing pages) over a test detection map, then
run_fresh_batch (the Google fresh pass) against a local Browserbase REST stub and a fake Playwright that records every
navigation; every case reads the API's `lanes` over HTTP too. No real network, no paid call. Fictional creators only."""
import contextlib
import glob
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
import tracker_view

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
CREATE = {"projectId": HOST_PROJECT, "timeout": 300, "browserSettings": {"solveCaptchas": True}}


class BBStub(ThreadingHTTPServer):
    """Browserbase REST on loopback: POST /sessions -> {id, connectUrl}; POST /sessions/<id> = a release."""

    def __init__(self):
        self.creates, self.releases, self.lock = [], [], threading.Lock()
        stub = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
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
    (connectUrl, url) in navs. script: per-navigation overrides ("wall", "fail"), else a results page with links[q]
    (no links: the empty-result page)."""

    def __init__(self):
        self.navs, self.routes, self.script, self.links, self.closed = [], [], [], {}, []
        self.chromium = self

    def connect_over_cdp(self, url, **kw):
        pw = self

        class Page:
            url = "about:blank"

            def route(self, pattern, handler):
                pw.routes.append((pattern, handler))

            def goto(self, u, **kw):
                pw.navs.append((url, u))
                step = pw.script.pop(0) if pw.script else None
                if step == "fail":
                    raise RuntimeError("net::ERR_TIMED_OUT")
                if step == "wall":
                    self.url, self.html = "https://www.google.com/sorry/index?continue=x", WALL
                    return
                links = pw.links.get(parse_qs(urlsplit(u).query)["q"][0], [])
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
        for p in (mock.patch.multiple(tracker_serp, BB_API=self.bb.base, _playwright=lambda: self.pw),
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

    def day_state(self, wid=None, d=2):
        with tdb.db() as c:
            w = c.execute("SELECT * FROM watches WHERE watch_id = ?", (wid or self.w,)).fetchone()
            return tracker_view.day_state(c, w, f"2026-11-{d:02d}")

    def scan(self, wid=None, d=2):
        return self.rows("SELECT outcome FROM daily_scans WHERE watch_id = ? AND day = ?", wid or self.w,
                         f"2026-11-{d:02d}")[0]["outcome"]


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
        self.assertEqual([(p, h) for p, h in self.pw.routes], [("**/*", tracker_serp.block_assets)])
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
        self.assertEqual((self.scan(), self.day_state()), ("ok", "complete"))
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
        self.assertEqual((self.scan(), self.day_state()), ("partial", "coverage_reduced"))
        self.assertEqual(self.rows("SELECT * FROM serp_cache"), [])

    def test_two_walls_end_the_query_incomplete(self):
        self.pw.script = ["wall", "wall"]
        self.day(2)
        self.assertEqual(len(self.pw.navs), 2)
        self.assertEqual(len(self.pw.sessions()), 2)
        self.assert_charged()
        self.assertEqual((self.fresh()["state"], self.fresh()["reason"]), ("reduced", "google_failed"))
        self.assertEqual(self.day_state(), "coverage_reduced")

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
        self.assertEqual((self.scan(), self.day_state()), ("partial", "coverage_reduced"))
        self.assertEqual(self.lanes()["listing_recheck"]["state"], "ok")

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
        self.assertEqual((self.scan(), self.day_state()), ("partial", "partial"))
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
        self.assertEqual((f["state"], f["reason"], f["next_attempt_on"]), ("waiting", "no_browserbase_key", None))
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

    def test_no_cse_or_serper_in_the_phase_2_tracker_modules(self):
        mods = ("tracker_plan", "tracker_budget", "tracker_admission", "tracker_lanes", "tracker_judge", "tracker_usage",
                "tracker_serp")
        files = [f for m in mods for f in glob.glob(os.path.join(os.path.dirname(tracker_lanes.__file__), m + ".py"))]
        self.assertGreaterEqual(len(files), 6)
        for f in files:
            with open(f, encoding="utf-8") as fh:
                self.assertIsNone(re.search(r"cse_scanner|serper|customsearch", fh.read(), re.I), f)


if __name__ == "__main__":
    import unittest
    unittest.main()

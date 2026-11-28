"""Paid Google lane (Phase 2 ticket 27; cadence slice A ticket 81): the full Google pass inside every scan and on a
carry's day, for every tenant, against a local Browserbase REST stub and a fake Playwright that records every
navigation; reservations, caps and the breaker hold (stub request count = `used` units). No real network, no paid
call. Fictional creators only."""
import contextlib
import io
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from tracker_fixture import Base, tdb, tracker_scheduler, tracker_stub_fetch
from test_tracker_lanes import SITE, Lanes, at, pack
import bb_client
import cse_scanner
import leakshaven
import tracker_cli
import tracker_lanes
import tracker_plan
import tracker_probe
import tracker_serp


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


def tile(vertical, href, title, thumb=None):
    """A result's markup; with a thumb, an images tile (data-lpage) or a result with its one image."""
    if thumb is None:
        return f'<div><a href="{href}"><h3>{title}</h3></a></div>'
    if vertical == "images":
        return f'<div data-lpage="{href}" aria-label="{title}"><a href="#"><img src="{thumb}"></a></div>'
    return f'<div><a href="{href}"><h3>{title}</h3></a><img src="{thumb}"></div>'


class FakePW:
    """Started sync Playwright stand-in: chromium.connect_over_cdp -> a browser whose pages record every goto as
    (connectUrl, url) in navs and the page's route handler in blocks. script: per-navigation overrides ("wall",
    "fail", "shell" = a bare #search), else a results page with links[(vertical, q)] ((href, title[, thumb]), see
    tile), or links[q] on web (no links: the empty-result page). page_fail: new_page raises."""

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
                self.html = RESULTS.format("".join(tile(v, *x) for x in links)) if links else EMPTY

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


def wd(d):
    return tdb.parse(at(d)).weekday()


class Google(Lanes):
    """self.w's plan is 14 loads (handle 9, strong alias miavale_x 4, weak alias miav 1), slotted on 2026-11-02's
    weekday; day() is a plain tick."""

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
                  mock.patch.dict(os.environ, TRACKER_UNCAPPED_TENANTS=self.t, BROWSERBASE_API_KEY=HOST_KEY,
                                  BROWSERBASE_PROJECT_ID=HOST_PROJECT)):
            p.start()
            self.addCleanup(p.stop)
        self.slot(2)

    def day(self, d, *packs):
        self.tick(d, *packs)

    def used(self, wid=None):
        sql = "SELECT COALESCE(SUM(used), 0) AS n FROM load_reservation WHERE unit = 'load'"
        return self.rows(sql + " AND watch_id = ?", wid)[0]["n"] if wid else self.rows(sql)[0]["n"]

    def assert_charged(self):
        self.assertEqual(len(self.pw.navs), self.used())
        self.assertEqual(self.rows("SELECT * FROM load_reservation WHERE state != 'settled'"), [])
        for _, body in self.bb.creates:
            self.assertNotIn("proxies", body)
        self.assertEqual({urlsplit(u).netloc for _, u in self.pw.navs} - {"www.google.com"}, set())

    def scan(self, wid=None, d=2):
        return self.rows("SELECT outcome FROM daily_scans WHERE watch_id = ? AND day = ?", wid or self.w,
                         f"2026-11-{d:02d}")[0]["outcome"]

    def slot(self, d, wid=None):
        with tdb.db() as c:
            c.execute("UPDATE watches SET weekly_slot = ? WHERE watch_id = ?", (wd(d), wid or self.w))

    def row(self, wid=None):
        return self.rows("SELECT * FROM watches WHERE watch_id = ?", wid or self.w)[0]

    def plan(self, wid=None):
        return tracker_plan.build(self.row(wid), "onlyfans")

    def navs(self):
        return [u for _, u in self.pw.navs]

    def full(self, wid=None):
        return self.lanes(wid)["google_full"]

    def full_state(self, wid):
        return self.rows("SELECT state, reason FROM lane_state WHERE lane = 'google_full' AND watch_id = ?", wid)

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


REAL_LOAD = tracker_serp.Session.load


class TestFullPass(Google):
    def test_session_settings_and_blocking_per_vertical(self):
        plan = self.plan()
        self.assertEqual(plan.loads, 14)
        web, img, vid = f"{SITE}/video/mia_vale-w1", f"{SITE}/gallery/mia_vale-i1", f"{SITE}/clip/mia_vale-v1"
        self.pw.links.update({("web", '"mia_vale"'): [(web, "Mia")], ("images", '"mia_vale"'): [(img, "Mia pics")],
                              ("videos", '"mia_vale"'): [(vid, "Mia clip")]})
        self.day(2)
        urls = [u for q in plan.queries for u in q.urls()]
        self.assertEqual(self.navs(), urls)
        self.assertEqual(len(self.bb.creates), 2)
        self.assertEqual({k for k, _ in self.bb.creates}, {HOST_KEY})
        self.assertEqual([b for _, b in self.bb.creates], [CREATE] * 2)
        self.assertEqual(len(self.bb.releases), 2)
        blocks = dict(zip((u for _, u in self.pw.navs), self.pw.blocks))
        for u in urls:
            self.assertIs(blocks[u].func, tracker_serp.block_assets)
            want = {"media", "font"} if "tbm=isch" in u else {"image", "media", "font", "stylesheet"}
            self.assertEqual(blocks[u].keywords, {"types": want}, u)
        self.assert_charged()
        self.assertEqual(self.used(), 14)
        self.assertEqual(self.lane_view(), {"cadence": "weekly", "state": "ok", "reason": None,
                                            "next_attempt_on": "2026-11-09", "trimmed": []})
        self.assertEqual(self.full()["last_success_at"], at(2))
        self.assertEqual(self.full_day(), [{"day": "2026-11-02", "outcome": "ok", "reason": None}])
        b = self.get(f"/v1/creators/{self.w}/leaks")[1]
        self.assertEqual(sorted((x["url"], x["kind"], x["sources"], x["found_on_first_scan"]) for x in b["leaks"]),
                         sorted([(u, "page", ["google_web"], True) for u in (web, img, vid)]
                                + [(img, "media", ["google_images"], True), (vid, "media", ["google_videos"], True)]))
        self.assertEqual({(r["url"], r["kind"]): json.loads(r["google_fields_json"]) for r in self.rows(
            "SELECT url, kind, google_fields_json FROM leaks")},
            {(web, "page"): [["web", "handle"]], (img, "page"): [["images", "handle"]],
             (vid, "page"): [["videos", "handle"]], (img, "media"): [["images", "handle"]],
             (vid, "media"): [["videos", "handle"]]})
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
        self.assertEqual(self.navs(), [])
        self.assertEqual((self.full()["state"], self.full(w2)["state"]), ("never", "never"))
        self.day(3)
        self.assertEqual(len(self.navs()), 14)
        self.assertEqual((self.full()["state"], self.full(w2)["state"]), ("ok", "never"))
        self.assertEqual(self.full()["next_attempt_on"], "2026-11-10")
        self.day(4)
        self.assertEqual(len(self.navs()), 14 + 9)
        self.assertEqual(self.full(w2)["state"], "ok")
        self.day(5)
        self.assertEqual(len(self.navs()), 23)
        self.assertEqual(self.full_day(), [{"day": "2026-11-03", "outcome": "ok", "reason": None}])
        self.assert_charged()

    def test_paused_and_missing_creds(self):
        with tdb.db() as c:
            c.execute("UPDATE watches SET paused = 1, paused_at = ? WHERE watch_id = ?", (at(2), self.w))
        self.day(2)
        self.assertEqual((self.pw.navs, self.full()["state"]), ([], "paused"))
        with tdb.db() as c:
            c.execute("UPDATE watches SET paused = 0, paused_at = NULL WHERE watch_id = ?", (self.w,))
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
            c.execute("UPDATE tracker_limits SET daily_loads = 9")
        self.day(2)
        cut = [q for q in self.plan().queries if q.field.startswith("alias:") or "mega.nz" in q.text
               or "site:t.me" in q.text]
        kept = [u for q in self.plan().queries if q not in cut for u in q.urls()]
        self.assertEqual(self.navs(), kept)
        self.assertEqual(len(kept), 7)
        self.assert_charged()
        self.assert_day_within_cap(2, 9)
        trimmed = [{"field": "alias:1", "value": "miav"}, {"field": "alias:0", "value": "miavale_x"}]
        self.assertEqual(self.lane_view(), {"cadence": "weekly", "state": "reduced", "reason": "cap_global",
                                            "next_attempt_on": "2026-11-03", "trimmed": trimmed})
        self.assertEqual(self.full_day(), [{"day": "2026-11-02", "outcome": "partial", "reason": "cap_global"}])
        self.assertEqual(self.scan(), "partial")
        carry = self.carry()
        self.assertEqual((carry["on"], carry["reason"], carry["first"]), ("2026-11-03", "cap_global", True))
        self.assertEqual(sorted(map(tuple, carry["pages"])), sorted((q.vertical, q.text, 0) for q in cut))

        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 5")
        self.day(3)
        carried = [u for u in self.navs()[7:]]
        self.assertEqual(sorted(carried), sorted(q.urls()[0] for q in cut if q.field == "handle"))
        self.assert_charged()
        self.assert_day_within_cap(3, 5)
        self.assertIsNone(self.carry())
        self.assertEqual(self.lane_view(), {"cadence": "weekly", "state": "reduced", "reason": "cap_global",
                                            "next_attempt_on": "2026-11-09", "trimmed": trimmed})
        self.assertEqual(self.full_day()[1], {"day": "2026-11-03", "outcome": "partial", "reason": "cap_global"})

        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 300")
        self.day(4)
        self.day(5)
        self.assertEqual(len(self.navs()), 9)
        self.assertEqual(len(self.full_day()), 2)
        self.assert_charged()

    def test_carry_runs_whole_inside_the_next_days_room(self):
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 9")
        self.day(2)
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 300")
        self.day(3)
        self.assertEqual(len(self.navs()), 14)
        self.assertEqual(sorted(self.navs()), sorted(u for q in self.plan().queries for u in q.urls()))
        self.assertEqual(self.lane_view(), {"cadence": "weekly", "state": "ok", "reason": None,
                                            "next_attempt_on": "2026-11-09", "trimmed": []})
        self.assertIsNone(self.carry())
        self.day(4)
        self.assertEqual(len(self.navs()), 14)
        self.assert_charged()

    def test_identity_grown_after_admission_trimmed_never_over_the_cap(self):
        with tdb.db() as c:
            c.execute("UPDATE watches SET plan_loads = 9, instagram = 'mia.vale.ig', x = 'miavale_xx' WHERE watch_id = ?",
                      (self.w,))
            c.execute("UPDATE tracker_limits SET daily_loads = 11")
        self.assertEqual(self.plan().loads, 19)
        self.day(2)
        self.assert_charged()
        self.assert_day_within_cap(2, 11)
        self.assertEqual(len(self.navs()), 9)
        self.assertEqual([t["field"] for t in self.full()["trimmed"]], ["alias:1", "alias:0", "x", "instagram"])

    def test_month_cap_waits_until_the_1st(self):
        with tdb.db() as c:
            c.execute("UPDATE tenants SET month_loads = 0")
        self.day(2)
        self.assertEqual(self.navs(), [])
        self.assertEqual(self.lane_view(), {"cadence": "weekly", "state": "waiting", "reason": "cap_tenant_month",
                                            "next_attempt_on": "2026-12-01", "trimmed": []})
        self.assertEqual(self.full_day(), [{"day": "2026-11-02", "outcome": "partial", "reason": "cap_tenant_month"}])
        carry = self.carry()
        self.assertEqual((carry["on"], carry["reason"], len(carry["pages"])), ("2026-12-01", "cap_tenant_month", 14))
        for d in (3, 4, 30):
            self.day(d)
        self.assertEqual(self.navs(), [])
        self.assertEqual(self.full()["next_attempt_on"], "2026-12-01")
        with tdb.db() as c:
            c.execute("UPDATE tenants SET month_loads = 300")
        tracker_scheduler.daily_pass("2026-12-01T05:00:00Z")
        self.assertEqual(len(self.navs()), 14)
        self.assertIsNone(self.carry())
        self.clock("2026-12-01T05:00:00Z")
        self.assertEqual({k: self.full()[k] for k in ("state", "next_attempt_on")},
                         {"state": "ok", "next_attempt_on": "2026-12-07"})
        self.assert_charged()

    def test_month_cap_partial_cut_waits_until_the_1st(self):
        with tdb.db() as c:
            c.execute("UPDATE tenants SET month_loads = 7")
        self.day(2)
        self.assertEqual(len(self.navs()), 5)
        f = self.full()
        self.assertEqual((f["state"], f["reason"], f["next_attempt_on"]), ("reduced", "cap_tenant_month", "2026-12-01"))
        self.assertEqual(self.carry()["on"], "2026-12-01")
        self.assert_charged()

    def test_wall_retries_once_and_a_second_wall_ends_the_query_incomplete(self):
        self.pw.script = ["wall", None, "wall", "wall"]
        self.day(2)
        urls = [u for q in self.plan().queries for u in q.urls()]
        self.assertEqual(self.navs(), [urls[0], urls[0], urls[1], urls[1], *urls[2:]])
        self.assertEqual(len(self.pw.sessions()), 3 + 1)
        self.assert_charged()
        self.assertEqual(self.used(), 16)
        self.assertEqual(self.rows("SELECT held, used FROM load_reservation"), [{"held": 16, "used": 16}])
        f = self.full()
        self.assertEqual((f["state"], f["reason"], f["last_success_at"]), ("reduced", "google_failed", at(2)))
        self.assertEqual(self.full_day(), [{"day": "2026-11-02", "outcome": "partial", "reason": "google_failed"}])
        self.assertEqual(self.rows("SELECT page FROM serp_cache WHERE text = '\"mia_vale\"' AND vertical = 'web'"),
                         [{"page": 0}])
        self.assertIsNone(self.carry())

    def test_wall_with_the_hold_used_up_ends_incomplete_one_navigation(self):
        self.pw.script = ["wall", None, None, None, "wall"] + [None] * 10 + ["wall"]
        self.day(2)
        urls = [u for q in self.plan().queries for u in q.urls()]
        self.assertEqual(self.navs(), [urls[0], urls[0], urls[1], urls[2], urls[3], urls[3], *urls[4:]])
        self.assert_charged()
        self.assertEqual(self.rows("SELECT held, used FROM load_reservation"), [{"held": 16, "used": 16}])
        self.assertEqual((self.full()["state"], self.full()["reason"]), ("reduced", "google_failed"))

    def test_breaker_failed_create_ends_the_pass(self):
        self.day(2)
        n = len(self.bb.creates)
        self.slot(4)
        self.bb.fail = True
        self.day(4)
        self.assertEqual(len(self.bb.creates), n + 1)
        self.assertEqual(len(self.pw.navs), 14)
        self.assert_charged()
        self.assertEqual((self.full()["state"], self.full()["reason"]), ("reduced", "google_failed"))

    def test_breaker_carries_across_the_ticks_weekly_watches(self):
        w2 = self.watch(self.t, username="rowan_ash", account_id="acc-r", weekly_slot=wd(2))
        self.pw.script = ["wall"] * 100
        self.day(2)
        self.assert_charged()
        self.assertEqual(sorted(self.used(w) for w in (self.w, w2)), [0, 6])
        self.assertEqual({(self.full(w)["state"], self.full(w)["reason"]) for w in (self.w, w2)},
                         {("reduced", "google_failed")})
        self.assertEqual(self.rows("SELECT * FROM serp_cache"), [])

    def test_empty_shell_page_is_incomplete(self):
        self.pw.script = ["shell"]
        self.day(2)
        self.assert_charged()
        self.assertEqual(len(self.navs()), 14)
        self.assertEqual((self.full()["state"], self.full()["reason"]), ("reduced", "google_failed"))
        cached = {(r["vertical"], r["text"], r["page"], r["since"]) for r in self.rows("SELECT * FROM serp_cache")}
        self.assertNotIn(("web", '"mia_vale"', 0, ""), cached)
        self.assertIn(("web", '"mia_vale"', 1, ""), cached)
        self.assertEqual(len(cached), 13)

    def test_crashed_slot_scan_reruns_once_after_the_lease(self):
        with tdb.db() as c:
            c.execute("INSERT INTO daily_scans (watch_id, day, started_at, trigger) VALUES (?, '2026-11-02', ?, 'weekly')",
                      (self.w, at(2)))
        tracker_scheduler.daily_pass(tdb.plus(at(2), hours=1))
        self.assertEqual((self.navs(), self.full()["state"]), ([], "never"))
        tracker_scheduler.daily_pass(tdb.plus(at(2), hours=3))
        self.assertEqual(len(self.navs()), 14)
        tracker_scheduler.daily_pass(tdb.plus(at(2), hours=6))
        self.assertEqual(len(self.navs()), 14)
        self.assertEqual(self.full_day(), [{"day": "2026-11-02", "outcome": "ok", "reason": None}])
        self.assertEqual(self.rows("SELECT trigger, outcome FROM daily_scans"), [{"trigger": "weekly", "outcome": "ok"}])
        self.assert_charged()

    def test_watch_seeded_today_skips_its_slot_scan(self):
        import tracker_seed
        w2 = self.watch(self.t, username="rowan_ash", account_id="acc-r", seeded=False, weekly_slot=wd(2))
        cand = {"google": [], "mega": [], "errors": []}
        with mock.patch.object(tracker_seed, "_quick_candidates", return_value=lambda *a: cand):
            self.day(2)
        lanes = self.lanes(w2)
        self.assertEqual({k: v["state"] for k, v in lanes.items()},
                         {"origin_probe": "ok", "mega_lookup": "never", "listing_recheck": "never", "google_full": "never",
                          "registry_crawl": "never"})
        self.assertEqual(lanes["origin_probe"]["next_attempt_on"], "2026-11-09")
        self.assertEqual(sum("rowan_ash" in u for u in self.navs()), 0)
        self.assertEqual(self.rows("SELECT trigger FROM daily_scans WHERE watch_id = ?", w2), [{"trigger": "seed"}])
        self.day(9)
        self.assertEqual(self.full(w2)["state"], "ok")
        self.assertEqual(sum("rowan_ash" in u for u in self.navs()), self.plan(w2).loads)
        self.assert_charged()

    def test_trimmed_slot_keeps_first_scan_for_the_carry(self):
        mega_hit, later = f"{SITE}/video/mia_vale-c1", f"{SITE}/video/mia_vale-c2"
        self.pw.links[("web", '"mia_vale" mega.nz')] = [(mega_hit, "Mia")]
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 9")
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
        self.pw.script = ["wall", "wall"]
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
            c.execute("UPDATE tracker_limits SET daily_loads = 9")
        self.day(2)
        carry = self.carry()
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 300")
        with mock.patch.object(tracker_lanes.tracker_judge, "admit_hit", side_effect=RuntimeError("boom")):
            self.day(3)
        self.assertEqual(self.carry(), carry)
        self.assertEqual(self.full()["state"], "failed")
        n = len(self.navs())
        tracker_scheduler.daily_pass(tdb.plus(at(3), hours=1))
        self.assertEqual(len(self.navs()), n)
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
        with mock.patch.dict(os.environ, TRACKER_UNCAPPED_TENANTS=f"{self.t},{t2}"):
            self.day(2)
            self.assertEqual(len(self.navs()), 14)
            self.assert_charged()
            self.assertEqual((self.used(self.w), self.used(w2)), (14, 0))
            self.assertEqual(self.lanes_of(w2, key2)["google_full"]["state"], "ok")
            b = self.get(f"/v1/creators/{w2}/leaks", key2)[1]
            self.assertEqual(sorted((x["url"], x["kind"]) for x in b["leaks"]), [(hit, "media"), (hit, "page")])
        self.assertEqual(self.rows("SELECT google_fields_json FROM leaks WHERE watch_id = ?", w2),
                         [{"google_fields_json": '[["images","alias:miavalex"]]'}] * 2)


class TestEveryTenant(Google):
    """The machinery the retired fresh pass shared, on the full pass (ticket 81)."""

    def test_tenant_on_no_list_runs_on_its_own_creds_under_its_caps(self):
        self.clock(tdb.plus(Base.T0, seconds=1))
        t2, t3 = self.tenant("Agency B"), self.tenant("Agency C")
        with tdb.db() as c:
            c.execute("UPDATE tenants SET bb_key = ?, bb_project = 'prj-b', month_loads = 5 WHERE tenant_id = ?",
                      (OWN_KEY, t2))
        w2 = self.watch(t2, username="rowan_ash", account_id="acc-b", weekly_slot=wd(2))
        w3 = self.watch(t3, username="juniper_lee", account_id="acc-c", weekly_slot=wd(2))
        self.day(2)
        self.assertEqual([(k, b["projectId"]) for k, b in self.bb.creates],
                         [(HOST_KEY, HOST_PROJECT)] * 2 + [(OWN_KEY, "prj-b")])
        self.assertEqual(len(self.navs()), 14 + self.used(w2))
        self.assertLessEqual(self.used(w2), 5)
        self.assertEqual(self.used(w3), 0)
        self.assertEqual(self.full_state(w2), [{"state": "reduced", "reason": "cap_tenant_month"}])
        self.assertEqual(self.full_state(w3), [{"state": "waiting", "reason": "no_browserbase_key"}])
        self.assertEqual(self.full()["state"], "ok")
        self.assert_charged()

    def test_own_creds_from_the_cli_never_mix_in_a_session(self):
        self.clock(tdb.plus(Base.T0, seconds=1))
        t2 = self.tenant("Agency B")
        w2 = self.watch(t2, username="rowan_ash", account_id="acc-b", weekly_slot=wd(2))
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
        with mock.patch.object(tracker_probe, "log", side_effect=lambda m: log.write(m + "\n")):
            self.pw.script = ["fail"] * 6
            self.day(2)
        self.assertEqual([(k, b["projectId"]) for k, b in self.bb.creates],
                         [(HOST_KEY, HOST_PROJECT)] * 3 + [(OWN_KEY, "prj-b")] * 3)
        urls = lambda w: [u for q in self.plan(w).queries for u in q.urls()]
        self.assertEqual(self.navs(), urls(self.w)[:3] + urls(w2)[:3])
        self.assertEqual(len(self.pw.sessions()), 6)
        self.assertNotIn(OWN_KEY, log.getvalue())
        self.assertNotIn(HOST_KEY, log.getvalue())
        self.assert_charged()

    def test_failed_loads_no_other_engine(self):
        self.leak(self.w, f"{SITE}/models/mia_vale/")
        self.pw.script = ["fail"] * 100
        with mock.patch.object(cse_scanner, "_call", side_effect=AssertionError("CSE called")) as cse:
            self.day(2)
        cse.assert_not_called()
        self.assertEqual(len(self.navs()), 3)
        self.assert_charged()
        self.assertTrue(all(not re.search(r"google|bing|duckduckgo|serper", u) for u in tracker_stub_fetch.CALLS))
        self.assertEqual((self.full()["state"], self.full()["reason"]), ("reduced", "google_failed"))
        self.assertEqual(self.full_day(), [{"day": "2026-11-02", "outcome": "partial", "reason": "google_failed"}])
        self.assertEqual(self.scan(), "partial")
        self.assertEqual(self.lanes()["listing_recheck"]["state"], "ok")
        self.assertEqual(self.get(f"/v1/creators/{self.w}")[1]["this_week"]["state"], "coverage_reduced")

    def test_over_the_cap_full_waits_while_zero_cost_lanes_run(self):
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
        f = lanes["google_full"]
        self.assertEqual((f["state"], f["reason"], f["next_attempt_on"], f["last_success_at"]),
                         ("waiting", "cap_global", "2026-11-03", None))
        self.assertEqual(self.full_day(), [{"day": "2026-11-02", "outcome": "partial", "reason": "cap_global"}])
        self.assertEqual(self.rows("SELECT paused FROM watches WHERE watch_id = ?", self.w), [{"paused": 0}])
        self.assertEqual(self.scan(), "partial")
        one = self.get(f"/v1/creators/{self.w}")[1]
        self.assertEqual((one["paused"], one["this_week"]["state"]), (False, "partial"))

        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 300")
            c.execute("UPDATE tenants SET month_loads = 0")
        self.day(3)
        f = self.full()
        self.assertEqual((f["state"], f["reason"], f["next_attempt_on"]), ("waiting", "cap_tenant_month", "2026-11-09"))
        self.assertIsNone(self.carry())
        self.assertEqual(self.pw.navs, [])

    def test_broken_playwright_bills_nothing(self):
        with mock.patch.object(tracker_serp, "_playwright", side_effect=ImportError("No module named 'playwright'")):
            self.day(2)
        self.assertEqual((self.pw.navs, self.bb.releases), ([], []))
        self.assertEqual(self.used(), 0)
        self.assert_charged()
        self.assertEqual(len(self.rows("SELECT * FROM load_reservation")), 1)
        self.assertEqual((self.full()["state"], self.full()["reason"]), ("reduced", "google_failed"))

    def test_page_prep_failure_burns_no_unit(self):
        self.pw.page_fail = True
        self.day(2)
        self.assertEqual((self.pw.navs, self.used()), ([], 0))
        self.assert_charged()
        self.assertEqual(self.full_day(), [{"day": "2026-11-02", "outcome": "partial", "reason": "google_failed"}])

    def test_session_rotates_by_age(self):
        t = [1000.0]
        with mock.patch.object(tracker_serp, "_clock", lambda: t[0]), \
                mock.patch.object(tracker_serp.Session, "load", autospec=True,
                                  side_effect=lambda sess, page, url: (t.__setitem__(0, t[0] + 100),
                                                                       REAL_LOAD(sess, page, url))[1]):
            self.day(2)
        self.assertLess(tracker_serp.ROTATE_S, tracker_serp.SESSION_S)
        per = -(-tracker_serp.ROTATE_S // 100)
        self.assertEqual(len(self.navs()), 14)
        self.assertEqual([sum(1 for c, _ in self.pw.navs if c == s) for s in self.pw.sessions()],
                         [per] * (14 // per) + [14 % per] * bool(14 % per))
        self.assert_charged()
        self.assertEqual(self.full()["state"], "ok")

    def test_missing_tenant_row_skips_only_that_watch(self):
        t2 = self.tenant("Agency B")
        w2 = self.watch(t2, username="rowan_ash", account_id="acc-b", weekly_slot=wd(2))
        with tdb.db() as c:
            c.execute("DELETE FROM tenants WHERE tenant_id = ?", (t2,))
        self.day(2)
        self.assertEqual(self.navs(), [u for q in self.plan().queries for u in q.urls()])
        self.assertEqual(self.rows("SELECT watch_id, state FROM lane_state WHERE lane = 'google_full'"),
                         [{"watch_id": self.w, "state": "ok"}])
        self.assertEqual(self.full_state(w2), [])
        self.assert_charged()

    def test_gone_records_nothing(self):
        gone = tracker_lanes.tracker_budget.Refused("gone", None)
        with mock.patch.object(tracker_lanes.tracker_budget, "reserve", return_value=gone):
            self.day(2)
        self.assertEqual((self.pw.navs, self.bb.creates), ([], []))
        self.assertEqual(self.full_state(self.w), [])
        self.assertEqual(self.full_day(), [])

    def test_no_fresh_pass_left(self):
        self.day(2)
        self.day(3)
        self.assertEqual(len(self.navs()), 14)
        self.assertFalse(any("qdr" in u for u in self.navs()))
        for t in ("lane_state", "lane_day"):
            self.assertEqual(self.rows(f"SELECT lane FROM {t} WHERE lane = 'google_fresh'"), [])
        self.assertFalse({"FRESH", "FRESH_HOLD", "run_fresh_batch"} & set(vars(tracker_lanes)))
        self.assertFalse(hasattr(tracker_plan, "fresh"))

    def test_no_cse_or_serper_in_the_phase_2_tracker_modules(self):
        mods = ("tracker_plan", "tracker_budget", "tracker_admission", "tracker_lanes", "tracker_judge", "tracker_serp")
        for f in (os.path.join(os.path.dirname(tracker_lanes.__file__), m + ".py") for m in mods):
            with open(f, encoding="utf-8") as fh:
                self.assertIsNone(re.search(r"cse_scanner|serper|customsearch", fh.read(), re.I), f)


class TestVisibility(Google):
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
        self.pw.script = [None] * sum(q.pages for q in qs[:alias_img]) + ["fail"]
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
            c.execute("UPDATE tracker_limits SET daily_loads = 9")
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
            c.execute("UPDATE tenants SET month_loads = 0")
        self.day(2)
        self.assertEqual((self.full()["state"], self.full()["reason"]), ("waiting", "cap_tenant_month"))
        self.assertEqual(self.vis(lid), [True])
        self.assertEqual(self.fields(lid), [["images", "alias:miavalex"]])
        with tdb.db() as c:
            c.execute("UPDATE tenants SET month_loads = 1000")
        self.slot(4)
        self.pw.script = ["fail"] * 100
        self.day(4)
        self.assertEqual((self.full()["state"], self.full()["reason"]), ("reduced", "google_failed"))
        self.assertEqual(self.vis(lid), [True])
        self.slot(6)
        self.pw.script = []
        self.day(6)
        self.assertEqual(self.vis(lid), [True, None])
        self.assert_charged()

    def test_shell_page_never_counts_toward_false(self):
        lid = self.known([["web", "handle"]])
        self.pw.script = [None] * 8 + ["shell"]
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
        self.pw.script = [None] + ["wall"] * 100
        self.day(2)
        self.assertEqual(self.rows("SELECT google_fields_json FROM leaks WHERE url = ?", hit),
                         [{"google_fields_json": '[["web","handle"]]'}])
        self.assertEqual((self.vis(only_alias), self.vis(handle)), ([True], [True]))
        self.assertEqual(self.fields(only_alias), [["images", "alias:miavalex"]])
        self.slot(4)
        self.pw.script = []
        self.day(4)
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

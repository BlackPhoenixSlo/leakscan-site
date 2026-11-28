"""Manual refresh (cadence slice A ticket 82): POST /v1/watches/{id}/refresh over HTTP, the queue on watches, and the
scheduler tick that runs it as a `refresh` scan at any hour under the normal reservations (test_tracker_google's
Browserbase stub and fake Playwright). 2026-11-02 is a Monday, self.w's slot day. Fictional creators only."""
import http.client
import importlib
import json
from unittest import mock

from tracker_fixture import tdb, tracker_scheduler
from test_tracker_google import Google, SITE
import tracker_api
import tracker_lanes


def ts(d, hm):
    return f"2026-11-{d:02d}T{hm}:00Z"


class Refresh(Google):
    def post(self, wid=None, key=None, at=None):
        if at:
            self.clock(at)
        c = http.client.HTTPConnection("127.0.0.1", self.api.server_address[1], timeout=10)
        c.request("POST", f"/v1/watches/{wid or self.w}/refresh", body=b'{"ignored": true}',
                  headers={"Authorization": f"Bearer {key or self.key}", "Content-Type": "application/json"})
        r = c.getresponse()
        body = r.read()
        c.close()
        self.last_headers = dict(r.getheaders())
        return r.status, json.loads(body) if body else None

    def queued(self, wid=None):
        return self.rows("SELECT refresh_queued_at FROM watches WHERE watch_id = ?", wid or self.w)[0]["refresh_queued_at"]

    def scans(self, wid=None):
        return [(r["day"], r["trigger"], r["outcome"]) for r in self.rows(
            "SELECT day, trigger, outcome FROM daily_scans WHERE watch_id = ? ORDER BY day", wid or self.w)]

    def run_at(self, when):
        out = tracker_scheduler.daily_pass(when)
        self.clock(when)
        return out


class TestRoute(Refresh):
    def test_202_scan_on_the_next_tick_same_queued_at_mid_scan_429_then_202_at_24h(self):
        st, b = self.post(at=ts(4, "12:59"))
        self.assertEqual((st, b), (202, {"watch_id": self.w, "queued_at": ts(4, "12:59"),
                                         "next_refresh_at": ts(5, "12:59")}))
        self.assertEqual(self.queued(), ts(4, "12:59"))
        self.assertEqual(self.post(), (202, b))
        mid, real = [], tracker_lanes.run_scan

        def scan(*a):
            mid.append(self.post())
            return real(*a)
        with mock.patch.object(tracker_lanes, "run_scan", side_effect=scan):
            out = self.run_at(ts(4, "13:00"))
        self.assertEqual((out["refreshed"], out["weekly"]), (1, 0))
        self.assertEqual(mid, [(202, {"watch_id": self.w, "queued_at": ts(4, "12:59"),
                                      "next_refresh_at": ts(5, "13:00")})])
        self.assertEqual(self.scans(), [("2026-11-04", "refresh", "ok")])
        self.assertIsNone(self.queued())
        self.assertEqual(len(self.navs()), 14)
        self.assert_charged()
        self.assertEqual({k: v["last_attempt_at"] for k, v in self.lanes().items() if k != "registry_crawl"},
                         dict.fromkeys(("origin_probe", "mega_lookup", "listing_recheck", "google_full"), ts(4, "13:00")))
        one = self.get(f"/v1/creators/{self.w}")[1]
        self.assertEqual((one["next_refresh_at"], one["next_check_at"]), (ts(5, "13:00"), ts(9, "04:00")))

        st, b = self.post(at=ts(5, "12:00"))
        self.assertEqual((st, b), (429, {"error": "refresh_cooldown", "retry_after_s": 3600,
                                         "next_refresh_at": ts(5, "13:00")}))
        self.assertEqual(self.last_headers["Retry-After"], "3600")
        self.assertIsNone(self.queued())
        self.assertEqual(self.post(at="2026-11-05T12:59:59Z")[1]["retry_after_s"], 1)
        st, b = self.post(at=ts(5, "13:00"))
        self.assertEqual((st, b["queued_at"], b["next_refresh_at"]), (202, ts(5, "13:00"), ts(6, "13:00")))
        self.assertEqual(self.queued(), ts(5, "13:00"))

    def test_refresh_runs_before_daily_at(self):
        self.post(at=ts(4, "01:30"))
        out = self.run_at(ts(4, "01:31"))
        self.assertEqual(out["refreshed"], 1)
        self.assertEqual(self.scans(), [("2026-11-04", "refresh", "ok")])

    def test_paused_409_deleted_410_other_tenant_404_bad_key_401_nothing_queued(self):
        t2 = self.tenant("Agency B")
        key2 = self.issue(t2)
        w2 = self.watch(t2, username="rowan_ash", account_id="acc-b")
        paused = self.watch(self.t, username="juniper_lee", account_id="acc-p", paused=True)
        gone = self.watch(self.t, username="sable_quinn", account_id="acc-g", paused=True)
        with tdb.db() as c:
            c.execute("UPDATE watches SET deleted_at = ?, purge_after = ? WHERE watch_id = ?", (ts(2, "05:00"),
                                                                                                   ts(9, "05:00"), gone))
        self.assertEqual(self.post(w2), (404, {"error": "not_found"}))
        self.assertEqual(self.post("w_nope"), (404, {"error": "not_found"}))
        self.assertEqual(self.post(paused), (409, {"error": "watch_paused"}))
        self.assertEqual(self.post(gone), (410, {"error": "watch_deleted"}))
        self.assertEqual(self.post(key="lt_bad")[0], 401)
        self.assertEqual(self.rows("SELECT watch_id FROM watches WHERE refresh_queued_at IS NOT NULL"), [])
        self.assertEqual(self.post(w2, key2)[0], 202)
        self.queue(paused)
        self.assertEqual(self.post(paused), (409, {"error": "watch_paused"}))
        self.run_at(ts(2, "06:00"))
        self.assertEqual((self.queued(paused), self.scans(paused)), (None, []))

    def queue(self, wid):
        with tdb.db() as c:
            c.execute("UPDATE watches SET refresh_queued_at = ? WHERE watch_id = ?", (tdb.now(), wid))

    def test_seed_in_flight_answers_202_with_its_start(self):
        with tdb.db() as c:
            c.execute("UPDATE watches SET seeded_at = NULL WHERE watch_id = ?", (self.w,))
            c.execute("INSERT INTO daily_scans (watch_id, day, started_at, trigger) VALUES (?, '2026-11-02', ?, 'seed')",
                      (self.w, ts(2, "05:00")))
        st, b = self.post(at=ts(2, "05:30"))
        self.assertEqual((st, b), (202, {"watch_id": self.w, "queued_at": ts(2, "05:00"),
                                         "next_refresh_at": ts(3, "05:00")}))
        self.assertIsNone(self.queued())

    def test_survives_a_restart(self):
        self.assertEqual(self.post(at=ts(4, "12:00"))[0], 202)
        importlib.reload(tracker_scheduler)
        tdb.init()
        out = self.run_at(ts(4, "12:01"))
        self.assertEqual(out["refreshed"], 1)
        self.assertEqual(self.scans(), [("2026-11-04", "refresh", "ok")])

    def test_logs_ids_and_counts_only(self):
        with mock.patch.object(tracker_api, "_log") as log:
            self.post(at=ts(4, "12:00"))
        self.assertEqual(log.call_args_list, [mock.call(f"refresh queued {self.w}")])
        self.assertNotIn(self.key, str(log.call_args_list))
        self.assertNotIn("mia_vale", str(log.call_args_list))


class TestScan(Refresh):
    def test_cap_tenant_month_finishes_partial_lanes_waiting_cooldown_kept(self):
        with tdb.db() as c:
            c.execute("UPDATE tenants SET month_loads = 0")
        self.post(at=ts(4, "13:00"))
        self.run_at(ts(4, "13:01"))
        self.assertEqual(self.scans(), [("2026-11-04", "refresh", "partial")])
        f = self.full()
        self.assertEqual((f["state"], f["reason"], f["next_attempt_on"]), ("waiting", "cap_tenant_month", "2026-12-01"))
        self.assertEqual((self.pw.navs, self.bb.creates), ([], []))
        self.assertEqual(self.get(f"/v1/creators/{self.w}")[1]["this_week"]["state"], "partial")
        st, b = self.post(at=ts(4, "18:00"))
        self.assertEqual((st, b["next_refresh_at"]), (429, ts(5, "13:01")))

    def test_refresh_absorbs_a_pending_carry(self):
        hit = f"{SITE}/video/mia_vale-c9"
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 9")
        self.run_at(ts(2, "04:00"))
        cut = {tuple(p) for p in self.carry()["pages"]}
        self.assertEqual((len(self.navs()), self.carry()["on"]), (7, "2026-11-03"))
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 300")
        self.pw.links[("web", '"mia_vale" mega.nz')] = [(hit, "Mia")]
        self.assertEqual(self.post(at=ts(3, "04:00"))[0], 202)
        with mock.patch.object(tracker_lanes, "run_carry", wraps=tracker_lanes.run_carry) as carry:
            out = self.run_at(ts(3, "04:00"))
        self.assertEqual(out["refreshed"], 1)
        carry.assert_not_called()
        self.assertEqual(self.scans(), [("2026-11-02", "weekly", "partial"), ("2026-11-03", "refresh", "ok")])
        self.assertIsNone(self.carry())
        self.assertEqual(len(self.navs()), 7 + 14)
        cut_urls = {u for q in tracker_lanes._pages(self.plan().queries) if tracker_lanes._page_key(q) in cut
                    for u in q.urls()}
        self.assertLessEqual(cut_urls, set(self.navs()[7:]))
        self.assertEqual(self.full_day()[-1], {"day": "2026-11-03", "outcome": "ok", "reason": None})
        leaks = {x["url"]: x["found_on_first_scan"] for x in self.get(f"/v1/creators/{self.w}/leaks")[1]["leaks"]}
        self.assertEqual(leaks[hit], True)
        self.run_at(ts(3, "05:00"))
        self.assertEqual(len(self.navs()), 21)
        self.assert_charged()


if __name__ == "__main__":
    import unittest
    unittest.main()

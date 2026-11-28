"""Operator scan (tracker_cli scan): a full scan now of a tenant's live seeded watches, past the weekly slot and the
refresh cooldown, under the same caps, owning today's daily_scans row (test_tracker_google's Browserbase stub and fake
Playwright, the Mega index stub). 2026-11-02 is a Monday, self.w's slot day. Fictional creators only."""
import contextlib
import http.client
import io

from tracker_fixture import tdb, tracker_scheduler
from test_tracker_lanes import pack
from test_tracker_media import IMG, THUMB, Media
import tracker_cli
import tracker_lanes


def ts(d, hm):
    return f"2026-11-{d:02d}T{hm}:00Z"


class ScanNow(Media):
    def setUp(self):
        super().setUp()
        self.seeded_today(self.w)

    def seeded_today(self, wid, day=2, finished=True):
        with tdb.db() as c:
            c.execute("INSERT INTO daily_scans (watch_id, day, started_at, finished_at, outcome, trigger) "
                      "VALUES (?,?,?,?,?,'seed')", (wid, ts(day, "01:00")[:10], ts(day, "01:00"),
                                                    ts(day, "01:05") if finished else None, "ok" if finished else None))

    def cli(self, when, *args):
        self.clock(when)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            tracker_cli.main(["scan", "--tenant", self.t, *args])
        return out.getvalue().splitlines()

    def scans(self, wid=None):
        return [(r["day"], r["trigger"], r["outcome"]) for r in self.rows(
            "SELECT day, trigger, outcome FROM daily_scans WHERE watch_id = ? ORDER BY day", wid or self.w)]


class TestScanNow(ScanNow):
    def test_all_lanes_run_on_a_watch_seeded_today_media_and_thumb_stored(self):
        self.pw.links[("images", '"mia_vale"')] = [(IMG, "Mia pics", THUMB)]
        self.index(pack(1))
        lines = self.cli(ts(2, "07:09"))
        n = len(self.pw.navs)
        self.assertEqual(lines, [f"{self.w}\tscan=ok\torigin_probe=ok\tmega_lookup=ok\tlisting_recheck=ok\t"
                                 f"google_full=ok\tloads={n}\tmedia_new=1\tthumbs=1",
                                 "total\tgoogle_full=ok:1\tlisting_recheck=ok:1\tmega_lookup=ok:1\torigin_probe=ok:1"])
        self.assertEqual(n, 14)
        self.assert_charged()
        self.assertEqual(self.scans(), [("2026-11-02", "refresh", "ok")])
        self.assertEqual({k: v["state"] for k, v in self.lanes().items()},
                         {"origin_probe": "ok", "mega_lookup": "ok", "listing_recheck": "ok", "google_full": "ok",
                          "registry_crawl": "never"})
        self.assertIsNotNone(self.items()[(IMG, "media")]["preview"])
        self.assertNotIn("mia_vale", "\n".join(lines))

    def test_scheduler_never_reruns_it_today_cooldown_kept_next_weeks_slot_runs(self):
        self.cli(ts(2, "07:09"))
        n = len(self.pw.navs)
        for when in (ts(2, "07:30"), ts(2, "23:59")):
            self.clock(when)
            self.assertEqual(self.post()[0], 429)
            out = tracker_scheduler.daily_pass(when)
            self.assertEqual((out["weekly"], out["refreshed"], len(self.pw.navs)), (0, 0, n), when)
        self.assertEqual(self.scans(), [("2026-11-02", "refresh", "ok")])
        one = self.get(f"/v1/creators/{self.w}")[1]
        self.assertEqual((one["next_refresh_at"], one["next_check_at"]), (ts(3, "07:09"), ts(9, "04:00")))
        out = tracker_scheduler.daily_pass(ts(9, "04:00"))
        self.assertEqual(out["weekly"], 1)
        self.assertEqual(self.scans(), [("2026-11-02", "refresh", "ok"), ("2026-11-09", "weekly", "ok")])
        self.assertEqual(len(self.pw.navs), 2 * n)

    def post(self):
        c = http.client.HTTPConnection("127.0.0.1", self.api.server_address[1], timeout=10)
        c.request("POST", f"/v1/watches/{self.w}/refresh", headers={"Authorization": f"Bearer {self.key}"})
        r = c.getresponse()
        r.read()
        c.close()
        return r.status, r

    def test_caps_still_refuse(self):
        for sql, reason in (("UPDATE tracker_limits SET daily_loads = 0", "cap_global"),
                            ("UPDATE tenants SET month_loads = 0", "cap_tenant_month")):
            with self.subTest(reason):
                with tdb.db() as c:
                    c.execute("UPDATE tracker_limits SET daily_loads = 300")
                    c.execute("UPDATE tenants SET month_loads = 1000")
                    c.execute(sql)
                line = self.cli(ts(2, "07:09"))[0]
                self.assertIn("\tgoogle_full=waiting\tloads=0\t", line)
                self.assertEqual((self.full()["reason"], self.pw.navs, self.bb.creates), (reason, [], []))
                self.assertEqual(self.scans(), [("2026-11-02", "refresh", "partial")])

    def test_paused_deleted_unseeded_skipped_in_flight_refused_crashed_row_taken_over(self):
        paused = self.watch(self.t, username="juniper_lee", account_id="w_s1", watch_id="w_s1", paused=True)
        gone = self.watch(self.t, username="sable_quinn", account_id="w_s2", watch_id="w_s2")
        fresh = self.watch(self.t, username="rowan_ash", account_id="w_s3", watch_id="w_s3", seeded=False)
        busy = self.watch(self.t, username="wren_hale", account_id="w_s4", watch_id="w_s4")
        crashed = self.watch(self.t, username="ivy_north", account_id="w_s5", watch_id="w_s5")
        with tdb.db() as c:
            c.execute("UPDATE watches SET deleted_at = ? WHERE watch_id = ?", (ts(2, "01:00"), gone))
            c.execute("INSERT INTO daily_scans (watch_id, day, started_at, trigger) VALUES (?, '2026-11-02', ?, 'weekly')",
                      (busy, ts(2, "07:00")))
        self.seeded_today(crashed, finished=False)
        lines = self.cli(ts(2, "07:09"), *(f"--watch={w}" for w in (paused, gone, fresh, busy, "w_nope", crashed)))
        self.assertEqual(lines[:5], [f"{paused}\tskipped=paused", f"{gone}\tskipped=deleted",
                                     f"{fresh}\tskipped=unseeded", f"{busy}\tskipped=in_flight", "w_nope\tskipped=unknown"])
        self.assertTrue(lines[5].startswith(f"{crashed}\tscan=ok\t"), lines[5])
        self.assertEqual(len(lines), 7)
        for w in (paused, gone, fresh):
            self.assertEqual(self.scans(w), [])
        self.assertEqual(self.scans(busy), [("2026-11-02", "weekly", None)])
        self.assertEqual(self.scans(crashed), [("2026-11-02", "refresh", "ok")])
        self.assertEqual(self.scans(), [("2026-11-02", "seed", "ok")])

    def test_a_carry_waits_while_a_scan_of_its_watch_is_in_flight(self):
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 9")
        self.cli(ts(2, "07:09"))
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = 300")
            c.execute("UPDATE daily_scans SET finished_at = NULL WHERE watch_id = ?", (self.w,))
        self.clock(ts(3, "05:00"))
        self.assertEqual(self.carry()["on"], "2026-11-03")
        self.assertFalse(tracker_lanes.run_carry(self.w, "2026-11-03", {}))
        with tdb.db() as c:
            c.execute("UPDATE daily_scans SET finished_at = ? WHERE watch_id = ?", (ts(2, "07:10"), self.w))
        self.assertTrue(tracker_lanes.run_carry(self.w, "2026-11-03", {}))


if __name__ == "__main__":
    import unittest
    unittest.main()

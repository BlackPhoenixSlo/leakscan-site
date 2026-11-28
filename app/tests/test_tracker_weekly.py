"""Weekly cadence (cadence slice A tickets 81, 83): the scheduler tick's slot scans, the 24 h slot guard, carries and
dead-streak confirms between slots, the scan claim's triggers, and `this_week` / `next_check_at` on the Creator reads.
2026-11-02 is a Monday; Lanes' Mega index and listing stubs, no Browserbase creds. Fictional creators only."""
import http.client
import json
from datetime import timedelta
from unittest import mock

from tracker_fixture import tdb, tracker_scheduler, tracker_stub_fetch
from test_tracker_lanes import SITE, Lanes, at, pack
import tracker_lanes
import tracker_seed

MON, TUE = 0, 1


def ts(d, hm):
    return f"2026-11-{d:02d}T{hm}:00Z"


class Weekly(Lanes):
    def setUp(self):
        super().setUp()
        self.slot(TUE)

    def slot(self, wd, wid=None):
        with tdb.db() as c:
            c.execute("UPDATE watches SET weekly_slot = ? WHERE watch_id = ?", (wd, wid or self.w))

    def tick_at(self, when, *packs):
        self.index(*packs)
        self.mega.calls = []
        out = tracker_scheduler.daily_pass(when)
        self.clock(when)
        return out

    def queue(self, when, wid=None):
        with tdb.db() as c:
            c.execute("UPDATE watches SET refresh_queued_at = ? WHERE watch_id = ?", (when, wid or self.w))

    def post(self, wid=None, key=None):
        c = http.client.HTTPConnection("127.0.0.1", self.api.server_address[1], timeout=10)
        c.request("POST", f"/v1/watches/{wid or self.w}/refresh", headers={"Authorization": f"Bearer {key or self.key}"})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, json.loads(body) if body else None

    def scans(self, wid=None):
        return [(r["day"], r["trigger"], r["outcome"]) for r in self.rows(
            "SELECT day, trigger, outcome FROM daily_scans WHERE watch_id = ? ORDER BY day", wid or self.w)]

    def lane_days(self, wid=None):
        return sorted({r["day"] for r in self.rows("SELECT day FROM lane_day WHERE watch_id = ?", wid or self.w)})

    def one(self, wid=None):
        return self.get(f"/v1/creators/{wid or self.w}")[1]


class TestSlot(Weekly):
    def test_slot_tick_runs_every_lane_once_other_weekdays_none(self):
        page = f"{SITE}/video/mia_vale-1"
        self.leak(self.w, page)
        self.answers({"*": 200})
        self.tick_at(ts(2, "05:00"), pack(1))
        self.tick_at(ts(3, "03:59"), pack(1))
        self.assertEqual((self.scans(), self.mega.calls, tracker_stub_fetch.CALLS), ([], [], []))
        self.assertEqual({x["state"] for x in self.lanes().values()}, {"never"})
        out = self.tick_at(ts(3, "04:00"), pack(1))
        self.assertEqual((out["weekly"], out["refreshed"], out["probed"]), (1, 0, 1))
        self.assertEqual([p for p, _ in self.mega.calls], ["/content/suggest", "/content"])
        self.assertEqual(tracker_stub_fetch.CALLS, [page])
        lanes = self.lanes()
        self.assertEqual({k: (v["state"], v["last_attempt_at"], v["next_attempt_on"]) for k, v in lanes.items()},
                         {"origin_probe": ("ok", ts(3, "04:00"), "2026-11-10"),
                          "mega_lookup": ("ok", ts(3, "04:00"), "2026-11-10"),
                          "listing_recheck": ("ok", ts(3, "04:00"), "2026-11-10"),
                          "google_full": ("waiting", ts(3, "04:00"), "2026-11-10"),
                          "registry_crawl": ("never", None, None)})
        for when in (ts(3, "04:01"), ts(3, "13:00"), *(ts(d, "05:00") for d in range(4, 10))):
            self.tick_at(when, pack(1))
            self.assertEqual(self.mega.calls, [], when)
        self.assertEqual(tracker_stub_fetch.CALLS, [page])
        self.tick_at(ts(10, "04:00"), pack(1))
        self.assertEqual(len(self.mega.calls), 2)
        self.assertEqual(self.scans(), [("2026-11-03", "weekly", "ok"), ("2026-11-10", "weekly", "ok")])
        self.assertEqual(self.lane_days(), ["2026-11-03", "2026-11-10"])

    def test_scan_in_the_last_24h_skips_the_slot_and_lanes_show_it(self):
        late = self.w
        early = self.watch(self.t, username="rowan_ash", account_id="acc-r", weekly_slot=TUE)
        self.queue(ts(2, "03:30"), early)
        self.tick_at(ts(2, "03:30"))
        self.queue(ts(2, "04:30"), late)
        self.tick_at(ts(2, "04:30"))
        self.assertEqual(self.scans(late), [("2026-11-02", "refresh", "ok")])
        self.tick_at(ts(3, "04:00"), pack(1))
        self.assertEqual(self.scans(late), [("2026-11-02", "refresh", "ok")])
        self.assertEqual(self.scans(early), [("2026-11-02", "refresh", "ok"), ("2026-11-03", "weekly", "ok")])
        self.assertEqual({(v["last_attempt_at"], v["next_attempt_on"]) for k, v in self.lanes(late).items()
                          if k != "registry_crawl"}, {(ts(2, "04:30"), "2026-11-10")})
        one = self.one(late)
        self.assertEqual((one["next_check_at"], one["this_week"]["state"], one["last_checked_at"][:10]),
                         (ts(10, "04:00"), "complete", "2026-11-02"))

    def test_seed_today_skips_the_slot_scan(self):
        w2 = self.watch(self.t, username="rowan_ash", account_id="acc-r", seeded=False, weekly_slot=TUE)
        cand = {"google": [], "mega": [], "errors": []}
        with mock.patch.object(tracker_seed, "_quick_candidates", return_value=lambda *a: cand) as qc:
            self.tick_at(ts(3, "04:00"))
        self.assertEqual(qc.call_count, 1)
        self.assertEqual(self.scans(w2), [("2026-11-03", "seed", "ok")])
        self.assertEqual(self.lanes(w2)["origin_probe"]["next_attempt_on"], "2026-11-10")
        self.assertEqual(self.lanes(w2)["mega_lookup"]["state"], "never")
        self.assertEqual(self.one(w2)["next_check_at"], ts(10, "04:00"))

    def test_first_dead_probe_gets_one_confirm_probe_the_next_day(self):
        page = f"{SITE}/video/mia_vale-2"
        lid = self.leak(self.w, page, google=False)
        self.answers({"*": 404})
        self.tick_at(ts(3, "04:00"), pack(1))
        self.assertEqual((self.state(lid)["consecutive_dead"], tracker_stub_fetch.CALLS), (1, [page]))
        before = self.rows("SELECT * FROM lane_state ORDER BY lane")
        self.tick_at(ts(3, "20:00"), pack(1))
        self.assertEqual(tracker_stub_fetch.CALLS, [page])
        self.tick_at(ts(4, "03:59"), pack(1))
        self.assertEqual(tracker_stub_fetch.CALLS, [page])
        self.tick_at(ts(4, "04:00"), pack(1))
        self.assertEqual(tracker_stub_fetch.CALLS, [page, page])
        st = self.state(lid)
        self.assertEqual((st["consecutive_dead"], st["origin_status"]), (2, "gone"))
        self.assertEqual(self.pills()[page], "gone")
        self.assertEqual(self.mega.calls, [])
        self.assertEqual(self.rows("SELECT * FROM lane_state ORDER BY lane"), before)
        self.assertEqual((self.lane_days(), self.scans()), (["2026-11-03"], [("2026-11-03", "weekly", "ok")]))
        self.assertEqual(self.rows("SELECT * FROM load_reservation"), [])
        for d in (5, 6):
            self.tick_at(ts(d, "04:00"))
        self.assertEqual(tracker_stub_fetch.CALLS, [page, page])

    def test_carry_and_confirm_never_own_a_row(self):
        with tdb.db() as c:
            c.execute("UPDATE watches SET carry_json = ? WHERE watch_id = ?",
                      (json.dumps({"on": "2026-11-04", "reason": "cap_global", "first": False, "pages": []}), self.w))
        with mock.patch.object(tracker_scheduler.tracker_lanes, "run_carry", return_value=True) as carry:
            self.tick_at(ts(4, "04:00"))
        carry.assert_called_once_with(self.w, "2026-11-04", {})
        self.assertEqual(self.scans(), [])


class TestF7(Weekly):
    """Fable F7's cases on the claim and the tick order."""

    def test_refresh_queued_at_0359_on_the_slot_day_gives_one_scan(self):
        self.queue(ts(3, "03:59"))
        out = self.tick_at(ts(3, "04:00"), pack(1))
        self.assertEqual((out["refreshed"], out["weekly"]), (1, 0))
        self.assertEqual(len(self.mega.calls), 2)
        self.tick_at(ts(3, "04:01"), pack(1))
        self.assertEqual(self.mega.calls, [])
        self.assertEqual(self.scans(), [("2026-11-03", "refresh", "ok")])
        self.assertIsNone(self.rows("SELECT refresh_queued_at FROM watches WHERE watch_id = ?", self.w)[0]
                          ["refresh_queued_at"])

    def test_legacy_null_trigger_row_never_counts(self):
        with tdb.db() as c:
            c.execute("INSERT INTO daily_scans (watch_id, day, started_at, finished_at, outcome) VALUES "
                      "(?, '2026-11-03', ?, ?, 'ok')", (self.w, ts(3, "02:00"), ts(3, "02:01")))
        self.clock(ts(3, "02:30"))
        self.assertEqual(self.one()["next_refresh_at"], Lanes.T0)
        self.assertEqual(self.one()["next_check_at"], ts(3, "04:00"))
        out = self.tick_at(ts(3, "04:00"), pack(1))
        self.assertEqual(out["weekly"], 1)
        self.assertEqual(len(self.mega.calls), 2)
        self.assertEqual(self.scans(), [("2026-11-03", "weekly", "ok")])
        self.assertEqual(self.rows("SELECT started_at FROM daily_scans")[0]["started_at"], ts(3, "04:00"))

    def test_legacy_null_trigger_row_never_counts_toward_the_cooldown(self):
        with tdb.db() as c:
            c.execute("INSERT INTO daily_scans (watch_id, day, started_at, finished_at, outcome) VALUES "
                      "(?, '2026-11-02', ?, ?, 'ok')", (self.w, ts(2, "22:00"), ts(2, "22:01")))
        self.clock(ts(3, "01:00"))
        st, b = self.post()
        self.assertEqual((st, b["queued_at"]), (202, ts(3, "01:00")))

    def test_failed_refresh_or_weekly_at_0100_not_rerun_at_0400_reseed_still_runs(self):
        seed = self.watch(self.t, username="rowan_ash", account_id="acc-s", seeded=False, weekly_slot=TUE)
        refreshed = self.watch(self.t, username="juniper_lee", account_id="acc-r", seeded=False, weekly_slot=TUE)
        with tdb.db() as c:
            for wid, trigger in ((seed, "seed"), (refreshed, "refresh"), (self.w, "weekly")):
                c.execute("INSERT INTO daily_scans (watch_id, day, started_at, finished_at, outcome, trigger) VALUES "
                          "(?, '2026-11-03', ?, ?, 'failed', ?)", (wid, ts(3, "01:00"), ts(3, "01:05"), trigger))
        cand = {"google": [], "mega": [], "errors": []}
        with mock.patch.object(tracker_seed, "_quick_candidates", return_value=lambda *a: cand) as qc:
            out = self.tick_at(ts(3, "04:00"), pack(1))
            self.tick_at(ts(3, "07:00"), pack(1))
        self.assertEqual((qc.call_count, out["seeded"], out["weekly"]), (1, 1, 0))
        self.assertEqual(self.mega.calls, [])
        self.assertEqual(self.scans(seed), [("2026-11-03", "seed", "ok")])
        self.assertEqual(self.scans(refreshed), [("2026-11-03", "refresh", "failed")])
        self.assertEqual(self.scans(), [("2026-11-03", "weekly", "failed")])

    def test_crashed_refresh_row_is_taken_over_after_the_lease_only(self):
        with tdb.db() as c:
            c.execute("INSERT INTO daily_scans (watch_id, day, started_at, trigger) VALUES (?, '2026-11-04', ?, "
                      "'refresh')", (self.w, ts(4, "09:00")))
        self.queue(ts(4, "09:00"))
        self.tick_at(ts(4, "10:00"), pack(1))
        self.assertEqual((self.mega.calls, self.scans()), ([], [("2026-11-04", "refresh", None)]))
        self.tick_at(ts(4, "11:30"), pack(1))
        self.assertEqual(len(self.mega.calls), 2)
        self.assertEqual(self.scans(), [("2026-11-04", "refresh", "ok")])


class TestTick(Weekly):
    """Review fixes: the queue a slot scan serves, the claim's real start, the queue re-checked mid-tick."""

    def second(self, wid="w_zz_second", slot=TUE):
        return self.watch(self.t, username="rowan_ash", account_id=wid, watch_id=wid, weekly_slot=slot)

    def test_refresh_posted_just_before_the_weekly_claim_is_served_by_it(self):
        real, posted = tracker_seed.claim, []

        def claim(c, wid, now, retry=False, trigger="seed"):
            if trigger == "weekly" and not posted:
                posted.append(self.post())
            return real(c, wid, now, retry=retry, trigger=trigger)
        with mock.patch.object(tracker_seed, "claim", side_effect=claim):
            out = self.tick_at(ts(3, "04:00"), pack(1))
        self.assertEqual((posted[0][0], out["weekly"], out["refreshed"]), (202, 1, 0))
        self.assertEqual(self.rows("SELECT refresh_queued_at FROM watches"), [{"refresh_queued_at": None}])
        for when in (ts(3, "05:00"), ts(4, "03:59")):
            self.assertEqual((self.tick_at(when, pack(1)) or {}).get("refreshed", 0), 0, when)
        self.assertEqual(self.post()[0], 429)
        self.tick_at(ts(4, "13:00"), pack(1))
        self.assertEqual(self.scans(), [("2026-11-03", "weekly", "ok")])

    def test_long_tick_claims_at_the_real_start_and_a_second_process_never_takes_over(self):
        w2, t, ran, nested = self.second(), [tdb.parse(ts(3, "04:00"))], [], []
        real = tracker_lanes.run_scan

        def scan(wid, day, serps):
            ran.append(wid)
            if wid == self.w:
                t[0] += timedelta(hours=3)
            elif not nested:
                nested.append(tracker_scheduler.daily_pass())
            return real(wid, day, serps)
        self.index(pack(1), pack(1))
        tdb.set_clock(lambda: t[0])
        with mock.patch.object(tracker_lanes, "run_scan", side_effect=scan):
            out = tracker_scheduler.daily_pass()
        self.assertEqual((out["weekly"], nested[0]["weekly"], ran), (2, 0, [self.w, w2]))
        self.assertEqual([r["started_at"] for r in self.rows("SELECT started_at FROM daily_scans ORDER BY watch_id")],
                         [ts(3, "04:00"), ts(3, "07:00")])
        self.assertEqual(self.one(w2)["next_refresh_at"], ts(4, "07:00"))

    def test_refresh_posted_mid_tick_runs_before_the_next_slot_claim(self):
        w2, w3, ran = self.second(), self.second("w_zz_third", MON), []
        real = tracker_lanes.run_scan

        def scan(wid, day, serps):
            ran.append(wid)
            if wid == self.w:
                self.assertEqual(self.post(w3)[0], 202)
            return real(wid, day, serps)
        with mock.patch.object(tracker_lanes, "run_scan", side_effect=scan):
            out = self.tick_at(ts(3, "04:00"), pack(1), pack(1), pack(1))
        self.assertEqual((ran, out["weekly"], out["refreshed"]), ([self.w, w3, w2], 2, 1))
        self.assertEqual(self.scans(w3), [("2026-11-03", "refresh", "ok")])


class TestThisWeekStates(Weekly):
    def week(self, when, wid=None):
        self.clock(when)
        return self.one(wid)["this_week"]["state"]

    def test_seed_day(self):
        w2 = self.watch(self.t, username="rowan_ash", account_id="acc-r", seeded=False, weekly_slot=TUE)
        self.assertEqual(self.week(ts(2, "05:00"), w2), "pending")
        seen = {}
        cand = {"google": [], "mega": [], "errors": []}

        def mid(*a):
            seen["state"] = self.week(ts(2, "06:00"), w2)
            return cand
        with mock.patch.object(tracker_seed, "_quick_candidates", return_value=mid):
            self.tick_at(ts(2, "06:00"))
        self.assertEqual(seen, {"state": "pending"})
        self.assertEqual(self.week(ts(2, "06:01"), w2), "complete")
        self.assertEqual(self.week(ts(3, "03:00"), w2), "complete")

    def test_slot_day_before_and_after_the_scan_never_by_the_clock_alone(self):
        self.queue(ts(2, "12:00"))
        self.assertEqual(self.week(ts(2, "12:00")), "pending")
        self.tick_at(ts(2, "12:00"))
        self.assertEqual(self.week(ts(2, "12:01")), "complete")
        self.assertEqual(self.week(ts(3, "03:00")), "complete")
        self.tick_at(ts(3, "04:00"))
        self.assertEqual(self.scans(), [("2026-11-02", "refresh", "ok")])
        self.assertEqual(self.week(ts(3, "05:00")), "complete")
        self.assertEqual(self.week(ts(9, "03:00")), "complete")
        self.assertEqual(self.week(ts(10, "00:30")), "pending")
        self.assertEqual(self.week(ts(10, "03:59")), "pending")
        self.tick_at(ts(10, "04:00"))
        self.assertEqual(self.week(ts(10, "04:01")), "complete")
        self.assertEqual(self.week(ts(11, "01:00")), "complete")

    def test_queued_refresh_paused_and_a_failed_lane(self):
        self.queue(ts(4, "09:00"))
        self.assertEqual(self.week(ts(4, "09:00")), "pending")
        with tdb.db() as c:
            c.execute("UPDATE watches SET paused = 1, paused_at = ? WHERE watch_id = ?", (ts(4, "09:00"), self.w))
        self.assertEqual(self.week(ts(4, "09:00")), "paused")
        self.assertIsNone(self.one()["next_refresh_at"])
        self.tick_at(ts(4, "09:01"))
        self.assertEqual(self.scans(), [])
        with tdb.db() as c:
            c.execute("UPDATE watches SET paused = 0, paused_at = NULL WHERE watch_id = ?", (self.w,))
        self.assertEqual(self.week(ts(4, "09:02")), "pending")
        self.mega.mode = "404"
        self.tick_at(ts(10, "04:00"))
        self.assertEqual(self.week(ts(10, "05:00")), "partial")


if __name__ == "__main__":
    import unittest
    unittest.main()

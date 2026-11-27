"""Load reservation (Service seams, test_tracker_budget): caps hold under concurrency, partial grants, consume / settle /
expire_stale, the daily reset, the Creator cap by rank, the caps CLI and the purge. All data synthetic."""
import contextlib
import io
import os
import sqlite3
import subprocess
import sys
import threading
import unittest
from unittest import mock

from tracker_fixture import Base, tdb
import tracker_api
import tracker_budget as tb
import tracker_cli
import tracker_purge

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestBudget(Base):
    def setUp(self):
        super().setUp()
        self.a, self.b = self.tenant("Agency A"), self.tenant("Agency B")
        self.wa, self.wb = self.watch(self.a), self.watch(self.b, username="rowan_ash")

    def caps(self, daily_loads=None, daily_judge=None, **month):
        with tdb.db() as c:
            if daily_loads is not None:
                c.execute("UPDATE tracker_limits SET daily_loads = ?", (daily_loads,))
            if daily_judge is not None:
                c.execute("UPDATE tracker_limits SET daily_judge = ?", (daily_judge,))
            for tid, n in month.items():
                c.execute("UPDATE tenants SET month_loads = ? WHERE tenant_id = ?", (n, getattr(self, tid)))

    def reserve(self, watch, unit, n, partial=False):
        tid = self.rows("SELECT tenant_id FROM watches WHERE watch_id = ?", watch)[0]["tenant_id"]
        return tb.reserve(tid, watch, unit, n, partial=partial)

    def spent(self, unit, tenant=None):
        with tdb.db() as c:
            return tb.month_loads_spent(c, tenant, tdb.day()[:7]) if tenant else tb.day_spent(c, unit, tdb.day())

    def stampede(self, watches):
        grants, errors = [], []
        go = threading.Barrier(16)

        def worker(i):
            w = watches[i % len(watches)]
            go.wait()
            try:
                for unit, n in (("load", 3), ("judge_call", 2)):
                    while True:
                        r = self.reserve(w, unit, n, partial=i % 4 < 2)
                        if isinstance(r, tb.Refused):
                            break
                        grants.append((w, unit, r.held))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        return grants

    def test_16_threads_never_pass_the_global_day_cap(self):
        self.caps(daily_loads=40, daily_judge=30)
        grants = self.stampede([self.wa, self.wb])
        self.assertEqual(self.spent("load"), 40)
        self.assertEqual(self.spent("judge_call"), 30)
        self.assertEqual(sum(g for _, u, g in grants if u == "load"), 40)
        self.assertEqual(len(self.rows("SELECT * FROM load_reservation")), len(grants))

    def test_16_threads_never_pass_the_tenant_month_cap(self):
        self.caps(daily_judge=40, a=25, b=1000)
        self.stampede([self.wa, self.wb])
        self.assertEqual(self.spent("load", self.a), 25)
        self.assertEqual(self.spent("load"), 300)
        self.assertEqual(self.spent("judge_call"), 40)

    def test_partial_grant_and_refusals_say_when_to_try_again(self):
        self.caps(daily_loads=5)
        self.assertEqual(self.reserve(self.wa, "load", 3).held, 3)
        self.assertEqual(self.reserve(self.wa, "load", 3), tb.Refused("cap_global", "2026-11-03"))
        self.assertEqual(self.reserve(self.wa, "load", 3, partial=True).held, 2)
        self.assertEqual(self.reserve(self.wb, "load", 1, partial=True), tb.Refused("cap_global", "2026-11-03"))
        self.assertEqual(self.spent("load"), 5)

        self.caps(daily_loads=300, a=8)
        self.assertEqual(self.reserve(self.wa, "load", 4), tb.Refused("cap_tenant_month", "2026-12-01"))
        self.assertEqual(self.reserve(self.wa, "load", 4, partial=True).held, 3)
        self.assertEqual(self.reserve(self.wa, "judge_call", 50).held, 50)
        self.assertEqual(self.reserve(self.wb, "load", 4).held, 4)
        self.clock("2026-12-31T23:00:00Z")
        self.caps(a=0)
        self.assertEqual(self.reserve(self.wa, "load", 1), tb.Refused("cap_tenant_month", "2027-01-01"))
        self.assertEqual(self.spent("load", self.a), 0)

    def test_the_day_cap_resets_at_utc_midnight(self):
        self.caps(daily_loads=3, daily_judge=1)
        self.clock("2026-11-02T23:59:59Z")
        self.assertEqual(self.reserve(self.wa, "load", 3).held, 3)
        self.assertEqual(self.reserve(self.wa, "judge_call", 1).held, 1)
        self.assertEqual(self.reserve(self.wb, "load", 1), tb.Refused("cap_global", "2026-11-03"))
        self.clock("2026-11-03T00:00:00Z")
        self.assertEqual(self.reserve(self.wb, "load", 3).held, 3)
        self.assertEqual(self.reserve(self.wb, "judge_call", 1).held, 1)
        self.assertEqual(self.reserve(self.wa, "load", 1), tb.Refused("cap_global", "2026-11-04"))

    def test_consume_never_passes_the_hold_and_settle_releases_the_rest(self):
        self.caps(daily_loads=5)
        r = self.reserve(self.wa, "load", 5)
        self.assertEqual([tb.consume(r) for _ in range(3)], [True, True, True])
        self.assertFalse(tb.consume(r, 3))
        self.assertTrue(tb.consume(r, 2))
        self.assertFalse(tb.consume(r))
        self.assertEqual(r.used, 5)
        self.assertEqual(self.rows("SELECT used FROM load_reservation WHERE id = ?", r.id), [{"used": 5}])
        with self.assertRaises(ValueError):
            tb.consume(r, 0)
        for held, used in ((0, 0), (2, 3), (2, -1)):
            with self.assertRaises(sqlite3.IntegrityError), tdb.db() as c:
                c.execute("INSERT INTO load_reservation (id, tenant_id, watch_id, unit, day, month, held, used, "
                          "created_at) VALUES ('rs_bad', ?, ?, 'load', '2026-11-02', '2026-11', ?, ?, ?)",
                          (self.a, self.wa, held, used, self.T0))

        self.caps(daily_loads=10)
        r = self.reserve(self.wb, "load", 5)
        tb.consume(r, 2)
        self.assertIsInstance(self.reserve(self.wa, "load", 1), tb.Refused)
        self.assertTrue(tb.settle(r))
        self.assertFalse(tb.settle(r))
        self.assertFalse(tb.consume(r))
        self.assertEqual(self.spent("load"), 7)
        self.assertEqual(self.reserve(self.wa, "load", 9, partial=True).held, 3)
        self.assertEqual(self.rows("SELECT state, used, held, settled_at FROM load_reservation WHERE id = ?", r.id),
                         [{"state": "settled", "used": 2, "held": 5, "settled_at": self.T0}])

    def test_expire_stale_counts_a_crashed_hold_in_full(self):
        self.caps(daily_judge=5)
        r = self.reserve(self.wa, "judge_call", 4)
        tb.consume(r)
        self.assertEqual(tb.expire_stale(tdb.plus(self.T0, hours=2)), 0)
        self.assertEqual(tb.expire_stale(tdb.plus(self.T0, hours=2, seconds=1)), 1)
        self.assertEqual(self.rows("SELECT state FROM load_reservation WHERE id = ?", r.id), [{"state": "expired"}])
        self.assertFalse(tb.settle(r))
        self.assertFalse(tb.consume(r))
        self.assertEqual(self.spent("judge_call"), 4)
        self.assertEqual(self.reserve(self.wb, "judge_call", 5, partial=True).held, 1)
        self.clock(tdb.plus(self.T0, hours=3))
        self.assertEqual(tb.expire_stale(), 1)

    def test_watch_past_a_lowered_creator_cap_is_refused_and_never_paused(self):
        later = []
        for i, name in enumerate(("noa_lind", "ava_rowe")):
            self.clock(tdb.plus(self.T0, minutes=i + 1))
            later.append(self.watch(self.a, username=name))
        tracker_cli.main(["tenant", "cap", self.a, "2"])
        self.assertIsInstance(self.reserve(self.wa, "load", 1), tb.Reservation)
        self.assertIsInstance(tb.reserve(self.a, later[0], "load", 1), tb.Reservation)
        self.assertEqual(tb.reserve(self.a, later[1], "judge_call", 1), tb.Refused("creator_cap", None))
        self.assertEqual(self.rows("SELECT * FROM load_reservation WHERE watch_id = ?", later[1]), [])
        self.assertEqual(self.rows("SELECT paused, paused_at FROM watches WHERE watch_id = ?", later[1]),
                         [{"paused": 0, "paused_at": None}])
        with tdb.db() as c:
            c.execute("UPDATE watches SET deleted_at = ? WHERE watch_id = ?", (tdb.now(), self.wa))
        self.assertIsInstance(tb.reserve(self.a, later[1], "load", 1), tb.Reservation)
        self.assertEqual(tb.reserve(self.a, self.wa, "load", 1), tb.Refused("gone", None))
        self.assertEqual(tb.reserve(self.a, "w_missing", "load", 1), tb.Refused("gone", None))
        self.assertEqual(tb.reserve(self.b, later[1], "load", 1), tb.Refused("gone", None))
        for unit, n in (("minutes", 1), ("load", 0)):
            with self.assertRaises(ValueError):
                tb.reserve(self.a, later[1], unit, n)

    def cli(self, *args, ok=True):
        p = subprocess.run([sys.executable, os.path.join(APP, "tracker_cli.py"), *args], capture_output=True, text=True,
                           timeout=30, env=dict(os.environ))
        self.assertEqual(p.returncode == 0, ok, p.stderr)
        return p.stdout

    def main(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tracker_cli.main(list(args))
        return buf.getvalue()

    def test_cli_caps_take_effect_on_the_next_reserve(self):
        self.assertEqual(self.cli("caps", "global"), "global\tdaily_loads=300\tdaily_judge=2000\tloads_today=0\tjudge_today=0\n")
        self.assertEqual(sum(line.endswith("\tmonth_loads=1000\tloads_month=0") for line in self.cli("tenant", "list").splitlines()), 2)
        self.cli("caps", "global", "--daily-loads", "2", "--daily-judge", "1")
        self.cli("caps", "tenant", self.a, "--month-loads", "1")
        self.assertEqual(self.reserve(self.wa, "load", 2), tb.Refused("cap_tenant_month", "2026-12-01"))
        self.assertEqual(self.reserve(self.wa, "load", 1).held, 1)
        self.assertEqual(self.reserve(self.wb, "load", 2), tb.Refused("cap_global", "2026-11-03"))
        self.assertEqual(self.reserve(self.wb, "judge_call", 2), tb.Refused("cap_global", "2026-11-03"))
        self.cli("caps", "global", "--daily-judge", "5")
        self.assertEqual(self.reserve(self.wb, "judge_call", 2).held, 2)
        self.assertEqual(self.reserve(self.wb, "load", 2), tb.Refused("cap_global", "2026-11-03"))
        self.assertEqual(self.main("caps", "global"), "global\tdaily_loads=2\tdaily_judge=5\tloads_today=1\tjudge_today=2\n")
        self.assertIn(f"{self.a}\tAgency A\tmax=5\tused=1\tkeys=0\tmonth_loads=1\tloads_month=1\n",
                      self.main("tenant", "list"))
        self.cli("caps", "global", "--daily-loads", "-1", ok=False)
        self.cli("caps", "tenant", "tn_missing", "--month-loads", "1", ok=False)

    def test_purged_watch_leaves_no_reservation_row_and_its_spend_stays(self):
        self.clock(tdb.plus(self.T0, days=-31))
        old = self.watch(self.a, username="noa_lind")
        self.clock(self.T0)
        r = self.reserve(old, "load", 5)
        tb.consume(r, 5)
        tb.settle(r)
        r = self.reserve(old, "load", 4)
        tb.settle(r)
        self.reserve(old, "judge_call", 2)
        self.reserve(self.wb, "load", 1)
        created = self.rows("SELECT created_at FROM watches WHERE watch_id = ?", old)[0]["created_at"]
        self.assertEqual(tracker_api.delete_watch({"tenant_id": self.a}, {"requested_at": [created]}, b"", old), (204, None))
        self.assertIn(("load_reservation", "watch_id"), tracker_purge.WATCH_TABLES)
        self.assertEqual(tracker_purge.run()["deleted_ids"], [old])
        self.assertEqual(self.rows("SELECT * FROM load_reservation WHERE watch_id = ?", old), [])
        self.assertEqual(self.spent("load"), 6)
        self.assertEqual(self.spent("load", self.a), 5)
        self.assertEqual(self.spent("judge_call"), 2)
        self.assertEqual(self.rows("SELECT tenant_id, unit, day, month, held, used, state FROM load_reservation WHERE "
                                   "watch_id IS NULL ORDER BY unit"),
                         [{"tenant_id": self.a, "unit": "judge_call", "day": "2026-11-02", "month": "2026-11", "held": 2,
                           "used": 2, "state": "settled"},
                          {"tenant_id": self.a, "unit": "load", "day": "2026-11-02", "month": "2026-11", "held": 5,
                           "used": 5, "state": "settled"}])
        self.clock(tdb.plus(self.T0, days=-31))
        again = self.watch(self.a, username="ava_rowe")
        self.clock(self.T0)
        tb.consume(self.reserve(again, "load", 3), 1)
        tracker_api.delete_watch({"tenant_id": self.a}, {}, b"", again)
        with tdb.db() as c:
            c.execute("UPDATE watches SET purge_after = ? WHERE watch_id = ?", (self.T0, again))
        tracker_purge.run()
        self.assertEqual(self.rows("SELECT held, used FROM load_reservation WHERE watch_id IS NULL AND unit = 'load'"),
                         [{"held": 8, "used": 8}])
        self.assertEqual(self.spent("load", self.a), 8)

    def test_init_adds_month_loads_to_a_phase_1_db(self):
        mock.patch.dict(os.environ, TRACKER_DB=os.path.join(self.tmp.name, "phase1.db")).start()
        self.addCleanup(mock.patch.stopall)
        with contextlib.closing(sqlite3.connect(tdb.path())) as c:
            c.execute("CREATE TABLE tenants (tenant_id TEXT PRIMARY KEY, label TEXT NOT NULL, "
                      "creators_max INTEGER NOT NULL DEFAULT 5, created_at TEXT NOT NULL)")
            c.execute("INSERT INTO tenants VALUES ('tn_old', 'Old', 5, ?)", (self.T0,))
            c.commit()
        tdb.init()
        tdb.init()
        self.assertEqual(self.rows("SELECT month_loads FROM tenants"), [{"month_loads": 1000}])
        self.assertEqual(self.rows("SELECT daily_loads, daily_judge FROM tracker_limits"),
                         [{"daily_loads": 300, "daily_judge": 2000}])


if __name__ == "__main__":
    unittest.main()

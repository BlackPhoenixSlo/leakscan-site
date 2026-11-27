"""Load reservation (Service seams, test_tracker_budget): caps hold under concurrency, partial grants, consume / settle /
expire_stale, the Creator cap by rank, the caps CLI and the purge. All data synthetic."""
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
        tid = self.a if watch == self.wa else self.b
        with tdb.db() as c:
            return tb.reserve(c, tid, watch, unit, n, partial=partial)

    def spent(self, unit, tenant=None):
        with tdb.db() as c:
            return tb.spent(c, unit, day=None if tenant else tdb.day(), tenant_id=tenant, month=tdb.day()[:7])

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

    def test_consume_never_passes_the_hold_and_settle_releases_the_rest(self):
        self.caps(daily_loads=5)
        r = self.reserve(self.wa, "load", 5)
        self.assertEqual([tb.consume(r) for _ in range(3)], [True, True, True])
        self.assertFalse(tb.consume(r, 3))
        self.assertTrue(tb.consume(r, 2))
        self.assertFalse(tb.consume(r))
        self.assertEqual(r.used, 5)
        self.assertEqual(self.rows("SELECT used FROM load_reservation WHERE id = ?", r.id), [{"used": 5}])

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
        self.assertEqual(tb.expire_stale(tdb.parse(tdb.plus(self.T0, hours=2, seconds=1))), 1)
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
        with tdb.db() as c:
            self.assertIsInstance(tb.reserve(c, self.a, later[0], "load", 1), tb.Reservation)
            self.assertEqual(tb.reserve(c, self.a, later[1], "judge_call", 1), tb.Refused("creator_cap", "2026-11-03"))
        self.assertEqual(self.rows("SELECT * FROM load_reservation WHERE watch_id = ?", later[1]), [])
        self.assertEqual(self.rows("SELECT paused, paused_at FROM watches WHERE watch_id = ?", later[1]),
                         [{"paused": 0, "paused_at": None}])
        with tdb.db() as c:
            c.execute("UPDATE watches SET deleted_at = ? WHERE watch_id = ?", (tdb.now(), self.wa))
            c.commit()
            self.assertIsInstance(tb.reserve(c, self.a, later[1], "load", 1), tb.Reservation)
            with self.assertRaises(ValueError):
                tb.reserve(c, self.a, self.wa, "load", 1)
            with self.assertRaises(ValueError):
                tb.reserve(c, self.a, later[1], "minutes", 1)

    def cli(self, *args, ok=True):
        p = subprocess.run([sys.executable, os.path.join(APP, "tracker_cli.py"), *args], capture_output=True, text=True,
                           timeout=30, env=dict(os.environ))
        self.assertEqual(p.returncode == 0, ok, p.stderr)
        return p.stdout

    def test_cli_caps_take_effect_on_the_next_reserve(self):
        out = self.cli("caps", "list").splitlines()
        self.assertIn("daily_loads=300\tdaily_judge=2000", out[0])
        self.assertEqual(sum("month_loads=1000\t" in line for line in out[1:]), 2)
        self.cli("caps", "global", "--daily-loads", "2", "--daily-judge", "1")
        self.cli("caps", "tenant", self.a, "--month-loads", "1")
        self.assertEqual(self.reserve(self.wa, "load", 2), tb.Refused("cap_tenant_month", "2026-12-01"))
        self.assertEqual(self.reserve(self.wa, "load", 1).held, 1)
        self.assertEqual(self.reserve(self.wb, "load", 2), tb.Refused("cap_global", "2026-11-03"))
        self.assertEqual(self.reserve(self.wb, "judge_call", 2), tb.Refused("cap_global", "2026-11-03"))
        self.cli("caps", "global", "--daily-judge", "5")
        self.assertEqual(self.reserve(self.wb, "judge_call", 2).held, 2)
        self.assertEqual(self.reserve(self.wb, "load", 2), tb.Refused("cap_global", "2026-11-03"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tracker_cli.main(["caps", "list"])
        out = buf.getvalue().splitlines()
        self.assertEqual(out[0], "global\tdaily_loads=2\tdaily_judge=5\tloads_today=1\tjudge_today=2")
        self.assertIn(f"{self.a}\tAgency A\tmonth_loads=1\tloads_month=1\tcreators_max=5", out)
        self.cli("caps", "global", ok=False)
        self.cli("caps", "global", "--daily-loads", "-1", ok=False)
        self.cli("caps", "tenant", "tn_missing", "--month-loads", "1", ok=False)

    def test_purged_watch_leaves_no_reservation_row(self):
        tb.settle(self.reserve(self.wa, "load", 2))
        self.reserve(self.wa, "judge_call", 1)
        self.reserve(self.wb, "load", 1)
        with tdb.db() as c:
            c.execute("UPDATE watches SET deleted_at = ?, purge_after = ? WHERE watch_id = ?",
                      (self.T0, self.T0, self.wa))
        self.assertIn(("load_reservation", "watch_id"), tracker_purge.WATCH_TABLES)
        self.assertEqual(tracker_purge.run(self.T0)["deleted_ids"], [self.wa])
        self.assertEqual([r["watch_id"] for r in self.rows("SELECT watch_id FROM load_reservation")], [self.wb])

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

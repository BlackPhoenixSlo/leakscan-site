"""Watch purge (Seam 5): purge_after passes -> the watch and every watch-keyed row go, its id stays in deleted_ids.
All data synthetic."""
import os
import unittest
from unittest import mock

from tracker_fixture import Base, tdb, tracker_scheduler
import db
import tracker_purge

DEL = "2026-11-02T05:00:00Z"


class TestPurge(Base):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(db, "DB_PATH", os.path.join(self.tmp.name, "public.db"))
        p.start()
        self.addCleanup(p.stop)
        db.init_db()
        self.slug = db.insert_scan([{"domain": "leaksite.example"}], handle="mia_vale", status="complete")
        self.t = self.tenant()
        self.gone, self.keep = self.watch(self.t), self.watch(self.t, username="ava_rowe")
        for w in (self.gone, self.keep):
            self.leak(w, f"https://leaksite.example/{w}")
            with tdb.db() as c:
                c.execute("INSERT INTO pending_hits (watch_id, url_key, url, title, source, seen_at) VALUES "
                          "(?,?,?,?,?,?)", (w, f"p.example/{w}", f"https://p.example/{w}", "t", "google_web", DEL))
        tracker_scheduler.daily_pass()
        with tdb.db() as c:
            c.execute("UPDATE watches SET deleted_at = ?, purge_after = ? WHERE watch_id = ?",
                      (DEL, tdb.plus(DEL, days=30), self.gone))

    def counts(self, w):
        tables = {"watches": "watch_id = ?", "leaks": "watch_id = ?", "pending_hits": "watch_id = ?",
                  "daily_scans": "watch_id = ?",
                  "leak_events": "leak_id IN (SELECT leak_id FROM leaks WHERE watch_id = ?)",
                  "probe_state": "leak_id IN (SELECT leak_id FROM leaks WHERE watch_id = ?)"}
        with tdb.db() as c:
            return {t: c.execute(f"SELECT count(*) FROM {t} WHERE {q}", (w,)).fetchone()[0] for t, q in tables.items()}

    def at(self, days):
        return tdb.plus(DEL, days=days)

    def test_day_29_nothing_day_31_everything(self):
        before_keep = self.counts(self.keep)
        self.assertTrue(all(self.counts(self.gone).values()))
        self.assertEqual(tracker_purge.run(self.at(29)), {"watches": [], "deleted_ids": [], "errors": 0})
        self.assertTrue(all(self.counts(self.gone).values()))
        self.assertEqual(tracker_purge.run(self.at(31)), {"watches": [self.gone], "deleted_ids": [self.gone], "errors": 0})
        self.assertEqual(set(self.counts(self.gone).values()), {0})
        self.assertEqual(self.counts(self.keep), before_keep)
        self.assertEqual(self.rows("SELECT watch_id, tenant_id, deleted_at FROM deleted_ids"),
                         [{"watch_id": self.gone, "tenant_id": self.t, "deleted_at": self.at(31)}])
        self.assertEqual(len(self.rows("SELECT * FROM tenants")), 1)
        self.assertEqual(db.get_scan(self.slug)["handle"], "mia_vale")
        self.assertEqual(tracker_purge.run(self.at(32))["watches"], [])

    def test_deleted_ids_kept_at_day_61(self):
        tracker_purge.run(self.at(31))
        tracker_purge.run(self.at(61))
        self.clock(self.at(61))
        tracker_scheduler.daily_pass()
        self.assertEqual([r["watch_id"] for r in self.rows("SELECT watch_id FROM deleted_ids")], [self.gone])

    def test_dry_run_deletes_nothing(self):
        before = self.counts(self.gone)
        self.assertEqual(tracker_purge.run(self.at(31), dry_run=True)["watches"], [self.gone])
        self.assertEqual(self.counts(self.gone), before)
        self.assertEqual(self.rows("SELECT * FROM deleted_ids"), [])

    def test_watch_tables_hook_and_a_failing_row_is_skipped(self):
        with tdb.db() as c:
            c.execute("CREATE TABLE later_phase (wid TEXT)")
            c.execute("INSERT INTO later_phase VALUES (?)", (self.gone,))
        with mock.patch.object(tracker_purge, "WATCH_TABLES", tracker_purge.WATCH_TABLES + [("later_phase", "wid")]):
            self.assertEqual(tracker_purge.run(self.at(31))["errors"], 0)
        self.assertEqual(self.rows("SELECT * FROM later_phase"), [])
        third = self.watch(self.t, username="noa_lind", deleted_at=DEL, purge_after=DEL)
        self.leak(third, "https://leaksite.example/third")
        with mock.patch.object(tracker_purge, "WATCH_TABLES", [("missing_table", "watch_id")]):
            self.assertEqual(tracker_purge.run(self.at(31))["errors"], 1)
        self.assertEqual(self.counts(third)["leaks"], 1)
        self.assertEqual(tracker_purge.run(self.at(31))["deleted_ids"], [third])

    def test_scheduler_purges_once_per_utc_day(self):
        self.clock(self.at(31))
        self.assertEqual(tracker_scheduler.daily_pass()["purged"]["deleted_ids"], [self.gone])
        self.assertIsNone(tracker_scheduler.daily_pass()["purged"])


if __name__ == "__main__":
    unittest.main()

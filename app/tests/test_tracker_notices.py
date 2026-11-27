"""Removal service seam (Phase 3 `test_tracker_notices`), `none` branch: offer counts, first_daily_at, Service status."""
import unittest
from datetime import timedelta

from test_tracker_api import NOW, Base, ts
import tracker_db


class TestRemoval(Base):
    def scan(self, wid, day, outcome, finished=True):
        with tracker_db.db() as c:
            c.execute("INSERT OR REPLACE INTO daily_scans (watch_id, day, started_at, finished_at, outcome) VALUES (?,?,?,?,?)",
                      (wid, day, f"{day}T04:00:00Z", f"{day}T04:07:00Z" if finished else None, outcome if finished else None))

    def reads(self, wid="w_mia_00001", key=None):
        one = self.req("GET", f"/v1/creators/{wid}", key=key or self.a)[2]
        row = next(x for x in self.req("GET", "/v1/creators", key=key or self.a)[2]["creators"] if x["watch_id"] == wid)
        self.assertEqual({k: v for k, v in one.items() if k != "lanes"}, row)
        return row

    def test_offer_counts_windows(self):
        self.put("w_mia_00001")
        ago = lambda **kw: ts(NOW - timedelta(**kw))
        live = lambda: {"origin": "live", "at": ago(hours=8), "live_at": ago(hours=8)}
        gone = lambda: {"origin": "gone", "at": ago(hours=8), "live_at": ago(days=9)}
        self.leak("w_mia_00001", "lk_live30", "https://example-leaks.test/live30", seen=ago(days=30), probe=live())
        self.leak("w_mia_00001", "lk_live29", "https://example-leaks.test/live29", seen=ago(days=30, minutes=-1), probe=live())
        self.leak("w_mia_00001", "lk_back_in", "https://example-leaks.test/backin", seen=ago(days=40), probe=live(),
                  statuses=[(ago(days=35), "live", "gone", ago(days=36)), (ago(days=30), "gone", "live", None)])
        self.leak("w_mia_00001", "lk_back_out", "https://example-leaks.test/backout", seen=ago(days=40), probe=live(),
                  statuses=[(ago(days=35), "live", "gone", ago(days=36)), (ago(days=30, minutes=1), "gone", "live", None)])
        self.leak("w_mia_00001", "lk_cached", "https://example-leaks.test/cached", seen=ago(days=10), google=True, probe=gone())
        self.leak("w_mia_00001", "lk_gone", "https://example-leaks.test/gone", seen=ago(days=40), probe=gone())
        self.leak("w_mia_00001", "lk_new_in", "https://example-leaks.test/newin", seen="2026-11-21T00:00:00Z", first_scan=False)
        self.leak("w_mia_00001", "lk_new_out", "https://example-leaks.test/newout", seen="2026-11-20T23:59:59Z", first_scan=False)
        self.leak("w_mia_00001", "lk_first", "https://example-leaks.test/first", seen=ts(NOW))
        self.leak("w_mia_00001", "lk_listed", "https://mega.example-index.test/f/1", kind="mega", site="example-index.test",
                  seen=ago(days=60), source="mega_index")
        r = self.reads()
        self.assertEqual(r["offer_counts"], {"visible": 5, "came_back_30d": 1, "cached": 1, "live_30d": 3, "new_7d": 1})
        with tracker_db.db() as conn:
            tracker_db.add_event(conn, "lk_back_in", "status", {"from": "live", "to": "gone", "dead_since": ago(days=1)}, at=ago(hours=8))
            conn.execute("UPDATE probe_state SET origin_status = 'gone' WHERE leak_id = 'lk_back_in'")
        self.assertEqual(self.reads()["offer_counts"], {"visible": 4, "came_back_30d": 0, "cached": 1, "live_30d": 2, "new_7d": 1})
        self.clock = NOW.replace(hour=0) + timedelta(days=1)
        self.assertEqual(self.reads()["offer_counts"]["new_7d"], 0)

    def test_offer_counts_empty(self):
        self.put("w_mia_00001")
        self.assertEqual(self.reads()["offer_counts"], {"visible": 0, "came_back_30d": 0, "cached": 0, "live_30d": 0, "new_7d": 0})

    def test_first_daily_at(self):
        self.put("w_mia_00001")
        self.put("w_ash_00002", account_id="acc-2", username="rowanash", aliases=[])
        self.assertIsNone(self.reads()["first_daily_at"])
        self.scan("w_mia_00001", "2026-11-20", "failed")
        self.scan("w_mia_00001", "2026-11-21", "skipped")
        self.scan("w_mia_00001", "2026-11-22", None, finished=False)
        self.assertIsNone(self.reads()["first_daily_at"])
        self.scan("w_mia_00001", "2026-11-24", "partial")
        self.assertEqual(self.reads()["first_daily_at"], "2026-11-24T04:07:00Z")
        self.scan("w_mia_00001", "2026-11-25", "ok")
        self.assertEqual(self.reads()["first_daily_at"], "2026-11-24T04:07:00Z")
        self.scan("w_mia_00001", "2026-11-22", "ok")
        self.assertEqual(self.reads()["first_daily_at"], "2026-11-22T04:07:00Z")
        self.scan("w_ash_00002", "2026-11-26", "ok")
        self.assertEqual(self.reads("w_ash_00002")["first_daily_at"], "2026-11-26T04:07:00Z")

    def test_service_status_none_and_no_offer_key(self):
        self.put("w_mia_00001")
        self.leak("w_mia_00001", "lk_live", "https://example-leaks.test/live", probe={"origin": "live", "at": ts(NOW)})
        r = self.reads()
        self.assertEqual((r["service_status"], r["service_status_since"], r["removal"]), ("none", None, None))

        def keys(o):
            if isinstance(o, dict):
                return set(o) | set().union(*map(keys, o.values()))
            return set().union(*map(keys, o)) if isinstance(o, list) else set()

        for path in ("/v1/me", "/v1/creators", "/v1/creators/w_mia_00001", "/v1/creators/w_mia_00001/leaks",
                     "/v1/leaks?watch_id=w_mia_00001"):
            self.assertNotIn("offer", keys(self.req("GET", path, key=self.a)[2]), path)

    def test_tenant_isolation(self):
        self.put("w_mia_00001")
        self.put("w_rowan_0001", key=self.b, account_id="acc-2001", username="rowanash", display_name="Rowan Ash", aliases=[])
        self.leak("w_mia_00001", "lk_live", "https://example-leaks.test/live", seen=ts(NOW - timedelta(days=31)),
                  probe={"origin": "live", "at": ts(NOW)})
        self.scan("w_mia_00001", "2026-11-26", "ok")
        self.assertEqual(self.reads()["offer_counts"]["live_30d"], 1)
        b = self.reads("w_rowan_0001", key=self.b)
        self.assertEqual((b["offer_counts"], b["first_daily_at"]),
                         ({"visible": 0, "came_back_30d": 0, "cached": 0, "live_30d": 0, "new_7d": 0}, None))
        self.assertEqual(self.req("GET", "/v1/creators/w_mia_00001", key=self.b)[:3:2], (404, {"error": "not_found"}))


if __name__ == "__main__":
    unittest.main()

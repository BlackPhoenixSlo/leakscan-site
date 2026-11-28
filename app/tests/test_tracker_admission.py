"""tracker_admission: least-loaded Weekly slot, waitlist, Creator cap, paused watches, edits, backfill (spec Service
seams, ticket 23). Temp TRACKER_DB, fixed clock, fictional Creators only."""
import contextlib
import json
import os
import sqlite3
from datetime import timedelta
from unittest import mock

from tracker_fixture import Base, tdb

import tracker_admission as adm
import tracker_api
import tracker_seed


WORST = {"username": "mia_vale", "platform": "onlyfans", "instagram": "mia.vale.ig", "x": "miavale_x",
         "aliases_json": json.dumps(["rowanash", "vale.mia", "mia-official", "miavee", "rowan_mia"])}  # 34 loads


class AdmissionBase(Base):
    def setUp(self):
        super().setUp()
        self.t = self.tenant()
        self.x = self.tenant("Agency X")

    def admit(self, tenant_id=None, identity=None):
        with tdb.db() as c:
            return adm.admit(c, tenant_id or self.t, identity or WORST)

    def cap(self, daily_loads):
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = ? WHERE id = 1", (daily_loads,))

    def slotted(self, slot, plan=34, **kw):
        return self.watch(self.x, weekly_slot=slot, plan_loads=plan, **kw)


class TestSlot(AdmissionBase):
    def test_least_loaded_tie_lowest_weekday(self):
        self.assertEqual(self.admit(), adm.Slot(0, 34))
        self.slotted(0)
        self.assertEqual(self.admit(), adm.Slot(1, 34))
        for d, plan in ((1, 9), (2, 4), (3, 7), (4, 4), (5, 8), (6, 5)):
            self.slotted(d, plan)
        self.assertEqual(self.admit(), adm.Slot(2, 34))

    def test_slot_column_range(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.slotted(7)


class TestWaitlist(AdmissionBase):
    def test_slot_day_past_cap(self):
        for d in range(7):
            self.slotted(d)
        # 7 watches: every day = 34; new watch needs 34 + 34 = 68
        self.cap(67)
        self.assertEqual(self.admit(), adm.Waitlist())
        self.cap(68)
        self.assertEqual(self.admit(), adm.Slot(0, 34))

    def test_projected_has_no_fresh_loads(self):
        self.slotted(0, plan=100)
        self.slotted(3, plan=9, paused=True)
        with tdb.db() as c:
            self.assertEqual(adm.projected(c), [100, 0, 0, 9, 0, 0, 0])
        # a day over the cap no longer blocks the others (no daily per-watch load on it)
        self.cap(34)
        self.assertEqual(self.admit(), adm.Slot(1, 34))
        self.cap(33)
        self.assertEqual(self.admit(), adm.Waitlist())

    def test_accepting_new(self):
        self.slotted(0, plan=100)
        self.cap(33)
        with tdb.db() as c:
            self.assertFalse(adm.accepting_new(c))
        self.cap(34)
        with tdb.db() as c:
            self.assertTrue(adm.accepting_new(c))

    def test_deleted_watches_do_not_count(self):
        w = self.slotted(0, plan=100)
        self.cap(101)
        with tdb.db() as c:
            c.execute("UPDATE watches SET deleted_at = ? WHERE watch_id = ?", (tdb.now(), w))
        self.assertEqual(self.admit(), adm.Slot(0, 34))


class TestCreatorCap(AdmissionBase):
    def test_creator_cap(self):
        with tdb.db() as c:
            c.execute("UPDATE tenants SET creators_max = 1 WHERE tenant_id = ?", (self.t,))
        w = self.watch(self.t, weekly_slot=0, plan_loads=34)
        self.assertEqual(self.admit(), adm.CreatorCap(1))
        self.assertNotEqual(adm.CreatorCap(1), adm.Slot(1, 34))
        self.assertEqual(self.admit(self.tenant("Agency B")), adm.Slot(1, 34))
        self.cap(1)
        self.assertEqual(self.admit(), adm.CreatorCap(1), "creator cap answers before the waitlist")
        self.cap(300)
        with tdb.db() as c:
            c.execute("UPDATE watches SET deleted_at = ? WHERE watch_id = ?", (tdb.now(), w))
        self.assertEqual(self.admit(), adm.Slot(0, 34))


class TestPaused(AdmissionBase):
    def test_paused_watches_count(self):
        for d in range(7):
            self.slotted(d, plan=100, paused=d == 0)
        self.slotted(1, plan=1)
        self.assertEqual(self.admit(), adm.Slot(0, 34))
        self.cap(130)
        self.assertEqual(self.admit(), adm.Waitlist())


class TestEdits(AdmissionBase):
    def put(self, watch_id, **over):
        b = {"account_id": watch_id, "platform": "onlyfans", "username": "mia_vale", "verified": True, "aliases": [],
             "paused": False, **over}
        try:
            return tracker_api.put_watch({"tenant_id": self.t}, {}, json.dumps(b).encode(), watch_id)
        except tracker_api._Err as e:
            return e.code, e.body

    def test_create_stores_slot_edit_never_refused(self):
        with mock.patch.object(tracker_seed, "start"):
            self.assertEqual(self.put("w_mia_00001", paused=True)[0], 200)
            self.assertEqual(self.put("w_ash_00002", username="rowan_ash")[0], 200)
            got = self.rows("SELECT watch_id, weekly_slot, plan_loads FROM watches ORDER BY watch_id")
            self.assertEqual(got, [{"watch_id": "w_ash_00002", "weekly_slot": 1, "plan_loads": 9},
                                   {"watch_id": "w_mia_00001", "weekly_slot": 0, "plan_loads": 9}])
            self.cap(2)
            self.assertEqual(self.put("w_bee_00003", username="bee_example"), (409, {"error": "waitlist"}))
            self.assertEqual(self.rows("SELECT COUNT(*) n FROM watches")[0]["n"], 2)
            with mock.patch.object(adm, "plan_loads", return_value=50):
                self.assertEqual(self.put("w_ash_00002", username="rowan_ash", aliases=["rowanash.x"])[0], 200)
            self.assertEqual(self.put("w_mia_00001", paused=False)[0], 200)
            got = self.rows("SELECT watch_id, weekly_slot, plan_loads, paused FROM watches ORDER BY watch_id")
            self.assertEqual(got, [{"watch_id": "w_ash_00002", "weekly_slot": 1, "plan_loads": 50, "paused": 0},
                                   {"watch_id": "w_mia_00001", "weekly_slot": 0, "plan_loads": 9, "paused": 0}])
            self.assertEqual(self.put("w_mia_00001", aliases=["rowanash"])[0], 200)
            self.assertEqual(self.rows("SELECT weekly_slot, plan_loads FROM watches WHERE watch_id = 'w_mia_00001'"),
                             [{"weekly_slot": 0, "plan_loads": 13}])


class TestBackfill(AdmissionBase):
    def test_creation_order_idempotent(self):
        t0 = tdb.parse(self.T0)
        self.watch(self.t, watch_id="w_pre_00000", weekly_slot=0, plan_loads=31)
        for wid, h in (("w_third_0003", 3), ("w_first_0001", 1), ("w_gone_00009", 0), ("w_second_002", 2)):
            self.clock(tdb.fmt(t0 + timedelta(hours=h)))
            self.watch(self.t, watch_id=wid, weekly_slot=None)
        with tdb.db() as c:
            c.execute("UPDATE watches SET deleted_at = ? WHERE watch_id = 'w_gone_00009'", (tdb.now(),))
        tdb.init()
        want = {"w_pre_00000": (0, 31), "w_first_0001": (1, 9), "w_second_002": (2, 9), "w_third_0003": (3, 9),
                "w_gone_00009": (None, None)}
        got = {r["watch_id"]: (r["weekly_slot"], r["plan_loads"]) for r in self.rows("SELECT * FROM watches")}
        self.assertEqual(got, want)
        tdb.init()
        self.assertEqual({r["watch_id"]: (r["weekly_slot"], r["plan_loads"]) for r in self.rows("SELECT * FROM watches")}, want)


class TestMigration(Base):
    def test_phase_1_watches_get_slot_and_plan(self):
        mock.patch.dict(os.environ, TRACKER_DB=os.path.join(self.tmp.name, "phase1.db")).start()
        self.addCleanup(mock.patch.stopall)
        with contextlib.closing(sqlite3.connect(tdb.path())) as c:
            c.execute("CREATE TABLE watches (watch_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, account_id TEXT NOT NULL, "
                      "platform TEXT NOT NULL, username TEXT NOT NULL, verified INTEGER NOT NULL DEFAULT 0, display_name TEXT, "
                      "aliases_json TEXT NOT NULL DEFAULT '[]', instagram TEXT, x TEXT, paused INTEGER NOT NULL DEFAULT 0, "
                      "paused_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, seeded_at TEXT, deleted_at TEXT, "
                      "purge_after TEXT)")
            c.execute("INSERT INTO watches (watch_id, tenant_id, account_id, platform, username, created_at, updated_at) "
                      "VALUES ('w_old_00001', 'tn_old', 'acc-1', 'onlyfans', 'mia_vale', ?, ?)", (self.T0, self.T0))
            c.commit()
        tdb.init()
        tdb.init()
        self.assertEqual(self.rows("SELECT watch_id, weekly_slot, plan_loads, carry_json FROM watches"),
                         [{"watch_id": "w_old_00001", "weekly_slot": 0, "plan_loads": 9, "carry_json": None}])

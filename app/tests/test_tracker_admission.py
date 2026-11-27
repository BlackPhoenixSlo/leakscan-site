"""tracker_admission: least-loaded Weekly slot, waitlist, Creator cap, paused watches, edits, backfill (spec Service
seams, ticket 23). Temp TRACKER_DB, fixed clock, fictional Creators only."""
import json
import sqlite3
from datetime import timedelta
from unittest import mock

from tracker_fixture import Base, tdb

import tracker_admission as adm
import tracker_api
import tracker_seed


class AdmissionBase(Base):
    def setUp(self):
        super().setUp()
        self.t = self.tenant()
        self.x = self.tenant("Agency X")

    def admit(self, tenant_id=None, identity=None):
        with tdb.db() as c:
            return adm.admit(c, tenant_id or self.t, identity or {"username": "mia_vale", "aliases_json": "[]"})

    def cap(self, daily_loads):
        with tdb.db() as c:
            c.execute("UPDATE tracker_limits SET daily_loads = ? WHERE id = 1", (daily_loads,))

    def slotted(self, slot, plan=31, **kw):
        return self.watch(self.x, weekly_slot=slot, plan_loads=plan, **kw)


class TestSlot(AdmissionBase):
    def test_least_loaded_tie_lowest_weekday(self):
        self.assertEqual(self.admit(), adm.Slot(0))
        self.slotted(0)
        self.assertEqual(self.admit(), adm.Slot(1))
        for d, plan in ((1, 9), (2, 4), (3, 7), (4, 4), (5, 8), (6, 5)):
            self.slotted(d, plan)
        self.assertEqual(self.admit(), adm.Slot(2))

    def test_slot_column_range(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.slotted(7)


class TestWaitlist(AdmissionBase):
    def test_slot_day_past_cap(self):
        for d in range(7):
            self.slotted(d)
        # 7 watches: every day = 7 fresh + 31 = 38; new watch needs 38 + 31 + 1 = 70
        self.cap(69)
        self.assertEqual(self.admit(), adm.Waitlist())
        self.cap(70)
        self.assertEqual(self.admit(), adm.Slot(0))

    def test_any_day_past_cap(self):
        self.slotted(0, plan=100)
        # p = [101, 1, 1, 1, 1, 1, 1]: slot day 1 fits easily, day 0 has no room for the new fresh load
        self.cap(101)
        self.assertEqual(self.admit(), adm.Waitlist())
        self.cap(102)
        self.assertEqual(self.admit(), adm.Slot(1))

    def test_accepting_new(self):
        self.slotted(0, plan=100)
        self.cap(101)
        with tdb.db() as c:
            self.assertFalse(adm.accepting_new(c))
        self.cap(102)
        with tdb.db() as c:
            self.assertTrue(adm.accepting_new(c))

    def test_deleted_watches_do_not_count(self):
        w = self.slotted(0, plan=100)
        self.cap(101)
        with tdb.db() as c:
            c.execute("UPDATE watches SET deleted_at = ? WHERE watch_id = ?", (tdb.now(), w))
        self.assertEqual(self.admit(), adm.Slot(0))


class TestCreatorCap(AdmissionBase):
    def test_creator_cap(self):
        with tdb.db() as c:
            c.execute("UPDATE tenants SET creators_max = 1 WHERE tenant_id = ?", (self.t,))
        w = self.watch(self.t, weekly_slot=0, plan_loads=31)
        self.assertEqual(self.admit(), adm.CreatorCap(1))
        self.assertEqual(self.admit(self.tenant("Agency B")), adm.Slot(1))
        self.cap(1)
        self.assertEqual(self.admit(), adm.CreatorCap(1), "creator cap answers before the waitlist")
        self.cap(300)
        with tdb.db() as c:
            c.execute("UPDATE watches SET deleted_at = ? WHERE watch_id = ?", (tdb.now(), w))
        self.assertEqual(self.admit(), adm.Slot(0))


class TestPaused(AdmissionBase):
    def test_paused_watches_count(self):
        self.slotted(0, plan=100, paused=True)
        self.assertEqual(self.admit(), adm.Slot(1))
        self.cap(101)
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
            self.assertEqual(got, [{"watch_id": "w_ash_00002", "weekly_slot": 1, "plan_loads": 31},
                                   {"watch_id": "w_mia_00001", "weekly_slot": 0, "plan_loads": 31}])
            self.cap(2)
            self.assertEqual(self.put("w_bee_00003", username="bee_example"), (409, {"error": "waitlist"}))
            self.assertEqual(self.rows("SELECT COUNT(*) n FROM watches")[0]["n"], 2)
            with mock.patch.object(adm, "plan_loads", return_value=50):
                self.assertEqual(self.put("w_ash_00002", username="rowan_ash", aliases=["rowanash.x"])[0], 200)
            self.assertEqual(self.put("w_mia_00001", paused=False)[0], 200)
            got = self.rows("SELECT watch_id, weekly_slot, plan_loads, paused FROM watches ORDER BY watch_id")
            self.assertEqual(got, [{"watch_id": "w_ash_00002", "weekly_slot": 1, "plan_loads": 50, "paused": 0},
                                   {"watch_id": "w_mia_00001", "weekly_slot": 0, "plan_loads": 31, "paused": 0}])


class TestBackfill(AdmissionBase):
    def test_creation_order_idempotent(self):
        t0 = tdb.parse(self.T0)
        self.watch(self.t, watch_id="w_pre_00000", weekly_slot=0, plan_loads=31)
        for wid, h in (("w_third_0003", 3), ("w_first_0001", 1), ("w_gone_00009", 0), ("w_second_002", 2)):
            self.clock(tdb.fmt(t0 + timedelta(hours=h)))
            self.watch(self.t, watch_id=wid)
        with tdb.db() as c:
            c.execute("UPDATE watches SET deleted_at = ? WHERE watch_id = 'w_gone_00009'", (tdb.now(),))
        tdb.init()
        want = {"w_pre_00000": (0, 31), "w_first_0001": (1, 31), "w_second_002": (2, 31), "w_third_0003": (3, 31),
                "w_gone_00009": (None, None)}
        got = {r["watch_id"]: (r["weekly_slot"], r["plan_loads"]) for r in self.rows("SELECT * FROM watches")}
        self.assertEqual(got, want)
        tdb.init()
        self.assertEqual({r["watch_id"]: (r["weekly_slot"], r["plan_loads"]) for r in self.rows("SELECT * FROM watches")}, want)

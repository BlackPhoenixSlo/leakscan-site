"""Shared setup for the tracker tests: a temp TRACKER_DB, a settable clock, tenants / watches / Leaks written straight
through tracker_db, and the stub fetcher. The Mega index is off (tests that run it point it at leakshaven_stub);
Browserbase points nowhere and has no host key (tests that run the Google lanes stub both). All data synthetic."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import bb_client
import leakshaven
import tracker_db as tdb
import tracker_probe
import tracker_rules
import tracker_scheduler
import tracker_seed
import tracker_serp
import tracker_stub_fetch


class Base(unittest.TestCase):
    T0 = "2026-11-02T05:00:00Z"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fetch_file = os.path.join(self.tmp.name, "fetch.json")
        env = mock.patch.dict(os.environ, TRACKER_DB=os.path.join(self.tmp.name, "tracker.db"),
                              TRACKER_STUB_FETCH=self.fetch_file, BROWSERBASE_API_KEY="", BROWSERBASE_PROJECT_ID="")
        env.start()
        self.addCleanup(env.stop)
        for paid in (mock.patch.multiple(bb_client, BB_API="http://127.0.0.1:9", CREATE_GAP=0),
                     mock.patch.object(tracker_serp, "_playwright", mock.Mock(side_effect=AssertionError))):
            paid.start()
            self.addCleanup(paid.stop)
        off = mock.patch.object(leakshaven, "ENABLED", False)
        off.start()
        self.addCleanup(off.stop)
        self.addCleanup(self.tmp.cleanup)
        tdb.init()
        self.clock(self.T0)
        self.addCleanup(tdb.set_clock, None)
        tracker_stub_fetch.CALLS.clear()
        tracker_probe.set_fetcher(tracker_stub_fetch.FETCH)
        self.addCleanup(tracker_probe.set_fetcher, None)
        tracker_scheduler._purged_day = None
        tracker_probe._inflight.clear()
        tracker_seed._busy.clear()

    def clock(self, ts):
        dt = tdb.parse(ts)
        tdb.set_clock(lambda: dt)

    def answers(self, table):
        with open(self.fetch_file, "w", encoding="utf-8") as fh:
            json.dump(table, fh)

    def tenant(self, label="Agency A"):
        tid = tdb.new_id("tn_")
        with tdb.db() as c:
            c.execute("INSERT INTO tenants (tenant_id, label, created_at) VALUES (?,?,?)", (tid, label, tdb.now()))
        return tid

    def watch(self, tenant_id, username="mia_vale", aliases=(), seeded=True, paused=False, **kw):
        wid = kw.pop("watch_id", None) or tdb.new_id("w_")
        row = dict(watch_id=wid, tenant_id=tenant_id, account_id=kw.pop("account_id", wid), platform="onlyfans",
                   username=username, aliases_json=json.dumps(list(aliases)), paused=int(paused),
                   created_at=tdb.now(), updated_at=tdb.now(), seeded_at=tdb.now() if seeded else None, **kw)
        with tdb.db() as c:
            c.execute(f"INSERT INTO watches ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
        return wid

    def leak(self, watch_id, url, kind="page", google=True):
        lid = tdb.new_id("lk_")
        with tdb.db() as c:
            c.execute("INSERT INTO leaks (leak_id, watch_id, url_key, url, leak_site, kind, title, created_at) "
                      "VALUES (?,?,?,?,?,?,?,?)", (lid, watch_id, tracker_rules.url_key(url, kind != "page"), url,
                                                   tracker_rules.registrable_domain(tracker_rules.host_of(url)),
                                                   kind, "t", tdb.now()))
            tdb.add_event(c, lid, "seen", {"source": "google_web" if google else "mega_index", "first_scan": True})
            if google:
                tdb.add_event(c, lid, "google_seen")
        return lid

    def state(self, leak_id):
        with tdb.db() as c:
            r = c.execute("SELECT * FROM probe_state WHERE leak_id = ?", (leak_id,)).fetchone()
        return dict(r) if r else None

    def events(self, leak_id, type_=None):
        with tdb.db() as c:
            rows = c.execute("SELECT at, type, data_json FROM leak_events WHERE leak_id = ? ORDER BY id", (leak_id,))
            return [{"at": r[0], "type": r[1], "data": json.loads(r[2])} for r in rows if not type_ or r[1] == type_]

    def rows(self, sql, *args):
        with tdb.db() as c:
            return [dict(r) for r in c.execute(sql, args)]

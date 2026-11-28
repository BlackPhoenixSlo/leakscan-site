"""Scheduler tick (spec "Daily pass (service)", cadence spec slice A): a daemon thread like the retention loop wakes
every TICK_S. A scan (tracker_lanes.run_scan: every lane of one watch) owns the watch's daily_scans row for its UTC day
(tracker_seed.claim) with its trigger. Each tick, in order:
  1. Queued refreshes (watches.refresh_queued_at, POST /v1/watches/{id}/refresh), at any hour: a `refresh` scan (an
     unseeded watch is seeded instead); the row's finish clears the queue; a paused or deleted watch's queue is
     dropped. A refresh absorbs a pending carry (its whole plan replaces it).
  From TRACKER_DAILY_AT (UTC HH:MM, default 04:00) on (before it, a tick that ran no refresh returns None):
  2. Rows still open from an earlier day (a crash) finish failed.
  3. The daily re-seed of every live unseeded watch (tracker_seed.claim retry: a failed or crashed seed row of the day).
  4. A `weekly` scan of every live seeded watch whose weekly_slot is today's weekday, unless a scan of it (a row with a
     trigger) started less than tracker_view.REFRESH_COOLDOWN_H before today's TRACKER_DAILY_AT: that scan is the week's
     (today's weekly row is left to the claim, so a crashed one is taken over after tracker_seed.LEASE_H).
  5. Pending carries due today (tracker_lanes.run_carry) and the dead-streak confirm (tracker_probe.run confirm: a
     page whose latest settled probe was its first dead one is probed once on a later day); neither owns a row.
  6. The purge, once per UTC day.
A scan's row finishes failed when the Origin probe failed, partial when it was ok but a lane_day row of its day isn't;
one watch's error fails only its own row. A row still open after tracker_seed.LEASE_H (a crash) is taken over by the
next claim of its trigger; a failed weekly or refresh row is never rerun. TRACKER_SCHEDULER=0 keeps the thread off."""
import ipaddress
import os
import threading
import time
from datetime import timedelta

import tracker_db as tdb
import tracker_lanes
import tracker_probe
import tracker_purge
import tracker_seed
import tracker_view
from tracker_probe import log

TICK_S = 60
_purged_day = None
_LIVE = "SELECT watch_id FROM watches WHERE paused = 0 AND deleted_at IS NULL "


def _finish(wid, day, outcome, refresh=False):
    with tdb.db() as c:
        c.execute("UPDATE daily_scans SET finished_at = ?, outcome = CASE WHEN ? = 'ok' AND EXISTS (SELECT 1 FROM "
                  "lane_day WHERE watch_id = daily_scans.watch_id AND day = daily_scans.day AND outcome != 'ok') "
                  "THEN 'partial' ELSE ? END WHERE watch_id = ? AND day = ? AND finished_at IS NULL",
                  (tdb.now(), outcome, outcome, wid, day))
        if refresh:
            c.execute("UPDATE watches SET refresh_queued_at = NULL WHERE watch_id = ?", (wid,))


def _scan(wid, today, serps, out, refresh=False):
    """The claimed row's work: the seed for an unseeded watch (it finishes its own row), else run_scan."""
    outcome = "failed"
    try:
        with tdb.db() as c:
            seeded = c.execute("SELECT seeded_at FROM watches WHERE watch_id = ?", (wid,)).fetchone()[0]
        if not seeded:
            out["seeded"] += bool(tracker_seed.run(wid, claimed=True))
        else:
            r = tracker_lanes.run_scan(wid, today, serps)
            if r["probe"]:
                out.update(probed=out["probed"] + 1, keys=out["keys"] + r["probe"]["keys"],
                           fetched=out["fetched"] + r["probe"]["fetched"])
            outcome = r["outcome"]
    except Exception as e:
        log(f"tracker scan failed: {type(e).__name__}")
    _finish(wid, today, outcome, refresh)


def _pass(now, due):
    global _purged_day
    today, serps = tdb.day(now), {}
    out = {"seeded": 0, "probed": 0, "keys": 0, "fetched": 0, "refreshed": 0, "weekly": 0, "purged": None}
    with tdb.db() as c:
        c.execute("UPDATE watches SET refresh_queued_at = NULL WHERE refresh_queued_at IS NOT NULL AND "
                  "(paused = 1 OR deleted_at IS NOT NULL)")
        queued = [r[0] for r in c.execute(_LIVE + "AND refresh_queued_at IS NOT NULL ORDER BY refresh_queued_at, "
                                          "watch_id")]
    for wid in queued:
        with tdb.db() as c:
            mine = tracker_seed.claim(c, wid, now, trigger="refresh")
        if mine:
            _scan(wid, today, serps, out, refresh=True)
            out["refreshed"] += 1
    if not due:
        return out if out["refreshed"] else None
    floor = tdb.fmt(tracker_view.due_at(now) - timedelta(hours=tracker_view.REFRESH_COOLDOWN_H))
    with tdb.db() as c:
        c.execute("UPDATE daily_scans SET finished_at = ?, outcome = 'failed' WHERE finished_at IS NULL AND day < ?",
                  (tdb.now(), today))
        order = "ORDER BY created_at, watch_id"
        unseeded = [r[0] for r in c.execute(_LIVE + "AND seeded_at IS NULL " + order)]
        reseed = [w for w in unseeded if tracker_seed.claim(c, w, now, retry=True)]
    for wid in reseed:
        _scan(wid, today, serps, out)
    with tdb.db() as c:
        slot = [r[0] for r in c.execute(
            _LIVE + "AND seeded_at IS NOT NULL AND weekly_slot = ? AND NOT EXISTS (SELECT 1 FROM daily_scans d WHERE "
            "d.watch_id = watches.watch_id AND d.trigger IS NOT NULL AND d.started_at > ? AND NOT "
            "(d.day = ? AND d.trigger = 'weekly')) " + order, (now.weekday(), floor, today))]
    for wid in slot:
        with tdb.db() as c:
            mine = tracker_seed.claim(c, wid, now, trigger="weekly")
        if mine:
            _scan(wid, today, serps, out)
            out["weekly"] += 1
    with tdb.db() as c:
        live = [r[0] for r in c.execute(_LIVE + order)]
        carried = [r[0] for r in c.execute(_LIVE + "AND carry_json IS NOT NULL " + order)]
    for wid in carried:
        try:
            tracker_lanes.run_carry(wid, today, serps)
        except Exception as e:
            log(f"tracker carry failed: {type(e).__name__}")
    try:
        tracker_probe.run(live, confirm=True)
    except Exception as e:
        log(f"tracker dead-streak confirm failed: {type(e).__name__}")
    if _purged_day != today:
        _purged_day = today
        out["purged"] = tracker_purge.run(tdb.now())
    return out


def daily_pass(at=None):
    """One tick at `at` (ISO ts or aware datetime; default now) -> counts, None before TRACKER_DAILY_AT unless a queued
    refresh ran. An explicit `at` drives tracker_db's clock for the tick (tracker_cli daily --at, the Seam 6 tracer)."""
    at_dt = tdb.parse(at) if isinstance(at, str) else at
    if at is not None and at_dt is None:
        raise ValueError("at")
    prev, t0 = tdb._clock, time.monotonic()
    if at_dt:
        tdb.set_clock(lambda: at_dt + timedelta(seconds=time.monotonic() - t0))
    try:
        now = tdb.now_dt()
        tdb.init()
        return _pass(now, now >= tracker_view.due_at(now))
    finally:
        if at_dt:
            tdb.set_clock(prev)


def _loop():
    while True:
        try:
            daily_pass()
        except Exception as e:
            log(f"tracker daily pass failed: {type(e).__name__}")
        time.sleep(TICK_S)


def _public(ip):
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def start():
    """The scheduler thread (None when TRACKER_SCHEDULER=0)."""
    if os.environ.get("TRACKER_SCHEDULER", "1") == "0":
        return None
    tdb.init()
    if not any(map(_public, tracker_probe._self_ips())):
        log("tracker: no public address in TRACKER_SELF_IPS; probes can't refuse the service's own")
    t = threading.Thread(target=_loop, daemon=True, name="tracker scheduler")
    t.start()
    return t

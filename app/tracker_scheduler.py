"""Scheduler tick (spec "Daily pass (service)", cadence spec slice A): a daemon thread like the retention loop wakes
every TICK_S. A scan (tracker_lanes.run_scan: every lane of one watch) owns the watch's daily_scans row for its UTC day
(tracker_seed.claim, stamped with the scan's real start) with its trigger; any scan the tick claims clears the
watch's refresh queue when it finishes. Each tick, in order:
  1. Queued refreshes (watches.refresh_queued_at, POST /v1/watches/{id}/refresh), at any hour: a `refresh` scan (an
     unseeded watch is seeded instead); a paused or deleted watch's queue is dropped. A refresh absorbs a pending
     carry (its whole plan replaces it). The queue is drained again before each step-3/4 claim.
  From TRACKER_DAILY_AT (UTC HH:MM, default 04:00) on (before it, a tick that ran no refresh returns None):
  2. Rows still open from an earlier day (a crash) finish failed.
  3. The daily re-seed of every live unseeded watch (tracker_seed.claim retry: a failed or crashed seed row of the day).
  4. A `weekly` scan of every live seeded watch whose weekly_slot is today's weekday, unless a scan of it (a row with a
     trigger) started less than tracker_view.REFRESH_COOLDOWN_H before today's TRACKER_DAILY_AT: that scan is the week's
     (today's weekly row is left to the claim, so a crashed one is taken over after tracker_seed.LEASE_H); re-checked
     right before each claim, so a refresh drained mid-tick (even past UTC midnight) is the week's scan.
  5. Pending carries due today (tracker_lanes.run_carry) and the dead-streak confirm (tracker_probe.run confirm: a
     page whose latest settled probe was its first dead one is probed once on a later day); neither owns a row.
  6. The purge, once per UTC day.
A scan's row finishes failed when the Origin probe failed, partial when it was ok but a lane_day row of its day isn't;
one watch's error fails only its own row. A row still open after tracker_seed.LEASE_H (a crash) is taken over by the
next claim of its trigger; a failed weekly or refresh row is never rerun. TRACKER_SCHEDULER=0 keeps the thread off.
scan_now (tracker_cli scan) is an operator's refresh outside the tick."""
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


def _finish(wid, day, outcome):
    """A refresh queued before the scan's claim (once claimed, POST answers with the running scan) is served by it."""
    with tdb.db() as c:
        c.execute("UPDATE daily_scans SET finished_at = ?, outcome = CASE WHEN ? = 'ok' AND EXISTS (SELECT 1 FROM "
                  "lane_day WHERE watch_id = daily_scans.watch_id AND day = daily_scans.day AND outcome != 'ok') "
                  "THEN 'partial' ELSE ? END WHERE watch_id = ? AND day = ? AND finished_at IS NULL",
                  (tdb.now(), outcome, outcome, wid, day))
        c.execute("UPDATE watches SET refresh_queued_at = NULL WHERE watch_id = ?", (wid,))


def _claimed(wid, serps, out, trigger, retry=False):
    """Claim wid's row at the real start (not the tick's) and run its scan -> True when it ran here. serps is keyed by
    UTC day: a tick crossing midnight gets the new day's sessions, serp_cache and breaker."""
    now = tdb.now_dt()
    with tdb.db() as c:
        mine = tracker_seed.claim(c, wid, now, retry=retry, trigger=trigger)
    if mine:
        _scan(wid, tdb.day(now), serps.setdefault(tdb.day(now), {}), out)
    return mine


def _drain(serps, out):
    with tdb.db() as c:
        c.execute("UPDATE watches SET refresh_queued_at = NULL WHERE refresh_queued_at IS NOT NULL AND "
                  "(paused = 1 OR deleted_at IS NOT NULL)")
        queued = [r[0] for r in c.execute(_LIVE + "AND refresh_queued_at IS NOT NULL ORDER BY refresh_queued_at, "
                                          "watch_id")]
    for wid in queued:
        out["refreshed"] += _claimed(wid, serps, out, "refresh")


def _scan(wid, today, serps, out):
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
    _finish(wid, today, outcome)


def scan_now(wid, serps):
    """Operator scan (tracker_cli scan): a `refresh` scan now, past the weekly slot and the refresh cooldown, under the
    same caps. Today's row is the only cross-process claim, so it is taken over in place once finished (or open past
    tracker_seed.LEASE_H, a crash); the scan then counts as the watch's last for the cooldown and the slot guard, like
    a refresh -> its start, None when the watch isn't live and seeded or today's row is in flight."""
    now = tdb.now_dt()
    at, today = tdb.fmt(now), tdb.day(now)
    with tdb.db() as c:
        mine = c.execute(_LIVE + "AND seeded_at IS NOT NULL AND watch_id = ?", (wid,)).fetchone() and (
            c.execute("INSERT OR IGNORE INTO daily_scans (watch_id, day, started_at, trigger) VALUES (?,?,?,'refresh')",
                      (wid, today, at)).rowcount or
            c.execute("UPDATE daily_scans SET started_at = ?, finished_at = NULL, outcome = NULL, trigger = 'refresh' "
                      "WHERE watch_id = ? AND day = ? AND (finished_at IS NOT NULL OR started_at < ?)",
                      (at, wid, today, tdb.fmt(now - timedelta(hours=tracker_seed.LEASE_H)))).rowcount)
    if not mine:
        return None
    _scan(wid, today, serps.setdefault(today, {}), dict.fromkeys(("seeded", "probed", "keys", "fetched"), 0))
    return at


def _pass(now, due):
    global _purged_day
    today, serps = tdb.day(now), {}
    out = {"seeded": 0, "probed": 0, "keys": 0, "fetched": 0, "refreshed": 0, "weekly": 0, "purged": None}
    _drain(serps, out)
    if not due:
        return out if out["refreshed"] else None
    floor = tdb.fmt(tracker_view.due_at(now) - timedelta(hours=tracker_view.REFRESH_COOLDOWN_H))
    with tdb.db() as c:
        c.execute("UPDATE daily_scans SET finished_at = ?, outcome = 'failed' WHERE finished_at IS NULL AND day < ?",
                  (tdb.now(), today))
        order = "ORDER BY created_at, watch_id"
        unseeded = [r[0] for r in c.execute(_LIVE + "AND seeded_at IS NULL " + order)]
    for wid in unseeded:
        _drain(serps, out)
        _claimed(wid, serps, out, "seed", retry=True)
    fresh = ("AND NOT EXISTS (SELECT 1 FROM daily_scans d WHERE d.watch_id = watches.watch_id AND d.trigger IS NOT NULL "
             "AND d.started_at > ? AND NOT (d.day = ? AND d.trigger = 'weekly')) ")
    with tdb.db() as c:
        slot = [r[0] for r in c.execute(_LIVE + "AND seeded_at IS NOT NULL AND weekly_slot = ? " + fresh + order,
                                        (now.weekday(), floor, today))]
    for wid in slot:
        _drain(serps, out)
        with tdb.db() as c:
            if not c.execute(_LIVE + "AND watch_id = ? " + fresh, (wid, floor, today)).fetchone():
                continue
        out["weekly"] += _claimed(wid, serps, out, "weekly")
    with tdb.db() as c:
        carried = [r[0] for r in c.execute(_LIVE + "AND carry_json IS NOT NULL " + order)]
    for wid in carried:
        try:
            tracker_lanes.run_carry(wid, today, serps.setdefault(today, {}))
        except Exception as e:
            log(f"tracker carry failed: {type(e).__name__}")
    try:
        tracker_probe.run(confirm=True)
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

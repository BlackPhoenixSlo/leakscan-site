"""Daily pass (spec "Daily pass (service)"): a daemon thread like the retention loop wakes every TICK_S; from
TRACKER_DAILY_AT (UTC HH:MM, default 04:00) on it claims the day's daily_scans row (tracker_seed.claim) for every
unpaused, undeleted watch, seeds the unseeded ones (the seed probes and finishes its own row) and runs the rest's daily
lanes one watch at a time (tracker_lanes.run_daily: the Origin probe, each url_key once a day, the Mega lookup, the
listing recheck) and finishes their rows, failed when the probe failed; one watch's error fails only its own row. Then
the Google fresh pass over those watches (tracker_lanes.run_fresh_batch; after the rows finish, since the paid batch can
outlast tracker_seed.LEASE_H), and an ok row with a partial or failed lane_day row of the day turns partial. Then the
purge, once per UTC day. Rows still open from an earlier day (a crash) finish failed; today's are taken over after
tracker_seed.LEASE_H. TRACKER_SCHEDULER=0 keeps the thread off."""
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


def _finish(ids, day, outcome):
    with tdb.db() as c:
        c.executemany("UPDATE daily_scans SET finished_at = ?, outcome = ? WHERE watch_id = ? AND day = ? AND "
                      "finished_at IS NULL", [(tdb.now(), outcome, w, day) for w in ids])


def _pass(now):
    global _purged_day
    today = tdb.day(now)
    out = {"seeded": 0, "probed": 0, "keys": 0, "fetched": 0, "purged": None}
    with tdb.db() as c:
        c.execute("UPDATE daily_scans SET finished_at = ?, outcome = 'failed' WHERE finished_at IS NULL AND day < ?",
                  (tdb.now(), today))
        live = [r[0] for r in c.execute("SELECT watch_id FROM watches WHERE paused = 0 AND deleted_at IS NULL "
                                        "ORDER BY created_at, watch_id")]
        mine = [w for w in live if tracker_seed.claim(c, w, now, retry=True)]
        unseeded = {r[0] for r in c.execute("SELECT watch_id FROM watches WHERE seeded_at IS NULL")}
    done = []
    for wid in mine:
        outcome = "failed"
        try:
            if wid in unseeded:
                out["seeded"] += bool(tracker_seed.run(wid, claimed=True))
            else:
                r = tracker_lanes.run_daily(wid, today)
                if r["probe"]:
                    out.update(probed=out["probed"] + 1, keys=out["keys"] + r["probe"]["keys"],
                               fetched=out["fetched"] + r["probe"]["fetched"])
                outcome = r["outcome"]
                if outcome != "skipped":
                    done.append(wid)
        except Exception as e:
            log(f"tracker daily watch failed: {type(e).__name__}")
        _finish([wid], today, outcome)
    try:
        tracker_lanes.run_fresh_batch(done, today)
    except Exception as e:
        log(f"tracker fresh pass failed: {type(e).__name__}")
    with tdb.db() as c:
        c.executemany("UPDATE daily_scans SET outcome = 'partial' WHERE watch_id = ? AND day = ? AND outcome = 'ok' "
                      "AND EXISTS (SELECT 1 FROM lane_day WHERE watch_id = daily_scans.watch_id AND "
                      "day = daily_scans.day AND outcome != 'ok')", [(w, today) for w in done])
    if _purged_day != today:
        _purged_day = today
        out["purged"] = tracker_purge.run(tdb.now())
    return out


def daily_pass(at=None):
    """One pass at `at` (ISO ts or aware datetime; default now) -> counts, None before TRACKER_DAILY_AT. An explicit
    `at` drives tracker_db's clock for the pass (tracker_cli daily --at, the Seam 6 tracer)."""
    at_dt = tdb.parse(at) if isinstance(at, str) else at
    if at is not None and at_dt is None:
        raise ValueError("at")
    prev, t0 = tdb._clock, time.monotonic()
    if at_dt:
        tdb.set_clock(lambda: at_dt + timedelta(seconds=time.monotonic() - t0))
    try:
        now = tdb.now_dt()
        if now < tracker_view.due_at(now):
            return None
        tdb.init()
        return _pass(now)
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

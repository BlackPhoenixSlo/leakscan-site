"""Daily pass (spec "Daily pass (service)"): a daemon thread like the retention loop wakes every TICK_S; from
TRACKER_DAILY_AT (UTC HH:MM, default 04:00) on it opens the day's daily_scans row for every unpaused, undeleted watch
that has none, seeds the unseeded ones (the seed probes and finishes its own row), probes the rest in one pass (each
url_key once) and finishes their rows; then the purge, once per UTC day. Rows still open from an earlier day (a crash)
finish failed; today's open rows are resumed. TRACKER_SCHEDULER=0 keeps the thread off."""
import os
import threading
import time
from datetime import timedelta

import tracker_db as tdb
import tracker_probe
import tracker_purge
import tracker_seed
from tracker_probe import log

DAILY_AT = os.environ.get("TRACKER_DAILY_AT", "04:00")
TICK_S = 60
_purged_day = None


def due_at(dt):
    """The day's TRACKER_DAILY_AT moment on dt's UTC day."""
    h, m = (int(x) for x in DAILY_AT.split(":"))
    return dt.replace(hour=h, minute=m, second=0, microsecond=0)


def next_check_at(dt=None):
    dt = dt or tdb.now_dt()
    at = due_at(dt)
    return tdb.fmt(at if at > dt else at + timedelta(days=1))


def _finish(ids, day, outcome):
    with tdb.db() as c:
        c.executemany("UPDATE daily_scans SET finished_at = ?, outcome = ? WHERE watch_id = ? AND day = ? AND "
                      "finished_at IS NULL", [(tdb.now(), outcome, w, day) for w in ids])


def _pass(today):
    global _purged_day
    out = {"seeded": 0, "probed": 0, "keys": 0, "fetched": 0, "purged": None}
    with tdb.db() as c:
        c.execute("UPDATE daily_scans SET finished_at = ?, outcome = 'failed' WHERE finished_at IS NULL AND day < ?",
                  (tdb.now(), today))
        live = [r[0] for r in c.execute("SELECT watch_id FROM watches WHERE paused = 0 AND deleted_at IS NULL "
                                        "ORDER BY created_at, watch_id")]
        c.executemany("INSERT OR IGNORE INTO daily_scans (watch_id, day, started_at) VALUES (?,?,?)",
                      [(w, today, tdb.now()) for w in live])
        open_ = {r[0]: r[1] for r in c.execute(
            "SELECT d.watch_id, w.seeded_at FROM daily_scans d JOIN watches w ON w.watch_id = d.watch_id WHERE d.day = ? "
            "AND d.finished_at IS NULL AND w.paused = 0 AND w.deleted_at IS NULL", (today,))}
    for wid in [w for w, seeded in open_.items() if not seeded]:
        out["seeded"] += bool(tracker_seed.run(wid))
    with tdb.db() as c:
        ids = [r[0] for r in c.execute(
            "SELECT d.watch_id FROM daily_scans d JOIN watches w ON w.watch_id = d.watch_id WHERE d.day = ? AND "
            "d.finished_at IS NULL AND w.seeded_at IS NOT NULL", (today,)) if r[0] in open_]
    with tracker_seed.claim_all(ids) as mine:
        if mine:
            try:
                r = tracker_probe.run(mine)
                out.update(probed=len(mine), keys=r["keys"], fetched=r["fetched"])
                _finish(mine, today, "ok")
            except Exception as e:
                log(f"tracker daily probe failed: {type(e).__name__}")
                _finish(mine, today, "failed")
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
        if now < due_at(now):
            return None
        tdb.init()
        return _pass(tdb.day(now))
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


def start():
    """The scheduler thread (None when TRACKER_SCHEDULER=0)."""
    if os.environ.get("TRACKER_SCHEDULER", "1") == "0":
        return None
    tdb.init()
    t = threading.Thread(target=_loop, daemon=True, name="tracker scheduler")
    t.start()
    return t

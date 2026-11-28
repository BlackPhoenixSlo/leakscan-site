"""Seed (spec "Seed (service)" 1-5): one private run of the Quick scan's candidate step (public_app.quick_candidates)
-> admitted Leaks + Pending hits, under the UTC day's daily_scans row, then the watch's first probe pass.

Admission: needles are lowercased with `_`, `.`, `-` removed (URLs percent-decoded first). A Google item passes the
host rules (tracker_rules.host_class "skip" is never a Leak nor a Pending hit) and its URL holds the handle (>= 4) or
a strong alias (>= 5). A Mega item needs its aggregator match from the handle (>= 4) or a strong alias, never a name.
Any other item naming the handle or an alias (>= 4) in its title or URL is a Pending hit. The display name is unused.
Needles, norm() and the Leak / Pending hit writes are tracker_judge's; this rule is Phase 1's, not tracker_judge.admission."""
import contextlib
import json
import os
import queue
import threading
from datetime import timedelta

import tracker_db as tdb
import tracker_judge
import tracker_lanes
import tracker_probe
import tracker_rules as rules
import tracker_view

LEASE_H = 2
MEGA_SITE = "leakshaven.com"
_LOCK = threading.Lock()
_busy = set()
_Q = queue.Queue()
_pending = set()
_workers = []


def _quick_candidates():
    return tracker_judge.app_attr("quick_candidates")


@contextlib.contextmanager
def claim_all(watch_ids):
    """-> the ids this thread now owns (seed / daily work) in this process; ids another thread holds are left out."""
    with _LOCK:
        mine = [w for w in dict.fromkeys(watch_ids) if w not in _busy]
        _busy.update(mine)
    try:
        yield mine
    finally:
        with _LOCK:
            _busy.difference_update(mine)


def start(watch_id):
    """Queue the seed on a FIFO drained by TRACKER_SEED_WORKERS (default 2) daemon threads, started on the first call,
    so a PUT burst can't run unbounded seeds at once; an id already queued or running isn't queued again. The queue is
    lost on restart (the daily pass seeds unseeded watches). Inline, returning run()'s result, when
    TRACKER_SEED_INLINE=1."""
    if os.environ.get("TRACKER_SEED_INLINE") == "1":
        return run(watch_id)
    k = max(1, int(os.environ.get("TRACKER_SEED_WORKERS") or 2))
    with _LOCK:
        if watch_id in _pending:
            return
        _pending.add(watch_id)
        if not _workers:
            _workers.extend(threading.Thread(target=_work, args=(_Q,), daemon=True, name="tracker seed")
                            for _ in range(k))
            for t in _workers:
                t.start()
        _Q.put(watch_id)
        depth, k = _Q.qsize(), len(_workers)
    if depth > k:
        tracker_probe.log(f"tracker seed queued depth={depth}")


def _work(q):
    while True:
        watch_id = q.get()
        try:
            run(watch_id)
        except Exception as e:
            tracker_probe.log(f"tracker seed worker error: {type(e).__name__}")
        finally:
            with _LOCK:
                _pending.discard(watch_id)


def admit_mega(c, watch_id, it, handle, at, first_scan=True):
    """One Mega index item (leakshaven start(source=True)) -> (admitted, pending) 0/1 counts: a Leak when its aggregator
    match came from the handle (>= HANDLE_MIN) or a strong alias, else a Pending hit. handle is norm()ed."""
    url, title, how = it.get("url") or "", it.get("title") or "", it.get("match_source")
    key, term = rules.url_key(url), tracker_judge.norm(it.get("match_term"))
    if (how == "handle" and len(handle) >= tracker_judge.HANDLE_MIN) or (
            how == "alias" and len(term) >= tracker_judge.STRONG_MIN):
        return tracker_judge.admit(c, watch_id, url, key, MEGA_SITE, "mega", title, "mega_index", at, first_scan), 0
    return 0, tracker_judge.pend(c, watch_id, url, key, title, "mega_index", at)


def _finish(watch_id, today, outcome):
    with tdb.db() as c:
        c.execute("UPDATE daily_scans SET finished_at = ?, outcome = ? WHERE watch_id = ? AND day = ?",
                  (tdb.now(), outcome, watch_id, today))
        c.execute("UPDATE watches SET refresh_queued_at = NULL WHERE watch_id = ?", (watch_id,))


def claim(c, watch_id, now_dt, retry=False, trigger="seed"):
    """Open watch_id's daily_scans row for now_dt's UTC day with `trigger` (seed | weekly | refresh): the claim on its
    scan across threads and processes -> True when the caller now holds it. A weekly or refresh claim takes over its
    own trigger's row, or a trigger-less one (from before triggers), left open over LEASE_H hours (a crash), and a
    trigger-less row that finished. retry (the daily re-seed) takes over a seed row left open over LEASE_H hours, and
    once one that failed before the day's TRACKER_DAILY_AT (Seed 5); never a weekly or refresh row."""
    at, today = tdb.fmt(now_dt), tdb.day(now_dt)
    if c.execute("INSERT OR IGNORE INTO daily_scans (watch_id, day, started_at, trigger) VALUES (?,?,?,?)",
                 (watch_id, today, at, trigger)).rowcount:
        return True
    stale, due = tdb.fmt(now_dt - timedelta(hours=LEASE_H)), tdb.fmt(tracker_view.due_at(now_dt))
    take = "UPDATE daily_scans SET started_at = ?, finished_at = NULL, outcome = NULL, trigger = ? WHERE watch_id = ? " \
           "AND day = ? AND "
    if trigger != "seed" and c.execute(
            take + "((trigger IS NULL AND finished_at IS NOT NULL) OR "
            "(COALESCE(trigger, ?) = ? AND finished_at IS NULL AND started_at < ?))",
            (at, trigger, watch_id, today, trigger, trigger, stale)).rowcount:
        return True
    return retry and c.execute(
        take + "COALESCE(trigger, 'seed') = 'seed' AND "
        "((finished_at IS NULL AND started_at < ?) OR (outcome = 'failed' AND started_at < ?))",
        (at, trigger, watch_id, today, stale, due)).rowcount == 1


def run(watch_id, claimed=False):
    """Seed one unpaused, undeleted, unseeded watch -> {admitted, pending, outcome: ok | failed}, None when skipped
    (or already running here, or its day's row is someone else's). claimed: the caller already holds the day's row.
    The row always finishes; a failed candidate step leaves seeded_at NULL (the daily pass retries)."""
    with claim_all([watch_id]) as mine:
        return _run(watch_id, claimed) if mine else None


def _run(watch_id, claimed):
    now = tdb.now_dt()
    at, today = tdb.fmt(now), tdb.day(now)
    with tdb.db() as c:
        w = c.execute("SELECT * FROM watches WHERE watch_id = ?", (watch_id,)).fetchone()
        if not w or w["deleted_at"] or w["paused"] or w["seeded_at"] or not (claimed or claim(c, watch_id, now)):
            return None
    outcome = "failed"
    try:
        out = _seed(w, at)
        outcome = out["outcome"]
        return out
    finally:
        _finish(watch_id, today, outcome)


def _seed(w, at):
    watch_id = w["watch_id"]
    aliases = [a for a in json.loads(w["aliases_json"] or "[]") if isinstance(a, str) and a.strip()]
    try:
        cand = _quick_candidates()(w["username"], aliases)
    except Exception as e:
        cand = {"google": [], "mega": [], "errors": ["unavailable", type(e).__name__]}
    if "unavailable" in cand["errors"] or (cand["errors"] and not cand["google"]):
        tracker_probe.log(f"tracker seed failed errors={len(cand['errors'])}")
        return {"admitted": 0, "pending": 0, "outcome": "failed"}
    handle, strong, weak = tracker_judge.needles(w)
    names = strong + weak
    admitted = pending = 0
    with tdb.db() as c:
        for it in cand["google"]:
            url, title = it.get("link") or "", it.get("title") or ""
            host = rules.host_of(url)
            cls = rules.host_class(host)
            if cls == "skip":
                continue
            key = tracker_judge.leak_key(url, cls)
            if any(n in tracker_judge.norm(url) for n in strong):
                if tracker_judge.admit(c, watch_id, url, key, rules.registrable_domain(host) or host, cls, title,
                                       "google_web", at):
                    admitted += 1
                    c.execute("UPDATE leaks SET google_fields_json = ? WHERE watch_id = ? AND url_key = ?",
                              (tdb.SEED_FIELDS, watch_id, key))
            elif any(n in tracker_judge.norm(title) or n in tracker_judge.norm(url) for n in names):
                pending += tracker_judge.pend(c, watch_id, url, key, title, "google_web", at)
        for it in cand["mega"]:
            a, p = admit_mega(c, watch_id, it, handle, at)
            admitted, pending = admitted + a, pending + p
        c.execute("UPDATE watches SET seeded_at = ? WHERE watch_id = ?", (at, watch_id))
    outcome = "ok" if tracker_lanes.origin_probe(w, at[:10]) is not None else "failed"
    tracker_probe.log(f"tracker seed {outcome} admitted={admitted} pending={pending}")
    return {"admitted": admitted, "pending": pending, "outcome": outcome}

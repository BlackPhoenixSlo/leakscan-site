"""Seed (spec "Seed (service)" 1-5): one private run of the Quick scan's candidate step (public_app.quick_candidates)
-> admitted Leaks + Pending hits, under the UTC day's daily_scans row, then the watch's first probe pass.

Admission: needles are lowercased with `_`, `.`, `-` removed (URLs percent-decoded first). A Google item passes the
host rules (tracker_rules.host_class "skip" is never a Leak nor a Pending hit) and its URL holds the handle (>= 4) or
a strong alias (>= 5). A Mega item needs its aggregator match from the handle (>= 4) or a strong alias, never a name.
Any other item naming the handle or an alias (>= 4) in its title or URL is a Pending hit. The display name is unused."""
import contextlib
import json
import os
import re
import sys
import threading
from datetime import timedelta
from urllib.parse import unquote

import tracker_db as tdb
import tracker_probe
import tracker_rules as rules
import tracker_view

HANDLE_MIN, STRONG_MIN = 4, 5
LEASE_H = 2
MEGA_SITE = "leakshaven.com"
_LOCK = threading.Lock()
_busy = set()


def norm(s):
    return re.sub(r"[_.\-]", "", unquote(s or "").lower())


def _quick_candidates():
    # `python3 app/public_app.py` runs as __main__: importing public_app would load a second copy of the app
    main = sys.modules.get("__main__")
    return getattr(main, "quick_candidates", None) or __import__("public_app").quick_candidates


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
    """Seed in a daemon thread (inline, returning run()'s result, when TRACKER_SEED_INLINE=1)."""
    if os.environ.get("TRACKER_SEED_INLINE") == "1":
        return run(watch_id)
    threading.Thread(target=run, args=(watch_id,), daemon=True, name="tracker seed").start()


def _admit(c, watch_id, url, key, site, kind, title, source, at, first_scan=True):
    leak_id = tdb.new_id("lk_")
    if not c.execute("INSERT OR IGNORE INTO leaks (leak_id, watch_id, url_key, url, leak_site, kind, title, created_at) "
                     "VALUES (?,?,?,?,?,?,?,?)", (leak_id, watch_id, key, url, site, kind, title, at)).rowcount:
        return 0
    tdb.add_event(c, leak_id, "seen", {"source": source, "first_scan": first_scan}, at)
    if source == "google_web":
        tdb.add_event(c, leak_id, "google_seen", None, at)
    return 1


def _pend(c, watch_id, url, key, title, source, at):
    return c.execute("INSERT OR IGNORE INTO pending_hits (watch_id, url_key, url, title, source, seen_at) "
                     "SELECT ?,?,?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM leaks WHERE watch_id = ? AND url_key = ?)",
                     (watch_id, key, url, title, source, at, watch_id, key)).rowcount


def _finish(watch_id, today, outcome):
    with tdb.db() as c:
        c.execute("UPDATE daily_scans SET finished_at = ?, outcome = ? WHERE watch_id = ? AND day = ?",
                  (tdb.now(), outcome, watch_id, today))


def claim(c, watch_id, now_dt, retry=False):
    """Open watch_id's daily_scans row for now_dt's UTC day: the claim on its seed / daily work across threads and
    processes -> True when the caller now holds it. retry (the daily pass) also takes over a row left open over LEASE_H
    hours (a crash), and once a row that failed before the day's TRACKER_DAILY_AT (Seed 5)."""
    at, today = tdb.fmt(now_dt), tdb.day(now_dt)
    if c.execute("INSERT OR IGNORE INTO daily_scans (watch_id, day, started_at) VALUES (?,?,?)",
                 (watch_id, today, at)).rowcount:
        return True
    stale, due = tdb.fmt(now_dt - timedelta(hours=LEASE_H)), tdb.fmt(tracker_view.due_at(now_dt))
    return retry and c.execute(
        "UPDATE daily_scans SET started_at = ?, finished_at = NULL, outcome = NULL WHERE watch_id = ? AND day = ? AND "
        "((finished_at IS NULL AND started_at < ?) OR (outcome = 'failed' AND started_at < ?))",
        (at, watch_id, today, stale, due)).rowcount == 1


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
    handle = norm(w["username"])
    names = [n for n in dict.fromkeys([handle, *map(norm, aliases)]) if len(n) >= HANDLE_MIN]
    strong = [n for n in names if n == handle or len(n) >= STRONG_MIN]
    admitted = pending = 0
    with tdb.db() as c:
        for it in cand["google"]:
            url, title = it.get("link") or "", it.get("title") or ""
            host = rules.host_of(url)
            cls = rules.host_class(host)
            if cls == "skip":
                continue
            key = rules.url_key(url, keep_fragment=cls != "page")
            if any(n in norm(url) for n in strong):
                admitted += _admit(c, watch_id, url, key, rules.registrable_domain(host) or host, cls, title,
                                   "google_web", at)
            elif any(n in norm(title) or n in norm(url) for n in names):
                pending += _pend(c, watch_id, url, key, title, "google_web", at)
        for it in cand["mega"]:
            url, title, how = it.get("url") or "", it.get("title") or "", it.get("match_source")
            key, term = rules.url_key(url), norm(it.get("match_term"))
            if (how == "handle" and len(handle) >= HANDLE_MIN) or (how == "alias" and len(term) >= STRONG_MIN):
                admitted += _admit(c, watch_id, url, key, MEGA_SITE, "mega", title, "mega_index", at)
            else:
                pending += _pend(c, watch_id, url, key, title, "mega_index", at)
        c.execute("UPDATE watches SET seeded_at = ? WHERE watch_id = ?", (at, watch_id))
    try:
        tracker_probe.run([watch_id])
        outcome = "ok"
    except Exception as e:
        tracker_probe.log(f"tracker seed probe failed: {type(e).__name__}")
        outcome = "failed"
    tracker_probe.log(f"tracker seed {outcome} admitted={admitted} pending={pending}")
    return {"admitted": admitted, "pending": pending, "outcome": outcome}

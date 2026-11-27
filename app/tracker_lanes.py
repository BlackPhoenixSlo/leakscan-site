"""Leak lanes (Phase 2 spec "Lanes in detail"): run_daily(watch_id, day) runs a seeded watch's daily lanes in order inside
Phase 1's daily pass (tracker_scheduler) and writes each lane's lane_state row, plus a lane_day row for the lanes Phase 2
adds. Lanes so far: origin_probe (Phase 1's probe; only its lane_state row is new), then mega_lookup. A paused or
deleted watch runs no lane (tracker_view reads its lanes `paused`). One lane failing never stops the next.

Mega lookup ($0, no reservation): the Mega index client (leakshaven) with the handle and the strong aliases (tracker_seed
norm() length >= STRONG_MIN) and names=(), so a display-name title match can never pick the Creator; the index's
deleted packs come back too. A new live pack is admitted like the seed's (tracker_seed._admit / _pend, source
mega_index); a never-known deleted one is skipped. A known pack runs the 2-dead rule on its probe_state
(consecutive_dead, first_dead, flaps, dead_since, as tracker_probe.step): deleted on two lookups in a row -> status
listed -> gone; seen live again -> gone -> listed; absent from the index's page -> nothing changes, nothing resets.
It runs at most once per watch per UTC day (an ok lane_day row), so a retried day never counts a sighting twice."""
import json

import leakshaven
import tracker_db as tdb
import tracker_probe
import tracker_rules as rules
import tracker_seed

_MEGA_OK = ("ok", "nomatch", "short")


class LaneFailed(Exception):
    pass


def _record(watch_id, day, lane, ok, at, ledger=True):
    state, reason = ("ok", None) if ok else ("failed", "lane_failed")
    with tdb.db() as c:
        c.execute("INSERT INTO lane_state (watch_id, lane, state, reason, last_attempt_at, last_success_at, next_attempt_on) "
                  "VALUES (?,?,?,?,?,?,?) ON CONFLICT (watch_id, lane) DO UPDATE SET state = excluded.state, "
                  "reason = excluded.reason, last_attempt_at = excluded.last_attempt_at, "
                  "last_success_at = COALESCE(excluded.last_success_at, lane_state.last_success_at), "
                  "next_attempt_on = excluded.next_attempt_on, trimmed_json = excluded.trimmed_json",
                  (watch_id, lane, state, reason, at, at if ok else None, tdb.plus(day + "T00:00:00Z", days=1)[:10]))
        if ledger:
            c.execute("INSERT INTO lane_day (watch_id, day, lane, outcome, reason) VALUES (?,?,?,?,?) ON CONFLICT "
                      "(watch_id, day, lane) DO UPDATE SET outcome = excluded.outcome, reason = excluded.reason",
                      (watch_id, day, lane, state, reason))


def _ran_ok(watch_id, day, lane):
    with tdb.db() as c:
        return c.execute("SELECT 1 FROM lane_day WHERE watch_id = ? AND day = ? AND lane = ? AND outcome = 'ok'",
                         (watch_id, day, lane)).fetchone() is not None


def run_daily(watch_id, day):
    """-> {"probe": tracker_probe.run()'s counts, None when it raised}; None for a paused, deleted or missing watch."""
    with tdb.db() as c:
        w = c.execute("SELECT * FROM watches WHERE watch_id = ?", (watch_id,)).fetchone()
    if not w or w["paused"] or w["deleted_at"]:
        return None
    at = tdb.now()
    try:
        probe = tracker_probe.run([watch_id])
    except Exception as e:
        probe = None
        tracker_probe.log(f"tracker origin probe failed: {type(e).__name__}")
    _record(watch_id, day, "origin_probe", probe is not None, at, ledger=False)
    if leakshaven.ENABLED and not _ran_ok(watch_id, day, "mega_lookup"):
        at = tdb.now()
        try:
            _mega(w, at)
            ok = True
        except Exception as e:
            ok = False
            tracker_probe.log(f"tracker mega lookup failed: {e if isinstance(e, LaneFailed) else type(e).__name__}")
        _record(watch_id, day, "mega_lookup", ok, at)
    return {"probe": probe}


def _mega(w, at):
    wid, handle = w["watch_id"], tracker_seed.norm(w["username"])
    strong = [a for a in json.loads(w["aliases_json"] or "[]")
              if isinstance(a, str) and len(tracker_seed.norm(a)) >= tracker_seed.STRONG_MIN]
    items, reason = leakshaven.result(leakshaven.start(w["username"], strong, (), source=True, deleted=True),
                                      leakshaven.TIMEOUT)
    if reason not in _MEGA_OK:
        raise LaneFailed(reason)
    with tdb.db() as c:
        first = c.execute("SELECT 1 FROM lane_state WHERE watch_id = ? AND lane = 'mega_lookup' AND last_success_at IS "
                          "NOT NULL", (wid,)).fetchone() is None
        for it in items:
            url, title, dead = it.get("url") or "", it.get("title") or "", it.get("status") == "deleted"
            key = rules.url_key(url)
            known = c.execute("SELECT l.leak_id AS lid, p.consecutive_dead, p.origin_status, p.first_dead, p.flaps, "
                              "p.dead_since FROM leaks l LEFT JOIN probe_state p ON p.leak_id = l.leak_id "
                              "WHERE l.watch_id = ? AND l.url_key = ? AND l.kind = 'mega'", (wid, key)).fetchone()
            if known:
                _sighting(c, known, dead, at)
                continue
            if dead:
                continue
            how, term = it.get("match_source"), tracker_seed.norm(it.get("match_term"))
            if (how == "handle" and len(handle) >= tracker_seed.HANDLE_MIN) or \
                    (how == "alias" and len(term) >= tracker_seed.STRONG_MIN):
                tracker_seed._admit(c, wid, url, key, tracker_seed.MEGA_SITE, "mega", title, "mega_index", at,
                                    first_scan=first)
            else:
                tracker_seed._pend(c, wid, url, key, title, "mega_index", at)


def _sighting(c, r, dead, at):
    n, since, origin = r["consecutive_dead"] or 0, r["dead_since"], r["origin_status"]
    first_dead, flaps, ev = r["first_dead"] or 0, r["flaps"] or 0, None
    if dead:
        n += 1
        if n == 1:
            first_dead, since = first_dead + 1, at
        if n >= 2 and origin != "gone":
            origin, ev = "gone", {"from": "listed", "to": "gone", "dead_since": since, "source": "mega_index"}
    else:
        if n == 0 and origin != "gone":
            return
        if n == 1:
            flaps += 1
        if origin == "gone":
            ev = {"from": "gone", "to": "listed", "dead_since": None, "source": "mega_index"}
        n, since, origin = 0, None, None
    c.execute("INSERT INTO probe_state (leak_id, consecutive_dead, origin_status, first_dead, flaps, dead_since) "
              "VALUES (?,?,?,?,?,?) ON CONFLICT (leak_id) DO UPDATE SET consecutive_dead = excluded.consecutive_dead, "
              "origin_status = excluded.origin_status, first_dead = excluded.first_dead, flaps = excluded.flaps, "
              "dead_since = excluded.dead_since", (r["lid"], n, origin, first_dead, flaps, since))
    if ev:
        tdb.add_event(c, r["lid"], "status", ev, at)

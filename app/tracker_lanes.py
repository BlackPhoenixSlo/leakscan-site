"""Leak lanes (Phase 2 spec "Lanes in detail"): run_daily(watch_id, day) runs a seeded watch's daily lanes in order inside
Phase 1's daily pass (tracker_scheduler) and writes each lane's lane_state row, plus a lane_day row for the lanes Phase 2
adds. Lanes so far: origin_probe (Phase 1's probe; only its lane_state row is new; the seed records it too), then
mega_lookup. A paused or deleted watch runs no lane (tracker_view reads its lanes `paused`). One lane failing never stops the next.

Mega lookup ($0, no reservation): the Mega index client (leakshaven) with the handle and the strong aliases (tracker_seed
norm() length >= STRONG_MIN) and names=(), so a display-name title match can never pick the Creator; the index's
deleted packs come back too. A new live pack is admitted like the seed's (tracker_seed.admit_mega); a never-known
deleted one is skipped. A known pack is a probe result for its probe_state (tracker_probe.record: deleted = dead,
otherwise live), so two deleted lookups in a row turn it gone and a live one turns it live (pill Listed again), each
status event with source mega_index; absent from the index's page -> nothing changes, nothing resets.
It runs at most once per watch per UTC day (an ok lane_day row): a retried day makes no second index call."""
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


def origin_probe(watch_id, day):
    """Phase 1's probe for one watch as the origin_probe lane (the daily pass and the seed) -> tracker_probe.run()'s
    counts, None when it raised; writes the lane's lane_state row either way."""
    at = tdb.now()
    try:
        probe = tracker_probe.run([watch_id])
    except Exception as e:
        probe = None
        tracker_probe.log(f"tracker origin probe failed: {type(e).__name__}")
    _record(watch_id, day, "origin_probe", probe is not None, at, ledger=False)
    return probe


def run_daily(watch_id, day):
    """-> {outcome: ok | failed (the Origin probe failed) | skipped (paused, deleted or missing), probe: counts | None}."""
    with tdb.db() as c:
        w = c.execute("SELECT * FROM watches WHERE watch_id = ?", (watch_id,)).fetchone()
    if not w or w["paused"] or w["deleted_at"]:
        return {"outcome": "skipped", "probe": None}
    probe = origin_probe(watch_id, day)
    if leakshaven.ENABLED and not _ran_ok(watch_id, day, "mega_lookup"):
        at = tdb.now()
        try:
            _mega(w, at)
            ok = True
        except Exception as e:
            ok = False
            tracker_probe.log(f"tracker mega lookup failed: {e if isinstance(e, LaneFailed) else type(e).__name__}")
        _record(watch_id, day, "mega_lookup", ok, at)
    return {"outcome": "ok" if probe is not None else "failed", "probe": probe}


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
            dead = it.get("status") == "deleted"
            known = c.execute("SELECT l.leak_id, p.* FROM leaks l LEFT JOIN probe_state p ON p.leak_id = l.leak_id "
                              "WHERE l.watch_id = ? AND l.url_key = ? AND l.kind = 'mega'",
                              (wid, rules.url_key(it.get("url") or ""))).fetchone()
            if known:
                tracker_probe.record(c, known, "dead" if dead else "live", at, source="mega_index")
            elif not dead:
                tracker_seed.admit_mega(c, wid, it, handle, at, first_scan=first)

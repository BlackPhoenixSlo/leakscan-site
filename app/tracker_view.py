"""Tracker API read model: pills, derived Leak fields and Creator rows from tracker_db rows (spec "Pill rule (service)")."""
import json
import os
from datetime import timedelta

import tracker_db

PILLS = ("live", "cached", "gone", "listed", "not_checked")
CAME_BACK_DAYS = 30
LANES = (("origin_probe", "daily"), ("mega_lookup", "daily"), ("listing_recheck", "daily"), ("google_fresh", "daily"),
         ("google_full", "weekly"), ("registry_crawl", "weekly"))


def daily_at():
    """TRACKER_DAILY_AT "HH:MM" (UTC) -> (h, m); default 04:00."""
    try:
        h, m = (int(p) for p in os.environ.get("TRACKER_DAILY_AT", "04:00").split(":"))
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except ValueError:
        pass
    return 4, 0


def due_at(dt):
    """dt's UTC day at TRACKER_DAILY_AT."""
    h, m = daily_at()
    return dt.replace(hour=h, minute=m, second=0, microsecond=0)


def next_check_at(now_dt):
    at = due_at(now_dt)
    return tracker_db.fmt(at if at > now_dt else at + timedelta(days=1))


def _events(c, leak_ids):
    out = {i: [] for i in leak_ids}
    for i in range(0, len(leak_ids), 500):
        part = leak_ids[i:i + 500]
        for r in c.execute(f"SELECT leak_id, at, type, data_json FROM leak_events WHERE leak_id IN ({','.join('?' * len(part))}) "
                           "ORDER BY id", part):
            try:
                data = json.loads(r["data_json"] or "{}")
            except ValueError:
                data = {}
            out[r["leak_id"]].append({"at": r["at"], "type": r["type"], "data": data if isinstance(data, dict) else {}})
    return out


def _probes(c, leak_ids):
    out = {}
    for i in range(0, len(leak_ids), 500):
        part = leak_ids[i:i + 500]
        out.update((r["leak_id"], r) for r in c.execute(
            f"SELECT * FROM probe_state WHERE leak_id IN ({','.join('?' * len(part))})", part))
    return out


def pill(kind, origin_status, events):
    statuses = [e for e in events if e["type"] == "status"]
    if kind != "page":
        if not statuses or statuses[-1]["data"].get("to") != "gone":
            return "listed"
        origin_status = "gone"
    if origin_status == "gone":
        return "cached" if any(e["type"] == "google_seen" for e in events) else "gone"
    return "live" if origin_status == "live" else "not_checked"


def came_back(p, events, now_dt):
    since = tracker_db.fmt(now_dt - timedelta(days=CAME_BACK_DAYS))
    return p == "live" and any(e["type"] == "status" and e["data"].get("from") == "gone" and e["data"].get("to") == "live"
                               and (e["at"] or "") >= since for e in events)


def leak(row, events, probe, now_dt):
    seen = [e for e in events if e["type"] == "seen"]
    sources = []
    for e in seen:
        s = e["data"].get("source")
        if s and s not in sources:
            sources.append(s)
    origin = probe["origin_status"] if probe else None
    p = pill(row["kind"], origin, events)
    return {"leak_id": row["leak_id"], "url": row["url"], "leak_site": row["leak_site"], "kind": row["kind"],
            "sources": sources, "title": row["title"], "pill": p, "came_back": came_back(p, events, now_dt),
            "found_on_first_scan": any(e["data"].get("first_scan") is True for e in seen),
            "first_seen_at": seen[0]["at"] if seen else row["created_at"],
            "last_up_at": probe["last_live_at"] if probe else None,
            "last_probe_at": probe["last_probe_at"] if probe else None,
            "origin_status": origin, "events": events}


def leaks(c, watch_ids, now_dt):
    """Every Leak of watch_ids, newest first_seen_at first, then leak_id; each dict carries watch_id and events."""
    if not watch_ids:
        return []
    rows = []
    for i in range(0, len(watch_ids), 500):
        part = list(watch_ids)[i:i + 500]
        rows += c.execute(f"SELECT * FROM leaks WHERE watch_id IN ({','.join('?' * len(part))})", part).fetchall()
    ids = [r["leak_id"] for r in rows]
    ev, pr = _events(c, ids), _probes(c, ids)
    out = [{"watch_id": r["watch_id"], **leak(r, ev[r["leak_id"]], pr.get(r["leak_id"]), now_dt)} for r in rows]
    out.sort(key=lambda x: x["leak_id"])
    out.sort(key=lambda x: x["first_seen_at"], reverse=True)
    return out


def creator(c, w, now_dt):
    today = tracker_db.day(now_dt)
    ls = leaks(c, [w["watch_id"]], now_dt)
    counts = {p: 0 for p in PILLS}
    for x in ls:
        counts[x["pill"]] += 1
    counts["new_today"] = sum(x["first_seen_at"][:10] == today and not x["found_on_first_scan"] for x in ls)
    counts["found_on_first_scan"] = sum(x["found_on_first_scan"] for x in ls)
    counts["came_back_30d"] = sum(x["came_back"] for x in ls)
    last = c.execute("SELECT MAX(finished_at) FROM daily_scans WHERE watch_id=? AND outcome IN ('ok', 'partial')",
                     (w["watch_id"],)).fetchone()[0]
    return {"watch_id": w["watch_id"], "account_id": w["account_id"], "paused": bool(w["paused"]),
            "paused_since": w["paused_at"] if w["paused"] else None, "seeded": w["seeded_at"] is not None,
            "last_checked_at": last, "next_check_at": next_check_at(now_dt), "counts": counts}


def lanes(c, w):
    """The drill-in's `lanes`, in LANES order: a lane with no lane_state row reads `never`; every lane of a paused watch
    reads `paused`, keeping its last success and attempt."""
    rows = {r["lane"]: r for r in c.execute("SELECT * FROM lane_state WHERE watch_id = ?", (w["watch_id"],))}
    out = []
    for lane, cadence in LANES:
        r = rows.get(lane)
        x = {"lane": lane, "cadence": cadence, "state": "never", "reason": None, "last_success_at": None,
             "last_attempt_at": None, "next_attempt_on": None, "trimmed": []}
        if r:
            x.update({k: r[k] for k in ("state", "reason", "last_success_at", "last_attempt_at", "next_attempt_on")},
                     trimmed=json.loads(r["trimmed_json"]))
        if w["paused"]:
            x.update(state="paused", reason=None, next_attempt_on=None)
        out.append(x)
    return out

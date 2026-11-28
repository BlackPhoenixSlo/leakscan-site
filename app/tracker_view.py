"""Tracker API read model: pills, derived Leak fields and Creator rows from tracker_db rows (spec "Pill rule (service)")."""
import json
import os
from datetime import timedelta

import tracker_db
import tracker_preview

PILLS = ("live", "cached", "gone", "listed", "not_checked")
CAME_BACK_DAYS = 30
OFFER_LIVE_DAYS, OFFER_NEW_DAYS = 30, 7
LANES = tuple((n, "weekly") for n in ("origin_probe", "mega_lookup", "listing_recheck", "google_full", "registry_crawl"))
REFRESH_COOLDOWN_H = 24


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


def last_scan_at(c, watch_id):
    """Start of the watch's last scan (aware dt) or None; rows without a trigger (before it existed) don't count."""
    r = c.execute("SELECT MAX(started_at) FROM daily_scans WHERE watch_id = ? AND trigger IS NOT NULL",
                  (watch_id,)).fetchone()[0]
    return tracker_db.parse(r)


def next_scan_at(slot, last, now_dt):
    """The next weekly scan start: the first `slot` weekday from now_dt's UTC day on, at TRACKER_DAILY_AT, that is at
    least REFRESH_COOLDOWN_H after the last scan start (a slot inside that window is skipped for the week); slot None
    (a watch not slotted yet) = any weekday."""
    at = due_at(now_dt)
    if last:
        t = last + timedelta(hours=REFRESH_COOLDOWN_H)
        d = due_at(t)
        at = max(at, d if d >= t else d + timedelta(days=1))
    return at + timedelta(days=(slot - at.weekday()) % 7 if slot is not None else 0)


def next_check_at(w, last, now_dt):
    """The next weekly scan start, or the pending carry's day at TRACKER_DAILY_AT when that comes first."""
    at = next_scan_at(w["weekly_slot"], last, now_dt)
    carry = json.loads(w["carry_json"] or "null")
    if carry:
        at = min(at, due_at(max(tracker_db.parse(carry["on"]), now_dt)))
    return tracker_db.fmt(at)


def in_flight(c, w):
    """A queued (watches.refresh_queued_at) or running (unfinished daily_scans row) scan -> (queued_at, started_at or
    None); None when there is neither. A running scan's queued_at is its refresh's, else its start."""
    run = c.execute("SELECT MAX(started_at) FROM daily_scans WHERE watch_id = ? AND finished_at IS NULL",
                    (w["watch_id"],)).fetchone()[0]
    queued = w["refresh_queued_at"]
    return (queued or run, run) if queued or run else None


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


def visible(events):
    """Google visibility from the last google_seen: True | False | None (unknown, also when there is none)."""
    seen = [e for e in events if e["type"] == "google_seen"]
    return tracker_db.visible_of(seen[-1]["data"]) if seen else None


def pill(kind, origin_status, events):
    """A media Leak's origin_status is its landing page Leak's (landing_probes)."""
    statuses = [e for e in events if e["type"] == "status"]
    if kind not in ("page", "media"):
        if not statuses or statuses[-1]["data"].get("to") != "gone":
            return "listed"
        origin_status = "gone"
    if origin_status == "gone":
        return "cached" if visible(events) is True else "gone"
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
            "origin_status": origin, "preview": preview_of(None, row, events), "events": events}


def preview_of(c, row, events=None):
    """A leaks row's `preview` from its events (read through c when not given)."""
    if events is None:
        events = _events(c, [row["leak_id"]])[row["leak_id"]]
    return tracker_preview.preview(row, visible(events))


def landing_probes(rows, probes):
    """probes {leak_id: probe_state} with each media row's entry replaced by its landing page Leak's (same watch,
    url_key = landing_key), absent when that Leak is unknown or unprobed: a media Leak is never probed itself."""
    by_key = {(r["watch_id"], r["url_key"]): r["leak_id"] for r in rows}
    out = dict(probes)
    for r in rows:
        if r["kind"] == "media":
            out.pop(r["leak_id"], None)
            landing = probes.get(by_key.get((r["watch_id"], r["landing_key"])))
            if landing:
                out[r["leak_id"]] = landing
    return out


def leaks(c, watch_ids, now_dt):
    """Every Leak of watch_ids, newest first_seen_at first, then leak_id; each dict carries watch_id and events."""
    if not watch_ids:
        return []
    rows = []
    for i in range(0, len(watch_ids), 500):
        part = list(watch_ids)[i:i + 500]
        rows += c.execute(f"SELECT * FROM leaks WHERE watch_id IN ({','.join('?' * len(part))})", part).fetchall()
    ids = [r["leak_id"] for r in rows]
    ev, pr = _events(c, ids), landing_probes(rows, _probes(c, ids))
    out = [{"watch_id": r["watch_id"], **leak(r, ev[r["leak_id"]], pr.get(r["leak_id"]), now_dt)} for r in rows]
    out.sort(key=lambda x: x["leak_id"])
    out.sort(key=lambda x: x["first_seen_at"], reverse=True)
    return out


def _changed(ls, since, to, fr=None):
    return sum(any(e["type"] == "status" and (e["at"] or "")[:10] >= since and e["data"].get("to") == to
                   and (fr is None or e["data"].get("from") == fr) for e in x["events"])
               for x in ls)


def week_state(c, w, now_dt, last):
    """this_week.state (spec ticket 83), first match wins: paused; pending while a scan is queued or running, or on the
    slot day before its scan starts (unless skipped); the latest finished scan of the 7-day window by its outcome and its
    day's lane_day rows; pending when no scan ever finished; else complete."""
    wid = w["watch_id"]
    if w["paused"]:
        return "paused"
    if in_flight(c, w) or (w["seeded_at"] and w["weekly_slot"] is not None
                           and next_scan_at(w["weekly_slot"], last, now_dt) == due_at(now_dt)):
        return "pending"
    scan = c.execute("SELECT day, outcome FROM daily_scans WHERE watch_id = ? AND finished_at IS NOT NULL AND day >= ? "
                     "ORDER BY started_at DESC LIMIT 1", (wid, tracker_db.day(now_dt - timedelta(days=6)))).fetchone()
    if not scan:
        ever = c.execute("SELECT 1 FROM daily_scans WHERE watch_id = ? AND finished_at IS NOT NULL", (wid,)).fetchone()
        return "complete" if ever else "pending"
    reasons = {r[0] for r in c.execute("SELECT reason FROM lane_day WHERE watch_id = ? AND day = ? AND outcome != 'ok'",
                                       (wid, scan["day"]))}
    if scan["outcome"] in ("failed", "skipped") or reasons - {"google_failed"}:
        return "partial"
    return "coverage_reduced" if reasons else "complete"


def offer_counts(ls, counts, now_dt):
    old, week = tracker_db.fmt(now_dt - timedelta(days=OFFER_LIVE_DAYS)), tracker_db.day(now_dt - timedelta(days=OFFER_NEW_DAYS - 1))
    return {"visible": counts["live"] + counts["cached"], "came_back_30d": counts["came_back_30d"], "cached": counts["cached"],
            "live_30d": sum(x["pill"] == "live" and x["first_seen_at"] <= old for x in ls),
            # owner default 2026-11-28: a media Leak is its landing's twin, never a second new one
            "new_7d": sum(not x["found_on_first_scan"] and x["kind"] != "media" and x["first_seen_at"][:10] >= week
                          for x in ls)}


def creator(c, w, now_dt, ls):
    today = tracker_db.day(now_dt)
    counts = {p: 0 for p in PILLS}
    for x in ls:
        counts[x["pill"]] += 1
    found = [x["found_on_first_scan"] for x in ls if x["first_seen_at"][:10] == today]
    counts["new_today"] = found.count(False)
    counts["found_on_first_scan"] = sum(x["found_on_first_scan"] for x in ls)
    counts["came_back_30d"] = sum(x["came_back"] for x in ls)
    first, last = c.execute("SELECT MIN(finished_at), MAX(finished_at) FROM daily_scans WHERE watch_id=? "
                            "AND outcome IN ('ok', 'partial')", (w["watch_id"],)).fetchone()
    started, since = last_scan_at(c, w["watch_id"]), tracker_db.day(now_dt - timedelta(days=OFFER_NEW_DAYS - 1))
    offer = offer_counts(ls, counts, now_dt)
    # a watch with no scan yet (created paused, then resumed) can be refreshed right away
    refresh_at = None if w["paused"] else tracker_db.fmt(started + timedelta(hours=REFRESH_COOLDOWN_H)) if started \
        else w["created_at"]
    return {"watch_id": w["watch_id"], "account_id": w["account_id"], "paused": bool(w["paused"]),
            "paused_since": w["paused_at"] if w["paused"] else None, "seeded": w["seeded_at"] is not None,
            "last_checked_at": last, "next_check_at": next_check_at(w, started, now_dt), "next_refresh_at": refresh_at,
            "counts": counts,
            "this_week": {"since": since, "state": week_state(c, w, now_dt, started), "new": offer["new_7d"],
                          "first_scan": sum(x["found_on_first_scan"] and x["first_seen_at"][:10] >= since for x in ls), "came_back": _changed(ls, since, "live", "gone"),
                          "gone": _changed(ls, since, "gone")},
            "service_status": "none", "service_status_since": None, "removal": None, "offer_counts": offer,
            "first_daily_at": first}


def preview_leak(ls):
    """The most recently seen Live page Leak, else None."""
    live = sorted((x for x in ls if x["kind"] == "page" and x["pill"] == "live"), key=lambda x: x["leak_id"])
    if not live:
        return None
    x = max(live, key=lambda x: max((e["at"] for e in x["events"] if e["type"] == "seen"), default=x["first_seen_at"]))
    return {"leak_id": x["leak_id"], "leak_site": x["leak_site"], "kind": x["kind"], "title": x["title"], "pill": x["pill"],
            "first_seen_at": x["first_seen_at"], "preview": None}


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

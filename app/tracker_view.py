"""Tracker API read model: pills, derived Leak fields and Creator rows from tracker_db rows (spec "Pill rule (service)")."""
import json
import os
from datetime import timedelta

import tracker_db

PILLS = ("live", "cached", "gone", "listed", "not_checked")
CAME_BACK_DAYS = 30
TAKEN_DOWN_MAX = 6
OFFER_LIVE_DAYS, OFFER_NEW_DAYS = 30, 7
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


def visible(events):
    """Google visibility from the last google_seen: True | False | None (unknown, also when there is none)."""
    seen = [e for e in events if e["type"] == "google_seen"]
    return tracker_db.visible_of(seen[-1]["data"]) if seen else None


def pill(kind, origin_status, events):
    statuses = [e for e in events if e["type"] == "status"]
    if kind != "page":
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


def _changed(ls, day, to, fr=None):
    return sum(any(e["type"] == "status" and (e["at"] or "")[:10] == day and e["data"].get("to") == to
                   and (fr is None or e["data"].get("from") == fr) for e in x["events"])
               for x in ls)


def day_state(c, w, day):
    """pending = no finished daily_scans row for day; the paid batches run after it finishes."""
    if w["paused"]:
        return "paused"
    scan = c.execute("SELECT finished_at, outcome FROM daily_scans WHERE watch_id = ? AND day = ?",
                     (w["watch_id"], day)).fetchone()
    if not scan or scan["finished_at"] is None:
        return "pending"
    reasons = {r[0] for r in c.execute("SELECT reason FROM lane_day WHERE watch_id = ? AND day = ? AND outcome != 'ok'",
                                       (w["watch_id"], day))}
    if scan["outcome"] in ("failed", "skipped") or reasons - {"google_failed"}:
        return "partial"
    return "coverage_reduced" if reasons else "complete"


def offer_counts(ls, counts, now_dt):
    old, week = tracker_db.fmt(now_dt - timedelta(days=OFFER_LIVE_DAYS)), tracker_db.day(now_dt - timedelta(days=OFFER_NEW_DAYS - 1))
    return {"visible": counts["live"] + counts["cached"], "came_back_30d": counts["came_back_30d"], "cached": counts["cached"],
            "live_30d": sum(x["pill"] == "live" and x["first_seen_at"] <= old for x in ls),
            "new_7d": sum(not x["found_on_first_scan"] and x["first_seen_at"][:10] >= week for x in ls)}


def creator(c, w, now_dt, ls=None):
    today = tracker_db.day(now_dt)
    ls = leaks(c, [w["watch_id"]], now_dt) if ls is None else ls
    counts = {p: 0 for p in PILLS}
    for x in ls:
        counts[x["pill"]] += 1
    found = [x["found_on_first_scan"] for x in ls if x["first_seen_at"][:10] == today]
    counts["new_today"] = found.count(False)
    counts["found_on_first_scan"] = sum(x["found_on_first_scan"] for x in ls)
    counts["came_back_30d"] = sum(x["came_back"] for x in ls)
    first, last = c.execute("SELECT MIN(finished_at), MAX(finished_at) FROM daily_scans WHERE watch_id=? "
                            "AND outcome IN ('ok', 'partial')", (w["watch_id"],)).fetchone()
    return {"watch_id": w["watch_id"], "account_id": w["account_id"], "paused": bool(w["paused"]),
            "paused_since": w["paused_at"] if w["paused"] else None, "seeded": w["seeded_at"] is not None,
            "last_checked_at": last, "next_check_at": next_check_at(now_dt), "counts": counts,
            "today": {"day": today, "state": day_state(c, w, today), "new": counts["new_today"], "first_scan": found.count(True),
                      "came_back": _changed(ls, today, "live", "gone"), "gone": _changed(ls, today, "gone")},
            "service_status": "none", "service_status_since": None, "removal": None, "offer_counts": offer_counts(ls, counts, now_dt),
            "first_daily_at": first}


def _gone_at(events):
    return next((e["at"] for e in reversed(events) if e["type"] == "status" and e["data"].get("to") == "gone"), None)


def taken_down(ls, service_status):
    """`active`/`former` only: Gone-pill Leaks with gone_after_notice, newest current gone event first, then leak_id."""
    if service_status not in ("active", "former"):
        return None
    out = [{"leak_id": x["leak_id"], "leak_site": x["leak_site"], "kind": x["kind"], "title": x["title"],
            "gone_at": _gone_at(x["events"]), "preview": x.get("preview")}
           for x in ls if x.get("gone_after_notice") is True and x["pill"] == "gone"]
    out.sort(key=lambda x: x["leak_id"])
    out.sort(key=lambda x: x["gone_at"] or "", reverse=True)
    return out[:TAKEN_DOWN_MAX]


def preview_leak(ls):
    """The Visible Leak with the newest preview seen_at, else the most recently seen Live page Leak, else None."""
    ls = sorted(ls, key=lambda x: x["leak_id"])
    pv = [x for x in ls if x["pill"] in ("live", "cached") and (x.get("preview") or {}).get("seen_at")]
    if pv:
        x = max(pv, key=lambda x: x["preview"]["seen_at"])
    else:
        live = [x for x in ls if x["kind"] == "page" and x["pill"] == "live"]
        if not live:
            return None
        x = max(live, key=lambda x: max((e["at"] for e in x["events"] if e["type"] == "seen"), default=x["first_seen_at"]))
    return {"leak_id": x["leak_id"], "leak_site": x["leak_site"], "kind": x["kind"], "title": x["title"], "pill": x["pill"],
            "first_seen_at": x["first_seen_at"], "preview": x.get("preview")}


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

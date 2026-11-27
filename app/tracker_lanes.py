"""Leak lanes (Phase 2 spec "Lanes in detail"): run_daily(watch_id, day) runs a seeded watch's daily lanes in order inside
Phase 1's daily pass (tracker_scheduler) and writes each lane's lane_state row, plus a lane_day row for the lanes Phase 2
adds. Lanes so far: origin_probe (Phase 1's probe; only its lane_state row is new; the seed records it too), then
mega_lookup, then listing_recheck. A paused or deleted watch runs no lane (tracker_view reads its lanes `paused`). One
lane failing never stops the next. Each added lane runs at most once per watch per UTC day (a non-failed lane_day row).

Mega lookup ($0, no reservation): the Mega index client (leakshaven) with the handle and the strong aliases (tracker_seed
norm() length >= STRONG_MIN) and names=(), so a display-name title match can never pick the Creator; the index's
deleted packs come back too. A new live pack is admitted like the seed's (tracker_seed.admit_mega); a never-known
deleted one is skipped. A known pack is a probe result for its probe_state (tracker_probe.record: deleted = dead,
otherwise live), so two deleted lookups in a row turn it gone and a live one turns it live (pill Listed again), each
status event with source mega_index; absent from the index's page -> nothing changes, nothing resets.

Listing recheck ($0, no reservation, runs over any cap): the watch's `page` Leaks that the detection map (MAP_FILE) classes
as a Creator listing (is_listing), at most LISTING_MAX a day, oldest leaks.recheck_at first; page 1 of each over plain
HTTP (tracker_probe's fetcher: its public-address rule, 15 s, <= 5 redirects, body <= 2 MB) behind the leak crawler's
per-host throttle. Every same-site anchor that isn't media, a listing or the page itself is a hit for
tracker_judge.admit_hit with source site_search. More listings than LISTING_MAX -> lane `reduced`, reason
listing_rotated (lane_day `partial`); no listing answering at all -> `failed`.
A Leak a lane admits on its first-ever successful run for the watch is a first-scan find (seen.first_scan)."""
import functools
import html as _html
import json
import os
import re
from urllib.parse import parse_qsl, urljoin, urlsplit

import leak_crawler
import leakshaven
import tracker_db as tdb
import tracker_judge
import tracker_pagekind
import tracker_probe
import tracker_rules as rules
import tracker_seed

_MEGA_OK = ("ok", "nomatch", "short")
MAP_FILE = os.path.join(tdb.HERE, "bruqi_detection_map.json")
LISTING_MAX = 20
LISTING_BODY = 2 * 1024 * 1024
LISTING_GAP = 0.4
_ANCHOR = re.compile(r"""<a\b[^>]*?\bhref\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_OUTCOME = {"ok": "ok", "reduced": "partial", "failed": "failed"}


class LaneFailed(Exception):
    pass


def _record(watch_id, day, lane, at, state="ok", reason=None, ledger=True):
    with tdb.db() as c:
        c.execute("INSERT INTO lane_state (watch_id, lane, state, reason, last_attempt_at, last_success_at, next_attempt_on) "
                  "VALUES (?,?,?,?,?,?,?) ON CONFLICT (watch_id, lane) DO UPDATE SET state = excluded.state, "
                  "reason = excluded.reason, last_attempt_at = excluded.last_attempt_at, "
                  "last_success_at = COALESCE(excluded.last_success_at, lane_state.last_success_at), "
                  "next_attempt_on = excluded.next_attempt_on, trimmed_json = excluded.trimmed_json",
                  (watch_id, lane, state, reason, at, None if state == "failed" else at,
                   tdb.plus(day + "T00:00:00Z", days=1)[:10]))
        if ledger:
            c.execute("INSERT INTO lane_day (watch_id, day, lane, outcome, reason) VALUES (?,?,?,?,?) ON CONFLICT "
                      "(watch_id, day, lane) DO UPDATE SET outcome = excluded.outcome, reason = excluded.reason",
                      (watch_id, day, lane, _OUTCOME[state], reason))


def _ran(watch_id, day, lane):
    with tdb.db() as c:
        return c.execute("SELECT 1 FROM lane_day WHERE watch_id = ? AND day = ? AND lane = ? AND outcome != 'failed'",
                         (watch_id, day, lane)).fetchone() is not None


def _first(c, watch_id, lane):
    return c.execute("SELECT 1 FROM lane_state WHERE watch_id = ? AND lane = ? AND last_success_at IS NOT NULL",
                     (watch_id, lane)).fetchone() is None


def _lane(w, day, lane, fn):
    """fn(w, at) -> None (ok) | a `reduced` reason; a raise -> failed / lane_failed."""
    at = tdb.now()
    try:
        reason = fn(w, at)
        state = "reduced" if reason else "ok"
    except Exception as e:
        state, reason = "failed", "lane_failed"
        tracker_probe.log(f"tracker {lane} failed: {e if isinstance(e, LaneFailed) else type(e).__name__}")
    _record(w["watch_id"], day, lane, at, state, reason)


def origin_probe(watch_id, day):
    """Phase 1's probe for one watch as the origin_probe lane (the daily pass and the seed) -> tracker_probe.run()'s
    counts, None when it raised; writes the lane's lane_state row either way."""
    at = tdb.now()
    try:
        probe = tracker_probe.run([watch_id])
    except Exception as e:
        probe = None
        tracker_probe.log(f"tracker origin probe failed: {type(e).__name__}")
    _record(watch_id, day, "origin_probe", at, *(("ok",) if probe is not None else ("failed", "lane_failed")),
            ledger=False)
    return probe


def run_daily(watch_id, day):
    """-> {outcome: ok | failed (the Origin probe failed) | skipped (paused, deleted or missing), probe: counts | None}."""
    with tdb.db() as c:
        w = c.execute("SELECT * FROM watches WHERE watch_id = ?", (watch_id,)).fetchone()
    if not w or w["paused"] or w["deleted_at"]:
        return {"outcome": "skipped", "probe": None}
    probe = origin_probe(watch_id, day)
    if leakshaven.ENABLED and not _ran(watch_id, day, "mega_lookup"):
        _lane(w, day, "mega_lookup", _mega)
    if not _ran(watch_id, day, "listing_recheck"):
        _lane(w, day, "listing_recheck", _recheck)
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
        first = _first(c, wid, "mega_lookup")
        for it in items:
            dead = it.get("status") == "deleted"
            known = c.execute("SELECT l.leak_id, p.* FROM leaks l LEFT JOIN probe_state p ON p.leak_id = l.leak_id "
                              "WHERE l.watch_id = ? AND l.url_key = ? AND l.kind = 'mega'",
                              (wid, rules.url_key(it.get("url") or ""))).fetchone()
            if known:
                tracker_probe.record(c, known, "dead" if dead else "live", at, source="mega_index")
            elif not dead:
                tracker_seed.admit_mega(c, wid, it, handle, at, first_scan=first)


@functools.lru_cache(maxsize=4)
def _patterns(path):
    """detection map -> {domain: [(path regex with group n, query key | None)]}: each host's profile template and check
    URL (leak_crawler.listing_urls_for's page-1 listings) that carry {name}."""
    with open(path, encoding="utf-8") as fh:
        dmap = json.load(fh)
    out = {}
    for dom, info in dmap.items():
        if not isinstance(info, dict) or not info.get("check_url"):
            continue
        for t in {leak_crawler.profile_template(info), info["check_url"]} - {None}:
            p = urlsplit(t)
            rx = re.escape(p.path.rstrip("/")).replace(r"\{lang\}", "[^/]+")
            key = next((k for k, v in parse_qsl(p.query) if v == "{name}"), None)
            if "{name}" in p.path and not key:
                out.setdefault(dom, []).append((re.compile(rx.replace(r"\{name\}", "(?P<n>[^/]+)", 1) + "/?"), None))
            elif key and "{name}" not in p.path:
                out.setdefault(dom, []).append((re.compile(rx + "/?"), key))
    return out


def is_listing(url, names):
    """True when the detection map's pattern for url's host classes it as a listing whose name holds one of names
    (norm()ed handle / strong aliases)."""
    try:
        p = urlsplit(url)
        host = (p.hostname or "").removeprefix("www.")
    except ValueError:
        return False
    pats, dmap = None, _patterns(MAP_FILE)
    while host and pats is None:
        pats, host = dmap.get(host), host.partition(".")[2] if "." in host else ""
    for rx, key in pats or ():
        m = rx.fullmatch(p.path)
        if m:
            name = dict(parse_qsl(p.query)).get(key, "") if key else m.group("n")
            if any(n in tracker_seed.norm(name) for n in names):
                return True
    return False


def _hits(base, body, names):
    """Same-site anchors on a listing page -> [(url, text)], minus media, listings and the page itself."""
    site, seen, out = rules.registrable_domain(rules.host_of(base)), {rules.url_key(base)}, []
    for href, text in _ANCHOR.findall(body or ""):
        try:
            u = urljoin(base, _html.unescape(href.strip()))
        except ValueError:
            continue
        key = rules.url_key(u)
        if (key in seen or urlsplit(u).scheme not in ("http", "https")
                or rules.registrable_domain(rules.host_of(u)) != site or rules.is_media_url(u)
                or tracker_pagekind.url_kind(u) in tracker_pagekind.LISTING_KINDS or is_listing(u, names)):
            continue
        seen.add(key)
        out.append((u, re.sub(r"\s+", " ", _html.unescape(_TAG.sub(" ", text))).strip()[:200]))
    return out


def _recheck(w, at):
    wid, names = w["watch_id"], tracker_judge.needles(w)[1]
    with tdb.db() as c:
        rows = c.execute("SELECT leak_id, url FROM leaks WHERE watch_id = ? AND kind = 'page' "
                         "ORDER BY recheck_at, created_at, rowid", (wid,)).fetchall()
        first = _first(c, wid, "listing_recheck")
    todo = [r for r in rows if is_listing(r["url"], names)]
    fetch, answered = tracker_probe.fetcher(max_body=LISTING_BODY), 0
    for r in todo[:LISTING_MAX]:
        url = r["url"].partition("#")[0]
        leak_crawler._throttle(urlsplit(url).netloc, LISTING_GAP)
        try:
            status, body = fetch(url)
        except Exception:
            status, body = 0, ""
        answered += bool(status)
        with tdb.db() as c:
            c.execute("UPDATE leaks SET recheck_at = ? WHERE leak_id = ?", (at, r["leak_id"]))
            if status == 200:
                for u, title in _hits(url, body, names):
                    tracker_judge.admit_hit(c, w, u, title, "site_search", at, first_scan=first)
    if todo and not answered:
        raise LaneFailed("no listing answered")
    return "listing_rotated" if len(todo) > LISTING_MAX else None

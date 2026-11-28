"""Leak lanes (Phase 2 spec "Lanes in detail", cadence spec slice A): run_scan(watch_id, day, serps) is one scan of a
seeded watch (tracker_scheduler: a weekly slot scan or a refresh): every lane in order, each writing its lane_state row
(next_attempt_on: the watch's next weekly scan day, tracker_view.next_scan_at) plus a lane_day row for the lanes Phase 2
adds. Lanes so far: origin_probe (Phase 1's probe; only its lane_state row is new; the seed records it too), then
mega_lookup, listing_recheck and google_full; registry_crawl is listed (tracker_view.LANES) but not built yet.
run_carry runs only a pending carry's pages on its day. A paused or deleted watch runs no lane (tracker_view reads its
lanes `paused`). One lane failing never stops the next.

Mega lookup ($0, no reservation): the Mega index client (leakshaven) with the handle and the strong aliases (tracker_judge
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
A Leak a lane admits on its first-ever successful run for the watch is a first-scan find (seen.first_scan); for the
listing recheck, so is one found on a listing never rechecked before (leaks.recheck_at NULL).

Google full pass (paid, in every scan, and run_carry on a carry's day): runs for every tenant (owner 2026-11-28;
`tracker_cli caps global --daily-loads 0` stops it). Browserbase creds: the host's BROWSERBASE_API_KEY
/ BROWSERBASE_PROJECT_ID for TRACKER_UNCAPPED_TENANTS, the tenant's own (tracker_cli tenant bb) for every other; none ->
`waiting` / no_browserbase_key, no lane_day row; a watch whose tenant row is missing is skipped. One _Serp per creds
across a tick's watches (tracker_serp.Session, so a session never serves two keys; it rotates at serp.ROTATE_S old),
serp_cache by (UTC day, vertical, text, page, since '') first: a hit reuses the links and reserves nothing. Each vertical
blocks its own assets (tracker_serp.BLOCKED); an empty page counts only with Google's no-results wording. A load is
consumed before every navigation; a wall (tracker_serp.WALLS) ends the session and retries once in a fresh one while
the hold has a load left; a second wall, a failed load or a results page without links is an incomplete page (`reduced`
/ google_failed, lane_day partial). Breaker: a failed create, or BREAKER incomplete pages in a row, and the creds'
remaining misses get no reservation and no session. tracker_plan.build()'s misses + FULL_RETRIES (wall retries) are
reserved with a partial grant; a short grant trims the plan (Plan.trim) to what fits, the dropped fields go to
lane_state.trimmed (lane `reduced`, the cap's reason, lane_day partial); refused -> `waiting` with the cap's reason (a
gone watch records nothing); the watch is never paused. A scan's run (the whole plan) cut by cap_global /
cap_tenant_month writes watches.carry_json: its cut pages run once on the cap's next_on (next UTC day / the 1st), never
carried again; a later scan absorbs a pending carry (runs the whole plan, replaces the carry). Result links go through
tracker_judge.admit_hit with source google_web (a /goto link is dropped); no other engine is called. Each returned
link's (vertical, field) pairs join leaks.google_fields_json. Only a run that searched (a page completed, breaker intact) touches visibility: one that
completed every planned pair of a Leak and returned none marks it not visible (google_seen visible false), a set
emptied by fields leaving the identity unknown (null); a tripped breaker only adds pairs. A run with a completed page
ends the first-scan baseline, which a trimmed scan hands to its carry run."""
import functools
import html as _html
import json
import os
import re
from dataclasses import replace
from urllib.parse import parse_qsl, urljoin, urlsplit

import leak_crawler
import leakshaven
import tracker_budget
import tracker_db as tdb
import tracker_judge
import tracker_pagekind
import tracker_plan
import tracker_preview
import tracker_probe
import tracker_rules as rules
import tracker_seed
import tracker_serp as serp
import tracker_view

_MEGA_OK = ("ok", "nomatch", "short")
MAP_FILE = os.path.join(tdb.HERE, "bruqi_detection_map.json")
LISTING_MAX = 20
LISTING_BODY = 2 * 1024 * 1024
LISTING_GAP = 0.4
_ANCHOR = re.compile(r"""<a\b[^>]*?\bhref\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_OUTCOME = {"ok": "ok", "reduced": "partial", "failed": "failed", "waiting": "partial"}
BREAKER = 3
FULL = tracker_plan.LANE
FULL_RETRIES = 2


class LaneFailed(Exception):
    pass


_KEEP = object()


def _record(watch_id, day, lane, at, state="ok", reason=None, ledger=True, next_on=None, success=None, trimmed=(),
            carry=_KEEP):
    """next_on None = the next UTC day; success None = state ok or reduced; trimmed = [{field, value}] skipped; carry
    (a JSON string or None) replaces watches.carry_json in the same transaction."""
    reason = reason or ("lane_failed" if state == "failed" else None)
    success = state in ("ok", "reduced") if success is None else success
    next_on = next_on or tdb.plus(day + "T00:00:00Z", days=1)[:10]
    with tdb.db() as c:
        c.execute("INSERT INTO lane_state (watch_id, lane, state, reason, last_attempt_at, last_success_at, next_attempt_on, "
                  "trimmed_json) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT (watch_id, lane) DO UPDATE SET state = excluded.state, "
                  "reason = excluded.reason, last_attempt_at = excluded.last_attempt_at, "
                  "last_success_at = COALESCE(excluded.last_success_at, lane_state.last_success_at), "
                  "next_attempt_on = excluded.next_attempt_on, trimmed_json = excluded.trimmed_json",
                  (watch_id, lane, state, reason, at, at if success else None, next_on, json.dumps(list(trimmed))))
        if carry is not _KEEP:
            c.execute("UPDATE watches SET carry_json = ? WHERE watch_id = ?", (carry, watch_id))
        if ledger:
            c.execute("INSERT INTO lane_day (watch_id, day, lane, outcome, reason) VALUES (?,?,?,?,?) ON CONFLICT "
                      "(watch_id, day, lane) DO UPDATE SET outcome = excluded.outcome, reason = excluded.reason",
                      (watch_id, day, lane, _OUTCOME[state], reason))


def _next_scan(w, at):
    """next_attempt_on of a lane run at `at`: the watch's next weekly scan day after a scan starting then."""
    return tracker_view.next_scan_at(w["weekly_slot"], tdb.parse(at), tdb.parse(at)).date().isoformat()


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
        state, reason = "failed", None
        tracker_probe.log(f"tracker {lane} failed: {e if isinstance(e, LaneFailed) else type(e).__name__}")
    _record(w["watch_id"], day, lane, at, state, reason, next_on=_next_scan(w, at))


def origin_probe(w, day):
    """Phase 1's probe for watch row w as the origin_probe lane (a scan and the seed) -> tracker_probe.run()'s counts,
    None when it raised; writes the lane's lane_state row either way."""
    at = tdb.now()
    try:
        probe = tracker_probe.run([w["watch_id"]])
    except Exception as e:
        probe = None
        tracker_probe.log(f"tracker origin probe failed: {type(e).__name__}")
    _record(w["watch_id"], day, "origin_probe", at, "ok" if probe is not None else "failed", ledger=False,
            next_on=_next_scan(w, at))
    return probe


def run_scan(watch_id, day, serps):
    """One scan of a watch, every lane in order; serps {creds: _Serp} is shared across a tick's watches -> {outcome: ok
    | failed (the Origin probe failed) | skipped (paused, deleted or missing), probe: counts | None}."""
    with tdb.db() as c:
        w = c.execute("SELECT * FROM watches WHERE watch_id = ?", (watch_id,)).fetchone()
    if not w or w["paused"] or w["deleted_at"]:
        return {"outcome": "skipped", "probe": None}
    probe = origin_probe(w, day)
    if leakshaven.ENABLED:
        _lane(w, day, "mega_lookup", _mega)
    _lane(w, day, "listing_recheck", _recheck)
    _full_lane(w, day, serps, True)
    return {"outcome": "ok" if probe is not None else "failed", "probe": probe}


def run_carry(watch_id, day, serps):
    """A pending carry's pages on (or after) its day, once a day (a failed run retries on the next tick) -> True when
    it ran."""
    with tdb.db() as c:
        w = c.execute("SELECT * FROM watches WHERE watch_id = ?", (watch_id,)).fetchone()
    carry = json.loads(w["carry_json"] or "null") if w else None
    if not carry or carry["on"] > day or w["paused"] or w["deleted_at"] or not w["seeded_at"] or _ran(watch_id, day, FULL):
        return False
    _full_lane(w, day, serps, False)
    return True


def _full_lane(w, day, serps, whole):
    try:
        _full(w, day, serps, whole)
    except Exception as e:
        tracker_probe.log(f"tracker {FULL} failed: {type(e).__name__}")
        at = tdb.now()
        _record(w["watch_id"], day, FULL, at, "failed", next_on=_next_scan(w, at))


def _mega(w, at):
    wid, handle = w["watch_id"], tracker_judge.norm(w["username"])
    strong = [a for a in json.loads(w["aliases_json"] or "[]")
              if isinstance(a, str) and len(tracker_judge.norm(a)) >= tracker_judge.STRONG_MIN]
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
            if any(n in tracker_judge.norm(name) for n in names):
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
        rows = c.execute("SELECT leak_id, url, recheck_at FROM leaks WHERE watch_id = ? AND kind = 'page' "
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
                    tracker_judge.admit_hit(c, w, u, title, "site_search", at,
                                            first_scan=first or r["recheck_at"] is None)
    if todo and not answered:
        raise LaneFailed("no listing answered")
    return "listing_rotated" if len(todo) > LISTING_MAX else None


def _creds(c, w, uncapped, lane):
    """-> the watch's Browserbase (key, project), () when it has none, None (logged) when its tenant row is missing."""
    t = c.execute("SELECT bb_key, bb_project FROM tenants WHERE tenant_id = ?", (w["tenant_id"],)).fetchone()
    if not t:
        tracker_probe.log(f"tracker {lane} skipped {w['watch_id']}: no tenant row")
        return None
    creds = (os.environ.get("BROWSERBASE_API_KEY", ""), os.environ.get("BROWSERBASE_PROJECT_ID", "")) \
        if w["tenant_id"] in uncapped else tuple(t)
    return creds if all(creds) else ()


class _Serp:
    """Browserbase sessions on one creds for a UTC day, the day's serp_cache, and the breaker: a failed create, or
    BREAKER incomplete searches in a row, and every later miss gets no reservation and no session (broken)."""

    def __init__(self, creds, day):
        self.creds, self.day, self.session, self.fails, self.broken = creds, day, None, 0, False

    def drop(self):
        if self.session:
            self.session.release()
        self.session = None

    def cached(self, q, since):
        with tdb.db() as c:
            row = c.execute("SELECT results_json FROM serp_cache WHERE day = ? AND vertical = ? AND text = ? AND "
                            "page = ? AND since = ?", (self.day, q.vertical, q.text, q.start, since)).fetchone()
        return json.loads(row[0]) if row else None

    def cache(self, q, since, links):
        with tdb.db() as c:
            c.execute("INSERT OR REPLACE INTO serp_cache (day, vertical, text, page, since, results_json) "
                      "VALUES (?,?,?,?,?,?)", (self.day, q.vertical, q.text, q.start, since, json.dumps(links)))

    def search(self, lane, r, url, vertical="web", strict=False):
        """-> the page's [[url, title]], or None (incomplete; counts toward the breaker, links reset it). A load is
        consumed right before each navigation, after its page is ready. A wall retries once in a fresh session while
        the hold has a load left. strict: an empty page is complete only with Google's no-results wording."""
        links = self._search(lane, r, url, vertical, strict)
        if links is None:
            self.failed()
        else:
            self.fails = 0
        return links

    def failed(self):
        self.fails += 1
        self.broken = self.broken or self.fails >= BREAKER

    def _search(self, lane, r, url, vertical, strict):
        walls = 0
        while walls < 2 and r.used < r.held:
            if self.session is None or self.session.stale():
                self.drop()
                self.session = serp.Session(*self.creds)
                try:
                    self.session.create()
                except Exception:
                    self.broken = True
                    self.drop()
                    raise
            try:
                page = self.session.page(vertical)
            except Exception as e:
                tracker_probe.log(f"tracker {lane} page failed: {type(e).__name__}")
                self.drop()
                return None
            if not tracker_budget.consume(r):
                serp.close_page(page)
                return None
            try:
                final, html = self.session.load(page, url)
            except Exception as e:
                tracker_probe.log(f"tracker {lane} load failed: {type(e).__name__}")
                self.drop()
                return None
            kind = serp.classify_serp(final, html or "")
            if kind in serp.WALLS:
                walls += 1
                self.drop()
                continue
            links = serp.serp_links(html, final)
            if links:
                return [list(x) for x in links]
            return [] if kind == "no_results" and (not strict or serp.says_no_results(html or "")) else None
        return None


def _pages(queries):
    return [replace(q, start=p, pages=1) for q in queries for p in range(q.start, q.start + q.pages)]


def _page_key(q):
    return q.vertical, q.text, q.start


def _pair(q, values):
    """A query's (vertical, field) for google_fields_json; an alias is keyed by its norm() value, since alias:<i> shifts
    when an earlier alias is removed."""
    return q.vertical, _field_key(q.field, values[q.field])


def _field_key(field, value):
    return f"alias:{tracker_judge.norm(value)}" if field.startswith("alias:") else field


def _carried(full, pages):
    """The current plan's single-page queries still named by a carry (a removed field's pages are gone)."""
    keep = {tuple(p) for p in pages}
    qs = tuple(q for q in _pages(full.queries) if _page_key(q) in keep)
    return tracker_plan.Plan(qs, {f: v for f, v in full.values.items() if any(q.field == f for q in qs)})


def _full(w, day, serps, whole):
    """The full Google pass (spec "Full Google pass"): a scan's whole plan, or a carry's pages on its day. Searches go
    through serps' _Serp for the creds (its session loop and breaker; strict: an empty page needs Google's no-results
    wording). Holds the misses + FULL_RETRIES wall retries (partial grant); a grant under the misses trims the plan until
    its misses fit the grant - FULL_RETRIES (at least 1). A whole run carries cap_global / cap_tenant_month cuts to the
    cap's next_on, once; a carry run never carries again. A pending carry's first-scan baseline (carry_json.first) goes
    on into whichever run takes it. A run with a completed page is a success (it ends the baseline, _first). carry_json
    changes only with the run's lane_state (a crash keeps a pending carry)."""
    uncapped, wid = tdb.env_set("TRACKER_UNCAPPED_TENANTS"), w["watch_id"]
    carry = json.loads(w["carry_json"] or "null")
    with tdb.db() as c:
        c.execute("DELETE FROM serp_cache WHERE day < ?", (day,))
        creds = _creds(c, w, uncapped, FULL)
    at = tdb.now()
    next_on = _next_scan(w, at)
    if creds is None:
        return
    if not creds:
        _record(wid, day, FULL, at, "waiting", "no_browserbase_key", ledger=False, next_on=next_on, carry=None)
        return
    browser = serps.setdefault(creds, _Serp(creds, day))
    full = tracker_plan.build(w, w["platform"])
    plan = full if whole or not carry else _carried(full, carry["pages"])
    cache = {}
    for q in _pages(plan.queries):
        links = browser.cached(q, "")
        if links is not None:
            cache[_page_key(q)] = links
    misses = lambda p: sum(_page_key(q) not in cache for q in _pages(p.queries))
    need, r, short, dropped, cut = misses(plan), None, None, [], []
    if need:
        r = tracker_budget.reserve(w["tenant_id"], wid, "load", need + min(FULL_RETRIES, need), partial=True)
        if isinstance(r, tracker_budget.Refused):
            if r.reason == "gone":
                return
            short, r, cut, plan = r, None, list(plan.queries), tracker_plan.Plan((), {})
        elif r.held < need:
            short, room = r.short, max(1, r.held - FULL_RETRIES)
            t = next(n for n in range(plan.loads, -1, -1) if misses(plan.trim(n).plan) <= room)
            tr = plan.trim(t)
            plan, dropped, cut = tr.plan, tr.dropped, tr.cut
    done, results = set(), []
    try:
        for q in _pages(plan.queries):
            k = _page_key(q)
            links = cache.get(k)
            if links is None and not browser.broken:
                try:
                    links = browser.search(FULL, r, q.urls()[0], q.vertical, strict=True)
                except Exception as e:
                    tracker_probe.log(f"tracker {FULL} search failed: {type(e).__name__}")
                if links is not None:
                    browser.cache(q, "", links)
            if links is not None:
                done.add(k)
                results.append((q, links))
    finally:
        browser.drop()
        if r:
            tracker_budget.settle(r)
    want = {}
    for q in _pages(full.queries):
        want.setdefault(_pair(q, full.values), set()).add(_page_key(q))
    with tdb.db() as c:
        first = _first(c, wid, FULL) or bool(carry and carry.get("first"))
        returned = {}
        for q, links in results:
            for u, title in links:
                if not serp.is_goto(u):
                    tracker_judge.admit_hit(c, w, u, title, "google_web", at, first_scan=first)
                    returned.setdefault(tracker_judge.leak_key(u), set()).add(_pair(q, full.values))
        if done:
            _visibility(c, w, full, returned, {p for p, ks in want.items() if ks <= done}, at, not browser.broken)
    new_carry = None
    if whole and cut and short.reason in ("cap_global", "cap_tenant_month"):
        next_on = short.next_on
        new_carry = json.dumps({"on": next_on, "reason": short.reason, "first": first,
                                "pages": [list(_page_key(q)) for q in _pages(cut)]})
    incomplete = any(_page_key(q) not in done for q in _pages(plan.queries))
    if short and r is None:
        state, reason = "waiting", short.reason
    elif incomplete:
        state, reason = "reduced", "google_failed"
    elif cut:
        state, reason = "reduced", short.reason
    else:
        state, reason = "ok", None
    _record(wid, day, FULL, at, state, reason, next_on=next_on, trimmed=dropped,
            success=state in ("ok", "reduced") and bool(done), carry=new_carry)


def _visibility(c, w, full, returned, complete, at, judge):
    """After a full-pass run where some page completed: each Leak's google_fields_json gains the pairs that returned it
    and loses those whose field left the identity; google_seen{visible} is written on a change: true when returned;
    only when judge (the breaker held): null when a non-empty set became empty, false when every pair of the set still
    in the plan completed in this run (complete) without returning it; otherwise (a fresh-only Leak too) it stays.
    A thumb whose query left the plan, or whose Leak turned not visible, is cleared."""
    fields = {_field_key(f, v) for f, v in full.values.items()}
    planned = {_pair(q, full.values) for q in full.queries}
    tracker_preview.prune(c, w["watch_id"], {tracker_preview.query_id(*p) for p in planned})
    last = {}
    for lid, data in c.execute("SELECT e.leak_id, e.data_json FROM leak_events e JOIN leaks l ON l.leak_id = e.leak_id "
                               "WHERE l.watch_id = ? AND e.type = 'google_seen' ORDER BY e.id", (w["watch_id"],)):
        last[lid] = tdb.visible_of(json.loads(data or "{}"))
    for row in c.execute("SELECT leak_id, url_key, google_fields_json FROM leaks WHERE watch_id = ?",
                         (w["watch_id"],)).fetchall():
        lid, old = row["leak_id"], {tuple(p) for p in json.loads(row["google_fields_json"] or "[]")}
        got = returned.get(row["url_key"], set())
        new = {p for p in old | got if p[1] in fields} if judge else old | got
        if new != old:
            c.execute("UPDATE leaks SET google_fields_json = ? WHERE leak_id = ?",
                      (json.dumps(sorted(new), separators=(",", ":")), lid))
        cur, checked = last.get(lid), new & planned
        vis = True if got else cur if not judge else None if old and not new else \
            False if checked and checked <= complete else cur
        if vis != cur:
            tdb.add_event(c, lid, "google_seen", {"visible": vis}, at)
            if vis is False:
                tracker_preview.clear_thumb(c, lid)

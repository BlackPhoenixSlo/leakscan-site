"""Leak lanes (Phase 2 spec "Lanes in detail"): run_daily(watch_id, day) runs a seeded watch's daily lanes in order inside
Phase 1's daily pass (tracker_scheduler) and writes each lane's lane_state row, plus a lane_day row for the lanes Phase 2
adds. Lanes so far: origin_probe (Phase 1's probe; only its lane_state row is new; the seed records it too), then
mega_lookup, then listing_recheck; after every watch's run_daily, run_fresh_batch(watch_ids, day) runs google_fresh.
A paused or deleted watch runs no lane (tracker_view reads its lanes `paused`). One lane failing never stops the next.
Each added lane runs at most once per watch per UTC day (a non-failed lane_day row).

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

Google fresh pass (paid, run_fresh_batch after every watch's $0 lanes): runs only for tenants on TRACKER_PAID_TENANTS
(comma list, default empty: nothing paid runs, the lane stays `never`). Browserbase creds: the host's BROWSERBASE_API_KEY
/ BROWSERBASE_PROJECT_ID for TRACKER_UNCAPPED_TENANTS, the tenant's own (tracker_cli tenant bb) for every other; none ->
`waiting` / no_browserbase_key, no lane_day row. Watches are grouped by creds, so a session never serves two keys, and
each group's misses are packed LOADS_PER_SESSION to a Browserbase session (tracker_serp.Session). Each watch's query is
tracker_plan.fresh(); serp_cache by (UTC day, vertical, text, page, since) first: a hit reuses the links and reserves
nothing, a miss reserves FRESH_HOLD loads (partial grant), consumes one before every navigation and caches the links of
a page that loaded. A wall (tracker_serp.WALLS) ends the session and retries once in a fresh one, if the hold has a
load left; a second wall, a failed load, a results page without links or a spent hold -> no result: `reduced` /
google_failed (lane_day partial). A session also rotates at serp.ROTATE_S old. Breaker: a failed create, or BREAKER
incomplete queries in a row, and the group's remaining misses are google_failed with no reservation and no session.
Refused -> `waiting` with the cap's reason and next_on (a gone watch records nothing); the watch is never paused. A
watch whose tenant row is missing is skipped. Result links go through tracker_judge.admit_hit with source google_web (a
/goto link is dropped), which only ever marks a Leak visible in Google. No other engine is called.

Google full pass (paid, run_weekly_batch(watch_ids, day, serps) after the fresh batch, on a watch's weekly_slot weekday
or its carry day): the same gate, creds, Session and cache (since '') as fresh, and each creds group's breaker goes on
from the fresh batch across the tick's watches; each vertical blocks its own assets (tracker_serp.BLOCKED); an empty
page counts only with Google's no-results wording. tracker_plan.build()'s misses + FULL_RETRIES (wall retries) are reserved with a partial grant; a
short grant trims the plan (Plan.trim) to what fits, the dropped fields go to lane_state.trimmed (lane `reduced`, the
cap's reason, lane_day partial). A slot run cut by cap_global / cap_tenant_month writes watches.carry_json: its cut pages
run once on the cap's next_on (next UTC day / the 1st), never carried again. Each returned link's (vertical, field) pairs
join leaks.google_fields_json. Only a run that searched (a page completed, breaker intact) touches visibility: one that
completed every planned pair of a Leak and returned none marks it not visible (google_seen visible false), a set
emptied by fields leaving the identity unknown (null). The first-scan baseline holds until a run ends ok."""
import functools
import html as _html
import json
import os
import re
from dataclasses import replace
from datetime import date, timedelta
from urllib.parse import parse_qsl, urljoin, urlsplit

import leak_crawler
import leakshaven
import tracker_budget
import tracker_db as tdb
import tracker_judge
import tracker_pagekind
import tracker_plan
import tracker_probe
import tracker_rules as rules
import tracker_seed
import tracker_serp as serp

_MEGA_OK = ("ok", "nomatch", "short")
MAP_FILE = os.path.join(tdb.HERE, "bruqi_detection_map.json")
LISTING_MAX = 20
LISTING_BODY = 2 * 1024 * 1024
LISTING_GAP = 0.4
_ANCHOR = re.compile(r"""<a\b[^>]*?\bhref\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_OUTCOME = {"ok": "ok", "reduced": "partial", "failed": "failed", "waiting": "partial"}
FRESH = "google_fresh"
BREAKER = 3
FRESH_HOLD = 2  # the load and its one wall retry; settle releases what a query didn't use
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
    _record(watch_id, day, "origin_probe", at, "ok" if probe is not None else "failed", ledger=False)
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


def run_fresh_batch(watch_ids, day):
    """The Google fresh pass over watch_ids (the daily pass's, in its order) for UTC day (module docstring) -> its
    {creds: _Serp}, so the weekly lanes go on with each group's breaker."""
    paid, uncapped, groups = tdb.env_set("TRACKER_PAID_TENANTS"), tdb.env_set("TRACKER_UNCAPPED_TENANTS"), {}
    if not paid:
        return {}
    with tdb.db() as c:
        c.execute("DELETE FROM serp_cache WHERE day < ?", (day,))
    with tdb.db() as c:
        for wid in watch_ids:
            w = c.execute("SELECT * FROM watches WHERE watch_id = ?", (wid,)).fetchone()
            if not w or w["paused"] or w["deleted_at"] or w["tenant_id"] not in paid:
                continue
            creds = _creds(c, w, uncapped, FRESH)
            if creds is None:
                continue
            if not creds:
                groups.setdefault(None, []).append(w)
            elif not _ran(wid, day, FRESH):
                groups.setdefault(creds, []).append(w)
    for w in groups.pop(None, []):
        _record(w["watch_id"], day, FRESH, tdb.now(), "waiting", "no_browserbase_key", ledger=False)
    serps = {}
    for creds, ws in groups.items():
        serps[creds] = _Batch(creds, day)
        serps[creds].run(ws)
    return serps


class _Serp:
    """Browserbase sessions on one creds for a UTC day, the day's serp_cache, and the breaker: a failed create, or
    BREAKER incomplete searches in a row, and every later miss gets no reservation and no session (broken)."""

    def __init__(self, creds, day, lane):
        self.creds, self.day, self.lane, self.session, self.fails, self.broken = creds, day, lane, None, 0, False

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

    def search(self, r, url, vertical="web", strict=False):
        """-> the page's [[url, title]], or None (incomplete; counts toward the breaker, links reset it). A load is
        consumed right before each navigation, after its page is ready. A wall retries once in a fresh session while
        the hold has a load left. strict: an empty page is complete only with Google's no-results wording."""
        links = self._search(r, url, vertical, strict)
        self.fails = 0 if links is not None else self.fails + 1
        self.broken = self.broken or self.fails >= BREAKER
        return links

    def _search(self, r, url, vertical, strict):
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
                tracker_probe.log(f"tracker {self.lane} page failed: {type(e).__name__}")
                self.drop()
                return None
            if not tracker_budget.consume(r):
                serp.close_page(page)
                return None
            try:
                final, html = self.session.load(page, url)
            except Exception as e:
                tracker_probe.log(f"tracker {self.lane} load failed: {type(e).__name__}")
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


class _Batch(_Serp):
    """One creds group's fresh misses, packed into sessions."""

    def __init__(self, creds, day):
        super().__init__(creds, day, FRESH)

    def run(self, ws):
        try:
            for w in ws:
                try:
                    self._watch(w)
                except Exception as e:
                    tracker_probe.log(f"tracker {FRESH} failed: {type(e).__name__}")
                    self._failed(w, tdb.now())
        finally:
            self.drop()

    def _failed(self, w, at):
        _record(w["watch_id"], self.day, FRESH, at, "reduced", "google_failed", success=False)

    def _watch(self, w):
        at, q = tdb.now(), tracker_plan.fresh(w)
        since = q.since or ""
        links = self.cached(q, since)
        if links is None:
            if self.broken:
                self._failed(w, at)
                return
            r = tracker_budget.reserve(w["tenant_id"], w["watch_id"], "load", FRESH_HOLD, partial=True)
            if isinstance(r, tracker_budget.Refused):
                if r.reason != "gone":
                    _record(w["watch_id"], self.day, FRESH, at, "waiting", r.reason, next_on=r.next_on)
                return
            try:
                links = self.search(r, q.urls()[0])
            finally:
                tracker_budget.settle(r)
            if links is None:
                self._failed(w, at)
                return
            self.cache(q, since, links)
        with tdb.db() as c:
            first = _first(c, w["watch_id"], FRESH)
            for u, title in links:
                if not serp.is_goto(u):
                    tracker_judge.admit_hit(c, w, u, title, "google_web", at, first_scan=first)
        _record(w["watch_id"], self.day, FRESH, at)


def weekly_due(w, day):
    """The watch's weekly lanes run on its slot weekday and on the day its carried pages are due."""
    carry = json.loads(w["carry_json"] or "null")
    return w["weekly_slot"] == date.fromisoformat(day).weekday() or bool(carry and carry["on"] <= day)


def run_weekly_batch(watch_ids, day, serps=None):
    """run_weekly over watch_ids, one _Serp per creds across them all; serps = run_fresh_batch's, so a creds group
    the fresh pass broke stays broken."""
    serps = {} if serps is None else serps
    for wid in watch_ids:
        try:
            run_weekly(wid, day, serps)
        except Exception as e:
            tracker_probe.log(f"tracker weekly lanes failed: {type(e).__name__}")


def run_weekly(watch_id, day, serps=None):
    """The weekly lanes of one unpaused, undeleted, seeded watch that is weekly_due on UTC day -> True when due; serps
    {creds: _Serp} is shared across a tick's watches. Lanes so far: google_full; the registry crawl (ticket 30) is
    added here as its own lane."""
    with tdb.db() as c:
        w = c.execute("SELECT * FROM watches WHERE watch_id = ?", (watch_id,)).fetchone()
    if not w or w["paused"] or w["deleted_at"] or not w["seeded_at"] or not weekly_due(w, day):
        return False
    if not _ran(watch_id, day, FULL):
        try:
            _full(w, day, {} if serps is None else serps)
        except Exception as e:
            tracker_probe.log(f"tracker {FULL} failed: {type(e).__name__}")
            _record(watch_id, day, FULL, tdb.now(), "failed", next_on=_next_slot(w, day))
    return True


def _next_slot(w, day):
    d = date.fromisoformat(day)
    return (d + timedelta(days=(w["weekly_slot"] - d.weekday()) % 7 or 7)).isoformat()


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


def _full(w, day, serps):
    """The full Google pass (spec "Full Google pass"): the slot's whole plan, or a carry's pages on its day. Gate,
    creds and serp_cache (since '') are the fresh pass's; searches go through serps' _Serp for the creds (its session
    loop and breaker; strict: an empty page needs Google's no-results wording). Holds the misses + FULL_RETRIES wall
    retries (partial grant); a grant under the misses trims the plan until its misses fit the grant - FULL_RETRIES (at
    least 1). The slot run carries cap_global / cap_tenant_month cuts to the cap's next_on, once; a carry run never
    carries again. carry_json changes only with the run's lane_state (a crash keeps a pending carry)."""
    paid, uncapped, wid = tdb.env_set("TRACKER_PAID_TENANTS"), tdb.env_set("TRACKER_UNCAPPED_TENANTS"), w["watch_id"]
    if w["tenant_id"] not in paid:
        return
    slot, carry = w["weekly_slot"] == date.fromisoformat(day).weekday(), json.loads(w["carry_json"] or "null")
    with tdb.db() as c:
        c.execute("DELETE FROM serp_cache WHERE day < ?", (day,))
        creds = _creds(c, w, uncapped, FULL)
    at, next_on = tdb.now(), _next_slot(w, day)
    if creds is None:
        return
    if not creds:
        _record(wid, day, FULL, at, "waiting", "no_browserbase_key", ledger=False, next_on=next_on, carry=None)
        return
    browser = serps.get(creds) or serps.setdefault(creds, _Serp(creds, day, FULL))
    browser.lane = FULL
    full = tracker_plan.build(w, w["platform"])
    plan = full if slot or not carry else _carried(full, carry["pages"])
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
                    links = browser.search(r, q.urls()[0], q.vertical, strict=True)
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
        first = c.execute("SELECT 1 FROM lane_day WHERE watch_id = ? AND lane = ? AND outcome = 'ok'",
                          (wid, FULL)).fetchone() is None
        returned = {}
        for q, links in results:
            for u, title in links:
                if not serp.is_goto(u):
                    tracker_judge.admit_hit(c, w, u, title, "google_web", at, first_scan=first)
                    returned.setdefault(tracker_judge.leak_key(u), set()).add(_pair(q, full.values))
        if done and not browser.broken:
            _visibility(c, w, full, returned, {p for p, ks in want.items() if ks <= done}, at)
    new_carry = None
    if slot and cut and short.reason in ("cap_global", "cap_tenant_month"):
        next_on = short.next_on
        new_carry = json.dumps({"on": next_on, "reason": short.reason, "pages": [list(_page_key(q)) for q in _pages(cut)]})
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
            success=state in ("ok", "reduced") and not incomplete, carry=new_carry)


def _visibility(c, w, full, returned, complete, at):
    """After a full-pass run that searched (some page completed, breaker intact): each Leak's google_fields_json gains
    the pairs that returned it and loses those whose field left the identity; google_seen{visible} is written on a
    change: true when returned, null when a non-empty set became empty, false when every pair of the set still in the
    plan completed in this run (complete) without returning it; otherwise (a fresh-only Leak too) it stays."""
    fields = {_field_key(f, v) for f, v in full.values.items()}
    planned = {_pair(q, full.values) for q in full.queries}
    last = {}
    for lid, data in c.execute("SELECT e.leak_id, e.data_json FROM leak_events e JOIN leaks l ON l.leak_id = e.leak_id "
                               "WHERE l.watch_id = ? AND e.type = 'google_seen' ORDER BY e.id", (w["watch_id"],)):
        last[lid] = tdb.visible_of(json.loads(data or "{}"))
    for row in c.execute("SELECT leak_id, url_key, google_fields_json FROM leaks WHERE watch_id = ?",
                         (w["watch_id"],)).fetchall():
        lid, old = row["leak_id"], {tuple(p) for p in json.loads(row["google_fields_json"] or "[]")}
        got = returned.get(row["url_key"], set())
        new = {p for p in old | got if p[1] in fields}
        if new != old:
            c.execute("UPDATE leaks SET google_fields_json = ? WHERE leak_id = ?",
                      (json.dumps(sorted(new), separators=(",", ":")), lid))
        cur, checked = last.get(lid), new & planned
        vis = True if got else None if old and not new else False if checked and checked <= complete else cur
        if vis != cur:
            tdb.add_event(c, lid, "google_seen", {"visible": vis}, at)

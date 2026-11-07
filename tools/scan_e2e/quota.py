"""Scenario `quota` (see tools/scan_e2e.py): Google failing is never a clean result. Unlike every other scenario this drives the REAL
public_app.Handler serving site/ (scan_stub.py is a fake API: the bug lived in the app), started by this module per viewport.
Declared bypasses, all at their wire: Google CSE + DeepSeek = app/tests/upstream_stub.py, leakshaven its stub, profile pages a fake urlopen,
media gathering and alias enrichment off. Socket guard: nothing leaves loopback. SCAN_LIMITER is the real one (the no-charge check)."""
import argparse
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

from . import reach, reuse
from .common import PIP_AWAY, ROOT, cfg, check, new_ctx

HANDLE = "mira.example"   # upstream_stub.HANDLE: importing it here would run the app's tests dir in the harness
FALSE = ("No leaks found", "No public", "Nothing indexed", "No image results", "No video results", "No web results", "0 images", "0 links")
EVENTS = "window.__results = 0; addEventListener('leakscan:result', () => { window.__results++; }, true);"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class App:
    """The real app + its upstream stub, one viewport's; `db` read directly (read-only), faults set on the stub's control route."""

    def __init__(self, vp_name):
        self.tmp = tempfile.TemporaryDirectory(prefix="e2e-quota-")
        self.port, self.cse, self.db = free_port(), free_port(), os.path.join(self.tmp.name, "public.db")
        self.base, self.log = f"http://127.0.0.1:{self.port}/", cfg.out / f"{vp_name}-quota-app.log"
        env = {**os.environ, **({reach.ENV: str(cfg.out / "reach-quota.log")} if reuse.cacheable() else {})}
        self.err = open(self.log, "w")
        self.proc = subprocess.Popen([sys.executable, "-m", "scan_e2e.quota", "--port", str(self.port), "--cse", str(self.cse), "--data", self.tmp.name]
                                     + (["--broken"] if "quota" in cfg.broken else []), cwd=ROOT / "tools", env=env, stdout=subprocess.PIPE, stderr=self.err)
        self.proc.stdout.readline()

    def stop(self):
        self.proc.terminate()
        self.proc.wait()
        self.proc.stdout.close()
        self.err.close()
        self.tmp.cleanup()

    def fault(self, fault=None, limit=None):
        q = "&".join(f"{k}={v}" for k, v in (("fault", fault), ("limit", limit)) if v is not None)
        req = urllib.request.Request(f"http://127.0.0.1:{self.cse}/__cse?{q}", data=b"", method="POST")
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())["cse_calls"]

    def rows(self, handle):
        with sqlite3.connect(f"file:{self.db}?mode=ro", uri=True) as c:
            return c.execute("SELECT status, hit_count, extra_json FROM scans WHERE handle=?", (handle,)).fetchall()

    def said(self, what):
        return sum(what in x for x in self.log.read_text().splitlines())

    def post(self, handle=HANDLE):
        """The API as the visitor's browser calls it -> (status, body)."""
        req = urllib.request.Request(self.base + "api/public-scan", data=json.dumps({"handle": handle, "platform": "onlyfans.com"}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()


def hero_submit(page, base, handle):
    page.goto(base)
    page.locator("#scan input[name=h]").fill(handle)


def hero_settled(page):
    page.wait_for_function("() => { const c = document.querySelector('.report-card'); return c && !c.hasAttribute('aria-busy') && !document.querySelector('#scan button').disabled; }", timeout=20000)
    page.wait_for_timeout(250)


def no_false_claim(name, text):
    said = [f for f in FALSE if f in text]
    check(f"quota: {name}: nothing reads as nothing found", not said, said)


def unfinished(browser, app, vp_name, vp, fault):
    """One failure, both surfaces, from a clean browser (a stored last report would hide what this one did)."""
    tag = f"{vp_name} {fault}"
    ctx, net = new_ctx(browser, vp_name, vp, init=[PIP_AWAY, EVENTS])
    calls = app.fault(fault)
    page = ctx.new_page()
    hero_submit(page, app.base, HANDLE)
    page.screenshot(path=str(cfg.out / f"{vp_name}-quota-{fault}-trigger.png"))
    page.locator("#scan button[type=submit]").click()
    hero_settled(page)
    card = page.locator(".report-card").inner_text()
    check(f"quota: {tag} hero: says it didn't finish, try again", page.locator(".report-card .live").get_attribute("data-error") == "failed" and "didn’t finish" in card and "Try again" in card, card[:200])
    no_false_claim(f"{tag} hero", card)
    check(f"quota: {tag} hero: no report in the URL", "r=" not in page.url, page.url)
    check(f"quota: {tag} hero: nothing remembered", page.evaluate("localStorage.getItem('leakscan.last')") is None)
    check(f"quota: {tag} hero: no result event (the conversion hangs on it)", page.evaluate("window.__results") == 0)
    check(f"quota: {tag} #free phone: the illustration stays", page.locator(".phone-free.is-live").count() == 0)
    page.locator(".report-card").scroll_into_view_if_needed()
    page.screenshot(path=str(cfg.out / f"{vp_name}-quota-{fault}-hero.png"))
    page.goto(f"{app.base}scan/?p=onlyfans.com&h={HANDLE}")
    page.wait_for_selector("#error:not([hidden]), #report:not([hidden])", timeout=20000)
    body = page.locator("body").inner_text()
    check(f"quota: {tag} scan page: the failed state", page.locator("#error").is_visible() and page.locator("#error").get_attribute("data-kind") == "failed"
          and "didn’t finish" in page.locator("#error-title").inner_text() and "couldn’t finish" in body and "Try again" in body, body[:200])
    check(f"quota: {tag} scan page: no report, no empty card, a retry button", page.locator("#report").is_hidden() and page.locator("#empty").is_hidden() and page.locator("#retry").is_visible())
    no_false_claim(f"{tag} scan page", body)
    check(f"quota: {tag} scan page: no report in the URL, no result event", "r=" not in page.url and page.evaluate("window.__results") == 0, page.url)
    page.screenshot(path=str(cfg.out / f"{vp_name}-quota-{fault}-scan.png"))
    check(f"quota: {tag}: no row stored", not app.rows(HANDLE), [r[:2] for r in app.rows(HANDLE)])
    check(f"quota: {tag}: said in the log, no scan done", app.said("scan unfinished level=low") > 0 and not app.said("scan done"), app.said("scan done"))
    check(f"quota control: {tag}: Google was really asked, both times", app.fault(fault) >= calls + 2, calls)
    page.close()
    ctx.close()
    check(f"quota control: {tag}: nothing off loopback, no page errors", not (net["outside"] or net["errors"]), {k: net[k][:3] for k in ("outside", "errors")})


def retry_heals(browser, app, vp_name, vp):
    """Still failing, then Google back: the same page's retry button gets a real report, the one result event, a stored row."""
    ctx, net = new_ctx(browser, vp_name, vp, init=[PIP_AWAY, EVENTS])
    page = ctx.new_page()
    app.fault("429")
    page.goto(f"{app.base}scan/?p=onlyfans.com&h={HANDLE}")
    page.wait_for_selector("#error:not([hidden]), #report:not([hidden])", timeout=20000)
    app.fault()
    if page.locator("#retry").is_visible():
        page.locator("#retry").click()
    else:   # the break run: the old "empty" report has no retry; the control below still has to hold
        page.goto(f"{app.base}scan/?p=onlyfans.com&h={HANDLE}")
    page.wait_for_function("() => !document.getElementById('report').hidden && !document.getElementById('empty').checkVisibility()", timeout=20000)
    check(f"quota control: {vp_name} Google back: a real report, its result event", "r=" in page.url and page.evaluate("window.__results") >= 1, page.url)
    done = [r for r in app.rows(HANDLE) if r[0] == "complete"]
    check(f"quota control: {vp_name} Google back: a stored report with its hits", len(done) == 1 and done[0][1] > 0, [r[:2] for r in done])
    check(f"quota: {vp_name} Google back: a reuse source (no earlier scan's aggregator lookup in the way)", bool(done) and bool(json.loads(done[0][2]).get("scan_key")), [r[:2] for r in done])
    page.screenshot(path=str(cfg.out / f"{vp_name}-quota-healed.png"))
    page.close()
    ctx.close()


def partial_and_empty(browser, app, vp_name, vp):
    """A call failed after hits: left as it was, this measures what it shows. Google answering with nothing: "No leaks found" stands (FALSE isn't over-broad)."""
    ctx, _net = new_ctx(browser, vp_name, vp, init=[PIP_AWAY, EVENTS])
    page = ctx.new_page()
    app.fault(limit=1)
    hero_submit(page, app.base, "partial.example")
    page.locator("#scan button[type=submit]").click()
    hero_settled(page)
    row = app.rows("partial.example")
    card = page.locator(".report-card").inner_text()
    check(f"quota control: {vp_name} partial: its hits show, no error", page.locator(".live-rows li").count() > 0 and page.locator(".report-card .live").get_attribute("data-error") is None, card[:120])
    check(f"quota control: {vp_name} partial: stored complete, not a reuse source", len(row) == 1 and row[0][0] == "complete" and not json.loads(row[0][2]).get("scan_key"), [r[:2] for r in row])
    print(f"NOTE partial {vp_name}: hits={row[0][1] if row else None} says partial={'partial' in card.replace('partial.example', '').lower() or 'couldn’t finish' in card}", flush=True)
    page.locator(".report-card").scroll_into_view_if_needed()
    page.screenshot(path=str(cfg.out / f"{vp_name}-quota-partial.png"))
    app.fault("empty")
    hero_submit(page, app.base, "nothing.example")
    page.locator("#scan button[type=submit]").click()
    hero_settled(page)
    card = page.locator(".report-card").inner_text()
    row = app.rows("nothing.example")
    check(f"quota control: {vp_name} Google answered with nothing: still No leaks found", "No leaks found" in card and [r[0] for r in row] == ["empty"], card[:120])
    page.locator(".report-card").scroll_into_view_if_needed()
    page.screenshot(path=str(cfg.out / f"{vp_name}-quota-true-empty.png"))
    page.close()
    ctx.close()


def quota_flow(browser, vp_name, vp):
    app = App(vp_name)
    try:
        for fault in ("429", "403", "reset"):
            unfinished(browser, app, vp_name, vp, fault)
        # the wire, and the real limiter (5 scans a minute): 8 more failures, on top of the 6 above, cost nothing
        app.fault("429")
        api = [app.post() for _ in range(8)]
        check(f"quota: {vp_name} API: failed event, no result, never rate limited", all(s == 200 and "event: failed" in b and "event: result" not in b for s, b in api), [(s, b[:80]) for s, b in api][:2])
        (cfg.out / f"{vp_name}-quota-side-effects.json").write_text(json.dumps({"api_status": api[0][0], "api_body": api[0][1], "rows_after_14_failures": len(app.rows(HANDLE))}, indent=1, ensure_ascii=False))
        retry_heals(browser, app, vp_name, vp)
        partial_and_empty(browser, app, vp_name, vp)
    finally:
        app.stop()


def serve():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int)
    ap.add_argument("--cse", type=int)
    ap.add_argument("--data")
    ap.add_argument("--broken", action="store_true")
    a = ap.parse_args()
    if os.environ.get(reach.ENV):
        reach.to_log(os.environ[reach.ENV])
    sys.path[:0] = [str(ROOT / "app"), str(ROOT / "app" / "tests")]
    os.environ.update(GOOGLE_API_KEY="fake", GOOGLE_CSE_ID="fake", DEEPSEEK_API_KEY="fake", DATA_DIR=a.data, PUBLIC_DB=os.path.join(a.data, "public.db"))
    connect = socket.socket.connect

    def guarded(self, addr):
        if self.family != socket.AF_UNIX and addr[0] not in ("127.0.0.1", "::1", "localhost"):
            raise OSError("blocked non-loopback")
        return connect(self, addr)
    socket.socket.connect = guarded
    from http.server import ThreadingHTTPServer

    import chat_proxy
    import cse_scanner
    import db
    import leakshaven
    import leakshaven_stub
    import media_gather
    import profile_extract
    import public_app
    import ratelimit
    import upstream_stub
    from test_profile import FakeFetch, ig_routes
    up, lsv = upstream_stub.Stub(a.cse).start(), leakshaven_stub.Stub().start()
    cse_scanner.CSE_ENDPOINT, chat_proxy.DEEPSEEK_URL = up.base + "/customsearch/v1", up.base + "/chat/completions"
    leakshaven.BASE, leakshaven.ENABLED, leakshaven.MIN_GAP = lsv.base, True, 0.0
    public_app.PROFILE_ENABLED, public_app.ALIAS_ENRICH, media_gather.MEDIA_ENABLED = True, False, False
    public_app.SCAN_REUSE_TTL = 21600
    profile_extract.urlopen = FakeFetch(ig_routes())
    if a.broken:   # the bug back: a scan that found nothing never hears its calls failed. Hits + a failed call stay partial, as they are.
        def hide(fn, found):
            def wrapped(*args, errors=None, **kw):
                mine = []
                out = fn(*args, errors=mine, **kw)
                if errors is not None and found(out):
                    errors.extend(mine)
                return out
            return wrapped
        cse_scanner.cse_search_wide = hide(cse_scanner.cse_search_wide, lambda out: out[0])
        cse_scanner.cse_paginate = hide(cse_scanner.cse_paginate, bool)
        public_app.SCAN_LIMITER = ratelimit.Limiter(rate_per_min=10 ** 6, burst=10 ** 6, max_concurrent=100)   # those scans are charged again: the controls below still have to run
    db.DB_PATH = os.environ["PUBLIC_DB"]
    db.init_db()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), public_app.Handler)
    srv.daemon_threads = True
    print("ready", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    serve()

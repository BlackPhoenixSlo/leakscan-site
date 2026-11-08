#!/usr/bin/env python3
"""Real-path proof of site/js/analytics.js: drives the pages in headless Chromium, under the production sub-path.

    nice -n 10 python3 tools/analytics_e2e.py OUT_DIR [--break-order]

Run A = the committed file with ADS_ID emptied: inert, compared to the same page with analytics.js blanked.
Run B = configured with fake values: order, banner, reject / accept / reopen, both conversions, nothing sensitive sent.
--break-order moves the denied default after `config`: only the `order:` check may go red.

Bypasses (declared):
- A's and B's analytics.js are Playwright-routed copies: A with the ids emptied, B with AW-000000000 + fake labels (the
  real ids never reach Google from here).
- gtag.js is Google's real file (fetched once, then replayed); every other non-loopback request is recorded, then
  aborted, so no beacon reaches Google. t.me / wa.me get a local stub page.
- /api/* goes to tools/scan_stub.py (synthetic scan) through a Playwright route: the real backend needs paid API keys.
Evidence in OUT_DIR: results.json, requests.json (every outside request), screenshots.
"""
import argparse, functools, hashlib, http.server, json, pathlib, re, socket, subprocess, sys, tempfile, threading, time
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
SUB = "leakscan-site"
ADS, L_SCAN, L_CONTACT = "AW-000000000", "FAKElabelSCAN", "FAKElabelCONTACT"
HANDLE, NAME = "zzprobehandle77", "Zzprobe Nameonly"
PAGES = ("", "scan/", "privacy.html", "imprint.html", "video/")
LOOP = ("127.0.0.1", "localhost")
GOOGLE = re.compile(r"google|gstatic|doubleclick|ggpht|youtube", re.I)
TYPES = ("ad_storage", "ad_user_data", "ad_personalization", "analytics_storage")
DEFAULT_LINE = "  gtag('consent', 'default', Object.assign(consent('denied'), { wait_for_update: 500 }));\n"
CONFIG_RE = re.compile(r"  gtag\('config', ADS_ID.*\n")
IDS_RE = re.compile(r"const (ADS_ID|LABEL_SCAN|LABEL_CONTACT) = '[^']*'")
FOOT_TG = 'a.channel[href^="https://t.me/jakabasej"]'
# test hook: what dataLayer held at the moment the gtag.js <script> went into the page
INIT = """
const add = Node.prototype.appendChild;
Node.prototype.appendChild = function (n) {
  if (n.tagName === 'SCRIPT' && /gtag\\/js/.test(n.src || '')) window.__atInject = (window.dataLayer || []).map(e => Array.from(e).slice(0, 2));
  return add.call(this, n);
};"""
LAYER = """() => (window.dataLayer || []).map(e => {
  if (e && typeof e.length === 'number') return Array.from(e).map(x => x instanceof Date ? 'DATE' : x);
  return { event: e && e.event };
})"""

results, requests, gtag_info = [], [], {}
real_gtag = {}


def check(name, ok, detail=""):
    results.append({"check": name, "ok": bool(ok), "detail": str(detail)[:600]})
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""), flush=True)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def with_ids(ads="", scan="", contact=""):
    src = (ROOT / "site/js/analytics.js").read_text(encoding="utf-8")
    val = {"ADS_ID": ads, "LABEL_SCAN": scan, "LABEL_CONTACT": contact}
    src, n = IDS_RE.subn(lambda m: f"const {m[1]} = '{val[m[1]]}'", src)
    assert n == 3, n
    return src


def routed_copy(broken):
    src = with_ids(ADS, L_SCAN, L_CONTACT)
    if broken:
        assert src.count(DEFAULT_LINE) == 1 and CONFIG_RE.search(src)
        src = src.replace(DEFAULT_LINE, "")
        src = CONFIG_RE.sub(lambda m: m[0] + DEFAULT_LINE, src, count=1)
    return src


class Run:
    def __init__(self, browser, base, stub, out, script):
        self.browser, self.base, self.stub, self.out, self.script = browser, base, stub, out, script

    def ctx(self, tag, script=None, **kw):
        """New context; `script` = analytics.js body to serve (None = the committed file)."""
        script = self.script if script is None else script
        ctx = self.browser.new_context(viewport=kw.pop("viewport", {"width": 1280, "height": 800}), service_workers="block", **kw)
        ctx.add_init_script(INIT)

        def handle(route, req):
            u = urlsplit(req.url)
            if u.hostname in LOOP:
                if u.path.endswith("/js/analytics.js") and script != "committed":
                    return route.fulfill(body=script, content_type="text/javascript")
                if u.path.startswith("/api/"):
                    return route.fulfill(response=route.fetch(url=self.stub + u.path + ("?" + u.query if u.query else "")))
                return route.continue_()
            try:
                post = req.post_data
            except Exception:
                post = "<binary>"
            requests.append({"run": tag, "method": req.method, "url": req.url, "post": post, "type": req.resource_type,
                             "referer": req.headers.get("referer"), "page_frame": req.frame.url if req.is_navigation_request() is False else ""})
            if u.hostname == "www.googletagmanager.com" and u.path == "/gtag/js":
                if "body" not in real_gtag:
                    r = route.fetch()
                    real_gtag.update(body=r.body(), status=r.status, ctype=r.headers.get("content-type", ""))
                    gtag_info.update(url=req.url, status=r.status, bytes=len(real_gtag["body"]),
                                     sha256=hashlib.sha256(real_gtag["body"]).hexdigest())
                return route.fulfill(status=real_gtag["status"], body=real_gtag["body"], content_type=real_gtag["ctype"])
            if u.hostname in ("t.me", "wa.me"):
                return route.fulfill(body="<title>stub</title>stub", content_type="text/html")
            return route.abort()

        ctx.route("**/*", handle)
        page = ctx.new_page()
        page.errs = []
        page.on("console", lambda m: page.errs.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: page.errs.append("pageerror: " + str(e)))
        return ctx, page

    def open(self, page, path=""):
        page.goto(self.base + path, wait_until="load")
        page.wait_for_timeout(700)

    def hits(self, tag, label):
        """One per conversion: gtag sends one conversion on several endpoints (and retries an aborted one), same `random`."""
        seen = {}
        for r in requests:
            if r["run"] == tag and label in r["url"]:
                seen.setdefault(params(r).get("random"), r)
        return list(seen.values())

    def wait_hits(self, page, tag, label, n=1):
        for _ in range(40):
            if len(self.hits(tag, label)) >= n:
                break
            page.wait_for_timeout(100)
        page.wait_for_timeout(1200)    # a late duplicate would land here
        return self.hits(tag, label)

    def scan(self, page, handle=HANDLE):
        page.fill("#scan .scan-handle", handle)
        page.click("#scan button[type=submit]")
        page.wait_for_function("location.search.includes('r=')", timeout=20000)

    def conv(self, page, label):
        return [e for e in page.evaluate(LAYER) if isinstance(e, list) and e[:2] == ["event", "conversion"]
                and e[2].get("send_to") == f"{ADS}/{label}"]

    def shot(self, page, name):
        page.screenshot(path=str(self.out / name))


def params(hit):
    return {k: v[0] for k, v in parse_qs(urlsplit(hit["url"]).query, keep_blank_values=True).items()}


def run_a(run):
    print("--- Run A: ADS_ID empty", flush=True)
    inert = with_ids()
    for path in PAGES:
        snap = {}
        for mode, script in (("blanked", "// blanked"), ("committed", inert)):
            tag = f"A-{mode}-{path}"
            ctx, page = run.ctx(tag, script=script)
            run.open(page, path)
            page.mouse.move(300, 300)
            page.mouse.wheel(0, 400)
            page.wait_for_timeout(1500)
            snap[mode] = {
                "cookies": ctx.cookies(), "errs": list(page.errs),
                "storage": page.evaluate("[Object.keys(localStorage).sort(), Object.keys(sessionStorage).sort()]"),
                "outside": [r["url"] for r in requests if r["run"] == tag],
                "banner": page.locator(".cc-banner").count(), "layer": page.evaluate("typeof window.dataLayer"),
                "links_hidden": page.evaluate("[...document.querySelectorAll('[data-cookie-settings]')].every(e => e.hidden)"),
            }
            ctx.close()
        c, b = snap["committed"], snap["blanked"]
        p = path or "index"
        check(f"A {p}: no outside request", not c["outside"], c["outside"])
        check(f"A {p}: no banner, no dataLayer, settings link stays hidden", c["banner"] == 0 and c["layer"] == "undefined" and c["links_hidden"], c)
        check(f"A {p}: no cookies", not c["cookies"], c["cookies"])
        check(f"A {p}: storage same as with analytics.js blanked", c["storage"] == b["storage"], (c["storage"], b["storage"]))
        check(f"A {p}: no console errors", not c["errs"], c["errs"])
    # the flows too: a finished scan and a contact click still send nothing
    ctx, page = run.ctx("A-flow", script=inert)
    run.open(page)
    run.scan(page)
    page.wait_for_timeout(800)
    page.locator(FOOT_TG).click()
    page.wait_for_timeout(800)
    bad = [r["url"] for r in requests if r["run"] == "A-flow" and GOOGLE.search(urlsplit(r["url"]).hostname)]
    check("A flow: scan + contact click reach no Google host", not bad, bad)
    check("A flow: no console errors", not page.errs, page.errs)
    ctx.close()


def run_b(run):
    print("--- Run B: configured with fake values", flush=True)

    # order + banner
    ctx, page = run.ctx("B-order")
    run.open(page)
    layer = page.evaluate(LAYER)
    at = page.evaluate("window.__atInject") or []
    first = layer[0] if layer else None
    ok = bool(first) and first[:2] == ["consent", "default"] and all(first[2].get(t) == "denied" for t in TYPES) \
        and first[2].get("wait_for_update") and at[:1] == [["consent", "default"]]
    check("order: denied default is dataLayer[0] and was queued before gtag.js went in", ok, {"first": first, "at_inject": at})
    json.dump(layer, open(run.out / "datalayer-first-load.json", "w"), indent=1)
    sets = [e for e in layer if isinstance(e, list) and e[0] == "set"]
    check("set: ads_data_redaction, url_passthrough on", ["set", "ads_data_redaction", True] in sets and ["set", "url_passthrough", True] in sets, sets)
    cfg = next((e for e in layer if isinstance(e, list) and e[:2] == ["config", ADS]), None)
    check("config: page_location clean, title fixed, no page view, no enhanced conversions",
          cfg and cfg[2].get("page_location") == run.base and cfg[2].get("page_title") == "Abolita"
          and cfg[2].get("send_page_view") is False and cfg[2].get("allow_enhanced_conversions") is False, cfg)
    check("gtag.js: real file loaded", gtag_info.get("status") == 200 and gtag_info.get("bytes", 0) > 10000 and page.evaluate("typeof window.google_tag_manager") != "undefined", gtag_info)
    check("banner: shows, nothing granted yet", page.locator(".cc-banner").is_visible() and "granted" not in json.dumps(layer), layer)
    a, r = page.get_by_role("button", name="Accept"), page.get_by_role("button", name="Reject")
    style = "e => { const s = getComputedStyle(e), b = e.getBoundingClientRect(); return [s.backgroundColor, s.color, s.borderColor, s.fontSize, s.fontWeight, Math.round(b.width), Math.round(b.height)]; }"
    check("banner: Accept and Reject equally prominent", a.evaluate(style) == r.evaluate(style), (a.evaluate(style), r.evaluate(style)))
    run.shot(page, "01-banner-trigger-desktop.png")
    ctx.close()
    ctx, page = run.ctx("B-phone", viewport={"width": 390, "height": 844}, color_scheme="dark")
    run.open(page)
    run.shot(page, "01-banner-trigger-phone-dark.png")
    ow = page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    check("banner: fits a 390 px phone, no sideways scroll", ow and page.locator(".cc-banner").bounding_box()["width"] <= 390)
    ctx.close()

    # reject
    ctx, page = run.ctx("B-reject")
    run.open(page)
    page.get_by_role("button", name="Reject").click()
    run.shot(page, "02-settled-after-reject.png")
    layer = page.evaluate(LAYER)
    check("reject: banner gone, stored, update denied, nothing granted",
          page.locator(".cc-banner").count() == 0 and page.evaluate("localStorage['leakscan.consent']") == "denied"
          and ["consent", "update"] == next((e[:2] for e in layer if isinstance(e, list) and e[:2] == ["consent", "update"]), None)
          and "granted" not in json.dumps(layer), layer)
    page.reload(wait_until="load")
    page.wait_for_timeout(700)
    layer = page.evaluate(LAYER)
    check("reject: persists across reload (no banner, nothing granted)",
          page.locator(".cc-banner").count() == 0 and page.evaluate("localStorage['leakscan.consent']") == "denied" and "granted" not in json.dumps(layer), layer)
    run.scan(page)
    hits = run.wait_hits(page, "B-reject", L_SCAN)
    check("reject: scan conversion still a cookieless ping (gcs G100)", hits and all(params(h).get("gcs") == "G100" for h in hits), [h["url"] for h in hits])
    gcl = [c["name"] for c in ctx.cookies() if c["name"].startswith(("_gcl", "_gac"))]
    check("reject: no ad cookies, no _gcl storage", not gcl and not page.evaluate("Object.keys(localStorage).filter(k => k.startsWith('_gcl'))"), gcl)
    ctx.close()

    # accept + in-page scan on the landing, then a reload of the personalized page
    ctx, page = run.ctx("B-accept")
    run.open(page)
    page.get_by_role("button", name="Accept").click()
    run.shot(page, "03-settled-after-accept.png")
    layer = page.evaluate(LAYER)
    upd = [e for e in layer if isinstance(e, list) and e[:2] == ["consent", "update"]]
    check("accept: update grants all four, stored, banner gone",
          len(upd) == 1 and all(upd[0][2].get(t) == "granted" for t in TYPES) and page.evaluate("localStorage['leakscan.consent']") == "granted"
          and page.locator(".cc-banner").count() == 0, upd)
    page.reload(wait_until="load")
    page.wait_for_timeout(700)
    layer = page.evaluate(LAYER)
    idx = {e[0] + ":" + str(e[1]): i for i, e in reversed(list(enumerate(layer))) if isinstance(e, list) and len(e) > 1 and isinstance(e[1], str)}
    check("accept: persists across reload (no banner, granted before config)",
          page.locator(".cc-banner").count() == 0 and idx.get("consent:update", 99) < idx.get(f"config:{ADS}", -1), layer[:8])
    run.scan(page)
    hits = run.wait_hits(page, "B-accept", L_SCAN)
    slug = parse_qs(urlsplit(page.url).query)["r"][0]
    check("scan: conversion once, right label (dataLayer + wire)", len(run.conv(page, L_SCAN)) == 1 and len(hits) == 1, [h["url"] for h in hits])
    check("scan: no contact conversion from it", not run.conv(page, L_CONTACT) and not run.hits("B-accept", L_CONTACT))
    check("accept: conversion carries gcs G111", hits and params(hits[0]).get("gcs") == "G111", hits and params(hits[0]).get("gcs"))
    check("scan: hit's url clean although the bar says ?r=", "r=" in page.url and hits and params(hits[0]).get("url") == run.base,
          hits and {k: params(hits[0]).get(k) for k in ("url", "ref", "tiba")})
    cookies = sorted(c["name"] for c in ctx.cookies())
    storage = page.evaluate("Object.keys(localStorage).sort()")
    days = {c["name"]: round((c["expires"] - time.time()) / 86400) for c in ctx.cookies()}
    print("    measured after accept: cookies (days)", days, "localStorage", storage, flush=True)
    run.measured = {"cookies_after_accept": cookies, "cookie_days": days, "localstorage_after_accept": storage}
    run.shot(page, "04-after-scan-settled.png")
    page.reload(wait_until="load")
    page.wait_for_timeout(1500)
    check("scan: reopening ?r= is not another conversion", not run.conv(page, L_SCAN) and len(run.hits("B-accept", L_SCAN)) == 1)

    # reopen: every page's link, and withdrawing clears what Accept left
    settings = page.locator("[data-cookie-settings] >> visible=true")
    check("reopen: link visible once configured", settings.count() >= 1)
    url_before = page.url
    settings.first.locator("a").click()
    check("reopen: banner back, focus inside, no navigation", page.locator(".cc-banner").is_visible() and page.url == url_before
          and page.evaluate("!!document.activeElement.closest('.cc-banner')"))
    run.shot(page, "05-banner-reopened.png")
    page.get_by_role("button", name="Reject").click()
    layer = page.evaluate(LAYER)
    gcl = [c["name"] for c in ctx.cookies() if c["name"].startswith(("_gcl", "_gac"))]
    gls = page.evaluate("Object.keys(localStorage).filter(k => k.startsWith('_gcl'))")
    check("reopen: Reject withdraws (update denied, stored, ad cookies + storage gone)",
          layer[-1][:2] == ["consent", "update"] and all(layer[-1][2].get(t) == "denied" for t in TYPES)
          and page.evaluate("localStorage['leakscan.consent']") == "denied" and not gcl and not gls, (layer[-1], gcl, gls))
    ctx.close()
    for path in PAGES:
        ctx, page = run.ctx("B-pages")
        run.open(page, path)
        page.get_by_role("button", name="Accept").click()
        link = page.locator("[data-cookie-settings] a")
        link.scroll_into_view_if_needed()
        link.click()
        check(f"reopen on {path or 'index'}: link opens the banner", page.locator(".cc-banner").is_visible(), page.errs)
        ctx.close()

    # scan page: the leak surface. Title + URL hold the handle; the DM link is prefilled with it.
    ctx, page = run.ctx("B-scanpage")
    run.open(page, "scan/")
    page.get_by_role("button", name="Accept").click()
    page.fill(".scan-handle", HANDLE)
    page.click("form button[type=submit]")
    page.wait_for_function("location.search.includes('r=')", timeout=20000)
    page.wait_for_timeout(500)
    slug2 = parse_qs(urlsplit(page.url).query)["r"][0]
    hits = run.wait_hits(page, "B-scanpage", L_SCAN)
    check("scan/ page: conversion once, right label", len(run.conv(page, L_SCAN)) == 1 and len(hits) == 1, [h["url"] for h in hits])
    title = page.evaluate("document.title")
    check("scan/ page: report title holds no handle (gtag.js sends document.title as tiba)", HANDLE not in title and "report" in title, title)
    check("scan/ page: tiba + url clean", hits and params(hits[0]).get("tiba") == title and params(hits[0]).get("url") == run.base + "scan/", hits and params(hits[0]))
    cta = page.locator('a[data-msg="tg"]:visible').first
    href = cta.get_attribute("href")
    check("leak surface exists: the DM link is prefilled with the handle", HANDLE in href.replace("%40", "@"), href)
    cta.click()
    hits = run.wait_hits(page, "B-scanpage", L_CONTACT)
    check("contact: scan/ prefilled DM link, conversion once, right label", len(hits) == 1, [h["url"] for h in hits])
    check("contact: hit holds nothing of the DM link", hits and HANDLE not in hits[0]["url"] and "t.me" not in hits[0]["url"])
    ctx.close()

    # contact on the landing, same tab: the click leaves the page, does the hit still go out?
    ctx, page = run.ctx("B-contact")
    run.open(page)
    page.get_by_role("button", name="Reject").click()
    page.wait_for_timeout(300)
    page.locator(FOOT_TG).click()
    hits = run.wait_hits(page, "B-contact", L_CONTACT)
    check("contact: footer Telegram link, same tab, hit leaves before the page does, once", len(hits) == 1 and page.url.startswith("https://t.me/"), [h["url"] for h in hits])
    ctx.close()

    # contact: once per page load; a leak link on t.me is not contact (page held in place by a test hook)
    ctx, page = run.ctx("B-once")
    run.open(page)
    page.get_by_role("button", name="Reject").click()
    page.evaluate("""() => {
      document.addEventListener('click', e => e.preventDefault());
      const a = document.createElement('a'); a.id = 'leak'; a.href = 'https://t.me/someleakchannel/123'; a.textContent = 'leak'; document.body.append(a);
    }""")
    page.evaluate("document.getElementById('leak').click()")
    page.wait_for_timeout(300)
    check("contact: a t.me leak link does not count", not run.conv(page, L_CONTACT))
    page.locator(FOOT_TG).click()
    page.locator('a.channel[href^="https://wa.me/"]').click()
    page.locator('a.channel[href^="mailto:"]').click()
    hits = run.wait_hits(page, "B-once", L_CONTACT)
    check("contact: 3 contact clicks, one page load, one conversion", len(run.conv(page, L_CONTACT)) == 1 and len(hits) == 1, [h["url"] for h in hits])
    ctx.close()

    # sensitive URL + ad click id on arrival; the mini player's frame stays inert; the referrer to the next page is clean
    ctx, page = run.ctx("B-url")
    page.goto(f"{run.base}?gclid=TESTgclid123&gbraid=TESTgbraid&h={HANDLE}&name={NAME.replace(' ', '+')}&utm_term={HANDLE}#{HANDLE}", wait_until="load")
    page.wait_for_timeout(700)
    page.get_by_role("button", name="Accept").click()
    run.scan(page)
    hits = run.wait_hits(page, "B-url", L_SCAN)
    u = hits and params(hits[0]).get("url", "")
    check("privacy: accepted, ad click ids survive the override, nothing else does", u == f"{run.base}?gclid=TESTgclid123&gbraid=TESTgbraid", u)
    run.measured_cookies_ad_click = sorted(c["name"] for c in ctx.cookies())
    page.mouse.move(300, 300)
    page.mouse.wheel(0, 300)
    try:
        page.wait_for_selector(".pip iframe", timeout=8000, state="attached")
        page.wait_for_timeout(1500)
    except Exception:
        pass
    frames = [f for f in page.frames if "/video/" in f.url]
    framed = [f.evaluate("[typeof window.dataLayer, document.querySelectorAll('.cc-banner').length]") for f in frames]
    check("frame: mini player's video/ loaded analytics.js and stayed inert", frames and all(x == ["undefined", 0] for x in framed), (len(frames), framed))
    ctx.close()
    # denied: Google's own redaction empties the ids too (ads_data_redaction), the query stays ours
    ctx, page = run.ctx("B-url-denied")
    page.goto(f"{run.base}?gclid=TESTgclid123&h={HANDLE}", wait_until="load")
    page.wait_for_timeout(700)
    page.get_by_role("button", name="Reject").click()
    run.scan(page)
    hits = run.wait_hits(page, "B-url-denied", L_SCAN)
    u = hits and params(hits[0]).get("url", "")
    check("privacy: rejected, click id redacted by Google's tag, nothing else in the url", u.split("?")[0].rstrip("/") == run.base.rstrip("/") and urlsplit(u).query == "gclid=0", u)
    ctx.close()
    ctx, page = run.ctx("B-ref")
    run.open(page, f"scan/?r=demoR3port01")
    page.wait_for_timeout(600)
    page.get_by_role("button", name="Reject").click()
    page.locator(".site-header .brand").click()
    page.wait_for_load_state("load")
    page.wait_for_timeout(700)
    page.evaluate("document.addEventListener('click', e => e.preventDefault())")
    page.locator(FOOT_TG).click()
    hits = run.wait_hits(page, "B-ref", L_CONTACT)
    p = hits and params(hits[0]) or {}
    check("privacy: referrer from scan/?r= reduced to its path", (p.get("ref") or "").rstrip("/") == run.base + "scan", {k: p.get(k) for k in ("url", "ref")})

    # video/?name= : name in the URL, title too; its name bar's scan counts once
    ctx.close()
    ctx, page = run.ctx("B-video")
    run.open(page, "video/?name=" + NAME.replace(" ", "+"))
    page.get_by_role("button", name="Reject").click()
    page.evaluate("document.querySelector('.vo-nb-chg') && document.querySelector('.vo-nb-chg').click()")
    page.fill("#vo-nb-in", HANDLE)
    page.evaluate("document.querySelector('.vo-nb-f').requestSubmit()")
    hits = run.wait_hits(page, "B-video", L_SCAN)
    check("video/: name bar's scan, conversion once, url clean", len(hits) == 1 and params(hits[0]).get("url", "").rstrip("/") == run.base + "video", [h["url"] for h in hits])
    ctx.close()

    # nothing sensitive left the browser for Google, in any run
    outside = [r for r in requests if GOOGLE.search(urlsplit(r["url"]).hostname)]
    slugs = {slug, slug2, "demoR3port01"}
    needles = {HANDLE, NAME, NAME.replace(" ", "+"), NAME.replace(" ", "%20")} | slugs
    leaks = [(n, r["url"], r["post"], r["referer"]) for r in outside for n in needles
             if n.lower() in " ".join(str(x) for x in (r["url"], r["post"], r["referer"])).lower()]
    check(f"privacy: none of {len(needles)} sensitive strings in {len(outside)} Google requests (url, body, referer)", outside and not leaks, leaks[:3])
    hosts = sorted({urlsplit(r["url"]).hostname for r in requests})
    print("    outside hosts seen:", hosts, flush=True)
    check("privacy: outside hosts are Google's tag / ad hosts + the t.me / wa.me stubs", all(GOOGLE.search(h) or h in ("t.me", "wa.me") for h in hosts), hosts)
    params_seen = sorted({k for r in outside for k in params(r)})
    run.measured = {**getattr(run, "measured", {}), "hosts": hosts, "params_seen": params_seen, "google_requests": len(outside),
                    "cookies_after_accept_with_ad_click": getattr(run, "measured_cookies_ad_click", [])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--break-order", action="store_true")
    ap.add_argument("--only", choices=("A", "B"))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True, text=True).stdout.strip()

    tmp = tempfile.TemporaryDirectory()
    (pathlib.Path(tmp.name) / SUB).symlink_to(ROOT / "site")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=tmp.name))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/{SUB}/"
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        stub_port = s.getsockname()[1]
    stub = subprocess.Popen([sys.executable, str(ROOT / "tools/scan_stub.py"), "--port", str(stub_port), "--delay", "0.02"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                run = Run(browser, base, f"http://127.0.0.1:{stub_port}", out, routed_copy(a.break_order))
                time.sleep(0.5)    # the stub binds
                if a.only != "B":
                    run_a(run)
                if a.only != "A":
                    run_b(run)
            finally:
                browser.close()
    finally:
        stub.terminate()
        srv.shutdown()
        tmp.cleanup()
    failed = [r for r in results if not r["ok"]]
    json.dump({"git_sha": sha, "dirty": dirty, "break_order": a.break_order, "base": base, "gtag_js": gtag_info,
               "measured": getattr(run, "measured", {}), "passed": len(results) - len(failed), "failed": [r["check"] for r in failed],
               "checks": results}, open(out / "results.json", "w"), indent=1)
    json.dump(requests, open(out / "requests.json", "w"), indent=1)
    print(f"{len(results) - len(failed)} passed, {len(failed)} failed; sha {sha[:7]}{' (dirty)' if dirty else ''}; evidence {out}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

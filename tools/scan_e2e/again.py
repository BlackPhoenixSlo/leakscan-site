"""Scenario `again` (see tools/scan_e2e.py for what it proves): the report's age line, on the hero card and the scan page."""
import json
import urllib.request

from .common import FX, PIP_AWAY, cfg, check, digits, links, new_ctx, served

AGED, YOUNG = "demoAged1", "demoYoung1"
LINE = "Scanned 2 hours ago · Scan again"


def scan_log():
    with urllib.request.urlopen(f"{cfg.base}api/_scan-log") as r:
        return json.loads(r.read())


def slug_of(url):
    return url.split("r=")[1].split("&")[0].split("#")[0]


def asked_fresh(name, before, want):
    log = scan_log()[before:]
    check(f"again: POST {name}: one request, same inputs, fresh:true", len(log) == 1 and log[0] == {**want, "level": "low", "fresh": True}, log)


def line_ok(name, page, sel):
    page.wait_for_selector(f"{sel} .aged-again", timeout=15000)
    check(f"again: {name}: says how old, offers a scan", page.locator(f"{sel} .aged").inner_text().strip() == LINE,
          page.locator(f"{sel} .aged").inner_text())
    aria = page.locator(f"{sel} .aged-again").evaluate("b => [b.tagName, b.type]")
    check(f"again: {name}: a real button", aria == ["BUTTON", "button"], aria)


def hero(ctx, vp_name):
    page = ctx.new_page()
    for slug, name in ((YOUNG, "4 minutes old"), ("demoR3port01", "no as_of (an API from before)")):
        page.goto(f"{cfg.base}?r={slug}")
        page.wait_for_selector(".report-card .live-open", timeout=15000)
        check(f"again: hero {name}: no line", page.locator(".report-card .aged").count() == 0)
    page.goto(f"{cfg.base}?r={AGED}")
    line_ok("hero", page, ".report-card")
    want = len(links(served(AGED)))
    check("again: hero shows the old result first", digits(page.locator(".live-count").inner_text()) == want, page.locator(".live-count").inner_text())
    page.locator(".report-card").screenshot(path=str(cfg.out / f"{vp_name}-again-hero-trigger.png"))
    n = len(scan_log())
    page.locator(".report-card .aged-again").click()
    page.wait_for_function("old => { const l = document.querySelector('.live[data-slug]'); return l && l.dataset.slug !== old; }", arg=AGED, timeout=20000)
    asked_fresh("hero", n, {"handle": FX["handle"], "platform": FX["platform"], "instagram": "mira.ig", "x": "mira_x"})
    new = page.locator(".live[data-slug]").get_attribute("data-slug")
    fresh = served(new)
    check("again: hero: fresh result replaces it", new != AGED and digits(page.locator(".live-count").inner_text()) == len(links(fresh)) != want, page.locator(".live-count").inner_text())
    check("again: hero: fresh = no line", page.locator(".report-card .aged").count() == 0)
    check("again: hero: the report link is the fresh one", slug_of(page.url) == new, page.url)
    check("again: hero: socials kept", "mira.ig" in page.locator(".live-socials").inner_text(), page.locator(".live-socials").inner_text())
    page.locator(".report-card").screenshot(path=str(cfg.out / f"{vp_name}-again-hero-settled.png"))
    page.reload()
    page.wait_for_selector(".report-card .live-open", timeout=15000)
    check("again: hero: a reload keeps the fresh report", page.locator(".live[data-slug]").get_attribute("data-slug") == new and page.locator(".report-card .aged").count() == 0)
    n = len(scan_log())
    page.fill("#scan input[name=h]", "plainvisitor")
    page.locator("#scan button[type=submit]").click()
    page.wait_for_selector(".live[data-slug] .live-open", timeout=20000)
    log = scan_log()[n:]
    check("again: POST a form scan never sends fresh", len(log) == 1 and "fresh" not in log[0], log)
    page.close()


def scan_page(ctx, vp_name):
    page = ctx.new_page()
    page.goto(f"{cfg.base}scan/?r={YOUNG}")
    page.wait_for_selector("#report:not([hidden])", timeout=15000)
    check("again: scan page 4 minutes old: no line", page.locator("#scan-aged").is_hidden())
    page.goto(f"{cfg.base}scan/?r={AGED}")
    line_ok("scan page", page, "#scan-aged")
    check("again: scan page shows the old result first", digits(page.locator("[data-stat=pages]").inner_text()) == 3, page.locator("[data-stat=pages]").inner_text())
    page.screenshot(path=str(cfg.out / f"{vp_name}-again-scan-trigger.png"))
    n = len(scan_log())
    page.locator("#scan-aged .aged-again").click()
    page.wait_for_selector("#progress:not([hidden])", timeout=5000)
    check("again: scan page: scanning hides the line", page.locator("#scan-aged").is_hidden())
    page.wait_for_function("old => !location.search.includes(old) && !document.getElementById('report').hidden", arg=AGED, timeout=20000)
    asked_fresh("scan page", n, {"handle": FX["handle"], "platform": FX["platform"], "instagram": "mira.ig", "x": "mira_x"})
    new, fresh = slug_of(page.url), None
    fresh = served(new)
    check("again: scan page: fresh result replaces it", digits(page.locator("[data-stat=pages]").inner_text()) == fresh["hit_count"] != 3, page.locator("[data-stat=pages]").inner_text())
    check("again: scan page: fresh = no line", page.locator("#scan-aged").is_hidden())
    page.screenshot(path=str(cfg.out / f"{vp_name}-again-scan-settled.png"))
    page.close()


def again_flow(browser, vp_name, vp):
    ctx, net = new_ctx(browser, vp_name, vp, init=[PIP_AWAY])
    hero(ctx, vp_name)
    scan_page(ctx, vp_name)
    ctx.close()
    check("again: no request off loopback, no page / console errors", not (net["outside"] or net["errors"] or net["console"]), {k: net[k][:3] for k in ("outside", "errors", "console")})

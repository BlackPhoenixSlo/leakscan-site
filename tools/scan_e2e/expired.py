"""Scenario parts `expired` (see tools/scan_e2e.py): reports retention trimmed, what a visitor reads at each tier."""
from .again import asked_fresh, scan_log, slug_of
from .common import FX, PIP_AWAY, PROFILE, cfg, check, digits, new_ctx, served

TRIMMED, SUMMARY = "demoTrimmed1", "demoSummary1"
LINES = {TRIMMED: "Scanned 5 days ago, images expired · Scan again", SUMMARY: "Scanned 2 months ago, details expired · Scan again"}
INPUTS = {"handle": FX["handle"], "platform": FX["platform"], "instagram": "mira.ig"}
FALSE = ("No leaks found", "No image results", "No video results", "No web results", "Nothing indexed", "0 images", "0 links")


def no_false_claim(name, text):
    said = [f for f in FALSE if f in text]
    check(f"expired: {name}: nothing reads as nothing found", not said, said)


def hero(ctx, vp_name):
    page = ctx.new_page()
    # trimmed: the links stay, no Images tab, the #free phone says expired
    page.goto(f"{cfg.base}?r={TRIMMED}")
    page.wait_for_selector(".report-card .aged-again", timeout=15000)
    r = served(TRIMMED)
    check("expired: hero trimmed: the line", page.locator(".report-card .aged").inner_text().strip() == LINES[TRIMMED], page.locator(".report-card .aged").inner_text())
    check("expired: hero trimmed: its links show", digits(page.locator(".live-count").inner_text()) == r["hit_count"] and page.locator(".live-rows li").count() > 0, page.locator(".live-count").inner_text())
    check("expired: hero trimmed: no Images tab, no strip", page.locator("#tab-report-images").count() == 0 and page.locator(".live-strip").count() == 0)
    page.wait_for_function("() => { const m = document.querySelector('.live-media'); return m && (m.hidden || m.style.visibility === 'hidden'); }", timeout=10000)
    check("expired: hero trimmed: photos line gone (media none)", "Photos ready" not in page.locator(".report-card").inner_text())
    no_false_claim("hero trimmed", page.locator(".report-card").inner_text())
    free = page.locator("[data-live=free-images]").text_content()
    check("expired: #free phone trimmed: images say expired", "expired" in free and "right now" not in free, free)
    no_false_claim("#free phone trimmed", free + page.locator("[data-live=free-videos]").text_content())
    page.locator(".report-card").screenshot(path=str(cfg.out / f"{vp_name}-expired-hero-trimmed.png"))
    n = len(scan_log())
    page.locator(".report-card .aged-again").click()
    page.wait_for_function("old => { const l = document.querySelector('.live[data-slug]'); return l && l.dataset.slug !== old; }", arg=TRIMMED, timeout=20000)
    log = scan_log()[n:]
    check("expired: POST hero: same inputs, fresh:true", len(log) == 1 and log[0] == {**INPUTS, "level": "low", "fresh": True}, log)
    check("expired: hero: Scan again = a full report", page.locator(".report-card .aged").count() == 0 and page.locator("#tab-report-images").count() == 1)
    # summary: the count stands, the note names the kept hosts
    page.goto(f"{cfg.base}?r={SUMMARY}")
    page.wait_for_selector(".report-card .aged-again", timeout=15000)
    r = served(SUMMARY)
    top = r["top_domains"][0]["domain"]
    check("expired: hero summary: the line", page.locator(".report-card .aged").inner_text().strip() == LINES[SUMMARY], page.locator(".report-card .aged").inner_text())
    check("expired: hero summary: the count stands, no list", digits(page.locator(".live-count").inner_text()) == r["hit_count"] > 0 and page.locator(".live-rows li").count() == 0, page.locator(".live-count").inner_text())
    note = page.locator(".live-empty").inner_text()
    check("expired: hero summary: says expired, what it found, where", "expired" in note and top in note and str(r["hit_count"]) in note and str(r["domain_count"]) in note, note)
    no_false_claim("hero summary", page.locator(".report-card").inner_text())
    check("expired: #free phone summary: the illustration stays", page.locator(".phone-free.is-live").count() == 0)
    page.locator(".report-card").screenshot(path=str(cfg.out / f"{vp_name}-expired-hero-summary.png"))
    page.close()


def scan_page(ctx, vp_name):
    page = ctx.new_page()
    r = served(TRIMMED)
    page.goto(f"{cfg.base}scan/?r={TRIMMED}")
    page.wait_for_selector("#scan-aged .aged-again", timeout=15000)
    stats = lambda: (digits(page.locator("[data-stat=domains]").inner_text()), digits(page.locator("[data-stat=pages]").inner_text()), digits(page.locator("[data-stat=google]").inner_text()))
    want = (r["domain_count"], r["hit_count"], r["google_total"])
    check("expired: scan trimmed: the line", page.locator("#scan-aged .aged").inner_text().strip() == LINES[TRIMMED], page.locator("#scan-aged .aged").inner_text())
    check("expired: scan trimmed: counts as scanned", stats() == want, stats())
    check("expired: scan trimmed: sites listed, the empty Google view gone", page.locator("#sites").is_visible() and page.locator("#google").is_hidden() and page.locator("[data-sec=google]").is_hidden())
    no_false_claim("scan trimmed", page.locator("body").inner_text())
    page.screenshot(path=str(cfg.out / f"{vp_name}-expired-scan-trimmed.png"))
    n = len(scan_log())
    page.locator("#scan-aged .aged-again").click()
    page.wait_for_function("old => !location.search.includes(old) && !document.getElementById('report').hidden", arg=TRIMMED, timeout=20000)
    log = scan_log()[n:]
    check("expired: POST scan page: same inputs, fresh:true", len(log) == 1 and log[0] == {**INPUTS, "level": "low", "fresh": True}, log)
    fresh = served(slug_of(page.url))
    check("expired: scan page: Scan again = a full report", page.locator("#google").is_visible() and page.locator("[data-sec=google]").is_visible() and page.locator("#scan-aged").is_hidden() and digits(page.locator("[data-stat=pages]").inner_text()) == fresh["hit_count"])
    page.screenshot(path=str(cfg.out / f"{vp_name}-expired-scan-settled.png"))
    r = served(SUMMARY)
    page.goto(f"{cfg.base}scan/?r={SUMMARY}")
    page.wait_for_selector("#scan-aged .aged-again", timeout=15000)
    check("expired: scan summary: the line", page.locator("#scan-aged .aged").inner_text().strip() == LINES[SUMMARY], page.locator("#scan-aged .aged").inner_text())
    check("expired: scan summary: counts as scanned", stats() == (r["domain_count"], r["hit_count"], r["google_total"]), stats())
    note = page.locator("#expired").inner_text()
    check("expired: scan summary: says expired, where", page.locator("#expired").is_visible() and "expired" in note and r["top_domains"][0]["domain"] in note, note)
    check("expired: scan summary: no empty lists", page.locator("#google").is_hidden() and page.locator("#sites").is_hidden() and page.locator("#empty").is_hidden())
    no_false_claim("scan summary", page.locator("body").inner_text())
    page.screenshot(path=str(cfg.out / f"{vp_name}-expired-scan-summary.png"))
    page.close()


def expired_flow(browser, vp_name, vp):
    ctx, net = new_ctx(browser, vp_name, vp, init=[PIP_AWAY])
    hero(ctx, vp_name)
    scan_page(ctx, vp_name)
    ctx.close()
    check("expired: no request off loopback, no page / console errors", not (net["outside"] or net["errors"] or net["console"]), {k: net[k][:3] for k in ("outside", "errors", "console")})


def personal_flow(browser, vp_name, vp):
    """?r= personalization and the showcase demo keep working from what a summary row keeps: profile + top_domains."""
    ctx, net = new_ctx(browser, vp_name, vp, init=[PIP_AWAY])
    page = ctx.new_page()
    name = PROFILE["display_name"]
    for slug in (TRIMMED, SUMMARY):
        page.goto(f"{cfg.base}showcase/?r={slug}")
        page.wait_for_function("n => document.body.innerText.includes(n)", arg=name, timeout=15000)
        check(f"personal: showcase {slug}: her name", True)
        broken = page.evaluate("() => [...document.images].filter(i => i.complete && !i.naturalWidth && i.getAttribute('src')).map(i => i.getAttribute('src'))")
        check(f"personal: showcase {slug}: no broken image", not broken, broken[:3])
        check(f"personal: showcase {slug}: no media asked of a dead slug", not page.evaluate("s => [...document.images].some(i => (i.getAttribute('src') || '').includes('/api/media/' + s + '/'))", slug))
    page.screenshot(path=str(cfg.out / f"{vp_name}-personal-showcase-summary.png"))
    r = served(SUMMARY)
    page.goto(f"{cfg.base}?r={SUMMARY}")
    page.wait_for_selector(".report-card .aged-again", timeout=15000)
    page.wait_for_function("h => document.body.innerText.includes(h)", arg="@" + FX["handle"], timeout=15000)
    hosts = [t["domain"] for t in r["top_domains"]]
    check("personal: landing summary: her hosts fill the page", any(h in page.locator("#removals").inner_text() for h in hosts) if page.locator("#removals").count() else True)
    page.close()
    ctx.close()
    check("personal: no page / console errors", not (net["errors"] or net["console"]), {k: net[k][:3] for k in ("errors", "console")})

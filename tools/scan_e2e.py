#!/usr/bin/env python3
"""End-to-end proof of the on-site free scan against the local stub (never the production API or jackbase.me).

    cd ~/leakhunt && uv run python ~/leakscan-site/tools/scan_e2e.py OUT_DIR [--only scan|personalize|askai|inline]
        [--omit-results] [--omit-profile] [--break-allowlist] [--break-drift] [--break-phones]

Starts tools/scan_stub.py on a free port (--omit-results / --omit-profile are passed through: break-it runs), then
for phone (390x844) and desktop (1440x900) runs three scenarios.

scan: home → fill the hero form → submit → scan/?p=&h= → progress → report. Asserts summary numbers
equal the fixture, tab item counts (All 10 → all pages after "More results", Images ≤ 30, Videos), device toggle swaps
frames, Reveal unblurs, CTA hrefs carry the report link + handle, every hit URL is listed, `?r=<slug>` reopens without
a new scan, and the stub `failed` / 429 / busy / empty / not-found paths show their UI. Every non-loopback request is
aborted and must not happen at all. Screenshots of each state go to OUT_DIR. One PASS/FAIL line per check; exit 1 on
any FAIL.

personalize (js/personalize.js): landing without a slug has byte-identical visible text to the same page without personalize.js and calls no
API; `?r=<slug>` fills both "Your website" phones (name, top leak domains by occurrences, blurred stub thumbs, IG /
TikTok / site rows), the showcase url bar and iframe src; the demo iframe and every showcase page show the profile
and no pottery / Orla / she-her text; demo photos poll /api/media (pending → ready swap, no layout jump; none / 404
keep the placeholders; same-origin relative srcs are accepted and stop polling); scan-only results personalize the phones but leave the demo as Orla;
the malicious fixture never reaches the DOM; scan → report card → landing → localStorage → Reset; the public
window.LeakScanPersonalize.apply() re-personalizes in place and idempotently. Checks that need the
profile are named "profile: …" (the --omit-profile break run must turn only those red). Non-loopback requests are
aborted; the only ones allowed to be attempted are the demo's disclosed Google Fonts.

askai (js/chat.js, the "Ask AI before you DM me" popup): launcher covers no hero text at load (phone: hidden while
the hero is on screen), visible and clear of the hero CTA (desktop) / sticky bar (phone),
open/close/Esc/backdrop/focus return/focus trap, FAQ chips and fuzzy-typed questions answered with zero network
requests, other questions streamed from the stub's /api/chat (request body: kb, slug, history cap), link rules (anchor
scrolls, allowlisted hosts only), failed / 429 / no-API (file://) fallbacks, retry, sessionStorage restore, reduced
motion, JS off. Requests made by the lazy showcase iframe (disclosed Google Fonts, aborted) are not counted against
the popup. --break-allowlist serves chat.js with its host allowlist disabled: only `links:` checks may go red.

inline (js/inline-scan.js): the hero form scans in place; the card becomes the report: Links / Images / Sites tabs
(counts from the fixture, switching never resizes the card), whole-row links, a film strip of what Google Images shows
(blurred, ↗, links to its result or the full report) that drifts by itself after ~4 s idle, stops for good on a
pointerdown and never moves under prefers-reduced-motion (no layout shift: card box + PerformanceObserver), the #free
band's mini Google Images frame with her tiles; errors, reload, reset. --break-drift serves inline-scan.js with the
drift speed 0: only `drift:` checks may go red. --break-phones serves personalize.js without the phone links: only
`phones:` checks may go red.
"""
import json, pathlib, re, socket, subprocess, sys, time, urllib.request
from urllib.parse import parse_qs, quote, urlsplit
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
FX = json.loads((ROOT / "tools" / "fixtures" / "scan-sample.json").read_text())
out = pathlib.Path(sys.argv[1]).expanduser()
out.mkdir(parents=True, exist_ok=True)
omit = "--omit-results" in sys.argv
omit_profile = "--omit-profile" in sys.argv
SCENARIOS = [sys.argv[sys.argv.index("--only") + 1]] if "--only" in sys.argv else ["scan", "personalize", "askai", "inline"]
BREAK_ALLOWLIST = "--break-allowlist" in sys.argv
BREAK_DRIFT = "--break-drift" in sys.argv
BREAK_PHONES = "--break-phones" in sys.argv
GS_RE = re.compile(r"^https://[a-z0-9-]+\.gstatic\.com/[^\s\"'<>\\]*$")
PEOPLE = {"imgs/portrait.webp", "imgs/hero-wide.webp", "imgs/studio-portrait.webp"}   # showcase hero defaults: Pexels people photos (tools/showcase/CREDITS.md)


def _images(fx):
    """Mirror of inline-scan.js model().images: images[] (with the result that has that thumb) then results' thumbs,
    gstatic only, deduped, max 60; the ones with a link first. → [(src, link, domain)]"""
    ok = lambda u: isinstance(u, str) and len(u) <= 600 and GS_RE.match(u)
    res = [r for r in fx.get("results", []) if r.get("link")]
    by, seen, out = {}, set(), []
    for r in res:
        if ok(r.get("thumb")) and r["thumb"] not in by:
            by[r["thumb"]] = r

    def add(u, r):
        if ok(u) and u not in seen:
            seen.add(u)
            out.append((u, r["link"] if r else "", r["domain"] if r else ""))
    for u in fx.get("images", [])[:200]:
        add(u, by.get(u))
    for r in res:
        add(r.get("thumb"), r)
    out = out[:60]
    return [o for o in out if o[1]] + [o for o in out if not o[1]]


def break_routes(ctx):
    """--break-drift / --break-phones: serve the script with the feature disabled (wire boundary, same bytes otherwise)."""
    for flag, name, old, new in ((BREAK_DRIFT, "inline-scan.js", "DRIFT_SPEED = 24", "DRIFT_SPEED = 0"),
                                 (BREAK_PHONES, "personalize.js", "    phones(m, d);\n", "\n")):
        if not flag:
            continue
        body = (ROOT / "site" / "js" / name).read_text(encoding="utf-8")
        assert old in body, f"break: marker not found in {name}"
        ctx.route(f"**/js/{name}", lambda r, _q, b=body.replace(old, new, 1): r.fulfill(body=b, content_type="application/javascript"))
VIEWPORTS = (("phone", {"width": 390, "height": 844}), ("desktop", {"width": 1440, "height": 900}))
fails = []

PAGES = [r for r in FX["results"] if r["kind"] != "video"]
ALSO = "Also found as " + ", ".join("@" + a for a in FX["aliases"]["discovered"])
# leak-page socials on platforms the profile does not have (the discovered Instagram never replaces hers)
FOUND = [s["url"] for s in FX["aliases"]["socials"] if s["platform"] not in {a["platform"] for a in FX["profile"]["accounts"]}]
VIDEOS = [r for r in FX["results"] if r["kind"] == "video"]
IMAGES = min(30, len(dict.fromkeys(FX["images"] + [r["thumb"] for r in FX["results"] if r["thumb"]])))


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name}{': ' + str(detail) if detail != '' else ''}", flush=True)
    if not ok:
        fails.append(name)


def digits(s):
    return int(re.sub(r"\D", "", s) or 0)


def scan_flow(browser, vp_name, vp):
    ctx = browser.new_context(viewport=vp, device_scale_factor=2 if vp_name == "phone" else 1,
                              is_mobile=vp_name == "phone", has_touch=vp_name == "phone")
    outside, posts, errors = [], [], []

    def route(r, _req, outside=outside):
        if urlsplit(r.request.url).hostname in ("127.0.0.1", "localhost"):
            r.continue_()
        else:
            outside.append(r.request.url)
            r.abort()

    ctx.route("**/*", route)
    page = ctx.new_page()
    page.on("request", lambda q, posts=posts: q.method == "POST" and posts.append(q.url))
    page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
    shot = lambda name, full=False, page=page, v=vp_name: page.screenshot(path=str(out / f"{v}-{name}.png"), full_page=full)

    # 1. a scan/?p=&h= link (older links + the no-JS hero form land here; the JS hero form scans in place: `inline`)
    bodies = []
    page.on("request", lambda q, bodies=bodies: q.method == "POST" and "/api/public-scan" in q.url and bodies.append(json.loads(q.post_data)))
    page.goto(base + "scan/?p=fansly.com&h=%40demo.creator", wait_until="load")

    # 2. progress
    page.wait_for_selector("#progress-log li", timeout=5000)
    check(f"{vp_name} progress visible", page.locator("#progress").is_visible()
          and "demo.creator" in page.locator("#scan-title").inner_text())
    check(f"{vp_name} scan/?p=&h= posts platform + clean handle, no socials",
          bodies == [{"platform": "fansly.com", "handle": "demo.creator", "level": "low"}], bodies)
    shot("1-progress")

    # 3. report
    page.wait_for_selector("#report:not([hidden])", timeout=15000)
    page.wait_for_timeout(600)
    slug = parse_qs(urlsplit(page.url).query).get("r", [""])[0]
    check(f"{vp_name} url becomes ?r=<slug>", bool(re.fullmatch(r"[A-Za-z0-9]{12}", slug)), page.url)
    stat = lambda k: digits(page.locator(f"[data-stat={k}]").inner_text())
    got = (stat("domains"), stat("pages"), stat("google"))
    want = (FX["domain_count"], FX["hit_count"], FX["google_total"])
    check(f"{vp_name} summary numbers match fixture", got == want, f"{got} vs {want}")
    check(f"{vp_name} title shows handle", page.locator("#scan-title").inner_text() == "@demo.creator")
    check(f"{vp_name} aliases: header says Also found as the discovered handles", page.locator("#scan-aliases").is_visible()
          and page.locator("#scan-aliases").inner_text() == ALSO, page.locator("#scan-aliases").inner_text())
    aff = page.evaluate("""() => {
        const hint = document.querySelector('.g-hint'), deco = [...document.querySelectorAll('.g-tab-deco')];
        return {hint: hint && hint.offsetParent !== null ? hint.textContent.trim() : null,
          deco: deco.map(e => [e.tagName, e.tabIndex, e.getAttribute('aria-hidden'), +getComputedStyle(e).opacity, getComputedStyle(e).cursor]),
          tabs: [...document.querySelectorAll('.g-tab')].map(e => getComputedStyle(e).cursor),
          seg: [...document.querySelectorAll('#device label')].map(e => getComputedStyle(e).cursor)};
    }""")
    check(f"{vp_name} scan page: hint next to the frame", aff["hint"] == "Tap All · Images · Videos to switch, tap any result to open it.", aff["hint"])
    check(f"{vp_name} scan page: decorative tabs muted, not focusable; real tabs + device toggle pointer",
          aff["deco"] and all(d[0] == "SPAN" and d[1] == -1 and d[2] == "true" and d[3] < .6 and d[4] == "default" for d in aff["deco"])
          and set(aff["tabs"]) == {"pointer"} and set(aff["seg"]) == {"pointer"}, aff)

    # 4. device + tabs (both devices, all three tabs)
    default = "phone" if vp_name == "phone" else "computer"
    check(f"{vp_name} default device {default}", page.locator(f".frame-{default}").count() == 1
          and page.locator("#device input:checked").get_attribute("value") == default)
    for device in (default, "computer" if default == "phone" else "phone"):
        if page.locator("#device input:checked").get_attribute("value") != device:
            page.locator(f"#device label:has(input[value={device}])").click()
            page.wait_for_timeout(300)
        other = "computer" if device == "phone" else "phone"
        check(f"{vp_name} toggle shows {device} frame only", page.locator(f".frame-{device}").is_visible()
              and page.locator(f".frame-{other}").count() == 0)
        if device == "computer":
            check(f"{vp_name} computer url bar", "google.com/search?q=demo.creator+leaks" in page.locator(".bw-url").inner_text())
            box = page.locator(".frame-computer").bounding_box()
            check(f"{vp_name} computer frame fits viewport", box["x"] >= 0 and box["x"] + box["width"] <= vp["width"] + 1,
                  f"x={box['x']:.0f} w={box['width']:.0f}")
        g = page.locator("#google")
        # All
        page.locator("#g-tab-all").click()
        n0 = page.locator("#g-panel .g-r").count()
        page.evaluate("window.scrollTo(0, document.getElementById('google').offsetTop)")
        g.screenshot(path=str(out / f"{vp_name}-3-{device}-all.png"))
        for _ in range(10):
            if page.locator("[data-more=all]").count() == 0:
                break
            page.locator("[data-more=all]").click()
        n1 = page.locator("#g-panel .g-r").count()
        check(f"{vp_name}/{device} All tab count", (n0, n1) == (min(10, len(PAGES)), len(PAGES)), f"{n0}→{n1} want 10→{len(PAGES)}")
        check(f"{vp_name}/{device} every result title carries open ↗", page.locator("#g-panel .g-r a.g-title > .g-go").count() == n1)
        check(f"{vp_name}/{device} tab aria-selected", page.locator("#g-tab-all").get_attribute("aria-selected") == "true"
              and page.locator("#g-tab-images").get_attribute("aria-selected") == "false")
        # Images
        page.locator("#g-tab-images").click()
        while page.locator("[data-more=images]").count():
            page.locator("[data-more=images]").click()
        ni = page.locator("#g-panel .g-tile").count()
        check(f"{vp_name}/{device} Images tab count", ni == IMAGES, f"{ni} want {IMAGES}")
        page.wait_for_timeout(500)
        go = lambda: page.eval_on_selector("#g-panel .g-tile-a .g-go", "e => [+getComputedStyle(e).opacity, getComputedStyle(e.querySelector('.g-go-w')).display]")
        if vp_name == "phone":   # touch: a small ↗ that is always there. Fresh page: element shots taller than the
            # viewport make Playwright drop touch emulation ((hover: none) stops matching) for the rest of the page's life
            p3 = ctx.new_page()
            p3.goto(base + "scan/?r=" + slug)
            p3.wait_for_selector("#report:not([hidden])", timeout=5000)
            if p3.locator("#device input:checked").get_attribute("value") != device:
                p3.locator(f"#device label:has(input[value={device}])").click()
                p3.wait_for_timeout(300)
            p3.locator("#g-tab-images").click()
            p3.wait_for_timeout(400)
            g0 = p3.eval_on_selector("#g-panel .g-tile-a .g-go", "e => [+getComputedStyle(e).opacity, getComputedStyle(e.querySelector('.g-go-w')).display]")
            check(f"{vp_name}/{device} tiles: persistent ↗ badge on touch", g0[0] > .8 and g0[1] == "none", g0)
            p3.evaluate("document.querySelector('#g-panel .g-tile-a').scrollIntoView({block: 'center'})")
            p3.screenshot(path=str(out / f"{vp_name}-4b-{device}-touch-badges.png"))
            p3.close()
        else:
            g0 = go()
            page.locator("#g-panel .g-tile-a").first.hover()
            page.wait_for_timeout(300)
            g1 = go()
            check(f"{vp_name}/{device} tiles: 'open ↗' only on hover", g0[0] == 0 and g1[0] == 1 and g1[1] != "none", (g0, g1))
            g.screenshot(path=str(out / f"{vp_name}-4b-{device}-tile-hover.png"))
            page.mouse.move(0, 0)
        g.screenshot(path=str(out / f"{vp_name}-4-{device}-images.png"))
        # Videos
        page.locator("#g-tab-videos").click()
        nv = page.locator("#g-panel .g-v").count()
        check(f"{vp_name}/{device} Videos tab count", nv == len(VIDEOS), f"{nv} want {len(VIDEOS)}")
        page.wait_for_timeout(300)
        g.screenshot(path=str(out / f"{vp_name}-5-{device}-videos.png"))

    # 5. keyboard: arrow keys move between tabs
    page.locator("#g-tab-videos").focus()
    page.keyboard.press("ArrowLeft")
    check(f"{vp_name} ArrowLeft selects Images", page.locator("#g-tab-images").get_attribute("aria-selected") == "true"
          and page.evaluate("document.activeElement.id") == "g-tab-images")

    # 6. reveal
    blur = lambda: page.eval_on_selector("#g-panel .g-img img", "e => getComputedStyle(e).filter")
    before = blur()
    page.locator("#reveal").click()
    page.wait_for_timeout(400)
    after = blur()
    check(f"{vp_name} blurred by default, Reveal unblurs", "blur" in before and after == "none"
          and page.locator("#reveal").get_attribute("aria-pressed") == "true", f"{before} → {after}")
    page.locator("#google").screenshot(path=str(out / f"{vp_name}-6-revealed.png"))
    page.locator("#reveal").click()

    # 7. CTAs + links
    link = base + "scan/?r=" + slug
    hrefs = page.eval_on_selector_all("#send [data-msg]", "els => els.map(e => e.href)")
    check(f"{vp_name} CTA hrefs carry report link + handle", len(hrefs) == 3 and all(
        (quote(link, safe="") in h or quote(link, safe="").replace("%20", "+") in h) and "demo.creator" in h for h in hrefs)
          and hrefs[0].startswith("https://t.me/jakabasej?text=") and hrefs[1].startswith("https://wa.me/38640703992?text=")
          and hrefs[2].startswith("mailto:me@jackbase.dev?") and "body=" in hrefs[2], hrefs)
    deep = page.locator("#deep-link").get_attribute("href")
    check(f"{vp_name} deep-scan link", deep == "https://jackbase.me/scan?p=fansly.com&h=demo.creator&l=deep&go=1", deep)
    listed = set(page.eval_on_selector_all("#links-list a", "els => els.map(e => e.href)"))
    check(f"{vp_name} every hit url listed", all(h["url"] in listed for h in FX["hits"]),
          f"{sum(h['url'] in listed for h in FX['hits'])}/{len(FX['hits'])}")
    check(f"{vp_name} per-site rows == domain_count", page.locator("#sites-body tr").count() == FX["domain_count"])
    page.locator("#send").scroll_into_view_if_needed()
    page.locator("#send").screenshot(path=str(out / f"{vp_name}-7-cta.png"))

    # 8. reopen ?r=<slug> in a fresh page: no new scan
    n_posts = len(posts)
    p2 = ctx.new_page()
    p2.on("request", lambda q, posts=posts: q.method == "POST" and posts.append(q.url))
    p2.goto(base + "scan/?r=" + slug)
    p2.wait_for_selector("#report:not([hidden])", timeout=5000)
    check(f"{vp_name} ?r= reopens without a new scan", len(posts) == n_posts
          and digits(p2.locator("[data-stat=domains]").inner_text()) == FX["domain_count"])
    p2.screenshot(path=str(out / f"{vp_name}-8-reopen.png"))
    # full-page shots drop Playwright's touch emulation ((hover: none) stops matching), so take it here, on the throwaway page
    p2.screenshot(path=str(out / f"{vp_name}-2-report-full.png"), full_page=True)
    p2.goto(base + "scan/?r=evilR3port01")
    p2.wait_for_selector("#report:not([hidden])", timeout=5000)
    check(f"{vp_name} aliases: malicious discovered handles never shown", p2.locator("#scan-aliases").is_hidden()
          and "alert(1)" not in p2.locator("#scan-aliases").evaluate("e => e.textContent"))
    p2.close()

    # 9. error / empty paths
    for h, kind, want in (("stub-fail", "failed", "didn’t finish"), ("stub-429", "rate_limited", "limit"),
                          ("stub-busy", "busy", "busy")):
        page.goto(base + f"scan/?p=onlyfans.com&h={h}")
        page.wait_for_selector("#error:not([hidden])", timeout=10000)
        msg = page.eval_on_selector_all("#error [data-msg]", "els => els.map(e => e.href)")
        check(f"{vp_name} {kind} error UI", page.locator("#error").get_attribute("data-kind") == kind
              and want in page.locator("#error-title").inner_text() and len(msg) == 3 and all(h in m for m in msg),
              page.locator("#error-title").inner_text())
        shot(f"9-error-{kind}")
    page.goto(base + "scan/?p=onlyfans.com&h=stub-empty")
    page.wait_for_selector("#report:not([hidden])", timeout=10000)
    check(f"{vp_name} empty status UI", page.locator("#empty").is_visible() and not page.locator("#google").is_visible()
          and "Nothing indexed for this handle right now" in page.locator("#empty").inner_text())
    check(f"{vp_name} aliases: none discovered -> header line hidden", page.locator("#scan-aliases").is_hidden())
    shot("9-empty")
    page.goto(base + "scan/?r=doesNotExist")
    page.wait_for_selector("#error:not([hidden])", timeout=5000)
    check(f"{vp_name} not_found UI", page.locator("#error").get_attribute("data-kind") == "not_found")
    page.goto(base + "scan/?p=onlyfans.com&h=" + quote("bad handle!"))
    check(f"{vp_name} bad handle → form + message", page.locator("#scan-form").is_visible()
          and page.locator("#form-error").is_visible())
    page.goto(base + "scan/?p=instagram.com&h=" + quote("https://instagram.com/demo.creator/"))
    page.wait_for_selector("#progress:not([hidden])", timeout=5000)
    check(f"{vp_name} URL pasted as handle → cleaned", page.locator("#scan-title").inner_text() == "Scanning Google for @demo.creator")
    page.wait_for_selector("#report:not([hidden])", timeout=15000)

    check(f"{vp_name} no request left loopback", not outside, outside)
    check(f"{vp_name} no JS errors", not errors, errors)
    ctx.close()



# ---------------------------------------------------------------- personalize
# Checks named "profile: ..." need the scan result's `profile` (and the media it unlocks); every other check must stay
# green when the stub drops it (--omit-profile = the break-it run).
POTTERY = re.compile(r"brennick|\borla\b|clay|stoneware|galway|kiln|potter|pottery|\bpots?\b|glaze|wheel|\bmugs?\b|"
                     r"ireland|irish|celadon|ceramic|420 grams", re.I)
PRONOUN = re.compile(r"\b(she|her|hers|herself)\b", re.I)
PROFILE = FX["profile"]
ACC = {a["platform"]: a for a in PROFILE["accounts"]}


def top_domains(hits):
    occ = {}
    for h in hits:
        occ[h["domain"]] = occ.get(h["domain"], 0) + (h.get("occurrences") or 1)
    return sorted(occ, key=lambda d: -occ[d])[:4]


TOP = top_domains(FX["hits"])


def top_urls(hits):
    """per domain, the URL of its most-seen hit (first one on a tie): what the before-phone's leak rows open"""
    best, url = {}, {}
    for h in hits:
        d, n = h["domain"].lower().removeprefix("www."), h.get("occurrences") or 1
        if d not in best or n > best[d]:
            best[d], url[d] = n, h["url"]
    return url


TOP_URLS = top_urls(FX["hits"])
GSTATIC = [u for u in FX["images"] if u.startswith("https://") and ".gstatic.com/" in u][:3]
DEMO_PAGES = ["", "about.html", "links.html", "timeline.html", "verify.html", "blog.html", "statement.html",
              "blog/post-1.html", "blog/post-2.html", "blog/post-3.html", "404.html"]
FONT_HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com"}   # the demo's disclosed Google Fonts; aborted here
PROD_HOSTS = ("scan.srv1395798.hstgr.cloud", "72.62.92.114", "jackbase.me")


def stub_media(slug, mode="normal"):
    import urllib.request
    urllib.request.urlopen(urllib.request.Request(f"{base}__stub/media?slug={slug}&mode={mode}", method="POST")).read()


def baseline_index():
    """This tree's index.html without personalize.js / inline-scan.js (the page those scripts must leave alone when
    there is no slug), with the stub's data-api injected like the stub does."""
    html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    html = re.sub(r'<script src="js/(personalize|inline-scan)\.js" defer></script>\n', "", html)
    return "no-p-scripts", re.sub(r"<body\b", f'<body data-api="{API}"', html, count=1)


def personalize_flow(browser, vp_name, vp):
    tag = f"{vp_name} personalize"
    net = {"outside": [], "api": [], "dialogs": [], "errors": []}

    def new_ctx():
        ctx = browser.new_context(viewport=vp, device_scale_factor=2 if vp_name == "phone" else 1,
                                  is_mobile=vp_name == "phone", has_touch=vp_name == "phone")

        def route(r, _req):
            if urlsplit(r.request.url).hostname in ("127.0.0.1", "localhost"):
                if "/api/" in r.request.url:
                    net["api"].append(r.request.url)
                r.continue_()
            else:
                net["outside"].append(r.request.url)
                r.abort()
        ctx.route("**/*", route)
        break_routes(ctx)
        ctx.on("page", lambda pg: (pg.on("dialog", lambda d: (net["dialogs"].append(d.message), d.dismiss())),
                                   pg.on("pageerror", lambda e: net["errors"].append(str(e)))))
        return ctx

    def scroll_all(page):
        for y in range(0, 9000, 450):
            page.evaluate(f"window.scrollTo(0, {y})")
            page.wait_for_timeout(40)

    texts = lambda page, sel: page.eval_on_selector_all(sel, "els => els.filter(e => e.offsetParent !== null).map(e => e.textContent.trim())")
    shown = lambda page, sel: page.eval_on_selector_all(sel, "els => els.filter(e => getComputedStyle(e).display !== 'none').length")

    # A. no slug: visible text byte-identical to the page without personalize.js, no API call
    ctx = new_ctx()
    page = ctx.new_page()
    net["api"].clear()
    page.goto(base, wait_until="load")
    page.wait_for_timeout(1200)
    now = page.evaluate("document.body.innerText")
    no_api = list(net["api"])
    sha, html = baseline_index()
    ctx2 = new_ctx()
    ctx2.route(base, lambda r, _q: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=html))
    p2 = ctx2.new_page()
    p2.goto(base, wait_until="load")
    p2.wait_for_timeout(1200)
    then = p2.evaluate("document.body.innerText")
    check(f"{tag} no slug: visible text identical to the page without the scripts", now == then, f"{len(now)} vs {len(then)} chars")
    check(f"{tag} no slug: no API call", not no_api, no_api)
    static = page.evaluate("""() => ({links: document.querySelectorAll('.ba a').length,
        roles: [...document.querySelectorAll('.ba .phone')].map(p => p.getAttribute('role')),
        hidden: [...document.querySelectorAll('.ba .phone-screen')].map(s => s.getAttribute('aria-hidden')), hint: !!document.querySelector('.ba-hint'),
        band: [document.querySelector('.gmini').getAttribute('role'), document.querySelectorAll('.gmini a').length, document.querySelectorAll('.gmini-grid .gi-card').length],
        lav: [...document.querySelectorAll('.report-card .report-rows .lav')].map(e => e.textContent)})""")
    check(f"{tag} no slug: phones = one image each, rows not links, no tap hint", static["links"] == 0 and static["roles"] == ["img", "img"]
          and static["hidden"] == ["true", "true"] and not static["hint"], static)
    check(f"{tag} no slug: #free band = static Google Images illustration, hero rows = letter avatars",
          static["band"] == ["img", 0, 10] and static["lav"] == ["L", "F", "P", "F"], static)
    page.locator("#showcase").scroll_into_view_if_needed()
    try:
        page.wait_for_function("() => { const f = document.querySelector('iframe[data-p=demo]'); const i = f && f.contentDocument && f.contentDocument.querySelector('img.hero__bg'); return i && i.complete && i.naturalWidth > 0; }", timeout=9000)
    except Exception:
        pass
    hero0 = page.evaluate("() => { const i = document.querySelector('iframe[data-p=demo]').contentDocument.querySelector('img.hero__bg'); return [i.getAttribute('src'), i.alt, i.naturalWidth]; }")
    check(f"{tag} no slug: showcase hero = a people photo (Pexels series, credited)", hero0[0] in PEOPLE and "Orla" in hero0[1] and hero0[2] > 0, hero0)
    page.wait_for_timeout(500)
    page.locator("#showcase").screenshot(path=str(out / f"{vp_name}-p0-showcase-default.png"))
    ctx2.close()
    ctx.close()

    # B. landing ?r=<fixture slug>
    stub_media(FX["slug"])
    ctx = new_ctx()
    page = ctx.new_page()
    page.goto(base + "?r=" + FX["slug"], wait_until="load")
    page.wait_for_selector("[data-p=scanned]:not([hidden])", timeout=9000)
    check(f"{tag} hero line links back to the report", "Scanned @demo.creator" in page.locator("[data-p=scanned]").inner_text()
          and page.locator("[data-p=scanned] a").get_attribute("href") == "scan/?r=" + FX["slug"])
    page.locator(".hero").screenshot(path=str(out / f"{vp_name}-p1-hero-line.png"))
    name = PROFILE["display_name"]
    check(f"{tag} profile: both phones search for the name", texts(page, "[data-p=search]") == [name, name], texts(page, "[data-p=search]"))
    sites = [page.locator(f'[data-p="leak-{i}"] .m-site').inner_text() for i in range(1, 5)]
    check(f"{tag} before phone: top leak domains by occurrences", sites == TOP, f"{sites} want {TOP}")
    titles = [page.locator(f'[data-p="leak-{i}"] .m-title').inner_text() for i in range(1, 5)]
    want = [f"{name} leaked: full gallery", f"{name}: all photos and videos", f"{name} videos (new)", f"{name} leak thread"]
    check(f"{tag} profile: leak rows use the templated name", titles == want, titles)
    page.locator("#website").scroll_into_view_if_needed()
    page.wait_for_timeout(600)
    thumbs = page.eval_on_selector_all("[data-p=thumbs] img.p-img", "els => els.map(e => [e.src, e.naturalWidth, getComputedStyle(e).filter])")
    check(f"{tag} thumbs from the stub thumb endpoint, blurred", len(thumbs) == len(GSTATIC) and all(
        t[0].startswith(API + "/api/thumb?u=") and t[1] > 0 and "blur" in t[2] for t in thumbs), thumbs)
    check(f"{tag} profile: Instagram rows = name (@ig)", texts(page, '[data-p="ig"] .m-title') == [f"{name} (@{ACC['instagram']['handle']})"] * 2,
          texts(page, '[data-p="ig"] .m-title'))
    after = [page.locator(f'[data-p="{k}"] .m-site').inner_text() for k in ("own", "blog")] + [
        page.locator('[data-p="own"] .m-title').inner_text(), page.locator('[data-p="tt"] .m-title').inner_text()]
    sd = PROFILE["site_domain"]
    check(f"{tag} profile: after phone site / blog / TikTok", after == [sd, f"{sd} › blog", f"{name}: Official site", "@" + ACC["tiktok"]["handle"]], after)
    check(f"{tag} after phone: removed row = top leak domain", page.locator('[data-p="gone"] .m-site').inner_text() == TOP[0])
    page.locator("#website").screenshot(path=str(out / f"{vp_name}-p2-your-website.png"))
    ph = page.evaluate("""() => {
        const r = k => [...document.querySelectorAll(`.ba [data-p="${k}"] > a.m-link`)].map(a => [a.getAttribute('href'), a.target, a.rel]);
        return {rows: Object.fromEntries(['leak-1', 'leak-2', 'leak-3', 'leak-4', 'ig', 'tt', 'own', 'blog', 'gone'].map(k => [k, r(k)])),
          roles: [...document.querySelectorAll('.ba .phone')].map(p => [p.getAttribute('role'), p.getAttribute('aria-label')]),
          hidden: [...document.querySelectorAll('.ba .phone-screen')].map(s => s.getAttribute('aria-hidden')),
          buried: document.querySelectorAll('.ba [aria-hidden=true] a, .ba [role=img] a').length,
          hint: (document.querySelector('.ba-hint') || {}).textContent};
    }""")
    NT = ["_blank", "noopener noreferrer nofollow"]
    want_rows = {**{f"leak-{i + 1}": [[TOP_URLS[d]] + NT] for i, d in enumerate(TOP)}, "ig": [[ACC["instagram"]["url"]] + NT] * 2,
                 "tt": [[ACC["tiktok"]["url"]] + NT], "own": [["#showcase", "", ""]], "blog": [["#showcase", "", ""]], "gone": [["#pricing", "", ""]]}
    check(f"{tag} phones: profile: every row links (leaks → her leak pages, IG / TikTok → her accounts, site → #showcase, Removed → #pricing)",
          ph["rows"] == want_rows, ph["rows"])
    check(f"{tag} phones: labelled groups, no aria-hidden over links, 'Tap a result to open it'",
          [r[0] for r in ph["roles"]] == ["group", "group"] and all(r[1] and not r[1].startswith("Illustration") for r in ph["roles"])
          and ph["hidden"] == [None, None] and ph["buried"] == 0 and ph["hint"] == "Tap a result to open it", ph)
    hov = None
    if page.locator('.ba [data-p="leak-1"] a').count():   # absent under --break-phones: fail the check, don't crash the run
        page.locator('.ba [data-p="leak-1"] a').hover()
        page.wait_for_timeout(300)
        hov = page.eval_on_selector('.ba [data-p="leak-1"] a', "a => [getComputedStyle(a).backgroundColor, getComputedStyle(a.querySelector('.m-title')).textDecorationLine, getComputedStyle(a).cursor]")
    check(f"{tag} phones: row hover = tint + underlined title + pointer", bool(hov) and hov[0] != "rgba(0, 0, 0, 0)" and hov[1] == "underline" and hov[2] == "pointer", hov)
    page.locator("#website").screenshot(path=str(out / f"{vp_name}-p2b-phones-hover.png"))
    page.mouse.move(0, 0)
    check(f"{tag} profile: showcase url bar = site_domain", page.locator("[data-p=site-url]").inner_text() == sd)
    check(f"{tag} showcase iframe + button carry the slug", page.locator("iframe[data-p=demo]").get_attribute("src") == "showcase/?r=" + FX["slug"]
          and page.locator("a[data-p=demo]").get_attribute("href") == "showcase/?r=" + FX["slug"])
    page.locator("#showcase").scroll_into_view_if_needed()
    page.wait_for_function("() => { const f = document.querySelector('iframe[data-p=demo]'); return f && f.contentDocument && f.contentDocument.readyState === 'complete' && /\\?r=/.test(f.contentWindow.location.search); }", timeout=9000)
    frame = page.frame(url=re.compile(r"/showcase/\?r="))
    try:
        frame.wait_for_function(f"() => document.body.innerText.includes({json.dumps(name)})", timeout=9000)
    except Exception:
        pass
    ft = frame.evaluate("document.body.innerText")
    check(f"{tag} profile: demo iframe shows name, location, handles", all(x in ft for x in (
        name, PROFILE["location"], "@" + ACC["instagram"]["handle"], "@" + ACC["tiktok"]["handle"])), ft[:160])
    check(f"{tag} profile: demo iframe has no pottery / Orla text", not POTTERY.search(ft + frame.title()), POTTERY.findall(ft)[:8])
    try:
        frame.wait_for_function("() => /\\/api\\/media\\//.test(document.querySelector('img.hero__bg').getAttribute('src'))", timeout=8000)
    except Exception:
        pass
    check(f"{tag} profile: demo iframe hero swapped to API media", "/api/media/" in (frame.locator("img.hero__bg").get_attribute("src") or ""))
    hsrc = frame.locator("img.hero__bg").get_attribute("src") or ""
    check(f"{tag} profile: iframe hero src passes MEDIA_RE (API origin /api/media/<slug>/<n>.jpg)",
          re.fullmatch(re.escape(API) + r"/api/media/" + FX["slug"] + r"/\d+\.jpg", hsrc) is not None, hsrc)
    page.wait_for_timeout(700)
    page.locator("#showcase").screenshot(path=str(out / f"{vp_name}-p3-showcase-iframe.png"))
    ctx.close()

    # C. demo direct: progressive media swap, no layout jump, slug kept on links
    stub_media(FX["slug"])
    ctx = new_ctx()
    page = ctx.new_page()
    page.goto(base + "showcase/?r=" + FX["slug"], wait_until="load")
    box0 = page.locator("img.hero__bg").bounding_box()
    try:
        page.wait_for_function("() => /\\/api\\/media\\//.test(document.querySelector('img.hero__bg').getAttribute('src'))", timeout=6000)
    except Exception:
        pass
    pending = (page.locator("img.hero__bg").get_attribute("src") or "", page.locator('img[data-p-media="1"]').get_attribute("src") or "",
               shown(page, "[data-p-media-only]"))
    check(f"{tag} profile: media pending: hero + portrait swapped, gallery still hidden",
          pending[0].startswith(API + "/api/media/") and pending[1].startswith(API + "/api/media/") and pending[2] == 0, pending)
    page.wait_for_timeout(700)
    box1 = page.locator("img.hero__bg").bounding_box()
    pbox = page.locator('img[data-p-media="1"]').bounding_box()
    check(f"{tag} profile: no layout jump on swap", box0 == box1 and pbox and abs(pbox["width"] / pbox["height"] - 2400 / 3200) < .02, f"{box0} {box1} {pbox}")
    page.screenshot(path=str(out / f"{vp_name}-p4-demo-media-pending.png"))
    try:
        page.wait_for_function("() => [...document.querySelectorAll('[data-p-media-only]')].filter(e => getComputedStyle(e).display !== 'none').length === 4", timeout=9000)
    except Exception:
        pass
    page.locator("[data-p-gallery]").scroll_into_view_if_needed()
    try:
        page.wait_for_function("() => [...document.querySelectorAll('[data-p-media-only] img')].every(e => e.complete && e.naturalWidth > 0)", timeout=6000)
    except Exception:
        pass
    gal = page.eval_on_selector_all("[data-p-media-only] img", "els => els.map(e => [e.getAttribute('src'), e.naturalWidth])")
    check(f"{tag} profile: media ready: 4 gallery photos fade in from the API", shown(page, "[data-p-media-only]") == 4
          and all(g[0].startswith(API + "/api/media/") and g[1] > 0 for g in gal), gal)
    page.wait_for_timeout(700)
    page.screenshot(path=str(out / f"{vp_name}-p5-demo-media-ready.png"))
    about = page.locator("nav a[href*='about.html']").first.get_attribute("href") or ""
    check(f"{tag} profile: internal demo links keep ?r=", "about.html?r=" + FX["slug"] in about, about)
    if vp_name == "desktop":
        for rel in DEMO_PAGES:
            page.goto(base + "showcase/" + rel + "?r=" + FX["slug"], wait_until="load")
            try:
                page.wait_for_function(f"() => document.title.includes({json.dumps(name)})", timeout=6000)
            except Exception:
                pass
            t = page.evaluate("document.body.innerText")
            alts = " ".join(page.eval_on_selector_all("img", "els => els.filter(e => e.offsetParent !== null).map(e => e.alt)"))
            check(f"{tag} profile: showcase/{rel or 'index'}: name, no pottery, no she/her", name in page.title()
                  and name.upper() in page.locator(".nav__logo").inner_text().upper()
                  and not POTTERY.search(t + page.title() + alts) and not PRONOUN.search(t),
                  (POTTERY.findall(t + alts) + PRONOUN.findall(t))[:6])
        page.goto(base + "showcase/links.html?r=" + FX["slug"], wait_until="load")
        page.wait_for_timeout(1500)
        btns = page.eval_on_selector_all(".p-links a", "els => els.map(e => [e.href, e.target])")
        av = page.eval_on_selector("img.links-avatar", "e => [e.getAttribute('src'), e.naturalWidth]")
        check(f"{tag} profile: links page = the profile accounts + leak-page socials for new platforms, avatar from the API",
              [b[0] for b in btns] == [a["url"] for a in PROFILE["accounts"]] + FOUND and all(b[1] == "_blank" for b in btns)
              and av[0] == f"{API}/api/avatar/{FX['slug']}" and av[1] == 48, f"{btns} {av}")
        page.screenshot(path=str(out / f"{vp_name}-p6-demo-links.png"), full_page=True)
    ctx.close()

    # D. media none / 404: placeholders stay, polling stops, scan page status hidden
    for mode in ("none", "404"):
        stub_media(FX["slug"], mode)
        ctx = new_ctx()
        page = ctx.new_page()
        net["api"].clear()
        page.goto(base + "showcase/?r=" + FX["slug"], wait_until="load")
        page.wait_for_timeout(7500)
        polls = [u for u in net["api"] if re.search(r"/api/media/[^/]+$", u)]
        hero = page.locator("img.hero__bg").get_attribute("src")
        check(f"{tag} profile: media {mode}: placeholders kept, galleries hidden, polling stopped",
              hero == "imgs/portrait.webp" and shown(page, "[data-p-media-only]") == 0 and len(polls) == (1 if mode == "none" else 2),
              f"hero={hero} polls={len(polls)}")
        page.goto(base + "scan/?r=" + FX["slug"], wait_until="load")
        page.wait_for_selector("#report:not([hidden])", timeout=6000)
        page.wait_for_timeout(4000)
        check(f"{tag} media {mode}: scan page status line hidden", page.locator("#after-media").is_hidden())
        ctx.close()
    stub_media(FX["slug"], "relative")
    ctx = new_ctx()
    page = ctx.new_page()
    page.goto(base + "showcase/?r=" + FX["slug"], wait_until="load")
    try:
        page.wait_for_function("() => document.querySelector('img.hero__bg').naturalWidth === 1067", timeout=6000)
    except Exception:
        pass
    rel = page.eval_on_selector("img.hero__bg", "e => [e.getAttribute('src'), e.naturalWidth]")
    check(f"{tag} profile: same-origin relative media srcs accepted", rel == [f"/api/media/{FX['slug']}/0.jpg", 1067], rel)
    ctx.close()
    stub_media(FX["slug"])

    # E. scan only (profile null): phones from the scan, demo stays the fictional creator
    ctx = new_ctx()
    page = ctx.new_page()
    page.goto(base + "?r=demoNoProf01", wait_until="load")
    page.wait_for_selector("[data-p=scanned]:not([hidden])", timeout=9000)
    h = FX["handle"]
    got = (texts(page, "[data-p=search]"), page.locator('[data-p="leak-1"] .m-title').inner_text(), shown(page, '[data-p="ig"], [data-p="tt"]'),
           page.locator('[data-p="own"] .m-site').inner_text(), page.locator("[data-p=site-url]").inner_text())
    check(f"{tag} scan-only: phones use the handle, unknown IG/TikTok rows hidden, url bar default",
          got == ([h, h], f"{h} leaked: full gallery", 0, re.sub(r"[^a-z0-9-]", "", h.lower()) + ".com", "yourname.com"), got)
    page.locator("#showcase").scroll_into_view_if_needed()
    page.wait_for_timeout(2500)
    frame = page.frame(url=re.compile(r"/showcase/\?r=demoNoProf01"))
    ft = frame.evaluate("document.body.innerText") if frame else ""
    check(f"{tag} scan-only: demo stays Orla, no @handle in its name slots", "Orla Brennick" in ft and h not in ft
          and frame.locator(".nav__logo").inner_text().upper() == "ORLA BRENNICK", ft[:120])
    page.locator("#website").screenshot(path=str(out / f"{vp_name}-p7-scan-only.png"))
    page.goto(base + "?r=demoFoundIG1", wait_until="load")
    page.wait_for_selector("[data-p=scanned]:not([hidden])", timeout=9000)
    ig = [s["handle"] for s in FX["aliases"]["socials"] if s["platform"] == "instagram"][0]
    got = (texts(page, '[data-p="ig"] .m-title'), shown(page, '[data-p="tt"]'))
    check(f"{tag} aliases: scan-only: leak-page Instagram fills the IG rows", got == ([f"{h} (@{ig})"] * 2, 0), got)
    ctx.close()

    # F. malicious values never reach the DOM
    ctx = new_ctx()
    page = ctx.new_page()
    bad = []
    for path in ("?r=evilR3port01", "showcase/?r=evilR3port01", "showcase/about.html?r=evilR3port01", "showcase/links.html?r=evilR3port01"):
        page.goto(base + path, wait_until="load")
        page.wait_for_timeout(4200 if path.startswith("showcase/?") else 1500)
        if path.startswith("?"):
            page.locator("#showcase").scroll_into_view_if_needed()
            page.wait_for_timeout(1500)
        docs = [page.content()] + [f.content() for f in page.frames[1:]]
        for d in docs:
            for needle in ("alert(1)", "javascript:", "onerror", "onload=", "A" * 60, "x" * 400, "evil.example"):
                if needle in d:
                    bad.append(f"{path}: {needle}")
        if path.startswith("?"):
            check(f"{tag} profile: malicious profile falls back to the valid username", texts(page, "[data-p=search]") == ["evil.user"] * 2,
                  texts(page, "[data-p=search]"))
            check(f"{tag} malicious hits: only the valid domain is shown", page.locator('[data-p="leak-1"] .m-site').inner_text() == "safe-leak.example"
                  and shown(page, '[data-p^="leak-"]') == 1 and page.locator("[data-p=thumbs] img").count() == 0)
    check(f"{tag} malicious fixture: nothing reaches the DOM, no dialog", not bad and not net["dialogs"], bad + net["dialogs"])
    ctx.close()

    # G. real flow: scan → report card → landing (?r=, then localStorage) → reset
    stub_media(FX["slug"])
    ctx = new_ctx()
    page = ctx.new_page()
    page.goto(base + "scan/?p=onlyfans.com&h=demo.creator", wait_until="load")
    page.wait_for_selector("#report:not([hidden])", timeout=15000)
    slug = parse_qs(urlsplit(page.url).query).get("r", [""])[0]
    page.locator("#after-card").scroll_into_view_if_needed()
    try:
        page.wait_for_function("() => document.getElementById('after-media').textContent === 'Photos ready'", timeout=10000)
    except Exception:
        pass
    check(f"{tag} report card links to the landing section + demo", page.locator("#after-link").get_attribute("href") == f"../?r={slug}#website"
          and page.locator("#demo-link").get_attribute("href") == f"../showcase/?r={slug}")
    check(f"{tag} profile: report status line ends at 'Photos ready'", page.locator("#after-media").is_visible()
          and page.locator("#after-media").inner_text() == "Photos ready", page.locator("#after-media").inner_text())
    page.locator("#after-card").screenshot(path=str(out / f"{vp_name}-p8-report-card.png"))
    last = json.loads(page.evaluate("localStorage.getItem('leakscan.last')") or "{}")
    check(f"{tag} scan writes leakscan.last", last.get("slug") == slug and last.get("handle") == "demo.creator", last)
    with page.expect_navigation():
        page.locator("#after-link").click()
    page.wait_for_selector("[data-p=scanned]:not([hidden])", timeout=9000)
    check(f"{tag} card → landing #website", page.url.endswith(f"/?r={slug}#website"), page.url)
    page.goto(base, wait_until="load")
    page.wait_for_selector("[data-p=scanned]:not([hidden])", timeout=9000)
    check(f"{tag} profile: landing without ?r= personalizes from localStorage", texts(page, "[data-p=search]") == [name, name])
    page.locator("#website").screenshot(path=str(out / f"{vp_name}-p9-landing-from-localstorage.png"))
    if page.locator("[data-p=scanned] button").is_visible():
        page.locator("[data-p=scanned] button").click()
    page.wait_for_load_state("load")
    page.wait_for_timeout(1000)
    check(f"{tag} Reset restores the defaults", texts(page, "[data-p=search]") == ["yourname", "yourname"]
          and page.evaluate("localStorage.getItem('leakscan.last')") is None and page.locator("[data-p=scanned]").is_hidden())
    ctx.close()

    # H. public API for a later inline scan: apply(result) without reload, twice, with other data
    ctx = new_ctx()
    page = ctx.new_page()
    page.goto(base, wait_until="load")
    page.wait_for_timeout(500)
    api_res = page.evaluate("""async (api) => {
        const get = async s => (await fetch(api + '/api/scan-result/' + s)).json();
        const P = window.LeakScanPersonalize, q = s => [...document.querySelectorAll(s)];
        const vis = s => q(s).filter(e => getComputedStyle(e).display !== 'none' && !e.hidden).length;
        const snap = () => ({search: q('[data-p=search]').map(e => e.textContent), url: q('[data-p=site-url]')[0].textContent,
            ig: vis('[data-p=ig]'), thumbs: q('[data-p=thumbs] img').length, handles: q('[data-p=report-handle],[data-p=scan-handle]').map(e => e.textContent),
            line: vis('[data-p=scanned]'), leak1: q('[data-p=leak-1] .m-site')[0].textContent, links: q('.ba a.m-link').length,
            hints: q('.ba-hint').length});
        const out = {bad: [P.apply(null), P.apply({slug: '<x>'}), P.applySlug('../x')], keys: Object.keys(P).sort()};
        const full = await get('demoR3port01'), bare = await get('demoNoProf01');
        out.ok1 = P.apply(full); P.apply(full); out.a = snap();
        out.ok2 = P.apply(bare); out.b = snap();
        return out;
    }""", API)
    check(f"{tag} public API: window.LeakScanPersonalize {{apply, applySlug, pollMedia}}, junk rejected",
          api_res["keys"] == ["apply", "applySlug", "pollMedia"] and api_res["bad"] == [False, False, False] and api_res["ok1"] and api_res["ok2"], api_res)
    a, b2 = api_res["a"], api_res["b"]
    check(f"{tag} phones: apply() twice = same links, other data re-wires (no IG / TikTok rows without a profile)",
          (a["links"], a["hints"], b2["links"], b2["hints"]) == (10, 1, 7, 1), (a["links"], a["hints"], b2["links"], b2["hints"]))
    check(f"{tag} profile: apply() personalizes in place, twice = same DOM (3 thumbs, not 6)",
          a["search"] == [name, name] and a["url"] == sd and a["ig"] == 2 and a["thumbs"] == len(GSTATIC), a)
    check(f"{tag} apply() again with other data resets the slots first",
          b2["search"] == [h, h] and b2["url"] == "yourname.com" and b2["ig"] == 0 and b2["thumbs"] == len(GSTATIC)
          and b2["handles"] == ["@" + h, "@" + h] and b2["line"] == 1 and b2["leak1"] == TOP[0], b2)
    ctx.close()

    hosts = {urlsplit(u).hostname for u in net["outside"]}
    check(f"{tag} nothing left loopback but the demo's aborted Google Fonts", hosts <= FONT_HOSTS, sorted(hosts))
    check(f"{tag} production hosts never contacted", not any(h in u for u in net["outside"] + net["api"] for h in PROD_HOSTS))
    check(f"{tag} no JS errors", not net["errors"], net["errors"])


LOOP = ("127.0.0.1", "localhost")
ALLOW_LINE = "return HOSTS.indexOf(h) >= 0;"


def overlap(a, b):
    return a and b and a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"] \
        and a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"]


def chat_log():
    with urllib.request.urlopen(base + "api/_chat-log") as r:
        return json.loads(r.read())


def askai(browser, vp_name, vp):
    """The Ask-AI popup on the homepage, one viewport. See module docstring."""
    v = f"{vp_name} askai"
    opts = dict(viewport=vp, device_scale_factor=2 if vp_name == "phone" else 1,
                is_mobile=vp_name == "phone", has_touch=vp_name == "phone")
    ctx = browser.new_context(**opts)
    outside, errors, reqs = [], [], []

    def route(r, _req):
        if urlsplit(r.request.url).hostname in LOOP or r.request.url.startswith("file:"):
            return r.continue_()
        try:
            frame = r.request.frame.url
        except Exception:
            frame = ""
        outside.append((r.request.url, frame))
        r.abort()

    ctx.route("**/*", route)
    if BREAK_ALLOWLIST:
        def broken(r, _req):
            if not r.request.url.startswith("http"):
                return r.continue_()
            body = r.fetch().text()
            assert ALLOW_LINE in body, "break-allowlist: marker line not found in chat.js"
            r.fulfill(body=body.replace(ALLOW_LINE, "return true;"), content_type="application/javascript")
        ctx.route("**/js/chat.js", broken)
    page = ctx.new_page()
    page.on("request", lambda q: reqs.append(q.url))
    page.on("pageerror", lambda e: errors.append(e.stack or str(e)))
    # Chrome logs every non-2xx fetch as a console error; the stub-429 one is the expected path, not a bug.
    page.on("console", lambda m: m.type == "error" and (urlsplit(m.location.get("url") or base).hostname in LOOP
                                                        or (m.location.get("url") or "").startswith("file:"))
            and not ("status of 429" in m.text and "/api/chat" in (m.location.get("url") or ""))
            and errors.append(f"{m.text} @ {m.location.get('url')}"))

    def shot(name):
        for scheme in ("light", "dark"):
            page.emulate_media(color_scheme=scheme)
            page.wait_for_timeout(150)
            page.screenshot(path=str(out / f"{vp_name}-askai-{name}-{scheme}.png"))
        page.emulate_media(color_scheme="light")

    L = page.locator(".askai-launcher")
    dlg = page.locator("#askai")
    inp = page.locator("#askai-input")
    is_open = lambda: page.evaluate("document.getElementById('askai').open")
    active_in_dialog = lambda: page.evaluate("document.getElementById('askai').contains(document.activeElement)")
    bot = page.locator(".askai-bot")

    def ask(q):
        inp.fill(q)
        inp.press("Enter")

    def settle():
        page.wait_for_selector(".askai-log[aria-busy=false]", timeout=10000)

    def click_L():   # phone: the launcher is hidden while the hero is on screen, so scroll past it first
        if vp_name == "phone" and page.evaluate("document.querySelector('.hero').getBoundingClientRect().bottom > 0"):
            page.evaluate("document.getElementById('how').scrollIntoView({behavior: 'instant'})")
            page.wait_for_selector(".askai-launcher:not(.in-hero)", timeout=3000)
        L.click()

    # 1. launcher: covers no hero text / control at load (phone: hidden until the hero scrolls away)
    page.goto(base, wait_until="load")
    page.wait_for_selector(".askai-launcher:not([hidden])", state="attached", timeout=5000)
    page.wait_for_timeout(500)
    covered = page.evaluate("""() => { const L = document.querySelector('.askai-launcher');
      if (getComputedStyle(L).visibility === 'hidden') return [];
      const b = L.getBoundingClientRect(), hit = [], w = document.createTreeWalker(document.querySelector('.hero'), NodeFilter.SHOW_TEXT);
      for (let n; (n = w.nextNode());) { if (!n.textContent.trim()) continue; const r = document.createRange(); r.selectNodeContents(n);
        for (const q of r.getClientRects()) if (q.right > b.left && q.left < b.right && q.bottom > b.top && q.top < b.bottom) hit.push(n.textContent.trim()); }
      return hit; }""")
    check(f"{v} launcher covers no hero text at load", covered == [], covered)
    if vp_name == "phone":
        check(f"{v} launcher hidden while hero on screen", not L.is_visible())
        page.evaluate("document.getElementById('how').scrollIntoView()")
        page.wait_for_selector(".mobile-cta.show", timeout=3000)
        page.wait_for_timeout(500)
    check(f"{v} launcher visible + labelled", L.is_visible() and L.get_attribute("aria-label") == "Ask AI before you DM me"
          and "Ask AI before you DM me" in L.inner_text(), L.inner_text())
    lb = L.bounding_box()
    if vp_name == "phone":
        mb = page.locator(".mobile-cta").bounding_box()
        check(f"{v} launcher clear of sticky scan bar", not overlap(lb, mb), f"launcher={lb} bar={mb}")
    else:
        cta = page.locator("#scan button[type=submit]").bounding_box()
        check(f"{v} launcher clear of hero CTA", not overlap(lb, cta), f"launcher={lb} cta={cta}")
    check(f"{v} launcher inside viewport bottom-right", lb["x"] + lb["width"] <= vp["width"] and lb["y"] + lb["height"] <= vp["height"]
          and vp["width"] - (lb["x"] + lb["width"]) <= 32 and vp["height"] - (lb["y"] + lb["height"]) <= (100 if vp_name == "phone" else 32), lb)   # phone: above the sticky bar
    shot("1-launcher")
    if vp_name == "phone":
        page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")

    # 2. open / close / focus
    click_L()
    page.wait_for_timeout(300)
    d = page.get_by_role("dialog", name="Ask about Abolita")
    check(f"{v} opens role=dialog named, aria-modal, input focused", is_open() and d.count() == 1 and d.is_visible()
          and dlg.get_attribute("aria-modal") == "true" and page.evaluate("document.activeElement.id") == "askai-input")
    box = dlg.bounding_box()
    if vp_name == "phone":
        check(f"{v} bottom sheet", abs(box["y"] + box["height"] - vp["height"]) < 2 and box["width"] == vp["width"], box)
    else:
        check(f"{v} 380px panel bottom-right", round(box["width"]) == 380 and box["x"] + box["width"] <= vp["width"] - 20, box)
    note = page.locator(".askai-note")
    check(f"{v} disclaimer + 3 contacts", "Answers come from this page. For your case, message Jaka" in note.inner_text()
          and note.locator("a[href='https://t.me/jakabasej']").count() == 1 and note.locator("a[href='https://wa.me/38640703992']").count() == 1
          and note.locator("a[href='mailto:me@jackbase.dev']").count() == 1)
    faq_q = page.eval_on_selector_all("#faq details summary", "els => els.map(e => e.textContent.trim())")
    chips = page.eval_on_selector_all(".askai-chip", "els => els.map(e => e.textContent)")
    check(f"{v} greeting + chips from page FAQ", bot.first.is_visible() and chips[:1] == ["What does it cost?"]
          and len(chips) >= 4 and chips[1:] == faq_q[:len(chips) - 1], chips)
    trapped = True
    for _ in range(14):
        page.keyboard.press("Tab")
        trapped = trapped and active_in_dialog()
    for _ in range(4):
        page.keyboard.press("Shift+Tab")
        trapped = trapped and active_in_dialog()
    check(f"{v} focus trapped in dialog (Tab/Shift+Tab)", trapped)
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    check(f"{v} Esc closes, focus back on launcher", not is_open()
          and page.evaluate("document.activeElement.classList.contains('askai-launcher')"))
    click_L()
    page.locator(".askai-close").click()
    check(f"{v} close button closes, focus back", not is_open()
          and page.evaluate("document.activeElement.classList.contains('askai-launcher')"))
    click_L()
    page.mouse.click(8, 8)
    page.wait_for_timeout(200)
    check(f"{v} backdrop click closes", not is_open())
    faq_link = page.locator("#faq a[data-askai-open]")
    faq_link.scroll_into_view_if_needed()
    faq_link.click()
    page.wait_for_timeout(200)
    opened = is_open()
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    check(f"{v} FAQ 'Ask the AI' link opens it, focus returns to link", opened and not is_open()
          and page.evaluate("document.activeElement.hasAttribute('data-askai-open')"))
    page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")

    # 3. cached answers: chips + fuzzy typed questions, zero network
    click_L()
    n = len(reqs)
    t0 = time.time()
    page.locator(".askai-chip", has_text="What does it cost?").click()
    page.wait_for_selector("[data-source=cached]", timeout=2000)
    ms = (time.time() - t0) * 1000
    c1 = page.locator("[data-source=cached]").last
    check(f"{v} chip → instant cached answer, 0 requests", len(reqs) == n and "€250" in c1.inner_text() and "€500" in c1.inner_text(),
          f"{ms:.0f} ms, {len(reqs) - n} requests")
    check(f"{v} cached answer: section link + more-detail option",
          c1.locator("a.askai-anchor[href='#pricing']").inner_text() == "Pricing"
          and c1.locator("button", has_text="Ask the AI for more detail").count() == 1)
    shot("2-cached")
    faq_a = page.eval_on_selector("#faq details p", "e => e.textContent.replace(/\\s+/g, ' ').trim()")
    page.locator(".askai-chip", has_text=faq_q[0]).click()
    c2 = page.locator("[data-source=cached]").last
    check(f"{v} FAQ chip answer = page text + FAQ link", " ".join(c2.inner_text().split()).startswith(faq_a)
          and c2.locator("a.askai-anchor[href='#faq']").inner_text() == "FAQ" and len(reqs) == n)
    for q in ("how much does it cost", "how much", "Is it legal?", "can I cancel"):
        k = page.locator("[data-source=cached]").count()
        ask(q)
        page.wait_for_timeout(150)
        check(f"{v} fuzzy '{q}' → cached, 0 requests", page.locator("[data-source=cached]").count() == k + 1 and len(reqs) == n
              and page.locator(".askai-user").last.inner_text() == q)
    check(f"{v} 'how much' → pricing answer", "€250" in page.locator("[data-source=cached]").nth(3).inner_text())
    inp.fill("line one")
    inp.press("Shift+Enter")
    inp.type("line two")
    check(f"{v} Shift+Enter = newline, no send", inp.input_value() == "line one\nline two"
          and page.locator(".askai-user").last.inner_text() == "can I cancel")
    inp.fill("")

    # 4. streamed answers (a scan slug in localStorage, as scan/ leaves it, is sent along; set only now so
    # personalize.js's own fetches for it can't land inside the zero-request windows above)
    page.evaluate("localStorage.setItem('leakscan.last', JSON.stringify({slug: 'demoR3port01', handle: 'demo.creator'}))")
    nlog = len(chat_log())
    q = "Do you work with agencies?"
    ask(q)
    page.wait_for_selector("[data-source=ai]:not(.askai-typing)", timeout=5000)
    first_len = len(page.locator("[data-source=ai]").last.inner_text())
    busy_mid = page.locator(".askai-log").get_attribute("aria-busy") == "true"
    settle()
    ai = page.locator("[data-source=ai]").last
    final = ai.inner_text()
    check(f"{v} other question → streamed answer (grows token by token)", busy_mid and 0 < first_len < len(final)
          and "Short answer" in final, f"{first_len} → {len(final)} chars")
    log = chat_log()
    body = log[-1] if len(log) > nlog else {}
    check(f"{v} chat request: kb, slug, last user msg, ≤8 msgs", body.get("kb") == "landing" and body.get("slug") == "demoR3port01"
          and body.get("messages", [{}])[-1] == {"role": "user", "content": q} and len(body["messages"]) <= 8
          and body["messages"][0]["role"] == "user", {k: (len(v_) if k == "messages" else v_) for k, v_ in body.items()})
    ask("blorp fizzle wug")
    settle()
    log = chat_log()
    check(f"{v} nonsense → not cached, history capped at 8", len(log) == nlog + 2 and len(log[-1]["messages"]) <= 8
          and page.locator("[data-source=ai]").count() == 2, len(log[-1]["messages"]))

    # 5. link rules (on the first streamed answer)
    hrefs = ai.evaluate("b => [...b.querySelectorAll('a')].map(a => [a.getAttribute('href'), a.textContent, a.target, a.rel])")
    check(f"{v} links: #pricing is <a> 'Pricing'", ["#pricing", "Pricing", "", ""] in hrefs, hrefs)
    check(f"{v} links: t.me is <a> target=_blank rel=noopener", ["https://t.me/jakabasej", "Telegram", "_blank", "noopener"] in hrefs, hrefs)
    check(f"{v} links: javascript: is plain text", not any("javascript" in (h[0] or "").lower() for h in hrefs)
          and "Don't click x or" in final, hrefs)
    check(f"{v} links: evil.example is plain text", not any("evil.example" in (h[0] or "") for h in hrefs)
          and "this deal" in final and "https://evil.example/raw" in final, hrefs)
    check(f"{v} links: bare #contact → labelled anchor", ["#contact", "Ran the scan? Send me the report link", "", ""] in hrefs, hrefs)
    check(f"{v} bold + bullets rendered, no on* attrs", ai.locator("strong").count() == 3 and ai.locator("li").count() == 3
          and ai.evaluate("b => [...b.querySelectorAll('*')].every(e => ![...e.attributes].some(a => a.name.startsWith('on')))"))
    shot("3-streamed")
    ai.locator("a[href='#pricing']").click()
    try:   # smooth scroll over ~7000px takes ~1.5 s; settles at the page's scroll-padding-top (header + 12px)
        page.wait_for_function("Math.abs(document.getElementById('pricing').getBoundingClientRect().top"
                               " - parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop)) < 8", timeout=5000)
    except Exception:
        pass
    top = page.evaluate("document.getElementById('pricing').getBoundingClientRect().top")
    check(f"{v} anchor click scrolls to #pricing" + (" (sheet closed)" if vp_name == "phone" else " (panel stays)"),
          0 <= top < 120 and is_open() == (vp_name != "phone"), f"top={top:.0f} open={is_open()}")

    # 6. failure paths
    if not is_open():
        click_L()
    for word, kind, text in (("stub-fail", "failed", "couldn’t answer"), ("stub-429", "rate_limited", "Too many")):
        ask(f"{word} please")
        page.wait_for_selector(f"[data-source=error][data-kind={kind}]", timeout=5000)
        e = page.locator(f"[data-source=error][data-kind={kind}]").last
        hs = e.evaluate("b => [...b.querySelectorAll('a')].map(a => a.href)")
        check(f"{v} {kind} → message + 3 contact links + retry", text in e.inner_text() and len(hs) == 3
              and hs[0].startswith("https://t.me/jakabasej") and hs[1].startswith("https://wa.me/38640703992")
              and hs[2].startswith("mailto:me@jackbase.dev") and e.locator("button", has_text="Try again").count() == 1, hs)
        settle()
    shot("4-fallback")
    k = len(chat_log())
    page.locator("[data-source=error] button", has_text="Try again").last.click()
    page.wait_for_selector("[data-source=error][data-kind=rate_limited]", timeout=5000)
    settle()
    check(f"{v} retry resends", len(chat_log()) == k + 1 and chat_log()[-1]["messages"][-1]["content"] == "stub-429 please")
    k = page.locator("[data-source=cached]").count()
    page.locator("[data-source=cached] button", has_text="Ask the AI for more detail").first.click()
    settle()
    check(f"{v} 'more detail' → AI request", chat_log()[-1]["messages"][-1]["content"] == "Can you give me more detail on that?")

    # 7. storage: sessionStorage restore, nothing in localStorage/cookies
    page.reload(wait_until="load")
    click_L()
    users = page.eval_on_selector_all(".askai-user", "els => els.map(e => e.textContent)")
    check(f"{v} reload restores chat from sessionStorage", q in users and "how much" in users, len(users))
    check(f"{v} no localStorage writes, no cookies", page.evaluate("Object.keys(localStorage)") == ["leakscan.last"]
          and ctx.cookies() == [], page.evaluate("Object.keys(localStorage)"))
    page.keyboard.press("Escape")

    # 8. no API origin: page opened from disk (no data-api, not http) → nothing to call
    k, kl, ne = len(reqs), len(chat_log()), len(errors)
    page.goto((ROOT / "site" / "index.html").as_uri(), wait_until="load")
    click_L()
    page.locator(".askai-chip", has_text="What does it cost?").click()
    ask("Do you work with agencies?")
    page.wait_for_selector("[data-source=error][data-kind=no_api]", timeout=3000)
    e = page.locator("[data-source=error][data-kind=no_api]")
    check(f"{v} no API origin → cached still works, fallback + contacts, no request", len(chat_log()) == kl
          and e.locator("a").count() == 3 and not any("/api/chat" in u for u in reqs[k:]),
          {"chat_posts": len(chat_log()) - kl, "links": e.locator("a").count(), "api": [u for u in reqs[k:] if "/api/" in u]})
    page.keyboard.press("Escape")
    # From disk the showcase iframe opens Chrome's directory listing, whose own scripts throw; keep only chat.js errors.
    errors[ne:] = [x for x in errors[ne:] if "chat.js" in x]

    # 9. reduced motion
    anim = lambda: page.eval_on_selector(".askai-panel", "e => getComputedStyle(e).animationName")
    page.goto(base, wait_until="load")
    click_L()
    a1 = anim()
    page.keyboard.press("Escape")
    page.emulate_media(reduced_motion="reduce")
    click_L()
    a2 = anim()
    page.keyboard.press("Escape")
    page.emulate_media(reduced_motion="no-preference")
    check(f"{v} reduced motion: no open animation", a1 == "askai-in" and a2 == "none", f"{a1} / {a2}")

    main_outside = [u for u, f in outside if "/showcase/" not in f and urlsplit(u).hostname not in FONT_HOSTS]
    check(f"{v} no request left loopback (popup / main frame)", not main_outside, main_outside)
    check(f"{v} no console / JS errors", not errors, errors)
    ctx.close()

    # 10. JS off: no launcher, no dialog
    ctx = browser.new_context(java_script_enabled=False, **opts)
    ctx.route("**/*", lambda r, _q: r.continue_() if urlsplit(r.request.url).hostname in LOOP else r.abort())
    page = ctx.new_page()
    page.goto(base, wait_until="load")
    check(f"{v} JS off: launcher + dialog hidden", not page.locator(".askai-launcher").is_visible()
          and not page.locator("#askai").is_visible())
    ctx.close()


# ---------------------------------------------------------------- inline
# The hero form scans on the landing page itself (js/inline-scan.js + js/scan-engine.js). Checks named "hero: ..."
# need a fresh scan `result` event; "profile: ..." need `profile`.
def _rows(fx):
    """Mirror of inline-scan.js model(): distinct valid links, hits first (Live / Found), then Google results (Indexed)."""
    rows, seen = [], set()
    for h in fx["hits"]:
        if h["url"] not in seen:
            seen.add(h["url"])
            rows.append((h["domain"], h.get("title"), h["url"], "Live" if h.get("live") is True else "Found"))
    for r in fx.get("results", []):
        if r["link"] not in seen:
            seen.add(r["link"])
            rows.append((r["domain"], r.get("title"), r["link"], "Indexed"))
    return rows


def _site_counts(rows):
    occ, order = {}, []
    for d, *_ in rows:
        if d not in occ:
            occ[d] = 0
            order.append(d)
        occ[d] += 1
    return [(d, occ[d]) for d in order]


def _sites(rows):
    occ, order = {}, []
    for d, *_ in rows:
        if d not in occ:
            occ[d] = 0
            order.append(d)
        occ[d] += 1
    return [(d, occ[d]) for d in sorted(order, key=lambda d: -occ[d])][:5]


def inline_flow(browser, vp_name, vp):
    tag = f"{vp_name} inline"
    rows = _rows(FX)
    N = len(rows)
    net = {"outside": [], "bodies": [], "errors": [], "console": [], "nav": []}

    def new_ctx(js=True, scheme="light", motion="no-preference"):
        ctx = browser.new_context(viewport=vp, device_scale_factor=2 if vp_name == "phone" else 1, java_script_enabled=js,
                                  is_mobile=vp_name == "phone", has_touch=vp_name == "phone", color_scheme=scheme, reduced_motion=motion)
        # layout shifts, for the zero-CLS checks (PerformanceObserver, buffered from page start)
        ctx.add_init_script("window.__ls = []; try { new PerformanceObserver(l => l.getEntries().forEach(e => window.__ls.push([e.startTime, e.value, e.hadRecentInput]))).observe({type: 'layout-shift', buffered: true}); } catch (e) {}")

        def route(r, _req):
            if urlsplit(r.request.url).hostname in ("127.0.0.1", "localhost"):
                r.continue_()
            else:
                net["outside"].append(r.request.url)
                r.abort()
        ctx.route("**/*", route)
        break_routes(ctx)

        def on_page(pg):
            pg.on("pageerror", lambda e: net["errors"].append(str(e)))
            # the browser logs each provoked 429 / 400 / aborted scan POST as "Failed to load resource": expected here
            pg.on("console", lambda m: m.type == "error" and urlsplit(m.location.get("url") or "").hostname not in FONT_HOSTS
                  and not (m.text.startswith("Failed to load resource") and "/api/public-scan" in (m.location.get("url") or ""))
                  and net["console"].append(m.text + " @ " + (m.location.get("url") or "")))
            pg.on("request", lambda q: q.method == "POST" and "/api/public-scan" in q.url and net["bodies"].append(json.loads(q.post_data)))
            pg.on("framenavigated", lambda f: f == pg.main_frame and net["nav"].append(f.url))
        ctx.on("page", on_page)
        return ctx

    def shot(page, name, el=None):
        for scheme in ("light", "dark"):
            page.emulate_media(color_scheme=scheme)
            page.wait_for_timeout(80)
            (page.locator(el) if el else page).screenshot(path=str(out / f"{vp_name}-i{name}-{scheme}.png"))
        page.emulate_media(color_scheme="light")

    def submit(page, h, social=""):
        net["bodies"].clear()
        page.locator("#scan input[name=h]").fill(h)
        page.locator("#scan input[name=ig]").fill(social)
        page.locator("#scan button[type=submit]").click()

    def settled(page, timeout=15000):
        page.wait_for_function("() => { const c = document.querySelector('.report-card'); return c && !c.hasAttribute('aria-busy') && !document.querySelector('#scan button').disabled; }", timeout=timeout)
        page.wait_for_timeout(250)

    card = lambda page: page.evaluate("""() => {
        const c = document.querySelector('.report-card'), L = c.querySelector('.live'), t = s => { const e = L && L.querySelector(s); return e && !e.hidden ? e.textContent.trim() : null; };
        return {live: c.classList.contains('is-live'), title: t('.live-title'), socials: t('.live-socials'), aliases: t('.live-aliases'), count: t('.live-count'),
          status: t('.live-status'), error: L && L.getAttribute('data-error'), empty: t('.live-empty'), more: t('.live-more'),
          rows: [...c.querySelectorAll('.live-rows li')].map(li => { const a = li.querySelector('a'); return {tag: a && a.tagName,
            dom: li.querySelector('.live-dom').textContent, ttl: li.querySelector('.live-ttl').textContent, href: a && a.href,
            target: a && a.target, rel: a && a.rel, badge: li.querySelector('.live-badge').textContent}; }),
          open: L && L.querySelector('.live-open') ? L.querySelector('.live-open').getAttribute('href') : null,
          msgs: L ? [...L.querySelectorAll('[data-msg]')].map(a => a.href) : [], role: c.getAttribute('role')};
    }""")
    ill = lambda page: page.evaluate("""() => {
        const s = document.querySelector('.gmini'), n = s.querySelector('[data-live] .gmini-n'), send = document.querySelector('[data-free-send]');
        return {live: s.classList.contains('is-live'), pill: n && n.textContent, label: s.getAttribute('aria-label'), role: s.getAttribute('role'),
          tiles: [...s.querySelectorAll('[data-live=band-grid] a.gi-card')].map(a => [a.href, a.target, a.rel, a.querySelector('img') ? a.querySelector('img').src : null]),
          visible_illus: [...s.querySelectorAll('.gmini-grid:not(.live-grid) .gi-card')].filter(e => e.offsetParent !== null).length,
          send: send.getAttribute('href'), h: Math.round(s.getBoundingClientRect().height)};
    }""")
    strip = lambda page: page.evaluate("""() => {
        const s = document.querySelector('.report-card .live-strip'), c = document.querySelector('.report-card').getBoundingClientRect();
        const pb = document.querySelector('.report-card .live-strip-pause');
        return s && {x: s.scrollLeft, drift: s.getAttribute('data-drift'), card: [c.width, c.height], max: s.scrollWidth - s.clientWidth,
          shifts: window.__ls.slice(), pause: pb ? (pb.offsetParent ? 'shown' : 'none') : null, pauseLabel: pb && pb.getAttribute('aria-label')};
    }""")
    msgs_ok = lambda m, *need: len(m) == 3 and m[0].startswith("https://t.me/jakabasej?text=") and m[1].startswith(
        "https://wa.me/38640703992?text=") and m[2].startswith("mailto:me@jackbase.dev?") and all(all(x in u for x in need) for u in m)

    # 1. before + submit → progress, no navigation
    stub_media(FX["slug"])
    ctx = new_ctx()
    page = ctx.new_page()
    page.goto(base, wait_until="load")
    page.wait_for_timeout(300)
    form = page.evaluate("() => { const f = document.getElementById('scan'); return [f.getAttribute('action'), f.getAttribute('method'), [...f.elements].map(e => e.name).filter(Boolean)]; }")
    check(f"{tag} form markup: GET scan/ with h + ig, no platform select", form == ["scan/", "get", ["h", "ig"]], form)
    shot(page, "1-before", ".hero")
    page.locator("#free").scroll_into_view_if_needed()
    page.wait_for_timeout(700)
    shot(page, "1-band-before", "#free")
    band_h0 = ill(page)["h"]
    page.evaluate("scrollTo({top: 0, behavior: 'instant'})")
    page.wait_for_timeout(300)
    net["nav"].clear()
    submit(page, "@demo.creator", "https://www.instagram.com/demo.ig/")
    page.wait_for_function("() => /step/.test((document.querySelector('.report-card .live-status') || {}).textContent || '')", timeout=5000)
    c = card(page)
    check(f"{tag} progress visible in the hero card", c["live"] and c["title"] == "@demo.creator" and "Searching Google, step" in c["status"]
          and page.locator(".report-card .live-status").is_visible() and page.locator("#scan button").is_disabled(), c["status"])
    check(f"{tag} second scan state: no stale rows while scanning", not c["rows"] and not ill(page)["live"])
    shot(page, "2-progress", ".hero")
    check(f"{tag} body: onlyfans + handle + instagram from a pasted URL",
          net["bodies"] == [{"platform": "onlyfans.com", "handle": "demo.creator", "level": "low", "instagram": "demo.ig"}], net["bodies"])

    # 2. settled hero card
    settled(page)
    slug = parse_qs(urlsplit(page.url).query).get("r", [""])[0]
    check(f"{tag} hero: no navigation, URL = index.html?r=<slug>", re.fullmatch(r"[A-Za-z0-9]{12}", slug or "") is not None
          and page.url == base + "?r=" + slug and all(urlsplit(u).path == "/" for u in net["nav"]), [page.url] + net["nav"])
    c = card(page)
    want = [{"tag": "A", "dom": d, "ttl": t, "href": u, "target": "_blank", "badge": b} for d, t, u, b in rows[:5]]
    got = [{k: r[k] for k in ("tag", "dom", "ttl", "href", "target", "badge")} for r in c["rows"]]
    check(f"{tag} hero: rows = the fixture's first 5 links (domain, title, href, badge)", got == want, got)
    check(f"{tag} hero: row links rel noopener + nofollow, card no longer role=img", c["rows"] and all(
        "noopener" in r["rel"] and "nofollow" in r["rel"] for r in c["rows"]) and c["role"] is None, [r["rel"] for r in c["rows"]])
    check(f"{tag} hero: count + more", c["count"] == f"{N} links found" and c["more"] == f"+ {N - 5} more in the full report", (c["count"], c["more"]))
    check(f"{tag} hero: socials in the header", c["socials"] == "Instagram @demo.ig", c["socials"])
    check(f"{tag} hero: aliases: Also found as the discovered handles", c["aliases"] == ALSO, c["aliases"])
    check(f"{tag} hero: Open full report = scan/?r=<slug>", c["open"] == "scan/?r=" + slug, c["open"])
    check(f"{tag} hero: Send me the report = DM links with report URL + handle", msgs_ok(c["msgs"], quote(base + "scan/?r=" + slug, safe=""), "demo.creator"), c["msgs"])
    focus = page.evaluate("document.activeElement.className")
    try:   # bring() scrolls smoothly; give it time to land
        page.wait_for_function("() => { const r = document.querySelector('.report-card').getBoundingClientRect(); return r.top >= 0 && r.top < innerHeight - 100; }", timeout=2500)
    except Exception:
        pass
    box = page.locator(".report-card").bounding_box()
    check(f"{tag} hero: card focused + scrolled into view", "live-title" in focus and box["y"] >= 0 and box["y"] < vp["height"] - 100, f"{focus} y={box['y']:.0f}")
    IM = _images(FX)
    NI = len(IM)
    tile_href = lambda it: it[1] or base + "scan/?r=" + slug
    want_tiles = lambda k: [[tile_href(it), "_blank" if it[1] else "", "noopener noreferrer nofollow" if it[1] else "",
                             API + "/api/thumb?u=" + quote(it[0], safe="")] for it in IM[:k]]
    i = ill(page)
    check(f"{tag} band: #free mini Google Images = her first 10 image results (link → result in a new tab, else the report)",
          i["live"] and i["pill"] == f"{NI} images" and i["visible_illus"] == 0 and i["role"] is None
          and [t[:3] + [t[3]] for t in i["tiles"]] == want_tiles(10), i)
    check(f"{tag} band: same height before/after results (row reserved, no shift)", abs(i["h"] - band_h0) <= 1, [band_h0, i["h"]])
    check(f"{tag} band: 'Send me the report' = Telegram with the report link", (i["send"] or "").startswith("https://t.me/jakabasej?text=")
          and quote(base + "scan/?r=" + slug, safe="") in i["send"], i["send"])
    hero = page.evaluate("""() => {
        const c = document.querySelector('.report-card'), q = s => [...c.querySelectorAll(s)];
        return {tabs: q('.live-tab').map(b => [b.id, b.textContent, b.getAttribute('aria-selected'), b.tabIndex]),
          panels: q('.live-panel').map(p => [p.id, p.classList.contains('on'), getComputedStyle(p).visibility]),
          strip: q('.live-strip a.gi-card').map(a => [a.href, a.target, a.rel, a.querySelector('img').src]),
          stripH: (c.querySelector('.live-strip-h') || {}).textContent,
          blur: getComputedStyle(c.querySelector('.live-strip .gi-img')).filter, ico: q('.live-rows .live-ico').length,
          rowH: Math.min(...q('.live-rows a.live-link').map(a => a.getBoundingClientRect().height)),
          sites: q('.live-sites a.live-link').map(a => [a.href, a.target, a.rel])};
    }""")
    sites = _sites(rows)
    check(f"{tag} hero: tabs Links / Images / Sites with the fixture's counts, Links selected",
          hero["tabs"] == [["lt-links", f"Links{N}", "true", 0], ["lt-images", f"Images{NI}", "false", -1], ["lt-sites", f"Sites{FX['domain_count']}", "false", -1]]
          and [p[1:] for p in hero["panels"]] == [[True, "visible"], [False, "hidden"], [False, "hidden"]], hero["tabs"])
    check(f"{tag} hero: rows >= 44px with a letter avatar / blurred site thumb each", hero["rowH"] >= 44 and hero["ico"] == 5, hero["rowH"])
    check(f"{tag} hero: strip 'What Google Images shows for @demo.creator' = first 24 images, blurred, link → result / report",
          hero["stripH"] == "What Google Images shows for @demo.creator" and hero["strip"] == want_tiles(24) and "blur" in hero["blur"], hero["strip"][:3])
    by_dom = {}
    for d, _t, u, _b in rows:
        by_dom.setdefault(d, u)
    check(f"{tag} hero: Sites tab = top 6 sites, each opens its first link in a new tab",
          hero["sites"] == [[by_dom[d], "_blank", "noopener noreferrer nofollow"] for d in [x[0] for x in sorted(_site_counts(rows), key=lambda x: -x[1])][:6]], hero["sites"])
    # tabs switch the body without moving anything; Reveal unblurs
    cbox = lambda: page.evaluate("() => { const r = document.querySelector('.report-card').getBoundingClientRect(), d = document.documentElement.getBoundingClientRect(); return [Math.round(r.x - d.x), Math.round(r.y - d.y), r.width, r.height]; }")
    card0 = cbox()
    page.locator("#lt-images").click()
    page.wait_for_timeout(350)
    gi = page.evaluate("() => [document.querySelector('#lp-images').classList.contains('on'), getComputedStyle(document.querySelector('#lp-links')).visibility, document.querySelectorAll('#lp-images .live-grid a.gi-card').length, (document.querySelector('#lp-images .live-more') || {}).textContent]")
    card1 = cbox()
    G = 12 if vp_name == "phone" else 16
    check(f"{tag} hero: Images tab shows the image grid (phone 12, else 16) in place (card box unchanged)", gi == [True, "hidden", G, f"+ {NI - G} more in the full report"]
          and card0 == card1, (gi, card0, card1))
    shot(page, "3b-card-images", ".report-card")
    page.locator("#lp-images .live-reveal").click()
    page.wait_for_timeout(400)
    rv = page.evaluate("() => [getComputedStyle(document.querySelector('#lp-images .gi-img')).filter, [...document.querySelectorAll('.report-card .live-reveal')].map(b => b.getAttribute('aria-pressed'))]")
    check(f"{tag} hero: Reveal unblurs (both toggles in sync)", rv[0] == "none" and set(rv[1]) == {"true"}, rv)
    page.locator("#lp-images .live-reveal").click()
    page.locator("#lt-sites").click()
    page.wait_for_timeout(350)
    check(f"{tag} hero: Sites tab in place (card box unchanged, page coords)", cbox() == card0, (cbox(), card0))
    shot(page, "3c-card-sites", ".report-card")
    page.locator("#lt-links").focus()
    page.keyboard.press("ArrowRight")
    check(f"{tag} hero: arrow keys move between tabs", page.evaluate("document.activeElement.id") == "lt-images"
          and page.locator("#lp-images").get_attribute("class") == "live-panel on")
    page.locator("#lt-links").click()
    page.mouse.move(0, 0)
    # drift: idle ~4 s → the strip scrolls itself; 2 frames 2 s apart; a pointerdown on it stops it for good
    try:
        page.wait_for_function("() => { const s = document.querySelector('.report-card .live-strip'); return s && s.scrollLeft > 4; }", timeout=9000)
    except Exception:
        pass
    a0 = strip(page)
    page.locator(".report-card .live-strip-box").screenshot(path=str(out / f"{vp_name}-i3d-strip-t0.png"))
    page.wait_for_timeout(2000)
    a1 = strip(page)
    page.locator(".report-card .live-strip-box").screenshot(path=str(out / f"{vp_name}-i3d-strip-t2.png"))
    check(f"{tag} drift: idle → the strip scrolls by itself (rAF), ~24 px/s", a0["drift"] == "on" and 20 <= a1["x"] - a0["x"] <= 90, (a0["x"], a1["x"]))
    check(f"{tag} hero: a visible 'Pause slideshow' button while it may move", a1["pause"] == "shown" and a1["pauseLabel"] == "Pause slideshow", a1["pause"])
    late = [x for x in a1["shifts"] if x[1] > 0 and not x[2] and x[0] > page.evaluate("performance.now()") - 4000]
    check(f"{tag} hero: zero layout shift while the strip drifts / loads (card box + PerformanceObserver)",
          a0["card"] == a1["card"] and [round(v) for v in a1["card"]] == [round(card0[2]), round(card0[3])] and not late, (a0["card"], a1["card"], late))
    page.locator(".report-card .live-strip").dispatch_event("pointerdown")
    b0 = strip(page)["x"]
    page.wait_for_timeout(2000)
    b1 = strip(page)
    check(f"{tag} hero: pointerdown on the strip stops the drift for good (button → Play)", b1["x"] == b0 and b1["drift"] is None and b1["pause"] == "shown"
          and b1["pauseLabel"] == "Play slideshow", (b0, b1["x"], b1["drift"], b1["pause"], b1["pauseLabel"]))
    page.locator(".report-card .live-strip-box").screenshot(path=str(out / f"{vp_name}-i3d-strip-after-pointerdown.png"))
    page.locator(".report-card .live-strip-pause").click()   # Play: a deliberate restart, no 4 s wait
    c0 = strip(page)["x"]
    page.wait_for_timeout(1500)
    c1 = strip(page)
    page.locator(".report-card .live-strip-pause").click()   # Stop
    page.wait_for_timeout(300)
    c2 = strip(page)
    page.wait_for_timeout(1000)
    check(f"{tag} drift: Play restarts it at once, Stop ends it", c1["drift"] == "on" and c1["x"] - c0 >= 15 and c1["pauseLabel"] == "Pause slideshow"
          and c2["drift"] is None and strip(page)["x"] == c2["x"] and c2["pauseLabel"] == "Play slideshow", (c0, c1["x"], c2["x"], c1["drift"], c2["drift"]))
    last = json.loads(page.evaluate("localStorage.getItem('leakscan.last')") or "{}")
    check(f"{tag} hero: localStorage leakscan.last", last.get("slug") == slug and last.get("handle") == "demo.creator", last)
    # personalize (same checks as #18's ?r= path, via apply())
    try:
        page.wait_for_selector("[data-p=scanned]:not([hidden])", timeout=5000)
    except Exception:
        pass
    texts = lambda sel: page.eval_on_selector_all(sel, "els => els.filter(e => e.offsetParent !== null).map(e => e.textContent.trim())")
    name = PROFILE["display_name"]
    check(f"{tag} hero: personalize line + phones' leak domains", "Scanned @demo.creator" in page.locator("[data-p=scanned]").inner_text()
          and [page.locator(f'[data-p="leak-{k}"] .m-site').inner_text() for k in range(1, 5)] == TOP)
    check(f"{tag} profile: phones search for the name, IG row = the typed Instagram", texts("[data-p=search]") == [name, name]
          and texts('[data-p="ig"] .m-title') == [f"{name} (@demo.ig)"] * 2, texts('[data-p="ig"] .m-title'))
    check(f"{tag} hero: showcase iframe + button carry the slug", page.locator("iframe[data-p=demo]").get_attribute("src") == "showcase/?r=" + slug
          and page.locator("a[data-p=demo]").get_attribute("href") == "showcase/?r=" + slug)
    try:
        page.wait_for_function("() => (document.querySelector('.live-media') || {}).textContent === 'Photos ready: see your demo site'", timeout=12000)
    except Exception:
        pass
    check(f"{tag} profile: hero media line ends at 'Photos ready'", page.locator(".live-media").is_visible()
          and page.locator(".live-media a").get_attribute("href") == "#showcase", page.evaluate("(document.querySelector('.live-media') || {}).textContent"))
    page.evaluate("window.scrollTo(0, 0)")
    shot(page, "3-settled", ".hero")
    shot(page, "3-settled-card", ".report-card")
    page.locator("#free").scroll_into_view_if_needed()
    page.wait_for_timeout(700)
    shot(page, "4-band", "#free")
    page.locator("#website").scroll_into_view_if_needed()
    page.wait_for_timeout(700)
    shot(page, "5-phones", "#website")

    # 3. reload with ?r= restores the hero card, no new scan
    n_posts = len(net["bodies"])
    page.reload(wait_until="load")
    try:
        page.wait_for_selector(".report-card .live-rows li", timeout=6000)
    except Exception:
        pass
    c2 = card(page)
    check(f"{tag} reload ?r= restores hero card (rows, count, socials), no new scan", c2["rows"] == c["rows"] and c2["count"] == c["count"]
          and c2["socials"] == "Instagram @demo.ig" and ill(page)["pill"] == f"{NI} images" and len(net["bodies"]) == n_posts, c2["count"])

    # 4. second scan resets, badges only from data (stub-mixed: live true / false / missing, then Google results)
    submit(page, "stub-mixed")
    page.wait_for_function("() => /step/.test((document.querySelector('.report-card .live-status') || {}).textContent || '')", timeout=5000)
    mid = card(page)
    check(f"{tag} second scan resets hero card + illustration", not mid["rows"] and mid["title"] == "@stub-mixed" and mid["count"] is None
          and not ill(page)["live"] and mid["socials"] is None, mid)
    settled(page)
    mixed = _rows({"hits": [dict(h) for h in FX["hits"][:3]], "results": FX["results"]})
    c = card(page)
    check(f"{tag} hero: badges only what the data says (Live / Found / Indexed)", [r["badge"] for r in c["rows"]] == ["Live", "Found", "Found", "Indexed", "Indexed"]
          and not any(b in json.dumps(c) for b in ("Dead", "Cached", "Removed")), [r["badge"] for r in c["rows"]])
    check(f"{tag} hero: second result replaces the first", c["title"] == "@stub-mixed" and c["count"] == f"{len(mixed)} links found"
          and c["socials"] is None and net["bodies"] == [{"platform": "onlyfans.com", "handle": "stub-mixed", "level": "low"}], (c["count"], net["bodies"]))
    check(f"{tag} hero: aliases: no discovered handles -> line hidden", c["aliases"] is None, c["aliases"])
    check(f"{tag} hero: URL follows the new slug", parse_qs(urlsplit(page.url).query).get("r", [""])[0] not in ("", slug), page.url)

    # 5. zero hits + X from a pasted URL
    submit(page, "stub-empty", "x.com/demo_x")
    settled(page)
    c = card(page)
    i = ill(page)
    check(f"{tag} zero hits: honest empty state, send still there", c["empty"] and c["empty"].startswith("No leaks found for @stub-empty right now")
          and c["count"] == "0 links found" and not c["rows"] and c["open"] and msgs_ok(c["msgs"], "stub-empty") and not i["live"]
          and i["visible_illus"] > 0 and page.locator(".report-card .live-tabs").count() == 0, c)
    check(f"{tag} body: x.com URL → x, no instagram", net["bodies"] == [{"platform": "onlyfans.com", "handle": "stub-empty", "level": "low", "x": "demo_x"}], net["bodies"])
    check(f"{tag} hero: X social in the header", c["socials"] == "X @demo_x", c["socials"])
    page.locator(".report-card").screenshot(path=str(out / f"{vp_name}-i6-empty.png"))

    # 6. errors: 429 rate_limited / busy, failed, network, server 400, client-side validation
    for h, kind, want in (("stub-429", "rate_limited", "busy"), ("stub-busy", "busy", "busy"), ("stub-fail", "failed", "didn’t finish")):
        submit(page, h)
        settled(page)
        c = card(page)
        txt = page.locator(".report-card .live-error").inner_text() if page.locator(".report-card .live-error").count() else ""
        check(f"{tag} {kind} error inline, form re-enabled", c["error"] == kind and want in txt and ("minute" in txt) and msgs_ok(c["msgs"], h)
              and page.locator("#scan button").is_enabled(), txt)
        check(f"{tag} hero: {kind} keeps the last report's ?r= in the URL", page.url.startswith(base + "?r="), page.url)
        page.locator(".report-card").screenshot(path=str(out / f"{vp_name}-i7-error-{kind}.png"))
    page.route("**/api/public-scan", lambda r, _q: r.abort())   # fake: network down (wire boundary)
    submit(page, "demo.creator")
    settled(page)
    c = card(page)
    check(f"{tag} network error inline, form re-enabled", c["error"] == "network" and "Couldn’t reach" in page.locator(".live-error").inner_text()
          and msgs_ok(c["msgs"], "demo.creator") and page.locator("#scan button").is_enabled())
    page.unroute("**/api/public-scan")
    page.route("**/api/public-scan", lambda r, _q: r.fulfill(status=400, content_type="application/json", body='{"error":"bad_handle"}'))  # fake: server 400
    submit(page, "demo.creator")
    settled(page)
    check(f"{tag} server 400 → 'doesn’t look right' at the form, card back to illustration", "doesn’t look right" in page.locator(".inline-msg").inner_text()
          and not card(page)["live"] and page.locator("#scan button").is_enabled())
    page.unroute("**/api/public-scan")
    for h, s, field in (("bad handle!", "", "h"), ("demo.creator", "tiktok.com/someone", "ig")):
        submit(page, h, s)
        page.wait_for_timeout(200)
        check(f"{tag} client validation ({field}) → message, no POST", "doesn’t look right" in page.locator(".inline-msg").inner_text()
              and not net["bodies"] and page.evaluate("document.activeElement.name") == field, net["bodies"])
    page.locator(".hero").screenshot(path=str(out / f"{vp_name}-i8-validation.png"))

    # 7. a good scan again, then Reset page resets everything
    submit(page, "demo.creator", "demo.ig")
    settled(page)
    check(f"{tag} hero: scan works again after errors", len(card(page)["rows"]) == 5 and not page.locator(".inline-msg").is_visible())
    if page.locator("[data-p=scanned] button").is_visible():
        page.locator("[data-p=scanned] button").click()
    page.wait_for_load_state("load")
    page.wait_for_timeout(1200)
    check(f"{tag} Reset page resets hero card + illustration", not card(page)["live"] and not ill(page)["live"] and page.url == base
          and page.evaluate("localStorage.getItem('leakscan.last')") is None and card(page)["role"] == "img")
    ctx.close()

    # 7b. reduced motion: the report restores from ?r=, the strip never moves by itself
    ctx = new_ctx(motion="reduce")
    page = ctx.new_page()
    page.goto(base + "?r=" + slug, wait_until="load")
    try:
        page.wait_for_selector(".report-card .live-strip a.gi-card", timeout=8000)
    except Exception:
        pass
    page.mouse.move(0, 0)
    page.wait_for_timeout(6500)
    r = strip(page)
    check(f"{tag} hero: reduced motion → strip still, no drift after 6.5 s idle", r and r["x"] == 0 and r["drift"] is None and r["max"] > 0 and r["pause"] == "none", r and (r["x"], r["drift"], r["max"], r["pause"]))
    page.locator(".report-card .live-strip-box").screenshot(path=str(out / f"{vp_name}-i3d-strip-reduced-motion.png"))
    ctx.close()

    # 8. no JS: plain GET to scan/ with h + ig; scan/ reads h / ig / x and posts the socials
    ctx = new_ctx(js=False)
    page = ctx.new_page()
    page.goto(base, wait_until="load")
    page.locator("#scan input[name=h]").fill("@Some.Name")
    page.locator("#scan input[name=ig]").fill("x.com/some_x")
    with page.expect_navigation(url=re.compile(r"/scan/\?")):
        page.locator("#scan button[type=submit]").click()
    q = parse_qs(urlsplit(page.url).query)
    check(f"{tag} no JS: form GETs scan/?h=&ig=", urlsplit(page.url).path == "/scan/" and q == {"h": ["@Some.Name"], "ig": ["x.com/some_x"]}, page.url)
    ctx.close()
    ctx = new_ctx()
    page = ctx.new_page()
    for qs, want in (("h=%40Some.Name&ig=x.com%2Fsome_x", {"handle": "Some.Name", "x": "some_x"}),
                     ("h=demo.creator&ig=%40demo.ig", {"handle": "demo.creator", "instagram": "demo.ig"}),
                     ("h=demo.creator&x=demo_x", {"handle": "demo.creator", "x": "demo_x"})):
        net["bodies"].clear()
        page.goto(base + "scan/?" + qs, wait_until="load")
        try:
            page.wait_for_selector("#report:not([hidden])", timeout=15000)
        except Exception:
            pass
        check(f"{tag} scan/?{qs} posts the socials", net["bodies"] == [{"platform": "onlyfans.com", "level": "low", **want}], net["bodies"])
    net["bodies"].clear()
    page.goto(base + "scan/", wait_until="load")
    f = page.locator("#scan-form")
    f.locator("input[name=h]").fill("demo.creator")
    f.locator("input[name=ig]").fill("https://twitter.com/demo_x")
    with page.expect_navigation(url=re.compile(r"/scan/\?h=")):
        f.locator("button[type=submit]").click()
    try:
        page.wait_for_selector("#report:not([hidden])", timeout=15000)
    except Exception:
        pass
    check(f"{tag} scan/ page form: same two fields, twitter URL → x", net["bodies"] == [{"platform": "onlyfans.com", "handle": "demo.creator", "level": "low", "x": "demo_x"}], net["bodies"])
    page.goto(base + "scan/?h=demo.creator&ig=tiktok.com%2Fx", wait_until="load")
    check(f"{tag} scan/ bad social → form message", page.locator("#form-error").is_visible() and "Instagram or X" in page.locator("#form-error").inner_text())
    ctx.close()

    hosts = {urlsplit(u).hostname for u in net["outside"]}
    check(f"{tag} no request left loopback but the demo's aborted Google Fonts", hosts <= FONT_HOSTS, sorted(hosts))
    check(f"{tag} no JS errors, no console errors", not net["errors"] and not net["console"], net["errors"] + net["console"])


with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
stub = subprocess.Popen([sys.executable, str(ROOT / "tools" / "scan_stub.py"), "--port", str(port), "--delay", "0.25"]
                        + (["--omit-results"] if omit else []) + (["--omit-profile"] if omit_profile else []),
                        stderr=subprocess.DEVNULL, stdout=subprocess.PIPE)
stub.stdout.readline()
base = f"http://127.0.0.1:{port}/"
API = f"http://localhost:{port}"   # the stub injects the other loopback name as data-api

try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for vp_name, vp in VIEWPORTS:
            if "scan" in SCENARIOS:
                scan_flow(browser, vp_name, vp)
            if "personalize" in SCENARIOS:
                personalize_flow(browser, vp_name, vp)
            if "askai" in SCENARIOS:
                askai(browser, vp_name, vp)
            if "inline" in SCENARIOS:
                inline_flow(browser, vp_name, vp)
        browser.close()
finally:
    stub.terminate()

(out / "e2e-summary.json").write_text(json.dumps({"fails": fails, "omit_results": omit, "omit_profile": omit_profile,
                                                  "scenarios": SCENARIOS, "break_allowlist": BREAK_ALLOWLIST}, indent=1))
sys.exit(1 if fails else 0)

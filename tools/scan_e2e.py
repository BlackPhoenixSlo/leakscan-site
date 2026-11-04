#!/usr/bin/env python3
"""End-to-end proof of the on-site free scan against the local stub (never the production API or jackbase.me).

    cd ~/leakhunt && uv run python ~/leakscan-site/tools/scan_e2e.py OUT_DIR [--only scan|personalize|askai]
        [--omit-results] [--omit-profile] [--break-allowlist]

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

askai (js/chat.js, the "Ask AI before you DM me" popup): launcher visible and clear of the hero CTA / sticky bar,
open/close/Esc/backdrop/focus return/focus trap, FAQ chips and fuzzy-typed questions answered with zero network
requests, other questions streamed from the stub's /api/chat (request body: kb, slug, history cap), link rules (anchor
scrolls, allowlisted hosts only), failed / 429 / no-API (file://) fallbacks, retry, sessionStorage restore, reduced
motion, JS off. Requests made by the lazy showcase iframe (disclosed Google Fonts, aborted) are not counted against
the popup. --break-allowlist serves chat.js with its host allowlist disabled: only `links:` checks may go red.
"""
import json, pathlib, re, socket, subprocess, sys, time, urllib.request
from urllib.parse import parse_qs, quote, urlsplit
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
FX = json.loads((ROOT / "tools" / "fixtures" / "scan-sample.json").read_text())
REPORT_BASE = "https://blackphoenixslo.github.io/leakscan-site/scan/?r="
out = pathlib.Path(sys.argv[1]).expanduser()
out.mkdir(parents=True, exist_ok=True)
omit = "--omit-results" in sys.argv
omit_profile = "--omit-profile" in sys.argv
SCENARIOS = [sys.argv[sys.argv.index("--only") + 1]] if "--only" in sys.argv else ["scan", "personalize", "askai"]
BREAK_ALLOWLIST = "--break-allowlist" in sys.argv
VIEWPORTS = (("phone", {"width": 390, "height": 844}), ("desktop", {"width": 1440, "height": 900}))
fails = []

PAGES = [r for r in FX["results"] if r["kind"] != "video"]
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

    # 1. home → form → scan page
    page.goto(base, wait_until="load")
    page.locator("#scan .scan-handle").fill("@demo.creator")
    page.locator("#scan select[name=p]").select_option("fansly.com")
    with page.expect_navigation(url=re.compile(r"/scan/\?")):
        page.locator("#scan button").click()
    q = parse_qs(urlsplit(page.url).query)
    check(f"{vp_name} lands on scan/?p=&h=", q.get("p") == ["fansly.com"] and q.get("h") == ["@demo.creator"], page.url)

    # 2. progress
    page.wait_for_selector("#progress-log li", timeout=5000)
    check(f"{vp_name} progress visible", page.locator("#progress").is_visible()
          and "demo.creator" in page.locator("#scan-title").inner_text())
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
    shot("2-report-full", full=True)

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
        check(f"{vp_name}/{device} tab aria-selected", page.locator("#g-tab-all").get_attribute("aria-selected") == "true"
              and page.locator("#g-tab-images").get_attribute("aria-selected") == "false")
        # Images
        page.locator("#g-tab-images").click()
        while page.locator("[data-more=images]").count():
            page.locator("[data-more=images]").click()
        ni = page.locator("#g-panel .g-tile").count()
        check(f"{vp_name}/{device} Images tab count", ni == IMAGES, f"{ni} want {IMAGES}")
        page.wait_for_timeout(500)
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
    link = REPORT_BASE + slug
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
GSTATIC = [u for u in FX["images"] if u.startswith("https://") and ".gstatic.com/" in u][:3]
DEMO_PAGES = ["", "about.html", "links.html", "timeline.html", "verify.html", "blog.html", "statement.html",
              "blog/post-1.html", "blog/post-2.html", "blog/post-3.html", "404.html"]
FONT_HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com"}   # the demo's disclosed Google Fonts; aborted here
PROD_HOSTS = ("scan.srv1395798.hstgr.cloud", "72.62.92.114", "jackbase.me")


def stub_media(slug, mode="normal"):
    import urllib.request
    urllib.request.urlopen(urllib.request.Request(f"{base}__stub/media?slug={slug}&mode={mode}", method="POST")).read()


def baseline_index():
    """This tree's index.html without js/personalize.js (so other features' text doesn't count), data-api injected
    like the stub does."""
    html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    tag = '<script src="js/personalize.js" defer></script>\n'
    assert tag in html, "baseline: personalize.js script tag not found in index.html"
    return "no personalize.js", re.sub(r"<body\b", f'<body data-api="{API}"', html.replace(tag, ""), count=1)


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
    check(f"{tag} no slug: visible text identical to the page with {sha}", now == then, f"{len(now)} vs {len(then)} chars")
    check(f"{tag} no slug: no API call", not no_api, no_api)
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
        check(f"{tag} profile: links page = the profile accounts, avatar from the API",
              [b[0] for b in btns] == [a["url"] for a in PROFILE["accounts"]] and all(b[1] == "_blank" for b in btns)
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
        page.wait_for_function("() => document.querySelector('img.hero__bg').naturalWidth === 120", timeout=6000)
    except Exception:
        pass
    rel = page.eval_on_selector("img.hero__bg", "e => [e.getAttribute('src'), e.naturalWidth]")
    check(f"{tag} profile: same-origin relative media srcs accepted", rel == [f"/api/media/{FX['slug']}/0.jpg", 120], rel)
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
            line: vis('[data-p=scanned]'), leak1: q('[data-p=leak-1] .m-site')[0].textContent});
        const out = {bad: [P.apply(null), P.apply({slug: '<x>'}), P.applySlug('../x')], keys: Object.keys(P).sort()};
        const full = await get('demoR3port01'), bare = await get('demoNoProf01');
        out.ok1 = P.apply(full); P.apply(full); out.a = snap();
        out.ok2 = P.apply(bare); out.b = snap();
        return out;
    }""", API)
    check(f"{tag} public API: window.LeakScanPersonalize {{apply, applySlug, pollMedia}}, junk rejected",
          api_res["keys"] == ["apply", "applySlug", "pollMedia"] and api_res["bad"] == [False, False, False] and api_res["ok1"] and api_res["ok2"], api_res)
    a, b2 = api_res["a"], api_res["b"]
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

    # 1. launcher
    page.goto(base, wait_until="load")
    page.wait_for_selector(".askai-launcher:not([hidden])", timeout=5000)
    check(f"{v} launcher visible + labelled", L.is_visible() and L.get_attribute("aria-label") == "Ask AI before you DM me"
          and "Ask AI before you DM me" in L.inner_text(), L.inner_text())
    cta = page.locator("#scan button[type=submit]").bounding_box()
    lb = L.bounding_box()
    check(f"{v} launcher clear of hero CTA", not overlap(lb, cta), f"launcher={lb} cta={cta}")
    check(f"{v} launcher inside viewport bottom-right", lb["x"] + lb["width"] <= vp["width"] and lb["y"] + lb["height"] <= vp["height"]
          and vp["width"] - (lb["x"] + lb["width"]) <= 32 and vp["height"] - (lb["y"] + lb["height"]) <= 32, lb)
    shot("1-launcher")
    if vp_name == "phone":
        page.evaluate("document.getElementById('how').scrollIntoView()")
        page.wait_for_selector(".mobile-cta.show", timeout=3000)
        page.wait_for_timeout(500)
        mb, lb2 = page.locator(".mobile-cta").bounding_box(), L.bounding_box()
        check(f"{v} launcher clear of sticky scan bar", not overlap(lb2, mb), f"launcher={lb2} bar={mb}")
        page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")

    # 2. open / close / focus
    L.click()
    page.wait_for_timeout(300)
    d = page.get_by_role("dialog", name="Ask about LeakScan")
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
    L.click()
    page.locator(".askai-close").click()
    check(f"{v} close button closes, focus back", not is_open()
          and page.evaluate("document.activeElement.classList.contains('askai-launcher')"))
    L.click()
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
    L.click()
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
        L.click()
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
    L.click()
    users = page.eval_on_selector_all(".askai-user", "els => els.map(e => e.textContent)")
    check(f"{v} reload restores chat from sessionStorage", q in users and "how much" in users, len(users))
    check(f"{v} no localStorage writes, no cookies", page.evaluate("Object.keys(localStorage)") == ["leakscan.last"]
          and ctx.cookies() == [], page.evaluate("Object.keys(localStorage)"))
    page.keyboard.press("Escape")

    # 8. no API origin: page opened from disk (no data-api, not http) → nothing to call
    k, kl, ne = len(reqs), len(chat_log()), len(errors)
    page.goto((ROOT / "site" / "index.html").as_uri(), wait_until="load")
    L.click()
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
    L.click()
    a1 = anim()
    page.keyboard.press("Escape")
    page.emulate_media(reduced_motion="reduce")
    L.click()
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
        browser.close()
finally:
    stub.terminate()

(out / "e2e-summary.json").write_text(json.dumps({"fails": fails, "omit_results": omit, "omit_profile": omit_profile,
                                                  "scenarios": SCENARIOS, "break_allowlist": BREAK_ALLOWLIST}, indent=1))
sys.exit(1 if fails else 0)

#!/usr/bin/env python3
"""End-to-end proof of the on-site free scan against the local stub (never the production API or jackbase.me).

    cd ~/leakhunt && uv run python ~/leakscan-site/tools/scan_e2e.py OUT_DIR [--only scan|personalize|askai|inline|tabs|removals|pip]
        [--omit-results] [--omit-profile] [--break-allowlist] [--break-drift] [--break-phones] [--break-thumbs] [--break-people] [--break-remove]
        [--break-incremental] [--break-tuck]

Starts tools/scan_stub.py on a free port (--omit-results / --omit-profile are passed through: break-it runs), then
for phone (390x844) and desktop (1440x900) runs three scenarios.

scan: home → fill the hero form → submit → scan/?p=&h= → progress → report. Asserts summary numbers
equal the fixture, tab item counts (All 10 → all pages after "More results", Images ≤ 30, Videos), device toggle swaps
frames, Reveal unblurs, CTA hrefs carry the report link + handle, every hit URL is listed, `?r=<slug>` reopens without
a new scan, and the stub `failed` / 429 / busy / empty / not-found paths show their UI. Then `stub-huge` (1000 links on
100 sites, CPU x4): render time, DOM budget, sites / links shown in steps, filter, export, the pinned phone scrolling
into the sites, CLS 0 (whole flow), no 5xx / console errors; --break-incremental (scan.js with every step 1e9) turns only the
`incremental:` checks red. Every non-loopback request is
aborted and must not happen at all. Screenshots of each state go to OUT_DIR. One PASS/FAIL line per check; exit 1 on
any FAIL.

personalize (js/personalize.js): landing without a slug has byte-identical visible text to the same page without personalize.js and calls no
API; `?r=<slug>` fills both "Your website" phones (name, top leak domains by occurrences, blurred stub thumbs, IG /
TikTok / site rows), the showcase url bar and iframe src; the demo iframe and every showcase page show the profile
and no pottery / Orla / she-her text; demo photos poll /api/media (pending → ready swap, no layout jump; none / 404
keep the placeholders; same-origin relative srcs are accepted and stop polling); scan-only results personalize the phones but leave the demo as Orla
(blog.html too: Orla's 3 posts; with a profile the 3 starter posts blog/own-*.html, cards + pages);
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
band's mini Google Images frame with her tiles; errors, reload, reset; a shared ?r= link makes one /api/scan-result
request and (phone) scrolls the card under the nav, not with #website. --break-drift serves inline-scan.js with the
drift speed 0: only `drift:` checks may go red. --break-phones serves personalize.js without the phone links: only
`phones:` checks may go red.

tabs (the owner's three asks): (1) report card ?r=demoBrokenT1 (stub: three page-result thumbs answer 404 / a 1×1
blank, two are a flat site logo, a video still leads images[]): failed / blank / logo tiles leave the strip, the Images grid and the #free phone, the
next image takes the slot, the label / tab / "+N more" / phone counts say what shows, every tile is painted, video
stills only after the real images; (2) #website copy → demo iframe → Before / After phones (in #showcase), their All / Images / Videos tabs switch
on click and keys without moving anything, the demo pops out to a full-screen layer (Esc / button / backdrop close,
focus back, page scroll locked, nothing behind it moves, "Open the demo site" link kept); (3) the #free phone: same
tabs, the illustration without a scan, her handle / rows / tiles / videos + Reveal with ?r=; no horizontal overflow.
Screenshots: <vp>-t*.png. --break-thumbs serves inline-scan.js with the drop disabled: only `thumbs:` checks may go red. --break-people serves
scan-engine.js with E.isPhoto always true (logos kept): only `thumbs:` checks may go red.

removals (js/removals.js, the #removals "Where I remove from" panels): section placed after #faq and directly before
#contact; demo defaults (Orla Brennick); leak-side images blurred by default (+ Reveal); Remove flips all 4 panels
(Mega / X / Reddit / leak site) to their removed state and Show again back, with zero layout shift; a drag on the stage
moves the compare edge + clip; arrow keys on the handle; reduced motion = no transition; no horizontal overflow (390);
?r=demoRemove1 personalizes from the backend's top-level `mega` list + x.com / reddit.com / top other host hits, thumbs via
/api/thumb, still blurred, no URL rendered; no mega[] → demo fallback; evil values dropped. Screenshots of every panel
live + removed, light + dark. --break-remove serves removals.js without the Remove click handler: only `toggle:` checks
may go red.

pip (js/pip.js, the floating mini player of site/video/): landing without ?pip=1 and scan/ without ?r= show none and load
no /video/; scan/?r=<slug> mounts it by itself after the page's load (lazy): 16:9, 45% of the phone width / 320 px,
same-origin iframe of /video/?r=<slug> in embed form (no name bar / player UI, stage = frame), starts muted + playing, a
tap unmutes; drags snap to the nearest corner (under the sticky header / report nav); a fling past the left / right
edge tucks it off-screen with a '>' / '<' tab at that edge (paused), a tap or an inward drag on the tab brings it back;
Esc tucks, Enter on the tab returns; corner / tucked / closed kept in sessionStorage; expand = /video/?r=&t=; x closes
for the session; header, report nav, Scan now, phone CTA bar and Ask-AI launcher stay clickable (elementFromPoint);
CLS 0 after it mounts; reduced motion = no transitions; no request off loopback, no console errors. Phone (Chromium,
real touch via CDP), desktop, and WebKit iPhone 13 (taps are touch, drags use the mouse: pointerType mouse). Screenshots:
<vp>-pip-*.png. --break-tuck serves pip.js with tuck() emptied: only `tuck:` checks may go red.
"""
import base64
import json, pathlib, re, socket, subprocess, sys, time, urllib.request
from urllib.parse import parse_qs, quote, unquote, urlsplit
from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
FX = json.loads((ROOT / "tools" / "fixtures" / "scan-sample.json").read_text())
out = pathlib.Path(sys.argv[1]).expanduser()
out.mkdir(parents=True, exist_ok=True)
omit = "--omit-results" in sys.argv
omit_profile = "--omit-profile" in sys.argv
SCENARIOS = [sys.argv[sys.argv.index("--only") + 1]] if "--only" in sys.argv else ["scan", "personalize", "askai", "inline", "tabs", "removals", "pip"]
BREAK_ALLOWLIST = "--break-allowlist" in sys.argv
BREAK_DRIFT = "--break-drift" in sys.argv
BREAK_PHONES = "--break-phones" in sys.argv
BREAK_THUMBS = "--break-thumbs" in sys.argv
BREAK_PEOPLE = "--break-people" in sys.argv
BREAK_REMOVE = "--break-remove" in sys.argv
BREAK_INCREMENTAL = "--break-incremental" in sys.argv
BREAK_TUCK = "--break-tuck" in sys.argv
GS_RE = re.compile(r"^https://[a-z0-9-]+\.gstatic\.com/[^\s\"'<>\\]*$")
PEOPLE = {"imgs/portrait.webp", "imgs/hero-wide.webp", "imgs/studio-portrait.webp"}   # showcase hero defaults: Pexels people photos (tools/showcase/CREDITS.md)


VIDEO_RE = re.compile(r"\.(?:mp4|m3u8|webm|mov|mkv)(?:[?#]|$)|/(?:videos?|watch|embed|clips?|vod)(?:[/?#.-]|$)", re.I)
is_video = lambda r: bool(r) and (r.get("kind") == "video" or bool(VIDEO_RE.search(r.get("link") or "")))
dead_thumb = lambda u, extra=(): "DEAD" in u or "BLANK" in u or "LOGO" in u or any(x in u for x in extra)   # LOGO: no person photo (E.isPhoto)


def _images(fx, alive=False, extra=()):
    """Mirror of inline-scan.js model().images: images[] (with the result that has that thumb) then results' thumbs,
    gstatic only, deduped, video results' stills skipped, max 60; the ones with a link first; then the video results'
    stills (top-up), max 60 in all. alive: minus the thumbs the stub answers 404 or blank, plus `extra` (route-level 404s;
    gallery() drops them all). → [(src, link, domain)]"""
    ok = lambda u: isinstance(u, str) and len(u) <= 600 and GS_RE.match(u)
    res = [r for r in fx.get("results", []) if r.get("link")]
    by, seen, out = {}, set(), []
    for r in res:
        if ok(r.get("thumb")) and r["thumb"] not in by:
            by[r["thumb"]] = r

    def add(u, r):
        if ok(u) and u not in seen and not is_video(r):
            seen.add(u)
            out.append((u, r["link"] if r else "", r["domain"] if r else ""))
    for u in fx.get("images", [])[:200]:
        add(u, by.get(u))
    for r in res:
        add(r.get("thumb"), r)
    out = out[:60]
    out = [o for o in out if o[1]] + [o for o in out if not o[1]]
    had = {o[0] for o in out}
    out = (out + [(u, by[u]["link"], by[u]["domain"]) for u, v in _scan_images(fx) if v and u not in had])[:60]
    return [o for o in out if not dead_thumb(o[0], extra)] if alive else out


def _band(fx, ims):
    """The #free band's Images grid: first 9 of `ims` minus the stills its Videos tab shows (first 3 video results)."""
    v3 = {r.get("thumb") for r in [r for r in fx.get("results", []) if r.get("link") and is_video(r)][:3]}
    return [x for x in ims if x[0] not in v3][:9]


def _scan_images(fx, alive=False):
    """Mirror of scan.js imageItems() (videos: true): images[] (each an image result, whatever result shares its thumb) then
    every result's thumb, video results' stills included, gstatic only, deduped, no cap. → [(src, video)]; alive: minus the
    thumbs the stub answers 404 or blank."""
    ok = lambda u: isinstance(u, str) and len(u) <= 600 and GS_RE.match(u)
    res = [r for r in fx.get("results", []) if r.get("link")]
    by, seen, out = {}, set(), []
    for r in res:
        if r.get("thumb") and r["thumb"] not in by:
            by[r["thumb"]] = r
    for u, r in [(u, by.get(u)) for u in fx.get("images", [])] + [(r.get("thumb"), r) for r in res]:
        if ok(u) and u not in seen:
            seen.add(u)
            out.append((u, is_video(r)))
    return [o for o in out if not dead_thumb(o[0])] if alive else out


def break_routes(ctx):
    """--break-drift / --break-phones: serve the script with the feature disabled (wire boundary, same bytes otherwise)."""
    for flag, name, old, new in ((BREAK_DRIFT, "inline-scan.js", "DRIFT_SPEED = 24", "DRIFT_SPEED = 0"),
                                 (BREAK_PHONES, "personalize.js", "    phones(m, d);\n", "\n"),
                                 (BREAK_THUMBS, "inline-scan.js", "      if (g.dead[src]) return;\n", "      return;\n"),
                                 (BREAK_PEOPLE, "scan-engine.js", "    return !s || !(", "    return true || !("),
                                 (BREAK_INCREMENTAL, "scan.js", "SITES_STEP = 10, MORE_SITES = 25, LINKS_STEP = 10, MORE_LINKS = 50",
                                  "SITES_STEP = 1e9, MORE_SITES = 1e9, LINKS_STEP = 1e9, MORE_LINKS = 1e9")):
        if not flag:
            continue
        body = (ROOT / "site" / "js" / name).read_text(encoding="utf-8")
        assert old in body, f"break: marker not found in {name}"
        ctx.route(f"**/js/{name}", lambda r, _q, b=body.replace(old, new, 1): r.fulfill(body=b, content_type="application/javascript"))
VIEWPORTS = (("phone", {"width": 390, "height": 844}), ("desktop", {"width": 1440, "height": 900}))
fails = []
MEASURED = {}

PAGES = [r for r in FX["results"] if r["kind"] != "video"]
ALSO = "Also found as " + ", ".join("@" + a for a in FX["aliases"]["discovered"])
# leak-page socials on platforms the profile does not have (the discovered Instagram never replaces hers)
FOUND = [s["url"] for s in FX["aliases"]["socials"] if s["platform"] not in {a["platform"] for a in FX["profile"]["accounts"]}]
VIDEOS = [r for r in FX["results"] if r["kind"] == "video"]
IMAGES = len(_scan_images(FX))   # the scan page: video stills too (play badge)


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
    break_routes(ctx)
    page = ctx.new_page()
    page.on("request", lambda q, posts=posts: q.method == "POST" and posts.append(q.url))
    page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
    shot = lambda name, full=False, page=page, v=vp_name: page.screenshot(path=str(out / f"{v}-{name}.png"), full_page=full)

    # 1. a scan/?p=&h= link (older links + the no-JS hero form land here; the JS hero form scans in place: `inline`)
    bodies = []
    page.on("request", lambda q, bodies=bodies: q.method == "POST" and "/api/public-scan" in q.url and bodies.append(json.loads(q.post_data)))
    page.goto(base + "scan/?p=fansly.com&h=%40demo.creator", wait_until="load")

    # 2. progress
    page.wait_for_selector("#progress-log li:not(:empty)", timeout=5000)
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
        return {hint: hint && hint.offsetParent !== null ? hint.innerText.trim() : null,
          deco: deco.map(e => [e.tagName, e.tabIndex, e.getAttribute('aria-hidden'), +getComputedStyle(e).opacity, getComputedStyle(e).cursor]),
          tabs: [...document.querySelectorAll('.g-tab')].map(e => getComputedStyle(e).cursor),
          seg: [...document.querySelectorAll('#device label')].map(e => getComputedStyle(e).cursor)};
    }""")
    bare = page.evaluate(BARE_HOVER)
    check(f"{vp_name} scan page: no :hover rule outside @media (hover: hover) (no sticky tint after a tap)", not bare, bare)
    want_hint = "Tap All · Images · Videos to switch, tap any result to open it." if vp_name == "phone" else "Click All · Images · Videos to switch, click any result to open it."
    check(f"{vp_name} scan page: hint next to the frame says Tap on touch / Click with a mouse", aff["hint"] == want_hint, aff["hint"])
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
            small = vp_name == "phone"   # 1060 px frame at 350 px: tabs / tiles too small to tap
            check(f"{vp_name} computer frame hint fits the scale", page.locator("#g-hint").inner_text().strip() == (
                "Shrunk to fit this screen. Switch to Phone to tap results." if small else want_hint), page.locator("#g-hint").inner_text())
            if small:
                page.locator("#g-hint [data-device-go]").click()
                page.wait_for_timeout(300)
                check(f"{vp_name} hint 'Switch to Phone' = the Phone toggle", page.locator(".frame-phone").count() == 1
                      and page.locator("#device input:checked").get_attribute("value") == "phone" and page.locator("#g-hint").inner_text().strip() == (
                          # Playwright's full-page screenshot flips the touch context to hover + fine pointer: ask the page
                          want_hint.replace("Tap", "Click").replace(" tap ", " click ") if page.evaluate("matchMedia('(hover: hover) and (pointer: fine)').matches") else want_hint),
                      [page.locator(".frame-phone").count(), page.locator("#device input:checked").get_attribute("value"), page.locator("#g-hint").inner_text()])
                page.locator("#device label:has(input[value=computer])").click()
                page.wait_for_timeout(300)
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
        first = (1 <= n0 <= min(10, len(PAGES))) if device == "phone" else n0 == min(10, len(PAGES))   # phone: first look fitted to ~1.5 screens
        check(f"{vp_name}/{device} All tab count (More reaches every result)", first and n1 == len(PAGES), f"{n0}→{n1} want {'≤' if device == 'phone' else ''}10→{len(PAGES)}")
        check(f"{vp_name}/{device} every result title carries open ↗", page.locator("#g-panel .g-r a.g-title .g-go").count() == n1)
        alone = page.evaluate(GO_ALONE)
        check(f"{vp_name}/{device} open ↗ never sits alone on a line (it rides on the title's last word)", not alone, alone[:3])
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
        nv0 = page.locator("#g-panel .g-v").count()
        while page.locator("[data-more=videos]").count():
            page.locator("[data-more=videos]").click()
        nv = page.locator("#g-panel .g-v").count()
        check(f"{vp_name}/{device} Videos tab count (first look {5 if device == 'phone' else 8}, More reaches every video)",
              nv0 == min(5 if device == "phone" else 8, len(VIDEOS)) and nv == len(VIDEOS), f"{nv0}→{nv} want {len(VIDEOS)}")
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
    listed = open_all_sites(page)
    check(f"{vp_name} every hit url listed", all(h["url"] in listed for h in FX["hits"]),
          f"{sum(h['url'] in listed for h in FX['hits'])}/{len(FX['hits'])}")
    check(f"{vp_name} per-site rows == domain_count", page.locator("#lx-list .lx-site").count() == FX["domain_count"])
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



def open_all_sites(page):
    """Show every site row, open each, press every "Show N more" → every link href in the list."""
    while page.locator("#lx-more").is_visible():
        page.locator("#lx-more").click()
    page.evaluate("document.querySelectorAll('#lx-list details').forEach(d => d.open = true)")
    page.wait_for_timeout(100)
    while page.locator(".lx-lmore").count():
        page.evaluate("document.querySelectorAll('.lx-lmore').forEach(b => b.click())")
    return set(page.eval_on_selector_all("#lx-list a", "els => els.map(e => e.href)"))


sys.path.insert(0, str(ROOT / "tools"))
from scan_stub import huge_result, videos_result   # noqa: E402  (the stub's own generator: the e2e expects what it serves)
HUGE = huge_result("stub-huge")
VIDS = _scan_images(videos_result("stub-videos"))   # real-report shape: 33 unique thumbs, 18 from video results
HUGE_SITES = {}
for _u, _d in [(h["url"], h["domain"]) for h in HUGE["hits"]] + [(r["link"], r["domain"]) for r in HUGE["results"]]:
    HUGE_SITES.setdefault(_d, {})[_u] = 1
HUGE_LINKS = sum(len(v) for v in HUGE_SITES.values())
HUGE_TOP = max(HUGE_SITES, key=lambda d: len(HUGE_SITES[d]))
HUGE_IMAGES = len(_scan_images(HUGE))
HUGE_VIDEOS = sum(r["kind"] == "video" for r in HUGE["results"])
NODE_BUDGET = 900   # whole page after the report renders (main before this change: ~3,800 at this size)
IN_VIEW = """() => { const a = document.activeElement, r = a.getBoundingClientRect(), s = a.closest('.ph-scroll');
    let top = document.querySelector('.rnav').getBoundingClientRect().bottom, bot = innerHeight;   /* clear of the sticky nav, */
    if (s) { const sr = s.getBoundingClientRect(), t = s.querySelector('.g-tabs');                 /* inside the phone screen, */
        top = Math.max(top, sr.top, t ? t.getBoundingClientRect().bottom : 0); bot = Math.min(bot, sr.bottom); }   /* under its tabs */
    return r.top >= top - 1 && r.bottom <= bot + 1 ? true : [Math.round(r.top), Math.round(r.bottom), Math.round(top), Math.round(bot)]; }"""


def huge_flow(browser, vp_name, vp):
    """stub-huge (1000 hit links on 100 sites): render time, DOM size, incremental sites / links, filter, the pinned
    phone scroll story, CLS, lazy thumbs, export, no 5xx / console errors. Checks named "incremental: …" are the ones
    --break-incremental (scan.js with every step = 1e9, everything rendered) must turn red; nothing else may."""
    phone = vp_name == "phone"
    tag = f"{vp_name} huge:"
    ctx = browser.new_context(viewport=vp, device_scale_factor=2 if phone else 1, is_mobile=phone, has_touch=phone, accept_downloads=True)
    outside, errors, bad, thumbs = [], [], [], []
    ctx.route("**/*", lambda r, _q: r.continue_() if urlsplit(r.request.url).hostname in ("127.0.0.1", "localhost") else (outside.append(r.request.url), r.abort()))
    break_routes(ctx)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.on("response", lambda r: r.status >= 500 and bad.append(f"{r.status} {r.url}"))
    page.on("request", lambda q: "/api/thumb" in q.url and thumbs.append(q.url))
    # layout shifts over the whole flow: form → progress (log fills) → report → scroll story
    page.add_init_script("""window.__ls = []; new PerformanceObserver(l => l.getEntries().forEach(e => { if (!e.hadRecentInput) window.__ls.push(e); }))
      .observe({type: 'layout-shift', buffered: true});""")
    CLS = """() => { const ls = window.__ls;
      return [+ls.reduce((a, e) => a + e.value, 0).toFixed(4), ls.slice(0, 3).map(e => e.sources.map(s => s.node && s.node.nodeType === 1 ? s.node.tagName + '.' + s.node.className : '?').join(','))]; }"""
    cdp = ctx.new_cdp_session(page)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})   # a mid-range phone, not this machine

    # 1. a fresh scan: result event → painted report
    page.goto(base + "scan/?h=stub-huge", wait_until="load")
    page.wait_for_selector("#report:not([hidden])", timeout=20000)
    page.wait_for_function("performance.getEntriesByName('leakscan:report').length > 0", timeout=5000)
    ms = page.evaluate("performance.getEntriesByName('leakscan:report')[0].duration")
    check(f"{tag} report painted < 1500 ms after the result event (CPU x4)", ms < 1500, f"{ms:.0f} ms")
    nodes = page.evaluate("document.getElementsByTagName('*').length")
    check(f"{tag} incremental: page DOM <= {NODE_BUDGET} elements after render", nodes <= NODE_BUDGET, nodes)
    check(f"{tag} summary + section nav say 100 sites / 1,000 pages", (digits(page.locator("[data-stat=domains]").inner_text()),
          digits(page.locator("[data-stat=pages]").inner_text()), page.locator("#rnav-n").inner_text()) == (100, 1000, "100"))
    check(f"{tag} heading line: every site + link counted", page.locator("#lx-sub").inner_text() == f"100 sites · {HUGE_LINKS:,} links (1,000 indexed pages + {HUGE_LINKS - 1000} more Google results) · most copies first",
          page.locator("#lx-sub").inner_text())
    rows = lambda: page.locator("#lx-list .lx-site").count()
    check(f"{tag} incremental: 10 sites, no link rows until a site is opened, 'Show 25 more sites · 90 left'",
          (rows(), page.locator("#lx-list a").count(), page.locator("#lx-more").inner_text()) == (10, 0, "Show 25 more sites · 90 left"),
          (rows(), page.locator("#lx-list a").count(), page.locator("#lx-more").inner_text()))
    first = page.locator("#lx-list .lx-name").first.inner_text()
    check(f"{tag} biggest site first", first == HUGE_TOP, first)
    thumbs0 = len(set(thumbs))   # at load, before any scroll / tab / reopen; distinct images (a tile's people-photo probe re-reads its own thumb)
    check(f"{tag} lazy thumbs: at load <= 24 of {HUGE_IMAGES} images fetched (strip + first screen only)", thumbs0 <= 24, (thumbs0, len(thumbs)))

    # 2. the scroll story: summary → pinned phone (screen scrolls 1:1) → the sites
    if phone:
        g = page.evaluate("""() => { const t = document.querySelector('.ph-track'), f = t.firstElementChild, s = t.querySelector('.ph-scroll');
            return {top: t.getBoundingClientRect().top + scrollY, pin: parseFloat(getComputedStyle(f).top), h: t.offsetHeight, fh: f.offsetHeight,
                    max: s.scrollHeight - s.clientHeight, vh: innerHeight}; }""")
        check(f"{tag} phone frame fits the screen under the nav", g["fh"] + g["pin"] <= g["vh"], g)
        check(f"{tag} phone frame ~80% of the screen (>= 78%)", g["fh"] >= 0.78 * g["vh"], [g["fh"], g["vh"]])
        check(f"{tag} track = frame + screen overflow", abs(g["h"] - g["fh"] - g["max"]) <= 2 and g["max"] > 400, g)
        runs = {}   # All: first look fitted (<= 1.5 screens, rest behind More); Images 12 / Videos 5 in the screen's own scroll, rest behind More
        for t in ("images", "videos", "all"):
            page.locator(f"#g-tab-{t}").click()
            page.wait_for_timeout(300)
            runs[t] = page.evaluate("""() => { const t = document.querySelector('.ph-track'), s = t.querySelector('.ph-scroll'), tl = [...document.querySelectorAll('#g-panel .g-tile, #g-panel .g-v')];
                const last = tl[tl.length - 1], sr = s.getBoundingClientRect();
                return {run: t.offsetHeight - t.firstElementChild.offsetHeight, more: !!document.querySelector('#g-panel [data-more]'), n: tl.length,
                        cols: tl.filter(e => e.offsetTop === (tl[0] && tl[0].offsetTop)).length, inner: tl.every(e => s.contains(e)),
                        reach: !last || last.getBoundingClientRect().bottom - sr.top + s.scrollTop <= s.scrollHeight + 1}; }""")
        page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
        ri, rv = runs["images"], runs["videos"]
        check(f"{tag} pin: All first look <= 1.5 screens, rest behind More", runs["all"]["run"] <= 1.5 * g["vh"] and runs["all"]["more"], [runs["all"], g["vh"]])
        check(f"{tag} pin: Images first look = 4 rows x 3 = {min(HUGE_IMAGES, 12)} of {HUGE_IMAGES} inside the screen's own scroll (< 1 screen of scrolling), rest behind More",
              ri["n"] == min(HUGE_IMAGES, 12) and ri["cols"] == 3 and ri["inner"] and ri["reach"] and ri["more"] == (HUGE_IMAGES > 12) and ri["run"] < g["vh"], [ri, g["vh"]])
        check(f"{tag} pin: Videos first look = 5 of {HUGE_VIDEOS} inside the screen's own scroll (<= 1.75 screens of scrolling, relaxed), rest behind More",
              rv["n"] == min(HUGE_VIDEOS, 5) and rv["inner"] and rv["reach"] and rv["more"] == (HUGE_VIDEOS > 5) and rv["run"] <= 1.75 * g["vh"], [rv, g["vh"]])
        # hand-off: 60 px before the screen's end, a 400 px wheel / touch scroll over the phone ends the screen and moves the
        # page the rest (frame goes up, nothing stuck); "Show more …" is hidden (rise) until it enters the screen, then shown
        HO = """() => { const f = document.querySelector('.frame-phone'), s = f.querySelector('.ph-scroll'), m = document.querySelector('#g-panel [data-more]');
            return {y: Math.round(scrollY), st: Math.round(s.scrollTop), max: s.scrollHeight - s.clientHeight, ft: Math.round(f.getBoundingClientRect().top),
                    rise: !!m && m.classList.contains('g-rise'), seen: !!m && m.classList.contains('g-in'), op: m ? +getComputedStyle(m).opacity : -1}; }"""
        ho, rise = {}, {}
        OP = "() => { const m = document.querySelector('#g-panel [data-more]'); return m ? +getComputedStyle(m).opacity : -1; }"
        for t in ("images", "videos"):
            page.locator(f"#g-tab-{t}").click()
            rise[t] = [page.evaluate(OP)]   # no flash: hidden from the first frame
            page.evaluate("document.querySelector('#g-panel [data-more]').focus({preventScroll: true})")
            rise[t].append(page.evaluate(OP))   # keyboard focus: shown at once
            page.evaluate("document.activeElement.blur()")
            page.wait_for_timeout(700)
            for how in ("wheel", "touch"):
                a0 = page.evaluate(HO)
                page.evaluate(f"window.scrollTo({{top: {g['top'] - g['pin']} + {a0['max']} - 60, behavior: 'instant'}})")
                page.wait_for_timeout(300)
                a = page.evaluate(HO)
                box = page.locator(".frame-phone").bounding_box()
                cx, cy = box["x"] + box["width"] / 2, g["pin"] + 200
                if how == "wheel":
                    page.mouse.move(cx, cy)
                    page.mouse.wheel(0, 400)
                else:
                    page.context.new_cdp_session(page).send("Input.synthesizeScrollGesture", {"x": int(cx), "y": int(cy), "yDistance": -400, "speed": 1200, "gestureSourceType": "touch", "preventFling": True})
                page.wait_for_timeout(800)
                z = page.evaluate(HO)
                ho[f"{t}/{how}"] = {"hidden_at_top": [a0["rise"], a0["seen"], a0["op"]], "dy": z["y"] - a["y"], "st": [a["st"], z["st"], z["max"]],
                                    "frame_up": g["pin"] - z["ft"], "shown": [z["seen"], z["op"]]}
            page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
            page.wait_for_timeout(200)
        page.locator("#g-tab-all").click()
        page.wait_for_timeout(300)
        check(f"{tag} pin: Images / Videos hand-off: a wheel / touch scroll past the screen's end moves the page (screen at its end, frame goes up the rest)",
              all(abs(v["dy"] - 400) <= 8 and v["st"][1] == v["st"][2] and abs(v["frame_up"] - (400 - (v["st"][2] - v["st"][0]))) <= 8 for v in ho.values()), ho)
        check(f"{tag} pin: 'Show more images / videos' hidden until it enters the screen, then shown (rise animation, ends at opacity 1)",
              all(v["hidden_at_top"] == [True, False, 0] and v["shown"] == [True, 1] for k, v in ho.items() if k.endswith("wheel")), ho)
        check(f"{tag} pin: 'Show more …' rise: no flash (opacity 0 from the tab's first frame), keyboard focus shows it at once", all(v == [0, 1] for v in rise.values()), rise)
        rctx = browser.new_context(viewport=vp, device_scale_factor=2, is_mobile=True, has_touch=True, reduced_motion="reduce")
        rp = rctx.new_page()
        rp.goto(base + "scan/?r=" + parse_qs(urlsplit(page.url).query).get("r", [""])[0], wait_until="load")
        rp.wait_for_selector("#report:not([hidden])", timeout=8000)
        rm = {}
        for t in ("images", "videos"):
            rp.locator(f"#g-tab-{t}").click()
            rm[t] = rp.evaluate("() => { const m = document.querySelector('#g-panel [data-more]'); return [m.classList.contains('g-rise'), +getComputedStyle(m).opacity]; }")
        rctx.close()
        check(f"{tag} pin: reduced motion: 'Show more …' never hidden, no rise", all(v == [False, 1] for v in rm.values()), rm)
        page.evaluate(f"window.scrollTo({{top: {g['top'] - g['pin'] + 400}, behavior: 'instant'}})")
        page.wait_for_timeout(250)
        st = page.evaluate("() => [document.querySelector('.frame-phone').getBoundingClientRect().top, document.querySelector('.ph-scroll').scrollTop]")
        check(f"{tag} pin: mid-scroll the frame stays put and its screen scrolls 1:1", abs(st[0] - g["pin"]) <= 1 and abs(st[1] - 400) <= 2, st)
        page.screenshot(path=str(out / f"{vp_name}-h2-pinned.png"))
        pb = page.evaluate("() => [document.querySelector('.ph-reveal').getBoundingClientRect().top, document.querySelector('.ph-scroll').getBoundingClientRect().bottom]")
        check(f"{tag} pin: the Reveal pill sits in its own bar, under the results (covers no line)", pb[0] >= pb[1] - 1, pb)
        pill = page.locator(".ph-reveal")
        blur = lambda: page.eval_on_selector(".ph-scroll .g-img img", "e => getComputedStyle(e).filter")
        b0 = blur()
        pill.click()
        page.wait_for_timeout(350)
        b1 = [blur(), page.locator("#reveal").get_attribute("aria-pressed"), page.locator(".ph-reveal").get_attribute("aria-pressed"), page.locator(".ph-reveal").inner_text()]
        page.locator(".ph-reveal").click()
        page.wait_for_timeout(350)
        check(f"{tag} pin: Reveal / Blur on the pinned phone = the button above (state shared)", "blur" in b0 and b1 == ["none", "true", "true", "Blur images"]
              and "blur" in blur() and page.locator("#reveal").get_attribute("aria-pressed") == "false", [b0, b1])
        page.locator("#g-tab-images").click()
        page.wait_for_timeout(250)
        st = page.evaluate("() => [document.querySelector('.frame-phone').getBoundingClientRect().top, document.querySelector('.ph-scroll').scrollTop, document.querySelectorAll('#g-panel .g-tile').length]")
        check(f"{tag} pin: a tab switched mid-scroll opens at its top, frame stays put", abs(st[0] - g["pin"]) <= 1 and st[1] == 0 and st[2] > 0, st)
        page.locator("#g-tab-all").click()
        had = page.locator("#g-panel .g-r").count()
        page.locator("[data-more=all]").evaluate("b => b.focus()")   # as Tab would: the screen scrolls to it, the page follows
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        page.wait_for_timeout(400)
        nx = page.evaluate("() => { const a = document.activeElement, r = a.closest('.g-r'); return [a.className, [...document.querySelectorAll('#g-panel .g-r')].indexOf(r)]; }")
        nx.append(page.evaluate(IN_VIEW))
        check(f"{tag} keyboard More results → focus on the first new result, in view", nx == ["g-title", had, True], [nx, had])
        page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
        page.wait_for_timeout(150)
    # the All tab's Images block: one row, every image, swipe sideways (snap), keyboard + desktop arrows; the page never scrolls sideways
    page.locator("#g-tab-all").click()
    page.wait_for_timeout(250)
    STRIP = """() => { const s = document.querySelector('#g-panel .g-strip'); if (!s) return null; const b = [...s.querySelectorAll(':scope > .g-pack-b')], cs = getComputedStyle(s),
        sl = s.getBoundingClientRect().left + parseFloat(cs.scrollPaddingLeft || 0), w = s.parentNode;
        return {n: b.length, rows: new Set(b.map(e => e.offsetTop)).size, tile: [Math.round(b[0].offsetWidth), Math.round(b[0].offsetHeight)], sw: s.scrollWidth, cw: s.clientWidth,
          left: Math.round(s.scrollLeft), snap: cs.scrollSnapType, ox: cs.overflowX, bar: s.offsetHeight - s.clientHeight, open: b.every(e => e.matches('a[target=_blank][href^=http], button[data-goto=images]')) && b.some(e => e.matches('a')),
          snapped: b.some(e => Math.abs(e.getBoundingClientRect().left - sl) <= 2), start: w.classList.contains('at-start'), end: w.classList.contains('at-end'),
          lazy: b.every(e => e.querySelector('img').loading === 'lazy'), showMore: /show more images/i.test(document.getElementById('g-panel').textContent),
          pageX: document.documentElement.scrollWidth - innerWidth, inner: (document.querySelector('.ph-scroll') || {}).scrollTop || 0}; }"""
    s0 = page.evaluate(STRIP)
    check(f"{tag} strip: All tab Images = one row of all {HUGE_IMAGES} images, square {'~110px' if phone else '150px'} tiles, scrollWidth > clientWidth, snap x mandatory, no scrollbar, no 'Show more images', each tile opens its page (or the Images tab)",
          s0 and s0["n"] == HUGE_IMAGES and s0["rows"] == 1 and abs(s0["tile"][0] - s0["tile"][1]) <= 1 and (95 <= s0["tile"][0] <= 125 if phone else s0["tile"][0] == 150)
          and s0["sw"] > s0["cw"] and s0["snap"] == "x mandatory" and s0["ox"] == "auto" and s0["bar"] == 0 and not s0["showMore"] and s0["open"] and s0["lazy"] and s0["start"], s0)
    sb = page.eval_on_selector("#g-panel .g-strip", "s => { const r = s.getBoundingClientRect(); return [r.left + r.width * .75, r.top + r.height / 2]; }")
    if phone:   # a real touch swipe (right → left), momentum + snap settle
        cdp.send("Input.synthesizeScrollGesture", {"x": int(sb[0]), "y": int(min(sb[1], vp["height"] - 10)), "xDistance": -260, "yDistance": 0, "gestureSourceType": "touch", "speed": 1200})
    else:       # hover shows the arrows; the next arrow pages the strip
        page.mouse.move(*sb)
        page.wait_for_timeout(350)
        arrows = page.evaluate("() => ['.g-strip-prev', '.g-strip-next'].map(c => { const b = document.querySelector('#g-panel ' + c); return [+getComputedStyle(b).opacity, b.disabled, b.getAttribute('aria-label')]; })")
        try:
            page.locator("#g-panel .g-strip-next").click(timeout=3000)
        except PWTimeout:
            arrows.append("next not clickable")
    page.wait_for_timeout(1200)
    s1 = page.evaluate(STRIP)
    page.screenshot(path=str(out / f"{vp_name}-h2b-strip-swiped.png"))
    if phone:
        check(f"{tag} strip: a touch swipe left scrolls the strip and snaps to a tile; page and phone screen stay put", s1["left"] > 100 and s1["snapped"] and s1["pageX"] <= 0
              and s1["inner"] == s0["inner"] and not s1["start"], [s0["left"], s1])
    else:
        prev_on = page.evaluate("() => !document.querySelector('#g-panel .g-strip-prev').disabled")
        check(f"{tag} strip: desktop arrows on hover, named (prev hidden + disabled at the start), next pages the strip and snaps, then prev is enabled",
              arrows[0][:2] == [0, True] and arrows[1][:2] == [1, False] and arrows[0][2] and arrows[1][2] and prev_on
              and s1["left"] >= 0.6 * s1["cw"] and s1["snapped"] and not s1["start"] and s1["pageX"] <= 0, [arrows, prev_on, s1])
        page.mouse.move(0, 0)
    page.locator("#g-panel .g-strip > .g-pack-b").first.focus()
    kk = []
    for key in ("ArrowRight", "ArrowRight", "ArrowLeft", "End", "Home"):
        page.keyboard.press(key)
        page.wait_for_timeout(450)
        kk.append(page.evaluate("() => { const a = document.activeElement, b = [...document.querySelectorAll('#g-panel .g-strip > .g-pack-b')]; return b.indexOf(a); }"))
        if key == "End":
            kk.append(page.evaluate("document.querySelector('#g-panel .g-strip-w').classList.contains('at-end')"))
    page.keyboard.press("Tab")
    kk.append(page.evaluate("() => [...document.querySelectorAll('#g-panel .g-strip > .g-pack-b')].indexOf(document.activeElement)"))
    check(f"{tag} strip: keyboard → / ← / End / Home move focus along the tiles (End scrolls the strip to its end), Tab reaches the next one",
          kk == [1, 2, 1, HUGE_IMAGES - 1, True, 0, 1], kk)
    page.locator("#g-panel .g-strip").evaluate("s => s.scrollTo({left: 0, behavior: 'instant'})")
    page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
    page.wait_for_timeout(200)
    page.mouse.move(vp["width"] / 2, vp["height"] / 2)
    steps = 0
    while page.evaluate("document.getElementById('sites-title').getBoundingClientRect().top") > vp["height"] * .4 and steps < 200:
        page.mouse.wheel(0, 240)
        page.wait_for_timeout(30)
        steps += 1
    page.wait_for_timeout(300)
    end = page.evaluate("() => { const s = document.querySelector('.ph-scroll'); return s ? s.scrollHeight - s.clientHeight - s.scrollTop : 0; }")
    sec = page.evaluate("document.querySelector('.rnav-a[aria-current]') && document.querySelector('.rnav-a[aria-current]').dataset.sec")
    check(f"{tag} scroll: wheeling down past the Google frame reaches the sites ({steps} steps), frame scrolled to its end, nav on Sites",
          steps < 200 and end <= 2 and sec == "sites", [steps, end, sec])
    page.evaluate("window.scrollBy({top: -Math.round(innerHeight * .3), behavior: 'instant'})")   # just past the mock
    page.wait_for_timeout(300)
    page.screenshot(path=str(out / f"{vp_name}-h3-past-mock.png"))
    cls0 = page.evaluate(CLS)   # report built + the whole scroll story, no clicks yet

    # 3. show more sites, open a site, its links in steps, close = gone
    nx, nl = None, None   # (no Show more when everything is already shown: --break-incremental)
    if page.locator("#lx-more").is_visible():
        page.locator("#lx-more").evaluate("b => { b.scrollIntoView({block: 'center', behavior: 'instant'}); b.focus(); }")   # as Tab would bring it
        page.keyboard.press("Enter")
        page.wait_for_timeout(400)
        nx = page.evaluate("() => { const a = document.activeElement, rows = [...document.querySelectorAll('#lx-list .lx-site')]; return [a.tagName, rows.indexOf(a.closest('.lx-site'))]; }")
        nx.append(page.evaluate(IN_VIEW))
        page.keyboard.press("Enter")   # open that site from the keyboard
        page.wait_for_timeout(100)
        lm = page.locator("#lx-list .lx-site").nth(10).locator(".lx-lmore")
        if lm.count():
            lm.evaluate("b => { b.scrollIntoView({block: 'center', behavior: 'instant'}); b.focus(); }")
            page.keyboard.press("Enter")
            page.wait_for_timeout(400)
            nl = page.evaluate("() => { const a = document.activeElement, l = a.closest('.lx-links'); return [a.tagName, l ? [...l.children].indexOf(a.parentNode) : -1]; }")
            nl.append(page.evaluate(IN_VIEW))
    check(f"{tag} incremental: keyboard Show more sites → focus on the first new site, in view", nx == ["SUMMARY", 10, True], nx)
    check(f"{tag} incremental: keyboard Show more links → focus on the first new link, in view", nl == ["A", 10, True], nl)
    if nx:
        page.locator("#lx-list .lx-site").nth(10).locator("summary").click()   # close it again
    page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
    page.wait_for_timeout(100)
    if page.locator("#lx-more").is_visible():
        page.locator("#lx-more").click()
    check(f"{tag} incremental: each Show more adds 25 sites", rows() == 60 and page.locator("#lx-more").inner_text() == "Show 25 more sites · 40 left", rows())
    top = page.locator("#lx-list .lx-site").first
    top.locator("summary").click()
    n_top = len(HUGE_SITES[HUGE_TOP])
    page.wait_for_timeout(150)
    lm = top.locator(".lx-lmore")
    got = (top.locator("a").count(), lm.inner_text() if lm.count() else None)
    check(f"{tag} incremental: an opened site shows 10 links + 'Show 50 more links · {n_top - 10} left'", got == (10, f"Show 50 more links · {n_top - 10} left"), got)
    hrefs = top.locator("a").evaluate_all("els => els.map(e => e.href)")
    check(f"{tag} opened site lists its own links, external + safe", set(hrefs) <= set(HUGE_SITES[HUGE_TOP]) and top.locator("a").first.get_attribute("rel") == "noopener noreferrer nofollow"
          and top.locator("a").first.get_attribute("target") == "_blank", hrefs[:2])
    while top.locator(".lx-lmore").count():
        top.locator(".lx-lmore").click()
    check(f"{tag} every link of the site reachable", top.locator("a").count() == n_top, top.locator("a").count())
    top.locator("summary").scroll_into_view_if_needed()
    page.screenshot(path=str(out / f"{vp_name}-h4-open-site.png"))
    top.locator("summary").click()
    page.wait_for_timeout(100)
    check(f"{tag} closing a site drops its links from the DOM", top.locator("a").count() == 0)

    # 4. filter: by site, by URL part, nothing; clear
    def filt(q):
        page.locator("#lx-q").fill(q)
        page.wait_for_timeout(350)
        return page.locator("#lx-status").inner_text()
    q = "thread/1"
    want = {d: [u for u in us if q in u.lower()] for d, us in HUGE_SITES.items()}
    want = {d: v for d, v in want.items() if v}
    st = filt(q)
    check(f"{tag} filter by URL part: status counts sites + links", st == f"{len(want)} sites · {sum(map(len, want.values()))} links match “{q}”", st)
    shown = page.locator("#lx-list a").evaluate_all("els => els.map(e => e.href)")
    check(f"{tag} filter: only matching links shown, highlighted", shown and all(q in u.lower() for u in shown)
          and page.locator("#lx-list a mark").count() == len(shown), len(shown))
    check(f"{tag} incremental: filter shows 10 sites + Show more, opens only the first", rows() == min(10, len(want))
          and page.locator("#lx-list details[open]").count() == 1, [rows(), page.locator("#lx-list details[open]").count()])
    prev = page.locator("#lx-list .lx-top").evaluate_all("els => els.map(e => e.textContent)")
    check(f"{tag} filter: each site's preview is its first matching link", prev and all(q in t.lower() for t in prev), prev[:3])
    page.screenshot(path=str(out / f"{vp_name}-h5-filter.png"))
    filt("huge-2")   # matches the tail of long links: the preview starts just before the match
    vis = page.evaluate("""() => [...document.querySelectorAll('#lx-list .lx-top')].filter(e => e.offsetWidth).map(e => {
        const m = e.querySelector('mark'); return !!m && m.getBoundingClientRect().right <= e.getBoundingClientRect().right + 1; })""")
    check(f"{tag} filter: a match in a link's tail is in view in its preview", vis and all(vis), vis)
    st = filt("FANZONE")
    check(f"{tag} filter by site name (any case)", st.startswith("1 site · ") and page.locator("#lx-list .lx-name").all_inner_texts() == ["fanzone.example"], st)
    st = filt("zzqx")
    check(f"{tag} filter: nothing → says so, empty list hidden", st == "No site or link contains “zzqx”." and rows() == 0 and page.locator("#lx-more").is_hidden(), st)
    filt("")
    check(f"{tag} incremental: clearing the filter → first 10 sites again", rows() == 10 and page.locator("#lx-status").inner_text() == "")

    # 5. export carries everything, whatever is shown
    with page.expect_download() as dl:
        page.locator("#download").click()
    txt = pathlib.Path(dl.value.path()).read_text()
    got = {ln for ln in txt.splitlines() if ln.startswith("https://") and "/scan/?r=" not in ln}
    check(f"{tag} Download .txt carries every link ({HUGE_LINKS})", got == {u for us in HUGE_SITES.values() for u in us}, len(got))

    # 5b. section nav: scrolls to the section, no history entry, no #hash in the report URL
    hl, url0 = page.evaluate("history.length"), page.url
    page.locator(".rnav-a[data-sec=sites]").click()
    page.wait_for_timeout(900)
    nav = page.evaluate("""() => [history.length, location.hash, Math.round(document.getElementById('sites').getBoundingClientRect().top),
        document.activeElement.id, document.querySelector('.rnav-a[aria-current]') && document.querySelector('.rnav-a[aria-current]').dataset.sec]""")
    page.locator(".rnav-a[data-sec=google]").click()
    page.wait_for_timeout(900)
    nav2 = page.evaluate("[history.length, location.hash, Math.round(document.getElementById('google').getBoundingClientRect().top)]")
    check(f"{tag} section nav: scrolls to Sites / Google, focus on the heading, no history entry or #hash",
          nav[0] == hl and nav[1] == "" and 0 <= nav[2] <= 200 and nav[3] == "sites-title" and nav[4] == "sites"
          and nav2[0] == hl and nav2[1] == "" and 0 <= nav2[2] <= 200 and page.url == url0, [hl, nav, nav2])

    # 6. reopen ?r= (stored huge report) renders the same way
    slug = parse_qs(urlsplit(page.url).query).get("r", [""])[0]
    page.goto(base + "scan/?r=" + slug)
    page.wait_for_selector("#report:not([hidden])", timeout=8000)
    page.wait_for_function("performance.getEntriesByName('leakscan:report').length > 0", timeout=5000)
    ms2 = page.evaluate("performance.getEntriesByName('leakscan:report')[0].duration")
    check(f"{tag} ?r= reopen: built + painted < 1500 ms (CPU x4)", ms2 < 1500, f"{ms2:.0f} ms")
    check(f"{tag} incremental: ?r= reopen shows the first 10 sites", rows() == 10, rows())
    page.screenshot(path=str(out / f"{vp_name}-h1-top.png"))
    cls = [cls0, page.evaluate(CLS)]
    check(f"{tag} no layout shift without input over the whole flow (CLS 0: form → progress → report → scroll story; ?r= reopen)", cls[0][0] == 0 and cls[1][0] == 0, cls)
    check(f"{tag} no 5xx", not bad, bad)
    check(f"{tag} no request left loopback", not outside, outside)
    check(f"{tag} no JS / console errors", not errors, errors)
    (out / f"{vp_name}-huge-metrics.json").write_text(json.dumps({"render_ms": round(ms), "reopen_ms": round(ms2), "dom_elements": nodes,
                                                                  "wheel_steps_to_sites": steps, "cls": [cls[0][0], cls[1][0]], "thumbs_at_load": thumbs0, "thumbs_total": len(thumbs)}))
    ctx.close()
    if phone:   # screens too short to pin the phone: a shorter static preview, no scroll box inside the page; More expands it
        for w, h in ((320, 568), (390, 560)):
            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2, is_mobile=True, has_touch=True)
            p2 = ctx.new_page()
            p2.goto(base + "scan/?r=" + slug)
            p2.wait_for_selector("#report:not([hidden])", timeout=8000)
            p2.wait_for_timeout(300)
            SCROLLERS = """() => [...document.querySelectorAll('#report *')].filter(e => ['auto', 'scroll'].includes(getComputedStyle(e).overflowY)
                && e.scrollHeight > e.clientHeight + 1).map(e => e.className)"""
            r = p2.evaluate("""() => { const f = document.querySelector('.frame-phone'); return [getComputedStyle(f).position, document.querySelectorAll('#g-panel .g-r').length,
                !!document.querySelector('#g-panel [data-more=all]')]; }""")
            sc = p2.evaluate(SCROLLERS)
            fh = {}
            for t, item in (("images", ".g-tile"), ("videos", ".g-v"), ("all", ".g-r")):
                p2.locator(f"#g-tab-{t}").click()
                p2.wait_for_timeout(250)
                fh[t] = [p2.evaluate("document.querySelector('.frame-phone').offsetHeight"), p2.locator(f"#g-panel {item}").count()]
            check(f"{tag} short screen ({w}x{h}): All's static preview <= 1.5 screens tall; Images its first 12, Videos its first 5",
                  fh["all"][0] <= 1.5 * h and fh["images"][1] == min(HUGE_IMAGES, 12) and fh["videos"][1] == min(HUGE_VIDEOS, 5), [fh, 1.5 * h])
            p2.locator("[data-more=all]").click()
            p2.wait_for_timeout(200)
            n2 = p2.locator("#g-panel .g-r").count()
            sc2 = p2.evaluate(SCROLLERS)
            check(f"{tag} short screen ({w}x{h}): frame not pinned, short preview, no inner scroll box; More results expands it",
                  r[0] == "static" and 0 < r[1] < 10 and r[2] and not sc and not sc2 and n2 > r[1], [r, sc, n2, sc2])
            pl = p2.evaluate("""() => { const b = document.querySelector('.ph-reveal'), r = b.getBoundingClientRect(), s = document.querySelector('.ph-screen').getBoundingClientRect();
                const g = document.createRange(); g.selectNodeContents(b.querySelector('span'));
                return [new Set([...g.getClientRects()].map(x => Math.round(x.top))).size, Math.round(r.left - s.left), Math.round(s.right - r.right)]; }""")
            check(f"{tag} short screen ({w}x{h}): Reveal pill label on one line, inside the phone screen", pl[0] == 1 and min(pl[1:]) >= 8, pl)
            # Show fewer: back to exactly the first look; focus on More, clear of the pinned header + section nav
            fl = {}
            for t, item in (("all", ".g-r"), ("images", ".g-tile"), ("videos", ".g-v")):
                p2.locator(f"#g-tab-{t}").click()
                p2.wait_for_timeout(200)
                n0 = r[1] if t == "all" else p2.locator(f"#g-panel {item}").count()   # All: grown above
                if t != "all" and p2.locator(f"[data-more={t}]").count():
                    p2.locator(f"[data-more={t}]").click()
                    p2.wait_for_timeout(200)
                n1 = p2.locator(f"#g-panel {item}").count()
                if p2.locator(f"[data-less={t}]").count():
                    p2.locator(f"[data-less={t}]").click()
                    p2.wait_for_timeout(300)
                fl[t] = p2.evaluate("""([t, item]) => { const a = document.activeElement, r = a.getBoundingClientRect(), bar = document.querySelector('.rnav').getBoundingClientRect().bottom;
                    return {n: document.querySelectorAll('#g-panel ' + item).length, more: a.matches('[data-more=' + t + ']'), top: Math.round(r.top), bar: Math.round(bar), inView: r.bottom <= innerHeight}; }""", [t, item])
                fl[t].update(first=n0, grown=n1)
            check(f"{tag} short screen ({w}x{h}): Show fewer restores each tab's first look exactly; focus on More, below the pinned bar, in view",
                  all(v["n"] == v["first"] < v["grown"] and v["more"] and v["top"] >= v["bar"] and v["inView"] for v in fl.values()), fl)
            ctx.close()
        # rotation / resize: each tab not grown by More refits to the new screen; a tab grown by More keeps its items
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
        p4 = ctx.new_page()
        p4.goto(base + "scan/?r=" + slug)
        p4.wait_for_selector("#report:not([hidden])", timeout=8000)
        p4.locator("#g-tab-images").click()
        p4.locator("[data-more=images]").click()
        ni = p4.locator("#g-panel .g-tile").count()
        p4.locator("#g-tab-all").click()
        p4.wait_for_timeout(200)
        RUN = "() => { const t = document.querySelector('.ph-track'); return t.offsetHeight - t.firstElementChild.offsetHeight; }"
        rr = {"all@844": p4.evaluate(RUN)}
        p4.set_viewport_size({"width": 360, "height": 640})
        p4.wait_for_timeout(700)
        rr["all"] = p4.evaluate(RUN)
        rr["frame_pct"] = p4.evaluate("Math.round(100 * document.querySelector('.frame-phone').offsetHeight / innerHeight)")
        p4.locator("#g-tab-videos").click()
        p4.wait_for_timeout(300)
        rr["videos_n"] = p4.locator("#g-panel .g-v").count()
        p4.locator("#g-tab-images").click()
        p4.wait_for_timeout(300)
        rr["images_n"] = [ni, p4.locator("#g-panel .g-tile").count()]
        check(f"{tag} resize 390x844 → 360x640: All refits (<= 1.5 screens), frame >= 78%, Videos first 5, Images grown by More keeps its {min(HUGE_IMAGES, 36)}",
              rr["all@844"] > 1.5 * 640 and rr["all"] <= 1.5 * 640 and rr["frame_pct"] >= 78 and rr["videos_n"] == min(HUGE_VIDEOS, 5)
              and rr["images_n"][0] == rr["images_n"][1] == min(HUGE_IMAGES, 36), rr)
        # a grown tab shrinks back: "Show fewer" restores its first look (12), the view lands on its More button
        grown = p4.locator("#g-panel .g-tile").count()
        has_less = p4.locator("[data-less=images]").count() == 1
        if has_less:
            p4.locator("[data-less=images]").click()
            p4.wait_for_timeout(300)
        sf = p4.evaluate("""() => { const m = document.querySelector('#g-panel [data-more=images]'), r = m && m.getBoundingClientRect();
            return {n: document.querySelectorAll('#g-panel .g-tile').length, less: !!document.querySelector('[data-less]'),
              focus: document.activeElement === m, seen: !!r && r.top >= document.querySelector('.rnav').getBoundingClientRect().bottom && r.bottom <= innerHeight}; }""")
        sf["grown"], sf["has_less"] = grown, has_less
        check(f"{tag} Show fewer: grown Images (36) goes back to its first 12, focus + view on its More button",
              has_less and grown == min(HUGE_IMAGES, 36) and sf["n"] == min(HUGE_IMAGES, 12) and not sf["less"] and sf["focus"] and sf["seen"], sf)
        ctx.close()
        # keyboard: Enter on "Show more images" until all are shown; focus stays in the panel (new tile / More / Show fewer)
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
        p6 = ctx.new_page()
        p6.goto(base + "scan/?r=" + slug)
        p6.wait_for_selector("#report:not([hidden])", timeout=8000)
        p6.locator("#g-tab-images").click()
        p6.wait_for_timeout(300)
        kb = []
        for _ in range(12):
            m = p6.locator("#g-panel [data-more=images]")
            if not m.count():
                break
            m.focus()
            p6.keyboard.press("Enter")
            p6.wait_for_timeout(150)
            kb.append(p6.evaluate("() => { const a = document.activeElement; return [!!a.closest('#g-panel'), a.className, document.querySelectorAll('#g-panel .g-tile').length]; }"))
        check(f"{tag} keyboard: Enter on More until every image shows, focus never leaves the panel (ends on Show fewer / a tile)",
              kb and all(k[0] for k in kb) and not p6.locator("#g-panel [data-more=images]").count(), kb)
        ctx.close()
        # landscape phone: pinned chrome (site header + section nav) <= 15% of the screen height
        ctx = browser.new_context(viewport={"width": 844, "height": 390}, device_scale_factor=2, is_mobile=True, has_touch=True)
        p5 = ctx.new_page()
        p5.goto(base + "scan/?r=" + slug)
        p5.wait_for_selector("#report:not([hidden])", timeout=8000)
        p5.evaluate("document.getElementById('sites').scrollIntoView({behavior: 'instant'}); window.scrollBy(0, 400)")
        p5.wait_for_timeout(200)
        ch = p5.evaluate("""() => { const b = e => e.getBoundingClientRect(), h = b(document.querySelector('.site-header')), n = b(document.querySelector('.rnav'));
            return {header: Math.max(0, Math.round(h.bottom)), nav: [Math.round(n.top), Math.round(n.bottom)], chrome: Math.round(Math.max(0, h.bottom, n.bottom)), vh: innerHeight}; }""")
        p5.screenshot(path=str(out / f"{vp_name}-h6-landscape.png"))
        check(f"{tag} landscape 844x390: pinned chrome (header + section nav) <= 15% of the screen", ch["nav"][0] >= -1 and ch["chrome"] <= 0.15 * ch["vh"], ch)
        ctx.close()
        wide = {}   # narrow phones: nothing sticks out sideways (summary numbers, section nav, controls, filter)
        for w in (320, 360):
            ctx = browser.new_context(viewport={"width": w, "height": 700}, device_scale_factor=2, is_mobile=True, has_touch=True)
            p3 = ctx.new_page()
            p3.goto(base + "scan/?r=" + slug)
            p3.wait_for_selector("#report:not([hidden])", timeout=8000)
            p3.fill("#lx-q", "thread/1")
            p3.wait_for_timeout(400)
            wide[w] = p3.evaluate("document.documentElement.scrollWidth")
            ctx.close()
        check(f"{tag} no sideways scroll at 320 / 360 px", all(v <= w for w, v in wide.items()), wide)

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
              "blog/post-1.html", "blog/post-2.html", "blog/post-3.html", "blog/own-1.html", "blog/own-2.html",
              "blog/own-3.html", "404.html"]
ORLA_POSTS = ["blog/post-1.html", "blog/post-2.html", "blog/post-3.html"]
OWN_POSTS = ["blog/own-1.html", "blog/own-2.html", "blog/own-3.html"]   # starter posts: shown only with a profile
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
        roles: [...document.querySelectorAll('.ba .phone')].map(p => p.getAttribute('role') + ':' + /^Illustration/.test(p.getAttribute('aria-label'))),
        hidden: [...document.querySelectorAll('.ba .phone-screen')].map(s => s.getAttribute('aria-hidden')), hint: !!document.querySelector('.ba-hint'),
        band: [document.querySelector('.phone-free').getAttribute('role'), document.querySelectorAll('.phone-free a').length, document.querySelectorAll('#mp-free-images .m-illus .gi-card').length],
        lav: [...document.querySelectorAll('.report-card .report-rows .lav')].map(e => e.textContent)})""")
    check(f"{tag} no slug: phones = labelled illustrations (groups: their tabs are buttons), rows not links, no tap hint", static["links"] == 0
          and static["roles"] == ["group:true", "group:true"] and static["hidden"] == [None, None] and not static["hint"], static)
    check(f"{tag} no slug: #free phone = static illustration (9 blurred tiles, no links), hero rows = letter avatars",
          static["band"] == ["group", 0, 9] and static["lav"] == ["L", "F", "P", "F"], static)
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
    lav = page.eval_on_selector_all('.ba [data-p^="leak-"] .fav', "els => els.map(e => [e.textContent, getComputedStyle(e).backgroundColor])")
    check(f"{tag} before phone: leak rows get letter avatars like the hero card", [l[0] for l in lav] == [d[0].upper() for d in TOP]
          and all(l[1] != "rgb(215, 210, 204)" for l in lav), lav)
    page.locator("#showcase .ba").screenshot(path=str(out / f"{vp_name}-p2-before-after.png"))
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
    check(f"{tag} phones: row hover = tint + underlined title + pointer (desktop; touch: no sticky tint)", bool(hov) and hov[2] == "pointer" and (
          (hov[0] != "rgba(0, 0, 0, 0)" and hov[1] == "underline") if page.evaluate("matchMedia('(hover: hover)').matches") else (hov[0] == "rgba(0, 0, 0, 0)" and hov[1] == "none")), hov)
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
    page.wait_for_timeout(400)   # last batch's photos preload + fade
    alts = page.eval_on_selector_all("img[data-p-src]", "els => [...new Set(els.map(e => e.alt))]")
    tots = {a.rsplit(" of ", 1)[-1] for a in alts}
    check(f"{tag} profile: media alts tell the photos apart ('<name>, photo n of N', one N for all after batches)", len(alts) >= 4
          and all(re.fullmatch(re.escape(PROFILE["display_name"]) + r", photo \d of \d", a) for a in alts) and len(tots) == 1, alts)
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
    check(f"{tag} profile: same-origin relative media srcs accepted, loaded via the API base", rel == [f"{API}/api/media/{FX['slug']}/0.jpg", 1067], rel)
    ctx.close()
    # VPS layout: site served by the API container (no data-api → API = ''), backend emits srcs on the production scan
    # host (its PUBLIC_ORIGIN). They must pass and load from the page's own origin; the scan host is never requested.
    # Bypass (declared): the showcase HTML's injected data-api is stripped on the wire, so the page runs with API = ''.
    stub_media(FX["slug"], "scanhost")
    ctx = new_ctx()
    page = ctx.new_page()
    page.route(re.compile(r"/showcase/(\?.*)?$"), lambda r: r.fulfill(response=(res := r.fetch()),
               body=re.sub(r' data-api="[^"]*"', "", res.text(), count=1)))
    n_out = len(net["outside"])
    page.goto(base + "showcase/?r=" + FX["slug"], wait_until="load")
    try:
        page.wait_for_function("() => [...document.querySelectorAll('img[data-p-media]')].every(e => /\\/api\\/media\\//.test(e.getAttribute('src')))", timeout=12000)
        page.locator("[data-p-gallery]").scroll_into_view_if_needed()
        page.wait_for_function("() => [...document.querySelectorAll('img[data-p-media]')].every(e => e.complete && e.naturalWidth > 0)", timeout=6000)
    except Exception:
        pass
    sh = page.evaluate("""() => ({api: document.body.getAttribute('data-api'), origin: location.origin,
      hero: [document.querySelector('img.hero__bg').getAttribute('src'), document.querySelector('img.hero__bg').src, document.querySelector('img.hero__bg').naturalWidth],
      slots: [...document.querySelectorAll('img[data-p-media]')].map(e => [e.getAttribute('src'), e.naturalWidth])})""")
    rx = re.escape(f"/api/media/{FX['slug']}/") + r"\d+\.jpg"
    check(f"{tag} profile: scan-host media srcs (VPS, API ''): page runs same-origin (no data-api)", sh["api"] is None, sh["api"])
    check(f"{tag} profile: scan-host media srcs: all 6 slots swapped, loaded", len(sh["slots"]) == 6
          and all(re.fullmatch(rx, s[0]) and s[1] > 0 for s in sh["slots"]), sh["slots"])
    check(f"{tag} profile: scan-host media srcs: hero = <API>/api/media/<slug>/<n>.jpg on the local stub",
          re.fullmatch(rx, sh["hero"][0]) is not None and sh["hero"][1] == sh["origin"] + sh["hero"][0] and sh["hero"][2] == 1067, sh["hero"])
    scan_reqs = [u for u in net["outside"][n_out:] if urlsplit(u).hostname == "scan.srv1395798.hstgr.cloud"]
    check(f"{tag} profile: scan-host media srcs: 0 requests to the scan host", not scan_reqs, scan_reqs)
    page.wait_for_timeout(700)
    page.screenshot(path=str(out / f"{vp_name}-p5b-demo-media-scanhost.png"))
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

    # E2. blog: no profile → Orla's 3 posts exactly as before; profile → the 3 starter posts in her name (cards + pages)
    cards = ("() => [...document.querySelectorAll('.blog-card')].filter(c => c.offsetParent !== null)"
             ".map(c => c.querySelector('a.blog-card__link').getAttribute('href'))")
    ctx = new_ctx()
    page = ctx.new_page()
    seen = {}
    for q in ("", "?r=demoNoProf01"):
        page.goto(base + "showcase/blog.html" + q, wait_until="load")
        page.wait_for_timeout(1500)
        seen[q] = (page.evaluate(cards), page.evaluate("document.body.innerText"), page.title())
        check(f"{tag} blog {q or 'no slug'}: Orla's 3 posts, no starter cards", seen[q][0] == ORLA_POSTS
              and "Orla" in seen[q][2], seen[q][0])
    check(f"{tag} blog: scan-only page text identical to no slug", seen[""][1] == seen["?r=demoNoProf01"][1])
    stub_media(FX["slug"])
    page.goto(base + "showcase/blog.html?r=" + FX["slug"], wait_until="load")
    try:
        page.wait_for_function(f"() => document.title.includes({json.dumps(name)})", timeout=6000)
    except Exception:
        pass
    hrefs = page.evaluate(cards)
    t = page.evaluate("document.body.innerText")
    check(f"{tag} profile: blog: 3 starter cards (?r= kept), Orla's hidden, no pottery / Orla, setup note",
          [urlsplit(h).path.split("/showcase/")[-1] for h in hrefs] == OWN_POSTS
          and all(f"r={FX['slug']}" in h for h in hrefs) and not POTTERY.search(t + page.title())
          and f"Prewritten for {PROFILE['first_name']}" in t, (hrefs, POTTERY.findall(t)[:6]))
    page.screenshot(path=str(out / f"{vp_name}-p8-blog.png"), full_page=True)
    for i, href in enumerate(hrefs):
        title = page.evaluate(f"() => [...document.querySelectorAll('.blog-card')].filter(c => c.offsetParent !== null)[{i}]"
                              ".querySelector('.blog-card__title').textContent.trim()")
        page.goto(href, wait_until="load")
        try:
            page.wait_for_function("() => [...document.querySelectorAll('img[data-p-media]')].every(i => (i.getAttribute('src') || '').includes('/api/media/') && i.complete && i.naturalWidth > 0)", timeout=15000)
        except Exception:
            pass
        rel = OWN_POSTS[i] if i < len(OWN_POSTS) else href
        pt = page.evaluate("document.body.innerText")
        body = page.locator("article.post-body").inner_text()
        st = page.evaluate("""() => ({h1: document.querySelector('h1').textContent.trim(),
            author: document.querySelector('.post-meta__author').textContent.trim(),
            media: [...document.querySelectorAll('img[data-p-media]')].map(i => [(i.getAttribute('src') || '').includes('/api/media/'), getComputedStyle(i.closest('[data-p-media-only]') || i).display !== 'none']),
            links: [...document.querySelectorAll('article a[href]')].map(a => a.getAttribute('href'))})""")
        check(f"{tag} profile: {rel}: title + author = her name, ≥ 350 words, photos from the API, ?r= kept, no pottery / Orla / she",
              st["h1"] == title and name in page.title() and st["author"] == name and len(body.split()) >= 350
              and st["media"] == [[True, True], [True, True]] and st["links"] and all(f"r={FX['slug']}" in h for h in st["links"])
              and not POTTERY.search(pt + page.title()) and not PRONOUN.search(pt),
              (st["h1"], st["author"], len(body.split()), st["media"], POTTERY.findall(pt)[:4], PRONOUN.findall(pt)[:4]))
        page.screenshot(path=str(out / f"{vp_name}-p8-{rel.replace('/', '-').removesuffix('.html')}.png"), full_page=True)
        page.goto(base + "showcase/blog.html?r=" + FX["slug"], wait_until="load")
        page.wait_for_function(f"() => document.title.includes({json.dumps(name)})", timeout=6000)
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

    def click_L():   # hidden over the hero (phone), the report card's actions or the phones (any width): scroll to where it shows
        shown = "(() => { const L = document.querySelector('.askai-launcher'), c = L.classList; return !c.contains('in-quiet') && !(c.contains('in-hero') && innerWidth < 720) && getComputedStyle(L).opacity === '1'; })()"
        for sec in (None, "how", "pricing", "faq"):
            if sec:
                page.evaluate(f"document.getElementById('{sec}').scrollIntoView({{behavior: 'instant'}})")
            page.wait_for_timeout(450)   # IntersectionObserver / rAF + the pill's fade settle
            if page.evaluate(shown):
                break
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
def thumb_paint(pw, vp_name, vp):
    """Row thumbs under reduced motion, as a visitor sees them: a fresh browser, three plain scans one after another (no e2e hooks),
    scrolled the moment the report lands. Each thumb: neutral tile under it, opacity 1 at once, photo painted in a plain viewport
    screenshot (an async-decoded thumb once stayed an empty slot here, from the 2nd context on)."""
    b = pw.chromium.launch()
    runs = []
    for n in range(3):
        ctx = b.new_context(viewport=vp, device_scale_factor=2 if vp_name == "phone" else 1, is_mobile=vp_name == "phone",
                            has_touch=vp_name == "phone", reduced_motion="reduce")
        ctx.route("**/*", lambda r, _q: r.continue_() if urlsplit(r.request.url).hostname in ("127.0.0.1", "localhost") else r.abort())
        page = ctx.new_page()
        page.goto(f"http://127.0.0.1:{port}/", wait_until="load")
        page.wait_for_timeout(500)
        page.locator("#scan input[name=h]").fill("@demo.creator")
        btn = page.locator("#scan button[type=submit]")
        btn.tap() if vp_name == "phone" else btn.click()
        page.wait_for_function("() => { const c = document.querySelector('.report-card'); return c && !c.hasAttribute('aria-busy') && c.querySelector('.live-rows'); }", timeout=15000)
        page.evaluate("document.querySelector('.report-card .live-strip-box').scrollIntoView({block: 'center', behavior: 'instant'})")
        page.wait_for_timeout(3000)
        st = page.evaluate("""() => [...document.querySelectorAll('.report-card .live-rows .live-ico')].map(e => { const i = e.querySelector('img'), r = e.getBoundingClientRect();
          return [getComputedStyle(e).backgroundColor, i ? getComputedStyle(i).opacity : null, i ? i.complete && i.naturalWidth > 0 : null, [r.x + 4, r.y + 4, r.width - 8, r.height - 8]]; })""")
        png = page.screenshot()
        (out / f"{vp_name}-t{n}-rows-reduced-motion.png").write_bytes(png)
        shot = base64.b64encode(png).decode()
        for x in st:
            x[3] = page.evaluate(PIX_SD, [shot, x[3]]) if x[1] is not None else None
        runs.append(st)
        ctx.close()
    b.close()
    bad = [[n, k, x] for n, st in enumerate(runs) for k, x in enumerate(st)
           if x[1] is not None and (x[0] in ("rgba(0, 0, 0, 0)", "transparent") or x[1] != "1" or not x[2] or x[3] < 6)]
    check(f"{vp_name} inline hero: reduced motion, 3 fresh scans → every row thumb on a neutral tile, opacity 1 at once, photo painted (no empty slot)",
          all(len(st) == 5 for st in runs) and not bad, bad or [[x[3] for x in st] for st in runs])


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
        ctx.add_init_script("window.__anim = []; const _a = Element.prototype.animate; Element.prototype.animate = function (k, o) { if (this.classList && this.classList.contains('report-card')) window.__anim.push([k, o && o.duration]); return _a.apply(this, arguments); };")
        ctx.add_init_script("window.__ls = []; try { new PerformanceObserver(l => l.getEntries().forEach(e => window.__ls.push([e.startTime, e.value, e.hadRecentInput]))).observe({type: 'layout-shift', buffered: true}); } catch (e) {}")

        def route(r, _req):
            u = r.request.url
            if urlsplit(u).hostname in ("127.0.0.1", "localhost"):
                if "/api/thumb" in u and DEAD_THUMB in unquote(u):   # fault at the wire: one Google thumb is gone (404)
                    return r.fulfill(status=404, body="")
                r.continue_()
            else:
                net["outside"].append(u)
                r.abort()
        ctx.route("**/*", route)
        break_routes(ctx)

        def on_page(pg):
            pg.on("pageerror", lambda e: net["errors"].append(str(e)))
            # the browser logs each provoked 429 / 400 / aborted scan POST as "Failed to load resource": expected here
            pg.on("console", lambda m: m.type == "error" and urlsplit(m.location.get("url") or "").hostname not in FONT_HOSTS
                  and not (m.text.startswith("Failed to load resource") and ("/api/public-scan" in (m.location.get("url") or "")
                                                                             or DEAD_THUMB in unquote(m.location.get("url") or "")))
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
        const s = document.querySelector('.phone-free'), n = s.querySelector('[data-live=band-images] .m-n'), send = document.querySelector('[data-free-send]');
        return {live: s.classList.contains('is-live'), pill: n && n.textContent, label: s.getAttribute('aria-label'), role: s.getAttribute('role'),
          tiles: [...s.querySelectorAll('[data-live=band-images] a.gi-card')].map(a => [a.href, a.target, a.rel, a.querySelector('img') ? a.querySelector('img').src : null]),
          visible_illus: [...s.querySelectorAll('.m-illus .gi-card')].filter(e => e.offsetParent !== null).length,
          send: send.getAttribute('href'), h: Math.round(s.getBoundingClientRect().height)};
    }""")
    strip = lambda page: page.evaluate("""() => {
        const s = document.querySelector('.report-card .live-strip'), c = document.querySelector('.report-card').getBoundingClientRect();
        const pb = document.querySelector('.report-card .live-strip-pause');
        const tr = s && s.querySelector('.live-strip-track'), tx = tr ? new DOMMatrix(getComputedStyle(tr).transform).m41 : 0;
        return s && {x: Math.round(s.scrollLeft - tx), drift: s.getAttribute('data-drift'), card: [c.width, c.height], max: s.scrollWidth - s.clientWidth,
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
    fh = page.evaluate("Math.round(document.getElementById('free').getBoundingClientRect().height)")
    check(f"{tag} band: #free compact (<= 640 px desktop: the phone beside the copy / 1240 px phone: stacked)", fh <= (1240 if vp_name == "phone" else 640), fh)
    page.evaluate("scrollTo({top: 0, behavior: 'instant'})")
    page.wait_for_timeout(300)
    net["nav"].clear()
    lcol = lambda: page.evaluate("() => ['.scan-alt', '.assurances'].map(s => { const r = document.querySelector(s).getBoundingClientRect(); return Math.round(r.top + scrollY); })")
    lc0 = lcol()
    submit(page, "@demo.creator", "https://www.instagram.com/demo.ig/")
    page.wait_for_function("() => /step/.test((document.querySelector('.report-card .live-status') || {}).textContent || '')", timeout=5000)
    c = card(page)
    check(f"{tag} progress visible in the hero card", c["live"] and c["title"] == "@demo.creator" and "Searching Google, step" in c["status"]
          and page.locator(".report-card .live-status").is_visible() and page.locator("#scan button").is_disabled(), c["status"])
    check(f"{tag} second scan state: no stale rows while scanning", not c["rows"] and not ill(page)["live"])
    page.wait_for_timeout(400)   # bring()'s smooth scroll lands, the observer runs
    qz = page.evaluate("(() => { const c = document.querySelector('.askai-launcher').classList; return [c.contains('in-quiet') || (c.contains('in-hero') && innerWidth < 720), document.querySelector('.report-card').hasAttribute('aria-busy'), c.value]; })()")
    check(f"{tag} askai: launcher quiet while the scan runs (card skeleton on screen; phone: also hidden over the hero)", qz[:2] == [True, True], qz)
    shot(page, "2-progress", ".hero")
    check(f"{tag} body: onlyfans + handle + instagram from a pasted URL",
          net["bodies"] == [{"platform": "onlyfans.com", "handle": "demo.creator", "level": "low", "instagram": "demo.ig"}], net["bodies"])
    fv = page.evaluate("[document.querySelector('#scan [name=h]').value, document.querySelector('#scan [name=ig]').value]")
    check(f"{tag} form: a pasted URL / @name shows as the bare handle in the fields", fv == ["demo.creator", "demo.ig"], fv)

    # 2. settled hero card
    settled(page)
    page.wait_for_selector("[data-p=scanned]:not([hidden])", timeout=5000)
    lc1 = lcol()
    check(f"{tag} hero: the left column doesn't move when the result lands (scanned line takes the note's slot)", lc1 == lc0, (lc0, lc1))
    an = page.evaluate("window.__anim.map(a => [a[0].map(k => parseFloat(k.height)), a[1]])")
    hf = page.evaluate("document.querySelector('.report-card').offsetHeight")
    check(f"{tag} hero: the card eases twice, no snap: at Scan up to the skeleton (about the report's height), then to the result's exact height (~320 ms each)",
          len(an) == 2 and an[0][0][1] > an[0][0][0] + 200 and abs(an[1][0][1] - hf) <= 1 and abs(hf - an[0][0][1]) <= 0.15 * hf
          and all(200 <= a[1] <= 500 for a in an), [an, hf])
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
    try:
        page.wait_for_function("() => { const r = document.querySelector('.report-card .live-send').getBoundingClientRect(); return r.bottom <= innerHeight; }", timeout=2500)
    except Exception:
        pass
    page.wait_for_timeout(300)
    SETTLE = "() => { const pad = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0, c = document.querySelector('.report-card').getBoundingClientRect();" \
             " return [Math.round(c.top), Math.round(c.bottom), Math.round(document.querySelector('.report-card .live-send').getBoundingClientRect().bottom), innerHeight, Math.round(pad)]; }"
    # phone: a compact "Open full report" beside the count chip, in view after the result, same href as the main button, no taller head
    top = page.evaluate("""() => { const t = document.querySelector('.report-card .live-open-top'), c = document.querySelector('.report-card .live-count'),
        h = document.querySelector('.report-card .report-head'), o = document.querySelector('.report-card .live-open');
      const vis = !!t && getComputedStyle(t).display !== 'none', r = t && t.getBoundingClientRect(), cr = c.getBoundingClientRect(), h1 = h.offsetHeight;
      let h0 = h1; if (t) { t.hidden = true; h0 = h.offsetHeight; t.hidden = false; }
      return {vis, same: !!t && !!o && t.getAttribute('href') === o.getAttribute('href'), row: vis ? Math.abs((r.top + r.bottom) / 2 - (cr.top + cr.bottom) / 2) <= 4 : null,
        inview: vis ? r.top >= 0 && r.bottom <= innerHeight : null, grow: h1 - h0, open: o.getBoundingClientRect().bottom > innerHeight}; }""")
    if vp_name == "phone":
        check(f"{tag} hero: phone: 'Open full report' also beside the count chip (same href, same row, in view, head no taller)",
              top["vis"] and top["same"] and top["row"] and top["inview"] and top["grow"] == 0, top)
    else:
        check(f"{tag} hero: desktop: no second 'Open full report' in the card head (the main button is in view)", not top["vis"] and not top["open"], top)
    if vp_name == "desktop":   # phone: the report is taller than the screen; its title stays in view, the buttons are a scroll away
        st = page.evaluate(SETTLE)
        check(f"{tag} hero: settled at 1440x900: the whole card in view, its top not under the sticky nav", st[0] >= st[4] - 1 and st[1] <= st[3], st)
        lctx = new_ctx()   # a 1440x800 laptop (own context: this page's localStorage stays as it is): same, the Send buttons included
        lp = lctx.new_page()
        lp.set_viewport_size({"width": 1440, "height": 800})
        lp.goto(base, wait_until="load")
        lp.wait_for_timeout(300)
        submit(lp, "@demo.creator", "demo.ig")
        settled(lp)
        lp.wait_for_timeout(1500)   # the ease + the smooth scroll
        st = lp.evaluate(SETTLE)
        check(f"{tag} hero: settled at 1440x800: card top not under the sticky nav, whole card + Send buttons above the fold", st[0] >= st[4] - 1 and st[1] <= st[3] and st[2] <= st[3], st)
        lp.screenshot(path=str(out / f"{vp_name}-i2s-settled-1440x800.png"))
        lctx.close()
    IM = _images(FX, alive=True, extra=(DEAD_THUMB,))   # the 404 thumb (DEAD_THUMB) is dropped by gallery(): not a tile, not counted
    NI = len(IM)
    tile_href = lambda it: it[1] or base + "scan/?r=" + slug
    want_tiles = lambda k: [[tile_href(it), "_blank" if it[1] else "", "noopener noreferrer nofollow" if it[1] else "",
                             API + "/api/thumb?u=" + quote(it[0], safe="")] for it in (_band(FX, IM) if k == 9 else IM[:k])]
    i = ill(page)
    check(f"{tag} thumbs: band: #free phone Images tab = her first 9 image results (link → result in a new tab, else the report)",
          i["live"] and i["pill"] == f"{NI} images" and i["visible_illus"] == 0 and i["role"] == "group"
          and [t[:3] + [t[3]] for t in i["tiles"]] == want_tiles(9), i)
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
          sites: q('.live-sites li:not([hidden]) a.live-link').map(a => [a.href, a.target, a.rel])};
    }""")
    sites = _sites(rows)
    check(f"{tag} thumbs: hero: tabs Links / Images / Sites with the fixture's counts, Links selected",
          hero["tabs"] == [["lt-links", f"Links{N}", "true", 0], ["lt-images", f"Images{NI}", "false", -1], ["lt-sites", f"Sites{FX['domain_count']}", "false", -1]]
          and [p[1:] for p in hero["panels"]] == [[True, "visible"], [False, "hidden"], [False, "hidden"]], hero["tabs"])
    check(f"{tag} hero: rows >= 44px with a letter avatar / blurred site thumb each", hero["rowH"] >= 44 and hero["ico"] == 5, hero["rowH"])
    check(f"{tag} thumbs: hero: strip 'What Google Images shows for @demo.creator' = first 24 images, blurred, link → result / report",
          hero["stripH"] == "What Google Images shows for @demo.creator" and hero["strip"] == want_tiles(24) and "blur" in hero["blur"], hero["strip"][:3])
    by_dom = {}
    for d, _t, u, _b in rows:
        by_dom.setdefault(d, u)
    ns = len(hero["sites"])
    check(f"{tag} hero: Sites tab = the top sites (6-12, as many as fit), each opens its first link in a new tab", 6 <= ns <= 12 and
          hero["sites"] == [[by_dom[d], "_blank", "noopener noreferrer nofollow"] for d in [x[0] for x in sorted(_site_counts(rows), key=lambda x: -x[1])][:ns]], hero["sites"])
    sg = page.evaluate("""() => { const p = document.querySelector('#lp-sites'), ul = p.querySelector('ul'), m = p.querySelector('.live-more'), others = [...document.querySelectorAll('.report-card .live-panel:not(#lp-sites)')];
        const nat = e => e.lastElementChild.getBoundingClientRect().bottom - e.getBoundingClientRect().top;
        const lastRow = [...ul.children].filter(li => !li.hidden).pop();
        return {gap: Math.round(m.getBoundingClientRect().top - lastRow.getBoundingClientRect().bottom), clip: Math.round(lastRow.getBoundingClientRect().bottom - ul.getBoundingClientRect().bottom), more: m.textContent, href: m.getAttribute('href'),
          grew: Math.round(nat(p) - Math.max(...others.map(nat))), card: [document.querySelector('.report-card').getBoundingClientRect().width, document.querySelector('.hero-grid').clientWidth]}; }""")
    nsites = len(_site_counts(rows))
    check(f"{tag} hero: Sites panel has no empty band ('+N more sites' link at its foot, gap < one row, last row whole, card not taller for it)", sg["gap"] < 52 + 12 and sg["clip"] <= 4
          and sg["grew"] <= 0 and sg["more"] == f"+ {nsites - ns} more sites in the full report" and sg["href"] == "scan/?r=" + slug, sg)
    cw = page.evaluate("[document.querySelector('.report-card').getBoundingClientRect().right, document.querySelector('.hero-grid').getBoundingClientRect().right - parseFloat(getComputedStyle(document.querySelector('.hero-grid')).paddingRight)]")
    check(f"{tag} hero: the card fits its column (no overflow into the gutter)", cw[0] <= cw[1] + 0.5, cw)
    # tabs switch the body without moving anything; Reveal unblurs
    cbox = lambda: page.evaluate("() => { const r = document.querySelector('.report-card').getBoundingClientRect(), d = document.documentElement.getBoundingClientRect(); return [Math.round(r.x - d.x), Math.round(r.y - d.y), r.width, r.height]; }")
    page.wait_for_function("() => !document.querySelector('.report-card').getAnimations().length", timeout=3000)   # the card's height ease
    card0 = cbox()
    page.locator("#lt-images").click()
    page.wait_for_timeout(350)
    gi = page.evaluate("() => [document.querySelector('#lp-images').classList.contains('on'), getComputedStyle(document.querySelector('#lp-links')).visibility, document.querySelectorAll('#lp-images .live-grid a.gi-card').length, (document.querySelector('#lp-images .live-more') || {}).textContent]")
    card1 = cbox()
    G = 12 if vp_name == "phone" else 16
    check(f"{tag} thumbs: hero: Images tab shows the image grid (phone 12, else 16) in place (card box unchanged)", gi == [True, "hidden", G, f"+ {NI - G} more in the full report"]
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
        page.wait_for_function("() => { const s = document.querySelector('.report-card .live-strip'), t = s && s.querySelector('.live-strip-track'); return s && s.scrollLeft - new DOMMatrix(getComputedStyle(t).transform).m41 > 4; }", timeout=9000)
    except Exception:
        pass
    a0 = strip(page)
    page.locator(".report-card .live-strip-box").screenshot(path=str(out / f"{vp_name}-i3d-strip-t0.png"))
    page.wait_for_timeout(2000)
    a1 = strip(page)
    page.locator(".report-card .live-strip-box").screenshot(path=str(out / f"{vp_name}-i3d-strip-t2.png"))
    check(f"{tag} drift: idle → the strip scrolls by itself (rAF), ~24 px/s", a0["drift"] == "on" and 20 <= a1["x"] - a0["x"] <= 90, (a0["x"], a1["x"]))
    sm = page.evaluate("""() => new Promise(done => { const t = document.querySelector('.report-card .live-strip-track'), xs = [];
        const f = () => { xs.push(new DOMMatrix(getComputedStyle(t).transform).m41); if (xs.length < 40) requestAnimationFrame(f); else done(xs); }; requestAnimationFrame(f); })""")
    moved = sum(1 for a, b in zip(sm, sm[1:]) if a != b)
    check(f"{tag} drift: smooth, the track moves (translate3d, sub-pixel) on almost every frame, scrollLeft untouched", moved >= 30
          and any(x != round(x) for x in sm), (moved, sm[:4]))
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
    # tiles: a light placeholder in the light theme (no black flash), faded in once loaded; the #free frame stays Google-dark
    tl = page.evaluate("""() => { const lum = e => { const m = getComputedStyle(e).backgroundImage.match(/rgba?\\(([^)]+)\\)/); if (!m) return null;
        const [r, g, b] = m[1].split(',').map(parseFloat); return Math.round(.2126 * r + .7152 * g + .0722 * b); };
        return {card: lum(document.querySelector('.report-card .gi-box')), band: lum(document.querySelector('.phone-free .gi-box')),
          waiting: [...document.querySelectorAll('.report-card .live-strip .gi-wait img')].filter(i => i.complete && i.naturalWidth).length,
          loaded: [...document.querySelectorAll('.report-card .live-strip .gi-box:not(.gi-wait) img')].filter(i => i.complete && i.naturalWidth).length, fade: getComputedStyle(document.querySelector('.report-card .gi-img')).transitionProperty}; }""")
    check(f"{tag} tiles: light placeholder in the light theme (the #free phone's screen too), images fade in on load", tl["card"] is not None and tl["card"] > 150
          and tl["band"] is not None and tl["band"] > 150 and tl["waiting"] == 0 and tl["loaded"] >= 3 and "opacity" in tl["fade"], tl)
    # a row whose thumb failed: neutral letter on the theme surface (no bright hue among the blurred thumbs)
    fb = page.evaluate("""() => { const s2 = getComputedStyle(document.documentElement).getPropertyValue('--surface-2').trim(), probe = document.createElement('i');
        probe.style.background = s2; document.body.appendChild(probe); const want = getComputedStyle(probe).backgroundColor; probe.remove();
        const lone = [...document.querySelectorAll('.report-card .live-ico')].filter(e => !e.querySelector('img'));
        return {n: lone.length, ok: lone.every(e => e.classList.contains('fav-none') && getComputedStyle(e).backgroundColor === want), bg: lone.map(e => getComputedStyle(e).backgroundColor), want,
          hue: [...document.querySelectorAll('.report-card .live-ico')].filter(e => e.style.background).length}; }""")
    check(f"{tag} hero: a failed row thumb falls back to a neutral theme-coloured letter; no letter hue anywhere in the card (neutral while thumbs load)", fb["n"] >= 1 and fb["ok"] and fb["hue"] == 0, fb)
    # hover looks only where there is hover (a tap leaves nothing tinted)
    page.locator(".report-card .live-link").first.hover()
    page.wait_for_timeout(250)
    hv = page.evaluate("getComputedStyle(document.querySelector('.report-card .live-link')).backgroundColor")
    hov = page.evaluate("matchMedia('(hover: hover)').matches")   # Playwright's screenshots flip a touch context to hover: ask the page
    bare = page.evaluate(BARE_HOVER)
    check(f"{tag} hero: row hover tint only where hover exists (phone: none after a tap; no :hover rule, a:hover included, outside @media (hover: hover))", (hv == "rgba(0, 0, 0, 0)") == (not hov) and not bare, [hv, hov, bare])
    page.mouse.move(0, 0)
    # the Ask AI pill never sits on the card's actions or on the before / after phones
    def pill_clear(sel):
        page.evaluate(f"document.querySelector('{sel}').scrollIntoView({{block: 'end', behavior: 'instant'}})")
        page.wait_for_timeout(600)
        return page.evaluate(f"""() => {{ const L = document.querySelector('.askai-launcher'), b = L.getBoundingClientRect(), r = document.querySelector('{sel}').getBoundingClientRect();
            const over = r.right > b.left && r.left < b.right && r.bottom > b.top && r.top < b.bottom;
            return [over, getComputedStyle(L).visibility]; }}""")
    if vp_name == "phone":   # the sticky "Free scan" bar steps aside while the showcase preview is behind it, and is back after
        page.evaluate("document.querySelector('#showcase .browser-demo').scrollIntoView({block: 'center', behavior: 'instant'})")
        page.wait_for_timeout(500)
        on_demo = page.evaluate("document.querySelector('.mobile-cta').classList.contains('show')")
        page.evaluate("document.getElementById('pricing').scrollIntoView({behavior: 'instant'})")
        page.wait_for_timeout(500)
        on_pricing = page.evaluate("document.querySelector('.mobile-cta').classList.contains('show')")
        check(f"{tag} sticky scan bar: hidden over the showcase preview, shown again past it", not on_demo and on_pricing, [on_demo, on_pricing])
    pa, pb, ps = pill_clear(".report-card .live-actions"), pill_clear(".ba"), pill_clear("#showcase .browser-demo")
    check(f"{tag} askai: launcher hidden while it would cover the card's actions / the phones / the showcase preview", all(not o or v == "hidden" for o, v in (pa, pb, ps))
          and (pa[0] or pb[0]) and (ps[0] or vp_name != "phone"), (pa, pb, ps))
    page.evaluate("scrollTo({top: 0, behavior: 'instant'})")
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
    page.locator("#showcase .ba").scroll_into_view_if_needed()
    page.wait_for_timeout(700)
    shot(page, "5-phones", "#showcase .ba")

    # 3. reload with ?r= restores the hero card, no new scan
    n_posts = len(net["bodies"])
    page.reload(wait_until="load")
    try:
        page.wait_for_selector(".report-card .live-rows li", timeout=6000)
    except Exception:
        pass
    c2 = card(page)
    check(f"{tag} thumbs: reload ?r= restores hero card (rows, count, socials), no new scan", c2["rows"] == c["rows"] and c2["count"] == c["count"]
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

    # 7c. a shared ?r= link in a fresh browser: ONE /api/scan-result request (inline-scan.js + personalize.js share it);
    # phone: the card (below the hero text) is brought under the nav; desktop: it is already in view, no scroll;
    # ?r=…#website: the anchor wins, the card is not brought
    ctx = new_ctx()
    page = ctx.new_page()
    reqs = []
    page.on("request", lambda q: "/api/scan-result/" in q.url and reqs.append(q.url))
    page.goto(base + "?r=" + slug, wait_until="load")
    try:
        page.wait_for_selector(".report-card .live-rows li", timeout=8000)
        page.wait_for_function("() => document.querySelector('[data-p=search]').textContent !== 'yourname'", timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(1500)   # personalize.js has applied too (smooth scroll settled)
    pos = page.evaluate("() => { const r = document.querySelector('.report-card').getBoundingClientRect(); return {top: Math.round(r.top), y: Math.round(scrollY), ih: innerHeight, pad: parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0, name: document.querySelector('[data-p=search]').textContent}; }")
    check(f"{tag} shared ?r= link: one /api/scan-result request (hero card + personalize share it)", len(reqs) == 1 and pos["name"] != "yourname", (len(reqs), pos["name"]))
    if vp_name == "phone":
        check(f"{tag} shared ?r= link: phone scrolls the report card up under the nav", pos["y"] > 0 and pos["pad"] - 2 <= pos["top"] <= pos["pad"] + 40, pos)
    else:
        check(f"{tag} shared ?r= link: desktop card already in view, page not scrolled", pos["y"] == 0 and 0 <= pos["top"] < pos["ih"] - 200, pos)
    page.screenshot(path=str(out / f"{vp_name}-i3e-shared-link.png"))
    ctx.close()
    ctx = new_ctx()
    page = ctx.new_page()
    page.goto(base + "?r=" + slug + "#website", wait_until="load")
    try:
        page.wait_for_selector(".report-card .live-rows li", timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(1500)
    pos = page.evaluate("() => { const c = document.querySelector('.report-card').getBoundingClientRect(), w = document.getElementById('website').getBoundingClientRect(); return {card: Math.round(c.top), website: Math.round(w.top), ih: innerHeight}; }")
    check(f"{tag} shared ?r=…#website link: no jump to the card", not (0 <= pos["card"] < pos["ih"]) and pos["website"] < pos["ih"], pos)
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


def tabs_flow(browser, vp_name, vp):
    tag = f"{vp_name} tabs"
    net = {"outside": [], "errors": [], "console": []}
    sys.path.insert(0, str(ROOT / "tools"))
    import importlib
    stubmod = importlib.import_module("scan_stub")
    BROKEN = stubmod.broken_thumbs(FX)
    m = MEASURED.setdefault(vp_name, {})

    def new_ctx(motion="no-preference"):
        ctx = browser.new_context(viewport=vp, device_scale_factor=2 if vp_name == "phone" else 1, is_mobile=vp_name == "phone",
                                  has_touch=vp_name == "phone", reduced_motion=motion)
        ctx.add_init_script("window.__ls = []; try { new PerformanceObserver(l => l.getEntries().forEach(e => window.__ls.push([e.startTime, e.value, e.hadRecentInput, (e.sources || []).map(s => s.node && s.node.nodeType === 1 ? s.node.tagName + '.' + s.node.className + ' ' + [s.previousRect.y, s.currentRect.y, s.previousRect.height, s.currentRect.height].map(Math.round) : '#text')]))).observe({type: 'layout-shift', buffered: true}); } catch (e) {}")

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
            pg.on("console", lambda msg: msg.type == "error" and urlsplit(msg.location.get("url") or "").hostname not in FONT_HOSTS
                  and not (msg.text.startswith("Failed to load resource") and "DEAD" in unquote(msg.location.get("url") or ""))
                  and net["console"].append(msg.text + " @ " + (msg.location.get("url") or "")))
        ctx.on("page", on_page)
        return ctx

    shot = lambda page, name, el=None: (page.locator(el) if el else page).screenshot(path=str(out / f"{vp_name}-t{name}.png"))
    overflow = lambda page: page.evaluate("""() => ({doc: document.documentElement.scrollWidth, vw: innerWidth,
        wide: [...document.querySelectorAll('.phone, .browser-demo, .report-card, .free-band, .ba')].filter(e => { const r = e.getBoundingClientRect(); return r.width && (r.left < -0.5 || r.right > innerWidth + 0.5); }).map(e => e.className)})""")

    # ---------- (1) report card: broken thumbs leave, counts follow ----------
    E = _images(BROKEN)                # what the client lists before any probe (video still already skipped)
    A = _images(BROKEN, alive=True)    # what shows once the 404 / blank ones are dropped
    AS = _scan_images(BROKEN, alive=True)   # the scan page's list (video stills included)
    vids = {r["thumb"] for r in BROKEN["results"] if r.get("kind") == "video" and r.get("thumb")}
    G = 12 if vp_name == "phone" else 16
    ctx = new_ctx()
    page = ctx.new_page()
    page.goto(base + "?r=demoBrokenT1", wait_until="load")
    page.wait_for_selector(".report-card #lt-images", timeout=8000)
    page.wait_for_timeout(1500)   # probes answered
    page.evaluate("document.querySelector('.report-card').scrollIntoView({block: 'start', behavior: 'instant'})")
    page.locator("#lt-images").click()
    page.wait_for_timeout(1200)
    st = page.evaluate("""() => { const c = document.querySelector('.report-card'), src = a => decodeURIComponent((a.querySelector('img').getAttribute('src').split('u=')[1]) || '');
        const tiles = sel => [...c.querySelectorAll(sel)].map(src);
        return {grid: tiles('#lp-images .live-grid a.gi-card'), strip: tiles('.live-strip a.gi-card'), label: c.querySelector('.live-imgs-head p').textContent,
          tab: c.querySelector('#lt-images .live-tab-n').textContent, more: (m => m && !m.hidden ? m.textContent : null)(c.querySelector('#lp-images .live-more')),
          painted: [...c.querySelectorAll('#lp-images .live-grid img')].map(i => i.complete && i.naturalWidth >= 16 && getComputedStyle(i).opacity === '1'),
          gaps: (g => { const r = [...g.children].map(e => e.getBoundingClientRect()); return r.length ? [new Set(r.map(x => Math.round(x.left))).size, r.length] : null; })(c.querySelector('#lp-images .live-grid'))}; }""")
    m["report_images_listed"], m["report_images_shown"] = len(E), len(A)
    m["report_grid_tiles"] = len(st["grid"])
    check(f"{tag} thumbs: failed / blank thumbs dropped from the Images grid, next ones fill in (grid = first {G} that load)",
          st["grid"] == [x[0] for x in A[:G]] and not any(dead_thumb(u) for u in st["grid"] + st["strip"]), (len(E), len(A), st["grid"][:4]))
    check(f"{tag} thumbs: label / tab / '+N more' count what shows ({len(E)} listed → {len(A)} shown)",
          st["label"] == f"{len(A)} images on Google Images" and st["tab"] == str(len(A)) and st["more"] == (f"+ {len(A) - G} more in the full report" if len(A) > G else None), st)
    check(f"{tag} thumbs: every grid tile painted (loaded, >= 16 px, opacity 1), no empty square", len(st["painted"]) == min(G, len(A)) and all(st["painted"]), st["painted"])
    check(f"{tag} thumbs: strip = first 24 that load", st["strip"] == [x[0] for x in A[:24]], st["strip"][:3])
    vs = [u in vids for u in st["strip"]]
    check(f"{tag} videos: video stills only after every real image (strip; images[]' leading still moved back), none if photos fill it",
          any(u in vids for u in BROKEN["images"][:1]) and vs == sorted(vs) and st["strip"][:1] != BROKEN["images"][:1], [sum(vs), len(vs)])
    shot(page, "1-card-images-broken-removed", ".report-card")
    # #free band Videos rows: a logo still (no person photo) leaves its 16:9 box grey + play mark, the row stays
    page.locator("#free").scroll_into_view_if_needed()
    page.locator("#mt-free-videos").click()
    page.wait_for_timeout(1500)
    BV = [r for r in BROKEN["results"] if is_video(r)][:3]
    bv = page.evaluate("""() => [...document.querySelectorAll('[data-live=band-videos] a.m-link')].map(a => { const i = a.querySelector('.m-vthumb img');
        return [a.href, i ? (i.complete && i.naturalWidth >= 16) : null, !!a.querySelector('.m-vthumb .m-play')]; })""")
    check(f"{tag} videos: #free Videos rows: logo still dropped (grey box + play kept, row stays), the rest painted",
          [x[0] for x in bv] == [r["link"] for r in BV] and [x[1] for x in bv] == [None if dead_thumb(r.get("thumb") or "DEAD") else True for r in BV]
          and all(x[2] for x in bv) and any("LOGO" in (r.get("thumb") or "") for r in BV), bv)
    # the same report on the scan page: failed tiles leave its Images grid too
    ctx.close()
    ctx = new_ctx()
    page = ctx.new_page()
    page.goto(base + "scan/?r=demoBrokenT1", wait_until="load")
    page.wait_for_selector("#g-tab-images", timeout=8000)
    page.locator("#g-tab-images").click()
    page.wait_for_timeout(1500)
    sp = page.evaluate("() => [...document.querySelectorAll('.g-grid .g-tile img')].map(i => [decodeURIComponent(i.getAttribute('src').split('u=')[1]), i.complete && i.naturalWidth >= 16])")
    check(f"{tag} thumbs: scan page Images grid: failed / blank tiles removed, the rest painted", sp and all(ok for _u, ok in sp) and not any(dead_thumb(u) for u, _ok in sp), [u[-24:] for u, ok in sp if not ok][:4])
    page.locator("#g-tab-videos").click()
    page.wait_for_timeout(1500)
    VS = [r for r in BROKEN["results"] if r.get("kind") == "video"]
    sv = page.evaluate("() => [...document.querySelectorAll('#g-panel .g-v .g-vthumb')].map(a => { const i = a.querySelector('img'); return [a.href, i ? (i.complete && i.naturalWidth >= 16) : a.querySelector('.g-img-none') ? null : false]; })")
    check(f"{tag} videos: scan page Videos tab: logo still → grey box (row stays, count honest), the rest painted",
          [x[0] for x in sv] == [r["link"] for r in VS[:len(sv)]] and len(sv) == min(5 if vp_name == "phone" else 8, len(VS))
          and [x[1] for x in sv] == [None if dead_thumb(r.get("thumb") or "DEAD") else True for r in VS[:len(sv)]]
          and any("LOGO" in (r.get("thumb") or "") for r in VS[:len(sv)]), sv)
    ctx.close()
    if vp_name == "desktop":   # desktop Images: every thumb answers late (after the tab is up): same-size tiles, nothing moves
        ctx = new_ctx()
        page = ctx.new_page()
        held, hold = [], [True]   # held until the tab is up; later requests (spare tiles) pass
        page.route(lambda u: "/api/thumb" in u, lambda r: held.append(r) if hold[0] else r.continue_())
        page.goto(base + "scan/?r=demoBrokenT1", wait_until="load")
        page.wait_for_selector("#g-tab-images", timeout=8000)
        page.evaluate("document.getElementById('g-stage').scrollIntoView({block: 'start', behavior: 'instant'})")
        page.wait_for_timeout(300)
        t0, y0 = page.evaluate("() => { document.querySelector('#g-tab-images').click(); return [performance.now(), document.getElementById('sites').getBoundingClientRect().top]; }")
        page.wait_for_timeout(600)
        hold[0] = False
        while held:
            held.pop().continue_()
        page.wait_for_timeout(1800)
        d1 = page.evaluate("""(t0) => [document.getElementById('sites').getBoundingClientRect().top, document.querySelectorAll('.g-grid .g-tile img').length,
            [...document.querySelectorAll('.g-grid .g-tile img')].filter(i => i.complete && i.naturalWidth >= 16).length,
            window.__ls.filter(x => x[0] > t0 + 200 && x[1] > 0 && !x[2]).map(x => x[3])]""", t0)
        check(f"{tag} thumbs: desktop Images, thumbs answering late: tiles keep their size, the sections below stay put, no layout shift",
              d1[1] > 8 and d1[2] == d1[1] and abs(d1[0] - y0) < 1 and not d1[3], [y0] + d1[:3] + [d1[3][:2]])
        ctx.close()
    if vp_name == "phone":   # pinned phone: a failed tile's slot goes to the next image (same size), nothing moves
        ctx = new_ctx()
        page = ctx.new_page()
        held, hold = [], [True]   # the 404 / blank / logo thumbs answer late: after the Images tab is up (the All tab's strip would fail them first); later requests (a logo's pixel probe) pass
        page.route(lambda u: "/api/thumb" in u and dead_thumb(unquote(u)), lambda r: held.append(r) if hold[0] else r.continue_())
        page.goto(base + "scan/?r=demoBrokenT1", wait_until="load")
        page.wait_for_selector("#g-tab-images", timeout=8000)
        page.wait_for_timeout(800)
        t0, s0 = page.evaluate("""() => { document.querySelector('#g-tab-images').click();
            return [performance.now(), [...document.querySelectorAll('.g-grid .g-tile img')].map(i => decodeURIComponent(i.getAttribute('src').split('u=')[1]))]; }""")
        page.wait_for_timeout(800)
        hold[0] = False
        for r in held:
            r.continue_()
        page.wait_for_timeout(1500)
        s1 = page.evaluate("""(t0) => [[...document.querySelectorAll('.g-grid .g-tile img')].map(i => [decodeURIComponent(i.getAttribute('src').split('u=')[1]), i.complete && i.naturalWidth >= 16]),
            window.__ls.filter(x => x[0] > t0 + 200 && x[1] > 0 && !x[2]).map(x => x[3])]""", t0)
        # phone Images: first 12; a failed slot is taken by a spare image (else the last tile)
        d0 = next(i for i, u in enumerate(s0) if dead_thumb(u)) if any(dead_thumb(u) for u in s0) else -1
        check(f"{tag} thumbs: pinned phone Images: failed tiles' slots filled in place (spare image, else the last tile), every live image painted, tiles above untouched, no layout shift",
              d0 >= 0 and len(s1[0]) == (len(s0) if len(AS) > len(s0) else len(AS)) and all(ok for _u, ok in s1[0]) and [u for u, _ok in s1[0][:d0]] == s0[:d0]
              and not dead_thumb(s1[0][d0][0]) and not any(dead_thumb(u) for u, _ok in s1[0]) and not s1[1], [len(s0), len(AS), len(s1[0]), d0, s1[1][:2]])
        page.locator("#device input[value=computer]").check(force=True)
        page.wait_for_timeout(300)
        back = page.evaluate("() => [...document.querySelectorAll('#g-stage img')].map(i => decodeURIComponent(i.getAttribute('src').split('u=')[1] || ''))")
        check(f"{tag} thumbs: a device switch keeps failed thumbs out (Computer view lists none of them)", back and not any(dead_thumb(u) for u in back), [u[-24:] for u in back if dead_thumb(u)])
        ctx.close()
    # more than 80 Google results (the page list stops at 80): every result's thumb is still in the strip and the Images tab
    ctx = new_ctx()
    page = ctx.new_page()
    def many(r, _q):
        d = json.loads(r.fetch().text())
        d["results"] = d["results"] + [{"title": f"Extra page {k}", "link": f"https://extra{k}.example/p/{k}", "domain": f"extra{k}.example", "snippet": "x",
                                        "thumb": f"https://encrypted-tbn0.gstatic.com/images?q=tbn:EXTRA{k:04d}", "kind": "page"} for k in range(90)]
        many.pages = sum(x.get("kind") != "video" for x in d["results"][:80])
        many.n = len(_scan_images(d))
        r.fulfill(json=d)
    page.route("**/api/scan-result/demoR3port01", many)
    page.goto(base + "scan/?r=demoR3port01", wait_until="load")
    page.wait_for_selector("#report:not([hidden])", timeout=8000)
    strip_n = page.locator("#g-panel .g-strip > .g-pack-b").count()
    while page.locator("#g-panel [data-more=all]").count():
        page.locator("#g-panel [data-more=all]").click()
    pages_n = page.locator("#g-panel .g-r").count()
    page.locator("#g-tab-images").click()
    isteps = [page.locator("#g-panel .g-tile").count()]
    while page.locator("#g-panel [data-more=images]").count():
        page.locator("#g-panel [data-more=images]").click()
        isteps.append(page.locator("#g-panel .g-tile").count())
    tab_n = isteps[-1]
    i0 = 24 if vp_name == "desktop" else 12   # Images: desktop 24, phone 12; +24 per More
    check(f"{tag} thumbs: > 80 results: every result's thumb in the strip and the Images tab ({i0}, +24 per More; pages stay capped at 80)",
          strip_n == tab_n == many.n > 80 and pages_n == many.pages and isteps == [min(i0 + 24 * k, many.n) for k in range(len(isteps))], [strip_n, isteps, many.n, pages_n, many.pages])
    ctx.close()
    # a report that is mostly video results (real 2_YPj7TbK4rm shape): every unique thumb in the strip and the Images tab,
    # video results' stills with a play badge; images[] entries that share a video still stay image results. Fresh scan + reopen
    for how in ("scan/?h=stub-videos", "scan/?r=demoVideos01"):
        ctx = new_ctx()
        page = ctx.new_page()
        page.goto(base + how, wait_until="load")
        page.wait_for_selector("#report:not([hidden])", timeout=15000)
        page.wait_for_timeout(300)
        TILES = """(sel) => { const t = [...document.querySelectorAll(sel)];
            return [t.length, t.filter(e => e.querySelector('.g-vid')).length, t.map(e => decodeURIComponent(e.querySelector('img').getAttribute('src').split('u=')[1]))]; }"""
        sv = page.evaluate(TILES, "#g-panel .g-strip > .g-pack-b")
        badge = page.evaluate("() => { const e = document.querySelector('#g-panel .g-strip .g-vid'), b = e && getComputedStyle(e, '::after'); return b ? [b.content, b.width, b.position] : null; }") or [None] * 3
        page.locator("#g-tab-images").click()
        while page.locator("#g-panel [data-more=images]").count():
            page.locator("#g-panel [data-more=images]").click()
        iv = page.evaluate(TILES, "#g-panel .g-tile")
        if how.endswith("demoVideos01"):
            page.evaluate("document.querySelector('#g-panel .g-tile').scrollIntoView({block: 'start', behavior: 'instant'})")
            page.wait_for_timeout(500)
            shot(page, "v-videos-images-tab")
        page.locator("#g-tab-videos").click()
        vcount = lambda: page.locator("#g-panel .g-v").count()
        first, steps, kb = vcount(), [], None
        if how.endswith("demoVideos01"):
            page.wait_for_timeout(300)
            shot(page, "v-videos-first-look")
        if how.endswith("demoVideos01") and page.locator("#g-panel [data-more=videos]").count():   # keyboard Enter → +12, focus on the first new video
            page.locator("#g-panel [data-more=videos]").focus()
            page.keyboard.press("Enter")
            page.wait_for_timeout(300)
            kb = page.evaluate("() => { const v = [...document.querySelectorAll('#g-panel .g-v')]; return v.findIndex(e => e.contains(document.activeElement)); }")
            steps.append(vcount())
        names = set()
        while page.locator("#g-panel [data-more=videos]").count():
            names.add(page.locator("#g-panel [data-more=videos]").inner_text())
            page.locator("#g-panel [data-more=videos]").click()
            page.wait_for_timeout(100)
            steps.append(vcount())
        vn = vcount()
        if how.endswith("demoVideos01"):   # Show fewer: back to the first look, focus on Show more videos, in view
            if page.locator("#g-panel [data-less=videos]").count():
                names.add(page.locator("#g-panel [data-less=videos]").inner_text())
                page.locator("#g-panel [data-less=videos]").click()
                page.wait_for_timeout(300)
            fw = [vcount(), page.evaluate("document.activeElement.matches('[data-more=videos]')"), page.evaluate(IN_VIEW)]
            shot(page, "v-videos-show-fewer")
            f0 = 5 if vp_name == "phone" else 8
            check(f"{tag} Videos: first look {f0}, 'Show more videos' +12 (Enter: focus on the first new one) up to all 34, Show fewer → {f0}, focus on Show more, in view",
                  first == f0 and steps == [min(f0 + 12 * k, 34) for k in range(1, len(steps) + 1)] and steps[-1:] == [34] and kb == f0
                  and fw == [f0, True, True] and names == {'Show more videos', 'Show fewer'}, [first, steps, kb, fw, sorted(names)])
            page.locator("#g-tab-all").click()
            page.evaluate("document.querySelector('#g-panel .g-strip').scrollIntoView({block: 'center', behavior: 'instant'})")
            page.wait_for_timeout(500)
            shot(page, "v-videos-all-strip")
        want = [u for u, _v in VIDS]
        check(f"{tag} videos report ({how.split('?')[1]}): strip + Images tab = all {len(VIDS)} unique thumbs in order, play badge on the {sum(v for _u, v in VIDS)} from video results, Videos tab reaches 34",
              sv[2] == iv[2] == want and sv[1] == iv[1] == sum(v for _u, v in VIDS) and vn == 34 and badge[0] == '""' and badge[1] == "24px" and badge[2] == "absolute",
              [sv[:2], iv[:2], len(want), vn, badge])
        ctx.close()
    # every thumb fails (late, after the report is up): the All strip keeps its height (visible slots stay as empty tiles), nothing below moves
    ctx = new_ctx()
    page = ctx.new_page()
    held, hold = [], [True]
    GIF1 = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==")   # 1x1: a "blank" thumb (drop path, no console 404)
    page.route(lambda u: "/api/thumb" in u, lambda r: held.append(r) if hold[0] else r.fulfill(status=200, body=GIF1, content_type="image/gif"))
    page.goto(base + "scan/?r=demoR3port01", wait_until="load")
    page.wait_for_selector("#report:not([hidden])", timeout=8000)
    page.wait_for_timeout(600)
    POS = """() => { const s = document.querySelector('#g-panel .g-strip'), b = [...s.children];
        return [s.offsetHeight, Math.round(document.querySelector('#g-panel .g-r').getBoundingClientRect().top + scrollY), b.length,
                b.filter(e => e.querySelector('.g-img-none')).length, b.filter(e => { const i = e.querySelector('img'); return i && i.complete && i.naturalWidth >= 16; }).length]; }"""
    a0, t0 = page.evaluate(POS), page.evaluate("performance.now()")
    hold[0] = False
    while held:
        held.pop().fulfill(status=200, body=GIF1, content_type="image/gif")
    page.wait_for_timeout(2000)
    a1 = page.evaluate(POS)
    ls = page.evaluate("(t0) => window.__ls.filter(x => x[0] > t0 && x[1] > 0 && !x[2]).map(x => x[3])", t0)
    check(f"{tag} thumbs: every All-strip thumb comes back blank, late: strip keeps its height, results below stay put, failed visible slots stay as empty tiles, no layout shift",
          a1[0] == a0[0] and a1[1] == a0[1] and a1[2] >= 1 and a1[3] >= 1 and a1[4] == 0 and not ls, [a0, a1, ls[:2]])
    ctx.close()
    STRIP_IN_VIEW = """() => { const t = document.querySelector('.ph-track');   /* the strip on screen: phone pinned at its top, desktop centred */
        if (t && getComputedStyle(t.firstElementChild).position === 'sticky') window.scrollTo({top: t.getBoundingClientRect().top + scrollY - parseFloat(getComputedStyle(t.firstElementChild).top), behavior: 'instant'});
        else document.querySelector('#g-panel .g-strip').scrollIntoView({block: 'center', behavior: 'instant'}); }"""
    # failure order: the strip's last tile fails first (empty slot), then the first one: its slot gets a tile with an image, never the empty one
    ctx = new_ctx()
    page = ctx.new_page()
    held, hold, pick = [], [True], []
    page.route(lambda u: "/api/thumb" in u, lambda r: held.append(r) if hold[0] or any(r.request.url.endswith(x) for x in pick) else r.continue_())
    page.goto(base + "scan/?r=demoR3port01", wait_until="load")
    page.wait_for_selector("#report:not([hidden])", timeout=8000)
    pick += page.evaluate("() => { const b = document.querySelector('#g-panel .g-strip').children; return [b[0], b[b.length - 1]].map(e => e.querySelector('img').getAttribute('src')); }")
    hold[0] = False
    for r in [r for r in held if not any(r.request.url.endswith(x) for x in pick)]:
        held.remove(r)
        r.continue_()
    blank = lambda src: [r.fulfill(status=200, body=GIF1, content_type="image/gif") for r in [r for r in held if r.request.url.endswith(src)] if not held.remove(r)]
    page.evaluate(STRIP_IN_VIEW)
    page.evaluate("() => { const s = document.querySelector('#g-panel .g-strip'); s.scrollTo({left: s.scrollWidth, behavior: 'instant'}); }")
    page.wait_for_timeout(800)
    blank(pick[1])
    page.wait_for_timeout(500)
    page.evaluate("() => { const b = document.querySelector('#g-panel .g-strip').children; b[b.length - 2].focus({preventScroll: true}); }")   # the donor has focus
    page.evaluate("document.querySelector('#g-panel .g-strip').scrollTo({left: 0, behavior: 'instant'})")
    page.wait_for_timeout(800)
    t0 = page.evaluate("performance.now()")
    blank(pick[0])
    page.wait_for_timeout(1200)
    lf = page.evaluate("""() => { const b = [...document.querySelector('#g-panel .g-strip').children], i = b[0].querySelector('img'), e = b[b.length - 1];
        return {first: !!i && !b[0].querySelector('.g-img-none'), painted: !!i && i.complete && i.naturalWidth >= 16, lastEmpty: !!e.querySelector('.g-img-none'),
                lastName: (e.matches('a, button') ? e : e.querySelector('a, button')).getAttribute('aria-label') || '', n: b.length, focus: document.activeElement === b[0]}; }""")
    lf["inView"] = page.evaluate("() => { const r = document.querySelector('#g-panel .g-strip').getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }")
    lf["shift"] = page.evaluate("(t0) => window.__ls.filter(x => x[0] > t0 && x[1] > 0 && !x[2]).map(x => x[3])", t0)
    check(f"{tag} thumbs: last strip tile fails first (empty slot keeps a name), then the first: its slot gets a tile with an image (not the empty one), a focused donor keeps focus; no layout shift",
          lf["inView"] and lf["first"] and lf["painted"] and lf["focus"] and lf["lastEmpty"] and lf["lastName"] and not lf["shift"], lf)
    ctx.close()
    # viewing the strip's end: its last 6 tiles fail (empty slots fill the view), then the first one: nothing at the end moves, no clamp
    ctx = new_ctx()
    page = ctx.new_page()
    held, hold, pick = [], [True], []
    page.route(lambda u: "/api/thumb" in u, lambda r: held.append(r) if hold[0] or any(r.request.url.endswith(x) for x in pick) else r.continue_())
    page.goto(base + "scan/?r=demoR3port01", wait_until="load")
    page.wait_for_selector("#report:not([hidden])", timeout=8000)
    pick += page.evaluate("() => { const b = [...document.querySelector('#g-panel .g-strip').children]; return [b[0]].concat(b.slice(-6)).map(e => e.querySelector('img').getAttribute('src')); }")
    hold[0] = False
    for r in [r for r in held if not any(r.request.url.endswith(x) for x in pick)]:
        held.remove(r)
        r.continue_()
    page.evaluate(STRIP_IN_VIEW)
    page.evaluate("() => { const s = document.querySelector('#g-panel .g-strip'); s.scrollTo({left: s.scrollWidth, behavior: 'instant'}); }")
    page.wait_for_timeout(800)
    for src in pick[1:]:
        blank(src)
    page.wait_for_timeout(800)
    END = """() => { const s = document.querySelector('#g-panel .g-strip'), b = [...s.children];
        return [Math.round(s.scrollLeft), Math.round(b[b.length - 1].getBoundingClientRect().left), b.length, b.slice(-6).filter(e => e.querySelector('.g-img-none')).length]; }"""
    e0, t0 = page.evaluate(END), page.evaluate("performance.now()")
    blank(pick[0])
    page.wait_for_timeout(1000)
    e1 = page.evaluate(END)
    ls = page.evaluate("(t0) => window.__ls.filter(x => x[0] > t0 && x[1] > 0 && !x[2]).map(x => x[3])", t0)
    check(f"{tag} thumbs: viewing the strip's end, its last 6 fail then the first: the end stays put (scroll position, tiles), no layout shift",
          e0[3] == 6 and e1[:3] == e0[:3] and not ls, [e0, e1, ls[:2]])
    ctx.close()

    # ---------- (3) #free phone: tabs, illustration without a scan ----------
    ctx = new_ctx()
    page = ctx.new_page()
    page.goto(base, wait_until="load")
    page.locator("#free").scroll_into_view_if_needed()
    page.wait_for_timeout(900)
    PH = """(sel) => { const ph = document.querySelector(sel), r = ph.getBoundingClientRect();
        return {box: [Math.round(r.x), Math.round(r.y + scrollY), Math.round(r.width), Math.round(r.height)],
          sel: [...ph.querySelectorAll('[role=tab]')].map(b => [b.textContent, b.getAttribute('aria-selected'), b.tabIndex]),
          shown: [...ph.querySelectorAll('[role=tabpanel]')].filter(p => !p.hidden && p.offsetParent !== null).map(p => p.id),
          shifts: window.__ls.filter(x => x[1] > 0).length, focus: document.activeElement && document.activeElement.id}; }"""
    s0 = page.evaluate(PH, ".phone-free")
    check(f"{tag} free: no scan → Images tab selected, illustration tiles", s0["shown"] == ["mp-free-images"] and s0["sel"][1] == ["Images", "true", 0], s0)
    boxes, seen, shifts = [s0["box"]], [], []
    for k, label in (("all", "All"), ("images", "Images"), ("videos", "Videos")):
        # per click, before shot() (its light/dark flip is not a tab switch); the fixed Ask-AI pill's own height
        # animation (pre-existing, main) is not the tab's doing either
        t0 = page.evaluate("performance.now()")
        page.locator(f"#mt-free-{k}").click()
        page.wait_for_timeout(250)
        shifts += page.evaluate("t0 => window.__ls.filter(x => x[0] >= t0 && x[1] > 0 && !x[3].every(n => n.startsWith('BUTTON.askai-launcher'))).map(x => [x[1], x[3]])", t0)
        sk = page.evaluate(PH, ".phone-free")
        boxes.append(sk["box"])
        seen.append(sk["shown"] == [f"mp-free-{k}"] and [x[1] for x in sk["sel"]] == ["true" if x[0] == label else "false" for x in sk["sel"]])
        shot(page, f"3-free-{k}-demo", "#free .free-phone")
    check(f"{tag} free: tabs switch on click (All / Images / Videos), the phone never moves or resizes, zero layout shift",
          all(seen) and len({tuple(b) for b in boxes}) == 1 and not shifts, (seen, boxes, shifts))
    page.locator("#mt-free-videos").focus()
    page.keyboard.press("ArrowRight")
    k1 = page.evaluate(PH, ".phone-free")
    page.keyboard.press("End")
    k2 = page.evaluate(PH, ".phone-free")
    check(f"{tag} free: keyboard: → wraps to All, End = Videos (roving tabindex)", k1["focus"] == "mt-free-all" and k1["shown"] == ["mp-free-all"]
          and k2["focus"] == "mt-free-videos" and k2["shown"] == ["mp-free-videos"] and [x[2] for x in k2["sel"]] == [-1, -1, 0], (k1, k2))
    m["free_phone_box"] = s0["box"]
    m["overflow_no_scan"] = overflow(page)
    ctx.close()

    # with a report: her handle, rows, tiles (Reveal), videos
    ctx = new_ctx()
    page = ctx.new_page()
    page.goto(base + "?r=" + FX["slug"] + "#free", wait_until="load")
    page.wait_for_selector(".phone-free.is-live", timeout=8000)
    page.wait_for_timeout(1500)
    page.locator("#free").scroll_into_view_if_needed()
    rows = _rows(FX)
    IMs = _images(FX, alive=True)
    VID = [r for r in FX["results"] if is_video(r)]
    lv = page.evaluate("""() => { const ph = document.querySelector('.phone-free'), q = s => [...ph.querySelectorAll(s)];
        return {search: ph.querySelector('[data-p=scan-handle]').textContent, label: ph.getAttribute('aria-label'),
          all: q('[data-live=band-all] a.m-link').map(a => [a.href, a.target, a.querySelector('.m-site').textContent]),
          tiles: q('[data-live=band-images] a.gi-card').map(a => decodeURIComponent(a.querySelector('img').getAttribute('src').split('u=')[1])),
          n: (ph.querySelector('[data-live=band-images] .m-n') || {}).textContent,
          vids: q('[data-live=band-videos] a.m-link').map(a => a.href), illus: q('.m-illus').filter(e => e.offsetParent !== null).length}; }""")
    check(f"{tag} free: report → search = @handle, All = her first 4 rows (new tab), Images = first 9 that load + count, Videos = her video results",
          lv["search"] == "@demo.creator" and lv["label"] == "Google results for @demo.creator" and [x[0] for x in lv["all"]] == [r[2] for r in rows[:4]]
          and all(x[1] == "_blank" for x in lv["all"]) and lv["tiles"] == [x[0] for x in _band(FX, IMs)] and lv["n"] == f"{len(IMs)} images"
          and lv["vids"] == [r["link"] for r in VID[:3]] and lv["illus"] == 0, lv)
    for k in ("all", "images", "videos"):
        page.locator(f"#mt-free-{k}").click()
        page.wait_for_timeout(500 if k == "images" else 250)
        if k == "images":
            b0 = page.evaluate("getComputedStyle(document.querySelector('#mp-free-images .gi-img')).filter")
            page.locator("#mp-free-images .live-reveal").click()
            page.wait_for_timeout(400)
            b1 = page.evaluate("[getComputedStyle(document.querySelector('#mp-free-images .gi-img')).filter, document.querySelector('#mp-free-images .live-reveal').getAttribute('aria-pressed')]")
            shot(page, "3-free-images-revealed", "#free .free-phone")
            page.locator("#mp-free-images .live-reveal").click()
            page.wait_for_timeout(300)
            check(f"{tag} free: report → blurred by default, Reveal unblurs, Blur again", "blur" in b0 and b1 == ["none", "true"], (b0, b1))
        shot(page, f"3-free-{k}", "#free .free-phone")
    m["overflow_report"] = overflow(page)
    ctx.close()

    # ---------- (2) order, Before / After tabs, pop-out ----------
    ctx = new_ctx()
    page = ctx.new_page()
    page.goto(base, wait_until="load")
    order = page.evaluate("""() => { const y = e => e.getBoundingClientRect().top + scrollY, b = e => e.getBoundingClientRect().bottom + scrollY;
        const w = document.getElementById('website'), sc = document.getElementById('showcase'), fr = sc.querySelector('.browser-demo'), ba = document.querySelector('.ba');
        return {website: Math.round(y(w)), showcase: Math.round(y(sc)), frameBottom: Math.round(b(fr)), ba: Math.round(y(ba)), inShowcase: sc.contains(ba),
          link: (a => a && a.getAttribute('href'))(sc.querySelector('a.btn[data-p=demo]'))}; }""")
    check(f"{tag} order: #website copy → demo iframe (#showcase) → Before / After phones below it; 'Open the demo site' link kept",
          order["website"] < order["showcase"] < order["frameBottom"] <= order["ba"] and order["inShowcase"] and order["link"] == "showcase/", order)
    page.locator("#showcase .ba").scroll_into_view_if_needed()
    page.wait_for_timeout(900)
    ok, shifts = [], []
    for side in ("before", "after"):
        for k in ("images", "videos", "all"):
            t0 = page.evaluate("performance.now()")
            page.locator(f"#mt-{side}-{k}").click()
            page.wait_for_timeout(300)
            shifts += page.evaluate("t0 => window.__ls.filter(x => x[0] >= t0 && x[1] > 0 && !x[3].every(n => n.startsWith('BUTTON.askai-launcher'))).map(x => [x[1], x[3]])", t0)
            r = page.evaluate("(id) => document.getElementById(id).closest('.phone').getBoundingClientRect().height", f"mp-{side}-{k}")
            vis = page.evaluate(f"[...document.querySelectorAll('[id^=mp-{side}-]')].filter(p => !p.hidden).map(p => p.id)")
            imgs = page.evaluate(f"[...document.querySelectorAll('#mp-{side}-{k} img')].map(i => i.complete && i.naturalWidth > 0)")
            ok.append([side, k, vis == [f"mp-{side}-{k}"], all(imgs), round(r)])
            if k != "all":
                shot(page, f"2-ba-{side}-{k}", "#showcase .ba")
    hs = {x[4] for x in ok}
    check(f"{tag} before/after: All / Images / Videos switch in both phones, their photos load, phone height fixed (no CLS)",
          all(x[2] and x[3] for x in ok) and len(hs) == 1 and not shifts, (ok, shifts))
    shot(page, "2-before-after", "#showcase .ba")
    m["overflow_before_after"] = overflow(page)
    # pop-out
    page.evaluate("document.querySelector('#showcase .browser-demo').scrollIntoView({block: 'center', behavior: 'instant'})")
    page.wait_for_timeout(1200)
    LAY = """() => { const r = e => { const b = e.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.top + scrollY), Math.round(b.width), Math.round(b.height)]; };
        const f = document.querySelector('#showcase .browser-demo');
        return {y: Math.round(scrollY), ba: r(document.querySelector('.ba')), head: r(document.querySelector('#showcase .section-head')), link: r(document.querySelector('#showcase a.btn[data-p=demo]')),
          pop: f.classList.contains('is-pop'), fig: (b => [Math.round(b.left), Math.round(b.top), Math.round(b.right), Math.round(b.bottom)])(f.getBoundingClientRect()),
          vw: innerWidth, vh: innerHeight, role: f.getAttribute('role'), modal: f.getAttribute('aria-modal'), lock: document.documentElement.classList.contains('pop-lock'),
          focus: document.activeElement.className, inert: document.querySelector('.site-header, header').inert && document.getElementById('pricing').inert,
          btn: document.querySelector('.demo-pop').getAttribute('aria-label'), iframeTab: f.querySelector('iframe').tabIndex}; }"""
    l0 = page.evaluate(LAY)
    page.locator(".demo-pop").click()
    page.wait_for_timeout(400)
    l1 = page.evaluate(LAY)
    page.mouse.move(vp["width"] // 2, 20)
    page.mouse.wheel(0, 600)
    page.wait_for_timeout(400)
    l1b = page.evaluate(LAY)
    shot(page, "2-popout-open")
    covers = l1["fig"][0] <= 24 and l1["fig"][1] <= 24 and l1["fig"][2] >= l1["vw"] - 24 and l1["fig"][3] >= l1["vh"] - 24
    check(f"{tag} popout: opens a full-screen layer (role=dialog, aria-modal, rest of the page inert, focus on Close, iframe keyboard-reachable)",
          l1["pop"] and covers and l1["role"] == "dialog" and l1["modal"] == "true" and l1["inert"] and "demo-pop" in l1["focus"]
          and l1["btn"] == "Close full screen" and l1["iframeTab"] == 0, l1)
    check(f"{tag} popout: page behind is scroll-locked and does not move (scrollY, phones, heading, link: same page coords)",
          l1["lock"] and l1b["y"] == l0["y"] == l1["y"] and l1["ba"] == l0["ba"] and l1["head"] == l0["head"] and l1["link"] == l0["link"], (l0, l1, l1b["y"]))
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    l2 = page.evaluate(LAY)
    check(f"{tag} popout: Esc closes, focus back on the button, nothing moved, page unlocked",
          not l2["pop"] and not l2["lock"] and "demo-pop" in l2["focus"] and l2["role"] is None and not l2["inert"] and l2["iframeTab"] == -1
          and [l2[k] for k in ("y", "ba", "head", "link")] == [l0[k] for k in ("y", "ba", "head", "link")], (l0, l2))
    page.locator(".demo-pop").click()
    page.wait_for_timeout(300)
    page.evaluate("document.querySelector('#showcase iframe').contentWindow.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
    page.wait_for_timeout(200)
    in_frame = page.evaluate(LAY)["pop"]
    page.locator(".demo-pop").click()
    page.wait_for_timeout(200)
    page.locator(".demo-pop").click()
    page.wait_for_timeout(200)
    by_btn = page.evaluate(LAY)["pop"]
    page.locator(".demo-pop").click()
    page.wait_for_timeout(200)
    page.mouse.click(2, vp["height"] - 2) if vp_name == "desktop" else page.evaluate("document.querySelector('.demo-backdrop').click()")
    page.wait_for_timeout(200)
    by_bd = page.evaluate(LAY)
    check(f"{tag} popout: Esc inside the demo, the Close button and the backdrop close it too", in_frame is False and by_btn is False and by_bd["pop"] is False and by_bd["y"] == l0["y"],
          (in_frame, by_btn, by_bd["pop"]))
    shot(page, "2-popout-closed")
    m["popout"] = {"before": l0, "open": l1, "after_close": l2}
    ov = [m.get("overflow_no_scan"), m.get("overflow_report"), m["overflow_before_after"]]
    check(f"{tag} layout: no horizontal overflow at {vp['width']} px (document, phones, demo frame, card)",
          all(o and o["doc"] <= o["vw"] and not o["wide"] for o in ov), ov)
    ctx.close()
    hosts = {urlsplit(u).hostname for u in net["outside"]}
    check(f"{tag} no request left loopback but the demo's aborted Google Fonts", hosts <= FONT_HOSTS, sorted(hosts))
    check(f"{tag} no JS errors, no console errors (the stub's 404 thumbs aside)", not net["errors"] and not net["console"], net["errors"] + net["console"])

# ---------- removals (js/removals.js, css/removals.css: the #removals "Where I remove from" panels) ----------
RM_PANELS = ("mega", "x", "reddit", "site")
RM_STATE = """() => { const y0 = scrollY, out = [...document.querySelectorAll('#removals .rm-card')].map(c => {
  const s = c.querySelector('.rm-stage'), b = c.querySelector('.rm-btn');
  s.scrollIntoView({block: 'center', behavior: 'instant'});
  const r = s.getBoundingClientRect(), top = document.elementFromPoint(r.left + r.width * .75, r.top + r.height / 2), cb = c.getBoundingClientRect();
  return {k: c.dataset.rm, p: c.querySelector('.rm-handle').getAttribute('aria-valuenow'), pressed: b.getAttribute('aria-pressed'),
    label: b.textContent, clip: getComputedStyle(c.querySelector('.rm-gone')).clipPath,
    shown: top && top.closest('.rm-gone') ? 'gone' : top && top.closest('.rm-live') ? 'live' : String(top && top.className),
    box: [r.x, r.y + scrollY, r.width, r.height].map(Math.round), card: [cb.x, cb.y + scrollY, cb.width, cb.height].map(Math.round)}; });
  scrollTo({top: y0, behavior: 'instant'}); return out; }"""
RM_TEXT = """() => Object.fromEntries([...document.querySelectorAll('#removals [data-rm-k]')].map(e => [e.dataset.rmK, e.textContent]))"""


def removals_flow(browser, vp_name, vp):
    tag = f"{vp_name} removals:"
    net = {"outside": [], "errors": [], "results": [], "dialogs": []}

    def new_ctx(scheme="light", motion="no-preference"):
        ctx = browser.new_context(viewport=vp, device_scale_factor=2 if vp_name == "phone" else 1, is_mobile=vp_name == "phone",
                                  has_touch=vp_name == "phone", color_scheme=scheme, reduced_motion=motion)
        ctx.add_init_script("window.__ls = []; try { new PerformanceObserver(l => l.getEntries().forEach(e => window.__ls.push([e.startTime, e.value, e.hadRecentInput]))).observe({type: 'layout-shift', buffered: true}); } catch (e) {}")

        def route(r, _req):
            if urlsplit(r.request.url).hostname in ("127.0.0.1", "localhost"):
                r.continue_()
            else:
                net["outside"].append(r.request.url)
                r.abort()
        ctx.route("**/*", route)
        if BREAK_REMOVE:   # wire boundary: removals.js served with the Remove click handler gone (same bytes otherwise)
            body = (ROOT / "site" / "js" / "removals.js").read_text(encoding="utf-8")
            old = "card.querySelector('.rm-btn').addEventListener('click',"
            assert old in body, "break: marker not found in removals.js"
            ctx.route("**/js/removals.js", lambda r: r.fulfill(body=body.replace(old, "(function () {})(", 1), content_type="application/javascript"))

        def on_page(pg):
            pg.on("pageerror", lambda e: net["errors"].append(str(e)))
            pg.on("dialog", lambda d: (net["dialogs"].append(d.message), d.dismiss()))
            pg.on("request", lambda q: "/api/scan-result/" in q.url and net["results"].append(q.url))
        ctx.on("page", on_page)
        return ctx

    def open_(ctx, q=""):
        page = ctx.new_page()
        page.goto(base + q, wait_until="load")
        page.locator("#removals .section-head").scroll_into_view_if_needed()
        page.locator("#removals .rm-grid").scroll_into_view_if_needed()
        page.wait_for_timeout(700)
        return page

    def settled_imgs(page):
        try:
            page.wait_for_function("() => [...document.querySelectorAll('#removals .rm-img')].every(i => i.complete && i.naturalWidth > 0)", timeout=6000)
        except Exception:
            pass

    for scheme in ("light", "dark"):
        ctx = new_ctx(scheme)
        page = open_(ctx)
        order = page.evaluate("() => { const r = document.getElementById('removals'); return [r && r.previousElementSibling && r.previousElementSibling.id, r && r.nextElementSibling && r.nextElementSibling.id, r && r.closest('main') && r.closest('main').id]; }")
        if scheme == "light":
            check(f"{tag} section sits after #faq, directly before #contact, inside <main>", order == ["faq", "contact", "main"], order)
            t = page.evaluate(RM_TEXT)
            check(f"{tag} defaults: demo creator (Orla Brennick / brennickclay) in every panel",
                  t.get("name") == "Orla Brennick" and t.get("mega-title") == "brennickclay – pack" and t.get("x-l1") == "Orla Brennick leaked"
                  and t.get("album") == "Orla Brennick – album" and t.get("host") == "leak-mirror.example", t)
            outs = page.eval_on_selector_all("#removals .rm-out", "es => es.map(e => e.textContent)")
            check(f"{tag} one outcome line per panel", outs == ["Mega: folder disabled", "X: media disabled after copyright report",
                                                             "Reddit: removed on copyright notice", "Leak sites: album deleted or 404"], outs)
            check(f"{tag} no links in the section (mock-ups only)", page.locator("#removals a").count() == 0)
        settled_imgs(page)
        blur = page.eval_on_selector_all("#removals .rm-img", "es => es.map(e => [e.getAttribute('src'), getComputedStyle(e).filter, e.naturalWidth])")
        check(f"{tag} {scheme}: every leak-side image blurred by default, loaded from site/img", len(blur) == 10 and all(
            "blur(" in b[1] and b[0].startswith("img/removals/") and b[2] > 0 for b in blur), blur)
        sw = page.evaluate("() => [document.documentElement.scrollWidth, innerWidth, Math.max(...[...document.querySelectorAll('#removals *')].map(e => e.parentElement.closest('.rm-stage') ? 0 : e.getBoundingClientRect().right))]")
        check(f"{tag} {scheme}: no horizontal overflow", sw[0] <= sw[1] and sw[2] <= sw[1] + 0.5, sw)
        cols = page.evaluate("() => new Set([...document.querySelectorAll('#removals .rm-card')].map(c => Math.round(c.getBoundingClientRect().x))).size")
        check(f"{tag} {scheme}: layout {'stacked' if vp_name == 'phone' else '2x2'}", cols == (1 if vp_name == "phone" else 2), cols)
        before = page.evaluate(RM_STATE)
        check(f"{tag} {scheme}: starts live (edge at 100, removed layer clipped away)", all(
            s["p"] == "100" and s["pressed"] == "false" and s["label"] == "Remove" and s["shown"] == "live" for s in before), before)
        for k, card in zip(RM_PANELS, page.locator("#removals .rm-card").all()):
            card.screenshot(path=str(out / f"removals-{vp_name}-{scheme}-{k}-1-live.png"))
        page.evaluate("() => { window.__ls.length = 0; }")
        for b in page.locator("#removals .rm-btn").all():
            b.click()
        page.wait_for_timeout(1000)
        after = page.evaluate(RM_STATE)
        check(f"{tag} {scheme}: toggle: Remove flips all 4 panels to removed (edge 0, removed layer on top, 'Show again')",
              [s["k"] for s in after] == list(RM_PANELS) and all(s["p"] == "0" and s["pressed"] == "true" and s["label"] == "Show again"
                                                               and s["shown"] == "gone" and s["clip"] == "inset(0px 0px 0px 0%)" for s in after), after)
        ls = page.evaluate("() => window.__ls.filter(e => !e[2]).reduce((a, e) => a + e[1], 0)")
        check(f"{tag} {scheme}: CLS 0 on toggle, stage + card boxes unchanged", ls == 0 and [s["box"] + s["card"] for s in before] == [s["box"] + s["card"] for s in after],
              f"cls={ls}")
        for k, card in zip(RM_PANELS, page.locator("#removals .rm-card").all()):
            card.screenshot(path=str(out / f"removals-{vp_name}-{scheme}-{k}-2-removed.png"))
        page.locator("#removals .rm-btn").first.click()
        page.wait_for_timeout(1000)
        back = page.evaluate(RM_STATE)[0]
        check(f"{tag} {scheme}: toggle: Show again puts the leak back", back["p"] == "100" and back["shown"] == "live" and back["label"] == "Remove", back)
        if scheme == "light":
            # drag: grab the stage near its right edge, pull to 30 %
            st = page.locator('#removals .rm-card[data-rm="x"] .rm-stage')
            st.scroll_into_view_if_needed()
            r = st.bounding_box()
            y = r["y"] + r["height"] * .4
            page.mouse.move(r["x"] + r["width"] - 4, y)
            page.mouse.down()
            for f in (.8, .6, .45, .3):
                page.mouse.move(r["x"] + r["width"] * f, y, steps=3)
            page.mouse.up()
            d = page.evaluate(RM_STATE)[1]
            check(f"{tag} drag moves the edge and the clip (left = leak, right = removed)", 27 <= int(d["p"]) <= 33
                  and d["clip"] == f"inset(0px 0px 0px {d['p']}%)" and d["shown"] == "gone", d)
            st.screenshot(path=str(out / f"removals-{vp_name}-drag-x-30.png"))
            page.locator('#removals .rm-card[data-rm="x"] .rm-handle').focus()
            page.keyboard.press("End")
            k1 = page.evaluate(RM_STATE)[1]
            page.keyboard.press("ArrowLeft")
            k2 = page.evaluate(RM_STATE)[1]
            check(f"{tag} keyboard on the handle: End = all leak, ArrowLeft steps 10", k1["p"] == "100" and k2["p"] == "90", [k1["p"], k2["p"]])
            page.locator("#removals .rm-reveal").click()
            page.wait_for_timeout(500)   # filter transition .25s
            rv = page.eval_on_selector_all("#removals .rm-img", "es => es.map(e => getComputedStyle(e).filter)")
            check(f"{tag} Reveal unblurs, Blur images re-blurs", all(f == "none" for f in rv) and page.locator("#removals .rm-reveal").inner_text().strip() == "Blur images")
            page.locator("#removals .rm-reveal").click()
        ctx.close()

    # reduced motion: no transition, the flip is immediate
    ctx = new_ctx(motion="reduce")
    page = open_(ctx)
    page.locator("#removals .rm-btn").first.click()
    rm = page.evaluate("() => [getComputedStyle(document.querySelector('#removals .rm-gone')).transitionDuration, document.querySelector('#removals .rm-handle').getAttribute('aria-valuenow')]")
    check(f"{tag} toggle: reduced motion flips with no transition", rm == ["0s", "0"], rm)
    ctx.close()

    # personalized: ?r=<slug> (shared scan-result request), the backend's mega[], x / reddit / leak-site hits, thumbs still blurred
    MEGA = {"title": "demo.creator MEGA pack 2026", "meta": "6.2 GB · 412 images · 88 videos · 3 days ago"}
    top_leak = top_domains(FX["hits"])[0]
    for scheme in ("light", "dark"):
        ctx = new_ctx(scheme)
        net["results"].clear()
        page = open_(ctx, "?r=demoRemove1")
        try:
            page.wait_for_function("() => document.getElementById('removals').getAttribute('data-rm-for') === 'demo.creator'", timeout=6000)
        except Exception:
            pass
        settled_imgs(page)
        t = page.evaluate(RM_TEXT)
        if scheme == "light":
            check(f"{tag} ?r=: personalized name + handle + mega title / size / counts", t.get("name") == FX["profile"]["display_name"]
                  and t.get("mega-title") == MEGA["title"] and t.get("mega-meta") == MEGA["meta"] and t.get("mega-img") == "412 files"
                  and t.get("mega-vid") == "88 files", t)
            check(f"{tag} ?r=: x.com hit → X post, reddit.com hit → subreddit + title, top other host → leak-site chrome",
                  t.get("x-at") == "@demo_reposter" and t.get("x-l1") == "Mira Example leaked full set" and t.get("sub") == "r/demo_leaksub"
                  and t.get("rd-title") == "Mira Example new pack in comments" and t.get("host") == top_leak, t)
            html = page.inner_html("#removals")
            check(f"{tag} ?r=: no URL rendered, no links", "mega.nz/" not in html and "x.com/" not in html and "reddit.com/" not in html
                  and page.locator("#removals a").count() == 0)
            check(f"{tag} ?r=: one /api/scan-result request (shared with the hero card)", len(net["results"]) == 1, net["results"])
        th = page.eval_on_selector_all("#removals .rm-img", "es => es.map(e => [e.getAttribute('src'), getComputedStyle(e).filter, e.naturalWidth])")
        check(f"{tag} ?r= {scheme}: real thumbs via <API>/api/thumb, still blurred", all(
            s[0].startswith(API + "/api/thumb?u=") and "blur(" in s[1] and s[2] > 0 for s in th), th[:2])
        page.locator("#removals .rm-grid").screenshot(path=str(out / f"removals-{vp_name}-{scheme}-personalized-1-live.png"))
        for b in page.locator("#removals .rm-btn").all():
            b.click()
        page.wait_for_timeout(1000)
        page.locator("#removals .rm-grid").screenshot(path=str(out / f"removals-{vp_name}-{scheme}-personalized-2-removed.png"))
        ctx.close()

    # no mega[] / no x / reddit hits → demo shapes with her name; hostile values never reach the DOM
    ctx = new_ctx()
    page = open_(ctx, "?r=demoNoProf01")
    try:
        page.wait_for_function("() => document.getElementById('removals').getAttribute('data-rm-for') === 'demo.creator'", timeout=6000)
    except Exception:
        pass
    t = page.evaluate(RM_TEXT)
    check(f"{tag} no mega[]: fallback '<handle> – pack' + demo counts, her handle as name", t.get("mega-title") == "demo.creator – pack"
          and t.get("mega-meta") == "4 GB · 369 images · 1069 videos · 7 minutes ago" and t.get("name") == "demo.creator"
          and t.get("x-at") == "@leak.mirror" and t.get("sub") == "r/democreator_leaks", t)
    page.goto(base + "?r=evilR3port01", wait_until="load")
    page.wait_for_timeout(1500)
    html = page.inner_html("#removals")
    t = page.evaluate(RM_TEXT)
    check(f"{tag} hostile mega[] dropped (no markup, no javascript:, no oversize)", "onerror" not in html and "javascript" not in html
          and "xxxxx" not in html and page.locator("#removals img:not(.rm-img)").count() == 0 and not net["dialogs"], t.get("mega-meta"))
    ctx.close()
    hosts = {urlsplit(u).hostname for u in net["outside"]}
    check(f"{tag} no request left loopback but the demo iframe's aborted Google Fonts, no JS errors", hosts <= FONT_HOSTS and not net["errors"],
          sorted(hosts) + net["errors"])


PIP_J = """() => { const p = document.querySelector('.pip'), t = document.querySelector('.pip-tab'), R = e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.width, r.height].map(Math.round); };
  if (!p) return null; const f = p.querySelector('iframe'); let v = null, emb = null;
  try { const d = f.contentDocument, e = d.querySelector('.vo-video'), st = d.querySelector('.vo-stage').getBoundingClientRect();
    v = {paused: e.paused, muted: e.muted, t: e.currentTime}; emb = {nb: getComputedStyle(d.querySelector('.vo-nb')).display, ui: getComputedStyle(d.querySelector('.vo-ui')).display,
    sw: Math.round(st.width), sh: Math.round(st.height), fw: f.clientWidth, fh: f.clientHeight}; } catch (x) { v = String(x); }
  return {cls: p.className, box: R(p), on: p.classList.contains('on') && !p.classList.contains('tucked'), tucked: p.classList.contains('tucked'),
    tab: t && !t.hidden ? {box: R(t), side: t.dataset.side, chev: t.innerHTML.includes('m9 6') ? '>' : t.innerHTML.includes('m15 6') ? '<' : '?'} : null,
    v, emb, src: f.src, focus: document.activeElement && document.activeElement.className, vw: document.documentElement.clientWidth, vh: innerHeight}; }"""
PIP_HIT = """([sel, inside]) => [...document.querySelectorAll(sel)].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.bottom > 0 && r.top < innerHeight && getComputedStyle(e).visibility !== 'hidden'; })
  .map(e => { const r = e.getBoundingClientRect(), pts = [[r.left + r.width / 2, r.top + r.height / 2], [r.left + 4, r.top + r.height / 2], [r.right - 4, r.top + r.height / 2]];
    return pts.every(([x, y]) => { const h = document.elementFromPoint(x, y); return h && h.closest(inside || sel) === e.closest(inside || sel); }); })"""


def pip_flow(pw, chromium, vp_name, vp, engine="chromium"):
    """js/pip.js: the floating mini player of site/video/ (report page default with ?r=, landing with ?pip=1)."""
    tag = f"{vp_name}{'-webkit' if engine == 'webkit' else ''} pip:"
    net = {"outside": [], "errors": [], "video": []}
    phone = vp_name == "phone"
    browser = pw.webkit.launch() if engine == "webkit" else chromium

    def new_ctx(motion="no-preference"):
        opts = dict(pw.devices["iPhone 13"]) if engine == "webkit" else dict(viewport=vp, device_scale_factor=2 if phone else 1, is_mobile=phone, has_touch=phone)
        ctx = browser.new_context(**opts, reduced_motion=motion)
        ctx.add_init_script("""window.__ls = []; try { new PerformanceObserver(l => l.getEntries().forEach(e => window.__ls.push([e.startTime, e.value]))).observe({type: 'layout-shift', buffered: true}); } catch (e) {}
          new MutationObserver(() => { if (!window.__pipAt && document.querySelector('.pip iframe')) window.__pipAt = performance.now(); }).observe(document, {childList: true, subtree: true});""")

        def route(r, _req):
            if urlsplit(r.request.url).hostname in ("127.0.0.1", "localhost"):
                if "/video/" in r.request.url:
                    net["video"].append(r.request.url)
                r.continue_()
            else:
                net["outside"].append(r.request.url)
                r.abort()
        ctx.route("**/*", route)
        if BREAK_TUCK:   # wire boundary: pip.js served with the tuck handler gone (same bytes otherwise)
            body = (ROOT / "site" / "js" / "pip.js").read_text(encoding="utf-8")
            old = "  function tuck(side) {\n"
            assert old in body, "break: marker not found in pip.js"
            ctx.route("**/js/pip.js", lambda r: r.fulfill(body=body.replace(old, old + "    return;\n", 1), content_type="application/javascript"))
        ctx.on("page", lambda pg: (pg.on("pageerror", lambda e: net["errors"].append(str(e))),
                                   pg.on("console", lambda m: m.type == "error" and net["errors"].append(m.text))))
        pg = ctx.new_page()
        return ctx, pg, (ctx.new_cdp_session(pg) if engine == "chromium" and phone else None)

    def st(pg):
        return pg.evaluate(PIP_J)

    def ready(pg, url, wake=True):
        pg.goto(base + url, wait_until="load")
        if wake:
            pg.keyboard.press("Shift")   # an interaction mounts it at once (else: idle)
        pg.wait_for_function("() => { const p = document.querySelector('.pip'); return p && p.classList.contains('on'); }", timeout=10000)
        pg.wait_for_timeout(500)
        return st(pg)

    def tap(pg, x, y):
        if phone:
            pg.touchscreen.tap(x, y)
        else:
            pg.mouse.click(x, y)
        pg.wait_for_timeout(450)

    def drag(pg, cdp, pts, step=16, hold=0):   # real touch via CDP (Chromium phone), else the mouse (WebKit: pointerType mouse, declared)
        if cdp:
            cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": pts[0][0], "y": pts[0][1]}]})
            for x, y in pts[1:]:
                pg.wait_for_timeout(step)
                cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y}]})
            pg.wait_for_timeout(hold)
            cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        else:
            pg.mouse.move(*pts[0]); pg.mouse.down()
            for x, y in pts[1:]:
                pg.wait_for_timeout(step)
                pg.mouse.move(x, y)
            pg.wait_for_timeout(hold)
            pg.mouse.up()
        pg.wait_for_timeout(600)

    def centre(s):
        b = s["box"]
        return b[0] + b[2] / 2, b[1] + b[3] / 2

    def to_corner(pg, cdp, s, corner):   # slow drag + hold (no fling) to the middle of that quadrant
        x0, y0 = centre(s)
        x1 = s["vw"] * (0.25 if corner[1] == "l" else 0.75)
        y1 = s["vh"] * (0.3 if corner[0] == "t" else 0.7)
        drag(pg, cdp, [(x0 + (x1 - x0) * i / 12, y0 + (y1 - y0) * i / 12) for i in range(13)], 30, 200)
        return st(pg)

    def fling(pg, cdp, s, dx):
        x0, y0 = centre(s)
        drag(pg, cdp, [(x0 + dx * i / 6, y0) for i in range(7)], 10, 0)
        return st(pg)

    def clear(pg):   # header / report nav / Scan now / CTA bar / launcher still get the click with the player up
        hdr = all(pg.evaluate(PIP_HIT, [".site-header a, .site-header button", ""]))
        nav = all(pg.evaluate(PIP_HIT, [".rnav a, .rnav button", ""]))
        scan = all(pg.evaluate(PIP_HIT, ["#scan button[type=submit]", ""]))
        bars = all(pg.evaluate(PIP_HIT, [".mobile-cta.show, .askai-launcher:not([hidden])", ""]))
        return hdr and nav and scan and bars, {"hdr": hdr, "nav": nav, "scan": scan, "bars": bars}

    def shot(pg, name):
        pg.screenshot(path=str(out / f"{tag.split()[0]}-pip-{name}.png"))

    # flags: landing without ?pip=1, scan/ without ?r= = no player, no /video/ request
    ctx, pg, cdp = new_ctx()
    pg.goto(base, wait_until="load"); pg.keyboard.press("Shift"); pg.evaluate("scrollBy(0, 400)"); pg.wait_for_timeout(4500)
    pg.goto(base + "scan/", wait_until="load"); pg.keyboard.press("Shift"); pg.wait_for_timeout(4500)
    check(f"{tag} flag: landing without ?pip=1 and scan/ without ?r= show no player, load no /video/",
          pg.locator(".pip").count() == 0 and not net["video"], net["video"])

    # report page: default on with ?r= (idle mount, no interaction)
    s = ready(pg, "scan/?r=demoR3port01", wake=False)
    lz = pg.evaluate("() => [window.__pipAt, performance.getEntriesByType('navigation')[0].loadEventEnd]")
    check(f"{tag} lazy: iframe created only after the page's load", lz[0] and lz[0] >= lz[1], lz)
    w, h, vw = s["box"][2], s["box"][3], s["vw"]
    check(f"{tag} appear: 16:9, {'45% of the screen' if phone else '320 px'} wide", abs(w - (min(320, 0.45 * vw))) <= 1 and abs(w * 9 / 16 - h) <= 1.5, s["box"])
    t0 = s["v"]["t"] if isinstance(s["v"], dict) else -1
    pg.wait_for_timeout(900); s = st(pg)
    check(f"{tag} appear: starts muted and playing", isinstance(s["v"], dict) and s["v"]["muted"] and not s["v"]["paused"] and s["v"]["t"] > t0 and "muted" in s["cls"], s["v"])
    u = urlsplit(s["src"])
    check(f"{tag} appear: same-origin iframe of /video/?r=<slug>", f"{u.scheme}://{u.netloc}/" == base and u.path == "/video/" and parse_qs(u.query).get("r") == ["demoR3port01"], s["src"])
    e = s["emb"] or {}
    check(f"{tag} embed: no name bar / player UI, the stage fills the frame", e.get("nb") == "none" and e.get("ui") == "none" and abs(e.get("sw", 0) - e.get("fw", -9)) <= 1 and abs(e.get("sh", 0) - e.get("fh", -9)) <= 1, e)
    ok, d = clear(pg)
    check(f"{tag} clear: header + report nav clickable with the player up (bottom corner)", ok, d)
    shot(pg, "1-appear")
    tap(pg, *centre(s)); s = st(pg)
    check(f"{tag} unmute: a tap on the player turns the sound on, keeps playing", isinstance(s["v"], dict) and not s["v"]["muted"] and not s["v"]["paused"] and "muted" not in s["cls"], s["v"])
    shot(pg, "2-unmuted")
    s = to_corner(pg, cdp, s, "tl")
    top_clear = pg.evaluate("() => Math.max(...['.site-header', '.rnav'].map(q => document.querySelector(q)).filter(Boolean).map(e => { const r = e.getBoundingClientRect(); return r.top < 140 ? r.bottom : 0; }))")
    check(f"{tag} drag: snapped to the top-left corner, under the sticky header / nav", s["on"] and s["box"][0] == (12 if phone else 24) and s["box"][1] >= top_clear, [s["box"], top_clear])
    ok, d = clear(pg)
    check(f"{tag} clear: header + report nav clickable with the player in the top corner", ok, d)
    shot(pg, "3-dragged-tl")
    s = fling(pg, cdp, s, -150)
    check(f"{tag} tuck: fling left → off-screen, '>' tab at the left edge, paused",
          s["tucked"] and s["box"][0] + s["box"][2] <= 0 and bool(s["tab"]) and s["tab"]["side"] == "l" and s["tab"]["chev"] == ">" and s["tab"]["box"][0] == 0
          and isinstance(s["v"], dict) and s["v"]["paused"], [s["box"], s["tab"]])
    shot(pg, "4-tucked-left")
    if s["tab"]:
        b = s["tab"]["box"]; tap(pg, b[0] + b[2] / 2, b[1] + b[3] / 2); s = st(pg)
    check(f"{tag} tuck: tab tapped → back on screen in its corner, playing", s["on"] and not s["tab"] and s["box"][0] == (12 if phone else 24) and isinstance(s["v"], dict) and not s["v"]["paused"], s["box"])
    shot(pg, "5-back")

    s = ready(pg, "scan/?r=demoR3port01")   # fresh page: corner from sessionStorage
    check(f"{tag} state: corner kept in sessionStorage across a reload", s["on"] and s["box"][0] == (12 if phone else 24) and s["box"][1] < s["vh"] / 2, s["box"])
    s = to_corner(pg, cdp, s, "tr")
    check(f"{tag} drag: snapped to the top-right corner", s["on"] and s["box"][0] + s["box"][2] == s["vw"] - (12 if phone else 24), s["box"])
    s = fling(pg, cdp, s, 150)
    check(f"{tag} tuck: fling right → off-screen, '<' tab at the right edge", s["tucked"] and s["box"][0] >= s["vw"] and bool(s["tab"]) and s["tab"]["side"] == "r"
          and s["tab"]["chev"] == "<" and s["tab"]["box"][0] + s["tab"]["box"][2] == s["vw"], [s["box"], s["tab"]])
    shot(pg, "6-tucked-right")
    if s["tab"]:
        b = s["tab"]["box"]; cx, cy = b[0] + b[2] / 2, b[1] + b[3] / 2
        drag(pg, cdp, [(cx - 12 * i, cy) for i in range(7)], 16, 0); s = st(pg)
    check(f"{tag} tuck: tab dragged inward → back in the top-right corner", s["on"] and not s["tab"] and s["box"][0] + s["box"][2] == s["vw"] - (12 if phone else 24), s["box"])

    s = ready(pg, "scan/?r=demoR3port01")
    pg.focus(".pip-snd"); pg.keyboard.press("Escape"); pg.wait_for_timeout(500); s = st(pg)
    check(f"{tag} tuck: Esc inside the player tucks it, focus on the tab", s["tucked"] and bool(s["tab"]) and s["focus"] == "pip-tab", [s["cls"], s["focus"]])
    s = ready(pg, "scan/?r=demoR3port01")
    check(f"{tag} tuck: tucked state kept across a reload", s is not None and s["tucked"] if s else False, s and s["cls"])
    pg.focus(".pip-tab"); pg.keyboard.press("Enter"); pg.wait_for_timeout(500); s = st(pg)
    check(f"{tag} tuck: Enter on the tab brings it back, focus inside the player", s["on"] and not s["tab"] and (s["focus"] or "").startswith("pip-"), [s["cls"], s["focus"]])
    ls = pg.evaluate("() => window.__ls.filter(e => e[0] >= (window.__pipAt || 0)).reduce((a, e) => a + e[1], 0)")
    check(f"{tag} cls: 0 after the player mounts", ls == 0, ls)

    s = ready(pg, "scan/?r=demoR3port01")
    pg.wait_for_timeout(1200)
    pg.click(".pip-exp"); pg.wait_for_url("**/video/**", timeout=8000); pg.wait_for_selector(".vo-stage")
    u = urlsplit(pg.url); qq = parse_qs(u.query)
    check(f"{tag} expand: opens the full /video/ page with ?r= and the time", u.path == "/video/" and qq.get("r") == ["demoR3port01"] and qq.get("t", ["x"])[0].isdigit() and pg.locator(".pip").count() == 0, pg.url)
    shot(pg, "7-expanded")
    s = ready(pg, "scan/?r=demoR3port01")
    pg.click(".pip-x"); pg.wait_for_timeout(400)
    gone = pg.locator(".pip, .pip-tab").count() == 0
    shot(pg, "8-closed")
    pg.goto(base + "scan/?r=demoR3port01", wait_until="load"); pg.keyboard.press("Shift"); pg.wait_for_timeout(1500)
    check(f"{tag} close: x removes it, stays closed for the session", gone and pg.locator(".pip").count() == 0)
    ctx.close()

    # landing ?pip=1: Scan now + header + phone CTA bar / launcher stay clickable
    ctx, pg, cdp = new_ctx()
    s = ready(pg, "?pip=1")
    ok, d = clear(pg)
    check(f"{tag} landing ?pip=1: shown, Scan now + header clickable", s["on"] and "r=" not in s["src"] and ok and d["scan"], d)
    shot(pg, "9-landing")
    pg.evaluate("scrollTo(0, document.querySelector('#why').offsetTop)"); pg.wait_for_timeout(1200)
    bar = pg.locator(".mobile-cta.show").count() == 1
    ov = pg.evaluate("""() => { const p = document.querySelector('.pip').getBoundingClientRect(); return [...document.querySelectorAll('.mobile-cta.show, .askai-launcher:not([hidden])')]
      .filter(e => getComputedStyle(e).visibility !== 'hidden').map(e => { const r = e.getBoundingClientRect(); return r.left < p.right && r.right > p.left && r.top < p.bottom && r.bottom > p.top; }); }""")
    ok, d = clear(pg)
    check(f"{tag} landing ?pip=1: past the hero the player sits clear of the CTA bar / Ask-AI launcher", not any(ov) and ok and (bar or not phone) and len(ov) >= 1, [bar, ov, d])
    shot(pg, "10-landing-scrolled")
    ctx.close()

    ctx, pg, cdp = new_ctx(motion="reduce")
    ready(pg, "scan/?r=demoR3port01")
    td = pg.evaluate("() => getComputedStyle(document.querySelector('.pip')).transitionDuration")
    check(f"{tag} motion: prefers-reduced-motion = no transitions", all(float(x.strip()[:-1]) == 0 for x in td.split(",")), td)
    ctx.close()
    if engine == "webkit":
        browser.close()
    # allowed: the landing's lazy demo iframe's disclosed Google Fonts (aborted here, hence ERR_FAILED); Playwright's WebKit build has
    # no native media-control icons ("Button failed to load", the /video/ page's own <video controls>, also without the player)
    hosts = sorted({urlsplit(x).hostname for x in net["outside"] if x.startswith("http")} - FONT_HOSTS)
    errs = [x for x in net["errors"] if "net::ERR_FAILED" not in x and not x.startswith("Button failed to load, iconName")]
    check(f"{tag} no request left loopback (but the demo's disclosed fonts), no console / JS errors", not hosts and not errs, hosts + errs[:5])


with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
stub = subprocess.Popen([sys.executable, str(ROOT / "tools" / "scan_stub.py"), "--port", str(port), "--delay", "0.25"]
                        + (["--omit-results"] if omit else []) + (["--omit-profile"] if omit_profile else []),
                        stderr=subprocess.DEVNULL, stdout=subprocess.PIPE)
stub.stdout.readline()
base = f"http://127.0.0.1:{port}/"
# every :hover rule of the page's own stylesheets sits inside @media (hover: hover): a tap on touch leaves nothing painted
DEAD_THUMB = "DEMO0111"   # inline flow: this fixture thumb (a Sites-tab icon, past the 24 tiles) answers 404
# titles whose "open ↗" pill wrapped onto a line with no title text (its vertical centre off the last text line)
# std-dev of the luminance of a PNG screenshot (base64), decoded in the page: ~0 = a flat, empty slot
PIX_SD = """async ([b64, r]) => { const im = new Image(); im.src = 'data:image/png;base64,' + b64; await im.decode();
  const k = im.width / innerWidth, w = Math.max(1, Math.round(r[2] * k)), h = Math.max(1, Math.round(r[3] * k));
  const c = document.createElement('canvas'); c.width = w; c.height = h; const x = c.getContext('2d'); x.drawImage(im, r[0] * k, r[1] * k, w, h, 0, 0, w, h);
  const d = x.getImageData(0, 0, w, h).data; let n = 0, s = 0, s2 = 0;
  for (let i = 0; i < d.length; i += 4) { const l = .2126 * d[i] + .7152 * d[i + 1] + .0722 * d[i + 2]; n++; s += l; s2 += l * l; }
  return Math.round(Math.sqrt(Math.max(0, s2 / n - (s / n) ** 2)) * 10) / 10; }"""
GO_ALONE = """() => [...document.querySelectorAll('#g-panel .g-title .g-go')].filter(go => {
  const r = document.createRange(), host = go.closest('.g-title'), g = go.getBoundingClientRect();
  if (!g.height) return false;
  const w = document.createTreeWalker(host, NodeFilter.SHOW_TEXT); let last = null, t;
  while ((t = w.nextNode())) if (!go.contains(t) && t.textContent.trim()) last = t;
  if (!last) return true;
  r.selectNodeContents(last); const rs = [...r.getClientRects()], lr = rs[rs.length - 1];
  return Math.abs((lr.top + lr.bottom) / 2 - (g.top + g.bottom) / 2) > 12;
}).map(go => go.closest('.g-title').textContent.slice(0, 50))"""
BARE_HOVER = """() => { const out = [], walk = (rules, gated) => { for (const r of rules) {
    if (r.cssRules && !r.selectorText) walk(r.cssRules, gated || /hover:\\s*hover/.test(r.conditionText || (r.media && r.media.mediaText) || ''));
    else if (r.selectorText && /:hover/.test(r.selectorText) && !gated) out.push(r.selectorText); } };
  for (const sh of document.styleSheets) { try { walk(sh.cssRules, false); } catch (e) {} } return out; }"""
API = f"http://localhost:{port}"   # the stub injects the other loopback name as data-api

try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for vp_name, vp in VIEWPORTS:
            if "scan" in SCENARIOS:
                scan_flow(browser, vp_name, vp)
                huge_flow(browser, vp_name, vp)
            if "personalize" in SCENARIOS:
                personalize_flow(browser, vp_name, vp)
            if "askai" in SCENARIOS:
                askai(browser, vp_name, vp)
            if "inline" in SCENARIOS:
                inline_flow(browser, vp_name, vp)
                thumb_paint(pw, vp_name, vp)
            if "tabs" in SCENARIOS:
                tabs_flow(browser, vp_name, vp)
            if "removals" in SCENARIOS:
                removals_flow(browser, vp_name, vp)
            if "pip" in SCENARIOS:
                pip_flow(pw, browser, vp_name, vp)
        if "pip" in SCENARIOS:
            pip_flow(pw, browser, "phone", None, "webkit")   # iPhone 13 (Playwright device), WebKit
        browser.close()
finally:
    stub.terminate()

(out / "e2e-summary.json").write_text(json.dumps({"fails": fails, "omit_results": omit, "omit_profile": omit_profile,
                                                  "scenarios": SCENARIOS, "break_allowlist": BREAK_ALLOWLIST, "break_thumbs": BREAK_THUMBS, "break_people": BREAK_PEOPLE,
                                                  "break_incremental": BREAK_INCREMENTAL, "break_tuck": BREAK_TUCK,
                                                  "measured": MEASURED}, indent=1))
sys.exit(1 if fails else 0)

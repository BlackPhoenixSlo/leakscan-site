"""Scenario `personalize` (see tools/scan_e2e.py for what it proves). Checks named "profile: ..." need the scan result's
`profile` (and the media it unlocks); every other check must stay green when the stub drops it (--omit-profile = the
break-it run). One function per part (A-H), run in order by personalize_flow()."""
import json
import re
import types
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit

from .common import (ACC, FX, PROD_HOSTS, PROFILE, ROOT, bring, cfg, check, hover, new_ctx, occurrences, served, stub_media,
                     top_ok)

NAME, SD, H = PROFILE["display_name"], PROFILE["site_domain"], FX["handle"]   # the fixture's expected profile
NT = ["_blank", "noopener noreferrer nofollow"]
PEOPLE = {"imgs/portrait.webp", "imgs/hero-wide.webp", "imgs/studio-portrait.webp"}   # showcase hero defaults: Pexels people photos (tools/showcase/CREDITS.md)
POTTERY = re.compile(r"brennick|\borla\b|clay|stoneware|galway|kiln|potter|pottery|\bpots?\b|glaze|wheel|\bmugs?\b|"
                     r"ireland|irish|celadon|ceramic|420 grams", re.I)
PRONOUN = re.compile(r"\b(she|her|hers|herself)\b", re.I)
DEMO_PAGES = ["", "about.html", "links.html", "timeline.html", "verify.html", "blog.html", "statement.html",
              "blog/post-1.html", "blog/post-2.html", "blog/post-3.html", "blog/own-1.html", "blog/own-2.html",
              "blog/own-3.html", "404.html"]
ORLA_POSTS = ["blog/post-1.html", "blog/post-2.html", "blog/post-3.html"]
OWN_POSTS = ["blog/own-1.html", "blog/own-2.html", "blog/own-3.html"]   # starter posts: shown only with a profile
# the lazy showcase iframe loaded with its ?r= (slow under load: never a fixed wait; IFRAME_MS = up to 25 s)
IFRAME_R = "() => { const f = document.querySelector('iframe[data-p=demo]'); return f && f.contentDocument && f.contentDocument.readyState === 'complete' && /\\?r=/.test(f.contentWindow.location.search); }"
IFRAME_MS = 25000
IFRAME_STATE = """() => { const f = document.querySelector('iframe[data-p=demo]'); if (!f) return 'no iframe';
    const d = f.contentDocument, r = f.getBoundingClientRect();
    return {src: f.getAttribute('src'), top: Math.round(r.top), h: Math.round(r.height), vh: innerHeight, y: Math.round(scrollY),
      href: d && d.location.href.replace(location.origin, ''), ready: d && d.readyState,
      pending: d ? [...d.images].filter(i => !i.complete).map(i => (i.currentSrc || i.getAttribute('src') || '').slice(-50)) : null}; }"""
# leak-page socials on platforms the profile does not have (the discovered Instagram never replaces hers)
FOUND = [s["url"] for s in FX["aliases"]["socials"] if s["platform"] not in ACC]
# what personalization shows: rows it hid (data-p-off) are out; a Before / After tab that is not selected is not "hidden"
texts = lambda page, sel: page.eval_on_selector_all(sel, "els => els.filter(e => !e.closest('[data-p-off]')).map(e => e.textContent.trim())")
shown = lambda page, sel: page.eval_on_selector_all(sel, "els => els.filter(e => getComputedStyle(e).display !== 'none').length")


# the demo iframe's loads from now on (LOADS), where it is (FRAME_NOW), and whether it has loaded `page` (FRAME_AT)
LOADS = """() => { const f = document.querySelector('iframe[data-p=demo]'); window.__fl = [];
    if (!f.__fl) { f.__fl = 1; f.addEventListener('load', () => window.__fl.push(f.contentWindow.location.href.replace(location.origin, ''))); } }"""
FRAME_NOW = """() => { const w = document.querySelector('iframe[data-p=demo]').contentWindow;
    return {path: w.location.pathname, search: w.location.search, loads: window.__fl}; }"""
FRAME_AT = """(p => { const w = document.querySelector('iframe[data-p=demo]').contentWindow;
    return w.location.pathname.endsWith('/showcase/' + p) && w.document.readyState === 'complete'; })"""


TG_DEFAULT = ["Free scan: type your handle", "#scan", "#i-scan-search", None]
TG_BAR = """() => { const a = document.querySelector('.mobile-cta');
  return [a.textContent.trim(), a.getAttribute('href'), a.querySelector('use').getAttribute('href'), a.getAttribute('target')]; }"""


def tg_bar(page):
    return page.evaluate(TG_BAR)


def tg_shot(page, name):
    """Phone: the sticky bar in view (hero scrolled away, #pricing on screen), viewport screenshot."""
    if not page.evaluate("innerWidth < 720"):
        return
    bring(page, "#pricing", "center")
    try:
        page.wait_for_selector(".mobile-cta.show", timeout=3000)
    except Exception:
        pass
    page.wait_for_timeout(400)
    page.screenshot(path=str(cfg.out / name))


def wait_demo(page):
    """the landing's demo iframe loaded with its ?r=; a timeout raises with the iframe's state (the flow's FAIL line)"""
    try:
        page.wait_for_function(IFRAME_R, timeout=IFRAME_MS)
    except Exception as e:
        raise RuntimeError(f"demo iframe not loaded with ?r= in {IFRAME_MS // 1000} s: {json.dumps(page.evaluate(IFRAME_STATE))}") from e


def baseline_index():
    """This tree's index.html without personalize.js / inline-scan.js (the page those scripts must leave alone when
    there is no slug), with the stub's data-api injected like the stub does."""
    html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    html = re.sub(r'<script src="js/(personalize|inline-scan)\.js" defer></script>\n', "", html)
    return "no-p-scripts", re.sub(r"<body\b", f'<body data-api="{cfg.api}"', html, count=1)


def no_slug(t):
    """No slug: visible text byte-identical to the page without personalize.js, no API call"""
    tag, net, vp_name = t.tag, t.net, t.vp_name
    ctx = t.ctx()
    page = ctx.new_page()
    net["api"].clear()
    page.goto(cfg.base, wait_until="load")
    page.wait_for_timeout(1200)
    now = page.evaluate("document.body.innerText")
    no_api = list(net["api"])
    sha, html = baseline_index()
    ctx2 = t.ctx()
    ctx2.route(cfg.base, lambda r, _q: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=html))
    p2 = ctx2.new_page()
    p2.goto(cfg.base, wait_until="load")
    p2.wait_for_timeout(1200)
    then = p2.evaluate("document.body.innerText")
    check(f"{tag} no slug: visible text identical to the page without the scripts", now == then, f"{len(now)} vs {len(then)} chars")
    check(f"{tag} no slug: no API call", not no_api, no_api)
    check(f"{tag} tgcta: no slug: sticky bar = 'Free scan: type your handle' → #scan (scan icon)", tg_bar(page) == TG_DEFAULT, tg_bar(page))
    tg_shot(page, f"{vp_name}-p0-bar-default.png")
    static = page.evaluate("""() => ({links: document.querySelectorAll('.ba .phone a').length,
        roles: [...document.querySelectorAll('.ba .phone')].map(p => p.getAttribute('role') + ':' + /^Illustration/.test(p.getAttribute('aria-label'))),
        hidden: [...document.querySelectorAll('.ba .phone-screen')].map(s => s.getAttribute('aria-hidden')), hint: !!document.querySelector('.ba-hint'),
        band: [document.querySelector('.phone-free').getAttribute('role'), document.querySelectorAll('.phone-free a').length, document.querySelectorAll('#panel-free-images .m-illus .gi-card').length],
        lav: [...document.querySelectorAll('.report-card .report-rows .lav')].map(e => e.textContent)})""")
    check(f"{tag} no slug: phones = labelled illustrations (groups: their tabs are buttons), rows not links, no tap hint", static["links"] == 0
          and static["roles"] == ["group:true", "group:true"] and static["hidden"] == [None, None] and not static["hint"], static)
    check(f"{tag} no slug: #free phone = static illustration (9 blurred tiles, no links), hero rows = blurred site marks (no letters)",
          static["band"] == ["group", 0, 9] and static["lav"] == ["", "", "", ""], static)
    bring(page, "#showcase")
    try:
        page.wait_for_function("() => { const f = document.querySelector('iframe[data-p=demo]'); const i = f && f.contentDocument && f.contentDocument.querySelector('img.hero__bg'); return i && i.complete && i.naturalWidth > 0; }", timeout=IFRAME_MS)
    except Exception:
        pass
    hero0 = page.evaluate("() => { const i = document.querySelector('iframe[data-p=demo]').contentDocument.querySelector('img.hero__bg'); return [i.getAttribute('src'), i.alt, i.naturalWidth]; }")
    check(f"{tag} no slug: showcase hero = a people photo (Pexels series, credited)", hero0[0] in PEOPLE and "Orla" in hero0[1] and hero0[2] > 0, hero0)
    page.wait_for_timeout(500)
    page.locator("#showcase").screenshot(path=str(cfg.out / f"{vp_name}-p0-showcase-default.png"))
    ctx2.close()
    ctx.close()


def landing(t):
    """Landing ?r=<fixture slug>"""
    tag, vp_name = t.tag, t.vp_name
    stub_media(FX["slug"])
    ctx = t.ctx()
    page = ctx.new_page()
    page.goto(cfg.base + "?r=" + FX["slug"], wait_until="load")
    page.wait_for_selector("[data-p=scanned]:not([hidden])", timeout=9000)
    check(f"{tag} hero line links back to the report", "Scanned @demo.creator" in page.locator("[data-p=scanned]").inner_text()
          and page.locator("[data-p=scanned] a").evaluate("a => a.href") == urljoin(page.url, "scan/?r=" + FX["slug"]))
    page.locator(".hero").screenshot(path=str(cfg.out / f"{vp_name}-p1-hero-line.png"))
    want_tg = f"Hi Jaka, I ran the free scan. My report link and handle: {cfg.base}scan/?r={FX['slug']} @demo.creator"
    tb = tg_bar(page)
    check(f"{tag} tgcta: ?r=: sticky bar = 'DM me on Telegram' (send icon) → t.me/jakabasej, #contact prefill + absolute report link + @handle, URL-encoded",
          tb == ["DM me on Telegram", "https://t.me/jakabasej?text=" + quote(want_tg, safe="!*'()"), "#i-send", None]
          and parse_qs(urlsplit(tb[1]).query).get("text") == [want_tg], tb)
    (cfg.out / f"{vp_name}-tgcta-href.txt").write_text(f"no slug: {TG_DEFAULT[1]}\n?r={FX['slug']}: {tb[1]}\ndecoded text: {parse_qs(urlsplit(tb[1]).query).get('text')}\n")
    tg_shot(page, f"{vp_name}-p1-bar-telegram.png")
    d = served(FX["slug"])   # the oracle: what the API sent
    occ = occurrences(d["hits"])
    # #free = one Before / After block: Before = her scan (js/free-phone.js: Google for @handle), After = her own pages
    check(f"{tag} profile: After phone searches for the name, Before for her @handle",
          texts(page, "[data-p=search]") == [NAME] and texts(page, ".phone-free [data-p=scan-handle]") == ["@demo.creator"],
          (texts(page, "[data-p=search]"), texts(page, ".phone-free [data-p=scan-handle]")))
    bring(page, "#free")
    page.wait_for_timeout(600)
    free = page.evaluate("""() => ({rows: [...document.querySelectorAll('.phone-free [data-live=free-all] a.m-link')].map(a => [a.querySelector('.m-site').textContent, a.href, a.target]),
        label: document.querySelector('.phone-free').getAttribute('aria-label'), send: document.querySelector('[data-free-send]').href})""")
    served_urls = {h["url"] for h in d["hits"]}
    check(f"{tag} Before phone: her own results (served hits, new tab), labelled for her handle, caption link sends the report",
          free["rows"] and all(r[1] in served_urls and r[2] == "_blank" for r in free["rows"]) and free["label"] == "Google results for @demo.creator"
          and free["send"].startswith("https://t.me/jakabasej?text=") and FX["slug"] in unquote(free["send"]), free)
    check(f"{tag} profile: Instagram row = name (@ig)", texts(page, '[data-p="ig"] .m-title') == [f"{NAME} (@{ACC['instagram']['handle']})"],
          texts(page, '[data-p="ig"] .m-title'))
    after = [page.locator(f'[data-p="{k}"] .m-site').inner_text() for k in ("own", "blog")] + [
        page.locator('[data-p="own"] .m-title').inner_text(), page.locator('[data-p="tt"] .m-title').inner_text()]
    check(f"{tag} profile: after phone site / blog / TikTok", after == [SD, f"{SD} › blog", f"{NAME}: Official site", "@" + ACC["tiktok"]["handle"]], after)
    gone = page.locator('[data-p="gone"] .m-site').inner_text()
    check(f"{tag} after phone: removed row = the top leak domain by the served hits' occurrences", top_ok([gone], occ, 1), (gone, occ))
    lav = page.eval_on_selector_all('.ba [data-p="gone"] .fav', "els => els.map(e => [e.textContent, getComputedStyle(e).backgroundColor])")
    check(f"{tag} after phone: removed row gets a letter avatar like the hero card", [l[0] for l in lav] == [gone[0].upper()]
          and all(l[1] != "rgb(215, 210, 204)" for l in lav), lav)
    page.locator("#showcase .ba").screenshot(path=str(cfg.out / f"{vp_name}-p2-before-after.png"))
    ph = page.evaluate("""() => {
        const r = k => [...document.querySelectorAll(`.ba [data-p="${k}"] > a.m-link`)].map(a => [a.getAttribute('href'), a.target, a.rel]);
        return {rows: Object.fromEntries(['ig', 'tt', 'own', 'blog', 'gone'].map(k => [k, r(k)])),
          roles: [...document.querySelectorAll('.ba .phone')].map(p => [p.getAttribute('role'), p.getAttribute('aria-label')]),
          hidden: [...document.querySelectorAll('.ba .phone-screen')].map(s => s.getAttribute('aria-hidden')),
          buried: document.querySelectorAll('.ba [aria-hidden=true] a, .ba [role=img] a').length,
          hint: (document.querySelector('.ba-hint') || {}).textContent};
    }""")
    NT = ["_blank", "noopener noreferrer nofollow"]
    want_rows = {"ig": [[ACC["instagram"]["url"]] + NT], "tt": [[ACC["tiktok"]["url"]] + NT], "own": [["#showcase", "", ""]],
                 "blog": [["#showcase", "", ""]], "gone": [["#pricing", "", ""]]}
    check(f"{tag} phones: profile: every After row links (IG / TikTok → her accounts, site → #showcase, Removed → #pricing)",
          ph["rows"] == want_rows, ph["rows"])
    check(f"{tag} phones: labelled groups, no aria-hidden over links, 'Tap a result to open it'",
          [r[0] for r in ph["roles"]] == ["group", "group"] and all(r[1] and not r[1].startswith("Illustration") for r in ph["roles"])
          and ph["hidden"] == [None, None] and ph["buried"] == 0 and ph["hint"] == "Tap a result to open it", ph)
    hov = None
    page.click("#ba-tab-after")
    if page.locator('.ba [data-p="own"] a').count():   # absent under --break-phones: fail the check, don't crash the run
        hover(page, '.ba [data-p="own"] a')
        page.wait_for_timeout(300)   # the .15 s tint transition
        hov = page.eval_on_selector('.ba [data-p="own"] a', "a => [getComputedStyle(a).backgroundColor, getComputedStyle(a.querySelector('.m-title')).textDecorationLine, getComputedStyle(a).cursor]")
    check(f"{tag} phones: row hover = tint + underlined title + pointer (desktop; touch: no sticky tint)", bool(hov) and hov[2] == "pointer" and (
          (hov[0] != "rgba(0, 0, 0, 0)" and hov[1] == "underline") if page.evaluate("matchMedia('(hover: hover)').matches") else (hov[0] == "rgba(0, 0, 0, 0)" and hov[1] == "none")), hov)
    page.locator("#website").screenshot(path=str(cfg.out / f"{vp_name}-p2b-phones-hover.png"))
    page.mouse.move(0, 0)
    check(f"{tag} profile: showcase url bar = site_domain", page.locator("[data-p=site-url]").inner_text() == SD)
    check(f"{tag} showcase iframe + button carry the slug", page.locator("iframe[data-p=demo]").get_attribute("src") == "showcase/?r=" + FX["slug"]
          and page.locator("a[data-p=demo]").get_attribute("href") == "showcase/?r=" + FX["slug"])
    bring(page, "#showcase")
    wait_demo(page)
    frame = page.frame(url=re.compile(r"/showcase/\?r="))
    try:
        frame.wait_for_function(f"() => document.body.innerText.includes({json.dumps(NAME)})", timeout=9000)
    except Exception:
        pass
    ft = frame.evaluate("document.body.innerText")
    check(f"{tag} profile: demo iframe shows name, location, handles", all(x in ft for x in (
        NAME, PROFILE["location"], "@" + ACC["instagram"]["handle"], "@" + ACC["tiktok"]["handle"])), ft[:160])
    check(f"{tag} profile: demo iframe has no pottery / Orla text", not POTTERY.search(ft + frame.title()), POTTERY.findall(ft)[:8])
    try:
        frame.wait_for_function("() => /\\/api\\/media\\//.test(document.querySelector('img.hero__bg').getAttribute('src'))", timeout=8000)
    except Exception:
        pass
    check(f"{tag} profile: demo iframe hero swapped to API media", "/api/media/" in (frame.locator("img.hero__bg").get_attribute("src") or ""))
    hsrc = frame.locator("img.hero__bg").get_attribute("src") or ""
    check(f"{tag} profile: iframe hero src passes MEDIA_RE (API origin /api/media/<slug>/<n>.jpg)",
          re.fullmatch(re.escape(cfg.api) + r"/api/media/" + FX["slug"] + r"/\d+\.jpg", hsrc) is not None, hsrc)
    page.wait_for_timeout(700)
    page.locator("#showcase").screenshot(path=str(cfg.out / f"{vp_name}-p3-showcase-iframe.png"))
    ctx.close()


def demo_media(t):
    """Demo direct: progressive media swap, no layout jump, slug kept on links"""
    tag, vp_name = t.tag, t.vp_name
    stub_media(FX["slug"])
    ctx = t.ctx()
    page = ctx.new_page()
    page.goto(cfg.base + "showcase/?r=" + FX["slug"], wait_until="load")
    box0 = page.locator("img.hero__bg").bounding_box()
    try:
        page.wait_for_function("() => /\\/api\\/media\\//.test(document.querySelector('img.hero__bg').getAttribute('src'))", timeout=6000)
    except Exception:
        pass
    pending = (page.locator("img.hero__bg").get_attribute("src") or "", page.locator('img[data-p-media="1"]').get_attribute("src") or "",
               shown(page, "[data-p-media-only]"))
    check(f"{tag} profile: media pending: hero + portrait swapped, gallery still hidden",
          pending[0].startswith(cfg.api + "/api/media/") and pending[1].startswith(cfg.api + "/api/media/") and pending[2] == 0, pending)
    page.wait_for_timeout(700)
    box1 = page.locator("img.hero__bg").bounding_box()
    pbox = page.locator('img[data-p-media="1"]').bounding_box()
    check(f"{tag} profile: no layout jump on swap", box0 == box1 and pbox and abs(pbox["width"] / pbox["height"] - 2400 / 3200) < .02, f"{box0} {box1} {pbox}")
    page.screenshot(path=str(cfg.out / f"{vp_name}-p4-demo-media-pending.png"))
    try:
        page.wait_for_function("() => [...document.querySelectorAll('[data-p-media-only]')].filter(e => getComputedStyle(e).display !== 'none').length === 4", timeout=9000)
    except Exception:
        pass
    bring(page, "[data-p-gallery]")
    try:
        page.wait_for_function("() => [...document.querySelectorAll('[data-p-media-only] img')].every(e => e.complete && e.naturalWidth > 0)", timeout=6000)
    except Exception:
        pass
    gal = page.eval_on_selector_all("[data-p-media-only] img", "els => els.map(e => [e.getAttribute('src'), e.naturalWidth])")
    check(f"{tag} profile: media ready: 4 gallery photos fade in from the API", shown(page, "[data-p-media-only]") == 4
          and all(g[0].startswith(cfg.api + "/api/media/") and g[1] > 0 for g in gal), gal)
    page.wait_for_timeout(400)   # last batch's photos preload + fade
    alts = page.eval_on_selector_all("img[data-p-src]", "els => [...new Set(els.map(e => e.alt))]")
    tots = {a.rsplit(" of ", 1)[-1] for a in alts}
    check(f"{tag} profile: media alts tell the photos apart ('<name>, photo n of N', one N for all after batches)", len(alts) >= 4
          and all(re.fullmatch(re.escape(PROFILE["display_name"]) + r", photo \d of \d", a) for a in alts) and len(tots) == 1, alts)
    page.wait_for_timeout(700)
    page.screenshot(path=str(cfg.out / f"{vp_name}-p5-demo-media-ready.png"))
    about = page.locator("nav a[href*='about.html']").first.get_attribute("href") or ""
    check(f"{tag} profile: internal demo links keep ?r=", "about.html?r=" + FX["slug"] in about, about)
    if vp_name == "desktop":
        for rel in DEMO_PAGES:
            page.goto(cfg.base + "showcase/" + rel + "?r=" + FX["slug"], wait_until="load")
            try:
                page.wait_for_function(f"() => document.title.includes({json.dumps(NAME)})", timeout=6000)
            except Exception:
                pass
            t = page.evaluate("document.body.innerText")
            alts = " ".join(page.eval_on_selector_all("img", "els => els.filter(e => e.offsetParent !== null).map(e => e.alt)"))
            check(f"{tag} profile: showcase/{rel or 'index'}: name, no pottery, no she/her", NAME in page.title()
                  and NAME.upper() in page.locator(".nav__logo").inner_text().upper()
                  and not POTTERY.search(t + page.title() + alts) and not PRONOUN.search(t),
                  (POTTERY.findall(t + alts) + PRONOUN.findall(t))[:6])
        page.goto(cfg.base + "showcase/links.html?r=" + FX["slug"], wait_until="load")
        page.wait_for_timeout(1500)
        btns = page.eval_on_selector_all(".p-links a", "els => els.map(e => [e.href, e.target])")
        av = page.eval_on_selector("img.links-avatar", "e => [e.getAttribute('src'), e.naturalWidth]")
        check(f"{tag} profile: links page = the profile accounts + leak-page socials for new platforms, avatar from the API",
              [b[0] for b in btns] == [a["url"] for a in PROFILE["accounts"]] + FOUND and all(b[1] == "_blank" for b in btns)
              and av[0] == f"{cfg.api}/api/avatar/{FX['slug']}" and av[1] == 48, f"{btns} {av}")
        page.screenshot(path=str(cfg.out / f"{vp_name}-p6-demo-links.png"), full_page=True)
    ctx.close()


def media_modes(t):
    """Media none / 404: placeholders stay, polling stops, scan page status hidden"""
    tag, net, vp_name = t.tag, t.net, t.vp_name
    for mode in ("none", "404"):
        stub_media(FX["slug"], mode)
        ctx = t.ctx()
        page = ctx.new_page()
        net["api"].clear()
        page.goto(cfg.base + "showcase/?r=" + FX["slug"], wait_until="load")
        page.wait_for_timeout(7500)
        polls = [u for u in net["api"] if re.search(r"/api/media/[^/]+$", u)]
        hero = page.locator("img.hero__bg").get_attribute("src")
        check(f"{tag} profile: media {mode}: placeholders kept, galleries hidden, polling stopped",
              hero == "imgs/portrait.webp" and shown(page, "[data-p-media-only]") == 0 and len(polls) == (1 if mode == "none" else 2),
              f"hero={hero} polls={len(polls)}")
        page.goto(cfg.base + "scan/?r=" + FX["slug"], wait_until="load")
        page.wait_for_selector("#report:not([hidden])", timeout=6000)
        page.wait_for_timeout(4000)
        check(f"{tag} media {mode}: scan page status line hidden", page.locator("#after-media").is_hidden())
        ctx.close()
    stub_media(FX["slug"], "relative")
    ctx = t.ctx()
    page = ctx.new_page()
    page.goto(cfg.base + "showcase/?r=" + FX["slug"], wait_until="load")
    try:
        page.wait_for_function("() => document.querySelector('img.hero__bg').naturalWidth === 1067", timeout=6000)
    except Exception:
        pass
    rel = page.eval_on_selector("img.hero__bg", "e => [e.getAttribute('src'), e.naturalWidth]")
    check(f"{tag} profile: same-origin relative media srcs accepted, loaded via the API base", rel == [f"{cfg.api}/api/media/{FX['slug']}/0.jpg", 1067], rel)
    ctx.close()
    # VPS layout: site served by the API container (no data-api → API = ''), backend emits srcs on the production scan
    # host (its PUBLIC_ORIGIN). They must pass and load from the page's own origin; the scan host is never requested.
    # Bypass (declared): the showcase HTML's injected data-api is stripped on the wire, so the page runs with API = ''.
    stub_media(FX["slug"], "scanhost")
    ctx = t.ctx()
    page = ctx.new_page()
    page.route(re.compile(r"/showcase/(\?.*)?$"), lambda r: r.fulfill(response=(res := r.fetch()),
               body=re.sub(r' data-api="[^"]*"', "", res.text(), count=1)))
    n_out = len(net["outside"])
    page.goto(cfg.base + "showcase/?r=" + FX["slug"], wait_until="load")
    try:
        page.wait_for_function("() => [...document.querySelectorAll('img[data-p-media]')].every(e => /\\/api\\/media\\//.test(e.getAttribute('src')))", timeout=12000)
        bring(page, "[data-p-gallery]")
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
    page.screenshot(path=str(cfg.out / f"{vp_name}-p5b-demo-media-scanhost.png"))
    ctx.close()
    stub_media(FX["slug"])


def scan_only(t):
    """Scan only (profile null): phones from the scan, demo stays the fictional creator"""
    tag, vp_name = t.tag, t.vp_name
    ctx = t.ctx()
    page = ctx.new_page()
    page.goto(cfg.base + "?r=demoNoProf01", wait_until="load")
    page.wait_for_selector("[data-p=scanned]:not([hidden])", timeout=9000)
    got = (texts(page, "[data-p=search]"), page.locator('[data-p="gone"] .m-site').inner_text(), shown(page, '[data-p="ig"], [data-p="tt"]'),
           page.locator('[data-p="own"] .m-site').inner_text(), page.locator("[data-p=site-url]").inner_text())
    check(f"{tag} scan-only: After phone uses the handle, Removed = her top leak domain, unknown IG/TikTok rows hidden, url bar default",
          got[0] == [H] and top_ok([got[1]], occurrences(served("demoNoProf01")["hits"]), 1)
          and got[2:] == (0, re.sub(r"[^a-z0-9-]", "", H.lower()) + ".com", "yourname.com"), got)
    bring(page, "#showcase")
    wait_demo(page)
    frame = page.frame(url=re.compile(r"/showcase/\?r=demoNoProf01"))
    try:
        frame.wait_for_function("() => document.body.innerText.includes('Orla Brennick')", timeout=9000)
    except Exception:
        pass
    page.wait_for_timeout(1500)   # room for a wrong personalization to land
    ft = frame.evaluate("document.body.innerText") if frame else ""
    check(f"{tag} scan-only: demo stays Orla, no @handle in its name slots", "Orla Brennick" in ft and H not in ft
          and frame.locator(".nav__logo").inner_text().upper() == "ORLA BRENNICK", ft[:120])
    page.locator("#website").screenshot(path=str(cfg.out / f"{vp_name}-p7-scan-only.png"))
    # C25: navigating inside the demo is never undone: its About link carries ?r= (scan-only too) and stays there; a page
    # opened without ?r= (an early click, the API down) is left alone, not sent back to the demo home
    page.evaluate(LOADS)
    bring(page, "iframe[data-p=demo]", "center")   # its own top nav clear of the landing's sticky one
    frame.locator("a[href*='about.html']:visible").first.click()
    try:
        page.wait_for_function(f"() => {FRAME_AT}('about.html')", timeout=9000)
    except Exception:
        pass
    page.wait_for_timeout(1500)   # room for a bounce
    at = page.evaluate(FRAME_NOW)
    check(f"{tag} scan-only: an in-demo link (About) opens about.html?r=demoNoProf01 and stays there (one load, no bounce)",
          at["path"].endswith("/showcase/about.html") and at["search"] == "?r=demoNoProf01" and len(at["loads"]) == 1, at)
    page.evaluate(LOADS)
    page.evaluate("() => { const w = document.querySelector('iframe[data-p=demo]').contentWindow; w.location.href = new URL('links.html', w.location.href).href; }")
    try:
        page.wait_for_function(f"() => {FRAME_AT}('links.html')", timeout=9000)
    except Exception:
        pass
    page.wait_for_timeout(1500)
    at = page.evaluate(FRAME_NOW)
    check(f"{tag} scan-only: a page opened inside the demo without ?r= stays (never sent back to the demo home)",
          at["path"].endswith("/showcase/links.html") and at["search"] == "" and len(at["loads"]) == 1, at)
    page.close()
    # C25: the stuck demo (round 4) is still corrected: the lazy iframe's own first load of showcase/ landing after the
    # src change (Chrome's race, 1 in 16 measured), forced here: its ?r= request held, the bare page committed instead
    page, held = ctx.new_page(), []
    page.route(re.compile(r"/showcase/\?r=demoNoProf01$"), lambda r: held.append(r) if not held else r.continue_())
    page.goto(cfg.base + "?r=demoNoProf01", wait_until="domcontentloaded")   # no load event while the iframe's request is held
    page.wait_for_selector("[data-p=scanned]:not([hidden])", timeout=9000)
    page.evaluate(LOADS)
    bring(page, "#showcase")
    for _ in range(90):
        if held:
            break
        page.wait_for_timeout(100)
    page.evaluate("() => document.querySelector('iframe[data-p=demo]').contentWindow.location.replace(new URL('showcase/', location.href).href)")
    try:
        page.wait_for_function(IFRAME_R, timeout=9000)
    except Exception:
        pass
    page.wait_for_timeout(1000)
    at = page.evaluate(FRAME_NOW)
    check(f"{tag} scan-only: a stale load of showcase/ without ?r= before the first ?r= load is sent on to showcase/?r=demoNoProf01",
          bool(held) and at["search"] == "?r=demoNoProf01" and at["path"].endswith("/showcase/")
          and (lambda l: l[-1:] == ["?r=demoNoProf01"] and "" in l and set(l) == {"", "?r=demoNoProf01"})(
              [u.split("/showcase/")[-1] for u in at["loads"]]), at)
    page.goto(cfg.base + "?r=demoFoundIG1", wait_until="load")
    page.wait_for_selector("[data-p=scanned]:not([hidden])", timeout=9000)
    ig = [s["handle"] for s in FX["aliases"]["socials"] if s["platform"] == "instagram"][0]
    got = (texts(page, '[data-p="ig"] .m-title'), shown(page, '[data-p="tt"]'))
    check(f"{tag} aliases: scan-only: leak-page Instagram fills the IG row", got == ([f"{H} (@{ig})"], 0), got)
    ctx.close()


def blog(t):
    """Blog: no profile → Orla's 3 posts exactly as before; profile → the 3 starter posts in her name (cards + pages)"""
    tag, vp_name = t.tag, t.vp_name
    cards = ("() => [...document.querySelectorAll('.blog-card')].filter(c => c.offsetParent !== null)"
             ".map(c => c.querySelector('a.blog-card__link').getAttribute('href'))")
    ctx = t.ctx()
    page = ctx.new_page()
    seen = {}
    for q in ("", "?r=demoNoProf01"):
        page.goto(cfg.base + "showcase/blog.html" + q, wait_until="load")
        page.wait_for_timeout(1500)
        seen[q] = (page.evaluate(cards), page.evaluate("document.body.innerText"), page.title())
        check(f"{tag} blog {q or 'no slug'}: Orla's 3 posts, no starter cards{', ?r= kept on them' if q else ''}",
              [urlsplit(h).path.split("/showcase/")[-1] for h in seen[q][0]] == ORLA_POSTS
              and all((urlsplit(h).query == q[1:]) for h in seen[q][0]) and "Orla" in seen[q][2], seen[q][0])
    check(f"{tag} blog: scan-only page text identical to no slug", seen[""][1] == seen["?r=demoNoProf01"][1])
    stub_media(FX["slug"])
    page.goto(cfg.base + "showcase/blog.html?r=" + FX["slug"], wait_until="load")
    try:
        page.wait_for_function(f"() => document.title.includes({json.dumps(NAME)})", timeout=6000)
    except Exception:
        pass
    hrefs = page.evaluate(cards)
    txt = page.evaluate("document.body.innerText")
    check(f"{tag} profile: blog: 3 starter cards (?r= kept), Orla's hidden, no pottery / Orla, setup note",
          [urlsplit(h).path.split("/showcase/")[-1] for h in hrefs] == OWN_POSTS
          and all(f"r={FX['slug']}" in h for h in hrefs) and not POTTERY.search(txt + page.title())
          and f"Prewritten for {PROFILE['first_name']}" in txt, (hrefs, POTTERY.findall(txt)[:6]))
    page.screenshot(path=str(cfg.out / f"{vp_name}-p8-blog.png"), full_page=True)
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
              st["h1"] == title and NAME in page.title() and st["author"] == NAME and len(body.split()) >= 350
              and st["media"] == [[True, True], [True, True]] and st["links"] and all(f"r={FX['slug']}" in h for h in st["links"])
              and not POTTERY.search(pt + page.title()) and not PRONOUN.search(pt),
              (st["h1"], st["author"], len(body.split()), st["media"], POTTERY.findall(pt)[:4], PRONOUN.findall(pt)[:4]))
        page.screenshot(path=str(cfg.out / f"{vp_name}-p8-{rel.replace('/', '-').removesuffix('.html')}.png"), full_page=True)
        page.goto(cfg.base + "showcase/blog.html?r=" + FX["slug"], wait_until="load")
        page.wait_for_function(f"() => document.title.includes({json.dumps(NAME)})", timeout=6000)
    ctx.close()


def malicious(t):
    """Malicious values never reach the DOM"""
    tag, net = t.tag, t.net
    ctx = t.ctx()
    page = ctx.new_page()
    bad = []
    for path in ("?r=evilR3port01", "showcase/?r=evilR3port01", "showcase/about.html?r=evilR3port01", "showcase/links.html?r=evilR3port01"):
        page.goto(cfg.base + path, wait_until="load")
        page.wait_for_timeout(4200 if path.startswith("showcase/?") else 1500)
        if path.startswith("?"):
            bring(page, "#showcase")
            wait_demo(page)   # the iframe's own document is checked too
            page.wait_for_timeout(1500)
        docs = [page.content()] + [f.content() for f in page.frames[1:]]
        for d in docs:
            for needle in ("alert(1)", "javascript:", "onerror", "onload=", "A" * 60, "x" * 400, "evil.example"):
                if needle in d:
                    bad.append(f"{path}: {needle}")
        if path.startswith("?"):
            check(f"{tag} profile: malicious profile falls back to the valid username", texts(page, "[data-p=search]") == ["evil.user"],
                  texts(page, "[data-p=search]"))
            live = texts(page, ".phone-free [data-live=free-all] .m-site")
            check(f"{tag} malicious hits: only the valid domain is shown (Removed row, Before phone)", page.locator('[data-p="gone"] .m-site').inner_text() == "safe-leak.example"
                  and set(live) <= {"safe-leak.example"}, live)
    check(f"{tag} malicious fixture: nothing reaches the DOM, no dialog", not bad and not net["dialogs"], bad + net["dialogs"])
    ctx.close()


def real_flow(t):
    """Real flow: scan → report card → landing (?r=, then localStorage) → reset"""
    tag, vp_name = t.tag, t.vp_name
    stub_media(FX["slug"])
    ctx = t.ctx()
    page = ctx.new_page()
    page.goto(cfg.base + "scan/?p=onlyfans.com&h=demo.creator", wait_until="load")
    page.wait_for_selector("#report:not([hidden])", timeout=15000)
    slug = parse_qs(urlsplit(page.url).query).get("r", [""])[0]
    bring(page, "#after-card")
    try:
        page.wait_for_function("() => document.getElementById('after-media').textContent === 'Photos ready'", timeout=10000)
    except Exception:
        pass
    check(f"{tag} report card links to the landing section + demo", page.locator("#after-link").get_attribute("href") == f"../?r={slug}#website"
          and page.locator("#demo-link").get_attribute("href") == f"../showcase/?r={slug}")
    check(f"{tag} profile: report status line ends at 'Photos ready'", page.locator("#after-media").is_visible()
          and page.locator("#after-media").inner_text() == "Photos ready", page.locator("#after-media").inner_text())
    page.locator("#after-card").screenshot(path=str(cfg.out / f"{vp_name}-p8-report-card.png"))
    last = json.loads(page.evaluate("localStorage.getItem('leakscan.last')") or "{}")
    check(f"{tag} scan writes leakscan.last", last.get("slug") == slug and last.get("handle") == "demo.creator", last)
    with page.expect_navigation():
        page.locator("#after-link").click()
    page.wait_for_selector("[data-p=scanned]:not([hidden])", timeout=9000)
    check(f"{tag} card → landing #website", page.url.endswith(f"/?r={slug}#website"), page.url)
    page.goto(cfg.base, wait_until="load")
    page.wait_for_selector("[data-p=scanned]:not([hidden])", timeout=9000)
    check(f"{tag} profile: landing without ?r= personalizes from localStorage", texts(page, "[data-p=search]") == [NAME])
    page.locator("#website").screenshot(path=str(cfg.out / f"{vp_name}-p9-landing-from-localstorage.png"))
    if page.locator("[data-p=scanned] button").is_visible():
        page.locator("[data-p=scanned] button").click()
    page.wait_for_load_state("load")
    page.wait_for_timeout(1000)
    check(f"{tag} Reset restores the defaults", texts(page, "[data-p=search]") == ["yourname"]
          and page.evaluate("localStorage.getItem('leakscan.last')") is None and page.locator("[data-p=scanned]").is_hidden())
    check(f"{tag} tgcta: Reset → the original sticky bar", tg_bar(page) == TG_DEFAULT, tg_bar(page))
    tg_shot(page, f"{vp_name}-p9-bar-after-reset.png")
    ctx.close()


def public_api(t):
    """A later in-page scan: the leakscan:result event personalizes without reload, twice, with other data"""
    tag = t.tag
    ctx = t.ctx()
    page = ctx.new_page()
    page.goto(cfg.base, wait_until="load")
    page.wait_for_timeout(500)
    api_res = page.evaluate("""async (api) => {
        const get = async s => (await fetch(api + '/api/scan-result/' + s)).json();
        const P = window.LeakScanPersonalize, q = s => [...document.querySelectorAll(s)];
        const fire = d => document.dispatchEvent(new CustomEvent('leakscan:result', {detail: d}));
        const vis = s => q(s).filter(e => getComputedStyle(e).display !== 'none' && !e.hidden).length;
        const snap = () => ({search: q('[data-p=search]').map(e => e.textContent), url: q('[data-p=site-url]')[0].textContent,
            ig: vis('[data-p=ig]'), handles: q('[data-p=report-handle],[data-p=scan-handle]').map(e => e.textContent),
            line: vis('[data-p=scanned]'), gone: q('[data-p=gone] .m-site')[0].textContent, links: q('.ba a.m-link').length,
            hints: q('.ba-hint').length, on: document.documentElement.classList.contains('p-on')});
        const out = {keys: Object.keys(P).sort(), before: snap()};
        fire({}); fire({slug: '<x>'}); out.junk = snap();
        const full = await get('demoR3port01'), bare = await get('demoNoProf01');
        fire(full); fire(full); out.a = snap();
        fire(bare); out.b = snap();
        return out;
    }""", cfg.api)
    check(f"{tag} public API: window.LeakScanPersonalize {{pollMedia}} only; junk leakscan:result changes nothing",
          api_res["keys"] == ["pollMedia"] and api_res["junk"] == api_res["before"] and not api_res["junk"]["on"], api_res)
    a, b2 = api_res["a"], api_res["b"]
    check(f"{tag} phones: event twice = same links, other data re-wires (no IG / TikTok rows without a profile)",
          (a["links"], a["hints"], b2["links"], b2["hints"]) == (5, 1, 3, 1), (a["links"], a["hints"], b2["links"], b2["hints"]))
    check(f"{tag} profile: event personalizes in place, twice = same DOM (one IG row, not two)",
          a["search"] == [NAME] and a["url"] == SD and a["ig"] == 1, a)
    occ = occurrences(served("demoNoProf01")["hits"])
    check(f"{tag} event again with other data resets the slots first",
          b2["search"] == [H] and b2["url"] == "yourname.com" and b2["ig"] == 0
          and b2["handles"] == ["@" + H, "@" + H] and b2["line"] == 1 and occ.get(b2["gone"]) == max(occ.values()), b2)
    ctx.close()


def personalize_flow(browser, vp_name, vp):
    net = {"api": []}
    t = types.SimpleNamespace(tag=f"{vp_name} personalize", net=net, vp_name=vp_name, ctx=lambda: new_ctx(
        browser, vp_name, vp, net, route=lambda r: "/api/" in r.request.url and net["api"].append(r.request.url))[0])
    for part in (no_slug, landing, demo_media, media_modes, scan_only, blog, malicious, real_flow, public_api):
        part(t)
    tag = t.tag
    hosts = {urlsplit(u).hostname for u in net["outside"]}
    check(f"{tag} nothing left loopback (the demo included: no Google Fonts)", not hosts, sorted(hosts))
    check(f"{tag} production hosts never contacted", not any(h in u for u in net["outside"] + net["api"] for h in PROD_HOSTS))
    check(f"{tag} no JS errors", not net["errors"], net["errors"])

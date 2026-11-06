"""Scenario `inline` (see tools/scan_e2e.py for what it proves). The hero form scans on the landing page itself
(js/inline-scan.js + js/scan-engine.js). Checks named "hero: ..." need a fresh scan `result` event; "profile: ..." need
`profile`. One function per part, run in order by inline_flow() on one shared `run` namespace (page, slug, served result)."""
import base64
import json
import re
import types
from urllib.parse import parse_qs, quote, unquote, urlsplit

from .common import (ALSO, BARE_HOVER, FX, PROFILE, TILES, bring, cfg, check, digits, hover, links, new_ctx, occurrences, served,
                     settled_count, stub_media, swipe, tiles_ok, top_ok)

DEAD_THUMB = "DEMO0111"   # this fixture thumb (a Sites-tab icon, past the 24 tiles) answers 404: a fault at the wire
# std-dev of the luminance of a PNG screenshot (base64), decoded in the page: ~0 = a flat, empty slot
PIX_SD = """async ([b64, r]) => { const im = new Image(); im.src = 'data:image/png;base64,' + b64; await im.decode();
  const k = im.width / innerWidth, w = Math.max(1, Math.round(r[2] * k)), h = Math.max(1, Math.round(r[3] * k));
  const c = document.createElement('canvas'); c.width = w; c.height = h; const x = c.getContext('2d'); x.drawImage(im, r[0] * k, r[1] * k, w, h, 0, 0, w, h);
  const d = x.getImageData(0, 0, w, h).data; let n = 0, s = 0, s2 = 0;
  for (let i = 0; i < d.length; i += 4) { const l = .2126 * d[i] + .7152 * d[i + 1] + .0722 * d[i + 2]; n++; s += l; s2 += l * l; }
  return Math.round(Math.sqrt(Math.max(0, s2 / n - (s / n) ** 2)) * 10) / 10; }"""
# the card's height eases (Element.animate on .report-card) and layout shifts (PerformanceObserver, buffered from start)
INIT = ["window.__anim = []; const _a = Element.prototype.animate; Element.prototype.animate = function (k, o) { if (this.classList && this.classList.contains('report-card')) window.__anim.push([k, o && o.duration]); return _a.apply(this, arguments); };",
        "window.__ls = []; try { new PerformanceObserver(l => l.getEntries().forEach(e => window.__ls.push([e.startTime, e.value, e.hadRecentInput]))).observe({type: 'layout-shift', buffered: true}); } catch (e) {}"]
CARD = """() => {
    const c = document.querySelector('.report-card'), L = c.querySelector('.live'), t = s => { const e = L && L.querySelector(s); return e && !e.hidden ? e.textContent.trim() : null; };
    return {live: c.classList.contains('is-live'), title: t('.live-title'), socials: t('.live-socials'), aliases: t('.live-aliases'), count: t('.live-count'),
      status: t('.live-status'), error: L && L.getAttribute('data-error'), empty: t('.live-empty'), more: t('.live-more'),
      rows: [...c.querySelectorAll('.live-rows li')].map(li => { const a = li.querySelector('a'); return {tag: a && a.tagName,
        dom: li.querySelector('.live-dom').textContent, ttl: li.querySelector('.live-ttl').textContent, href: a && a.href,
        target: a && a.target, rel: a && a.rel, badge: li.querySelector('.live-badge').textContent}; }),
      open: L && L.querySelector('.live-open') ? L.querySelector('.live-open').getAttribute('href') : null,
      msgs: L ? [...L.querySelectorAll('[data-msg]')].map(a => a.href) : [], role: c.getAttribute('role')};
}"""
ILL = """() => {
    const s = document.querySelector('.phone-free'), n = s.querySelector('[data-live=free-images] .m-n'), send = document.querySelector('[data-free-send]');
    return {live: s.classList.contains('is-live'), pill: n && n.textContent, label: s.getAttribute('aria-label'), role: s.getAttribute('role'),
      tiles: [...s.querySelectorAll('[data-live=free-images] a.gi-card')].map(a => [a.href, a.target, a.rel, a.querySelector('img') ? a.querySelector('img').src : null]),
      visible_illus: [...s.querySelectorAll('.m-illus .gi-card')].filter(e => e.offsetParent !== null).length,
      send: send.getAttribute('href'), h: Math.round(s.getBoundingClientRect().height)};
}"""
STRIP = """() => {
    const s = document.querySelector('.report-card .live-strip'), c = document.querySelector('.report-card').getBoundingClientRect();
    const pb = document.querySelector('.report-card .live-strip-pause');
    const tr = s && s.querySelector('.live-strip-track'), tx = tr ? new DOMMatrix(getComputedStyle(tr).transform).m41 : 0;
    return s && {x: Math.round(s.scrollLeft - tx), drift: s.getAttribute('data-drift'), card: [c.width, c.height], max: s.scrollWidth - s.clientWidth,
      shifts: window.__ls.slice(), pause: pb ? (pb.offsetParent ? 'shown' : 'none') : null, pauseLabel: pb && pb.getAttribute('aria-label')};
}"""
card = lambda page: page.evaluate(CARD)
ill = lambda page: page.evaluate(ILL)
strip = lambda page: page.evaluate(STRIP)
lcol = lambda page: page.evaluate("() => ['.scan-alt', '.assurances'].map(s => { const r = document.querySelector(s).getBoundingClientRect(); return Math.round(r.top + scrollY); })")
msgs_ok = lambda m, *need: len(m) == 3 and m[0].startswith("https://t.me/jakabasej?text=") and m[1].startswith(
    "https://wa.me/38640703992?text=") and m[2].startswith("mailto:me@jackbase.dev?") and all(all(x in u for x in need) for u in m)
report_url = lambda slug: cfg.base + "scan/?r=" + slug   # E.reportUrl(slug): absolute, from the page's own site root


def ctx_for(browser, vp_name, vp, net, js=True, scheme="light", motion="no-preference"):
    """new_ctx + this scenario's wire fault (DEAD_THUMB → 404), scan POST bodies and main-frame navigations; the
    browser's "Failed to load resource" for a provoked 429 / 400 / aborted scan POST or the 404 thumb is expected."""
    ctx = new_ctx(browser, vp_name, vp, net, init=INIT, java_script_enabled=js, color_scheme=scheme, reduced_motion=motion,
                  route=lambda r: "/api/thumb" in r.request.url and DEAD_THUMB in unquote(r.request.url) and (r.fulfill(status=404, body="") or True),
                  console_ok=lambda m: m.text.startswith("Failed to load resource") and (
                      "/api/public-scan" in (m.location.get("url") or "") or DEAD_THUMB in unquote(m.location.get("url") or "")))[0]

    def on_page(pg):
        pg.on("request", lambda q: q.method == "POST" and "/api/public-scan" in q.url and net["bodies"].append(json.loads(q.post_data)))
        pg.on("framenavigated", lambda f: f == pg.main_frame and net["nav"].append(f.url))
    ctx.on("page", on_page)
    return ctx


def shot(run, page, name, el=None):
    for scheme in ("light", "dark"):
        page.emulate_media(color_scheme=scheme)
        page.wait_for_timeout(80)
        (page.locator(el) if el else page).screenshot(path=str(cfg.out / f"{run.vp_name}-i{name}-{scheme}.png"))
    page.emulate_media(color_scheme="light")


def submit(run, page, h, social=""):
    run.net["bodies"].clear()
    page.locator("#scan input[name=h]").fill(h)
    page.locator("#scan input[name=ig]").fill(social)
    page.locator("#scan button[type=submit]").click()


def settled(page, timeout=15000):
    page.wait_for_function("() => { const c = document.querySelector('.report-card'); return c && !c.hasAttribute('aria-busy') && !document.querySelector('#scan button').disabled; }", timeout=timeout)
    page.wait_for_timeout(250)


def thumb_paint(pw, vp_name, vp):
    """Row thumbs under reduced motion, as a visitor sees them: a fresh browser, three plain scans one after another (no e2e hooks),
    scrolled the moment the report lands. Each thumb: neutral tile under it, opacity 1 at once, photo painted in a plain viewport
    screenshot (an async-decoded thumb once stayed an empty slot here, from the 2nd context on)."""
    b = pw.chromium.launch()
    runs = []
    for n in range(3):
        ctx, _ = new_ctx(b, vp_name, vp, reduced_motion="reduce")
        page = ctx.new_page()
        page.goto(cfg.base, wait_until="load")
        page.wait_for_timeout(500)
        page.locator("#scan input[name=h]").fill("@demo.creator")
        btn = page.locator("#scan button[type=submit]")
        btn.tap() if vp_name == "phone" else btn.click()
        page.wait_for_function("() => { const c = document.querySelector('.report-card'); return c && !c.hasAttribute('aria-busy') && c.querySelector('.live-rows'); }", timeout=15000)
        bring(page, ".report-card .live-strip-box", "center")
        page.wait_for_timeout(3000)
        st = page.evaluate("""() => [...document.querySelectorAll('.report-card .live-rows .live-ico')].map(e => { const i = e.querySelector('img'), r = e.getBoundingClientRect();
          return [getComputedStyle(e).backgroundColor, i ? getComputedStyle(i).opacity : null, i ? i.complete && i.naturalWidth > 0 : null, [r.x + 4, r.y + 4, r.width - 8, r.height - 8]]; })""")
        png = page.screenshot()
        (cfg.out / f"{vp_name}-t{n}-rows-reduced-motion.png").write_bytes(png)
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


def before_submit(run):
    """Before + submit → progress, no navigation"""
    tag, net, vp_name = run.tag, run.net, run.vp_name
    stub_media(FX["slug"])
    ctx = run.new_ctx()
    page = ctx.new_page()
    page.goto(cfg.base, wait_until="load")
    page.wait_for_timeout(300)
    form = page.evaluate("() => { const f = document.getElementById('scan'); return [f.getAttribute('action'), f.getAttribute('method'), [...f.elements].map(e => e.name).filter(Boolean)]; }")
    check(f"{tag} form markup: GET scan/ with h + ig, no platform select", form == ["scan/", "get", ["h", "ig"]], form)
    shot(run, page, "1-before", ".hero")
    bring(page, "#free", "center")
    page.wait_for_timeout(700)
    shot(run, page, "1-band-before", "#free")
    band_h0 = ill(page)["h"]
    fh = page.evaluate("Math.round(document.getElementById('free').getBoundingClientRect().height)")
    check(f"{tag} band: #free compact (<= 640 px desktop: the phone beside the copy / 1240 px phone: stacked)", fh <= (1240 if vp_name == "phone" else 640), fh)
    page.evaluate("scrollTo({top: 0, behavior: 'instant'})")
    page.wait_for_timeout(300)
    net["nav"].clear()
    lc0 = lcol(page)
    submit(run, page, "@demo.creator", "https://www.instagram.com/demo.ig/")
    page.wait_for_function("() => /step/.test((document.querySelector('.report-card .live-status') || {}).textContent || '')", timeout=5000)
    c = card(page)
    check(f"{tag} progress visible in the hero card", c["live"] and c["title"] == "@demo.creator" and "Searching Google, step" in c["status"]
          and page.locator(".report-card .live-status").is_visible() and page.locator("#scan button").is_disabled(), c["status"])
    check(f"{tag} second scan state: no stale rows while scanning", not c["rows"] and not ill(page)["live"])
    page.wait_for_timeout(400)   # inline-scan.js bring()'s smooth scroll lands, the observer runs
    qz = page.evaluate("(() => { const c = document.querySelector('.askai-launcher').classList; return [c.contains('in-quiet') || (c.contains('in-hero') && innerWidth < 720), document.querySelector('.report-card').hasAttribute('aria-busy'), c.value]; })()")
    check(f"{tag} askai: launcher quiet while the scan runs (card skeleton on screen; phone: also hidden over the hero)", qz[:2] == [True, True], qz)
    shot(run, page, "2-progress", ".hero")
    check(f"{tag} body: onlyfans + handle + instagram from a pasted URL",
          net["bodies"] == [{"platform": "onlyfans.com", "handle": "demo.creator", "level": "low", "instagram": "demo.ig"}], net["bodies"])
    fv = page.evaluate("[document.querySelector('#scan [name=h]').value, document.querySelector('#scan [name=ig]').value]")
    check(f"{tag} form: a pasted URL / @name shows as the bare handle in the fields", fv == ["demo.creator", "demo.ig"], fv)
    run.ctx = ctx
    run.page = page
    run.band_h0 = band_h0
    run.lc0 = lc0


def hero_card(run):
    """Settled hero card"""
    tag, net, vp_name, vp = run.tag, run.net, run.vp_name, run.vp
    page = run.page
    lc0 = run.lc0
    settled(page)
    page.wait_for_selector("[data-p=scanned]:not([hidden])", timeout=5000)
    lc1 = lcol(page)
    check(f"{tag} hero: the left column doesn't move when the result lands (scanned line takes the note's slot)", lc1 == lc0, (lc0, lc1))
    an = page.evaluate("window.__anim.map(a => [a[0].map(k => parseFloat(k.height)), a[1]])")
    hf = page.evaluate("document.querySelector('.report-card').offsetHeight")
    check(f"{tag} hero: the card eases twice, no snap: at Scan up to the skeleton (about the report's height), then to the result's exact height (~320 ms each)",
          len(an) == 2 and an[0][0][1] > an[0][0][0] + 200 and abs(an[1][0][1] - hf) <= 1 and abs(hf - an[0][0][1]) <= 0.15 * hf
          and all(200 <= a[1] <= 500 for a in an), [an, hf])
    slug = parse_qs(urlsplit(page.url).query).get("r", [""])[0]
    d = served(slug)   # the oracle: what the API sent for this report
    rows = links(d)
    N = len(rows)
    check(f"{tag} hero: no navigation, URL = index.html?r=<slug>", re.fullmatch(r"[A-Za-z0-9]{12}", slug or "") is not None
          and page.url == cfg.base + "?r=" + slug and all(urlsplit(u).path == "/" for u in net["nav"]), [page.url] + net["nav"])
    c = card(page)
    want = [{"tag": "A", "dom": dom, "ttl": ttl, "href": u, "target": "_blank", "badge": b} for u, dom, ttl, b in rows[:5]]
    got = [{k: r[k] for k in ("tag", "dom", "ttl", "href", "target", "badge")} for r in c["rows"]]
    check(f"{tag} hero: rows = the served result's first 5 links (domain, title, href, badge: what the data says)", got == want, got)
    check(f"{tag} hero: row links rel noopener + nofollow, card no longer role=img", c["rows"] and all(
        "noopener" in r["rel"] and "nofollow" in r["rel"] for r in c["rows"]) and c["role"] is None, [r["rel"] for r in c["rows"]])
    check(f"{tag} hero: count + more", c["count"] == f"{N} links found" and c["more"] == f"+ {N - 5} more in the full report", (c["count"], c["more"]))
    check(f"{tag} hero: socials in the header", c["socials"] == "Instagram @demo.ig", c["socials"])
    check(f"{tag} hero: aliases: Also found as the discovered handles", c["aliases"] == ALSO, c["aliases"])
    check(f"{tag} hero: Open full report = <site>/scan/?r=<slug>", c["open"] == report_url(slug), c["open"])
    check(f"{tag} hero: Send me the report = DM links with report URL + handle", msgs_ok(c["msgs"], quote(report_url(slug), safe=""), "demo.creator"), c["msgs"])
    focus = page.evaluate("document.activeElement.className")
    try:   # inline-scan.js bring() scrolls smoothly; give it time to land
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
        lctx = run.new_ctx()   # a 1440x800 laptop (own context: this page's localStorage stays as it is): same, the Send buttons included
        lp = lctx.new_page()
        lp.set_viewport_size({"width": 1440, "height": 800})
        lp.goto(cfg.base, wait_until="load")
        lp.wait_for_timeout(300)
        submit(run, lp, "@demo.creator", "demo.ig")
        settled(lp)
        lp.wait_for_timeout(1500)   # the ease + the smooth scroll
        st = lp.evaluate(SETTLE)
        check(f"{tag} hero: settled at 1440x800: card top not under the sticky nav, whole card + Send buttons above the fold", st[0] >= st[4] - 1 and st[1] <= st[3] and st[2] <= st[3], st)
        lp.screenshot(path=str(cfg.out / f"{vp_name}-i2s-settled-1440x800.png"))
        lctx.close()
    run.slug = slug
    run.c = c
    run.d = d
    run.rows = rows


def hero_tiles(run):
    """Image tiles: judged by what shows (common.tiles_ok), and every view of the one result agrees with the others;"""
    tag = run.tag
    page = run.page
    slug = run.slug
    band_h0 = run.band_h0
    d = run.d
    rows = run.rows
    # the strip is swiped through first (common.swipe: lazy tiles, a 404 one must leave once it comes into view)
    N = len(rows)
    swipe(page, ".report-card .live-strip", (DEAD_THUMB,))
    NI = digits(settled_count(page, "#tab-report-images .live-tab-n"))   # the count once every thumb was seen, checked against the views below
    i = ill(page)
    strip_t = page.evaluate(TILES, ".report-card .live-strip a.gi-card")
    tile_shape = lambda x: (x[1] == "_blank" and x[2] == "noopener noreferrer nofollow") or (x[0] == report_url(slug) and x[1] == "" and x[2] == "")
    free_t = [[unquote(t[3].split("u=")[1]), t[0], t[1]] for t in i["tiles"]]
    # its first 9 = the strip's; past them a dead slot's refill depends on the view's size (E.gallery), so any strip tile
    b18 = [t[:3] for t in strip_t[:18]]
    check(f"{tag} thumbs: band: #free phone Images tab = 18 of the report's tiles (the first 9 as the hero strip), count = the hero's, link → result in a new tab, else the report",
          i["live"] and i["pill"] == f"{NI} images" and i["visible_illus"] == 0 and i["role"] == "group" and len(i["tiles"]) == len(b18)
          and all(t[3].startswith(cfg.api + "/api/thumb?u=") for t in i["tiles"]) and all(tile_shape(t) for t in i["tiles"])
          and free_t[:9] == b18[:9] and all(t in [x[:3] for x in strip_t] for t in free_t) and not tiles_ok([x + [True] for x in free_t], d, (DEAD_THUMB,)), (NI, i["pill"], len(i["tiles"]), len(b18), [(k, a[0][-24:], b[0][-24:]) for k, (a, b) in enumerate(zip(free_t, b18)) if a != b][:3],
           tiles_ok([x + [True] for x in free_t], d, (DEAD_THUMB,))))
    check(f"{tag} band: same height before/after results (row reserved, no shift)", abs(i["h"] - band_h0) <= 1, [band_h0, i["h"]])
    check(f"{tag} band: 'Send me the report' = Telegram with the report link", (i["send"] or "").startswith("https://t.me/jakabasej?text=")
          and quote(report_url(slug), safe="") in i["send"], i["send"])
    hero = page.evaluate("""() => {
        const c = document.querySelector('.report-card'), q = s => [...c.querySelectorAll(s)];
        return {tabs: q('.live-tab').map(b => [b.id, b.textContent, b.getAttribute('aria-selected'), b.tabIndex]),
          panels: q('.live-panel').map(p => [p.id, !p.hidden, getComputedStyle(p).visibility]),
          strip: q('.live-strip a.gi-card').map(a => [a.href, a.target, a.rel, a.querySelector('img').src]),
          stripH: (c.querySelector('.live-strip-h') || {}).textContent,
          blur: getComputedStyle(c.querySelector('.live-strip .gi-img')).filter, ico: q('.live-rows .live-ico').length,
          rowH: Math.min(...q('.live-rows a.live-link').map(a => a.getBoundingClientRect().height)),
          sites: q('.live-sites li:not([hidden]) a.live-link').map(a => [a.href, a.target, a.rel])};
    }""")
    check(f"{tag} thumbs: hero: tabs Links / Images / Sites with the served counts (Images: at least the strip's tiles), Links selected",
          hero["tabs"] == [["tab-report-links", f"Links{N}", "true", 0], ["tab-report-images", f"Images{NI}", "false", -1], ["tab-report-sites", f"Sites{d['domain_count']}", "false", -1]]
          and NI >= len(strip_t) > 0
          and [p[1:] for p in hero["panels"]] == [[True, "visible"], [False, "hidden"], [False, "hidden"]], hero["tabs"])
    check(f"{tag} hero: rows >= 44px with a letter avatar / blurred site thumb each", hero["rowH"] >= 44 and hero["ico"] == 5, hero["rowH"])
    check(f"{tag} thumbs: hero: strip 'What Google Images shows for @demo.creator' = 24 tiles (no dead / video still / repeat, result tiles first, each opens its own result), blurred",
          hero["stripH"] == "What Google Images shows for @demo.creator" and len(strip_t) == min(24, NI) and not tiles_ok(strip_t, d, (DEAD_THUMB,))
          and all(tile_shape(t) for t in hero["strip"]) and "blur" in hero["blur"], (tiles_ok(strip_t, d, (DEAD_THUMB,)), hero["strip"][:3]))
    dom_of, first, per = {u: dom for u, dom, _t, _b in rows}, {}, {}   # per served domain: its first link, its link count
    for u, dom, _t, _b in rows:
        first.setdefault(dom, u)
        per[dom] = per.get(dom, 0) + 1
    shown_d = [dom_of.get(x[0]) for x in hero["sites"]]
    ns = len(hero["sites"])
    check(f"{tag} hero: Sites tab = the top sites by served links (6-12, as many as fit), each opens its first link in a new tab", 6 <= ns <= 12
          and top_ok(shown_d, per, ns) and all(x == [first[dm], "_blank", "noopener noreferrer nofollow"] for x, dm in zip(hero["sites"], shown_d)), hero["sites"])
    sg = page.evaluate("""() => { const p = document.querySelector('#panel-report-sites'), ul = p.querySelector('ul'), m = p.querySelector('.live-more'), others = [...document.querySelectorAll('.report-card .live-panel:not(#panel-report-sites)')];
        const nat = e => e.lastElementChild.getBoundingClientRect().bottom - e.getBoundingClientRect().top;
        const lastRow = [...ul.children].filter(li => !li.hidden).pop();
        return {gap: Math.round(m.getBoundingClientRect().top - lastRow.getBoundingClientRect().bottom), clip: Math.round(lastRow.getBoundingClientRect().bottom - ul.getBoundingClientRect().bottom), more: m.textContent, href: m.getAttribute('href'),
          grew: Math.round(nat(p) - Math.max(...others.map(nat))), card: [document.querySelector('.report-card').getBoundingClientRect().width, document.querySelector('.hero-grid').clientWidth]}; }""")
    nsites = len(per)
    check(f"{tag} hero: Sites panel has no empty band ('+N more sites' link at its foot, gap < one row, last row whole, card not taller for it)", sg["gap"] < 52 + 12 and sg["clip"] <= 4
          and sg["grew"] <= 0 and sg["more"] == f"+ {nsites - ns} more sites in the full report" and sg["href"] == report_url(slug), sg)
    cw = page.evaluate("[document.querySelector('.report-card').getBoundingClientRect().right, document.querySelector('.hero-grid').getBoundingClientRect().right - parseFloat(getComputedStyle(document.querySelector('.hero-grid')).paddingRight)]")
    check(f"{tag} hero: the card fits its column (no overflow into the gutter)", cw[0] <= cw[1] + 0.5, cw)
    run.NI = NI


def hero_tabs(run):
    """Tabs switch the body without moving anything; Reveal unblurs"""
    tag, vp_name = run.tag, run.vp_name
    page = run.page
    NI = run.NI
    cbox = lambda: page.evaluate("() => { const r = document.querySelector('.report-card').getBoundingClientRect(), d = document.documentElement.getBoundingClientRect(); return [Math.round(r.x - d.x), Math.round(r.y - d.y), r.width, r.height]; }")
    page.wait_for_function("() => !document.querySelector('.report-card').getAnimations().length", timeout=3000)   # the card's height ease
    card0 = cbox()
    page.locator("#tab-report-images").click()
    page.wait_for_timeout(350)
    gi = page.evaluate("() => [!document.querySelector('#panel-report-images').hidden, getComputedStyle(document.querySelector('#panel-report-links')).visibility, document.querySelectorAll('#panel-report-images .live-grid a.gi-card').length, (document.querySelector('#panel-report-images .live-more') || {}).textContent]")
    card1 = cbox()
    G = 12 if vp_name == "phone" else 16
    check(f"{tag} thumbs: hero: Images tab shows the image grid (phone 12, else 16) in place (card box unchanged)", gi == [True, "hidden", G, f"+ {NI - G} more in the full report"]
          and card0 == card1, (gi, card0, card1))
    shot(run, page, "3b-card-images", ".report-card")
    page.locator("#panel-report-images .reveal-btn").click()
    page.wait_for_timeout(400)
    rv = page.evaluate("() => [getComputedStyle(document.querySelector('#panel-report-images .gi-img')).filter, [...document.querySelectorAll('.report-card .reveal-btn')].map(b => b.getAttribute('aria-pressed'))]")
    check(f"{tag} hero: Reveal unblurs (both toggles in sync)", rv[0] == "none" and set(rv[1]) == {"true"}, rv)
    page.locator("#panel-report-images .reveal-btn").click()
    page.locator("#tab-report-sites").click()
    page.wait_for_timeout(350)
    check(f"{tag} hero: Sites tab in place (card box unchanged, page coords)", cbox() == card0, (cbox(), card0))
    shot(run, page, "3c-card-sites", ".report-card")
    page.locator("#tab-report-links").focus()
    page.keyboard.press("ArrowRight")
    check(f"{tag} hero: arrow keys move between tabs", page.evaluate("document.activeElement.id") == "tab-report-images"
          and page.locator("#panel-report-images").get_attribute("hidden") is None)
    page.locator("#tab-report-links").click()
    page.mouse.move(0, 0)
    run.card0 = card0


def drift(run):
    """Drift: idle ~4 s → the strip scrolls itself; 2 frames 2 s apart; a pointerdown on it stops it for good"""
    tag, vp_name = run.tag, run.vp_name
    page = run.page
    card0 = run.card0
    bring(page, ".report-card .live-strip-box", "center")   # the drift runs only while the strip is on screen (phone: it can sit below the fold)
    try:
        page.wait_for_function("() => { const s = document.querySelector('.report-card .live-strip'), t = s && s.querySelector('.live-strip-track'); return s && s.scrollLeft - new DOMMatrix(getComputedStyle(t).transform).m41 > 4; }", timeout=9000)
    except Exception:
        pass
    a0 = strip(page)
    page.locator(".report-card .live-strip-box").screenshot(path=str(cfg.out / f"{vp_name}-i3d-strip-t0.png"))
    page.wait_for_timeout(2000)
    a1 = strip(page)
    page.locator(".report-card .live-strip-box").screenshot(path=str(cfg.out / f"{vp_name}-i3d-strip-t2.png"))
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
    page.locator(".report-card .live-strip-box").screenshot(path=str(cfg.out / f"{vp_name}-i3d-strip-after-pointerdown.png"))
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


def hero_look(run):
    """Tiles: a light placeholder in the light theme (no black flash), faded in once loaded; the #free frame stays Google-dark"""
    tag, vp_name = run.tag, run.vp_name
    page = run.page
    slug = run.slug
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
    hover(page, ".report-card .live-link")
    page.wait_for_timeout(250)
    hv = page.evaluate("getComputedStyle(document.querySelector('.report-card .live-link')).backgroundColor")
    hov = page.evaluate("matchMedia('(hover: hover)').matches")   # Playwright's screenshots flip a touch context to hover: ask the page
    bare = page.evaluate(BARE_HOVER)
    check(f"{tag} hero: row hover tint only where hover exists (phone: none after a tap; no :hover rule, a:hover included, outside @media (hover: hover))", (hv == "rgba(0, 0, 0, 0)") == (not hov) and not bare, [hv, hov, bare])
    page.mouse.move(0, 0)
    # the Ask AI pill never sits on the card's actions or on the before / after phones
    def pill_clear(sel):
        bring(page, sel, "end")
        page.wait_for_timeout(600)
        return page.evaluate(f"""() => {{ const L = document.querySelector('.askai-launcher'), b = L.getBoundingClientRect(), r = document.querySelector('{sel}').getBoundingClientRect();
            const over = r.right > b.left && r.left < b.right && r.bottom > b.top && r.top < b.bottom;
            return [over, getComputedStyle(L).visibility]; }}""")
    if vp_name == "phone":   # the sticky "Free scan" bar steps aside while the showcase preview is behind it, and is back after
        bring(page, "#showcase .browser-demo", "center")
        page.wait_for_timeout(500)
        on_demo = page.evaluate("document.querySelector('.mobile-cta').classList.contains('show')")
        bring(page, "#pricing")
        page.wait_for_timeout(500)
        on_pricing = page.evaluate("document.querySelector('.mobile-cta').classList.contains('show')")
        check(f"{tag} sticky scan bar: hidden over the showcase preview, shown again past it", not on_demo and on_pricing, [on_demo, on_pricing])
    pa, pb, ps = pill_clear(".report-card .live-actions"), pill_clear(".ba"), pill_clear("#showcase .browser-demo")
    check(f"{tag} askai: launcher hidden while it would cover the card's actions / the phones / the showcase preview", all(not o or v == "hidden" for o, v in (pa, pb, ps))
          and (pa[0] or pb[0]) and (ps[0] or vp_name != "phone"), (pa, pb, ps))
    page.evaluate("scrollTo({top: 0, behavior: 'instant'})")
    last = json.loads(page.evaluate("localStorage.getItem('leakscan.last')") or "{}")
    check(f"{tag} hero: localStorage leakscan.last", last.get("slug") == slug and last.get("handle") == "demo.creator", last)


def hero_personalize(run):
    """Personalize (same checks as #18's ?r= path, via the leakscan:result event)"""
    tag = run.tag
    page = run.page
    slug = run.slug
    d = run.d
    try:
        page.wait_for_selector("[data-p=scanned]:not([hidden])", timeout=5000)
    except Exception:
        pass
    texts = lambda sel: page.eval_on_selector_all(sel, "els => els.filter(e => e.offsetParent !== null).map(e => e.textContent.trim())")
    name = PROFILE["display_name"]
    check(f"{tag} hero: personalize line + phones' leak domains", "Scanned @demo.creator" in page.locator("[data-p=scanned]").inner_text()
          and top_ok([page.locator(f'[data-p="leak-{k}"] .m-site').inner_text() for k in range(1, 5)], occurrences(d["hits"]), 4))
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
    shot(run, page, "3-settled", ".hero")
    shot(run, page, "3-settled-card", ".report-card")
    bring(page, "#free", "center")
    page.wait_for_timeout(700)
    shot(run, page, "4-band", "#free")
    bring(page, "#showcase .ba", "center")
    page.wait_for_timeout(700)
    shot(run, page, "5-phones", "#showcase .ba")


def reload_rescan(run):
    """Reload with ?r= restores the hero card, no new scan"""
    tag, net, vp_name = run.tag, run.net, run.vp_name
    page = run.page
    slug = run.slug
    c = run.c
    NI = run.NI
    n_posts = len(net["bodies"])
    page.reload(wait_until="load")
    try:
        page.wait_for_selector(".report-card .live-rows li", timeout=6000)
    except Exception:
        pass
    swipe(page, ".report-card .live-strip", (DEAD_THUMB,))   # settled as NI was: the 404 tile seen and dropped
    settled_count(page, "#tab-report-images .live-tab-n")
    c2 = card(page)
    check(f"{tag} thumbs: reload ?r= restores hero card (rows, count, socials), no new scan", c2["rows"] == c["rows"] and c2["count"] == c["count"]
          and c2["socials"] == "Instagram @demo.ig" and ill(page)["pill"] == f"{NI} images" and len(net["bodies"]) == n_posts,
          [c2["count"], c2["rows"] == c["rows"], c2["socials"], ill(page)["pill"], NI, len(net["bodies"]) - n_posts])

    # 4. second scan resets, badges only from data (stub-mixed: live true / false / missing, then Google results)
    submit(run, page, "stub-mixed")
    page.wait_for_function("() => /step/.test((document.querySelector('.report-card .live-status') || {}).textContent || '')", timeout=5000)
    mid = card(page)
    check(f"{tag} second scan resets hero card + illustration", not mid["rows"] and mid["title"] == "@stub-mixed" and mid["count"] is None
          and not ill(page)["live"] and mid["socials"] is None, mid)
    settled(page)
    mixed = links(served(parse_qs(urlsplit(page.url).query).get("r", [""])[0]))
    c = card(page)
    check(f"{tag} hero: badges only what the data says (Live / Found / Indexed)", [r["badge"] for r in c["rows"]] == ["Live", "Found", "Found", "Indexed", "Indexed"]
          and not any(b in json.dumps(c) for b in ("Dead", "Cached", "Removed")), [r["badge"] for r in c["rows"]])
    check(f"{tag} hero: second result replaces the first", c["title"] == "@stub-mixed" and c["count"] == f"{len(mixed)} links found"
          and c["socials"] is None and net["bodies"] == [{"platform": "onlyfans.com", "handle": "stub-mixed", "level": "low"}], (c["count"], net["bodies"]))
    check(f"{tag} hero: aliases: no discovered handles -> line hidden", c["aliases"] is None, c["aliases"])
    check(f"{tag} hero: URL follows the new slug", parse_qs(urlsplit(page.url).query).get("r", [""])[0] not in ("", slug), page.url)

    # 5. zero hits + X from a pasted URL
    submit(run, page, "stub-empty", "x.com/demo_x")
    settled(page)
    c = card(page)
    i = ill(page)
    check(f"{tag} zero hits: honest empty state, send still there", c["empty"] and c["empty"].startswith("No leaks found for @stub-empty right now")
          and c["count"] == "0 links found" and not c["rows"] and c["open"] and msgs_ok(c["msgs"], "stub-empty") and not i["live"]
          and i["visible_illus"] > 0 and page.locator(".report-card .live-tabs").count() == 0, c)
    check(f"{tag} body: x.com URL → x, no instagram", net["bodies"] == [{"platform": "onlyfans.com", "handle": "stub-empty", "level": "low", "x": "demo_x"}], net["bodies"])
    check(f"{tag} hero: X social in the header", c["socials"] == "X @demo_x", c["socials"])
    page.locator(".report-card").screenshot(path=str(cfg.out / f"{vp_name}-i6-empty.png"))


def errors_reset(run):
    """Errors: 429 rate_limited / busy, failed, network, server 400, client-side validation"""
    tag, net, vp_name = run.tag, run.net, run.vp_name
    page = run.page
    ctx = run.ctx
    for h, kind, want in (("stub-429", "rate_limited", "busy"), ("stub-busy", "busy", "busy"), ("stub-fail", "failed", "didn’t finish")):
        submit(run, page, h)
        settled(page)
        c = card(page)
        txt = page.locator(".report-card .live-error").inner_text() if page.locator(".report-card .live-error").count() else ""
        check(f"{tag} {kind} error inline, form re-enabled", c["error"] == kind and want in txt and ("minute" in txt) and msgs_ok(c["msgs"], h)
              and page.locator("#scan button").is_enabled(), txt)
        check(f"{tag} hero: {kind} keeps the last report's ?r= in the URL", page.url.startswith(cfg.base + "?r="), page.url)
        page.locator(".report-card").screenshot(path=str(cfg.out / f"{vp_name}-i7-error-{kind}.png"))
    page.route("**/api/public-scan", lambda r, _q: r.abort())   # fake: network down (wire boundary)
    submit(run, page, "demo.creator")
    settled(page)
    c = card(page)
    check(f"{tag} network error inline, form re-enabled", c["error"] == "network" and "Couldn’t reach" in page.locator(".live-error").inner_text()
          and msgs_ok(c["msgs"], "demo.creator") and page.locator("#scan button").is_enabled())
    page.unroute("**/api/public-scan")
    page.route("**/api/public-scan", lambda r, _q: r.fulfill(status=400, content_type="application/json", body='{"error":"bad_handle"}'))  # fake: server 400
    submit(run, page, "demo.creator")
    settled(page)
    check(f"{tag} server 400 → 'doesn’t look right' at the form, card back to illustration", "doesn’t look right" in page.locator(".inline-msg").inner_text()
          and not card(page)["live"] and page.locator("#scan button").is_enabled())
    page.unroute("**/api/public-scan")
    for h, s, field in (("bad handle!", "", "h"), ("demo.creator", "tiktok.com/someone", "ig")):
        submit(run, page, h, s)
        page.wait_for_timeout(200)
        check(f"{tag} client validation ({field}) → message, no POST", "doesn’t look right" in page.locator(".inline-msg").inner_text()
              and not net["bodies"] and page.evaluate("document.activeElement.name") == field, net["bodies"])
    page.locator(".hero").screenshot(path=str(cfg.out / f"{vp_name}-i8-validation.png"))

    # 7. a good scan again, then Reset page resets everything
    submit(run, page, "demo.creator", "demo.ig")
    settled(page)
    check(f"{tag} hero: scan works again after errors", len(card(page)["rows"]) == 5 and not page.locator(".inline-msg").is_visible())
    if page.locator("[data-p=scanned] button").is_visible():
        page.locator("[data-p=scanned] button").click()
    page.wait_for_load_state("load")
    page.wait_for_timeout(1200)
    check(f"{tag} Reset page resets hero card + illustration", not card(page)["live"] and not ill(page)["live"] and page.url == cfg.base
          and page.evaluate("localStorage.getItem('leakscan.last')") is None and card(page)["role"] == "img")
    ctx.close()


def shared_links(run):
    """Reduced motion: the report restores from ?r=, the strip never moves by itself"""
    tag, vp_name = run.tag, run.vp_name
    slug = run.slug
    ctx = run.new_ctx(motion="reduce")
    page = ctx.new_page()
    page.goto(cfg.base + "?r=" + slug, wait_until="load")
    try:
        page.wait_for_selector(".report-card .live-strip a.gi-card", timeout=8000)
    except Exception:
        pass
    page.mouse.move(0, 0)
    page.wait_for_timeout(6500)
    r = strip(page)
    check(f"{tag} hero: reduced motion → strip still, no drift after 6.5 s idle", r and r["x"] == 0 and r["drift"] is None and r["max"] > 0 and r["pause"] == "none", r and (r["x"], r["drift"], r["max"], r["pause"]))
    page.locator(".report-card .live-strip-box").screenshot(path=str(cfg.out / f"{vp_name}-i3d-strip-reduced-motion.png"))
    ctx.close()

    # 7c. a shared ?r= link in a fresh browser: ONE /api/scan-result request (inline-scan.js + personalize.js share it);
    # phone: the card (below the hero text) is brought under the nav; desktop: it is already in view, no scroll;
    # ?r=…#website: the anchor wins, the card is not brought
    ctx = run.new_ctx()
    page = ctx.new_page()
    reqs = []
    page.on("request", lambda q: "/api/scan-result/" in q.url and reqs.append(q.url))
    page.goto(cfg.base + "?r=" + slug, wait_until="load")
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
    page.screenshot(path=str(cfg.out / f"{vp_name}-i3e-shared-link.png"))
    ctx.close()
    ctx = run.new_ctx()
    page = ctx.new_page()
    page.goto(cfg.base + "?r=" + slug + "#website", wait_until="load")
    try:
        page.wait_for_selector(".report-card .live-rows li", timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(1500)
    pos = page.evaluate("() => { const c = document.querySelector('.report-card').getBoundingClientRect(), w = document.getElementById('website').getBoundingClientRect(); return {card: Math.round(c.top), website: Math.round(w.top), ih: innerHeight}; }")
    check(f"{tag} shared ?r=…#website link: no jump to the card", not (0 <= pos["card"] < pos["ih"]) and pos["website"] < pos["ih"], pos)
    ctx.close()


def no_js(run):
    """No JS: plain GET to scan/ with h + ig; scan/ reads h / ig / x and posts the socials"""
    tag, net = run.tag, run.net
    ctx = run.new_ctx(js=False)
    page = ctx.new_page()
    page.goto(cfg.base, wait_until="load")
    page.locator("#scan input[name=h]").fill("@Some.Name")
    page.locator("#scan input[name=ig]").fill("x.com/some_x")
    with page.expect_navigation(url=re.compile(r"/scan/\?")):
        page.locator("#scan button[type=submit]").click()
    q = parse_qs(urlsplit(page.url).query)
    check(f"{tag} no JS: form GETs scan/?h=&ig=", urlsplit(page.url).path == "/scan/" and q == {"h": ["@Some.Name"], "ig": ["x.com/some_x"]}, page.url)
    ctx.close()
    ctx = run.new_ctx()
    page = ctx.new_page()
    for qs, want in (("h=%40Some.Name&ig=x.com%2Fsome_x", {"handle": "Some.Name", "x": "some_x"}),
                     ("h=demo.creator&ig=%40demo.ig", {"handle": "demo.creator", "instagram": "demo.ig"}),
                     ("h=demo.creator&x=demo_x", {"handle": "demo.creator", "x": "demo_x"})):
        net["bodies"].clear()
        page.goto(cfg.base + "scan/?" + qs, wait_until="load")
        try:
            page.wait_for_selector("#report:not([hidden])", timeout=15000)
        except Exception:
            pass
        check(f"{tag} scan/?{qs} posts the socials", net["bodies"] == [{"platform": "onlyfans.com", "level": "low", **want}], net["bodies"])
    net["bodies"].clear()
    page.goto(cfg.base + "scan/", wait_until="load")
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
    page.goto(cfg.base + "scan/?h=demo.creator&ig=tiktok.com%2Fx", wait_until="load")
    check(f"{tag} scan/ bad social → form message", page.locator("#form-error").is_visible() and "Instagram or X" in page.locator("#form-error").inner_text())
    ctx.close()


def inline_flow(browser, vp_name, vp):
    net = {"bodies": [], "nav": []}
    run = types.SimpleNamespace(tag=f"{vp_name} inline", net=net, vp_name=vp_name, vp=vp,
                                new_ctx=lambda **o: ctx_for(browser, vp_name, vp, net, **o))
    for part in (before_submit, hero_card, hero_tiles, hero_tabs, drift, hero_look, hero_personalize, reload_rescan,
                 errors_reset, shared_links, no_js):
        part(run)
    tag = run.tag
    hosts = {urlsplit(u).hostname for u in net["outside"]}
    check(f"{tag} no request left loopback (the demo iframe included: no Google Fonts)", not hosts, sorted(hosts))
    check(f"{tag} no JS errors, no console errors", not net["errors"] and not net["console"], net["errors"] + net["console"])

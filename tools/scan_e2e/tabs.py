"""Scenario `tabs` (see tools/scan_e2e.py for what it proves)."""
import base64
import json
import types
from urllib.parse import parse_qs, unquote, urlsplit

from .common import (COUNTS, FX, MEASURED, TILES, bring, cfg, check, dead_thumb, digits, links, new_ctx, scan_images, served, settled_count, swipe,
                     tiles_ok, video_stills)
from .huge import IN_VIEW

# layout shifts with their sources (PerformanceObserver, buffered from page start)
LS_SOURCES = "window.__ls = []; try { new PerformanceObserver(l => l.getEntries().forEach(e => window.__ls.push([e.startTime, e.value, e.hadRecentInput, (e.sources || []).map(s => s.node && s.node.nodeType === 1 ? s.node.tagName + '.' + s.node.className + ' ' + [s.previousRect.y, s.currentRect.y, s.previousRect.height, s.currentRect.height].map(Math.round) : '#text')]))).observe({type: 'layout-shift', buffered: true}); } catch (e) {}"


def dead_tail(browser, vp_name, vp, net, tag):
    """C12: demoDeadTail1 = 24 live thumbs, then 8 dead / blank ones that no view shows at first (past the strip's 24).
    Sampled every 0.5 s from load: no count ever says more than 24, and every one settles at 24."""
    ctx = new_ctx(browser, vp_name, vp, net, console_ok=lambda m: m.text.startswith("Failed to load resource")
                  and ("DEAD" in unquote(m.location.get("url") or "") or "BLANK" in unquote(m.location.get("url") or "")))[0]
    page = ctx.new_page()
    page.goto(cfg.base + "?r=demoDeadTail1", wait_until="load")
    page.wait_for_selector(".report-card #tab-report-images", timeout=8000)
    want, samples = ["24", "24 images on Google Images", "24 images"], []
    for _ in range(80):
        samples.append(page.evaluate(COUNTS))
        if samples[-1] == want:
            break
        page.wait_for_timeout(500)
    over = [x for x in samples if any(digits(c) > 24 for c in x)]
    MEASURED.setdefault(vp_name, {})["dead_tail_settle_s"] = len(samples) * 0.5
    check(f"{tag} thumbs: dead tail (24 live + 8 dead thumbs past the strip): no count ever over 24 while checking, all settle at 24 "
          "(tab, Images label, #free phone)", not over and samples[-1] == want, (samples[-1], over[:3], f"{len(samples)} samples"))
    page.locator(".report-card").screenshot(path=str(cfg.out / f"{vp_name}-t1-dead-tail-settled.png"))
    ctx.close()


def tabs_flow(browser, vp_name, vp):
    """The owner's three asks, one part each (report_card, free_phone, order_popout), then the page-wide checks."""
    tag = f"{vp_name} tabs"
    net = {"outside": [], "errors": [], "console": []}
    broken = served("demoBrokenT1")   # the wire payload, not stub code
    m = MEASURED.setdefault(vp_name, {})

    def ctx_(motion="no-preference"):
        return new_ctx(browser, vp_name, vp, net, init=[LS_SOURCES], reduced_motion=motion, console_ok=lambda msg: (
            msg.text.startswith("Failed to load resource") and "DEAD" in unquote(msg.location.get("url") or "")
            or "STALE" in unquote(msg.text + (msg.location.get("url") or "")) and ("CORS" in msg.text or "ERR_FAILED" in msg.text)))[0]   # the stale copy's refusal (then E.fresh)

    shot = lambda page, name, el=None: (page.locator(el) if el else page).screenshot(path=str(cfg.out / f"{vp_name}-t{name}.png"))
    overflow = lambda page: page.evaluate("""() => ({doc: document.documentElement.scrollWidth, vw: innerWidth,
        wide: [...document.querySelectorAll('.phone, .browser-demo, .report-card, .free-band, .ba')].filter(e => { const r = e.getBoundingClientRect(); return r.width && (r.left < -0.5 || r.right > innerWidth + 0.5); }).map(e => e.className)})""")

    t = types.SimpleNamespace(browser=browser, vp_name=vp_name, vp=vp, tag=tag, net=net, broken=broken, m=m, ctx_=ctx_, shot=shot, overflow=overflow)
    report_card(t)
    scan_page(t)
    free_phone(t)
    order_popout(t)
    hosts = {urlsplit(u).hostname for u in net["outside"]}
    check(f"{tag} no request left loopback (the demo iframe included: no Google Fonts)", not hosts, sorted(hosts))
    check(f"{tag} no JS errors, no console errors (the stub's 404 thumbs and STALE CORS refusals aside)", not net["errors"] and not net["console"], net["errors"] + net["console"])


def report_card(t):
    """(1) the report card: broken thumbs leave, counts follow (landing card, scan page, dead tail)."""
    browser, vp_name, vp, tag, net, broken, m, ctx_, shot = t.browser, t.vp_name, t.vp, t.tag, t.net, t.broken, t.m, t.ctx_, t.shot
    # ---------- (1) report card: broken thumbs leave, counts follow ----------
    # demoBrokenT1 = the fixture with 3 page thumbs swapped for 404 / blank ones and a video still first in images[]:
    # its count = the clean fixture's count minus the dead thumbs the page tried (observed on the wire), never a list
    # re-derived here (H10)
    vids = video_stills(broken)
    G = 12 if vp_name == "phone" else 16
    ctx = ctx_()
    page = ctx.new_page()
    page.goto(cfg.base + "?r=" + FX["slug"], wait_until="load")
    page.wait_for_selector(".report-card #tab-report-images", timeout=8000)
    n_clean = digits(settled_count(page, "#tab-report-images .live-tab-n"))
    ctx.close()
    ctx = ctx_()
    page = ctx.new_page()
    tried = set()
    page.on("request", lambda q: "/api/thumb" in q.url and dead_thumb(unquote(q.url)) and tried.add(unquote(q.url).split("u=")[1]))
    page.goto(cfg.base + "?r=demoBrokenT1", wait_until="load")
    page.wait_for_selector(".report-card #tab-report-images", timeout=8000)
    try:   # a 404 / blank thumb's tile goes at once (E.watchThumb); --break-thumbs: never goes
        page.wait_for_function("() => ![...document.querySelectorAll('.report-card a.gi-card img')].some(i => /DEAD|BLANK|LOGO/.test(decodeURIComponent(i.getAttribute('src'))))", timeout=8000)
    except Exception:
        pass
    swipe(page, ".report-card .live-strip")   # lazy strip tiles: load (and drop a dead one) only once swiped to
    bring(page, ".report-card")
    page.locator("#tab-report-images").click()
    settled_count(page, "#tab-report-images .live-tab-n")   # "N" once every thumb was seen ("N+" before)
    page.wait_for_timeout(600)
    st = page.evaluate("""() => { const c = document.querySelector('.report-card');
        return {label: c.querySelector('.live-imgs-head p').textContent,
          tab: c.querySelector('#tab-report-images .live-tab-n').textContent, more: (m => m && !m.hidden ? m.textContent : null)(c.querySelector('#panel-report-images .live-more')),
          painted: [...c.querySelectorAll('#panel-report-images .live-grid img')].map(i => i.complete && i.naturalWidth >= 16 && getComputedStyle(i).opacity === '1'),
          gaps: (g => { const r = [...g.children].map(e => e.getBoundingClientRect()); return r.length ? [new Set(r.map(x => Math.round(x.left))).size, r.length] : null; })(c.querySelector('#panel-report-images .live-grid'))}; }""")
    grid = page.evaluate(TILES, ".report-card #panel-report-images .live-grid a.gi-card")
    strip_t = page.evaluate(TILES, ".report-card .live-strip a.gi-card")
    clean = scan_images(served(FX["slug"]))
    gone, new = clean - scan_images(broken), scan_images(broken) - clean   # swapped-out originals; swapped-in + extra (LOGO0905) images
    NB = n_clean - len(gone) + len([u for u in new if u not in tried])   # what stays: clean minus swapped, plus new ones not dead on the wire
    m["report_images_clean"], m["report_dead_tried"], m["report_grid_tiles"] = n_clean, len(tried), len(grid)
    check(f"{tag} thumbs: failed / blank thumbs dropped from the Images grid and strip, next ones fill in (no dead / repeat, result tiles first)",
          tried == {u for u in scan_images(broken) if dead_thumb(u)} and len(grid) == min(G, NB) and not tiles_ok(grid, broken) and not tiles_ok(strip_t, broken)
          and {t[0] for t in grid} <= {t[0] for t in strip_t},   # one gallery; each view swaps in its own next image, in place
          (sorted(tried), tiles_ok(grid, broken), tiles_ok(strip_t, broken), len(grid), [t[0][-12:] for t in grid if t[0] not in {x[0] for x in strip_t}]))
    check(f"{tag} thumbs: label / tab / '+N more' count what shows ({n_clean} clean − {len(gone)} swapped + {NB - n_clean + len(gone)} new alive = {NB})",
          st["label"] == f"{NB} images on Google Images" and st["tab"] == str(NB) and st["more"] == (f"+ {NB - len(grid)} more in the full report" if NB > len(grid) else None), st)
    check(f"{tag} thumbs: every grid tile painted (loaded, >= 16 px, opacity 1), no empty square", len(st["painted"]) == len(grid) and all(st["painted"]), st["painted"])
    check(f"{tag} thumbs: strip = 24 tiles, each loads once swiped to", len(strip_t) == min(24, NB) and all(t[3] for t in strip_t),
          [len(strip_t), [t[0][-20:] for t in strip_t if not t[3]]])
    check(f"{tag} videos: video stills only after every real image (grid, strip; images[]' leading still moved back)",
          "video still before a real image" not in tiles_ok(grid, broken) + tiles_ok(strip_t, broken)
          and any(u in vids for u in broken["images"][:1]) and strip_t[:1] and strip_t[0][0] != broken["images"][0], [sorted(vids)[:2], [t[0] in vids for t in strip_t]])
    shot(page, "1-card-images-broken-removed", ".report-card")
    # #free Videos rows: a logo still (no person photo) leaves its 16:9 box grey + play mark, the row stays
    bring(page, "#free", "center")
    page.locator("#tab-free-videos").click()
    page.wait_for_timeout(1500)
    BV = [r for r in broken["results"] if r.get("kind") == "video" and r.get("link")][:6]
    bv = page.evaluate("""() => [...document.querySelectorAll('[data-live=free-videos] a.m-link')].map(a => { const i = a.querySelector('.m-vthumb img');
        return [a.href, i ? (i.complete && i.naturalWidth >= 16) : null, !!a.querySelector('.m-vthumb .m-play')]; })""")
    check(f"{tag} videos: #free Videos rows: logo still dropped (grey box + play kept, row stays), the rest painted",
          [x[0] for x in bv] == [r["link"] for r in BV] and [x[1] for x in bv] == [None if dead_thumb(r.get("thumb") or "DEAD") else True for r in BV]
          and all(x[2] for x in bv) and any("LOGO" in (r.get("thumb") or "") for r in BV), bv)
    # row icons (Links + Sites): a person photo of the row's own site or the neutral letter: never a logo / dead thumb,
    # never another site's photo; a site whose own thumb fails borrows one of its other results' photos
    tdom = {}
    for r in broken["results"]:
        if r.get("thumb"):
            tdom.setdefault(r["thumb"], set()).add(r["domain"])
    ri = page.evaluate("""() => [...document.querySelectorAll('.report-card .live-rows a.live-link, .report-card .live-sites a.live-link')].map(a => {
        const i = a.querySelector('.live-ico img'); return [a.querySelector('.live-dom').textContent, i ? decodeURIComponent(i.getAttribute('src').split('u=')[1] || '') : '']; })""")
    bad_doms = {d for t, ds in tdom.items() if dead_thumb(t) for d in ds}
    check(f"{tag} thumbs: row icons (Links + Sites): own-site person photos or the letter, no logo / failed thumb, a failed site borrows its own other photo",
          ri and not any(dead_thumb(u) for _d, u in ri if u) and all(d in tdom.get(u, ()) for d, u in ri if u)
          and any(d in bad_doms and u for d, u in ri), [x for x in ri if x[1] and (dead_thumb(x[1]) or x[0] not in tdom.get(x[1], ()))] or [x[0] for x in ri if x[0] in bad_doms])
    # the same report on the scan page: failed tiles leave its Images grid too
    ctx.close()
    ctx = ctx_()
    page = ctx.new_page()
    page.goto(cfg.base + "scan/?r=demoBrokenT1", wait_until="load")
    page.wait_for_selector("#tab-google-images", timeout=8000)
    page.locator("#tab-google-images").click()
    try:
        page.wait_for_function("() => ![...document.querySelectorAll('.g-grid .g-tile img')].some(i => /DEAD|BLANK|LOGO/.test(decodeURIComponent(i.getAttribute('src'))))", timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(800)
    sp = page.evaluate("() => [...document.querySelectorAll('.g-grid .g-tile img')].map(i => [decodeURIComponent(i.getAttribute('src').split('u=')[1]), i.complete && i.naturalWidth >= 16])")
    # the scan page's Images grid (every image, video stills too): desktop 24 (3 rows of 8), phone 12 (4 rows of 3), then "Show more"
    live = [u for u in scan_images(broken) if not dead_thumb(u)]
    want = min(24 if vp_name == "desktop" else 12, len(live))
    check(f"{tag} thumbs: scan page Images grid: failed / blank tiles removed, their slots filled ({want} of {len(live)} live images), all painted",
          len(sp) == want and all(ok for _u, ok in sp) and not any(dead_thumb(u) for u, _ok in sp)
          and len({u for u, _ok in sp}) == len(sp), (len(sp), want, [u[-24:] for u, ok in sp if not ok][:4]))
    page.locator("#tab-google-videos").click()
    page.wait_for_timeout(1500)
    VS = [r for r in broken["results"] if r.get("kind") == "video"]
    sv = page.evaluate("() => [...document.querySelectorAll('#panel-google .g-v .g-vthumb')].map(a => { const i = a.querySelector('img'); return [a.href, i ? (i.complete && i.naturalWidth >= 16) : a.querySelector('.g-img-none') ? null : false]; })")
    check(f"{tag} videos: scan page Videos tab: logo still → grey box (row stays, count honest), the rest painted",
          [x[0] for x in sv] == [r["link"] for r in VS[:len(sv)]] and len(sv) == min(5 if vp_name == "phone" else 8, len(VS))
          and [x[1] for x in sv] == [None if dead_thumb(r.get("thumb") or "DEAD") else True for r in VS[:len(sv)]]
          and any("LOGO" in (r.get("thumb") or "") for r in VS[:len(sv)]), sv)
    ctx.close()
    if vp_name == "desktop":   # desktop Images: every thumb answers late (after the tab is up): same-size tiles, nothing moves
        ctx = ctx_()
        page = ctx.new_page()
        held, hold = [], [True]   # held until the tab is up; later requests (spare tiles) pass
        page.route(lambda u: "/api/thumb" in u, lambda r: held.append(r) if hold[0] else r.continue_())
        page.goto(cfg.base + "scan/?r=demoBrokenT1", wait_until="load")
        page.wait_for_selector("#tab-google-images", timeout=8000)
        bring(page, "#g-stage")
        page.wait_for_timeout(300)
        t0, y0 = page.evaluate("() => { document.querySelector('#tab-google-images').click(); return [performance.now(), document.getElementById('sites').getBoundingClientRect().top]; }")
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
        ctx = ctx_()
        page = ctx.new_page()
        held, hold = [], [True]   # the 404 / blank thumbs answer late: after the Images tab is up (the All tab's strip would fail them first)
        page.route(lambda u: "/api/thumb" in u and dead_thumb(unquote(u)), lambda r: held.append(r) if hold[0] else r.continue_())
        page.goto(cfg.base + "scan/?r=demoBrokenT1", wait_until="load")
        page.wait_for_selector("#tab-google-images", timeout=8000)
        page.wait_for_timeout(800)
        t0, s0 = page.evaluate("""() => { document.querySelector('#tab-google-images').click();
            return [performance.now(), [...document.querySelectorAll('.g-grid .g-tile img')].map(i => decodeURIComponent(i.getAttribute('src').split('u=')[1]))]; }""")
        page.wait_for_timeout(800)
        hold[0] = False   # later requests (E.watchThumb's status check) pass
        while held:
            held.pop().continue_()
        page.wait_for_timeout(1500)
        s1 = page.evaluate("""(t0) => [[...document.querySelectorAll('.g-grid .g-tile img')].map(i => [decodeURIComponent(i.getAttribute('src').split('u=')[1]), i.complete && i.naturalWidth >= 16]),
            window.__ls.filter(x => x[0] > t0 + 200 && x[1] > 0 && !x[2]).map(x => x[3])]""", t0)
        # phone Images: first 12; a failed slot is taken by a spare image (else the last tile)
        d0 = next((i for i, u in enumerate(s0) if dead_thumb(u)), -1)
        check(f"{tag} thumbs: pinned phone Images: failed tiles' slots filled in place (spare image, else the last tile), every live image painted, tiles above untouched, no layout shift",
              d0 >= 0 and len(s1[0]) == (len(s0) if len(live) > len(s0) else len(live)) and all(ok for _u, ok in s1[0]) and [u for u, _ok in s1[0][:d0]] == s0[:d0]
              and not dead_thumb(s1[0][d0][0]) and not any(dead_thumb(u) for u, _ok in s1[0]) and not s1[1], [len(s0), len(live), len(s1[0]), d0, s1[1][:2]])
        page.locator("#device input[value=computer]").check(force=True)
        page.wait_for_timeout(1000)   # a thumb the phone never showed: its probe (a STALE one: refusal, E.fresh retry) settles
        back = page.evaluate("() => [...document.querySelectorAll('#g-stage img')].map(i => decodeURIComponent(i.getAttribute('src').split('u=')[1] || ''))")
        check(f"{tag} thumbs: a device switch keeps failed thumbs out (Computer view lists none of them)", back and not any(dead_thumb(u) for u in back),
              [u[-24:] for u in back if dead_thumb(u)])
        ctx.close()

    dead_tail(browser, vp_name, vp, net, tag)


GIF1 = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==")   # 1x1: a "blank" thumb (drop path, no console 404)
SHIFTS = "(t0) => window.__ls.filter(x => x[0] > t0 && x[1] > 0 && !x[2]).map(x => x[3])"
SRCS = """(sel) => [...document.querySelectorAll(sel)].filter(e => e.querySelector('.g-vid')).map(e => decodeURIComponent(e.querySelector('img').getAttribute('src').split('u=')[1]))"""
STRIP_IN_VIEW = """() => { const t = document.querySelector('.ph-track');   /* the strip on screen: phone pinned at its top, desktop centred */
    if (t && getComputedStyle(t.firstElementChild).position === 'sticky') window.scrollTo({top: t.getBoundingClientRect().top + scrollY - parseFloat(getComputedStyle(t.firstElementChild).top), behavior: 'instant'});
    else document.querySelector('#panel-google .g-strip').scrollIntoView({block: 'center', behavior: 'instant'}); }"""


def held_thumbs(t):
    """A scan page of demoR3port01 whose /api/thumb answers are held: → (page, ctx, held, pick, blank). Every request is
    held until the report is up; then all go on except those ending in a `pick` src; blank(src) answers those with a
    1x1 GIF (a blank thumb: E.watchThumb's drop path)."""
    ctx = t.ctx_()
    page = ctx.new_page()
    held, hold, pick = [], [True], []
    page.route(lambda u: "/api/thumb" in u, lambda r: held.append(r) if hold[0] or any(r.request.url.endswith(x) for x in pick) else r.continue_())
    page.goto(cfg.base + "scan/?r=demoR3port01", wait_until="load")
    page.wait_for_selector("#report:not([hidden])", timeout=8000)

    def release(srcs):
        pick.extend(srcs)
        hold[0] = False
        for r in [r for r in held if not any(r.request.url.endswith(x) for x in pick)]:
            held.remove(r)
            r.continue_()

    def blank(src):
        for r in [r for r in held if r.request.url.endswith(src)]:
            held.remove(r)
            r.fulfill(status=200, body=GIF1, content_type="image/gif")
    return page, ctx, release, blank


def scan_page(t):
    """The scan page's images: > 80 results, a report of mostly videos (strip + Images tab + Videos tab), and thumbs that
    fail late on the All tab's strip (nothing on screen moves: E.gallery's `still` views)."""
    vp_name, tag, ctx_, shot = t.vp_name, t.tag, t.ctx_, t.shot
    # more than 80 Google results (the page list stops at 80): every result's thumb is still in the strip and the Images tab
    ctx = ctx_()
    page = ctx.new_page()

    def many(r, _q):
        d = json.loads(r.fetch().text())
        d["results"] = d["results"] + [{"title": f"Extra page {k}", "link": f"https://extra{k}.example/p/{k}", "domain": f"extra{k}.example", "snippet": "x",
                                        "thumb": f"https://encrypted-tbn0.gstatic.com/images?q=tbn:EXTRA{k:04d}", "kind": "page"} for k in range(90)]
        many.pages = sum(x.get("kind") != "video" for x in d["results"][:80])
        many.n = len(scan_images(d))
        r.fulfill(json=d)
    page.route("**/api/scan-result/demoR3port01", many)
    page.goto(cfg.base + "scan/?r=demoR3port01", wait_until="load")
    page.wait_for_selector("#report:not([hidden])", timeout=8000)
    strip_n = page.locator("#panel-google .g-strip > .g-pack-b").count()
    while page.locator("#panel-google [data-more=all]").count():
        page.locator("#panel-google [data-more=all]").click()
    pages_n = page.locator("#panel-google .g-r").count()
    page.locator("#tab-google-images").click()
    isteps = [page.locator("#panel-google .g-tile").count()]
    while page.locator("#panel-google [data-more=images]").count():
        page.locator("#panel-google [data-more=images]").click()
        isteps.append(page.locator("#panel-google .g-tile").count())
    i0 = 24 if vp_name == "desktop" else 12   # Images: desktop 24, phone 12; +24 per More
    check(f"{tag} thumbs: > 80 results: every result's thumb in the strip and the Images tab ({i0}, +24 per More; pages stay capped at 80)",
          strip_n == isteps[-1] == many.n > 80 and pages_n == many.pages and isteps == [min(i0 + 24 * k, many.n) for k in range(len(isteps))], [strip_n, isteps, many.n, pages_n, many.pages])
    ctx.close()
    # a report that is mostly video results (real-report shape): every image in the strip and the Images tab, video
    # results' stills with a play badge (images[] entries that share one too); the Videos tab's steps. Fresh scan + reopen
    for how in ("scan/?h=stub-videos", "scan/?r=demoVideos01"):
        ctx = ctx_()
        page = ctx.new_page()
        page.goto(cfg.base + how, wait_until="load")
        page.wait_for_selector("#report:not([hidden])", timeout=15000)
        page.wait_for_timeout(300)
        vd = served(parse_qs(urlsplit(page.url).query)["r"][0])   # the oracle: what the API sent
        nvid = sum(r.get("kind") == "video" for r in vd["results"])
        sv, sb = page.evaluate(TILES, "#panel-google .g-strip > .g-pack-b"), set(page.evaluate(SRCS, "#panel-google .g-strip > .g-pack-b"))
        badge = page.evaluate("() => { const e = document.querySelector('#panel-google .g-strip .g-vid'), b = e && getComputedStyle(e, '::after'); return b ? [b.content, b.width, b.position] : null; }") or [None] * 3
        page.locator("#tab-google-images").click()
        while page.locator("#panel-google [data-more=images]").count():
            page.locator("#panel-google [data-more=images]").click()
        iv, ib = page.evaluate(TILES, "#panel-google .g-tile"), set(page.evaluate(SRCS, "#panel-google .g-tile"))
        if how.endswith("demoVideos01"):
            bring(page, "#panel-google .g-tile")
            page.wait_for_timeout(500)
            shot(page, "v-videos-images-tab")
        page.locator("#tab-google-videos").click()
        vcount = lambda: page.locator("#panel-google .g-v").count()
        first, steps, kb = vcount(), [], None
        if how.endswith("demoVideos01"):
            page.wait_for_timeout(300)
            shot(page, "v-videos-first-look")
        if how.endswith("demoVideos01") and page.locator("#panel-google [data-more=videos]").count():   # keyboard Enter → +12, focus on the first new video
            page.locator("#panel-google [data-more=videos]").focus()
            page.keyboard.press("Enter")
            page.wait_for_timeout(300)
            kb = page.evaluate("() => { const v = [...document.querySelectorAll('#panel-google .g-v')]; return v.findIndex(e => e.contains(document.activeElement)); }")
            steps.append(vcount())
        names = set()
        while page.locator("#panel-google [data-more=videos]").count():
            names.add(page.locator("#panel-google [data-more=videos]").inner_text())
            page.locator("#panel-google [data-more=videos]").click()
            page.wait_for_timeout(100)
            steps.append(vcount())
        vn = vcount()
        if how.endswith("demoVideos01"):   # Show fewer: back to the first look, focus on Show more videos, in view
            if page.locator("#panel-google [data-less=videos]").count():
                names.add(page.locator("#panel-google [data-less=videos]").inner_text())
                page.locator("#panel-google [data-less=videos]").click()
                page.wait_for_timeout(300)
            fw = [vcount(), page.evaluate("document.activeElement.matches('[data-more=videos]')"), page.evaluate(IN_VIEW)]
            shot(page, "v-videos-show-fewer")
            f0 = 5 if vp_name == "phone" else 8
            check(f"{tag} Videos: first look {f0}, 'Show more videos' +12 (Enter: focus on the first new one) up to all {nvid}, Show fewer → {f0}, focus on Show more, in view",
                  first == f0 and steps == [min(f0 + 12 * k, nvid) for k in range(1, len(steps) + 1)] and steps[-1:] == [nvid] and kb == f0
                  and fw == [f0, True, True] and names == {'Show more videos', 'Show fewer'}, [first, steps, kb, fw, sorted(names)])
            page.locator("#tab-google-all").click()
            bring(page, "#panel-google .g-strip", "center")
            page.wait_for_timeout(500)
            shot(page, "v-videos-all-strip")
        want, stills = scan_images(vd), video_stills(vd)
        src = lambda ts: [x[0] for x in ts]
        check(f"{tag} videos report ({how.split('?')[1]}): strip + Images tab = all {len(want)} images once, same order (result tiles first, each opens its own result), "
              f"play badge on the {len(want & stills)} video results' stills, Videos tab reaches {nvid}",
              src(sv) == src(iv) and set(src(sv)) == want and len(sv) == len(want) and not tiles_ok(sv, vd, videos=True) and not tiles_ok(iv, vd, videos=True)
              and sb == ib == want & stills and sb and vn == nvid and badge[0] == '""' and badge[1] == "24px" and badge[2] == "absolute",
              [len(sv), len(iv), len(want), len(sb), len(ib), tiles_ok(sv, vd, videos=True), vn, badge])
        ctx.close()
    # every thumb fails (late, after the report is up): the All strip keeps its height (visible slots stay as empty tiles), nothing below moves
    ctx = ctx_()
    page = ctx.new_page()
    held, hold = [], [True]
    page.route(lambda u: "/api/thumb" in u, lambda r: held.append(r) if hold[0] else r.fulfill(status=200, body=GIF1, content_type="image/gif"))
    page.goto(cfg.base + "scan/?r=demoR3port01", wait_until="load")
    page.wait_for_selector("#report:not([hidden])", timeout=8000)
    page.wait_for_timeout(600)
    POS = """() => { const s = document.querySelector('#panel-google .g-strip'), b = [...s.children];
        return [s.offsetHeight, Math.round(document.querySelector('#panel-google .g-r').getBoundingClientRect().top + scrollY), b.length,
                b.filter(e => e.querySelector('.g-img-none')).length, b.filter(e => { const i = e.querySelector('img'); return i && i.complete && i.naturalWidth >= 16; }).length]; }"""
    a0, t0 = page.evaluate(POS), page.evaluate("performance.now()")
    hold[0] = False
    while held:
        held.pop().fulfill(status=200, body=GIF1, content_type="image/gif")
    page.wait_for_timeout(2000)
    a1 = page.evaluate(POS)
    ls = page.evaluate(SHIFTS, t0)
    check(f"{tag} thumbs: every All-strip thumb comes back blank, late: strip keeps its height, results below stay put, failed visible slots stay as empty tiles, no layout shift",
          a1[0] == a0[0] and a1[1] == a0[1] and a1[2] >= 1 and a1[3] >= 1 and a1[4] == 0 and not ls, [a0, a1, ls[:2]])
    ctx.close()
    # failure order: the strip's last tile fails first (empty slot), then the first one: its slot gets a tile with an image, never the empty one
    page, ctx, release, blank = held_thumbs(t)
    pick = page.evaluate("() => { const b = document.querySelector('#panel-google .g-strip').children; return [b[0], b[b.length - 1]].map(e => e.querySelector('img').getAttribute('src')); }")
    release(pick)
    page.evaluate(STRIP_IN_VIEW)
    page.evaluate("() => { const s = document.querySelector('#panel-google .g-strip'); s.scrollTo({left: s.scrollWidth, behavior: 'instant'}); }")
    page.wait_for_timeout(800)
    blank(pick[1])
    page.wait_for_timeout(500)
    page.evaluate("() => { const b = document.querySelector('#panel-google .g-strip').children; b[b.length - 2].focus({preventScroll: true}); }")   # the donor has focus
    page.evaluate("document.querySelector('#panel-google .g-strip').scrollTo({left: 0, behavior: 'instant'})")
    page.wait_for_timeout(800)
    t0 = page.evaluate("performance.now()")
    blank(pick[0])
    page.wait_for_timeout(1200)
    lf = page.evaluate("""() => { const b = [...document.querySelector('#panel-google .g-strip').children], i = b[0].querySelector('img'), e = b[b.length - 1];
        return {first: !!i && !b[0].querySelector('.g-img-none'), painted: !!i && i.complete && i.naturalWidth >= 16, lastEmpty: !!e.querySelector('.g-img-none'),
                lastName: (e.matches('a, button') ? e : e.querySelector('a, button')).getAttribute('aria-label') || '', n: b.length, focus: document.activeElement === b[0]}; }""")
    lf["inView"] = page.evaluate("() => { const r = document.querySelector('#panel-google .g-strip').getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }")
    lf["shift"] = page.evaluate(SHIFTS, t0)
    check(f"{tag} thumbs: last strip tile fails first (empty slot keeps a name), then the first: its slot gets a tile with an image (not the empty one), a focused donor keeps focus; no layout shift",
          lf["inView"] and lf["first"] and lf["painted"] and lf["focus"] and lf["lastEmpty"] and lf["lastName"] and not lf["shift"], lf)
    ctx.close()
    # viewing the strip's end: its last 6 tiles fail (empty slots fill the view), then the first one: nothing at the end moves, no clamp
    page, ctx, release, blank = held_thumbs(t)
    pick = page.evaluate("() => { const b = [...document.querySelector('#panel-google .g-strip').children]; return [b[0]].concat(b.slice(-6)).map(e => e.querySelector('img').getAttribute('src')); }")
    release(pick)
    page.evaluate(STRIP_IN_VIEW)
    page.evaluate("() => { const s = document.querySelector('#panel-google .g-strip'); s.scrollTo({left: s.scrollWidth, behavior: 'instant'}); }")
    page.wait_for_timeout(800)
    for src in pick[1:]:
        blank(src)
    page.wait_for_timeout(800)
    END = """() => { const s = document.querySelector('#panel-google .g-strip'), b = [...s.children];
        return [Math.round(s.scrollLeft), Math.round(b[b.length - 1].getBoundingClientRect().left), b.length, b.slice(-6).filter(e => e.querySelector('.g-img-none')).length]; }"""
    e0, t0 = page.evaluate(END), page.evaluate("performance.now()")
    blank(pick[0])
    page.wait_for_timeout(1000)
    e1 = page.evaluate(END)
    ls = page.evaluate(SHIFTS, t0)
    check(f"{tag} thumbs: viewing the strip's end, its last 6 fail then the first: the end stays put (scroll position, tiles), no layout shift",
          e0[3] == 6 and e1[:3] == e0[:3] and not ls, [e0, e1, ls[:2]])
    ctx.close()


def free_phone(t):
    """(3) the #free phone: tabs, the illustration without a scan, her report with one."""
    tag, m, ctx_, shot, overflow = t.tag, t.m, t.ctx_, t.shot, t.overflow
    # ---------- (3) #free phone: tabs, illustration without a scan ----------
    ctx = ctx_()
    page = ctx.new_page()
    page.goto(cfg.base, wait_until="load")
    bring(page, "#free", "center")
    page.wait_for_timeout(900)
    PH = """(sel) => { const ph = document.querySelector(sel), r = ph.getBoundingClientRect();
        return {box: [Math.round(r.x), Math.round(r.y + scrollY), Math.round(r.width), Math.round(r.height)],
          sel: [...ph.querySelectorAll('[role=tab]')].map(b => [b.textContent, b.getAttribute('aria-selected'), b.tabIndex]),
          shown: [...ph.querySelectorAll('[role=tabpanel]')].filter(p => !p.hidden && p.offsetParent !== null).map(p => p.id),
          shifts: window.__ls.filter(x => x[1] > 0).length, focus: document.activeElement && document.activeElement.id}; }"""
    s0 = page.evaluate(PH, ".phone-free")
    check(f"{tag} free: no scan → Images tab selected, illustration tiles, search 'yourhandle nude leaks'", s0["shown"] == ["panel-free-images"] and s0["sel"][1] == ["Images", "true", 0]
          and page.inner_text(".phone-free [data-p=scan-handle]") == "yourhandle nude leaks", s0)
    boxes, seen, shifts = [s0["box"]], [], []
    for k, label in (("all", "All"), ("images", "Images"), ("videos", "Videos")):
        # per click, before shot() (its light/dark flip is not a tab switch); the fixed Ask-AI pill's own height
        # animation (pre-existing, main) is not the tab's doing either
        t0 = page.evaluate("performance.now()")
        page.locator(f"#tab-free-{k}").click()
        page.wait_for_timeout(250)
        shifts += page.evaluate("t0 => window.__ls.filter(x => x[0] >= t0 && x[1] > 0 && !x[3].every(n => n.startsWith('BUTTON.askai-launcher'))).map(x => [x[1], x[3]])", t0)
        sk = page.evaluate(PH, ".phone-free")
        boxes.append(sk["box"])
        seen.append(sk["shown"] == [f"panel-free-{k}"] and [x[1] for x in sk["sel"]] == ["true" if x[0] == label else "false" for x in sk["sel"]])
        shot(page, f"3-free-{k}-demo", "#free .free-phone")
    check(f"{tag} free: tabs switch on click (All / Images / Videos), the phone never moves or resizes, zero layout shift",
          all(seen) and len({tuple(b) for b in boxes}) == 1 and not shifts, (seen, boxes, shifts))
    page.locator("#tab-free-videos").focus()
    page.keyboard.press("ArrowRight")
    k1 = page.evaluate(PH, ".phone-free")
    page.keyboard.press("End")
    k2 = page.evaluate(PH, ".phone-free")
    check(f"{tag} free: keyboard: → wraps to All, End = Videos (roving tabindex)", k1["focus"] == "tab-free-all" and k1["shown"] == ["panel-free-all"]
          and k2["focus"] == "tab-free-videos" and k2["shown"] == ["panel-free-videos"] and [x[2] for x in k2["sel"]] == [-1, -1, 0], (k1, k2))
    m["free_phone_box"] = s0["box"]
    m["overflow_no_scan"] = overflow(page)
    ctx.close()

    # with a report: her handle, rows, tiles (Reveal), videos
    ctx = ctx_()
    page = ctx.new_page()
    page.goto(cfg.base + "?r=" + FX["slug"] + "#free", wait_until="load")
    page.wait_for_selector(".phone-free.is-live", timeout=8000)
    page.wait_for_timeout(1500)
    bring(page, "#free", "center")
    d = served(FX["slug"])
    rows = links(d)
    VID = [r for r in d.get("results", []) if r.get("kind") == "video"]
    hero_n = digits(settled_count(page, "#tab-report-images .live-tab-n"))
    strip18 = page.evaluate(TILES, ".report-card .live-strip a.gi-card")[:18]
    lv = page.evaluate("""() => { const ph = document.querySelector('.phone-free'), q = s => [...ph.querySelectorAll(s)];
        return {search: ph.querySelector('[data-p=scan-handle]').textContent, label: ph.getAttribute('aria-label'),
          all: q('[data-live=free-all] a.m-link').map(a => [a.href, a.target, a.querySelector('.m-site').textContent]),
          tiles: q('[data-live=free-images] a.gi-card').map(a => [decodeURIComponent(a.querySelector('img').getAttribute('src').split('u=')[1]), a.href, a.target, true]),
          n: (ph.querySelector('[data-live=free-images] .m-n') || {}).textContent,
          vids: q('[data-live=free-videos] a.m-link').map(a => a.href), illus: q('.m-illus').filter(e => e.offsetParent !== null).length}; }""")
    check(f"{tag} free: report → search = 'handle nude leaks', All = her first 8 rows (new tab), Images = first 18 that load + count, Videos = her first 6",
          lv["search"] == "demo.creator nude leaks" and lv["label"] == "Google results for @demo.creator" and [x[0] for x in lv["all"]] == [r[0] for r in rows[:8]]
          and all(x[1] == "_blank" for x in lv["all"]) and [t[:3] for t in lv["tiles"]] == [t[:3] for t in strip18] and len(lv["tiles"]) == len(strip18)
          and not tiles_ok(lv["tiles"], d) and lv["n"] == f"{hero_n} images"
          and lv["vids"] == [r["link"] for r in VID[:6]] and lv["illus"] == 0, lv)
    for k in ("all", "images", "videos"):
        page.locator(f"#tab-free-{k}").click()
        page.wait_for_timeout(500 if k == "images" else 250)
        if k == "images":
            b0 = page.evaluate("getComputedStyle(document.querySelector('#panel-free-images .gi-img')).filter")
            page.locator("#panel-free-images .reveal-btn").click()
            page.wait_for_timeout(400)
            b1 = page.evaluate("[getComputedStyle(document.querySelector('#panel-free-images .gi-img')).filter, document.querySelector('#panel-free-images .reveal-btn').getAttribute('aria-pressed')]")
            shot(page, "3-free-images-revealed", "#free .free-phone")
            page.locator("#panel-free-images .reveal-btn").click()
            page.wait_for_timeout(300)
            check(f"{tag} free: report → blurred by default, Reveal unblurs, Blur again", "blur" in b0 and b1 == ["none", "true"], (b0, b1))
        shot(page, f"3-free-{k}", "#free .free-phone")
    # each tab scrolls inside the fixed screen (a wheel on it moves the list, not the page; at its end a new wheel still
    # scrolls the page: no trap); "Show more" adds the next batch (8 / 18 / 6), no repeat, the page never moves; once all
    # show it goes. All / Videos end at every served link / video; Images at what loads (judged by tiles_ok)
    PANEL = """(k) => { const p = document.getElementById('panel-free-' + k), b = p.querySelector('.m-more'), ph = document.querySelector('.phone-free').getBoundingClientRect();
        const ids = k === 'images' ? [...p.querySelectorAll('[data-live] .m-grid > a.gi-card')].map(a => decodeURIComponent(a.querySelector('img').getAttribute('src').split('u=')[1]))
          : [...p.querySelectorAll('[data-live] a.m-link')].map(a => a.href);
        return {ids, more: !!b && !b.hidden, scroll: [p.scrollTop, p.scrollHeight, p.clientHeight], y: scrollY,
          phone: [ph.x, ph.y, ph.width, ph.height].map(Math.round)}; }"""
    bring(page, ".phone-free", "center")
    page.wait_for_timeout(300)
    for k, step, want in (("all", 8, [r[0] for r in rows]), ("images", 18, None), ("videos", 6, [r["link"] for r in VID])):
        page.locator(f"#tab-free-{k}").click()
        page.wait_for_timeout(300)
        p0 = page.evaluate(PANEL, k)
        bx = page.locator(f"#panel-free-{k}").bounding_box()
        page.mouse.move(bx["x"] + bx["width"] / 2, bx["y"] + bx["height"] / 2)
        page.mouse.wheel(0, 200)
        page.wait_for_timeout(500)
        p1 = page.evaluate(PANEL, k)
        check(f"{tag} free: report → {k}: the list scrolls inside the phone (same box), a wheel on it moves the list, not the page",
              p0["scroll"][1] > p0["scroll"][2] and p1["scroll"][0] > p0["scroll"][0] and p1["y"] == p0["y"] and p1["phone"] == p0["phone"],
              (p0["scroll"], p1["scroll"], p0["y"], p1["y"], p0["phone"], p1["phone"]))
        page.evaluate("k => { const p = document.getElementById('panel-free-' + k); p.scrollTop = p.scrollHeight; }", k)
        page.wait_for_timeout(300)
        shot(page, f"3-free-{k}-more", "#free .free-phone")   # the trigger: the list's end, "Show more"
        seen, last = [p0], p0
        while last["more"] and len(seen) < 30:
            page.locator(f"#panel-free-{k} .m-more").click()
            page.wait_for_timeout(700 if k == "images" else 250)
            last = page.evaluate(PANEL, k)
            seen.append(last)
        n = [len(x["ids"]) for x in seen]
        grew = len(n) > 1 and all(0 < b - a <= step for a, b in zip(n, n[1:])) and n[0] == min(step, n[-1])
        kept = all(x["ids"][:len(y["ids"])] == y["ids"] for y, x in zip(seen, seen[1:]))
        ok_end = last["ids"] == want if want else (not tiles_ok([[u, "", "", True] for u in last["ids"]], d)
                                                   and len(last["ids"]) == digits(page.inner_text("#panel-free-images .m-n")))
        check(f"{tag} free: report → {k}: Show more adds up to {step} per click (no repeat, earlier ones kept in place), ends at every item (Images: its count), then goes; the page / phone never move",
              grew and kept and ok_end and len(set(last["ids"])) == len(last["ids"]) and not last["more"]
              and {x["y"] for x in seen} == {p0["y"]} and {tuple(x["phone"]) for x in seen} == {tuple(p0["phone"])},
              (n, kept, ok_end, [x["y"] for x in seen], want and len(want)))
        page.evaluate("k => { const p = document.getElementById('panel-free-' + k); p.scrollTop = p.scrollHeight; }", k)
        page.wait_for_timeout(500)
        shot(page, f"3-free-{k}-more-end", "#free .free-phone")   # settled: every item, no button
        y0 = page.evaluate("scrollY")
        page.mouse.wheel(0, 200)
        page.wait_for_timeout(500)
        check(f"{tag} free: report → {k}: at the list's end a new wheel on the phone scrolls the page (no trap)", page.evaluate("scrollY") > y0)
        bring(page, ".phone-free", "center")
        page.wait_for_timeout(200)
    m["overflow_report"] = overflow(page)
    ctx.close()


def order_popout(t):
    """(2) section order, Before / After tabs, pop-out, no horizontal overflow."""
    vp_name, vp, tag, m, ctx_, shot, overflow = t.vp_name, t.vp, t.tag, t.m, t.ctx_, t.shot, t.overflow
    # ---------- (2) order, Before / After tabs, pop-out ----------
    ctx = ctx_()
    page = ctx.new_page()
    page.goto(cfg.base, wait_until="load")
    order = page.evaluate("""() => { const y = e => e.getBoundingClientRect().top + scrollY, b = e => e.getBoundingClientRect().bottom + scrollY;
        const w = document.getElementById('website'), sc = document.getElementById('showcase'), fr = sc.querySelector('.browser-demo'), ba = document.querySelector('.ba');
        return {website: Math.round(y(w)), showcase: Math.round(y(sc)), frameBottom: Math.round(b(fr)), ba: Math.round(y(ba)), inShowcase: sc.contains(ba),
          link: (a => a && a.getAttribute('href'))(sc.querySelector('a.btn[data-p=demo]'))}; }""")
    check(f"{tag} order: #website copy → demo iframe (#showcase) → Before / After phones below it; 'Open the demo site' link kept",
          order["website"] < order["showcase"] < order["frameBottom"] <= order["ba"] and order["inShowcase"] and order["link"] == "showcase/", order)
    bring(page, "#showcase .ba", "center")
    page.wait_for_timeout(900)
    ok, shifts = [], []
    for side in ("before", "after"):
        for k in ("images", "videos", "all"):
            t0 = page.evaluate("performance.now()")
            page.locator(f"#tab-{side}-{k}").click()
            page.wait_for_timeout(300)
            shifts += page.evaluate("t0 => window.__ls.filter(x => x[0] >= t0 && x[1] > 0 && !x[3].every(n => n.startsWith('BUTTON.askai-launcher'))).map(x => [x[1], x[3]])", t0)
            r = page.evaluate("(id) => document.getElementById(id).closest('.phone').getBoundingClientRect().height", f"panel-{side}-{k}")
            vis = page.evaluate(f"[...document.querySelectorAll('[id^=panel-{side}-]')].filter(p => !p.hidden).map(p => p.id)")
            imgs = page.evaluate(f"[...document.querySelectorAll('#panel-{side}-{k} img')].map(i => i.complete && i.naturalWidth > 0)")
            ok.append([side, k, vis == [f"panel-{side}-{k}"], all(imgs), round(r)])
            if k != "all":
                shot(page, f"2-ba-{side}-{k}", "#showcase .ba")
    hs = {x[4] for x in ok}
    check(f"{tag} before/after: All / Images / Videos switch in both phones, their photos load, phone height fixed (no CLS)",
          all(x[2] and x[3] for x in ok) and len(hs) == 1 and not shifts, (ok, shifts))
    shot(page, "2-before-after", "#showcase .ba")
    m["overflow_before_after"] = overflow(page)
    # pop-out
    bring(page, "#showcase .browser-demo", "center")
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

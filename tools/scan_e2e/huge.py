"""Scenario `scan`, part 2 (run right after scan.py): `stub-huge`, 1000 hit links on 100 sites at CPU x4. See
tools/scan_e2e.py; checks named "incremental: …" are the ones --break-incremental must turn red, nothing else."""
import json
import pathlib
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import TimeoutError as PWTimeout

from .common import PIP_AWAY, cfg, check, digits, new_ctx, scan_images, served, touch_scroll


def by_site(d):
    """domain → {url: 1} over a served result's hits, then its Google results (the order the API sends them)."""
    out = {}
    for u, dom in [(h["url"], h["domain"]) for h in d.get("hits", [])] + [(r["link"], r["domain"]) for r in d.get("results", [])]:
        out.setdefault(dom, {})[u] = 1
    return out


NODE_BUDGET = 905   # whole page after the report renders (main before this change: ~3,800 at this size); 900 + analytics.js's script + footer link
IN_VIEW = """() => { const a = document.activeElement, r = a.getBoundingClientRect(), s = a.closest('.ph-scroll');
    let top = document.querySelector('.rnav').getBoundingClientRect().bottom, bot = innerHeight;   /* clear of the sticky nav, */
    if (s) { const sr = s.getBoundingClientRect(), t = s.querySelector('.g-tabs');                 /* inside the phone screen, */
        top = Math.max(top, sr.top, t ? t.getBoundingClientRect().bottom : 0); bot = Math.min(bot, sr.bottom); }   /* under its tabs */
    return r.top >= top - 1 && r.bottom <= bot + 1 ? true : [Math.round(r.top), Math.round(r.bottom), Math.round(top), Math.round(bot)]; }"""


STRIP = """() => { const s = document.querySelector('#panel-google .g-strip'); if (!s) return null; const b = [...s.querySelectorAll(':scope > .g-pack-b')], cs = getComputedStyle(s),
    sl = s.getBoundingClientRect().left + parseFloat(cs.scrollPaddingLeft || 0), w = s.parentNode;
    return {n: b.length, rows: new Set(b.map(e => e.offsetTop)).size, tile: [Math.round(b[0].offsetWidth), Math.round(b[0].offsetHeight)], sw: s.scrollWidth, cw: s.clientWidth,
      left: Math.round(s.scrollLeft), snap: cs.scrollSnapType, ox: cs.overflowX, bar: s.offsetHeight - s.clientHeight, open: b.every(e => e.matches('a[target=_blank][href^=http], button[data-goto=images]')) && b.some(e => e.matches('a')),
      snapped: b.some(e => Math.abs(e.getBoundingClientRect().left - sl) <= 2), start: w.classList.contains('at-start'), end: w.classList.contains('at-end'),
      lazy: b.every(e => e.querySelector('img').loading === 'lazy'), showMore: /show more images/i.test(document.getElementById('panel-google').textContent),
      pageX: document.documentElement.scrollWidth - innerWidth, inner: (document.querySelector('.ph-scroll') || {}).scrollTop || 0}; }"""


def strip_flow(page, cdp, tag, vp_name, vp, n_img):
    """The All tab's Images block: one row, every image, swipe sideways (snap), keyboard + desktop arrows; the page never
    scrolls sideways."""
    phone = vp_name == "phone"
    page.locator("#tab-google-all").click()
    page.wait_for_timeout(250)
    s0 = page.evaluate(STRIP)
    check(f"{tag} strip: All tab Images = one row of all {n_img} images, square {'~110px' if phone else '150px'} tiles, scrollWidth > clientWidth, snap x mandatory, no scrollbar, no 'Show more images', each tile opens its page (or the Images tab)",
          s0 and s0["n"] == n_img and s0["rows"] == 1 and abs(s0["tile"][0] - s0["tile"][1]) <= 1 and (95 <= s0["tile"][0] <= 125 if phone else s0["tile"][0] == 150)
          and s0["sw"] > s0["cw"] and s0["snap"] == "x mandatory" and s0["ox"] == "auto" and s0["bar"] == 0 and not s0["showMore"] and s0["open"] and s0["lazy"] and s0["start"], s0)
    sb = page.eval_on_selector("#panel-google .g-strip", "s => { const r = s.getBoundingClientRect(); return [r.left + r.width * .75, r.top + r.height / 2]; }")
    if phone:   # a real touch swipe (right → left), momentum + snap settle
        touch_scroll(page, cdp, int(sb[0]), int(min(sb[1], vp["height"] - 10)), dx=-260, speed=1200)
    else:       # hover shows the arrows; the next arrow pages the strip
        page.mouse.move(*sb)
        page.wait_for_timeout(350)
        arrows = page.evaluate("() => ['.g-strip-prev', '.g-strip-next'].map(c => { const b = document.querySelector('#panel-google ' + c); return [+getComputedStyle(b).opacity, b.disabled, b.getAttribute('aria-label')]; })")
        try:
            page.locator("#panel-google .g-strip-next").click(timeout=3000)
        except PWTimeout:
            arrows.append("next not clickable")
    page.wait_for_timeout(1200)
    s1 = page.evaluate(STRIP)
    page.screenshot(path=str(cfg.out / f"{vp_name}-h2b-strip-swiped.png"))
    if phone:
        check(f"{tag} strip: a touch swipe left scrolls the strip and snaps to a tile; page and phone screen stay put", s1["left"] > 100 and s1["snapped"] and s1["pageX"] <= 0
              and s1["inner"] == s0["inner"] and not s1["start"], [s0["left"], s1])
    else:
        prev_on = page.evaluate("() => !document.querySelector('#panel-google .g-strip-prev').disabled")
        check(f"{tag} strip: desktop arrows on hover, named (prev hidden + disabled at the start), next pages the strip and snaps, then prev is enabled",
              arrows[0][:2] == [0, True] and arrows[1][:2] == [1, False] and arrows[0][2] and arrows[1][2] and prev_on
              and s1["left"] >= 0.6 * s1["cw"] and s1["snapped"] and not s1["start"] and s1["pageX"] <= 0, [arrows, prev_on, s1])
        page.mouse.move(0, 0)
    page.locator("#panel-google .g-strip > .g-pack-b").first.focus()
    kk = []
    for key in ("ArrowRight", "ArrowRight", "ArrowLeft", "End", "Home"):
        page.keyboard.press(key)
        page.wait_for_timeout(450)
        kk.append(page.evaluate("() => { const a = document.activeElement, b = [...document.querySelectorAll('#panel-google .g-strip > .g-pack-b')]; return b.indexOf(a); }"))
        if key == "End":
            kk.append(page.evaluate("document.querySelector('#panel-google .g-strip-w').classList.contains('at-end')"))
    page.keyboard.press("Tab")
    kk.append(page.evaluate("() => [...document.querySelectorAll('#panel-google .g-strip > .g-pack-b')].indexOf(document.activeElement)"))
    check(f"{tag} strip: keyboard → / ← / End / Home move focus along the tiles (End scrolls the strip to its end), Tab reaches the next one",
          kk == [1, 2, 1, n_img - 1, True, 0, 1], kk)
    page.locator("#panel-google .g-strip").evaluate("s => s.scrollTo({left: 0, behavior: 'instant'})")
    page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
    page.wait_for_timeout(200)


def huge_flow(browser, vp_name, vp):
    """stub-huge (1000 hit links on 100 sites): render time, DOM size, incremental sites / links, filter, the pinned
    phone scroll story, CLS, lazy thumbs, export, no 5xx / console errors. Checks named "incremental: …" are the ones
    --break-incremental (scan.js with every step = 1e9, everything rendered) must turn red; nothing else may."""
    phone = vp_name == "phone"
    tag = f"{vp_name} huge:"
    ctx, net = new_ctx(browser, vp_name, vp, init=[PIP_AWAY], accept_downloads=True)   # player put away (common.PIP_AWAY)
    bad, thumbs = [], []
    page = ctx.new_page()
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
    page.goto(cfg.base + "scan/?h=stub-huge", wait_until="load")
    page.wait_for_selector("#report:not([hidden])", timeout=20000)
    page.wait_for_function("performance.getEntriesByName('leakscan:report').length > 0", timeout=5000)
    hd = served(parse_qs(urlsplit(page.url).query).get("r", [""])[0])   # the oracle: what the API sent
    sites, n_img, n_vid = by_site(hd), len(scan_images(hd)), sum(r.get("kind") == "video" for r in hd["results"])
    n_links = sum(len(v) for v in sites.values())
    biggest = max(sites, key=lambda d: len(sites[d]))
    ms = page.evaluate("performance.getEntriesByName('leakscan:report')[0].duration")
    check(f"{tag} report painted < 1500 ms after the result event (CPU x4)", ms < 1500, f"{ms:.0f} ms")
    nodes, pipn = page.evaluate("""() => [document.getElementsByTagName('*').length,   // the mini player (fixed, same size on every page) not the report's
        [...document.querySelectorAll('.pip, .pip-tab')].reduce((n, e) => n + 1 + e.getElementsByTagName('*').length, 0)]""")
    check(f"{tag} incremental: page DOM <= {NODE_BUDGET} elements after render (the mini player's own elements aside)", nodes - pipn <= NODE_BUDGET, [nodes, pipn])
    check(f"{tag} summary + section nav say 100 sites / 1,000 pages", (digits(page.locator("[data-stat=domains]").inner_text()),
          digits(page.locator("[data-stat=pages]").inner_text()), page.locator("#rnav-n").inner_text()) == (100, 1000, "100"))
    check(f"{tag} heading line: every site + link counted", page.locator("#lx-sub").inner_text() == f"100 sites · {n_links:,} links (1,000 indexed pages + {n_links - 1000} more Google results) · most copies first",
          page.locator("#lx-sub").inner_text())
    rows = lambda: page.locator("#lx-list .lx-site").count()
    check(f"{tag} incremental: 10 sites, no link rows until a site is opened, 'Show 25 more sites · 90 left'",
          (rows(), page.locator("#lx-list a").count(), page.locator("#lx-more").inner_text()) == (10, 0, "Show 25 more sites · 90 left"),
          (rows(), page.locator("#lx-list a").count(), page.locator("#lx-more").inner_text()))
    first = page.locator("#lx-list .lx-name").first.inner_text()
    check(f"{tag} biggest site first", first == biggest, first)
    thumbs0 = len(set(thumbs))   # at load, before any scroll / tab / reopen; distinct images (a tile's CORS load may re-read its own thumb)
    check(f"{tag} lazy thumbs: at load <= 24 of {n_img} images fetched (strip + first screen only)", thumbs0 <= 24, (thumbs0, len(thumbs)))

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
            page.locator(f"#tab-google-{t}").click()
            page.wait_for_timeout(300)
            runs[t] = page.evaluate("""() => { const t = document.querySelector('.ph-track'), s = t.querySelector('.ph-scroll'), tl = [...document.querySelectorAll('#panel-google .g-tile, #panel-google .g-v')];
                const last = tl[tl.length - 1], sr = s.getBoundingClientRect();
                return {run: t.offsetHeight - t.firstElementChild.offsetHeight, more: !!document.querySelector('#panel-google [data-more]'), n: tl.length,
                        cols: tl.filter(e => e.offsetTop === (tl[0] && tl[0].offsetTop)).length, inner: tl.every(e => s.contains(e)),
                        reach: !last || last.getBoundingClientRect().bottom - sr.top + s.scrollTop <= s.scrollHeight + 1}; }""")
        page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
        ri, rv = runs["images"], runs["videos"]
        check(f"{tag} pin: All first look <= 1.5 screens, rest behind More", runs["all"]["run"] <= 1.5 * g["vh"] and runs["all"]["more"], [runs["all"], g["vh"]])
        check(f"{tag} pin: Images first look = 4 rows x 3 = {min(n_img, 12)} of {n_img} inside the screen's own scroll (< 1 screen of scrolling), rest behind More",
              ri["n"] == min(n_img, 12) and ri["cols"] == 3 and ri["inner"] and ri["reach"] and ri["more"] == (n_img > 12) and ri["run"] < g["vh"], [ri, g["vh"]])
        check(f"{tag} pin: Videos first look = 5 of {n_vid} inside the screen's own scroll (<= 1.75 screens of scrolling, relaxed), rest behind More",
              rv["n"] == min(n_vid, 5) and rv["inner"] and rv["reach"] and rv["more"] == (n_vid > 5) and rv["run"] <= 1.75 * g["vh"], [rv, g["vh"]])
        # hand-off: 60 px before the screen's end, a 400 px wheel / touch scroll over the phone ends the screen and moves the
        # page the rest (frame goes up, nothing stuck); "Show more …" is hidden (rise) until it enters the screen, then shown
        HO = """() => { const f = document.querySelector('.frame-phone'), s = f.querySelector('.ph-scroll'), m = document.querySelector('#panel-google [data-more]');
            return {y: Math.round(scrollY), st: Math.round(s.scrollTop), max: s.scrollHeight - s.clientHeight, ft: Math.round(f.getBoundingClientRect().top),
                    rise: !!m && m.classList.contains('g-rise'), seen: !!m && m.classList.contains('g-in'), op: m ? +getComputedStyle(m).opacity : -1}; }"""
        OP = "() => { const m = document.querySelector('#panel-google [data-more]'); return m ? +getComputedStyle(m).opacity : -1; }"
        ho, rise = {}, {}
        for t in ("images", "videos"):
            page.locator(f"#tab-google-{t}").click()
            rise[t] = [page.evaluate(OP)]   # no flash: hidden from the first frame
            page.evaluate("document.querySelector('#panel-google [data-more]').focus({preventScroll: true})")
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
                    touch_scroll(page, page.context.new_cdp_session(page), int(cx), int(cy), dy=-400, speed=1200)
                page.wait_for_timeout(800)
                z = page.evaluate(HO)
                ho[f"{t}/{how}"] = {"hidden_at_top": [a0["rise"], a0["seen"], a0["op"]], "dy": z["y"] - a["y"], "st": [a["st"], z["st"], z["max"]],
                                    "frame_up": g["pin"] - z["ft"], "shown": [z["seen"], z["op"]]}
            page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
            page.wait_for_timeout(200)
        page.locator("#tab-google-all").click()
        page.wait_for_timeout(300)
        check(f"{tag} pin: Images / Videos hand-off: a wheel / touch scroll past the screen's end moves the page (screen at its end, frame goes up the rest)",
              all(abs(v["dy"] - 400) <= 8 and v["st"][1] == v["st"][2] and abs(v["frame_up"] - (400 - (v["st"][2] - v["st"][0]))) <= 8 for v in ho.values()), ho)
        check(f"{tag} pin: 'Show more images / videos' hidden until it enters the screen, then shown (rise animation, ends at opacity 1)",
              all(v["hidden_at_top"] == [True, False, 0] and v["shown"] == [True, 1] for k, v in ho.items() if k.endswith("wheel")), ho)
        check(f"{tag} pin: 'Show more …' rise: no flash (opacity 0 from the tab's first frame), keyboard focus shows it at once", all(v == [0, 1] for v in rise.values()), rise)
        rctx = browser.new_context(viewport=vp, device_scale_factor=2, is_mobile=True, has_touch=True, reduced_motion="reduce")
        rp = rctx.new_page()
        rp.goto(cfg.base + "scan/?r=" + parse_qs(urlsplit(page.url).query).get("r", [""])[0], wait_until="load")
        rp.wait_for_selector("#report:not([hidden])", timeout=8000)
        rm = {}
        for t in ("images", "videos"):
            rp.locator(f"#tab-google-{t}").click()
            rm[t] = rp.evaluate("() => { const m = document.querySelector('#panel-google [data-more]'); return [m.classList.contains('g-rise'), +getComputedStyle(m).opacity]; }")
        rctx.close()
        check(f"{tag} pin: reduced motion: 'Show more …' never hidden, no rise", all(v == [False, 1] for v in rm.values()), rm)
        page.evaluate(f"window.scrollTo({{top: {g['top'] - g['pin'] + 400}, behavior: 'instant'}})")
        page.wait_for_timeout(250)
        st = page.evaluate("() => [document.querySelector('.frame-phone').getBoundingClientRect().top, document.querySelector('.ph-scroll').scrollTop]")
        check(f"{tag} pin: mid-scroll the frame stays put and its screen scrolls 1:1", abs(st[0] - g["pin"]) <= 1 and abs(st[1] - 400) <= 2, st)
        page.screenshot(path=str(cfg.out / f"{vp_name}-h2-pinned.png"))
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
        page.locator("#tab-google-images").click()
        page.wait_for_timeout(250)
        st = page.evaluate("() => [document.querySelector('.frame-phone').getBoundingClientRect().top, document.querySelector('.ph-scroll').scrollTop, document.querySelectorAll('#panel-google .g-tile').length]")
        check(f"{tag} pin: a tab switched mid-scroll opens at its top, frame stays put", abs(st[0] - g["pin"]) <= 1 and st[1] == 0 and st[2] > 0, st)
        page.locator("#tab-google-all").click()
        had = page.locator("#panel-google .g-r").count()
        page.locator("[data-more=all]").evaluate("b => b.focus()")   # as Tab would: the screen scrolls to it, the page follows
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        page.wait_for_timeout(400)
        nx = page.evaluate("() => { const a = document.activeElement, r = a.closest('.g-r'); return [a.className, [...document.querySelectorAll('#panel-google .g-r')].indexOf(r)]; }")
        nx.append(page.evaluate(IN_VIEW))
        check(f"{tag} keyboard More results → focus on the first new result, in view", nx == ["g-title", had, True], [nx, had])
        page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
        page.wait_for_timeout(150)
    strip_flow(page, cdp, tag, vp_name, vp, n_img)
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
    page.screenshot(path=str(cfg.out / f"{vp_name}-h3-past-mock.png"))
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
    n_top = len(sites[biggest])
    page.wait_for_timeout(150)
    lm = top.locator(".lx-lmore")
    got = (top.locator("a").count(), lm.inner_text() if lm.count() else None)
    check(f"{tag} incremental: an opened site shows 10 links + 'Show 50 more links · {n_top - 10} left'", got == (10, f"Show 50 more links · {n_top - 10} left"), got)
    hrefs = top.locator("a").evaluate_all("els => els.map(e => e.href)")
    check(f"{tag} opened site lists its own links, external + safe", set(hrefs) <= set(sites[biggest]) and top.locator("a").first.get_attribute("rel") == "noopener noreferrer nofollow"
          and top.locator("a").first.get_attribute("target") == "_blank", hrefs[:2])
    while top.locator(".lx-lmore").count():
        top.locator(".lx-lmore").click()
    check(f"{tag} every link of the site reachable", top.locator("a").count() == n_top, top.locator("a").count())
    top.locator("summary").evaluate("e => e.scrollIntoView({block: 'center', behavior: 'instant'})")   # as bring()
    page.screenshot(path=str(cfg.out / f"{vp_name}-h4-open-site.png"))
    top.locator("summary").click()
    page.wait_for_timeout(100)
    check(f"{tag} closing a site drops its links from the DOM", top.locator("a").count() == 0)

    # 4. filter: by site, by URL part, nothing; clear
    def filt(q):
        page.locator("#lx-q").fill(q)
        page.wait_for_timeout(350)
        return page.locator("#lx-status").inner_text()
    q = "thread/1"
    want = {d: [u for u in us if q in u.lower()] for d, us in sites.items()}
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
    page.screenshot(path=str(cfg.out / f"{vp_name}-h5-filter.png"))
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
    check(f"{tag} Download .txt carries every link ({n_links})", got == {u for us in sites.values() for u in us}, len(got))

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
    page.goto(cfg.base + "scan/?r=" + slug)
    page.wait_for_selector("#report:not([hidden])", timeout=8000)
    page.wait_for_function("performance.getEntriesByName('leakscan:report').length > 0", timeout=5000)
    ms2 = page.evaluate("performance.getEntriesByName('leakscan:report')[0].duration")
    check(f"{tag} ?r= reopen: built + painted < 1500 ms (CPU x4)", ms2 < 1500, f"{ms2:.0f} ms")
    check(f"{tag} incremental: ?r= reopen shows the first 10 sites", rows() == 10, rows())
    page.screenshot(path=str(cfg.out / f"{vp_name}-h1-top.png"))
    cls = [cls0, page.evaluate(CLS)]
    check(f"{tag} no layout shift without input over the whole flow (CLS 0: form → progress → report → scroll story; ?r= reopen)", cls[0][0] == 0 and cls[1][0] == 0, cls)
    check(f"{tag} no 5xx", not bad, bad)
    check(f"{tag} no request left loopback", not net["outside"], net["outside"])
    check(f"{tag} no JS / console errors", not net["errors"] and not net["console"], net["errors"] + net["console"])
    (cfg.out / f"{vp_name}-huge-metrics.json").write_text(json.dumps({"render_ms": round(ms), "reopen_ms": round(ms2), "dom_elements": nodes,
                                                                  "wheel_steps_to_sites": steps, "cls": [cls[0][0], cls[1][0]], "thumbs_at_load": thumbs0, "thumbs_total": len(thumbs)}))
    ctx.close()
    if phone:   # screens too short to pin the phone: a shorter static preview, no scroll box inside the page; More expands it
        for w, h in ((320, 568), (390, 560)):
            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2, is_mobile=True, has_touch=True)
            p2 = ctx.new_page()
            p2.goto(cfg.base + "scan/?r=" + slug)
            p2.wait_for_selector("#report:not([hidden])", timeout=8000)
            p2.wait_for_timeout(300)
            SCROLLERS = """() => [...document.querySelectorAll('#report *')].filter(e => ['auto', 'scroll'].includes(getComputedStyle(e).overflowY)
                && e.scrollHeight > e.clientHeight + 1).map(e => e.className)"""
            r = p2.evaluate("""() => { const f = document.querySelector('.frame-phone'); return [getComputedStyle(f).position, document.querySelectorAll('#panel-google .g-r').length,
                !!document.querySelector('#panel-google [data-more=all]')]; }""")
            sc = p2.evaluate(SCROLLERS)
            fh = {}
            for t, item in (("images", ".g-tile"), ("videos", ".g-v"), ("all", ".g-r")):
                p2.locator(f"#tab-google-{t}").click()
                p2.wait_for_timeout(250)
                fh[t] = [p2.evaluate("document.querySelector('.frame-phone').offsetHeight"), p2.locator(f"#panel-google {item}").count()]
            check(f"{tag} short screen ({w}x{h}): All's static preview <= 1.5 screens tall; Images its first 12, Videos its first 5",
                  fh["all"][0] <= 1.5 * h and fh["images"][1] == min(n_img, 12) and fh["videos"][1] == min(n_vid, 5), [fh, 1.5 * h])
            p2.locator("[data-more=all]").click()
            p2.wait_for_timeout(200)
            n2 = p2.locator("#panel-google .g-r").count()
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
                p2.locator(f"#tab-google-{t}").click()
                p2.wait_for_timeout(200)
                n0 = r[1] if t == "all" else p2.locator(f"#panel-google {item}").count()   # All: grown above
                if t != "all" and p2.locator(f"[data-more={t}]").count():
                    p2.locator(f"[data-more={t}]").click()
                    p2.wait_for_timeout(200)
                n1 = p2.locator(f"#panel-google {item}").count()
                if p2.locator(f"[data-less={t}]").count():
                    p2.locator(f"[data-less={t}]").click()
                    p2.wait_for_timeout(300)
                fl[t] = p2.evaluate("""([t, item]) => { const a = document.activeElement, r = a.getBoundingClientRect(), bar = document.querySelector('.rnav').getBoundingClientRect().bottom;
                    return {n: document.querySelectorAll('#panel-google ' + item).length, more: a.matches('[data-more=' + t + ']'), top: Math.round(r.top), bar: Math.round(bar), inView: r.bottom <= innerHeight}; }""", [t, item])
                fl[t].update(first=n0, grown=n1)
            check(f"{tag} short screen ({w}x{h}): Show fewer restores each tab's first look exactly; focus on More, below the pinned bar, in view",
                  all(v["n"] == v["first"] < v["grown"] and v["more"] and v["top"] >= v["bar"] and v["inView"] for v in fl.values()), fl)
            ctx.close()
        # rotation / resize: each tab not grown by More refits to the new screen; a tab grown by More keeps its items
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
        p4 = ctx.new_page()
        p4.goto(cfg.base + "scan/?r=" + slug)
        p4.wait_for_selector("#report:not([hidden])", timeout=8000)
        p4.locator("#tab-google-images").click()
        p4.locator("[data-more=images]").click()
        ni = p4.locator("#panel-google .g-tile").count()
        p4.locator("#tab-google-all").click()
        p4.wait_for_timeout(200)
        RUN = "() => { const t = document.querySelector('.ph-track'); return t.offsetHeight - t.firstElementChild.offsetHeight; }"
        rr = {"all@844": p4.evaluate(RUN)}
        p4.set_viewport_size({"width": 360, "height": 640})
        p4.wait_for_timeout(700)
        rr["all"] = p4.evaluate(RUN)
        rr["frame_pct"] = p4.evaluate("Math.round(100 * document.querySelector('.frame-phone').offsetHeight / innerHeight)")
        p4.locator("#tab-google-videos").click()
        p4.wait_for_timeout(300)
        rr["videos_n"] = p4.locator("#panel-google .g-v").count()
        p4.locator("#tab-google-images").click()
        p4.wait_for_timeout(300)
        rr["images_n"] = [ni, p4.locator("#panel-google .g-tile").count()]
        check(f"{tag} resize 390x844 → 360x640: All refits (<= 1.5 screens), frame >= 78%, Videos first 5, Images grown by More keeps its {min(n_img, 36)}",
              rr["all@844"] > 1.5 * 640 and rr["all"] <= 1.5 * 640 and rr["frame_pct"] >= 78 and rr["videos_n"] == min(n_vid, 5)
              and rr["images_n"][0] == rr["images_n"][1] == min(n_img, 36), rr)
        # a grown tab shrinks back: "Show fewer" restores its first look (12), the view lands on its More button
        grown = p4.locator("#panel-google .g-tile").count()
        has_less = p4.locator("[data-less=images]").count() == 1
        if has_less:
            p4.locator("[data-less=images]").click()
            p4.wait_for_timeout(300)
        sf = p4.evaluate("""() => { const m = document.querySelector('#panel-google [data-more=images]'), r = m && m.getBoundingClientRect();
            return {n: document.querySelectorAll('#panel-google .g-tile').length, less: !!document.querySelector('[data-less]'),
              focus: document.activeElement === m, seen: !!r && r.top >= document.querySelector('.rnav').getBoundingClientRect().bottom && r.bottom <= innerHeight}; }""")
        sf["grown"], sf["has_less"] = grown, has_less
        check(f"{tag} Show fewer: grown Images (36) goes back to its first 12, focus + view on its More button",
              has_less and grown == min(n_img, 36) and sf["n"] == min(n_img, 12) and not sf["less"] and sf["focus"] and sf["seen"], sf)
        ctx.close()
        # keyboard: Enter on "Show more images" until all are shown; focus stays in the panel (new tile / More / Show fewer)
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
        p6 = ctx.new_page()
        p6.goto(cfg.base + "scan/?r=" + slug)
        p6.wait_for_selector("#report:not([hidden])", timeout=8000)
        p6.locator("#tab-google-images").click()
        p6.wait_for_timeout(300)
        kb = []
        for _ in range(12):
            m = p6.locator("#panel-google [data-more=images]")
            if not m.count():
                break
            m.focus()
            p6.keyboard.press("Enter")
            p6.wait_for_timeout(150)
            kb.append(p6.evaluate("() => { const a = document.activeElement; return [!!a.closest('#panel-google'), a.className, document.querySelectorAll('#panel-google .g-tile').length]; }"))
        check(f"{tag} keyboard: Enter on More until every image shows, focus never leaves the panel (ends on Show fewer / a tile)",
              kb and all(k[0] for k in kb) and not p6.locator("#panel-google [data-more=images]").count(), kb)
        ctx.close()
        # landscape phone: pinned chrome (site header + section nav) <= 15% of the screen height
        ctx = browser.new_context(viewport={"width": 844, "height": 390}, device_scale_factor=2, is_mobile=True, has_touch=True)
        p5 = ctx.new_page()
        p5.goto(cfg.base + "scan/?r=" + slug)
        p5.wait_for_selector("#report:not([hidden])", timeout=8000)
        p5.evaluate("document.getElementById('sites').scrollIntoView({behavior: 'instant'}); window.scrollBy(0, 400)")
        p5.wait_for_timeout(200)
        ch = p5.evaluate("""() => { const b = e => e.getBoundingClientRect(), h = b(document.querySelector('.site-header')), n = b(document.querySelector('.rnav'));
            return {header: Math.max(0, Math.round(h.bottom)), nav: [Math.round(n.top), Math.round(n.bottom)], chrome: Math.round(Math.max(0, h.bottom, n.bottom)), vh: innerHeight}; }""")
        p5.screenshot(path=str(cfg.out / f"{vp_name}-h6-landscape.png"))
        check(f"{tag} landscape 844x390: pinned chrome (header + section nav) <= 15% of the screen", ch["nav"][0] >= -1 and ch["chrome"] <= 0.15 * ch["vh"], ch)
        ctx.close()
        wide = {}   # narrow phones: nothing sticks out sideways (summary numbers, section nav, controls, filter)
        for w in (320, 360):
            ctx = browser.new_context(viewport={"width": w, "height": 700}, device_scale_factor=2, is_mobile=True, has_touch=True)
            p3 = ctx.new_page()
            p3.goto(cfg.base + "scan/?r=" + slug)
            p3.wait_for_selector("#report:not([hidden])", timeout=8000)
            p3.fill("#lx-q", "thread/1")
            p3.wait_for_timeout(400)
            wide[w] = p3.evaluate("document.documentElement.scrollWidth")
            ctx.close()
        check(f"{tag} no sideways scroll at 320 / 360 px", all(v <= w for w, v in wide.items()), wide)

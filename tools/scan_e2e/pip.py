"""Scenario `pip` (see tools/scan_e2e.py for what it proves)."""
import base64
import json
import os
import sys
from urllib.parse import parse_qs, urlsplit

from .common import LOOP, MEASURED, break_routes, cfg, check, touch_scroll

os.environ["PW_TEST_SCREENSHOT_NO_FONTS_READY"] = "1"   # WebKit's document.fonts.ready waits for the page's parse, so a screenshot while pip.js is held would hang (still:)


PIP_J = """() => { const p = document.querySelector('.pip'), t = document.querySelector('.pip-tab'), c = document.querySelector('.hero .report-card'),
    R = e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.width, r.height].map(Math.round); };
  if (!p) return null; const f = p.querySelector('iframe'); let v = null, emb = null;
  try { const d = f.contentDocument, e = d.querySelector('.vo-video'), st = d.querySelector('.vo-stage').getBoundingClientRect();
    v = {paused: e.paused, muted: e.muted, t: e.currentTime, src: e.currentSrc, dur: e.duration}; emb = {nb: getComputedStyle(d.querySelector('.vo-nb')).display, ui: getComputedStyle(d.querySelector('.vo-ui')).display,
    sw: Math.round(st.width), sh: Math.round(st.height), fw: f.clientWidth, fh: f.clientHeight}; } catch (x) { v = String(x); }
  const pic = p.querySelector('.pip-pic').getBoundingClientRect(), ctl = [...p.querySelectorAll('button, a')].map(b => b.getBoundingClientRect()),
    g = p.querySelector('.pip-rs'), gr = g.getBoundingClientRect(), x = p.querySelector('.pip-exp'), xb = p.querySelector('.pip-x'), xr = xb && xb.getBoundingClientRect();
  return {cls: p.className, mode: p.dataset.mode, big: p.classList.contains('big'), url: location.href, opens: window.__opens || 0,
    bar: [...p.querySelectorAll('.pip-bar button')].map(b => { const r = b.getBoundingClientRect(); return [b.className, b.getAttribute('aria-label'), Math.round(r.width), Math.round(r.height)]; }),
    exp: x && [x.getAttribute('aria-label'), x.getAttribute('aria-expanded'), x.innerHTML.includes('m6 9') ? 'v' : 'expand'],
    xbox: xr ? [xr.left - pic.left, xr.top - pic.top, pic.right - xr.right, xr.width, xr.height].map(Math.round) : null,
    vvh: Math.round(window.visualViewport ? visualViewport.height : innerHeight), live: p.classList.contains('live'),
    grip: getComputedStyle(g).display === 'none' ? null : [gr.left - pic.left, gr.top - pic.top, gr.width, gr.height].map(Math.round), box: R(p), pic: R(p.querySelector('.pip-pic')), card: c ? R(c) : null,
    on: p.classList.contains('on') && !p.classList.contains('tucked'), tucked: p.classList.contains('tucked'),
    overPic: ctl.filter(b => b.right > pic.left && b.left < pic.right && b.bottom > pic.top && b.top < pic.bottom).length,
    tab: t && !t.hidden ? {box: R(t), side: t.dataset.side, chev: t.innerHTML.includes('m9 6') ? '>' : t.innerHTML.includes('m15 6') ? '<' : '?'} : null,
    v, emb, src: f.src, focus: document.activeElement && document.activeElement.className, vw: document.documentElement.clientWidth, vh: innerHeight,
    hdr: Math.max(...['.site-header', '.rnav'].map(q => document.querySelector(q)).filter(Boolean).map(e => { const r = e.getBoundingClientRect(); return r.top < 140 ? r.bottom : 0; })),
    store: [...Object.keys(sessionStorage), ...Object.keys(localStorage)].filter(k => /pip/i.test(k))}; }"""
PIP_HIT = """([sel, inside]) => [...document.querySelectorAll(sel)].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.bottom > 0 && r.top < innerHeight && getComputedStyle(e).visibility !== 'hidden'; })
  .map(e => { const r = e.getBoundingClientRect(), pts = [[r.left + r.width / 2, r.top + r.height / 2], [r.left + 4, r.top + r.height / 2], [r.right - 4, r.top + r.height / 2]];
    return pts.every(([x, y]) => { const h = document.elementFromPoint(x, y); return h && h.closest(inside || sel) === e.closest(inside || sel); }); })"""
PIP_NOT = """(sel) => [...document.querySelectorAll(sel)].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.bottom > 0 && r.top < innerHeight && getComputedStyle(e).visibility !== 'hidden'; })
  .map(e => { const r = e.getBoundingClientRect(), H = window.visualViewport ? visualViewport.height : innerHeight, ys = [r.top + 2, r.top + r.height / 2, r.bottom - 2].filter(y => y >= 0 && y < H),
    xs = [r.left + 4, r.left + r.width / 2, r.right - 4];
    return ys.every(y => xs.every(x => { const h = document.elementFromPoint(x, y); return !h || !h.closest('.pip, .pip-tab'); })); })"""


# inside the player's iframe: pause, seek to t (Range, as Pages serves it), then the <video> source / duration, a 64x36
# frame grab (luminance mean / SD, colourfulness: Hasler-Suesstrunk) and the overlay state (cards / captions) at t
PIP_TAKE = """async (t) => { const v = document.querySelector('video'); v.pause();
  if (Math.abs(v.currentTime - t) > 0.05) await new Promise(r => { v.addEventListener('seeked', r, {once: true}); v.currentTime = t; setTimeout(r, 8000); });
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  const c = document.createElement('canvas'); c.width = 64; c.height = 36; const x = c.getContext('2d'); x.drawImage(v, 0, 0, 64, 36);
  const d = x.getImageData(0, 0, 64, 36).data, rg = [], yb = [], L = [];
  for (let i = 0; i < d.length; i += 4) { rg.push(d[i] - d[i + 1]); yb.push((d[i] + d[i + 1]) / 2 - d[i + 2]); L.push(.299 * d[i] + .587 * d[i + 1] + .114 * d[i + 2]); }
  const m = a => a.reduce((s, y) => s + y, 0) / a.length, sd = a => { const k = m(a); return Math.sqrt(m(a.map(y => (y - k) ** 2))); };
  const g = document.querySelector('[data-prefab=google]'), cap = document.querySelector('.vo-capt'), stg = document.querySelector('.vo-stage');
  const gr = g.getBoundingClientRect(), sr = stg.getBoundingClientRect();
  const first = [...v.querySelectorAll('source')].find(e => v.canPlayType(e.type));
  return {src: v.currentSrc.split('/').pop(), first: first && first.getAttribute('src'), dur: v.duration, t: v.currentTime,
    lum: m(L), lumsd: sd(L), colorful: Math.hypot(sd(rg), sd(yb)) + .3 * Math.hypot(m(rg), m(yb)), sw: stg.clientWidth,
    card: !g.hasAttribute('data-off'), cardIn: gr.left >= sr.left + sr.width * .45 && gr.right <= sr.right + 1 && gr.top >= sr.top - 1 && gr.bottom <= sr.bottom + 1,
    capOn: !cap.hasAttribute('data-off'), capShown: getComputedStyle(cap).display !== 'none', capText: cap.textContent.trim().toLowerCase()}; }"""

# the 360p mini + the 720p layer, read inside the iframe (or /video/ itself); every 20 ms from HD_WATCH: [now, master t, paused, layer t, shown]
F360, F720 = ("jack-360.webm", "jack-360.mp4"), ("jack.webm", "jack.mp4")
HD_IOS = """() => { const P = HTMLMediaElement.prototype, play = P.play, pause = P.pause; window.__ios = 0;
  P.play = function () { const r = play.call(this); if (this.classList.contains('pip-hd')) { window.__ios++; pause.call(document.querySelector('.vo-video')); } return r; }; }"""
HD_J = """() => { const v = document.querySelector('.vo-video'), h = document.querySelector('.pip-hd'), b = e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.width, r.height].map(Math.round); }, z = q => +getComputedStyle(document.querySelector(q)).zIndex, pg = getComputedStyle(document.querySelector('.vo-pg .vo-hd'));
  return {n: document.querySelectorAll('video').length, src: v.currentSrc.split('/').pop(), t: v.currentTime, p: v.paused, e: v.ended, mu: v.muted, w: v.videoWidth, rect: b(v), stage: b(document.querySelector('.vo-stage')), capt: z('.vo-capt'), over: z('.vo-over'), pghd: [+pg.opacity, pg.height],
    hd: h && {src: h.currentSrc.split('/').pop(), t: h.currentTime, p: h.paused, mu: h.muted, w: h.videoWidth, on: h.classList.contains('on'), rect: b(h), op: +getComputedStyle(h).opacity, z: +getComputedStyle(h).zIndex}}; }"""
HD_WATCH = """() => { const v = document.querySelector('.vo-video'), X = window.__hdw = []; setInterval(() => { const h = document.querySelector('.pip-hd'); X.push([performance.now(), v.currentTime, v.paused, h ? h.currentTime : null, !!(h && h.classList.contains('on'))]); }, 20); }"""

# the first-paint still: when it entered the page (a mutation with neither it nor the box = a gap), LCP elements
STILL_INIT = """window.__st = {gap: false, lcp: []}; new MutationObserver(() => { const s = document.querySelector('.pip-still');
    if (s && window.__st.at == null) window.__st.at = performance.now();
    if (window.__st.at != null && !s && !document.querySelector('.pip.on') && document.readyState !== 'complete') window.__st.gap = true; }).observe(document, {childList: true, subtree: true});
  try { new PerformanceObserver(l => l.getEntries().forEach(e => window.__st.lcp.push(e.element ? e.element.className || e.element.tagName : e.url))).observe({type: 'largest-contentful-paint', buffered: true}); } catch (e) {}
  """
STILL_J = """() => { const e = document.querySelector('.pip-still'); if (!e) return null; const r = e.getBoundingClientRect(), c = getComputedStyle(e), f = performance.getEntriesByName('first-contentful-paint')[0];
  return {box: [r.left, r.top, r.width, r.height], shown: c.display !== 'none' && c.visibility === 'visible' && r.width > 0, at: window.__st.at, fcp: f && f.startTime, vw: document.documentElement.clientWidth,
    hdr: document.querySelector('.site-header').getBoundingClientRect().bottom}; }"""
# a PNG of the spot vs the still's own image, both at 64 x 36: mean absolute difference (0-255), luminance SD
STILL_PX = """async (png) => { const load = u => new Promise((ok, no) => { const i = new Image(); i.onload = () => ok(i); i.onerror = () => no(new Error('image')); i.src = u; });
  const px = i => { const c = document.createElement('canvas'); c.width = 64; c.height = 36; const x = c.getContext('2d'); x.drawImage(i, 0, 0, 64, 36); return x.getImageData(0, 0, 64, 36).data; };
  const a = px(await load('data:image/png;base64,' + png)), b = px(await load(document.querySelector('.pip-still').style.backgroundImage.slice(5, -2)));
  let d = 0; const L = []; for (let i = 0; i < a.length; i += 4) { d += Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2]); L.push(.299 * a[i] + .587 * a[i + 1] + .114 * a[i + 2]); }
  const m = L.reduce((s, y) => s + y, 0) / L.length;
  return {diff: +(d / (L.length * 3)).toFixed(1), lum: +m.toFixed(1), sd: +Math.sqrt(L.reduce((s, y) => s + (y - m) ** 2, 0) / L.length).toFixed(1)}; }"""


def pip_flow(pw, chromium, vp_name, vp, engine="chromium"):
    """js/pip.js: the mini player of site/video/ (landing: docked on the hero card, then floating; scan report with ?r=: floating)."""
    tag = f"{vp_name}{'-webkit' if engine == 'webkit' else ''} pip:"
    net = {"outside": [], "errors": [], "video": [], "pages": []}
    phone = vp_name == "phone"
    browser = pw.webkit.launch() if engine == "webkit" else chromium
    M = 12 if phone else 24

    def new_ctx(motion="no-preference", scheme="light", init=""):
        opts = dict(pw.devices["iPhone 13"]) if engine == "webkit" else dict(viewport=vp, device_scale_factor=2 if phone else 1, is_mobile=phone, has_touch=phone)
        ctx = browser.new_context(**opts, reduced_motion=motion, color_scheme=scheme)
        if init:
            ctx.add_init_script(init)
        ctx.add_init_script("""window.__opens = 0; const __o = window.open; window.open = function () { window.__opens++; return __o.apply(this, arguments); };
          window.__ls = []; try { new PerformanceObserver(l => l.getEntries().forEach(e => window.__ls.push([e.startTime, e.value, (e.sources || []).some(s => { const n = s.node && (s.node.nodeType === 1 ? s.node : s.node.parentElement); return !!(n && n.closest('.pip, .pip-tab')); })]))).observe({type: 'layout-shift', buffered: true}); } catch (e) {}
          new MutationObserver(() => { if (!window.__pipAt && document.querySelector('.pip iframe')) window.__pipAt = performance.now(); }).observe(document, {childList: true, subtree: true});
          if (window.top === window) { window.__pt = {}; const tick = () => { const p = document.querySelector('.pip'), T = window.__pt;   // when the box + poster / the first frame show
            if (p) { const r = p.getBoundingClientRect(), c = getComputedStyle(p), f = p.querySelector('iframe'), H = window.visualViewport ? visualViewport.height : innerHeight;
              const on = c.visibility === 'visible' && +c.opacity > .5 && r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= H && r.width > 0;
              let rs = -1; try { rs = f.contentDocument.querySelector('video').readyState; } catch (e) {}
              if (on && T.box == null) T.box = performance.now();
              if (on && T.poster == null && getComputedStyle(p.querySelector('.pip-pic')).backgroundImage.startsWith('url(')   // painted (a blob of the fetched poster)
                  && performance.getEntriesByType('resource').some(e => e.name.includes('jack-poster') && e.responseEnd > 0)) T.poster = performance.now();
              if (on && T.frame == null && rs >= 2 && +getComputedStyle(f).opacity > .5) T.frame = performance.now(); }
            if (window.__pt.frame == null) setTimeout(tick, 25); }; tick();
            const R = e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.width, r.height].map(Math.round); };   // follow: every frame while window.__rs is an array
            const f = () => { if (window.__rs) { const p = document.querySelector('.pip'), t = document.querySelector('.pip-tab');
              window.__rs.push([Math.round(scrollY), p ? R(p) : null, t && !t.hidden ? R(t) : null, p ? p.dataset.mode : '', Math.round(window.visualViewport ? visualViewport.height : innerHeight)]); }
              requestAnimationFrame(f); }; requestAnimationFrame(f); }""")

        def route(r, _req):
            if urlsplit(r.request.url).hostname in LOOP or r.request.url.startswith(("data:", "blob:")):   # WebKit routes those too
                if "/video/" in r.request.url:
                    net["video"].append(r.request.url)
                r.continue_()
            else:
                net["outside"].append(r.request.url)
                r.abort()
        ctx.route("**/*", route)
        break_routes(ctx)   # --break-tuck: tuck() emptied; --break-dock: no dock anchor (common.BREAKS)
        ctx.on("page", lambda pg: (pg.on("pageerror", lambda e: net["errors"].append(str(e))),
                                   pg.on("console", lambda m: m.type == "error" and "/api/thumb-sheet/" not in (m.location or {}).get("url", "") and net["errors"].append(   # no sheet: per-thumb, sheet.py checks it
                                       f"{m.text} @ {(m.location or {}).get('url', '')} on {pg.url}"))))   # which resource / page
        pg = ctx.new_page()
        ctx.on("page", lambda p: net["pages"].append(p.url))   # any page after this one (window.open / target=_blank) = a new tab
        return ctx, pg, (ctx.new_cdp_session(pg) if engine == "chromium" and phone else None)

    def st(pg):
        return pg.evaluate(PIP_J)

    def ready(pg, url, wake=True, card=False):
        pg.goto(cfg.base + url, wait_until="load")
        if wake:
            pg.keyboard.press("Shift")   # an interaction mounts it at once (else: idle)
        if card:   # the docked player loads once it is near the screen: bring the card's bottom (its dock spot) into view
            if "r=" in url:
                pg.wait_for_selector(".hero .report-card.is-live", timeout=10000)
            pg.wait_for_timeout(800)
            pg.evaluate("(() => { const r = document.querySelector('.hero .report-card').getBoundingClientRect(); scrollTo(0, Math.max(0, scrollY + r.bottom - innerHeight * 0.6)); })()")
        pg.wait_for_function("() => { const p = document.querySelector('.pip'); return p && p.classList.contains('on'); }", timeout=12000)
        pg.wait_for_timeout(700)
        return st(pg)

    def tap(pg, x, y):
        if phone:
            pg.touchscreen.tap(x, y)
        else:
            pg.mouse.click(x, y)
        pg.wait_for_timeout(450)

    def drag(pg, cdp, pts, step=16, hold=0, mid=None):   # real touch via CDP (Chromium phone), else the mouse (WebKit: pointerType mouse, declared)
        if cdp:
            cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": pts[0][0], "y": pts[0][1]}]})
            for x, y in pts[1:]:
                pg.wait_for_timeout(step)
                cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y}]})
            pg.wait_for_timeout(hold)
            m = mid() if mid else None   # mid-gesture sample, finger still down
            cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        else:
            pg.mouse.move(*pts[0]); pg.mouse.down()
            for x, y in pts[1:]:
                pg.wait_for_timeout(step)
                pg.mouse.move(x, y)
            pg.wait_for_timeout(hold)
            m = mid() if mid else None
            pg.mouse.up()
        pg.wait_for_timeout(600)
        return m

    def pic_c(s):
        b = s["pic"]
        return b[0] + b[2] / 2, b[1] + b[3] / 2

    def drop(pg, cdp, s, x1, y1):   # slow drag of the picture's centre to (x1, y1) + hold: no fling
        x0, y0 = pic_c(s)
        drag(pg, cdp, [(x0 + (x1 - x0) * i / 12, y0 + (y1 - y0) * i / 12) for i in range(13)], 30, 200)
        s = st(pg)
        for _ in range(12):   # Linux WebKit can still be gliding into its spot 600 ms after the drop (measured)
            pg.wait_for_timeout(150)
            s, s0 = st(pg), s
            if s["box"] == s0["box"]:
                break
        return s

    def fling(pg, cdp, s, dx):
        x0, y0 = pic_c(s)
        drag(pg, cdp, [(x0 + dx * i / 6, y0) for i in range(7)], 0, 0)   # no wait: pip.js wants > 0.87 px/ms here; 25 px / (10 ms + a Linux round trip) is on that line (measured: tucked 3 of 8)
        return st(pg)

    def grip(pg, cdp, s, dx, dy):
        g = pg.locator(".pip-rs").bounding_box()
        x0, y0 = g["x"] + g["width"] / 2, g["y"] + g["height"] / 2
        drag(pg, cdp, [(x0 + dx * i / 10, y0 + dy * i / 10) for i in range(11)], 20, 150)
        return st(pg)

    def ratio_ok(s):
        return abs(s["pic"][2] * 9 / 16 - s["pic"][3]) <= 1.5

    def clear(pg):   # header / report nav / Scan now / CTA bar / launcher still get the click with the player up
        hdr = all(pg.evaluate(PIP_HIT, [".site-header a, .site-header button", ""]))
        nav = all(pg.evaluate(PIP_HIT, [".rnav a, .rnav button", ""]))
        scan = all(pg.evaluate(PIP_HIT, ["#scan button[type=submit]", ""]))
        bars = all(pg.evaluate(PIP_HIT, [".mobile-cta.show, .askai-launcher:not([hidden])", ""]))
        return hdr and nav and scan and bars, {"hdr": hdr, "nav": nav, "scan": scan, "bars": bars}

    def shot(pg, name):
        pg.screenshot(path=str(cfg.out / f"{tag.split()[0]}-pip-{name}.png"))

    FW = 320 if phone else 640   # default floating width: min(FW, 45vw) (computer: 2x, Jack 2026-11-06)

    def float_default(s):   # top-right at min(FW, 45vw), in the top half
        return s["mode"] == "float" and abs(s["box"][2] - min(FW, 0.45 * s["vw"])) <= 1 and s["box"][0] + s["box"][2] == s["vw"] - M and s["hdr"] <= s["box"][1] < s["vh"] / 2

    def top_right(s):   # right under the header / nav, at the right edge
        return s["mode"] == "float" and s["box"][0] + s["box"][2] == s["vw"] - M and 0 <= s["box"][1] - s["hdr"] <= 8 + 1 + (0 if phone else 16)

    def on_screen(s):   # every px of the player inside the visual viewport, under the header
        b = s["box"]
        return s["on"] and b[0] >= 0 and b[0] + b[2] <= s["vw"] and b[1] >= s["hdr"] and b[1] + b[3] <= s["vvh"]

    def x_ok(s):   # the close X: on the picture's top-right corner, >= 40 x 40
        return bool(s["xbox"]) and s["xbox"][1] == 0 and s["xbox"][2] == 0 and s["xbox"][3] >= 40 and s["xbox"][4] >= 40

    def form_clear(pg):   # elementFromPoint over the on-screen part of the scan inputs, Scan now and the "Scanned @… · Your report" line ≠ the player
        r = {k: pg.evaluate(PIP_NOT, q) for k, q in (("inputs", "#scan input"), ("scan", "#scan button[type=submit]"), ("scanned", "[data-p=scanned]:not([hidden]) a, [data-p=scanned]:not([hidden]) button"))}
        return all(all(v) for v in r.values()), r

    def dock_checks(pg, s, what):
        c = s["card"]
        b = s["box"]
        ix = max(0, min(b[0] + b[2], c[0] + c[2]) - max(b[0], c[0])); iy = max(0, min(b[1] + b[3], c[1] + c[3]) - max(b[1], c[1]))
        cov = ix * iy / (c[2] * c[3])
        MEASURED[f"{tag} dock {what}"] = {"pip": b, "card": c, "coverage": round(cov, 3)}
        w0 = c[2] * 0.55; h0 = w0 * 9 / 16 + 40   # #79's docked box; now 2x, grown up-left from its bottom-right corner
        check(f"{tag} dock: {what}: docked, 2 x 55% of the card wide, bottom-right corner where #79's was (card corner + 30%)",
              s["mode"] == "dock" and abs(b[2] - round(2 * w0)) <= 1 and (abs(b[0] + b[2] - (c[0] + c[2] + 0.3 * w0)) <= 2 or b[0] + b[2] == s["vw"] - 12)
              and abs(b[1] + b[3] - (c[1] + c[3] + 0.3 * h0)) <= 2 and ratio_ok(s), [b, c])
        fok, fr = form_clear(pg)
        ok, d = clear(pg)
        check(f"{tag} dock: {what}: scan inputs / Scan now / Scanned line not under it (it may cover the card's rows), header / Ask-AI still clickable", fok and ok, [fr, d, round(cov, 3)])
        check(f"{tag} dock: {what}: start spot off the screen corner (up / left of it)", not (0 <= s["vw"] - (b[0] + b[2]) <= 24 and 0 <= s["vh"] - (b[1] + b[3]) <= 24), b)

    # still: Jack's face in a phone's first paint, from the HTML alone: js/pip.js held at the wire (or served empty), so
    # what shows is what the page paints by itself; a screenshot of the spot = the still's own image (pixels, not the DOM).
    # Released: the box on the same rect, no frame with neither, the still under the poster. Off where pip.js is off / moved.
    def still_page(url, init="", pip="hold"):
        ctx, pg, _ = new_ctx(init=STILL_INIT + init)
        held = []
        ctx.route("**/js/pip.js", lambda r, _q=None: held.append(r) if pip == "hold" else r.fulfill(body="", content_type="application/javascript"))
        pg.goto(cfg.base + url, wait_until="commit")
        pg.wait_for_function("() => performance.getEntriesByName('first-contentful-paint').length > 0", timeout=15000)
        return ctx, pg, held, pg.evaluate(STILL_J)

    for what, url in ((("landing", ""), ("report", "scan/?r=demoR3port01")) if phone else ()):
        vt = f"{tag} still: {what}:"
        ctx, pg, held, s = still_page(url)
        check(f"{vt} in the page before its first contentful paint (pip.js held), top-right under the header", bool(s) and s["shown"] and s["at"] is not None and s["at"] <= s["fcp"]
              and abs(s["box"][0] + s["box"][2] + M - s["vw"]) <= 1 and abs(s["box"][1] - s["hdr"] - 8) <= 1, s)
        px = None
        if s and s["shown"]:
            x, y, w = s["box"][:3]
            png = pg.screenshot(clip={"x": x, "y": y, "width": w, "height": w * 9 / 16})
            px = pg.evaluate(STILL_PX, base64.b64encode(png).decode())
        check(f"{vt} first paint shows his face: the spot's pixels = the still's image", bool(px) and px["diff"] < 25 and px["sd"] > 15, px)
        shot(pg, f"still-{what}-first-paint")
        for r in held:
            r.fallback()
        pg.wait_for_function("() => document.querySelector('.pip.on')", timeout=15000)
        a = st(pg)
        check(f"{vt} pip.js mounted: the box on the same rect (±1 px)", bool(s) and s["shown"] and all(abs(u - v) <= 1 for u, v in zip(a["box"], s["box"])), [a["box"], s and s["box"]])
        e = pg.evaluate("() => [window.__st.gap, !!document.querySelector('.pip-still'), getComputedStyle(document.querySelector('.pip-pic')).backgroundImage.slice(0, 10)]")
        check(f"{vt} replaced in one task: no moment with neither, the still gone, its image in the picture", not e[0] and not e[1] and (not s or not s["shown"] or e[2].startswith(('url("data:', 'url("blob:'))), e)
        pg.wait_for_function("() => /blob:.*data:/.test(getComputedStyle(document.querySelector('.pip-pic')).backgroundImage)", timeout=10000) if s and s["shown"] else None
        lcp = pg.evaluate("window.__st.lcp")
        check(f"{vt} never the LCP element", not any("pip-still" in x for x in lcp), lcp)
        pg.wait_for_function("() => document.querySelector('.pip.live')", timeout=15000)
        shot(pg, f"still-{what}-settled")
        ctx.close()
    ctx, pg, held, s = still_page("", pip="empty")
    pg.wait_for_function("() => document.readyState === 'complete'", timeout=15000)
    check(f"{tag} still: pip.js never comes: nothing left on the page after load", not pg.query_selector(".pip-still"), pg.evaluate("window.__st.at"))
    ctx.close()
    for what, url, init in (("?pip=0", "?pip=0", ""), ("report page without ?r=", "scan/", "")) + ((("computer", "", ""),) if not phone else ()):
        ctx, pg, held, s = still_page(url, init)
        check(f"{tag} still: none: {what}", s is None, s)
        if what == "computer":
            shot(pg, "still-computer-first-paint")
            for r in held:
                r.fallback()
            pg.wait_for_function("() => document.querySelector('.pip.live')", timeout=15000)
            shot(pg, "still-computer-settled")
        ctx.close()

    # vis: Jack's iPhone report (no player after a scan): landing, no interaction, dark + light; fresh / after a stored scan
    # of sophieraiin (localStorage leakscan.last → the stub's demoR3port01) / with an old "closed" flag in sessionStorage.
    # Box + poster < 1 s after DOMContentLoaded, first frame < 3 s (Chromium: CDP Fast 4G; WebKit can't be throttled:
    # unthrottled loopback, declared), fully on screen top-right under the header (wide: or docked, fully on screen),
    # never over the inputs / Scan now / "Scanned" line, X on its top-right → edge tab → back; then after a scroll.
    SCAN = "localStorage.setItem('leakscan.last', JSON.stringify({slug: 'demoR3port01', handle: 'sophieraiin', platform: 'onlyfans', ts: Date.now()}));"
    STALE = "if (!sessionStorage.getItem('__seed')) { sessionStorage.setItem('__seed', '1'); sessionStorage.setItem('leakscan.pip', JSON.stringify({p: null, w: 0, t: '', u: 0, x: 1})); }"
    FAST4G = {"offline": False, "latency": 165, "downloadThroughput": 9e6 / 8 * 0.9, "uploadThroughput": 1.5e6 / 8 * 0.9}   # the DevTools preset
    for scheme in ("dark", "light"):
        for what, init in (("fresh", ""), ("stored scan", SCAN), ("old closed flag", SCAN + STALE)):
            vt = f"{tag} vis: {scheme}, {what}:"
            ctx, pg, cdp = new_ctx(scheme=scheme, init="try { " + init + " } catch (e) {}")
            if engine == "chromium":
                n = cdp or ctx.new_cdp_session(pg)
                n.send("Network.enable"); n.send("Network.emulateNetworkConditions", FAST4G)
            pg.goto(cfg.base, wait_until="domcontentloaded")
            dcl = pg.evaluate("performance.getEntriesByType('navigation')[0].domContentLoadedEventEnd") or pg.evaluate("performance.now()")
            name = f"vis-{scheme}-{what.split()[0] if what != 'old closed flag' else 'closed'}"
            at = {}
            for t in (0.5, 1, 2, 3):
                pg.wait_for_timeout(max(0, dcl + t * 1000 - pg.evaluate("performance.now()")))
                at[t] = st(pg)
                if t in (1, 3) and (what != "old closed flag" or t == 3):
                    shot(pg, f"{name}-{t}s")
            spot = lambda s: on_screen(s) and (top_right(s) or (not phone and s["mode"] == "dock"))
            check(f"{vt} fully on screen{' top-right under the header' if phone else ''} at 0.5 / 1 / 2 s after DOMContentLoaded",
                  all(at[t] and spot(at[t]) for t in (0.5, 1, 2)), [at[t] and [at[t]["box"], at[t]["mode"]] for t in (0.5, 1, 2)])
            try:
                pg.wait_for_function("() => window.__pt && window.__pt.frame != null", timeout=8000)
            except Exception:   # noqa: BLE001 - reported by the check below
                pass
            pt = pg.evaluate("window.__pt")
            box, pst, frm = [None if pt.get(k) is None else round(pt[k] - dcl) for k in ("box", "poster", "frame")]
            cls, clsp = pg.evaluate("[window.__ls.reduce((a, e) => a + e[1], 0), window.__ls.filter(e => e[2]).reduce((a, e) => a + e[1], 0)]")
            MEASURED[f"{vt} ms after DCL"] = {"dcl": round(dcl), "box": box, "poster": pst, "first_frame": frm, "fast4g": engine == "chromium", "cls_page": cls, "cls_player": clsp}
            pg.wait_for_timeout(400); s = st(pg)
            check(f"{vt} box + poster on screen < 1 s after DOMContentLoaded (poster bytes in)", box is not None and pst is not None and max(box, pst) < 1000, [box, pst])
            hold = pg.evaluate("""() => { const n = performance.getEntriesByType('navigation')[0], rs = performance.getEntriesByType('resource');
                const p = rs.find(e => e.name.includes('jack-poster')), w = document.querySelector('.pip iframe').contentWindow;   // the iframe's navigation start
                let f = null; try { if (w.location.href !== 'about:blank') f = Math.round(w.performance.timeOrigin - performance.timeOrigin); } catch (e) {}
                return [p && p.initiatorType, f, Math.round(n.loadEventStart)]; }""")
            check(f"{vt} the player does not hold the page's load event: poster by fetch(), iframe started at / after it", hold[0] == "fetch" and hold[1] is not None and 0 < hold[2] <= hold[1], hold)   # loadEventStart 0 = not fired yet (held)
            check(f"{vt} cls: no layout shift from the player over the whole load (layout-shift sources; page total {cls:.4f})", clsp == 0, [clsp, cls])
            budget = 8000 if engine == "webkit" and sys.platform == "linux" else 3000   # Linux WebKit decodes in software on a CI runner: 631-4439 ms (measured); phone Chromium keeps 3 s here, WebKit on a Mac too
            check(f"{vt} first video frame < {budget // 1000} s after DOMContentLoaded ({'Fast 4G' if engine == 'chromium' else 'WebKit, unthrottled'})", frm is not None and frm < budget and s["live"], frm)
            ok, d = form_clear(pg)
            check(f"{vt} fully on screen, top-right under the header{'' if phone else ' (or docked, fully on screen)'}",
                  on_screen(s) and (top_right(s) or (not phone and s["mode"] == "dock")), [s["box"], s["hdr"], s["vvh"], s["mode"]])
            check(f"{vt} inputs / Scan now / Scanned line not under it (elementFromPoint)", ok, d)
            check(f"{vt} close X on the picture's top-right corner, >= 40 px", x_ok(s), s["xbox"])
            if what != "fresh":
                line = pg.evaluate("(() => { const e = document.querySelector('[data-p=scanned]'); return e && !e.hidden ? e.textContent : null; })()")
                check(f"{vt} the 'Scanned @… · Your report' line is up (the stored scan)", bool(line) and "Your report" in line, line)
            if what == "stored scan":
                b0 = s["box"]
                pg.click(".pip-x"); pg.wait_for_timeout(600); s = st(pg)
                check(f"{vt} X → hidden, the tab at the top-right corner (right edge, its top = the player's top, under the header)", s["tucked"] and bool(s["tab"])
                      and (abs(s["tab"]["box"][1] - b0[1]) <= 1 if phone else 0 <= s["tab"]["box"][1] - s["hdr"] <= 8 + 16 + 1) and s["tab"]["box"][1] >= s["hdr"]
                      and s["tab"]["box"][0] + s["tab"]["box"][2] == s["vw"], [s["tab"], b0, s["hdr"]])
                shot(pg, f"{name}-closed-tab")
                if s["tab"]:
                    b = s["tab"]["box"]; tap(pg, b[0] + b[2] / 2, b[1] + b[3] / 2); pg.wait_for_timeout(300); s = st(pg)
                check(f"{vt} tab tapped → back, fully on screen{' top-right' if phone else ''}, same box as before the X", s["on"] and not s["tab"] and on_screen(s) and (top_right(s) or not phone)
                      and all(abs(a - c) <= 1 for a, c in zip(s["box"], b0)), [s["box"], b0, s["tab"]])
                # reload (owner: "it should always be in the good spot"): X → tab → reload = a first visit's player on its home spot
                m0 = s["mode"]
                pg.click(".pip-x"); pg.wait_for_timeout(600); s = st(pg)
                check(f"{vt} reload: X again → the tab", s["tucked"] and bool(s["tab"]), s["tab"])
                pg.reload(wait_until="domcontentloaded"); pg.wait_for_timeout(1500); s = st(pg)
                check(f"{vt} reload: after X + reload the full player is back on its home spot ({'top-right under the header' if phone else 'as on the first load: docked while that spot fits, else top-right'}), first load's box + mode, no tab",
                      s["on"] and not s["tucked"] and not s["tab"] and on_screen(s) and s["mode"] == m0 and (top_right(s) if phone or m0 == "float" else m0 == "dock")
                      and all(abs(a - c) <= 1 for a, c in zip(s["box"], b0)), [s["box"], b0, s["mode"], m0, s["tab"]])
                check(f"{vt} reload: nothing about the player in sessionStorage / localStorage", s["store"] == [], s["store"])
                shot(pg, f"{name}-reload-home")
                b0 = s["box"]
                shot(pg, f"{name}-back")
                pg.evaluate("(() => { const f = document.querySelector('#scan'); scrollTo(0, f.getBoundingClientRect().top + scrollY - 70); })()")
                pg.wait_for_timeout(900); s = st(pg)
                check(f"{vt} scrolled to the scan form: {'same spot (±1 px), ' if phone else ''}fully on screen", on_screen(s) and (not phone or all(abs(a - c) <= 1 for a, c in zip(s["box"], b0))), [s["box"], b0])
                shot(pg, f"{name}-scroll-form")
                pg.evaluate("scrollTo(0, document.querySelector('#why').offsetTop)"); pg.wait_for_timeout(900); s = st(pg)
                check(f"{vt} scrolled down the page: floating top-right, fully on screen", on_screen(s) and top_right(s), [s["box"], s["hdr"]])
                shot(pg, f"{name}-scrolled")
            ctx.close()

    # follow (Jack: "when I scroll up and down it didn't follow, it got hidden"): landing after a stored scan, dark. Every
    # animation frame (rAF sampler) while scrolling 3 screens down and back, slowly and with fast flicks: phone = the same
    # rect (±1 px) at every scroll position; desktop = fully on screen in every frame, the same rect whenever floating.
    # Then a URL-bar collapse / expand (viewport height -94 px and back: window + visualViewport resize), a drop mid-screen,
    # and X → tab at the top-right corner, scrolled, tap → back to the prior spot. Scrolling: Chromium phone = real touch
    # gestures via CDP (flicks with momentum); desktop = the wheel; WebKit = script scrollBy per frame (bypass, declared:
    # Playwright's mobile WebKit has no wheel / touch scroll).
    ft = f"{tag} follow:"

    def scroll(pg, cdp, dy, fast):
        if cdp:
            touch_scroll(pg, cdp, 60, 560, dy=-dy, speed=6000 if fast else 900, fling=fast)
        elif engine == "webkit":
            pg.evaluate("""async ([dy, n]) => { for (let i = 0; i < n; i++) { scrollBy({top: dy / n, behavior: 'instant'}); await new Promise(r => requestAnimationFrame(r)); } }""",
                        [dy, 3 if fast else max(1, int(abs(dy)) // 30)])
        else:
            pg.mouse.move(60, 600)   # the page gutter, as the touch path (x 60): over the demo site's iframe a wheel scrolls the demo, not the page
            n = 3 if fast else max(1, int(abs(dy)) // 60)
            for _ in range(n):
                pg.mouse.wheel(0, dy / n); pg.wait_for_timeout(8 if fast else 40)
        pg.wait_for_timeout(900 if fast else 350)

    def rec(pg):
        return pg.evaluate("(() => { const a = window.__rs || []; window.__rs = []; return a; })()")

    def trip(pg, cdp, H, fast):   # 3 screens down and back to the top
        if fast:
            for _ in range(3):
                scroll(pg, cdp, H * 1.2, True)
            for _ in range(12):   # dispatched flicks (Linux, touch_scroll) carry further than CDP's gesture: until the top
                scroll(pg, cdp, -H * 1.2, True)
                if pg.evaluate("scrollY") <= 2:
                    break
        else:
            for _ in range(3):
                scroll(pg, cdp, H, False)
            scroll(pg, cdp, -H * 3.2, False)

    def same(rs, k, ref):   # every sampled rect (index k) within 1 px of ref
        bad = [r for r in rs if not r[k] or any(abs(a - b) > 1 for a, b in zip(r[k], ref))]
        return not bad, bad[:3]

    def inside(rs):
        return [r for r in rs if not r[1] or r[1][0] < 0 or r[1][1] < 0 or r[1][0] + r[1][2] > vpw or r[1][1] + r[1][3] > r[4]][:3]

    ctx, pg, cdp = new_ctx(scheme="dark", init="try { " + SCAN + " } catch (e) {}")
    pg.goto(cfg.base, wait_until="domcontentloaded")
    pg.wait_for_function("() => { const p = document.querySelector('.pip'); return p && p.classList.contains('on'); }", timeout=12000)
    pg.wait_for_timeout(1500)
    s0 = st(pg); H, vpw, home = s0["vh"], s0["vw"], s0["box"]
    pg.evaluate("window.__rs = []")
    shot(pg, "strip-0-top")
    for i in range(1, 4):
        scroll(pg, cdp, H, False); shot(pg, f"strip-{i}-screens")
    scroll(pg, cdp, -H * 3.2, False); shot(pg, "strip-4-back-top")
    slow = rec(pg)
    trip(pg, cdp, H, True)
    fast = rec(pg)
    for what, rs in (("slow", slow), ("fast flicks", fast)):
        far = max([r[0] for r in rs] or [0])
        MEASURED[f"{ft} {what}"] = {"frames": len(rs), "max_scrollY": far, "home": home, "rects": sorted({tuple(r[1]) for r in rs if r[1]})[:6]}
        check(f"{ft} {what}: reached 3 screens down and back to the top ({len(rs)} frames sampled)", far >= 2.95 * H and rs and rs[-1][0] <= 2, [far, 3 * H, rs[-1][0] if rs else None])
        if phone:
            ok, bad = same(rs, 1, home)
            check(f"{ft} {what}: phone: the same rect (±1 px) in every frame at every scroll position, top-right under the header", ok and top_right(s0), [home, bad])
        else:
            fl = [r for r in rs if r[3] == "float"]
            ok, bad = same(fl, 1, fl[0][1]) if fl else (False, "never floating")
            check(f"{ft} {what}: desktop: fully on screen in every frame, the same rect (±1 px) whenever floating", not inside(rs) and ok, [inside(rs), bad])
    if phone:   # URL-bar collapse / expand: the viewport height only (window + visualViewport resize), at the top and 2 screens down
        vs = pg.viewport_size
        for y in (0, 2):
            pg.evaluate(f"scrollTo({{top: {y} * innerHeight, behavior: 'instant'}})"); pg.wait_for_timeout(400)
            rec(pg)
            for h in (vs["height"] - 94, vs["height"], vs["height"] - 94, vs["height"]):
                pg.set_viewport_size({"width": vs["width"], "height": h}); pg.wait_for_timeout(450)
            rs = rec(pg)
            ok, bad = same(rs, 1, home)
            check(f"{ft} URL bar collapse / expand ({vs['height']} → {vs['height'] - 94} → {vs['height']}, x2) at {y} screens: no jump (±1 px), inside the viewport",
                  ok and not inside(rs) and len({r[4] for r in rs}) > 1, [home, bad, sorted({r[4] for r in rs})])
        pg.evaluate("scrollTo({top: 0, behavior: 'instant'})"); pg.wait_for_timeout(400)
    # X → the tab at the top-right corner, scrolled, tap → back
    s0 = st(pg); b0, m0 = s0["box"], s0["mode"]
    pg.click(".pip-x"); pg.wait_for_timeout(600); s = st(pg); shot(pg, "strip-5-after-x")
    tb = s["tab"]["box"] if s["tab"] else None
    check(f"{ft} X → tab at the top-right corner (right edge, under the header, at the home spot's top)",
          bool(tb) and tb[0] + tb[2] == vpw and tb[1] >= s["hdr"] and (abs(tb[1] - home[1]) <= 1 if phone else tb[1] - s["hdr"] <= 8 + 16 + 1), [tb, home, s["hdr"]])
    rec(pg); trip(pg, cdp, H, False); trip(pg, cdp, H, True); rs = rec(pg)
    ok, bad = same(rs, 2, tb or [0, 0, 0, 0])
    check(f"{ft} tab: the same rect (±1 px) in every frame, slow + flicks, 3 screens down and back", bool(tb) and ok and len(rs) > 10, [tb, bad, len(rs)])
    pg.evaluate("scrollTo({top: 2 * innerHeight, behavior: 'instant'})"); pg.wait_for_timeout(400)   # tapped scrolled down (WebKit sent no click there)
    if tb:
        tap(pg, tb[0] + tb[2] / 2, tb[1] + tb[3] / 2); pg.wait_for_timeout(300)
    s = st(pg); shot(pg, "strip-6-tab-tapped")
    if m0 == "dock":   # docked on the hero card (it fits the screen at the top here): 2 screens down the dock is off screen, so it floats; at the top it docks again
        check(f"{ft} tab tapped 2 screens down (was docked) → back, floating fully on screen", s["on"] and not s["tab"] and s["mode"] != "dock"
              and s["box"][0] >= 0 and s["box"][1] >= 0 and s["box"][0] + s["box"][2] <= vpw and s["box"][1] + s["box"][3] <= H, [s["box"], s["mode"]])
    pg.evaluate("scrollTo({top: 0, behavior: 'instant'})"); pg.wait_for_timeout(400)
    s = st(pg) if m0 == "dock" else s
    check(f"{ft} tab tapped 2 screens down → back at the prior spot (±1 px{'; docked: back at the top' if m0 == 'dock' else ''})", s["on"] and not s["tab"] and all(abs(a - c) <= 1 for a, c in zip(s["box"], b0)), [s["box"], b0, m0])
    # dropped mid-screen: stays there while scrolling (and through the URL bar), X / tab → back there
    s = drop(pg, cdp, s, vpw / 2, H / 2); mid = s["box"]
    rec(pg); trip(pg, cdp, H, False); trip(pg, cdp, H, True)
    if phone:
        vs = pg.viewport_size
        for h in (vs["height"] - 94, vs["height"]):
            pg.set_viewport_size({"width": vs["width"], "height": h}); pg.wait_for_timeout(450)
    rs = rec(pg)
    ok, bad = same(rs, 1, mid)
    check(f"{ft} dropped mid-screen, then scrolled (slow + flicks{', URL bar' if phone else ''}): the same rect (±1 px) in every frame", ok and len(rs) > 10, [mid, bad])
    pg.click(".pip-x"); pg.wait_for_timeout(600); s = st(pg)
    tb = s["tab"]["box"] if s["tab"] else None
    rec(pg); trip(pg, cdp, H, True); rs = rec(pg)
    ok, bad = same(rs, 2, tb or [0, 0, 0, 0])
    check(f"{ft} dropped, X → tab at the top-right corner, flicks: the same tab rect", bool(tb) and tb[0] + tb[2] == vpw and tb[1] - s["hdr"] <= 8 + 16 + 1 and ok, [tb, bad])
    if tb:
        tap(pg, tb[0] + tb[2] / 2, tb[1] + tb[3] / 2); pg.wait_for_timeout(300)
    s = st(pg)
    check(f"{ft} dropped, X, tab tapped → back mid-screen where it was dropped (±1 px)", s["on"] and all(abs(a - c) <= 1 for a, c in zip(s["box"], mid)), [s["box"], mid])
    ctx.close()

    # flags: landing ?pip=0 and scan/ without ?r= = no player, no /video/ request
    net["video"].clear()
    ctx, pg, cdp = new_ctx()
    pg.goto(cfg.base + "?pip=0", wait_until="load"); pg.keyboard.press("Shift"); pg.evaluate("scrollBy(0, 400)"); pg.wait_for_timeout(4500)
    pg.goto(cfg.base + "scan/", wait_until="load"); pg.keyboard.press("Shift"); pg.wait_for_timeout(4500)
    check(f"{tag} flag: landing ?pip=0 and scan/ without ?r= show no player, load no /video/", pg.locator(".pip").count() == 0 and not net["video"], net["video"])

    # report page: floating, default on with ?r= (idle mount, no interaction)
    s = ready(pg, "scan/?r=demoR3port01", wake=False)
    lz = pg.evaluate("() => [window.__pipAt, performance.getEntriesByType('navigation')[0].loadEventEnd]")
    check(f"{tag} vis: no lazy wait: player + iframe created before the page's load event", lz[0] and lz[0] <= lz[1], lz)   # <=: WebKit's clock is whole ms here, ties seen
    check(f"{tag} appear: top-right, {'45% of the screen' if phone else '640 px'} wide, 16:9 picture", float_default(s) and ratio_ok(s), [s["box"], s["pic"]])
    check(f"{tag} bar: on the picture only the close X (top-right, >= 40 px) and the 28 px resize corner (top-left), 40 px bar", s["overPic"] == 1 and x_ok(s)
          and s["box"][3] - s["pic"][3] == 40 and s["grip"] == [0, 0, 28, 28], [s["overPic"], s["xbox"], s["box"], s["pic"], s["grip"]])
    check(f"{tag} bar: exactly play / sound / expand, each a >= 40x40 px button, no link",
          [b[0] for b in s["bar"]] == ["pip-pp", "pip-snd", "pip-exp"] and all(b[2] >= 40 and b[3] >= 40 for b in s["bar"])
          and pg.locator(".pip a").count() == 0 and s["exp"] == ["Expand video", "false", "expand"], [s["bar"], s["exp"]])
    t0 = s["v"]["t"] if isinstance(s["v"], dict) else -1
    pg.wait_for_timeout(900); s = st(pg)
    check(f"{tag} appear: starts muted and playing", isinstance(s["v"], dict) and s["v"]["muted"] and not s["v"]["paused"] and s["v"]["t"] > t0 and "muted" in s["cls"], s["v"])
    u = urlsplit(s["src"])
    check(f"{tag} appear: same-origin iframe of /video/?r=<slug>", f"{u.scheme}://{u.netloc}/" == cfg.base and u.path == "/video/" and parse_qs(u.query).get("r") == ["demoR3port01"], s["src"])
    e = s["emb"] or {}
    check(f"{tag} embed: no name bar / player UI, the stage fills the picture", e.get("nb") == "none" and e.get("ui") == "none" and abs(e.get("sw", 0) - e.get("fw", -9)) <= 1 and abs(e.get("sh", 0) - e.get("fh", -9)) <= 1, e)
    ok, d = clear(pg)
    check(f"{tag} clear: header + report nav clickable with the player up", ok, d)
    shot(pg, "1-report-appear")
    tap(pg, *pic_c(s)); s = st(pg)
    check(f"{tag} unmute: a tap on the picture expands it with the sound on, playing", s["big"] and isinstance(s["v"], dict) and not s["v"]["muted"] and not s["v"]["paused"] and "muted" not in s["cls"], s["v"])
    pg.click(".pip-exp"); pg.wait_for_timeout(600); s = st(pg)
    check(f"{tag} unmute: minimized back to the mini player, sound still on", not s["big"] and float_default(s) and isinstance(s["v"], dict) and not s["v"]["muted"], [s["box"], s["v"]])
    mx, my = s["vw"] / 2, s["vh"] / 2
    s = drop(pg, cdp, s, mx, my)
    cx, cy = pic_c(s)
    check(f"{tag} drop: released mid-screen it stays there (no snap)", s["on"] and abs(cx - mx) <= 3 and abs(cy - my) <= 3, [s["box"], round(mx), round(my)])
    shot(pg, "2-dropped-middle")
    s = drop(pg, cdp, s, s["vw"] * 0.3, 5)
    check(f"{tag} drop: dragged up into the header it stays under it, fully on-screen", s["on"] and s["box"][1] >= s["hdr"] and s["box"][0] >= 8, [s["box"], s["hdr"]])
    ok, d = clear(pg)
    check(f"{tag} clear: header + report nav clickable with the player at the top", ok, d)
    spot = s["box"]
    s = fling(pg, cdp, s, -150)
    check(f"{tag} tuck: fling left → off-screen, '>' tab at the left edge, paused",
          s["tucked"] and s["box"][0] + s["box"][2] <= 0 and bool(s["tab"]) and s["tab"]["side"] == "l" and s["tab"]["chev"] == ">" and s["tab"]["box"][0] == 0
          and isinstance(s["v"], dict) and s["v"]["paused"], [s["box"], s["tab"]])
    shot(pg, "3-tucked-left")
    if s["tab"]:
        b = s["tab"]["box"]; tap(pg, b[0] + b[2] / 2, b[1] + b[3] / 2); s = st(pg)
    check(f"{tag} tuck: tab tapped → back where it was, playing", s["on"] and not s["tab"] and abs(s["box"][0] - spot[0]) <= 2 and abs(s["box"][1] - spot[1]) <= 2
          and isinstance(s["v"], dict) and not s["v"]["paused"], [s["box"], spot])
    shot(pg, "4-back")

    s = ready(pg, "scan/?r=demoR3port01")   # a new page: nothing kept from the last one
    check(f"{tag} reload: a new page after a drop starts on the home spot at default size (nothing kept), nothing in storage",
          s["on"] and float_default(s) and top_right(s) and s["store"] == [], [s["box"], spot, s["store"]])
    s = drop(pg, cdp, s, s["vw"] - s["pic"][2] * 0.2, s["vh"] * 0.4)   # 30% past the right edge, slowly: kept on-screen, not tucked
    check(f"{tag} drop: half past the right edge without a fling → pulled fully on-screen", s["on"] and s["box"][0] + s["box"][2] == s["vw"] - 8, s["box"])
    s = fling(pg, cdp, s, 150)
    check(f"{tag} tuck: fling right → off-screen, '<' tab at the right edge", s["tucked"] and s["box"][0] >= s["vw"] and bool(s["tab"]) and s["tab"]["side"] == "r"
          and s["tab"]["chev"] == "<" and s["tab"]["box"][0] + s["tab"]["box"][2] == s["vw"], [s["box"], s["tab"]])
    shot(pg, "5-tucked-right")
    if s["tab"]:
        b = s["tab"]["box"]; tx, ty = b[0] + b[2] / 2, b[1] + b[3] / 2
        drag(pg, cdp, [(tx - 12 * i, ty) for i in range(7)], 16, 0); s = st(pg)
    check(f"{tag} tuck: tab dragged inward → back at the right edge", s["on"] and not s["tab"] and s["box"][0] + s["box"][2] == s["vw"] - 8, s["box"])

    # resize: the grip (pointer) + pinch (Chromium phone); 16:9, 160 px .. 60% / 90% of the width, kept
    s = ready(pg, "scan/?r=demoR3port01")
    w0, r0 = s["box"][2], s["box"][0] + s["box"][2]
    s = grip(pg, cdp, s, -90, -40)
    check(f"{tag} resize: grip dragged out → bigger, 16:9 kept, bottom-right edge anchored", s["on"] and s["box"][2] >= w0 + 80 and ratio_ok(s)
          and s["box"][0] + s["box"][2] == r0, [w0, r0, s["box"], s["pic"]])
    shot(pg, "6-resized")
    s = grip(pg, cdp, s, 900, 600)
    check(f"{tag} resize: min 168 px wide", s["box"][2] == 168 and ratio_ok(s), s["box"])
    s = drop(pg, cdp, s, s["vw"] / 2, s["vh"] / 2)
    s = grip(pg, cdp, s, -1400, -1000)
    mx_w = min(s["vw"] * (0.9 if phone else 0.6), (s["vh"] - s["hdr"] - 8 - 8 - 40) * 16 / 9)
    check(f"{tag} resize: max {'90' if phone else '60'}% of the width (or the screen height)", abs(s["box"][2] - mx_w) <= 2 and ratio_ok(s) and s["box"][1] >= s["hdr"], [s["box"], round(mx_w)])
    big = s["box"][2]
    s = ready(pg, "scan/?r=demoR3port01")
    check(f"{tag} reload: resized + reload = default size again, home spot", s["on"] and abs(s["box"][2] - w0) <= 1 and top_right(s), [s["box"], w0, big])
    if cdp:   # two real touch points spreading over the picture
        s = grip(pg, cdp, s, 700, 500)   # back to the min
        s = drop(pg, cdp, s, s["vw"] / 2, s["vh"] / 2)
        w1, (cx, cy) = s["box"][2], pic_c(s)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": cx - 20, "y": cy, "id": 1}, {"x": cx + 20, "y": cy, "id": 2}]})
        for i in range(1, 9):
            pg.wait_for_timeout(20)
            cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": cx - 20 - 8 * i, "y": cy, "id": 1}, {"x": cx + 20 + 8 * i, "y": cy, "id": 2}]})
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []}); pg.wait_for_timeout(600); s = st(pg)
        check(f"{tag} resize: pinch out → bigger, 16:9", s["box"][2] > w1 + 40 and ratio_ok(s), [w1, s["box"]])

    s = ready(pg, "scan/?r=demoR3port01")
    pg.focus(".pip-snd"); pg.keyboard.press("Escape"); pg.wait_for_timeout(500); s = st(pg)
    check(f"{tag} tuck: Esc inside the player tucks it, focus on the tab", s["tucked"] and bool(s["tab"]) and s["focus"] == "pip-tab", [s["cls"], s["focus"]])
    pg.focus(".pip-tab"); pg.keyboard.press("Enter"); pg.wait_for_timeout(500); s = st(pg)
    check(f"{tag} tuck: Enter on the tab brings it back, focus inside the player", s["on"] and not s["tab"] and (s["focus"] or "").startswith("pip-"), [s["cls"], s["focus"]])
    pg.focus(".pip-snd"); pg.keyboard.press("Escape"); pg.wait_for_timeout(500)
    s = ready(pg, "scan/?r=demoR3port01")
    check(f"{tag} reload: tucked + reload = the full player on its home spot, no tab", bool(s) and s["on"] and not s["tucked"] and not s["tab"] and top_right(s), s and [s["cls"], s["box"]])
    ls = pg.evaluate("() => window.__ls.filter(e => e[0] >= (window.__pipAt || 0) && e[2]).reduce((a, e) => a + e[1], 0)")   # shifts of the player (sources)
    check(f"{tag} cls: 0 from the player after it mounts (report)", ls == 0, ls)

    s = ready(pg, "scan/?r=demoR3port01")
    pg.click(".pip-x"); pg.wait_for_timeout(500); s = st(pg)
    check(f"{tag} close: X hides it behind the right edge tab (never gone), paused", s["tucked"] and bool(s["tab"]) and s["tab"]["side"] == "r"
          and isinstance(s["v"], dict) and s["v"]["paused"], [s["cls"], s["tab"]])
    ctx.close()

    # expanded (YouTube style): tap → big under the header, the page scrolls under it, pull down → mini, fling the mini
    # down → hidden with a tab, tab → back; never a new page / tab. Fresh session: the mini player at its default spot.
    ctx, pg, cdp = new_ctx()
    s = ready(pg, "scan/?r=demoR3port01"); pg.wait_for_timeout(600)
    mini, url0 = s["box"], s["url"]
    shot(pg, "7a-mini")
    tap(pg, *pic_c(s)); pg.wait_for_timeout(300); s = st(pg)
    bw = s["vw"] if phone else min(960, round(s["vw"] * 0.7))
    big_ok = lambda s: s["big"] and s["mode"] == "big" and abs(s["box"][1] - (s["hdr"] + (0 if phone else 12))) <= 1 and abs(s["box"][2] - bw) <= 1 \
        and abs(s["box"][0] - (s["vw"] - bw) / 2) <= 1 and ratio_ok(s)
    check(f"{tag} expand: tap on the picture → expanded in place: {'full width' if phone else f'{bw} px centred'}, right under the header, sound on, playing",
          big_ok(s) and isinstance(s["v"], dict) and not s["v"]["muted"] and not s["v"]["paused"] and s["url"] == url0, [s["box"], s["hdr"], s["vw"], s["v"]])
    check(f"{tag} expand: the toggle is now a chevron-down 'Minimize video' (aria-expanded), no resize corner", s["exp"] == ["Minimize video", "true", "v"] and s["grip"] is None, [s["exp"], s["grip"]])
    shot(pg, "7b-expanded")
    y0, big0 = pg.evaluate("scrollY"), s["box"]
    sx, sy = s["vw"] / 2, min(s["vh"] - 60, big0[1] + big0[3] + 120)   # a finger / the wheel on the page below the player
    if cdp:
        touch_scroll(pg, cdp, sx, sy, dy=-500, speed=1500)
    elif engine == "webkit":   # bypass, declared: Playwright's mobile WebKit has no wheel / touch scroll; a script scroll
        pg.evaluate("scrollBy(0, 500)")
    else:
        pg.mouse.move(sx, sy); pg.mouse.wheel(0, 500)
    pg.wait_for_timeout(900); s = st(pg)
    y1 = pg.evaluate("scrollY")
    below = pg.evaluate("""() => { const r = document.querySelector('.pip').getBoundingClientRect(), h = document.elementFromPoint(innerWidth / 2, Math.min(innerHeight - 4, r.bottom + 20)),
      c = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 3);
      return [h && !h.closest('.pip') && h !== document.documentElement && h !== document.body ? (h.className || h.tagName) : null, !!(c && c.closest('.pip'))]; }""")
    check(f"{tag} expand: the page scrolls under the expanded player (no scroll lock): scrollY moved, the player stays under the header, page content right below it",
          y1 - y0 > 200 and big_ok(s) and below[0] and below[1], [y0, y1, s["box"], s["hdr"], below])
    shot(pg, "7c-expanded-scrolled")
    pg.click(".pip-exp"); pg.wait_for_timeout(600); s = st(pg)
    check(f"{tag} minimize: the chevron → back to the mini player top-right", not s["big"] and float_default(s) and s["exp"] == ["Expand video", "false", "expand"], [s["box"], s["exp"]])
    pg.click(".pip-exp"); pg.wait_for_timeout(600)
    pg.focus(".pip-exp"); pg.keyboard.press("Escape"); pg.wait_for_timeout(600); s = st(pg)
    check(f"{tag} minimize: Esc (focus inside) → mini again, focus kept on the toggle", not s["big"] and float_default(s) and s["focus"] == "pip-exp", [s["box"], s["focus"]])
    tap(pg, *pic_c(s)); pg.wait_for_timeout(300); s = st(pg)

    def pull(s, frac, steps, step, hold, sample=True):   # finger on the expanded picture, down by frac of the way to the mini spot
        x0, y0 = pic_c(s)
        dy = max(120, mini[1] - s["box"][1]) * frac
        return drag(pg, cdp, [(x0, y0 + dy * i / steps) for i in range(steps + 1)], step, hold, mid=(lambda: st(pg)) if sample else None)
    m = pull(s, 0.15, 8, 30, 200); s = st(pg)
    check(f"{tag} pull: dragged down 15% → follows the finger (lower, scaled down), released → snaps back expanded",
          m["box"][1] > big0[1] + 10 and m["box"][2] < bw - 10 and big_ok(s), [m["box"], s["box"]])
    m = pull(s, 0.5, 12, 30, 200); s = st(pg)
    check(f"{tag} pull: dragged down 50% → mini player top-right, still playing with sound",
          m["box"][2] < bw * 0.85 and not s["big"] and float_default(s) and isinstance(s["v"], dict) and not s["v"]["paused"] and not s["v"]["muted"], [m["box"], s["box"], s["v"]])
    shot(pg, "7d-pulled-mini")
    tap(pg, *pic_c(s)); pg.wait_for_timeout(300); s = st(pg)
    pull(s, 0.25, 1, 0, 0, sample=False); s = st(pg)   # one move (CDP touch moves land ~33 ms apart: 30 px in 3 = 0.37 px/ms, no flick), no mid sample   # under the 30% distance threshold: only the speed can minimize it
    check(f"{tag} pull: a quick flick down (25% of the way) → mini", not s["big"] and float_default(s), s["box"])
    if s["big"]:   # the pull broken (--break-pull): back to the mini so the checks below stay independent of it
        pg.click(".pip-exp"); pg.wait_for_timeout(600); s = st(pg)
        if isinstance(s["v"], dict) and s["v"]["paused"]:   # its taps toggled play / pause
            pg.click(".pip-pp"); pg.wait_for_timeout(400); s = st(pg)
    x0, y0 = pic_c(s)
    flung = s["box"]
    dy = (s["vh"] - y0) / 6   # flung from wherever it sits to the bottom edge
    drag(pg, cdp, [(x0, y0 + dy * i) for i in range(7)], 10, 0); s = st(pg)
    check(f"{tag} tuck: mini flung down past the bottom → hidden, '<' tab at the right edge, paused",
          s["tucked"] and s["box"][0] >= s["vw"] and bool(s["tab"]) and s["tab"]["side"] == "r" and isinstance(s["v"], dict) and s["v"]["paused"], [s["box"], s["tab"]])
    shot(pg, "7e-hidden-tab")
    if s["tab"]:
        b = s["tab"]["box"]; tap(pg, b[0] + b[2] / 2, b[1] + b[3] / 2); s = st(pg)
    check(f"{tag} tuck: tab tapped → the mini player is back where the flick started, playing", s["on"] and not s["tab"] and abs(s["box"][0] - flung[0]) <= 2
          and abs(s["box"][1] - flung[1]) <= 2 and isinstance(s["v"], dict) and not s["v"]["paused"], [s["box"], flung])
    shot(pg, "7f-back")
    tap(pg, *pic_c(s)); pg.wait_for_timeout(300)
    pg.click(".pip-x"); pg.wait_for_timeout(500); s = st(pg)
    check(f"{tag} close: X on the expanded player → hidden behind the right edge tab, not expanded", s["tucked"] and not s["big"] and bool(s["tab"]), [s["cls"], s["tab"]])
    check(f"{tag} expand: no new page / tab, no window.open, same URL throughout", not net["pages"] and s["opens"] == 0 and pg.url == url0, [net["pages"], s["opens"], pg.url])
    ctx.close()

    # landing, default on: docked on the hero card, floating once the hero is out, re-docked on the way back
    ctx, pg, cdp = new_ctx()
    s = ready(pg, "", card=phone)
    if phone:   # a phone never docks: with the card's dock spot on screen it is still top-right, clear of the form
        ok, d = form_clear(pg)
        check(f"{tag} vis: phone, hero card in view: still floating top-right, fully on screen, scan form clear", top_right(s) and on_screen(s) and ok, [s["box"], s["hdr"], d])
    else:
        dock_checks(pg, s, "before a scan (weekly report card)")
    shot(pg, "8-landing-docked")
    ok, d = clear(pg)
    check(f"{tag} landing: Scan now + header clickable with the player up", ok and d["scan"], d)
    ls = pg.evaluate("() => window.__ls.filter(e => e[0] >= (window.__pipAt || 0) && e[2]).reduce((a, e) => a + e[1], 0)")   # shifts of the player (sources)
    check(f"{tag} cls: 0 from the player after it mounts (landing, docked)", ls == 0, ls)
    docked = s["box"]
    tap(pg, *pic_c(s)); pg.wait_for_timeout(300); b = st(pg)
    check(f"{tag} landing: tap on the docked player → expanded under the header", b["big"] and abs(b["box"][1] - (b["hdr"] + (0 if phone else 12))) <= 1
          and abs(b["box"][2] - (b["vw"] if phone else min(960, round(b["vw"] * 0.7)))) <= 1, [b["box"], b["hdr"]])
    shot(pg, "8b-landing-expanded")
    pg.click(".pip-exp"); pg.wait_for_timeout(700); s = st(pg)
    check(f"{tag} landing: minimized → {'top-right' if phone else 'docked on the card'} again, same box", s["mode"] == ("float" if phone else "dock") and all(abs(a - c) <= 2 for a, c in zip(s["box"], docked)), [s["box"], docked])
    pg.evaluate("scrollTo(0, document.querySelector('#why').offsetTop)"); pg.wait_for_timeout(1300); s = st(pg)
    ov = pg.evaluate("""() => { const p = document.querySelector('.pip').getBoundingClientRect(); return [...document.querySelectorAll('.mobile-cta.show, .askai-launcher:not([hidden])')]
      .filter(e => getComputedStyle(e).visibility !== 'hidden').map(e => { const r = e.getBoundingClientRect(); return r.left < p.right && r.right > p.left && r.top < p.bottom && r.bottom > p.top; }); }""")
    ok, d = clear(pg)
    check(f"{tag} vis: cycle: hero out of view → floating top-right under the header, normal size, clear of the CTA bar / Ask-AI launcher",
          s["on"] and top_right(s) and on_screen(s) and abs(s["box"][2] - min(FW, 0.45 * s["vw"])) <= 1 and not any(ov) and ok, [s["box"], s["hdr"], ov, d])
    shot(pg, "9-landing-floating")
    pg.evaluate("scrollTo(0, 0)"); pg.wait_for_timeout(300)
    if phone:
        pg.evaluate("document.querySelector('.hero .report-card').scrollIntoView({block: 'center', behavior: 'instant'})")
    pg.wait_for_timeout(1200); s = st(pg)
    check(f"{tag} dock: scrolled back up → {'top-right again (phone)' if phone else 'docked again on the card'}", s["mode"] == ("float" if phone else "dock") and abs(s["box"][2] - docked[2]) <= 1, [s["box"], docked])
    mx, my = s["vw"] * 0.4, s["vh"] * 0.45
    s = drop(pg, cdp, s, mx, my)
    moved = s["box"]
    pg.evaluate("scrollTo(0, document.querySelector('#why').offsetTop)"); pg.wait_for_timeout(1200); s1 = st(pg)
    pg.evaluate("scrollTo(0, 0)"); pg.wait_for_timeout(1200); s2 = st(pg)
    check(f"{tag} moved: once dragged it stays where it was dropped, hero in or out (no re-dock)",
          s1["mode"] == s2["mode"] == "float" and abs(s1["box"][0] - moved[0]) <= 2 and abs(s1["box"][1] - moved[1]) <= 2 and abs(s2["box"][1] - moved[1]) <= 2, [moved, s1["box"], s2["box"]])
    ctx.close()

    # landing after a scan (the hero card is her report): same docking rule
    ctx, pg, cdp = new_ctx()
    s = ready(pg, "?r=demoR3port01", card=True)
    if phone:
        ok, d = form_clear(pg)
        check(f"{tag} vis: phone, report card in view: floating, fully on screen, scan form clear", s["mode"] == "float" and on_screen(s) and ok, [s["box"], d])
    else:
        dock_checks(pg, s, "after a scan (report card)")
    shot(pg, "10-landing-docked-report")
    ctx.close()

    # the real take (site/video/jack.webm + jack.mp4, PR #72) inside the player: source, length, picture, cues
    def take(pg, t):
        return pg.query_selector(".pip iframe").content_frame().evaluate(PIP_TAKE, t)

    for where, url, kw in (("floating (report)", "scan/?r=demoR3port01", {}), ("docked (landing)", "", {"card": True})):
        ctx, pg, cdp = new_ctx()
        ready(pg, url, **kw)
        pg.query_selector(".pip iframe").content_frame().wait_for_function("() => document.querySelector('video').readyState >= 2", timeout=15000)
        a = take(pg, 3.0)
        if where.startswith("floating"):
            check(f"{tag} take: playing source = the real take, the first <source> this engine plays (jack.webm / jack.mp4, a phone's mini jack-360.*: mini:)",
                  a["src"] in F720 + F360 and a["src"] == a["first"], [a["src"], a["first"]])
            check(f"{tag} take: duration about 56.9 s", abs(a["dur"] - 56.9) < 0.2, a["dur"])
        # placeholder (b794368~1) measured lum 51, SD 16, colourfulness 12; the real take 150+ / 55+ / 23+
        check(f"{tag} take: {where}: frame at 3 s is the real take, not the placeholder", a["lum"] > 100 and a["lumsd"] > 35 and a["colorful"] > 18,
              {k: round(a[k], 1) for k in ("t", "lum", "lumsd", "colorful")})
        b, c = take(pg, 9.0), take(pg, 11.5)
        check(f"{tag} take: {where}: google card off before its cue (9 s), on at 11.5 s inside the picture's right half (Jack's left half clear)",
              not b["card"] and c["card"] and c["cardIn"], [b["card"], c["card"], c["cardIn"]])
        shot(pg, f"{11 if where.startswith('floating') else 12}-take-{where.split()[0]}-card")
        e = take(pg, 2.95)
        shot(pg, f"{13 if where.startswith('floating') else 14}-take-{where.split()[0]}-caption")
        f = take(pg, 4.9)
        tiny = e["sw"] < 260   # #72: under 260 px wide no captions (unreadable)
        check(f"{tag} take: {where}: caption 'real' at 2.95 s, gone in the pause after 'bot.' (4.9 s); {e['sw']} px wide: "
              + ("hidden (under 260 px)" if tiny else "drawn"),
              e["capOn"] and "real" in e["capText"] and not f["capOn"] and e["capShown"] == (not tiny), [e["capOn"], e["capText"], e["capShown"], e["sw"], f["capOn"]])
        ctx.close()

    # mini: a phone's mini plays the 360p files, chosen while the page parses (no 720p request before expand); a computer's and
    # /video/ opened directly 720p only. Requests as the route saw them (bypass, declared: page.route = no HTTP cache here)
    def fr(pg):
        return pg.query_selector(".pip iframe").content_frame()

    def video_up(f):
        f.wait_for_function("() => document.querySelector('video').readyState >= 2", timeout=20000)

    def vfiles(n0):
        return sorted({urlsplit(u).path.rsplit("/", 1)[-1] for u in net["video"][n0:] if urlsplit(u).path.endswith((".webm", ".mp4"))})

    def hd_on(f, ms=20000):   # no raise: --break-pipmini has no layer at all
        try:
            f.wait_for_function("() => document.querySelector('.pip-hd.on')", timeout=ms)
            return True
        except Exception:
            return False

    def hd_watch(f):   # HD_WATCH's samples: the first with the layer shown, the lag there and all along, the master's clock vs the wall clock
        s = json.loads(f.evaluate("JSON.stringify(window.__hdw)"))
        on = next((y for y in s if y[4]), None)
        run = [(p, q) for p, q in zip(s, s[1:]) if not p[2] and not q[2]]
        return {"on": on and round(on[0] - s[0][0]), "lag0": on and round(abs(on[1] - on[3]), 3), "lagmax": max((round(abs(y[1] - y[3]), 3) for y in s if y[4]), default=None),
                "wall": round(sum(q[0] - p[0] for p, q in run) / 1000, 2), "adv": round(sum(q[1] - p[1] for p, q in run), 2)}

    def hd_ok(a):   # the 720p layer showing, in sync, the master under it still playing
        H = a["hd"] or {}
        return bool(H.get("on")) and abs(a["t"] - H.get("t", 1e9)) <= 0.25 and not H.get("p") and not a["p"]

    for what, url in (("report", "scan/?r=demoR3port01"), ("landing", ""), ("named", "?name=Orla%20Brennick")):
        ctx, pg, cdp = new_ctx()
        n0 = len(net["video"])
        s = ready(pg, url)
        f = fr(pg)
        video_up(f)
        pg.wait_for_timeout(800)
        a, got, q = f.evaluate(HD_J), vfiles(n0), parse_qs(urlsplit(s["src"]).query)
        if phone:
            check(f"{tag} mini: {what}: 360p file playing (640 px), ?mini=1, no 720p request and no HD layer before expand", a["src"] in F360 and a["w"] == 640 and q.get("mini") == ["1"] and got and all(x in F360 for x in got) and not a["hd"], [a["src"], a["w"], q, got, a["hd"]])
            if what != "report":   # the main flow below has the details
                pg.tap(".pip-exp")
                ok = hd_on(f)
                check(f"{tag} hd: {what}: expand reveals the 720p layer", ok and hd_ok(f.evaluate(HD_J)), f.evaluate(HD_J))
        else:
            check(f"{tag} mini: {what}: computer: 720p file (1280 px), no ?mini, no jack-360 request", a["src"] in F720 and a["w"] == 1280 and "mini" not in q and got and all(x in F720 for x in got), [a["src"], a["w"], q, got])
            pg.click(".pip-exp")
            pg.wait_for_timeout(1200)
            a = f.evaluate(HD_J)
            check(f"{tag} mini: {what}: computer: expand adds no second video", a["n"] == 1 and not a["hd"] and a["src"] in F720, [a["n"], a["hd"], a["src"]])
        ctx.close()
    ctx, pg, cdp = new_ctx()
    n0 = len(net["video"])
    pg.goto(cfg.base + "video/", wait_until="load")
    pg.wait_for_function("() => document.querySelector('video').readyState >= 2", timeout=20000)
    pg.wait_for_timeout(500)
    a, got = pg.evaluate(HD_J), vfiles(n0)
    check(f"{tag} mini: /video/ opened directly: 720p, no jack-360 request, no second video", a["src"] in F720 and a["w"] == 1280 and got and all(x in F720 for x in got) and a["n"] == 1, [a["src"], a["w"], got, a["n"]])
    ctx.close()

    # hd: expand = 720p at the same second over the still-playing mini; it follows the master and drops out to it, never a freeze
    if phone and engine == "webkit" and sys.platform == "linux":   # declared in .github/workflows/e2e.yml: WebKit on GStreamer is no iPhone's AVFoundation: after a forced fault the layer stays parked ahead of the master > 15 s, the guard drops it at the take's end (measured)
        print(f"SKIP {tag} hd: sync flow: Linux WebKit's media stack; phone Chromium here and WebKit on a Mac still run it", flush=True)
    elif phone:
        ctx, pg, cdp = new_ctx()
        ready(pg, "scan/?r=demoR3port01")
        f = fr(pg)
        video_up(f)
        pg.wait_for_timeout(1500)
        n0 = len(net["video"])
        f.evaluate(HD_WATCH)
        shot(pg, "hd-1-mini")
        pg.tap(".pip-exp")
        pg.wait_for_timeout(350)
        shot(pg, "hd-2-expanded-360")
        a = f.evaluate(HD_J)
        check(f"{tag} hd: expanded at once on the 360p master: sound on, playing, nothing shown over it yet", a["w"] == 640 and not a["mu"] and not a["p"] and not (a["hd"] or {}).get("on"), [a["w"], a["mu"], a["p"], a["hd"]])
        ok = hd_on(f)
        pg.wait_for_timeout(1000)
        w = hd_watch(f)
        ok = ok and hd_on(f, 8000)   # may be off right now by design: a stalled layer hides, the master plays on (back at +3420 ms after the tap, measured)
        a = f.evaluate(HD_J)
        H = a["hd"] or {}
        shot(pg, "hd-3-revealed-720")
        check(f"{tag} hd: revealed in sync: 720p (1280 px) at the master's second (first shown within 0.2 s, never more than 0.3 s off), same box as master and stage",
              ok and w["lag0"] is not None and w["lag0"] <= 0.2 and w["lagmax"] <= 0.3 and H.get("w") == 1280 and H.get("rect") == a["rect"] == a["stage"] and H.get("op") == 1, [w, H, a["rect"], a["stage"]])
        check(f"{tag} hd: the master never froze across the switch (its clock kept the wall clock's pace), sound on the master, the layer muted", w["wall"] > 1 and w["adv"] >= 0.8 * w["wall"] and not a["mu"] and H.get("mu") is True, [w, a["mu"], H.get("mu")])
        check(f"{tag} hd: layers: under the captions and cards, one extra <video>, same container as the master, the fake phone's own header untouched",
              H.get("z", 9) < min(a["capt"], a["over"]) and a["n"] == 2 and H.get("src") == a["src"].replace("-360.", ".") and a["pghd"] == [1, "64px"], [H.get("z"), a["capt"], a["over"], a["n"], H.get("src"), a["pghd"]])
        check(f"{tag} hd: the 720p file requested only after the tap", (H.get("src") or "?") in vfiles(n0), vfiles(n0))
        pg.tap(".pip-pp")
        pg.wait_for_timeout(600)
        a = f.evaluate(HD_J)
        H = a["hd"] or {}
        check(f"{tag} hd: pause button: both stay paused (the guard quiet), within 0.06 s of each other", a["p"] and H.get("p") is True and abs(a["t"] - H.get("t", 1e9)) <= 0.06, [a["p"], a["t"], H])
        pg.tap(".pip-pp")
        ok = hd_on(f, 15000)
        pg.wait_for_timeout(1000)
        a = f.evaluate(HD_J)
        check(f"{tag} hd: play again: both playing, shown, in sync", ok and hd_ok(a), a)
        tap(pg, *pic_c(st(pg)))
        pg.wait_for_timeout(600)
        a = f.evaluate(HD_J)
        H = a["hd"] or {}
        check(f"{tag} hd: a tap on the picture pauses too: both stay paused (the guard quiet), the layer kept", a["p"] and H.get("p") is True and a["n"] == 2, [a["p"], a["n"], H])
        tap(pg, *pic_c(st(pg)))
        ok = hd_on(f, 15000)
        pg.wait_for_timeout(500)
        a = f.evaluate(HD_J)
        check(f"{tag} hd: a tap again: both playing, shown, in sync", ok and hd_ok(a), a)
        pg.tap(".pip-snd")
        pg.wait_for_timeout(200)
        a = f.evaluate(HD_J)
        check(f"{tag} hd: the sound button mutes the master, the layer stays muted, picture unchanged", a["mu"] and (a["hd"] or {}).get("mu") is True and hd_ok(a), a)
        pg.tap(".pip-snd")
        f.evaluate("() => { const h = document.querySelector('.pip-hd'); if (h) h.currentTime = Math.max(0, h.currentTime - 3); }")   # bypass, declared: the fault forced from the page
        pg.wait_for_timeout(120)
        a = f.evaluate(HD_J)
        check(f"{tag} hd: fell 3 s behind (forced): hidden within 120 ms, the master plays on with sound", not (a["hd"] or {}).get("on") and not a["p"] and not a["mu"], a)
        ok = hd_on(f, 15000)
        pg.wait_for_timeout(600)
        a = f.evaluate(HD_J)
        check(f"{tag} hd: then back, in sync", ok and hd_ok(a), a)
        pg.tap(".pip-exp")
        pg.wait_for_timeout(250)
        a = f.evaluate(HD_J)
        shot(pg, "hd-4-minimized")
        check(f"{tag} hd: minimize: the layer dropped at once (no 720p element left to download), the master still playing with sound", not a["hd"] and a["n"] == 1 and not a["p"] and not a["mu"], a)
        pg.tap(".pip-exp")
        ok = hd_on(f, 15000)
        pg.wait_for_timeout(500)
        a = f.evaluate(HD_J)
        check(f"{tag} hd: re-expand: a new layer in sync at the master's second, no second one", ok and hd_ok(a) and a["n"] == 2 and (a["hd"] or {}).get("w") == 1280, a)
        f.evaluate("() => { const n = document.querySelector('.vo-nb form'), i = n.querySelector('input'); i.value = 'Orla Brennick'; n.requestSubmit(); }")   # bypass, declared: the name bar is hidden in the embed; its submit from the page
        pg.wait_for_timeout(150)
        a = f.evaluate(HD_J)
        check(f"{tag} hd: ?name= rebuilt in place (master back to the start): the old second is hidden at once", a["t"] < 2 and not (a["hd"] or {}).get("on"), a)
        ok = hd_on(f, 15000)
        pg.wait_for_timeout(500)
        a = f.evaluate(HD_J)
        check(f"{tag} hd: ?name= rebuilt: the layer back in sync, still 2 videos", ok and hd_ok(a) and a["n"] == 2, a)
        f.evaluate("() => { const v = document.querySelector('.vo-video'); v.currentTime = v.duration - 0.8; }")
        pg.wait_for_timeout(1800)
        a = f.evaluate(HD_J)
        check(f"{tag} hd: the take ended: both stopped", a["e"] and (a["hd"] or {}).get("p") is True, a)
        pg.tap(".pip-pp")
        pg.wait_for_timeout(250)
        a = f.evaluate(HD_J)
        check(f"{tag} hd: replay: master from the start, the last frame not left over it", not a["p"] and a["t"] < 2 and not (a["hd"] or {}).get("on"), a)
        ok = hd_on(f, 15000)
        pg.wait_for_timeout(500)
        a = f.evaluate(HD_J)
        check(f"{tag} hd: replay: the layer back in sync", ok and hd_ok(a), a)
        pg.tap(".pip-x")
        pg.wait_for_timeout(400)
        a = f.evaluate(HD_J)
        check(f"{tag} hd: X: the master paused, the layer dropped", a["p"] and not a["hd"] and a["n"] == 1, a)
        pg.tap(".pip-tab")
        pg.wait_for_timeout(500)
        a = f.evaluate(HD_J)
        check(f"{tag} hd: the tab: back on the mini, playing, no layer", not a["p"] and not a["hd"] and a["n"] == 1, a)
        shot(pg, "hd-5-settled")
        pg.tap(".pip-exp")
        ok = hd_on(f, 15000)
        pg.wait_for_timeout(500)
        a = f.evaluate(HD_J)
        check(f"{tag} hd: X and the take's end were no browser pause: expand still reaches the 720p", ok and hd_ok(a), a)
        ctx.close()

        # guard: the browser pauses the master as the second video starts (iOS? unproven on a real iPhone). Bypass, declared: the fault forced by a test hook in the
        # page, through the prototype's pause right after the layer's play(), so past pip.js's own pause: a browser's pause wouldn't pass there either
        ctx, pg, cdp = new_ctx()
        ready(pg, "scan/?r=demoR3port01")
        f = fr(pg)
        video_up(f)
        pg.wait_for_timeout(800)
        f.evaluate(HD_IOS)
        pg.tap(".pip-exp")
        try:
            f.wait_for_function("() => window.__ios > 0", timeout=20000)
        except Exception:
            pass
        pg.wait_for_timeout(500)
        a = f.evaluate(HD_J)
        pg.wait_for_timeout(1000)
        b, fired = f.evaluate(HD_J), f.evaluate("window.__ios")
        shot(pg, "hd-7-guard")
        check(f"{tag} hd: guard: the browser pauses the master right after the layer's play(): layer dropped, the master back, sound on, its clock running", fired == 1 and not b["hd"] and b["n"] == 1 and not b["p"] and not b["mu"] and b["t"] - a["t"] >= 0.7, [fired, a["t"], b])
        n1 = len(net["video"])
        pg.tap(".pip-exp")
        pg.wait_for_timeout(300)
        pg.tap(".pip-exp")
        pg.wait_for_timeout(2500)
        a = f.evaluate(HD_J)
        check(f"{tag} hd: guard: minimize + expand: no 720p again this page view (no layer, no request), the master playing", not a["hd"] and a["n"] == 1 and not a["p"] and not [u for u in net["video"][n1:] if "-360." not in u] and f.evaluate("window.__ios") == 1, [a, net["video"][n1:]])
        ctx.close()

        # the wire's two faults: the 720p never answers (a slow link: the mini plays on), the 360p files are gone (720p by itself, no layer)
        ctx, pg, cdp = new_ctx()
        for x in F720:
            ctx.route(f"**/video/{x}", lambda r: None)
        ready(pg, "scan/?r=demoR3port01")
        f = fr(pg)
        video_up(f)
        pg.wait_for_timeout(800)
        f.evaluate(HD_WATCH)
        pg.tap(".pip-exp")
        pg.wait_for_timeout(4000)
        a, w = f.evaluate(HD_J), hd_watch(f)
        check(f"{tag} hd: the 720p never answers: never shown, no freeze, the mini plays on with sound", w["on"] is None and not a["p"] and not a["mu"] and w["wall"] > 2 and w["adv"] >= 0.8 * w["wall"], [w, a["p"], a["mu"]])
        shot(pg, "hd-6-720p-never-answers")
        pg.tap(".pip-exp")
        pg.wait_for_timeout(300)
        s = st(pg)
        check(f"{tag} hd: the 720p never answers: minimize still works", not s["big"] and not f.evaluate(HD_J)["p"], s["box"])
        ctx.close()
        e0 = len(net["errors"])
        ctx, pg, cdp = new_ctx()
        ctx.route("**/video/jack-360.*", lambda r: r.fulfill(status=404, body=""))
        ready(pg, "scan/?r=demoR3port01")
        f = fr(pg)
        video_up(f)
        a = f.evaluate(HD_J)
        pg.tap(".pip-exp")
        pg.wait_for_timeout(1200)
        b = f.evaluate(HD_J)
        check(f"{tag} mini: the 360p files 404: the 720p plays by itself, expand adds no layer", a["src"] in F720 and b["n"] == 1 and not b["hd"] and not b["p"], [a["src"], b["n"], b["hd"], b["p"]])
        ctx.close()
        del net["errors"][e0:]   # the injected 404s

    ctx, pg, cdp = new_ctx(motion="reduce")
    ready(pg, "scan/?r=demoR3port01")
    td = pg.evaluate("() => getComputedStyle(document.querySelector('.pip')).transitionDuration")
    check(f"{tag} motion: prefers-reduced-motion = no transitions", all(float(x.strip()[:-1]) == 0 for x in td.split(",")), td)
    ctx.close()
    if engine == "webkit":
        browser.close()
    # allowed: Playwright's WebKit build has no native media-control icons ("Button failed to load", the /video/ page's own
    # <video controls>, also without the player)
    hosts = sorted({urlsplit(x).hostname for x in net["outside"] if x.startswith("http")})   # WebKit routes data: / blob: too
    errs = [x for x in net["errors"] if not x.startswith("Button failed to load, iconName")]
    check(f"{tag} no request left loopback (the demo iframe included: no Google Fonts), no console / JS errors", not hosts and not errs, hosts + errs[:5])


MEDIA_J = """window.__mf = []; const __f = window.fetch; window.fetch = function (u) { if (String(u).includes('/api/media/')) { const v = document.querySelector('.vo-video'); window.__mf.push([String(u), v ? v.currentTime : -1, performance.now()]); } return __f.apply(this, arguments); };"""
OWN_J = """() => { const o = [...document.querySelectorAll('.vo-own')], m = i => i.getAttribute('src').includes('/api/media/'), v = document.querySelector('.vo-video');
  return {n: o.length, set: o.filter(m).length, ok: o.filter(i => m(i) && i.complete && i.naturalWidth > 0).length, ct: v.currentTime, paused: v.paused, mf: window.__mf}; }"""
PLAY4 = "() => { const v = document.querySelector('.vo-video'); v.muted = true; v.playbackRate = 4; return v.play(); }"   # the take x 4
PHOTOS_AT = 5


def photos_flow(pw, chromium, vp_name, vp, engine="chromium"):
    """js/video-overlays.js photosLater: her photos (shown from the Images card's after state, ~16 s) start at PHOTOS_AT s of the take: on every
    path once, never stuck, nothing before it. WebKit: seeks only (Playwright's WebKit video clock stays at 0, measured: declared)."""
    if vp_name != "phone":
        return
    webkit = engine == "webkit"
    tag = f"{vp_name}{'-webkit' if webkit else ''} photos:"
    S = "demoR3port01"
    browser = pw.webkit.launch() if webkit else chromium

    def page(url, init=""):
        ctx = browser.new_context(**(dict(pw.devices["iPhone 13"]) if webkit else dict(viewport=vp, device_scale_factor=2, is_mobile=True, has_touch=True)))
        ctx.add_init_script(MEDIA_J)
        if init:
            ctx.add_init_script(init)
        ctx.route("**/*", lambda r, _q: r.continue_() if urlsplit(r.request.url).hostname in LOOP or r.request.url.startswith(("data:", "blob:")) else r.abort())
        break_routes(ctx)
        pg = ctx.new_page()
        pg.goto(cfg.base + url, wait_until="load")
        return ctx, pg

    def named(f):
        f.wait_for_function("() => document.documentElement.dataset.voMode === 'named'", timeout=15000)

    def started(f, what, s=None, past=PHOTOS_AT):   # nothing before `past`, then one chain (the media index's own polls are >= 4 s apart), all photos loaded
        try:
            f.wait_for_function("() => window.__mf.length > 0 && [...document.querySelectorAll('.vo-own')].every(i => i.getAttribute('src').includes('/api/media/') && i.complete && i.naturalWidth > 0)", timeout=20000)
        except Exception:
            pass
        f.wait_for_timeout(700)
        o = f.evaluate(OWN_J)
        gaps = [b[2] - a[2] for a, b in zip(o["mf"], o["mf"][1:])]
        check(f"{tag} {what}: all {o['n']} own photos loaded, started at >= {past} s of the take, once",
              o["n"] >= 4 and o["ok"] == o["n"] and bool(o["mf"]) and o["mf"][0][1] >= past and all(g > 3500 for g in gaps) and (s is None or all(s in x[0] for x in o["mf"])),
              {"ct_at_start": o["mf"][0][1] if o["mf"] else None, "index_gaps_ms": [round(g) for g in gaps], "ok": o["ok"], "n": o["n"]})

    def none_yet(f, what, ms=1200):
        f.wait_for_timeout(ms)
        o = f.evaluate(OWN_J)
        check(f"{tag} {what}: no photo request yet (video at {o['ct']:.1f} s, paused {o['paused']})", not o["mf"] and o["set"] == 0 and o["ct"] < PHOTOS_AT, o["mf"][:2])

    # a deep link past it: at once, without a single second played
    ctx, pg = page(f"video/?r={S}&t=20")
    named(pg.main_frame)
    started(pg.main_frame, "?t=20")
    ctx.close()

    # no result, no photos: the generic take past it
    ctx, pg = page("video/")
    pg.evaluate("() => { const v = document.querySelector('.vo-video'); v.pause(); v.currentTime = 9; }")
    pg.wait_for_timeout(1000)
    o = pg.evaluate(OWN_J)
    check(f"{tag} generic /video/ past it: no request, default photos", not o["mf"] and o["set"] == 0, o["mf"][:2])
    ctx.close()

    # /video/ directly: nothing below it, a seek across it starts them
    ctx, pg = page(f"video/?r={S}")
    f = pg.main_frame
    named(f)
    f.evaluate("() => { const v = document.querySelector('.vo-video'); v.pause(); v.currentTime = 4.5; }")
    none_yet(f, "/video/ directly, below it")
    f.evaluate("() => { document.querySelector('.vo-video').currentTime = 5.1; }")
    started(f, "/video/ directly, a seek past it", S)
    f.evaluate("() => { document.querySelector('.vo-video').currentTime = 2; }")   # back under it and over it again: no second start
    f.wait_for_timeout(300)
    f.evaluate("() => { document.querySelector('.vo-video').currentTime = 9; }")
    f.wait_for_timeout(600)
    o = f.evaluate(OWN_J)
    check(f"{tag} back under it and past it again: no second start", all(b[2] - a[2] > 3500 for a, b in zip(o["mf"], o["mf"][1:])), [round(x[2]) for x in o["mf"]])
    ctx.close()

    # the demo iframe personalized: still lazy (WebKit starts one at once on a src change, measured): no request until scrolled to, then her photos
    ctx, pg = page(f"?r={S}")
    reqs = []
    ctx.on("request", lambda q: "/showcase/" in q.url and reqs.append(q.url))
    pg.wait_for_function("() => { const f = document.querySelector('iframe[data-p=demo]'); return (f.getAttribute('src') || f.getAttribute('data-src')).includes('r='); }", timeout=15000)
    pg.wait_for_timeout(2500)
    check(f"{tag.replace('photos:', 'demo-lazy:')} personalized: the demo not requested before it is scrolled to", not reqs, reqs[:2])
    pg.evaluate("() => document.querySelector('#showcase').scrollIntoView()")
    try:
        pg.wait_for_function("() => { const d = document.querySelector('iframe[data-p=demo]').contentDocument, i = d && d.querySelector('img.hero__bg'); return i && i.getAttribute('src').includes('/api/media/') && i.complete && i.naturalWidth > 0; }", timeout=20000)
        ok = True
    except Exception:
        ok = False
    pg.screenshot(path=str(cfg.out / f"{vp_name}{'-webkit' if webkit else ''}-demo-lazy-scrolled.png"))
    check(f"{tag.replace('photos:', 'demo-lazy:')} scrolled to: loads with her slug, her photo on the hero", ok and any("/showcase/" in x.url and "r=" in x.url for x in pg.frames), reqs[:2])
    ctx.close()
    if webkit:
        browser.close()
        return

    # really played, paused before it, resumed
    ctx, pg = page(f"video/?r={S}")
    f = pg.main_frame
    named(f)
    f.evaluate("() => { const v = document.querySelector('.vo-video'); v.pause(); v.currentTime = 2; }")
    none_yet(f, "paused at 2 s")
    f.evaluate(PLAY4)
    started(f, "paused before it, then played on", S)
    ctx.close()

    # autoplay blocked (play() refused until a tap: a hook, declared): the reader taps, it plays, they come
    ctx, pg = page(f"video/?r={S}", "window.__block = true; const __p = HTMLMediaElement.prototype.play; HTMLMediaElement.prototype.play = function () { return window.__block ? Promise.reject(new DOMException('blocked', 'NotAllowedError')) : __p.apply(this, arguments); };")
    f = pg.main_frame
    named(f)
    none_yet(f, "autoplay blocked")
    f.evaluate("() => { window.__block = false; }")
    pg.locator(".vo-stage").tap()
    f.wait_for_function("() => !document.querySelector('.vo-video').paused", timeout=5000)
    f.evaluate(PLAY4)
    started(f, "autoplay blocked, then a tap", S)
    ctx.close()

    # the shared link in the iPhone theater (Fullscreen API removed, declared: as on iPhone Safari): /video/ has no autoplay, nothing until the reader plays
    ctx, pg = page(f"video/?r={S}", "Object.defineProperty(Document.prototype, 'fullscreenEnabled', { get: () => false }); Element.prototype.requestFullscreen = undefined; Element.prototype.webkitRequestFullscreen = undefined;")
    f = pg.main_frame
    named(f)
    pg.locator(".vo-fs").tap()
    f.wait_for_function("() => document.documentElement.dataset.voFull === 'theater'", timeout=3000)
    none_yet(f, "iPhone theater, not played yet")
    pg.locator(".vo-stage").tap()
    f.wait_for_function("() => !document.querySelector('.vo-video').paused", timeout=5000)
    f.evaluate(PLAY4)
    started(f, "iPhone theater, then a tap", S)
    ctx.close()

    # the mini player (the landing's real path): tucked, then back; off-screen, then back
    for what, away, back in (("tucked by its X", lambda pg: pg.click(".pip-x"), lambda pg: pg.click(".pip-tab")),
                             ("off-screen", lambda pg: pg.evaluate("() => document.querySelector('.pip').style.setProperty('transform', 'translate(-9999px, 0)', 'important')"),
                              lambda pg: pg.evaluate("() => document.querySelector('.pip').style.removeProperty('transform')"))):
        ctx, pg = page(f"?r={S}")
        pg.keyboard.press("Shift")
        pg.wait_for_function("() => { const p = document.querySelector('.pip'), d = p && p.querySelector('iframe').contentDocument; return p && p.classList.contains('on') && d && d.documentElement && d.documentElement.dataset.voMode === 'named'; }", timeout=20000)
        f = next(x for x in pg.frames if "/video/" in x.url)
        away(pg)
        f.wait_for_function("() => document.querySelector('.vo-video').paused", timeout=5000)
        none_yet(f, f"mini player {what}")
        back(pg)
        f.wait_for_function("() => !document.querySelector('.vo-video').paused", timeout=5000)
        f.evaluate(PLAY4)
        started(f, f"mini player {what}, then back", S)
        ctx.close()

    # the name bar: a result before it waits for it
    ctx, pg = page("video/")
    f = pg.main_frame
    f.fill("#vo-nb-in", "photosone")
    f.press("#vo-nb-in", "Enter")
    named(f)
    f.wait_for_function("() => /[?&]r=/.test(location.search)", timeout=15000)
    one = pg.url.split("r=")[-1]
    none_yet(f, "?name= rebuild in place, her result in before it", 300)
    f.evaluate(PLAY4)
    started(f, "?name= rebuild in place", one)
    ctx.close()

    # the name bar: the take holds at its Building beat (past it) until the scan answers: a later result starts them at once
    held = []
    ctx, pg = page("video/")
    ctx.route("**/api/public-scan", lambda r: held.append(r))
    f = pg.main_frame
    f.fill("#vo-nb-in", "photostwo")
    f.press("#vo-nb-in", "Enter")
    f.wait_for_timeout(300)
    f.evaluate(PLAY4)
    f.wait_for_function("() => document.querySelector('.vo-video').currentTime > 6", timeout=15000)
    o = f.evaluate(OWN_J)
    check(f"{tag} scan still running past it: nothing to ask for yet", held != [] and not o["mf"], o["mf"][:2])
    held[0].continue_()
    named(f)
    started(f, "her result after it: at once")
    ctx.close()

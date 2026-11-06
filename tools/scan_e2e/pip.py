"""Scenario `pip` (see tools/scan_e2e.py for what it proves)."""
from urllib.parse import parse_qs, urlsplit

from .common import LOOP, MEASURED, break_routes, cfg, check


PIP_J = """() => { const p = document.querySelector('.pip'), t = document.querySelector('.pip-tab'), c = document.querySelector('.hero .report-card'),
    R = e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.width, r.height].map(Math.round); };
  if (!p) return null; const f = p.querySelector('iframe'); let v = null, emb = null;
  try { const d = f.contentDocument, e = d.querySelector('.vo-video'), st = d.querySelector('.vo-stage').getBoundingClientRect();
    v = {paused: e.paused, muted: e.muted, t: e.currentTime, src: e.currentSrc, dur: e.duration}; emb = {nb: getComputedStyle(d.querySelector('.vo-nb')).display, ui: getComputedStyle(d.querySelector('.vo-ui')).display,
    sw: Math.round(st.width), sh: Math.round(st.height), fw: f.clientWidth, fh: f.clientHeight}; } catch (x) { v = String(x); }
  const pic = p.querySelector('.pip-pic').getBoundingClientRect(), ctl = [...p.querySelectorAll('button, a')].map(b => b.getBoundingClientRect()),
    g = p.querySelector('.pip-rs'), gr = g.getBoundingClientRect(), x = p.querySelector('.pip-exp');
  return {cls: p.className, mode: p.dataset.mode, big: p.classList.contains('big'), url: location.href, opens: window.__opens || 0,
    bar: [...p.querySelectorAll('.pip-bar button')].map(b => { const r = b.getBoundingClientRect(); return [b.className, b.getAttribute('aria-label'), Math.round(r.width), Math.round(r.height)]; }),
    exp: x && [x.getAttribute('aria-label'), x.getAttribute('aria-expanded'), x.innerHTML.includes('m6 9') ? 'v' : 'expand'],
    grip: getComputedStyle(g).display === 'none' ? null : [gr.left - pic.left, gr.top - pic.top, gr.width, gr.height].map(Math.round), box: R(p), pic: R(p.querySelector('.pip-pic')), card: c ? R(c) : null,
    on: p.classList.contains('on') && !p.classList.contains('tucked'), tucked: p.classList.contains('tucked'),
    overPic: ctl.filter(b => b.right > pic.left && b.left < pic.right && b.bottom > pic.top && b.top < pic.bottom).length,
    tab: t && !t.hidden ? {box: R(t), side: t.dataset.side, chev: t.innerHTML.includes('m9 6') ? '>' : t.innerHTML.includes('m15 6') ? '<' : '?'} : null,
    v, emb, src: f.src, focus: document.activeElement && document.activeElement.className, vw: document.documentElement.clientWidth, vh: innerHeight,
    hdr: Math.max(...['.site-header', '.rnav'].map(q => document.querySelector(q)).filter(Boolean).map(e => { const r = e.getBoundingClientRect(); return r.top < 140 ? r.bottom : 0; })),
    ss: JSON.parse(sessionStorage.getItem('leakscan.pip') || 'null')}; }"""
PIP_HIT = """([sel, inside]) => [...document.querySelectorAll(sel)].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.bottom > 0 && r.top < innerHeight && getComputedStyle(e).visibility !== 'hidden'; })
  .map(e => { const r = e.getBoundingClientRect(), pts = [[r.left + r.width / 2, r.top + r.height / 2], [r.left + 4, r.top + r.height / 2], [r.right - 4, r.top + r.height / 2]];
    return pts.every(([x, y]) => { const h = document.elementFromPoint(x, y); return h && h.closest(inside || sel) === e.closest(inside || sel); }); })"""
# what is under the docked player: elementFromPoint on a 12x8 grid over its box with the player hidden; any link / button / input there = covered
PIP_UNDER = """() => { const p = document.querySelector('.pip'), r = p.getBoundingClientRect(), out = new Set();
  p.style.visibility = 'hidden'; const LIVE = 'a[href], button, input, select, textarea, summary, label, [role="tab"], [role="button"], [tabindex]:not([tabindex="-1"])';
  for (let i = 0; i <= 12; i++) for (let j = 0; j <= 8; j++) { const x = r.left + 1 + (r.width - 2) * i / 12, y = r.top + 1 + (r.height - 2) * j / 8;
    if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) continue;
    const h = document.elementFromPoint(x, y), l = h && h.closest(LIVE); if (l && !l.closest('.askai-launcher, .mobile-cta, .pip-tab')) out.add((l.className || l.tagName) + ':' + (l.textContent || '').trim().slice(0, 20)); }
  p.style.visibility = ''; return [...out]; }"""


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


def pip_flow(pw, chromium, vp_name, vp, engine="chromium"):
    """js/pip.js: the mini player of site/video/ (landing: docked on the hero card, then floating; scan report with ?r=: floating)."""
    tag = f"{vp_name}{'-webkit' if engine == 'webkit' else ''} pip:"
    net = {"outside": [], "errors": [], "video": [], "pages": []}
    phone = vp_name == "phone"
    browser = pw.webkit.launch() if engine == "webkit" else chromium
    M = 12 if phone else 24

    def new_ctx(motion="no-preference"):
        opts = dict(pw.devices["iPhone 13"]) if engine == "webkit" else dict(viewport=vp, device_scale_factor=2 if phone else 1, is_mobile=phone, has_touch=phone)
        ctx = browser.new_context(**opts, reduced_motion=motion)
        ctx.add_init_script("""window.__opens = 0; const __o = window.open; window.open = function () { window.__opens++; return __o.apply(this, arguments); };
          window.__ls = []; try { new PerformanceObserver(l => l.getEntries().forEach(e => window.__ls.push([e.startTime, e.value]))).observe({type: 'layout-shift', buffered: true}); } catch (e) {}
          new MutationObserver(() => { if (!window.__pipAt && document.querySelector('.pip iframe')) window.__pipAt = performance.now(); }).observe(document, {childList: true, subtree: true});""")

        def route(r, _req):
            if urlsplit(r.request.url).hostname in LOOP:
                if "/video/" in r.request.url:
                    net["video"].append(r.request.url)
                r.continue_()
            else:
                net["outside"].append(r.request.url)
                r.abort()
        ctx.route("**/*", route)
        break_routes(ctx)   # --break-tuck: tuck() emptied; --break-dock: no dock anchor (common.BREAKS)
        ctx.on("page", lambda pg: (pg.on("pageerror", lambda e: net["errors"].append(str(e))),
                                   pg.on("console", lambda m: m.type == "error" and net["errors"].append(m.text))))
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
        return st(pg)

    def fling(pg, cdp, s, dx):
        x0, y0 = pic_c(s)
        drag(pg, cdp, [(x0 + dx * i / 6, y0) for i in range(7)], 10, 0)
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

    def float_default(s):   # bottom-right at min(320 px, 45vw)
        return s["mode"] == "float" and abs(s["box"][2] - min(320, 0.45 * s["vw"])) <= 1 and s["box"][0] + s["box"][2] == s["vw"] - M and s["box"][1] > s["vh"] / 2

    def dock_checks(pg, s, what):
        c = s["card"]
        b = s["box"]
        ix = max(0, min(b[0] + b[2], c[0] + c[2]) - max(b[0], c[0])); iy = max(0, min(b[1] + b[3], c[1] + c[3]) - max(b[1], c[1]))
        cov = ix * iy / (c[2] * c[3])
        MEASURED[f"{tag} dock {what}"] = {"pip": b, "card": c, "coverage": round(cov, 3)}
        check(f"{tag} dock: {what}: docked, 55% of the card wide, in its bottom-right slot (live report: hanging off that corner)",
              s["mode"] == "dock" and abs(b[2] - round(c[2] * 0.55)) <= 1 and (b[0] + b[2] >= c[0] + c[2] - 13 and b[1] + b[3] > c[1] + c[3]
              or b[0] + b[2] >= c[0] + c[2] - 24 and b[1] + b[3] <= c[1] + c[3]) and b[1] > c[1] + c[3] * 0.5 and ratio_ok(s), [b, c])
        check(f"{tag} dock: {what}: covers <= 25% of the card", cov <= 0.25, round(cov, 3))
        under = pg.evaluate(PIP_UNDER)
        ok, d = clear(pg)
        check(f"{tag} dock: {what}: no link / button / input under it (grid), Scan now / header / Ask-AI still clickable", not under and ok, [under, d])
        check(f"{tag} dock: {what}: start spot off the screen corner (up / left of it)", not (0 <= s["vw"] - (b[0] + b[2]) <= 24 and 0 <= s["vh"] - (b[1] + b[3]) <= 24), b)

    # flags: landing ?pip=0 and scan/ without ?r= = no player, no /video/ request
    ctx, pg, cdp = new_ctx()
    pg.goto(cfg.base + "?pip=0", wait_until="load"); pg.keyboard.press("Shift"); pg.evaluate("scrollBy(0, 400)"); pg.wait_for_timeout(4500)
    pg.goto(cfg.base + "scan/", wait_until="load"); pg.keyboard.press("Shift"); pg.wait_for_timeout(4500)
    check(f"{tag} flag: landing ?pip=0 and scan/ without ?r= show no player, load no /video/", pg.locator(".pip").count() == 0 and not net["video"], net["video"])

    # report page: floating, default on with ?r= (idle mount, no interaction)
    s = ready(pg, "scan/?r=demoR3port01", wake=False)
    lz = pg.evaluate("() => [window.__pipAt, performance.getEntriesByType('navigation')[0].loadEventEnd]")
    check(f"{tag} lazy: iframe created only after the page's load", lz[0] and lz[0] >= lz[1], lz)
    check(f"{tag} appear: bottom-right, {'45% of the screen' if phone else '320 px'} wide, 16:9 picture", float_default(s) and ratio_ok(s), [s["box"], s["pic"]])
    check(f"{tag} bar: no control drawn over the picture (only the 28 px resize corner, top-left), 40 px bar", s["overPic"] == 0 and s["box"][3] - s["pic"][3] == 40
          and s["grip"] == [0, 0, 28, 28], [s["overPic"], s["box"], s["pic"], s["grip"]])
    check(f"{tag} bar: exactly play / sound / expand / close, each a >= 40x40 px button, no link",
          [b[0] for b in s["bar"]] == ["pip-pp", "pip-snd", "pip-exp", "pip-x"] and all(b[2] >= 40 and b[3] >= 40 for b in s["bar"])
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
    check(f"{tag} drop: released mid-screen it stays there (no snap)", s["on"] and abs(cx - mx) <= 3 and abs(cy - my) <= 3 and s["ss"]["p"], [s["box"], round(mx), round(my)])
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

    s = ready(pg, "scan/?r=demoR3port01")   # fresh page: spot from sessionStorage
    check(f"{tag} state: spot kept in sessionStorage across a reload", s["on"] and abs(s["box"][0] - spot[0]) <= 2 and abs(s["box"][1] - spot[1]) <= 2, [s["box"], spot])
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
    w0 = s["box"][2]
    s = grip(pg, cdp, s, -90, -40)
    check(f"{tag} resize: grip dragged out → bigger, 16:9 kept, bottom-right edge anchored", s["on"] and s["box"][2] >= w0 + 80 and ratio_ok(s)
          and s["box"][0] + s["box"][2] == s["vw"] - 8, [w0, s["box"], s["pic"]])
    shot(pg, "6-resized")
    s = grip(pg, cdp, s, 900, 600)
    check(f"{tag} resize: min 168 px wide (the 4 x 40 px buttons)", s["box"][2] == 168 and ratio_ok(s), s["box"])
    s = drop(pg, cdp, s, s["vw"] / 2, s["vh"] / 2)
    s = grip(pg, cdp, s, -1400, -1000)
    mx_w = min(s["vw"] * (0.9 if phone else 0.6), (s["vh"] - s["hdr"] - 8 - 8 - 40) * 16 / 9)
    check(f"{tag} resize: max {'90' if phone else '60'}% of the width (or the screen height)", abs(s["box"][2] - mx_w) <= 2 and ratio_ok(s) and s["box"][1] >= s["hdr"], [s["box"], round(mx_w)])
    big = s["box"][2]
    s = ready(pg, "scan/?r=demoR3port01")
    check(f"{tag} resize: size kept across a reload", abs(s["box"][2] - big) <= 1, [s["box"][2], big])
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
    s = ready(pg, "scan/?r=demoR3port01")
    check(f"{tag} tuck: tucked state kept across a reload", bool(s) and s["tucked"], s and s["cls"])
    pg.focus(".pip-tab"); pg.keyboard.press("Enter"); pg.wait_for_timeout(500); s = st(pg)
    check(f"{tag} tuck: Enter on the tab brings it back, focus inside the player", s["on"] and not s["tab"] and (s["focus"] or "").startswith("pip-"), [s["cls"], s["focus"]])
    ls = pg.evaluate("() => window.__ls.filter(e => e[0] >= (window.__pipAt || 0)).reduce((a, e) => a + e[1], 0)")
    check(f"{tag} cls: 0 after the player mounts (report)", ls == 0, ls)

    s = ready(pg, "scan/?r=demoR3port01")
    pg.click(".pip-x"); pg.wait_for_timeout(400)
    gone = pg.locator(".pip, .pip-tab").count() == 0
    pg.goto(cfg.base + "scan/?r=demoR3port01", wait_until="load"); pg.keyboard.press("Shift"); pg.wait_for_timeout(1500)
    check(f"{tag} close: x removes it, stays closed for the session", gone and pg.locator(".pip").count() == 0)
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
        cdp.send("Input.synthesizeScrollGesture", {"x": sx, "y": sy, "yDistance": -500, "gestureSourceType": "touch", "speed": 1500})
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
    check(f"{tag} minimize: the chevron → back to the mini player bottom-right", not s["big"] and float_default(s) and s["exp"] == ["Expand video", "false", "expand"], [s["box"], s["exp"]])
    pg.click(".pip-exp"); pg.wait_for_timeout(600)
    pg.focus(".pip-exp"); pg.keyboard.press("Escape"); pg.wait_for_timeout(600); s = st(pg)
    check(f"{tag} minimize: Esc (focus inside) → mini again, focus kept on the toggle", not s["big"] and float_default(s) and s["focus"] == "pip-exp", [s["box"], s["focus"]])
    tap(pg, *pic_c(s)); pg.wait_for_timeout(300); s = st(pg)

    def pull(s, frac, steps, step, hold):   # finger on the expanded picture, down by frac of the way to the mini spot
        x0, y0 = pic_c(s)
        dy = max(120, mini[1] - s["box"][1]) * frac
        return drag(pg, cdp, [(x0, y0 + dy * i / steps) for i in range(steps + 1)], step, hold, mid=lambda: st(pg))
    m = pull(s, 0.15, 8, 30, 200); s = st(pg)
    check(f"{tag} pull: dragged down 15% → follows the finger (lower, scaled down), released → snaps back expanded",
          m["box"][1] > big0[1] + 10 and m["box"][2] < bw - 10 and big_ok(s), [m["box"], s["box"]])
    m = pull(s, 0.5, 12, 30, 200); s = st(pg)
    check(f"{tag} pull: dragged down 50% → mini player bottom-right, still playing with sound",
          m["box"][2] < bw * 0.85 and not s["big"] and float_default(s) and isinstance(s["v"], dict) and not s["v"]["paused"] and not s["v"]["muted"], [m["box"], s["box"], s["v"]])
    shot(pg, "7d-pulled-mini")
    tap(pg, *pic_c(s)); pg.wait_for_timeout(300); s = st(pg)
    pull(s, 0.2, 4, 8, 0); s = st(pg)
    check(f"{tag} pull: a quick flick down (20% of the way) → mini", not s["big"] and float_default(s), s["box"])
    if s["big"]:   # the pull broken (--break-pull): back to the mini so the checks below stay independent of it
        pg.click(".pip-exp"); pg.wait_for_timeout(600); s = st(pg)
        if isinstance(s["v"], dict) and s["v"]["paused"]:   # its taps toggled play / pause
            pg.click(".pip-pp"); pg.wait_for_timeout(400); s = st(pg)
    x0, y0 = pic_c(s)
    drag(pg, cdp, [(x0, y0 + 25 * i) for i in range(7)], 10, 0); s = st(pg)
    check(f"{tag} tuck: mini flung down past the bottom → hidden, '<' tab at the right edge, paused",
          s["tucked"] and s["box"][0] >= s["vw"] and bool(s["tab"]) and s["tab"]["side"] == "r" and isinstance(s["v"], dict) and s["v"]["paused"], [s["box"], s["tab"]])
    shot(pg, "7e-hidden-tab")
    if s["tab"]:
        b = s["tab"]["box"]; tap(pg, b[0] + b[2] / 2, b[1] + b[3] / 2); s = st(pg)
    check(f"{tag} tuck: tab tapped → the mini player is back where the flick started, playing", s["on"] and not s["tab"] and abs(s["box"][0] - mini[0]) <= 2
          and abs(s["box"][1] - mini[1]) <= 2 and isinstance(s["v"], dict) and not s["v"]["paused"], [s["box"], mini])
    shot(pg, "7f-back")
    pg.click(".pip-x"); pg.wait_for_timeout(400)
    check(f"{tag} close: x removes it (after expand / pull / hide)", pg.locator(".pip, .pip-tab").count() == 0)
    check(f"{tag} expand: no new page / tab, no window.open, same URL throughout", not net["pages"] and s["opens"] == 0 and pg.url == url0, [net["pages"], s["opens"], pg.url])
    ctx.close()

    # landing, default on: docked on the hero card, floating once the hero is out, re-docked on the way back
    ctx, pg, cdp = new_ctx()
    s = ready(pg, "", card=phone)
    dock_checks(pg, s, "before a scan (weekly report card)")
    shot(pg, "8-landing-docked")
    ok, d = clear(pg)
    check(f"{tag} landing: Scan now + header clickable with the player up", ok and d["scan"], d)
    ls = pg.evaluate("() => window.__ls.filter(e => e[0] >= (window.__pipAt || 0)).reduce((a, e) => a + e[1], 0)")
    check(f"{tag} cls: 0 after the player mounts (landing, docked)", ls == 0, ls)
    docked = s["box"]
    tap(pg, *pic_c(s)); pg.wait_for_timeout(300); b = st(pg)
    check(f"{tag} landing: tap on the docked player → expanded under the header", b["big"] and abs(b["box"][1] - (b["hdr"] + (0 if phone else 12))) <= 1
          and abs(b["box"][2] - (b["vw"] if phone else min(960, round(b["vw"] * 0.7)))) <= 1, [b["box"], b["hdr"]])
    shot(pg, "8b-landing-expanded")
    pg.click(".pip-exp"); pg.wait_for_timeout(700); s = st(pg)
    check(f"{tag} landing: minimized → docked on the card again, same box", s["mode"] == "dock" and all(abs(a - c) <= 2 for a, c in zip(s["box"], docked)), [s["box"], docked])
    pg.evaluate("scrollTo(0, document.querySelector('#why').offsetTop)"); pg.wait_for_timeout(1300); s = st(pg)
    ov = pg.evaluate("""() => { const p = document.querySelector('.pip').getBoundingClientRect(); return [...document.querySelectorAll('.mobile-cta.show, .askai-launcher:not([hidden])')]
      .filter(e => getComputedStyle(e).visibility !== 'hidden').map(e => { const r = e.getBoundingClientRect(); return r.left < p.right && r.right > p.left && r.top < p.bottom && r.bottom > p.top; }); }""")
    ok, d = clear(pg)
    check(f"{tag} cycle: hero out of view → floating, bottom-right, normal size, clear of the CTA bar / Ask-AI launcher",
          s["on"] and s["mode"] == "float" and abs(s["box"][2] - min(320, 0.45 * s["vw"])) <= 1 and s["box"][0] + s["box"][2] == s["vw"] - M and not any(ov) and ok, [s["box"], ov, d])
    shot(pg, "9-landing-floating")
    pg.evaluate("scrollTo(0, 0)"); pg.wait_for_timeout(300)
    if phone:
        pg.evaluate("document.querySelector('.hero .report-card').scrollIntoView({block: 'center', behavior: 'instant'})")
    pg.wait_for_timeout(1200); s = st(pg)
    check(f"{tag} dock: scrolled back up → docked again on the card", s["mode"] == "dock" and abs(s["box"][2] - docked[2]) <= 1, [s["box"], docked])
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
            check(f"{tag} take: playing source = the real take, the first <source> this engine plays (jack.webm / jack.mp4)",
                  a["src"] in ("jack.webm", "jack.mp4") and a["src"] == a["first"], [a["src"], a["first"]])
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

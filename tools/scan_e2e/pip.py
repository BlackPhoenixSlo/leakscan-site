"""Scenario `pip` (see tools/scan_e2e.py for what it proves)."""
from urllib.parse import parse_qs, urlsplit

from .common import LOOP, break_routes, cfg, check


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
            if urlsplit(r.request.url).hostname in LOOP:
                if "/video/" in r.request.url:
                    net["video"].append(r.request.url)
                r.continue_()
            else:
                net["outside"].append(r.request.url)
                r.abort()
        ctx.route("**/*", route)
        break_routes(ctx)   # --break-tuck: pip.js with tuck() emptied (common.BREAKS)
        ctx.on("page", lambda pg: (pg.on("pageerror", lambda e: net["errors"].append(str(e))),
                                   pg.on("console", lambda m: m.type == "error" and net["errors"].append(m.text))))
        pg = ctx.new_page()
        return ctx, pg, (ctx.new_cdp_session(pg) if engine == "chromium" and phone else None)

    def st(pg):
        return pg.evaluate(PIP_J)

    def ready(pg, url, wake=True):
        pg.goto(cfg.base + url, wait_until="load")
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
        pg.screenshot(path=str(cfg.out / f"{tag.split()[0]}-pip-{name}.png"))

    # flags: landing without ?pip=1, scan/ without ?r= = no player, no /video/ request
    ctx, pg, cdp = new_ctx()
    pg.goto(cfg.base, wait_until="load"); pg.keyboard.press("Shift"); pg.evaluate("scrollBy(0, 400)"); pg.wait_for_timeout(4500)
    pg.goto(cfg.base + "scan/", wait_until="load"); pg.keyboard.press("Shift"); pg.wait_for_timeout(4500)
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
    check(f"{tag} appear: same-origin iframe of /video/?r=<slug>", f"{u.scheme}://{u.netloc}/" == cfg.base and u.path == "/video/" and parse_qs(u.query).get("r") == ["demoR3port01"], s["src"])
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
    pg.goto(cfg.base + "scan/?r=demoR3port01", wait_until="load"); pg.keyboard.press("Shift"); pg.wait_for_timeout(1500)
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
    # allowed: Playwright's WebKit build has no native media-control icons ("Button failed to load", the /video/ page's own
    # <video controls>, also without the player)
    hosts = sorted({urlsplit(x).hostname for x in net["outside"] if x.startswith("http")})   # WebKit routes data: / blob: too
    errs = [x for x in net["errors"] if not x.startswith("Button failed to load, iconName")]
    check(f"{tag} no request left loopback (the demo iframe included: no Google Fonts), no console / JS errors", not hosts and not errs, hosts + errs[:5])

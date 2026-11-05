#!/usr/bin/env python3
"""Real-path proof for site/video/: serve site/ (Range-capable, tools/video/serve.py), open video/?t=<cue> in BOTH modes,
generic (no name, no scan) and named (?name=NAME), at phone 390x844 and desktop 1440x900, wait until the <video> has
seeked there, screenshot, and assert: only the cue's prefab is on screen, in the right state (wipe --p 100 live / 0
removed), the mode's name in it ("Your name" / NAME), html[data-vo-mode], at both widths (phone too: no stacking) it
sits inside the stage's right half, vertically centred (left >= 50 %, centre within 5 % of the middle: Jack on the left stays uncovered), the rolling
counters (google "About 4,120 results" → "About 3 results", mega "52 GB · 318 videos" → "0 GB · 0 videos"), no request
leaves 127.0.0.1, no console error (named: the 404 of the jack-named.mp4 HEAD probe is expected, declared). Each prefab
is shot live (settled; google-images after its tap + grid) and removed (removed + 2 s).
After state (removed): google lists the name's site (<name>.com) + instagram.com and no leak host; google-images shows
>= 4 loaded, unblurred photos of her own (not .rm-img), no "No results".
Plus:
- end card (data-cue-cta, default data-cue-say): generic shows the "Type your name" card + form, named shows the
  "for NAME" pill instead; the form reloads with ?name=<trimmed> (named), an invalid name stays put with a message
- snap (google removed + 0.1 s): "GONE." word card, shake offset, flash; live + 0.25 s: "GOOGLE" word card
- reduced motion (prefers-reduced-motion: reduce): no shake / scale, no flash / particles, the after layer fades
- frame-1920-generic-google-live.png / frame-1920-named-mega-removed.png (counter at 0, stamp, particles) /
  frame-1920-generic-cta.png: the full 1920x1080 frame = the framing proofs
- sfx: AudioContext wrapped (declared) to log oscillators / noise sources: none before the play gesture, a pop at the
  live cue, whoosh + thud at the removed cue, nothing with ?sfx=0
- speech (named only): speechSynthesis.speak stubbed (declared: no voice in headless); Space = the play gesture; spoken
  once at data-cue-say-start and once at data-cue-say with NAME, rate 0.95, video ducked to 0.25 then restored, "for
  NAME" pill; generic → never spoken; data-cue-say moved past the end (declared) → spoken + end card on `ended`
- named take: jack-named.mp4 routed to jack.mp4's bytes (declared, wire boundary) → it plays and every cue moves by
  data-cue-named-shift; generic never asks for it
- personalized (tools/scan_stub.py, ?r=demoRemove1): named mode, texts from the scan result in every prefab; every
  .rm-img = the scan's thumbs via <API>/api/thumb, loaded, still blurred; and ?name= keeps the default photos (img/removals)
- cta-steps (generic end card): at cta + 0.9 step 1 typing (a proper prefix of the demo name), + 2.2 typed in full, + 3.3
  step 2 mid-scan (bar 10-90 %, "N leaks found" rolling) = frame-1920-generic-cta-steps-step2.png; after the take ends
  the post-roll clock keeps it looping: step 3 with the name flipped in (frame-1920-generic-cta-steps-step3-postroll.png);
  named mode never shows it
- player: phone (touch): no native controls, own play bar, a tap on the stage plays + "Rotate for full size" hint;
  proof-phone-portrait-generic-google-live.png = the whole 390x844 screen, card inside the stage's right half;
  iPhone theater (declared: Fullscreen API removed by an init script, as on iPhone Safari): the button rotates the stage
  90deg over the screen (proof-phone-theater-generic-google-live.png; the card in its right half = the screen's lower
  half), scroll locked, Esc / back / X each close it; desktop: the button puts the STAGE in full screen, the card on the
  right half of the centred 16:9 picture
--break-thumbs serves video-overlays.js without the thumb src assignment: only the thumbs check goes red.
--break-steps serves index.html without the cta-steps animation (.vo-steps): only the "cta-steps:" checks go red.
Usage: cd ~/leakhunt && uv run python ~/leakscan-site/tools/video/cue_shots.py OUT_DIR [--name Tessa] [--break-thumbs] [--break-steps]
Prints one line per shot / check + 'FAIL …' lines; exit 1 on any failure."""
import argparse, pathlib, re, socket, subprocess, sys, urllib.parse
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from serve import serve
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2]
GENERIC = "Your name"
CTA_TEXT = "Type your name in the link → this video rebuilds with YOUR leaks"
VIEWPORTS = {"phone": dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True),
             "desktop": dict(viewport={"width": 1440, "height": 900})}
SEEKED = ("t => { const v = document.querySelector('video'); return v.readyState >= 3 && !v.seeking"
          " && Math.abs(v.currentTime - t) < 0.05 }")
# demoRemove1 (tools/scan_stub.py): what its scan result must put in the [data-vo] slots
WANT_TEXT = {"name": "Mira Example", "site": "miraexample.com", "ig": "mira.example", "tt": "mira.draws", "x-at": "@demo_reposter", "x-l1": "Mira Example leaked full set", "sub": "r/demo_leaksub",
             "rd-title": "Mira Example new pack in comments", "mega-title": "demo.creator MEGA pack 2026",
             "mega-meta": "6.2 GB · 412 images · 88 videos · 3 days ago"}
COUNT = {("google", "live"): "About 4,120 results", ("google", "removed"): "About 3 results",
         ("mega", "live"): "52 GB · 318 videos", ("mega", "removed"): "0 GB · 0 videos"}
OWN = "() => [...document.querySelectorAll('.vo-own')].map(i => [i.getAttribute('src'), i.naturalWidth, getComputedStyle(i).filter])"
# the after layer of the visible prefab: [text, [[src, naturalWidth, filter] of its <img>]]
AFTER = """() => { const g = [...document.querySelectorAll('.vo-pf[data-prefab]')].find(e => !e.hasAttribute('data-off')).querySelector('.rm-gone');
  return [g.textContent.replace(/\\s+/g, ' '), [...g.querySelectorAll('img')].map(i => [i.getAttribute('src'), i.naturalWidth, getComputedStyle(i).filter, i.classList.contains('rm-img')])]; }"""
VISIBLE = """() => { const s = document.querySelector('.vo-stage').getBoundingClientRect();
  return [...document.querySelectorAll('.vo-pf')].filter(e => !e.hasAttribute('data-off')).map(e => { const r = e.getBoundingClientRect(), rs = e.querySelector('.rm-stage');
    return [e.dataset.prefab || e.className, rs ? getComputedStyle(rs).getPropertyValue('--p').trim() : null, e.textContent.replace(/\\s+/g, ' '),
            [(r.left - s.left) / s.width, (r.top - s.top) / s.height, (r.right - s.left) / s.width, (r.bottom - s.top) / s.height],
            [...e.querySelectorAll('.vo-roll')].map(x => x.textContent)]; }); }"""
# the visible prefab's effect state: [--x, --f, kw-live [text, opacity], kw-gone [...], transform, flash display, burst display, stamp opacity, max particle opacity, .rm-gone [opacity, clip-path]]
FX = """pid => { const e = document.querySelector(`.vo-pf[data-prefab="${pid}"]`), cs = getComputedStyle(e), kw = c => { const k = e.querySelector(c); return [k.textContent, +getComputedStyle(k).opacity]; };
  const g = getComputedStyle(e.querySelector('.rm-gone'));
  return [+e.style.getPropertyValue('--x'), +e.style.getPropertyValue('--f'), kw('.vo-kw-live'), kw('.vo-kw-gone'), cs.transform,
          getComputedStyle(e.querySelector('.vo-rs'), '::after').display, getComputedStyle(e.querySelector('.vo-burst')).display,
          +getComputedStyle(e.querySelector('.vo-stamp')).opacity, Math.max(...[...e.querySelectorAll('.vo-burst i')].map(i => +getComputedStyle(i).opacity)),
          [+g.opacity, g.clipPath], e.offsetWidth, e.offsetHeight]; }"""
LEAK_HOSTS = re.compile(r"\.example\b|leak|pirate|forum-dump|free-galleries", re.I)
IMGS = "() => [...document.querySelectorAll('.rm-img')].map(i => [i.getAttribute('src'), i.naturalWidth, getComputedStyle(i).filter])"
SAY_STUB = """window.__said = []; if ('speechSynthesis' in window) speechSynthesis.speak = u => { const v = document.querySelector('video');
  __said.push([u.text, v.currentTime, v.volume, u.rate, u.lang]); setTimeout(() => u.onend && u.onend(), 400); };"""
SFX_STUB = """window.__sfx = []; window.__actx = 0; { const A = window.AudioContext; if (A) window.AudioContext = class extends A {
  constructor(...a) { super(...a); __actx++; }
  createOscillator() { __sfx.push(['osc', +document.querySelector('video').currentTime.toFixed(2)]); return super.createOscillator(); }
  createBufferSource() { __sfx.push(['noise', +document.querySelector('video').currentTime.toFixed(2)]); return super.createBufferSource(); } }; }"""
# cta-steps state: {off, so: [opacity per step], typed, bar, count, mini} or null without the animation
STEPS = """() => { const c = document.querySelector('.vo-cta'), s = c && c.querySelector('.vo-steps'); if (!s) return null;
  return {off: c.hasAttribute('data-off'), so: [...s.querySelectorAll('.vo-step')].map(e => +getComputedStyle(e).opacity), typed: s.querySelector('.vo-mi-t').textContent,
          bar: +s.style.getPropertyValue('--bar'), count: s.querySelector('.vo-mc').textContent.replace(/\\s+/g, ' ').trim(), mini: s.querySelector('.vo-mini-n').textContent}; }"""
DEMO = "Orla Brennick"
# [stage rect, .vo-over rect, visible card rect, stage transform, data-vo-full, html overflow, video.controls]
GEOM = """() => { const r = e => { const b = e.getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; }, st = document.querySelector('.vo-stage'),
  card = [...document.querySelectorAll('.vo-pf')].find(e => !e.hasAttribute('data-off'));
  return [r(st), r(document.querySelector('.vo-over')), card ? r(card.querySelector('.vo-phone, .vo-panel, .vo-steps') || card) : null, getComputedStyle(st).transform,
          document.documentElement.dataset.voFull || null, getComputedStyle(document.documentElement).overflow, document.querySelector('video').controls]; }"""
IPHONE_FS = ("Object.defineProperty(Document.prototype, 'fullscreenEnabled', { get: () => false });"
             "Element.prototype.requestFullscreen = undefined; Element.prototype.webkitRequestFullscreen = undefined;")
fails = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
    if not ok:
        fails.append(name)
    return ok


def after_ok(pid, name, txt, imgs):
    site = re.sub(r"[^a-z0-9-]", "", name.lower()) + ".com"
    if pid == "google":
        return site in txt and "instagram.com" in txt and not LEAK_HOSTS.search(txt)
    own = [i for i in imgs if i[1] > 0 and i[2] == "none" and not i[3]]
    return len(own) >= 4 and "No results" not in txt and site in txt and "Instagram" in txt and not LEAK_HOSTS.search(txt)


def guard(ctx, base_ok, seen=None):
    """abort + record every request outside the local server(s); seen collects every URL"""
    ext = []

    def route(r):
        if seen is not None:
            seen.append(r.request.url)
        if any(r.request.url.startswith(b) for b in base_ok):
            r.fallback()   # → a --break-* route (registered earlier), else the network
        else:
            ext.append(r.request.url)
            r.abort()
    ctx.route("**/*", route)
    return ext


def console(pg, errs):
    probe = lambda m: m.type == "error" and "404" in m.text and (m.location or {}).get("url", "").endswith("/video/jack-named.mp4")
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and not probe(m) else None)
    pg.on("pageerror", lambda e: errs.append(str(e)))


BREAK = {}   # --break-* routes, applied to every context


def ctx_new(b, **kw):
    ctx = b.new_context(**kw)
    for pat, body, ctype in BREAK.values():   # one-arg handler (playwright passes (route, request) to two-arg ones)
        ctx.route(pat, (lambda body, ctype: lambda r: r.fulfill(body=body, content_type=ctype))(body, ctype))
    return ctx


def goto(pg, base, query, t):
    pg.goto(f"{base}video/?{query}{'&' if query else ''}t={t:g}")
    pg.wait_for_function(SEEKED, arg=t, timeout=15000)
    pg.wait_for_timeout(1200)   # the native loading spinner fades out


def stage_attr(html, k):
    m = re.search(r'class="vo-stage"[^>]*\b%s="([\d.]+)"' % re.escape(k), html)
    return float(m[1]) if m else None


def personalized(b, out, break_thumbs):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    stub = subprocess.Popen([sys.executable, str(ROOT / "tools" / "scan_stub.py"), "--port", str(port)],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        stub.stdout.readline()
        base, api = f"http://127.0.0.1:{port}/", f"http://localhost:{port}"   # the stub injects the other loopback name as data-api
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        ext, errs = guard(ctx, (base, api + "/")), []
        if break_thumbs:   # wire boundary: same bytes minus the thumb src assignment
            js = (ROOT / "site/js/video-overlays.js").read_text(encoding="utf-8")
            assert "im.setAttribute('src', src);" in js, "break: marker not found"
            js = js.replace("im.setAttribute('src', src);", "", 1)
            ctx.route("**/js/video-overlays.js", lambda r: r.fulfill(body=js, content_type="application/javascript"))
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"{base}video/?r=demoRemove1&t=15.3")
        try:
            pg.wait_for_function("() => document.querySelector('[data-vo=name]').textContent === 'Mira Example'", timeout=8000)
            pg.wait_for_function("() => [...document.querySelectorAll('.rm-img')].every(i => i.complete)", timeout=8000)
        except Exception:
            pass
        pg.wait_for_timeout(500)
        txt = pg.evaluate("() => Object.fromEntries([...document.querySelectorAll('[data-vo]')].reverse().map(e => [e.dataset.vo, e.textContent]))")
        got = {k: txt.get(k) for k in WANT_TEXT}
        check("personalized ?r=demoRemove1: texts from the scan result (name, X, Reddit, Mega)", got == WANT_TEXT, got)
        check("personalized ?r=demoRemove1: named mode", pg.evaluate("() => document.documentElement.dataset.voMode") == "named")
        im = pg.evaluate(IMGS)
        check(f"personalized ?r=demoRemove1: all {len(im)} .rm-img = scan thumbs via {api}/api/thumb, loaded, blurred",
              len(im) == 13 and all(s.startswith(api + "/api/thumb?u=") and w > 0 and "blur(" in f for s, w, f in im), im[:3])
        own = pg.evaluate(OWN)
        check(f"personalized ?r=demoRemove1: the {len(own)} after photos stay the landing after-phone's (assets/phone), unblurred",
              len(own) == 6 and all(s.startswith("../assets/phone/") and w > 0 and f == "none" for s, w, f in own), own[:3])
        # evidence shots via the solo view (the stub has no Range, so the page's <video> can't seek to a cue)
        for pid, state in (("google-images", "live"), ("x", "live"), ("google", "removed"), ("google-images", "removed")):
            pg.goto(f"{base}video/?prefab={pid}&state={state}&r=demoRemove1")
            try:
                pg.wait_for_function("() => [...document.querySelectorAll('.rm-img')].every(i => i.complete && i.naturalWidth > 0 && i.src.includes('/api/thumb'))", timeout=8000)
            except Exception:
                pass
            pg.wait_for_timeout(800)   # decode + paint of the blurred thumbs
            pg.screenshot(path=str(out / f"desktop-personalized-demoRemove1-{pid}-{state}.png"))
            if state == "removed":
                txt, imgs = pg.evaluate(AFTER)
                check(f"personalized ?r=demoRemove1: {pid} after state = miraexample.com + Instagram, no leak host",
                      after_ok(pid, "miraexample", txt, imgs) and ("mira.example" in txt or pid == "google-images"), txt)
        check("personalized: no request outside the stub, no JS error", not ext and not errs, (ext, errs))
        ctx.close()
    finally:
        stub.terminate()


def play(pg, until):
    """click the page (not the <video>), Space = play: the user gesture; wait until currentTime > until (or ended)"""
    pg.mouse.click(5, 5)
    pg.keyboard.press("Space")
    pg.wait_for_function(f"() => document.querySelector('video').currentTime > {until} || document.querySelector('video').ended", timeout=10000)


def speech(b, base, out, name, cues):
    start, say = cues["say-start"], cues["say"]
    for label, query, t, until in (("start", f"name={name}", 0, start + 0.6), ("end", f"name={name}", say - 0.6, say + 0.6)):
        ctx = ctx_new(b, viewport={"width": 1440, "height": 900})
        ctx.add_init_script(SAY_STUB)
        pg = ctx.new_page()
        goto(pg, base, query, t)
        play(pg, until)
        pg.wait_for_timeout(100)
        pill = pg.evaluate("() => { const e = document.querySelector('.vo-for'); return [e.hasAttribute('data-off'), e.innerText.replace(/\\s+/g, ' ').trim()]; }")
        pg.screenshot(path=str(out / f"desktop-named-say-{label}-{name}.png"))
        pg.wait_for_timeout(400)
        said, vol = pg.evaluate("() => [__said, document.querySelector('video').volume]")
        at = start if label == "start" else say
        check(f"speech ?name={name} ({label}, data-cue-say{'-start' if label == 'start' else ''}={at}): spoken once with the name, rate 0.95, en, ducked to 0.25 then restored",
              len(said) == 1 and said[0][0] == name and at <= said[0][1] < at + 0.5 and said[0][2] == 0.25 and abs(said[0][3] - 0.95) < 1e-6
              and said[0][4] == "en" and vol == 1, (said, vol))
        check(f"speech ?name={name} ({label}): 'for {name}' pill on screen", not pill[0] and pill[1].endswith(f"for {name}"), pill)
        ctx.close()
    # generic: never spoken, no pill, the end card instead
    ctx = ctx_new(b, viewport={"width": 1440, "height": 900})
    ctx.add_init_script(SAY_STUB)
    pg = ctx.new_page()
    goto(pg, base, "", say - 0.6)
    play(pg, say + 0.6)
    got = pg.evaluate("() => [__said, document.querySelector('.vo-for').hasAttribute('data-off'), (document.querySelector('.vo-cta')?.hasAttribute('data-off') ?? 'missing')]")
    check("speech, generic (no ?name, no scan): never spoken, no pill, end card shown", got == [[], True, False], got)
    ctx.close()
    # data-cue-say past the end of the take (declared: moved to 99): the video's `ended` brings the name / the end card
    for query in (f"name={name}", ""):
        ctx = ctx_new(b, viewport={"width": 1440, "height": 900})
        ctx.add_init_script(SAY_STUB)
        pg = ctx.new_page()
        goto(pg, base, query, 43.2)
        pg.evaluate("() => document.querySelector('.vo-stage').setAttribute('data-cue-say', '99')")
        play(pg, 99)
        pg.wait_for_timeout(300)
        got = pg.evaluate("() => [__said.map(s => s[0]), document.querySelector('.vo-for').hasAttribute('data-off'), (document.querySelector('.vo-cta')?.hasAttribute('data-off') ?? 'missing')]")
        want = [[name], False, True] if query else [[], True, False]
        check(f"ended before data-cue-say ({'named' if query else 'generic'}): {'name spoken + pill' if query else 'end card'} at the end", got == want, got)
        ctx.close()


def sfx(b, base, cues):
    g = cues["google"]
    for label, query, t, until, want in (("pop at live", "", g[0] - 0.4, g[0] + 0.3, [["osc", g[0]]]),
                                         ("whoosh + thud at removed", "", g[1] - 0.3, g[1] + 0.4, [["noise", g[1]], ["osc", g[1]]]),
                                         ("?sfx=0: silent", "sfx=0", g[1] - 0.3, g[1] + 0.4, [])):
        ctx = ctx_new(b, viewport={"width": 1440, "height": 900})
        ctx.add_init_script(SFX_STUB)
        pg = ctx.new_page()
        goto(pg, base, query, t)
        before = pg.evaluate("() => [__actx, __sfx.length]")
        play(pg, until)
        pg.keyboard.press("Space")
        got, n = pg.evaluate("() => [__sfx, __actx]")
        ok = before == [0, 0] and len(got) == len(want) and all(k == w[0] and w[1] <= v < w[1] + 0.2 for (k, v), w in zip(got, want))
        check(f"sfx: {label} (no AudioContext before the play gesture; logged {got}, {n} context)", ok and n == (0 if not want else 1), (before, got, n))
        ctx.close()


def named_take(b, base, name, cues, shift):
    """jack-named.mp4 = jack.mp4's bytes via a route (declared): it must play and shift every cue by data-cue-named-shift"""
    ctx = ctx_new(b, viewport={"width": 1440, "height": 900})
    ctx.route("**/video/jack-named.mp4", lambda r: r.continue_(url=r.request.url.replace("jack-named.mp4", "jack.mp4")))
    pg = ctx.new_page()
    g = cues["google"]
    for t, want in ((round(g[0] + 0.8, 2), []), (round(g[2] + 0.9, 2), ["google"])):   # jack.mp4 time: google on / gone
        pg.goto(f"{base}video/?name={name}&t={t:g}")
        pg.wait_for_function("() => (document.querySelector('video').currentSrc || '').endsWith('/jack-named.mp4')", timeout=8000)
        pg.wait_for_function(SEEKED, arg=t, timeout=15000)
        pg.wait_for_timeout(300)
        vis = [s[0] for s in pg.evaluate(VISIBLE)]
        check(f"named take: jack-named.mp4 plays, cues + {shift} s: at {t:g} visible {want}", vis == want and pg.evaluate("() => document.querySelector('.vo').dataset.voTake") == "named", vis)
    ctx.close()


def cta_steps(pg, base, out, cta, name_q):
    """the generic end card's 3-step loop, on the 1920x1080 page (pg)"""
    goto(pg, base, "", round(cta + 0.9, 2))
    s = pg.evaluate(STEPS)
    check("cta-steps: cta + 0.9 = step 1, the name typing (a proper prefix of the demo name)",
          s and s["so"][0] > .9 and s["so"][1] == 0 and 0 < len(s["typed"]) < len(DEMO) and DEMO.startswith(s["typed"]), s)
    goto(pg, base, "", round(cta + 2.2, 2))
    s = pg.evaluate(STEPS)
    check(f"cta-steps: cta + 2.2 = step 1, typed in full ({DEMO!r})", s and s["so"][0] > .9 and s["typed"] == DEMO, s)
    goto(pg, base, "", round(cta + 3.3, 2))
    f = out / "frame-1920-generic-cta-steps-step2.png"
    pg.locator(".vo-stage").screenshot(path=str(f))
    s = pg.evaluate(STEPS)
    n = re.fullmatch(r"(\d+) leaks found", s["count"]) if s else None
    check(f"cta-steps: cta + 3.3 = step 2 mid-scan (bar 10-90 %, 'N leaks found' rolling to 37), steps 1 / 3 off -> {f.name}",
          s and s["so"] == [0, 1, 0] and .1 < s["bar"] < .9 and n and 0 < int(n[1]) < 37, s)
    # past the end: the post-roll clock keeps the loop going (the real take ends ~2 s after the cue)
    pg.goto(f"{base}video/?t=43.4")
    pg.wait_for_function(SEEKED, arg=43.4, timeout=15000)
    play(pg, 43.9)
    pg.wait_for_function("() => document.querySelector('video').ended", timeout=8000)
    try:
        pg.wait_for_function("() => { const s = document.querySelectorAll('.vo-step'); return s.length === 3 && +getComputedStyle(s[2]).opacity > .9"
                             " && document.querySelector('.vo-mini-n').textContent !== 'Your name'"
                             " && document.querySelector('.vo-steps').style.getPropertyValue('--fp') === '1.000'; }", timeout=9000)
    except Exception:
        pass
    f = out / "frame-1920-generic-cta-steps-step3-postroll.png"
    pg.locator(".vo-stage").screenshot(path=str(f))
    s = pg.evaluate(STEPS)
    check(f"cta-steps: after the video ends it keeps looping: step 3, the mini page flipped to {DEMO!r} -> {f.name}",
          s and s["so"][2] > .9 and s["mini"] == DEMO and pg.evaluate("() => document.querySelector('video').ended"), s)
    for t in (round(cta + 0.9, 2), round(cta + 3.3, 2)):
        goto(pg, base, name_q, t)
        s = pg.evaluate(STEPS)
        check(f"cta-steps: named mode never shows it (t={t:g})", s and s["off"] and pg.evaluate("() => document.documentElement.dataset.voMode") == "named", s)


def player(b, base, out, cues):
    """phone merged layout, tap-to-play + hint, iPhone theater, desktop full screen"""
    g = cues["google"]
    t = round(g[0] + 1.3, 2)
    near = lambda a, b, tol=2: abs(a - b) <= tol
    ctx = ctx_new(b, **VIEWPORTS["phone"])
    pg = ctx.new_page()
    goto(pg, base, "", t)
    pg.screenshot(path=str(out / "proof-phone-portrait-generic-google-live.png"))
    st, ov, card, tr, full, _, ctl = pg.evaluate(GEOM)
    check("player: phone portrait: stage 16:9 full width, .vo-over = its right half, the card inside it (not below) -> proof-phone-portrait-generic-google-live.png",
          near(st[2], 390) and near(st[3], 390 * 9 / 16) and near(ov[0], st[0] + st[2] / 2) and near(ov[1], st[1]) and near(ov[3], st[3])
          and card and card[0] >= ov[0] - 1 and card[1] >= st[1] - 1 and card[1] + card[3] <= st[1] + st[3] + 1, (st, ov, card))
    vis = pg.evaluate("() => [document.documentElement.hasAttribute('data-vo-touch'), getComputedStyle(document.querySelector('.vo-ctl')).display, getComputedStyle(document.querySelector('.vo-fs')).display]")
    check("player: phone = touch: native controls off, own play bar + Rotate button shown", ctl is False and vis == [True, "flex", "flex"], (ctl, vis))
    pg.locator(".vo-stage").tap(position={"x": 97, "y": 140})
    pg.wait_for_function("() => !document.querySelector('video').paused", timeout=5000)
    pg.wait_for_timeout(400)
    pg.screenshot(path=str(out / "phone-generic-tap-played-hint.png"))
    h = pg.evaluate("() => { const e = document.querySelector('.vo-hint'); return [getComputedStyle(e).display, e.textContent, document.documentElement.hasAttribute('data-vo-playing')]; }")
    check("player: phone: a tap on the stage plays, 'Rotate for full size' hint shown", h == ["block", "Rotate for full size", True], h)
    ctx.close()
    # iPhone Safari: no element full screen → theater (declared: the Fullscreen API removed by an init script)
    ctx = ctx_new(b, **VIEWPORTS["phone"])
    ctx.add_init_script(IPHONE_FS)
    pg = ctx.new_page()
    goto(pg, base, "", t)
    n0 = pg.evaluate("history.length")

    def open_theater():
        pg.locator(".vo-fs").tap()
        pg.wait_for_function("() => document.documentElement.dataset.voFull === 'theater'", timeout=3000)
        pg.wait_for_timeout(300)
    open_theater()
    pg.screenshot(path=str(out / "proof-phone-theater-generic-google-live.png"))
    st, ov, card, tr, full, ovf, ctl = pg.evaluate(GEOM)
    m = [float(x) for x in re.findall(r"-?[\d.e]+", tr)[:4]]
    rotated = len(m) == 4 and near(m[0], 0, .01) and near(m[1], 1, .01) and near(m[2], -1, .01) and near(m[3], 0, .01)
    # rotated 90deg clockwise: the stage's right half = the lower half of the screen box
    check("player: iPhone theater: stage rotated 90deg, filling the 390 px width (693 px tall), scroll locked, no native controls, "
          "card in its right half (= the lower half) -> proof-phone-theater-generic-google-live.png",
          rotated and near(st[2], 390) and near(st[3], 390 * 16 / 9, 3) and ovf == "hidden" and ctl is False
          and card and card[1] >= st[1] + st[3] / 2 - 1 and card[1] + card[3] <= st[1] + st[3] + 1 and card[0] >= st[0] - 1, (tr, st, card, ovf, ctl))
    pg.keyboard.press("Escape")
    closed = lambda: pg.evaluate("() => !document.documentElement.dataset.voFull && getComputedStyle(document.documentElement).overflow !== 'hidden'")
    pg.wait_for_timeout(300)
    c1 = closed()
    open_theater()
    pg.evaluate("history.back()")
    pg.wait_for_timeout(500)
    c2 = closed()
    open_theater()
    pg.locator(".vo-fs").tap()
    pg.wait_for_timeout(500)
    c3 = closed() and pg.evaluate("history.length") == n0 + 1 and pg.url.endswith(f"t={t:g}")
    check("player: iPhone theater closes on Esc / back / the X (scroll unlocked, page stays)", c1 and c2 and c3, (c1, c2, c3, pg.url))
    ctx.close()
    # desktop: the STAGE goes full screen (cards stay), on the right half of the centred 16:9 picture
    ctx = ctx_new(b, **VIEWPORTS["desktop"])
    pg = ctx.new_page()
    goto(pg, base, "", t)
    pg.locator(".vo-fs").click()
    try:
        pg.wait_for_function("() => document.fullscreenElement === document.querySelector('.vo-stage')", timeout=4000)
    except Exception:
        pass
    pg.wait_for_timeout(500)
    pg.screenshot(path=str(out / "desktop-fullscreen-generic-google-live.png"))
    st, ov, card, tr, full, _, ctl = pg.evaluate(GEOM)
    vw, vh = pg.evaluate("() => [innerWidth, innerHeight]")
    pw = min(vw, vh * 16 / 9)
    check("player: desktop full screen = the stage (data-vo-full=fs); .vo-over = the right half of the centred 16:9 picture, card inside, native controls kept",
          full == "fs" and near(ov[0], (vw + pw) / 2 - pw / 2) and near(ov[2], pw / 2) and near(ov[3], pw * 9 / 16) and near(ov[1], (vh - pw * 9 / 16) / 2)
          and card and card[0] >= ov[0] and card[0] + card[2] <= ov[0] + ov[2] + 1 and ctl is True, (full, [vw, vh], ov, card, ctl))
    pg.locator(".vo-fs").click()
    pg.wait_for_timeout(400)
    check("player: desktop: the X leaves full screen", pg.evaluate("() => !document.fullscreenElement && !document.documentElement.dataset.voFull"))
    ctx.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--name", default="Tessa")
    ap.add_argument("--break-thumbs", action="store_true")
    ap.add_argument("--break-steps", action="store_true")
    a = ap.parse_args()
    out = pathlib.Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    html = (ROOT / "site/video/index.html").read_text(encoding="utf-8")
    if a.break_steps:   # wire boundary: index.html minus the cta-steps animation (the end card + form stay)
        broken, k = re.subn(r'\n        <div class="vo-steps".*?\n        </div>\n(?=        <p class="vo-dots")', "\n", html, flags=re.S)
        assert k == 1, "break: .vo-steps block not found"
        BREAK["steps"] = (lambda u: urllib.parse.urlsplit(u).path.endswith("/video/"), broken, "text/html")
    pf = [(m[1], float(m[2]), float(m[3]), float(m[4])) for m in re.finditer(
        r'data-prefab="([\w-]+)" data-cue-live="([\d.]+)" data-cue-removed="([\d.]+)" data-cue-out="([\d.]+)"', html)]
    tap = re.search(r'data-prefab="google-images"[^>]*data-cue-tap="([\d.]+)"', html)
    cues = {p[0]: p[1:] for p in pf}
    cues["say-start"], cues["say"] = stage_attr(html, "data-cue-say-start"), stage_attr(html, "data-cue-say")
    cta = stage_attr(html, "data-cue-cta") or cues["say"]
    shift = stage_attr(html, "data-cue-named-shift") or 0
    name_q = "name=" + urllib.parse.quote(a.name)
    with serve() as base, sync_playwright() as p:
        b = p.chromium.launch()
        for mode, query, who in (("generic", "", GENERIC), ("named", name_q, a.name)):
            for vp, opts in VIEWPORTS.items():
                ctx = ctx_new(b, **opts)
                seen = []
                ext = guard(ctx, (base,), seen)
                pg = ctx.new_page()
                errs = []
                console(pg, errs)
                for pid, live, rem, off in pf:
                    tl = round(live + min(1.3, rem - live - 0.1), 2)
                    if pid == "google-images":   # after the tap + grid
                        tl = round(min(rem - 0.1, max(tl, (float(tap[1]) if tap else live + 0.6) + 1.0)), 2)
                    for state, t in (("live", tl), ("removed", min(rem + 2.0, off - 0.45))):
                        goto(pg, base, query, t)
                        shot = out / f"{vp}-{mode}-t{t:05.2f}-{pid}-{state}.png"
                        if vp == "phone":
                            pg.locator(".vo-stage").screenshot(path=str(shot))
                        else:
                            pg.screenshot(path=str(shot))
                        st = pg.evaluate(VISIBLE)
                        vis = [s[0] for s in st]
                        ok = vis == [pid] and float(st[0][1]) == (100 if state == "live" else 0) and who in st[0][2]
                        box = [round(x, 3) for x in st[0][3]] if st else None
                        corner = (box and box[0] >= .5 and box[1] >= 0 and box[2] <= 1 and box[3] <= 1
                                                   and abs((box[1] + box[3]) / 2 - .5) <= .05)
                        print(f"{vp} {mode} t={t:g} {pid} {state}: visible={vis} p={[s[1] for s in st]} box={box} rolls={st[0][4] if st else None} -> {shot.name}")
                        if not ok:
                            check(f"{vp} {mode} t={t:g}: only {pid} {state} with {who!r}", False, [(s[0], s[1]) for s in st])
                        if not corner:
                            check(f"{vp} {mode} t={t:g}: {pid} on the right half, vertically centred (left >= .5, centre .5 +- .05)", False, box)
                        if (pid, state) in COUNT and st and COUNT[(pid, state)] not in st[0][4]:
                            check(f"{vp} {mode} t={t:g}: {pid} {state} counter reads {COUNT[(pid, state)]!r}", False, st[0][4])
                        if state == "removed" and pid in ("google", "google-images"):
                            txt, imgs = pg.evaluate(AFTER)
                            check(f"{vp} {mode} t={t:g}: {pid} after state = {who}'s site + Instagram"
                                  + (", >= 4 unblurred own photos" if pid == "google-images" else "") + ", no leak host",
                                  after_ok(pid, who, txt, imgs), (txt[:160], imgs[:2]))
                # the end card / pill
                t = round(cta + 0.6, 2)
                goto(pg, base, query, t)
                shot = out / f"{vp}-{mode}-t{t:05.2f}-end.png"
                (pg.locator(".vo-stage") if vp == "phone" else pg).screenshot(path=str(shot))
                st = pg.evaluate(VISIBLE)
                got = [(s[0], s[2].strip()) for s in st]
                want = "cta-steps" if mode == "generic" else "vo-pf vo-for"
                ok = len(st) == 1 and st[0][0] == want and (CTA_TEXT in st[0][2] if mode == "generic" else re.sub(r"\s", "", st[0][2]).endswith("for" + re.sub(r"\s", "", a.name)))
                if st:   # both widths: the right half
                    box = st[0][3]
                    ok = ok and box[0] >= .5 and box[2] <= 1 and abs((box[1] + box[3]) / 2 - .5) <= .05
                check(f"{vp} {mode} t={t:g}: end = {'the Type-your-name card + form' if mode == 'generic' else f'the for {a.name} pill, no card'}, right half -> {shot.name}", ok, got)
                mode_attr = pg.evaluate("() => document.documentElement.dataset.voMode")
                check(f"{vp} {mode}: html[data-vo-mode={mode}]", mode_attr == mode, mode_attr)
                check(f"{vp} {mode}: no console errors", not errs, errs)
                check(f"{vp} {mode}: no requests outside the local server", not ext, sorted(set(ext)))
                if mode == "generic":
                    check(f"{vp} generic: never asks for jack-named.mp4", not any("jack-named" in u for u in seen))
                if vp == "desktop" and mode == "named":   # defaults stay for ?name= (no scan photos without a scan)
                    im = pg.evaluate(IMGS)
                    check(f"?name={a.name}: all {len(im)} .rm-img keep the default photos (img/removals), blurred",
                          len(im) == 13 and all(s.startswith("../img/removals/") and "blur(" in f for s, w, f in im), im[:3])
                    src = pg.evaluate("() => document.querySelector('video').currentSrc")
                    check(f"?name={a.name}: no jack-named.mp4 on the server → jack.mp4 / .webm plays", re.search(r"/jack\.(mp4|webm)$", src or "") is not None, src)
                if vp == "desktop" and mode == "generic":
                    # the form: trimmed + collapsed name → ?name=; an invalid one stays
                    if check("end card form: #vo-name present", pg.locator("#vo-name").count() == 1):
                        pg.fill("#vo-name", "<b>")
                        pg.press("#vo-name", "Enter")
                        pg.wait_for_timeout(300)
                        msg = pg.evaluate("() => document.querySelector('#vo-name').validationMessage")
                        check("end card form: invalid name '<b>' → no navigation, a message", "name=" not in pg.url and bool(msg), (pg.url, msg))
                        pg.fill("#vo-name", f"  {a.name}   Q ")
                        pg.screenshot(path=str(out / "desktop-generic-end-form-typed.png"))
                        with pg.expect_navigation():
                            pg.press("#vo-name", "Enter")
                        pg.wait_for_function("() => document.documentElement.dataset.voMode === 'named'", timeout=8000)
                        nm = pg.evaluate("() => document.querySelector('[data-vo=name]').textContent")
                        check(f"end card form: '{a.name} Q' → ?name={urllib.parse.quote(a.name + ' Q')}, named mode, texts", pg.url.endswith(f"/video/?name={urllib.parse.quote(a.name + ' Q')}") and nm == f"{a.name} Q", (pg.url, nm))
                        pg.screenshot(path=str(out / "desktop-generic-end-form-submitted.png"))
                    # the snap: word cards, shake, flash
                    g = cues["google"]
                    goto(pg, base, "", round(g[0] + 0.25, 2))
                    fx = pg.evaluate(FX, "google")
                    check(f"word card at google live + 0.25: 'GOOGLE' popped", fx[2][0] == "GOOGLE" and fx[2][1] > .9, fx[2])
                    goto(pg, base, "", round(g[1] + 0.08, 2))
                    pg.screenshot(path=str(out / "desktop-generic-snap-google.png"))
                    fx = pg.evaluate(FX, "google")
                    check("snap at google removed + 0.08: 'GONE.' card, shake offset, flash on", fx[3][0] == "GONE." and fx[3][1] > .9 and abs(fx[0]) > 1 and fx[1] > .2 and fx[5] == "block", fx[:6])
                ctx.close()
        # reduced motion: plain fades
        ctx = ctx_new(b, viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
        pg = ctx.new_page()
        g, m = cues["google"], cues["mega"]
        goto(pg, base, "", round(g[1] + 0.08, 2))
        pg.screenshot(path=str(out / "desktop-generic-reduced-snap-google.png"))
        fx = pg.evaluate(FX, "google")
        tr = re.findall(r"-?[\d.]+", fx[4])
        plain = len(tr) == 6 and tr[:4] == ["1", "0", "0", "1"] and abs(float(tr[4]) + fx[10] / 2) < 1 and abs(float(tr[5]) + fx[11] / 2) < 1
        check("reduced motion, snap: no shake / scale (plain translate(-50%, -50%)), no flash", plain and fx[5] == "none", (fx[4], fx[5]))
        goto(pg, base, "", round(m[1] + 0.25 + 0.475, 2))
        fx = pg.evaluate(FX, "mega")
        check("reduced motion, mid-wipe: after layer fades (opacity ~0.5, no clip-path)", 0.2 < fx[9][0] < 0.8 and fx[9][1] == "none", fx[9])
        goto(pg, base, "", round(m[1] + 1.6, 2))
        fx = pg.evaluate(FX, "mega")
        check("reduced motion, stamp: no particles (burst display none), stamp unscaled", fx[6] == "none" and fx[7] == 1, (fx[6], fx[7]))
        ctx.close()
        player(b, base, out, cues)
        # the framing proofs: the whole 1920x1080 frame
        ctx = ctx_new(b, viewport={"width": 1920, "height": 1080})
        pg = ctx.new_page()
        for mode, pid, t in (("generic", "google", cues["google"][0] + 1), ("named", "mega", cues["mega"][1] + 1.6), ("generic", "cta", cta + 0.6)):
            goto(pg, base, name_q if mode == "named" else "", round(t, 2))
            f = out / f"frame-1920-{mode}-{pid}-{'live' if pid == 'google' else 'removed' if pid == 'mega' else 'card'}.png"
            pg.locator(".vo-stage").screenshot(path=str(f))
            print(f"framing proof t={t:g} -> {f.name}")
            if pid == "mega":
                fx = pg.evaluate(FX, "mega")
                rolls = pg.evaluate(VISIBLE)[0][4]
                check("frame mega removed (named): counter at 0, stamp on, particles flying", "0 GB · 0 videos" in rolls and fx[7] == 1 and fx[8] > .3 and fx[6] == "block", (rolls, fx[6:9]))
        cta_steps(pg, base, out, cta, name_q)
        ctx.close()
        speech(b, base, out, a.name, cues)
        sfx(b, base, cues)
        named_take(b, base, a.name, cues, shift)
        personalized(b, out, a.break_thumbs)
    for f in fails:
        print("FAIL", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

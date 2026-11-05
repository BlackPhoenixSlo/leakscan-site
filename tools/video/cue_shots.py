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
  "for NAME" pill instead; the form rebuilds in place: ?name=<trimmed> (replaceState, same document, named), an invalid name stays put with a message
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
- cta-steps (generic end card, one 10 s take in a phone replica of the landing; phases past the take's end drawn with the pure
  draw(t), declared): cta + 0.3 hero (logo loaded, the site's h1, empty onlyfans.com/ field, camera at rest), + 2.2 the
  camera zoomed onto the field (scale >= 2.2) typing a proper prefix, + 3.05 the field typed handle(DEMO) ("jakabasej")
  in full, + 3.75 "Scan now" pressed (camera pulled back), + 5.6 the scan card mid-scan (bar 10-90 %, "Searching <place>,
  step N of 9…", "@<handle>"), the places walk Google → … → Mega with N rising, + 7.4 "N links found" rolling, + 8.3
  the report ("87 links found", tabs Links 87 / Images 12 / Sites 31, 5 *.example rows, "+ 82 more"), + 9.65 the toast
  "Rewatch this video with YOUR content" + the name flipped in (frame-1920-generic-cta-<n>-<phase>.png); after the take
  ends the post-roll clock keeps it looping to the flip (frame-1920-generic-cta-flip-postroll.png); phone portrait +
  iPhone theater: every phase shot (phone-{portrait,theater}-generic-cta-<n>-<phase>.png), typed handle on screen >= 11 px
  portrait / >= 20 px theater, the toast's letters >= 11 px portrait; named mode never shows it, its "for NAME" pill stays from
  data-cue-say to the end and after the take ends (desktop-named-pill-after-end.png)
- player: phone (touch): no native controls, own play bar, a tap on the stage plays + "Rotate for full size" hint;
  proof-phone-portrait-generic-google-live.png = the whole 390x844 screen, card inside the stage's right half;
  iPhone theater (declared: Fullscreen API removed by an init script, as on iPhone Safari): the button rotates the stage
  90deg over the screen (proof-phone-theater-generic-google-live.png; the card in its right half = the screen's lower
  half), scroll locked, Esc / back / X each close it; desktop: the button puts the STAGE in full screen, the card on the
  right half of the centred 16:9 picture
--break-thumbs serves video-overlays.js without the thumb src assignment: only the thumbs check goes red.
- name bar + in-place swap (phone 390x844, desktop 1440x900, frame 1920x1156 = a 1920x1080 stage + the bar), speech stubbed
  (declared): generic at 0 s the bar sits under the stage, in view, with the pulsing "type your name" pill (gone after the
  first focus); an invalid name is rejected inline (message, URL unchanged); phone: in theater (declared: Fullscreen API
  removed, as iPhone) the "Your name" pill closes it and focuses the input; played past 2.4 s, SWAP_NAME + Enter →
  at once (no rebuild card: no .vo-rb in the page, no pause event): ?name=<encoded> (replaceState, same document), named
  mode, within 1 s playing from < 1 s ({vp}-swap-settled.png); spoken with SWAP_NAME at data-cue-say-start (desktop: and at data-cue-say), "for" pill; google at its live cue
  shows SWAP_NAME; cta-steps never shown (MutationObserver); Change re-opens the input prefilled; Reset → generic, URL
  without query, restarted, end card back. Proof PNGs: frame-1920-swap-bar-generic-0s.png (page), frame-1920-swap-settled.png,
  frame-1920-swap-google-live.png (1920x1080 stage).
- full frame (1920x1080, 1280x800, phone 390x844, iPhone theater, desktop full screen): the <video> box == the stage box,
  the drawn picture (object-fit + videoWidth / Height) covers the whole stage (full screen: the centred 16:9 picture, the
  overlay = its right half); .vo-over / .vo-box = the stage's right half, transparent (no background, no shadow: the
  cards are drawn straight on the video); at a card-free time (3 s) the screen's right half = the video frame's right half
  (screenshot, native controls off (declared), vs drawImage(video), 8x8 grid, every cell |diff| < 8) -> full-frame-<vp>.png
--break-full serves css/video.css with the old split layout appended (the video in the left half, an opaque panel behind
  the cards): only the "full frame:" checks go red.
--break-thumbs serves video-overlays.js without the thumb src assignment: only the thumbs check goes red.
--break-steps serves index.html without the cta-steps phone (.vo-steps): only the "cta-steps:" checks go red.
--break-swap serves video-overlays.js with the submit's rebuild(n) call removed: only the "swap:" checks go red.
--break-demo serves video-overlays.js with the old demo name (DEMO = 'Orla Brennick'): only the "cta-steps: typed … DEMO" check goes red.
Usage: cd ~/leakhunt && uv run python ~/leakscan-site/tools/video/cue_shots.py OUT_DIR [--name Tessa] [--break-thumbs] [--break-steps] [--break-swap] [--break-demo] [--break-full]
Prints one line per shot / check + 'FAIL …' lines; exit 1 on any failure."""
import argparse, pathlib, re, socket, subprocess, sys, time, urllib.parse
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
# cta-steps state (null without the phone): scene opacities, camera scales (--cz per scene page), hero, typed handle + its
# on-screen px (font x --k x camera), scan line, report, the end toast (+ its smallest on-screen px) and the flipped name
STEPS = """() => { const c = document.querySelector('.vo-cta'), s = c && c.querySelector('.vo-steps'); if (!s) return null;
  const q = x => s.querySelector(x), mi = q('.vo-mi-t'), k = +document.querySelector('.vo-box').style.getPropertyValue('--k'), logo = q('.vo-hd img'),
        cz = [...s.querySelectorAll('.vo-pg')].map(e => +e.style.getPropertyValue('--cz')), fs = e => parseFloat(getComputedStyle(e).fontSize), sp = x => x.replace(/\\s+/g, ' ').trim();
  return {off: c.hasAttribute('data-off'), so: [...s.querySelectorAll('.vo-step')].map(e => +getComputedStyle(e).opacity), cz,
          h1: sp(q('.vo-h1').textContent), logo: logo.complete && logo.naturalWidth > 0, typed: mi.textContent, px: +(fs(mi) * k * cz[0]).toFixed(1),
          btn: q('.vo-mbtn').textContent.trim(), press: +s.style.getPropertyValue('--press'), ms: q('.vo-ms').textContent, bar: +s.style.getPropertyValue('--bar'),
          at: q('.vo-sc-scan .vo-at').textContent, count: sp(q('.vo-mc').textContent), tabs: [...s.querySelectorAll('.vo-tabs2 > span')].map(e => sp(e.textContent)),
          rows: [...s.querySelectorAll('.vo-dom')].map(e => e.textContent), more: q('.vo-more').textContent, end: sp(q('.vo-end-h').textContent),
          eo: +getComputedStyle(q('.vo-end')).opacity, endpx: +(Math.min(fs(q('.vo-end-h')), fs(q('.vo-end-f'))) * k).toFixed(1), mini: q('.vo-mini-n').textContent}; }"""
DEMO, LEAKS = "Jaka Basej", 87
HERO_H1 = "Leaked content, taken down by a real person. Me."
handle = lambda n: re.sub(r"[^\w.]", "", n.lower()) or "creator"   # = js handle(): "Jaka Basej" → "jakabasej"
# the phases (s into the loop) shot on every viewport
PHASES = (("1-hero", 0.3), ("2-zoom", 1.6), ("3-typed", 3.05), ("4-press", 3.75), ("5-scanning", 5.6), ("6-report", 8.3), ("7-flip", 9.65))
DRAW = "t => { document.querySelector('video').pause(); window.VideoOverlays.draw(t); }"
PROGRESS = re.compile(r"Searching (Google|Google Images|X|Reddit|Mega), step ([1-9]) of 9…")
# [stage rect, .vo-over rect, visible card rect, stage transform, data-vo-full, html overflow, video.controls]
GEOM = """() => { const r = e => { const b = e.getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; }, st = document.querySelector('.vo-stage'),
  card = [...document.querySelectorAll('.vo-pf')].find(e => !e.hasAttribute('data-off'));
  return [r(st), r(document.querySelector('.vo-over')), card ? r(card.querySelector('.vo-phone, .vo-panel, .vo-steps') || card) : null, getComputedStyle(st).transform,
          document.documentElement.dataset.voFull || null, getComputedStyle(document.documentElement).overflow, document.querySelector('video').controls]; }"""
IPHONE_FS = ("Object.defineProperty(Document.prototype, 'fullscreenEnabled', { get: () => false });"
             "Element.prototype.requestFullscreen = undefined; Element.prototype.webkitRequestFullscreen = undefined;")
SWAP_NAME = "Jaka Basej"
SWAP_VIEWPORTS = {"phone": VIEWPORTS["phone"], "desktop": VIEWPORTS["desktop"], "frame-1920": dict(viewport={"width": 1920, "height": 1156})}
# [stage rect, bar rect, input rect, button rect, hint [display, rect, animation], innerHeight, video.currentTime]
BAR = """() => { const r = e => { const b = e.getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; }, h = document.querySelector('.vo-nb-hint'), hs = getComputedStyle(h);
  return [r(document.querySelector('.vo-stage')), r(document.querySelector('.vo-nb')), r(document.querySelector('#vo-nb-in')), r(document.querySelector('.vo-nb-f button')),
          [hs.display, r(h), hs.animationName], innerHeight, document.querySelector('video').currentTime]; }"""
CTA_WATCH = """() => { window.__ctaSeen = false; const c = document.querySelector('.vo-cta');
  new MutationObserver(() => { if (!c.hasAttribute('data-off')) __ctaSeen = true; }).observe(c, { attributes: true }); }"""
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
    """the generic end card's 10 s take, on the 1920x1080 page (pg); returns the handle the hero typed in full"""
    shot = lambda ph: pg.locator(".vo-stage").screenshot(path=str(out / f"frame-1920-generic-cta-{ph}.png"))
    goto(pg, base, "", round(cta + 0.3, 2))
    shot("1-hero")
    s = pg.evaluate(STEPS)
    check("cta-steps: cta + 0.3 = the hero in the phone (logo, the site's h1, empty field, camera at rest) -> frame-1920-generic-cta-1-hero.png",
          s and s["so"][0] > .9 and s["so"][1:] == [0, 0] and s["h1"] == HERO_H1 and s["logo"] and s["typed"] == "" and s["cz"][0] < 1, s)
    goto(pg, base, "", round(cta + 3.05, 2))
    shot("3-typed")
    s = pg.evaluate(STEPS)
    full = s["typed"] if s else ""
    check(f"cta-steps: typed at cta + 3.05: the onlyfans.com/ field holds handle(DEMO) {handle(DEMO)!r} in full, camera zoomed on it -> frame-1920-generic-cta-3-typed.png",
          s and s["so"][0] > .9 and s["typed"] == handle(DEMO) and s["cz"][0] >= 2.2, s)
    goto(pg, base, "", round(cta + 2.2, 2))
    s0 = pg.evaluate(STEPS)
    check("cta-steps: cta + 2.2 = the camera zoomed onto the field (scale >= 2.2), typing a proper prefix of the handle",
          s0 and s0["so"][0] > .9 and s0["cz"][0] >= 2.2 and 0 < len(s0["typed"]) < len(full) and full.startswith(s0["typed"]), (s0, full))
    ph = dict(PHASES)
    for name in ("2-zoom", "4-press", "5-scanning", "6-report", "7-flip"):   # past the take's end: the pure draw(t) (declared)
        pg.evaluate(DRAW, cta + ph[name])
        shot(name)
        s = pg.evaluate(STEPS)
        if name == "4-press":
            check("cta-steps: cta + 3.75 'Scan now' pressed, the camera pulled back to the form -> frame-1920-generic-cta-4-press.png",
                  s and s["so"][0] > .9 and s["btn"] == "Scan now" and s["press"] > .5 and s["cz"][0] < 1.2, s)
        if name == "5-scanning":
            check(f"cta-steps: cta + 5.6 = the scan card (hero / report off): '@{full}', bar 10-90 %, 'Searching <place>, step N of 9…' -> frame-1920-generic-cta-5-scanning.png",
                  s and s["so"] == [0, 1, 0] and s["at"] == "@" + full and .1 < s["bar"] < .9 and PROGRESS.fullmatch(s["ms"] or ""), s)
        if name == "6-report":
            check(f"cta-steps: cta + 8.3 = the report: '{LEAKS} links found', tabs Links 87 / Images 12 / Sites 31, 5 *.example rows, '+ 82 more' -> frame-1920-generic-cta-6-report.png",
                  s and s["so"][2] > .9 and s["so"][:2] == [0, 0] and s["count"] == f"{LEAKS} links found" and s["tabs"] == ["Links 87", "Images 12", "Sites 31"]
                  and len(s["rows"]) == 5 and all(r.endswith(".example") for r in s["rows"]) and s["more"] == "+ 82 more in the full report", s)
        if name == "7-flip":
            check(f"cta-steps: cta + 9.65 = 'Rewatch this video with YOUR content' + the name flipped in (its handle = {full!r}) -> frame-1920-generic-cta-7-flip.png",
                  s and s["so"][2] > .9 and s["eo"] > .9 and s["end"] == "Rewatch this video with YOUR content" and s["mini"] != GENERIC and handle(s["mini"]) == full, s)
    walk = []
    for dt in (4.5, 5.0, 5.5, 6.0, 6.4, 7.4):
        pg.evaluate(DRAW, cta + dt)
        s = pg.evaluate(STEPS)
        walk.append((s["ms"], s["count"]))
    m = [PROGRESS.fullmatch(w[0] or "") for w in walk[:-1]]
    roll = re.fullmatch(r"(\d+) links found", walk[-1][1])
    check(f"cta-steps: the scan walks Google → … → Mega, step N rising; at + 7.4 'N links found' rolling to {LEAKS}",
          all(m) and len({x[1] for x in m}) >= 4 and m[0][1] == "Google" and m[-1][1] == "Mega" and [int(x[2]) for x in m] == sorted(int(x[2]) for x in m)
          and roll and 0 < int(roll[1]) < LEAKS, walk)
    # past the end: the post-roll clock keeps the loop going (the real take ends ~3.5 s after the cue)
    pg.goto(f"{base}video/?t=43.4")
    pg.wait_for_function(SEEKED, arg=43.4, timeout=15000)
    play(pg, 43.9)
    pg.wait_for_function("() => document.querySelector('video').ended", timeout=8000)
    try:
        pg.wait_for_function("() => { const s = document.querySelectorAll('.vo-step'); return s.length === 3 && +getComputedStyle(s[2]).opacity > .9"
                             " && document.querySelector('.vo-mini-n').textContent !== 'Your name'"
                             " && document.querySelector('.vo-steps').style.getPropertyValue('--fp') === '1.000'; }", timeout=12000)
    except Exception:
        pass
    f = out / "frame-1920-generic-cta-flip-postroll.png"
    pg.locator(".vo-stage").screenshot(path=str(f))
    s = pg.evaluate(STEPS)
    check(f"cta-steps: after the video ends it keeps looping to the end: the toast + the name flipped in (handle {full!r}) -> {f.name}",
          s and full and s["so"][2] > .9 and s["eo"] > .5 and handle(s["mini"]) == full and pg.evaluate("() => document.querySelector('video').ended"), s)
    for t in (round(cta + 0.9, 2), round(cta + 3.05, 2)):
        goto(pg, base, name_q, t)
        s = pg.evaluate(STEPS)
        check(f"cta-steps: named mode never shows it (t={t:g})", s and s["off"] and pg.evaluate("() => document.documentElement.dataset.voMode") == "named", s)
    # named: the name stays on screen at the end (the "for NAME" pill from data-cue-say on, also after the take ends)
    nm = urllib.parse.unquote(name_q.split("=", 1)[1])
    goto(pg, base, name_q, round(cta + 3.0, 2))
    pill = lambda: pg.evaluate("() => { const e = document.querySelector('.vo-for'); return [e.hasAttribute('data-off'), e.innerText.replace(/\\s+/g, ' ').trim(), document.querySelector('video').ended]; }")
    p1 = pill()
    pg.goto(f"{base}video/?{name_q}&t=43.4")
    pg.wait_for_function(SEEKED, arg=43.4, timeout=15000)
    play(pg, 43.9)
    pg.wait_for_function("() => document.querySelector('video').ended", timeout=8000)
    pg.wait_for_timeout(1500)
    f = out / "desktop-named-pill-after-end.png"
    pg.locator(".vo-stage").screenshot(path=str(f))
    p2 = pill()
    check(f"named end: 'for {nm}' pill on at data-cue-say + 3 s and still 1.5 s after the take ended -> {f.name}",
          not p1[0] and p1[1].endswith(f"for {nm}") and not p2[0] and p2[1].endswith(f"for {nm}") and p2[2], (p1, p2))
    return full


def cta_phone(b, base, out, cta, full):
    """every phase on an iPhone: portrait (the stage = the top 390x219) and the rotated theater; the typed handle readable"""
    ctx = ctx_new(b, **VIEWPORTS["phone"])
    ctx.add_init_script(IPHONE_FS)
    pg = ctx.new_page()
    goto(pg, base, "", round(cta + 3.05, 2))
    for view in ("portrait", "theater"):
        if view == "theater":
            pg.locator(".vo-fs").tap()
            pg.wait_for_function("() => document.documentElement.dataset.voFull === 'theater'", timeout=3000)
            pg.wait_for_timeout(400)
        for name, u in PHASES:
            pg.evaluate(DRAW, cta + u)
            pg.screenshot(path=str(out / f"phone-{view}-generic-cta-{name}.png"))
        pg.evaluate(DRAW, cta + 3.05)
        s = pg.evaluate(STEPS)
        lo = 11 if view == "portrait" else 20
        check(f"cta-steps (phone {view}): typed {full!r} in full, on-screen glyphs >= {lo} px" + (", the toast's >= 11 px" if view == "portrait" else "")
              + f" -> phone-{view}-generic-cta-*.png", s and full and s["so"][0] > .9 and s["typed"] == full and s["px"] >= lo
              and (view == "theater" or s["endpx"] >= 11), s)
    ctx.close()


def swap(b, base, out, cues, cta, vp, opts):
    """the name bar: generic → SWAP_NAME in place (no reload), Change, Reset; vp = phone | desktop | frame-1920"""
    want_q = "?name=" + urllib.parse.quote(SWAP_NAME)
    ctx = ctx_new(b, **opts)
    ctx.add_init_script(SAY_STUB)
    if vp == "phone":
        ctx.add_init_script(IPHONE_FS)
    seen = []
    ext = guard(ctx, (base,), seen)
    pg = ctx.new_page()
    errs = []
    console(pg, errs)
    pg.goto(f"{base}video/")
    pg.wait_for_function("() => document.querySelector('video').readyState >= 3", timeout=15000)
    pg.wait_for_timeout(1200)
    pg.screenshot(path=str(out / f"{vp}-swap-bar-generic-0s.png"))
    st, bar, inp, btn, hint, vh, t = pg.evaluate(BAR)
    check(f"bar ({vp}): generic at {t:g} s: the name bar right under the stage, full width, input + button in view -> {vp}-swap-bar-generic-0s.png",
          t == 0 and abs(bar[1] - (st[1] + st[3])) <= 1 and abs(bar[2] - st[2]) <= 1 and bar[1] + bar[3] <= vh + 1
          and all(r[3] > 20 and r[1] + r[3] <= vh + 1 for r in (inp, btn)), (st, bar, inp, btn, vh, t))
    check(f"bar ({vp}): the pulsing '👇 type your name' pill on the input, in view", hint[0] != "none" and hint[2] == "vo-nb-pulse"
          and hint[1][3] > 0 and hint[1][1] >= st[1] + st[3] - hint[1][3] and hint[1][1] + hint[1][3] <= vh
          and pg.evaluate("() => document.querySelector('.vo-nb-hint').textContent") == "\U0001F447 type your name", hint)
    pg.fill("#vo-nb-in", "<b>")
    pg.press("#vo-nb-in", "Enter")
    pg.wait_for_timeout(300)
    bad = pg.evaluate("() => { const e = document.querySelector('.vo-nb-err'); return [e.hidden, e.textContent, document.querySelector('#vo-nb-in').getAttribute('aria-invalid'), document.documentElement.dataset.voMode, getComputedStyle(document.querySelector('.vo-nb-hint')).display]; }")
    check(f"bar ({vp}): invalid '<b>' rejected inline (message, aria-invalid), URL + mode unchanged; the hint gone after the first focus",
          not bad[0] and "1-40" in bad[1] and bad[2] == "true" and bad[3] == "generic" and bad[4] == "none" and pg.url == f"{base}video/", (bad, pg.url))
    pg.fill("#vo-nb-in", "")
    if vp == "phone":   # iPhone theater: the pill opens the bar
        pg.locator(".vo-fs").tap()
        pg.wait_for_function("() => document.documentElement.dataset.voFull === 'theater'", timeout=3000)
        pg.wait_for_timeout(300)
        pg.screenshot(path=str(out / "phone-swap-theater-pill.png"))
        pill = pg.evaluate("() => { const b = document.querySelector('.vo-nb-pill').getBoundingClientRect(); return [getComputedStyle(document.querySelector('.vo-nb-pill')).display, b.width > 0]; }")
        pg.locator(".vo-nb-pill").tap()
        pg.wait_for_timeout(500)
        got = pg.evaluate("() => [document.documentElement.dataset.voFull || null, document.activeElement && document.activeElement.id]")
        check("bar (phone): theater shows the 'Your name' pill; a tap closes the theater and focuses the bar input -> phone-swap-theater-pill.png",
              pill == ["block", True] and got == [None, "vo-nb-in"], (pill, got))
        pg.evaluate("() => document.activeElement.blur()")
    pg.evaluate(CTA_WATCH)
    play(pg, 2.4)
    before = pg.evaluate("() => document.querySelector('video').currentTime")
    pg.fill("#vo-nb-in", SWAP_NAME)
    pg.evaluate("() => { window.__same = 1; window.__said.length = 0; window.__pauses = 0; document.querySelector('video').addEventListener('pause', () => __pauses++); }")
    t0 = time.monotonic()
    pg.press("#vo-nb-in", "Enter")
    now = pg.evaluate("() => [document.querySelector('.vo-rb'), location.search, document.documentElement.dataset.voMode, document.querySelector('video').currentTime < 1]")
    check(f"swap ({vp}): Enter → at once, no rebuild card (no .vo-rb in the page): {want_q}, named mode, back at 0", now == [None, want_q, "named", True], now)
    done = False
    try:
        pg.wait_for_function("""q => { const v = document.querySelector('video'); return location.search === q && document.documentElement.dataset.voMode === 'named'
            && !v.paused && v.currentTime > 0 && v.currentTime < 1; }""", arg=want_q, timeout=1000)
        done = True
    except Exception:
        pass
    pg.wait_for_timeout(300)
    pg.locator(".vo-stage").screenshot(path=str(out / f"{vp}-swap-settled.png"))
    dt = time.monotonic() - t0
    got = pg.evaluate("() => [location.search, document.documentElement.dataset.voMode, !document.querySelector('video').paused, document.querySelector('video').currentTime, window.__same === 1, document.querySelector('.vo-nb-n').textContent]")
    pauses = pg.evaluate("() => __pauses")
    check(f"swap ({vp}): {dt:.2f} s after Enter: {want_q}, same document, named mode, restarted from {before:.1f} s, playing within 1 s, never paused, bar 'Rebuilt for {SWAP_NAME}' -> {vp}-swap-settled.png",
          done and got[4] and got[5] == SWAP_NAME and pauses == 0, (got, dt, pauses))
    try:
        pg.wait_for_function("() => __said.length > 0", timeout=3000)
    except Exception:
        pass
    pg.wait_for_timeout(150)
    said = pg.evaluate("() => __said")
    pill = pg.evaluate("() => { const e = document.querySelector('.vo-for'); return [e.hasAttribute('data-off'), e.innerText.replace(/\\s+/g, ' ').trim()]; }")
    check(f"swap ({vp}): spoken once with {SWAP_NAME!r} at data-cue-say-start {cues['say-start']} after the restart, 'for' pill",
          len(said) == 1 and said[0][0] == SWAP_NAME and cues["say-start"] <= said[0][1] < cues["say-start"] + 0.5 and not pill[0] and pill[1].endswith(f"for {SWAP_NAME}"), (said, pill))
    g = cues["google"]
    tg = round(g[0] + 1.3, 2)
    pg.evaluate("t => { const v = document.querySelector('video'); v.pause(); v.currentTime = t; }", tg)
    pg.wait_for_function(SEEKED, arg=tg, timeout=15000)
    pg.wait_for_timeout(1200)
    pg.locator(".vo-stage").screenshot(path=str(out / f"{vp}-swap-google-live.png"))
    vis = pg.evaluate(VISIBLE)
    check(f"swap ({vp}): google at its live cue (t={tg:g}) shows {SWAP_NAME!r} -> {vp}-swap-google-live.png",
          [v[0] for v in vis] == ["google"] and SWAP_NAME in vis[0][2] and GENERIC not in vis[0][2], [(v[0], v[2][:80]) for v in vis])
    if vp == "desktop":   # the end say cue too
        say = cues["say"]
        pg.evaluate("t => { document.querySelector('video').currentTime = t; }", say - 0.6)
        pg.wait_for_function(SEEKED, arg=say - 0.6, timeout=15000)
        pg.evaluate("() => document.querySelector('video').play()")
        try:
            pg.wait_for_function("() => __said.length > 1", timeout=3000)
        except Exception:
            pass
        said = pg.evaluate("() => __said")
        check(f"swap (desktop): spoken again with {SWAP_NAME!r} at data-cue-say {say}", len(said) == 2 and said[1][0] == SWAP_NAME and say <= said[1][1] < say + 0.5, said)
        pg.evaluate("() => document.querySelector('video').pause()")
    tc = round(cta + 0.6, 2)
    pg.evaluate("t => { const v = document.querySelector('video'); v.pause(); v.currentTime = t; }", tc)
    pg.wait_for_function(SEEKED, arg=tc, timeout=15000)
    pg.wait_for_timeout(300)
    vis = [v[0] for v in pg.evaluate(VISIBLE)]
    check(f"swap ({vp}): cta-steps never appears after the swap (observer + at cta + 0.6 = {tc:g}: {vis})",
          "cta-steps" not in vis and pg.evaluate("() => __ctaSeen") is False and pg.evaluate("() => document.documentElement.dataset.voMode") == "named", vis)
    pg.evaluate("() => document.querySelector('.vo-nb-chg').click()")   # DOM click: hidden (no swap) must fail the check, not abort
    pg.wait_for_timeout(200)
    ch = pg.evaluate("() => [getComputedStyle(document.querySelector('.vo-nb-f')).display, document.querySelector('#vo-nb-in').value, document.activeElement.id]")
    check(f"swap ({vp}): Change re-opens the input, prefilled with {SWAP_NAME!r}, focused", ch[0] != "none" and ch[1:] == [SWAP_NAME, "vo-nb-in"], ch)
    pg.evaluate("() => document.activeElement.blur()")
    pg.evaluate("() => document.querySelector('.vo-nb-rst').click()")
    try:
        pg.wait_for_function("""() => { const v = document.querySelector('video'); return location.search === '' && document.documentElement.dataset.voMode === 'generic'
            && !v.paused && v.currentTime < 2 && document.querySelector('[data-vo=name]').textContent === 'Your name'; }""", timeout=3000)
    except Exception:
        pass
    got = pg.evaluate("() => [location.search, document.documentElement.dataset.voMode, document.querySelector('[data-vo=name]').textContent, !document.querySelector('video').paused, document.querySelector('video').currentTime, getComputedStyle(document.querySelector('.vo-nb-f')).display, window.__same === 1]")
    pg.evaluate("t => { const v = document.querySelector('video'); v.pause(); v.currentTime = t; }", tc)
    pg.wait_for_function(SEEKED, arg=tc, timeout=15000)
    pg.wait_for_timeout(300)
    vis = [v[0] for v in pg.evaluate(VISIBLE)]
    check(f"swap ({vp}): Reset → generic in place (URL without query, 'Your name', restarted + playing, the form back), end card back at {tc:g}",
          got[0] == "" and got[1:4] == ["generic", GENERIC, True] and got[4] < 2 and got[5] != "none" and got[6] and vis == ["cta-steps"], (got, vis))
    check(f"bar ({vp}): no console errors, no request outside the local server", not errs and not ext, (errs, sorted(set(ext))))
    ctx.close()


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


# layout box (offset*, so the theater's rotation does not matter) of the stage / video / .vo-over, the drawn picture's size
# (object-fit), the overlay layers' paint, the screen rects of the stage + .vo-over, data-vo-full
FULL = """() => { const st = document.querySelector('.vo-stage'), v = document.querySelector('.vo-video'), ov = document.querySelector('.vo-over'),
  bx = document.querySelector('.vo-box'), lay = e => [e.offsetLeft, e.offsetTop, e.offsetWidth, e.offsetHeight], fit = getComputedStyle(v).objectFit,
  sc = fit === 'cover' ? Math.max(v.offsetWidth / v.videoWidth, v.offsetHeight / v.videoHeight) : fit === 'contain' || fit === 'scale-down'
     ? Math.min(v.offsetWidth / v.videoWidth, v.offsetHeight / v.videoHeight) : NaN, r = e => { const b = e.getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; },
  paint = e => { const c = getComputedStyle(e); return [c.backgroundColor, c.backgroundImage, c.boxShadow, c.filter, c.backdropFilter || 'none']; };
  return [lay(st), lay(v), fit === 'fill' ? [v.offsetWidth, v.offsetHeight] : [v.videoWidth * sc, v.videoHeight * sc], lay(ov), paint(ov), paint(bx),
          r(st), r(ov), document.documentElement.dataset.voFull || null]; }"""
# the stage region x0..x1, y0..y1 (fractions) as an 8x8 RGB grid, on the screenshot vs the same region of the video frame drawn alone
PIX = """async ([png, box]) => { const v = document.querySelector('.vo-video'), st = document.querySelector('.vo-stage').getBoundingClientRect(), dpr = devicePixelRatio;
  const mean = (src, sx, sy, sw, sh) => { const c = document.createElement('canvas'); c.width = 8; c.height = 8; const g = c.getContext('2d');
    g.imageSmoothingQuality = 'high'; g.drawImage(src, sx, sy, sw, sh, 0, 0, 8, 8); return [...g.getImageData(0, 0, 8, 8).data].filter((x, i) => i % 4 < 3); };
  const img = await createImageBitmap(await (await fetch('data:image/png;base64,' + png)).blob());
  const [x0, y0, x1, y1] = box;
  return [mean(img, (st.left + x0 * st.width) * dpr, (st.top + y0 * st.height) * dpr, (x1 - x0) * st.width * dpr, (y1 - y0) * st.height * dpr),
          mean(v, x0 * v.videoWidth, y0 * v.videoHeight, (x1 - x0) * v.videoWidth, (y1 - y0) * v.videoHeight)]; }"""


def full_frame(b, base, out):
    """the video fills the whole stage, the cards are drawn on its right half (transparent overlay layer)"""
    import base64
    near = lambda a, b, tol=1.5: abs(a - b) <= tol
    clear = lambda p: p[0] in ("rgba(0, 0, 0, 0)", "transparent") and p[1] == "none" and p[2] == "none" and p[3] == "none" and p[4] == "none"
    for vp, opts, how in (("1920", dict(viewport={"width": 1920, "height": 1156}), None), ("1280", dict(viewport={"width": 1280, "height": 800}), None),
                          ("phone", VIEWPORTS["phone"], None), ("theater", VIEWPORTS["phone"], "theater"), ("fullscreen", VIEWPORTS["desktop"], "fs")):
        ctx = ctx_new(b, **opts)
        if how == "theater":
            ctx.add_init_script(IPHONE_FS)
        pg = ctx.new_page()
        goto(pg, base, "", 3)   # card-free: before google's live cue
        if how:
            pg.locator(".vo-fs").click()
            pg.wait_for_function("w => document.documentElement.dataset.voFull === w", arg=how, timeout=4000)
            pg.wait_for_timeout(500)
        shot = out / f"full-frame-{vp}.png"
        pg.screenshot(path=str(shot))
        if how is None:   # declared: native controls off for the pixel probe (their gradient darkens the bottom of the frame)
            pg.evaluate("() => { document.querySelector('.vo-video').controls = false; }")
            pg.wait_for_timeout(300)
            png = pg.screenshot()
        st, vb, pic, ov, pov, pbx, sr, orr, full = pg.evaluate(FULL)
        check(f"full frame: {vp}: the <video> box == the stage box -> {shot.name}", all(near(x, y) for x, y in zip(vb, [0, 0, st[2], st[3]])), (st, vb))
        if how == "fs":   # the whole take, centred: the overlay = the right half of that picture
            check(f"full frame: {vp}: the 16:9 picture centred in the full-screen stage, .vo-over = its right half, transparent",
                  near(pic[0] / pic[1], 16 / 9, .02) and near(orr[0], sr[0] + (st[2] - pic[0]) / 2 + pic[0] / 2) and near(orr[2], pic[0] / 2) and near(orr[3], pic[1])
                  and clear(pov) and clear(pbx), (st, pic, orr, pov, pbx))
            ctx.close()
            continue
        check(f"full frame: {vp}: the drawn picture covers the whole stage (object-fit)", pic[0] >= st[2] - 1.5 and pic[1] >= st[3] - 1.5, (st, pic))
        check(f"full frame: {vp}: .vo-over / .vo-box = the stage's right half, transparent (no background / shadow / filter)",
              near(ov[0], st[2] / 2) and near(ov[1], 0) and near(ov[2], st[2] / 2) and near(ov[3], st[3]) and clear(pov) and clear(pbx), (st, ov, pov, pbx))
        if how is None:   # the theater is rotated on screen: its geometry above is enough
            a_, v_ = pg.evaluate(PIX, [base64.b64encode(png).decode(), [.56, .1, .96, .9]])
            check(f"full frame: {vp}: the screen's right half (no card at 3 s) = the video frame's right half", max(abs(x - y) for x, y in zip(a_, v_)) < 8,
                  max(abs(x - y) for x, y in zip(a_, v_)))
        ctx.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--name", default="Tessa")
    ap.add_argument("--break-thumbs", action="store_true")
    ap.add_argument("--break-steps", action="store_true")
    ap.add_argument("--break-swap", action="store_true")
    ap.add_argument("--break-demo", action="store_true")
    ap.add_argument("--break-full", action="store_true")
    a = ap.parse_args()
    out = pathlib.Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    html = (ROOT / "site/video/index.html").read_text(encoding="utf-8")
    if a.break_steps:   # wire boundary: index.html minus the cta-steps animation (the end card + form stay)
        broken, k = re.subn(r'\n        <div class="vo-steps".*?\n        </div>\n(?=        <form class="vo-cta-f")', "\n", html, flags=re.S)
        assert k == 1, "break: .vo-steps block not found"
        BREAK["steps"] = (lambda u: urllib.parse.urlsplit(u).path.endswith("/video/"), broken, "text/html")
    if a.break_swap:   # wire boundary: video-overlays.js minus the submit's in-place rebuild (validation stays)
        js = (ROOT / "site/js/video-overlays.js").read_text(encoding="utf-8")
        broken, k = re.subn(r"(inp\.blur\(\);)\n\s*rebuild\(n\);", r"\1", js)
        assert k == 1, "break: rebuild(n) call not found"
        BREAK["swap"] = ("**/js/video-overlays.js", broken, "application/javascript")
    if a.break_demo:   # wire boundary: video-overlays.js with the old demo name
        js = (ROOT / "site/js/video-overlays.js").read_text(encoding="utf-8")
        broken, k = re.subn(r"DEMO = '[^']*'", "DEMO = 'Orla Brennick'", js)
        assert k == 1, "break: DEMO not found"
        BREAK["demo"] = ("**/js/video-overlays.js", broken, "application/javascript")
    if a.break_full:   # wire boundary: css/video.css + the old split layout (video in the left half, an opaque panel behind the cards)
        css = (ROOT / "site/css/video.css").read_text(encoding="utf-8") + "\n.vo-video { width: 50%; object-fit: contain; } .vo-over { background: #353b43; }\n"
        BREAK["full"] = ("**/css/video.css", css, "text/css")
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
                        check("end card form: invalid name '<b>' → no rebuild, a message", "name=" not in pg.url and bool(msg), (pg.url, msg))
                        pg.fill("#vo-name", f"  {a.name}   Q ")
                        pg.screenshot(path=str(out / "desktop-generic-end-form-typed.png"))
                        pg.evaluate("() => { window.__same = 1; }")
                        pg.press("#vo-name", "Enter")
                        want = f"/video/?name={urllib.parse.quote(a.name + ' Q')}"
                        try:
                            pg.wait_for_function("u => location.href.endsWith(u) && document.documentElement.dataset.voMode === 'named'", arg=want, timeout=4000)
                        except Exception:
                            pass
                        nm = pg.evaluate("() => [document.querySelector('[data-vo=name]').textContent, window.__same === 1]")
                        check(f"swap: end card form: '{a.name} Q' → in place (same document), {want}, named mode, texts", pg.url.endswith(want) and nm == [f"{a.name} Q", True], (pg.url, nm))
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
        full_frame(b, base, out)
        for vp, opts in SWAP_VIEWPORTS.items():
            swap(b, base, out, cues, cta, vp, opts)
        for f in ("bar-generic-0s", "settled", "google-live"):
            print(f"swap proof -> frame-1920-swap-{f}.png")
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
        full = cta_steps(pg, base, out, cta, name_q)
        ctx.close()
        cta_phone(b, base, out, cta, full)
        speech(b, base, out, a.name, cues)
        sfx(b, base, cues)
        named_take(b, base, a.name, cues, shift)
        personalized(b, out, a.break_thumbs)
    for f in fails:
        print("FAIL", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

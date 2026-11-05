#!/usr/bin/env python3
"""Real-path proof for site/video/: serve site/ (Range-capable, tools/video/serve.py), open video/?name=NAME&t=<cue> at
phone 390x844 and desktop 1440x900, wait until the <video> has seeked there, screenshot, and assert: only the cue's
prefab is on screen, in the right state (wipe --p 100 live / 0 removed), NAME is in it, on desktop it sits in the
bottom-right corner (left >= 60 % / top >= 45 % of the frame: Jack's face stays uncovered), no request leaves
127.0.0.1, no console error. Each prefab is shot live (settled, <= live + 1.3 s) and removed (removed + 2 s).
Plus:
- frame-1920-google-live.png: the full 1920x1080 frame (placeholder take + the google card, live) = the framing proof
- personalized (tools/scan_stub.py, ?r=demoRemove1): texts from the scan result in every prefab; every .rm-img = the
  scan's thumbs via <API>/api/thumb, loaded, still blurred; and ?name= keeps the default photos (img/removals)
- speech (data-cue-say): speechSynthesis.speak stubbed (declared: no voice in headless), cue moved to 29.2 s (declared:
  the placeholder take is 30 s, the real cue is later); Space = the play gesture. ?name=NAME → spoken once with NAME,
  rate 0.95, video ducked to 0.25 then restored, "for NAME" pill shown; no name (default creator) → never spoken.
--break-thumbs serves video-overlays.js without the thumb src assignment: only the thumbs check goes red.
Usage: cd ~/leakhunt && uv run python ~/leakscan-site/tools/video/cue_shots.py OUT_DIR [--name Tessa] [--break-thumbs]
Prints one line per shot / check + 'FAIL …' lines; exit 1 on any failure."""
import argparse, pathlib, re, socket, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from serve import serve
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2]
VIEWPORTS = {"phone": dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True),
             "desktop": dict(viewport={"width": 1440, "height": 900})}
SEEKED = ("t => { const v = document.querySelector('video'); return v.readyState >= 3 && !v.seeking"
          " && Math.abs(v.currentTime - t) < 0.05 }")
# demoRemove1 (tools/scan_stub.py): what its scan result must put in the [data-vo] slots
WANT_TEXT = {"name": "Mira Example", "x-at": "@demo_reposter", "x-l1": "Mira Example leaked full set", "sub": "r/demo_leaksub",
             "rd-title": "Mira Example new pack in comments", "mega-title": "demo.creator MEGA pack 2026",
             "mega-meta": "6.2 GB · 412 images · 88 videos · 3 days ago"}
IMGS = "() => [...document.querySelectorAll('.rm-img')].map(i => [i.getAttribute('src'), i.naturalWidth, getComputedStyle(i).filter])"
SAY_STUB = """window.__said = []; if ('speechSynthesis' in window) speechSynthesis.speak = u => { const v = document.querySelector('video');
  __said.push([u.text, v.currentTime, v.volume, u.rate, u.lang]); setTimeout(() => u.onend && u.onend(), 400); };"""
fails = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
    if not ok:
        fails.append(name)


def guard(ctx, base_ok):
    """abort + record every request outside the local server(s)"""
    ext = []
    ctx.route("**/*", lambda r: r.continue_() if any(r.request.url.startswith(b) for b in base_ok) else (ext.append(r.request.url), r.abort()))
    return ext


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
        im = pg.evaluate(IMGS)
        check(f"personalized ?r=demoRemove1: all {len(im)} .rm-img = scan thumbs via {api}/api/thumb, loaded, blurred",
              len(im) == 13 and all(s.startswith(api + "/api/thumb?u=") and w > 0 and "blur(" in f for s, w, f in im), im[:3])
        pg.screenshot(path=str(out / "desktop-personalized-demoRemove1-x-live.png"))
        check("personalized: no request outside the stub, no JS error", not ext and not errs, (ext, errs))
        ctx.close()
    finally:
        stub.terminate()


def speech(b, base, name):
    for who in (name, None):
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_init_script(SAY_STUB)
        pg = ctx.new_page()
        pg.goto(f"{base}video/?t=28.6" + (f"&name={who}" if who else ""))
        pg.wait_for_function(SEEKED, arg=28.6, timeout=15000)
        pg.evaluate("() => document.querySelector('.vo-stage').setAttribute('data-cue-say', '29.2')")
        pg.mouse.click(5, 5)            # focus the page (not the <video>), then Space = play: the user gesture
        pg.keyboard.press("Space")
        if who:
            try:
                pg.wait_for_function("() => __said.length > 0", timeout=6000)
            except Exception:
                pass
            pg.wait_for_timeout(500)    # the pill has slid in (0.4 s)
            pill = pg.evaluate("() => { const e = document.querySelector('.vo-for'); return [e.hasAttribute('data-off'), e.innerText.replace(/\\s+/g, ' ').trim()]; }")
            pg.screenshot(path=str(pathlib.Path(OUT) / f"desktop-say-{who}.png"))
            pg.wait_for_timeout(300)
            said, vol = pg.evaluate("() => [__said, document.querySelector('video').volume]")
            check(f"speech ?name={who}: spoken once at the cue with the name, rate 0.95, en, video ducked to 0.25 then restored",
                  len(said) == 1 and said[0][0] == who and 29.2 <= said[0][1] < 29.7 and said[0][2] == 0.25 and abs(said[0][3] - 0.95) < 1e-6
                  and said[0][4] == "en" and vol == 1, (said, vol))
            check(f"speech ?name={who}: 'for {who}' pill on screen at the cue", not pill[0] and pill[1].endswith(f"for {who}"), pill)
        else:
            pg.wait_for_function("() => document.querySelector('video').currentTime > 29.9 || document.querySelector('video').ended", timeout=8000)
            said = pg.evaluate("() => [__said, document.querySelector('.vo-for').hasAttribute('data-off')]")
            check("speech, default creator (no ?name, no scan): never spoken, no pill", said == [[], True], said)
        ctx.close()


def main():
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--name", default="Tessa")
    ap.add_argument("--break-thumbs", action="store_true")
    a = ap.parse_args()
    out = OUT = pathlib.Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    html = (ROOT / "site/video/index.html").read_text(encoding="utf-8")
    cues = [(m[1], float(m[2]), float(m[3]), float(m[4])) for m in re.finditer(
        r'data-prefab="([\w-]+)" data-cue-live="([\d.]+)" data-cue-removed="([\d.]+)" data-cue-out="([\d.]+)"', html)]
    with serve() as base, sync_playwright() as p:
        b = p.chromium.launch()
        for vp, opts in VIEWPORTS.items():
            ctx = b.new_context(**opts)
            ext = guard(ctx, (base,))
            pg = ctx.new_page()
            errs = []
            pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: errs.append(str(e)))
            for pid, live, rem, off in cues:
                for state, t in (("live", round(live + min(1.3, rem - live - 0.1), 2)), ("removed", min(rem + 2.0, off - 0.45))):
                    pg.goto(f"{base}video/?name={a.name}&t={t:g}")
                    pg.wait_for_function(SEEKED, arg=t, timeout=15000)
                    pg.wait_for_timeout(1500)   # the native loading spinner fades out
                    shot = out / f"{vp}-t{t:05.2f}-{pid}-{state}.png"
                    if vp == "phone":
                        pg.locator(".vo-stage").screenshot(path=str(shot))
                    else:
                        pg.screenshot(path=str(shot))
                    st = pg.evaluate("""() => { const s = document.querySelector('.vo-stage').getBoundingClientRect();
                        return [...document.querySelectorAll('.vo-pf')].filter(e => !e.hasAttribute('data-off')).map(e => { const r = e.getBoundingClientRect();
                          return [e.dataset.prefab, getComputedStyle(e.querySelector('.rm-stage')).getPropertyValue('--p').trim(), e.textContent.replace(/\\s+/g, ' '),
                                  [(r.left - s.left) / s.width, (r.top - s.top) / s.height, (r.right - s.left) / s.width, (r.bottom - s.top) / s.height]]; }); }""")
                    vis = [s[0] for s in st]
                    ok = vis == [pid] and float(st[0][1]) == (100 if state == "live" else 0) and a.name in st[0][2]
                    box = [round(x, 3) for x in st[0][3]] if st else None
                    corner = vp == "phone" or (box and box[0] >= .6 and box[1] >= .45 and box[2] <= 1 and box[3] <= 1)
                    print(f"{vp} t={t:g} {pid} {state}: visible={vis} p={[s[1] for s in st]} box={box} -> {shot.name}")
                    if not ok:
                        check(f"{vp} t={t:g}: only {pid} {state} with {a.name!r}", False, [(s[0], s[1]) for s in st])
                    if not corner:
                        check(f"{vp} t={t:g}: {pid} in the bottom-right corner (left >= .6, top >= .45 of the frame)", False, box)
            check(f"{vp}: no console errors", not errs, errs)
            check(f"{vp}: no requests outside the local server", not ext, sorted(set(ext)))
            if vp == "desktop":   # defaults stay for ?name= (no scan photos without a scan)
                im = pg.evaluate(IMGS)
                check(f"?name={a.name}: all {len(im)} .rm-img keep the default photos (img/removals), blurred",
                      len(im) == 13 and all(s.startswith("../img/removals/") and "blur(" in f for s, w, f in im), im[:3])
            ctx.close()
        # the framing proof: the whole 1920x1080 frame, google card live
        ctx = b.new_context(viewport={"width": 1920, "height": 1080})
        pg = ctx.new_page()
        g = next(c for c in cues if c[0] == "google")
        t = g[1] + 1
        pg.goto(f"{base}video/?name={a.name}&t={t:g}")
        pg.wait_for_function(SEEKED, arg=t, timeout=15000)
        pg.wait_for_timeout(1500)
        pg.locator(".vo-stage").screenshot(path=str(out / "frame-1920-google-live.png"))
        print(f"framing proof t={t:g} -> frame-1920-google-live.png")
        ctx.close()
        speech(b, base, a.name)
        personalized(b, out, a.break_thumbs)
    for f in fails:
        print("FAIL", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

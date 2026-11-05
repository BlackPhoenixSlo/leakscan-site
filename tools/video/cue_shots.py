#!/usr/bin/env python3
"""Real-path proof for site/video/: serve site/ (Range-capable, tools/video/serve.py), open video/?name=NAME&t=<cue> at
phone 390x844 and desktop 1440x900, wait until the <video> has seeked there, screenshot, and assert: only the cue's
prefab is on screen, in the right state (wipe --p 100 live / 0 removed), NAME is in it, no request leaves 127.0.0.1,
no console error. Each prefab is shot live (live cue + 0.8 s) and removed (removed cue + 2 s).
Usage: cd ~/leakhunt && uv run python ~/leakscan-site/tools/video/cue_shots.py OUT_DIR [--name Tessa]
Prints one line per shot + 'FAIL …' lines; exit 1 on any failure."""
import argparse, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from serve import serve
from playwright.sync_api import sync_playwright

VIEWPORTS = {"phone": dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True),
             "desktop": dict(viewport={"width": 1440, "height": 900})}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--name", default="Tessa")
    a = ap.parse_args()
    out = pathlib.Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    fails = []
    html = (pathlib.Path(__file__).resolve().parents[2] / "site/video/index.html").read_text(encoding="utf-8")
    cues = [(m[1], float(m[2]), float(m[3])) for m in
            re.finditer(r'data-prefab="(\w+)" data-cue-live="([\d.]+)" data-cue-removed="([\d.]+)"', html)]
    with serve() as base, sync_playwright() as p:
        b = p.chromium.launch()
        for vp, opts in VIEWPORTS.items():
            ctx = b.new_context(**opts)
            pg = ctx.new_page()
            errs, ext = [], []
            pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("request", lambda r: ext.append(r.url) if not r.url.startswith(base) else None)
            for pid, live, rem in cues:
                for state, t in (("live", live + 0.8), ("removed", rem + 2.0)):
                    pg.goto(f"{base}video/?name={a.name}&t={t:g}")
                    pg.wait_for_function("t => { const v = document.querySelector('video'); return v.readyState >= 3"
                                         " && !v.seeking && Math.abs(v.currentTime - t) < 0.05 }", arg=t, timeout=15000)
                    pg.wait_for_timeout(400)
                    shot = out / f"{vp}-t{t:05.2f}-{pid}-{state}.png"
                    if vp == "phone":
                        pg.locator(".vo-stage").screenshot(path=str(shot))
                    else:
                        pg.screenshot(path=str(shot))
                    st = pg.evaluate("""() => [...document.querySelectorAll('.vo-pf')].filter(e => !e.hasAttribute('data-off'))
                        .map(e => [e.dataset.prefab, getComputedStyle(e.querySelector('.rm-stage')).getPropertyValue('--p').trim(),
                                   e.textContent.replace(/\\s+/g, ' ')])""")
                    vis = [s[0] for s in st]
                    ok = vis == [pid] and float(st[0][1]) == (100 if state == "live" else 0) and a.name in st[0][2]
                    print(f"{vp} t={t:g} {pid} {state}: visible={vis} p={[s[1] for s in st]} -> {shot.name}")
                    if not ok:
                        fails.append(f"{vp} t={t:g}: want only {pid} {state} with {a.name!r}, got {[(s[0], s[1]) for s in st]}")
            if errs:
                fails.append(f"{vp}: console errors {errs}")
            if ext:
                fails.append(f"{vp}: requests outside the local server {sorted(set(ext))}")
            ctx.close()
    for f in fails:
        print("FAIL", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

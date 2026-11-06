"""Scenario `sheet` (see tools/scan_e2e.py for what it proves)."""
import json
import urllib.request
from urllib.parse import urlsplit

from .common import cfg, check, new_ctx, settled_count


def mode(m):
    urllib.request.urlopen(urllib.request.Request(f"{cfg.base}__stub/sheet?mode={m}", method="POST")).read()


def counts():
    """(/api/thumb requests, /api/thumb-sheet requests) that reached the server so far."""
    return tuple(len(json.loads(urllib.request.urlopen(f"{cfg.base}api/{p}").read())) for p in ("_thumb-log", "_sheet-log"))


# every image a landing view shows, by the raw thumb behind it: hero, #free phone, the phones, the removals panels; every lazy one on the way.
# Sorted: which thumbs a view ends with is fixed (the first live ones), which slot each sits in follows the order the verdicts came in, on any path
LANDING = """async () => { for (let y = 0; y < document.body.scrollHeight; y += 500) { scrollTo({top: y, behavior: 'instant'}); await new Promise(r => setTimeout(r, 40)); }
  scrollTo({top: 0, behavior: 'instant'}); const q = s => [...document.querySelectorAll(s)], tx = s => ((document.querySelector(s) || {}).textContent || '').trim();
  return {counts: [tx('#tab-report-images .live-tab-n'), tx('.report-card .live-imgs-head p'), tx('.phone-free [data-live=free-images] .m-n')],
    hero: q('.report-card a.gi-card').map(a => a.getAttribute('data-src')).sort(), free: q('.phone-free [data-live=free-images] a.gi-card').map(a => a.getAttribute('data-src')).sort(),
    phones: q('[data-p="thumbs"] .p-img').length, removals: q('#removals .rm-img').map(i => !i.parentNode.hidden)}; }"""
STAGE = "() => [...document.querySelectorAll('#g-stage [data-src]')].map(t => t.getAttribute('data-src'))"
VIDEOS = "() => [...document.querySelectorAll('#g-stage .g-v')].map(v => [v.querySelector('a').getAttribute('href'), !!v.querySelector('img')])"
# <img>s that hold a thumb right now → [how many, how many on a blob URL, how many painted]
LOADED = """(sel) => { const m = [...document.querySelectorAll(sel)].filter(i => i.getAttribute('src')), l = m.filter(i => i.complete && i.naturalWidth >= 16);
  return [m.length, m.filter(i => i.getAttribute('src').startsWith('blob:')).length, l.length]; }"""
PEOPLE = "() => window.VideoOverlays && window.VideoOverlays.photos"
STREAMED = """() => document.querySelector('.report-card a.gi-card img[src^="blob:"], .phone-free a.gi-card img[src^="blob:"]')?.naturalWidth >= 16
  && !performance.getEntriesByType('resource').some(r => r.name.includes('/api/thumb-sheet/'))"""
SETTLED = "() => { const p = window.VideoOverlays && window.VideoOverlays.photos; return !!p && p.settled; }"


def landing(browser, vp_name, vp, slug, opts):
    """→ what the landing shows for slug once settled (counts, tiles, the video's photos), + the requests it took."""
    ctx, net = new_ctx(browser, vp_name, vp, **opts)
    page = ctx.new_page()
    n0 = counts()
    page.goto(cfg.base + "?r=" + slug, wait_until="load")
    settled_count(page, "#tab-report-images .live-tab-n", 45000)
    out = page.evaluate(LANDING)
    page.wait_for_selector(".pip iframe", state="attached", timeout=20000)
    fr = page.query_selector(".pip iframe").content_frame()
    fr.wait_for_function(SETTLED, timeout=60000)
    out["video"] = fr.evaluate(PEOPLE)
    page.wait_for_timeout(300)
    n1 = counts()
    return ctx, page, net, out, n1[0] - n0[0], n1[1] - n0[1]


def report(browser, vp_name, vp, slug, opts):
    """→ what scan/?r= shows on each tab, + the requests it took (Images = every image)."""
    ctx, net = new_ctx(browser, vp_name, vp, **opts)
    page = ctx.new_page()
    n0 = counts()
    page.goto(cfg.base + "scan/?r=" + slug, wait_until="load")
    page.wait_for_selector("#tab-google-images", timeout=20000)
    page.locator("#tab-google-images").click()
    page.wait_for_function("() => document.querySelector('#g-stage [data-src]')", timeout=20000)
    images, last = [], None
    for _ in range(60):   # the list stands still 3 s = every verdict in
        page.wait_for_timeout(1000)
        images = page.evaluate(STAGE)
        last = (images, 0) if not last or last[0] != images else (images, last[1] + 1)
        if last[1] >= 3 and len(images) and page.evaluate(LOADED, "#g-stage [data-src] img")[2] >= min(4, len(images)):
            break
    page.locator("#tab-google-videos").click()
    page.wait_for_timeout(500)
    videos = page.evaluate(VIDEOS)
    n1 = counts()
    return ctx, page, net, {"images": images, "videos": videos}, n1[0] - n0[0], n1[1] - n0[1]


def sheet_flow(pw, chromium, vp_name, vp, engine="chromium"):
    """/api/thumb-sheet (app/thumb_sheet.py, E.sheet in js/scan-engine.js): one request, every view shows what the per-thumb path shows."""
    tag = f"{vp_name}{'-webkit' if engine == 'webkit' else ''} sheet:"
    browser = pw.webkit.launch() if engine == "webkit" else chromium
    opts = dict(pw.devices["iPhone 13"]) if engine == "webkit" else {}
    on = "500" if "sheet500" in cfg.broken else "on"
    try:
        for slug in ("demoBrokenT1", "demoNoCell01"):
            nocell = slug == "demoNoCell01"
            mode("off")
            c0, _, net0, base, th0, sh0 = landing(browser, vp_name, vp, slug, opts)
            start, th_start = base, th0
            c0.close()
            mode(on)
            c1, page, net1, got, th1, sh1 = landing(browser, vp_name, vp, slug, opts)
            sent = [urlsplit(x[1]).query or x[1] for x in json.loads(urllib.request.urlopen(f"{cfg.base}api/_thumb-log").read())[-th1:]] if th1 else []
            check(f"{tag} {slug}: fallback (404): per-thumb path, as before", sh0 >= 1 and th0 > 5, [sh0, th0])
            check(f"{tag} {slug}: landing shows the same with the sheet: counts, hero, #free, phones, removals, video's photos",
                  {k: got[k] for k in got if k != "video"} == {k: base[k] for k in base if k != "video"} and got["video"]["kept"] == base["video"]["kept"]
                  and got["video"]["dropped"] == base["video"]["dropped"], {k: (base[k], got[k]) for k in base if base[k] != got[k]})
            check(f"{tag} {slug}: end card count = the report's", len(got["video"]["kept"]) == int(got["counts"][0] or -1), [len(got["video"]["kept"]), got["counts"]])
            check(f"{tag} {slug}: no dead / logo / blank thumb shown", not any(x in u for u in got["hero"] + got["free"] for x in ("DEAD", "BLANK", "LOGO")), got["hero"])
            if nocell:
                check(f"{tag} sheet requests: page + iframe = one; a thumb it does not name (and only that) goes to /api/thumb",
                      sh1 == 1 and th1 >= 1 and all("NOCELL" in q for q in sent), [sh1, th1, sent[:3]])
            else:
                check(f"{tag} sheet requests: page + iframe = one sheet, no /api/thumb (dead ones too)", sh1 == 1 and th1 == 0, [sh1, th1, th0, sent[:3]])
                load = page.evaluate(LOADED, ".report-card a.gi-card img, .phone-free a.gi-card img")
                check(f"{tag} tiles are real <img>s on blob URLs, painted", load[0] and load[0] == load[1], load)
                blur = "() => getComputedStyle(document.querySelector('#panel-report-images .gi-img')).filter"
                page.locator("#tab-report-images").click()
                page.wait_for_function("() => document.querySelector('#panel-report-images .gi-img')", timeout=5000)
                b0 = page.evaluate(blur)
                page.locator(".report-card").screenshot(path=str(cfg.out / f"sheet-{vp_name}-{engine}-1-blurred.png"))
                page.locator("#panel-report-images .reveal-btn").click()
                page.wait_for_timeout(400)
                b1 = page.evaluate(blur)
                page.locator(".report-card").screenshot(path=str(cfg.out / f"sheet-{vp_name}-{engine}-2-revealed.png"))
                check(f"{tag} blur on, Reveal takes it off", "blur" in b0 and "blur" not in b1, [b0, b1])
                errs = [e for e in net1["errors"] if not ("STALE" in e and "access control" in e)]   # WebKit reports the stub's STALE thumb (no ACAO, on purpose) refused on the per-thumb path
                check(f"{tag} no page errors", not errs and not net1["outside"], errs[:2])
            c1.close()
            if nocell:
                continue
            mode("off")
            c0, _, _, rbase, _, _ = report(browser, vp_name, vp, slug, opts)
            c0.close()
            mode(on)
            c1, page, net1, rgot, th, sh = report(browser, vp_name, vp, slug, opts)
            # WebKit: main's per-thumb list is not the same run to run either (E.isPhoto on the fixture's 2000 px stand-ins, undecoded: 2026-11-06-perf-sheet-*/webkit_scanpage): how many, not which
            same = (len(rgot["images"]), rgot["videos"]) == (len(rbase["images"]), rbase["videos"]) if engine == "webkit" else (sorted(rgot["images"]), rgot["videos"]) == (sorted(rbase["images"]), rbase["videos"])   # sorted: see LANDING
            check(f"{tag} scan page shows the same with the sheet: Images tab tiles, Videos rows", same and not any(x in u for u in rgot["images"] for x in ("DEAD", "BLANK", "LOGO")), {k: (rbase[k], rgot[k]) for k in rbase if rbase[k] != rgot[k]})
            check(f"{tag} scan page: one sheet, no /api/thumb", sh == 1 and th == 0, [sh, th])
            c1.close()
            mode("500" if "sheet500" in cfg.broken else "slow")
            c1, net1 = new_ctx(browser, vp_name, vp, **opts)
            page = c1.new_page()
            page.goto(cfg.base + "?r=" + slug, wait_until="commit")
            try:   # Resource Timing lists a request once its body has ended
                page.wait_for_function(STREAMED, timeout=8000)
                streamed = page.evaluate(STREAMED)
            except Exception:
                streamed = False
            check(f"{tag} read as it arrives: a tile paints while the sheet's second half is on its way", streamed)
            c1.close()
            mode("500" if "sheet500" in cfg.broken else "cut")
            c1, _, _, got, th1, sh1 = landing(browser, vp_name, vp, slug, opts)
            check(f"{tag} sheet cut halfway: same landing; what came stays, only the rest asks /api/thumb", {k: got[k] for k in got if k != "video"} == {k: start[k] for k in start if k != "video"} and got["video"]["kept"] == start["video"]["kept"]
                  and sh1 == 1 and 0 < th1 < th_start, {"requests": [sh1, th1, th_start], **{k: (start[k], got[k]) for k in start if start[k] != got[k]}})
            c1.close()
    finally:
        mode("off")
        if engine == "webkit":
            browser.close()

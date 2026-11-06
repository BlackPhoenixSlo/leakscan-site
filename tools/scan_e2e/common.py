"""Shared by every scenario: the run config (`cfg`, filled by configure() from main), the fixture, the stub, the one
break-it registry, new_ctx(), check() and the tile helpers. Importing it has no side effects."""
import argparse
import json
import pathlib
import re
import socket
import subprocess
import sys
import types
import urllib.request
from urllib.parse import urlsplit

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
FX = json.loads((ROOT / "tools" / "fixtures" / "scan-sample.json").read_text())   # the stub's fixture: expected profile / copy
SCENARIOS = ("scan", "personalize", "askai", "inline", "tabs", "removals", "pip")
VIEWPORTS = (("phone", {"width": 390, "height": 844}), ("desktop", {"width": 1440, "height": 900}))
LOOP = ("127.0.0.1", "localhost")
PROD_HOSTS = ("scan.srv1395798.hstgr.cloud", "72.62.92.114", "jackbase.me")
PROFILE = FX["profile"]
ACC = {a["platform"]: a for a in PROFILE["accounts"]}
ALSO = "Also found as " + ", ".join("@" + a for a in FX["aliases"]["discovered"])

# ---------- break-it registry: --break-<name> serves ONE script with ONE feature disabled, at the wire boundary (same
# bytes otherwise); only the checks named after that feature may go red. name -> (script or .css, marker, replacement)
BREAKS = {
    "drift": ("strip-drift.js", "DRIFT_SPEED = 24", "DRIFT_SPEED = 0"),
    "phones": ("personalize.js", "    phones(m, d);\n", "\n"),
    "thumbs": ("scan-engine.js", "    if (verdicts[src] === false || verdicts[src] === ok) return;\n", "    if (!ok || verdicts[src] === ok) return;\n"),
    "people": ("scan-engine.js", "    return !s || !(", "    return true || !("),   # E.isPhoto always true: logos kept
    "remove": ("removals.js", "card.querySelector('.rm-btn').addEventListener('click',", "(function () {})("),
    "sweep": ("removals.js", "  function step(c) {\n    c.t = 0;\n", "  function step(c) {\n    c.t = 0;\n    return;\n"),   # the sweep never steps
    "fprow": ("removals.css", ".fp-head { display: flex; align-items: center;", ".fp-head { display: flex; flex-direction: column; align-items: center;"),   # old centred head
    "tgcta": ("personalize.js", "    if (bar) {\n", "    if (false) {\n"),   # no Telegram sticky bar after a scan
    "allowlist": ("chat.js", "return HOSTS.indexOf(h) >= 0;", "return true;"),
    "tuck": ("pip.js", "  function tuck(side) {\n", "  function tuck(side) {\n    return;\n"),
    "pull": ("pip.js", "    if (drag.big) { pull(e, my); return; }\n", "    if (drag.big) return;\n"),   # expanded: no drag-down
    "dock": ("pip.js", "card = auto === 'dock' ? document.querySelector('.hero .report-card') : null;", "card = null;"),   # no dock anchor
    "incremental": ("scan.js", "SITES_STEP = 10, MORE_SITES = 25, LINKS_STEP = 10, MORE_LINKS = 50",
                    "SITES_STEP = 1e9, MORE_SITES = 1e9, LINKS_STEP = 1e9, MORE_LINKS = 1e9"),
}

# the run: set once by configure(); scenarios read cfg.out / cfg.base / cfg.api / cfg.broken
cfg = types.SimpleNamespace(out=None, port=0, base="", api="", omit=False, omit_profile=False, scenarios=SCENARIOS, broken=set())
fails = []
MEASURED = {}


def configure(argv):
    ap = argparse.ArgumentParser(prog="scan_e2e.py")
    ap.add_argument("out")
    ap.add_argument("--only", choices=SCENARIOS)
    ap.add_argument("--omit-results", action="store_true")
    ap.add_argument("--omit-profile", action="store_true")
    for k in BREAKS:
        ap.add_argument(f"--break-{k}", action="store_true")
    a = ap.parse_args(argv)
    cfg.out = pathlib.Path(a.out).expanduser()
    cfg.out.mkdir(parents=True, exist_ok=True)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        cfg.port = s.getsockname()[1]
    cfg.base = f"http://127.0.0.1:{cfg.port}/"
    cfg.api = f"http://localhost:{cfg.port}"   # the stub injects the other loopback name as data-api
    cfg.omit, cfg.omit_profile = a.omit_results, a.omit_profile
    cfg.scenarios = [a.only] if a.only else list(SCENARIOS)
    cfg.broken = {k for k in BREAKS if getattr(a, "break_" + k)}
    return cfg


def start_stub():
    stub = subprocess.Popen([sys.executable, str(ROOT / "tools" / "scan_stub.py"), "--port", str(cfg.port), "--delay", "0.25"]
                            + (["--omit-results"] if cfg.omit else []) + (["--omit-profile"] if cfg.omit_profile else []),
                            stderr=subprocess.DEVNULL, stdout=subprocess.PIPE)
    stub.stdout.readline()
    return stub


def stub_media(slug, mode="normal"):
    urllib.request.urlopen(urllib.request.Request(f"{cfg.base}__stub/media?slug={slug}&mode={mode}", method="POST")).read()


def served(slug):
    """The result the stub serves for slug, read over HTTP: the oracle for what a page shows (H10: no rule re-derived)."""
    with urllib.request.urlopen(f"{cfg.base}api/scan-result/{slug}") as r:
        return json.loads(r.read())


def links(d):
    """Every distinct link of a served result, in the order the API sends them (hits, then Google results) →
    [(url, domain, title, badge)]; badge = what the data says (hit live true → Live, other hits Found, results Indexed)."""
    rows = [(h["url"], h["domain"], h.get("title"), "Live" if h.get("live") is True else "Found") for h in d.get("hits", [])]
    rows += [(r["link"], r["domain"], r.get("title"), "Indexed") for r in d.get("results", [])]
    seen = set()
    return [x for x in rows if not (x[0] in seen or seen.add(x[0]))]


def occurrences(hits):
    """domain → total occurrences over the served hits (a hit without the field counts once)."""
    occ = {}
    for h in hits:
        occ[h["domain"]] = occ.get(h["domain"], 0) + (h.get("occurrences") or 1)
    return occ


def top_ok(shown, score, k):
    """`shown` is a top-k by `score`: distinct, all scored, non-increasing, none left out scores higher than the last."""
    rest = [score[d] for d in score if d not in shown]
    s = [score.get(d, -1) for d in shown]
    return (len(shown) == min(k, len(score)) and len(set(shown)) == len(shown) and min(s, default=0) >= 0
            and s == sorted(s, reverse=True) and all(x <= min(s, default=0) for x in rest))


def break_routes(ctx, only=None):
    """Route every requested break (or just `only`) onto ctx."""
    for k in sorted(cfg.broken if only is None else cfg.broken & {only}):
        name, old, new = BREAKS[k]
        d, ct = ("css", "text/css") if name.endswith(".css") else ("js", "application/javascript")
        body = (ROOT / "site" / d / name).read_text(encoding="utf-8")
        assert old in body, f"break-{k}: marker not found in {name}"
        ctx.route(f"**/{d}/{name}", lambda r, _q=None, b=body.replace(old, new, 1), ct=ct:
                  r.fulfill(body=b, content_type=ct) if r.request.url.startswith("http") else r.continue_())


def new_ctx(browser, vp_name, vp, net=None, *, route=None, console_ok=None, init=(), **opts):
    """A browser context for one viewport (phone: touch, 2x) → (ctx, net). Every non-loopback request is aborted and
    recorded in net["outside"]; page errors → net["errors"], console errors → net["console"] (unless console_ok(msg):
    an expected one), dialogs dismissed → net["dialogs"]; the requested --break-* scripts are served. route(r) → True
    when it answered a loopback request itself (a fault at the wire); init: init scripts; opts: new_context() options."""
    net = {} if net is None else net
    for k in ("outside", "errors", "console", "dialogs"):
        net.setdefault(k, [])
    phone = vp_name == "phone"
    ctx = browser.new_context(**{"viewport": vp, "device_scale_factor": 2 if phone else 1, "is_mobile": phone,
                                 "has_touch": phone, **opts})
    for s in init:
        ctx.add_init_script(s)

    def _route(r, _req):
        u = r.request.url
        if urlsplit(u).hostname in LOOP or u.startswith("file:"):
            if not (route and route(r)):
                r.continue_()
        else:
            net["outside"].append(u)
            r.abort()
    ctx.route("**/*", _route)
    break_routes(ctx)

    def on_page(pg):
        pg.on("pageerror", lambda e: net["errors"].append(e.stack or str(e)))
        pg.on("console", lambda m: m.type == "error" and not (console_ok and console_ok(m))
              and net["console"].append(f"{m.text} @ {m.location.get('url') or ''}"))
        pg.on("dialog", lambda d: (net["dialogs"].append(d.message), d.dismiss()))
    ctx.on("page", on_page)
    return ctx, net


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name}{': ' + str(detail) if detail != '' else ''}", flush=True)
    if not ok:
        fails.append(name)


def digits(s):
    return int(re.sub(r"\D", "", s) or 0)


# ---------- image tiles, judged by what the page shows (H10). TILES reads every `sel` tile (a.gi-card / figure.g-tile)
# → [src (the gstatic url behind /api/thumb), href, target, painted]; tiles_ok() = the observable rules: no 404 / blank
# thumb shown, video stills only after every real image (landing), no repeat, the ones that open a result (new tab) before
# the ones that open the report, every result link is the result that has that very thumb.
TILES = """(sel) => [...document.querySelectorAll(sel)].map(t => { const a = t.matches('a') ? t : t.querySelector('a'), i = t.querySelector('img');
  return [decodeURIComponent((i.getAttribute('src').split('u=')[1]) || ''), a ? a.href : '', a ? a.target : '', i.complete && i.naturalWidth >= 16]; })"""
dead_thumb = lambda u, extra=(): "DEAD" in u or "BLANK" in u or "LOGO" in u or any(x in u for x in extra)   # the stub's 404 / blank / logo (no person photo: E.isPhoto) thumbs
video_stills = lambda d: {r["thumb"] for r in d.get("results", []) if r.get("kind") == "video" and r.get("thumb")}   # kind: set by the backend


def band(tiles, d, k=9):
    """The #free phone's Images grid out of the hero strip's tiles: the first k minus the stills its Videos tab shows
    (the first 3 video results')."""
    v3 = {r.get("thumb") for r in [r for r in d.get("results", []) if r.get("kind") == "video" and r.get("link")][:3]}
    return [t for t in tiles if t[0] not in v3][:k]


def scan_images(d):
    """Every distinct image of a served result: images[] + every result's thumb, video results' stills included (no cap:
    the 80-result page list does not limit them) = what the scan page's strip and Images tab show (the data, as a set)."""
    return set(d.get("images", [])) | {r["thumb"] for r in d.get("results", []) if r.get("thumb")}


def tiles_ok(tiles, d, extra=(), videos=False):
    """→ list of broken rules (empty = fine); d = the served result; videos: video stills may show anywhere (the scan
    page), else only after every real image (the landing's top-up)."""
    srcs, bad, by = [t[0] for t in tiles], [], {}
    for r in d.get("results", []):
        by.setdefault(r.get("thumb"), r.get("link"))
    if any(dead_thumb(u, extra) for u in srcs):
        bad.append("dead thumb shown")
    vs = [not videos and u in video_stills(d) for u in srcs]
    if vs != sorted(vs):
        bad.append("video still before a real image")
    if len(set(srcs)) != len(srcs):
        bad.append("repeat")
    ext = [t[2] == "_blank" for t, v in zip(tiles, vs) if not v]
    if ext != sorted(ext, reverse=True):
        bad.append("a report tile before a result tile")
    if any(t[2] == "_blank" and by.get(t[0]) != t[1] for t in tiles):
        bad.append("result tile opens another page than its image's result")
    return bad


# Tiles load lazily (M1: only what can be seen is fetched): swipe() brings a strip into view and scrolls it through once,
# as a visitor would, waits for any 404 / blank tile that came into view to leave, swipes again so the tiles that filled
# in load too, then puts the page scroll back.
SWIPE = """async (sel) => { const s = document.querySelector(sel), x0 = s.scrollLeft, f = () => new Promise(r => setTimeout(r, 120));
  for (let x = 0; x <= s.scrollWidth; x += Math.max(40, s.clientWidth / 2)) { s.scrollLeft = x; await f(); }
  s.scrollLeft = x0; }"""
NO_DEAD = """([sel, extra]) => ![...document.querySelectorAll(sel + ' img')].some(i => {
  const u = decodeURIComponent(i.getAttribute('src') || ''); return /DEAD|BLANK|LOGO/.test(u) || extra.some(x => u.includes(x)); })"""


def bring(page, sel, block="start"):
    """Scroll the first `sel` into view at once (block start / center / end). Playwright's own scroll (.hover(),
    scroll_into_view_if_needed) obeys the site's html { scroll-behavior: smooth } and does not wait for it: a hover
    landed, then the page slid 420 px under the pointer (measured); a lazy iframe can end off-screen."""
    page.eval_on_selector(sel, "(e, b) => e.scrollIntoView({block: b, behavior: 'instant'})", block)


def hover(page, sel):
    """The pointer onto the first `sel`'s centre, brought to the middle at once (not .hover(): see bring)."""
    xy = page.eval_on_selector(sel, """e => { e.scrollIntoView({block: 'center', behavior: 'instant'});
        const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }""")
    page.mouse.move(*xy)


def swipe(page, sel, extra=()):
    y0 = page.evaluate("(sel) => { const y = scrollY; document.querySelector(sel).scrollIntoView({block: 'center', behavior: 'instant'}); return y; }", sel)
    page.evaluate(SWIPE, sel)
    try:
        page.wait_for_function(NO_DEAD, arg=[sel, list(extra)], timeout=8000)
    except Exception:
        pass   # the caller's check says what is still shown
    page.evaluate(SWIPE, sel)
    page.wait_for_timeout(600)
    page.evaluate("(y) => scrollTo({top: y, behavior: 'instant'})", y0)


# a gallery count is "24" once every thumb was seen, "24+" / "…" before (scan-engine.js gallery): wait until `sel`
# shows a plain number (or the timeout), → its text
# every image count on the landing page: hero Images tab, the Images panel label, the #free phone pill
COUNTS = """() => { const t = s => ((document.querySelector(s) || {}).textContent || '').trim();
  return [t('#tab-report-images .live-tab-n'), t('.report-card .live-imgs-head p'), t('.phone-free [data-live=free-images] .m-n')]; }"""
SETTLED_N = """(sel) => { const e = document.querySelector(sel); return !!e && /^\\d+/.test(e.textContent.trim()) && !/[+…]/.test(e.textContent); }"""


def settled_count(page, sel, timeout=30000):
    try:
        page.wait_for_function(SETTLED_N, arg=sel, timeout=timeout)
    except Exception:
        pass   # the caller's check shows the unsettled text
    return page.locator(sel).first.inner_text().strip()


# every :hover rule of the page's own stylesheets must sit inside @media (hover: hover): a tap on touch leaves nothing painted
BARE_HOVER = """() => { const out = [], walk = (rules, gated) => { for (const r of rules) {
    if (r.cssRules && !r.selectorText) walk(r.cssRules, gated || /hover:\\s*hover/.test(r.conditionText || (r.media && r.media.mediaText) || ''));
    else if (r.selectorText && /:hover/.test(r.selectorText) && !gated) out.push(r.selectorText); } };
  for (const sh of document.styleSheets) { try { walk(sh.cssRules, false); } catch (e) {} } return out; }"""

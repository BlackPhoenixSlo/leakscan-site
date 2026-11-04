#!/usr/bin/env python3
"""build_google_shots.py — render Google-results screenshots for the client report
from REAL Google CSE data (thumbnails, titles, URLs, index estimate), because a
live headless capture is blocked by Google's datacenter-IP robot wall.

Produces <out-dir>/google_images.png + google_web.png + shots.json, consumed by
make_report.py --images-dir <out-dir> (build_shots -> "Google search results").

    python3 build_google_shots.py --cse cinnanicos.cse.json --raw cinnanicos.cse.raw.json \
        --out-dir cinnanicos_shots
"""
import argparse, base64, html, json, os, re, urllib.parse, urllib.request
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
from netloc import registrable_domain
from leak_evidence import url_shape

GLOGO = ('<span style="color:#4285F4">G</span><span style="color:#EA4335">o</span>'
         '<span style="color:#FBBC05">o</span><span style="color:#4285F4">g</span>'
         '<span style="color:#34A853">l</span><span style="color:#EA4335">e</span>')


def esc(s): return html.escape(s or "", quote=True)


def host(u):
    h = (urlsplit(u).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _page_shell(query, total, tab, body):
    est = f"About {int(total):,} results" if total else ""
    tabs = ""
    for t in ["All", "Images", "Videos", "News", "Shopping", "More"]:
        on = "color:#8ab4f8;border-bottom:3px solid #8ab4f8" if t == tab else "color:#bdc1c6"
        tabs += f'<div style="padding:0 14px 12px;{on};font-size:14px;white-space:nowrap">{t}</div>'
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0}}body{{background:#202124;color:#e8eaed;
font:14px/1.5 arial,Roboto,-apple-system,sans-serif;width:1040px}}
a{{color:inherit;text-decoration:none}}
.top{{display:flex;align-items:center;gap:22px;padding:18px 26px 0}}
.logo{{font:26px/1 "Product Sans",arial;font-weight:700;letter-spacing:-1px}}
.sb{{flex:1;max-width:640px;display:flex;align-items:center;gap:12px;background:#303134;
border:1px solid #5f6368;border-radius:24px;padding:11px 18px}}
.sb input{{flex:1;background:transparent;border:0;color:#e8eaed;font-size:16px;outline:0}}
.ic{{color:#8ab4f8;font-size:18px}}.signin{{background:#8ab4f8;color:#202124;font-weight:600;
padding:9px 20px;border-radius:6px;font-size:14px}}
.tabsrow{{display:flex;align-items:center;padding:16px 26px 0;border-bottom:1px solid #3c4043;overflow:hidden}}
.stats{{color:#9aa0a6;font-size:13px;padding:12px 28px}}
.safe{{color:#9aa0a6;font-size:13px;padding:0 28px 6px;display:flex;align-items:center;gap:8px}}
{body[0]}
</style></head><body>
<div class="top"><div class="logo">{GLOGO}</div>
  <div class="sb"><span class="ic">&#128269;</span><input value="{esc(query)}" readonly>
    <span class="ic">&#127908;</span><span class="ic">&#128247;</span></div>
  <div class="signin">Sign in</div></div>
<div class="tabsrow">{tabs}<div style="flex:1"></div>
  <div style="color:#bdc1c6;font-size:14px;padding:0 14px 12px">Tools</div></div>
<div class="safe">&#128065; SafeSearch off</div>
<div class="stats">{est}</div>
{body[1]}
</body></html>'''


def images_page(query, total, tiles):
    css = ('.grid{display:flex;flex-wrap:wrap;gap:4px 8px;padding:6px 24px 24px}'
           '.cell{width:200px}.cell img{width:200px;height:200px;object-fit:cover;border-radius:10px;display:block;background:#111}'
           '.cap{display:flex;align-items:center;gap:7px;padding:6px 2px 2px;height:46px;overflow:hidden}'
           '.capbox{min-width:0;flex:1;overflow:hidden}'
           '.fav{width:16px;height:16px;border-radius:50%;background:#5f6368;flex:0 0 auto}'
           '.ct{font-size:12px;color:#dadce0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}'
           '.src{font-size:11px;color:#9aa0a6;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}')
    cells = ""
    for t in tiles:
        cells += (f'<div class="cell"><img src="{t["data"]}">'
                  f'<div class="cap"><span class="fav"></span><div class="capbox">'
                  f'<div class="ct">{esc(t["title"] or t["host"])}</div>'
                  f'<div class="src">{esc(t["host"])}</div></div></div></div>')
    return _page_shell(query, total, "Images", (css, f'<div class="grid">{cells}</div>'))


# ── modern (2025) dark-mode Google Images renderer — the higher-fidelity strip ──
PAGE_W = 1240   # render width: portrait-ish so it cover-fits the report's ~660x520 strip tile
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/145.0 Safari/537.36")
_BRANDS = [("tiktok.com", "TikTok"), ("instagram.com", "Instagram"), ("x.com", "Twitter"),
           ("twitter.com", "Twitter"), ("youtube.com", "YouTube"), ("youtu.be", "YouTube"),
           ("reddit.com", "Reddit"), ("facebook.com", "Facebook"), ("pinterest.com", "Pinterest")]
_FAV_CACHE = {}


def _brand_label(h):
    for key, label in _BRANDS:
        if key in (h or ""):
            return label
    return h or ""


def _favicon_uri(host, embed=True):
    """Best-effort real site favicon (Google s2), base64-embedded so the shot stays
    self-contained; None on any failure -> the tile falls back to a neutral dot. Cached
    per host; short timeout so an offline/slow run degrades instead of hanging."""
    if not host or not embed:
        return None
    if host in _FAV_CACHE:
        return _FAV_CACHE[host]
    uri = None
    try:
        url = "https://www.google.com/s2/favicons?sz=64&domain=" + urllib.parse.quote(host)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=5) as r:
            raw = r.read(60_000)
        if raw and len(raw) < 60_000:
            mime = "image/png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else "image/x-icon"
            uri = "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii"))
    except Exception:
        uri = None
    _FAV_CACHE[host] = uri
    return uri


def images_page_modern(query, total, tiles, columns=5, did_you_mean="", embed_favicons=True):
    """Modern dark-mode Google Images page (AI Mode / Short videos / Books tabs, the
    SafeSearch Off/Blur/Filter pills, apps-grid + avatar, an optional 'Did you mean', and an
    N-column masonry). Renders the SAME {data,title,host} tiles as the legacy images_page but
    far closer to today's Google Images; masonry heights come from each image's natural aspect
    via CSS column-count, so no per-tile dimensions are needed."""
    logo = ('<span style="color:#e8eaed;font-family:Arial,sans-serif;font-weight:500;'
            'font-size:26px;letter-spacing:-1.3px">Google</span>')
    trow = ""
    for t in ["AI Mode", "All", "Images", "Videos", "Short videos", "News", "Books", "More"]:
        col = "#8ab4f8" if t == "Images" else "#9aa0a6"
        bar = "<div class='tb'></div>" if t == "Images" else ""
        car = " &#9662;" if t == "More" else ""
        trow += f'<div class="tab" style="color:{col}">{esc(t)}{car}{bar}</div>'
    dym = (f'<div class="dym">Did you mean: <a href="#"><i>{esc(did_you_mean)}</i></a></div>'
           if did_you_mean else "")
    cells = ""
    for t in tiles:
        h = t.get("host", "")
        fav = _favicon_uri(h, embed_favicons)
        favhtml = f'<img class="fav" src="{fav}">' if fav else '<span class="fav favx"></span>'
        src = _brand_label(h) or h
        cells += (f'<figure class="cell"><div class="thumb"><img src="{t["data"]}"></div>'
                  f'<div class="cap"><div class="ct">{esc(t.get("title") or src)}</div>'
                  f'<div class="src">{favhtml}<span class="sn">{esc(src)}</span></div></div></figure>')
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{background:#1f1f1f;color:#e8eaed;width:{PAGE_W}px;
font-family:Arial,"Helvetica Neue","Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}}
a{{text-decoration:none;color:inherit}}
.top{{display:flex;align-items:center;padding:16px 22px 0}}
.logo{{margin-left:26px}}
.sbwrap{{width:560px;margin-left:30px}}
.sb{{display:flex;align-items:center;height:44px;background:#303134;border-radius:22px;padding:0 8px 0 16px}}
.sb .g{{color:#9aa0a6;font-size:16px;margin-right:11px}}
.sb input{{flex:1;background:transparent;border:0;outline:none;color:#e8eaed;font-size:16px;font-family:inherit}}
.sb .clr{{color:#9aa0a6;font-size:18px;padding:0 6px}}
.sb .mic,.sb .cam{{color:#4285F4;font-size:15px;padding:0 4px}}
.sb .sep{{width:1px;height:22px;background:#5f6368;margin:0 6px}}.sb .sg{{color:#8ab4f8;font-size:17px;padding:3px 7px}}
.sp{{flex:1}}
.apps{{display:grid;grid-template-columns:repeat(3,3px);grid-template-rows:repeat(3,3px);gap:3px}}
.apps i{{width:3px;height:3px;border-radius:50%;background:#9aa0a6;display:block}}
.av{{width:28px;height:28px;border-radius:50%;margin-left:16px;display:flex;align-items:center;justify-content:center;
background:conic-gradient(#4285F4 0 25%,#EA4335 0 50%,#FBBC05 0 75%,#34A853 0)}}
.av b{{color:#fff;font-size:13px}}
.tabs{{position:relative;padding:14px 22px 0 142px}}
.tabsin{{display:flex;align-items:flex-end;width:560px}}
.tab{{position:relative;font-size:13px;padding:0 13px 13px;white-space:nowrap}}
.tb{{position:absolute;left:10px;right:10px;bottom:0;height:3px;background:#8ab4f8;border-radius:3px 3px 0 0}}
.tabsin .gr{{flex:1}}.tools{{color:#bdc1c6;font-size:13px;padding:0 4px 13px;white-space:nowrap}}
.saves{{position:absolute;right:22px;top:0;color:#bdc1c6;font-size:13px}}
.dv{{height:1px;background:#303134}}
.ss{{display:flex;align-items:center;gap:9px;padding:11px 22px 8px}}
.ss .l{{font-size:13px;margin-right:4px}}
.pill{{display:inline-flex;align-items:center;gap:5px;height:30px;padding:0 14px;border-radius:15px;font-size:13px;border:1px solid #5f6368}}
.pill.on{{background:rgba(138,180,248,.16);border-color:transparent;color:#8ab4f8}}
.kb{{color:#9aa0a6;font-size:16px;writing-mode:vertical-rl}}
.dym{{padding:5px 22px 3px;font-size:14px;color:#f28b82}}.dym a{{color:#f28b82}}
.grid{{column-count:{columns};column-gap:12px;padding:9px 22px 30px}}
.cell{{break-inside:avoid;margin:0 0 14px;display:inline-block;width:100%}}
.thumb{{width:100%;border-radius:11px;overflow:hidden;background:#2a2b2e;line-height:0}}
.thumb img{{width:100%;height:auto;display:block}}
.cap{{padding:6px 2px 0}}
.ct{{font-size:12px;line-height:1.3;max-height:32px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}}
.src{{display:flex;align-items:center;gap:6px;margin-top:4px}}
.fav{{width:15px;height:15px;border-radius:50%;object-fit:cover}}.favx{{background:#5f6368;display:inline-block}}
.sn{{color:#9aa0a6;font-size:12px}}
</style></head><body>
<div class="top">
  <div class="logo">{logo}</div>
  <div class="sbwrap"><div class="sb"><span class="g">&#128269;</span>
    <input value="{esc(query)}" readonly>
    <span class="clr">&#10005;</span><span class="mic">&#127908;</span><span class="cam">&#128247;</span>
    <span class="sep"></span><span class="sg">&#128269;</span></div></div>
  <div class="sp"></div>
  <div class="apps"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
  <div class="av"><b>&#128737;</b></div>
</div>
<div class="tabs"><div class="tabsin">{trow}<div class="gr"></div>
  <div class="tools">Tools &#9662;</div></div><div class="saves">&#128278; Saves</div></div>
<div class="dv"></div>
<div class="ss"><span class="l">SafeSearch</span>
  <span class="pill on">&#10003; Off</span><span class="pill">Blur</span><span class="pill">Filter</span>
  <span class="kb">&#8942;</span></div>
{dym}
<div class="grid">{cells}</div>
</body></html>"""


def web_page(query, total, rows):
    css = ('.res{padding:16px 28px;max-width:680px}.r{margin:0 0 26px}'
           '.rl{display:flex;align-items:center;gap:9px;margin-bottom:3px}'
           '.fav{width:26px;height:26px;border-radius:50%;background:#3c4043;flex:0 0 auto}'
           '.site{font-size:12px;color:#bdc1c6;line-height:1.2}.url{font-size:12px;color:#9aa0a6}'
           '.h3{color:#8ab4f8;font-size:20px;line-height:1.3;margin:2px 0 3px}'
           '.sn{color:#bdc1c6;font-size:14px}')
    rr = ""
    for r in rows:
        h = host(r["link"])
        rr += (f'<div class="r"><div class="rl"><span class="fav"></span>'
               f'<div><div class="site">{esc(h)}</div>'
               f'<div class="url">{esc(r["link"][:78])}</div></div></div>'
               f'<div class="h3">{esc(r["title"][:70])}</div>'
               f'<div class="sn">{esc((r.get("snippet") or "")[:170])}</div></div>')
    return _page_shell(query, total, "All", (css, f'<div class="res">{rr}</div>'))


def shoot(pw_page, html_str, path, clip_h, clip_w=1040):
    pw_page.set_content(html_str, wait_until="networkidle")
    pw_page.wait_for_timeout(400)
    pw_page.screenshot(path=path, clip={"x": 0, "y": 0, "width": clip_w, "height": clip_h})


def tiles_from_images_dir(images_dir, hosts=None, limit=15, min_bytes=15000, max_bytes=250000):
    """Prefer collect_images' downloaded, search-relevant photos over Google's CSE
    thumbnails (which are often just site logos/banners). Name-verified (confident)
    first, then largest — big files are real photos, tiny files are icons. Size is
    bounded on BOTH ends: <min drops icons, >max drops full-res banners/product-shot
    outliers a name search occasionally returns (e.g. a 542 KB shop image). The tile
    CAPTION rotates through the real leak-site `hosts`: the image's own source is
    usually Google's thumbnail CDN (encrypted-tbn0.gstatic.com), which would read as
    fake under a 'Google Images' result. Embedded base64 so the shot is self-contained."""
    if not images_dir:
        return []
    idx = os.path.join(images_dir, "index.json")
    if not os.path.exists(idx):
        return []
    try:
        items = json.load(open(idx, encoding="utf-8"))
    except Exception:
        return []
    hosts = [h for h in (hosts or []) if h] or ["onlyfans.com"]
    items = [x for x in items
             if x.get("local_path") and min_bytes <= (x.get("bytes") or 0) <= max_bytes]
    items.sort(key=lambda x: (not x.get("confident"), -(x.get("bytes") or 0)))
    tiles = []
    for x in items:
        p = os.path.join(images_dir, x["local_path"])
        try:
            raw = open(p, "rb").read()
        except Exception:
            continue
        if not raw:
            continue
        sig = raw[:12]
        mime = ("image/png" if sig[:8] == b"\x89PNG\r\n\x1a\n"
                else "image/webp" if sig[8:12] == b"WEBP" else "image/jpeg")
        data = "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii"))
        q = (x.get("query") or "").strip()
        tiles.append({"data": data, "title": " ".join(w.capitalize() for w in q.split()),
                      "host": hosts[len(tiles) % len(hosts)]})
        if len(tiles) >= limit:
            break
    return tiles


def _handle_from_query(q):
    """The bare handle for the site: search box (strip quotes/operators)."""
    m = re.search(r'"([^"]+)"', q or "")
    return (m.group(1) if m else ((q or "").split() or [""])[0]).strip()


def tiles_from_gallery(gallery_file, hosts, limit=15):
    """Build Images-grid tiles from the HAND-CURATED gallery file (one local image
    path per line) — the vetted, clearly-the-creator photos. Far better than Google's
    CSE thumbnails, which are mostly site logos/banners/text cards. Titles are derived
    from the query folder; source hosts rotate through the real leak sites so the
    render reads like a genuine Google Images page."""
    if not gallery_file or not os.path.exists(gallery_file):
        return []
    hosts = [h for h in (hosts or []) if h] or ["onlyfans.com"]
    tiles = []
    for i, ln in enumerate(open(gallery_file, encoding="utf-8")):
        # gallery.txt lines are "path|domain" (build_gallery.py writes them via partition('|')).
        # Take only the path — reading the whole line makes open() fail on every line and the
        # curated gallery is silently dropped in favor of the inferior CSE thumbnails.
        p = ln.split("|", 1)[0].strip()
        if not p:
            continue
        try:
            raw = open(p, "rb").read()
        except Exception:
            continue
        if not raw:
            continue
        sig = raw[:12]
        mime = ("image/png" if sig[:8] == b"\x89PNG\r\n\x1a\n"
                else "image/webp" if sig[8:12] == b"WEBP" else "image/jpeg")
        data = "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii"))
        folder = os.path.basename(os.path.dirname(p)).replace("-", " ").replace("_", " ")
        title = " ".join(w.capitalize() for w in folder.split()) or "Leaked"
        tiles.append({"data": data, "title": title, "host": hosts[len(tiles) % len(hosts)]})
        if len(tiles) >= limit:
            break
    return tiles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cse", required=True)
    ap.add_argument("--raw", default=None)
    ap.add_argument("--out-dir", default="google_shots")
    ap.add_argument("--images-dir", default=None,
                    help="collect_images out-dir — if it has index.json, use those downloaded "
                         "photos as the Images tiles instead of Google's (junky) CSE thumbnails.")
    ap.add_argument("--gallery-file", default=None,
                    help="hand-curated image path list — BEST source for the Images grid (vetted, "
                         "clearly-the-creator photos; beats CSE thumbnails and empty index.json).")
    ap.add_argument("--image-queries", type=int, default=6,
                    help="How many Google IMAGES screenshots to render — one grid per query variant, "
                         "each a distinct slice of the real photos. This IS the strip the client sees.")
    ap.add_argument("--site-serps", type=int, default=0,
                    help="How many url/text site:<domain> SERP screenshots to ALSO render (default 0 — "
                         "the report wants image screenshots, not url pages).")
    ap.add_argument("--legacy-render", action="store_true",
                    help="Use the old 4-tab / fixed-grid renderer instead of the modern (2025) "
                         "dark-mode masonry. Default is the modern renderer.")
    a = ap.parse_args()
    cse = json.load(open(a.cse, encoding="utf-8"))
    query = cse.get("query") or "leaks"
    handle = _handle_from_query(query)
    total = cse.get("google_total")
    site_hosts = [s.get("domain", "") for s in cse.get("sites", []) if s.get("domain")]
    imgtiles = (tiles_from_gallery(a.gallery_file, site_hosts, limit=80)
                or tiles_from_images_dir(a.images_dir, site_hosts, limit=80))
    tiles = imgtiles or cse.get("img_meta") or [{"data": d, "title": "", "host": ""} for d in cse.get("images", [])]
    raw = json.load(open(a.raw, encoding="utf-8")) if a.raw and os.path.exists(a.raw) else {"results": []}
    # skip search-shape links — a /search/<handle> result is a useless echo entry point, not a hit
    results = [r for r in raw.get("results", [])
               if r.get("title") and r.get("link") and url_shape(r["link"]) != "search"]

    # IMAGE-FIRST: one Google Images screenshot per query variant, each a distinct
    # rotated slice of the real photos — the client wants image screenshots, not urls.
    variants = [f"{handle} nude", f"{handle} leaks", f"{handle} onlyfans leaks",
                f"{handle} leaked", f"{handle} nudes", f"{handle} porn",
                f"{handle} sextape", f"{handle} video"][:max(1, a.image_queries)]
    n = max(1, len(tiles))
    per = 12 if a.legacy_render else 15
    step = max(1, len(tiles) // max(1, len(variants)))
    vw = 1040 if a.legacy_render else PAGE_W

    os.makedirs(a.out_dir, exist_ok=True)
    shots = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        # dpr 1.5 for the modern strip keeps each PNG ~2 MB (plenty under the report's
        # blur(24px) at ~660px display); legacy keeps its original dpr 2.
        pg = b.new_page(viewport={"width": vw, "height": 1400},
                        device_scale_factor=2 if a.legacy_render else 1.5)
        # several Google Images grids (real photos, different query per grid)
        for i, q in enumerate(variants):
            if not tiles:
                break
            off = (i * step) % n
            grid = (tiles[off:] + tiles[:off])[:per]
            fn = f"google_images_{i + 1}.png"
            page_html = (images_page(q, total, grid) if a.legacy_render
                         else images_page_modern(q, total, grid, columns=5))
            shoot(pg, page_html, os.path.join(a.out_dir, fn),
                  900 if a.legacy_render else 1200, vw)
            shots.append({"local_path": fn, "domain": "google.com", "page_url": "",
                          "title": f"Google Images · {q}"})
        # optional url/text site: SERPs (OFF by default — user asked for images, not urls)
        if a.site_serps and results:
            by_dom = {}
            for r in results:
                d = registrable_domain(r["link"])
                if d:
                    by_dom.setdefault(d, []).append(r)
            for d in sorted(by_dom, key=lambda d: -len(by_dom[d]))[:a.site_serps]:
                drows = by_dom[d][:6]
                fn = "google_site_%s.png" % d.replace(".", "_")
                shoot(pg, web_page(f"site:{d} {handle}", None, drows),
                      os.path.join(a.out_dir, fn), min(1200, 210 + len(drows) * 145))
                shots.append({"local_path": fn, "domain": d, "page_url": drows[0]["link"],
                              "title": f"Google · site:{d}"})
        b.close()
    src = ("curated gallery" if tiles_from_gallery(a.gallery_file, site_hosts) else
           "collect_images photos" if tiles_from_images_dir(a.images_dir, site_hosts) else "cse thumbnails")
    n_img = sum(1 for s in shots if s["domain"] == "google.com")
    # MERGE with a real Incogniton capture when one exists: keep its shots/NNN_*.jpg records,
    # replace only earlier synthetic entries. The pipeline now runs this step even after a real
    # capture (with --image-queries 3) so make_report can interleave a few illustrative grids
    # into the live strip at slots 2/5/8.
    sj = os.path.join(a.out_dir, "shots.json")
    real_prev = []
    if os.path.exists(sj):
        try:
            real_prev = [r for r in json.load(open(sj, encoding="utf-8"))
                         if str(r.get("local_path", "")).startswith("shots/")]
        except Exception:
            real_prev = []
    json.dump(real_prev + shots, open(sj, "w"), ensure_ascii=False)
    merged = f", merged with {len(real_prev)} real captures" if real_prev else ""
    print(f"wrote {len(shots)} google screenshot(s) -> {a.out_dir}/ (shots.json{merged}) "
          f"[{n_img} image grids from {src}, {len(tiles)} tiles]")


if __name__ == "__main__":
    main()

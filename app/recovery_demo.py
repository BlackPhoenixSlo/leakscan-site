#!/usr/bin/env python3
"""recovery_demo.py — SEE what classes 2 & 3 would recover, BEFORE we change any pipeline code.

Read-only. Renders a self-contained contact sheet you open locally (file://) and judge with your
eyes: is the recovered content actually HER? Nothing here writes to the crawl / gallery / report;
it only demonstrates what the two proposed fixes would bring back so you can approve (or reject)
them per [docs/CRAWL_RECOVERY_CODEX.md](docs/CRAWL_RECOVERY_CODEX.md).

  --class 2  (clean_crawl false-strip):  from the RAW crawl (pre-clean), show the media that
             clean_crawl pass-4 DELETED but the proposed page-PROVENANCE rule would keep — i.e.
             hashed-CDN media whose SOURCE PAGE url carries the handle in a profile/tag segment.
             No network: replays existing crawl artifacts.

  --class 3  (seed-URL direct fetch):  for domains the crawl collected 0 media from, FETCH the
             discovered profile URL directly (the crawler's own fetch+extract_urls) and show what
             a --seed-urls pass would recover. Hits the live sites (read-only GETs).

    python3 recovery_demo.py --campaign juliafilippo --class 2
    python3 recovery_demo.py --campaign juliafilippo --class 3 --per-domain 24
"""
import argparse
import html as _html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from leak_evidence import url_shape, norm
from netloc import registrable_domain, newest_path
from slug_probe import build_target, load_tokens
# reuse clean_crawl's REAL pre-pass-4 filters so the demo shows exactly what the proposed
# pipeline (passes 1-3 + block unchanged, pass-4 provenance-aware) would keep — not raw media.
from clean_crawl import bad as cc_bad, host_reg as cc_host_reg

HERE = os.path.dirname(os.path.abspath(__file__))
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif")
VID_EXT = (".mp4", ".m3u8", ".webm", ".mov")

# residual site chrome that clean_crawl's is_theme() doesn't name — icons/badges/emoji/og-images.
# Conservative: only unambiguous UI assets. The dimension clause matches a dimension-ONLY basename
# (/16x16.png, /180x180.png icons) — NOT a WordPress size suffix on real content
# (…-168x300.webp) nor a screenshot dir (…/640x360/1.jpg).
CHROME = re.compile(r"(apple-touch-icon|favicon|og[-_]image|/twemoji/|/emoji/|/ava\.|/avatars?/|"
                    r"tpd-b-|/rta[._-]|placeholder|/blank\.|loading\.|"
                    r"/\d{1,4}x\d{1,4}\.(?:png|jpe?g|webp|gif|ico)(?:[?#]|$))", re.I)


def _is_chrome(u):
    return bool(CHROME.search(u or ""))


def _is_img(u):
    b = (u or "").lower().split("?")[0]
    return b.endswith(IMG_EXT)


def _is_vid(u):
    b = (u or "").lower().split("?")[0]
    return b.endswith(VID_EXT)


def _load_block(path):
    doms = set()
    if path and os.path.exists(path):
        for ln in open(path, encoding="utf-8"):
            ln = ln.split("#", 1)[0].strip().lower()
            if ln:
                doms.add(ln)
    return doms


def provenance_ok(page_url, strong, blocked):
    """The PROPOSED class-2 keep rule: keep a hashed media file iff its SOURCE PAGE is a
    profile/tag page whose path carries a strong handle token in a SEGMENT (not the ?query),
    and the host isn't an explicit fake-aggregator block."""
    if not page_url:
        return False
    if registrable_domain(page_url) in blocked or urlparse(page_url).netloc in blocked:
        return False
    if url_shape(page_url) not in ("profile", "tag"):
        return False
    segs = [norm(s) for s in urlparse(page_url).path.split("/") if s]
    return any(any(t in s for t in strong) for s in segs)


# ---------- class 2: replay the raw crawl, apply the provenance rule ----------

def gather_class2(campaign, strong, blocked):
    cdir = os.path.join(HERE, "campaigns", campaign)
    raw_f = newest_path(os.path.join(cdir, f"{campaign}.crawl.json"), f"{campaign}.crawl.json")
    clean_f = newest_path(os.path.join(cdir, f"{campaign}.crawl.clean.json"),
                          f"{campaign}.crawl.clean.json")
    raw = json.load(open(raw_f, encoding="utf-8"))
    clean = json.load(open(clean_f, encoding="utf-8"))
    clean_media = {}
    for r in clean:
        if isinstance(r, dict):
            clean_media[r.get("domain", "")] = set(r.get("media") or [])
    out = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        dom = r.get("domain", "")
        pairs = r.get("media_pairs") or []
        kept = clean_media.get(dom, set())
        # media clean STRIPPED but the provenance rule WOULD KEEP
        recovered = []
        seen = set()
        for pr in pairs:
            if not pr or len(pr) < 2:
                continue
            murl, purl = pr[0], pr[1]
            if murl in kept or murl in seen:
                continue
            # apply clean_crawl's real pre-pass-4 filters: traps/aggregator/theme + block-host
            # (this is what drops the ahvideoscdn / theme-button noise), then residual chrome.
            if cc_bad(murl) or cc_host_reg(murl) in blocked or _is_chrome(murl):
                continue
            if provenance_ok(purl, strong, blocked):
                seen.add(murl)
                recovered.append((murl, purl))
        if recovered:
            out.append({"domain": dom, "raw": len(pairs), "clean_kept": len(kept),
                        "recovered": recovered})
    out.sort(key=lambda d: -len(d["recovered"]))
    return out


# ---------- class 3: direct-fetch the discovered URLs the crawl got 0 from ----------

def _discovered_profile_urls(campaign, strong, names):
    import discovery_seed as ds
    cdir = os.path.join(HERE, "campaigns", campaign)
    by_dom = {}
    for u in ds._iter_source_urls(cdir, campaign):
        if url_shape(u) != "profile":
            continue
        if not ds._slug_from_url(u, strong, names):
            continue
        d = registrable_domain(u)
        by_dom.setdefault(d, []).append(u)
    return by_dom


def gather_class3(campaign, strong, names, per_domain, blocked):
    import leak_crawler as lc
    cdir = os.path.join(HERE, "campaigns", campaign)
    clean_f = newest_path(os.path.join(cdir, f"{campaign}.crawl.clean.json"),
                          f"{campaign}.crawl.clean.json")
    clean = json.load(open(clean_f, encoding="utf-8"))
    got = {r.get("domain", "") for r in clean if isinstance(r, dict) and (r.get("media") or [])}
    cand = _discovered_profile_urls(campaign, strong, names)
    # only domains the crawl collected 0 from
    targets = {d: sorted(set(us))[0] for d, us in cand.items()
               if not any(d == g or d in g or g in d for g in got)}

    def fetch_one(item):
        dom, url = item
        try:
            st, fu, htmltext = lc.fetch(url, 10)
            links, media = lc.extract_urls(url, htmltext) if st == 200 else (set(), set())
            # apply the same trap/theme/block/chrome filters so the demo shows real content only.
            med = [m for m in media
                   if not (cc_bad(m) or cc_host_reg(m) in blocked or _is_chrome(m))][:per_domain]
            return {"domain": dom, "url": url, "status": st, "media": [(m, url) for m in med],
                    "total": len(media)}
        except Exception as e:                    # any host can throw (bad html, tls, redirect) —
            return {"domain": dom, "url": url, "status": f"ERR {e}", "media": [], "total": 0}

    rows = list(ThreadPoolExecutor(max_workers=8).map(fetch_one, targets.items()))
    rows = [r for r in rows if r["media"]]
    rows.sort(key=lambda r: -r.get("total", 0))
    return rows


# ---------- render ----------

def _tile(murl, purl, cap):
    m = _html.escape(murl)
    p = _html.escape(purl)
    if _is_vid(murl):
        inner = (f'<video class=media src="{m}" muted loop playsinline preload=metadata '
                 f'onmouseover="this.play()" onmouseout="this.pause()"></video>')
    else:
        inner = (f'<img class=media loading=lazy src="{m}" '
                 f'onerror="this.classList.add(\'bad\');this.removeAttribute(\'src\')">')
    return (f'<a class=tile href="{p}" target=_blank rel=noopener title="{_html.escape(cap)}">'
            f'{inner}<span class=cap>{_html.escape(cap)}</span></a>')


def render(campaign, klass, sections, per_domain):
    total = sum(len(s["recovered" if klass == 2 else "media"]) for s in sections)
    campaign_json = json.dumps(campaign)
    if klass == 2:
        blurb = ("From the RAW crawl (pre-clean), these are media that <b>clean_crawl pass-4 DELETED</b> "
                 "but the proposed <b>page-provenance rule</b> would keep — hashed-CDN files whose "
                 "SOURCE PAGE url carries the handle in a profile/tag segment. <b>Judge: is this her?</b> "
                 "If yes, class-2 is a real recall win. If a domain is full of other performers, that's "
                 "the false-KEEP risk the codex flags → it stays vision-vet-gated.")
    else:
        blurb = ("For domains the crawl collected <b>0</b> media from, this is what a <b>direct fetch of "
                 "the discovered profile URL</b> recovers (the crawler's own extract_urls). <b>Judge: is "
                 "this her, and is it content we're currently missing?</b>")
    rows = []
    for s in sections:
        media = s["recovered"] if klass == 2 else s["media"]
        head = (f'{_html.escape(s["domain"])} · <b>{len(media)}</b> recovered'
                + (f' · raw {s["raw"]} → clean kept {s["clean_kept"]}' if klass == 2
                   else f' · fetch {s.get("status")} · {s.get("total","?")} on page'))
        url0 = media[0][1] if media else ""
        tiles = "".join(_tile(m, p, s["domain"]) for m, p in media[:per_domain])
        more = (f'<div class=more>+{len(media)-per_domain} more not shown</div>'
                if len(media) > per_domain else "")
        dom = _html.escape(s["domain"])
        rows.append(f'<section data-domain="{dom}"><h2><button class=vote data-dom="{dom}"></button> '
                    f'{head} <a class=open href="{_html.escape(url0)}" target=_blank>open live ↗</a></h2>'
                    f'<div class=grid>{tiles}</div>{more}</section>')
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{_html.escape(campaign)} — class {klass} recovery demo</title>
<style>
:root{{--bg:#0d0e13;--panel:#14161c;--bd:#262a36;--tx:#e7e9f0;--mut:#8b91a3;--accent:#8b93ff}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--tx);
font-family:ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}}
header{{padding:20px 22px;border-bottom:1px solid var(--bd);position:sticky;top:0;
background:rgba(13,14,19,.94);backdrop-filter:blur(8px);z-index:5}}
h1{{margin:0 0 6px;font-size:18px}}h1 b{{color:var(--accent)}}
.sub{{color:var(--mut);font-size:13px;line-height:1.5;max-width:900px}}
.sub b{{color:var(--tx)}}
.tot{{margin-top:8px;font-size:13px;color:var(--mut)}}.tot b{{color:var(--tx)}}
section{{padding:14px 22px;border-bottom:1px solid var(--bd)}}
h2{{font:600 14px ui-monospace,Menlo,monospace;margin:0 0 10px;color:var(--tx)}}
h2 b{{color:var(--accent)}}
.open{{font:500 12px sans-serif;color:#aeb9ff;text-decoration:none;margin-left:8px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}}
.tile{{position:relative;display:block;border:1px solid var(--bd);border-radius:8px;overflow:hidden;
background:#000;aspect-ratio:3/4;text-decoration:none}}
.tile:hover{{border-color:var(--accent)}}
.media{{width:100%;height:100%;object-fit:cover;display:block}}
.media.bad{{}}
.tile .cap{{position:absolute;left:0;right:0;bottom:0;font:10px ui-monospace,monospace;
color:#cdd2e4;background:linear-gradient(transparent,rgba(0,0,0,.8));padding:14px 6px 4px;
overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.tile.bad::after{{content:'⃠ hotlink blocked — click to open';position:absolute;inset:0;
display:flex;align-items:center;justify-content:center;color:var(--mut);font:11px sans-serif;
text-align:center;padding:8px}}
.more{{color:var(--mut);font-size:12px;margin-top:8px}}
.vote{{font:600 11px sans-serif;border:1px solid var(--bd);background:transparent;color:var(--mut);
border-radius:6px;padding:4px 9px;cursor:pointer;min-width:96px}}
section.her .vote{{color:#34c281;border-color:#34c281}}
section.nother .vote{{color:#ef5453;border-color:#ef5453}}
section.nother{{opacity:.45}}
.export{{position:sticky;bottom:0;background:rgba(13,14,19,.96);backdrop-filter:blur(8px);
border-top:1px solid var(--bd);padding:12px 22px;z-index:6}}
.export h3{{margin:0 0 6px;font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut)}}
.export textarea{{width:100%;min-height:52px;background:#0a0b0f;border:1px solid var(--bd);border-radius:8px;
color:#34c281;font:12px/1.5 ui-monospace,monospace;padding:9px;resize:vertical}}
.export .btn{{background:var(--panel);border:1px solid var(--bd);color:var(--tx);font:inherit;font-size:12px;
padding:6px 11px;border-radius:7px;cursor:pointer;margin-right:8px}}
</style></head><body>
<header><h1><b>class {klass}</b> recovery demo — {_html.escape(campaign)}</h1>
<div class=sub>{blurb}</div>
<div class=tot><b>{len(sections)}</b> domains · <b>{total}</b> media shown ·
tap each domain's <b>button</b> to mark it <b style="color:#34c281">her</b> /
<b style="color:#ef5453">not her</b> — the KEEP list at the bottom is the allowlist we'd gate the fix on.
Blank tile = hotlink blocked; <b>click it</b> to open live.</div></header>
{''.join(rows) if rows else '<section><p style="color:#8b91a3">Nothing to show.</p></section>'}
<div class=export><h3>KEEP — domains you marked HER (gate the class-{klass} fix on these)</h3>
<textarea id=box readonly placeholder="tap the domain buttons above…"></textarea>
<div style="margin-top:8px"><button class=btn id=copy>Copy</button>
<button class=btn id=reset>Reset all</button></div></div>
<script>
const KEY="recov:{klass}:"+{campaign_json};
let mark=JSON.parse(localStorage.getItem(KEY)||"{{}}");   // domain -> 'her'|'nother'
function paint(){{
  document.querySelectorAll("section[data-domain]").forEach(s=>{{
    const d=s.dataset.domain, v=mark[d];
    s.classList.toggle("her",v==="her"); s.classList.toggle("nother",v==="nother");
    const b=s.querySelector(".vote");
    b.textContent = v==="her"?"✓ her":v==="nother"?"✕ not her":"her? / not?";
  }});
  const keep=Object.keys(mark).filter(d=>mark[d]==="her").sort();
  document.getElementById("box").value=keep.join("\\n");
}}
document.querySelectorAll(".vote").forEach(b=>b.onclick=()=>{{
  const d=b.dataset.dom, v=mark[d];
  mark[d]= v==="her"?"nother":v==="nother"?undefined:"her";
  if(!mark[d])delete mark[d];
  localStorage.setItem(KEY,JSON.stringify(mark)); paint();
}});
document.getElementById("reset").onclick=()=>{{mark={{}};localStorage.setItem(KEY,"{{}}");paint();}};
document.getElementById("copy").onclick=()=>{{const t=document.getElementById("box");t.select();
  navigator.clipboard&&navigator.clipboard.writeText(t.value);}};
paint();
</script>
</body></html>"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--campaign", required=True)
    ap.add_argument("--class", dest="klass", type=int, choices=[2, 3], required=True)
    ap.add_argument("--tokens", default="")
    ap.add_argument("--name", default="")
    ap.add_argument("--per-domain", type=int, default=48, help="max tiles shown per domain")
    ap.add_argument("--block-file", default=os.path.join(HERE, "fake_aggregators.txt"))
    a = ap.parse_args()

    tokens = load_tokens(a.campaign, a.tokens)
    strong, names = build_target(tokens, a.name)
    blocked = _load_block(a.block_file)

    if a.klass == 2:
        sections = gather_class2(a.campaign, strong, blocked)
    else:
        sections = gather_class3(a.campaign, strong, names, a.per_domain, blocked)

    out = os.path.join(HERE, "campaigns", a.campaign, f"RECOVERY_class{a.klass}.html")
    open(out, "w", encoding="utf-8").write(render(a.campaign, a.klass, sections, a.per_domain))
    total = sum(len(s["recovered" if a.klass == 2 else "media"]) for s in sections)
    print(f"class {a.klass}: {len(sections)} domains, {total} media -> {out}")
    for s in sections[:12]:
        n = len(s["recovered"] if a.klass == 2 else s["media"])
        print(f"   {s['domain']:22} {n}")
    print(f"open it: file://{out}")


if __name__ == "__main__":
    main()

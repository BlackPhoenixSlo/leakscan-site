#!/usr/bin/env python3
"""
make_report.py (v2) — client-facing, shareable leak-detection report.

Single source of truth = the DMCA export produced by export_dmca.py (metadata.jsonl),
so the report and the paste-ready takedown files always agree. Adds:
  • 3-tier confidence — LIKELY (her, DMCA-ready) vs POSSIBLE (verify first) vs excluded
  • all detected links printed at the bottom, grouped by site, copy + download buttons
  • blurred example-leak gallery (crawl media whose URL carries the handle) with reveal
  • price scaled to the LIKELY leak count

    python3 make_report.py --prefix tarita --slug taritafit \
        --name "Ivette Aguero Tarazona" --brand "Tarita Fit" --out tarita-report.html

Reads: exports/<slug>_<stamp>/metadata.jsonl, <prefix>.crawl.json, <prefix>.takedown.csv,
optional <prefix>.live.csv.  Price anchors: 150 leaks -> €250 … 20000 -> €2500 (clamped).
"""
import argparse, base64, csv, html, io, json, os, re, sys
from datetime import date
from netloc import registrable_domain, echo_only_domains, canon_url, load_top_drop

try:
    from PIL import Image
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False

HERE = os.path.dirname(os.path.abspath(__file__))


def un(u): return re.sub(r"[^a-z0-9]", "", (u or "").lower())
def esc(s): return html.escape(s or "", quote=True)


def _photo_sig(url):
    """A visual signature for a leak image: the photo INDEX in its filename
    (e.g. taritafit_0001_300px.jpeg -> '0001'). Mirror networks host the same
    photo at different URLs but keep the same index, so deduping on this makes
    each gallery site show a DIFFERENT photo instead of all showing #0001."""
    base = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1].lower()
    nums = re.findall(r"\d+", base)
    return "n" + nums[0] if nums else base or url


def _load_env(path=None):
    """Minimal .env loader so the client CTA can read DM_INSTAGRAM / DM_TELEGRAM."""
    path = path or os.path.join(HERE, ".env")
    if not os.path.exists(path):
        return
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        key, val = ln.split("=", 1)
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def data_uri(path, maxpx=1000, quality=70):
    """Embed a local image as a compressed base64 data URI so the report stays a
    single self-contained (and encryptable) file — nothing leaks to a folder."""
    if not path or not os.path.exists(path):
        return ""
    try:
        raw = open(path, "rb").read()
    except Exception:
        return ""
    mime = "image/jpeg"
    if HAVE_PIL:
        try:
            im = Image.open(io.BytesIO(raw)).convert("RGB")
            im.thumbnail((maxpx, maxpx))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=quality)
            raw = buf.getvalue()
        except Exception:
            pass
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def _trim_empty(im):
    """Screenshots capture the whole browser viewport, so a search-results page
    that doesn't fill it leaves dead near-uniform bands (empty bottom, and an
    empty right column since the image grid only fills the left ~65%). Crop to
    the actual content: last row with contrast (full width) for the bottom, and
    last column with contrast within the GRID band (skipping the full-width top
    bar / sign-in button) for the right. Safety floors keep >=40% each way."""
    try:
        g = im.convert("L")
        w, h = g.size
        px = g.load()
        sx = max(1, w // 260)
        sy = max(1, h // 260)
        bottom = h
        for y in range(h - 1, -1, -1):
            row = [px[x, y] for x in range(0, w, sx)]
            if max(row) - min(row) > 42:
                bottom = y + 1
                break
        y0 = int(h * 0.18)                       # skip the full-width top bar
        yb = max(y0 + 1, bottom)
        right = w
        for x in range(w - 1, -1, -1):
            col = [px[x, y] for y in range(y0, yb, sy)]
            if max(col) - min(col) > 42:
                right = x + 1
                break
        bottom = max(int(h * 0.40), min(h, bottom + 10))
        right = max(int(w * 0.45), min(w, right + 10))
        if right < w or bottom < h:
            im = im.crop((0, 0, right, bottom))
    except Exception:
        pass
    return im


def _shot_uri(path, maxpx=1200, quality=72):
    """Auto-cropped, compressed data URI for a live screenshot (no dead bottom)."""
    if not path or not os.path.exists(path) or not HAVE_PIL:
        return data_uri(path)
    try:
        im = Image.open(path).convert("RGB")
    except Exception:
        return data_uri(path)
    im = _trim_empty(im)
    im.thumbnail((maxpx, maxpx))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def load_shots(images_dir):
    """Read shots.json and embed each screenshot as a data URI. Real Incogniton captures
    (shots/NNN_*.jpg — dense, live, light-theme google.com) LEAD the strip; the synthetic
    dark-theme gshots renders (google_images_N.png) are INTERLEAVED at slots 2/5/8/… — each
    carries its own per-tile 'illustrative' badge (build_shots), so the client can always tell
    them apart. With no real capture the synthetic set stands alone as the fallback strip."""
    if not images_dir:
        return []
    p = os.path.join(images_dir, "shots.json")
    if not os.path.exists(p):
        return []
    try:
        raw = json.load(open(p, encoding="utf-8"))
    except Exception:
        return []
    out = []
    for r in raw:
        uri = _shot_uri(os.path.join(images_dir, r.get("local_path", "")))
        if not uri:
            continue
        out.append({"uri": uri, "domain": r.get("domain", ""),
                    "page_url": r.get("page_url", ""),
                    "title": (r.get("title") or "")[:90],
                    "_real": r.get("local_path", "").startswith("shots/")})
    real = [s for s in out if s["_real"]]
    synth = [s for s in out if not s["_real"]]
    if real and synth:
        out = real[:]
        for j, s in enumerate(synth):      # 2nd, 5th, 8th, … spot in the strip
            out.insert(min(1 + 3 * j, len(out)), s)
    else:
        out = real or synth
    # keep the _real flag on each record — build_shots badges synthetic tiles 'illustrative'
    # and labels an all-synthetic strip accordingly.
    return out


def _collected_gallery(images_dir, leak_domains):
    """One embedded, name-verified image per confirmed-leak domain from
    collect_images.py's index.json — reliable (data-URI) gallery tiles that
    always render, spread over the sites we actually scraped this run."""
    if not images_dir:
        return []
    p = os.path.join(images_dir, "index.json")
    if not os.path.exists(p):
        return []
    try:
        rows = json.load(open(p, encoding="utf-8"))
    except Exception:
        return []
    out, seen = [], set()
    for r in rows:
        if not r.get("confident"):
            continue
        dom = r.get("registrable") or ""
        if not dom or dom in seen or dom not in leak_domains:
            continue
        uri = data_uri(os.path.join(images_dir, r.get("local_path", "")), maxpx=520, quality=68)
        if not uri:
            continue
        seen.add(dom)
        out.append({"img": uri, "domain": dom, "data": True,
                    "link": r.get("page_url") or f"https://{dom}"})
    return out


def price_for(n, lo_n=150, lo_p=250, hi_n=20000, hi_p=2500):
    if n <= lo_n: return lo_p
    if n >= hi_n: return hi_p
    return int(round((lo_p + (n - lo_n) * (hi_p - lo_p) / (hi_n - lo_n)) / 10.0) * 10)


def load_jsonl(path):
    out = []
    if path and os.path.exists(path):
        for ln in open(path, encoding="utf-8"):
            ln = ln.strip()
            if ln:
                try: out.append(json.loads(ln))
                except Exception: pass
    return out


def load_json(path):
    if path and os.path.exists(path):
        try: return json.load(open(path, encoding="utf-8"))
        except Exception: return None
    return None


def load_contacts(path):
    out = {}
    if path and os.path.exists(path):
        for r in csv.DictReader(open(path, encoding="utf-8-sig")):
            if r.get("domain"):
                out[r["domain"]] = r
    return out


def load_live(path):
    out = {}
    if path and os.path.exists(path):
        for r in csv.DictReader(open(path, encoding="utf-8-sig")):
            out[r.get("url", "")] = r.get("state", "")
    return out


def main():
    ap = argparse.ArgumentParser(description="Build a shareable client leak report (v2).")
    ap.add_argument("--prefix", default="tarita")
    ap.add_argument("--slug", default="taritafit")
    ap.add_argument("--stamp", default="latest")
    ap.add_argument("--name", default="Ivette Aguero Tarazona")
    ap.add_argument("--brand", default="Tarita Fit")
    ap.add_argument("--aliases-file", default="tarita-aliases.txt")
    ap.add_argument("--strong", default="taritafit,taritafitness")
    ap.add_argument("--crawl", default=None)
    ap.add_argument("--export-dir", default=None)
    ap.add_argument("--contacts", default=None)
    ap.add_argument("--live", default=None)
    ap.add_argument("--gallery-max", type=int, default=42)
    ap.add_argument("--images-dir", default=None,
                    help="collect_images.py out-dir (reads shots.json for the live-capture slideshow).")
    ap.add_argument("--cse", default=None,
                    help="cse_scanner json (google_total, sites, top_leaks, embedded images) for the 'Also on Google' section.")
    ap.add_argument("--triage", default=None,
                    help="slug_triage.py triage.json — drop echo-only domains (search echoes + crawl 0) "
                         "from the CSE 'Also on Google' sites so Google-indexed-but-empty hosts (xxbrits) "
                         "don't inflate her site count. Real hosts (crawl-confirmed) are never dropped.")
    ap.add_argument("--top-drop", default=os.path.join(HERE, "top_drop.txt"),
                    help="verified-empty result URLs (one/line, '#' comments) to drop from the report's "
                         "top public results. The ONLY authority — every other top result is kept, since "
                         "no URL pattern tells a real search page from an empty one (default: ./top_drop.txt).")
    ap.add_argument("--gallery-file", default=None,
                    help="Text file of local image paths (curated, clearly-the-creator) to EMBED as the "
                         "primary 'Your leaked content' gallery — always render, no hotlink breakage.")
    ap.add_argument("--out", default=None)
    ap.add_argument("--live-chat", action=argparse.BooleanOptionalAction, default=True,
                    help="Bake DEEPSEEK_API_KEY into the report so 'Ask about your report' is a live "
                         "LLM answering from the report facts (falls back to canned replies on error). "
                         "ON BY DEFAULT (pass --no-live-chat to disable); degrades to canned when no key "
                         "is in .env, so it's safe to leave on. SECURITY: the key ends up in the HTML — "
                         "only publish the PASSWORD-PROTECTED version, and use a low-balance key.")
    args = ap.parse_args()

    pre = args.prefix
    crawl = load_json(args.crawl or f"{pre}.crawl.json") or []
    export_dir = args.export_dir or os.path.join("exports", f"{args.slug}_{args.stamp}")
    meta = load_jsonl(os.path.join(export_dir, "metadata.jsonl"))
    contacts = load_contacts(args.contacts or f"{pre}.takedown.csv")
    live = load_live(args.live or f"{pre}.live.csv")
    out_path = args.out or f"{pre}-report.html"
    strong = [un(t) for t in args.strong.split(",") if un(t)]
    aliases = [ln.strip() for ln in open(args.aliases_file, encoding="utf-8")] if os.path.exists(args.aliases_file) else []
    aliases = [a for a in aliases if a][:14]

    # The headline leak counts AND the price quote come from the export's metadata.jsonl, NOT the
    # crawl. If that file is missing/empty while the crawl clearly found media, the report would
    # silently render "0 confirmed leaks" at the €250 floor. Warn loudly so the operator runs the
    # export step first instead of shipping a wrong price.
    if not meta:
        crawl_media = sum(len(r.get("media", [])) for r in crawl if isinstance(r, dict))
        if crawl_media:
            print(f"!! WARNING: no export metadata at {export_dir}/metadata.jsonl, but the crawl has "
                  f"{crawl_media} media. The report will show 0 confirmed leaks and the FLOOR price. "
                  f"Run export_dmca.py (the 'export' step) before 'report', or pass --export-dir.",
                  file=sys.stderr)

    likely = [r for r in meta if r.get("bucket") == "LIKELY"]
    possible = [r for r in meta if r.get("bucket") == "POSSIBLE"]

    def by_dom(records):
        d = {}
        for r in records:
            d.setdefault(r.get("domain") or registrable_domain(r["url"]), []).append(r["url"])
        return d
    likely_dom, possible_dom = by_dom(likely), by_dom(possible)

    # gallery: ONE image per site, across as many sites as we have. Prefer the
    # embedded, name-verified images we collected this run (they always render);
    # fall back to crawl media (remote, sometimes hotlink-protected).
    IMG = re.compile(r"\.(jpe?g|png|webp|gif|bmp)(\?|$)", re.I)
    media_count = 0
    dom_imgs, src_of = {}, {}
    for r in crawl:
        d = registrable_domain(r["domain"])
        for m, s in (r.get("media_pairs") or [[m, ""] for m in r.get("media", [])]):
            if any(t in un(m) for t in strong):
                media_count += 1
                if IMG.search(m):
                    dom_imgs.setdefault(d, []).append(m)
                    src_of.setdefault(m, s or (r["pages"][0] if r.get("pages") else f"https://{d}"))
    # one DISTINCT photo per site (mirror networks reuse the same photo index at
    # different URLs, so dedup on the photo signature), biggest sites first.
    used_sig, dom_first = set(), {}
    domlist = sorted(dom_imgs, key=lambda x: -len(likely_dom.get(x, [])))
    for d in domlist:
        for m in dom_imgs[d]:
            sig = _photo_sig(m)
            if sig in used_sig:
                continue
            used_sig.add(sig)
            dom_first[d] = {"img": m, "domain": d, "data": False,
                            "link": src_of.get(m, f"https://{d}")}
            break
    # any site squeezed out (all its photos' indices taken) still gets a tile
    for d in domlist:
        if d not in dom_first and dom_imgs[d]:
            m = dom_imgs[d][0]
            dom_first[d] = {"img": m, "domain": d, "data": False,
                            "link": src_of.get(m, f"https://{d}")}
    # add confident collected images for confirmed-leak sites not already covered
    for c in _collected_gallery(args.images_dir, set(likely_dom)):
        dom_first.setdefault(c["domain"], c)
    order = sorted(dom_first, key=lambda d: -len(likely_dom.get(d, [])))
    gallery = [dom_first[d] for d in order][:args.gallery_max]
    # curated, embedded gallery (clearly-the-creator images collected this run) —
    # these always render (data URIs), so they lead the strip as the primary examples.
    if args.gallery_file and os.path.exists(args.gallery_file):
        curated = []
        for ln in open(args.gallery_file, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            p, _, dom = ln.partition("|")   # "path|site" — site labels the tile (optional)
            p, dom = p.strip(), dom.strip()
            uri = data_uri(p if os.path.isabs(p) else os.path.join(HERE, p), maxpx=680, quality=72)
            if uri:
                # a labelled tile carries its source site → make it a clickable link
                # ("reveal more": it proves WHERE the leak is hosted); bare frames stay linkless.
                curated.append({"img": uri, "domain": dom, "data": True,
                                "link": f"https://{dom}" if dom else ""})
        if curated:
            # WEAVE, don't segregate. Keep the really-nude no-source frames leading (the opener
            # the client sees first — the sorting we like), but mix the SOURCE-BEARING tiles
            # (labelled gallery_imgs + the crawl tiles that carry a clickable source link) into
            # the start and in-between instead of dumping them all at the end.
            frames = [c for c in curated if not c["domain"]]   # pure nude frames — no label/link
            sourced = [c for c in curated if c["domain"]] + gallery   # everything that shows a source
            lead = min(3, len(frames))                         # open with the strongest nude examples
            woven, fi, si = list(frames[:lead]), lead, 0
            while fi < len(frames) or si < len(sourced):
                if si < len(sourced):
                    woven.append(sourced[si]); si += 1
                if fi < len(frames):
                    woven.append(frames[fi]); fi += 1
            gallery = woven[:max(args.gallery_max, len(curated) + 6)]

    n_likely, n_possible = len(likely), len(possible)
    # liveness over LIKELY urls if available
    up = sum(1 for r in likely if live.get(r["url"]) == "up")
    dead = sum(1 for r in likely if live.get(r["url"]) == "dead")
    have_live = bool(live)
    quote = price_for(n_likely)
    stamp = date.today().isoformat()

    top = sorted(likely_dom.items(), key=lambda kv: -len(kv[1]))[:12]
    top_max = max((len(v) for _, v in top), default=1) or 1

    shots = load_shots(args.images_dir)
    cse = load_json(args.cse) if args.cse else None
    # Clean the CSE 'Also on Google' data before it feeds the count + display:
    #   • sites (reach count): drop echo-only domains slug_triage confirmed host nothing of hers
    #     (their /search/<handle> reflects the query, crawl found 0). Needs the triage artifact;
    #     crawl-confirmed real hosts are never echo-only, so leakgallery is never dropped.
    #   • top_leaks (public result LINKS): KEEP everything — including /search/<handle> — minus the
    #     human-verified-empty URLs in top_drop.txt. No URL pattern separates a real search page from
    #     an empty one (leakgallery/juliafilippo-leak empty vs /sophieraiin-onlyfans-leaks full), so a
    #     human opening the page is the only authority; the old url_shape=="search" drop hid real hits.
    if cse:
        echo = echo_only_domains(args.triage) if args.triage else set()
        drop = load_top_drop(args.top_drop)

        def _dom(x):
            return registrable_domain(x.get("domain") or x.get("url", "")) if isinstance(x, dict) \
                else registrable_domain(x or "")

        def _url(x):
            return (x.get("url") or x.get("link") or "") if isinstance(x, dict) else (x or "")

        if isinstance(cse.get("sites"), list):
            cse["sites"] = [s for s in cse["sites"] if _dom(s) not in echo]
        if isinstance(cse.get("top_leaks"), list):
            cse["top_leaks"] = [t for t in cse["top_leaks"] if canon_url(_url(t)) not in drop]
    # total distinct sites she appears on = crawl-confirmed HOSTS ∪ Google-indexed sites (CSE).
    # The hero should reflect the full reach, not just the media-crawled hosts.
    cse_site_doms = {registrable_domain(s.get("domain", "")) for s in (cse.get("sites") if cse else [])}
    cse_site_doms.discard("")
    n_sites_total = len({registrable_domain(d) for d in likely_dom} | cse_site_doms)
    _load_env()
    ig = os.environ.get("DM_INSTAGRAM", "").strip().lstrip("@")
    tg = os.environ.get("DM_TELEGRAM", "").strip().lstrip("@")

    # Optional: bake a live DeepSeek assistant into the report (the report is a
    # static file with no backend, so the key must live client-side). Gated behind
    # --live-chat; the key sits inside the AES-encrypted payload once protected.
    ds_key = ds_sys = ""
    ds_model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    if args.live_chat:
        ds_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if ds_key:
            try:
                import chat_proxy
                sysp = chat_proxy.SYSTEM_PROMPT
                kb = chat_proxy.load_kb("kb.json")
            except Exception:
                sysp, kb = "", ""
            facts_ctx = (
                "REPORT FACTS — answer only from these, never invent URLs or numbers:\n"
                f"- prepared for: {args.name}\n"
                f"- confirmed leak copies (URLs): {n_likely}\n"
                f"- media files identified: {media_count}\n"
                f"- sites total: {n_sites_total} ({len(likely_dom)} hosting directly, the rest indexed on Google)\n"
                f"- takedown quote: €{quote} — one flat fee covering every confirmed leak\n"
                f"- biggest hosts: {', '.join(d for d, _ in top[:6])}\n"
                f"- contact: Instagram @{ig or 'n/a'} / Telegram @{tg or 'n/a'}\n"
                "- this is a first-pass scan; our manual deeper pass finds more.\n")
            ds_sys = "\n\n".join(x for x in (sysp, facts_ctx,
                     ("KNOWLEDGE BASE:\n" + kb) if kb else "") if x).strip()
            print(f"  [live-chat] DeepSeek key baked into {out_path} — ONLY publish the "
                  f"password-protected version (the key is in the HTML).")
        else:
            print("  [live-chat] no DEEPSEEK_API_KEY in .env — chat stays canned.")

    htmlout = render(
        name=args.name, brand=args.brand, stamp=stamp, aliases=aliases, gallery=gallery,
        quote=quote, n_likely=n_likely, n_possible=n_possible, n_media=media_count,
        n_domains=len(likely_dom), n_sites_total=n_sites_total,
        likely_dom=likely_dom, possible_dom=possible_dom,
        contacts=contacts, up=up, dead=dead, have_live=have_live, top=top, top_max=top_max,
        n_scanned=375, export_dir=export_dir, shots=shots, cse=cse, ig=ig, tg=tg,
        ds_key=ds_key, ds_sys=ds_sys, ds_model=ds_model,
    )
    open(out_path, "w", encoding="utf-8").write(htmlout)
    print(f"REPORT -> {out_path}")
    print(f"  LIKELY {n_likely} across {len(likely_dom)} sites | POSSIBLE {n_possible} across {len(possible_dom)} sites")
    print(f"  gallery tiles {len(gallery)} | media(strong) {media_count} | shots {len(shots)} | QUOTE €{quote}")


def bar(label, val, mx):
    return (f'<div class="bar"><span class="bl">{esc(label)}</span>'
            f'<span class="bt"><i style="width:{max(2,int(100*val/mx))}%"></i></span>'
            f'<span class="bv">{val}</span></div>')


def dom_table(dom_map, contacts, show_contact, cls_badge):
    rows = ""
    for d in sorted(dom_map, key=lambda x: -len(dom_map[x])):
        urls = dom_map[d]
        contact = ""
        if show_contact:
            em = (contacts.get(d, {}) or {}).get("best_email", "")
            contact = f'<td><code>{esc(em)}</code></td>' if em else '<td><span class="mut">—</span></td>'
        rows += (f'<tr><td class="dom">{esc(d)} {cls_badge}</td>'
                 f'<td class="num">{len(urls)}</td>{contact}'
                 f'<td><a href="{esc(urls[0])}" target="_blank" rel="noopener">open ↗</a></td></tr>')
    return rows


def links_block(dom_map, kind):
    """Collapsible, grouped, scrollable list of every URL (printed at the bottom)."""
    blocks = ""
    for d in sorted(dom_map, key=lambda x: -len(dom_map[x])):
        items = "".join(f'<li><a href="{esc(u)}" target="_blank" rel="noopener">{esc(u)}</a></li>'
                        for u in sorted(set(dom_map[d])))
        blocks += (f'<details class="lg"><summary>{esc(d)} <span class="mut">· {len(set(dom_map[d]))}</span></summary>'
                   f'<ul class="lk">{items}</ul></details>')
    return blocks


def _tile(src, cap, href, portrait, is_data):
    caphtml = esc(cap)
    if href:
        caphtml = (f'<a href="{esc(href)}" target="_blank" rel="noopener" '
                   f'onclick="event.stopPropagation()">{esc(cap)} ↗</a>')
    ref = '' if is_data else ' referrerpolicy="no-referrer"'
    return (f'<figure class="mt{" port" if portrait else ""}">'
            f'<img loading="lazy"{ref} src="{src}" draggable="false" '
            f'onerror="this.closest(\'figure\').classList.add(\'broken\')">'
            f'<span class="lk2">\U0001f51e tap</span>'
            f'<figcaption>{caphtml}</figcaption></figure>')


def _strip(items, dur=0):
    """Drag-to-scroll horizontal image strip (same behaviour as the Google-shots
    row): grab & drag or trackpad-scroll on hover, tap a tile to reveal. `dur` is
    kept for call-compat but unused. items: (src, cap, href, portrait, is_data)."""
    if not items:
        return ""
    row = "".join(_tile(*it) for it in items)
    return f'<div class="dragrow galrow">{row}</div>'


def _gtile(src, cap, href, real=True):
    """One full-size Google-results screenshot tile for the drag-scroll row. A synthetic
    (CSE-built) tile carries an 'illustrative' badge so it is never mistaken for a live capture."""
    caphtml = (f'<a href="{esc(href)}" target="_blank" rel="noopener">{esc(cap)} ↗</a>'
               if href else esc(cap))
    badge = "" if real else '<span class="gtag">\U0001f9ea illustrative</span>'
    return (f'<figure class="gt"><img src="{src}" draggable="false">{badge}'
            f'<span class="lk2">\U0001f51e tap to reveal</span>'
            f'<figcaption>{caphtml}</figcaption></figure>')


def build_shots(shots):
    """Full-size, drag-to-scroll row of Google-results screenshots (data URIs). Real Incogniton
    captures are labelled 'captured during the scan'; every CSE-built synthetic render carries a
    per-tile 'illustrative' badge so the client is never shown a fabricated page as a genuine
    live screenshot. A MIXED strip (real capture + gshots grids interleaved at slots 2/5/8 by
    load_shots) leads with the real label and calls out the badged tiles; an all-synthetic strip
    (Incogniton down or --google-shots=cse) is labelled illustrative throughout."""
    if not shots:
        return ""
    n_syn = sum(1 for s in shots if not s.get("_real"))
    real = n_syn < len(shots)
    tiles = "".join(_gtile(s["uri"], (s.get("title") or s.get("domain") or "Google Search"),
                           s.get("page_url", ""), s.get("_real", True)) for s in shots)
    if real and n_syn:
        pill = "\U0001f51e blurred · tap to reveal · drag to scroll"
        lead = (f"Full screenshots of Google image &amp; <code>site:</code> searches surfacing the "
                f"leaks, captured during the scan — plus {n_syn} \U0001f9ea-badged illustrative "
                f"grids reconstructed from Google's index. Drag sideways to browse all {len(shots)}.")
    elif real:
        pill = "\U0001f51e blurred · tap to reveal · drag to scroll"
        lead = (f"Full screenshots of Google image &amp; <code>site:</code> searches surfacing the "
                f"leaks, captured during the scan. Drag sideways to browse all {len(shots)}.")
    else:
        pill = "\U0001f9ea illustrative · reconstructed from Google's index"
        lead = (f"Reconstructed from Google's live index (Custom Search API) — an illustrative "
                f"preview of how your name surfaces in Google Images, not a live screenshot. "
                f"Drag sideways to browse all {len(shots)}.")
    return (f'''
  <section class="sec"><div class="sechead"><h2>Google search results</h2>
    <span class="pill warn">{pill}</span></div>
    <p class="lead">{lead}</p>
    <div class="dragrow">{tiles}</div></section>''')


def build_google(cse, k_has_shots=False):
    """'Also indexed on Google' section: sites Google indexes her on + the top
    public collection pages (+ a thumbnail marquee only when no Google-results
    screenshot is present). Fed by cse_scanner output."""
    if not cse:
        return ""
    imgs = cse.get("images") or []
    sites = cse.get("sites") or []
    top = cse.get("top_leaks") or []
    total = cse.get("google_total")
    n_sites = cse.get("n_sites") or len(sites)
    try:
        total_txt = f"~{int(total):,}" if total else ""
    except Exception:
        total_txt = str(total or "")
    # image visual comes from the Google-results screenshot strip (build_shots);
    # this section is the site + top-leak breakdown only (avoids showing the same
    # thumbnails twice). Falls back to a thumbnail marquee if no screenshot ran.
    img_items = [(u, "Google Images", "", True, True) for u in imgs]
    img_strip = ("" if k_has_shots else
                 (_strip(img_items, max(24, len(img_items) * 3)) if img_items else ""))
    site_rows = "".join(
        f'<div class="grow"><a href="{esc(s.get("url",""))}" target="_blank" rel="noopener" '
        f'class="gdom">{esc(s.get("domain",""))}</a>'
        f'<span class="gurls">{s.get("occ",0)}+ URLs</span></div>'
        for s in sites)   # show ALL Google-indexed sites (glist scrolls) — backs the headline count
    top_items = "".join(
        f'<li><a href="{esc(u)}" target="_blank" rel="noopener">{esc(u)}</a></li>'
        for u in top[:14])
    lead = (f"Google is indexing <b>{total_txt} results</b> for your name across "
            f"<b>{n_sites}+ sites</b> — these are the public pages anyone finds just by "
            f"searching. We get them delisted from Google too.") if total_txt else (
            f"Public pages indexing your name across <b>{n_sites}+ sites</b>.")
    return f'''
  <section class="sec"><div class="sechead"><h2>Also all over Google</h2>
    <label class="toggle" for="reveal"><span class="dot rvd"></span> Reveal all (NSFW)</label>
    <span class="pill warn">\U0001f51e blurred · tap any image</span></div>
    <p class="lead">{lead}</p>
    {img_strip}
    <div class="two">
      <section class="card"><h2>Sites indexing you on Google</h2>
        <div class="glist">{site_rows}</div></section>
      <section class="card"><h2>Top public results</h2>
        <ul class="lk gtop">{top_items}</ul></section>
    </div></section>'''


def render(**k):
    ig, tg = k.get("ig", ""), k.get("tg", "")
    aliases_chips = "".join(f'<span class="chip2">{esc(a)}</span>' for a in k["aliases"])
    google_html = build_shots(k.get("shots") or []) + build_google(k.get("cse"), bool(k.get("shots")))
    gitems = [(g["img"] if g.get("data") else esc(g["img"]), g["domain"],
               g.get("link", ""), True, bool(g.get("data"))) for g in k["gallery"]]
    gallery_html = (_strip(gitems, max(30, len(gitems) * 3)) if gitems else
                    '<p class="lead">Previews on these sources are video-only or hotlink-protected.</p>')
    bars = "".join(bar(d, len(u), k["top_max"]) for d, u in k["top"])
    likely_links = links_block(k["likely_dom"], "likely")
    likely_all = sorted({u for urls in k["likely_dom"].values() for u in urls})
    likely_js = json.dumps(likely_all)
    pricepos = max(3, min(100, int(100 * (k["quote"] - 250) / 2250)))
    top5 = [d for d, _ in k["top"][:5]]
    facts = json.dumps({"n_likely": k["n_likely"], "n_domains": k["n_domains"],
                        "n_sites_total": k.get("n_sites_total") or k["n_domains"],
                        "n_media": k["n_media"], "quote": k["quote"],
                        "top": top5, "ig": ig, "tg": tg, "name": k["name"]})
    ds_key_js = json.dumps(k.get("ds_key") or "")
    ds_sys_js = json.dumps(k.get("ds_sys") or "")
    ds_model_js = json.dumps(k.get("ds_model") or "deepseek-chat")

    dm_btns = ""
    if ig:
        dm_btns += f'<a class="dm ig" target="_blank" rel="noopener" href="https://instagram.com/{esc(ig)}">Instagram</a>'
    if tg:
        dm_btns += f'<a class="dm tg" target="_blank" rel="noopener" href="https://t.me/{esc(tg)}">Telegram</a>'
    cta_html = (f'''
  <section class="ctabar"><div class="ctatext"><b>Ready to get these removed?</b>
      <span>We file every DMCA takedown for you. Message us to start — we handle everything.</span></div>
    <div class="dmrow">{dm_btns}</div></section>''' if dm_btns else "")
    approve_href = ('https://instagram.com/' + esc(ig)) if ig else (('https://t.me/' + esc(tg)) if tg else '#')
    # reusable chat card (class-based so it can appear at top AND bottom; each
    # instance is wired independently by wireChat() in the script)
    chat_html = ('\n  <section class="chat"><div class="h">\U0001f4ac Ask about your report</div>'
                 '\n    <div class="clog"></div>'
                 '\n    <div class="qr">'
                 '\n      <b data-q="Is this all the leaks? Only these websites?">Is this all of them?</b>'
                 '\n      <b data-q="Which sites are they on?">Which sites?</b>'
                 '\n      <b data-q="How do I get them removed?">How to remove?</b>'
                 '\n      <b data-q="Will they come back?">Will they come back?</b>'
                 '\n      <b data-q="What does it cost?">What\'s the cost?</b>'
                 '\n    </div>'
                 '\n    <form class="cform"><input class="cin" autocomplete="off" placeholder="Ask anything about your leaks…">'
                 '\n      <button type="submit">➤</button></form>'
                 '\n  </section>')

    return f'''<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Leak Report · {esc(k["brand"])}</title>
<style>
:root{{--bg:#0f1020;--bg2:#171833;--card:#1c1e3d;--card2:#24264a;--tx:#eef0ff;--mut:#a3a7c9;
--acc:#7c5cff;--acc2:#38d9c7;--ok:#38d98a;--warn:#f5b74e;--bad:#ff6b6b;--line:#2c2e57;--r:16px}}
*{{box-sizing:border-box}}
body{{margin:0;min-height:100vh;background:radial-gradient(1200px 600px at 50% -10%,#241b4d 0%,var(--bg) 55%) fixed;
color:var(--tx);font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}
a{{color:inherit;text-decoration:none}}strong,b{{color:#fff}}
code{{font:12.5px/1.4 ui-monospace,Menlo,monospace;color:#cbd0f5;background:rgba(124,92,255,.14);padding:1px 5px;border-radius:5px}}
.topbar{{display:flex;align-items:center;justify-content:space-between;max-width:960px;margin:0 auto;padding:18px 20px;width:100%}}
.brand{{font-weight:800;font-size:20px;display:flex;align-items:center;gap:8px}}.brand .lg{{color:var(--acc2);font-size:22px}}
.tag{{font-size:12px;color:var(--mut);border:1px solid var(--line);padding:5px 11px;border-radius:999px}}
.wrap{{max-width:960px;margin:0 auto;padding:8px 20px 70px;width:100%}}
.hero{{text-align:center;padding:22px 0 6px}}
.badge{{display:inline-block;font-size:13px;color:var(--acc2);background:rgba(56,217,199,.1);
border:1px solid rgba(56,217,199,.25);padding:6px 13px;border-radius:999px;margin-bottom:16px}}
.hero h1{{font-size:clamp(28px,6vw,44px);line-height:1.08;margin:6px 0 12px;letter-spacing:-.5px}}
.hl{{color:transparent;background:linear-gradient(90deg,var(--acc),var(--acc2));-webkit-background-clip:text;background-clip:text}}
.hero .sub{{color:var(--mut);font-size:17px;max-width:560px;margin:0 auto 18px}}
.chips{{display:flex;flex-wrap:wrap;gap:7px;justify-content:center;margin:0 auto 8px;max-width:640px}}
.chip2{{background:var(--card);border:1px solid var(--line);color:#c7cbf0;padding:4px 11px;border-radius:999px;font-size:12.5px}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin:22px 0}}
.stat{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px}}
.stat .k{{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.06em}}
.stat .v{{font-size:30px;font-weight:750;margin-top:6px;line-height:1}}.stat .s{{color:var(--mut);font-size:12.5px;margin-top:7px}}
.stat.q{{background:linear-gradient(135deg,#241b4d,#1c1e3d);border-color:#3a2f6b}}.stat.q .v{{color:var(--acc2)}}
.band{{display:flex;align-items:center;gap:9px;margin-top:11px}}.band .t{{flex:1;height:7px;border-radius:999px;background:#2a2c55;position:relative;overflow:hidden}}
.band .t i{{position:absolute;inset:0 auto 0 0;background:linear-gradient(90deg,var(--ok),var(--acc2),var(--acc))}}.band small{{color:var(--mut);font-size:11px;white-space:nowrap}}
.chat{{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:16px;margin:20px 0}}
.chat .h{{font-weight:700;font-size:15px;margin-bottom:10px;display:flex;align-items:center;gap:8px}}
.clog{{display:flex;flex-direction:column;gap:9px;max-height:260px;overflow:auto;padding:2px}}
.msg{{max-width:82%;padding:9px 13px;border-radius:13px;font-size:14px;line-height:1.5;white-space:pre-wrap;word-break:break-word}}
.msg.bot{{background:var(--card2);border:1px solid var(--line);align-self:flex-start;border-bottom-left-radius:4px}}
.msg.me{{background:var(--acc);color:#0f1020;align-self:flex-end;border-bottom-right-radius:4px;font-weight:500}}
.qr{{display:flex;flex-wrap:wrap;gap:7px;margin:10px 0 4px}}
.qr b{{cursor:pointer;font-weight:500;font-size:12.5px;color:var(--acc2);background:rgba(56,217,199,.08);border:1px solid rgba(56,217,199,.28);padding:5px 11px;border-radius:999px}}
.qr b:hover{{background:rgba(56,217,199,.16)}}
.cform{{display:flex;gap:8px;margin-top:10px}}
.cform input{{flex:1;background:var(--bg2);border:1px solid var(--line);color:var(--tx);border-radius:11px;padding:11px 14px;font-size:14px;outline:none}}
.cform input:focus{{border-color:var(--acc)}}
.cform button{{background:linear-gradient(135deg,var(--acc),var(--acc2));border:0;color:#0f1020;font-weight:700;border-radius:11px;padding:0 18px;cursor:pointer;font-size:16px}}
.ctabar{{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:14px;
background:linear-gradient(135deg,#241b4d,#1c1e3d);border:1px solid #3a2f6b;border-radius:var(--r);padding:18px 22px;margin:20px 0}}
.ctatext b{{font-size:17px}}.ctatext span{{display:block;color:var(--mut);font-size:14px;margin-top:3px}}
.dmrow{{display:flex;gap:10px}}
.dm{{padding:11px 20px;border-radius:12px;font-weight:700;font-size:14px}}
.dm.ig{{background:linear-gradient(135deg,#f58529,#dd2a7b,#8134af);color:#fff}}
.dm.tg{{background:#2aabee;color:#fff}}
.sec{{margin:22px 0}}.sechead{{display:flex;align-items:center;gap:12px;margin:0 0 6px;flex-wrap:wrap}}
.sec h2{{margin:0;font-size:19px;flex:1}}.lead{{color:var(--mut);font-size:14px;margin:0 0 14px}}
.pill{{font-size:12px;padding:4px 11px;border-radius:999px;border:1px solid var(--line);background:var(--card)}}
.pill.warn{{color:var(--warn);border-color:rgba(245,183,78,.35);background:rgba(245,183,78,.1)}}
.toggle{{display:inline-flex;align-items:center;gap:9px;cursor:pointer;user-select:none;background:var(--card);
border:1px solid var(--line);padding:7px 13px;border-radius:999px;font-size:13px}}
.toggle .dot{{width:34px;height:19px;border-radius:999px;background:#33365e;position:relative;transition:.2s}}
.toggle .dot::after{{content:"";position:absolute;top:2px;left:2px;width:15px;height:15px;border-radius:50%;background:#fff;transition:.2s}}
.strip{{overflow:hidden;position:relative;border:1px solid var(--line);border-radius:var(--r);background:var(--card)}}
.strip .track{{display:flex;gap:14px;width:max-content;padding:14px 0;animation:marq var(--dur,60s) linear infinite}}
.strip:hover .track{{animation-play-state:paused}}
@keyframes marq{{from{{transform:translateX(0)}}to{{transform:translateX(-50%)}}}}
.mt{{position:relative;margin:0;height:220px;border-radius:12px;overflow:hidden;border:1px solid var(--line);background:#0e131c;cursor:pointer;flex:0 0 auto}}
.mt:first-child{{margin-left:14px}}
.mt.port{{width:165px}}.mt img{{height:100%;width:auto;max-width:none;display:block;object-fit:cover;filter:blur(20px) brightness(.7);transform:scale(1.06);transition:.25s}}
.mt.port img{{width:100%;object-fit:cover}}
.mt.broken{{display:none}}
.mt figcaption{{position:absolute;left:0;right:0;bottom:0;padding:6px 9px;font-size:11px;background:linear-gradient(180deg,transparent,rgba(0,0,0,.85));color:#cdd2f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.mt figcaption a{{color:#b9c2ff}}
.mt .lk2{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:12px;color:#e9eefc;pointer-events:none;text-shadow:0 1px 4px #000}}
#reveal:checked ~ .wrap .mt img,.mt.show img{{filter:none;transform:none}}
#reveal:checked ~ .wrap .mt .lk2,.mt.show .lk2{{display:none}}
#reveal:checked ~ .wrap .rvd{{background:var(--ok)}}#reveal:checked ~ .wrap .rvd::after{{left:17px}}
/* full-size, drag-to-scroll Google-results row */
.dragrow{{display:flex;gap:14px;overflow-x:auto;overflow-y:hidden;padding:2px 2px 14px;cursor:grab;scroll-snap-type:x proximity;-webkit-overflow-scrolling:touch}}
.dragrow.drag{{cursor:grabbing;scroll-snap-type:none}}
.dragrow::-webkit-scrollbar{{height:10px}}.dragrow::-webkit-scrollbar-track{{background:transparent}}
.dragrow::-webkit-scrollbar-thumb{{background:#33365e;border-radius:999px}}.dragrow::-webkit-scrollbar-thumb:hover{{background:#454982}}
.gt{{position:relative;margin:0;flex:0 0 auto;width:min(90vw,660px);height:min(64vh,520px);scroll-snap-align:start;border-radius:14px;overflow:hidden;border:1px solid var(--line);background:#0e131c;cursor:pointer}}
.gt img{{display:block;width:100%;height:100%;object-fit:cover;object-position:top center;background:#000;filter:blur(24px) brightness(.72);transition:filter .25s;user-select:none;-webkit-user-drag:none}}
.gt figcaption{{position:absolute;left:0;right:0;bottom:0;padding:9px 12px;font-size:12.5px;background:linear-gradient(180deg,transparent,rgba(0,0,0,.88));color:#dfe3ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.gt figcaption a{{color:#b9c2ff}}
.gt .lk2{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:14px;color:#e9eefc;pointer-events:none;text-shadow:0 1px 5px #000}}
.gt .gtag{{position:absolute;top:8px;left:8px;z-index:2;background:rgba(0,0,0,.72);color:#ffd7a8;font-size:11px;padding:2px 8px;border-radius:999px;letter-spacing:.02em;pointer-events:none}}
#reveal:checked ~ .wrap .gt img,.gt.show img{{filter:none}}
#reveal:checked ~ .wrap .gt .lk2,.gt.show .lk2{{display:none}}
.bars{{display:flex;flex-direction:column;gap:8px}}
.bar{{display:grid;grid-template-columns:150px 1fr 46px;align-items:center;gap:10px;font-size:12.5px}}
.bar .bl{{color:#c7cbf0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.bar .bt{{background:#22254a;border-radius:999px;height:11px;overflow:hidden}}.bar .bt i{{display:block;height:100%;background:linear-gradient(90deg,var(--acc),var(--acc2))}}
.bar .bv{{text-align:right;color:var(--mut);font-variant-numeric:tabular-nums}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:20px 22px}}
.card h2{{margin:0 0 6px;font-size:18px}}
.card ul{{margin:8px 0 0;padding-left:18px;color:#c7cbf0;font-size:14px;line-height:1.9}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:22px 0}}
.btn{{background:var(--card2);border:1px solid var(--line);color:var(--tx);border-radius:10px;padding:9px 14px;font-size:13px;cursor:pointer}}
.btn:hover{{border-color:var(--acc)}}.btn.p{{background:var(--acc);color:#0f1020;font-weight:700;border:0}}
.lg{{border:1px solid var(--line);border-radius:10px;margin:6px 0;background:var(--bg2)}}
.lg summary{{cursor:pointer;padding:9px 13px;font-weight:600;font-size:13px}}
.lk{{margin:0;padding:6px 12px 12px 26px;max-height:280px;overflow:auto;font:11.5px/1.6 ui-monospace,Menlo,monospace}}
.lk a{{color:#9fb4ff;word-break:break-all}}
.gtop{{list-style:none;padding-left:6px;max-height:260px}}
.glist{{display:flex;flex-direction:column;gap:2px;max-height:260px;overflow:auto}}
.grow{{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:7px 4px;border-bottom:1px solid var(--line)}}
.grow:last-child{{border-bottom:0}}
.gdom{{color:#cbd0f5;font-weight:600;word-break:break-all}}.gdom:hover{{color:var(--acc2)}}
.gurls{{color:var(--warn);font-weight:700;font-size:13px;white-space:nowrap}}
.cta{{display:inline-block;margin-top:12px;background:linear-gradient(135deg,var(--acc),var(--acc2));color:#0f1020;font-weight:700;padding:11px 22px;border-radius:12px}}
.disclaimer{{color:#f0d9a8;font-size:14px;font-style:italic;text-align:center;max-width:660px;margin:24px auto 0;line-height:1.6;background:rgba(245,183,78,.07);border:1px solid rgba(245,183,78,.25);border-radius:12px;padding:14px 18px}}
footer{{color:var(--mut);font-size:12.5px;margin-top:28px;line-height:1.7;text-align:center}}
@media(max-width:720px){{.two{{grid-template-columns:1fr}}.bar{{grid-template-columns:108px 1fr 40px}}.ctabar{{flex-direction:column;align-items:flex-start}}}}
</style></head><body>
<input type="checkbox" id="reveal" hidden>
<div class="topbar"><div class="brand"><span class="lg">◑</span> LeakScan</div>
  <span class="tag">Confidential · {esc(k["name"])}</span></div>
<div class="wrap">
  <div class="hero">
    <div class="badge">Private report · prepared for you</div>
    <h1>Your content was <span class="hl">leaked</span><br>across {k.get("n_sites_total") or k["n_domains"]} sites</h1>
    <p class="sub">We found <b>{k["n_likely"]:,}</b> confirmed copies of {esc(k["name"])}'s content on <b>{k["n_domains"]}</b> piracy sites — and traced it across <b>{k.get("n_sites_total") or k["n_domains"]}</b> sites in total once Google-indexed pages are included. Here's exactly where — and how we get them removed.</p>
    <div class="chips">{aliases_chips}</div>
  </div>

  <section class="sec"><div class="sechead"><h2>Your leaked content</h2>
    <label class="toggle" for="reveal"><span class="dot rvd"></span> Reveal all (NSFW)</label>
    <span class="pill warn">\U0001f51e blurred · tap any tile</span></div>
    <p class="lead">Actual copies of your leaked content found across the piracy sites &amp; Google, auto-scrolling. Hover to pause.</p>
    {gallery_html}</section>

  <div class="stats">
    <div class="stat"><div class="k">Confirmed leaks</div><div class="v">{k["n_likely"]:,}</div><div class="s">unique URLs under your handle</div></div>
    <div class="stat"><div class="k">Media items</div><div class="v">{k["n_media"]:,}</div><div class="s">photos / videos identified as yours</div></div>
    <div class="stat"><div class="k">Sites affected</div><div class="v">{k.get("n_sites_total") or k["n_domains"]}</div><div class="s">{k["n_domains"]} hosting · rest Google-indexed</div></div>
    <div class="stat q"><div class="k">Takedown quote</div><div class="v">€{k["quote"]:,}</div>
      <div class="band"><small>€250</small><span class="t"><i style="width:{pricepos}%"></i></span><small>€2,500</small></div></div>
  </div>

{google_html}
  <div class="two">
    <section class="card"><h2>Where the leaks are</h2><p class="lead">Top sites by confirmed leak links.</p><div class="bars">{bars}</div></section>
    <section class="card"><h2>What the takedown covers</h2>
      <ul><li>DMCA / abuse notices to every host &amp; registrar</li>
        <li>Google delisting for indexed pages</li>
        <li>Language-mirror &amp; re-upload coverage</li>
        <li>Re-scan on re-uploads · progress updates</li></ul>
      <a class="cta" href="{approve_href}" target="_blank">Approve &amp; start takedowns</a>
      <div class="dmrow" style="margin-top:12px">{dm_btns}</div></section>
  </div>

{cta_html}
{chat_html}
  <section class="card"><h2>All detected leak links <span style="color:var(--mut);font-weight:400">— {len(likely_all):,}</span></h2>
    <p class="lead">Every confirmed URL, grouped by site. Export for your records.</p>
    <div class="qr" style="margin:0 0 12px">
      <button class="btn p" onclick="dl(LINKS,'leak_links.txt')">⬇ Download ({len(likely_all):,})</button>
      <button class="btn" onclick="cp(LINKS)">Copy all</button>
      <span id="cpmsg" style="color:var(--mut);font-size:12.5px;align-self:center"></span></div>
    {likely_links}</section>
  <p class="disclaimer">* These are the most obvious leaks found in this first-pass automated scan. Once we begin, we manually check further and find lots more — across more sites too.</p>
{cta_html}
{chat_html}
  <footer>Confidential — prepared for {esc(k["name"])}. Generated {esc(k["stamp"])} · {k["n_scanned"]} known piracy domains scanned.<br>
    A link counts as a leak only when your handle appears in the file/page URL on a site confirmed to host your media.</footer>
</div>
<script>
const LINKS={likely_js}, F={facts};
const DS_KEY={ds_key_js}, DS_SYS={ds_sys_js}, DS_MODEL={ds_model_js};
async function askAI(hist){{
  const msgs=[{{role:'system',content:DS_SYS}}].concat(hist);
  const r=await fetch('https://api.deepseek.com/chat/completions',{{method:'POST',
    headers:{{'Content-Type':'application/json','Authorization':'Bearer '+DS_KEY}},
    body:JSON.stringify({{model:DS_MODEL||'deepseek-chat',messages:msgs,temperature:0.4,max_tokens:420,stream:false}})}});
  if(!r.ok) throw new Error('ds '+r.status);
  const d=await r.json(); const m=((d.choices||[])[0]||{{}}).message;
  if(!m||!m.content) throw new Error('empty'); return m.content.trim();
}}
function dl(a,n){{const b=new Blob([a.join("\\n")+"\\n"],{{type:"text/plain"}});const u=document.createElement("a");u.href=URL.createObjectURL(b);u.download=n;u.click();URL.revokeObjectURL(u.href);}}
function cp(a){{navigator.clipboard.writeText(a.join("\\n")).then(()=>{{document.getElementById("cpmsg").textContent="copied "+a.length+" links";}});}}
function nf(n){{return (n||0).toLocaleString();}}
function reply(q){{q=q.toLowerCase();
  if(/is this all|all of (them|it|the)|all the leak|that('?s| is) all|only these|just these|everything|complete|the whole|more sites|find more|tip of|is that it|is this it/.test(q)) return `No — these are just the most obvious leaks from a first-pass automated scan. Once we start, we manually dig deeper and almost always find many more, on other sites too. Consider this the tip of the iceberg.`;
  if(/come ?back|comeback|re-?upload|reupload|again|return|resurface|keep coming|new ones|future|monitor|ongoing/.test(q)) return `Some copies do get re-uploaded — we catch and remove those too. For ongoing protection there's an optional low monthly fee, so any new leaks get taken down as they appear.`;
  if(/how many|number|count|total/.test(q)&&!/site/.test(q)) return `We found ${{nf(F.n_likely)}} confirmed copies of your content across ${{F.n_sites_total}} sites (${{F.n_domains}} hosting them directly, the rest indexed on Google), plus ${{nf(F.n_media)}} media files — and this is only a first-pass scan, so there's more still out there.`;
  if(/site|where|which|host|page/.test(q)) return `Your content shows up across ${{F.n_sites_total}} sites so far — ${{F.n_domains}} confirmed hosting it, the rest indexed on Google. The biggest hosts: ${{F.top.slice(0,5).join(', ')}}. Full lists are in the report.`;
  if(/remov|takedown|take down|delete|dmca|report|get.*(down|off|remov)|stop/.test(q)) return `We file DMCA & abuse notices to every host and registrar, request Google delisting, and keep re-scanning for re-uploads. To start, message us on Instagram or Telegram — we handle everything.`;
  if(/cost|price|pay|much|fee|quote|worth|eur|charge/.test(q)) return `Full takedown across all ${{nf(F.n_likely)}} confirmed leaks is €${{nf(F.quote)}} — one flat fee covering every site. Optional low monthly fee after, for re-uploads.`;
  if(/media|photo|video|image|pic|content/.test(q)) return `${{nf(F.n_media)}} media files (photos and videos) were identified as yours — and this is just the first pass, there's more.`;
  if(/verif|proof|sure|real|confiden|accurate|trust/.test(q)) return `Every leak here is confirmed — your handle appears in the file or page URL on a site known to host your media. Name-only guesses were excluded, so this list is the defensible one.`;
  if(/^(hi|hello|hey|thanks|thank you|ok|okay)\b/.test(q)) return `Hi! Ask me which sites host your leaks, whether they come back, how removal works, or the cost.`;
  return `This is only a first-pass scan — there's more out there. I can tell you which sites host the ${{nf(F.n_likely)}}+ leaks found so far, whether they come back, how removal works, or the €${{nf(F.quote)}} cost. Or message us on Instagram / Telegram.`;
}}
function wireChat(sec){{
  const log=sec.querySelector('.clog');if(!log)return;
  const hist=[];
  const push=(t,who)=>{{const d=document.createElement('div');d.className='msg '+who;d.textContent=t;log.appendChild(d);log.scrollTop=log.scrollHeight;return d;}};
  const ask=async q=>{{
    push(q,'me'); hist.push({{role:'user',content:q}});
    if(DS_KEY){{
      const b=push('…','bot');
      try{{const a=await askAI(hist.slice(-8)); b.textContent=a; hist.push({{role:'assistant',content:a}});}}
      catch(e){{const a=reply(q); b.textContent=a; hist.push({{role:'assistant',content:a}});}}
    }} else {{
      setTimeout(()=>{{const a=reply(q); push(a,'bot'); hist.push({{role:'assistant',content:a}});}},240);
    }}
  }};
  sec.querySelectorAll('.qr b').forEach(b=>b.addEventListener('click',()=>ask(b.dataset.q)));
  const form=sec.querySelector('.cform');
  if(form)form.addEventListener('submit',e=>{{e.preventDefault();const i=sec.querySelector('.cin');const v=i.value.trim();if(!v)return;i.value='';ask(v);}});
  push(`I found ${{nf(F.n_likely)}} confirmed copies of your content across ${{F.n_sites_total}} sites so far — and this is just a first-pass scan, there's more out there. Ask me anything, or tap a question below.`,'bot');
}}
document.querySelectorAll('.chat').forEach(wireChat);
// drag-to-scroll + tap-to-reveal for the full-size Google-results row
document.querySelectorAll('.dragrow').forEach(row=>{{
  let down=false,sx=0,sl=0,moved=0;
  row.addEventListener('pointerdown',e=>{{down=true;moved=0;sx=e.clientX;sl=row.scrollLeft;row.classList.add('drag');}});
  window.addEventListener('pointerup',()=>{{down=false;row.classList.remove('drag');}});
  row.addEventListener('pointerleave',()=>{{down=false;row.classList.remove('drag');}});
  row.addEventListener('pointermove',e=>{{if(!down)return;const dx=e.clientX-sx;moved+=Math.abs(dx);row.scrollLeft=sl-dx;}});
  row.querySelectorAll('.gt,.mt').forEach(t=>t.addEventListener('click',e=>{{
    if(moved>6){{e.preventDefault();return;}}
    if(e.target.closest('a'))return;
    t.classList.toggle('show');
  }}));
}});
</script>
</body></html>'''


if __name__ == "__main__":
    main()

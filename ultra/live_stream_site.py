#!/usr/bin/env python3
"""
live_stream_site.py — a multi-user LIVE leak-report app ("watch the leaks come in").

Like public_app.py, but LIVE: hit Start and a real deep scan runs while you watch — first the
Google/CSE images + index data print, then the deep crawl streams every de-duplicated leak image
into the wall as it's found. MANY people can run and watch their OWN scans at once: each scan mints
its own unguessable slug and a shareable **/s/<slug>** report link (▸ Copy report link), exactly like
public_app.py's /s/<slug> share. Every API call carries ?job=<slug>, so sessions are fully isolated.

- Each scan runs on its OWN webscan_<sha1(slug)> scratch prefix (never collides / cross-deletes).
- The pipeline runs in TWO live phases: 1) scan,cse,gshots (Google/CSE evidence first) then
  2) seed,crawl,clean,triage,gallery,export (the deep scrape streams in, de-duplicated).
- Videos with no thumbnail are skipped on the wall; links are de-duped (normalized) from the start.
- The exact full-run command stays on screen (copy to reproduce); a "Collected links" box exports
  the complete de-duped list + a raw-vs-kept diff for later verification.
- Concurrency: up to MAX_LIVE_SCANS scans admitted (else 'busy'); the pipeline subprocess itself is
  serialized (shared slugs_cache.json) so a queued scan just waits its turn.

Stdlib only (ThreadingHTTPServer + SSE), matching public_app.py's http.server style.

    python3 live_stream_site.py                       # multi-user live app, port 8090
    PORT=9100 python3 live_stream_site.py --no-open
    REPORT_PREFIX=creatorj python3 live_stream_site.py   # open ONE existing campaign on /
    python3 live_stream_site.py --mode replay --rate 60      # legacy: TEST the stream plumbing
"""
from __future__ import annotations
import argparse, hashlib, html, json, os, random, re, secrets, sys, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE_TOKEN = os.environ.get("LIVE_TOKEN", "")   # if set, gate all routes behind ?t=<token>


def _load_env_file(path):
    """Tiny stdlib .env loader (so DM_*/DEEPSEEK_* work without importing web_common)."""
    try:
        for ln in open(path, encoding="utf-8"):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except OSError:
        pass


_load_env_file(os.path.join(HERE, ".env"))

DM = {"instagram": os.environ.get("DM_INSTAGRAM", ""),
      "whatsapp": os.environ.get("DM_WHATSAPP", ""),
      "telegram": os.environ.get("DM_TELEGRAM", "")}
PIPELINE = os.path.join(HERE, "pipeline_steps.py")
KB_FILE = os.path.join(HERE, "kb.json")
SCAN_ENABLED = os.environ.get("SCAN_ENABLED", "1").lower() in ("1", "true", "yes") \
    and os.path.exists(PIPELINE)

# Optional DeepSeek chat + subprocess helpers — reuse the existing modules when present
# (they ship on the local box; a minimal deploy without them degrades gracefully).
try:
    import web_common as _wc          # noqa: N813
    import chat_proxy as _chat
    _HAVE_CHAT = bool(os.environ.get("DEEPSEEK_API_KEY"))
except Exception:
    _wc = _chat = None
    _HAVE_CHAT = False

VID_EXT = (".mp4", ".webm", ".mov", ".m4v", ".ts")
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp")


def kind_of(url: str) -> str:
    u = url.lower().split("?", 1)[0]
    if u.endswith(VID_EXT) or "preview.mp4" in u or "/mp4/" in u:
        return "video"
    if u.endswith(IMG_EXT):
        return "image"
    return "media"


def _dash_to_domain(stem: str) -> str:
    """'thefappening-plus' -> 'thefappening.plus' (gallery filename → host)."""
    i = stem.rfind("-")
    return (stem[:i] + "." + stem[i + 1:]) if i > 0 else stem


def _rel(path: str) -> str:
    return os.path.relpath(os.path.abspath(path), HERE)


IMGX = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")


def _load_cse_thumbs(prefix: str, limit: int = 40) -> list:
    """CSE Google-Images thumbnails as base64 data: URIs from {prefix}.cse.json — REAL, Google-indexed
    leak images (encrypted-tbn0.gstatic.com), relevance-matched and self-contained (they load instantly
    and can't be hotlink-blocked). The CORRECT source for the Google-evidence masonry — never the raw
    crawl chrome (picazor flags/mascots) that only survived because it happened to load."""
    if not prefix:
        return []
    base = os.path.basename(prefix)
    for cand in (os.path.join(HERE, f"{prefix}.cse.json"),
                 os.path.join(HERE, "campaigns", base, f"{base}.cse.json")):
        try:
            d = json.load(open(cand, encoding="utf-8"))
        except Exception:
            continue
        out = []
        for m in (d.get("img_meta") or []):
            data = m.get("data")
            if data and isinstance(data, str) and data.startswith("data:"):
                out.append({"src": data, "host": m.get("host", ""), "title": (m.get("title") or "")[:90]})
            if len(out) >= limit:
                break
        return out
    return []


def build_catalog(assets_dir: str, prefix: str) -> dict:
    """Index the campaign's visual evidence: per-domain gallery screenshots, CSE image thumbnails
    (base64 `gimages` from cse.json = the real Google-indexed leak images), CSE result-page grid
    captures, and the synthetic 'leak index' link cards. Repo-root-relative paths serve via /asset
    (path-jailed); gimages are self-contained.

    Artifacts get SPLIT across locations mid-run: phase-1 outputs (_images: grids + linkcards, cse)
    land at the repo ROOT, while phase-2 `_out` writes (_gallery_imgs, triage) go to campaigns/<base>/
    once that dir exists — which also flips _assets_dir_for() to the campaign dir. Indexing a single
    dir would then silently drop the grids + link cards from the live view, so scan BOTH roots and
    dedupe by filename."""
    cat = {"gallery": [], "cse": [], "grids": [], "linkcards": [],
           "gimages": _load_cse_thumbs(prefix)}
    base = os.path.basename(prefix)
    roots = []
    for r in (assets_dir, HERE, os.path.join(HERE, "campaigns", base)):
        if r and os.path.isdir(r) and r not in roots:
            roots.append(r)
    if not roots:
        return cat

    # per-domain page screenshots — gallery.txt maps some to a host; rest via dash rule
    dommap = {}
    for r in roots:
        gfile = os.path.join(r, f"{prefix}_gallery.txt")
        if os.path.exists(gfile):
            for ln in open(gfile, encoding="utf-8"):
                if "|" in ln:
                    p, dom = ln.rstrip("\n").split("|", 1)
                    if dom.strip():
                        dommap.setdefault(os.path.basename(p), dom.strip())

    seen_gal, seen_cse, seen_grid, seen_lc = set(), set(), set(), set()
    for r in roots:
        gdir = os.path.join(r, f"{prefix}_gallery_imgs")
        if os.path.isdir(gdir):
            for fn in sorted(os.listdir(gdir)):
                if fn.lower().endswith(IMGX) and fn not in seen_gal:
                    seen_gal.add(fn)
                    dom = dommap.get(fn) or _dash_to_domain(os.path.splitext(fn)[0])
                    cat["gallery"].append({"domain": dom, "src": _rel(os.path.join(gdir, fn))})

        # CSE image-search thumbnails (real Google Images results per query variant)
        idir = os.path.join(r, f"{prefix}_images", "google")
        if os.path.isdir(idir):
            for q in sorted(os.listdir(idir)):
                qd = os.path.join(idir, q)
                if os.path.isdir(qd):
                    for fn in sorted(os.listdir(qd)):
                        key = f"{q}/{fn}"
                        if fn.lower().endswith(IMGX) and key not in seen_cse:
                            seen_cse.add(key)
                            cat["cse"].append({"query": q.replace("-", " "),
                                               "src": _rel(os.path.join(qd, fn))})

        # CSE result-page grid captures — _images = browser capture, _images_cse = synthetic/CSE.
        # linkcard_*.png = the synthetic 'leak index' link screenshots (build_linkcards.py).
        for sub, tag in ((f"{prefix}_images", "capture"), (f"{prefix}_images_cse", "synthetic")):
            d = os.path.join(r, sub)
            if os.path.isdir(d):
                for fn in sorted(os.listdir(d)):
                    if not fn.lower().endswith((".png", ".jpg")):
                        continue
                    if fn.startswith("google_images") and fn not in seen_grid:
                        seen_grid.add(fn)
                        cat["grids"].append({"src": _rel(os.path.join(d, fn)), "tag": tag})
                    elif fn.startswith("linkcard") and fn not in seen_lc:
                        seen_lc.add(fn)
                        cat["linkcards"].append({"src": _rel(os.path.join(d, fn))})
    return cat


# ── deep-report bridge (parity with public_app.py /s/<slug> share) ────────────
PER_DOMAIN_LINKS = int(os.environ.get("PER_DOMAIN_LINKS", "0"))   # max URLs kept per site (0 = unlimited)
LINKS_CAP = int(os.environ.get("LINKS_CAP", "0"))                # hard ceiling on grouped URLs (0 = unlimited)


def price_for(n, lo_n=150, lo_p=250, hi_n=20000, hi_p=2500, cap=500):
    """One-time takedown quote scaled to the confirmed-leak count — identical slope to
    public_app/make_report (150 leaks -> €250 … 20000 -> €2500, rounded to €10), but the
    payable quote is capped at €500 (floor stays €250)."""
    if n <= lo_n:
        return lo_p
    val = hi_p if n >= hi_n else int(round((lo_p + (n - lo_n) * (hi_p - lo_p) / (hi_n - lo_n)) / 10.0) * 10)
    return min(cap, val)


def monthly_for(quote, lo_q=250, hi_q=500, lo_m=200, hi_m=250):
    """Recurring monthly monitoring fee (€200–€250), placed on its band to match where the
    one-time quote sits on its €250–€500 band (so it maxes when the quote caps at €500)."""
    if quote <= lo_q:
        return lo_m
    if quote >= hi_q:
        return hi_m
    return int(round((lo_m + (quote - lo_q) * (hi_m - lo_m) / (hi_q - lo_q)) / 10.0) * 10)


def _registrable(host: str) -> str:
    """Coarse registrable domain (last two labels) — enough for the sites-affected counts."""
    parts = [p for p in (host or "").strip().lower().lstrip(".").split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else (parts[0] if parts else "")


def _p_cse(prefix: str) -> str:
    """Path to {prefix}.cse.json (repo root or campaigns/<base>/) if it exists yet, else ''. Used to
    surface the Google-CSE evidence the moment the CSE step finishes — before any crawl checkpoint."""
    if not prefix:
        return ""
    base = os.path.basename(prefix)
    for cand in (os.path.join(HERE, f"{prefix}.cse.json"),
                 os.path.join(HERE, "campaigns", base, f"{base}.cse.json")):
        if os.path.exists(cand):
            return cand
    return ""


def _cse_json(prefix: str) -> dict:
    """Load the campaign's Google-CSE bridge ({prefix}.cse.json at the repo root or in
    campaigns/<base>/) → {cse_sites, top_leaks, google_total, img_meta, images}. This is what
    feeds the 'Google search results' grids + the 'Also all over Google' breakdown. Never raises."""
    out = {"cse_sites": [], "top_leaks": [], "google_total": 0, "img_meta": [], "images": []}
    if not prefix:
        return out
    base = os.path.basename(prefix)
    for cand in (os.path.join(HERE, f"{prefix}.cse.json"),
                 os.path.join(HERE, "campaigns", base, f"{base}.cse.json")):
        if not os.path.exists(cand):
            continue
        try:
            d = json.load(open(cand, encoding="utf-8"))
        except Exception:
            break
        out["cse_sites"] = [{"domain": s.get("domain"), "url": s.get("url", ""),
                             "occ": s.get("occ", 0)}
                            for s in (d.get("sites") or []) if s.get("domain")][:60]
        out["top_leaks"] = [u for u in (d.get("top_leaks") or []) if u][:14]
        out["google_total"] = d.get("google_total") or 0
        out["img_meta"] = (d.get("img_meta") or [])[:14]
        out["images"] = (d.get("images") or [])[:18]
        break
    return out


def _assets_dir_for(prefix: str) -> str:
    d = os.path.join(HERE, "campaigns", os.path.basename(prefix))
    return d if os.path.isdir(d) else HERE


def _augment_report(rep: dict, prefix: str) -> dict:
    """Fold the Google-CSE breakdown + derived headline stats into a report dict (used for both
    the final export report and the live-crawl report), so the deep 'Google search results' and
    'Also all over Google' sections + the takedown quote render from real data."""
    cse = _cse_json(prefix)
    rep["cse_sites"] = cse["cse_sites"]
    rep["top_leaks"] = cse["top_leaks"]
    rep["google_total"] = cse["google_total"]
    rep["handle"] = (rep.get("aliases") or
                     [os.path.basename(prefix).replace("webscan_", "")])[0]
    host_reg = {_registrable(d["domain"]) for d in rep.get("domains", []) if d.get("domain")}
    cse_reg = {_registrable(s["domain"]) for s in cse["cse_sites"] if s.get("domain")}
    rep["n_hosting"] = len(host_reg)
    rep["n_sites"] = len(host_reg | cse_reg) or len(host_reg)
    rep["quote"] = price_for(rep.get("likely") or rep.get("total") or 0)
    rep["monthly"] = monthly_for(rep["quote"])
    return rep


def build_report(assets_dir: str, prefix: str) -> dict:
    """Load the REAL leak data into a report model (matches the make_report.py headline):
    the DMCA export metadata.jsonl (LIKELY/POSSIBLE buckets) is authoritative for counts and the
    grouped link list; the clean crawl adds page counts; direct_media_urls*.txt gives the media #.
    Returns totals + per-domain counts + links grouped by domain + the Google-CSE breakdown."""
    rep = {"likely": 0, "possible": 0, "total": 0, "pages": 0, "direct_media": 0,
           "domains": [], "by_domain": {}, "aliases": []}
    exdir = os.path.join(HERE, "exports", f"{prefix}_latest")
    meta = os.path.join(exdir, "metadata.jsonl")
    dom_counts, dom_likely, by_domain = {}, {}, {}
    by_dom_total = 0
    if os.path.exists(meta):
        for ln in open(meta, encoding="utf-8"):
            try:
                r = json.loads(ln)
            except Exception:
                continue
            dom, url, bucket = r.get("domain", "?"), r.get("url", ""), r.get("bucket", "")
            if not url:
                continue
            dom_counts[dom] = dom_counts.get(dom, 0) + 1
            if bucket == "LIKELY":
                rep["likely"] += 1
                dom_likely[dom] = dom_likely.get(dom, 0) + 1
            elif bucket == "POSSIBLE":
                rep["possible"] += 1
            lst = by_domain.setdefault(dom, [])
            if (PER_DOMAIN_LINKS <= 0 or len(lst) < PER_DOMAIN_LINKS) and \
               (LINKS_CAP <= 0 or by_dom_total < LINKS_CAP):
                lst.append({"url": url, "kind": kind_of(url), "bucket": bucket})
                by_dom_total += 1
    rep["total"] = rep["likely"] + rep["possible"]
    # direct media URL count (headline stat)
    if os.path.isdir(exdir):
        for fn in os.listdir(exdir):
            if fn.startswith("direct_media_urls") and fn.endswith(".txt"):
                try:
                    rep["direct_media"] += sum(
                        1 for l in open(os.path.join(exdir, fn), encoding="utf-8")
                        if l.strip() and not l.startswith("#"))
                except OSError:
                    pass
    # page counts from the clean crawl — search assets_dir first, then fall back to the newest
    # checkpoint anywhere for this prefix (root / campaigns/), so a share rebuilt from disk still
    # shows its page count instead of 0.
    cp = None
    for name in (f"{prefix}.crawl.clean.json", f"{prefix}.crawl.json"):
        cand = os.path.join(assets_dir, name)
        if os.path.exists(cand):
            cp = cand
            break
    cp = cp or _newest_crawl(prefix)
    if cp and os.path.exists(cp):
        rep["pages"] = sum(len(r["pages"]) for r in load_crawl(cp))
    # aliases (hero chips): the CLEAN real-username list (all of it) is preferred; only fall back to
    # the combinatorial {prefix}-aliases.txt (capped) when no clean list was persisted.
    rep["aliases"] = _real_aliases_for(prefix)
    if not rep["aliases"]:
        for cand in (os.path.join(assets_dir, f"{prefix}-aliases.txt"),
                     os.path.join(exdir, f"{prefix}-aliases.txt")):
            if os.path.exists(cand):
                rep["aliases"] = [l.strip() for l in open(cand, encoding="utf-8") if l.strip()][:10]
                break
    rep["domains"] = [{"domain": d, "n": dom_counts[d], "likely": dom_likely.get(d, 0)}
                      for d in sorted(dom_counts, key=lambda x: -dom_counts[x])]
    rep["by_domain"] = by_domain
    _augment_report(rep, prefix)
    return rep


def _empty_report(aliases=None) -> dict:
    return {"likely": 0, "possible": 0, "total": 0, "pages": 0, "direct_media": 0,
            "domains": [], "by_domain": {}, "aliases": aliases or [], "phase": "idle",
            "cse_sites": [], "top_leaks": [], "google_total": 0,
            "handle": (aliases or [""])[0], "n_hosting": 0, "n_sites": 0, "quote": 0}


def _newest_crawl(prefix: str):
    """Newest crawl checkpoint for a prefix (root or campaigns/<prefix>), clean preferred."""
    cands = []
    bn = os.path.basename(prefix)                       # root files carry the folder; campaign copies don't
    for root, pfx in ((HERE, prefix), (os.path.join(HERE, "campaigns", bn), bn)):
        for name in (f"{pfx}.crawl.clean.json", f"{pfx}.crawl.json"):
            p = os.path.join(root, name)
            if os.path.exists(p):
                cands.append(p)
    return max(cands, key=os.path.getmtime) if cands else None


def _norm_media(u: str) -> str:
    """Normalize a media URL for de-duplication: drop scheme, querystring, and trailing slash,
    lowercase the host. A leaked file mirrored under http/https or with tracking params is ONE
    leak, not several — this is the dedup the raw crawl doesn't do."""
    s = (u or "").split("?", 1)[0].split("#", 1)[0]
    s = s.split("://", 1)[-1].rstrip("/").lower()
    return s


def _report_from_crawl(cp: str, aliases=None) -> dict:
    """Preliminary report built from the GROWING crawl checkpoint — counts/domains/links fill in
    live as a scan runs (before the DMCA export exists). All provisionally LIKELY.

    HEADLINE ('total'/'likely') = de-duplicated MEDIA files + the handle-bearing PAGES that host
    them on confirmed sites — i.e. every distinct infringing URL, which is the takedown-actionable
    count and the LARGE number the client sees. 'direct_media' stays the media-only subset (the
    conservative "confirmed copies of the actual content" figure competitors report), and the live
    wall/generated screenshots stay MEDIA-only + filtered so only real leaked images ever show.

    Media is run through the SAME real-leak filter the wall uses (_wall_keep_media): SEO-spam /
    face-search domains blocked, chrome/icon/thumbnail junk dropped, catch-all other-creator domains
    removed, and every file de-duplicated on its base image id (so 4 WordPress sizes of one photo
    count once). Pages are counted ONLY on domains that survived that filter (confirmed hosting), so
    junk/tube domains inflate neither the media nor the page tally. That keeps the split honest: a big
    'infringing URLs' headline the client can defend, backed by a clean media subset and clean wall."""
    rep = _empty_report(aliases)
    rep["phase"] = "scanning"
    tokens = {t for t in (_slug_tokens(a) for a in (aliases or [])) if len(t) >= 4}
    total = pages = 0
    doms, by_domain = [], {}
    seen, pseen = set(), set()
    for r in sorted(load_crawl(cp), key=lambda x: -len(x.get("media", []))):
        pg = r["pages"]
        # real-leak filter + global de-dup on the base image id → unique leaked files only
        m = []
        for u in _wall_keep_media(r, tokens):
            k = _base_image_id(u)
            if not k or k in seen:
                continue
            seen.add(k)
            m.append(u)
        if not m:
            continue                                   # page-only / junk / other-creator hit
        mn = len(m)
        # count this domain's PAGES the way the export/download does: every CONFIRMED-host page (its
        # media carries the handle) PLUS its locale mirrors (leakgallery.com/it/…, es.fapeza.com/…),
        # each a distinct takedown URL. Non-mirror hosts add 1 per page; junk/other-creator hosts carry
        # no handle → contribute 0. Per-domain n = media + its own pages, so the per-site bar counts SUM
        # to the ~18k headline (they used to show media-only and under-counted mirror-heavy sites).
        pn = 0
        pageurls = []                                  # this domain's own pages/mirrors, kept for the listing
        if not _HAVE_CLEAN or any(_CLEAN.carries_handle(u, tokens) for u in m):
            for p in pg:
                for v in [p] + _locale_variants(p):     # canonical page + its locale mirrors
                    if v and v not in pseen:            # exact-URL dedup, same as the download set
                        pseen.add(v)
                        pn += 1
                        pageurls.append(v)
        n = mn + pn
        doms.append({"domain": r["domain"], "n": n, "likely": n})
        total += mn                                    # direct_media = media-only subset across all sites
        pages += pn
        # LISTING order: the WEBPAGES that display the leak come FIRST (leakgallery.com/<handle>/… — the
        # best takedown targets and what a human wants to open), then the raw media/CDN files. A pure-CDN
        # host (cdn.leakgallery.com, fapeza media) has no page, so it correctly shows media — that's not
        # luck, it's that only page-hosting domains HAVE a page to link. Capped so a 14k-mirror domain
        # doesn't dump every row into one group (the UI shows the first ~800 anyway).
        cap = PER_DOMAIN_LINKS if PER_DOMAIN_LINKS > 0 else 800
        ents = ([{"url": u, "kind": "page", "bucket": "LIKELY"} for u in pageurls]
                + [{"url": u, "kind": kind_of(u), "bucket": "LIKELY"} for u in m])
        by_domain[r["domain"]] = ents[:cap]
    # HEADLINE = distinct infringing URLs = de-duped media files + pages on those confirmed sites.
    # direct_media stays the media-only subset (the conservative figure). pages are already only from
    # domains that passed _wall_keep_media (loop `continue`s on media-empty records), so no junk here.
    combined = total + pages
    doms.sort(key=lambda d: -d["n"])                    # most-to-least, so bars/groups/top all rank by size
    rep.update({"likely": combined, "total": combined, "pages": pages, "direct_media": total,
                "domains": doms, "by_domain": by_domain})
    return rep


def _real_aliases_path(prefix: str) -> str:
    """Stable file holding the CLEAN real usernames for a prefix (survives the scratch wipe)."""
    return os.path.join(HERE, f"{prefix}.real_aliases.txt")


def _write_real_aliases(prefix: str, names) -> None:
    """Persist the clean real-username list so every later report (final export, rebuilt-from-disk)
    can show ALL the actual usernames as chips, not just the handle or the combinatorial variants."""
    clean = list(dict.fromkeys(n.strip() for n in (names or []) if n and n.strip()))
    if not clean:
        return
    try:
        path = _real_aliases_path(prefix)
        os.makedirs(os.path.dirname(path) or HERE, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(clean) + "\n")
    except OSError:
        pass


def _real_aliases_for(prefix: str) -> list:
    """The CLEAN real usernames (handle + user + title-harvested) written at scan start — preferred
    for report chips over the pipeline's combinatorial {prefix}-aliases.txt expansion."""
    base = os.path.basename(prefix)
    for cand in (_real_aliases_path(prefix),
                 os.path.join(HERE, "campaigns", base, f"{base}.real_aliases.txt")):
        try:
            return [l.strip() for l in open(cand, encoding="utf-8") if l.strip()][:40]
        except OSError:
            continue
    return []


def _aliases_for(prefix: str) -> list:
    """The handle + aliases the pipeline wrote to {prefix}-aliases.txt (repo root or campaigns/),
    so a report opened by prefix / rebuilt from disk names the creator instead of the webscan_ hash.
    Prefers the CLEAN real-username list; falls back to the combinatorial alias file (capped)."""
    real = _real_aliases_for(prefix)
    if real:
        return real
    base = os.path.basename(prefix)
    for cand in (os.path.join(HERE, f"{prefix}-aliases.txt"),
                 os.path.join(HERE, "campaigns", base, f"{base}-aliases.txt")):
        try:
            return [l.strip() for l in open(cand, encoding="utf-8") if l.strip()][:10]
        except OSError:
            continue
    return []


def build_report_live(assets_dir: str, prefix: str, scan=None) -> dict:
    """The report the site shows, resolved to the RICHEST source for the handle:
      · a scan actively running under this prefix → the GROWING crawl checkpoint (numbers climb
        live), with the resolved campaign's Google-CSE evidence folded in;
      · otherwise the full DMCA export (real campaign preferred over the webscan scratch subset);
      · otherwise the growing crawl / an empty 0-state prompting a scan.
    `scan` is this session's ScanJob (or None) — used for the running flag + handle chips.
    All branches carry the deep 'Google search results' + 'Also all over Google' fields."""
    handle = (scan.handle if scan else "") or ""
    if not prefix:
        return _empty_report()
    # Handle/alias chips: show ALL the real usernames — the live scan's full harvested list first
    # (handle + title-harvested aliases), else the clean list persisted to disk, else just the handle.
    # (_aliases_for itself now prefers the clean real-username file over the combinatorial expansion.)
    al = ((list(scan.aliases) if scan and getattr(scan, "aliases", None) else None)
          or _aliases_for(prefix)
          or ([handle] if handle else None) or None)
    running = bool(scan and scan.running and scan.prefix == prefix)
    adir = _assets_dir_for(prefix)
    cp = _newest_crawl(prefix)
    meta = os.path.join(HERE, "exports", f"{prefix}_latest", "metadata.jsonl")
    is_scan = os.path.basename(prefix).startswith("webscan_")
    # A live scan is driven by ITS OWN growing crawl checkpoint: real leaks stream in and the count
    # climbs as the crawler finds them. We NEVER fall back to a different campaign's cached export —
    # that was the "reuse old data" bug. Once the scan is DONE and its own export exists, we switch
    # to that export: with locale-mirror expansion it is now the FULLER "every removable URL" view
    # (~18k) — the post-clean crawl branch below dedups to the ~6k media+pages subset, which used to
    # be the bigger of the two but no longer is. (build_report reads THIS prefix's export only, so
    # the no-cross-campaign-reuse guarantee holds.)
    if cp and running:
        rep = _report_from_crawl(cp, aliases=al)
        _augment_report(rep, prefix)
        rep["phase"] = "scanning"
        return rep
    if cp and is_scan and not os.path.exists(meta):
        rep = _report_from_crawl(cp, aliases=al)     # done webscan_ scan but export missing → crawl
        _augment_report(rep, prefix)
        rep["phase"] = "done"
        return rep
    # PRE-CRAWL (phase 1): the CSE step finishes while the presence scan is still running, before any
    # crawl checkpoint exists. Surface the Google-CSE evidence NOW so the 'top leak results' (Google
    # search links + evidence images) show BEFORE the deep crawl starts streaming — then the crawl
    # branch above takes over and the counts climb.
    if running:
        # A running scan is ALWAYS in the "scanning" phase — even before the first crawl checkpoint or
        # cse.json exists. This closes the early dead-window where _empty_report returned phase="idle",
        # which made the producer's `rep.phase=='scanning'` gate fail and suppressed media streaming
        # until the first artifact landed. _augment_report folds in CSE evidence if/when it's there.
        rep = _empty_report(al)
        _augment_report(rep, prefix)
        rep["phase"] = "scanning"
        return rep
    # Opened to VIEW an existing campaign (REPORT_PREFIX=<slug>) → its classified DMCA export.
    if os.path.exists(meta):
        rep = build_report(adir, prefix)
        rep["phase"] = "done"
        return rep
    if cp:                                       # a crawl exists but no export → show the crawl
        rep = _report_from_crawl(cp, aliases=al)
        _augment_report(rep, prefix)
        rep["phase"] = "done"
        return rep
    return _empty_report(al)


def send_links_mail(to_addr: str, prefix: str, bucket: str = "LIKELY") -> str:
    """Email the detected leak links to `to_addr` via SMTP (Namecheap Private Email in .env).
    Returns '' on success or an error string."""
    import smtplib
    import ssl
    from email.message import EmailMessage
    host = os.environ.get("SMTP_HOST", "")
    port = int(os.environ.get("SMTP_PORT", "465") or 465)
    user = os.environ.get("SMTP_USER", "")
    pwd = os.environ.get("SMTP_PASSWORD", "")
    frm = os.environ.get("SMTP_FROM_EMAIL", user)
    frn = os.environ.get("SMTP_FROM_NAME", "Leak report")
    if not (host and user and pwd):
        return "email not configured on this host"
    links = full_links(prefix, bucket)
    if not links:
        return "no links to send yet"
    body = (f"Detected leak links for {prefix or 'scan'} ({bucket or 'ALL'}, {len(links)}):\n\n"
            + "\n".join(links) + "\n")
    msg = EmailMessage()
    msg["Subject"] = f"Leak links — {prefix or 'scan'} ({len(links)} {bucket or 'ALL'})"
    msg["From"] = f"{frn} <{frm}>"
    msg["To"] = to_addr
    msg.set_content(f"{len(links)} links attached as collected_leak_links.txt.\n")
    msg.add_attachment(body.encode("utf-8"), maintype="text", subtype="plain",
                       filename="collected_leak_links.txt")
    try:
        ctx = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
                s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls(context=ctx)
                s.login(user, pwd)
                s.send_message(msg)
        return ""
    except Exception as e:
        return f"send failed: {e}"


def _crawl_media_links(cp: str, tokens: set = None, include_pages: bool = True) -> list:
    """Every leak URL from a crawl checkpoint for the export/download/mail set.

    MEDIA: run through _wall_keep_media (junk/block/catch-all) and de-duped on the base image id
    (WordPress size variants collapse), so exported files match the on-screen leaks and carry no
    chrome/other-creator junk. `tokens` = handle slugs for the catch-all pass.

    PAGES (include_pages): for every record on a CONFIRMED-HOSTING site — one whose surviving media
    includes a file whose URL carries the handle (export_dmca's own confirmation rule) — also emit its
    gallery PAGE urls AND each page's locale-mirror variants (leakgallery.com/it/…, es.fapeza.com/…).
    Every locale is a separately-indexed page and thus a distinct takedown URL, so pages/mirrors are
    de-duped on the EXACT url only (never collapsed). Requiring a handle-bearing media file (not merely
    non-empty media) keeps directory/chrome hosts — a few flag icons, no real leak — from contributing
    pages, matching what the report counts."""
    tokens = tokens or set()
    out, seen, pseen = [], set(), set()
    for r in load_crawl(cp):
        keep = _wall_keep_media(r, tokens)
        for u in keep:
            k = _base_image_id(u)
            if k and k not in seen:
                seen.add(k)
                out.append(u)
        # confirmed host = surviving media carries the handle → keep its pages + locale mirrors
        confirmed = bool(keep) and (
            not _HAVE_CLEAN or any(_CLEAN.carries_handle(u, tokens) for u in keep))
        if include_pages and confirmed:
            for p in (r.get("pages") or []):
                for v in [p] + _locale_variants(p):
                    if v and v not in pseen:
                        pseen.add(v)
                        out.append(v)
    return out


def _raw_crawl(prefix: str):
    """The UN-cleaned {prefix}.crawl.json (truly raw — before clean_crawl stripped other-creator /
    trap URLs), root or campaigns/<prefix>/. Used for the RAW side of the de-dup diff."""
    bn = os.path.basename(prefix)                       # root file carries the folder; campaign copy doesn't
    for root, pfx in ((HERE, prefix), (os.path.join(HERE, "campaigns", bn), bn)):
        p = os.path.join(root, f"{pfx}.crawl.json")
        if os.path.exists(p):
            return p
    return _newest_crawl(prefix)


def full_links(prefix: str, bucket: str = "") -> list:
    """Every detected leak URL for copy-all / download / mail. A webscan / live scan is driven by its
    crawl, so it returns the de-duped MEDIA files PLUS every handle-bearing gallery PAGE (and each
    page's locale mirrors) on confirmed-hosting sites — the full takedown-actionable URL set, matching
    the report's headline count. A real campaign uses its classified DMCA export instead."""
    is_scan = os.path.basename(prefix).startswith("webscan_")
    cp = _newest_crawl(prefix)
    tokens = _handle_tokens(prefix)
    meta = os.path.join(HERE, "exports", f"{prefix}_latest", "metadata.jsonl")
    # webscan / live scan → the crawl's de-duped media + confirmed-host pages & their locale mirrors
    if is_scan and cp and bucket != "POSSIBLE":
        return _crawl_media_links(cp, tokens)
    if os.path.exists(meta):
        out = []
        for ln in open(meta, encoding="utf-8"):
            try:
                r = json.loads(ln)
            except Exception:
                continue
            u = r.get("url", "")
            if u and (not bucket or r.get("bucket") == bucket):
                out.append(u)
        return out
    if cp and bucket != "POSSIBLE":
        return _crawl_media_links(cp, tokens)
    return []


def dedup_diff_lines(prefix: str) -> list:
    """Verification aid: KEPT vs RAW so you can diff them and confirm no real leak was lost.
    KEPT = the exact de-duplicated leaked-file links the report page shows (full_links). RAW = every
    URL the crawl ORIGINALLY surfaced (the un-cleaned {prefix}.crawl.json — media AND pages, nothing
    dropped). Diff the two to see exactly what clean + de-dup removed (other-creator media on shared
    aggregators, responsive-size / mirror variants, trap pages) and check every removal is correct."""
    raw_cp = _raw_crawl(prefix) if prefix else None
    raw = [u for r in (load_crawl(raw_cp) if raw_cp else [])
           for u in (r.get("media") or []) + (r.get("pages") or [])]
    kept = full_links(prefix) if prefix else []
    return ([f"# === KEPT ({len(kept)}) — the de-duplicated leaked-file links the report shows ==="] + kept
            + ["", f"# === RAW ({len(raw)}) — every URL the crawl first found (media + pages, pre-clean) ==="]
            + raw)


CTYPE = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
         ".webp": "image/webp", ".gif": "image/gif", ".avif": "image/avif"}

try:
    from PIL import Image as _PILImage
    _HAVE_PIL = True
except Exception:
    _HAVE_PIL = False

_thumb_cache: dict = {}
_thumb_lock = threading.Lock()


def asset_bytes(full: str, ext: str, width: int):
    """Return (content_type, bytes). With width>0 and Pillow present, downscale to `width`px
    and cache — the CSE grid PNGs are ~2.5 MB each, so serving a ~40 KB JPEG thumbnail instead
    is the single biggest speed win for the wall (57 MB of assets → a few MB)."""
    if not width or not _HAVE_PIL:
        with open(full, "rb") as fh:
            return CTYPE.get(ext, "application/octet-stream"), fh.read()
    key = (full, width)
    with _thumb_lock:
        hit = _thumb_cache.get(key)
    if hit:
        return hit
    try:
        from io import BytesIO
        im = _PILImage.open(full)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        w, h = im.size
        if w > width:
            im = im.resize((width, max(1, round(h * width / w))), _PILImage.LANCZOS)
        buf = BytesIO()
        im.save(buf, "JPEG", quality=78, optimize=True)
        res = ("image/jpeg", buf.getvalue())
    except Exception:
        with open(full, "rb") as fh:
            res = (CTYPE.get(ext, "application/octet-stream"), fh.read())
    with _thumb_lock:
        _thumb_cache[key] = res
    return res


# ── remote media proxy (live wall) ───────────────────────────────────────────
# A fresh scan has no local screenshots yet, so the live image wall is fed straight from the
# de-duplicated media URLs the crawl surfaces. We proxy + thumbnail them here: a browser UA
# sidesteps most hotlink blocks, Pillow downscales so the wall stays light, and a cache makes
# re-requests instant. Never raises — a dead URL just returns 404 and the client drops the tile.
_MEDIA_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
_media_cache: dict = {}
_media_lock = threading.Lock()
_MEDIA_CACHE_CAP = 500
_MEDIA_MAX_BYTES = 10_000_000


def _thumb_from_bytes(data: bytes, ctype: str, width: int):
    """Downscale raw image bytes to `width`px JPEG (or pass through if Pillow/width absent)."""
    if not width or not _HAVE_PIL:
        return ctype or "application/octet-stream", data
    try:
        from io import BytesIO
        im = _PILImage.open(BytesIO(data))
        if getattr(im, "is_animated", False):
            im.seek(0)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        w, h = im.size
        if w > width:
            im = im.resize((width, max(1, round(h * width / w))), _PILImage.LANCZOS)
        buf = BytesIO()
        im.save(buf, "JPEG", quality=78, optimize=True)
        return "image/jpeg", buf.getvalue()
    except Exception:
        return ctype or "application/octet-stream", data


def _blocked_media_host(host: str) -> bool:
    """SSRF guard: refuse loopback / private / link-local / reserved fetch targets."""
    import ipaddress
    import socket
    host = (host or "").strip().lower()
    if not host or host == "localhost":
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return True
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except Exception:
            return True
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return True
    return False


def fetch_remote_thumb(url: str, width: int):
    """Fetch a remote image → (content_type, bytes), or (None, None) on any failure. Cached."""
    if not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
        return None, None
    from urllib.parse import urlparse
    if _blocked_media_host(urlparse(url).hostname or ""):
        return None, None
    key = (url, width)
    with _media_lock:
        if key in _media_cache:
            return _media_cache[key]
    import urllib.request
    res = (None, None)
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _MEDIA_UA, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
            "Referer": "https://www.google.com/"})
        with urllib.request.urlopen(req, timeout=8) as r:
            ctype = (r.headers.get("Content-Type", "") or "").split(";")[0].strip().lower()
            data = r.read(_MEDIA_MAX_BYTES + 1)
        if len(data) <= _MEDIA_MAX_BYTES and (not ctype or ctype.startswith("image/")):
            res = _thumb_from_bytes(data, ctype or "image/jpeg", width)
    except Exception:
        res = (None, None)
    with _media_lock:
        if len(_media_cache) > _MEDIA_CACHE_CAP:
            _media_cache.clear()
        _media_cache[key] = res
    return res


_crawl_cache: dict = {}          # path -> (mtime, parsed records) — skip re-parsing an unchanged file
_crawl_cache_lock = threading.Lock()


def load_crawl(path: str):
    """Return list of {domain, media:[...], pages:[...]} from a crawl.json (or []). Cached by mtime:
    during a scan the report build + the media streamer both read the (large, growing) crawl every
    poll — re-parsing it twice a second saturates the GIL and makes everything (incl. the chat) lag.
    We parse only when the file actually changes; the returned list is READ-ONLY for callers."""
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return []
    with _crawl_cache_lock:
        hit = _crawl_cache.get(path)
        if hit and hit[0] == mt:
            return hit[1]
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(d, list):
        return []
    out = []
    for r in d:
        if not isinstance(r, dict):
            continue
        out.append({
            "domain": r.get("domain", "?"),
            "media": [m for m in (r.get("media") or []) if isinstance(m, str)],
            "pages": [p for p in (r.get("pages") or []) if isinstance(p, str)],
        })
    with _crawl_cache_lock:
        _crawl_cache[path] = (mt, out)
        if len(_crawl_cache) > 8:
            _crawl_cache.clear()
            _crawl_cache[path] = (mt, out)
    return out


class Hub:
    """Shared, thread-safe stream state. Producer appends; SSE consumers wait on the cond."""

    def __init__(self):
        self.cv = threading.Condition()
        self.seq = 0
        self.total = 0                      # media leaks emitted
        self.pages = 0                      # page leaks emitted
        self.domains: dict[str, int] = {}   # domain -> media count
        self.recent: list[dict] = []        # last N events for late joiners' feed
        self.started = time.time()
        self.mode = "?"
        self.source = ""
        self.status = "starting"
        self.done = False
        self.assets = {"gallery": [], "cse": [], "grids": [], "linkcards": []}
        self.report = {"likely": 0, "possible": 0, "total": 0, "pages": 0, "direct_media": 0,
                       "domains": [], "by_domain": {}, "aliases": []}
        self._seen: set[str] = set()
        self._seen_norm: set[str] = set()   # normalized-URL dedup for the live wall (mirror/param dupes)

    def emit(self, domain: str, url: str, kind: str):
        with self.cv:
            if url in self._seen:
                return
            self._seen.add(url)
            self.seq += 1
            if kind == "page":
                self.pages += 1
            else:
                self.total += 1
                self.domains[domain] = self.domains.get(domain, 0) + 1
            ev = {"seq": self.seq, "t": round(time.time() - self.started, 2),
                  "domain": domain, "url": url, "kind": kind}
            self.recent.append(ev)
            if len(self.recent) > 200:
                self.recent = self.recent[-200:]
            self.cv.notify_all()

    def seed_seen(self, urls):
        """Mark URLs as already-seen WITHOUT emitting — used to baseline a file that already
        has stale content at launch, so watch streams only leaks discovered from now on."""
        with self.cv:
            self._seen.update(urls)
            self._seen_norm.update(_base_image_id(u) for u in urls)

    def set_report(self, rep: dict, feed: list):
        """Publish the full report state (real leak data) and refresh the live link feed. Only
        genuinely-new links flash; the rest are seeded so re-polling doesn't re-flash everything."""
        with self.cv:
            self.report = rep
            self.total = rep["total"]
            self.pages = rep["pages"]
            self.domains = {d["domain"]: d["n"] for d in rep["domains"]}
            for it in feed:
                if it["url"] in self._seen:
                    continue
                self._seen.add(it["url"])
                self.seq += 1
                ev = {"seq": self.seq, "domain": it["domain"], "url": it["url"],
                      "kind": it["kind"], "bucket": it.get("bucket", "")}
                self.recent.append(ev)
            if len(self.recent) > 200:
                self.recent = self.recent[-200:]
            self.cv.notify_all()

    def set_status(self, s: str):
        with self.cv:
            self.status = s
            self.cv.notify_all()

    def finish(self):
        with self.cv:
            self.done = True
            self.status = "complete"
            self.cv.notify_all()

    def snapshot(self, scan=None, prefix="", slug="", include_assets=False):
        with self.cv:
            top = sorted(self.domains.items(), key=lambda kv: -kv[1])
            snap = {
                "seq": self.seq, "total": self.total, "pages": self.pages,
                "domain_count": len(self.domains),
                "elapsed": round(time.time() - self.started, 1),
                "mode": self.mode, "source": self.source, "status": self.status,
                "done": self.done,
                "domains": [{"domain": d, "n": n} for d, n in top[:60]],
                "recent": self.recent[-40:],
                "asset_counts": {k: len(v) for k, v in self.assets.items()},
                "report": {k: self.report.get(k) for k in
                           ("likely", "possible", "total", "pages", "direct_media",
                            "domains", "aliases", "phase", "cse_sites", "top_leaks",
                            "google_total", "handle", "n_hosting", "n_sites", "quote")},
                # capped grouped links so the "grouped by domain" section fills LIVE during a scan
                "by_domain": {d["domain"]: (self.report.get("by_domain", {}).get(d["domain"], [])[:25])
                              for d in self.report.get("domains", [])[:50]},
                "dm": DM,
                "chat_enabled": _HAVE_CHAT,
                "scan_enabled": SCAN_ENABLED,
                "scan": scan.snapshot() if scan else _idle_scan_snapshot(),
                "prefix": prefix,
                "slug": slug,
            }
            if include_assets:
                snap["assets"] = self.assets
                snap["by_domain"] = self.report.get("by_domain", {})
            return snap

    def wait_after(self, seq: int, timeout: float):
        """Block until seq advances past `seq` or `timeout`. Return events after seq."""
        with self.cv:
            if self.seq <= seq and not self.done:
                self.cv.wait(timeout)
            new = [e for e in self.recent if e["seq"] > seq]
            return new, self.seq, self.done


# ── real new scan (reuses pipeline_steps.py — same step FORMAT as public_app) ──
SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{6,24}$")


def _idle_scan_snapshot():
    return {"running": False, "status": "idle", "handle": "", "prefix": "",
            "seq": 0, "rc": None, "cmd": "", "phase": "", "lines": []}


class ScanJob:
    """Runs the REAL pipeline (pipeline_steps.py) in the background and streams its progress lines.
    We reuse the pipeline's `--only` step FORMAT (like the public server) but never reimplement the
    crawler — the evolving deepscan stays authoritative. Runs LIVE in two phases so the browser sees
    Google/CSE images first, then the deep crawl's real leaks streaming in:
        phase 1 — scan,cse,gshots  (presence scan → Google CSE index + thumbnails + synthetic strip)
        phase 2 — seed,crawl,clean,triage,gallery,export  (deep crawl streams media live, then DMCA)
    One ScanJob per session (per shareable slug); the pipeline subprocess itself is serialized across
    sessions by _BIG_SCAN_LOCK (shared slugs_cache.json is not lock-safe)."""

    # Phase 1 runs as TWO concurrent subprocesses so the Google/CSE images print FAST instead of
    # waiting behind the ~375-domain presence scan: the presence scan (+ its leak-index link cards)
    # on one track, the CSE image evidence on the other. build_cse.py reads only --name/--strong
    # (never the scan output) and neither track touches the lock-shared slugs_cache.json, so they
    # are safe to run in parallel within a session. Phase 1 only builds cse.json — gshots does NOT
    # run here: before the crawl exists it can only render CSE tiles (blank when CSE is 429'd), and a
    # phase-1 gshots would also race the mid-scan render (both write {prefix}_images/*.png). Instead
    # the Google-Images grids are rendered MID-SCAN off each crawl wave (_render_gshots_live) and a
    # final authoritative time in phase 2 — both AFTER a crawl exists, so they carry real leak photos.
    SCAN_STEPS = "scan"
    CSE_STEPS = "cse"
    # gshots runs in phase 2 too — AFTER the full crawl + gallery — as the authoritative render. It
    # gets --crawl (and gallery.txt) now, so it enriches the Google-Images grids with real crawled
    # leak photos (and renders them as the SOLE source when CSE 429'd, instead of a blank strip),
    # overwriting the mid-scan grids in {prefix}_images/.
    PHASE2 = "seed,crawl,clean,triage,gallery,gshots,export"

    # Two-wave crawl: the presence scan prints `FOUND <domain>` incrementally (the biggest host is
    # usually found in the first few of 375). Rather than wait for the whole scan, fire a PARTIAL
    # deep crawl on the first wave of found domains CONCURRENTLY with the still-running scan, so real
    # leak media streams into the wall in ~5-10s. The full phase-2 crawl then --resume-merges onto it
    # (carrying those productive domains forward → the live count only ever climbs). Launch the wave
    # once we have WAVE1_MIN domains, or after WAVE1_WAIT s with at least WAVE1_FLOOR — whichever first.
    # Kept small/eager: the biggest hosts (thothd/m.thothd/picazor…) are usually in the first handful
    # of FOUND lines, so a 6-domain wave fires ~20 scan-checks sooner than a 10-domain one with no loss
    # of first-paint content (the full pass crawls the rest anyway).
    WAVE1_MIN = 10
    WAVE1_WAIT = 4.0
    WAVE1_FLOOR = 2

    def __init__(self):
        self.cv = threading.Condition()
        self.running = False
        self.status = "idle"
        self.phase = ""
        self.handle = ""
        self.aliases: list = []     # CLEAN real usernames (handle + user + title-harvested), for report chips
        self.prefix = ""
        self.cmd = ""
        self.events: list = []
        self.seq = 0
        self.rc = None
        self._procs = []            # live subprocesses (phase 1 runs two concurrently)
        self._cancelled = False
        self._gshots_lk = threading.Lock()  # single-flight guard for mid-scan Google-Images renders
        self._gshots_busy = False
        # operator switches from the scan form (both default OFF = everything runs)
        self._no_cse = False            # skip the Google CSE pass (+ the gshots strip it feeds)
        self._no_variations = False     # skip the title-harvest that discovers extra re-upload handles

    def snapshot(self):
        with self.cv:
            return {"running": self.running, "status": self.status, "handle": self.handle,
                    "prefix": self.prefix, "seq": self.seq, "rc": self.rc, "cmd": self.cmd,
                    "phase": self.phase,
                    "lines": [e["line"] for e in self.events[-120:]]}

    def _log(self, line: str):
        with self.cv:
            self.seq += 1
            self.events.append({"seq": self.seq, "line": line})
            if len(self.events) > 800:
                self.events = self.events[-800:]
            self.cv.notify_all()

    def _set(self, **kw):
        with self.cv:
            for k, v in kw.items():
                setattr(self, k, v)
            self.cv.notify_all()

    def wait_after(self, seq: int, timeout: float):
        with self.cv:
            if self.seq <= seq and self.running:
                self.cv.wait(timeout)
            return ([e for e in self.events if e["seq"] > seq], self.seq, self.running)

    def start(self, handle: str, aliases, prefix: str, on_done=None, on_release=None,
              no_cse: bool = False, no_variations: bool = False) -> bool:
        with self.cv:
            if self.running:
                return False
            self._no_cse = bool(no_cse)
            self._no_variations = bool(no_variations)
            self.running = True
            self.status = "starting"
            self.phase = "starting"
            self.handle = handle
            self.prefix = prefix
            _d = os.path.dirname(prefix)                # ensure webscans/ exists before the pipeline writes into it
            if _d:
                os.makedirs(os.path.join(HERE, _d), exist_ok=True)
            self.events = []
            self.seq = 0
            self.rc = None
            self.cmd = ""
            self._cancelled = False
        threading.Thread(target=self._run, args=(handle, aliases, prefix, on_done, on_release),
                         daemon=True).start()
        return True

    def cancel(self):
        import signal
        self._set(_cancelled=True)
        with self.cv:
            procs = [p for p in self._procs if p and p.poll() is None]
        if not procs:
            return
        # the pipeline spawns children (leak_scanner/crawler); kill each whole process group.
        # Phase 1 runs two subprocesses at once, so cancel must reap them all.
        for p in procs:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except Exception:
                try:
                    p.terminate()
                except Exception:
                    pass
        for _ in range(20):                 # give them ~2s to die, then SIGKILL the groups
            if all(p.poll() is not None for p in procs):
                break
            time.sleep(0.1)
        for p in procs:
            if p.poll() is None:
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except Exception:
                    pass
        self._log("■ scan cancelled")

    def _run_pipeline(self, argv, line_cb=None) -> int:
        import subprocess
        proc = subprocess.Popen(argv, cwd=HERE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1,
                                start_new_session=True)   # own group → cancel kills children
        with self.cv:
            self._procs.append(proc)
        try:
            for ln in proc.stdout:
                s = ln.rstrip()
                self._log(s)
                if line_cb:                      # e.g. sniff `FOUND <domain>` to start a partial crawl
                    try:
                        line_cb(s)
                    except Exception:
                        pass
            return proc.wait()
        finally:
            with self.cv:
                if proc in self._procs:
                    self._procs.remove(proc)

    def _render_gshots_live(self, common):
        """Render the Google-Images grids from the GROWING crawl checkpoint MID-SCAN, so the strip
        fills while the deep crawl is still running — not only at the phase-2 finish. Single-flight
        (a render already in flight skips the trigger) and non-blocking (own daemon thread), so it
        never stalls the crawl pump. Safe alongside crawl waves: build_google_shots only READS the
        atomically-written {prefix}.crawl.json + cse.json and writes {prefix}_images/, the same files
        the live report already reads mid-scan. Each render overwrites the last, so the strip keeps
        refreshing as more leaks are crawled; phase-2's final gshots is the authoritative pass."""
        if self._cancelled or self._no_cse:      # no cse.json → the strip has no source; don't spawn
            return
        with self._gshots_lk:
            if self._gshots_busy:
                return
            self._gshots_busy = True

        def _work():
            try:
                self._run_pipeline(common + ["--only", "gshots"])
            except Exception as e:
                self._log(f"  (mid-scan gshots render skipped: {e})")
            finally:
                with self._gshots_lk:
                    self._gshots_busy = False
        threading.Thread(target=_work, daemon=True).start()

    def _run(self, handle, aliases, prefix, on_done, on_release):
        import shlex
        import shutil as _sh
        import tempfile
        slugsan = re.sub(r"[^a-z0-9]", "", handle.lower()) or "client"
        names = list(dict.fromkeys([handle] + [a for a in (aliases or []) if a.strip()]))
        # Title-harvest the REAL re-upload handles the aggregators list side-by-side in their
        # profile <title> ("aliasone / examplelee.xo / qzv1p …") — those (qzv1p, glad.qzvk)
        # are unguessable, so username_variations can never reach them. Seed them BEFORE expansion
        # so the scan chases every alias's leaks, not just the handle the operator typed. Best-effort:
        # a network hiccup here must never block a scan. "No variations" turns this off — the scan
        # then runs on exactly the names the operator typed.
        if self._no_variations:
            self._log("  ↳ name variations OFF — scanning only the handle + aliases you typed "
                      "(no title-harvest of extra re-upload handles)")
        else:
            try:
                from title_aliases import harvest_aliases
                # pass the handle as name too, so a run-together handle also probes its display-name
                # slug forms (janedoee → jane-doe); pass the operator's extra aliases as `seeds`
                # so each of THOSE is probed too (typing 'qzv1p' surfaces aliasone / examplelee.xo).
                # harvest_aliases auto-extends its own budget per seed, so no scaling needed here.
                extra = [a for a in (aliases or []) if a.strip()]
                discovered = harvest_aliases(handle=handle, name=handle, seeds=extra,
                                             rounds=2, max_urls=48, timeout=12)
                fresh = [a for a in discovered if a.lower() not in {n.lower() for n in names}]
                if fresh:
                    names += fresh
                    self._log(f"  ↳ title-harvest: +{len(fresh)} real alias(es) from aggregator titles — "
                              + ", ".join(fresh[:12]) + (" …" if len(fresh) > 12 else ""))
            except Exception as e:
                self._log(f"  ↳ title-harvest skipped ({type(e).__name__}: {e})")
        _wipe_webscan_scratch(prefix)           # start FRESH — never reuse a prior scan's crawl/cache
        # Publish the CLEAN real-username list (handle + user + title-harvested, BEFORE the pipeline's
        # combinatorial expansion) so EVERY report — live, final, or rebuilt from disk — shows all the
        # actual usernames as hero chips, not just the one handle or the examplexo1/_x junk variants.
        self.aliases = list(names)
        _write_real_aliases(prefix, names)
        tmp = tempfile.mkdtemp(prefix="livescan-")
        nf = os.path.join(tmp, "names.txt")
        with open(nf, "w", encoding="utf-8") as fh:
            fh.write("\n".join(names) + "\n")
        common = [sys.executable, PIPELINE, "--name", handle, "--brand", handle, "--slug", slugsan,
                  "--prefix", prefix, "--aliases-file", nf, "--strong", ",".join(names[:3]),
                  # cse mode = always render the Google-Images evidence from CSE data (no Incogniton
                  # browser dependency), so the "Google & search evidence" grid reliably generates
                  "--google-shots", "cse", "--no-live-chat"]
        # Phase 1 fans out into two concurrent tracks (presence scan + link cards ‖ CSE images);
        # phase 2 is the deep crawl. Show all three commands so the operator can reproduce the run.
        p1_scan = common + ["--only", self.SCAN_STEPS]
        p1_cse = common + ["--only", self.CSE_STEPS]
        # No CSE → drop the Google-strip step too: build_google_shots reads {prefix}.cse.json, which
        # this run never writes. (The pipeline would skip it anyway; leaving it out keeps --only honest.)
        p2_steps = (",".join(s for s in self.PHASE2.split(",") if s != "gshots")
                    if self._no_cse else self.PHASE2)
        # --resume-crawl: the full deep crawl MERGES onto the partial pass's checkpoint (below) so the
        # live count never dips. Harmless no-op if the partial never fired (scan too fast / too few hits).
        phase2 = common + ["--only", p2_steps, "--resume-crawl"]
        cmds = [p1_scan] + ([] if self._no_cse else [p1_cse]) + [phase2]
        self._set(cmd="\n".join(shlex.join(c) for c in cmds))
        off = [n for n, on in (("CSE", self._no_cse), ("variations", self._no_variations)) if on]
        self._log(f"▶ live deep scan for @{handle}  ({len(names)} alias(es)) — prefix {prefix}"
                  + (f"  ·  off: {', '.join(off)}" if off else ""))
        self._log("  full command (copy to reproduce this exact run):")
        for c in cmds:
            self._log("    " + shlex.join(c))
        try:
            # serialize the ACTUAL pipeline subprocess across sessions — shared slugs_cache.json is
            # not lock-safe. A second scan keeps its slot and just waits its turn ("queued").
            if not _BIG_SCAN_LOCK.acquire(blocking=False):
                self._set(phase="queued", status="queued — another scan is running; you'll pick up shortly…")
                self._log("… queued — another deep scan is crawling; waiting for it to finish …")
                _BIG_SCAN_LOCK.acquire()
            rc1 = rc2 = None
            # ROLLING crawl pump: sniff `FOUND <domain>` off the presence scan and keep firing PARTIAL
            # deep-crawl waves on the newly-found domains CONCURRENTLY with the still-running scan — so
            # real leak media streams onto the wall THROUGHOUT the scan instead of only after the whole
            # 375-domain scan finishes. Waves SERIALIZE (one crawl subprocess at a time, driven by the
            # pump thread) so they never race on {prefix}.crawl.json / the slug cache; each wave after the
            # first --resume-merges onto the prior checkpoint, so the live count only ever climbs. The
            # scan writes neither the checkpoint nor the slug cache, so scan ‖ crawl is safe. The phase-2
            # deep pass then --resume-merges a full-depth crawl over everything for authoritative depth.
            found, found_set = [], set()
            found_lock = threading.Lock()
            crawled_set = set()                          # domains already dispatched to a wave
            scan_running = {"on": True}                  # flipped off when the presence scan returns
            pump = {"thread": None, "waves": 0, "t0": time.monotonic()}
            FOUND_RE = re.compile(r"\bFOUND\s+([a-z0-9][a-z0-9.\-]*\.[a-z]{2,})", re.I)

            def _on_scan_line(s):
                m = FOUND_RE.search(s)
                if m:
                    d = m.group(1).lower()
                    with found_lock:
                        if d not in found_set:
                            found_set.add(d)
                            found.append(d)

            def _crawl_pump():
                # Waves fire back-to-back: each call blocks on the crawl subprocess, so new FOUND domains
                # accumulate while a wave runs and the next wave picks up whatever landed — natural
                # batching that self-regulates (slower crawl → bigger batches → fewer subprocess spawns).
                first = True
                while not self._cancelled:
                    with found_lock:
                        batch = [d for d in found if d not in crawled_set]
                    if first:
                        # first wave: same eager trigger as the old single wave (WAVE1_MIN found, or
                        # WAVE1_WAIT elapsed with at least WAVE1_FLOOR) so first paint is just as fast.
                        ready = len(batch) >= self.WAVE1_MIN or (
                            (time.monotonic() - pump["t0"]) >= self.WAVE1_WAIT and len(batch) >= self.WAVE1_FLOOR)
                        if not ready:
                            if not scan_running["on"]:
                                if not batch:
                                    break
                            else:
                                time.sleep(0.5)
                                continue
                    elif not batch:
                        if not scan_running["on"]:
                            break                        # scan done + nothing left → hand off to phase 2
                        time.sleep(0.5)
                        continue
                    with found_lock:
                        batch = [d for d in found if d not in crawled_set]
                        crawled_set.update(batch)
                    if not batch:
                        continue
                    # --partial-crawl = ultra-shallow FAST PREVIEW (first grid page only); --resume-crawl
                    # (every wave after the first) MERGES onto the prior waves' checkpoint so nothing is
                    # lost and the count only climbs.
                    argvp = (common + ["--only", "crawl", "--domains", ",".join(batch), "--partial-crawl"]
                             + ([] if first else ["--resume-crawl"]))
                    self._log(f"── live crawl wave {pump['waves'] + 1} · {len(batch)} new domain(s) "
                              f"({len(crawled_set)} crawled so far) → leaks stream while the scan runs ──")
                    self._run_pipeline(argvp)            # blocks until this wave's crawl finishes
                    pump["waves"] += 1
                    first = False
                    # the wave just wrote a fresh {prefix}.crawl.json checkpoint — refresh the
                    # Google-Images strip from it NOW so the grids fill mid-scan (single-flight, so
                    # back-to-back waves don't pile up renders; each render overwrites the last).
                    self._render_gshots_live(common)

            try:
                if not self._cancelled:
                    cse_rc = {}
                    t_cse = None
                    if self._no_cse:
                        self._set(phase="scan", status="phase 1/2 · presence scan (CSE off)")
                        self._log("── PHASE 1/2 · presence scan ‖ rolling crawl — Google/CSE evidence OFF ──")
                    else:
                        self._set(phase="cse", status="phase 1/2 · Google & CSE evidence (concurrent)")
                        self._log("── PHASE 1/2 · Google + CSE evidence ‖ presence scan ‖ rolling crawl (concurrent) ──")
                        # run the CSE image evidence CONCURRENTLY with the presence scan so the Google
                        # images render in seconds instead of after the whole 375-domain scan.
                        t_cse = threading.Thread(target=lambda: cse_rc.__setitem__("rc", self._run_pipeline(p1_cse)),
                                                 daemon=True)
                        t_cse.start()
                    # rolling crawl pump: fires partial-crawl waves on found domains AS the scan discovers
                    # them, so leaks stream throughout — not after 375/375.
                    pump["thread"] = threading.Thread(target=_crawl_pump, daemon=True)
                    pump["thread"].start()
                    # streams the presence scan + link cards; _on_scan_line feeds the pump's found-domain set
                    rc_scan = self._run_pipeline(p1_scan, line_cb=_on_scan_line)
                    scan_running["on"] = False           # let the pump drain its last waves and exit
                    if t_cse:
                        t_cse.join()
                    rc1 = rc_scan if rc_scan else cse_rc.get("rc", 0)   # scan is the core step
                    # the last wave must FINISH before the full pass starts — both write the same
                    # {prefix}.crawl.json / slug cache, so overlapping them would race. Bounded by the
                    # crawler's shallow partial budget; the wall stays full while we wait.
                    if pump["thread"]:
                        self._log("  … finishing the last live crawl wave before the full deep pass (no data lost) …")
                        pump["thread"].join()
                if not self._cancelled:
                    self._set(phase="crawl", status="phase 2/2 · deep crawl (live)")
                    self._log("── PHASE 2/2 · deep crawl — full depth over every domain, real media streams in live, deduped ──")
                    # let any in-flight mid-scan Google-Images render finish before phase-2 gshots
                    # re-renders the same {prefix}_images/*.png (avoid two build_google_shots racing)
                    for _ in range(120):
                        with self._gshots_lk:
                            if not self._gshots_busy:
                                break
                        time.sleep(0.5)
                    rc2 = self._run_pipeline(phase2)
            finally:
                _BIG_SCAN_LOCK.release()
            rc = 1 if self._cancelled else (rc2 if rc2 is not None else (rc1 if rc1 is not None else 1))
            with self.cv:
                self.rc = rc
                self.status = "complete ✓" if rc == 0 else ("cancelled" if self._cancelled
                                                             else f"finished (rc={rc})")
            self._log(f"■ scan finished rc={rc}")
            if rc == 0 and on_done:
                try:
                    on_done(prefix)
                    self._log(f"→ report ready for @{self.handle} ({prefix})")
                except Exception as e:
                    self._log(f"  (report finalize failed: {e})")
        except Exception as e:
            with self.cv:
                self.rc = 1
                self.status = f"error: {e}"
            self._log(f"✗ scan error: {e}")
        finally:
            with self.cv:
                self.running = False
                self.phase = "done"
                self.cv.notify_all()
            _sh.rmtree(tmp, ignore_errors=True)
            if on_release:
                try:
                    on_release()
                except Exception:
                    pass


# ── multi-tenant sessions (one live report + scan per shareable /s/<slug>) ─────
# Every visitor who starts a scan gets an unguessable slug; the report, the growing crawl, the
# streamed images and the scan console are all keyed by it — so many people run and watch their OWN
# scans at once and share a /s/<slug> link. Mirrors public_app.py (JOBS registry + token_urlsafe
# slug + a unique, injective webscan_ scratch prefix per scan so cleanups never cross-delete).
MAX_LIVE_SCANS = int(os.environ.get("MAX_LIVE_SCANS", "4"))     # concurrent scans admitted
SESSION_TTL = float(os.environ.get("SESSION_TTL", "21600"))    # 6h idle → GC (relaunchable from disk)
_SCAN_SLOTS = threading.BoundedSemaphore(MAX_LIVE_SCANS)
_BIG_SCAN_LOCK = threading.Lock()
SESS_DIR = os.path.join(HERE, ".live_sessions")                # tiny per-slug sidecars survive restart


# All webscan_ scratch artifacts live UNDER this subdir (kept out of the repo root). The prefix carries
# the folder ("webscans/webscan_<sha>") so every pipeline path (<prefix>.crawl.json, <prefix>_images/…)
# lands inside it automatically; os.path.basename(prefix) stays "webscan_<sha>" so the campaigns/exports
# and startswith("webscan_") guards are unaffected.
WEBSCAN_DIR = os.environ.get("WEBSCAN_DIR", "webscans")


def _prefix_for_slug(slug: str) -> str:
    """Injective scratch prefix — matches ^webscan_[a-z0-9]+$ so two concurrent scans never collide
    on disk (and one's cleanup can't delete another's files, incl. on case-insensitive volumes).
    Namespaced under WEBSCAN_DIR/ so scans don't litter the repo root."""
    os.makedirs(os.path.join(HERE, WEBSCAN_DIR), exist_ok=True)
    return os.path.join(WEBSCAN_DIR, "webscan_" + hashlib.sha1(slug.encode("utf-8")).hexdigest()[:16])


class LiveSession:
    """One shareable live report: its own Hub (stream state), ScanJob (subprocess), scratch prefix
    and producer thread, keyed by an unguessable slug → /s/<slug>."""

    def __init__(self, slug, handle="", aliases=None, prefix="", readonly=False):
        self.slug = slug
        self.handle = handle
        self.aliases = aliases or []
        self.prefix = prefix or (_prefix_for_slug(slug) if slug else "")
        self.assets_dir = _assets_dir_for(self.prefix) if self.prefix else HERE
        self.hub = Hub()
        self.scan = ScanJob()
        self.readonly = readonly            # lazily rebuilt from disk (a done link) — no live scan
        self.auto = True                    # False on LANDING under legacy --mode replay/watch/auto
        self.created = time.time()
        self.viewers = 0
        self._producer = None
        self._prod_lock = threading.Lock()

    def snapshot(self, include_assets=False):
        return self.hub.snapshot(scan=self.scan, prefix=self.prefix, slug=self.slug,
                                 include_assets=include_assets)

    def ensure_producer(self):
        if not self.auto:                   # a legacy replay/watch producer owns this hub instead
            return
        with self._prod_lock:
            if self._producer and self._producer.is_alive():
                return
            self._producer = threading.Thread(target=producer_session, args=(self,), daemon=True)
            self._producer.start()


SESSIONS: dict = {}
SESSIONS_LOCK = threading.Lock()


def _persist_session(sess):
    try:
        os.makedirs(SESS_DIR, exist_ok=True)
        with open(os.path.join(SESS_DIR, sess.slug + ".json"), "w", encoding="utf-8") as fh:
            json.dump({"slug": sess.slug, "handle": sess.handle, "aliases": sess.aliases,
                       "prefix": sess.prefix, "created": sess.created}, fh)
    except Exception:
        pass


def _load_session_sidecar(slug):
    try:
        return json.load(open(os.path.join(SESS_DIR, slug + ".json"), encoding="utf-8"))
    except Exception:
        return None


def _slug_known(slug: str) -> bool:
    """True if this slug is a real report — a live in-memory session OR a persisted sidecar."""
    if not slug or not SLUG_RE.match(slug):
        return False
    with SESSIONS_LOCK:
        if slug in SESSIONS:
            return True
    return _load_session_sidecar(slug) is not None


def _recover_slug(path: str):
    """Best-effort recovery of a MISREAD /s/<slug> link. The thin second slash gets read as
    l / 1 / I / | or dropped entirely, so '.../s/zAbc…' arrives as '.../slzAbc…' or '.../szAbc…'.
    Returns a KNOWN slug to redirect to, or None — it only ever returns a slug that already
    exists, so a stray /s… path can never be mis-routed onto a stranger's report."""
    if not path.startswith("/s"):
        return None
    tail = path[2:].lstrip("/")                       # text after '/s', minus the slash if it survived
    cands = [tail]
    if tail and tail[0] in "lI1|/":                   # a slash misread as one of these, glued to the slug
        cands.append(tail[1:])
    for c in cands:
        if _slug_known(c):
            return c
    return None


def _sessions_list() -> list:
    """Every scan this server knows about — the live (in-memory) ones AND the on-disk sidecars that
    survive a restart — tagged running / queued / done, for the public 'Live scans on this server'
    panel. In-memory state wins (authoritative for the live scans); disk-only slugs are history."""
    items = {}
    for fn in _glob.glob(os.path.join(SESS_DIR, "*.json")):
        try:
            d = json.load(open(fn, encoding="utf-8"))
        except Exception:
            continue
        slug = d.get("slug") or os.path.splitext(os.path.basename(fn))[0]
        items[slug] = {"slug": slug, "handle": clean_handle(d.get("handle")) or "?",
                       "prefix": os.path.basename(d.get("prefix") or ""),
                       "created": d.get("created") or 0.0,
                       "state": "done", "status": "", "total": None, "viewers": 0}
    with SESSIONS_LOCK:
        for slug, sess in list(SESSIONS.items()):
            sc = sess.scan
            running = bool(sc and sc.running)
            phase = (getattr(sc, "phase", "") or "")
            state = "queued" if (running and phase == "queued") else ("running" if running else "done")
            items[slug] = {"slug": slug, "handle": clean_handle(sess.handle) or "?",
                           "prefix": os.path.basename(sess.prefix or ""),
                           "created": getattr(sess, "created", 0.0),
                           "state": state,
                           "status": (getattr(sc, "status", "") or "")[:140],
                           "total": getattr(sess.hub, "total", None),
                           "viewers": getattr(sess, "viewers", 0)}
    rank = {"running": 0, "queued": 1, "done": 2}
    out = sorted(items.values(), key=lambda x: (rank.get(x["state"], 3), -(x["created"] or 0)))
    return out


def _delete_session(slug: str):
    """Forget a scan: cancel it if running, drop it from memory, delete its sidecar, and wipe the
    webscan_ scratch (crawl/cse/export/images). GUARDED to the webscan_ namespace so it can never
    touch a real campaign. Returns (ok, error)."""
    if not slug or not SLUG_RE.match(slug):
        return False, "bad slug"
    prefix = ""
    with SESSIONS_LOCK:
        sess = SESSIONS.get(slug)
    if sess is not None:
        prefix = sess.prefix or ""
        try:
            if sess.scan and sess.scan.running:
                sess.scan.cancel()
        except Exception:
            pass
        with SESSIONS_LOCK:
            SESSIONS.pop(slug, None)
    if not prefix:
        prefix = (_load_session_sidecar(slug) or {}).get("prefix") or ""
    try:
        os.remove(os.path.join(SESS_DIR, slug + ".json"))
    except FileNotFoundError:
        pass
    except Exception as e:
        return False, str(e)
    if prefix and os.path.basename(prefix).startswith("webscan_"):
        _wipe_webscan_scratch(prefix)
    return True, ""


def _has_artifacts(prefix) -> bool:
    return bool(_newest_crawl(prefix)
                or os.path.exists(os.path.join(HERE, f"{prefix}.cse.json"))
                or os.path.exists(os.path.join(HERE, "exports", f"{prefix}_latest", "metadata.jsonl")))


def session_gc():
    """Evict finished, unwatched sessions older than the TTL (they relaunch from disk on demand).
    Caller may or may not hold SESSIONS_LOCK — we snapshot under the lock either way is fine here
    because we only ever call it while holding it."""
    now = time.time()
    drop = [s for s, sess in SESSIONS.items()
            if not sess.scan.running and sess.viewers <= 0 and now - sess.created > SESSION_TTL]
    for s in drop:
        del SESSIONS[s]


def session_get(slug, create_readonly=True):
    """In-memory session for a slug, or lazily rebuild a read-only (done) one from the on-disk
    artifacts + sidecar so a /s/<slug> link keeps working after a restart / GC. None if unknown."""
    if not slug or not SLUG_RE.match(slug):
        return None
    with SESSIONS_LOCK:
        sess = SESSIONS.get(slug)
    if sess or not create_readonly:
        return sess
    side = _load_session_sidecar(slug)
    prefix = (side or {}).get("prefix") or _prefix_for_slug(slug)
    if not _has_artifacts(prefix):
        return None                                     # unknown link — nothing on disk for it
    sess = LiveSession(slug, handle=(side or {}).get("handle", ""),
                       aliases=(side or {}).get("aliases", []), prefix=prefix, readonly=True)
    # Seed the rebuilt scan so the report shows username chips even after a restart: prefer the
    # persisted clean real-username list, else the sidecar aliases, else the handle. Without this the
    # fresh ScanJob has an empty handle → build_report_live's chip source is empty → zero chips.
    sess.scan.handle = sess.handle
    sess.scan.aliases = (_real_aliases_for(prefix) or list(sess.aliases)
                         or ([sess.handle] if sess.handle else []))
    with SESSIONS_LOCK:
        SESSIONS.setdefault(slug, sess)
        sess = SESSIONS[slug]
    sess.ensure_producer()
    return sess


_URLISH = re.compile(r"^(?:https?://|www\.)|^[\w.-]+\.[a-z]{2,}/", re.I)


def clean_handle(s: str) -> str:
    """'@https://onlyfans.com/creatorw' / 'instagram.com/creator.w/reels' → the bare
    username ('creatorw' / 'creator.w'). Anything URL-ish collapses to the FIRST path
    segment (that's the username on OF/IG/X/TikTok); a plain handle passes through untouched, so
    'jane.doe' stays 'jane.doe'. The URL itself is dropped — it's not a usable name variant."""
    s = (s or "").strip().lstrip("@").strip()
    if _URLISH.match(s):
        parts = [p for p in re.sub(r"[?#].*$", "", s).split("//")[-1].split("/") if p]
        s = parts[1] if len(parts) > 1 else (parts[0] if parts else "")
    return s.lstrip("@").strip()


def session_start(handle, aliases, no_cse=False, no_variations=False):
    """Mint a new slug, create its session, wipe + start the two-phase live scan and its producer.
    Returns (slug, error). error='busy' → the global concurrency cap (MAX_LIVE_SCANS) is hit.
    no_cse / no_variations are the scan form's opt-out switches (see ScanJob.start)."""
    if not _SCAN_SLOTS.acquire(blocking=False):
        return None, "busy"
    started = False                          # once True, the scan OWNS the slot (releases in _run)
    try:
        slug = secrets.token_urlsafe(9)
        while not SLUG_RE.match(slug) or slug in SESSIONS:
            slug = secrets.token_urlsafe(9)
        sess = LiveSession(slug, handle=handle, aliases=aliases)
        with SESSIONS_LOCK:
            session_gc()
            SESSIONS[slug] = sess
        _persist_session(sess)
        started = sess.scan.start(handle, aliases, sess.prefix,
                                  on_done=lambda pfx: _finalize_session(sess),
                                  on_release=_SCAN_SLOTS.release,
                                  no_cse=no_cse, no_variations=no_variations)
        if not started:
            return None, "already running"
        try:
            sess.ensure_producer()           # producer failure must NOT drop the scan-owned slot
        except Exception:
            pass
        return slug, ""
    finally:
        if not started:                      # scan never took the slot → release exactly once here
            _SCAN_SLOTS.release()


def _finalize_session(sess):
    """Clean finish — rebuild the visual catalog from the scan's own artifacts."""
    try:
        sess.assets_dir = _assets_dir_for(sess.prefix)
        sess.hub.assets = build_catalog(sess.assets_dir, sess.prefix)
    except Exception:
        pass


LANDING = LiveSession("", handle="")            # shared idle 0-state for the bare landing page


# ── producers ────────────────────────────────────────────────────────────────
def interleave(records):
    """Round-robin media across domains so the whole grid grows together, not one bar at a time."""
    lanes = []
    for r in records:
        seq = [(r["domain"], u, kind_of(u)) for u in r["media"]]
        seq += [(r["domain"], u, "page") for u in r["pages"]]
        if seq:
            lanes.append(seq)
    i = 0
    while lanes:
        lane = lanes[i % len(lanes)]
        yield lane.pop(0)
        if not lane:
            lanes.remove(lane)
        else:
            i += 1


def producer_replay(hub: Hub, path: str, rate: float):
    records = load_crawl(path)
    total = sum(len(r["media"]) + len(r["pages"]) for r in records)
    hub.mode = "replay"
    hub.source = os.path.basename(path)
    hub.set_status(f"replaying {total} leaks @ ~{int(rate)}/s")
    delay = 1.0 / max(1.0, rate)
    for domain, url, kind in interleave(records):
        hub.emit(domain, url, kind)
        # small jitter + occasional burst so the stream looks alive, not metronomic
        time.sleep(delay * random.uniform(0.3, 1.6))
    hub.finish()


def _feed_sample(rep: dict, cap: int = 240):
    """Round-robin links across domains so the live feed shows a spread, not one domain's dump."""
    lanes = [list(rep["by_domain"].get(d["domain"], [])) for d in rep["domains"]]
    lanes = [[dict(x, domain=d["domain"]) for x in lane]
             for d, lane in zip(rep["domains"], lanes) if lane]
    out, i = [], 0
    while lanes and len(out) < cap:
        lane = lanes[i % len(lanes)]
        out.append(lane.pop(0))
        if not lane:
            lanes.remove(lane)
        else:
            i += 1
    return out


import glob as _glob


def _wipe_webscan_scratch(prefix: str):
    """Delete every artifact a prior scan left for this webscan_<slug> scratch prefix (crawl
    checkpoints, slug cache, cse/gallery, DMCA export) so a NEW scan starts genuinely from scratch —
    the crawler re-discovers everything live, never resurfacing stale/cached data. GUARDED to the
    webscan_ namespace so it can never touch a real campaign."""
    base = os.path.basename(prefix)
    if not base.startswith("webscan_"):
        return
    scan_root = os.path.join(HERE, os.path.dirname(prefix))   # webscans/ (or repo root for legacy prefixes)
    targets = []
    for pat in (f"{base}.*", f"{base}-*", f"{base}_*"):
        targets += _glob.glob(os.path.join(scan_root, pat))
    targets += [os.path.join(HERE, "campaigns", base),           # campaign dir is basename-keyed
                os.path.join(HERE, "exports", f"{prefix}_latest")]  # export_dmca keys the dir on the FULL --slug (=prefix)
    for p in targets:
        try:
            if os.path.islink(p) or os.path.isfile(p):
                os.remove(p)
            elif os.path.isdir(p):
                import shutil
                shutil.rmtree(p, ignore_errors=True)
        except Exception:
            pass


def _slug_tokens(s: str) -> str:
    """URL/filename → its alnum-lowercased slug, so 'jane%20doee' and 'janedoee-full-nude.jpg'
    both reduce to a form that contains the handle token 'janedoee'."""
    from urllib.parse import unquote
    return re.sub(r"[^a-z0-9]", "", unquote(s or "").lower())


def _handle_tokens(prefix: str) -> set:
    """The creator's handle + aliases as alnum slugs (≥4 chars) — the KEEP signal the wall filters on."""
    return {t for t in (_slug_tokens(a) for a in _aliases_for(prefix)) if len(t) >= 4}


# The wall applies the SAME real-leak filter clean_crawl applies after the crawl, so it streams only
# leaks that survive (no RTA/ASACP badges, site chrome, or other-creator catch-all domains). Reusing
# clean_crawl's own predicates keeps a single source of truth. Guarded so a missing module never
# breaks the live site (falls back to a light theme/handle filter).
try:
    import clean_crawl as _CLEAN
    from netloc import registrable_domain as _regdom
    _HAVE_CLEAN = True
except Exception:
    _HAVE_CLEAN = False

# Locale-mirror expansion for the downloadable / emailed link set. Reuse the curated, live-verified
# host map in export_dmca (single source of truth) so the stream's exported links match the report's:
# every confirmed PAGE url also yields its per-locale mirrors (leakgallery.com/it/…, es.fapeza.com/…),
# each a separately-indexed page and thus a separate takedown URL. No-op for any host not in the map
# (incl. cdn/media subdomains). Guarded so a missing module never breaks the live site.
try:
    from export_dmca import locale_variants as _locale_variants
except Exception:
    def _locale_variants(_u):
        return []

# Chrome / icon / thumbnail junk that even clean_crawl keeps (it only names a few theme files), but is
# obviously NOT a leaked photo: favicons, app icons, flag icons, sprites, og-images, and tiny NNpx
# preview thumbnails (e.g. picazor's `35px_…`, `tpd-b-24px.png`). Matched on the media URL.
_JUNK_MEDIA_RE = re.compile(
    r"(android-chrome|apple-touch|mstile|safari-pinned|favicon|/icons?/|/flags?/|"
    r"\b\d{1,3}px[-_.]|opengraph|og[-_]image|/placeholder|/sprite|[-_/]logo[-_.]|[-_/]banner[-_.]|"
    r"/ads?/|1x1\.|/pixel|/blank|/spacer)", re.I)
_FLAG_ICON_RE = re.compile(r"^[a-z]{2}\.(png|gif|svg|webp)$", re.I)

# Domains blocked from the WALL only (the report/export still counts them): SEO-spam tubes that mint
# filenames from the SEARCH TERM but serve generic content (redwap), and reverse-image / face-search
# engines that return LOOK-ALIKE other creators (picazor) — neither is a real leak host for HER, and no
# URL heuristic can tell. Extend via fake_aggregators.txt (one registrable domain / line).
_WALL_BLOCK_BUILTIN = {"redwap-xxx.com", "redwap.me", "redwap.sex", "redwap.porn", "redwap.xxx",
                       "redwap.tv", "redwap.pics", "picazor.com", "fapfolder.club"}


def _load_wall_block() -> set:
    doms = set(_WALL_BLOCK_BUILTIN)
    p = os.path.join(HERE, "fake_aggregators.txt")
    try:
        for ln in open(p, encoding="utf-8"):
            ln = ln.split("#", 1)[0].strip().lower()
            if ln:
                doms.add(ln)
    except OSError:
        pass
    return doms


_WALL_BLOCK = _load_wall_block()


def _is_junk_media(u: str) -> bool:
    fn = u.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1].lower()
    return bool(_FLAG_ICON_RE.match(fn) or _JUNK_MEDIA_RE.search(u))


_SIZE_SUFFIX_RE = re.compile(r"-\d{2,4}x\d{2,4}(\.[a-z0-9]+)$", re.I)


def _base_image_id(u: str) -> str:
    """The image's identity IGNORING WordPress/responsive size variants — 'Pics-235-100x100.png',
    '…-150x150.png', '…-603x600.png' all reduce to the same id, so the same leaked photo served in
    4 thumbnail sizes counts (and shows) ONCE. Normalized (no scheme/query/host-case)."""
    s = _norm_media(u)
    return _SIZE_SUFFIX_RE.sub(r"\1", s)


def _dedup_size_variants(urls: list) -> list:
    """Collapse size variants of the same image, keeping the LARGEST (so the wall shows the full
    photo, not the 100x100 thumbnail). Order-stable on first appearance of each base id."""
    def area(u):
        m = _SIZE_SUFFIX_RE.search(u.split("?", 1)[0])
        if not m:
            return 1 << 30                                   # no size suffix = assume full-size
        w, h = re.findall(r"\d{2,4}", m.group(0))[:2]
        return int(w) * int(h)
    best, order = {}, []
    for u in urls:
        b = _base_image_id(u)
        if b not in best:
            order.append(b)
        if b not in best or area(u) > area(best[b]):
            best[b] = u
    return [best[b] for b in order]


def _wall_keep_media(r: dict, tokens: set) -> list:
    """The subset of a crawl record's media that is a REAL leak worth flashing on the wall. Layers:
      1. block-list SEO-spam tubes outright (redwap-style filename-lies);
      2. drop clean_crawl trap/aggregator/theme URLs + chrome/icon/tiny-thumbnail junk (favicons,
         app icons, `35px_…` previews) — even on hashed hosts, so picazor's icon dump is gone;
      3. catch-all: drop the whole domain if ≥25 media but <15% carry the handle (unless a known
         hashed-CDN re-upload host). This is what removes the 'crappy images' the raw crawl surfaces."""
    dom = (r.get("domain") or "").lower()
    media = r.get("media") or []
    if not _HAVE_CLEAN:
        return [u for u in media if not _is_junk_media(u)]
    try:
        reg = _regdom("http://" + dom) or dom
    except Exception:
        reg = dom
    if dom in _WALL_BLOCK or reg in _WALL_BLOCK:
        return []
    media = [u for u in media if not _CLEAN.bad(u) and not _is_junk_media(u)]
    if not media:
        return []
    # catch-all: a domain serving mostly non-handle media is an other-creator / junk aggregator. The
    # wall uses a LOWER min-count than the offline clean pass (12 vs 25) so junk domains are caught
    # while they're still small and don't flood the wall before the real leaks arrive. Real leak
    # domains carry the handle well above 15%, so they survive; hashed-CDN re-upload hosts are exempt.
    if dom not in _CLEAN.HASHED_HOSTS and reg not in _CLEAN.HASHED_HOSTS and len(media) >= 12:
        hits = [u for u in media if _CLEAN.carries_handle(u, tokens)]
        if len(hits) / len(media) < 0.15:                          # catch-all: other-creator / junk domain
            return []
    return _dedup_size_variants(media)                             # 4 thumbnail sizes of one leak → 1 (largest)


def _stream_new_media(hub: Hub, prefix: str, cap: int = 90, per_domain: int = 4):
    """Emit newly-discovered crawl media to the live wall/feed so real leak images appear the moment
    the crawler finds them. Real-time de-dup so the wall shows ONLY leaks that survive:
      (1) junk/block filter (_wall_keep_media) drops chrome/icons + SEO-spam + other-creator domains;
      (2) content de-dup on the BASE image id — collapses http/https, query-param, mirror, AND
          WordPress size variants (100x100/150x150/…603x600 of one photo → one), keeping the largest;
      (3) round-robin across domains with a per-emit per-domain cap, so no single domain floods the
          20-tile wall (the redwap/picazor dump problem)."""
    cp = _newest_crawl(prefix)
    if not cp:
        return
    tokens = _handle_tokens(prefix)
    lanes = []
    for r in load_crawl(cp):
        keep = _wall_keep_media(r, tokens)              # clean-parity: real leaks only, junk domains out
        if not keep:
            continue
        q = []
        for u in keep:
            nk = _base_image_id(u)
            if nk and nk not in hub._seen_norm and u not in hub._seen:
                q.append(u)
        if q:
            lanes.append([r["domain"], q, 0])           # [domain, queue, emitted-this-call]
    n = i = 0
    while lanes and n < cap:
        lane = lanes[i % len(lanes)]
        dom, q = lane[0], lane[1]
        u = q.pop(0)
        nk = _base_image_id(u)
        if nk and nk not in hub._seen_norm and u not in hub._seen:
            hub._seen_norm.add(nk)
            hub.emit(dom, u, kind_of(u))
            n += 1
            lane[2] += 1
        # drop the lane when its queue is empty OR it has hit the per-domain cap for this call
        if not q or lane[2] >= per_domain:
            lanes.pop(i % len(lanes))
        else:
            i += 1


def producer_session(sess, poll: float = 1.5):
    """Per-session live report loop: reads THIS session's growing crawl checkpoint + artifacts and
    keeps its Hub current — counts climb, real leak images stream to the wall (deduped) the instant
    the crawler finds them, and the visual catalog (screenshots + Google/CSE) fills in as the
    pipeline produces it. Bound to ONE slug, so many sessions run independently. Exits once the scan
    is done AND nobody is watching (frees the thread for GC; a later /s/<slug> visit relaunches it
    from disk via session_get → ensure_producer)."""
    hub, prefix = sess.hub, sess.prefix
    hub.mode = "report"
    last_asset_sig = None
    idle_rounds = 0
    while True:
        scan = sess.scan
        rep = build_report_live(sess.assets_dir, prefix, scan)
        hub.source = (f"live crawl · {prefix}" if prefix else "(no scan yet)")
        hub.set_report(rep, _feed_sample(rep))
        # stream freshly-found leak media to the wall the instant the crawler finds it — only while
        # THIS session's scan is actively crawling (phase 2). Images in, oldest rotate out.
        if prefix and scan.running and rep.get("phase") == "scanning":
            _stream_new_media(hub, prefix, cap=200)
        # keep the visual catalog fresh (screenshots + Google/CSE evidence) as steps produce it —
        # for the scan's OWN prefix only. Signature guard avoids re-publishing an unchanged catalog.
        if prefix:
            try:
                cat = build_catalog(sess.assets_dir, prefix)
                sig = (len(cat["gallery"]), len(cat["cse"]), len(cat["grids"]),
                       len(cat["linkcards"]), len(cat["gimages"]))
                if sig != last_asset_sig:
                    hub.assets = cat
                    last_asset_sig = sig
            except Exception:
                pass
        snap = scan.snapshot()
        if snap["running"]:
            hub.set_status(f"scanning @{snap['handle']} — {snap['status']} · "
                           f"{rep['total']:,} links / {len(rep['domains'])} sites so far")
        elif rep["total"]:
            hub.set_status(f"{rep['likely']:,} likely · {rep['possible']:,} possible · "
                           f"{len(rep['domains'])} sites · {rep['direct_media']:,} direct media")
        else:
            hub.set_status("no scan yet — start a deep scan to begin")
        active = snap["running"] or sess.viewers > 0
        idle_rounds = 0 if active else idle_rounds + 1
        if idle_rounds >= 2:                 # done + unwatched → settle and stop (relaunchable)
            return
        time.sleep(poll if active else min(poll * 2, 5.0))


def producer_watch(hub: Hub, paths, poll: float, replay_fallback: str, rate: float,
                   demo_fallback: bool, catch_up: bool = False):
    """Poll one or more growing crawl checkpoints forever and emit each poll's NEW leaks.

    Stays patient: if started BEFORE the scan, it waits (status shows 'waiting') and picks the
    stream up the moment the scan writes its first checkpoint. Only if --demo-fallback is set and
    nothing appears in ~20s does it replay the bundled crawl instead (to prove the plumbing).

    By default, content that ALREADY exists in a watched file at launch is baselined (counted as
    seen, not streamed), so pointing at a stale checkpoint doesn't dump thousands of old leaks —
    only leaks discovered from now on grow the site. Pass catch_up=True to stream the backlog too."""
    if isinstance(paths, str):
        paths = [paths]
    hub.mode = "watch"
    hub.source = " | ".join(dict.fromkeys(paths))   # distinct rel-paths (root vs campaigns/…)
    if not catch_up:
        base = 0
        for p in paths:
            if os.path.exists(p):
                urls = [u for r in load_crawl(p) for u in (r["media"] + r["pages"])]
                hub.seed_seen(urls)
                base += len(urls)
        if base:
            hub.set_status(f"baselined {base} existing leaks — streaming only new discoveries …")
    hub.set_status("waiting for the deep scan to write its first checkpoint …")
    waited = 0.0
    last_sizes: dict[str, int] = {}
    stale = 0
    while True:
        emitted_before = hub.seq
        active = None
        for path in paths:
            if not os.path.exists(path):
                continue
            for r in load_crawl(path):
                for u in r["media"]:
                    hub.emit(r["domain"], u, kind_of(u))
                for u in r["pages"]:
                    hub.emit(r["domain"], u, "page")
            try:
                sz = os.path.getsize(path)
            except OSError:
                sz = -1
            if sz != last_sizes.get(path):
                active = os.path.basename(path)
            last_sizes[path] = sz
        grew = hub.seq > emitted_before
        stale = 0 if (grew or active) else stale + 1
        waited += poll
        if hub.seq == 0:
            if demo_fallback and waited >= 20 and os.path.exists(replay_fallback):
                hub.set_status("no live scan yet — replaying bundled crawl to test the stream")
                return producer_replay(hub, replay_fallback, rate)
            hub.set_status(f"waiting for the deep scan … ({int(waited)}s)")
        else:
            live = grew or active or stale <= 2
            hub.set_status(f"{hub.total} media / {len(hub.domains)} domains"
                           + (f" · live ({active})" if live and active else
                              " · live" if live else " · idle (scan paused?)"))
        time.sleep(poll)


# ── HTTP ─────────────────────────────────────────────────────────────────────
def make_handler(page_html: bytes):

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # quiet
            pass

        def _send(self, code, ctype, body: bytes, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        # ── per-request session resolution (?job=<slug>) ──────────────────────
        def _job(self):
            from urllib.parse import urlparse, parse_qs
            return (parse_qs(urlparse(self.path).query).get("job") or [""])[0]

        def _session(self):
            """The session this request is bound to: the ?job=<slug> one (or a lazily-rebuilt
            done view from disk), or the shared idle LANDING for the bare page. None → dead link."""
            slug = self._job()
            if not slug:
                return LANDING
            return session_get(slug)

        def _gate_ok(self):
            """Optional access gate: if LIVE_TOKEN is set (for a public deploy of client
            content), require ?t=<token> once — it's remembered in a cookie thereafter."""
            if not LIVE_TOKEN:
                return True
            from urllib.parse import urlparse, parse_qs
            qt = parse_qs(urlparse(self.path).query).get("t", [""])[0]
            ck = self.headers.get("Cookie", "")
            if qt == LIVE_TOKEN or f"lt={LIVE_TOKEN}" in ck:
                return True
            return False

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                self._send(200, "text/plain", b"ok")
                return
            if not self._gate_ok():
                self._send(401, "text/html; charset=utf-8",
                           b"<body style='font:16px sans-serif;background:#0f1020;color:#eef0ff;"
                           b"text-align:center;padding:20vh'>\xf0\x9f\x94\x92 Private report."
                           b"<br><small>Append <code>?t=YOUR_TOKEN</code> to the URL.</small></body>")
                return
            # remember the token in a cookie so assets/SSE (no query) pass the gate
            set_cookie = None
            if LIVE_TOKEN:
                from urllib.parse import urlparse, parse_qs
                if parse_qs(urlparse(self.path).query).get("t", [""])[0] == LIVE_TOKEN:
                    set_cookie = {"Set-Cookie": f"lt={LIVE_TOKEN}; Path=/; HttpOnly; SameSite=Lax"}
            # landing (/) and every shareable /s/<slug> serve the SAME page shell; the client reads
            # the slug from location.pathname and binds all its API calls to ?job=<slug>.
            is_share = path.startswith("/s/") and bool(SLUG_RE.match(path[3:]))
            if path in ("/", "/index.html") or (is_share and _slug_known(path[3:])):
                self._send(200, "text/html; charset=utf-8", page_html, extra=set_cookie)
            elif path.startswith("/s"):
                # forgive a MISREAD /s/<slug> link — the thin second slash reads as l/1/I or drops
                # out, so '.../s/zAbc…' arrives as '.../slzAbc…' or '.../szAbc…'. If it resolves to a
                # real report, 302 to the canonical /s/<slug> (keeping any ?t=token + the cookie).
                rec = _recover_slug(path)
                if rec:
                    q = self.path.split("?", 1)
                    loc = "/s/" + rec + (("?" + q[1]) if len(q) > 1 else "")
                    self._send(302, "text/plain", b"", extra={**(set_cookie or {}), "Location": loc})
                else:
                    # unrecoverable /s… link (garbage or a long-gone report) → send them to the
                    # landing page rather than a dead 404, so a mistyped link still lands somewhere.
                    self._send(302, "text/plain", b"", extra={**(set_cookie or {}), "Location": "/"})
            elif path == "/api/state":
                sess = self._session()
                if sess is None:
                    self._send(404, "application/json", b'{"error":"unknown job"}')
                    return
                sess.ensure_producer()
                self._send(200, "application/json",
                           json.dumps(sess.snapshot()).encode("utf-8"))
            elif path == "/api/assets":
                sess = self._session()
                self._send(200, "application/json",
                           json.dumps(sess.hub.assets if sess else {}).encode("utf-8"))
            elif path == "/api/stream":
                self._sse()
            elif path == "/asset":
                self._asset()
            elif path == "/media":
                self._media()
            elif path == "/qr":
                self._qr()
            elif path == "/api/links":
                self._links()
            elif path == "/api/scan/stream":
                self._scan_sse()
            elif path == "/api/sessions":
                self._send(200, "application/json",
                           json.dumps(_sessions_list()).encode("utf-8"))
            elif path == "/favicon.ico":
                self._send(204, "text/plain", b"")
            else:
                self._send(404, "text/plain", b"not found")

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            if not self._gate_ok():
                self._send(401, "application/json", b'{"error":"unauthorized"}')
                return
            if path == "/api/chat":
                self._chat()
            elif path == "/api/scan":
                self._scan_start()
            elif path == "/api/scan/cancel":
                sess = self._session()
                if sess is not None:
                    sess.scan.cancel()
                self._send(200, "application/json", b'{"ok":true}')
            elif path == "/api/sessions/delete":
                try:
                    body = json.loads(self._read_body(4096) or b"{}")
                except Exception:
                    body = {}
                ok, err = _delete_session((body.get("slug") or "").strip())
                self._send(200 if ok else 400, "application/json",
                           json.dumps({"ok": ok, "error": err}).encode("utf-8"))
            elif path == "/api/mail":
                self._mail()
            else:
                self._send(404, "text/plain", b"not found")

        def _mail(self):
            try:
                body = json.loads(self._read_body(4096) or b"{}")
            except Exception:
                body = {}
            to = (body.get("email") or "").strip()
            bucket = (body.get("bucket") or "LIKELY").upper()
            if "@" not in to or "." not in to.split("@")[-1]:
                self._send(400, "application/json", b'{"ok":false,"error":"invalid email"}')
                return
            sess = self._session()
            err = send_links_mail(to, (sess.prefix if sess else "") or "",
                                  bucket if bucket in ("LIKELY", "POSSIBLE") else "")
            self._send(200, "application/json",
                       json.dumps({"ok": not err, "error": err}).encode())

        def _read_body(self, cap=65536):
            try:
                n = min(int(self.headers.get("Content-Length", 0)), cap)
            except ValueError:
                n = 0
            return self.rfile.read(n) if n else b""

        def _links(self):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            bucket = (q.get("bucket") or [""])[0].upper()
            fmt = (q.get("fmt") or ["txt"])[0]
            sess = self._session()
            prefix = (sess.prefix if sess else "") or ""
            is_diff = (q.get("diff") or ["0"])[0] in ("1", "true", "yes")
            links = full_links(prefix, bucket if bucket in ("LIKELY", "POSSIBLE") else "")
            # ?diff=1 appends the deduped + raw crawl lists so the two blocks can be diffed to verify
            # the de-dup (works mid-run: KEPT = the growing crawl's de-duped media, RAW = every URL it
            # has surfaced so far). The two downloads get DISTINCT filenames so they're clearly not the
            # same file: collected_leak_links.txt (just the kept links) vs dedup_proof_kept_vs_raw.txt.
            if is_diff:
                links = links + ["", "# ---- de-dup verification (diff the two blocks below) ----"] \
                    + dedup_diff_lines(prefix)
            body = ("\n".join(links) + "\n").encode("utf-8")
            fname = "dedup_proof_kept_vs_raw.txt" if is_diff else "collected_leak_links.txt"
            extra = {"Content-Disposition": f'attachment; filename="{fname}"'} \
                if fmt == "download" else None
            self._send(200, "text/plain; charset=utf-8", body, extra=extra)

        def _chat(self):
            if not _HAVE_CHAT:
                self._send(503, "application/json", b'{"error":"chat unavailable"}')
                return
            try:
                body = json.loads(self._read_body(32768) or b"{}")
            except Exception:
                body = {}
            try:
                _wc.sse_start(self)
                kb = _chat.load_kb(KB_FILE)
                ctx = (body.get("scan_context") or "")[:3200]  # roomy: holds counts + a few example URLs per top site
                msgs = _chat.build_messages(kb, ctx, body.get("messages") or [])
                if not any(m.get("role") == "user" for m in msgs):
                    return _wc.sse_fail(self, "Ask me anything about your scan or getting leaks removed.")
                _chat.stream_chat(self, msgs)
            except Exception as e:
                try:
                    _wc.sse_fail(self, f"chat error: {e}")
                except Exception:
                    pass

        def _scan_start(self):
            if not SCAN_ENABLED:
                self._send(503, "application/json", b'{"error":"scan not available on this host"}')
                return
            try:
                body = json.loads(self._read_body(8192) or b"{}")
            except Exception:
                body = {}
            # a pasted profile URL is normalised to the bare username (onlyfans.com/x, instagram.com/x → x)
            handle = clean_handle(body.get("handle"))
            if not handle or len(handle) > 60:
                self._send(400, "application/json", b'{"error":"handle required"}')
                return
            aliases = [a for a in dict.fromkeys(clean_handle(a) for a in (body.get("aliases") or [])
                                                if isinstance(a, str)) if a and a != handle][:12]
            # Every scan is its OWN session (its own slug + shareable /s/<slug> link), so many people
            # can run and watch their own scans at once — the report link is minted immediately.
            slug, err = session_start(handle, aliases,
                                      no_cse=bool(body.get("no_cse")),
                                      no_variations=bool(body.get("no_variations")))
            if err == "busy":
                self._send(429, "application/json",
                           json.dumps({"ok": False, "error": "busy",
                                       "msg": f"All {MAX_LIVE_SCANS} scan slots are in use — try again shortly."}).encode())
                return
            if not slug:
                self._send(500, "application/json",
                           json.dumps({"ok": False, "error": err or "could not start"}).encode())
                return
            self._send(200, "application/json",
                       json.dumps({"ok": True, "slug": slug, "share": "/s/" + slug}).encode())

        def _scan_sse(self):
            sess = self._session()
            if sess is None:
                self._send(404, "application/json", b'{"error":"unknown job"}')
                return
            scan = sess.scan
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(b"event: snapshot\ndata: "
                                 + json.dumps(scan.snapshot()).encode() + b"\n\n")
                self.wfile.flush()
                last = scan.snapshot()["seq"]
                while True:
                    new, cur, running = scan.wait_after(last, timeout=10)
                    if new:
                        self.wfile.write(b"event: lines\ndata: "
                                         + json.dumps({"lines": [e["line"] for e in new],
                                                       "scan": scan.snapshot()}).encode() + b"\n\n")
                        self.wfile.flush()
                        last = cur
                    else:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                    if not running and last >= cur:
                        self.wfile.write(b"event: end\ndata: "
                                         + json.dumps(scan.snapshot()).encode() + b"\n\n")
                        self.wfile.flush()
                        break
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                pass

        def _asset(self):
            from urllib.parse import urlparse, parse_qs, unquote
            q = parse_qs(urlparse(self.path).query)
            rel = unquote((q.get("p") or [""])[0])
            try:
                width = max(0, min(1600, int((q.get("w") or ["0"])[0])))
            except ValueError:
                width = 0
            full = os.path.realpath(os.path.join(HERE, rel))
            # jail: must stay inside the repo root, must be a real file
            ext = os.path.splitext(full)[1].lower()
            # images only: the app dir also holds .env (Docker `COPY .`) and the source
            if (not (full == HERE or full.startswith(HERE + os.sep)) or not os.path.isfile(full)
                    or ext not in CTYPE):
                self._send(404, "text/plain", b"not found")
                return
            try:
                ctype, body = asset_bytes(full, ext, width)
            except OSError:
                self._send(404, "text/plain", b"not found")
                return
            self._send(200, ctype, body)

        def _qr(self):
            """PNG QR code of a report link, for the downloadable card (scan instead of typing the
            slug). Only encodes THIS server's own /s/<slug> links, so it isn't a generic QR service.
            Uses the `qrcode` lib (Pillow backend); degrades to 404 if it isn't installed."""
            from urllib.parse import urlparse, parse_qs, unquote
            q = parse_qs(urlparse(self.path).query)
            u = unquote((q.get("u") or [""])[0]).strip()
            if not re.match(r"^https?://[A-Za-z0-9.\-:]+/s/[A-Za-z0-9_-]{6,24}$", u):
                self._send(400, "text/plain", b"bad qr target")
                return
            try:
                box = max(4, min(16, int((q.get("sz") or ["8"])[0])))
            except ValueError:
                box = 8
            try:
                import io
                import qrcode
                qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                                   box_size=box, border=3)   # border ≥3 = the required quiet zone
                qr.add_data(u)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
                buf = io.BytesIO()
                img.save(buf, "PNG")
                self._send(200, "image/png", buf.getvalue(),
                           extra={"Cache-Control": "public, max-age=86400"})
            except Exception:
                self._send(404, "text/plain", b"qr unavailable")

        def _media(self):
            """Proxy + thumbnail a remote media URL for the live wall (deduped crawl images)."""
            from urllib.parse import urlparse, parse_qs, unquote
            q = parse_qs(urlparse(self.path).query)
            url = unquote((q.get("u") or [""])[0])
            try:
                width = max(0, min(1200, int((q.get("w") or ["0"])[0])))
            except ValueError:
                width = 0
            ctype, body = fetch_remote_thumb(url, width or 360)
            if not body:
                self._send(404, "text/plain", b"not found")
                return
            self._send(200, ctype, body, extra={"Cache-Control": "public, max-age=3600"})

        def _sse(self):
            sess = self._session()
            if sess is None:
                self._send(404, "application/json", b'{"error":"unknown job"}')
                return
            sess.ensure_producer()
            hub = sess.hub
            with SESSIONS_LOCK:                       # count this viewer (keeps the producer alive)
                sess.viewers += 1
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                # 1) hand the late joiner a full snapshot (+ asset catalog) so the UI can
                #    build its evidence wall and jump counters to current
                snap = sess.snapshot(include_assets=True)
                self.wfile.write(b"event: snapshot\ndata: "
                                 + json.dumps(snap).encode("utf-8") + b"\n\n")
                self.wfile.flush()
                last = snap["seq"]
                # 2) stream deltas; heartbeat keeps proxies from closing an idle connection
                while True:
                    new, cur, done = hub.wait_after(last, timeout=10)
                    if new:
                        if not done:
                            # coalesce a burst into ONE frame — at 80 leaks/s this cuts SSE
                            # messages ~10x (fewer client reflows) without losing counts
                            time.sleep(0.12)
                            new, cur, done = hub.wait_after(last, timeout=0)
                        payload = {"events": new[-60:], "state": sess.snapshot()}
                        self.wfile.write(b"event: batch\ndata: "
                                         + json.dumps(payload).encode("utf-8") + b"\n\n")
                        self.wfile.flush()
                        last = cur
                    else:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                    if done and last >= cur:
                        self.wfile.write(b"event: done\ndata: {}\n\n")
                        self.wfile.flush()
                        break
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                pass
            finally:
                with SESSIONS_LOCK:
                    sess.viewers = max(0, sess.viewers - 1)

    return H


PAGE = r"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Live leak report</title>
<style>
:root{--bg:#0f1020;--bg2:#171833;--card:#1c1e3d;--card2:#24264a;--tx:#eef0ff;--mut:#a3a7c9;
--acc:#7c5cff;--acc2:#38d9c7;--ok:#38d98a;--warn:#f5b74e;--bad:#ff6b6b;--line:#2c2e57;--r:16px}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;color:var(--tx);font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
background:radial-gradient(1200px 600px at 50% -10%,#241b4d 0%,var(--bg) 55%) fixed}
a{color:inherit;text-decoration:none}
b,strong{color:#fff}
code{font:12px ui-monospace,Menlo,monospace;color:#cbd0f5;background:rgba(124,92,255,.14);padding:1px 5px;border-radius:5px}
.wrap{max-width:1000px;margin:0 auto;padding:0 20px 70px;width:100%}
.topbar{display:flex;align-items:center;gap:12px;max-width:1000px;margin:0 auto;padding:16px 20px;flex-wrap:wrap}
/* live crawl-progress bar under the top bar — segmented into the 8 pipeline steps. Completed
   steps glow in the accent gradient; the ACTIVE step fills in amber with its own sub-progress. */
.progwrap{position:sticky;top:0;z-index:40;max-width:1000px;margin:0 auto;padding:0 20px 8px;display:flex;align-items:center;gap:10px}
.progwrap .progsteps{flex:1;display:flex;gap:4px;height:6px;align-items:stretch}
.progwrap .seg{position:relative;flex:1;border-radius:999px;background:rgba(124,92,255,.14);overflow:hidden;transition:background .3s}
.progwrap .seg.done{background:linear-gradient(90deg,var(--acc),var(--acc2));box-shadow:0 0 10px -3px var(--acc)}
.progwrap .seg.active{background:rgba(245,183,78,.16)}
.progwrap .seg .fill{position:absolute;left:0;top:0;bottom:0;width:0;border-radius:999px;background:linear-gradient(90deg,var(--warn),#ffd27a);box-shadow:0 0 10px -2px var(--warn);transition:width .5s ease}
.progwrap .seg.active.indet .fill{width:45%;animation:segslide 1.25s ease-in-out infinite}
@keyframes segslide{0%{left:-45%}100%{left:100%}}
.progwrap .progtx{flex:0 0 auto;font:600 11px ui-monospace,monospace;color:var(--mut);white-space:nowrap}
.brand{font-weight:800;font-size:19px;display:flex;align-items:center;gap:8px}.brand .lg{color:var(--acc2);font-size:22px}
.live{display:inline-flex;align-items:center;gap:7px;font:700 11px ui-monospace,monospace;letter-spacing:.08em;
color:var(--ok);border:1px solid rgba(56,217,138,.3);background:rgba(56,217,138,.08);padding:4px 10px;border-radius:999px}
.live .d{width:8px;height:8px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 0 rgba(56,217,138,.7);animation:pulse 1.6s infinite}
.live.report .d{background:var(--acc2);box-shadow:0 0 0 0 rgba(56,217,199,.7)}
.live.scanning{color:var(--warn);border-color:rgba(245,183,78,.4);background:rgba(245,183,78,.1)}
.live.scanning .d{background:var(--warn);box-shadow:0 0 0 0 rgba(245,183,78,.7)}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(56,217,138,.5)}70%{box-shadow:0 0 0 9px rgba(56,217,138,0)}100%{box-shadow:0 0 0 0 rgba(56,217,138,0)}}
.controls{margin-left:auto;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.toggle,.btn{display:inline-flex;align-items:center;gap:9px;cursor:pointer;user-select:none;background:var(--card);
border:1px solid var(--line);padding:7px 13px;border-radius:999px;font-size:13px;color:var(--tx)}
.toggle:hover,.btn:hover{border-color:var(--acc)}
.toggle .dot{width:34px;height:19px;border-radius:999px;background:#33365e;position:relative;transition:.2s}
.toggle .dot::after{content:"";position:absolute;top:2px;left:2px;width:15px;height:15px;border-radius:50%;background:#fff;transition:.2s}
body.revealed .toggle .dot{background:var(--ok)}body.revealed .toggle .dot::after{left:17px}
.hero{text-align:center;padding:14px 0 6px}
.badge{display:inline-block;font-size:12.5px;color:var(--acc2);background:rgba(56,217,199,.1);
border:1px solid rgba(56,217,199,.25);padding:6px 13px;border-radius:999px;margin-bottom:14px}
.hero h1{font-size:clamp(28px,6vw,46px);line-height:1.08;margin:6px 0 12px;letter-spacing:-.5px}
.hl{color:transparent;background:linear-gradient(90deg,var(--acc),var(--acc2));-webkit-background-clip:text;background-clip:text}
.hero .sub{color:var(--mut);font-size:16px;max-width:600px;margin:0 auto 16px}
/* hero face row — overlapping avatar-stack of the model's own leaked thumbnails (blurred until
   Reveal), so the report opens with a face, not just numbers. Fed live from the reliable image
   sources (CSE Google-Images thumbs + vetted gallery); hidden until at least one loads. */
.herofaces{display:flex;justify-content:center;align-items:center;margin:0 auto 16px;min-height:0}
.herofaces:empty{display:none}
.herofaces .hf{width:52px;height:52px;border-radius:50%;overflow:hidden;margin-left:-14px;
  border:2px solid var(--bg);box-shadow:0 3px 10px rgba(0,0,0,.4);background:var(--card2);
  transition:transform .25s,margin .25s;flex:0 0 auto}
.herofaces .hf:first-child{margin-left:0}
.herofaces .hf:hover{transform:translateY(-4px) scale(1.1);z-index:3}
.herofaces .hf img{width:100%;height:100%;object-fit:cover;object-position:top center;display:block;
  filter:blur(9px) brightness(.72);transition:filter .35s}
body.revealed .herofaces .hf img{filter:none}
.herofaces .hfmore{width:52px;height:52px;border-radius:50%;margin-left:-14px;border:2px solid var(--bg);
  background:var(--card2);color:var(--mut);display:flex;align-items:center;justify-content:center;
  font:700 14px -apple-system,system-ui,sans-serif;box-shadow:0 3px 10px rgba(0,0,0,.4);flex:0 0 auto}
.chips{display:flex;flex-wrap:wrap;gap:7px;justify-content:center;margin:0 auto 6px;max-width:680px}
.chip2{background:var(--card);border:1px solid var(--line);color:#c7cbf0;padding:4px 11px;border-radius:999px;font-size:12.5px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:13px;margin:22px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:15px 17px}
.stat .k{color:var(--mut);font-size:11.5px;text-transform:uppercase;letter-spacing:.06em}
.stat .v{font-size:30px;font-weight:750;margin-top:5px;line-height:1;font-variant-numeric:tabular-nums}
.stat .s{color:var(--mut);font-size:12px;margin-top:6px}
.stat.q{background:linear-gradient(135deg,#241b4d,#1c1e3d);border-color:#3a2f6b}.stat.q .v{color:var(--acc2)}
.stat.pulse{animation:spulse .6s ease}
@keyframes spulse{0%{border-color:var(--acc)}100%{border-color:var(--line)}}
.band{display:flex;align-items:center;gap:9px;margin-top:10px}
.band .t{flex:1;height:7px;border-radius:999px;background:#2a2c55;position:relative;overflow:hidden}
.band .t i{position:absolute;inset:0 auto 0 0;width:0;background:linear-gradient(90deg,var(--ok),var(--acc2),var(--acc));transition:width .8s ease}
.band small{color:var(--mut);font-size:11px;white-space:nowrap}
.spark{display:flex;align-items:flex-end;gap:2px;height:22px;margin-top:8px}
.spark i{flex:1;background:var(--acc2);opacity:.8;border-radius:2px 2px 0 0;min-height:2px;transition:height .3s}
.sec{margin:26px 0}
.sechead{display:flex;align-items:center;gap:12px;margin:0 0 4px;flex-wrap:wrap}
.sec h2{margin:0;font-size:19px;flex:1}
.lead{color:var(--mut);font-size:13.5px;margin:0 0 14px}
.pill{font-size:11.5px;padding:4px 11px;border-radius:999px;border:1px solid var(--line);background:var(--card);color:var(--mut)}
.pill.warn{color:var(--warn);border-color:rgba(245,183,78,.35);background:rgba(245,183,78,.1)}
.pill.acc{color:var(--acc2);border-color:rgba(56,217,199,.3);background:rgba(56,217,199,.09)}
/* domain bars */
.bars{display:flex;flex-direction:column;gap:8px;background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:16px 18px}
.bar{display:grid;grid-template-columns:170px 1fr 84px;align-items:center;gap:12px;font-size:13px}
.bar .bl{color:#dfe3ff;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}
.bar .bt{background:#22254a;border-radius:999px;height:12px;overflow:hidden}
.bar .bt i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--acc),var(--acc2));border-radius:999px;transition:width .9s cubic-bezier(.2,.7,.2,1)}
.bar .bv{text-align:right;color:var(--mut);font-variant-numeric:tabular-nums;font-size:12.5px}
.bar .bv b{color:#fff}
.bar.hit .bt i{filter:brightness(1.3)}
@media(max-width:560px){.bar{grid-template-columns:110px 1fr 64px}}
/* screenshots */
.shots{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}
.shot{position:relative;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:#0e131c;aspect-ratio:4/3;cursor:pointer;
animation:rise .6s cubic-bezier(.16,1,.3,1) both}
.shot img{width:100%;height:100%;object-fit:cover;display:block;filter:blur(17px) brightness(.72);transition:filter .35s}
body.revealed .shot img,.shot.show img{filter:none}
.shot .scan{position:absolute;left:0;right:0;top:0;height:26%;pointer-events:none;
background:linear-gradient(180deg,rgba(56,217,199,.5),transparent);box-shadow:0 0 22px 4px rgba(56,217,199,.3);animation:sweep .9s ease-out forwards}
.shot .cap{position:absolute;left:0;right:0;bottom:0;padding:16px 10px 7px;font-size:12.5px;font-weight:600;
background:linear-gradient(transparent,rgba(0,0,0,.9));display:flex;justify-content:space-between;gap:8px;align-items:center}
.shot .cap .c{color:var(--acc2);font-variant-numeric:tabular-nums}
.shot .stamp{position:absolute;top:9px;left:9px;font:800 11px ui-monospace,monospace;letter-spacing:.5px;color:#fff;
background:var(--bad);border-radius:6px;padding:3px 7px;transform:rotate(-7deg);box-shadow:0 4px 14px -4px rgba(255,107,107,.7);animation:thunk .5s cubic-bezier(.2,1.4,.3,1) both}
.shot .rv{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:12px;color:#e9eefc;text-shadow:0 1px 5px #000;pointer-events:none}
body.revealed .shot .rv,.shot.show .rv{display:none}
@keyframes rise{from{opacity:0;transform:translateY(16px) scale(.94)}to{opacity:1;transform:none}}
@keyframes sweep{0%{top:-30%;opacity:0}12%{opacity:1}100%{top:120%;opacity:0}}
@keyframes thunk{0%{transform:rotate(-7deg) scale(2.6);opacity:0}60%{opacity:1}100%{transform:rotate(-7deg) scale(1);opacity:1}}
/* leak-index link cards — the 'useful links' scrape, shown below the image tiles (not blurred:
   these are link lists, not media). Wide browser-window screenshots, one per column row. */
.lcwrap{margin-top:20px}
.lchead{display:flex;align-items:center;gap:10px;font-size:13.5px;font-weight:700;color:var(--ink,#e9eefc);
margin:0 2px 11px;padding-top:15px;border-top:1px dashed var(--line)}
.linkcards{display:grid;grid-template-columns:1fr;gap:16px}
@media(min-width:1000px){.linkcards{grid-template-columns:repeat(auto-fill,minmax(440px,1fr))}}
.linkcard{border:1px solid var(--line);border-radius:14px;overflow:hidden;background:#0e131c;
box-shadow:0 14px 40px -20px rgba(0,0,0,.6);animation:rise .6s cubic-bezier(.16,1,.3,1) both}
.linkcard img{width:100%;height:auto;display:block}
/* google / search evidence */
.gcard{position:relative;border:1px solid var(--line);border-radius:14px;overflow:hidden;background:#0e0f14;margin-bottom:14px}
.gchrome{padding:10px 13px;border-bottom:1px solid #1c2230;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.glogo{font:700 16px Arial,sans-serif;letter-spacing:-1px}
.glogo b:nth-child(1){color:#4285F4}.glogo b:nth-child(2){color:#EA4335}.glogo b:nth-child(3){color:#FBBC05}
.glogo b:nth-child(4){color:#4285F4}.glogo b:nth-child(5){color:#34A853}.glogo b:nth-child(6){color:#EA4335}
.gbar{flex:1;min-width:170px;display:flex;align-items:center;gap:8px;background:#1b1c20;border:1px solid #2a2d36;border-radius:20px;padding:7px 14px;color:#e8eaed;font:13px Arial}
.gpills{display:flex;gap:12px;color:#9aa0ac;font:600 11px Arial;align-items:center}.gpills .on{color:#8ab4f8}
.synbadge{font:700 10px ui-monospace,monospace;color:var(--warn);border:1px solid #4a3a1c;background:rgba(74,58,28,.25);padding:3px 8px;border-radius:6px}
.gmason{column-count:6;column-gap:6px;padding:9px 11px}
@media(max-width:760px){.gmason{column-count:4}}
.evmore{height:48px}   /* lazy-load sentinel: scrolling it into view appends the next image chunk */
.gmason img{width:100%;border-radius:5px;margin-bottom:6px;display:block;break-inside:avoid;animation:pop .5s ease both;filter:blur(11px) brightness(.8);transition:filter .3s}
body.revealed .gmason img{filter:none}
@keyframes pop{from{opacity:0;transform:scale(.6)}to{opacity:1;transform:none}}
.shimmer{position:absolute;top:0;bottom:0;width:36%;left:-40%;pointer-events:none;background:linear-gradient(90deg,transparent,rgba(56,217,199,.1),transparent);animation:shine 2.8s linear infinite}
@keyframes shine{to{left:120%}}
.dragrow{display:flex;align-items:flex-start;gap:14px;overflow-x:auto;padding:2px 2px 14px;cursor:grab;scroll-snap-type:x proximity}
.dragrow.drag{cursor:grabbing;scroll-snap-type:none}
.dragrow::-webkit-scrollbar{height:9px}.dragrow::-webkit-scrollbar-thumb{background:#33365e;border-radius:999px}
.gt{position:relative;flex:0 0 auto;width:min(88vw,560px);height:min(56vh,420px);scroll-snap-align:start;border-radius:14px;overflow:hidden;border:1px solid var(--line);background:#0e131c}
.gt img{width:100%;height:100%;object-fit:cover;object-position:top center;display:block;filter:blur(20px) brightness(.72);transition:filter .3s}
body.revealed .gt img,.gt.show img{filter:none}
.gt .gtag{position:absolute;top:9px;left:9px;background:rgba(0,0,0,.72);color:#ffd7a8;font:600 11px ui-monospace,monospace;padding:3px 9px;border-radius:999px}
.gt .rv{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:13px;color:#e9eefc;text-shadow:0 1px 5px #000;pointer-events:none}
body.revealed .gt .rv,.gt.show .rv{display:none}
/* deep 'Google search results' — reconstructed variant panels (drag strip) */
.gstrip{padding-bottom:16px}
/* phone-resolution capture — the generated panels read like a real phone screenshot, not a huge desktop shot */
.gspanel{position:relative;flex:0 0 auto;width:min(86vw,390px);scroll-snap-align:start;border:1px solid var(--line);border-radius:14px;overflow:hidden;background:#0e0f14}
.gspanel.cseshot{background:#0b0e14}
/* a real CSE capture is a tall full-page screenshot — crop it to a phone-ish height so the panel is
   the SAME size as the generated ones (no giant image + black dead space below). */
.gspanel .cseimg{width:100%;display:block;max-height:600px;object-fit:cover;object-position:top center;filter:blur(15px) brightness(.72);transition:filter .35s}
body.revealed .gspanel .cseimg,.gspanel.revealed .cseimg{filter:none}
.gspanel.cseshot .lock{position:absolute;bottom:9px;right:10px;inset:auto;font-size:16px;pointer-events:none}
body.revealed .gspanel.cseshot .lock{display:none}
.csebadge{font:700 9px ui-monospace,monospace;color:#ffd479;border:1px solid rgba(255,212,121,.42);background:rgba(255,212,121,.08);padding:2px 7px;border-radius:5px;letter-spacing:.4px}
.gschrome{padding:9px 12px;border-bottom:1px solid #1c2230;display:flex;align-items:center;gap:9px;flex-wrap:wrap;background:#15161d}
.gslogo b{font-weight:800;font-size:16px}
.gslogo b:nth-child(1){color:#4285F4}.gslogo b:nth-child(2){color:#EA4335}.gslogo b:nth-child(3){color:#FBBC05}.gslogo b:nth-child(4){color:#4285F4}.gslogo b:nth-child(5){color:#34A853}.gslogo b:nth-child(6){color:#EA4335}
.gsq{flex:1;min-width:80px;background:#0b0c11;border:1px solid #2a2f3d;border-radius:999px;padding:5px 12px;color:#cfd3e6;font-size:12.5px;display:flex;justify-content:space-between;align-items:center;gap:8px}
.gstabs{padding:5px 12px;display:flex;gap:12px;border-bottom:1px solid #1c2230;color:#8a90a6;font-size:11.5px;flex-wrap:wrap;align-items:center}
.gstabs .on{color:#8ab4f8;border-bottom:2px solid #8ab4f8;padding-bottom:2px}
.gscount{margin-left:auto;color:#8a90a6}
.gsm{column-count:2;column-gap:7px;padding:9px 11px}
.gscell{break-inside:avoid;margin-bottom:9px}
/* VARIED heights (real Google-Images masonry look): the aspect-ratio is set per-tile inline on the
   container, cropped to that shape so images fill it (no empty gaps) but tiles are no longer all
   identical — some taller, some square — the way a real image search results page looks. */
.gsthumb{position:relative;border-radius:7px;overflow:hidden;background:#0e131c;aspect-ratio:3/4}
.gsthumb img{width:100%;height:100%;display:block;object-fit:cover;object-position:top center;
filter:blur(12px) brightness(.78);transition:filter .3s}
body.revealed .gsthumb img,.gspanel.revealed .gsthumb img{filter:none}
.gsthumb .lock{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:19px;pointer-events:none}
body.revealed .gsthumb .lock,.gspanel.revealed .gsthumb .lock{display:none}
.gsct{font-size:12px;color:#dfe3f2;margin:5px 2px 1px;line-height:1.25}
.gssrc{font-size:11px;color:#9aa0ac;display:flex;align-items:center;gap:5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-decoration:none}
a.gssrc:hover{color:var(--acc2)}a.gssrc:hover .gsfav{background:var(--acc2)}
/* whole image tile / whole web-result row are clickable links (keep the screenshot look) */
a.gscell{display:block;color:inherit;text-decoration:none;cursor:pointer}
a.gscell:hover .gsct{color:var(--acc2)}
a.gwrow{cursor:pointer;text-decoration:none;color:inherit}
a.gwrow:hover{background:rgba(255,255,255,.03)}
a.gwrow:hover .gwtitle{text-decoration:underline}
.gsfav{width:12px;height:12px;border-radius:50%;background:#333a4d;display:inline-block;flex:0 0 auto}
/* ── generated panel styled as a realistic MOBILE Google-Images screenshot ── */
/* FIXED one-phone-screen height so every panel is identical (padded to fill) and cuts off mid-image at the bottom */
.gspanel.gsmob{background:#1b1b1d;border-color:#000;height:940px;overflow:hidden}
.gsmob::after{content:'';position:absolute;left:0;right:0;bottom:0;height:70px;background:linear-gradient(180deg,transparent,#1b1b1d);pointer-events:none;z-index:6}
.gsphone{position:relative;padding-bottom:14px}
.gsstatus{display:flex;justify-content:space-between;align-items:center;padding:10px 17px 2px;color:#fff}
.gsclock{font:600 15px -apple-system,'Segoe UI',Roboto,sans-serif;display:flex;align-items:center;gap:6px}
.gsclock .moon{font-size:12px}
.gssys{display:flex;align-items:center;gap:6px}.gssys svg{display:block}
.gsbrand{position:relative;display:flex;justify-content:center;align-items:center;padding:10px 0 12px}
.gsword b{font-weight:800;font-size:27px;line-height:1}
.gsright{position:absolute;right:15px;display:flex;align-items:center;gap:13px}
.gsright svg{display:block}
.gsdot{position:absolute;left:12px;top:-1px;width:7px;height:7px;border-radius:50%;background:#ea4335}
.gsava{width:27px;height:27px;border-radius:50%;flex:0 0 auto;background:conic-gradient(from 20deg,#f28b82,#fdd663,#81c995,#78d9ec,#c58af9,#f28b82)}
.gssearch{display:flex;align-items:center;gap:11px;margin:0 15px;background:#303134;border-radius:999px;padding:12px 17px}
.gssearch .gsqt{flex:1;color:#e8eaed;font-size:15.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gssearch svg{flex:0 0 auto}
.gstabs2{display:flex;gap:19px;padding:13px 16px 0;color:#9aa0ac;font-size:14.5px;overflow:hidden;white-space:nowrap}
.gstabs2 .on{color:#fff;font-weight:600;border-bottom:3px solid #8ab4f8;padding-bottom:9px}
.gssafe{display:flex;align-items:center;gap:9px;padding:13px 15px;border-bottom:1px solid #2b2b2d;overflow:hidden;white-space:nowrap}
.gssafe .sslabel{color:#e8eaed;font-weight:700;font-size:14px}
.gssafe .sspill{color:#c7c7c9;font-size:14px;border:1px solid #48494b;border-radius:999px;padding:6px 15px}
.gssafe .sspill.on{color:#a8c7fa;border-color:transparent;background:#1e3a5f;font-weight:600}
.gssafe .sskebab{margin-left:auto;color:#c7c7c9;font-size:18px;letter-spacing:-1px}
.gsm.gsmm{column-count:2;column-gap:6px;padding:9px 8px 0}
.gsmob .gscell{margin-bottom:13px}
/* natural image heights → genuine varied masonry (some tall, some short) like the real page */
.gsmob .gsthumb{border-radius:13px;aspect-ratio:auto;background:#111}
.gsmob .gsthumb img{height:auto}
.gsstamp{position:absolute;left:7px;bottom:7px;background:rgba(0,0,0,.6);color:#fff;font:500 11px -apple-system,sans-serif;padding:2px 8px;border-radius:8px;pointer-events:none;z-index:2}
.gsmob .gsct{font-size:14px;color:#e8eaed;margin:7px 4px 1px;line-height:1.3;display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden}
.gsmob .gssrc{font-size:12.5px;color:#9aa0ac;margin:0 4px;display:block}
.gsmob a.gssrc:hover{color:#8ab4f8}
.gsmob .gssrc.mut{color:#70757f}
.gsfloat{display:flex;align-items:center;justify-content:center;gap:9px;margin:12px auto 2px;width:max-content;max-width:82%;background:#303134;color:#e8eaed;border-radius:999px;padding:10px 20px;font-size:14.5px;box-shadow:0 8px 22px -8px #000}
.gsfloat svg{flex:0 0 auto}
/* pin the search pill to the bottom of the clipped panel so it floats over the cut-off images */
.gsmob .gsfloat{position:absolute;left:50%;bottom:15px;transform:translateX(-50%);margin:0;z-index:8}
/* ── mobile WEB-search ("All" tab) result rows + bottom nav bar ── */
.gwlist{padding:2px 0 0}
.gwrow{padding:16px 16px 17px;border-bottom:1px solid #2b2b2d}
.gwtop{display:flex;align-items:center;gap:11px}
.gwfav{width:30px;height:30px;border-radius:50%;flex:0 0 auto;display:flex;align-items:center;justify-content:center;font:700 13px -apple-system,sans-serif;color:#15151a}
.gwsite{flex:1;min-width:0;display:flex;flex-direction:column;line-height:1.25}
.gwname{color:#e8eaed;font-size:14px}
.gwurl{color:#9aa0ac;font-size:12.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gwkebab{color:#c7c7c9;font-size:18px;flex:0 0 auto;letter-spacing:-1px}
.gwtitle{display:block;color:#a3c9ff;font-size:20px;line-height:1.25;margin:13px 0 9px;text-decoration:none;font-weight:400}
.gwsnip{color:#bdc1c6;font-size:14px;line-height:1.42;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}
.gwnav{position:absolute;left:0;right:0;bottom:13px;display:flex;align-items:center;justify-content:center;gap:10px;padding:0 13px;z-index:8}
.gwbtn{width:46px;height:46px;border-radius:50%;background:rgba(42,43,47,.94);color:#e8eaed;display:flex;align-items:center;justify-content:center;font-size:23px;flex:0 0 auto}
.gwpill{flex:1;max-width:290px;display:flex;align-items:center;gap:11px;background:rgba(42,43,47,.94);border-radius:999px;padding:12px 19px;color:#e8eaed;font-size:15px}
.gwpill svg{flex:0 0 auto}.gwpq{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gsweb{padding:6px 12px 12px}
.gsrow{padding:9px 0;border-bottom:1px solid #171a24}
.gsrow .gsurl{font-size:11px;color:#9aa0ac;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gsrow .gsh3{color:#8ab4f8;font-size:14.5px;text-decoration:none;display:block;margin:2px 0}
.gsrow .gssnip{font-size:12px;color:#b9bed3;line-height:1.35}
.revealall{font-size:12px;padding:5px 12px}
/* 'Also all over Google' — two columns */
.gtwo{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:720px){.gtwo{grid-template-columns:1fr}}
.gcol{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:15px 17px}
.gcol h3{margin:0 0 11px;font-size:15px}
.glist.gscroll{max-height:360px;overflow:auto}
.grow{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--line)}
.gdom{color:#c7cbf0;text-decoration:none;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gdom:hover{color:var(--acc2)}
.gurls{flex:0 0 auto;font:700 11px ui-monospace,monospace;color:var(--warn);background:rgba(245,183,78,.1);border:1px solid rgba(245,183,78,.3);border-radius:999px;padding:2px 9px}
.gtop{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:9px}
.gtop li{font-size:12px}
.gtop a{color:#8ab4f8;text-decoration:none;word-break:break-all}
.gtop a:hover{text-decoration:underline}
/* live feed + link groups */
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:820px){.grid2{grid-template-columns:1fr}}
.panel{background:var(--card);border:1px solid var(--line);border-radius:var(--r);overflow:hidden}
.panel .ph{padding:12px 15px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;font-weight:700;font-size:14px}
.panel .ph .mut{color:var(--mut);font:600 11px ui-monospace,monospace}
.feed{max-height:420px;overflow:auto}
.row{display:flex;align-items:center;gap:10px;padding:8px 15px;border-bottom:1px solid #23264d;font:12px ui-monospace,Menlo,monospace}
.row.flash{animation:rowin .9s ease-out}
@keyframes rowin{0%{background:rgba(124,92,255,.22);transform:translateX(12px)}100%{background:transparent;transform:none}}
.row .ic{width:16px;flex:0 0 16px;text-align:center}
.row .d{color:#fff;font-weight:700;flex:0 0 auto;max-width:34%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .u{color:var(--mut);flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .b{font-size:9px;font-weight:700;padding:2px 6px;border-radius:5px;flex:0 0 auto}
.b.LIKELY{color:var(--ok);border:1px solid rgba(56,217,138,.35)}.b.POSSIBLE{color:var(--warn);border:1px solid rgba(245,183,78,.35)}
.lgwrap{max-height:420px;overflow:auto;padding:10px 12px;display:flex;flex-direction:column;gap:6px}
.lg{border:1px solid var(--line);border-radius:10px;background:var(--bg2);overflow:hidden}
.lg summary{cursor:pointer;padding:9px 13px;font-weight:600;font-size:13px;display:flex;justify-content:space-between;gap:8px;list-style:none}
.lg summary::-webkit-details-marker{display:none}
.lg summary .mut{color:var(--mut);font:600 12px ui-monospace,monospace}
/* keep the group its current compact size but scroll THROUGH every leak inside it (all N URLs) */
.lg ul{margin:0;padding:6px 10px 10px 26px;display:flex;flex-direction:column;gap:5px;max-height:300px;overflow-y:auto;overscroll-behavior:contain}
.lg ul::-webkit-scrollbar{width:8px}.lg ul::-webkit-scrollbar-thumb{background:#33365e;border-radius:999px}
.lg li{font-family:ui-monospace,monospace;font-size:11px;line-height:1.7;min-height:1.7em;color:#aeb4e0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:0 0 auto}
.lg li a{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lg a:hover{color:var(--acc2)}
.sesslist{display:flex;flex-direction:column;gap:8px}
.sessgrouphd{font:700 12px ui-monospace,monospace;letter-spacing:.6px;text-transform:uppercase;color:var(--mut);margin:6px 2px 1px}
.sessrow{display:flex;align-items:center;gap:12px;padding:11px 13px;border:1px solid var(--line);border-radius:11px;background:var(--bg2)}
.sessrow.run{border-color:#2e7d5b;background:linear-gradient(90deg,rgba(38,201,143,.10),transparent 60%)}
.sessrow.queue{border-color:#7a5a1e}
.sessdot{width:9px;height:9px;border-radius:50%;flex:0 0 auto;background:#5b6081}
.sessrow.run .sessdot{background:#26c98f;box-shadow:0 0 0 0 rgba(38,201,143,.6);animation:sesspulse 1.6s infinite}
.sessrow.queue .sessdot{background:#f5b74e}
@keyframes sesspulse{0%{box-shadow:0 0 0 0 rgba(38,201,143,.55)}70%{box-shadow:0 0 0 7px rgba(38,201,143,0)}100%{box-shadow:0 0 0 0 rgba(38,201,143,0)}}
.sesshandle{font-weight:700;color:#eef0ff}.sesshandle .at{color:var(--mut)}
.sessmeta{color:var(--mut);font:12px ui-monospace,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sessrow .grow{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:2px}
.sessbadge{flex:0 0 auto;font:700 11px ui-monospace,monospace;padding:3px 8px;border-radius:999px;letter-spacing:.4px}
.sessbadge.run{color:#26c98f;background:rgba(38,201,143,.14)}
.sessbadge.queue{color:#f5b74e;background:rgba(245,183,78,.14)}
.sessbadge.done{color:#9aa0c7;background:rgba(154,160,199,.12)}
.sessopen{flex:0 0 auto;font:700 12px ui-monospace,monospace;color:var(--acc2);text-decoration:none;padding:6px 11px;border:1px solid var(--line);border-radius:9px}
.sessopen:hover{border-color:var(--acc2)}
.sessdel{flex:0 0 auto;cursor:pointer;background:transparent;border:1px solid var(--line);color:#c77;border-radius:9px;padding:6px 10px;font:700 12px ui-monospace,monospace}
.sessdel:hover{border-color:#c55;background:rgba(200,80,80,.12);color:#f88}
.sessdel:disabled{opacity:.4;cursor:default}
footer{color:var(--mut);font:11.5px ui-monospace,monospace;text-align:center;padding:10px 20px 30px}
.mile{position:fixed;left:50%;top:14%;transform:translateX(-50%) scale(.7);z-index:30;font:800 28px ui-monospace,monospace;color:#0f1020;
letter-spacing:.5px;padding:14px 26px;border-radius:14px;background:linear-gradient(135deg,var(--acc2),var(--acc));box-shadow:0 20px 60px -12px rgba(124,92,255,.6);opacity:0;pointer-events:none}
.mile.show{animation:mile 2.4s cubic-bezier(.2,1.2,.3,1) forwards}
@keyframes mile{0%{opacity:0;transform:translateX(-50%) scale(.7)}12%{opacity:1;transform:translateX(-50%) scale(1)}80%{opacity:1}100%{opacity:0;transform:translateX(-50%) scale(1.05)}}
body.present .topbar .controls,body.present .chips{opacity:.35}
@media (prefers-reduced-motion: reduce){.shimmer,.live .d{animation:none!important}.shot,.gmason img,.row,.mile.show{animation-duration:.3s!important}}
.ctabar{display:flex;flex-wrap:wrap;align-items:center;gap:14px;background:linear-gradient(135deg,#241b4d,#1c1e3d);border:1px solid #3a2f6b;border-radius:var(--r);padding:16px 20px;margin:22px 0}
.ctabar .ct{flex:1;min-width:200px}.ctabar .ct b{font-size:16px}.ctabar .ct span{display:block;color:var(--mut);font-size:13px;margin-top:2px}
.dmrow{display:flex;gap:9px;flex-wrap:wrap}
.dm{padding:9px 15px;border-radius:11px;font-weight:700;font-size:13px;color:#fff;display:inline-flex;gap:7px;align-items:center;cursor:pointer}
.dm.ig{background:linear-gradient(135deg,#f58529,#dd2a7b,#8134af)}.dm.wa{background:#25d366;color:#043}.dm.tg{background:#2aabee}
.linkactions{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 12px}
.mailin{background:var(--bg2);border:1px solid var(--line);color:var(--tx);border-radius:11px;padding:8px 13px;font-size:13px;outline:none;min-width:190px}
.mailin:focus{border-color:var(--acc)}
.mailmsg{color:var(--mut);font-size:12.5px}
.mut2{color:var(--mut);font-weight:400;font-size:15px}
.lgfull{display:grid;grid-template-columns:1fr 1fr;gap:6px;align-items:start}
@media(max-width:760px){.lgfull{grid-template-columns:1fr}}
.feed{max-height:180px;overflow:auto;border:1px solid var(--line);border-radius:11px;background:#0a0b16;margin:0 0 12px}
.toast{position:fixed;bottom:22px;left:50%;transform:translateX(-50%);background:var(--acc2);color:#0f1020;font-weight:700;padding:11px 18px;border-radius:11px;z-index:40;opacity:0;transition:.3s;pointer-events:none}
.toast.show{opacity:1}
.scanpanel{background:linear-gradient(135deg,#221a44,var(--card));border:1px solid #3a2f6b;border-radius:var(--r);padding:18px 20px;margin:0 0 22px;box-shadow:0 12px 40px -18px rgba(124,92,255,.5)}
.btn.primary{background:linear-gradient(135deg,var(--acc),var(--acc2));color:#0f1020;border:0;font-weight:800}
.btn.primary:hover{filter:brightness(1.08)}
.scanform{display:flex;gap:9px;flex-wrap:wrap;margin:12px 0 0}
.scanform input{flex:1;min-width:170px;background:var(--bg2);border:1px solid var(--line);color:var(--tx);border-radius:11px;padding:11px 14px;font-size:14px;outline:none}
.scanform input:focus{border-color:var(--acc)}
/* opt-out switches: unpressed = the step runs (default); pressed = that step is skipped this scan */
.btn.opt{background:var(--bg2);color:var(--mut);font-weight:700;white-space:nowrap}
.btn.opt:before{content:'○';font-size:14px;line-height:1}
.btn.opt[aria-pressed=true]{background:rgba(255,107,107,.15);border-color:var(--bad);color:#ffc0c0}
.btn.opt[aria-pressed=true]:before{content:'✕'}
.scanlog{background:#0a0b16;border:1px solid var(--line);border-radius:11px;padding:13px 14px;font:12px ui-monospace,monospace;color:#9fb0d8;max-height:min(56vh,440px);overflow:auto;white-space:pre-wrap;margin:0}
/* console (scan log) — now a standalone block at the bottom, just above the chat */
.console{margin:26px 0}
.consolehead{display:flex;align-items:center;gap:10px;margin:0 0 11px;flex-wrap:wrap}
.consolehead .chead{font-weight:800;font-size:17px}
.consolehead .pill{margin-left:auto}
/* live media wall — deduped crawl images streaming in */
.livewall{display:grid;grid-template-columns:repeat(auto-fill,minmax(132px,1fr));gap:9px;min-height:60px}
.wtile{position:relative;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:#0e131c;aspect-ratio:3/4;cursor:pointer;animation:rise .5s cubic-bezier(.16,1,.3,1) both}
.wtile img{width:100%;height:100%;object-fit:cover;display:block;filter:blur(15px) brightness(.72);transition:filter .35s}
.wtile a.wlink{display:block;width:100%;height:100%}
body.revealed .wtile img,.wtile.show img{filter:none}
.wtile .cap{position:absolute;left:0;right:0;bottom:0;padding:15px 8px 6px;font:600 10.5px ui-monospace,monospace;
background:linear-gradient(transparent,rgba(0,0,0,.92));display:flex;justify-content:space-between;gap:6px;align-items:center}
.wtile .cap span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wtile .cap a.hostln{color:inherit;text-decoration:none;position:relative;z-index:2;pointer-events:auto}
.wtile .cap a.hostln:hover{color:var(--acc);text-decoration:underline}
.shot .cap a.hostln{color:inherit;text-decoration:none;position:relative;z-index:2;pointer-events:auto}
.shot .cap a.hostln:hover{color:var(--acc2);text-decoration:underline}
.wtile .cap .c{color:var(--acc2);flex:0 0 auto}
.wtile .stamp{position:absolute;top:7px;left:7px;font:800 10px ui-monospace,monospace;letter-spacing:.5px;color:#fff;
background:var(--bad);border-radius:6px;padding:2px 6px;transform:rotate(-7deg);box-shadow:0 4px 14px -4px rgba(255,107,107,.7)}
.wtile .rv{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:15px;pointer-events:none}
body.revealed .wtile .rv,.wtile.show .rv{display:none}
.wtile.vid{display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#241b4d,#12152c)}
.wtile .vidph{font-size:30px;color:var(--acc2);opacity:.9}
.wallempty{grid-column:1/-1;color:var(--mut);font:13px ui-monospace,monospace;padding:14px 2px;text-align:center}
/* ── phase-driven layout ── */
/* default (unknown phase → finished-report look: full report, hide scan panel / wall / console) */
#scanpanel,#livewallsec,#scanconsole{display:none}
body.phase-idle #scanpanel{display:block}
body.scanopen #scanpanel,body.scanopen #scanintro{display:block!important}  /* "New deep scan" from a done report */
body.phase-scanning #livewallsec,body.phase-scanning #scanconsole{display:block}
/* after a scan ENDS, keep the console (copyable log) + the streamed images in place — no refresh,
   nothing lost. The CSE evidence sections (done-phase) render below them. */
body.scandone #scanconsole,body.scandone #livewallsec{display:block}
/* opening a finished /s/<slug> report → replay the leaks "flowing in" (see maybeReplay) — the wall
   has no live SSE stream in the done phase, so surface it while the replay floods it with images. */
body.replaying #livewallsec{display:block}
/* idle = only stats + ask bar + start box + chat (clean 0-state). Hide CTA + every report section. */
/* clean landing = just the deepscan box (hero + start form). Hide the empty stat cards, the ask
   pill, the chat, and every report section until a scan actually starts producing results. */
body.phase-idle #stats,
body.phase-idle #askbar,
body.phase-idle #chatsec,
body.phase-idle .ctabar,
body.phase-idle #barsec,
body.phase-idle #shotsec,
body.phase-idle #googlesec,
body.phase-idle #gsearchsec,
body.phase-idle #galsosec,
body.phase-idle #exportsec,
body.phase-idle #linksec{display:none}
/* clean landing: the topbar carries no report controls — no Reveal, no Copy report link */
body.phase-idle .topbar .controls{display:none}
/* #googlesec retired — the two clean sections do the job: IMAGES = #gsearchsec (CSE Google-Images
   thumbnails), TEXT links = #galsosec ('Also all over Google'). Hidden in every phase. */
#googlesec{display:none!important}
/* scanning keeps the full report visible (chart/screenshots/Google/links fill live); only the CTA
   "up buttons" stay hidden. The console now sits at the bottom, just above the chat. */
body.phase-scanning .ctabar{display:none}
body.phase-idle #topsec{display:none}
/* top results list (a representative link from each top site) */
.toplist{list-style:none;margin:0;padding:14px 16px;display:flex;flex-direction:column;gap:7px;background:var(--card);border:1px solid var(--line);border-radius:var(--r);counter-reset:tr}
.toplist li{display:flex;align-items:center;gap:11px;font:12.5px ui-monospace,Menlo,monospace;min-width:0}
.toplist li::before{counter-increment:tr;content:counter(tr);color:var(--acc2);font-weight:700;width:20px;flex:0 0 20px;text-align:right}
.toplist .td{color:#fff;font-weight:700;flex:0 0 auto;max-width:32%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.toplist .tu{color:var(--mut);flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.toplist a:hover .tu{color:var(--acc2)}
.toplist .tk{flex:0 0 auto;font-size:11px}
/* results card button + hidden canvas */
.cardbtn{background:linear-gradient(135deg,#241b4d,#1c1e3d);border:1px solid #3a2f6b}
/* results-card popup — opens on every load of a finished report */
.cardpop{position:fixed;inset:0;z-index:60;display:none;align-items:center;justify-content:center;
  padding:20px;background:rgba(6,7,18,.86);backdrop-filter:blur(6px)}
.cardpop.show{display:flex}
.cardbox{display:flex;flex-direction:column;gap:12px;max-width:min(430px,94vw);max-height:94vh;
  padding:16px;background:var(--card);border:1px solid var(--line);border-radius:18px;box-shadow:0 30px 90px rgba(0,0,0,.65)}
.cardbox img{width:100%;max-height:72vh;object-fit:contain;border-radius:12px;background:#0f1020}
.cardrow{display:flex;align-items:center;justify-content:space-between;gap:12px}
.cardrow .mut{font-size:12.5px}
.cardrow .btn{flex:0 0 auto;white-space:nowrap}
/* compact top "ask" bar — a quick DeepSeek question above the leaks, like the quick-scan */
.askbar{max-width:none;margin:0 0 22px}   /* full section width — same as every other block, not narrower */
.askans{display:flex;flex-direction:column;gap:8px;max-height:0;overflow:hidden;transition:max-height .3s ease}
.askans.on{max-height:280px;overflow:auto;margin-bottom:10px;padding:2px}
.askpill{display:flex;align-items:center;gap:8px;background:var(--card);border:1px solid var(--line);border-radius:999px;padding:5px 5px 5px 17px}
.askpill:focus-within{border-color:var(--acc)}
.askpill input{flex:1;background:transparent;border:0;color:var(--tx);font-size:14px;outline:none;padding:9px 0}
.askgo{flex:0 0 auto;width:40px;height:40px;border-radius:999px;border:0;cursor:pointer;color:#0f1020;font-size:17px;background:linear-gradient(135deg,var(--acc),var(--acc2))}
.askans .msg{max-width:100%;font-size:13px;padding:8px 12px}
.chat{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:13px 14px}
.clog{display:flex;flex-direction:column;gap:8px;max-height:200px;overflow:auto;padding:2px}
#chatsec{max-width:720px}
#chatsec .lead{display:none}
#chatsec .msg{font-size:13px;padding:7px 11px}
.msg{max-width:84%;padding:9px 13px;border-radius:13px;font-size:14px;line-height:1.5;white-space:pre-wrap;word-break:break-word}
.msg.bot{background:var(--card2);border:1px solid var(--line);align-self:flex-start;border-bottom-left-radius:4px}
.msg.me{background:var(--acc);color:#0f1020;align-self:flex-end;border-bottom-right-radius:4px;font-weight:500}
.qr{display:flex;flex-wrap:wrap;gap:7px;margin:10px 0 4px}
.qr b{cursor:pointer;font:500 12.5px sans-serif;color:var(--acc2);background:rgba(56,217,199,.08);border:1px solid rgba(56,217,199,.28);padding:5px 11px;border-radius:999px}
.cform{display:flex;gap:8px;margin-top:10px}
.cform input{flex:1;background:var(--bg2);border:1px solid var(--line);color:var(--tx);border-radius:11px;padding:11px 14px;font-size:14px;outline:none}
.cform input:focus{border-color:var(--acc)}
.cform button{background:linear-gradient(135deg,var(--acc),var(--acc2));border:0;color:#0f1020;font-weight:700;border-radius:11px;padding:0 16px;cursor:pointer;font-size:16px}
.btn.share{background:linear-gradient(135deg,var(--acc),var(--acc2));color:#0f1020;border:0;font-weight:800}
.btn.share:hover{filter:brightness(1.08)}
/* persistent copyable "full run" command box */
.cmdbox{margin:0 0 14px}
.cmdhead{display:flex;align-items:center;gap:10px;margin:0 0 7px;flex-wrap:wrap}
.cmdhead .ct{font-weight:700;font-size:13.5px}
.cmdhead .pill{margin-left:auto}
.cmdpre{background:#0a0b16;border:1px solid var(--line);border-radius:11px;padding:12px 14px;margin:0;
font:11.5px ui-monospace,Menlo,monospace;color:#9fe8d8;white-space:pre-wrap;word-break:break-all;max-height:160px;overflow:auto}
/* collected-links export (full list + diff-test download) */
.exportbox{width:100%;box-sizing:border-box;height:320px;margin-top:10px;background:#0a0b16;border:1px solid var(--line);
border-radius:11px;padding:12px 14px;color:#aeb4e0;font:11.5px ui-monospace,Menlo,monospace;resize:vertical;outline:none}
.exportbox:focus{border-color:var(--acc)}
</style></head><body>
<div class=topbar>
  <a class=brand href="/" title="Back to the start page"><span class=lg>🛡</span> Live leak <b>report</b></a>
  <span class="live report" id=live><span class=d></span> <span id=livetx>LIVE</span></span>
  <div class=controls>
    <button class="btn share" id=sharebtn hidden>🔗 Copy report link</button>
    <label class=toggle><input type=checkbox id=reveal hidden><span class=dot></span> Reveal</label>
  </div>
</div>
<div class=progwrap id=progwrap hidden><div class=progsteps id=progsteps></div><span class=progtx id=progtx></span></div>
<div class=wrap>
  <div class=hero>
    <div class=badge id=statusbadge>● auto-updating from the live scan</div>
    <h1><span class=hl id=h_leaks>0</span> leaked files across <span class=hl id=h_sites>0</span> sites</h1>
    <div class=herofaces id=herofaces></div>
    <div class=sub id=subline>Real-time map of everywhere this creator's content has been reposted — screenshots, Google hits, and every detected link.</div>
    <div class=chips id=chips></div>
  </div>

  <div class=stats id=stats>
    <div class=stat><div class=k>Leaked files</div><div class="v" id=s_total>0</div>
      <div class=band><div class=t><i id=band_total></i></div><small id=band_totaltx>—</small></div></div>
    <div class="stat q"><div class=k>DMCA-ready</div><div class="v" id=s_likely>0</div><div class=s>high-confidence · ready to file</div></div>
    <div class=stat><div class=k>Sites hosting</div><div class="v" id=s_sites>0</div><div class=s id=s_sites_s>domains</div></div>
    <div class=stat><div class=k>Direct media URLs</div><div class="v" id=s_dm>0</div><div class=s>images &amp; videos</div></div>
    <div class="stat q"><div class=k>Takedown quote</div><div class="v" id=s_quote>€0</div>
      <div class=band><small>€250</small><div class=t><i id=band_price></i></div><small>€500</small></div>
      <div class=s id=s_monthly>one-time · optional ongoing protection</div></div>
  </div>

  <div class=askbar id=askbar hidden>
    <div class=askans id=askans></div>
    <form class=askpill id=askform autocomplete=off>
      <input id=askinput type=text maxlength=1000 placeholder="Ask anything — leaks, DMCA, or how this works…" autocomplete=off>
      <button class=askgo id=asksend type=submit aria-label=Ask>➤</button>
    </form>
  </div>

  <div class=ctabar>
    <div class=ct><b>Need these taken down?</b><span>Copy every link, or reach out and we'll handle the removals.</span></div>
    <div class=dmrow id=dmrow></div>
    <button class=btn id=newscanbtn hidden>⚡ New deep scan</button>
  </div>

  <div class=sec id=livewallsec>
    <div class=sechead><h2>Leaks coming in <span class=mut2 id=wallsub>— live</span></h2><span class=pill acc id=wallcount>0 shown</span></div>
    <p class=lead>Every image the crawler is pulling right now, de-duplicated as it lands. Blurred — flip <b>Reveal</b> to view.</p>
    <div class=livewall id=livewall></div>
  </div>

  <div class=scanpanel id=scanpanel>
    <div id=scanintro>
      <div class=sechead><h2>Start a deep scan</h2><span class=pill id=scanpill>idle</span></div>
      <p class=lead>Enter a handle and hit Start — the full pipeline runs (presence → deep crawl of every known leak site → clean → triage → Google CSE → gallery → DMCA export). The images and counts fill in live as it goes.</p>
      <div class=scanform>
        <input id=scanhandle placeholder="handle to scan — e.g. janedoee" autocomplete=off>
        <input id=scanaliases placeholder="other names / aliases, comma-separated (optional)" autocomplete=off>
        <button type=button class="btn opt" id=optnocse aria-pressed=false
          title="Skip the Google Programmable Search pass — no 'Also all over Google' evidence grid. Faster; crawl-only.">No CSE</button>
        <button type=button class="btn opt" id=optnovar aria-pressed=false
          title="Scan only the handle + aliases you type — skip the title-harvest that discovers extra re-upload handles.">No variations</button>
        <button class="btn primary" id=scango>🔍 Start deep scan</button>
      </div>
    </div>
  </div>

  <div class=sec id=sessionssec>
    <div class=sechead><h2>Live scans on this server</h2><span class=pill id=sesspill>—</span></div>
    <p class=lead>Everyone's scans in one place — what's <b>running</b> now, what's <b>queued</b> behind it, and finished <b>history</b>. Open any one, or delete it to free the queue / disk.</p>
    <div class=sesslist id=sesslist><div class=mut2>loading…</div></div>
  </div>

  <div class=sec id=barsec>
    <div class=sechead><h2>Where the leaks are</h2><span class=pill acc id=dompill>top domains</span></div>
    <p class=lead>Every site found hosting this content, ranked by how many files it's carrying. <span class=mut2>Bar length is log-scaled so smaller sites stay visible next to the biggest — the number is the true count.</span></p>
    <div class=bars id=bars></div>
  </div>

  <div class=sec id=topsec>
    <div class=sechead><h2>Top results</h2><span class=pill acc id=toppill>most-linked</span></div>
    <p class=lead>The highest-volume public posts — a representative link from each top site, ready to open.</p>
    <ol class=toplist id=toplist></ol>
  </div>

  <div class=sec id=shotsec>
    <div class=sechead><h2>Site screenshots</h2><span class=pill id=shotpill>0 captured</span></div>
    <p class=lead>Live page captures of the sites hosting the content. Blurred — flip <b>Reveal</b> to view.</p>
    <div class="dragrow gstrip" id=siteshotgrids hidden></div>
    <div class=shots id=shotgrid></div>
  </div>

  <div class=sec id=googlesec>
    <div class=sechead><h2>Google &amp; search evidence</h2><span class=pill warn>🔞 blurred · your de-duplicated leaks</span></div>
    <p class=lead>Your actual de-duplicated leaked images — only verified matches (no ads / wrong-person / text tiles), shown the way they surface across Google Images. Scroll for more.</p>
    <div class=gcard id=gcard>
      <div class=gchrome>
        <span class=glogo><b>G</b><b>o</b><b>o</b><b>g</b><b>l</b><b>e</b></span>
        <span class=gbar><svg width=15 height=15 viewBox="0 0 24 24" fill="#9aa0ac"><path d="M15.5 14h-.79l-.28-.27a6.5 6.5 0 10-.7.7l.27.28v.79l5 5 1.5-1.5-5-5zm-6 0A4.5 4.5 0 1114 9.5 4.5 4.5 0 019.5 14z"/></svg><span id=gq>leaks</span></span>
        <span class=gpills><span class=on>Images</span><span>News</span><span>SafeSearch <b class=on>off</b></span></span>
        <div class=shimmer></div>
      </div>
      <div class=gmason id=gmason></div>
      <div id=evmore class=evmore></div>
    </div>
    <div class=dragrow id=grids hidden></div>
  </div>

  <div class=sec id=gsearchsec hidden>
    <div class=sechead><h2>Google search results</h2>
      <span class=pill warn>🔗 leak result links · drag to scroll</span></div>
    <p class=lead id=gslead>Reconstructed from Google's live index (Custom Search) — every public page where this creator surfaces, as search-result links. Drag sideways to browse them all.</p>
    <div class="dragrow gstrip" id=gstrip></div>
  </div>

  <div class=sec id=galsosec hidden>
    <div class=sechead><h2>Also all over Google</h2><span class=pill warn>🔞 blurred · tap any image</span></div>
    <p class=lead id=galead>Google is indexing your name across public sites — the pages anyone finds just by searching. We get them delisted from Google too.</p>
    <div class=gtwo>
      <div class=gcol><h3>Sites indexing you on Google</h3><div class="glist gscroll" id=gsites></div></div>
      <div class=gcol><h3>Top public results</h3><ol class=gtop id=gtop></ol></div>
    </div>
  </div>

  <div class=sec id=linksec>
    <div class=sechead><h2>All detected leak links <span class=mut2 id=linkcount></span></h2><span class=pill id=linkpill>0 links</span></div>
    <p class=lead>Every detected URL, grouped by site — most first, ready for takedown.</p>
    <div class=linkactions>
      <button class=btn id=copyall>⧉ Copy all</button>
      <a class=btn id=dlall href="/api/links?fmt=download" title="Just the kept, de-duplicated leak links">⭳ All kept links (.txt)</a>
      <a class=btn id=dldiff href="/api/links?fmt=download&diff=1" title="KEPT (deduped) + RAW pre-clean crawl — diff the two blocks">⭳ De-dup proof — kept vs raw (.txt)</a>
      <button class="btn cardbtn" id=cardbtn>🖼 Results card</button>
      <input id=mailto class=mailin type=email placeholder="email to send links…" autocomplete=off>
      <button class=btn id=mailbtn>✉ Mail links</button>
      <span id=mailmsg class=mailmsg></span>
    </div>
    <div class=feed id=feed hidden></div>
    <div class=lgfull id=groups></div>
  </div>

  <div id=scanconsole class=console>
    <div class=consolehead><span class=chead>▶ deep scan console</span>
      <span class=pill id=scanpill2>running</span>
      <button class=btn id=scancancel>■ Cancel</button></div>
    <div class=cmdbox id=scancmd hidden>
      <div class=cmdhead><span class=ct>⌨ Full run command</span>
        <span class=pill acc>copy to reproduce the exact run</span>
        <button class=btn id=cmdcopy>⧉ Copy command</button></div>
      <pre class=cmdpre id=scancmdpre></pre>
    </div>
    <pre class=scanlog id=scanlog></pre>
  </div>

  <div class=sec id=exportsec>
    <div class=sechead><h2>Collected leak links</h2><span class=pill id=exportpill>0 links</span></div>
    <p class=lead>The de-duplicated list of every collected leak link. Two <b>different</b> downloads:
      the <b>kept links</b> on their own, and a <b>de-dup proof</b> that also appends the raw pre-clean
      crawl so you can diff kept-vs-raw and confirm nothing real was dropped. Both work mid-run.</p>
    <div class=linkactions>
      <button class=btn id=exportload>⟳ Load full list</button>
      <button class=btn id=exportcopy>⧉ Copy all</button>
      <a class=btn id=exportdl href="/api/links?fmt=download" title="Just the kept, de-duplicated leak links">⭳ All kept links (.txt)</a>
      <a class=btn id=exportdiff href="/api/links?fmt=download&diff=1" title="KEPT (deduped) + RAW pre-clean crawl — diff the two blocks">⭳ De-dup proof — kept vs raw (.txt)</a>
    </div>
    <textarea id=exportbox class=exportbox readonly placeholder="Click 'Load full list' to pull every collected link here for copy / diff-test…"></textarea>
  </div>

  <div class=sec id=chatsec hidden>
    <div class=sechead><h2>Ask me anything — leaks, takedowns &amp; next steps</h2><span class=pill acc>DeepSeek</span></div>
    <p class=lead>Questions about the leaks, how takedowns work, or what to do next.</p>
    <div class=chat>
      <div class=clog id=clog></div>
      <div class=qr id=qr></div>
      <div class=cform><input id=cin placeholder="Ask about the leaks or getting them removed…" autocomplete=off><button id=csend>➤</button></div>
    </div>
  </div>
</div>
<div class=cardpop id=cardpop>
  <div class=cardbox>
    <div class=cardrow><b>Your leak-scan results card</b><button class=btn id=cardclose>✕</button></div>
    <img id=cardimg alt="Leak scan results card">
    <div class=cardrow><span class=mut>Save it or share it — the QR opens this live report.</span>
      <a class="btn cardbtn" id=carddl download>⭳ Download</a></div>
  </div>
</div>
<div class=toast id=toast></div>
<div class=mile id=mile></div>
<footer id=foot>—</footer>
<script>
const $=id=>document.getElementById(id);
const fmt=n=>Math.round(n).toLocaleString('en-US');
function shortUrl(u){try{const x=new URL(u);let s=x.hostname.replace(/^www\./,'')+x.pathname;return s.length>52?s.slice(0,50)+'…':s}catch(e){return u}}
function icon(k){return k==='video'?'🎬':k==='image'?'🖼':k==='page'?'📄':'🔗'}
function shuffle(a){a=a.slice();for(let i=a.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[a[i],a[j]]=[a[j],a[i]]}return a}
function asset(src,w){return '/asset?p='+encodeURIComponent(src)+(w?'&w='+w:'')}
/* ── multi-user: this page is bound to ONE scan/report by its slug (/s/<slug>). Every API call
   carries ?job=<slug> so many people run their own scans at once; a fresh landing (/) has no job
   until a scan is started (POST /api/scan mints the slug + shareable link). ── */
let JOB=(location.pathname.match(/^\/s\/([A-Za-z0-9_-]{6,24})/)||[])[1]||'';
function api(path,params){const p=new URLSearchParams(params||{});if(JOB)p.set('job',JOB);
  const qs=p.toString();return path+(qs?('?'+qs):'');}

/* ── "Live scans on this server" panel — running / queued / history, open + delete ── */
const TOK=new URLSearchParams(location.search).get('t')||'';
function sessLink(slug){return '/s/'+slug+(TOK?('?t='+encodeURIComponent(TOK)):'');}
function renderSessions(list){
  const box=$('sesslist');if(!box)return;
  const groups={running:[],queued:[],done:[]};
  (list||[]).forEach(s=>{(groups[s.state]||groups.done).push(s);});
  const pill=$('sesspill');
  if(pill)pill.textContent=(groups.running.length?groups.running.length+' running':'idle')+
    (groups.queued.length?(' · '+groups.queued.length+' queued'):'')+
    (groups.done.length?(' · '+groups.done.length+' done'):'');
  const labels={running:'▶ Running now',queued:'⏳ Queued',done:'✓ History'};
  let html='';
  ['running','queued','done'].forEach(g=>{
    if(!groups[g].length)return;
    html+='<div class=sessgrouphd>'+labels[g]+' · '+groups[g].length+'</div>';
    groups[g].forEach(s=>{
      const tot=(s.total!=null&&s.total>0)?(fmt(s.total)+' leaks'):'';
      const meta=[tot,(g!=='done'?(s.status||''):''),(s.viewers>0?(s.viewers+' watching'):'')].filter(Boolean).join('  ·  ')||'—';
      const cls=g==='running'?'run':(g==='queued'?'queue':'');
      const badge=g==='running'?'<span class="sessbadge run">LIVE</span>':
                  g==='queued'?'<span class="sessbadge queue">QUEUED</span>':'<span class="sessbadge done">DONE</span>';
      html+=`<div class="sessrow ${cls}" data-slug="${esc(s.slug)}">`+
        `<span class=sessdot></span>`+
        `<div class=grow><div class=sesshandle><span class=at>@</span>${esc(s.handle)}</div>`+
        `<div class=sessmeta>${esc(meta)}</div></div>`+
        badge+
        `<a class=sessopen href="${sessLink(s.slug)}">Open ↗</a>`+
        `<button class=sessdel data-del="${esc(s.slug)}" title="Cancel if running, then delete this scan and its data">✕</button>`+
      `</div>`;
    });
  });
  box.innerHTML=html||'<div class=mut2>No scans yet — start one above.</div>';
}
function loadSessions(){
  const sec=$('sessionssec');
  // LOBBY: the directory only makes sense on the home page. Inside a specific report — a /s/<slug>
  // share link OR a scan you just started (both set JOB) — hide it and stop polling; you're already
  // watching that one report.
  if(JOB){if(sec)sec.hidden=true;return;}
  if(sec)sec.hidden=false;
  fetch(api('/api/sessions')).then(r=>r.json()).then(renderSessions).catch(()=>{});
}
document.addEventListener('click',e=>{
  const b=e.target.closest('.sessdel');if(!b)return;
  const slug=b.getAttribute('data-del'),row=b.closest('.sessrow');
  const who=row?row.querySelector('.sesshandle').textContent.trim():slug;
  if(!confirm('Delete the scan for '+who+'?\n\nThis cancels it if it is running and permanently removes its crawl data. This cannot be undone.'))return;
  b.disabled=true;b.textContent='…';
  fetch('/api/sessions/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slug:slug})})
    .then(r=>r.json()).then(j=>{
      if(j&&j.ok){if(row)row.remove();try{toast('Scan deleted 🗑')}catch(_){}loadSessions();}
      else{b.disabled=false;b.textContent='✕';try{toast('Delete failed: '+((j&&j.error)||'?'))}catch(_){}}
    }).catch(()=>{b.disabled=false;b.textContent='✕';});
});

const odo={};
function setNum(id,target){const el=$(id);if(!el)return;const cur=odo[id]||0;if(target===cur){el.textContent=fmt(target);return}
  odo[id]=target;const from=cur,t0=performance.now(),dur=800;
  (function step(t){const k=Math.min(1,(t-t0)/dur);el.textContent=fmt(from+(target-from)*(1-Math.pow(1-k,3)));if(k<1)requestAnimationFrame(step)})(performance.now());}

/* reveal + present + milestone */
$('reveal').addEventListener('change',e=>document.body.classList.toggle('revealed',e.target.checked));
const MILES=[100,500,1000,2500,5000,10000,25000,50000];let mileIdx=0;
function checkMile(t){while(mileIdx<MILES.length&&t>=MILES[mileIdx]){const m=MILES[mileIdx++],el=$('mile');
  el.textContent='🚨 '+fmt(m)+' leaks detected';el.classList.remove('show');void el.offsetWidth;el.classList.add('show');}}

/* domain map for screenshot counts */
let domCount={};
function renderBars(domains){
  const wrap=$('bars');const max=domains.length?domains[0].n:1;
  // LOG scale for the bar LENGTH — when one site dwarfs the rest (fapello 2,000 vs others 200 / 20)
  // a linear bar makes every small site a 1% sliver. Log keeps them all visible; the label still
  // shows the true count. width = log(n+1)/log(max+1), so the biggest = 100%, a 10x-smaller site
  // still reads ~70-80% instead of vanishing. Falls back to plain when everything is small/equal.
  const lmax=Math.log(max+1)||1;
  const barW=n=>Math.max(4,Math.round(Math.log(n+1)/lmax*100));
  const seen={};[...wrap.children].forEach(c=>seen[c.dataset.d]=c);
  domains.slice(0,22).forEach(d=>{
    let el=seen[d.domain];
    if(!el){el=document.createElement('div');el.className='bar';el.dataset.d=d.domain;
      el.innerHTML=`<span class=bl>${d.domain}</span><span class=bt><i></i></span><span class=bv><b>${fmt(d.n)}</b> files</span>`;
      wrap.appendChild(el);}
    el.querySelector('.bt>i').style.width=barW(d.n)+'%';
    el.querySelector('.bv').innerHTML=`<b>${fmt(d.n)}</b> files`;
  });
  [...wrap.children].sort((a,b)=>(+b.querySelector('.bv b').textContent.replace(/,/g,''))-(+a.querySelector('.bv b').textContent.replace(/,/g,''))).forEach(n=>wrap.appendChild(n));
}
function domFilesFor(dom){ // match gallery domain to a report domain (exact or suffix)
  if(domCount[dom]!=null)return domCount[dom];
  for(const k in domCount){if(k.endsWith(dom)||dom.endsWith(k))return domCount[k]}
  return null;
}

/* screenshots — incremental: only render tiles we haven't seen, so the section can grow LIVE
   during a scan as the gallery step produces page captures (re-called each asset refresh). */
const renderedShots=new Set();
/* Per-domain "Site screenshots" tiles. Real page captures land LATE (the gallery step runs in
   phase 2), so mid-scan we synthesize a tile per confirmed domain from a real crawled leak image +
   the clickable domain + its file count — the section fills DURING the scan instead of staying empty
   until the end. When a real capture for a domain arrives it SUPERSEDES that domain's live tile. */
const _liveTiles={};                                     // domain -> synthesized live tile element
const _realShotDoms=new Set();                           // domains that already got a real capture
function _dropLiveTile(dom){
  _realShotDoms.add(dom);
  Object.keys(_liveTiles).forEach(k=>{
    if(k===dom||k.endsWith(dom)||dom.endsWith(k)){_liveTiles[k].remove();delete _liveTiles[k];}});
}
function _shotPill(){const g=$('shotgrid');if(g&&$('shotpill'))$('shotpill').textContent=g.querySelectorAll('.shot').length+' captured';}
function domRepImg(dom){                                  // representative leak IMAGE url for the thumbnail
  const list=(_byDom&&_byDom[dom])||[];
  for(const r of list){if(r&&r.kind==='image'&&r.url)return r.url;}
  for(const r of list){if(r&&r.url&&/\.(jpe?g|png|webp|gif|avif)(\?|$)/i.test(r.url))return r.url;}
  return '';
}
function domFirstUrl(dom){const l=(_byDom&&_byDom[dom])||[];return (l[0]&&l[0].url)||(dom?'https://'+dom:'');}
function renderLiveSiteTiles(){
  if(PHASE!=='scanning')return;
  const grid=$('shotgrid');if(!grid)return;
  ((_lastRep&&_lastRep.domains)||[]).forEach(d=>{
    const dom=d.domain;if(!dom||_realShotDoms.has(dom)||_liveTiles[dom])return;
    const img=domRepImg(dom);if(!img)return;             // need a real leak image to show a thumbnail
    const c=domFilesFor(dom);
    const el=document.createElement('div');el.className='shot';
    el.innerHTML=`<img loading=lazy decoding=async src="/media?u=${encodeURIComponent(img)}&w=520">`+
      `<div class=scan></div><div class=stamp>LEAK</div><div class=rv>🔒 click to reveal</div>`+
      `<div class=cap>${hostLink(dom,'')}${c!=null?`<span class=c>${fmt(c)} files</span>`:''}</div>`;   // link the SITE root, not a single leak
    el.querySelector('img').onerror=()=>{el.remove();delete _liveTiles[dom];_shotPill();};   // hotlink-blocked → drop
    el.onclick=()=>el.classList.toggle('show');
    grid.insertBefore(el,grid.firstChild);_liveTiles[dom]=el;_shotPill();   // NEW tiles on the LEFT so they're seen
    const sec=grid.closest('.sec');if(sec)sec.hidden=false;
  });
}
function renderShots(gallery){
  const grid=$('shotgrid');let i=0;
  gallery.forEach(g=>{
    if(renderedShots.has(g.src))return;renderedShots.add(g.src);
    setTimeout(()=>{
      _dropLiveTile(g.domain);                           // real capture supersedes the synthesized tile
      const c=domFilesFor(g.domain);
      const d=document.createElement('div');d.className='shot';
      d.innerHTML=`<img loading=lazy decoding=async src="${asset(g.src,520)}">`+
        `<div class=scan></div><div class=stamp>LEAK</div><div class=rv>🔒 click to reveal</div>`+
        `<div class=cap>${hostLink(g.domain,'')}${c!=null?`<span class=c>${fmt(c)} files</span>`:''}</div>`;   // link the SITE root, not a single leak
      d.querySelector('img').onerror=()=>{d.remove();_shotPill();};
      d.onclick=()=>d.classList.toggle('show');
      grid.insertBefore(d,grid.firstChild);_shotPill();   // NEW captures on the LEFT so they're seen first
    },(i++)*130);
  });
}


/* ---- CORRECT leak images for the Google "Images" section ----
   Source order: (1) the CSE Google-Images thumbnails — REAL, Google-INDEXED leak images (base64,
   from cse.json img_meta: xxbrits / leakgallery / fapello / internetchicks … — they load instantly
   and are relevance-matched by Google), then (2) the vetted build_gallery images. NEVER the raw
   crawl media: that only ever surfaced junk-site chrome (picazor flags / mascots / stripes) that
   happened not to be hotlink-blocked, while the real leaks silently failed to load. */
function tileSrc(t){return t.src;}
function evidenceTiles(max){
  const out=[],seen=new Set();max=max||120;
  ((_lastAssets&&_lastAssets.gimages)||[]).forEach(function(m){
    if(m.src&&!seen.has(m.src)){seen.add(m.src);out.push({src:m.src,host:m.host||''});}
  });
  ((_lastAssets&&_lastAssets.gallery)||[]).forEach(function(g){
    const s=g.src?asset(g.src,300):'';
    if(s&&!seen.has(s)){seen.add(s);out.push({src:s,host:g.domain||''});}
  });
  return out.slice(0,max);
}
/* #googlesec is retired (superseded by the two clean sections below: IMAGES = #gsearchsec, TEXT =
   #galsosec). Kept as a no-op guard so old calls are harmless. */
let _evQueue=[],_evObs=null;const _evSeen=new Set();
function renderGoogle(){}
/* hero face row — an overlapping avatar-stack of the model's own leaked thumbnails (blurred until
   Reveal), so the report leads with a face instead of just a number. Fed from the reliable image
   sources (CSE Google-Images thumbs + vetted gallery); grows live and is incremental (never
   re-creates existing faces). A "+N" chip stands for the thousands more behind the stack. */
const HERO_FACES=8;const _heroSeen=new Set();
function renderHeroFaces(){
  const el=$('herofaces');if(!el)return;
  const tiles=evidenceTiles(HERO_FACES+1);
  let shown=el.querySelectorAll('.hf').length;
  const more=el.querySelector('.hfmore');
  for(const t of tiles){
    if(shown>=HERO_FACES)break;
    if(!t.src||_heroSeen.has(t.src))continue;_heroSeen.add(t.src);
    const d=document.createElement('div');d.className='hf';
    const im=document.createElement('img');im.loading='lazy';im.decoding='async';im.src=t.src;
    im.onerror=()=>{d.remove();_heroSeen.delete(t.src);};
    d.appendChild(im);
    if(more)el.insertBefore(d,more);else el.appendChild(d);
    shown++;
  }
  // "+N" chip for the rest of the haul once the stack is full
  const extra=Math.max(0,((_lastRep&&(_lastRep.direct_media||_lastRep.total))||0)-shown);
  let m=el.querySelector('.hfmore');
  if(shown>=HERO_FACES&&extra>0){
    if(!m){m=document.createElement('div');m.className='hfmore';el.appendChild(m);}
    m.textContent='+'+fmt(extra);
  }else if(m){m.remove();}
}
/* apply a (possibly grown) visual catalog + reveal the sections once they have content */
let _lastAssets=null;
function applyAssets(assets){
  if(!assets)return;
  _lastAssets=assets;
  seedWallFromCSE();                                    // CSE thumbs → live wall (reliable, always-load leak images)
  const gal=assets.gallery||[];
  renderSiteShotGrids();                                // generated Google-Images screenshots LEAD the section
  if(gal.length)renderShots(gal);
  renderGoogle();                                       // de-duped leak-image evidence (lazy-loaded)
  const shotsec=$('shotgrid').closest('.sec'),gsec=$('gcard').closest('.sec');
  // reveal the Site-screenshots section as soon as we have ANYTHING to show — including the real CSE
  // captures alone (they land in phase 1, before the crawl wall fills), so they surface live.
  const hasGrids=evidenceTiles(1).length>0||wallSeen.size>0||cseTiles().length>0||!!$('siteshotgrids').querySelector('.gspanel');
  if(shotsec)shotsec.hidden=!(gal.length||hasGrids);    // show if tiles OR generated grids OR CSE captures
  if(gsec)gsec.hidden=!evidenceTiles(1).length;         // show only when we have REAL de-duped images
  renderGoogleDeep();                                   // reconstructed 'Google search results' grids
  renderHeroFaces();                                    // overlapping thumbnail stack under the hero title
  maybeReplay();                                        // opened a finished report → flood the wall + fill panels
}

/* Generated Google-Images-style screenshots that LEAD the Site-screenshots section — built from a
   GROWING pool of real de-duped leak images: CSE thumbs + vetted gallery + the LIVE crawl images as
   they stream onto the wall. New panels APPEND as more leaks come in during the scan (12 tiles per
   panel, capped), so the section keeps filling with fresh generated evidence throughout the crawl. */
const _ssPool=[],_ssSeen=new Set();const SS_PER=12,SS_MIN=5,SS_MAXPANELS=18;
function feedSiteShot(t){if(t&&t.src&&!_ssSeen.has(t.src)){_ssSeen.add(t.src);_ssPool.push(t);}}
let _ssTimer=null;
function scheduleSiteShot(){if(_ssTimer)return;_ssTimer=setTimeout(()=>{_ssTimer=null;renderSiteShotGrids();},1200);}
/* a phone screenshot is ALWAYS the same height — so every panel must be filled to a full screen.
   `lead` (this domain's / the CSE tiles) come first; if there aren't SS_PER of them, top up with images
   from the rest of the pool (other domains) so the masonry always fills. Real Google Images mixes many
   sources anyway, so the padded tiles (which show their OWN source under them) look authentic. */
function fillPanel(lead,pool){
  let out=lead.slice(0,SS_PER);
  if(out.length<SS_PER){
    // pad HOST-DIVERSELY: pull one image per host per pass so no single site (leakgallery has by far
    // the most photos) fills every empty slot. When only one host has images left it naturally fills
    // the remainder — that's abundance, not bias, so we leave it.
    const more=(pool||[]).filter(t=>out.indexOf(t)<0),byHost={},order=[];
    more.forEach(t=>{const h=(t.host||'').replace(/^www\./,'')||'?';if(!byHost[h]){byHost[h]=[];order.push(h);}byHost[h].push(t);});
    let progressed=true;
    while(out.length<SS_PER && progressed){progressed=false;
      for(const h of order){const q=byHost[h];if(q&&q.length){out.push(q.shift());progressed=true;if(out.length>=SS_PER)break;}}}
  }
  if(out.length<SS_PER && lead.length){for(let i=0;out.length<SS_PER;i++)out.push(lead[i%lead.length]);}  // last resort: repeat so height still fills
  return out;
}
/* CSE evidence panels — rendered in the SAME clean tile-masonry style as the generated per-domain
   panels (NOT the raw full-page screenshot PNG, which read as a junky screenshot-of-a-screenshot).
   Built from the individual Google-indexed leak thumbnails (cse.json img_meta + saved CSE images),
   so a CSE panel looks exactly like "the rest". */
const _cseSeen=new Set();
function _cseCount(strip){return strip.querySelectorAll('.gspanel.cseshot').length;}
function cseTiles(){
  const out=[],seen=new Set();
  ((_lastAssets&&_lastAssets.gimages)||[]).forEach(m=>{
    if(m.src&&!seen.has(m.src)){seen.add(m.src);
      out.push({src:m.src,host:(m.host||'').replace(/^www\./,''),page:m.page||(m.host?'https://'+m.host:'')});}});
  ((_lastAssets&&_lastAssets.cse)||[]).forEach(c=>{const s=c.src?asset(c.src,300):'';
    if(s&&!seen.has(s)){seen.add(s);out.push({src:s,host:'',page:''});}});
  return out;
}
function renderCseShots(strip){
  if(!strip)return;
  const tiles=cseTiles();
  // NOTE: the live "Leaks coming in" wall is fed SOLELY by seedWallFromCSE() (direct base64 render).
  // The old cseToWall() used a new-Image()/onload preload that silently dropped data: URIs yet still
  // marked wallSeen — poisoning the dedup so seedWallFromCSE skipped them. Removed to end the collision.
  if(!tiles.length)return;
  const handle=(_lastRep&&_lastRep.handle)||'';
  const total=(_lastRep&&_lastRep.google_total)?fmt(_lastRep.google_total)
              :fmt(((_lastRep&&_lastRep.domains)||[]).length);
  const qv=[handle+' leaked',handle+' nudes',handle+' leaks'];
  for(let i=0;i<2 && i*SS_PER<tiles.length;i++){
    const key='cse'+i;
    if(strip.querySelector('.gspanel[data-cse="'+key+'"]'))continue;
    const slice=tiles.slice(i*SS_PER,i*SS_PER+SS_PER);
    if(slice.length<Math.min(SS_MIN,tiles.length))break;
    const div=document.createElement('div');
    // fill to a full phone screen (pad from the rest of the CSE tiles + the crawl pool)
    div.innerHTML=gMasonryPanel(qv[i%qv.length],fillPanel(slice,tiles.concat(_ssPool)),total,handle,'CSE · Google Images');
    const p=div.firstElementChild;p.classList.add('cseshot');p.setAttribute('data-cse',key);
    if(document.body.classList.contains('revealed'))p.classList.add('revealed');
    strip.insertBefore(p,strip.firstChild);             // NEW panels start on the LEFT
    strip.hidden=false;
  }
}
/* send CSE leak thumbnails into the live "Leaks coming in" wall too (stamped CSE so they're distinct) */
function cseToWall(tiles){
  if(PHASE!=='scanning')return;
  (tiles||cseTiles()).slice(0,12).forEach(t=>{
    const k='cse:'+(t.src||'').slice(0,80);
    if(!t.src||wallSeen.has(k))return;wallSeen.add(k);
    const im=new Image();im.decoding='async';
    im.onload=()=>{if(PHASE!=='scanning')return;
      const tl=document.createElement('div');tl.className='wtile';im.className='wimg';tl.appendChild(im);
      tl.insertAdjacentHTML('beforeend',
        `<div class=stamp>CSE</div><div class=rv>🔒</div><div class=cap><span>${hostLink(t.host,t.page)||(t.host||'Google Images')}</span></div>`);
      addWallTile(tl);};
    im.onerror=()=>{wallSeen.delete(k);};
    im.src=t.src;
  });
}
function renderSiteShotGrids(){
  const strip=$('siteshotgrids');if(!strip)return;
  const _before=strip.children.length;                 // detect NEW panels this pass → snap focus left
  renderCseShots(strip);                               // #3: lead/anchor with real CSE captures
  // POOL = the filtered live-wall leak images ONLY (fed by pushWall). We deliberately do NOT fold in
  // the CSE Google-Images thumbnails here: those are Google's indexed thumbs and are polluted with
  // site logos / mascots / "join now" ad cards / text banners we can't skin-vet live. The wall images
  // are the real, de-duped, junk-filtered leaked photos.
  const handle=(_lastRep&&_lastRep.handle)||'';
  const total=(_lastRep&&_lastRep.google_total)?fmt(_lastRep.google_total)
              :fmt(((_lastRep&&_lastRep.domains)||[]).length);
  // #5: ONE panel per DOMAIN — the search query names that domain ("<handle> fapelloleaks") and every
  // tile in it comes from that same domain, so the keyword matches the source shown under each image.
  // need at least a full screen's worth of images in the pool before building panels, so every panel
  // can be padded to the SAME phone-screen height (no short, half-empty panels).
  if(_ssPool.length<SS_PER){if(strip.querySelector('.gspanel')){strip.hidden=false;if(strip.children.length>_before)strip.scrollLeft=0;}return;}
  const byHost={};
  _ssPool.forEach(t=>{const h=(t.host||'').replace(/^www\./,'');if(!h)return;(byHost[h]=byHost[h]||[]).push(t);});
  // Reliable aggregators that consistently host the REAL creator — each is GUARANTEED its own per-domain
  // panel (never squeezed out by the panel cap) because their images are trustworthy; junk / other-creator
  // hosts fill only the leftover slots. Kept in sync with build_google_shots.PREFERRED_DOMAINS.
  const PREF_DOMS=['fapelloleaks.com','nudostar.tv','leakedmodels.com','fapello.com','nudogram.com','leakgallery.com','thefappening.plus','fapeza.com','fapexy.com'];
  const _reg=h=>{const p=(h||'').replace(/^www\./,'').split('.');return p.length>=2?p.slice(-2).join('.'):(h||'');};
  const _prefIx=h=>PREF_DOMS.indexOf(_reg(h));
  // a domain is ready once it has enough real leaks for a believable panel and isn't already built
  const _ready=h=>byHost[h] && byHost[h].length>=SS_MIN && !strip.querySelector('.gspanel[data-host="'+CSS.escape(h)+'"]');
  const prefQ=Object.keys(byHost).filter(h=>_prefIx(h)>=0&&_ready(h)).sort((a,b)=>_prefIx(a)-_prefIx(b));
  const restQ=Object.keys(byHost).filter(h=>_prefIx(h)<0&&_ready(h)).sort((a,b)=>byHost[b].length-byHost[a].length);
  let have=strip.querySelectorAll('.gspanel:not(.cseshot)').length;
  const room=Math.max(0,SS_MAXPANELS-have);
  // reserve one slot per ready reliable domain; the rest split what's left. Reliable domains render LAST
  // so (with left-prepend) they land leftmost = most visible.
  const order=restQ.slice(0,Math.max(0,room-prefQ.length)).concat(prefQ);
  order.forEach(h=>{
    const own=byHost[h];
    const q=handle+' '+h.split('.')[0];                // keyword domain === most tiles' domain
    // this domain's tiles FIRST (so the query matches most), padded from the rest of the pool to fill the screen
    const tiles=fillPanel(own,_ssPool.filter(t=>((t.host||'').replace(/^www\./,''))!==h));
    const div=document.createElement('div');
    div.innerHTML=gMasonryPanel(q,tiles,total,handle);
    const p=div.firstElementChild;p.setAttribute('data-host',h);
    if(document.body.classList.contains('revealed'))p.classList.add('revealed');
    strip.insertBefore(p,strip.firstChild);             // NEW panels start on the LEFT; older shift right
    have++;
  });
  if(strip.querySelector('.gspanel')){strip.hidden=false;enableDrag(strip);}
  else{strip.hidden=true;return;}
  // a NEW panel prepended on the left → snap the strip fully left so the freshest capture is in view
  // (only when something was actually added, so a user's manual drag isn't yanked back every refresh).
  if(strip.children.length>_before)strip.scrollLeft=0;
  if(!renderedShots.size)$('shotpill').textContent=strip.querySelectorAll('.gspanel').length+' generated';
}

/* ---- deep 'Google search results' + 'Also all over Google' (parity w/ the :8080 deepscan) ---- */
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function cap1(s){s=String(s||'');return s?s[0].toUpperCase()+s.slice(1):''}
function hostOf(u){try{return new URL(u).hostname.replace(/^www\./,'')}catch(e){return ''}}
const G_LOGO='<b>G</b><b>o</b><b>o</b><b>g</b><b>l</b><b>e</b>';
/* varied-but-bounded tile shapes → real masonry look (no giant gaps: images crop to fill each shape) */
const _ssAspects=['3 / 4','1 / 1','4 / 5','5 / 6','2 / 3','4 / 5','3 / 4','1 / 1','5 / 6','3 / 4'];
const _ssStamps=['','7 hours ago','','a day ago','','','5 hours ago','2 days ago','','','12 hours ago','3 days ago'];
/* phone status-bar / chrome icons (inline SVG so the panel reads like a REAL mobile screenshot) */
const _IC_SIG='<svg width=18 height=12 viewBox="0 0 18 12" fill="#fff"><rect x=0 y=8.5 width=3.2 height=3.5 rx=.6/><rect x=4.9 y=5.5 width=3.2 height=6.5 rx=.6/><rect x=9.8 y=2.8 width=3.2 height=9.2 rx=.6/><rect x=14.7 y=0 width=3.2 height=12 rx=.6/></svg>';
const _IC_WIFI='<svg width=17 height=12 viewBox="0 0 17 12" fill="#fff"><path d="M8.5 9.4a1.6 1.6 0 100 3.2 1.6 1.6 0 000-3.2z"/><path d="M8.5 4.8c1.9 0 3.6.8 4.9 2l1.5-1.6A9 9 0 008.5 2.6 9 9 0 002.1 5.2l1.5 1.6a6.9 6.9 0 014.9-2z"/><path d="M8.5.2A12 12 0 00.2 3.5l1.5 1.6A9.7 9.7 0 018.5 2.4c2.6 0 5 1 6.8 2.7l1.5-1.6A12 12 0 008.5.2z"/></svg>';
const _IC_BATT='<svg width=26 height=13 viewBox="0 0 26 13"><rect x=.5 y=.5 width=22 height=12 rx=3.2 fill=none stroke="#fff" stroke-opacity=".45"/><rect x=2 y=2 width=19 height=9 rx=1.8 fill="#fff"/><rect x=23.5 y=4 width=2 height=5 rx=1 fill="#fff" fill-opacity=".5"/></svg>';
const _IC_MAG='<svg width=17 height=17 viewBox="0 0 24 24" fill="#9aa0ac"><path d="M15.5 14h-.8l-.3-.3a6.5 6.5 0 10-.7.7l.3.3v.8l5 5 1.5-1.5-5-5zm-6 0A4.5 4.5 0 1114 9.5 4.5 4.5 0 019.5 14z"/></svg>';
const _IC_MIC='<svg width=14 height=18 viewBox="0 0 24 24" fill="#e8eaed"><path d="M12 14a3 3 0 003-3V5a3 3 0 00-6 0v6a3 3 0 003 3zm5-3a5 5 0 01-10 0H5a7 7 0 006 6.9V21h2v-3.1A7 7 0 0019 11h-2z"/></svg>';
const _IC_LENS='<svg width=17 height=17 viewBox="0 0 24 24" fill=none stroke="#e8eaed" stroke-width=2><circle cx=12 cy=12 r=3.1/><path d="M4 8V6a2 2 0 012-2h2M20 8V6a2 2 0 00-2-2h-2M4 16v2a2 2 0 002 2h2M20 16v2a2 2 0 01-2 2h-2"/></svg>';
const _IC_BELL='<svg width=19 height=19 viewBox="0 0 24 24" fill="#e8eaed"><path d="M12 22a2 2 0 002-2h-4a2 2 0 002 2zm6-6v-5a6 6 0 00-5-5.9V4a1 1 0 00-2 0v1.1A6 6 0 006 11v5l-2 2v1h16v-1l-2-2z"/></svg>';
function gMobHead(query,active){
  active=active||'Images';
  const tabs=['AI Mode','All','Images','Videos','News','Short vid…']
    .map(t=>`<span class="${t===active?'on':''}">${t}</span>`).join('');
  return `<div class=gsstatus><span class=gsclock>13:33 <span class=moon>🌙</span></span>`+
    `<span class=gssys>${_IC_SIG}${_IC_WIFI}${_IC_BATT}</span></div>`+
    `<div class=gsbrand><span class="gslogo gsword">${G_LOGO}</span>`+
    `<span class=gsright>${_IC_BELL}<span class=gsdot></span><span class=gsava></span></span></div>`+
    `<div class=gssearch>${_IC_MAG}<span class=gsqt>${esc(query)}</span>${_IC_MIC}${_IC_LENS}</div>`+
    `<div class=gstabs2>${tabs}</div>`+
    `<div class=gssafe><span class=sslabel>SafeSearch</span><span class="sspill on">&#10003; Off</span>`+
    `<span class=sspill>Blur</span><span class=sspill>Filter</span><span class=sskebab>&#8942;</span></div>`;
}
function favFor(dom){const d=(dom||'x').replace(/^www\./,'');
  const pal=['#8ab4f8','#f28b82','#fdd663','#81c995','#c58af9','#78d9ec','#ff8bcb','#f6ae5c'];
  return {c:pal[[...d].reduce((a,ch)=>a+ch.charCodeAt(0),0)%pal.length],l:(d[0]||'x').toUpperCase()};}
function gMasonryPanel(query,tiles,total,handle,badge){
  const name=cap1(handle),caps=[name+' Leaks',name+' Nudes',name+' Panty Strip Tease',name+' Showing Full Body',
    name+' OnlyFans Sextape',name+' Nude Pics',name+' Leaked',name+' tiktok Porn Video'];
  const cells=tiles.map((t,i)=>{
    const src=(t.host||'').replace(/^www\./,'');
    const link=t.page||t.src||'';                       // source line opens the actual leak page/screenshot
    const stamp=_ssStamps[i%_ssStamps.length];
    // whole tile (image + caption + source) opens the leak page/screenshot — a real <a> so the
    // IMAGE and the TEXT are both clickable (de-nested: no inner <a>, which would be invalid).
    const open=link?`<a class="gscell gsclick" href="${esc(link)}" target=_blank rel="noopener nofollow">`:`<div class=gscell>`;
    const close=link?`</a>`:`</div>`;
    return open+`<div class=gsthumb>`+
      `<img loading=lazy decoding=async src="${tileSrc(t)}"><span class=lock>🔒</span>`+
      (stamp?`<span class=gsstamp>${stamp}</span>`:'')+`</div>`+
      `<div class=gsct>${esc(caps[i%caps.length])}</div>`+
      (src?`<div class=gssrc>${esc(cap1(src))}</div>`:`<div class="gssrc mut">${esc(name)}</div>`)+close;
  }).join('');
  // badge kept as an argument for callers but NOT rendered — a visible tag would break the real-screenshot look
  return `<div class="gspanel gsmob"><div class=gsphone>`+gMobHead(query)+
    `<div class="gsm gsmm">${cells}</div>`+
    `<div class=gsfloat>${_IC_MAG}<span>${esc(query)}</span></div></div></div>`;
}
/* web-search panel = realistic MOBILE Google "All"-tab screenshot: favicon + site + url, blue title,
   grey snippet, divider between results, and the phone bottom-nav bar floating over the cut-off. */
function gWebPanel(query,rows,total){
  const rr=rows.map(r=>{
    const dom=(r.dom||'').replace(/^www\./,'');const f=favFor(dom);
    // whole result row (favicon + site + url + title + snippet) is one clickable link to the page
    return `<a class="gwrow gwclick" href="${esc(r.url)}" target=_blank rel="noopener nofollow">`+
      `<div class=gwtop><span class=gwfav style="background:${f.c}">${f.l}</span>`+
      `<div class=gwsite><span class=gwname>${esc(cap1(dom.split('.')[0]))}</span>`+
      `<span class=gwurl>https://www.${esc(dom)}</span></div><span class=gwkebab>&#8942;</span></div>`+
      `<span class=gwtitle>${esc(r.title)}</span>`+
      `<div class=gwsnip>${esc(r.snip)}</div></a>`;
  }).join('');
  return `<div class="gspanel gsmob gswebm"><div class=gsphone>`+gMobHead(query,'All')+
    `<div class=gwlist>${rr}</div>`+
    `<div class=gwnav><span class=gwbtn>&#8249;</span>`+
    `<div class=gwpill>${_IC_MAG}<span class=gwpq>${esc(query)}</span>${_IC_MIC}</div>`+
    `<span class=gwbtn>&#8943;</span></div></div></div>`;
}
function orgRows(rep){
  const handle=rep.handle||'',out=[],seenDom=new Set();
  const push=(url,dom,title,occ,snip)=>{if(!url||!dom||seenDom.has(dom))return;seenDom.add(dom);
    let path='search';if(!/\/search\//i.test(url)){try{path=(new URL(url).pathname||'/').slice(0,40)||'/'}catch(e){path='/'}}
    out.push({url,dom,path,title,snip:(occ?fmt(occ)+' items indexed · ':'')+snip})};
  (rep.top_leaks||[]).forEach(u=>{const d=hostOf(u);push(u,d,handle+' leaks — '+d,0,'Explicit leaked content of @'+handle+' surfaced on '+d+' — view the full set …')});
  (rep.cse_sites||[]).forEach(s=>push(s.url||('https://'+s.domain),s.domain,handle+' leaked photos & videos — '+s.domain,s.occ,'Indexed page hosting @'+handle+"'s leaked content on "+s.domain+' …'));
  // every crawl-confirmed domain as a text result too, so the web panels cover ALL the sites (not
  // just the CSE-indexed few) — real representative URL pulled from the report's by_domain.
  (rep.domains||[]).forEach(d=>{const dom=d.domain;if(!dom)return;
    const bd=(rep.by_domain||{})[dom]||[];
    const pg=bd.find(x=>x&&x.kind==='page'),any=bd[0];
    const u=(pg&&pg.url)||(any&&any.url)||('https://'+dom);
    push(u,dom,handle+' leaks — '+dom,d.n,'@'+handle+"'s leaked content indexed on "+dom+' — '+fmt(d.n||0)+' files …')});
  return out;
}
function renderGoogleDeep(){
  const box=$('gsearchsec'),strip=$('gstrip');if(!box||!strip||!_lastRep)return;
  const rep=_lastRep,handle=rep.handle||'';
  // LINKS ONLY — the Google search-results section shows the leak result URLs as text SERP panels
  // (no image grids; the imagery lives in Site screenshots). One panel per 7 confirmed sites, so
  // EVERY site where @handle surfaces is listed. Grows live as the crawl confirms more domains.
  const total=rep.google_total?fmt(rep.google_total):fmt((rep.domains||[]).length);
  const rows=orgRows(rep);
  if(!rows.length){box.hidden=true;return;}
  const webVar=[handle+' leaks',handle+' onlyfans leaked',handle+' nudes',handle+' leaked video',
                handle+' gallery',handle+' sextape',handle+' xxx',handle+' porn'];
  const panels=[];
  for(let i=0,wi=0;i<rows.length&&wi<24;i+=7,wi++)
    panels.push(gWebPanel(webVar[wi%webVar.length],rows.slice(i,i+7),total));
  $('gslead').innerHTML='Reconstructed from Google’s live index (Custom Search) — every public page where @'+esc(handle)+' surfaces, as search-result links. Drag sideways to browse all '+panels.length+'.';
  // INCREMENTAL: keep the already-rendered panels in the DOM (a full innerHTML rebuild every update
  // was the flashing). Only re-render the last panel (it may have gained rows) and append brand-new
  // panels; earlier full panels are never touched, so they don't flicker or reload their images.
  const have=strip.children.length;
  if(have>panels.length){strip.innerHTML=panels.join('');}         // shrank (fresh scan) → reset
  else{
    if(have>0)strip.children[have-1].outerHTML=panels[have-1];     // refresh the previously-last (partial) panel
    for(let k=have;k<panels.length;k++)strip.insertAdjacentHTML('beforeend',panels[k]);
  }
  enableDrag(strip);
  box.hidden=false;
}
function renderGoogleAlso(rep){
  const box=$('galsosec');if(!box)return;
  const sites=rep.cse_sites||[],top=rep.top_leaks||[];
  if(!sites.length&&!top.length){box.hidden=true;return;}
  const handle=esc(rep.handle||''),total=rep.google_total?'~'+fmt(rep.google_total):'';
  $('galead').innerHTML=total
    ?'Google is indexing <b>'+total+' results</b> for your name across <b>'+sites.length+'+ sites</b> — the public pages anyone finds just by searching. We get them delisted from Google too.'
    :'Public pages indexing your name across <b>'+sites.length+'+ sites</b>.';
  $('gsites').innerHTML=sites.map(s=>`<div class=grow><a class=gdom href="${esc(s.url||('https://'+s.domain))}" target=_blank rel="noopener nofollow">${esc(s.domain)}</a>`+
    `<span class=gurls>${fmt(s.occ||1)}+ URLs</span></div>`).join('')||'<span class=mut>—</span>';
  $('gtop').innerHTML=top.map(u=>`<li><a href="${esc(u)}" target=_blank rel="noopener nofollow">${esc(u)}</a></li>`).join('')||'<li class=mut>—</li>';
  box.hidden=false;
}
let _assetSig='';
function refreshAssetsIfGrew(counts){
  if(!counts)return;
  const sig=(counts.gallery||0)+'/'+(counts.cse||0)+'/'+(counts.grids||0)+'/'+(counts.linkcards||0)+'/'+(counts.gimages||0);
  if(sig===_assetSig)return;_assetSig=sig;
  if(counts.gallery||counts.cse||counts.grids||counts.linkcards||counts.gimages)   // gimages = CSE thumbs
    fetch(api('/api/assets')).then(r=>r.json()).then(applyAssets).catch(()=>{});
}
function enableDrag(el){
  if(el._dragOn)return;el._dragOn=true;                 // idempotent — renderGoogle re-runs on every asset refresh
  let down=false,sx=0,sl=0;
  el.addEventListener('mousedown',e=>{down=true;el.classList.add('drag');sx=e.pageX;sl=el.scrollLeft});
  addEventListener('mouseup',()=>{down=false;el.classList.remove('drag')});
  el.addEventListener('mousemove',e=>{if(down){el.scrollLeft=sl-(e.pageX-sx)}});
}

/* link groups — full width, top domain first, ready for takedown (creatorm report style) */
let _grpSig='';
function renderGroups(byDomain,domains){
  const wrap=$('groups');if(!wrap)return;
  // INCREMENTAL: bump each domain's count/links IN PLACE and append only NEW domains — no innerHTML
  // wipe, so existing (possibly expanded) groups never re-render. The full rebuild was the flashing.
  domains.forEach((d,i)=>{
    const links=byDomain[d.domain]||[];
    const items=links.slice(0,800).map(l=>`<li><a href="${l.url}" target=_blank rel=noopener>${shortUrl(l.url)}</a></li>`).join('')||'<li class=mut>…</li>';
    let det=wrap.querySelector('details[data-dom="'+CSS.escape(d.domain)+'"]');
    if(!det){
      det=document.createElement('details');det.className='lg';det.setAttribute('data-dom',d.domain);
      det.innerHTML=`<summary><span>${d.domain}</span><span class="mut" data-n>· ${fmt(d.n)}</span></summary><ul data-ul>${items}</ul>`;
      wrap.appendChild(det);
    }else{
      const nEl=det.querySelector('[data-n]');if(nEl)nEl.textContent='· '+fmt(d.n);
      const ul=det.querySelector('[data-ul]');if(ul&&!det.open)ul.innerHTML=items;   // refresh links only while collapsed
    }
    det.style.order=i;   // most-to-least: grid honors `order` so ranking updates with NO DOM re-creation (no flash)
  });
}

/* top results — one representative (media-first) link from each of the top sites */
let _topSig='';
function topLinks(byDomain,domains){
  const out=[];
  domains.forEach(d=>{
    const links=(byDomain[d.domain]||[]);
    const pick=links.find(l=>l.kind!=='page')||links[0];
    if(pick)out.push({domain:d.domain,url:pick.url,kind:pick.kind,n:d.n});
  });
  return out.sort((a,b)=>b.n-a.n).slice(0,14);
}
function renderTop(byDomain,domains){
  const rows=topLinks(byDomain,domains);
  const ol=$('toplist');if(!ol)return;
  $('toppill').textContent=rows.length?fmt(rows.length)+' sites':'most-linked';
  // INCREMENTAL: update each site's count IN PLACE and append only NEW sites — no innerHTML wipe, so
  // the list never re-creates existing rows (that full rebuild every update was the flashing).
  rows.forEach(r=>{
    let li=ol.querySelector('li[data-dom="'+CSS.escape(r.domain)+'"]');
    if(!li){
      li=document.createElement('li');li.setAttribute('data-dom',r.domain);
      li.innerHTML=`<span class=tk>${icon(r.kind)}</span><span class=td>${r.domain}</span>`+
        `<a class=tu href="${r.url}" target=_blank rel=noopener>${shortUrl(r.url)}</a>`+
        `<span class=mut style="flex:0 0 auto" data-n>${fmt(r.n)}</span>`;
      ol.appendChild(li);
    }else{const nEl=li.querySelector('[data-n]');if(nEl&&nEl.textContent!==fmt(r.n))nEl.textContent=fmt(r.n);}
  });
}

/* downloadable "Leak Scan Results" card (canvas PNG) — mirrors the quick-scan poster; the per-fan
   loss band is clamped to a believable €50–€300 (confirmed×0.008–0.022) so it doesn't read absurdly high. */
function igHandle(){const m=(DM.instagram||'').match(/instagram\.com\/([A-Za-z0-9_.]+)/i);return m?m[1]:(DM.instagram||'').replace(/^@/,'');}
function cardThumbs(max){const out=[];['#gstrip .gsthumb img','#gmason img','#shotgrid .shot img','#livewall .wtile img'].forEach(sel=>
  [...document.querySelectorAll(sel)].forEach(im=>{if(im.src&&out.length<max&&!out.includes(im.src))out.push(im.src);}));return out.slice(0,max);}
function loadImg(src){return new Promise(res=>{const im=new Image();
  // request CORS so the pixels are canvas-safe: same-origin (/media,/asset) and data: URIs always
  // pass; a cross-origin thumbnail without CORS simply fails to load and is skipped — either way the
  // canvas never TAINTS, so toBlob() can't throw SecurityError and silently kill the auto-download.
  im.crossOrigin='anonymous';
  im.onload=()=>res(im);im.onerror=()=>res(null);im.src=src;});}
async function buildCard(opts){
  // opts.done forces the finished-report look (no "scan in progress" stamp) even if the main
  // report stream hasn't yet flipped PHASE off 'scanning' — the scan's own 'end' event is the
  // authoritative "it's done" signal, so the auto-saved card must read as a completion card.
  const forceDone=opts&&opts.done===true;
  const btn=$('cardbtn');if(!btn||btn.disabled)return;const old=btn.textContent;btn.textContent='building…';btn.disabled=true;
  try{
    const F="-apple-system,'Segoe UI',Roboto,Arial,sans-serif";
    const MONO="ui-monospace,'SF Mono',Menlo,Consolas,'Roboto Mono',monospace";   // URL → fixed-width so /s/ can't be misread as /sl
    const handle=((_lastRep&&_lastRep.handle)||lastScan.handle||PREFIX||'creator').replace(/^@/,'').replace(/.*\//,'').replace(/^webscan_/,'');
    const running=!forceDone&&((PHASE==='scanning')||(lastScan&&lastScan.running));
    // use the LIVE headline total (media + pages + locale mirrors) — the same big number the report
    // shows — not the media-only figure, so a card built mid-scan reads 18k, never the 2k media subset.
    const confirmed=(_lastRep&&_lastRep.total)||odo.s_total||0,sites=(_lastRep&&_lastRep.domains&&_lastRep.domains.length)||odo.h_sites||0,mediaN=(_lastRep&&_lastRep.direct_media)||odo.s_dm||0;
    const quote=(_lastRep&&_lastRep.quote)||Math.min(500,Math.max(250,Math.round(confirmed*0.13)));
    const monthly=(_lastRep&&_lastRep.monthly)||Math.min(250,Math.max(200,200+Math.round((quote-250)/250*50)));
    const lossLo=Math.min(150,Math.max(50,confirmed*0.008)),lossHi=Math.min(300,Math.max(120,confirmed*0.022));
    const doms=Object.entries(domCount).sort((a,b)=>b[1]-a[1]).slice(0,8);
    const tops=topLinks(_byDom,_doms).slice(0,5).map(r=>r.url);
    const thumbs=(await Promise.all(cardThumbs(10).map(loadImg))).filter(Boolean);
    const shareUrl=(typeof JOB!=='undefined'&&JOB)?(location.origin+'/s/'+JOB):'';
    const qrImg=shareUrl?await loadImg('/qr?u='+encodeURIComponent(shareUrl)+'&sz=8'):null;   // scannable report link (server-rendered)
    // H is HEADROOM, not the poster height: a full report (8 domains + 5 top links + URL box + QR)
    // runs to ~2220px and used to draw the QR clean off a 1920 canvas. finalH crops back to content.
    const W=1080,H=2400,P=64,IW=W-2*P;
    const cv=document.createElement('canvas');cv.width=W;cv.height=H;const c=cv.getContext('2d');
    const rr=(x,y,w,h,r)=>{c.beginPath();c.moveTo(x+r,y);c.arcTo(x+w,y,x+w,y+h,r);c.arcTo(x+w,y+h,x,y+h,r);c.arcTo(x,y+h,x,y,r);c.arcTo(x,y,x+w,y,r);c.closePath();};
    const fit=(t,wt,mx,mw)=>{let s=mx;c.font=wt+' '+s+'px '+F;while(s>14&&c.measureText(t).width>mw){s-=2;c.font=wt+' '+s+'px '+F;}return s;};
    const trunc=(t,mw)=>{if(c.measureText(t).width<=mw)return t;let x=t;while(x.length>4&&c.measureText(x+'…').width>mw)x=x.slice(0,-1);return x+'…';};
    // the ramp is pinned to 1920, not H, so the extra headroom doesn't stretch the purple fade
    const bg=c.createLinearGradient(0,0,0,1920);bg.addColorStop(0,'#191138');bg.addColorStop(.35,'#0f1020');bg.addColorStop(1,'#0f1020');c.fillStyle=bg;c.fillRect(0,0,W,H);
    c.textAlign='center';c.fillStyle='#eef0ff';fit('Leak Scan Results','800',60,IW-(thumbs.length?300:0));c.fillText('Leak Scan Results',W/2,150);
    c.fillStyle='#38d9c7';c.font='700 46px '+F;c.fillText(trunc('@'+handle,IW-(thumbs.length?260:0)),W/2,208);
    // cute: a tilted "photo sticker" of a real leak thumbnail flanking each side of the title
    if(thumbs.length){
      const sticker=(im,cx,cy,sz,ang)=>{if(!im)return;c.save();c.translate(cx,cy);c.rotate(ang);
        c.shadowColor='rgba(0,0,0,.45)';c.shadowBlur=14;c.shadowOffsetY=5;
        c.fillStyle='#fff';rr(-sz/2-7,-sz/2-7,sz+14,sz+22,11);c.fill();c.shadowColor='transparent';
        c.save();rr(-sz/2,-sz/2,sz,sz,7);c.clip();
        const s=Math.max(sz/im.width,sz/im.height);c.drawImage(im,-im.width*s/2,-im.height*s/2,im.width*s,im.height*s);
        c.restore();c.restore();};
      sticker(thumbs[0],P+56,158,98,-0.13);
      sticker(thumbs[thumbs.length>1?1:0],W-P-56,158,98,0.13);
    }
    if(running){                                         // honest "not finished yet" stamp on the poster
      c.font='800 26px '+F;const bt='⏳ SCAN IN PROGRESS — final count still rising';
      const bw=Math.min(IW,c.measureText(bt).width+44),bx=(W-bw)/2,by=236,bh=44;
      c.fillStyle='#3a2a12';rr(bx,by,bw,bh,bh/2);c.fill();c.strokeStyle='#7a5a1e';c.lineWidth=2;rr(bx,by,bw,bh,bh/2);c.stroke();
      c.fillStyle='#f5b74e';c.textAlign='center';c.fillText(bt,W/2,by+30);
    }
    const pX=P,pY=running?300:290,pW=IW,pH=470;c.fillStyle='#0c0d1c';rr(pX,pY,pW,pH,22);c.fill();c.strokeStyle='#2c2e57';c.lineWidth=2;rr(pX,pY,pW,pH,22);c.stroke();
    c.textAlign='left';const word='Google',cols=['#4285F4','#EA4335','#FBBC05','#4285F4','#34A853','#EA4335'];c.font='500 40px arial,sans-serif';let pen=pX+34;
    for(let i=0;i<word.length;i++){c.fillStyle=cols[i];c.fillText(word[i],pen,pY+62);pen+=c.measureText(word[i]).width;}
    const gc=5,gr=2,gap=14,tTop=pY+110,pad=34,tW=(pW-2*pad-(gc-1)*gap)/gc,tH=(pH-110-pad-(gr-1)*gap)/gr;let ti=0;
    for(let r=0;r<gr;r++)for(let col=0;col<gc;col++){const tx=pX+pad+col*(tW+gap),ty=tTop+r*(tH+gap);c.save();rr(tx,ty,tW,tH,12);c.clip();const im=thumbs[ti];
      if(im){const s=Math.max(tW/im.width,tH/im.height),dw=im.width*s,dh=im.height*s;c.drawImage(im,tx+(tW-dw)/2,ty+(tH-dh)/2,dw,dh);}
      else{const hue=(ti*43+275)%360;const g2=c.createLinearGradient(tx,ty,tx+tW,ty+tH);g2.addColorStop(0,'hsl('+hue+',46%,44%)');g2.addColorStop(1,'hsl('+((hue+40)%360)+',52%,24%)');c.fillStyle=g2;c.fillRect(tx,ty,tW,tH);c.textAlign='center';c.fillStyle='rgba(255,255,255,.85)';c.font='26px arial';c.fillText('🔒',tx+tW/2,ty+tH/2+9);c.textAlign='left';}
      c.restore();ti++;}
    let y=pY+pH+72;c.textAlign='left';c.fillStyle='#eef0ff';const hl=fmt(confirmed)+(running?' leaks so far across ':' confirmed leaks across ')+sites+' site'+(sites===1?'':'s');fit(hl,'800',46,IW);c.fillText(hl,P,y);y+=42;
    c.fillStyle='#8ea0ff';c.font='400 28px '+F;c.fillText(fmt(mediaN)+' media files identified · takedown €'+fmt(quote)+' + €'+fmt(monthly)+'/mo',P,y);y+=58;
    c.font='600 30px '+F;doms.forEach(([d,n])=>{c.textAlign='left';c.fillStyle='#dfe2ff';c.fillText('•  '+trunc(d,IW-260),P+4,y);c.textAlign='right';c.fillStyle='#f5b74e';c.fillText(fmt(n)+' URLs',W-P,y);y+=47;});y+=20;
    if(tops.length){c.textAlign='center';c.fillStyle='#eef0ff';c.font='700 34px '+F;c.fillText('Top leaks:',W/2,y);y+=44;c.fillStyle='#8fb4ff';c.font='400 24px '+F;tops.forEach(u=>{c.fillText(trunc(u,IW),W/2,y);y+=35;});y+=22;}
    c.textAlign='center';c.fillStyle='#ff6b6b';const loss='Loss: €'+lossLo.toFixed(1)+' – €'+lossHi.toFixed(1)+' per OnlyFans fan';fit(loss,'800',42,IW);y+=18;c.fillText(loss,W/2,y);y+=74;
    const ig=igHandle();c.fillStyle='#38d9c7';const cta=ig?('DM @'+ig+' on Instagram to get them removed'):'DM us to get them removed';fit(cta,'800',34,IW);c.fillText(cta,W/2,y);y+=44;
    c.fillStyle='#a3a7c9';c.font='400 24px '+F;c.fillText('Free scan & how to remove it yourself — or we do it for you.',W/2,y);y+=30;
    // bake the shareable report link onto the poster so the image alone leads back to the live report.
    // Draw the URL in MONOSPACE so the "/s/" slash reads unambiguously — in the proportional font it
    // crowded into the slug and people mistyped ".../s/z…" as ".../slz…" (a dead 404).
    if(shareUrl){y+=26;
      c.font='600 28px '+MONO;const urlTxt=trunc(shareUrl,IW-48);
      const boxW=Math.min(IW,c.measureText(urlTxt).width+56),boxX=(W-boxW)/2,boxH=94;
      c.fillStyle='#141631';rr(boxX,y,boxW,boxH,16);c.fill();c.strokeStyle='#2c2e57';c.lineWidth=2;rr(boxX,y,boxW,boxH,16);c.stroke();
      c.textAlign='center';c.fillStyle='#8ea0ff';c.font='700 22px '+F;c.fillText('Open the full live report',W/2,y+32);
      c.fillStyle='#38d9c7';c.font='600 28px '+MONO;c.fillText(urlTxt,W/2,y+70);y+=boxH+16;}
    // QR of that same link — scan instead of typing the slug. Sits at the very bottom so it obstructs
    // nothing; skipped silently if the QR endpoint is unavailable (qrImg===null).
    if(qrImg){
      const qs=210,qx=(W-qs)/2,qy=y+8,pad=16;
      c.fillStyle='#ffffff';rr(qx-pad,qy-pad,qs+2*pad,qs+2*pad,20);c.fill();   // white panel = the quiet zone the scanner needs
      c.drawImage(qrImg,qx,qy,qs,qs);
      c.textAlign='center';c.fillStyle='#a3a7c9';c.font='600 22px '+F;c.fillText('📱 Scan to open the report',W/2,qy+qs+pad+34);
      y=qy+qs+pad+34+16;}
    const finalH=Math.min(H,Math.round(y+P));let outCv=cv;
    if(finalH<H-4){outCv=document.createElement('canvas');outCv.width=W;outCv.height=finalH;outCv.getContext('2d').drawImage(cv,0,0);}
    outCv.toBlob(bl=>{if(!bl){toast('Card failed');return;}
      const url=URL.createObjectURL(bl),name='leakscan-'+handle+(running?'-partial':'')+'.png';
      if(opts&&opts.preview===true){showCardPop(url,name);return;}   // popup: show it, visitor hits Download
      const a=document.createElement('a');a.href=url;a.download=name;
      // the anchor MUST be in the document for .click() to trigger a download in Firefox (and some
      // Chrome configs) — a detached anchor is silently ignored, which is why auto-save appeared to do nothing.
      document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),4000);toast('Results card saved 📸');},'image/png');
  }catch(e){toast('Card failed: '+(e.message||e));}
  btn.textContent=old;btn.disabled=false;
}

/* Auto-download the "Leak Scan Results" card ONCE when a scan the visitor started in THIS
   session finishes — mirrors public_app.py's maybeAutoSavePoster. Gated to the scan stream's
   'end' event, so it fires for a scan you ran (fresh landing OR reconnected in-flight run) but
   NEVER when merely opening a shared /s/<slug> report (that view doesn't reconnect the scan
   stream). Deduped per slug + requires real hits so a re-render can't double-download. */
let _cardAutoSaved='';
function maybeAutoSaveCard(done){
  const key=JOB||'x';
  if(_cardAutoSaved===key)return;
  if(!((odo.s_total>0)||(_lastRep&&_lastRep.total>0)))return;   // nothing worth a poster
  _cardAutoSaved=key;
  buildCard({done:done===true});                                // scan-end auto-save → completion card
}

/* Same card, shown instead of saved: EVERY load of a finished report pops it up with a Download
   button (the auto-save above already handed it to whoever ran the scan, so that view skips it). */
function showCardPop(url,name){$('cardimg').src=url;const a=$('carddl');a.href=url;a.download=name;$('cardpop').classList.add('show');}
function hideCardPop(){$('cardpop').classList.remove('show');}
let _cardPopped=false;
function maybeShowCardPopup(rep){
  if(_cardPopped||!rep||rep.phase==='scanning'||!(rep.total>0))return;
  if(_cardAutoSaved===(JOB||'x'))return;                        // this visitor's own scan already saved it
  _cardPopped=true;
  setTimeout(()=>buildCard({preview:true,done:true}),1500);      // let the gallery thumbs land first
}

/* live feed */
function pushFeed(ev,flash){
  const feed=$('feed');const r=document.createElement('div');r.className='row'+(flash?' flash':'');
  const b=ev.bucket?`<span class="b ${ev.bucket}">${ev.bucket==='LIKELY'?'DMCA':'maybe'}</span>`:'';
  r.innerHTML=`<span class=ic>${icon(ev.kind)}</span><span class=d>${ev.domain}</span><span class=u>${shortUrl(ev.url)}</span>${b}`;
  feed.insertBefore(r,feed.firstChild);while(feed.children.length>60)feed.removeChild(feed.lastChild);
}

/* live media wall — deduped crawl images, proxied + thumbnailed as they land */
const wallSeen=new Set();
const WALL_MAX=20;                                     // a tight rotating live strip — new tiles in, oldest drop out
const WALL_DRIP=140;                                   // ms between wall tiles. Crawl media is proven reliable +
                                                       // fast-loading (measured), so it streams as fast as CSE
                                                       // instead of the old 500ms crawl (2/s) that left a ~600-item
                                                       // backlog draining for minutes — the real "leaks appear late".
function wallKey(u){try{const x=new URL(u);let p=(x.hostname+x.pathname).toLowerCase().replace(/\/+$/,'');
  return p.replace(/-\d{2,4}x\d{2,4}(\.[a-z0-9]+)$/,'$1');   // collapse -100x100/-603x600 size variants → one
  }catch(e){return (u||'').split('?')[0].toLowerCase()}}
function wallCount(){const n=$('livewall').querySelectorAll('.wtile').length;$('wallcount').textContent=n+' shown';
  const e=$('livewall').querySelector('.wallempty');if(n&&e)e.remove();}
function trimWall(){const wall=$('livewall');while(wall.querySelectorAll('.wtile').length>WALL_MAX)wall.removeChild(wall.lastElementChild);}
function addWallTile(t){const wall=$('livewall');t.onclick=()=>t.classList.toggle('show');wall.prepend(t);trimWall();wallCount();}
/* caption host → clickable link to the ACTUAL page/file hosting the leak (url), not the domain root.
   stopPropagation so the click opens the leak instead of toggling the tile's reveal; new tab,
   noopener/nofollow (we don't vouch for these). Falls back to the domain root only if no url. */
function hostLink(domain,url){const d=(domain||'').replace(/^www\./,'');const href=url||(d?'https://'+d:'');
  if(!href)return '';const label=d||href;
  return `<a class=hostln href="${href}" target=_blank rel="noopener noreferrer nofollow" onclick="event.stopPropagation()">${label}</a>`;}
/* PACED reveal — instead of flooding every image the instant it lands (one domain's dump filling
   the whole wall), events are de-duped into a queue and drained at a steady rate, so the wall reads
   as a calm live stream. Dedup is truly done first (here + server-side), then posted a few per second. */
const _wallQ=[];let _wallPump=null;
const CSE_DRIP=140;                                    // CSE base64 tiles stream in FAST (always decode)
function pushWall(ev){
  if((PHASE!=='scanning'&&!REPLAY)||!ev)return;        // stream images during a live scan OR a report-open replay
  // Two tile sources: crawl media (ev.url → proxied through /media, may be hotlink-blocked) and CSE
  // thumbnails (ev.imgsrc = a base64 data: URI that ALWAYS loads — real Google-indexed leak images).
  if(!ev.imgsrc){if(!ev.url||ev.kind==='page'||ev.kind==='video')return;}   // videos/pages have no thumbnail
  const k=ev.imgsrc?('cse:'+ev.imgsrc.slice(0,80)):wallKey(ev.url);         // dedup key per source
  if(wallSeen.has(k))return;wallSeen.add(k);
  if(ev.imgsrc)_wallQ.unshift(ev);else _wallQ.push(ev);          // CSE (reliable) jumps ahead of crawl media
  if(_wallQ.length>2000)_wallQ.length=2000;                      // bound the backlog (raised: don't drop eligible leaks)
  pumpWall();
}
function addWallImg(ev,im){                             // build + place a wall tile around a loaded <img>
  const t=document.createElement('div');t.className='wtile';
  im.className='wimg';
  const url=ev.url||'';                                 // make the IMAGE itself open the leak (caption link stays too)
  if(url){const a=document.createElement('a');a.className='wlink';a.href=url;a.target='_blank';a.rel='noopener nofollow';a.appendChild(im);t.appendChild(a);}
  else t.appendChild(im);
  const stamp=ev.imgsrc?'CSE':'LEAK';                   // CSE thumbs (Google-indexed) vs live crawl media
  t.insertAdjacentHTML('beforeend',
    `<div class=stamp>${stamp}</div><div class=rv>🔒</div><div class=cap><span>${hostLink(ev.domain,ev.url)||(ev.domain||'')}</span></div>`);
  addWallTile(t);
  feedSiteShot({src:(im.getAttribute('src')||''),host:ev.domain||'',page:ev.url||''});
  scheduleSiteShot();
}
// Self-rescheduling pump (setTimeout, not setInterval): a single stalled tick can never kill the
// stream permanently — any pushWall/seedWallFromCSE re-kicks it. CSE tiles drip FAST (140ms, they
// always render); crawl media at the calm 500ms beat.
function pumpWall(){
  if(_wallPump||(PHASE!=='scanning'&&!REPLAY)||!_wallQ.length)return;
  _wallPump=setTimeout(function step(){
    _wallPump=null;
    if((PHASE!=='scanning'&&!REPLAY)||!_wallQ.length)return;
    const ev=_wallQ.shift();
    let delay=WALL_DRIP;
    if(ev.imgsrc){
      // CSE base64 data: URI — ALWAYS decodes, so add the tile DIRECTLY (same as the report's evidence
      // <img>s). The old new-Image()/onload preload silently dropped these → wall stuck on 'warming up'.
      const im=document.createElement('img');im.decoding='async';im.src=ev.imgsrc;addWallImg(ev,im);
      delay=CSE_DRIP;
    }else{
      // crawl media: PRELOAD via /media and add ONLY once it truly loads, so hotlink-blocked hosts
      // (thothd) never leave a black tile.
      const im=new Image();im.decoding='async';
      im.onload=()=>{if(PHASE==='scanning'||REPLAY)addWallImg(ev,im);};
      im.onerror=()=>{wallSeen.delete(wallKey(ev.url));};
      im.src=`/media?u=${encodeURIComponent(ev.url)}&w=360`;
    }
    // Adaptive drain: when a burst has piled up (a wave just dumped its media), surface it FAST so the
    // wall catches up in seconds instead of trickling for minutes; fall back to the calm beat once drained.
    if(_wallQ.length>40)delay=Math.min(delay,45);
    _wallPump=setTimeout(step,delay);
  },0);
}
/* Seed the live wall from the CSE Google-Images thumbnails — REAL, Google-indexed leak images as
   base64 data: URIs that load instantly and can't be hotlink-blocked. This is the RELIABLE wall
   source: raw crawl media is flaky (the real leaks like thothd are hotlink-blocked, only junk-host
   chrome happens to load), so without this the wall can sit on 'warming up' for the whole scan. */
function seedWallFromCSE(){
  if(PHASE!=='scanning'&&!REPLAY)return;
  ((_lastAssets&&_lastAssets.gimages)||[]).forEach(m=>{
    if(m&&m.src)pushWall({domain:(m.host||'').replace(/^www\./,''),url:m.host?('https://'+m.host):'',imgsrc:m.src,kind:'image'});
  });
  pumpWall();                                          // resurrect the pump if a stalled tick had killed it
}

/* ── REPLAY on report-open ──────────────────────────────────────────────────
   A finished /s/<slug> report has no live SSE image stream, so the "Leaks coming in" wall and the
   generated per-domain screenshot panels would sit empty — only the CSE thumbnails ever rendered,
   which is why an opened report showed far fewer images than watching a live scan. Rebuild the image
   pool from the report's OWN data (every per-domain leak image URL + the CSE Google-Images thumbs +
   the vetted gallery) and stream it back through the normal wall pipeline, so opening a report shows
   the leaks flooding in ("brrr") AND fills every generated panel exactly like a live run. */
function replayPool(){
  const out=[],seen=new Set();
  // CSE Google-Images thumbnails first — base64 data: URIs that always decode
  ((_lastAssets&&_lastAssets.gimages)||[]).forEach(m=>{if(m&&m.src&&!seen.has(m.src)){seen.add(m.src);
    out.push({domain:(m.host||'').replace(/^www\./,''),url:m.host?('https://'+m.host):'',imgsrc:m.src,kind:'image'});}});
  // every per-domain leak IMAGE url from the report (proxied via /media; hotlink-blocked ones self-drop)
  Object.keys(_byDom||{}).forEach(dom=>{(_byDom[dom]||[]).forEach(r=>{
    if(r&&r.url&&!seen.has(r.url)&&(r.kind==='image'||/\.(jpe?g|png|webp|gif|avif)(\?|$)/i.test(r.url))){
      seen.add(r.url);out.push({domain:(dom||'').replace(/^www\./,''),url:r.url,kind:'image'});}});});
  // vetted gallery images last — same-origin /asset URLs that always load
  ((_lastAssets&&_lastAssets.gallery)||[]).forEach(g=>{const s=g.src?asset(g.src,360):'';
    if(s&&!seen.has(s)){seen.add(s);out.push({domain:(g.domain||'').replace(/^www\./,''),url:g.domain?('https://'+g.domain):'',imgsrc:s,kind:'image'});}});
  return out;
}
let _replayed='';
function maybeReplay(){
  if(PHASE!=='done')return;                            // only a finished report, never mid-scan
  if(document.body.classList.contains('scandone'))return;  // a scan we just ran already streamed live
  const key=JOB||PREFIX||'x';
  if(_replayed===key)return;
  const pool=replayPool();
  if(!pool.length)return;
  _replayed=key;REPLAY=true;
  document.body.classList.add('replaying');
  const sub=$('wallsub');if(sub)sub.textContent='— replaying this scan';
  const w=$('livewall');
  if(w&&!w.querySelector('.wtile')&&!w.querySelector('.wallempty')){
    const d=document.createElement('div');d.className='wallempty';
    d.textContent='◗ replaying — the leaks this scan found, streaming back in…';w.appendChild(d);}
  pool.forEach(pushWall);                              // preloads + drops hotlink-blocked, feeds the panel pool
  pumpWall();
}

let lastPulse=0,repPages=0,_byDom={},_doms=[],_lastRep=null;
function renderChips(rep){
  // Rebuild the hero username chips from the report's alias list. Called on EVERY report update
  // (SSE snapshot, batch, and the 5s poll) so the chips grow to the full harvested set instead of
  // being frozen at whatever the first render saw (often just the handle).
  const el=$('chips'); if(!el)return;
  const al=(rep&&rep.aliases)||[];
  if(el.childElementCount===al.length&&el.dataset.k===al.join('|'))return;   // no change → skip
  el.innerHTML='';el.dataset.k=al.join('|');
  al.forEach(a=>{const c=document.createElement('span');c.className='chip2';c.textContent=a;el.appendChild(c)});
}
function applyReport(rep,byDomain){
  _lastRep=rep;
  renderChips(rep);
  domCount={};rep.domains.forEach(d=>domCount[d.domain]=d.n);
  repPages=rep.pages||0;                              // kept for the chat context (no Pages card now)
  if(byDomain)_byDom=byDomain;_doms=rep.domains;      // kept for the downloadable results card
  setNum('h_leaks',rep.total);setNum('h_sites',rep.domains.length);
  setNum('s_total',rep.total);setNum('s_likely',rep.likely);setNum('s_sites',rep.domains.length);
  setNum('s_dm',rep.direct_media);
  // takedown quote — the €250–€500 (capped) price_for(confirmed) figure the make_report/public_app report shows
  const quote=rep.quote||0, monthly=rep.monthly||0;
  $('s_quote').textContent='€'+fmt(quote);
  $('band_price').style.width=Math.max(3,Math.min(100,Math.round(100*(quote-250)/250)))+'%';
  if($('s_monthly'))$('s_monthly').textContent = monthly ? ('one-time · + €'+fmt(monthly)+'/mo optional ongoing protection') : 'one-time · optional ongoing protection';
  $('s_sites_s').textContent=rep.domains.length+' domains';
  // honest split under the big headline: how much is media files vs the index/gallery pages hosting them
  const _media=rep.direct_media||0,_pages=Math.max(0,(rep.total||0)-_media);
  $('band_total').style.width=(rep.total?Math.round(_media/rep.total*100):0)+'%';
  $('band_totaltx').textContent=fmt(_media)+' media · '+fmt(_pages)+' pages';
  $('linkpill').textContent=fmt(rep.total)+' links';$('dompill').textContent=rep.domains.length+' domains';
  $('linkcount').textContent=rep.total?('— '+fmt(rep.total)):'';
  const scanning=rep.phase==='scanning';
  $('subline').textContent = rep.total
    ? "Real-time map of everywhere this creator's content has been reposted — grouped links, screenshots, and Google hits."
    : (scanning ? "Scanning… results are filling in live below." : "No scan yet — enter a handle below and hit Start.");
  $('feed').hidden=!scanning;
  renderBars(rep.domains);
  if(byDomain){renderGroups(byDomain,rep.domains);renderTop(byDomain,rep.domains);}
  renderGoogle();                                     // de-duped leak-image evidence (fed by _byDom)
  renderLiveSiteTiles();                              // per-domain Site-screenshot tiles fill MID-SCAN
  renderGoogleDeep();renderGoogleAlso(rep);           // Google search results + Also all over Google
  checkMile(rep.total);
  if(rep.total>lastPulse){lastPulse=rep.total;const st=$('s_total').closest('.stat');if(st){st.classList.remove('pulse');void st.offsetWidth;st.classList.add('pulse')}}
  maybeShowCardPopup(rep);                            // finished report → pop the results card once
}
function setStatus(s){
  const scanning=s.scan&&s.scan.running;
  const total=(s.report&&s.report.total)||0;
  setPhase(scanning?'scanning':(total>0?'done':'idle'));
  if(s.scan){lastScan.running=!!s.scan.running;lastScan.handle=s.scan.handle||lastScan.handle;
    lastScan.status=s.scan.status||'';renderCmd(s.scan);   // keep the copyable full-run command shown
    const ls=s.scan.lines||[];
    for(let i=ls.length-1;i>=0;i--){const m=String(ls[i]).match(/\[(\d+)\s*\/\s*(\d+)\]/);
      if(m){lastScan.progress=m[1]+' of '+m[2]+' known leak sites crawled';break;}}}
  // live crawl-progress bar — segmented into the 8 pipeline steps. The furthest step reached is
  // read from the "=== [id] title ===" markers; completed steps light up in the accent gradient,
  // the ACTIVE step fills amber with its own sub-progress (e.g. "136 / 187 sites" during the crawl).
  const pw=$('progwrap'),ps=$('progsteps'),pt=$('progtx');
  const STEPS8=[
    {label:'Presence scan',   ids:['scan']},
    {label:'Google & CSE',    ids:['cse','gshots','gcapture','images']},
    {label:'Seed frontier',   ids:['seed','seedurl']},
    {label:'Deep crawl',      ids:['crawl']},
    {label:'Clean & dedupe',  ids:['clean']},
    {label:'Triage',          ids:['triage']},
    {label:'Gallery',         ids:['gallery']},
    {label:'Export & report', ids:['export','report']}];
  if(pw&&ps){
    if(!ps.childElementCount){                       // build the 8 segments once
      STEPS8.forEach((s2,i)=>{const seg=document.createElement('div');seg.className='seg';
        seg.title=(i+1)+' · '+s2.label;seg.innerHTML='<span class=fill></span>';ps.appendChild(seg);});
    }
    const segs=ps.children;
    if(scanning){
      pw.hidden=false;
      const ls2=(s.scan&&s.scan.lines)||[];
      const idx={};STEPS8.forEach((s2,i)=>s2.ids.forEach(id=>{idx[id]=i;}));
      // furthest step reached = highest-index step marker seen so far (monotonic, no flicker)
      let ci=-1;
      for(const ln of ls2){const m=String(ln).match(/\[([a-z]+)\]/);if(m&&idx[m[1]]!=null&&idx[m[1]]>ci)ci=idx[m[1]];}
      if(ci<0)ci=0;
      // deep-crawl sub-progress = last "[N / M] known leak sites crawled" console line
      let cur=0,tot=0;
      for(let i=ls2.length-1;i>=0;i--){const m=String(ls2[i]).match(/\[(\d+)\s*\/\s*(\d+)\]/);if(m){cur=+m[1];tot=+m[2];break;}}
      const isCrawl=ci===3&&tot>0;
      const frac=isCrawl?Math.min(1,cur/tot):0;
      for(let i=0;i<segs.length;i++){
        const seg=segs[i],fill=seg.querySelector('.fill');
        seg.classList.toggle('done',i<ci);
        seg.classList.toggle('active',i===ci);
        if(i<ci){seg.classList.remove('indet');fill.style.width='';}
        else if(i===ci){
          if(isCrawl){seg.classList.remove('indet');fill.style.width=Math.round(frac*100)+'%';}
          else{seg.classList.add('indet');fill.style.width='';}
        }else{seg.classList.remove('indet');fill.style.width='0';}
      }
      pt.textContent=(ci+1)+'/8 · '+STEPS8[ci].label+(isCrawl?' · '+cur+' / '+tot+' sites':'');
    }else{
      pw.hidden=true;
      for(let i=0;i<segs.length;i++){segs[i].className='seg';segs[i].querySelector('.fill').style.width='0';}
    }
  }
  refreshAssetsIfGrew(s.asset_counts);            // pull new screenshots/CSE as the catalog grows
  $('statusbadge').textContent='● '+(s.status||s.mode);
  $('live').classList.toggle('scanning',!!scanning);
  $('livetx').textContent=scanning?'⟳ SCANNING':(s.mode==='report'?'LIVE REPORT':(s.done?'DONE':'LIVE'));
  $('foot').textContent=`source: ${s.source||'—'} · mode: ${s.mode} · ${(s.asset_counts?s.asset_counts.gallery:0)} screenshots · ${(s.asset_counts?s.asset_counts.cse:0)} CSE · seq ${fmt(s.seq)}`;
}

/* ---- phase layout · DM · copy-all · chat · new deep scan ---- */
let DM={},PREFIX='',featInit=false,PHASE='',REPLAY=false;
const lastScan={running:false,handle:'',status:'',progress:''};
function setPhase(p){if(p===PHASE)return;PHASE=p;
  document.body.classList.remove('phase-idle','phase-scanning','phase-done');
  document.body.classList.add('phase-'+p);
  if(p!=='done')document.body.classList.remove('scanopen');
  if(p==='scanning'){const w=$('livewall');
    if(w&&!w.querySelector('.wtile')&&!w.querySelector('.wallempty')){
      const d=document.createElement('div');d.className='wallempty';
      d.textContent='◗ warming up — images appear here as the crawler pulls them…';w.appendChild(d);}}
}
function toast(m){const t=$('toast');t.textContent=m;t.classList.add('show');clearTimeout(toast._t);toast._t=setTimeout(()=>t.classList.remove('show'),2600)}
function renderDM(dm){
  const row=$('dmrow');row.innerHTML='';
  [['instagram','ig','Instagram','📸'],['whatsapp','wa','WhatsApp','💬'],['telegram','tg','Telegram','✈']]
    .forEach(([k,cls,label,ic])=>{if(dm[k]){const a=document.createElement('a');a.className='dm '+cls;a.href=dm[k];a.target='_blank';a.rel='noopener';a.textContent=ic+' '+label;row.appendChild(a)}});
}
async function copyLinks(bucket){
  try{const r=await fetch(api('/api/links',bucket?{bucket}:null));const t=await r.text();
    await navigator.clipboard.writeText(t);toast('Copied '+t.split('\n').filter(Boolean).length.toLocaleString()+' links');return t;
  }catch(e){toast('Copy blocked — use Download .txt');return ''}
}
$('copyall').onclick=()=>copyLinks('');
$('cardbtn').onclick=buildCard;
$('cardclose').onclick=hideCardPop;
$('cardpop').onclick=e=>{if(e.target===$('cardpop'))hideCardPop()};      // click the backdrop to dismiss
document.addEventListener('keydown',e=>{if(e.key==='Escape')hideCardPop()});
$('mailbtn').onclick=async()=>{
  const to=$('mailto').value.trim();
  if(!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(to)){$('mailmsg').textContent='enter a valid email';return}
  $('mailmsg').textContent='sending…';$('mailbtn').disabled=true;
  try{
    const r=await fetch(api('/api/mail'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:to,bucket:'LIKELY'})});
    const j=await r.json();
    if(j.ok){$('mailmsg').textContent='✓ sent to '+to;toast('Links emailed to '+to)}
    else{$('mailmsg').textContent='✗ '+(j.error||'failed')}
  }catch(e){$('mailmsg').textContent='✗ failed'}
  $('mailbtn').disabled=false;
};
/* ── Copy report link (share) + collected-links export + full-run command box ── */
function showShare(){if(JOB)$('sharebtn').hidden=false;}
$('sharebtn').onclick=async()=>{if(!JOB)return;const url=location.origin+'/s/'+JOB;
  try{await navigator.clipboard.writeText(url);toast('Report link copied — anyone can open it to watch live');}
  catch(e){prompt('Copy this report link:',url);}};
let _exportWired=false;
function wireExport(){                                  // (re)point the download hrefs at the current job
  $('exportdl').href=api('/api/links',{fmt:'download'});
  $('exportdiff').href=api('/api/links',{fmt:'download',diff:'1'});
  if($('dlall'))$('dlall').href=api('/api/links',{fmt:'download'});
  if($('dldiff'))$('dldiff').href=api('/api/links',{fmt:'download',diff:'1'});
  if(_exportWired)return;_exportWired=true;
  $('exportload').onclick=loadExport;
  $('exportcopy').onclick=async()=>{let t=$('exportbox').value;if(!t)t=await loadExport();
    if(t){try{await navigator.clipboard.writeText(t);toast('Copied the full collected-links list');}
      catch(e){toast('Copy blocked — use Download');}}};
}
async function loadExport(){const b=$('exportload');b.disabled=true;b.textContent='loading…';let t='';
  try{t=await (await fetch(api('/api/links'))).text();$('exportbox').value=t;
    const n=t.split('\n').filter(x=>x&&!x.startsWith('#')).length;$('exportpill').textContent=fmt(n)+' links';}
  catch(e){toast('Load failed');}
  b.disabled=false;b.textContent='⟳ Load full list';return t;}
function renderCmd(scan){if(!scan||!scan.cmd)return;const pre=$('scancmdpre');
  if(pre.textContent!==scan.cmd)pre.textContent=scan.cmd;$('scancmd').hidden=false;}
$('cmdcopy').onclick=()=>{const t=$('scancmdpre').textContent;if(!t)return;
  navigator.clipboard.writeText(t).then(()=>toast('Command copied — paste it to reproduce the run'))
    .catch(()=>toast('Select the command to copy'));};

function addMsg(logEl,cls,txt){const d=document.createElement('div');d.className='msg '+cls;d.textContent=txt;logEl.appendChild(d);logEl.scrollTop=logEl.scrollHeight;return d}
function chatContext(){
  const tops=Object.entries(domCount).sort((a,b)=>b[1]-a[1]).slice(0,10).map(([d,n])=>`${d} (${fmt(n)})`).join(', ');
  const who=lastScan.handle||PREFIX||'this creator';
  // 2-3 REAL example leak URLs from each of the biggest sites — the visitor's OWN found links, the
  // very ones the on-page groups list. Prefer a [page] link (the webpage hosting the leak) PLUS a
  // media file, each tagged by kind, so the assistant can hand over the page or the image on request.
  const ex=(_doms||[]).slice(0,6).map(d=>{
    const ls=(_byDom[d.domain]||[]).filter(l=>l&&l.url);
    const picks=[];
    const pg=ls.find(l=>l.kind==='page'); if(pg)picks.push(pg);     // the webpage hosting the leak
    const md=ls.find(l=>l.kind!=='page'); if(md)picks.push(md);     // a direct image/video file
    for(const l of ls){if(picks.length>=3)break;if(!picks.includes(l))picks.push(l);}
    const parts=picks.map(l=>`[${l.kind||'link'}] ${l.url}`);
    return parts.length?`${d.domain}: ${parts.join(' | ')}`:'';
  }).filter(Boolean).join('\n');
  const exBlock=ex?`\nexample found URLs (this visitor's OWN leaks — the same links the on-page list already `+
    `shows; each is tagged [page] = the webpage hosting the leak, [image]/[video] = a direct media file. `+
    `You MAY quote one or two verbatim when they ask to see a leak — give a [page] link when they ask for `+
    `the page, a media link when they ask for the image; never the whole list, never invent one):\n${ex}`:'';
  const nums=`${fmt(odo.s_total||0)} detected leak links, ${fmt(odo.s_likely||0)} DMCA-ready (high-confidence), `+
    `across ${odo.h_sites||0} sites, ${fmt(odo.s_dm||0)} direct media URLs, ${fmt(repPages||0)} pages`;
  if(lastScan.running)
    return `A deep scan is CURRENTLY RUNNING and NOT finished for @${who}. Progress: `+
      `${lastScan.progress||'crawling known leak sites'}; current pipeline step: ${lastScan.status||'running'}. `+
      `The numbers are still climbing and will keep growing until it completes. So far: ${nums}. `+
      `Top sites so far: ${tops||'…'}.${exBlock}\nIMPORTANT: tell the user the scan is STILL IN PROGRESS — do NOT `+
      `say it is complete/final and do NOT present these counts as final totals; they are a live running tally.`;
  return `Scan for @${who} is COMPLETE. Totals: ${nums}. Top sites by file count: ${tops||'…'}.${exBlock}`;
}
let chatBusy=false;
async function sendChatInto(text,logEl,inputEl){        // shared by the bottom chat + the top ask bar
  if(chatBusy||!text.trim())return;chatBusy=true;
  addMsg(logEl,'me',text);if(inputEl)inputEl.value='';const bot=addMsg(logEl,'bot','…');
  try{
    const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({messages:[{role:'user',content:text}],scan_context:chatContext()})});
    const rd=r.body.getReader(),dec=new TextDecoder();let buf='',out='';
    while(true){const {value,done}=await rd.read();if(done)break;buf+=dec.decode(value,{stream:true});
      let i;while((i=buf.indexOf('\n\n'))>=0){const fr=buf.slice(0,i);buf=buf.slice(i+2);let ev='message',data='';
        fr.split('\n').forEach(l=>{if(l.startsWith('event:'))ev=l.slice(6).trim();else if(l.startsWith('data:'))data+=l.slice(5).trim()});
        if(ev==='token'){try{out+=JSON.parse(data)}catch(e){}bot.textContent=out;logEl.scrollTop=1e9}}
    }
    if(!out)bot.textContent='(no response)';
  }catch(e){bot.textContent='Chat is unavailable right now.'}
  chatBusy=false;
}
const sendChat=text=>sendChatInto(text,$('clog'),$('cin'));
$('csend').onclick=()=>sendChat($('cin').value);
$('cin').addEventListener('keydown',e=>{if(e.key==='Enter')sendChat($('cin').value)});
$('askform').addEventListener('submit',e=>{e.preventDefault();const v=$('askinput').value;if(!v.trim())return;
  $('askans').classList.add('on');sendChatInto(v,$('askans'),$('askinput'));});
function initChat(){
  if($('clog').children.length)return;
  addMsg($('clog'),'bot',"Hi — I can explain what this scan found and how to get the leaks removed. Ask me anything.");
  ['Is this all of them?','Which sites?','How to remove them?','Will they come back?',"What's the cost?"]
    .forEach(q=>{const b=document.createElement('b');b.textContent=q;b.onclick=()=>sendChat(q);$('qr').appendChild(b)});
}

function openScan(){document.body.classList.add('scanopen');$('scanpanel').scrollIntoView({behavior:'smooth',block:'center'});setTimeout(()=>$('scanhandle').focus(),250)}
$('newscanbtn').onclick=openScan;
$('scanhandle').addEventListener('keydown',e=>{if(e.key==='Enter')$('scango').click()});
$('scanaliases').addEventListener('keydown',e=>{if(e.key==='Enter')$('scango').click()});
// scan opt-outs — aria-pressed IS the state, so the button and the POST body can never disagree
const SCAN_OPTS={no_cse:'optnocse',no_variations:'optnovar'};
const optOn=id=>$(id).getAttribute('aria-pressed')==='true';
Object.values(SCAN_OPTS).forEach(id=>{const b=$(id);
  b.onclick=()=>{const on=!optOn(id);b.setAttribute('aria-pressed',String(on));
    toast(on?(id==='optnocse'?'Google CSE evidence off for this scan':'Alias variations off — typed names only')
           :(id==='optnocse'?'Google CSE evidence on':'Alias variations on'));};});
$('scancancel').onclick=()=>{$('scancancel').textContent='stopping…';fetch(api('/api/scan/cancel'),{method:'POST'})};
function resetReportTiles(){                            // clear a previous campaign's live-rendered content before a new scan
  wallSeen.clear();_wallQ.length=0;if(_wallPump){clearInterval(_wallPump);_wallPump=null;}$('livewall').innerHTML='';
  renderedShots.clear();_evSeen.clear();_evQueue=[];if(_evObs){_evObs.disconnect();_evObs=null;}
  _assetSig='';_grpSig='';
  $('shotgrid').innerHTML='';$('gmason').innerHTML='';$('grids').innerHTML='';$('groups').innerHTML='';$('bars').innerHTML='';
  $('siteshotgrids').innerHTML='';$('siteshotgrids').hidden=true;_ssPool.length=0;_ssSeen.clear();_cseSeen.clear();
  $('herofaces').innerHTML='';_heroSeen.clear();
  $('shotpill').textContent='0 captured';$('exportbox').value='';$('exportpill').textContent='0 links';
}
$('scango').onclick=async()=>{
  const h=$('scanhandle').value.trim();if(!h)return toast('Enter a handle');
  const aliases=$('scanaliases').value.split(',').map(s=>s.trim()).filter(Boolean);
  const opts={no_cse:optOn('optnocse'),no_variations:optOn('optnovar')};
  $('scango').disabled=true;let j;
  try{const r=await fetch('/api/scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.assign({handle:h,aliases},opts))});j=await r.json();}
  catch(e){$('scango').disabled=false;return toast('Could not start the scan');}
  $('scango').disabled=false;
  if(!j.ok)return toast(j.error==='busy'?(j.msg||'All scan slots are busy — try again shortly'):(j.error||'Could not start'));
  // this scan is its OWN report — bind the page to its slug + put the shareable link in the URL bar
  JOB=j.slug;history.pushState({},'',j.share||('/s/'+JOB));showShare();wireExport();
  {const _ss=$('sessionssec');if(_ss)_ss.hidden=true;}   // started a scan → we're now IN that report; hide the lobby
  lastScan.running=true;lastScan.handle=h;resetReportTiles();$('scanlog').textContent='';$('scancmd').hidden=true;
  document.body.classList.remove('scandone');       // fresh scan → drop the previous run's kept console/wall
  setPhase('scanning');
  // jump the viewer straight to the live results (stats + wall) so they watch the leaks fill in,
  // not the now-submitted scan form above it
  setTimeout(()=>{const t=$('stats')||$('livewallsec');if(t)t.scrollIntoView({behavior:'smooth',block:'start'});},120);
  openStream();                                     // rebind the live report stream to this new job
  streamScan();                                     // + its scan console stream
};
function streamScan(){
  if(streamScan._es){try{streamScan._es.close()}catch(e){}}
  const se=new EventSource(api('/api/scan/stream'));streamScan._es=se;const log=$('scanlog');
  const setp=t=>{$('scanpill').textContent=t;const p2=$('scanpill2');if(p2)p2.textContent=t;};
  const append=ls=>{ls.forEach(l=>log.textContent+=l+'\n');log.scrollTop=1e9};
  se.addEventListener('snapshot',e=>{const s=JSON.parse(e.data);append(s.lines);setp(s.status);renderCmd(s)});
  se.addEventListener('lines',e=>{const d=JSON.parse(e.data);append(d.lines);setp(d.scan.status);renderCmd(d.scan)});
  se.addEventListener('end',e=>{const s=JSON.parse(e.data);setp(s.status);lastScan.running=false;se.close();
    loadExport();                                    // pull the full collected-links list for diff-test
    // NO page reload — keep the console (so the full log stays copyable), the streamed images, and
    // the CSE evidence exactly as they are. The main /api/stream already keeps the report current,
    // so it just settles into the finished view in place.
    document.body.classList.add('scandone');
    // The scan's own 'end' event is the authoritative "finished" signal — settle the page to the
    // done phase now, ahead of the report stream catching up, so the whole view (and the auto-saved
    // card below) reads as complete instead of stuck on "scan in progress".
    if(s.rc===0&&((odo.s_total>0)||(_lastRep&&_lastRep.total>0)))setPhase('done');
    toast(s.rc===0?'Scan complete ✓ — CSE evidence kept below':'Scan stopped');
    // Auto-download the shareable results card on a clean finish. Small delay lets the final
    // report batch + wall/CSE thumbnails settle so the card draws current totals and images.
    // Pass done:true so it's stamped as a completion card, never "SCAN IN PROGRESS".
    if(s.rc===0)setTimeout(()=>maybeAutoSaveCard(true),900);
    const cx=$('scancancel');if(cx){cx.textContent='⧉ Copy log';cx.disabled=false;
      cx.onclick=()=>{navigator.clipboard.writeText(log.textContent).then(()=>toast('Console log copied')).catch(()=>toast('Select the log to copy'));};}
  });
}
function initFeatures(s){
  if(featInit)return;featInit=true;
  DM=s.dm||{};PREFIX=s.prefix||PREFIX;renderDM(DM);
  if(JOB)showShare();
  if(s.scan_enabled){
    $('newscanbtn').hidden=false;
    const empty=!(s.report&&s.report.total), running=s.scan&&s.scan.running;
    if(empty&&!running&&!JOB)setTimeout(()=>$('scanhandle').focus(),300);   // fresh landing → focus handle
  }
  if(s.chat_enabled){$('chatsec').hidden=false;$('askbar').hidden=false;initChat()}
  if(s.scan&&s.scan.running)streamScan();          // reconnect to an in-flight scan (phase via setStatus)
}

let es=null;
function onSnapshot(e){
  const s=JSON.parse(e.data);
  initFeatures(s);
  renderChips(s.report);                              // rebuild alias chips (applyReport also refreshes them)
  mileIdx=0;while(mileIdx<MILES.length&&s.report.total>=MILES[mileIdx])mileIdx++;
  applyReport(s.report,s.by_domain);setStatus(s);
  applyAssets(s.assets);                             // render screenshots + Google evidence (live-growable)
  const seed=(s.recent||[]).slice(-40);
  seed.forEach((ev,i)=>setTimeout(()=>{pushFeed(ev,true);pushWall(ev);},i*120));
}
function onBatch(e){
  const {events,state}=JSON.parse(e.data);
  if(state.report)applyReport(state.report,state.by_domain);
  setStatus(state);                                  // set phase before rendering wall tiles
  events.forEach(ev=>{pushFeed(ev,true);pushWall(ev);});
}
function openStream(){                                // (re)bind the live report stream to the current job
  if(es){try{es.close()}catch(e){}}
  es=new EventSource(api('/api/stream'));
  es.addEventListener('snapshot',onSnapshot);
  es.addEventListener('batch',onBatch);
  es.addEventListener('done',()=>{$('livetx').textContent='DONE';});
  es.onerror=()=>{$('statusbadge').textContent='● reconnecting…';};
}
if(JOB)showShare();
wireExport();
openStream();
setInterval(()=>{fetch(api('/api/state')).then(r=>r.json()).then(s=>{applyReport(s.report,s.by_domain);setStatus(s)}).catch(()=>{})},5000);
loadSessions();setInterval(loadSessions,4000);   // "Live scans on this server" panel — running/queued/history for everyone
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser(description="Live 'watch the leaks grow' stream site.")
    ap.add_argument("--mode", choices=["report", "auto", "watch", "replay"], default="report")
    ap.add_argument("--watch", default=None,
                    help="Growing crawl checkpoint to tap (default: newest of "
                         "creatorj.crawl.json / campaigns/creatorj/…).")
    ap.add_argument("--replay", default=None,
                    help="Existing crawl.json to replay for a live demo/test.")
    ap.add_argument("--rate", type=float, default=45.0, help="Replay leaks/sec (approx).")
    ap.add_argument("--poll", type=float, default=2.0, help="Watch poll interval (s).")
    ap.add_argument("--demo-fallback", action="store_true",
                    help="In watch mode, replay the bundled crawl if no scan appears in ~20s "
                         "(default: stay patient and keep waiting).")
    ap.add_argument("--catch-up", action="store_true",
                    help="In watch mode, also stream leaks that already exist in the file at "
                         "launch (default: baseline them and stream only new discoveries).")
    ap.add_argument("--assets-dir", default=None,
                    help="Campaign dir with gallery/CSE assets (default: campaigns/<prefix>).")
    ap.add_argument("--prefix", default=os.environ.get("REPORT_PREFIX") or None,
                    help="Campaign prefix (default: $REPORT_PREFIX or from crawl filename).")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8090)))
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    def newest(*cands):
        got = [c for c in cands if c and os.path.exists(c)]
        return max(got, key=os.path.getmtime) if got else (cands[0] if cands else "")

    # In watch mode we poll BOTH the repo-root file (where a fresh full run writes) and the
    # campaigns copy, so the site catches the deep scan wherever it lands.
    watch_paths = ([args.watch] if args.watch else
                   ["creatorj.crawl.json", "campaigns/creatorj/creatorj.crawl.json"])
    replay_path = args.replay or newest("campaigns/creatorj/creatorj.crawl.json",
                                        "creatorj.crawl.json")

    # visual evidence catalog (gallery screenshots, CSE thumbnails, CSE grids)
    ref_path = replay_path or (watch_paths[0] if watch_paths else "")
    # Default: start EMPTY (0) — the report fills in live when you run a deep scan. Pass
    # --prefix <name> (or $REPORT_PREFIX) to open an existing campaign instead.
    prefix = args.prefix or ""
    assets_dir = args.assets_dir or (
        os.path.join(HERE, "campaigns", prefix)
        if prefix and os.path.isdir(os.path.join(HERE, "campaigns", prefix)) else HERE)

    # The bare landing page (/) is the shared LANDING session. In the default multi-user 'report'
    # mode it starts EMPTY (just the "Start a deep scan" box) and EACH scan mints its OWN session +
    # shareable /s/<slug> link, so many people scan and watch at once. A --prefix / REPORT_PREFIX
    # (the single-campaign VPS deploy) instead opens that campaign on the bare page.
    if prefix:
        LANDING.prefix = prefix
        LANDING.assets_dir = assets_dir
        try:
            LANDING.hub.assets = build_catalog(assets_dir, prefix)
        except Exception:
            pass
    print(f"   assets: {len(LANDING.hub.assets['gallery'])} gallery · {len(LANDING.hub.assets['cse'])} cse · "
          f"{len(LANDING.hub.assets['grids'])} grids  (dir={_rel(assets_dir)}, prefix={prefix or '—'})")
    print(f"   chat={'on' if _HAVE_CHAT else 'off'}  scan={'on' if SCAN_ENABLED else 'off'}  "
          f"dm={sum(1 for v in DM.values() if v)}/3  max_scans={MAX_LIVE_SCANS}")

    # Legacy stream-test modes (replay/watch/auto) drive the LANDING hub directly so the bare page
    # shows the stream; LANDING's own per-session producer is disabled so they don't fight over it.
    if args.mode in ("replay", "watch", "auto"):
        LANDING.auto = False

        def start_producer():
            if args.mode == "replay":
                producer_replay(LANDING.hub, replay_path, args.rate)
            elif args.mode == "watch":
                producer_watch(LANDING.hub, watch_paths, args.poll, replay_path, args.rate,
                               args.demo_fallback, args.catch_up)
            else:  # auto: ride a scan that's actively writing, else replay to demo the stream
                fresh = next((p for p in watch_paths if os.path.exists(p)
                              and time.time() - os.path.getmtime(p) < 120), None)
                if fresh:
                    producer_watch(LANDING.hub, watch_paths, args.poll, replay_path, args.rate,
                                   args.demo_fallback, args.catch_up)
                else:
                    producer_replay(LANDING.hub, replay_path, args.rate)

        threading.Thread(target=start_producer, daemon=True).start()
    elif prefix:
        LANDING.ensure_producer()          # keep the single campaign live on the bare page

    host = os.environ.get("HOST", "127.0.0.1")   # Docker/VPS sets 0.0.0.0
    srv = ThreadingHTTPServer((host, args.port), make_handler(PAGE.encode("utf-8")))
    srv.daemon_threads = True
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{args.port}/"
    print(f"== live leak report → {url}  (Ctrl-C to stop) ==")
    print(f"   mode={args.mode}  bind={host}:{args.port}  token={'on' if LIVE_TOKEN else 'off'}  "
          f"· each scan → its own /s/<slug> link")
    if not args.no_open:
        threading.Thread(target=lambda: (time.sleep(1.0), webbrowser.open(url)),
                         daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n   stopped.")


if __name__ == "__main__":
    main()

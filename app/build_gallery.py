#!/usr/bin/env python3
"""build_gallery.py — NUDE-FIRST, one-per-site "Your leaked content" gallery.

Pools leaked images from BOTH sources the client cares about:
  • deep-crawl media  — leak PAGES, handle-verified (the URL carries the handle),
                        one NUDEST pick per registrable site (identity guard below)
  • Google-collected  — the Google-Images scrape in <prefix>_images/google/<query>/,
                        hand-vetted per campaign via a --google-keep list (only the
                        frames that are actually HER and tastefully explicit — no
                        hardcore, no two-person, no wrong-person, no memes)

Each candidate is scored by exposed-skin fraction (a rough 'likely nude' proxy:
nudes ~40-70%, clothed selfies ~10-25%), near-duplicates are dropped with an 8x8
average-hash, and the survivors are written NUDE-FIRST to a gallery-file. make_report
--gallery-file prepends it as the primary gallery, so the explicit evidence LEADS
instead of trailing.

Two curation flags make the per-campaign judgement calls reproducible instead of
manual:
  --block-file   registrable domains to DROP from the crawl set (wrong-person /
                 hardcore / SEO-spam sites the skin-scorer can't tell apart)
  --google-keep  relative paths under --google-root of the vetted Google frames

    # fresh (pipeline): download crawl media, fold vetted Google frames
    python3 build_gallery.py --crawl sophieraiin.crawl.clean.json --strong sophieraiin,sophierain \
        --out sophieraiin_gallery.txt --cache sophieraiin_gallery_imgs \
        --block-file sophieraiin_gallery_block.txt \
        --google-root sophieraiin_images/google --google-keep sophieraiin_google_keep.txt --max 48

    # re-run/delivery: reuse the already-vetted crawl picks verbatim (no re-download),
    # only (re)fold the Google frames and re-sort nude-first
    python3 build_gallery.py --reuse-gallery sophieraiin_gallery.txt --strong x \
        --google-root sophieraiin_images/google --google-keep sophieraiin_google_keep.txt \
        --out sophieraiin_gallery.txt --cache sophieraiin_gallery_imgs
"""
import argparse, concurrent.futures, io, os, re, json, urllib.request
from urllib.parse import urlparse
from PIL import Image
from netloc import registrable_domain

IMG_EXT = re.compile(r"\.(jpe?g|png|webp|avif)(\?|$)", re.I)
NUDE_FOLDER = re.compile(r"nude|leak|porn|onlyfans|sextape|nsfw", re.I)
GOOGLE_BOOST = 0.10          # nudge hand-vetted Google frames up (they're the cleanest nudes)


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def skin_score(raw):
    """Fraction of skin-tone pixels (0-1) — proxy for 'likely nude'. Accepts bytes
    or a path."""
    try:
        im = Image.open(io.BytesIO(raw) if isinstance(raw, (bytes, bytearray)) else raw).convert("RGB")
        im.thumbnail((150, 150))
        px = list(im.getdata())
        n = len(px) or 1
        skin = 0
        for r, g, b in px:
            mx, mn = max(r, g, b), min(r, g, b)
            if r > 95 and g > 40 and b > 20 and (mx - mn) > 15 and abs(r - g) > 15 and r > g and r > b:
                skin += 1
        return skin / n
    except Exception:
        return -1.0


def ahash(path):
    """64-bit average hash of a file — for near-duplicate collapse across sources."""
    try:
        im = Image.open(path).convert("L").resize((8, 8))
        px = list(im.getdata())
        avg = sum(px) / len(px)
        bits = 0
        for i, p in enumerate(px):
            if p >= avg:
                bits |= (1 << i)
        return bits
    except Exception:
        return None


def _is_dup(h, seen_hashes, thresh=6):
    """True if hash h is within `thresh` Hamming distance of any kept hash."""
    if h is None:
        return False
    for k in seen_hashes:
        if bin(h ^ k).count("1") <= thresh:
            return True
    return False


def fetch(url, timeout=12):
    try:
        host = urlparse(url).netloc
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": f"https://{host}/"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
        return raw if raw and len(raw) > 3000 else None
    except Exception:
        return None


def crawl_candidates(crawl_path, tokens, per_domain_scan, min_site_media, block):
    """{domain: [media urls carrying the handle]} — image urls only, capped per domain.
    IDENTITY GUARD: only include a site that hosts >= min_site_media handle-carrying
    images. A real host of the creator has many; a single 'sophieraiin.jpg' on a random
    site is usually SEO-spam / a mislabeled different person — drop those. Sites in
    `block` (wrong-person / hardcore the scorer can't tell apart) are dropped outright."""
    try:
        data = json.load(open(crawl_path, encoding="utf-8"))
    except (ValueError, OSError) as e:
        # A truncated/interrupted crawl (see leak_crawler's mid-run checkpoint) leaves malformed
        # JSON. Don't crash the gallery step on it — treat as no candidates; the report still builds.
        print(f"  build_gallery: cannot parse crawl {crawl_path} ({e}) — no crawl gallery tiles")
        return {}
    if not isinstance(data, list):
        return {}
    by_dom = {}
    for rec in data:
        for u in (rec.get("media") or []):
            if not IMG_EXT.search(u) or not any(t in norm(urlparse(u).path) for t in tokens):
                continue
            d = registrable_domain(u)
            if d and d not in block:
                by_dom.setdefault(d, []).append(u)
    return {d: urls[:per_domain_scan] for d, urls in by_dom.items()
            if len(urls) >= min_site_media}


def load_lines(path):
    if not path or not os.path.exists(path):
        return []
    return [ln.strip() for ln in open(path, encoding="utf-8")
            if ln.strip() and not ln.lstrip().startswith("#")]


def _dark_band(path):
    """Max fraction of any single row that is near-black — flags a solid censor bar or
    letterbox (the tell of text-meme / video-thumbnail junk). A 21-folder vision vet
    confirmed skin-fraction alone can't catch these, but dark_band>=0.6 drops them with
    ZERO false-drops on real keeps. PIL-only (no numpy dep)."""
    try:
        im = Image.open(path).convert("L").resize((96, 96))
        px = list(im.getdata())
        return max(sum(1 for v in px[r*96:(r+1)*96] if v < 40) / 96.0 for r in range(96))
    except Exception:
        return 0.0


def auto_google_keep(root, min_skin, cap, max_dark_band=0.6):
    """Automated stand-in for a hand-vetted --google-keep list. From the explicit query
    folders only (NUDE_FOLDER — nude/leak/porn/onlyfans/…), keep frames whose skin
    fraction clears `min_skin`. That threshold cleanly separates real leaked nudes
    (~0.4-0.99) from the text banners / memes / clothed selfies the scrape also pulls
    (~0-0.2). Highest-skin first, capped. Identity is BEST-EFFORT: the scrape is already
    handle-verified upstream, but skin-fraction can't tell whose body it is — a
    wrong-person nude can still pass, so --google-keep / --block-file remain the override."""
    picks = []
    for q in sorted(os.listdir(root)):
        d = os.path.join(root, q)
        if not os.path.isdir(d) or not NUDE_FOLDER.search(q):
            continue
        for name in sorted(os.listdir(d)):
            if not IMG_EXT.search(name):
                continue
            p = os.path.join(d, name)
            sc = skin_score(p)
            if sc >= min_skin and _dark_band(p) < max_dark_band:
                picks.append((sc, p))
    picks.sort(key=lambda x: -x[0])
    return [p for _, p in picks[:cap]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--crawl", default=None, help="clean crawl json (omit when --reuse-gallery).")
    ap.add_argument("--strong", required=True)
    ap.add_argument("--reuse-gallery", default=None,
                    help="Existing gallery.txt 'path|domain' lines to reuse as the crawl set "
                         "(skip re-download — keeps already-vetted picks verbatim).")
    ap.add_argument("--seed-gallery", default=None, help="vetted collected-image path list to fold in")
    ap.add_argument("--google-root", default=None, help="root of <query>/NNN.jpg Google scrape folders")
    ap.add_argument("--google-keep", default=None,
                    help="file of vetted 'query-folder/NNN.jpg' paths (relative to --google-root) to fold in")
    ap.add_argument("--google-auto", action="store_true",
                    help="No keep-list? Auto-pick explicit frames from the nude/leak/onlyfans/porn "
                         "query folders by skin fraction (drops text banners / memes / clothed). "
                         "Identity is best-effort — the scrape is already handle-verified upstream, "
                         "but it can't tell WHOSE nude body it is, so --google-keep / --block-file "
                         "stay the human override for the rare wrong-person frame.")
    ap.add_argument("--google-min-skin", type=float, default=0.35,
                    help="Auto mode: min skin fraction to accept a Google frame (default 0.35; "
                         "real nudes score ~0.4-0.99, text/memes/clothed ~0-0.2).")
    ap.add_argument("--google-max", type=int, default=24,
                    help="Auto mode: max Google frames to fold in (highest skin first).")
    ap.add_argument("--block-file", default=None, help="file of registrable domains to drop from crawl")
    ap.add_argument("--block", default="", help="comma-sep registrable domains to drop from crawl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", default="gallery_imgs")
    ap.add_argument("--max", type=int, default=48)
    ap.add_argument("--per-domain-scan", type=int, default=4)
    ap.add_argument("--min-site-media", type=int, default=4,
                    help="Only use sites hosting >= this many handle images (drops spam/wrong-person).")
    a = ap.parse_args()
    tokens = [norm(t) for t in a.strong.split(",") if norm(t)]
    os.makedirs(a.cache, exist_ok=True)
    block = set(d.strip().lower() for d in a.block.split(",") if d.strip()) | set(load_lines(a.block_file))

    items = []                                   # (score, path, label)

    # 1) crawl media — either reuse the already-vetted picks, or download fresh
    if a.reuse_gallery and os.path.exists(a.reuse_gallery):
        for ln in load_lines(a.reuse_gallery):
            p, _, dom = ln.partition("|")
            p, dom = p.strip(), dom.strip()
            if not os.path.exists(p) or registrable_domain("http://" + dom) in block or dom in block:
                continue
            sc = skin_score(p)
            if sc >= 0:
                items.append((sc, p, dom))
        print(f"crawl: reused {len(items)} already-vetted site picks from {a.reuse_gallery}")
    elif a.crawl:
        cand = crawl_candidates(a.crawl, tokens, a.per_domain_scan, a.min_site_media, block)
        flat = [(d, u) for d, urls in cand.items() for u in urls]
        print(f"crawl: {len(cand)} sites, downloading {len(flat)} candidate images…")
        scored = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
            futs = {ex.submit(fetch, u): (d, u) for d, u in flat}
            for f in concurrent.futures.as_completed(futs):
                d, u = futs[f]
                raw = f.result()
                if not raw:
                    continue
                sc = skin_score(raw)
                if sc < 0:
                    continue
                if d not in scored or sc > scored[d][0]:
                    scored[d] = (sc, u, raw)
        for d, (sc, u, raw) in scored.items():
            p = os.path.join(a.cache, re.sub(r"[^a-z0-9]+", "-", d)[:40] + ".jpg")
            try:
                Image.open(io.BytesIO(raw)).convert("RGB").save(p, "JPEG", quality=82)
                items.append((sc, p, d))
            except Exception:
                pass
        print(f"crawl: kept 1 nudest image for {len(items)} sites")

    # 2) Google-collected — a hand-vetted keep-list wins; else auto-pick by skin fraction.
    #    Each frame is its own tile (blank host chip — no verified host for a Google frame).
    google_paths = []
    if a.google_root and a.google_keep and os.path.exists(a.google_keep):
        for rel in load_lines(a.google_keep):
            google_paths.append(os.path.join(a.google_root, rel))
        print(f"google: hand-vetted keep-list -> {len(google_paths)} frames")
    elif a.google_root and a.google_auto:
        google_paths = auto_google_keep(a.google_root, a.google_min_skin, a.google_max)
        print(f"google: AUTO-picked {len(google_paths)} explicit frames "
              f"(skin>={a.google_min_skin:.0%}, cap {a.google_max}, no keep-list)")
    if a.seed_gallery:                            # legacy: plain path-per-line list
        google_paths += load_lines(a.seed_gallery)
    for p in google_paths:
        if not os.path.exists(p):
            print(f"  google keep miss: {p}")
            continue
        sc = skin_score(p)
        if sc < 0:
            continue
        folder = os.path.basename(os.path.dirname(p))
        if NUDE_FOLDER.search(folder):
            sc += GOOGLE_BOOST
        items.append((sc, p, ""))                 # blank label — no verified host for a Google frame
    if google_paths:
        print(f"google: folded {sum(1 for p in google_paths if os.path.exists(p))} vetted frames")

    # 3) NUDE-FIRST order, drop near-dupes (avg-hash), cap. Lines are "path|site" so
    #    make_report can label each crawl tile with its source domain (Google tiles blank).
    items.sort(key=lambda x: -x[0])
    seen_hashes, gallery = [], []
    for sc, p, d in items:
        h = ahash(p)
        if _is_dup(h, seen_hashes):
            continue
        if h is not None:
            seen_hashes.append(h)
        gallery.append((sc, p, d))
        if len(gallery) >= a.max:
            break
    lines = [f"{p}|{d}" for _, p, d in gallery]
    open(a.out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    n_g = sum(1 for _, _, d in gallery if not d)
    print(f"wrote {a.out}: {len(gallery)} images ({len(gallery)-n_g} crawl-site, {n_g} Google), "
          f"nude-first (top skin: {', '.join(f'{min(s, 1.0):.0%}' for s, _, _ in gallery[:6])})")


if __name__ == "__main__":
    main()

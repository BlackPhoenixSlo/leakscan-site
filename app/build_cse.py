#!/usr/bin/env python3
"""
build_cse.py — generate the `<prefix>.cse.json` the report's "Also all over Google"
section needs, HEADLESSLY via the Google CSE API (GOOGLE_API_KEY / GOOGLE_CSE_ID in
.env — no browser, no Incogniton).

Multi-seed widening (cse_search_wide) surfaces the sites Google indexes the creator
on; thumbnails are downloaded and base64-embedded so the report stays self-contained
and encryptable. top_leaks is curated: only links whose URL carries the handle, one
clean url per registrable domain.

    python3 build_cse.py --name "Sophie Rain" --strong "sophieraiin,sophierain" \
        --out sophieraiin.cse.json [--max-calls 15]
"""
import argparse, base64, json, os, re, sys, urllib.request

import cse_scanner
from netloc import registrable_domain, canon_url, load_top_drop

HERE = os.path.dirname(os.path.abspath(__file__))
TOP_DROP = os.path.join(HERE, "top_drop.txt")


def load_env():
    p = os.path.join(HERE, ".env")
    if not os.path.exists(p):
        return
    for ln in open(p, encoding="utf-8"):
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _fetch_thumb(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
        if not raw or len(raw) > 400_000:
            return None
        mime = "image/jpeg" if raw[:2] == b"\xff\xd8" else "image/png"
        return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")
    except Exception:
        return None


def build(name, tokens, max_calls=15, img_limit=40, top_n=12, drop=None, image_calls=6):
    handle = tokens[0]
    if drop is None:
        drop = load_top_drop(TOP_DROP)
    ntoks = [_norm(t) for t in tokens if _norm(t)]
    queries = [
        f'"{handle}" (onlyfans leaks OR nude OR leaks)',
        f'{handle} leaked', f'{handle} nude', f'{handle} onlyfans',
        f'leaks {handle}', f'porn {handle}', f'"{name}" leaked nude',
    ]
    errors = []   # failed Google calls: public_app._deep_worker reads them, no hit + a failed call is no clean result
    results, total = cse_scanner.cse_search_wide(
        queries, max_calls=max_calls,
        on_progress=lambda m: print(f"  [cse] {m}", file=sys.stderr), errors=errors)

    sites = [{"domain": s["domain"], "url": s.get("url", ""), "occ": s.get("occurrences", 0)}
             for s in cse_scanner.summarize_cse(results)]

    # embedded thumbnails (self-contained report) — from the web results' pagemap thumbnails
    images, img_meta = [], []
    for r in results:
        if len(images) >= img_limit:
            break
        uri = _fetch_thumb(r.get("image")) if r.get("image") else None
        if uri:
            images.append(uri)
            img_meta.append({"data": uri, "title": (r.get("title") or "")[:90], "host": r.get("host", "")})

    # Dedicated IMAGE search (searchType=image) → MORE real leak-image thumbnails: Google-INDEXED
    # images for the leak keywords ('<h> nude leaks', 'onlyfans leaks', 'porn videos'), not web-page
    # pagemap images. Google-hosted thumbnails, so they load reliably. FULLY GUARDED: any failure or
    # quota just keeps the web thumbnails above (never breaks the cse step).
    try:
        img_queries = [f"{handle} nude leaks", f"{handle} onlyfans leaks", f"{handle} porn videos"]
        have = {m["data"] for m in img_meta}
        for r in cse_scanner.cse_image_search(
                img_queries, max_calls=image_calls,
                on_progress=lambda m: print(f"  [cse-img] {m}", file=sys.stderr)):
            if len(images) >= img_limit:
                break
            uri = _fetch_thumb(r.get("image")) if r.get("image") else None
            if uri and uri not in have:
                have.add(uri)
                images.append(uri)
                img_meta.append({"data": uri, "title": (r.get("title") or "")[:90],
                                 "host": r.get("host", "")})
    except Exception as e:
        print(f"  [cse-img] enrichment skipped: {e}", file=sys.stderr)

    # top public results: only links carrying the handle, one clean url per registrable domain.
    # We KEEP search-shape links (/search/<handle>) — Google surfaced them for her handle, and no
    # URL pattern tells a real search page from an empty one; only a human opening it can. The sole
    # drop authority is top_drop.txt (verified-empty results). Dropping BEFORE the per-domain dedup
    # so an empty URL never consumes the slot a real URL on the same host could take.
    top, seen = [], set()
    for r in results:
        link = r.get("link", "")
        if not any(t in _norm(link) for t in ntoks):
            continue
        if canon_url(link) in drop:
            continue
        rd = registrable_domain(link)
        if not rd or rd in seen:
            continue
        seen.add(rd)
        top.append(link)
        if len(top) >= top_n:
            break

    return {
        "google_total": str(total or ""),
        "n_sites": len(sites),
        "n_results": len(results),
        "images": images,
        "img_meta": img_meta,
        "sites": sites,
        "top_leaks": top,
        "query": queries[0],
        "errors": errors,
    }, results


def main():
    ap = argparse.ArgumentParser(description="Build the report's cse.json headlessly.")
    ap.add_argument("--name", required=True, help="Display name, e.g. 'Sophie Rain'.")
    ap.add_argument("--strong", required=True, help="Comma handle tokens; first = primary handle.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--raw", default=None,
                    help="Raw results out (default: <out> with .cse.json -> .cse.raw.json). "
                         "Holds title/link/snippet per hit; powers build_google_shots' web-results screenshot.")
    ap.add_argument("--max-calls", type=int, default=15)
    ap.add_argument("--image-calls", type=int, default=6,
                    help="Dedicated searchType=image calls (nude leaks / onlyfans leaks / porn "
                         "videos) to enrich the leak-image thumbnails. 0 = web thumbnails only.")
    ap.add_argument("--top-drop", default=TOP_DROP,
                    help="verified-empty result URLs to drop from top_leaks (default: ./top_drop.txt)")
    args = ap.parse_args()
    load_env()
    tokens = [t.strip() for t in args.strong.split(",") if t.strip()]
    drop = load_top_drop(args.top_drop)
    cse, results = build(args.name, tokens, max_calls=args.max_calls, drop=drop,
                         image_calls=args.image_calls)
    json.dump(cse, open(args.out, "w", encoding="utf-8"), ensure_ascii=False)
    raw_out = args.raw or (args.out[:-len(".cse.json")] + ".cse.raw.json"
                           if args.out.endswith(".cse.json") else args.out + ".raw.json")
    json.dump({"query": cse["query"], "google_total": cse["google_total"], "results": results},
              open(raw_out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"{args.out}: google_total={cse['google_total']} | {cse['n_sites']} sites | "
          f"{len(cse['images'])} thumbs | {len(cse['top_leaks'])} top results "
          f"({len(drop)} verified-empties honored) (+raw -> {raw_out})")


if __name__ == "__main__":
    main()

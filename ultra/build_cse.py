#!/usr/bin/env python3
"""
build_cse.py — generate the `<prefix>.cse.json` the report's "Also all over Google"
section needs, HEADLESSLY via the Google CSE API (GOOGLE_API_KEY / GOOGLE_CSE_ID in
.env — no browser, no Incogniton).

Multi-seed widening (cse_search_wide) surfaces the sites Google indexes the creator
on; thumbnails are downloaded and base64-embedded so the report stays self-contained
and encryptable. top_leaks is curated: only links whose URL carries the handle, one
clean url per registrable domain.

    python3 build_cse.py --name "Jane Doe" --strong "janedoee,janedoe" \
        --out janedoee.cse.json [--max-calls 15]
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


def _alias_group(tokens, cap=3):
    """OR-group up to `cap` distinct alias spellings → '(a OR b OR c)'. One call then
    covers every spelling: as long as ONE alias is the spelling Google indexes, a
    keyword seed built on the group returns results even when the primary handle is a
    near-miss — and the union surfaces sites indexed under a DIFFERENT handle. Returns
    the bare handle when there's only one alias (so single-alias scans are unchanged)."""
    seen = []
    for t in tokens:
        t = (t or "").strip()
        if not t:
            continue
        tq = f'"{t}"' if " " in t else t     # quote multi-word aliases so the OR groups cleanly
        if tq not in seen:
            seen.append(tq)
        if len(seen) >= cap:
            break
    if not seen:
        return ""
    return f'({" OR ".join(seen)})' if len(seen) > 1 else seen[0]


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


def build(name, tokens, max_calls=15, img_limit=40, top_n=12, drop=None, image_calls=6, early_out=None):
    handle = tokens[0]
    grp = _alias_group(tokens)         # '(alias1 OR alias2 OR alias3)' — covers every spelling in one call
    cse_scanner.reset_calls()          # zero the billed-query meter for this run
    if drop is None:
        drop = load_top_drop(TOP_DROP)
    ntoks = [_norm(t) for t in tokens if _norm(t)]
    queries = [
        f'"{handle}" (onlyfans leaks OR nude OR leaks)',
        f'{grp} leaked', f'{grp} nude', f'{grp} onlyfans',
        f'leaks {grp}', f'porn {grp}', f'"{name}" leaked nude',
    ]
    # mutable state so the two _snap phases (fast-paint, final) share the same growing thumbnail set.
    images, img_meta, have = [], [], set()
    sites, top, total = [], [], None

    def _snap():
        return {"google_total": str(total or ""), "n_sites": len(sites), "n_results": len(images),
                "images": images, "img_meta": img_meta, "sites": sites, "top_leaks": top,
                "query": queries[0]}

    def _write_early(tag):
        if not early_out:
            return
        try:
            json.dump(_snap(), open(early_out, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"  [cse] {tag}: {len(img_meta)} thumb(s) live -> {os.path.basename(early_out)}",
                  file=sys.stderr)
        except Exception as e:
            print(f"  [cse] {tag} skipped: {e}", file=sys.stderr)

    def _keep_uri(uri, r):
        if uri and uri not in have:
            have.add(uri)
            images.append(uri)
            img_meta.append({"data": uri, "title": (r.get("title") or "")[:90],
                             "host": r.get("host", "")})
            return True
        return False

    def _add_images(rows):
        for r in rows:
            if len(images) >= img_limit:
                break
            _keep_uri(_fetch_thumb(r.get("image")) if r.get("image") else None, r)

    def _add_images_fast(rows, flush_every=2):
        """Fast-paint variant: download the thumbnails CONCURRENTLY (not one-at-a-time behind a 15s
        timeout each) and re-write cse.json every couple that land — so the live wall paints its first
        real CSE leak tiles within a second or two of the image search returning, instead of after all
        ~20 thumbnails have downloaded serially. Order-independent; fully guarded by the caller."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        rows = [r for r in rows if r.get("image")][: max(0, img_limit - len(images))]
        if not rows:
            return
        landed = 0
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(_fetch_thumb, r["image"]): r for r in rows}
            for fut in as_completed(futs):
                if len(images) >= img_limit:
                    break
                try:
                    uri = fut.result()
                except Exception:
                    uri = None
                if _keep_uri(uri, futs[fut]):
                    landed += 1
                    if landed % flush_every == 0:
                        _write_early("fast first-paint (streaming)")

    # ── FAST FIRST PAINT ─────────────────────────────────────────────────────────────────────
    # ONE quick image-search cycle (searchType=image) BEFORE the 15 web calls → real Google-indexed
    # leak thumbnails written to cse.json in a few seconds, so the live wall shows images almost
    # immediately instead of after the whole CSE run. Thumbnails download in PARALLEL with an
    # incremental write, so the wall paints its first tiles as soon as the FIRST couple land (not after
    # all 20 download behind a serial 15s-timeout each). FULLY GUARDED — any failure just falls through
    # to the normal flow below (never breaks the step).
    if early_out:
        try:
            _add_images_fast(cse_scanner.cse_image_search(
                [f"{grp} nude leaks", f"{grp} onlyfans leaks"], max_calls=2,
                on_progress=lambda m: print(f"  [cse-fast] {m}", file=sys.stderr)))
            _write_early("fast first-paint")
        except Exception as e:
            print(f"  [cse-fast] first-paint skipped: {e}", file=sys.stderr)

    # ── full web search (sites + top public results + more thumbnails) ───────────────────────
    results, total = cse_scanner.cse_search_wide(
        queries, max_calls=max_calls,
        on_progress=lambda m: print(f"  [cse] {m}", file=sys.stderr))
    sites = [{"domain": s["domain"], "url": s.get("url", ""), "occ": s.get("occurrences", 0)}
             for s in cse_scanner.summarize_cse(results)]
    seen = set()
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
    _add_images(results)          # web pagemap thumbnails
    _write_early("web snapshot")  # now with sites + top too

    # Dedicated IMAGE search enrichment → MORE Google-indexed leak thumbnails. FULLY GUARDED.
    try:
        _add_images(cse_scanner.cse_image_search(
            [f"{grp} nude leaks", f"{grp} onlyfans leaks", f"{grp} porn videos"],
            max_calls=image_calls,
            on_progress=lambda m: print(f"  [cse-img] {m}", file=sys.stderr)))
    except Exception as e:
        print(f"  [cse-img] enrichment skipped: {e}", file=sys.stderr)

    out = _snap()
    out["n_results"] = len(results)
    out["cse_calls"] = cse_scanner.calls_spent()
    # EXACT billed-query count for this run (ceiling is 23: 2 fast-paint + up to 15 web + up to 6 image)
    print(f"  [cse] CSE spent: {cse_scanner.calls_spent()} Google queries this run", file=sys.stderr)
    return out, results


def main():
    ap = argparse.ArgumentParser(description="Build the report's cse.json headlessly.")
    ap.add_argument("--name", required=True, help="Display name, e.g. 'Jane Doe'.")
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
    # early_out=args.out → build() publishes the web-result thumbnails to cse.json ~half the scan
    # sooner (the live wall seeds from them); this final dump then overwrites with the complete set.
    cse, results = build(args.name, tokens, max_calls=args.max_calls, drop=drop,
                         image_calls=args.image_calls, early_out=args.out)
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

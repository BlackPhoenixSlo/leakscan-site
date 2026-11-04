#!/usr/bin/env python3
"""
export_dmca.py — turn crawl + variant (+ optional search) results into paste-ready
DMCA export files, bucketed by confidence, ready to feed a later takedown-download step.

Buckets (devil's-advocate 3-tier model):
  LIKELY  — handle appears in the media URL or source-page slug  -> live_for_dmca_form.txt
  POSSIBLE— handle only on the page / in a search title/snippet   -> verify_first_name_on_page.txt
  (media direct URLs kept as a secondary file; dedup GROUPS by site, never deletes URLs)

    python3 export_dmca.py --crawl tarita.crawl.json --variants tarita.variants.json \
        --name "Ivette Aguero Tarazona" --aliases taritafit,ivetteaguero,tarita.fit \
        --slug taritafit --out-dir exports

Writes exports/<slug>_<stamp>/  (stamp via --stamp, default 'latest' since time is unavailable).
"""
import argparse, glob, json, os, re
from netloc import registrable_domain, norm_url, is_lowvalue_subdomain, echo_only_domains

CHUNK = 400


def un(u): return re.sub(r"[^a-z0-9]", "", (u or "").lower())


def load(path):
    if not path or not os.path.exists(path):
        return None
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return None


def load_lines(path):
    if not path or not os.path.exists(path):
        return []
    return [ln.strip() for ln in open(path, encoding="utf-8")
            if ln.strip().startswith("http")]


def has_tok(url, tokens):
    n = un(url)
    return any(t in n for t in tokens)


def main():
    ap = argparse.ArgumentParser(description="Bucket leak URLs into paste-ready DMCA export files.")
    ap.add_argument("--crawl")
    ap.add_argument("--variants")
    ap.add_argument("--search", help="Optional web_search.py json (has bucket=likely/possible).")
    ap.add_argument("--google-links", help="Optional google_shots.py links file (source-page URLs, "
                    "one per line) — the handle/name-carrying ones join LIKELY/POSSIBLE.")
    ap.add_argument("--name", default="")
    ap.add_argument("--strong", default="taritafit,taritafitness",
                    help="Handle tokens that AUTO-confirm LIKELY (name in URL is unambiguous).")
    ap.add_argument("--name-tokens", default="ivetteaguero,aguerotarazona,ivettetarazona",
                    help="Legal-name tokens: URL match => POSSIBLE only (catch-all sites reflect these into /model/<slug>/).")
    ap.add_argument("--aliases", default="", help="(kept for the report label; not used for classification)")
    ap.add_argument("--slug", default="client")
    ap.add_argument("--stamp", default="latest")
    ap.add_argument("--out-dir", default="exports")
    ap.add_argument("--triage", help="slug_triage.py triage.json — suppress its DROP domains "
                    "(search page echoes AND crawl found 0 handle-carrying files, e.g. xxbrits). "
                    "Crawl-confirmed real hosts are never DROP, so their media always passes.")
    args = ap.parse_args()

    strong = [un(a) for a in args.strong.split(",") if un(a)]
    names = [un(a) for a in args.name_tokens.split(",") if un(a)]
    # each record: {url, media_url, domain, bucket, reason, source, discovered_by}
    likely, possible, media = {}, {}, {}   # keyed by norm_url

    # Domains slug_triage marked DROP = its search page echoes AND the crawl found ZERO
    # handle-carrying media there. Such a domain hosts nothing of hers, so suppress every URL
    # from it (an echo /search/<handle> URL otherwise auto-buckets LIKELY via has_tok). A
    # crawl-confirmed host (leakgallery) is REVIEW, never DROP, so its 589 files pass untouched.
    echo_domains, suppressed = set(), [0]
    if args.triage and os.path.exists(args.triage):
        echo_domains = echo_only_domains(args.triage)

    def add(bucket, url, *, source_page="", reason="", by=""):
        if not url:
            return
        if echo_domains and registrable_domain(url) in echo_domains:
            suppressed[0] += 1
            return
        key = norm_url(url)
        rec = {"url": url, "source_page": source_page, "domain": registrable_domain(url),
               "reason": reason, "discovered_by": by, "bucket": bucket}
        (likely if bucket == "LIKELY" else possible).setdefault(key, rec)

    def bucket_for(url):
        """LIKELY iff a strong handle token is in the URL; POSSIBLE if only a legal-name
        token (catch-all sites reflect the name into the path); else None."""
        if has_tok(url, strong):
            return "LIKELY"
        if has_tok(url, names):
            return "POSSIBLE"
        return None

    crawl = load(args.crawl) or []
    # A domain is CONFIRMED-hosting only if it serves a MEDIA file whose URL carries the
    # handle. Catch-all sites (jjgirls) reflect the searched slug into a /model/<slug>/ PAGE
    # url but serve unrelated media -> they never become confirmed, so their pages can't be
    # auto-LIKELY (they fall to POSSIBLE for manual review).
    confirmed_domains = set()
    for r in crawl:
        for m in r.get("media", []):
            if has_tok(m, strong):
                confirmed_domains.add(registrable_domain(m))

    for r in crawl:
        for p in r.get("pages", []):
            if has_tok(p, strong) and registrable_domain(p) in confirmed_domains:
                add("LIKELY", p, reason="handle in page URL on a confirmed-hosting site", by="crawl")
            elif bucket_for(p):   # strong-but-unconfirmed or legal-name-only -> verify
                add("POSSIBLE", p, reason="handle/name in page URL, host not media-confirmed (verify)", by="crawl")
        pairs = r.get("media_pairs", []) or [[m, ""] for m in r.get("media", [])]
        for m, src in pairs:
            if has_tok(m, strong):
                media.setdefault(norm_url(m), {"url": m, "source_page": src,
                                               "domain": registrable_domain(m), "discovered_by": "crawl"})
                add("LIKELY", m, source_page=src, reason="handle in media URL", by="crawl")
            elif src and has_tok(src, strong) and registrable_domain(src) in confirmed_domains:
                add("LIKELY", src, reason="handle in source page URL on a confirmed-hosting site", by="crawl")
            elif src and bucket_for(src):
                add("POSSIBLE", src, reason="name in source page URL (verify)", by="crawl")

    for v in (load(args.variants) or []):
        add("LIKELY", v.get("url", ""), reason=f"verified {v.get('kind','variant')} ({v.get('title','')[:40]})",
            by="variant-expansion")

    for s in (load(args.search) or []):
        b = "LIKELY" if s.get("bucket") == "likely" else "POSSIBLE"
        add(b, s.get("url", ""), reason=f"{s.get('engine','search')}: {s.get('bucket','')}",
            by="search")

    # google_shots' one-pass source links — only bucket the ones that actually carry the
    # handle/name (generic google-tile hosts like pornhub/tiktok are too noisy to bucket blind).
    for u in load_lines(args.google_links):
        b = bucket_for(u)
        if b:
            add(b, u, reason="google-surfaced source page", by="google")

    # a URL in POSSIBLE that's already LIKELY -> drop from possible
    for k in list(possible):
        if k in likely:
            del possible[k]

    stamp_dir = os.path.join(args.out_dir, f"{args.slug}_{args.stamp}")
    os.makedirs(stamp_dir, exist_ok=True)

    def write_chunked(base, urls):
        urls = list(dict.fromkeys(urls))
        # stamp_dir is REUSED across runs (stamp defaults to 'latest', exist_ok=True). A smaller
        # re-run overwrites base.txt but would otherwise leave higher-numbered *_part*.txt from a
        # larger prior run on disk — a user pasting the chunk files would submit STALE URLs. Clear
        # this base's chunk files first so the export always reflects exactly this run.
        for stale in glob.glob(os.path.join(stamp_dir, f"{base}_part*.txt")):
            os.remove(stale)
        with open(os.path.join(stamp_dir, base + ".txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(urls) + ("\n" if urls else ""))
        if len(urls) > CHUNK:
            for i in range(0, len(urls), CHUNK):
                part = urls[i:i + CHUNK]
                with open(os.path.join(stamp_dir, f"{base}_part{i//CHUNK+1}.txt"), "w", encoding="utf-8") as fh:
                    fh.write("\n".join(part) + "\n")
        return urls

    likely_urls = write_chunked("live_for_dmca_form", [r["url"] for r in likely.values()])
    possible_urls = write_chunked("verify_first_name_on_page", [r["url"] for r in possible.values()])
    media_urls = write_chunked("direct_media_urls", [r["url"] for r in media.values()])

    # machine-readable sidecar (one json record per line) for the later download step
    with open(os.path.join(stamp_dir, "metadata.jsonl"), "w", encoding="utf-8") as fh:
        for r in list(likely.values()) + list(possible.values()):
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # human-readable EXPORT.txt grouped by registrable domain
    def grouped(records):
        by = {}
        for r in records:
            by.setdefault(r["domain"], []).append(r["url"])
        lines = []
        for d in sorted(by, key=lambda x: -len(by[x])):
            lines.append(f"\n# {d} ({len(by[d])})")
            lines += sorted(set(by[d]))
        return "\n".join(lines)

    with open(os.path.join(stamp_dir, "EXPORT.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"DMCA EXPORT — {args.name or args.slug}\n")
        fh.write(f"aliases: {args.aliases}\n")
        fh.write(f"{len(likely_urls)} LIKELY (DMCA-ready) · {len(possible_urls)} POSSIBLE (verify first) · "
                 f"{len(media_urls)} direct media URLs\n")
        fh.write("\n" + "=" * 60 + "\nA) LIKELY — paste into the DMCA form (live_for_dmca_form.txt)\n" + "=" * 60 + "\n")
        fh.write(grouped(likely.values()))
        fh.write("\n\n" + "=" * 60 + "\nB) POSSIBLE — verify her name on the page first (verify_first_name_on_page.txt)\n" + "=" * 60 + "\n")
        fh.write(grouped(possible.values()))
        fh.write("\n")

    print(f"EXPORT -> {stamp_dir}/")
    print(f"  LIKELY (DMCA-ready): {len(likely_urls)}  ->  live_for_dmca_form.txt"
          + (f" (+{(len(likely_urls)-1)//CHUNK} extra chunk files)" if len(likely_urls) > CHUNK else ""))
    print(f"  POSSIBLE (verify)  : {len(possible_urls)}  ->  verify_first_name_on_page.txt")
    print(f"  direct media URLs  : {len(media_urls)}  ->  direct_media_urls.txt")
    print(f"  metadata sidecar   : metadata.jsonl  |  human summary: EXPORT.txt")
    if echo_domains:
        print(f"  triage             : suppressed {suppressed[0]} URL(s) from {len(echo_domains)} "
              f"echo-only domain(s) (search echoes + crawl 0)")


if __name__ == "__main__":
    main()

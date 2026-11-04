#!/usr/bin/env python3
"""seed_url_crawl.py — class-3 recovery: DIRECT-fetch the discovered profile URLs the deep crawl
collected 0 media from, and merge the results into the crawl json.

The deep crawl learns slugs off a domain's own check page and builds URLs from the registry
template. That misses hosts whose real profile path differs from the template (masterfap
/profile/…), whose fetch transiently failed, or that aren't in the map at all (herleaks.com).
For those, the discovery stages already hold the EXACT working URL — so here we just fetch it,
extract media with the crawler's own extractor, and write a crawl record. Gated to a
HUMAN-confirmed keep-file (recovery_keep.txt) so we only ever fetch domains a human vision-
confirmed host HER — never a blanket sweep of everything discovery surfaced.

Media source page = the fetched profile URL (carries the handle), so clean_crawl --keep-file
provenance-keeps them. Idempotent: only (re)writes records for keep-file domains with 0 media.

    python3 seed_url_crawl.py --campaign juliafilippo --keep-file campaigns/juliafilippo/recovery_keep.txt
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import leak_crawler as lc
import discovery_seed as ds
from clean_crawl import bad as cc_bad, host_reg as cc_host_reg, load_block
from recovery_demo import _is_chrome
from leak_evidence import url_shape
from netloc import registrable_domain, newest_path
from slug_probe import build_target, load_tokens

HERE = os.path.dirname(os.path.abspath(__file__))


def discovered_urls_by_domain(campaign, strong, names):
    """{registrable_domain: [profile URLs]} from the discovery artifacts (same harvest as the seed)."""
    cdir = os.path.join(HERE, "campaigns", campaign)
    out = {}
    for u in ds._iter_source_urls(cdir, campaign):
        if url_shape(u) != "profile" or not ds._slug_from_url(u, strong, names):
            continue
        out.setdefault(registrable_domain(u), [])
        if u not in out[registrable_domain(u)]:
            out[registrable_domain(u)].append(u)
    return out


def fetch_media(url, strong, blocked, timeout=10):
    """Fetch one profile URL, return its content media (trap/theme/block/chrome filtered)."""
    try:
        st, fu, html = lc.fetch(url, timeout)
        if st != 200:
            return st, []
        _, media = lc.extract_urls(url, html)
        med = [m for m in media
               if not (cc_bad(m) or cc_host_reg(m) in blocked or _is_chrome(m))]
        return st, med
    except Exception as e:
        return f"ERR {e}", []


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--campaign", required=True)
    ap.add_argument("--keep-file", default=None,
                    help="per-campaign recovery_keep.txt additions (the GLOBAL recovery_hosts.txt "
                         "clean-host allowlist is always loaded too)")
    ap.add_argument("--crawl", default=None, help="crawl json to merge into (default newest campaign crawl)")
    ap.add_argument("--tokens", default="")
    ap.add_argument("--name", default="")
    ap.add_argument("--per-domain", type=int, default=6, help="max profile URLs to fetch per domain")
    ap.add_argument("--block-file", default=os.path.join(HERE, "fake_aggregators.txt"))
    ap.add_argument("--timeout", type=int, default=10)
    a = ap.parse_args()

    pre = a.campaign
    cdir = os.path.join(HERE, "campaigns", pre)
    crawl_f = a.crawl or newest_path(os.path.join(cdir, f"{pre}.crawl.json"), f"{pre}.crawl.json")
    data = json.load(open(crawl_f, encoding="utf-8"))
    tokens = load_tokens(pre, a.tokens)
    strong, names = build_target(tokens, a.name)
    keep = load_block(os.path.join(HERE, "recovery_hosts.txt"), "") | load_block(a.keep_file or "", "")
    blocked = load_block(a.block_file, "")

    by_dom = discovered_urls_by_domain(pre, strong, names)
    have = {r.get("domain", "") for r in data if isinstance(r, dict) and (r.get("media") or [])}
    # class-3 targets: keep-file domains that the crawl collected 0 media from
    targets = {d: by_dom[d][: a.per_domain] for d in by_dom
               if (d in keep or ".".join(d.split(".")[-2:]) in keep) and d not in have}
    if not targets:
        print("seed_url_crawl: no class-3 keep-file domains need fetching (all already have media)")
        return

    print(f"seed_url_crawl: fetching {sum(len(v) for v in targets.values())} URL(s) "
          f"across {len(targets)} keep-file domain(s)…", file=sys.stderr)

    def do_domain(item):
        dom, urls = item
        media, pairs, pages = [], [], []
        seen = set()
        for u in urls:
            st, med = fetch_media(u, strong, blocked, a.timeout)
            if med:
                pages.append(u)
            for m in med:
                if m not in seen:
                    seen.add(m)
                    media.append(m)
                    pairs.append([m, u])
        return dom, {"domain": dom, "method": "seed-url", "slugs": sorted({tokens[0]} if tokens else set()),
                     "pages": pages, "media": media, "media_pairs": pairs, "slug_detail": []}

    results = dict(ThreadPoolExecutor(max_workers=8).map(do_domain, targets.items()))

    # merge: replace an existing (empty) record for the domain, else append
    idx = {r.get("domain", ""): i for i, r in enumerate(data) if isinstance(r, dict)}
    added = 0
    for dom, rec in results.items():
        if not rec["media"]:
            print(f"  {dom}: 0 media (fetch failed / empty) — skipped", file=sys.stderr)
            continue
        if dom in idx:
            data[idx[dom]] = rec
        else:
            data.append(rec)
        added += len(rec["media"])
        print(f"  {dom}: +{len(rec['media'])} media from {len(rec['pages'])} page(s)", file=sys.stderr)

    json.dump(data, open(crawl_f, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"seed_url_crawl: merged {added} media into {crawl_f}")


if __name__ == "__main__":
    main()

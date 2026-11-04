#!/usr/bin/env python3
"""discovery_seed.py — feed profile URLs found by the discovery stages into the CRAWL FRONTIER.

The crawler discovers on-site slugs by fetching each domain's own check page and reading the
links off it. That fails on a site whose check page is a JS-rendered SEARCH grid that only
ECHOES the query (fapello.com/search/{handle}) — the real profile lives at a DISPLAY-NAME slug
the handle never spells (fapello.com/julia-filippo-58/), and it is only ever surfaced by the
Google-index stages (CSE / web search), which run AFTER the crawl. So those profile URLs sit in
the search artifacts, unused, and the domain looks empty to the crawl + triage. That is exactly
how https://fapello.com/julia-filippo-58/ was missed.

This module harvests every PROFILE-shape URL the discovery artifacts already carry, groups them
by registrable domain, and turns each into the on-site slug (the handle-carrying path segment,
page-number tail dropped). It then:

  • merges those slugs into slugs_cache.json — the frontier memory leak_crawler already loads —
    and writes campaigns/<c>/<c>.seed_slugs.json (auditable, and passed to `--seed-slugs`);
  • so the next crawl VISITS the real profile pages, and its Q1 sibling probe walks the numbered
    family (…-1..-N) to fill gaps + reach re-uploads (–58) the discovery snapshot never listed.

Same harvest also backs slug_triage's domain-hit guard (harvest_hits): a domain with N direct
profile URLs must never be DROPped on its search-page echo verdict.

    python3 discovery_seed.py --campaign juliafilippo --tokens julia.filippo,juliafilippo
"""
import argparse
import json
import os
import re
import sys
from urllib.parse import urlparse

from leak_evidence import url_shape, norm
from netloc import registrable_domain, canon_url, newest_path
from leak_crawler import bad_slug_seg
from slug_probe import build_target, load_tokens

HERE = os.path.dirname(os.path.abspath(__file__))

# discovery artifacts that carry candidate URLs (json → key list, or one-URL-per-line text)
_JSON_SOURCES = (
    "{p}.search.json",       # web_search.py — list[{url,...}]
    "{p}.cse.raw.json",      # cse_scanner — {results:[{link,...}]}
    "{p}.cse.json",          # build_cse — {results:[...]} or list
    "{p}-scan.json",         # leak_scanner — list[{url,...}]
    "{p}.variants.json",     # expand_variants — list[{url,...}]
)
_TEXT_SOURCES = (
    "{p}.search.links.txt",
    "{p}.google_links.txt",
    "{p}.variants.links.txt",
    "{p}-scan.links.txt",
)


def _urls_from_json(obj):
    """Yield candidate URLs from any of the json artifact shapes."""
    recs = obj.get("results", obj) if isinstance(obj, dict) else obj
    if not isinstance(recs, list):
        return
    for r in recs:
        if isinstance(r, str):
            yield r
        elif isinstance(r, dict):
            u = r.get("url") or r.get("link") or r.get("href")
            if u:
                yield u


def _iter_source_urls(cdir, prefix):
    """Yield every candidate URL across all present discovery artifacts (root or campaigns/)."""
    for tmpl in _JSON_SOURCES:
        name = tmpl.format(p=prefix)
        f = newest_path(os.path.join(cdir, name), os.path.join(HERE, name))
        if not f or not os.path.exists(f):
            continue
        try:
            obj = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        yield from _urls_from_json(obj)
    for tmpl in _TEXT_SOURCES:
        name = tmpl.format(p=prefix)
        f = newest_path(os.path.join(cdir, name), os.path.join(HERE, name))
        if not f or not os.path.exists(f):
            continue
        try:
            for ln in open(f, encoding="utf-8"):
                u = ln.strip().split("\t")[0].strip()
                if u.startswith("http"):
                    yield u
        except Exception:
            continue


def _seg_carries_handle(seg, strong, names):
    """True when a path SEGMENT is the creator's slug — the same evidence bar as triage's
    _url_is_target: a strong (>=8ch) handle substring, or >=2 name tokens. A single first
    name ('julia') is NOT enough (it could be a different person)."""
    n = norm(seg)
    if not n:
        return False
    if any(s in n for s in strong):
        return True
    return len(names) >= 2 and sum(1 for nm in names if nm in n) >= 2


def _slug_from_url(url, strong, names):
    """The on-site slug for a profile URL — the handle-carrying path segment, page-number
    tail dropped (…/julia-filippo-55/3 → 'julia-filippo-55'). None if no segment qualifies."""
    try:
        path = urlparse(url).path
    except ValueError:
        return None
    for seg in (s for s in path.split("/") if s):
        if seg.isdigit() or bad_slug_seg(seg):
            continue
        if re.search(r"\d{4,}$", seg):        # post-id tail (husvjjal-289520), not a slug
            continue
        if _seg_carries_handle(seg, strong, names):
            return seg
    return None


def harvest(cdir, prefix, strong, names):
    """Return (slugs_by_domain, hits_by_domain).

    slugs_by_domain: {registrable_domain: sorted[slug]}   — for the crawl frontier
    hits_by_domain:  {registrable_domain: count}          — distinct profile URLs (triage guard)
    """
    slugs, hits, seen = {}, {}, {}
    for url in _iter_source_urls(cdir, prefix):
        if url_shape(url) != "profile":       # search/tag/google shapes carry no on-site slug
            continue
        dom = registrable_domain(url)
        if not dom:
            continue
        slug = _slug_from_url(url, strong, names)
        if not slug:
            continue
        key = canon_url(url)
        seen.setdefault(dom, set())
        if key not in seen[dom]:
            seen[dom].add(key)
            hits[dom] = hits.get(dom, 0) + 1
        slugs.setdefault(dom, set()).add(slug)
    return ({d: sorted(v) for d, v in slugs.items()},
            hits)


def harvest_hits(campaign, strong, names, cdir=None):
    """Just {registrable_domain: distinct-profile-URL count} — for slug_triage's domain guard."""
    cdir = cdir or os.path.join(HERE, "campaigns", campaign)
    return harvest(cdir, campaign, strong, names)[1]


def _merge_cache(cache_path, slugs_by_domain):
    """Union the harvested slugs into slugs_cache.json (the crawler's frontier memory).
    Non-destructive: only adds; never drops another campaign's slugs."""
    cache = {}
    if os.path.exists(cache_path):
        try:
            cache = json.load(open(cache_path, encoding="utf-8"))
        except Exception:
            cache = {}
    added = 0
    for d, sl in slugs_by_domain.items():
        before = set(cache.get(d, []))
        after = before | set(sl)
        added += len(after) - len(before)
        cache[d] = sorted(after)
    try:
        json.dump(cache, open(cache_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    except Exception as e:
        print(f"(could not write slug cache: {e})", file=sys.stderr)
        return 0
    return added


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--campaign", required=True, help="prefix, e.g. juliafilippo")
    ap.add_argument("--name", default="", help="display name (adds name tokens)")
    ap.add_argument("--tokens", default="", help="extra comma handle tokens (beyond the alias file)")
    ap.add_argument("--out", default=None, help="seed file (default campaigns/<c>/<c>.seed_slugs.json)")
    ap.add_argument("--cache", default=os.path.join(HERE, "slugs_cache.json"))
    ap.add_argument("--no-cache", action="store_true", help="don't merge into slugs_cache.json")
    a = ap.parse_args()

    pre = a.campaign
    cdir = os.path.join(HERE, "campaigns", pre)
    tokens = load_tokens(pre, a.tokens)
    strong, names = build_target(tokens, a.name)
    if not strong and not names:
        ap.error(f"no handle tokens for {pre} (need --tokens or an alias file)")

    slugs_by_domain, hits = harvest(cdir, pre, strong, names)
    out = a.out or os.path.join(cdir, f"{pre}.seed_slugs.json")
    outdir = os.path.dirname(out)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    json.dump(slugs_by_domain, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)

    n_slugs = sum(len(v) for v in slugs_by_domain.values())
    print(f"seed: {n_slugs} profile slug(s) across {len(slugs_by_domain)} domain(s) -> {out}")
    for d in sorted(slugs_by_domain, key=lambda d: -len(slugs_by_domain[d]))[:8]:
        print(f"   {d}: {', '.join(slugs_by_domain[d][:6])}"
              f"{' …' if len(slugs_by_domain[d]) > 6 else ''}  ({hits.get(d,0)} url(s))")
    if not a.no_cache:
        added = _merge_cache(a.cache, slugs_by_domain)
        print(f"   slug cache: +{added} new slug(s) merged into {os.path.basename(a.cache)}")


if __name__ == "__main__":
    main()

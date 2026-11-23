#!/usr/bin/env python3
"""title_aliases.py — harvest a creator's REAL aliases from aggregator page TITLES.

The combinatorial generator (username_variations.py) only ever emits near-misses of
a handle you already know: examplexo → examplexo1, examplexo_x, … It can NEVER
produce an unrelated re-upload handle the creator actually used — `qzv1p`,
`glad.qzvk`, `aliasone`. Those are unguessable.

But the big leak aggregators PRINT them, side by side, in the profile page <title>:

    fapello.com/examplelee-xo/  → "aliasone / examplelee.xo / qzv1p Nude Leaks OnlyFans - Fapello"
    fapello.com/examplexo/   → "Examplexo / glad.qzvk / examplelee.xo Nude Leaks OnlyFans - Fapello"
    nudogram …                 → "aliasone / examplelee.xo / qzv1p Nude Leaks OnlyFans Page 2 - Nudogram v2.1"
    masterfap …                → "Examplelee Xo Free Onlyfans 468 Nude Leaked Pictures | MasterFap.net"

So AT THE START of a scan we fetch a handful of aggregator profile pages, read the
title, split on the ' / ' the sites use to list every alias they know, strip the
"Nude Leaks OnlyFans - Site" boilerplate tail, and recover the real handles. Those
seed the alias list BEFORE username_variations expands them — so the scan chases
qzv1p's re-uploads too, not just examplexo's.

    python3 title_aliases.py --handle examplexo
    python3 title_aliases.py https://fapello.com/examplelee-xo/ https://nudogram.com/models/examplelee-xo/
    python3 title_aliases.py --handle examplexo --json

Importable: `from title_aliases import harvest_aliases, aliases_from_title`.
"""
import argparse
import concurrent.futures
import os
import re
import sys
import urllib.parse

from leak_crawler import fetch

# ---------------------------------------------------------------- title parsing
# Words the aggregators glue onto the last alias / after the name — everything from
# the first one onward in a segment is boilerplate, not part of a handle.
BOILERPLATE = {
    "nude", "nudes", "naked", "leak", "leaks", "leaked", "onlyfans", "of", "fansly",
    "free", "vip", "premium", "pictures", "picture", "pics", "pic", "photos", "photo",
    "images", "image", "gallery", "album", "albums", "video", "videos", "vids", "clip",
    "clips", "porn", "porno", "sex", "xxx", "nsfw", "profile", "model", "models",
    "page", "content", "collection", "download", "watch", "online", "full", "set",
    "sets", "new", "latest", "trending", "reddit", "telegram", "mega", "folder",
    "exclusive", "official", "hot", "best", "top", "viral", "uncensored",
}
# Site-name tails that follow the last " - " / " | " separator.
SITE_TAIL_RE = re.compile(
    r"\s*[-|–—]\s*(?:fapello|nudogram|thefap|masterfap|fapeza|leakgallery|"
    r"thotslife|thothub|coomer|erome|fapachi|nudostar|hotgirl|internetchicks|"
    r"famousinternetgirls|[\w.]+\.(?:com|net|org|to|tv|cc|io|xyz|v[\d.]+))\b.*$",
    re.I,
)
# last char may be alnum OR '_' — a trailing underscore is a real handle char (creatorj_).
ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,57}[A-Za-z0-9_]$")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
OGTITLE_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\']og:title["\'][^>]+content=["\'](.*?)["\']', re.I)


def _valid_alias(tok):
    """A handle-shaped token that isn't pure boilerplate/number."""
    tok = tok.strip().strip(".-")        # trim stray end dots/hyphens; KEEP a real trailing '_'
    if not tok or not ALIAS_RE.match(tok):
        return None
    if tok.lower() in BOILERPLATE or tok.isdigit():
        return None
    if not re.search(r"[a-z]", tok, re.I):        # need at least one letter
        return None
    return tok


def aliases_from_title(title):
    """Extract the real alias handles a leak-aggregator title lists.

    'aliasone / examplelee.xo / qzv1p Nude Leaks OnlyFans - Fapello'
        → ['aliasone', 'examplelee.xo', 'qzv1p']
    Handles both the ' / '-delimited multi-alias form and the single-name form
    ('Examplelee Xo Free Onlyfans 468 Nude Leaked Pictures | MasterFap.net'
        → ['Examplelee Xo'] as a joined name candidate)."""
    if not title:
        return []
    # Gate: a genuine leak-profile title always appends a boilerplate marker
    # ("… Nude Leaks OnlyFans", "… Nude Leaked Pictures"). Requiring one rejects
    # challenge/blocked/homepage titles ("Just A Moment…", "Home - Fapello") that
    # would otherwise yield junk handles.
    if not any(w in BOILERPLATE for w in re.findall(r"[a-z]+", title.lower())):
        return []
    t = re.sub(r"\s+", " ", title).strip()
    t = SITE_TAIL_RE.sub("", t)                    # drop " - Fapello" / " | MasterFap.net"
    out, seen = [], set()

    def _emit(v):
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)

    def add(tok):
        v = _valid_alias(tok)
        if not v:
            return
        _emit(v)
        # if the handle carries an underscore, also emit the underscore-free form
        # (creatorj_ → creatorj, jane_doe → janedoe) — creators re-upload both ways.
        if "_" in v:
            _emit(_valid_alias(v.replace("_", "")))

    for seg in re.split(r"\s*/\s*", t):            # each ' / ' segment = one alias (+ trailing tail)
        seg = seg.strip()
        if not seg:
            continue
        # cut the segment at the first boilerplate/number word — keep the leading name tokens
        kept = []
        for w in seg.split(" "):
            base = w.strip().strip(".-_")
            if base.lower() in BOILERPLATE or base.isdigit():
                break
            kept.append(w)
        if not kept:
            continue
        if len(kept) == 1:
            add(kept[0])                           # a bare handle: qzv1p / examplelee.xo
        else:
            # a spaced display name ("Examplelee Xo"): keep the collapsed handle form too
            joined = "".join(kept)
            add(joined)
    return out


# Aggregators that PRINT every alias side-by-side in the title (' / '-delimited). {s} = slug.
# Empirically verified (title_aliases probe, 2026-07). They mirror the SAME alias list, so any
# one working mirror suffices — but we probe ALL of them for resilience: if one 404s / blocks a
# given profile (fapello did for jane-doe), another still carries it. Ordered by richness
# (leakgallery listed 8). These are the HOP hosts too (re-probed on each discovered alias).
_LISTERS = (
    "https://fapello.com/{s}/",
    "https://leakgallery.com/{s}/",
    "https://nudogram.com/models/{s}/",
    "https://fapeza.com/{s}/",
    "https://fapachi.com/{s}",
    "https://nudostar.tv/models/{s}/",
    "https://fapodrop.com/{s}/",
)
_HOP_HOSTS = _LISTERS
# FIRST-round net: all 7 listers + one single-handle host (masterfap) for primary-handle
# confirmation. Single-handle sites (thotslife/internetchicks/dirtyship/erome) are omitted:
# they never reveal a NEW alias. thothub/coomer/hotleaks/notfans = dead/blocked to a plain fetch.
_HOST_TMPL = _LISTERS + (
    "https://www.masterfap.net/profile/{s}/",
)


def _slug_forms(handle, name=None):
    """Every plausible on-site slug for a handle (+ optional display name). A run-together
    handle ('janedoee') can't be split back into 'jane-doe', but the NAME can:
    'Jane Doe' → jane-doe / janedoe / jane_doe / jane.doe."""
    forms = []

    def add(s):
        s = (s or "").strip("-._").lower()
        if s and s not in forms:
            forms.append(s)

    h = (handle or "").strip().lower()
    add(h)
    add(re.sub(r"[^a-z0-9]", "", h))               # core: alnum only
    add(re.sub(r"[^a-z0-9]+", "-", h).strip("-"))  # dashed
    if name:
        toks = [t for t in re.split(r"[^a-z0-9]+", name.lower()) if t]
        if toks:
            joined = "".join(toks)
            add(joined)
            add("-".join(toks))
            add("_".join(toks))
            add(".".join(toks))
    return forms


def _candidate_urls(handle, name=None, listing_only=False):
    """Aggregator profile URLs to probe for a handle/name, across every slug form and host.
    listing_only limits to the alias-listing hosts (fapello/nudogram) — used on hops so the
    round-2 fan-out stays small enough to stay inside the fetch budget."""
    hosts = _HOP_HOSTS if listing_only else _HOST_TMPL
    urls = []
    for s in _slug_forms(handle, name):
        for tmpl in hosts:
            urls.append(tmpl.format(s=s))
    return list(dict.fromkeys(urls))


def _title_of(url, timeout=20):
    try:
        st, _final, html = fetch(url, timeout=timeout)
    except Exception:
        return None
    if st != 200 or not html:
        return None
    m = TITLE_RE.search(html) or OGTITLE_RE.search(html)
    if not m:
        return None
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()


def campaign_profile_urls(campaign, cdir=None, limit=30):
    """Profile-shape URLs the discovery stages ALREADY found for a campaign — read from the
    same artifacts discovery_seed harvests. These are live, real URLs whatever their slug
    shape, so they title-harvest even when the handle can't be reshaped into the host slug.
    Only alias-listing hosts are kept (fapello/nudogram/fapeza/… print every alias)."""
    try:
        from discovery_seed import _iter_source_urls, HERE as _H
        from leak_evidence import url_shape
    except Exception:
        return []
    cdir = cdir or os.path.join(_H, "campaigns", campaign)
    keep_host = re.compile(r"(fapello|nudogram|fapeza|masterfap|thefap|leakgallery)", re.I)
    out, seen = [], set()
    for u in _iter_source_urls(cdir, campaign):
        if not keep_host.search(u) or url_shape(u) != "profile":
            continue
        # collapse to the profile root (drop trailing /page-number) so we fetch each slug once
        base = re.sub(r"/\d+/?$", "/", u)
        if base not in seen:
            seen.add(base)
            out.append(base)
            if len(out) >= limit:
                break
    return out


def harvest_aliases(urls=None, handle=None, name=None, seeds=None, campaign=None, timeout=20,
                    workers=8, rounds=2, max_urls=48, verbose=False):
    """Fetch each URL's title (explicit URLs, aggregator guesses from `handle`/`name`, extra
    operator-given handles in `seeds`, and/or profile URLs discovery already found for `campaign`)
    and return the union of aliases — order-preserving, deduped case-insensitively.

    `seeds` = handles the operator already knows (the extra aliases typed into the scan form) —
    each is probed on the mirrors too, so its OWN co-aliases surface (typing 'qzv1p' pulls in
    aliasone / examplelee.xo). Runs up to `rounds` hops: each NEW alias discovered is itself
    probed (examplexo's title yields examplelee.xo, whose dashed slug fapello.com/examplelee-xo/
    then yields qzv1p + aliasone). Bounded by `max_urls` total fetches."""
    out, seen = [], set()
    fetched = set()
    seeds = [s.strip() for s in (seeds or []) if s and s.strip()]
    # each seed adds ~1 host-row of round-1 fetches; grow the budget so those never crowd out the
    # base handle's discovery hop (capped so a huge alias list can't fan out without bound).
    max_urls = min(160, max_urls + 8 * len(seeds))

    def add(a):
        if a.lower() not in seen:
            seen.add(a.lower())
            out.append(a)

    frontier = list(dict.fromkeys(u for u in (urls or []) if u.startswith("http")))
    if campaign:
        frontier += campaign_profile_urls(campaign)
    if handle or name:
        frontier += _candidate_urls(handle, name)
    for s in seeds:                         # operator-given extra aliases — probe each one too
        frontier += _candidate_urls(s)
    frontier = list(dict.fromkeys(frontier))

    for _rnd in range(max(1, rounds)):
        batch = [u for u in frontier if u not in fetched][:max(0, max_urls - len(fetched))]
        if not batch:
            break
        fetched.update(batch)
        new_aliases = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            for url, title in zip(batch, ex.map(lambda u: _title_of(u, timeout), batch)):
                if not title:
                    continue
                found = aliases_from_title(title)
                if verbose:
                    print(f"  [{url}]\n    title: {title}\n    -> {found}", file=sys.stderr)
                for a in found:
                    if a.lower() not in seen:
                        new_aliases.append(a)
                    add(a)
        if not new_aliases or len(fetched) >= max_urls:
            break
        # next hop: probe the freshly discovered aliases — alias-listing hosts only, so the
        # fan-out stays inside max_urls and the productive URL (examplelee-xo) is still reached.
        for a in new_aliases:
            frontier += _candidate_urls(a, listing_only=True)
        frontier = list(dict.fromkeys(frontier))
    harvest_aliases.last_pages = len(fetched)      # how many pages were actually fetched (for messaging)
    return out


harvest_aliases.last_pages = 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("urls", nargs="*", help="explicit aggregator profile URLs to read titles from")
    ap.add_argument("--handle", help="handle to probe on the top aggregators (fapello/nudogram/fapeza/…)")
    ap.add_argument("--name", help='display name, e.g. "Jane Doe" — bridges a run-together handle '
                                   "to the host's display-name slug (jane-doe)")
    ap.add_argument("--seeds", help="comma-separated EXTRA handles you already know — each is probed "
                                    "too, so its own co-aliases surface (e.g. qzv1p,aliasone)")
    ap.add_argument("--campaign", help="also title-harvest the profile URLs discovery already found "
                                       "for this campaign (campaigns/<c>/…)")
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--rounds", type=int, default=2, help="alias->URL hops (default 2)")
    ap.add_argument("--json", action="store_true", help="emit a JSON list")
    ap.add_argument("--quiet", action="store_true", help="don't log per-URL titles to stderr")
    a = ap.parse_args()
    if not a.urls and not a.handle and not a.name and not a.campaign and not a.seeds:
        ap.error("give profile URLs and/or --handle / --name / --seeds / --campaign")
    seeds = [s.strip() for s in (a.seeds or "").split(",") if s.strip()]
    aliases = harvest_aliases(urls=a.urls, handle=a.handle, name=a.name, seeds=seeds,
                              campaign=a.campaign, timeout=a.timeout, rounds=a.rounds,
                              verbose=not a.quiet)
    if a.json:
        import json
        print(json.dumps(aliases, ensure_ascii=False))
    elif aliases:
        for al in aliases:
            print(al)
    else:
        print(f"(no aliases found across {harvest_aliases.last_pages} page(s) probed — "
              "the handle may have no re-upload aliases, or its host slug wasn't reached; "
              "try --name or pass explicit profile URLs)", file=sys.stderr)


if __name__ == "__main__":
    main()

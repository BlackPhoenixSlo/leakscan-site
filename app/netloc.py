#!/usr/bin/env python3
"""
netloc.py — host/URL helpers shared across the leak tools.

registrable_domain() collapses CDN/lang subdomains to the eTLD+1 so we can GROUP
by site (cdn.leakgallery.com -> leakgallery.com) WITHOUT deleting the underlying
media URL — dedup is for prioritisation, not deletion (devil's-advocate #7).

Also: a small multi-part-TLD table, a low-value-subdomain check, and URL
normalisation for dedup (lowercase host, strip tracking params, keep language
path prefixes because each is a separate takedown URL).
"""
import os
import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

# eTLD+1 needs to know 2-level public suffixes; small pragmatic table (extend as needed).
_MULTI_TLD = {
    "co.uk", "org.uk", "gov.uk", "ac.uk", "co.nz", "co.za", "com.au", "com.br",
    "com.mx", "com.ar", "co.jp", "com.tr", "com.ua", "co.in", "com.co",
}
_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|yclid$|mc_|ref$|ref_src$|igshid$|si$)")


def host_of(host_or_url: str) -> str:
    s = (host_or_url or "").strip()
    if "://" in s:
        s = urlparse(s).netloc
    elif "/" in s:
        s = s.split("/", 1)[0]
    return s.split("@")[-1].split(":")[0].lower().strip(".")


def registrable_domain(host_or_url: str) -> str:
    """cdn.leakgallery.com -> leakgallery.com ; 1q.harlock.co.uk -> harlock.co.uk"""
    host = host_of(host_or_url)
    if not host or host.replace(".", "").isdigit():
        return host
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    last2 = ".".join(parts[-2:])
    if last2 in _MULTI_TLD and len(parts) >= 3:
        return ".".join(parts[-3:])
    return last2


# subdomains that are almost always a CDN/asset mirror of a root that we already keep
_LOWVALUE_SUB = re.compile(r"^(cdn\d*|img\d*|images?|media|static|assets?|thumbs?|"
                           r"i\d*|c\d*|s\d*|t\d*|www\d+|amp|m|mobile|bg)\.", re.I)


def is_lowvalue_subdomain(host_or_url: str) -> bool:
    """True for cdn./img./static./bg. … mirrors (deprioritise, don't delete)."""
    host = host_of(host_or_url)
    return bool(_LOWVALUE_SUB.match(host)) and host != registrable_domain(host)


def norm_url(u: str) -> str:
    """Canonical form for dedup: lowercase host, drop tracking params, drop fragment,
    keep path (incl. language prefixes) and a trailing slash-insensitive path."""
    try:
        p = urlparse(u.strip())
    except Exception:
        return (u or "").strip()
    host = p.netloc.lower()
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=False)
         if not _TRACKING.match(k)]
    path = re.sub(r"/+$", "", p.path) or "/"
    return urlunparse((p.scheme.lower() or "https", host, path, "", urlencode(q), ""))


def newest_path(*candidates):
    """The most recently modified existing candidate path, or None.

    run_az.sh full runs write every pipeline artifact at the repo ROOT and only tidy them into
    campaigns/<c>/ AFTER the pipeline ends (mv preserves mtimes). So mid-run the fresh artifact
    lives at root while campaigns/ holds last run's copy — 'prefer campaigns/' reads stale data
    mid-run (the bug that killed slug_triage's crawl-guard on every fresh run), and 'prefer
    root' reads stale leftovers after a tidy. The newest existing copy is the only safe pick."""
    live = [p for p in candidates if p and os.path.exists(p)]
    return max(live, key=os.path.getmtime) if live else None


def echo_only_domains(triage_path: str) -> set:
    """Registrable domains slug_triage found ECHO-ONLY: every scanned entry-point on them is DROP
    (search page reflects the query but shows other performers) AND the crawl found zero handle-
    carrying media. Such a domain hosts nothing of hers — safe to suppress from the DMCA export
    and the 'Also on Google' count. A domain with ANY KEEP entry (fssquad's tag page) or crawl-
    confirmed media (leakgallery) is NOT echo-only and is never returned. Shared by export_dmca
    and make_report so both sides of the report filter identically."""
    import json
    import os
    if not triage_path or not os.path.exists(triage_path):
        return set()
    try:
        recs = json.load(open(triage_path, encoding="utf-8")).get("records", [])
    except Exception:
        return set()
    by = {}
    for r in recs:
        h = r.get("host")
        if h:
            by.setdefault(registrable_domain(h), []).append(r)
    return {d for d, rs in by.items()
            if rs and all(r.get("triage") == "DROP" for r in rs)
            and not any(r.get("crawl_media") for r in rs)}


def canon_url(u: str) -> str:
    """Canonical key for matching a human-verified 'empty' result URL to a CSE link.

    Lowercases host (minus www) + path (+ query when present), URL-decodes, and drops the
    scheme, fragment and trailing slash — so http/https, www., %20-vs-space and a trailing
    '/' all fold together. It KEEPS the full path+query, so two URLs on the SAME host that
    differ only in slug stay distinct: leakgallery.com/search/juliafilippo-leak (empty) is
    dropped while leakgallery.com/search/sophieraiin-onlyfans-leaks (real) is not."""
    from urllib.parse import urlsplit, unquote
    s = (u or "").strip()
    if not s:
        return ""
    if "://" not in s:
        s = "http://" + s
    try:
        p = urlsplit(s)
    except Exception:
        return s.lower()
    host = p.netloc.split("@")[-1].split(":")[0].lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+$", "", unquote(p.path)).lower()
    q = unquote(p.query).lower()
    return host + path + (("?" + q) if q else "")


def load_top_drop(path: str) -> set:
    """Load a verified-empty result-URL list (one URL/line, '#' comments) into a set of
    canon_url keys. These are 'top results' a HUMAN opened and confirmed carry NONE of the
    creator's content — the ONLY authority for dropping a top result, because no URL pattern
    distinguishes a real search page from an empty one (proven: /search/juliafilippo-leak
    empty vs /search/sophieraiin-onlyfans-leaks full; xxk.mobi empty vs xgx.mobi full).
    Cross-campaign entries are harmless: a URL only matches the report whose CSE surfaced it.
    Missing/unreadable file -> empty set (keep-all)."""
    if not path or not os.path.exists(path):
        return set()
    out = set()
    try:
        for ln in open(path, encoding="utf-8"):
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            k = canon_url(ln)
            if k:
                out.add(k)
    except Exception:
        return out
    return out


if __name__ == "__main__":
    import sys
    for a in sys.argv[1:]:
        print(f"{a}\n  registrable = {registrable_domain(a)}"
              f"\n  lowvalue_sub = {is_lowvalue_subdomain(a)}\n  norm = {norm_url(a)}")

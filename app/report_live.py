"""report_live.py — provisional, MONOTONE live snapshot for a running deep scan (version2site).

Reads the GROWING crawl checkpoint (<prefix>.crawl.json, rewritten by leak_crawler every few
domains during phase 1) and returns a provisional "candidates found so far" view: media items +
sites + per-domain candidate links. This is DELIBERATELY NOT the confirmed-leak count.

Why it must not be labeled "confirmed": the crawl set is a strict SUPERSET that clean_crawl →
slug_triage → export_dmca shrink hard (measured: rileyraid 4920 raw media → 23 export-LIKELY;
sophieraiin 12939 → 6543). If we showed the raw crawl count as "Confirmed leaks" it would climb to
thousands and then collapse when the export lands — looking broken and dishonest. So:

  - the caller shows these as a MONOTONE "candidates found so far" ticker (never shrinks), and
  - holds the authoritative "Confirmed leaks" / price tiles as SKELETONS until the export step
    COMPLETES (public_app only trusts metadata.jsonl once the phase has advanced past `export`).

Honesty / safety rules baked in here:
  - candidates & the per-domain link union only ever GROW within a scan (caller passes the prior
    floor; we union, never drop) — so a later clean/checkpoint rewrite can't lower the ticker.
  - torn/partial JSON reads (leak_crawler writes non-atomically, open("w")+json.dump) are swallowed
    → we return the last good parse from an (mtime,size) cache, so a poll never sees a torn count.
  - path-jailed to webscan_* prefixes: a public scan can never read a real campaign's files.
  - the (mtime,size) cache means repeated 1.5 s polls don't re-parse a multi-MB JSON every time.
"""
import hashlib
import json
import os
import re
import threading
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
# 0 = no per-domain cap on the live candidate view (leakgallery prints in full); the total is
# still bounded by CANDIDATES_CAP so a single poll payload can't run away.
PER_DOMAIN_LINKS = int(os.environ.get("PER_DOMAIN_LINKS", "0"))
CANDIDATES_CAP = int(os.environ.get("CANDIDATES_CAP", "40000"))   # sanity ceiling on the ticker/payload

_WEBSCAN_RE = re.compile(r"^webscan_[a-z0-9]+$")
_cache = {}                     # path -> (mtime, size, parsed_list)
_cache_lock = threading.Lock()


def prefix_for(slug):
    """The deterministic scratch prefix public_app derives for a scan slug."""
    return "webscan_" + hashlib.sha1(slug.encode("utf-8")).hexdigest()[:16]


def _newest_crawl(prefix):
    """Newest crawl checkpoint at the repo root for this prefix (clean preferred). Path-jailed to
    webscan_* so a public scan can never resolve to a real campaign's crawl."""
    if not _WEBSCAN_RE.match(os.path.basename(prefix)):
        return None
    cands = []
    for name in (f"{prefix}.crawl.clean.json", f"{prefix}.crawl.json"):
        p = os.path.join(HERE, name)
        if os.path.exists(p):
            cands.append(p)
    return max(cands, key=os.path.getmtime) if cands else None


def _load_crawl_cached(path):
    """Parse the growing crawl JSON, cached by (mtime,size). The writer is non-atomic, so a read
    landing mid-write raises → we return the last good parse (or [] if we never got one)."""
    try:
        st = os.stat(path)
    except OSError:
        return []
    with _cache_lock:
        hit = _cache.get(path)
        if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
            return hit[2]
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            data = []
    except (ValueError, OSError):
        with _cache_lock:
            hit = _cache.get(path)
        return hit[2] if hit else []
    with _cache_lock:
        _cache[path] = (st.st_mtime, st.st_size, data)
    return data


def _norm_media(u):
    """Dedup key: drop scheme/query/fragment, lowercase host+path. A file mirrored across
    http/https or with tracking params is ONE candidate."""
    s = (u or "").split("?", 1)[0].split("#", 1)[0]
    return s.split("://", 1)[-1].rstrip("/").lower()


def live_snapshot(prefix, floor=None):
    """Provisional monotone snapshot for a running scan's prefix.

    floor = the caller's previous {'candidates','sites','by_domain'} (its monotone memory) or None.
    Returns {'candidates','sites_found','by_domain','hits','provisional':True}. `by_domain` is the
    growing union of per-domain candidate media URLs (capped); it is never allowed to shrink."""
    floor = floor or {}
    by_domain = {d: list(v) for d, v in (floor.get("by_domain") or {}).items()}
    seen = set()
    for urls in by_domain.values():
        for u in urls:
            seen.add(_norm_media(u))

    cp = _newest_crawl(prefix)
    if cp:
        for r in sorted(_load_crawl_cached(cp), key=lambda x: -len(x.get("media") or [])):
            dom = r.get("domain")
            if not dom:
                continue
            lst = by_domain.setdefault(dom, [])
            if PER_DOMAIN_LINKS and len(lst) >= PER_DOMAIN_LINKS:
                continue
            for u in (r.get("media") or []):
                k = _norm_media(u)
                if not k or k in seen:
                    continue
                seen.add(k)
                lst.append(u)
                if PER_DOMAIN_LINKS and len(lst) >= PER_DOMAIN_LINKS:
                    break

    by_domain = {d: v for d, v in by_domain.items() if v}
    candidates = min(sum(len(v) for v in by_domain.values()), CANDIDATES_CAP)
    candidates = max(candidates, int(floor.get("candidates") or 0))     # monotone guard
    sites = max(len(by_domain), int(floor.get("sites") or 0))
    hits = [{"domain": d, "url": (v[0] if v else "https://" + d + "/"),
             "occurrences": len(v), "method": "crawl", "live": True}
            for d, v in sorted(by_domain.items(), key=lambda kv: -len(kv[1]))]
    return {"candidates": candidates, "sites_found": sites,
            "by_domain": by_domain, "hits": hits, "provisional": True}

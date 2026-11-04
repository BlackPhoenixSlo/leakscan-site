#!/usr/bin/env python3
"""
Deep leak crawler — search -> real slugs -> paginate/enumerate -> media.

Goes beyond the flat presence-check (leak_scanner.py), the way Bruqi's `search`
+ `crawl` methods do:

  1. DISCOVER  query each domain's search endpoint and read the REAL profile
               slugs out of the results — this catches name variations we can't
               guess (husvjjal-1, husvjjal_2, husvjjxl, new stage names) plus
               direct profile guesses.
  2. CRAWL     for each slug, walk the profile grid (?page=N) and, on sites that
               number content sequentially, enumerate /{slug}/{i}/ pages.
  3. EXTRACT   pull image/video URLs off every page and KEEP ONLY those whose URL
               contains the creator's slug — so a profile page full of unrelated
               "related models" thumbnails doesn't pollute the results.

Per-domain URL templates come from bruqi_detection_map.json (derived + live
verified from 22k real Bruqi findings). Stdlib only.

Usage
-----
    python3 leak_crawler.py husvjjal husvjjal2 liviadrusilla3
    python3 leak_crawler.py husvjjal --domains wildskirts.com,nudostar.tv,fapeza.com
    python3 leak_crawler.py husvjjal --max-profiles 10 --max-pages 12
"""

import argparse
import concurrent.futures as cf
import csv
import gzip
import json
import os
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/json,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "accept-encoding": "identity",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
}

# cap how many aliases a single domain probes for slugs — a junk-expanded identity
# list (search phrases, encoded blobs) otherwise multiplies fetches on slow hosts.
MAX_DISCOVERY_ALIASES = 30
MEDIA_EXT = re.compile(r"\.(jpe?g|png|webp|avif|gif|mp4|m3u8|mov|webm)(\?|$)", re.I)
MEDIA_NOISE = re.compile(r"(logo|favicon|sprite|/icon|placeholder|/blank|loading|empty\.png|"
                         r"profile_pic|profile_photo|avatar)", re.I)
HREF = re.compile(r"""href\s*=\s*["']([^"'#]+)["']""", re.I)
SRC = re.compile(r"""(?:src|data-src|data-original|data-lazy-src|data-url)\s*=\s*["']([^"'#]+)["']""", re.I)
SRCSET = re.compile(r"""srcset\s*=\s*["']([^"']+)["']""", re.I)
OGIMG = re.compile(r"""<meta[^>]+(?:property|name)=["']og:image["'][^>]+content=["']([^"']+)["']""", re.I)
# media URLs that aren't in src=/href= attrs (inline JSON, <script>, data blobs)
RAW_MEDIA = re.compile(r"""https?://[^\s"'<>)\\]+?\.(?:jpe?g|png|webp|avif|gif|mp4|m3u8|mov|webm)""", re.I)


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def stem(alias):
    """husvjjal3 / husvjjal-3 -> 'husvjjal' so numbered variations all match."""
    return re.sub(r"\d+$", "", norm(alias))


def _slug_priority(slug):
    """Sort key for capping to --max-profiles: numbered galleries first, HIGHEST index first
    (newest re-upload — the live one when older numbers were renumbered/404'd), then the plain
    handle slugs alphabetically. e.g. julia-filippo-58 outranks julia-filippo-1 outranks
    julia.filippo."""
    m = re.search(r"[-_](\d{1,4})$", slug or "")
    return (0, -int(m.group(1)), slug) if m else (1, 0, slug)


_SLUG_SEG_BAD = re.compile(r"\.(?:aspx?|php|s?html?|jpe?g|png|webp|avif|gif|mp4|m3u8|mov|webm)$", re.I)


def bad_slug_seg(seg):
    """True when a path segment can't be a real creator slug — a filename, a proxied
    URL, a hostname, a whitespace/star blob, or an absurdly long SEO string. Keeps
    junk like 't1.pictoa.com*media*...jpg.asp' out of slug lists + learned templates."""
    s = (seg or "").strip()
    seps = s.count("-") + s.count("_")   # real handles have ≤2; more = a search phrase
    return bool(not s or len(s) > 40 or "*" in s or " " in s or "://" in s
                or "%" in s or "+" in s or seps > 2
                or _SLUG_SEG_BAD.search(s) or s.count(".") >= 2)


def registrable(host):
    host = host.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    p = host.split(".")
    if len(p) > 2 and len(p[0]) == 2:
        host = ".".join(p[1:])
    return host


# ---- politeness: reserve a per-host time slot so we never hammer one site ----
MIN_INTERVAL = 0.0           # seconds between requests to the SAME host (set in main)
_HOST_LOCK = threading.Lock()
_HOST_NEXT = {}

# ---- slug memory: slugs confirmed on past runs, seeded into discovery (set in main) ----
KNOWN_SLUGS = {}             # domain -> [slug, ...] (already stem-filtered to the aliases)

# Q1 sibling-neighbourhood probe reach (discover_slugs): how far PAST the highest known
# numbered gallery to probe for newer re-uploads, and the total per-base probe budget.
SIBLING_REACH_ABOVE = 8      # probe <base>-(max+1) .. <base>-(max+8) — her newest re-uploads
SIBLING_PROBE_CAP = 48       # hard cap on sibling fetches per domain (above-max + gap-fill)


def _throttle(host):
    if MIN_INTERVAL <= 0:
        return
    with _HOST_LOCK:
        start = max(time.monotonic(), _HOST_NEXT.get(host, 0.0))
        _HOST_NEXT[host] = start + MIN_INTERVAL   # reserve the slot, then sleep unlocked
    delay = start - time.monotonic()
    if delay > 0:
        time.sleep(delay)


def fetch(url, timeout=15, retries=2, hdrs=None):
    host = urllib.parse.urlparse(url).netloc
    headers = dict(HEADERS, **hdrs) if hdrs else HEADERS
    for attempt in range(retries + 1):
        _throttle(host)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout, context=CTX) as r:
                raw = r.read(900000)
                if r.headers.get("content-encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return r.status, r.geturl(), raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < retries:    # backoff on rate-limit
                ra = e.headers.get("Retry-After", "")
                time.sleep(min(float(ra) if ra.isdigit() else 2.0 * (attempt + 1), 30))
                continue
            return e.code, url, ""
        except Exception:
            if attempt >= retries:
                return 0, url, ""             # timeout / reset — give up after retries
            time.sleep(1.0 * (attempt + 1))


def extract_urls(page_url, html):
    links, media, raw = set(), set(), set()
    for rx in (HREF, SRC):
        raw.update(rx.findall(html))
    for ss in SRCSET.findall(html):
        for part in ss.split(","):
            u = part.strip().split(" ")[0]
            if u:
                raw.add(u)
    raw.update(OGIMG.findall(html))
    for u in raw:
        u = u.strip()
        if not u or u.startswith(("data:", "javascript:", "mailto:", "tel:")):
            continue
        try:
            absu = urllib.parse.urljoin(page_url, u)
        except ValueError:
            continue   # malformed URL (e.g. bad [..] netloc -> "Invalid IPv6 URL"); skip, don't crash
        if not absu.startswith("http"):
            continue
        if MEDIA_EXT.search(absu):
            if not MEDIA_NOISE.search(absu):
                media.add(absu)
        else:
            links.add(absu)
    # full-text sweep for media URLs embedded in inline JSON / <script> / data blobs
    for mu in RAW_MEDIA.findall(html):
        if not MEDIA_NOISE.search(mu):
            media.add(mu)
    return links, media


def profile_template(info):
    """URL template (with {name}) for a creator's landing page (keeps trailing slash)."""
    cu = info.get("content_url")
    if cu:
        return cu.split("{idx}")[0]  # strip per-item index, keep trailing slash
    if info.get("method") == "profile":
        return info["check_url"]
    return None


def discover_slugs(domain, info, aliases, timeout, deadline=None):
    """Return the set of real on-site slugs for the creator (handles variations).

    Speed-tuned: ONE fetch of the check page per alias (reused for both the base-slug
    test and search-result extraction), and blind profile-variation probing only for
    stems we haven't already cracked (deduped + capped). Honors `deadline` (epoch secs)
    and caps the alias count so a junk-expanded list can't hang a slow host here."""
    slugs = set(KNOWN_SLUGS.get(domain, []))   # reuse slugs confirmed on past runs
    host = info["check_url"].split("/")[2]
    ptmpl = profile_template(info)
    is_search = info.get("method") == "search"
    cracked = {stem(s) for s in slugs}         # stems we already have a slug for

    for a in aliases[:MAX_DISCOVERY_ALIASES]:
        if deadline and time.time() > deadline:
            break
        st_a = stem(a)
        if not st_a:
            continue
        enc = urllib.parse.quote(a, safe="._-")
        cu = info["check_url"].replace("{name}", enc).replace("{lang}", "en")
        status, fu, html = fetch(cu, timeout)
        if status != 200:
            continue
        # the alias itself is a slug when the check page genuinely shows it
        if st_a in norm(html[:60000] + cu):
            slugs.add(a)
            cracked.add(st_a)
        # search pages also list the REAL slugs (variations / new stage names)
        if is_search:
            links, _ = extract_urls(f"https://{host}/", html)
            for u in links:
                pr = urllib.parse.urlparse(u)
                if registrable(pr.netloc) != domain:
                    continue
                for seg in (s for s in pr.path.split("/") if s):
                    # require the stem to be a PREFIX of the segment (so 'ava' no longer
                    # matches 'savannah'/'octavia'); reject post-id tails (husvjal-289520),
                    # pure numbers, and filename/URL/host junk (bad_slug_seg).
                    if (norm(seg).startswith(st_a) and not seg.isdigit()
                            and not re.search(r"\d{4,}$", seg) and not bad_slug_seg(seg)):
                        slugs.add(seg)
                        cracked.add(stem(seg))

    # blind profile-variation probing — only for stems still uncracked, deduped + capped
    if ptmpl:
        cands, seen = [], set(slugs) | set(aliases)
        for a in aliases:
            st_a = stem(a)
            if not st_a or st_a in cracked:
                continue
            for sfx in ("", "-1", "-2", "_1", "1", "2"):
                c = a + sfx
                if c not in seen:
                    seen.add(c)
                    cands.append((st_a, c))
        for st_a, cand in cands[:16]:
            if deadline and time.time() > deadline:
                break
            if st_a in cracked:
                continue
            url = ptmpl.replace("{name}", urllib.parse.quote(cand, safe="._-")).replace("{lang}", "en")
            status, fu, html = fetch(url, timeout)
            if status == 200 and st_a in norm(html[:60000] + url):
                slugs.add(cand)
                cracked.add(st_a)

    # sibling-neighbourhood probe (Q1) — once a NUMBERED gallery (<base>-N) is confirmed on
    # a site, that site very likely hosts adjacent galleries (<base>-1..-N+) that were simply
    # never LINKED on a page we fetched — which is exactly how fapello's -9 was found only by
    # luck while a hypothetical -7 stays invisible. Walk the profile template, 404-gated +
    # BODY-verified (stricter than the blind probe above, which is effectively 200-only).
    # Recall-only, additive, bounded — never drops anything.
    #
    # ABOVE-max is prioritised over below-gaps: on sites whose <base>-N is a GLOBAL re-upload
    # counter (fapello), a below gap is almost always a DIFFERENT model, while the numbers just
    # past our known max are her newest re-uploads — the ones a stale discovery snapshot misses
    # (e.g. snapshot knew -55, but the live newest is -58). Seeded/known slugs can themselves be
    # dead (a re-upload gets renumbered), so we still reach past max even when max itself 404s.
    if ptmpl:
        alias_stems = {stem(a) for a in aliases if stem(a)}
        base_max = {}   # (base, sep) -> highest index seen for OUR creator on this site
        for s in list(slugs):
            m = re.match(r"^(.*[^\d])([-_])(\d{1,3})$", s)
            if not m:
                continue
            base, sep, n = m.group(1), m.group(2), int(m.group(3))
            if stem(base) in alias_stems:                 # only our creator's numbered galleries
                base_max[(base, sep)] = max(base_max.get((base, sep), 0), n)
        above, below = [], []                             # probe above-max first, then gap-fill
        for (base, sep), maxn in base_max.items():
            for n in range(maxn + 1, maxn + 1 + SIBLING_REACH_ABOVE):
                above.append((stem(base), f"{base}{sep}{n}"))
            for n in range(1, maxn + 1):
                cand = f"{base}{sep}{n}"
                if cand not in slugs:
                    below.append((stem(base), cand))
        for st_b, cand in (above + below)[:SIBLING_PROBE_CAP]:
            if deadline and time.time() > deadline:
                break
            if cand in slugs:
                continue
            url = ptmpl.replace("{name}", urllib.parse.quote(cand, safe="._-")).replace("{lang}", "en")
            status, fu, html = fetch(url, timeout)
            if status == 200 and st_b in norm(html[:60000]):   # body must actually show the creator
                slugs.add(cand)
    return slugs


def _dedupe(urls):
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def listing_urls_for(info, slug, args):
    """Listing pages for one slug — the profile grid + the site's search/check page.

    NOT the numbered post pages (those are `post_urls_for`, walked separately so the
    sequential-404 stop can't cut a listing page short). Blind `?page=N` / `/page/N`
    pagination is emitted ONLY when the site has no real grid endpoint (`grid_url`);
    when it does, page-2..N of `?page` is dead weight (many sites ignore the param and
    re-serve page 1) and the grid walk enumerates the true post set instead."""
    enc = urllib.parse.quote(slug, safe="._-")
    grid_pages = getattr(args, "max_pages", 8)
    urls = []
    ptmpl = profile_template(info)
    if ptmpl:
        base = ptmpl.replace("{name}", enc).replace("{lang}", "en")
        urls.append(base)
        if not info.get("grid_url"):
            for n in range(2, grid_pages + 1):                  # blind grid pagination
                sep = "&" if "?" in base else "?"
                urls.append(f"{base}{sep}page={n}")
                urls.append(base.rstrip("/") + f"/page/{n}")
    # always fetch the site's own check page (search / tags / listing) for this slug —
    # this is the only crawl target for search-method domains with no profile template
    cku = info.get("check_url")
    if cku:
        urls.append(cku.replace("{name}", enc).replace("{lang}", "en"))
    return _dedupe(urls)


def grid_indices(info, slug, timeout, max_grid_pages=300, deadline=None):
    """Tier-1: walk the site's REAL lazy-load grid endpoint (`grid_url`, with `{idx}` =
    page number) until a page yields no new post links, and return the exact sorted list
    of post indices for this slug. This is the authoritative gallery size — it replaces
    blind `1..N` guessing and, unlike a sequential walk, tolerates gaps (deleted posts).

    fapello: `https://fapello.com/ajax/model/{name}/page-{idx}/` → pages 1..k, then empty.
    Returns None when the site has no grid endpoint (caller falls back to `post_urls_for`
    sequential enumeration)."""
    gtmpl = info.get("grid_url")
    if not gtmpl:
        return None
    domain = registrable(urllib.parse.urlparse(info["check_url"]).netloc)
    enc = urllib.parse.quote(slug, safe="._-")
    hard = info.get("idx_max") or 100000
    nslug, seen = norm(slug), set()
    for page in range(1, max_grid_pages + 1):       # safety bound; real stop is empty page
        if deadline and time.time() > deadline:
            break
        url = gtmpl.replace("{name}", enc).replace("{idx}", str(page)).replace("{lang}", "en")
        status, _, html = fetch(url, timeout)
        if status != 200 or len(html) < 20:
            break
        links, _ = extract_urls(url, html)
        added = 0
        for l in links:
            pr = urllib.parse.urlparse(l)
            if registrable(pr.netloc) != domain:
                continue
            segs = [s for s in pr.path.split("/") if s]
            # a real post link is exactly /{slug}/{int}/ — this excludes /content/…/1000/
            if len(segs) == 2 and segs[-1].isdigit() and norm(segs[0]) == nslug:
                i = int(segs[-1])
                if 1 <= i <= hard and i not in seen:
                    seen.add(i)
                    added += 1
        if added == 0:                              # page produced no new posts -> gallery end
            break
    return sorted(seen)


def post_urls_for(info, slug, args, grid_idx=None):
    """Numbered post-page URLs for a sequential site (`idx_type == "seq"`).

    When `grid_idx` (from `grid_indices`) is known these are EXACTLY the real posts; else
    a bounded sequential walk `1..cap` — `cap = min(--item-depth, idx_max)` — that the
    caller stops at the first run of consecutive misses (out-of-range posts 404). Either
    way the ceiling is the site's true gallery size, never the old `--max-pages` (8)."""
    if not (info.get("content_url") and info.get("idx_type") == "seq"):
        return []
    enc = urllib.parse.quote(slug, safe="._-")
    cu = info["content_url"].replace("{name}", enc).replace("{lang}", "en")
    if grid_idx:
        idxs = grid_idx
    else:
        item_depth = getattr(args, "item_depth", 400)
        cap = min(item_depth, info.get("idx_max") or item_depth)
        idxs = range(1, cap + 1)
    return [cu.replace("{idx}", str(i)) for i in idxs]


def build_slug_detail(slugs, media_pairs, pages):
    """Per-slug breakdown of the 4 build-up stages, IN ORDER:

        1. search   -> the slug name itself (how it was discovered)
        2. profile  -> images scraped off the slug's pages
        3. image-id -> the numbered item ids that resolved (200) under the slug
        4. scroll   -> the slug's content/listing pages walked via pagination

    media_pairs is [[img_url, source_page], ...]; pages is the flat page list.
    Attribution is by the CONCRETE slug as a whole path SEGMENT (not the digit-
    stripped stem, and not a bare substring): the normalized slug must equal a
    full normalized path segment of the image URL OR the page it came from. This
    keeps distinct creators apart (`husvjal` no longer steals `husvjall-326685`'s
    haul) and stops numbered variants (`husvjjal` / `husvjjal2`) all showing the
    same inflated set — each card reflects only what lives under THAT slug. Each
    entry is self-describing so the UI can showcase all four stages directly."""
    def owns(slug_norm, url):
        return slug_norm and any(norm(seg) == slug_norm
                                 for seg in urllib.parse.urlparse(url).path.split("/") if seg)

    detail = []
    for slug in slugs:
        sn = norm(slug)
        if not sn:
            detail.append({"slug": slug, "images": [], "item_ids": [], "pages": [],
                           "counts": {"images": 0, "item_ids": 0, "pages": 0}})
            continue
        imgs = sorted({m for m, src in media_pairs if owns(sn, m) or owns(sn, src)})
        pgs = sorted({p for p in pages if owns(sn, p)})
        ids = sorted({seg for p in pgs
                      for seg in [urllib.parse.urlparse(p).path.rstrip("/").rsplit("/", 1)[-1]]
                      if seg.isdigit()}, key=lambda s: int(s))
        detail.append({"slug": slug, "images": imgs, "item_ids": ids, "pages": pgs,
                       "counts": {"images": len(imgs), "item_ids": len(ids), "pages": len(pgs)}})
    # single-slug, hashed-media fallback: if nothing matched by segment the whole haul is this slug's
    if len(detail) == 1 and not detail[0]["images"] and media_pairs:
        detail[0]["images"] = sorted({m for m, _ in media_pairs})
        detail[0]["counts"]["images"] = len(detail[0]["images"])
    return detail


def merge_domain_result(old, new):
    """Union a re-scan result INTO a productive domain's pass-1 result (Q1 cross-site
    propagation). Preserves everything pass 1 found and ADDS only the new-identity slugs /
    pages / media the retry surfaced — never drops. Rebuilds slug_detail over the union."""
    slugs = sorted(set(old.get("slugs") or []) | set(new.get("slugs") or []))
    pages = sorted(set(old.get("pages") or []) | set(new.get("pages") or []))
    pairs = {m: src for m, src in old.get("media_pairs", [])}
    for m, src in new.get("media_pairs", []):
        pairs.setdefault(m, src)
    old["slugs"] = slugs
    old["pages"] = pages
    old["media"] = sorted(pairs)
    old["media_pairs"] = [[m, src] for m, src in sorted(pairs.items())]
    old["slug_detail"] = build_slug_detail(slugs, old["media_pairs"], pages)
    return old


# --------------------------------------------------------------------------- #
# per-site adapters for JS/SPA sites (curl the SSR search + JSON API directly)
# --------------------------------------------------------------------------- #
API_HDRS = {"accept": "application/json,*/*", "origin": "https://leakgallery.com",
            "referer": "https://leakgallery.com/", "x-requested-with": "XMLHttpRequest"}


def _ng_state(html):
    m = re.search(r'<script[^>]*id=["\']ng-state["\'][^>]*>(.*?)</script>', html, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1).replace("\\u002F", "/"))
    except Exception:
        return {}


def _collect_usernames(obj, out):
    if isinstance(obj, dict):
        u = obj.get("username")
        if isinstance(u, str) and u.lower() != "username":
            out.add(u)
        for v in obj.values():
            _collect_usernames(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_usernames(v, out)


def adapter_leakgallery(domain, info, aliases, args):
    """leakgallery = Angular SSR. search page SSRs the model list; content comes
    from api.leakgallery.com/profile/{slug}?page=N (JSON with medias[].file_path)."""
    out = {"domain": domain, "method": "api", "slugs": [], "pages": set(), "media": {}}
    slugs = set()
    for a in aliases:
        st_a = stem(a)
        if not st_a:
            continue
        slugs.add(a)  # try the alias itself
        status, _, html = fetch(f"https://leakgallery.com/search/{urllib.parse.quote(a)}", args.timeout)
        if status == 200:
            found = set()
            _collect_usernames(_ng_state(html), found)
            for u in found:
                if st_a in norm(u):
                    slugs.add(u)

    real = []
    for slug in sorted(slugs)[: args.max_profiles]:
        page, total, got, valid = 1, None, 0, False
        encslug = urllib.parse.quote(slug)
        while page <= 500:  # safety cap; real stop is mediaCount / max-media below
            # pagination is PATH-based: /profile/{slug} = p1, /profile/{slug}/{N} = pN
            api = f"https://api.leakgallery.com/profile/{encslug}"
            if page > 1:
                api += f"/{page}"
            status, _, body = fetch(api, args.timeout, hdrs=API_HDRS)
            if status != 200:
                break
            try:
                d = json.loads(body)
            except Exception:
                break
            medias = d.get("medias") or []
            if page == 1:
                total = d.get("mediaCount")
                if not medias:
                    break
                valid = True
                for old in (d.get("profile", {}).get("old_usernames") or "").split(","):
                    old = old.strip()
                    if old and old not in real:
                        slugs.add(old)
            for m in medias:
                src = f"https://leakgallery.com/{slug}/{m['id']}" if m.get("id") else f"https://leakgallery.com/{slug}"
                if m.get("id"):
                    out["pages"].add(src)
                fp = m.get("file_path") or m.get("thumbnail_path")
                if fp:
                    out["media"].setdefault("https://cdn.leakgallery.com/" + fp.lstrip("/"), src)
            got += len(medias)
            if not medias or (total and got >= total) or len(out["media"]) >= args.max_media:
                break
            page += 1
        if valid:
            real.append(slug)
    out["slugs"] = real
    out["media_pairs"] = [[m, src] for m, src in sorted(out["media"].items())]
    out["pages"] = sorted(out["pages"])
    out["media"] = sorted(out["media"])
    out["slug_detail"] = build_slug_detail(out["slugs"], out["media_pairs"], out["pages"])
    return out


ADAPTERS = {"leakgallery.com": adapter_leakgallery}


def crawl_domain(domain, info, aliases, args):
    if domain in ADAPTERS:
        return ADAPTERS[domain](domain, info, aliases, args)
    out = {"domain": domain, "method": info["method"], "slugs": [], "pages": set(), "media": {}}
    # hard wall-clock cap per domain so one slowloris host can't stall the whole crawl —
    # set BEFORE slug discovery, since discovery (one fetch per alias) was the uncapped hang.
    budget = getattr(args, "per_domain_budget", 0.0) or 0.0
    deadline = (time.time() + budget) if budget > 0 else None
    # When the discovered set exceeds --max-profiles, keep the NEWEST numbered galleries first:
    # on global-re-upload-counter sites (fapello) old <base>-N get renumbered and 404, so an
    # alphabetical cut keeps dead low numbers (-1..-55) and drops the one live re-upload (-58).
    # Numbered slugs, highest index first; then non-numbered handle slugs.
    slugs = sorted(discover_slugs(domain, info, aliases, args.timeout, deadline),
                   key=_slug_priority)[: args.max_profiles]
    out["slugs"] = slugs

    def harvest(url, st_s):
        """Fetch one page; return True if usable. Collects slug-matched media + item links."""
        status, fu, html = fetch(url, args.timeout)
        if status != 200 or len(html) < 300:
            return False
        links, media = extract_urls(url, html)
        # precise path: media whose URL carries the slug (nudostar/fapeza/leakgallery style)
        slug_media = [m for m in media if st_s in norm(urllib.parse.urlparse(m).path)]
        if slug_media:
            for m in slug_media:
                out["media"].setdefault(m, fu or url)   # remember which page each image came from
        else:
            # dedicated creator page with HASHED media (erothots/thothd/video pages): the
            # slug is in the PAGE url but not the media urls, so trust this page's media.
            psegs = [s for s in urllib.parse.urlparse(fu or url).path.split("/") if s]
            is_search = any(s.lower() in ("search", "search_v2") for s in psegs)
            page_is_creator = (not is_search) and any(st_s and st_s in norm(s) for s in psegs)
            if page_is_creator:
                for m in media:
                    out["media"].setdefault(m, fu or url)
        for l in links:
            pr = urllib.parse.urlparse(l)
            seg = [s for s in pr.path.split("/") if s]
            is_item = len(seg) >= 2 and seg[-1].isdigit() and seg[-2] != "page"  # real post, not /page/N
            if registrable(pr.netloc) == domain and st_s in norm(pr.path) and is_item:
                out["pages"].add(l)
        return True

    stop = getattr(args, "early_stop", False)
    item_depth = getattr(args, "item_depth", 400)
    for slug in slugs:
        st_s = stem(slug)
        posts_done = set()    # (canonical-host, id) already fetched — so mirrors/pass-2 don't refetch
        # pass 1a: listing/grid + search pages. The 10%-tail early-stop lives HERE, where a
        # page carries a whole grid of media, not on the per-post walk below.
        misses = 0
        ok_pages = 0          # successful listing fetches this slug
        weak = 0              # consecutive fetches that added ~no new media
        for u in listing_urls_for(info, slug, args):
            if deadline and time.time() > deadline:
                break
            before = len(out["media"])
            if not harvest(u, st_s):
                misses += 1
                if misses >= 4:
                    break
                continue
            misses = 0
            ok_pages += 1
            added = len(out["media"]) - before
            # "stop at last 10%": once a slug is producing, quit when the tail dries up —
            # 2 consecutive pages each adding < 10% of what we already have (min 3).
            if stop and ok_pages >= 3:
                if added < max(3, int(0.10 * before)):
                    weak += 1
                    if weak >= 2:
                        break
                else:
                    weak = 0
            if len(out["media"]) >= args.max_media:
                break
        # pass 1b: FULL numbered-post walk for sequential sites — the fix for "we don't
        # collect all the leaks". Depth is the site's true gallery size: the exact index set
        # from the grid (Tier-1) or a walk to the first run of consecutive-404s (Tier-2),
        # NOT --max-pages. Not subject to the 10%-tail stop: each post adds few media, so a
        # percentage rule would false-trip and re-truncate the gallery.
        gidx = (grid_indices(info, slug, args.timeout, deadline=deadline)
                if info.get("grid_url") and info.get("idx_type") == "seq" else None)
        dead = 0
        for u in post_urls_for(info, slug, args, gidx):
            if deadline and time.time() > deadline:
                break
            if len(out["media"]) >= args.max_media:
                break
            pr = urllib.parse.urlparse(u)
            posts_done.add((registrable(pr.netloc), pr.path.rstrip("/").rsplit("/", 1)[-1]))
            if not harvest(u, st_s):
                dead += 1
                if dead >= 5:            # 5 consecutive misses = past the last post (or a big gap)
                    break
                continue
            dead = 0
            out["pages"].add(u)          # record the post we actually walked (for slug_detail)
        # pass 2: post pages discovered as LINKS on the listing pages (id-based / SPA sites
        # with no seq content_url). Dedup by (canonical-host, numeric-id) so country mirrors
        # — pt./de./cz./es.fapello.com — don't multiply the fetch count, and order by id.
        if len(out["media"]) < args.max_media and not (deadline and time.time() > deadline):
            byid, order = {}, []
            for p in out["pages"]:
                pr = urllib.parse.urlparse(p)
                m = re.search(r"/(\d{3,})/?$", pr.path)
                if not m:
                    continue
                key = (registrable(pr.netloc), m.group(1))
                if key in posts_done or key in byid:
                    continue
                byid[key] = p
                order.append(key)
            order.sort(key=lambda k: int(k[1]))
            for key in order[:item_depth]:
                if deadline and time.time() > deadline:
                    break
                harvest(byid[key], st_s)
                if len(out["media"]) >= args.max_media:
                    break

    out["media_pairs"] = [[m, src] for m, src in sorted(out["media"].items())]
    out["pages"] = sorted(out["pages"])
    out["media"] = sorted(out["media"])
    out["slug_detail"] = build_slug_detail(slugs, out["media_pairs"], out["pages"])
    return out


def main():
    p = argparse.ArgumentParser(description="Deep crawl: search->real slugs->paginate/enumerate->media.")
    p.add_argument("names", nargs="*")
    p.add_argument("--names-file")
    p.add_argument("--map", default=os.path.join(HERE, "bruqi_detection_map.json"))
    p.add_argument("--domains", help="Comma list to restrict to (default: all verified).")
    p.add_argument("--out", default="data/leak-crawl")
    p.add_argument("--workers", type=int, default=10)
    p.add_argument("--timeout", type=int, default=15)
    p.add_argument("--politeness", type=float, default=0.4,
                   help="Min seconds between requests to the SAME host (rate-limit guard).")
    p.add_argument("--max-profiles", type=int, default=8, help="Max slugs to crawl per domain.")
    p.add_argument("--max-pages", type=int, default=8,
                   help="Max GRID/listing pages per slug (?page=N). Numbered posts are NOT capped "
                        "by this any more — see --item-depth.")
    p.add_argument("--item-depth", type=int, default=400,
                   help="Ceiling for the per-slug numbered-post walk on sequential sites when no "
                        "grid endpoint / idx_max is known. The real stop is the site's grid size "
                        "or a run of consecutive 404s; idx_max (from the map) caps it per-site.")
    p.add_argument("--max-media", type=int, default=2000, help="Cap media URLs per domain.")
    p.add_argument("--per-domain-budget", type=float, default=150.0,
                   help="Hard wall-clock cap per domain in seconds (prevents one slow host hanging the run); 0=off.")
    p.add_argument("--early-stop", action="store_true",
                   help="80/20: stop paginating a slug once the tail dries up (<10%% new media for 2 pages).")
    p.add_argument("--fast", action="store_true",
                   help="80/20 preset: --early-stop, no alias-expansion, tighter budget (overrides those defaults).")
    # Alias-expansion retry is OFF by default. It re-scanned the empty domains with the slugs
    # discovered in pass 1, but the matcher keeps a slug on a *substring* of a seed stem while the
    # trigger fired on *exact* stem inequality — so every SEO suffix-slug (`…-leak`, `…-tape`,
    # `…-1`) that still CONTAINS the seed stem was already found in pass 1, and the retry only ever
    # burned time (measured: 0 extra domains / 0 extra media on both juliafilippo and mckinley).
    # Opt back in with --expand only for the rare genuinely-different handle (old_usernames/cross-ref).
    p.add_argument("--expand", action="store_true",
                   help="Re-scan empty domains when pass 1 reveals a genuinely NEW identity "
                        "(different stem via old_usernames / cross-ref). OFF by default.")
    p.add_argument("--no-expand", action="store_true", help=argparse.SUPPRESS)  # deprecated: expansion is now off by default
    p.add_argument("--variations", action="store_true",
                   help="Auto-expand each name into near-miss handles (username_variations.py).")
    p.add_argument("--var-max", type=int, default=30, help="Max variations per name when --variations.")
    p.add_argument("--slug-cache", default=os.path.join(HERE, "slugs_cache.json"),
                   help="JSON domain->slugs, reused to seed discovery and updated each run.")
    p.add_argument("--no-slug-cache", action="store_true", help="Don't read or write the slug cache.")
    p.add_argument("--seed-slugs", default=None,
                   help="JSON domain->slugs harvested from the discovery stages (discovery_seed.py). "
                        "Injected into the frontier so the crawl visits real profile URLs its own "
                        "echo-page discovery can't reach (e.g. fapello.com display-name galleries).")
    args = p.parse_args()

    if args.fast:                       # 80/20 preset
        args.early_stop = True
        args.expand = False             # never expand in fast mode (already the default)
        if args.per_domain_budget in (0.0, 150.0):
            args.per_domain_budget = 60.0

    global MIN_INTERVAL, KNOWN_SLUGS
    MIN_INTERVAL = max(0.0, args.politeness)

    aliases = list(args.names)
    if args.names_file:
        with open(args.names_file, encoding="utf-8") as fh:
            aliases += [ln.strip() for ln in fh if ln.strip()]
    aliases = list(dict.fromkeys(aliases))
    if args.variations:
        from username_variations import expand_all
        aliases = expand_all(aliases, args.var_max)
    if not aliases:
        p.error("Provide at least one alias or --names-file.")

    dmap = json.load(open(args.map, encoding="utf-8"))
    want = set(d.strip() for d in args.domains.split(",")) if args.domains else None
    domains = {d: v for d, v in dmap.items()
               if v.get("check_url") and v.get("verified") and (not want or d in want)}

    # seed discovery with slugs confirmed on past runs (only those matching this creator)
    slug_cache = {}
    if not args.no_slug_cache and os.path.exists(args.slug_cache):
        try:
            slug_cache = json.load(open(args.slug_cache, encoding="utf-8"))
        except Exception:
            slug_cache = {}
    alias_stems = {stem(a) for a in aliases if stem(a)}
    KNOWN_SLUGS = {d: [s for s in sl if any(st in norm(s) for st in alias_stems)]
                   for d, sl in slug_cache.items()}
    KNOWN_SLUGS = {d: v for d, v in KNOWN_SLUGS.items() if v}
    if KNOWN_SLUGS:
        print(f"Slug cache: seeded {sum(len(v) for v in KNOWN_SLUGS.values())} known slugs "
              f"across {len(KNOWN_SLUGS)} domains.", file=sys.stderr)

    # frontier injection: profile slugs the discovery stages surfaced but this crawl's own
    # echo-page discovery can't reach (display-name galleries on JS-search sites). Same
    # alias-stem filter as the cache. The Q1 sibling probe then fills the numbered family.
    if args.seed_slugs and os.path.exists(args.seed_slugs):
        try:
            seed = json.load(open(args.seed_slugs, encoding="utf-8"))
        except Exception:
            seed = {}
        added = 0
        for d, sl in (seed.items() if isinstance(seed, dict) else []):
            keep = [s for s in sl if any(st in norm(s) for st in alias_stems)]
            if not keep:
                continue
            before = set(KNOWN_SLUGS.get(d, []))
            KNOWN_SLUGS[d] = sorted(before | set(keep))
            added += len(KNOWN_SLUGS[d]) - len(before)
        if added:
            print(f"Seed slugs: injected {added} discovered profile slug(s) into the frontier "
                  f"from {os.path.basename(args.seed_slugs)}.", file=sys.stderr)

    def run_pass(alias_set):
        out = []
        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(crawl_domain, d, info, alias_set, args): d for d, info in domains.items()}
            done = 0
            for fut in cf.as_completed(futs):
                r = fut.result()
                out.append(r)
                done += 1
                if r["slugs"]:
                    print(f"  [{done}/{len(domains)}] {r['domain']}: slugs={','.join(r['slugs'])[:48]} "
                          f"-> {len(r['pages'])} pages, {len(r['media'])} media", file=sys.stderr)
                else:
                    print(f"\r  [{done}/{len(domains)}]", end="", file=sys.stderr, flush=True)
                # checkpoint: persist partial results so one slow/hanging host can never
                # block the whole crawl's output — the JSON is always up to date.
                if done % 3 == 0 or done == len(futs):
                    try:
                        json.dump(sorted(out, key=lambda x: -len(x["media"])),
                                  open(f"{args.out}.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
                    except Exception:
                        pass
        print("", file=sys.stderr)
        return out

    print(f"Deep-crawling {len(domains)} domains for {len(aliases)} aliases ...", file=sys.stderr)
    results = run_pass(aliases)

    # alias expansion (opt-in via --expand): if a site revealed a genuinely NEW identity (a slug
    # whose norm does NOT contain any seed stem — an alt handle / old stage name, not a `-tape`
    # suffix which already matched in pass 1), fold it in and re-scan for it. "Genuinely new"
    # keeps the trigger consistent with the keep rule (line ~582), so this never re-hunts a
    # suffix-slug that was already found.
    #
    # Q1 cross-site propagation: re-scan the EMPTY domains AND the productive domains that have a
    # profile template — a site can file the creator under an alt handle it never LINKED while
    # still hosting her main handle, so productive sites need the new identity tried too. Results
    # on productive domains are MERGED (never replaced), so their pass-1 content is preserved.
    if args.expand:
        seed_stems = {stem(a) for a in aliases}
        discovered = {s for r in results for s in r["slugs"]}
        new_ids = sorted(s for s in discovered
                         if norm(s) and not any(st in norm(s) for st in seed_stems))
        rescan = {r["domain"]: dmap[r["domain"]] for r in results
                  if (not r["media"] and not r["pages"]) or profile_template(dmap[r["domain"]])}
        if new_ids and rescan:
            # only the NEW identities are added to the alias set — suffix-slugs were already
            # matched in pass 1, so re-passing them would just re-hammer for nothing.
            expanded = list(dict.fromkeys(aliases + new_ids))[:MAX_DISCOVERY_ALIASES]
            print(f"Alias expansion: new identities {new_ids[:12]}{' …' if len(new_ids) > 12 else ''}; "
                  f"re-scanning {len(rescan)} domains with {len(expanded)} aliases ...",
                  file=sys.stderr)
            domains_all, domains = domains, rescan
            retry = run_pass(expanded)
            domains = domains_all
            by = {r["domain"]: r for r in results}
            for r in retry:
                old = by.get(r["domain"])
                if old and (old["media"] or old["pages"]):
                    by[r["domain"]] = merge_domain_result(old, r)   # productive: keep + add
                elif r["media"] or r["pages"]:
                    by[r["domain"]] = r                             # was empty: take the hit
            results = list(by.values())

    results.sort(key=lambda r: -len(r["media"]))
    json.dump(results, open(f"{args.out}.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    all_slugs = sorted({f"{r['domain']}:{s}" for r in results for s in r["slugs"]})
    all_pages = sorted({u for r in results for u in r["pages"]})
    all_media = sorted({u for r in results for u in r["media"]})
    all_pairs = sorted({(m, src) for r in results for m, src in r.get("media_pairs", [])})
    for name, data in [("slugs", all_slugs), ("pages", all_pages), ("media", all_media)]:
        with open(f"{args.out}.{name}.txt", "w", encoding="utf-8") as fh:
            fh.write("\n".join(data) + ("\n" if data else ""))
    with open(f"{args.out}.pairs.txt", "w", encoding="utf-8") as fh:   # <img_url>\t<source page it was found on>
        fh.write("\n".join(f"{m}\t{src}" for m, src in all_pairs) + ("\n" if all_pairs else ""))
    with open(f"{args.out}.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["domain", "type", "url", "source"])
        for r in results:
            for u in r["pages"]:
                w.writerow([r["domain"], "page", u, ""])
            for m, src in r.get("media_pairs", []):
                w.writerow([r["domain"], "media", m, src])

    # persist every slug we confirmed this run so future runs start ahead
    if not args.no_slug_cache:
        for r in results:
            if r.get("slugs"):
                slug_cache[r["domain"]] = sorted(set(slug_cache.get(r["domain"], [])) | set(r["slugs"]))
        try:
            json.dump(slug_cache, open(args.slug_cache, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
            print(f"Slug cache updated: {sum(len(v) for v in slug_cache.values())} slugs "
                  f"across {len(slug_cache)} domains -> {args.slug_cache}", file=sys.stderr)
        except Exception as e:
            print(f"(could not write slug cache: {e})", file=sys.stderr)

    hit = [r for r in results if r["media"] or r["pages"]]
    print(f"\nDONE. {len(hit)} domains with content | {len(all_pages)} pages, {len(all_media)} media URLs.",
          file=sys.stderr)
    print(f"Files: {args.out}.slugs.txt / .pages.txt / .media.txt / .pairs.txt / .json / .csv", file=sys.stderr)


if __name__ == "__main__":
    main()

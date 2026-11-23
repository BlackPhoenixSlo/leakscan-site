"""
Level-1 "quick" scan — Google Programmable Search (Custom Search JSON API).

Anyone can run it; no ownership check. Two-pass "exclude-reset" strategy (matches
the Operator pipeline approach): search once, dedup the domains found, then search again
excluding those domains via -site: to surface NEW leak sites. Also extracts a
Google-hosted thumbnail per result for a (blurred) preview grid. Fast, no
site-scraping. Reads GOOGLE_API_KEY + GOOGLE_CSE_ID from env. Stdlib only.
"""

import json
import os
import re
import urllib.parse
import urllib.request
from urllib.parse import urlparse

CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"
MAX_EXCLUDE = 9   # cap -site: exclusions so the query stays short


def _host(link):
    try:
        h = (urlparse(link).hostname or "").lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def cse_available():
    return bool(os.environ.get("GOOGLE_API_KEY") and os.environ.get("GOOGLE_CSE_ID"))


# ── billable-call meter ──────────────────────────────────────────────────────
# Every _call() that returns a response is one billed Google CSE query. This counter lets a run
# report EXACTLY how many queries it spent (build_cse prints it), instead of the derived ceiling.
_CALLS = 0


def reset_calls():
    global _CALLS
    _CALLS = 0


def calls_spent():
    return _CALLS


def _call(query, key, cx, start=1, timeout=20, search_type=None):
    global _CALLS
    p = {"key": key, "cx": cx, "q": query, "num": 10, "start": start, "safe": "off"}
    if search_type:                     # e.g. "image" → Google IMAGE search (actual indexed images)
        p["searchType"] = search_type
    params = urllib.parse.urlencode(p)
    with urllib.request.urlopen(f"{CSE_ENDPOINT}?{params}", timeout=timeout) as r:
        raw = r.read().decode("utf-8")
    _CALLS += 1                         # count only calls that returned (i.e. were billed)
    return json.loads(raw)


# ── spelling-correction follow-through ───────────────────────────────────────
# The #1 reason a scan finds NOTHING is a handle typo: the alias fed in (e.g.
# "creatorpxo") is a variant Google doesn't index, so every query returns 0 —
# while Google's own response names the token it DOES index ("creatorp") in
# spelling.correctedQuery. We were throwing that field away. Now we follow it:
# retry the empty call with Google's correction and REMEMBER single-token handle
# fixes so later queries in the run skip straight to the spelling Google indexes.
# Generic leak keywords (leaks→leaked, etc.) are corrected per-call but NOT
# remembered, so the seed phrasing is preserved across queries.
_KEYWORD_TOKENS = {"leak", "leaks", "leaked", "leaking", "nude", "nudes", "naked",
                   "porn", "onlyfans", "of", "videos", "video", "vids", "sex",
                   "xxx", "free", "new", "photos", "pics", "gallery"}


def _tokenize(s):
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def _handle_fix(query, corrected):
    """If Google's spelling correction changes exactly ONE non-keyword token
    (a handle/name typo like creatorpxo→creatorp), return {wrong: right};
    otherwise {}. Multi-token rewrites and keyword-only corrections aren't
    remembered so intentional seed phrasing survives."""
    ow, cw = _tokenize(query), _tokenize(corrected)
    if len(ow) != len(cw):
        return {}
    diffs = [(a, b) for a, b in zip(ow, cw) if a != b]
    if len(diffs) != 1:
        return {}
    wrong, right = diffs[0]
    if not wrong or not right or wrong in _KEYWORD_TOKENS:
        return {}
    return {wrong: right}


def _apply_fix(text, fixes):
    if not fixes:
        return text
    return re.sub(r"[A-Za-z0-9]+",
                  lambda m: fixes.get(m.group(0).lower(), m.group(0)), text)


def _call_sp(query, key, cx, fixes, start=1, timeout=20, search_type=None, on_progress=None):
    """_call that transparently follows Google's spelling correction. `fixes` is a
    run-scoped dict of learned handle corrections (mutated in place): known fixes are
    applied to the query up front, and if a query still comes back empty while Google
    suggests a correction, we retry that single call with the corrected query and
    remember any single-token handle fix so subsequent queries never waste a call on
    the un-indexed spelling again."""
    q = _apply_fix(query, fixes)
    d = _call(q, key, cx, start=start, timeout=timeout, search_type=search_type)
    if d.get("items"):
        return d
    corrected = (d.get("spelling") or {}).get("correctedQuery")
    if not corrected or corrected == q:
        return d
    new = _handle_fix(q, corrected)
    if new and not (set(new.items()) <= set(fixes.items())):
        fixes.update(new)
        if on_progress:
            on_progress("spelling: " + ", ".join(f"{k}→{v}" for k, v in new.items()))
    d2 = _call(corrected, key, cx, start=start, timeout=timeout, search_type=search_type)
    return d2 if d2.get("items") else d


def _parse_items(d):
    out = []
    for it in d.get("items", []) or []:
        link = it.get("link")
        if not link:
            continue
        pm = it.get("pagemap", {}) or {}
        thumb = None
        cts = pm.get("cse_thumbnail") or []
        if cts:
            thumb = cts[0].get("src")   # Google-hosted (encrypted-tbn0.gstatic.com)
        out.append({
            "title": it.get("title", ""),
            "link": link,
            "snippet": it.get("snippet", ""),
            "host": _host(link),
            "image": thumb,
        })
    return out


def cse_search(query, pages=2, api_key=None, cx=None, timeout=20, on_progress=None):
    """Two-pass search. Returns (results, google_total). Pass 1 gets the top
    results; pass 2 re-queries excluding pass-1 domains (-site:) to widen domain
    coverage. Deduped by link. Raises on a hard first-page API error."""
    key = api_key or os.environ.get("GOOGLE_API_KEY", "")
    cid = cx or os.environ.get("GOOGLE_CSE_ID", "")
    if not key or not cid:
        raise RuntimeError("CSE not configured (GOOGLE_API_KEY / GOOGLE_CSE_ID missing)")

    if on_progress:
        on_progress("Searching Google for public copies…")
    fixes = {}
    d1 = _call_sp(query, key, cid, fixes, start=1, timeout=timeout, on_progress=on_progress)
    total = d1.get("searchInformation", {}).get("totalResults")
    items = _parse_items(d1)
    seen = {i["link"] for i in items}
    domains = []
    for i in items:
        if i["host"] and i["host"] not in domains:
            domains.append(i["host"])
    if on_progress:
        on_progress(f"Found {len(items)} results across {len(domains)} sites; widening the search…")

    if pages >= 2 and domains:
        negs = " ".join(f"-site:{d}" for d in domains[:MAX_EXCLUDE])
        try:
            d2 = _call_sp(f"{query} {negs}", key, cid, fixes, start=1, timeout=timeout)
            added = 0
            for i in _parse_items(d2):
                if i["link"] not in seen:
                    seen.add(i["link"])
                    items.append(i)
                    added += 1
            if on_progress:
                on_progress(f"Second pass found {added} more result(s) on new sites.")
        except Exception:
            pass  # second pass is best-effort

    return items, total


try:
    from netloc import registrable_domain as _regdom
except Exception:                                   # keep cse_scanner importable standalone
    def _regdom(h):
        h = (h or "").lower()
        if h.startswith("www."):
            h = h[4:]
        parts = h.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else h


def cse_search_deep(query, max_calls=15, api_key=None, cx=None, timeout=20,
                    q_budget=1900, on_progress=None):
    """Iterative 'exclude-reset' widening. Call 1 is the plain query; every later
    call appends `-site:<registrable-domain>` for EVERY domain seen so far, so
    Google is forced to surface NEW sites each round. Excluding the registrable
    domain knocks out all subdomain mirrors (residenceinn/uniprotest.thefap.net)
    at once. Stops early after two consecutive rounds that add no new results, or
    when the exclusion clause would blow the query-length budget. Returns
    (items, google_total_from_first_call)."""
    key = api_key or os.environ.get("GOOGLE_API_KEY", "")
    cid = cx or os.environ.get("GOOGLE_CSE_ID", "")
    if not key or not cid:
        raise RuntimeError("CSE not configured (GOOGLE_API_KEY / GOOGLE_CSE_ID missing)")

    seen_links, items = set(), []
    excl = []            # ordered list of registrable domains to exclude (-site:)
    total = None
    dry = 0
    fixes = {}
    for call in range(max_calls):
        negs = " ".join(f"-site:{d}" for d in excl)
        # trim oldest exclusions if the query would exceed the budget
        while negs and len(query) + 1 + len(negs) > q_budget:
            excl = excl[1:]
            negs = " ".join(f"-site:{d}" for d in excl)
        q = f"{query} {negs}".strip()
        try:
            d = _call_sp(q, key, cid, fixes, start=1, timeout=timeout, on_progress=on_progress)
        except Exception as e:
            if on_progress:
                on_progress(f"call {call+1}: API error ({e}); stopping")
            break
        if total is None:
            total = d.get("searchInformation", {}).get("totalResults")
        added, new_doms = 0, 0
        for it in _parse_items(d):
            if it["link"] in seen_links:
                continue
            seen_links.add(it["link"])
            items.append(it)
            added += 1
            rd = _regdom(it.get("host") or "")
            if rd and rd not in excl:
                excl.append(rd)
                new_doms += 1
        if on_progress:
            on_progress(f"call {call+1}/{max_calls}: +{added} results, "
                        f"+{new_doms} domains ({len(excl)} excluded next)")
        if added == 0:
            dry += 1
            if dry >= 2:
                break
        else:
            dry = 0
    return items, total


def cse_search_wide(queries, max_calls=15, api_key=None, cx=None, timeout=20,
                    q_budget=1900, on_progress=None):
    """Multi-seed exclude-reset widening. Same idea as cse_search_deep but CYCLES
    through several seed queries (e.g. the base query + `<h> nude` + `<h> porn`) so
    different phrasings surface different leak sites — while sharing ONE exclusion
    set across all seeds, so every later call `-site:`-excludes every domain any
    seed has seen. Stops after a full cycle of seeds adds nothing new. Returns
    (items, google_total_from_first_call)."""
    key = api_key or os.environ.get("GOOGLE_API_KEY", "")
    cid = cx or os.environ.get("GOOGLE_CSE_ID", "")
    if not key or not cid:
        raise RuntimeError("CSE not configured (GOOGLE_API_KEY / GOOGLE_CSE_ID missing)")
    if isinstance(queries, str):
        queries = [queries]

    seen_links, items, excl = set(), [], []
    total, dry, fixes = None, 0, {}
    for call in range(max_calls):
        base = queries[call % len(queries)]
        negs = " ".join(f"-site:{d}" for d in excl)
        while negs and len(base) + 1 + len(negs) > q_budget:   # keep query under limit
            excl = excl[1:]
            negs = " ".join(f"-site:{d}" for d in excl)
        q = f"{base} {negs}".strip()
        try:
            d = _call_sp(q, key, cid, fixes, start=1, timeout=timeout, on_progress=on_progress)
        except Exception as e:
            if on_progress:
                on_progress(f"call {call+1}: API error ({e}); stopping")
            break
        if total is None:
            total = d.get("searchInformation", {}).get("totalResults")
        added, new_doms = 0, 0
        for it in _parse_items(d):
            if it["link"] in seen_links:
                continue
            seen_links.add(it["link"])
            items.append(it)
            added += 1
            rd = _regdom(it.get("host") or "")
            if rd and rd not in excl:
                excl.append(rd)
                new_doms += 1
        if on_progress:
            on_progress(f"call {call+1}/{max_calls} [{base[:28]}]: +{added} results, "
                        f"+{new_doms} domains ({len(excl)} excluded next)")
        # stop only after a WHOLE cycle of seeds yields nothing new
        dry = dry + 1 if added == 0 else 0
        if dry >= len(queries):
            break
    return items, total


def summarize_cse(results):
    """Group CSE results by host into rows compatible with the results UI:
    {domain, url, occurrences, method, alias, live, title}."""
    by_host = {}
    for r in results or []:
        h = r.get("host")
        if not h:
            continue
        e = by_host.get(h)
        if e is None:
            e = {"domain": h, "url": r.get("link"), "occurrences": 0,
                 "method": "google", "alias": None, "live": True,
                 "title": (r.get("title") or "")[:120]}
            by_host[h] = e
        e["occurrences"] += 1
    return sorted(by_host.values(), key=lambda x: x["occurrences"], reverse=True)


def cse_images(results, limit=12):
    """Deduped list of Google-hosted thumbnail URLs for a blurred preview grid."""
    seen, out = set(), []
    for r in results or []:
        img = r.get("image")
        if img and img not in seen:
            seen.add(img)
            out.append(img)
        if len(out) >= limit:
            break
    return out


def _parse_image_items(d):
    """Parse a searchType=image response → real indexed IMAGES. Each item's `link` is the full
    image URL; `image.thumbnailLink` is the Google-hosted thumbnail (loads reliably, no hotlink
    block); `image.contextLink` is the page it's on."""
    out = []
    for it in d.get("items", []) or []:
        img = it.get("image", {}) or {}
        thumb = img.get("thumbnailLink")
        if not thumb:
            continue
        ctx = img.get("contextLink") or it.get("link") or ""
        out.append({
            "image": thumb,                      # Google-hosted thumbnail (encrypted-tbn0.gstatic.com)
            "full": it.get("link", ""),
            "host": _host(ctx),
            "title": it.get("title", ""),
        })
    return out


def cse_image_search(queries, max_calls=9, api_key=None, cx=None, timeout=20,
                     q_budget=1900, on_progress=None):
    """Google IMAGE search (searchType=image) across several seed queries, sharing ONE `-site:`
    exclusion set so each later call surfaces NEW hosts' images. Returns actual Google-indexed
    leak IMAGES (Google-hosted thumbnails) for the keywords — not web-page pagemap images. Deduped
    by thumbnail. Never raises (returns [] if CSE isn't configured or the API errors)."""
    key = api_key or os.environ.get("GOOGLE_API_KEY", "")
    cid = cx or os.environ.get("GOOGLE_CSE_ID", "")
    if not key or not cid:
        return []
    if isinstance(queries, str):
        queries = [queries]
    seen, out, excl, dry, fixes = set(), [], [], 0, {}
    for call in range(max_calls):
        base = queries[call % len(queries)]
        negs = " ".join(f"-site:{d}" for d in excl)
        while negs and len(base) + 1 + len(negs) > q_budget:
            excl = excl[1:]
            negs = " ".join(f"-site:{d}" for d in excl)
        q = f"{base} {negs}".strip()
        try:
            d = _call_sp(q, key, cid, fixes, start=1, timeout=timeout,
                         search_type="image", on_progress=on_progress)
        except Exception as e:
            if on_progress:
                on_progress(f"image call {call+1}: API error ({e}); stopping")
            break
        added = 0
        for it in _parse_image_items(d):
            if it["image"] in seen:
                continue
            seen.add(it["image"])
            out.append(it)
            added += 1
            rd = _regdom(it.get("host") or "")
            if rd and rd not in excl:
                excl.append(rd)
        if on_progress:
            on_progress(f"image call {call+1}/{max_calls} [{base[:24]}]: +{added} images "
                        f"({len(out)} total)")
        dry = dry + 1 if added == 0 else 0
        if dry >= len(queries):
            break
    return out


# Hosts that turn up in "<handle> leaks/nude/porn" results but are NOT leak hosts
# — their thumbnails are the creator's own socials, news, wikis or storefronts, so
# they're the "bad" images to drop from the preview strip and the shareable poster.
_BAD_IMG_HOSTS = {
    "tiktok.com", "instagram.com", "reddit.com", "redd.it", "x.com", "twitter.com",
    "youtube.com", "youtu.be", "facebook.com", "fb.com", "pinterest.com", "threads.net",
    "wikipedia.org", "wikimedia.org", "fandom.com", "linkedin.com", "imdb.com",
    "spotify.com", "twitch.tv", "tumblr.com", "quora.com", "amazon.com", "ebay.com",
    "google.com", "bing.com", "yahoo.com", "gstatic.com",
}


# A thumbnail is likely a real leaked-content image when it comes off an actual
# CONTENT page (a video/post/photo/gallery URL, or one whose slug names the
# creator) — and likely a site LOGO / ad banner when it comes off a search / tag /
# category / homepage. We can't see the pixels in the quick scan (stdlib, no
# vision), so we score by URL shape + handle relevance and rank the good ones up.
_CONTENT_HINTS = ("/video", "/post", "/photo", "/image", "/img/", "/gallery",
                  "/album", "/media", "/watch", "/v/", "/p/", "/pic")
_JUNK_HINTS = ("/search", "?s=", "?q=", "&q=", "/tag/", "/tags/", "/category",
               "/categories", "/models", "/model/", "/pornstar", "/browse")


def _img_score(r, tok):
    link = (r.get("link") or "").lower()
    title = (r.get("title") or "").lower()
    after = link.split("//", 1)[-1]
    path = after[after.find("/"):] if "/" in after else "/"
    s = 0
    if tok and tok in re.sub(r"[^a-z0-9]", "", link + " " + title):
        s += 2                                   # names the creator → probably their content
    if any(h in link for h in _CONTENT_HINTS):
        s += 2                                   # a content page, not an index
    if re.search(r"/\d{4,}", link):
        s += 1                                   # numeric content id
    if path in ("", "/"):
        s -= 3                                   # homepage → its og:image is the site logo
    elif any(h in link for h in _JUNK_HINTS):
        s -= 2                                   # search / tag / category / model index → logo/ad
    return s


def good_images(results, handle="", limit=12, bad_hosts=None):
    """"Good vs bad" thumbnail filter for the preview strip / poster. Drops results
    from social / news / non-leak hosts and de-dupes by image URL, then RANKS the
    rest so real leaked-content thumbnails (content-page URLs that name the creator)
    come before site logos / ad banners (search / tag / homepage thumbnails). This
    is the quick-scan approximation of the deep scan's vision gallery-vetting — it
    can't see pixels, so a logo off a content page can still slip through. Falls
    back to the raw thumbnails only if filtering leaves nothing."""
    bad = set(_BAD_IMG_HOSTS) | set(bad_hosts or [])
    tok = re.sub(r"[^a-z0-9]", "", (handle or "").lower())
    seen, scored = set(), []
    for i, r in enumerate(results or []):
        img = r.get("image")
        if not img or img in seen:
            continue
        if _regdom(r.get("host") or "") in bad:
            continue
        seen.add(img)
        scored.append((_img_score(r, tok), -i, img))   # higher score first, then earlier
    scored.sort(reverse=True)
    out = [img for _, _, img in scored]
    return out[:limit] or cse_images(results, limit)


def cse_paginate(query, pages=1, start=11, api_key=None, cx=None, timeout=20, on_progress=None):
    """Fetch extra result pages (start=11, 21, …) of the base query — a shallow
    depth fallback for when the widening pass surfaced too few distinct sites.
    Never raises; returns [] if CSE isn't configured."""
    key = api_key or os.environ.get("GOOGLE_API_KEY", "")
    cid = cx or os.environ.get("GOOGLE_CSE_ID", "")
    if not key or not cid:
        return []
    out, s = [], start
    for _ in range(max(0, pages)):
        try:
            d = _call(query, key, cid, start=s, timeout=timeout)
        except Exception:
            break
        items = _parse_items(d)
        if on_progress:
            on_progress(f"depth page @{s}: +{len(items)} result(s)")
        if not items:
            break
        out += items
        s += 10
    return out

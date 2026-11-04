#!/usr/bin/env python3
"""Evidence classification for leak-scan hits — kill search-echo false positives.

A search page (``fapeza.com/search/{name}``, ``naswup.com/?s={name}``) returns
HTTP 200 and echoes the handle all over its chrome (search box, title, language
switcher) even when it hosts NONE of the creator's content — the search just
shows "other videos". The raw scanner counts those echoes and reports a fat
"hit", which is exactly the junk that pollutes the public report.

We separate real hosting from echoes by evidence class:

  google           Google-CSE row (Google indexed it) ................... trust
  profile          dedicated page for the handle (/{name}/, /models/…) .. trust
  tag              curated tag listing (/tags/{name}/) ................... trust
  search-verified  a search page that DOES link the creator's content ... keep
  search-echo      a search page with no creator content links .......... DROP

Profile and tag pages are trusted, not URL-token-verified: the handle is a
canonical path the SITE created for the creator, and tag pages routinely link
their videos by numeric id (camwhores.tv/tags/<h>/) so a URL-token check would
wrongly drop a real page. Only full-text SEARCH pages are content-verified,
because that is where the "other videos" echoes live — we keep such a hit only
when the page links at least one piece of content whose URL carries the handle.
"""

import re

# --- shape detection (URL only, no page body needed) ------------------------
_SEARCH_Q = re.compile(r'[?&](s|q|k|kw|wd|word|find|query|keyword|search|term|text)=', re.I)
_SEARCH_PATH = re.compile(r'/search(?:/|\b|\?|$)|searchgate\.php', re.I)
_TAG_PATH = re.compile(r'/tags?/', re.I)

# Page chrome (not creator content) — excluded when counting content evidence.
_NAV = re.compile(
    r'(\?s=|[?&](q|s|k|kw|query|keyword|search|term|lang|hl|p|page|paged|start|o|sort|order|d|c)=|'
    r'/search|/tags?/|/categor|/rss|/feed|/wp-json|/wp-admin|/wp-includes|/wp-login|oembed|'
    r'/page/|/login|/register|/signup|/join|/dmca|/contact|/about|/terms|/privacy|'
    r'\.css(?:\?|$)|\.js(?:\?|$)|/cdn-cgi/|addtoany|sharer|/share|'
    r'(?:facebook|twitter|x)\.com|t\.me|/telegram|reddit\.com|pinterest|tumblr\.com|'
    r'youtube\.com|whatsapp|/ajax)', re.I)


def norm(s):
    """Lowercase, keep only alphanumerics (so h.1 / h_1 / h1 all compare equal)."""
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def handle_variants(alias):
    """A hit's alias plus its digit/separator-stripped 'core', both normalized,
    so a 'cinnanicos2' hit still matches a '/cinnanicos-nicky/' content URL."""
    out = set()
    a = norm(alias)
    if a:
        out.add(a)
    core = norm(re.sub(r'[0-9_.\-]+$', '', alias or ''))
    if len(core) >= 4:
        out.add(core)
    return out


def url_shape(url, method=None):
    """'google' | 'search' | 'tag' | 'profile' from the URL/method alone."""
    if method == 'google':
        return 'google'
    u = url or ''
    if _SEARCH_Q.search(u) or _SEARCH_PATH.search(u):
        return 'search'
    if _TAG_PATH.search(u):
        return 'tag'
    return 'profile'


def _content_urls(body):
    urls = re.findall(r'(?:href|src)\s*=\s*["\']([^"\']+)["\']', body or '', re.I)
    urls += re.findall(r'https?://[^\s"\'<>()]+', body or '')
    return urls


def content_matches(body, variants):
    """Count DISTINCT content URLs on the page that carry any handle variant,
    excluding search/nav/lang/asset/social chrome. Returns (count, samples).
    This is the evidence a search actually returned the creator's content."""
    vs = [v for v in (variants or []) if v]
    if not vs or not body:
        return 0, []
    seen = set()
    for u in _content_urls(body):
        if _NAV.search(u):
            continue
        nu = norm(u)
        if any(v in nu for v in vs):
            seen.add(re.split(r'[?#]', u, 1)[0])   # drop query so ?lang dupes fold
    return len(seen), sorted(seen)[:5]


def classify(url, method, body, alias):
    """Evidence label for a hit. `body` is only consulted for search shapes."""
    shape = url_shape(url, method)
    if shape in ('google', 'profile', 'tag'):
        return shape
    n, _ = content_matches(body, handle_variants(alias))
    return 'search-verified' if n > 0 else 'search-echo'


REAL = {'google', 'profile', 'tag', 'search-verified', 'search-unverified'}


def is_real(evidence):
    """True unless the hit is a content-less search echo."""
    return evidence in REAL or evidence is None  # None = un-classified, keep

#!/usr/bin/env python3
"""slug_probe — live-confirm the per-tile padding theory (see DEDUP_CODEX.md).

Fetches a leak-site search/tag/profile page, pulls every RESULT TILE's detail-URL
slug + title out of the grid, and classifies each tile TARGET / AMBIGUOUS / PADDING
against the campaign's alias tokens. Prints a per-site verdict and lists the padding
slugs so you can eyeball-confirm the observation ("this search never shows her —
it's Angela White / Mz Dani / Jerbear filler") straight from the log.

This is the *tier-1* gate from the codex made observable: it does NOT drop anything
from the pipeline — it only reports what a per-tile gate WOULD see. The page-level
search-echo verdict (leak_evidence.classify) stays the only thing with drop authority.

    python3 slug_probe.py --campaign juliafilippo URL [URL ...]
    python3 slug_probe.py --campaign juliafilippo --urls-file campaigns/juliafilippo/juliafilippo.search.links.txt
    python3 slug_probe.py --tokens juliafilippo,julia,filippo --name "Julia Filippo" URL ...

Reuses leak_crawler.fetch (real UA, gzip, throttle, retry) and leak_evidence.url_shape.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

# Reuse the existing pipeline plumbing so this reads like the rest of the repo.
from leak_crawler import fetch, MEDIA_NOISE          # (status, final_url, html) + logo/avatar regex
from netloc import newest_path
from leak_evidence import url_shape, handle_variants, norm, _NAV

# Routes that carry an actual result tile (a video/thread/album/gallery detail page).
_DETAIL_ROUTE = re.compile(
    r'/(?:video|videos|watch|v|embed|thread|threads|topic|topics|album|albums|'
    r'gallery|galleries|post|posts|media|clip|clips|movie|movies|scene|scenes|'
    r'photo|photos|set|sets)/', re.I)

# A path segment that looks like a numeric content id (dedup key + "is this a tile" hint).
_ID_SEG = re.compile(r'^\d{2,}$')

# A slug segment that looks like a title (>=2 words), used as a generic-route fallback.
_SLUGGY = re.compile(r'^[a-z0-9]+(?:[-_][a-z0-9]+){2,}$', re.I)


# ----------------------------------------------------------------------------- tokens
def build_target(tokens, name):
    """Return (strong_substrings, name_tokens).

    strong_substrings: flat (alnum-only) alias forms >=8 chars — safe to substring-match
        anywhere in a slug ('juliafilippo' inside 'onlyfans-leaked-juliafilippo').
    name_tokens: individual given/family-name tokens (>=3 chars) — matched on WORD
        boundaries only (so short 'julia' can't hit a random word); TARGET needs >=2
        of them, AMBIGUOUS if only one.
    """
    strong, names = set(), set()
    for t in tokens:
        for v in handle_variants(t):
            if len(v) >= 8:
                strong.add(v)
        # split the raw alias on separators to recover name parts (julia.filippo -> julia, filippo)
        for part in re.split(r'[^a-z0-9]+', (t or '').lower()):
            if len(part) >= 3 and not part.isdigit():
                names.add(part)
    for part in re.split(r'\s+', (name or '').strip().lower()):
        part = norm(part)
        if len(part) >= 3:
            names.add(part)
    # a lone all-in-one handle like 'juliafilippo' shouldn't also live in name_tokens
    # (it's already a strong substring); keep only genuine short parts there.
    names = {n for n in names if n not in strong}
    return strong, names


def classify(slug, title, strong, names):
    """TARGET / AMBIGUOUS / PADDING for one tile, with a human 'why'."""
    flat = norm(slug + ' ' + title)                       # alnum-only, for substring hits
    words = set(re.split(r'[^a-z0-9]+', (slug + ' ' + title).lower())) - {''}
    hit_strong = sorted(s for s in strong if s in flat)
    hit_names = sorted(n for n in names if n in words)
    if hit_strong:
        return 'target', f"handle «{hit_strong[0]}» in slug/title"
    if len(hit_names) >= 2:
        return 'target', f"name tokens {hit_names} present"
    if len(hit_names) == 1:
        return 'ambiguous', f"only «{hit_names[0]}» — could be a different person"
    return 'padding', 'no target token'


# ----------------------------------------------------------------------------- extract
# alt/anchor text that means "page chrome / ad", not a result tile.
_ALT_STOP = {'', 'logo', 'search', 'home', 'menu', 'premium', 'go premium', 'login', 'log in',
             'register', 'sign up', 'signup', 'join', 'next', 'prev', 'previous', 'more',
             'advertisement', 'ad', 'ads', 'banner', 'close', 'share', 'download', 'upload',
             'play onlyfans videos', 'categories', 'models', 'tags', 'channels'}


def _title_of(a):
    """Best title for an anchor: its title attr, its text, or a child img's alt/title."""
    for cand in (a.get('title'), a.get_text(' ', strip=True)):
        if cand and cand.strip():
            return cand.strip()
    img = a.find('img')
    if img:
        for cand in (img.get('alt'), img.get('title'), img.get('data-title')):
            if cand and cand.strip():
                return cand.strip()
    return ''


def _is_ad_or_chrome(alt, src):
    a = (alt or '').strip().lower()
    if a in _ALT_STOP or 'logo' in a or 'advert' in a:
        return True
    return bool(src and MEDIA_NOISE.search(src))


def extract_tiles(base_url, html):
    """Every result tile on the page: dedup'd list of {path, id, slug, title, url}.

    Layered so it works on both plain-HTTP grids and rendered model-slug grids:
      A. route tiles  — href matches a /video|thread|album|... route (the common leak-tube shape)
      B. thumbnail tiles — <a> wrapping an <img> with a real alt (nudogram /models/<slug>/ grids)
      C. sluggy tiles — a title-shaped last path segment (last-ditch)
    B and C only fire if A found nothing, so the working HTTP cases are unchanged."""
    soup = BeautifulSoup(html, 'lxml')
    host = urlparse(base_url).netloc
    reg = '.'.join(host.split('.')[-2:]) if host else ''
    tiles, seen = [], {}

    def add(href, title, img_src=None):
        href = (href or '').strip()
        if not href or href.startswith(('#', 'javascript:', 'mailto:')):
            return
        full = urljoin(base_url, href)
        p = urlparse(full)
        if p.netloc and reg and reg not in p.netloc:       # off-site (ads, socials) — skip
            return
        path = p.path
        segs = [s for s in path.split('/') if s]
        if not segs:
            return
        if _NAV.search(path) and not _DETAIL_ROUTE.search(path):
            return                                         # /search/, /tags/, /login chrome
        tid = next((s for s in segs if _ID_SEG.match(s)), None)
        slug = segs[-1] if not _ID_SEG.match(segs[-1]) else (segs[-2] if len(segs) > 1 else segs[-1])
        # a real tile carries an id or a title-shaped slug; bare nav routes are chrome
        if not tid and not ('-' in slug or '_' in slug or len(slug) >= 16):
            return
        key = (reg, path.rstrip('/').lower())              # path-based dedup (no id collisions)
        if key in seen:
            if title and len(title) > len(seen[key]['title']):
                seen[key]['title'] = title
            return
        rec = {'path': path, 'id': tid, 'slug': slug, 'title': title, 'url': full}
        seen[key] = rec
        tiles.append(rec)

    anchors = soup.find_all('a', href=True)
    for a in anchors:                                      # A. route tiles
        if _DETAIL_ROUTE.search(a['href']):
            add(a['href'], _title_of(a))
    if not tiles:                                          # B. thumbnail (model-slug) tiles
        for a in anchors:
            img = a.find('img')
            if not img:
                continue
            alt = (img.get('alt') or img.get('title') or a.get('title')
                   or a.get_text(' ', strip=True) or '').strip()
            if _is_ad_or_chrome(alt, img.get('src') or img.get('data-src')):
                continue
            add(a['href'], alt, img.get('src'))
    if not tiles:                                          # C. sluggy last-segment tiles
        for a in anchors:
            segs = [s for s in urlparse(a['href']).path.split('/') if s]
            if segs and _SLUGGY.match(segs[-1]) and not _NAV.search(a['href']):
                add(a['href'], _title_of(a))
    return tiles


# ----------------------------------------------------------------------------- per-URL
# Some hosts (Cloudflare-fronted, e.g. cums.net) 403 the crawler's default header set
# but accept a plain Windows-Chrome UA with a Google referer. Retry once with that.
_ALT_HDRS = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "referer": "https://www.google.com/",
    "accept-encoding": "gzip, deflate",
}


def render_html_batch(urls, timeout=30, wait_ms=3500, log=lambda *a: None):
    """Render JS-built grids with Playwright (headless chromium) → {url: html}.

    Sequential, one browser/page reused (Playwright sync API isn't thread-safe). Best-effort:
    a URL that errors or times out maps to '' so the caller falls back to its HTTP verdict.
    This is the tier-escalation for sites where plain HTTP returns an empty grid."""
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=_ALT_HDRS['user-agent'])
        page = ctx.new_page()
        for i, u in enumerate(urls, 1):
            try:
                page.goto(u, timeout=timeout * 1000, wait_until='domcontentloaded')
                page.wait_for_timeout(wait_ms)             # let the grid populate
                out[u] = page.content()
            except Exception as e:
                out[u] = ''
                log(f"  render-err [{i}/{len(urls)}] {urlparse(u).netloc}: {type(e).__name__}")
        browser.close()
    return out


def probe(url, strong, names, timeout, html_override=None):
    if html_override is not None:                          # rendered HTML supplied by caller
        status, final_url, html = (200 if html_override else 0), url, html_override
    else:
        status, final_url, html = fetch(url, timeout=timeout)
        if status in (403, 503, 0):                        # bot-filtered — retry with alt headers
            status, final_url, html = fetch(url, timeout=timeout, hdrs=_ALT_HDRS)
    shape = url_shape(url)
    rec = {'url': url, 'final_url': final_url, 'status': status, 'shape': shape,
           'html_bytes': len(html or ''), 'rendered': html_override is not None,
           'tiles': [], 'counts': {}, 'verdict': ''}
    if status != 200 or not html:
        rec['verdict'] = f'FETCH-FAIL ({status})'
        return rec
    tiles = extract_tiles(final_url or url, html)
    for t in tiles:
        t['cls'], t['why'] = classify(t['slug'], t['title'], strong, names)
    c = Counter(t['cls'] for t in tiles)
    rec['tiles'] = tiles
    rec['counts'] = {'tiles': len(tiles), 'target': c['target'],
                     'ambiguous': c['ambiguous'], 'padding': c['padding']}
    rec['verdict'] = verdict(shape, c, len(tiles))
    return rec


def verdict(shape, c, n):
    if n == 0:
        return ('THIN/JS — no tiles extracted (JS-rendered grid or profile page); '
                'trust the page-level verdict, do NOT drop')
    if shape in ('profile', 'tag'):
        base = 'TRUSTED-SHAPE'
        if c['target'] == 0:
            return f'{base} but 0 token-matched tiles — verify shape is genuine (keep by shape)'
        return f'{base} — {c["target"]}/{n} tiles token-match the handle'
    # search shape
    if c['target'] == 0:
        return ('PURE-ECHO — search reflects the query but 0 genuine target tiles; '
                'candidate to EXCLUDE from the report')
    if c['padding'] == 0 and c['ambiguous'] == 0:
        return f'CLEAN — all {n} tiles token-match'
    return (f'MIXED — {c["target"]} genuine / {c["padding"]} padding'
            f'{f" / {c['ambiguous']} ambiguous" if c["ambiguous"] else ""}; '
            f'keep the genuine detail-URLs, filter padding')


# ----------------------------------------------------------------------------- report
def print_report(records, strong, names, show):
    print(f"\n{'='*78}\nTARGET  strong-substrings={sorted(strong)}  name-tokens={sorted(names)}\n{'='*78}")
    for r in records:
        c = r['counts']
        print(f"\n▌ {urlparse(r['url']).netloc}   [{r['shape']}]   {r['url']}")
        if not c:
            print(f"    {r['verdict']}")
            continue
        print(f"    tiles={c['tiles']}  target={c['target']}  "
              f"ambiguous={c['ambiguous']}  padding={c['padding']}   ({r['html_bytes']}B)")
        print(f"    ➜ {r['verdict']}")
        tgt = [t for t in r['tiles'] if t['cls'] == 'target']
        pad = [t for t in r['tiles'] if t['cls'] == 'padding']
        amb = [t for t in r['tiles'] if t['cls'] == 'ambiguous']
        if tgt:
            print("    ── TARGET tiles ──")
            for t in tgt[:show]:
                print(f"       ✓ {(t['title'] or t['slug'])[:72]}")
                print(f"         {t['path']}")
        if amb:
            print("    ── AMBIGUOUS ──")
            for t in amb[:show]:
                print(f"       ? {(t['title'] or t['slug'])[:72]}  [{t['why']}]")
        if pad:
            print(f"    ── PADDING (showing {min(show,len(pad))}/{len(pad)}) ──")
            for t in pad[:show]:
                print(f"       ✗ {(t['title'] or t['slug'])[:72]}")
    # summary
    print(f"\n{'-'*78}\nSUMMARY")
    for r in records:
        c = r['counts'] or {}
        tag = r['verdict'].split(' ')[0].split('—')[0].strip() if r['verdict'] else '?'
        print(f"  {tag:14s} {urlparse(r['url']).netloc:22s} "
              f"target={c.get('target','-')} padding={c.get('padding','-')} shape={r['shape']}")


# ----------------------------------------------------------------------------- cli
def load_tokens(campaign, tokens_arg):
    toks = []
    if campaign:
        # newest of root (mid-run_az fresh artifact) vs campaigns/ (tidied prior run)
        f = newest_path(f'campaigns/{campaign}/{campaign}-aliases.txt', f'{campaign}-aliases.txt')
        if f:
            toks += [l.strip() for l in open(f) if l.strip()]
        else:
            print(f"[warn] no alias file for {campaign} (tried campaigns/ and repo root)", file=sys.stderr)
    if tokens_arg:
        toks += [t.strip() for t in tokens_arg.split(',') if t.strip()]
    return toks


def main():
    ap = argparse.ArgumentParser(description="Live-confirm per-tile padding on leak-site result pages.")
    ap.add_argument('urls', nargs='*', help="page URLs to probe")
    ap.add_argument('--campaign', help="load campaigns/<name>/<name>-aliases.txt for the target tokens")
    ap.add_argument('--tokens', help="extra comma-separated handle tokens")
    ap.add_argument('--name', default='', help='display name, e.g. "Julia Filippo" (adds name tokens)')
    ap.add_argument('--urls-file', help="read one URL per line (e.g. <prefix>.search.links.txt)")
    ap.add_argument('--out', help="write the full JSON log here")
    ap.add_argument('--show', type=int, default=12, help="max tiles to print per class")
    ap.add_argument('--timeout', type=int, default=15)
    a = ap.parse_args()

    urls = list(a.urls)
    if a.urls_file and os.path.exists(a.urls_file):
        urls += [l.strip() for l in open(a.urls_file) if l.strip() and l.strip().startswith('http')]
    urls = list(dict.fromkeys(urls))                       # dedup, keep order
    if not urls:
        ap.error("no URLs given (positional or --urls-file)")

    tokens = load_tokens(a.campaign, a.tokens)
    if not tokens and not a.name:
        ap.error("no target tokens — pass --campaign, --tokens, or --name")
    strong, names = build_target(tokens, a.name)

    records = [probe(u, strong, names, a.timeout) for u in urls]
    print_report(records, strong, names, a.show)

    if a.out or a.campaign:
        out = a.out or f'campaigns/{a.campaign}/{a.campaign}.slugprobe.json'
        json.dump({'target': {'strong': sorted(strong), 'names': sorted(names)},
                   'records': records}, open(out, 'w'), indent=1)
        print(f"\n[log] full JSON → {out}")


if __name__ == '__main__':
    main()

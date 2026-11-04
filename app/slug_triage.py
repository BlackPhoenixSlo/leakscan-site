#!/usr/bin/env python3
"""slug_triage — run slug_probe across a whole campaign, bucket sites DROP / KEEP / REVIEW.

Reads the campaign scan (<name>-scan.json), collapses the URLs to one representative per
(host, url-shape) so each site's each entry-point is judged once (no hammering the same host
with six alias variants), probes them concurrently, and splits the results into three files
you can check by hand:

    triage/DROP.txt    search pages that only ECHO the query — 0 genuine target tiles
    triage/KEEP.txt    genuine target tiles found, or trusted profile/tag shape
    triage/REVIEW.txt  couldn't judge safely — JS-only grid, fetch-fail, or single-name ambiguous

Bucketing is CONSERVATIVE: when in doubt it goes to REVIEW, never DROP (false-drop of real
infringing content is the cardinal sin — see DEDUP_CODEX.md). DROP is only ever a *candidate*
list for your manual confirmation; nothing here deletes from the pipeline.

    python3 slug_triage.py --campaign juliafilippo
    python3 slug_triage.py --campaign mckinleyrichardson --workers 8 --all-urls
"""
import argparse
import difflib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from leak_evidence import url_shape, norm
from netloc import newest_path
from slug_probe import build_target, classify, load_tokens, probe, render_html_batch
from discovery_seed import harvest_hits

PRIMARY_HINT = None   # set to the primary handle at runtime (prefer that alias's URL per host)


def representatives(scan, all_urls):
    """One (host, shape) representative per site entry-point (or every URL if --all-urls)."""
    reps = {}
    for r in scan:
        u = r.get('url')
        if not u:
            continue
        host = urlparse(u).netloc.replace('www.', '')
        shape = url_shape(u, r.get('method'))
        key = u if all_urls else (host, shape)
        # prefer the URL that carries the primary handle, then the shortest (canonical) URL
        score = ((PRIMARY_HINT or '') in u.lower(), -len(u))
        if key not in reps or score > reps[key][0]:
            reps[key] = (score, {'url': u, 'host': host, 'shape': shape,
                                 'method': r.get('method'), 'evidence': r.get('evidence')})
    return [v[1] for v in reps.values()]


def _reg(host):
    h = (host or '').replace('www.', '')
    p = h.split('.')
    return '.'.join(p[-2:]) if len(p) >= 2 else h


def _url_is_target(u, strong, names):
    """A crawl media URL that actually carries the handle — the STRONG signal a domain hosts her.
    A raw media count is padding-polluted (an echo page's harvested thumbnails, flag icons), so we
    require the handle in the file URL: leakgallery.com/content-videos/julia_filippo/… counts."""
    if any(s in norm(u) for s in strong):
        return True
    ul = (u or '').lower()
    return len(names) >= 2 and all(n in ul for n in names)


def crawl_media_hosts(campaign, strong, names):
    """{registrable-domain: count of HANDLE-CARRYING crawl media files}. The reliable
    'this domain hosts her at SOME url even if its search echoes' signal — search-page DROP
    verdicts on these are false-drops; keep the domain and target its model/profile URL."""
    hosts = {}
    for name in (f'{campaign}.crawl.clean.json', f'{campaign}.crawl.json'):
        # newest of root (mid-run_az fresh artifact) vs campaigns/ (tidied prior run)
        f = newest_path(f'campaigns/{campaign}/{name}', name)
        if not f:
            continue
        try:
            cj = json.load(open(f))
        except Exception:
            continue
        recs = cj if isinstance(cj, list) else (cj.get('domains') or cj.get('sites') or [])
        for r in recs:
            if not isinstance(r, dict):
                continue
            h = r.get('domain') or r.get('host') or urlparse(r.get('url', '')).netloc
            media = r.get('media') if isinstance(r.get('media'), list) else []
            urls = [m if isinstance(m, str) else (m.get('url', '') if isinstance(m, dict) else '')
                    for m in media]
            n = sum(1 for u in urls if _url_is_target(u, strong, names))
            if h and n:
                hosts[_reg(h)] = hosts.get(_reg(h), 0) + n
        break
    return hosts


def _cand_tokens(slug, title):
    """Candidate flat (alnum-only) alias forms from one result tile: the slug core (its
    trailing '-14'/'_2' post-index stripped) plus every adjacent word-bigram in slug+title.
    'sophie-rain-14' -> {'sophierain', 'sophierain'}; 'bad-barbie-sophie-rain' also yields
    'badbarbie','barbiesophie','sophierain'. The bigrams recover a readable stage name that
    the bare handle never spells (sophieraiin -> sophie rain)."""
    out = set()
    core = norm(re.sub(r'[-_]?\d+$', '', slug or ''))
    if core:
        out.add(core)
    words = [w for w in re.split(r'[^a-z0-9]+', (slug + ' ' + title).lower())
             if len(w) >= 3 and not w.isdigit()]
    for i in range(len(words) - 1):
        out.add(norm(words[i] + words[i + 1]))
    return out


def harvest_aliases(records, strong, seeds, min_hosts=2, min_ratio=0.90, min_len=8, cap=6):
    """Learn readable-name alias variants from the scraped tiles themselves, then add them to
    `strong` (mutates it). A creator's HANDLE (sophieraiin) rarely matches how sites LABEL her
    content (sophie-rain), so a scan seeded only with the handle sees 0 target tiles on her
    biggest hosts and DROPs them as pure echo. Those variants appear verbatim in the tile slugs.

    A candidate is promoted ONLY when it ALL of:
      · is NOT a super/substring of a known token — a genuinely new spelling, not a handle-compound
        ('videosophieraiin') that already matches and would just crowd out the real variant;
      · is string-similar to a seed handle token (ratio >= min_ratio) — real readable variants sit
        very high (raiin->rain = 0.95; separator-only diffs are already redundant). The 0.90 floor
        is deliberately ABOVE where a DIFFERENT co-listed creator lands (sophie-RAYNE ≈ 0.82) so we
        never adopt someone else's content into the client's report — the more dangerous error; and
      · recurs across >= min_hosts DISTINCT sites — so a one-off typo on a single page isn't adopted.
    Returns [(token, host_count, ratio)] promoted, closest-spelling first. Safe to run unattended."""
    seed_norms = {norm(s) for s in seeds if s} | set(strong)

    def _redundant(cand):
        # A candidate that CONTAINS a known token ('videosophieraiin' ⊃ 'sophieraiin') already
        # matches via that token — promoting it adds nothing. One that's CONTAINED BY a known
        # token is just a fragment. Only a genuinely NEW spelling (sophierain, missing an 'i')
        # earns a slot — otherwise handle-compounds (which recur on every host the handle seeded)
        # crowd out the readable-name variant we actually need.
        return any(s and (s in cand or cand in s) for s in seed_norms)

    cand_hosts = defaultdict(set)                 # flat token -> {registrable host}
    for rec in records:
        host = _reg(rec.get('host') or '')
        for t in rec.get('tiles') or []:
            for cand in _cand_tokens(t.get('slug') or '', t.get('title') or ''):
                if len(cand) >= min_len and not _redundant(cand):
                    cand_hosts[cand].add(host)
    promoted = []
    for cand, hosts in cand_hosts.items():
        if len(hosts) < min_hosts:
            continue
        ratio = max((difflib.SequenceMatcher(None, cand, s).ratio() for s in seed_norms),
                    default=0.0)
        if ratio >= min_ratio:
            promoted.append((cand, len(hosts), round(ratio, 3)))
    # strongest first: closest spelling to the handle wins the capped slots, then reach (hosts)
    promoted.sort(key=lambda x: (-x[2], -x[1]))
    promoted = promoted[:cap]
    for cand, _, _ in promoted:
        strong.add(cand)
    return promoted


def reclassify(records, strong, names):
    """Re-score every already-scraped tile with an enriched target set and recompute each site's
    counts — no re-fetch. Called after harvest_aliases() promotes learned variants so the KEEP/
    DROP verdict reflects them (leakgallery/fapeza flip from PURE-ECHO DROP to token-match KEEP)."""
    for rec in records:
        tiles = rec.get('tiles') or []
        for t in tiles:
            t['cls'], t['why'] = classify(t.get('slug') or '', t.get('title') or '', strong, names)
        c = Counter(t['cls'] for t in tiles)
        if rec.get('counts'):
            rec['counts'].update({'target': c['target'], 'ambiguous': c['ambiguous'],
                                  'padding': c['padding']})


def bucket(rec, strong):
    """(verdict, reason, confidence) — conservative: unsure -> REVIEW, never DROP.

    confidence: confirmed (real target tiles seen) > url-path (handle in the URL path, a
    dedicated page — LIKELY per export_dmca, tiles generic) > shape (trusted shape, JS grid)."""
    c = rec.get('counts') or {}
    if rec['status'] != 200 or not c:
        return 'REVIEW', f"fetch-fail ({rec['status']})", 'unknown'
    shape, n = rec['shape'], c['tiles']
    # handle in the URL PATH (not the ?query — a search reflection is not evidence)
    path_hit = any(s in norm(urlparse(rec['url']).path) for s in strong)
    if c['target'] > 0:
        return 'KEEP', f"{c['target']}/{n} tiles token-match the handle", 'confirmed'
    # from here target == 0
    if shape in ('profile', 'tag'):
        if path_hit:
            extra = (f"; {c['padding']} generic/padding tiles (titles don't repeat her name)"
                     if c['padding'] else "; grid JS/empty")
            return 'KEEP', f"handle in {shape} URL path — dedicated page for her{extra}", 'url-path'
        if n == 0:
            return 'KEEP', f"trusted {shape} shape; grid JS/empty", 'shape'
        return 'REVIEW', f"trusted {shape} shape, {c['padding']} non-matching tiles, no handle in path — verify", 'unknown'
    # search shape, target == 0
    if n == 0:
        return 'REVIEW', 'search page, 0 tiles extracted (JS-rendered grid — needs browser)', 'unknown'
    if c['ambiguous'] > 0:
        return 'REVIEW', f"{c['ambiguous']} single-name tile(s) — could be a different person", 'unknown'
    return 'DROP', f"PURE-ECHO — {c['padding']} padding tiles, 0 genuine target", 'echo'


def sample_tiles(rec, cls, k=6):
    return [t for t in rec['tiles'] if t['cls'] == cls][:k]


def write_bucket(path, title, items):
    lines = [f"# {title}", f"# {len(items)} sites — generated by slug_triage.py", ""]
    for rec, reason in items:
        c = rec['counts'] or {}
        conf = rec.get('confidence', '')
        tag = f"{{{conf}}} " if conf and conf not in ('echo', 'unknown') else ""
        lines.append(f"[{rec['shape']}] {tag}{rec['host']}  "
                     f"target={c.get('target','-')} padding={c.get('padding','-')} "
                     f"ambiguous={c.get('ambiguous','-')}  ({reason})")
        lines.append(f"    {rec['url']}")
        # show the evidence that supports the verdict
        if c.get('target'):
            for t in sample_tiles(rec, 'target'):
                lines.append(f"    ✓ {(t['title'] or t['slug'])[:76]}")
        for t in sample_tiles(rec, 'ambiguous'):
            lines.append(f"    ? {(t['title'] or t['slug'])[:76]}  [{t['why']}]")
        if not c.get('target'):
            for t in sample_tiles(rec, 'padding'):
                lines.append(f"    ✗ {(t['title'] or t['slug'])[:76]}")
        lines.append("")
    open(path, 'w').write("\n".join(lines))


def main():
    global PRIMARY_HINT
    ap = argparse.ArgumentParser(description="Triage a campaign's leak URLs into DROP/KEEP/REVIEW.")
    ap.add_argument('--campaign', required=True)
    ap.add_argument('--scan', help="scan json (default campaigns/<c>/<c>-scan.json)")
    ap.add_argument('--tokens', help="extra comma-separated handle tokens")
    ap.add_argument('--name', default='', help='display name for name-token matching')
    ap.add_argument('--workers', type=int, default=10)
    ap.add_argument('--render', choices=['off', 'empty', 'all'], default='off',
                    help="browser-render escalation: 'empty' re-probes sites whose HTTP grid was "
                         "empty (JS-rendered) — turns 'needs browser' REVIEWs into real DROP/KEEP; "
                         "'all' renders every site. Uses Playwright (headless).")
    ap.add_argument('--render-wait', type=int, default=3500, help="ms to let a rendered grid populate")
    ap.add_argument('--all-urls', action='store_true', help="probe every URL, not one per (host,shape)")
    ap.add_argument('--limit', type=int, default=0, help="cap number of sites (debug)")
    ap.add_argument('--timeout', type=int, default=15)
    ap.add_argument('--no-harvest', dest='harvest', action='store_false',
                    help="disable learning readable-name alias variants (sophie-rain) from the "
                         "scraped tiles — by default ON so a handle-only scan still keeps her "
                         "display-name hosts instead of dropping them as echo")
    ap.add_argument('--harvest-min-hosts', type=int, default=2,
                    help="a learned alias must recur across >= this many distinct sites (default 2)")
    ap.add_argument('--harvest-min-ratio', type=float, default=0.90,
                    help="a learned alias must be >= this string-similar to the handle (default "
                         "0.90 — above where a different co-listed creator lands, so we never "
                         "adopt someone else's content)")
    ap.set_defaults(harvest=True)
    a = ap.parse_args()

    scan_path = a.scan or newest_path(f'campaigns/{a.campaign}/{a.campaign}-scan.json',
                                      f'{a.campaign}-scan.json')
    scan = json.load(open(scan_path))
    tokens = load_tokens(a.campaign, a.tokens)
    PRIMARY_HINT = norm(tokens[0]) if tokens else a.campaign
    strong, names = build_target(tokens, a.name)

    reps = representatives(scan, a.all_urls)
    if a.limit:
        reps = reps[:a.limit]
    print(f"probing {len(reps)} site entry-points "
          f"(from {len(scan)} scan records) with {a.workers} workers…", file=sys.stderr)

    records, done = [], 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(probe, r['url'], strong, names, a.timeout): r for r in reps}
        for f in as_completed(futs):
            src = futs[f]
            rec = f.result()
            rec['host'] = src['host']
            rec['evidence_prior'] = src['evidence']
            records.append(rec)
            done += 1
            if done % 20 == 0 or done == len(reps):
                print(f"  {done}/{len(reps)}", file=sys.stderr)

    # ---- tier escalation: browser-render the sites HTTP couldn't judge -----------------
    by_url = {r['url']: r for r in records}
    if a.render != 'off':
        if a.render == 'all':
            targets = [r['url'] for r in records]
        else:   # 'empty' — JS-rendered grids (200 but 0 tiles) + blocked fetches
            targets = [r['url'] for r in records
                       if (r['status'] == 200 and (r['counts'] or {}).get('tiles', 0) == 0)
                       or r['status'] != 200]
        if targets:
            print(f"rendering {len(targets)} site(s) with a headless browser "
                  f"(escalation from empty/blocked HTTP grids)…", file=sys.stderr)
            htmls = render_html_batch(targets, timeout=a.timeout, wait_ms=a.render_wait,
                                      log=lambda *m: print(*m, file=sys.stderr))
            changed = 0
            for u in targets:
                html = htmls.get(u, '')
                if not html:
                    continue
                new = probe(u, strong, names, a.timeout, html_override=html)
                old = by_url[u]
                new['host'] = old['host']
                new['evidence_prior'] = old.get('evidence_prior')
                new['http_tiles_was'] = (old['counts'] or {}).get('tiles', 0)
                by_url[u] = new
                changed += 1
            records = list(by_url.values())
            print(f"  re-probed {changed} rendered page(s)", file=sys.stderr)

    # ---- alias harvest: learn readable-name variants from the scraped tiles, re-score --------
    # The handle rarely spells how sites label her (sophieraiin -> sophie-rain); a handle-only
    # scan therefore DROPs her biggest hosts as pure echo. Mine the tiles for handle-similar,
    # cross-host tokens and re-classify with them BEFORE the crawl/bucket pass, so both the
    # verdict and the crawl-media corroboration below see the enriched target set.
    harvested = []
    if a.harvest:
        harvested = harvest_aliases(records, strong, tokens, min_hosts=a.harvest_min_hosts,
                                    min_ratio=a.harvest_min_ratio)
        if harvested:
            reclassify(records, strong, names)
            print("[harvest] learned {} alias(es) from tiles across sites: {}".format(
                len(harvested), ", ".join(f"{c} ({h} hosts, ~{r})" for c, h, r in harvested)),
                file=sys.stderr)

    crawl_hosts = crawl_media_hosts(a.campaign, strong, names)
    # second host signal: profile URLs the DISCOVERY stages (Google/CSE/web-search) surfaced for
    # her on a domain. A domain with direct profile hits HOSTS her at those URLs even when its
    # search page echoes and the crawl never reached the (display-name) galleries — the same
    # false-drop the crawl-media guard prevents, one stage earlier. Keyed to _reg for lookup.
    disc_hosts = {}
    for d, c in harvest_hits(a.campaign, strong, names).items():
        disc_hosts[_reg(d)] = disc_hosts.get(_reg(d), 0) + c
    rescued = 0
    buckets = {'DROP': [], 'KEEP': [], 'REVIEW': []}
    _conf_rank = {'crawl-confirmed': -1, 'discovery-confirmed': -1, 'confirmed': 0,
                  'url-path': 1, 'shape': 2, 'unknown': 3, 'echo': 0}
    for rec in records:
        v, reason, conf = bucket(rec, strong)
        # False-drop guard, evidence-based: if the crawl found HANDLE-CARRYING media files on this
        # domain, OR the discovery stages found direct profile URLs for her here, the domain HOSTS
        # her even when its search page echoes. Never DROP such a domain — the search URL is the
        # wrong entry point, not proof she's absent. Crawl evidence (real files) outranks discovery
        # (URLs seen) when both exist.
        n = crawl_hosts.get(_reg(rec['host']), 0)
        disc = disc_hosts.get(_reg(rec['host']), 0)
        rec['crawl_media'] = n
        rec['discovery_hits'] = disc
        if v == 'DROP' and (n or disc):
            v = 'REVIEW'
            if n:
                conf = 'crawl-confirmed'
                reason = (f'search echoes BUT crawl has {n} real file(s) on this domain — '
                          f'KEEP the domain, target its model/profile URL (not the search). ' + reason)
            else:
                conf = 'discovery-confirmed'
                reason = (f'search echoes BUT {disc} direct profile URL(s) were discovered for her on '
                          f'this domain (Google/search index) — KEEP the domain, crawl those profile '
                          f'URLs (not the search page). ' + reason)
            rescued += 1
        elif v == 'REVIEW' and (n or disc):
            if n:
                reason = f'crawl has {n} real file(s) here — likely hosts her, find the model URL; ' + reason
                conf = 'crawl-confirmed'
            else:
                reason = f'{disc} direct profile URL(s) discovered here — likely hosts her, crawl them; ' + reason
                conf = 'discovery-confirmed'
        elif v == 'KEEP' and n:
            reason += f'  [crawl-corroborated: {n} real files]'
        rec['triage'] = v
        rec['triage_reason'] = reason
        rec['confidence'] = conf
        buckets[v].append((rec, reason))
    if rescued:
        print(f"[guard] rescued {rescued} real-host(s) from DROP -> REVIEW "
              f"(crawl-media or discovery-profile evidence)", file=sys.stderr)
    for b in buckets:
        if b == 'DROP':
            buckets[b].sort(key=lambda x: -(x[0]['counts'] or {}).get('padding', 0))
        else:   # KEEP/REVIEW: strongest confidence first, then most target tiles
            buckets[b].sort(key=lambda x: (_conf_rank.get(x[0]['confidence'], 9),
                                           -(x[0]['counts'] or {}).get('target', 0)))

    outdir = f'campaigns/{a.campaign}/triage'
    os.makedirs(outdir, exist_ok=True)
    write_bucket(f'{outdir}/DROP.txt',
                 "DROP candidates — search pages that only echo the query (0 genuine tiles). VERIFY before excluding.",
                 buckets['DROP'])
    write_bucket(f'{outdir}/KEEP.txt',
                 "KEEP — genuine target tiles found, or trusted profile/tag shape.",
                 buckets['KEEP'])
    write_bucket(f'{outdir}/REVIEW.txt',
                 "REVIEW — could not judge safely (JS-only grid, fetch-fail, or single-name ambiguous). Check by hand.",
                 buckets['REVIEW'])
    if harvested:
        open(f'{outdir}/harvested_aliases.txt', 'w').write(
            "# learned by slug_triage from tile slugs (handle-similar + cross-host)\n"
            + "\n".join(c for c, _, _ in harvested) + "\n")
    json.dump({'target': {'strong': sorted(strong), 'names': sorted(names),
                          'harvested': [c for c, _, _ in harvested]},
               'counts': {b: len(v) for b, v in buckets.items()},
               'records': records}, open(f'{outdir}/{a.campaign}.triage.json', 'w'), indent=1)

    print(f"\n{'='*60}\nTRIAGE  {a.campaign}   ({len(records)} sites)")
    print(f"  DROP   {len(buckets['DROP']):4d}  search pages that never show her")
    print(f"  KEEP   {len(buckets['KEEP']):4d}  genuine tiles / trusted shape")
    print(f"  REVIEW {len(buckets['REVIEW']):4d}  needs a manual look")
    print(f"{'='*60}\nfiles → {outdir}/{{DROP,KEEP,REVIEW}}.txt  +  {a.campaign}.triage.json")


if __name__ == '__main__':
    main()

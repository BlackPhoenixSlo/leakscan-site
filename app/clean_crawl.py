#!/usr/bin/env python3
"""clean_crawl.py — strip crawler false-positives from a crawl json before export.

Drops five classes of non-leak URLs that inflate the LIKELY count:
  1. recursion traps   — self-referential pagination (.../2257/2257/video/.../video/...)
  2. aggregator queries — /search/ /tags/ /tag/ result pages (reflect the slug, don't host)
  3. theme/UI assets    — forum/CMS chrome under the member/thread path
                          (/misc/ /buttons/ /metro/ close_popup.png ico-*.png ...)
  4. catch-all media    — on a domain where <15% of media carry the handle, the site is
                          serving OTHER creators (jjgirls / upskirt.tv / se.video style);
                          keep only the media whose URL carries the handle, drop the rest.
  5. fake-aggregators   — CDNs that SEO-name OTHER-people/studio content WITH the handle
                          (ahvideoscdn.net serving 'mckinley-richardson-*.jpg' studio porn),
                          so the URL carries the handle and beats passes 1-4. The only thing
                          that stops one is an explicit host block (--block-file/--block-domains);
                          it must be vision-confirmed not-the-creator before a domain is added.

Keeps everything else (real content pages + real media files carrying the handle).

    clean_crawl.py <in.json> <out.json> [--strong sophieraiin,sophierain]
                   [--catchall-ratio 0.15] [--catchall-min 25]
                   [--block-file fake_aggregators.txt] [--block-domains a.net,b.com]

Without --strong the catch-all pass falls back to the slugs recorded in the crawl
(and is skipped entirely if neither is available, so a plain run never over-drops).
"""
import argparse, json, os, re, sys
from urllib.parse import urlsplit

from netloc import registrable_domain
from leak_evidence import url_shape

HERE = os.path.dirname(os.path.abspath(__file__))
GLOBAL_KEEP = os.path.join(HERE, "recovery_hosts.txt")   # GLOBAL clean-host allowlist (all campaigns)

THEME_DIRS = ("/misc/", "/buttons/", "/metro/", "/viper-red/", "/viper-green/",
              "/skins/", "/styles/", "/css/", "/js/", "/wp-includes/",
              "/plugins/", "/themes/", "/static/img/", "/assets/")
THEME_FILES = ("close_popup", "ico-", "sprite", "favicon", "logo.", "button")

# Legit re-upload mirrors that host the creator's OWN media under HASHED urls (the slug
# is in the page url, not the media url) — so they look 0%-handle but aren't catch-alls.
# Exempt them from the catch-all pass so we don't drop genuine leaks.
HASHED_HOSTS = {"thothd.com", "erothots.com", "picazor.com", "leakgallery.com",
                "fapello.pics", "fapello.com", "thothub.to", "thothub.lol"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def load_block(path, inline):
    """Set of fake-aggregator registrable domains to drop outright. Comment lines (#) and
    blanks ignored. These are hosts that carry the handle but serve OTHER-people/studio
    content — confirmed not-the-creator (vision-vetted) before being added here."""
    doms = {d.strip().lower() for d in (inline or "").split(",") if d.strip()}
    if path and os.path.exists(path):
        for ln in open(path, encoding="utf-8"):
            ln = ln.split("#", 1)[0].strip().lower()
            if ln:
                doms.add(ln)
    return doms


def host_reg(u):
    try:
        return registrable_domain(u) or ""
    except Exception:
        return ""


def is_trap(u):
    segs = [s for s in urlsplit(u).path.split("/") if s]
    for a, b in zip(segs, segs[1:]):
        if a == b and re.fullmatch(r"\d+", a):
            return True
    nums = [s for s in segs if re.fullmatch(r"\d+", s)]
    return len(nums) != len(set(nums))


def is_agg(u):
    p = urlsplit(u).path.lower()
    return any(x in p for x in ("/search/", "/tags/", "/tag/"))


def is_theme(u):
    p = urlsplit(u).path.lower()
    if any(t in p for t in THEME_DIRS):
        return True
    fn = p.rsplit("/", 1)[-1]
    return any(t in fn for t in THEME_FILES)


def bad(u):
    return not u or is_trap(u) or is_agg(u) or is_theme(u)


def carries_handle(url, tokens):
    """True if the URL path carries any handle token (normalised, separator-insensitive)."""
    p = norm(urlsplit(url).path)
    return any(t and t in p for t in tokens)


def page_carries_handle(page_url, tokens):
    """PROVENANCE keep-rule (class-2): the media's SOURCE PAGE is a profile/tag page whose path
    carries the handle in a SEGMENT — so a hashed-CDN file that came off a page the site minted
    FOR HER is kept even though its own url has no handle. Only trusted for human-confirmed
    keep-file domains (a general tube's handle page can still carry other performers)."""
    if not page_url or url_shape(page_url) not in ("profile", "tag"):
        return False
    segs = [norm(s) for s in urlsplit(page_url).path.split("/") if s]
    return any(any(t and t in s for t in tokens) for s in segs)


def main():
    ap = argparse.ArgumentParser(description="Strip crawler false-positives from a crawl json.")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--strong", default="", help="Comma handle tokens for the catch-all pass.")
    ap.add_argument("--catchall-ratio", type=float, default=0.15,
                    help="A domain is a catch-all when < this fraction of its media carry the handle.")
    ap.add_argument("--catchall-min", type=int, default=25,
                    help="Only apply the catch-all pass to domains with at least this many media.")
    ap.add_argument("--block-file", default=None,
                    help="File of fake-aggregator registrable domains (one per line) to drop outright.")
    ap.add_argument("--block-domains", default="",
                    help="Comma-sep fake-aggregator registrable domains to drop outright.")
    ap.add_argument("--keep-file", default=None,
                    help="File of HUMAN-confirmed HER domains (recovery_keep.txt). On these the "
                         "pass-4 catch-all is replaced by the PROVENANCE keep-rule: keep hashed "
                         "media whose source page carries the handle in a profile/tag segment. "
                         "Recovers real leaks on hashed-CDN hosts that aren't in HASHED_HOSTS.")
    args = ap.parse_args()

    data = json.load(open(args.src, encoding="utf-8"))
    tokens = [norm(t) for t in args.strong.split(",") if t.strip()]
    if not tokens:   # fall back to slugs the crawl already confirmed for this creator
        tokens = sorted({norm(s) for r in data for s in (r.get("slugs") or []) if norm(s)})
    block = load_block(args.block_file, args.block_domains)
    # human-confirmed HER domains: the GLOBAL clean-host allowlist (all campaigns) + any
    # per-campaign --keep-file additions. A dedicated host confirmed for one model is trusted
    # for every model (recovery_hosts.txt); general tubes stay per-campaign.
    keep = load_block(GLOBAL_KEEP, "") | load_block(args.keep_file, "")

    dropped = kept = catchall_drop = block_drop = prov_kept = 0
    catchalls = []
    provenance = []
    for r in data:
        pages = r.get("pages", []) or []
        r["pages"] = [p for p in pages if not bad(p)]
        media = [m for m in (r.get("media", []) or []) if not bad(m)]
        pairs = [pr for pr in (r.get("media_pairs", []) or []) if pr and not bad(pr[0])]

        # fake-aggregator block: drop any url whose HOST is a known not-the-creator
        # aggregator CDN. ahvideoscdn.net SEO-names studio porn with the handle so it
        # passes every content filter above — an explicit host block is the only catch.
        if block:
            block_drop += (sum(1 for p in r["pages"] if host_reg(p) in block)
                           + sum(1 for m in media if host_reg(m) in block))
            r["pages"] = [p for p in r["pages"] if host_reg(p) not in block]
            media = [m for m in media if host_reg(m) not in block]
            pairs = [pr for pr in pairs if host_reg(pr[0]) not in block]

        dropped += (len(pages) - len(r["pages"]))

        # catch-all pass: a domain whose media overwhelmingly do NOT carry the handle is
        # serving other people — keep only the handle-carrying media on it. Known hashed-
        # media mirrors are exempt (their media legitimately lack the handle in the url).
        dom = r.get("domain", "")
        reg = ".".join(dom.split(".")[-2:])
        if keep and (dom in keep or reg in keep):
            # HUMAN-CONFIRMED her domain: replace the catch-all strip with PROVENANCE keep —
            # keep hashed media whose SOURCE PAGE (media_pairs[i][1]) carries the handle in a
            # profile/tag segment. Recovers real leaks on hashed-CDN hosts (fapfolder, thotchicks)
            # that pass-4 would zero out. Media with no qualifying pair are dropped.
            if tokens:
                pairs = [pr for pr in pairs
                         if carries_handle(pr[0], tokens) or page_carries_handle(pr[1], tokens)]
                kset = {pr[0] for pr in pairs}
                recovered = len(kset) - sum(1 for m in media if carries_handle(m, tokens))
                media = [m for m in media if m in kset]
                # surface the handle-carrying SOURCE PAGES so export/report list the takedown
                # target (a single collab article can have pages=[] but a handle-slug URL) —
                # without this a keep domain whose media are hashed never reaches the DMCA form.
                for pg in {pr[1] for pr in pairs if page_carries_handle(pr[1], tokens)}:
                    if pg not in r["pages"]:
                        r["pages"].append(pg)
                prov_kept += max(0, recovered)
                if recovered > 0:
                    provenance.append((r.get("domain", "?"), recovered, len(media)))
        elif tokens and len(media) >= args.catchall_min and dom not in HASHED_HOSTS and reg not in HASHED_HOSTS:
            hits = [m for m in media if carries_handle(m, tokens)]
            if len(hits) / len(media) < args.catchall_ratio:
                cut = len(media) - len(hits)
                catchall_drop += cut
                catchalls.append((r.get("domain", "?"), cut, len(hits)))
                media = hits
                pairs = [pr for pr in pairs if carries_handle(pr[0], tokens)]

        dropped += (len(r.get("media", []) or []) - len(media))
        r["media"], r["media_pairs"] = media, pairs
        kept += len(r["pages"]) + len(media)

    json.dump(data, open(args.dst, "w", encoding="utf-8"))
    print(f"clean_crawl: kept {kept}, dropped {dropped} "
          f"(trap/aggregator/theme + {catchall_drop} catch-all media "
          f"+ {block_drop} fake-aggregator) + {prov_kept} provenance-recovered on keep-file -> {args.dst}")
    for dom, cut, hits in sorted(catchalls, key=lambda x: -x[1])[:12]:
        print(f"  catch-all {dom}: dropped {cut} non-handle media (kept {hits})", file=sys.stderr)
    for dom, rec, tot in sorted(provenance, key=lambda x: -x[1]):
        print(f"  keep-file {dom}: provenance-recovered {rec} hashed media (kept {tot} total)", file=sys.stderr)


if __name__ == "__main__":
    main()

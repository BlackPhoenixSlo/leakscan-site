#!/usr/bin/env python3
"""google_shots.py — REAL Google Images search screenshots for the report's
"Google search results" strip (the sophieraiin look), captured through the
Incogniton residential-proxy browser (falls back to local Chrome).

Unlike build_google_shots.py (which fabricates Google-looking HTML), this drives a
real browser to google.com/…&udm=2 for a set of leak queries — handle + suffixes
(nude leaks / porn videos / onlyfans leaked / …) plus `<handle> site:<domain>` for
the top confirmed hosts — dismisses Google's adult "Check your settings"
interstitial, and screenshots the actual masonry results. Output mirrors what the
report already consumes:

    <out-dir>/shots/NNN_google-com.jpg   # the captures
    <out-dir>/shots.json                 # [{local_path, domain, page_url, title, query}]

make_report --images-dir <out-dir> then embeds them (blurred) into the gallery.

UNATTENDED by design: a walled/captcha page is SKIPPED, never waited on (set
CAPTCHA_ALERT=0 before browser_common loads). shots.json is only (re)written when at
least one shot is captured, so a fully-walled run leaves any existing synthetic
build_google_shots.py output in place.

    python3 google_shots.py --query juliafilippo --name "Julia Filippo" \
        --from-crawl campaigns/juliafilippo/juliafilippo.crawl.clean.json \
        --out-dir campaigns/juliafilippo/juliafilippo_images --max 13
    python3 google_shots.py --query juliafilippo --domains leakgallery.com,fapello.com \
        --out-dir juliafilippo_images --no-incogniton --headful
"""
import argparse
import collections
import hashlib
import io
import json
import os
import re
import sys
from urllib.parse import quote_plus

# Fully-unattended: a walled page is skipped, never voice-pinged/waited on.
os.environ["CAPTCHA_ALERT"] = "0"

import browser_common

try:
    from netloc import registrable_domain
except Exception:
    def registrable_domain(u):
        h = re.sub(r"^https?://", "", u or "").split("/")[0]
        return h[4:] if h.startswith("www.") else h
try:
    from PIL import Image
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False

# The 8 image-search suffixes sophieraiin used (handle-prefixed), then site: queries.
DEFAULT_SUFFIXES = ["nude leaks", "porn videos", "leaks", "onlyfans leaked",
                    "nude", "fapello", "leakgallery", "nudes"]


def top_domains_from_crawl(crawl_path, n):
    """Top-n registrable leak domains by media count — for the site: queries."""
    try:
        data = json.load(open(crawl_path, encoding="utf-8"))
    except Exception:
        return []
    c = collections.Counter()
    for rec in data if isinstance(data, list) else []:
        media = rec.get("media") or []
        # crawl records key the host as 'domain'; media is a list of urls
        d = registrable_domain(rec.get("domain") or "") or (registrable_domain(media[0]) if media else "")
        if d:
            c[d] += len(media) or 1
    return [d for d, _ in c.most_common(n)]


def top_domains_from_cse(cse_path, n):
    """Top-n registrable domains Google actually SURFACES her on, from the CSE scan's
    'sites' (occurrence-ranked). These return real, populated `site:` SERPs — unlike
    crawl-count hosts that have lots of media but little Google indexing."""
    try:
        d = json.load(open(cse_path, encoding="utf-8"))
    except Exception:
        return []
    c = collections.Counter()
    for s in d.get("sites", []):
        dom = registrable_domain(s.get("domain") or "")
        if dom:
            c[dom] += (s.get("occ") or 1)
    return [dom for dom, _ in c.most_common(n)]


def dismiss_interstitial(page, log):
    """Google's adult 'Check your settings' modal + cookie consent — click through."""
    for label in ("Got it", "Accept all", "I agree", "Reject all", "Turn off SafeSearch"):
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click(timeout=2500)
                page.wait_for_timeout(600)
                log(f"    dismissed '{label}'")
        except Exception:
            pass


def _compress(png, box=1700):
    if HAVE_PIL:
        try:
            im = Image.open(io.BytesIO(png)).convert("RGB")
            im.thumbnail((box, box))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=76)
            return True, buf.getvalue()
        except Exception:
            pass
    return False, png


def _brand(domain):
    """shareanynudes.com -> shareanynudes ; de.thefap.net -> thefap (the searchable brand)."""
    reg = registrable_domain(domain) or domain
    return reg.split(".")[0] if reg else ""


def build_queries(handle, name, suffixes, domains, max_n, site=False):
    """Query list: handle+suffix image searches, then per-domain searches. By DEFAULT the
    leak site is a plain KEYWORD (`juliafilippo fapello`) — a full masonry of her content;
    with site=True it uses the `site:<domain>` operator instead (for A/B comparison)."""
    out = []
    for s in suffixes:
        # use the real display name for the bare 'nude' search (sophieraiin used 'sophie rain nude')
        q = f"{name} {s}" if (s == "nude" and name) else f"{handle} {s}"
        out.append(q.strip())
    for d in domains:
        if site:
            out.append(f"{handle} site:{registrable_domain(d) or d}")
        else:
            b = _brand(d)
            if b:
                out.append(f"{handle} {b}")
    # dedup, preserve order, cap
    seen, uniq = set(), []
    for q in out:
        if q.lower() not in seen:
            seen.add(q.lower())
            uniq.append(q)
    return uniq[:max_n]


def capture(queries, out_dir, udm, timeout_ms, use_incogniton, headful, log,
            solve=False, solve_wait=300, collect_images_on=True, per_query=8, alias_alnum=(),
            hi_res=False):
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        log("[gshots] Playwright not installed — cannot screenshot "
            "(pip install playwright && playwright install chromium).")
        return [], collections.Counter(), [], set()
    shots_dir = os.path.join(out_dir, "shots")
    os.makedirs(shots_dir, exist_ok=True)
    # continue NNN numbering after any existing shots (site: run appended to plain run)
    existing = [f for f in os.listdir(shots_dir) if re.match(r"\d+_google-com", f)]
    n = max([int(f.split("_")[0]) for f in existing], default=0)
    shots, blocked = [], 0
    domain_counter = collections.Counter()           # source domains of the on-page tiles
    index, links = [], set()                          # ONE PASS also yields frames + source links
    seen_img, seen_idents, seen_hashes = set(), set(), set()
    try:                                              # reuse collect_images' scraper + downloader
        from collect_images import (scrape_google_images as _scrape_tiles,
                                     download_image as _dl_img, validate_image as _val_img,
                                     img_identity as _img_ident, slugify as _slugify,
                                     alnum as _alnum)
    except Exception:
        _scrape_tiles = _dl_img = _val_img = _img_ident = _slugify = _alnum = None
    with sync_playwright() as pw:
        try:
            browser, ctx, mode = browser_common.acquire_browser(
                pw, headful=headful, use_incogniton=use_incogniton, log=log)
        except Exception as e:
            # Incogniton unreachable AND local Chrome can't launch — don't crash with a traceback;
            # return empty exactly like the Playwright-missing branch so the run keeps going and
            # the synthetic gshots strip + crawl-only gallery remain the fallback.
            log(f"[gshots] could not acquire a browser ({e}) — skipping the real Google pass.")
            return [], collections.Counter(), [], set()
        try:
            ctx.set_default_timeout(timeout_ms)
            for pg in ctx.pages:
                pg.set_viewport_size({"width": 1600, "height": 1500})
        except Exception:
            pass
        page = ctx.new_page()
        try:
            page.set_viewport_size({"width": 1600, "height": 1500})
        except Exception:
            pass
        for q in queries:
            url = (f"https://www.google.com/search?q={quote_plus(q)}"
                   f"&udm={udm}&hl=en&gl=us")
            try:
                page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            except Exception as e:
                log(f"  [gshots] {q[:32]:34} goto failed ({str(e)[:40]}) — skip")
                continue
            page.wait_for_timeout(1200)
            dismiss_interstitial(page, log)
            if browser_common.looks_blocked(page):
                if solve:
                    log(f"  [gshots] {q[:32]:34} bot-wall — SOLVE IT in the browser window "
                        f"(waiting up to {solve_wait}s)…")
                    ok = browser_common.alert_and_wait(
                        page, log=log, max_wait=solve_wait,
                        blocked_check=lambda: browser_common.looks_blocked(page))
                    if ok:
                        dismiss_interstitial(page, log)
                        page.wait_for_timeout(900)
                    else:
                        blocked += 1
                        log(f"  [gshots] {q[:32]:34} still walled — skip")
                        continue
                else:
                    blocked += 1
                    log(f"  [gshots] {q[:32]:34} bot-wall/captcha — skip (unattended)")
                    continue
            try:                              # nudge lazy images in, then back to top
                for _ in range(2):
                    page.mouse.wheel(0, 1400)
                    page.wait_for_timeout(500)
                page.mouse.wheel(0, -8000)
                page.wait_for_timeout(400)
            except Exception:
                pass
            try:
                png = page.screenshot(full_page=False)
            except Exception as e:
                log(f"  [gshots] {q[:32]:34} screenshot failed ({str(e)[:40]}) — skip")
                continue
            n += 1
            is_jpeg, data = _compress(png)
            fp = os.path.join(shots_dir, f"{n:03d}_google-com{'.jpg' if is_jpeg else '.png'}")
            with open(fp, "wb") as fh:
                fh.write(data)
            try:
                title = page.title() or f"{q} - Google Search"
            except Exception:
                title = f"{q} - Google Search"
            shots.append({"local_path": os.path.relpath(fp, out_dir), "domain": "google.com",
                          "page_url": url, "title": title, "query": q,
                          "confident": True, "is_jpeg": is_jpeg})
            log(f"  [gshots] {len(shots)}/{len(queries)} {q[:32]:34} ok ({len(data)//1024}KB)")
            # harvest the per-tile SOURCE DOMAINS off this page (hosts of her images) so we
            # can rank/reuse them for the brand queries without a separate scrape.
            try:
                tiles = _scrape_tiles(page) if _scrape_tiles else []
            except Exception:
                tiles = []
            pdoms = [registrable_domain(t.get("page_url") or "") for t in tiles]
            pdoms = [d for d in pdoms if d and "google" not in d and "gstatic" not in d]
            for d in pdoms:
                domain_counter[d] += 1
            shots[-1]["tile_domains"] = [d for d, _ in collections.Counter(pdoms).most_common(12)]
            if pdoms:
                log(f"           +- {len(set(pdoms))} source domains "
                    f"(top: {', '.join(list(dict.fromkeys(pdoms))[:4])})")
            # HIGH-RES FRAMES + LINKS: the udm=2 masonry (great screenshot) only exposes
            # thumbnails, so for downloadable FULL-RES images re-open the SAME query on the
            # classic tbm=isch grid, whose /imgres anchors carry the full source `imgurl`
            # (exactly what got collect_images its real full-size images).
            if collect_images_on and _dl_img:
                if hi_res:
                    # opt-in extra pass: the classic tbm=isch grid (2x page loads). Google
                    # serves thumbnails on BOTH surfaces, so this barely changes resolution
                    # (~300-740px either way) — off by default; the crawl carries the hi-res gallery.
                    try:
                        isch = f"https://www.google.com/search?q={quote_plus(q)}&tbm=isch&hl=en&gl=us"
                        page.goto(isch, timeout=timeout_ms, wait_until="domcontentloaded")
                        page.wait_for_timeout(1000)
                        dismiss_interstitial(page, log)
                        if browser_common.looks_blocked(page):
                            raise RuntimeError("frame grid walled")
                        for _ in range(3):        # lazy-load the full grid
                            page.mouse.wheel(0, 3000)
                            page.wait_for_timeout(400)
                        ftiles = _scrape_tiles(page) if _scrape_tiles else []
                    except Exception as e:
                        ftiles = []
                        log(f"           +- frame pass skipped ({str(e)[:40]})")
                else:
                    ftiles = tiles            # default: reuse the udm=2 masonry tiles (one pass)
                slug = _slugify(q)
                dest_dir = os.path.join(out_dir, "google", slug)
                start = len(os.listdir(dest_dir)) if os.path.isdir(dest_dir) else 0
                kept, bsum = 0, 0
                for t in ftiles:
                    if kept >= per_query:
                        break
                    iu, pu = t.get("img_url") or "", t.get("page_url") or ""
                    if not iu or iu in seen_img:
                        continue
                    seen_img.add(iu)
                    ident = _img_ident(iu)
                    if ident and ident in seen_idents:
                        continue
                    if ident:
                        seen_idents.add(ident)
                    try:
                        raw = _dl_img(ctx.request, iu)
                    except Exception:
                        raw = None
                    ok, ext = _val_img(raw) if raw else (False, "")
                    if not ok:
                        continue
                    hh = hashlib.sha1(raw).hexdigest()
                    if hh in seen_hashes:
                        continue
                    seen_hashes.add(hh)
                    os.makedirs(dest_dir, exist_ok=True)
                    kept += 1
                    bsum += len(raw)
                    fpath = os.path.join(dest_dir, f"{start + kept:03d}.{ext}")
                    try:
                        with open(fpath, "wb") as fh:
                            fh.write(raw)
                    except Exception:
                        continue
                    hay = _alnum(iu + " " + pu)
                    index.append({"engine": "google", "query": q,
                                  "img_url": iu if not iu.startswith("data:") else "(data-uri)",
                                  "page_url": pu,
                                  "registrable": registrable_domain(pu) if pu else "",
                                  "local_path": os.path.relpath(fpath, out_dir),
                                  "bytes": len(raw),
                                  "confident": any(a and a in hay for a in alias_alnum)})
                    if pu.startswith("http"):
                        links.add(pu)
                if kept:
                    log(f"           +- {kept} frames (~{bsum // kept // 1024}KB avg, "
                        f"{'hi-res grid' if hi_res else 'one-pass'}) -> google/{slug}/")
        try:
            page.close()
            if mode != "incogniton":     # keep the shared Incogniton profile browser open
                browser.close()
        except Exception:
            pass
    if index:
        log(f"[gshots] collected {len(index)} google frames + {len(links)} source links (same pass).")
    log(f"[gshots] captured {len(shots)} screenshot(s); {blocked} query(ies) walled/skipped.")
    return shots, domain_counter, index, links


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--query", required=True, help="handle, e.g. juliafilippo")
    ap.add_argument("--name", default="", help="display name for the bare 'nude' search.")
    ap.add_argument("--domains", default="", help="comma leak domains for site: searches.")
    ap.add_argument("--from-cse", default=None,
                    help="derive site: domains from this CSE json's 'sites' — the hosts Google "
                         "actually surfaces her on (preferred; populated SERPs).")
    ap.add_argument("--from-crawl", default=None, help="fallback: derive site: domains from crawl json "
                    "(by media count — may include thinly-indexed hosts).")
    ap.add_argument("--top-domains", type=int, default=5)
    ap.add_argument("--suffixes", default="", help="comma override of the image-search suffixes.")
    ap.add_argument("--no-suffixes", action="store_true",
                    help="Skip the handle+suffix image searches — capture ONLY the per-domain "
                         "searches (top-up an existing run; merges into shots.json).")
    ap.add_argument("--site", action="store_true",
                    help="A/B: use the site:<domain> operator instead of the bare brand keyword.")
    ap.add_argument("--out-dir", required=True, help="images dir (shots/ + shots.json written here).")
    ap.add_argument("--max", type=int, default=13, help="max total screenshots.")
    ap.add_argument("--udm", default="2", help="Google surface (2=Images).")
    ap.add_argument("--timeout", type=int, default=30, help="per-page timeout (seconds).")
    ap.add_argument("--no-incogniton", action="store_true", help="skip Incogniton, use local Chrome.")
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--solve", action="store_true",
                    help="ATTENDED: on a captcha wall, keep a visible browser open and WAIT for you "
                         "to solve it (audible ping) instead of skipping. Forces --headful.")
    ap.add_argument("--solve-wait", type=int, default=300, help="Seconds to wait per captcha (--solve).")
    ap.add_argument("--collect-images", dest="collect_images", action="store_true", default=True,
                    help="ONE PASS: also download result thumbnails to google/<query>/ + index.json "
                         "(default on — replaces the separate collect_images incognito scrape).")
    ap.add_argument("--no-collect-images", dest="collect_images", action="store_false",
                    help="screenshots only; don't download frames or harvest links.")
    ap.add_argument("--per-query", type=int, default=8, help="frames to download per query.")
    ap.add_argument("--hi-res", dest="hi_res", action="store_true",
                    help="extra tbm=isch grid pass for frames (2x page loads). Google serves "
                         "thumbnails on both surfaces so it barely changes resolution — OFF by "
                         "default; the deep crawl supplies the hi-res gallery images.")
    ap.add_argument("--links-out", default=None,
                    help="append source-page URLs (dedup) here, e.g. {prefix}.google_links.txt.")
    ap.add_argument("--aliases", default="", help="comma handle/name variants for the 'confident' flag.")
    a = ap.parse_args()
    if a.solve:
        os.environ["CAPTCHA_ALERT"] = "1"        # let browser_common ping + poll while you solve
        a.headful = True                          # you must see the window to solve the wall
    browser_common.load_dotenv()

    def log(*x):
        print(*x, flush=True)

    try:                                          # same normaliser collect_images uses
        from collect_images import alnum as _alnum0
    except Exception:
        _alnum0 = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
    alias_src = [a.query, a.name] + [x.strip() for x in a.aliases.split(",") if x.strip()]
    alias_alnum = sorted({_alnum0(x) for x in alias_src if _alnum0(x)}, key=len, reverse=True)

    domains = [d.strip() for d in a.domains.split(",") if d.strip()]
    if not domains and a.from_cse:
        domains = top_domains_from_cse(a.from_cse, a.top_domains)     # Google-surfaced hosts
    if not domains and a.from_crawl:
        domains = top_domains_from_crawl(a.from_crawl, a.top_domains)  # fallback: crawl media count
    suffixes = [] if a.no_suffixes else ([s.strip() for s in a.suffixes.split(",") if s.strip()]
                                         or DEFAULT_SUFFIXES)
    queries = build_queries(a.query, a.name, suffixes, domains[:a.top_domains], a.max, site=a.site)
    os.makedirs(a.out_dir, exist_ok=True)
    log(f"[gshots] {len(queries)} queries for @{a.query} "
        f"({len(domains[:a.top_domains])} site-brand searches), out={a.out_dir}/")
    for q in queries:
        log(f"         · {q}")
    shots, domain_counter, index, links = capture(
        queries, a.out_dir, a.udm, a.timeout * 1000,
        use_incogniton=not a.no_incogniton, headful=a.headful, log=log,
        solve=a.solve, solve_wait=a.solve_wait,
        collect_images_on=a.collect_images, per_query=a.per_query, alias_alnum=alias_alnum,
        hi_res=a.hi_res)
    # write the harvested per-tile source-domains (hosts of her images) + intersect with CSE
    if domain_counter:
        ranked = domain_counter.most_common()
        with open(os.path.join(a.out_dir, "google_shots_domains.json"), "w", encoding="utf-8") as fh:
            json.dump([{"domain": d, "count": n} for d, n in ranked], fh, indent=2, ensure_ascii=False)
        log(f"\n[gshots] harvested {len(ranked)} tile source-domains -> "
            f"{a.out_dir}/google_shots_domains.json")
        for d, n in ranked[:20]:
            log(f"           {d:30} {n}")
        if a.from_cse and os.path.exists(a.from_cse):
            try:
                cse = json.load(open(a.from_cse, encoding="utf-8"))
                cse_doms = {registrable_domain(s.get("domain") or "") for s in cse.get("sites", [])}
                cse_doms.discard("")
                both = [(d, n) for d, n in ranked if d in cse_doms]
                log("[gshots] top domains in BOTH (page tiles ∩ CSE): "
                    + ", ".join(f"{d}({n})" for d, n in both[:8]))
                log("           brands(5): " + ",".join(d.split(".")[0] for d, _ in both[:5]))
            except Exception as e:
                log(f"[gshots] CSE intersect skipped: {e}")
    # ONE-PASS outputs: merge the downloaded frames into index.json (so build_gallery
    # --google-auto reads them) and append the source-page URLs to the links file.
    if index:
        idx_path = os.path.join(a.out_dir, "index.json")
        old_idx = []
        if os.path.exists(idx_path):
            try:
                old_idx = json.load(open(idx_path, encoding="utf-8"))
            except Exception:
                old_idx = []
        have = {r.get("local_path") for r in old_idx}
        merged_idx = old_idx + [r for r in index if r.get("local_path") not in have]
        json.dump(merged_idx, open(idx_path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        log(f"[gshots] index.json now {len(merged_idx)} google frames "
            f"({len(merged_idx) - len(old_idx)} new) -> {idx_path}")
    if links and a.links_out:
        old_links = set()
        if os.path.exists(a.links_out):
            old_links = {ln.strip() for ln in open(a.links_out, encoding="utf-8") if ln.strip()}
        all_links = sorted(old_links | links)
        open(a.links_out, "w", encoding="utf-8").write("\n".join(all_links) + "\n")
        log(f"[gshots] {len(all_links)} source links ({len(links - old_links)} new) -> {a.links_out}")
    if not shots:
        log("[gshots] nothing captured — leaving any existing shots.json untouched.")
        return
    # merge into any existing shots.json (dedup by page_url) so a site: top-up run
    # appends to an earlier image-search run instead of clobbering it.
    sj = os.path.join(a.out_dir, "shots.json")
    old = []
    if os.path.exists(sj):
        try:
            old = json.load(open(sj))
        except Exception:
            old = []
    seen = {s.get("page_url") for s in old}
    merged = old + [s for s in shots if s.get("page_url") not in seen]
    with open(sj, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2, ensure_ascii=False)
    log(f"[gshots] shots.json now {len(merged)} real Google screenshot(s) "
        f"({len(merged) - len(old)} new) — rebuild the report to embed them.")


if __name__ == "__main__":
    main()

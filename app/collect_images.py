#!/usr/bin/env python3
"""
collect_images.py — anti-piracy image collector (legitimate DMCA work).

For Google Images and each query family separately, scrapes image results
(thumbnail src + source-page url), downloads a spread of images PER query,
name-verifies them against the aliases, dedups (image URL, cross-mirror filename
stem, and exact bytes), and builds a blurred contact sheet (index.html + index.json).

Uses the INSTALLED Google Chrome (Playwright channel="chrome") in a fresh
INCOGNITO context (no stored state). No API keys.
Self-contained: stdlib + playwright + Pillow + netloc.py.

Usage:
  python3 collect_images.py --name "Ivette Aguero Tarazona" \
      --aliases taritafit,tarita.fit --out-dir tarita_images \
      [--per-source 8] [--engines google] [--headful]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import random
import re
import sys
import time
from urllib.parse import quote_plus, urlparse, parse_qs, unquote

from netloc import registrable_domain, norm_url

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except Exception as e:  # pragma: no cover
    print("FATAL: playwright not importable:", e, file=sys.stderr)
    sys.exit(2)

try:
    from PIL import Image
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

MIN_BYTES = 2048  # skip tiny/placeholder images (<2KB)


def alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s[:60] or "q"


def build_query_families(name: str, aliases: list[str]) -> list[str]:
    fams: list[str] = []
    for a in aliases:
        fams.append(f"{a} leaks")
        fams.append(f"{a} nude")
        fams.append(f"{a} onlyfans")
        fams.append(f"{a} porn")
    if name:
        fams.append(name)
    seen, out = set(), []
    for q in fams:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


# --------------------------------------------------------------------------- #
# Engine URLs & result scrapers -> list of {img_url, page_url}
# --------------------------------------------------------------------------- #
def google_url(q: str) -> str:
    return f"https://www.google.com/search?q={quote_plus(q)}&tbm=isch&hl=en&gl=us"


# Same-photo-different-mirror collapse: a distinctive filename stem (dimensions /
# thumb / CDN size suffixes stripped) is the cheapest cross-site dedup key there is.
_SIZE_SUFFIX = re.compile(
    r"[-_](?:\d{2,4}x\d{2,4}|thumb(?:nail)?|small|medium|large|scaled|min|\d{2,4}w)$", re.I)


def img_identity(img_url: str) -> str | None:
    """Distinctive filename stem from an image URL — 'sophieraiin_4f2a-1024x768.jpg'
    and '.../sophieraiin_4f2a.jpg' on another mirror collapse to 'sophieraiin4f2a'.
    Returns None for generic/numeric stems ('001', 'image') so we never over-merge."""
    try:
        base = os.path.basename(urlparse(img_url).path)
    except Exception:
        base = img_url or ""
    stem = re.sub(r"\.(jpe?g|png|webp|avif|gif)$", "", base, flags=re.I)
    stem = _SIZE_SUFFIX.sub("", stem)
    stem = alnum(stem)
    if len(stem) < 8 or stem.isdigit():   # too generic to be a safe identity key
        return None
    return stem


def _resolve_imgref(page_url: str) -> str:
    """Google wraps source page as /imgres?imgrefurl=...&imgurl=..."""
    if not page_url:
        return ""
    try:
        p = urlparse(page_url)
    except Exception:
        return page_url
    if "google." in (p.netloc or "") and "/imgres" in p.path:
        qs = parse_qs(p.query)
        ref = qs.get("imgrefurl", [""])[0]
        return unquote(ref) if ref else page_url
    return page_url


def _extract_source(href: str) -> str:
    """Real SOURCE-PAGE url behind a Google Images result anchor, so we keep the hosting
    domain (printed in the report / used for site: searches). Handles all three anchor
    forms: classic /imgres?imgrefurl=, the /url?q= redirect, and — modern udm=2 — a
    direct source link. Returns "" only when the anchor is a pure Google/gstatic href."""
    if not href:
        return ""
    try:
        p = urlparse(href)
        q = parse_qs(p.query or "")
        if "/imgres" in p.path or "imgrefurl" in (p.query or ""):
            return unquote(q.get("imgrefurl", [""])[0] or "")
        if p.path.rstrip("/").endswith("/url"):
            return unquote((q.get("q") or q.get("url") or [""])[0] or "")
        if href.startswith("http") and "google." not in (p.netloc or "") \
                and "gstatic." not in (p.netloc or ""):
            return href
    except Exception:
        pass
    return ""


def scrape_google_images(page):
    """Thumbnails + their SOURCE PAGE. Each result thumb <img> lives inside an <a>; keep
    that anchor's real source (see _extract_source) so the hosting domain is never lost.
    Modern udm=2 no longer uses /imgres anchors, so we select result anchors broadly and
    fall back to the classic /imgres selector."""
    out, seen = [], set()
    anchors = (page.query_selector_all(
                   "[role=main] a:has(img), #search a:has(img), div[data-attrid] a:has(img)")
               or page.query_selector_all("a[href*='/imgres']"))
    for a in anchors:
        img = a.query_selector("img")
        if not img:
            continue
        src = img.get_attribute("src") or img.get_attribute("data-src") or ""
        if not (src.startswith("http") or src.startswith("data:image")) or src in seen:
            continue
        href = a.get_attribute("href") or ""
        if href and not href.startswith("http"):
            href = "https://www.google.com" + href
        page_url = _extract_source(href)
        img_url = src
        if "/imgres" in href:                 # classic anchor also carries the full-res imgurl
            try:
                full = parse_qs(urlparse(href).query).get("imgurl", [""])[0]
                if full:
                    img_url = unquote(full) or src
            except Exception:
                pass
        seen.add(src)
        out.append({"img_url": img_url, "page_url": page_url})
    # last-ditch: raw imgs, still probing each one's nearest anchor for a source
    if not out:
        for img in page.query_selector_all("img"):
            src = img.get_attribute("data-src") or img.get_attribute("src") or ""
            if src.startswith("http") or src.startswith("data:image"):
                try:
                    href = img.evaluate("el => { const a = el.closest('a'); return a ? a.href : ''; }") or ""
                except Exception:
                    href = ""
                out.append({"img_url": src, "page_url": _extract_source(href)})
    return out


IMG_ENGINES = {
    "google": {"url": google_url, "scrape": scrape_google_images,
               "wait": "img, #search, #islrg"},
}


def detect_block(engine: str, page, html: str) -> str | None:
    """Precise block detection (engines ship 'captcha'/'challenge' scripts on
    every page, so we never flag on loose substrings)."""
    url = (page.url or "").lower()
    low = html.lower()
    if engine == "google":
        if "consent.google.com" in url:
            return "consent"
        if "/sorry/" in url:
            return "captcha"
        if "before you continue to google" in low:
            return "consent"
        if "our systems have detected unusual traffic" in low:
            return "captcha"
    if "verify you are human" in low or "are you a robot" in low:
        return "captcha"
    return None


# --------------------------------------------------------------------------- #
# Download / validate
# --------------------------------------------------------------------------- #
def download_image(ctx_request, img_url: str) -> bytes | None:
    """Fetch bytes via the browser context's request API (shares incognito state)."""
    try:
        if img_url.startswith("data:image"):
            head, b64 = img_url.split(",", 1)
            return base64.b64decode(b64 + "=" * (-len(b64) % 4))
        resp = ctx_request.get(img_url, timeout=20000)
        if not resp.ok:
            return None
        return resp.body()
    except Exception:
        return None


def validate_image(data: bytes) -> tuple[bool, str]:
    """Return (ok, ext). Reject tiny/placeholder; identify format via Pillow."""
    if not data or len(data) < MIN_BYTES:
        return False, ""
    if HAVE_PIL:
        try:
            im = Image.open(io.BytesIO(data))
            im.verify()
            fmt = (im.format or "JPEG").lower()
            w, h = im.size if hasattr(im, "size") else (0, 0)
            if w and h and (w < 40 or h < 40):
                return False, ""
            ext = {"jpeg": "jpg"}.get(fmt, fmt)
            if ext not in ("jpg", "png", "webp", "gif", "bmp"):
                ext = "jpg"
            return True, ext
        except Exception:
            return False, ""
    # no Pillow: sniff magic bytes
    if data[:3] == b"\xff\xd8\xff":
        return True, "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True, "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True, "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True, "gif"
    return False, ""


# --------------------------------------------------------------------------- #
# Screenshot capture — visual proof of the pages that host our leaks
# --------------------------------------------------------------------------- #
def _dedup_targets(items, cap, per_domain):
    """items: [{page_url, query?, confident?}] -> deduped, <=per_domain per site, <=cap."""
    seen, per, out = set(), {}, []
    for it in items:
        u = (it.get("page_url") or "").strip()
        if not u or not u.startswith("http"):
            continue
        nu = norm_url(u)
        if nu in seen:
            continue
        dom = registrable_domain(u)
        if per.get(dom, 0) >= max(1, per_domain):
            continue
        seen.add(nu)
        per[dom] = per.get(dom, 0) + 1
        out.append({"page_url": u, "domain": dom,
                    "query": it.get("query", ""), "confident": bool(it.get("confident"))})
        if len(out) >= cap:
            break
    return out


def _targets_from_file(path, cap, per_domain):
    """Round-robin across domains so a cap of N spreads over as many sites as possible."""
    by_dom = {}
    order = []
    if path and os.path.exists(path):
        for ln in open(path, encoding="utf-8"):
            u = ln.strip()
            if not u or not u.startswith("http"):
                continue
            dom = registrable_domain(u)
            if dom not in by_dom:
                by_dom[dom] = []
                order.append(dom)
            by_dom[dom].append(u)
    flat = []
    i = 0
    while any(by_dom.values()):
        dom = order[i % len(order)]
        if by_dom[dom]:
            flat.append({"page_url": by_dom[dom].pop(0)})
        i += 1
        if i > (cap + 5) * (len(order) + 1) * 4:
            break
    return _dedup_targets(flat, cap, per_domain)


def capture_shots(browser, shared_ctx, mode, targets, out_dir, log, timeout_ms=25000):
    """Open each target page and save a viewport screenshot (compressed JPEG).
    Returns a list of {page_url, domain, local_path, title, query, confident}."""
    shots = []
    shots_dir = os.path.join(out_dir, "shots")
    os.makedirs(shots_dir, exist_ok=True)
    if mode == "incogniton":
        sctx, page = shared_ctx, shared_ctx.new_page()
    else:
        sctx = browser.new_context(user_agent=UA, locale="en-US",
                                   viewport={"width": 1366, "height": 950})
        sctx.set_default_timeout(timeout_ms)
        page = sctx.new_page()
    try:                                    # BIGGER shots — taller/wider viewport = more image rows
        page.set_viewport_size({"width": int(os.environ.get("SHOT_W", "1600")),
                                "height": int(os.environ.get("SHOT_H", "1600"))})
    except Exception:
        pass
    n = 0
    for t in targets:
        u, dom = t["page_url"], t["domain"]
        try:
            page.goto(u, timeout=timeout_ms, wait_until="domcontentloaded")
        except Exception as e:
            log(f"  [shot] {dom} goto failed: {str(e)[:70]}")
            continue
        # Google search-results shots can land on a consent/captcha
        # wall — STOP + voice-ping the operator to solve it, then screenshot the
        # real results instead of the wall.
        seng = "google" if "google." in u else ""
        if seng and mode == "incogniton":
            import browser_common
            try:
                _h = page.content()
            except Exception:
                _h = ""
            if detect_block(seng, page, _h):
                def _sb(_e=seng):
                    try:
                        return bool(detect_block(_e, page, page.content()))
                    except Exception:
                        return False
                browser_common.alert_and_wait(page, log=log, blocked_check=_sb)
        try:
            page.wait_for_timeout(1600)
            # nudge lazy media in, then back to top so the hero image is in frame
            for _ in range(2):
                page.mouse.wheel(0, 1300)
                page.wait_for_timeout(650)
            page.mouse.wheel(0, -6000)
            page.wait_for_timeout(400)
        except Exception:
            pass
        try:
            png = page.screenshot(full_page=False)
        except Exception as e:
            log(f"  [shot] {dom} screenshot failed: {str(e)[:70]}")
            continue
        n += 1
        base = f"{n:03d}_" + re.sub(r"[^a-z0-9]+", "-", dom.lower())[:40]
        fpath = os.path.join(shots_dir, base + ".jpg")
        try:
            if HAVE_PIL:
                im = Image.open(io.BytesIO(png)).convert("RGB")
                _mx = int(os.environ.get("SHOT_MAX", "1200"))   # bigger shots: raise via SHOT_MAX
                im.thumbnail((_mx, _mx))
                im.save(fpath, "JPEG", quality=int(os.environ.get("SHOT_Q", "80")))
            else:
                fpath = os.path.join(shots_dir, base + ".png")
                with open(fpath, "wb") as fh:
                    fh.write(png)
        except Exception:
            fpath = os.path.join(shots_dir, base + ".png")
            with open(fpath, "wb") as fh:
                fh.write(png)
        try:
            title = page.title() or ""
        except Exception:
            title = ""
        shots.append({
            "page_url": u, "domain": dom,
            "local_path": os.path.relpath(fpath, out_dir),
            "title": title, "query": t.get("query", ""),
            "confident": t.get("confident", False),
        })
        log(f"  [shot] {n:2d}/{len(targets)} {dom}  ok")
    try:
        page.close()
        if mode != "incogniton":
            sctx.close()
    except Exception:
        pass
    with open(os.path.join(out_dir, "shots.json"), "w", encoding="utf-8") as fh:
        json.dump(shots, fh, indent=2, ensure_ascii=False)
    return shots


def main():
    ap = argparse.ArgumentParser(description="Anti-piracy image collector")
    ap.add_argument("--name", default="")
    ap.add_argument("--aliases", default="")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--per-source", type=int, default=8,
                    help="images to keep per engine per query family")
    ap.add_argument("--engines", default="google")
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--no-incogniton", action="store_true",
                    help="Use local headless Chrome instead of the Incogniton profile.")
    ap.add_argument("--profile-id", default=None, help="Override INCOGNITON_PROFILE_ID.")
    ap.add_argument("--shots", type=int, default=0,
                    help="Also screenshot up to N pages that host our leaks (0=off).")
    ap.add_argument("--shots-file", default=None,
                    help="Newline-delimited leak-page URLs to screenshot (else uses the "
                         "confident image source pages found during the run).")
    ap.add_argument("--shots-per-domain", type=int, default=2,
                    help="Max screenshots to take per registrable domain (variety).")
    ap.add_argument("--links-only", action="store_true",
                    help="Harvest first-page result/source links per engine; skip image download.")
    ap.add_argument("--engines-only-shots", action="store_true",
                    help="Skip image scraping; only capture the --shots-file screenshots.")
    args = ap.parse_args()

    import browser_common
    browser_common.load_dotenv()

    aliases = [a.strip() for a in args.aliases.split(",") if a.strip()]
    alias_alnum = sorted({alnum(a) for a in aliases if alnum(a)}, key=len, reverse=True)
    engines = [e.strip().lower() for e in args.engines.split(",") if e.strip()]
    engines = [e for e in engines if e in IMG_ENGINES]
    if args.engines_only_shots:
        engines = []          # screenshot-only run: skip image scraping entirely
    elif not engines:
        print("No valid image engines.", file=sys.stderr)
        sys.exit(1)

    families = build_query_families(args.name, aliases)
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    cap_total = max(1, args.per_source) * len(families) * len(engines)

    def log(*a):
        print(*a, flush=True)

    log(f"[collect_images] aliases={aliases} engines={engines} "
        f"families={len(families)} per-source={args.per_source} cap={cap_total}")

    index: list = []
    link_rows: list = []       # first-page result/source links across all engines
    link_seen: set = set()
    seen_img_urls: set = set()
    seen_idents: set = set()      # distinctive URL filename stems (cross-mirror dedup)
    seen_hashes: set = set()
    total = 0
    status_summary: dict = {}

    # Flush index.json/index.html on SIGTERM/SIGINT (timeout wrapper / Ctrl-C) so
    # a long, mostly-blocked run keeps the images already on disk + their index.
    import signal

    def _on_signal(signum, frame):
        try:
            _write_outputs(out_dir, index, args.name, aliases, status_summary, link_rows)
            log(f"\n[collect_images] signal {signum}: flushed index for "
                f"{len(index)} images to {out_dir}/")
        except Exception as e:
            log(f"[collect_images] signal flush error: {e}")
        os._exit(0)

    for _sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(_sig, _on_signal)
        except Exception:
            pass

    with sync_playwright() as pw:
        browser, shared_ctx, mode = browser_common.acquire_browser(
            pw, headful=args.headful, use_incogniton=not args.no_incogniton,
            profile_id=args.profile_id, log=log)
        try:
            for engine in engines:
                cfg = IMG_ENGINES[engine]
                if mode == "incogniton":
                    ctx, page = shared_ctx, shared_ctx.new_page()
                else:
                    ctx = browser.new_context(user_agent=UA, locale="en-US",
                                              viewport={"width": 1366, "height": 950})
                    ctx.set_default_timeout(30000)
                    page = ctx.new_page()
                log(f"\n=== IMAGE ENGINE: {engine} ({mode}) ===")
                for query in families:
                    if total >= cap_total:
                        break
                    slug = slugify(query)
                    key = f"{engine}||{query}"
                    st = "ok"
                    try:
                        page.goto(cfg["url"](query), timeout=35000,
                                  wait_until="domcontentloaded")
                    except Exception as e:
                        log(f"  [{engine}] {query!r} goto failed: {e}")
                        status_summary[key] = "blocked"
                        continue
                    try:
                        page.wait_for_selector(cfg["wait"], timeout=6000)
                    except Exception:
                        pass

                    # EARLY block check: skip the scroll/settle work if this is
                    # already a captcha/consent wall (keeps blocked runs fast).
                    try:
                        html = page.content()
                    except Exception:
                        html = ""
                    blk = detect_block(engine, page, html)
                    if blk and (mode == "incogniton" or args.headful):
                        # visible browser: STOP + voice-ping the operator to solve the
                        # wall, wait until the accurate per-engine detector says it's
                        # cleared, then re-read and continue (re-scrapes this query).
                        def _still_blocked(_e=engine):
                            try:
                                return bool(detect_block(_e, page, page.content()))
                            except Exception:
                                return False
                        if browser_common.alert_and_wait(page, log=log,
                                                         blocked_check=_still_blocked):
                            try:
                                html = page.content()
                            except Exception:
                                html = ""
                            blk = detect_block(engine, page, html)
                    if blk:
                        log(f"  [{engine}] {query!r} -> {blk}")
                        status_summary[key] = blk
                        time.sleep(random.uniform(1.0, 2.0))
                        continue

                    time.sleep(random.uniform(0.6, 1.2))
                    # scroll to trigger lazy image loading
                    for _ in range(3):
                        try:
                            page.mouse.wheel(0, 3000)
                        except Exception:
                            break
                        time.sleep(0.5)

                    try:
                        html = page.content()
                    except Exception:
                        pass

                    try:
                        raw = cfg["scrape"](page)
                    except Exception as e:
                        log(f"  [{engine}] {query!r} scrape error: {e}")
                        raw = []

                    # Harvest EVERY source link on this first results page (not just
                    # the images we keep) — first-page links are wanted per engine.
                    new_links = 0
                    for it in raw:
                        pu = _resolve_imgref(it.get("page_url", "") or "")
                        if pu and pu.startswith("http") and pu not in link_seen:
                            link_seen.add(pu)
                            link_rows.append({"url": pu, "engine": engine,
                                              "query": query,
                                              "registrable": registrable_domain(pu)})
                            new_links += 1
                    if args.links_only:
                        status_summary[key] = "links" if raw else "empty"
                        log(f"  [{engine}] {query!r:40s} links +{new_links:3d} "
                            f"(total links={len(link_seen)})")
                        time.sleep(random.uniform(0.5, 1.0))
                        continue

                    dest_dir = os.path.join(out_dir, engine, slug)
                    kept = 0
                    n = 0
                    for item in raw:
                        if kept >= args.per_source or total >= cap_total:
                            break
                        img_url = item.get("img_url", "")
                        page_url = _resolve_imgref(item.get("page_url", "")) or ""
                        if not img_url:
                            continue
                        dkey = img_url if img_url.startswith("data:") else norm_url(img_url)
                        if dkey in seen_img_urls:
                            continue
                        seen_img_urls.add(dkey)
                        # cross-mirror dedup on the URL filename stem: the same photo
                        # reposted at another size/CDN shares its distinctive stem, so
                        # we skip it before spending a download on it.
                        ident = img_identity(img_url)
                        if ident:
                            if ident in seen_idents:
                                continue
                            seen_idents.add(ident)

                        data = download_image(ctx.request, img_url)
                        ok, ext = validate_image(data)
                        if not ok:
                            continue
                        h = hashlib.sha1(data).hexdigest()
                        if h in seen_hashes:
                            continue
                        seen_hashes.add(h)

                        os.makedirs(dest_dir, exist_ok=True)
                        n += 1
                        fname = f"{n:03d}.{ext}"
                        fpath = os.path.join(dest_dir, fname)
                        try:
                            with open(fpath, "wb") as fh:
                                fh.write(data)
                        except Exception:
                            continue

                        hay = alnum(img_url + " " + page_url)
                        confident = any(a and a in hay for a in alias_alnum)
                        rel = os.path.relpath(fpath, out_dir)
                        index.append({
                            "engine": engine,
                            "query": query,
                            "img_url": img_url if not img_url.startswith("data:") else "(data-uri)",
                            "page_url": page_url,
                            "registrable": registrable_domain(page_url) if page_url else "",
                            "local_path": rel,
                            "bytes": len(data),
                            "confident": confident,
                        })
                        kept += 1
                        total += 1

                    status_summary[key] = ("ok" if kept else
                                           ("empty" if not raw else "empty"))
                    log(f"  [{engine}] {query!r:40s} kept {kept:2d} "
                        f"(scraped {len(raw)})  total={total}")
                    time.sleep(random.uniform(1.0, 2.0))
                try:
                    page.close()
                    if mode != "incogniton":   # keep the shared Incogniton profile context open
                        ctx.close()
                except Exception:
                    pass
                if total >= cap_total:
                    break

            # ── screenshots of the pages that host our leaks (visual proof) ──
            if args.shots and args.shots > 0:
                if args.shots_file:
                    targets = _targets_from_file(args.shots_file, args.shots, args.shots_per_domain)
                else:
                    cp = [{"page_url": r["page_url"], "query": r["query"], "confident": True}
                          for r in index if r.get("confident") and r.get("page_url")]
                    targets = _dedup_targets(cp, args.shots, args.shots_per_domain)
                if targets:
                    log(f"\n=== SCREENSHOTS: capturing {len(targets)} leak pages ({mode}) ===")
                    try:
                        shots = capture_shots(browser, shared_ctx, mode, targets, out_dir, log)
                        log(f"[shots] saved {len(shots)} screenshots to {out_dir}/shots/")
                    except Exception as e:
                        log(f"[shots] capture error: {e}")
                else:
                    log("[shots] no target pages to screenshot.")
        finally:
            # Write outputs FIRST — a captcha/challenge page can make
            # browser.close() hang, and we must not lose the collected index
            # or the images already on disk. Then close best-effort.
            try:
                _write_outputs(out_dir, index, args.name, aliases, status_summary, link_rows)
            except Exception as e:
                log(f"[collect_images] output write error: {e}")
            try:
                browser.close()
            except Exception:
                pass

    conf = sum(1 for r in index if r["confident"])
    per_engine = {}
    for r in index:
        per_engine[r["engine"]] = per_engine.get(r["engine"], 0) + 1
    log("\n" + "=" * 60)
    log(f"IMAGES: {len(index)} downloaded ({conf} confident, "
        f"{len(index)-conf} maybe)")
    log(f"per-engine: {per_engine}")
    blocked = {k: v for k, v in status_summary.items() if v not in ("ok",)}
    log(f"blocked/empty queries: {len(blocked)}")
    log(f"wrote: {out_dir}/index.json, {out_dir}/index.html")


def _write_outputs(out_dir, index, name, aliases, status_summary, link_rows=None):
    """Persist index.json + index.html. Called BEFORE browser teardown so a
    hanging close() can never lose the results."""
    with open(os.path.join(out_dir, "index.json"), "w") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    write_contact_sheet(out_dir, index, name, aliases, status_summary)
    if link_rows is not None:
        _write_links(out_dir, link_rows)


def _write_links(out_dir, link_rows):
    """Persist first-page result/source links: a dedup URL list (.txt) + full
    rows with engine/query/domain (.json)."""
    seen, urls = set(), []
    for r in link_rows:
        u = r.get("url")
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    with open(os.path.join(out_dir, "first_page_links.txt"), "w") as f:
        f.write("\n".join(urls) + ("\n" if urls else ""))
    with open(os.path.join(out_dir, "first_page_links.json"), "w") as f:
        json.dump(link_rows, f, indent=2, ensure_ascii=False)


def write_contact_sheet(out_dir, index, name, aliases, status_summary):
    from html import escape
    by_engine: dict = {}
    for r in index:
        by_engine.setdefault(r["engine"], []).append(r)

    parts = []
    parts.append("""<!doctype html><html><head><meta charset="utf-8">
<title>DMCA image contact sheet</title>
<style>
 body{font-family:system-ui,Arial,sans-serif;background:#111;color:#eee;margin:16px}
 h1{font-size:18px} h2{font-size:15px;margin:18px 0 6px;color:#9cf}
 .note{color:#aaa;font-size:12px;margin-bottom:10px}
 .grid{display:flex;flex-wrap:wrap;gap:10px}
 .card{width:180px;background:#1c1c1c;border:1px solid #333;border-radius:6px;
       padding:6px;font-size:11px}
 .card img{width:168px;height:168px;object-fit:cover;border-radius:4px;
       filter:blur(18px) brightness(.7);transition:filter .15s;cursor:pointer;
       background:#000}
 .card img.reveal{filter:none}
 .badge{display:inline-block;padding:1px 6px;border-radius:3px;font-weight:600}
 .confident{background:#2e7d32;color:#fff}
 .maybe{background:#5d4037;color:#fff}
 a{color:#9cf;word-break:break-all}
 .meta{margin-top:4px;line-height:1.3}
</style>
<script>
 function rev(e){e.classList.toggle('reveal');}
 function revAll(){document.querySelectorAll('.card img').forEach(i=>i.classList.add('reveal'));}
 function hideAll(){document.querySelectorAll('.card img').forEach(i=>i.classList.remove('reveal'));}
</script></head><body>""")
    parts.append(f"<h1>DMCA evidence contact sheet — {escape(name or '')}</h1>")
    parts.append(f"<div class='note'>aliases: {escape(', '.join(aliases))} &middot; "
                 f"{len(index)} images. Images are BLURRED by default — click a "
                 f"thumbnail to reveal it. Each links to its source page for takedown."
                 f" <button onclick='revAll()'>reveal all</button> "
                 f"<button onclick='hideAll()'>hide all</button></div>")

    for engine in sorted(by_engine):
        rows = by_engine[engine]
        c = sum(1 for r in rows if r["confident"])
        parts.append(f"<h2>{escape(engine)} — {len(rows)} images ({c} confident)</h2>")
        parts.append("<div class='grid'>")
        for r in rows:
            badge = ("<span class='badge confident'>confident</span>" if r["confident"]
                     else "<span class='badge maybe'>maybe</span>")
            page_url = r.get("page_url") or ""
            src_link = (f"<a href='{escape(page_url)}' target='_blank' rel='noreferrer'>"
                        f"{escape(registrable_domain(page_url) or page_url)}</a>"
                        if page_url else "<i>no source page</i>")
            parts.append(
                "<div class='card'>"
                f"<img src='{escape(r['local_path'])}' onclick='rev(this)' loading='lazy'>"
                f"<div class='meta'>{badge}<br>"
                f"<b>q:</b> {escape(r['query'])}<br>"
                f"<b>src:</b> {src_link}</div></div>")
        parts.append("</div>")

    # status footer
    blocked = {k: v for k, v in status_summary.items() if v not in ("ok",)}
    if blocked:
        parts.append("<h2>blocked / empty queries</h2><div class='note'>")
        for k, v in blocked.items():
            parts.append(escape(f"{k} -> {v}") + "<br>")
        parts.append("</div>")
    parts.append("</body></html>")

    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write("\n".join(parts))


if __name__ == "__main__":
    main()

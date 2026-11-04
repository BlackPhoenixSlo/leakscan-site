#!/usr/bin/env python3
"""
web_search.py — anti-piracy leak finder (legitimate DMCA work).

Runs an alias/name query set against Google and Reddit web search using the
INSTALLED Google Chrome (Playwright channel="chrome") in a fresh INCOGNITO
context per engine (no stored cookies/state). Scrapes organic result links,
drops platforms we never file against, and buckets each hit as
"likely" / "possible" based on where the alias appears.

No Google CSE / no API keys. Self-contained: stdlib + playwright + netloc.py.

Usage:
  python3 web_search.py --name "Ivette Aguero Tarazona" \
      --aliases taritafit,tarita.fit,tarita_fit --out tarita.search \
      [--engines google,reddit] [--max-per-query 20] [--headful]

Outputs:
  <out>.json         list of {engine,query,url,registrable,title,snippet,bucket,status}
  <out>.links.txt    unique likely+possible URLs, one per line
  <out>.status.json  per (engine,query) status summary
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import signal
import sys
import time
from urllib.parse import quote_plus, urlparse, parse_qs, unquote

from netloc import registrable_domain, is_lowvalue_subdomain, norm_url

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except Exception as e:  # pragma: no cover
    print("FATAL: playwright not importable:", e, file=sys.stderr)
    sys.exit(2)


# --------------------------------------------------------------------------- #
# Platforms / domains we never target (originals, socials, the engines, aggregators)
# --------------------------------------------------------------------------- #
EXCLUDED_DOMAINS = {
    # socials / originals
    "x.com", "twitter.com", "t.co", "instagram.com", "facebook.com", "fb.com",
    "fb.me", "tiktok.com", "youtube.com", "youtu.be", "onlyfans.com",
    "fansly.com", "patreon.com", "linktr.ee", "linktree.com", "beacons.ai",
    "allmylinks.com", "snapchat.com", "threads.net", "pinterest.com",
    "twitch.tv", "discord.com", "discord.gg", "telegram.org", "t.me",
    "linkedin.com",
    # reddit itself is never a takedown target here (we still SEARCH it)
    "reddit.com", "redd.it", "redditmedia.com",
    # search engines / their infra
    "google.com", "google.co.uk", "gstatic.com", "googleusercontent.com",
    "bing.com", "microsoft.com", "msn.com", "search.brave.com", "brave.com",
    "duckduckgo.com", "yahoo.com", "yandex.com", "ecosia.org",
    # link aggregators / shorteners / caches
    "bit.ly", "goo.gl", "tinyurl.com", "ow.ly", "webcache.googleusercontent.com",
    "translate.google.com", "archive.org", "web.archive.org",
    "wikipedia.org", "wikimedia.org", "amazon.com", "apple.com", "spotify.com",
    "imdb.com",
}

# Known piracy hosts we run explicit site: operators against.
PIRACY_SITES = ["picazor.com", "thothd.com", "leakgallery.com", "fapello.com"]

# Realistic desktop UA (Chrome). channel="chrome" already gives a real Chrome,
# we still set a stable UA string on the context.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def build_queries(name: str, aliases: list[str]) -> list[str]:
    q: list[str] = []
    for a in aliases:
        q.append(f'"{a}" onlyfans')
        q.append(f'"{a}" leak')
        q.append(f'"{a}" leaked')
        q.append(f'"{a}" nude')
    if name:
        q.append(f'"{name}" onlyfans nude')
    for a in aliases:
        for site in PIRACY_SITES:
            q.append(f"site:{site} {a}")
    # de-dup preserving order
    seen, out = set(), []
    for x in q:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


# --------------------------------------------------------------------------- #
# URL cleaning for redirect wrappers (Google /url?q=, Bing /ck/a, DDG l/)
# --------------------------------------------------------------------------- #
def unwrap(href: str) -> str | None:
    if not href:
        return None
    href = href.strip()
    if href.startswith("//"):
        href = "https:" + href
    try:
        p = urlparse(href)
    except Exception:
        return None
    host = (p.netloc or "").lower()
    # Google redirect
    if host.endswith("google.com") and p.path.startswith("/url"):
        qs = parse_qs(p.query)
        for k in ("q", "url"):
            if k in qs and qs[k]:
                return qs[k][0]
        return None
    # Bing redirect /ck/a?...&u=a1<base64>
    if host.endswith("bing.com") and "/ck/a" in p.path:
        qs = parse_qs(p.query)
        u = qs.get("u", [None])[0]
        if u:
            import base64
            v = u[2:] if u[:2] in ("a1", "a2", "a3") else u
            v = v.replace("-", "+").replace("_", "/")
            v += "=" * (-len(v) % 4)
            try:
                return base64.b64decode(v).decode("utf-8", "ignore")
            except Exception:
                return None
        return None
    if not p.scheme:
        return None
    return href


# --------------------------------------------------------------------------- #
# Status detection
# --------------------------------------------------------------------------- #
def detect_status(engine: str, page, html: str) -> str | None:
    """Return a blocking status ('consent'|'captcha'|'blocked') or None if ok.

    IMPORTANT: engines ship the word "captcha"/"challenge" in hidden anti-bot
    scripts on EVERY page, so we must NOT flag on loose substrings. We detect a
    block only via (a) a redirect to a known block URL, (b) an unmistakable
    block <title>, or (c) a real block container/phrase — and, for engines that
    have a results container, only when that container is ABSENT.
    """
    url = (page.url or "").lower()
    low = html.lower()
    title = ""
    try:
        title = (page.title() or "").strip().lower()
    except Exception:
        pass

    if engine == "google":
        if "consent.google.com" in url or "consent.youtube" in url:
            return "consent"
        if "/sorry/" in url:
            return "captcha"
        if "before you continue to google" in low:
            return "consent"
        if "our systems have detected unusual traffic" in low:
            return "captcha"
        # google renders results into div#search / #rso; absence + block phrase = block
        if "id=\"search\"" not in low and "id=\"rso\"" not in low:
            if "unusual traffic" in low or "not a robot" in low:
                return "captcha"

    elif engine == "reddit":
        if title == "blocked" or "whoa there" in low or "you've been blocked" in low:
            return "blocked"
        if "our cdn was unable" in low or "network security" in low:
            return "blocked"

    # generic hard blocks (only very specific phrases)
    if "verify you are human" in low or "are you a robot" in low:
        return "captcha"
    return None


# --------------------------------------------------------------------------- #
# Per-engine result extraction (returns list of (url, title, snippet))
# --------------------------------------------------------------------------- #
def _txt(el) -> str:
    try:
        return (el.inner_text() or "").strip().replace("\n", " ")[:400]
    except Exception:
        return ""


def extract_google(page):
    out = []
    # Each organic result lives in a div.g / div[data-hveid] with an h3 inside an anchor.
    anchors = page.query_selector_all("a:has(h3)")
    for a in anchors:
        href = a.get_attribute("href")
        u = unwrap(href)
        if not u:
            continue
        h3 = a.query_selector("h3")
        title = _txt(h3) if h3 else ""
        # snippet: climb to the result container and read text
        snip = ""
        try:
            cont = a.evaluate_handle("n => n.closest('div.g, div[data-hveid], div[data-sokoban-container]')")
            el = cont.as_element()
            if el:
                snip = _txt(el)
        except Exception:
            pass
        out.append((u, title, snip))
    return out


def extract_reddit(page):
    out = []
    # old.reddit search results
    for div in page.query_selector_all("div.search-result-link, div.search-result"):
        a = div.query_selector("a.search-title, a.search-link, a.title")
        if not a:
            continue
        u = unwrap(a.get_attribute("href"))
        if not u:
            continue
        out.append((u, _txt(a), _txt(div)))
    if out:
        return out
    # fallback: any external outbound link on the page
    for a in page.query_selector_all("a[href^='http']"):
        u = unwrap(a.get_attribute("href"))
        if u:
            out.append((u, _txt(a), ""))
    return out


ENGINES = {
    "google": {
        "url": lambda q: f"https://www.google.com/search?q={quote_plus(q)}&num=30&hl=en&gl=us",
        "extract": extract_google,
        "wait": "input[name=q], form[action='/search'], div#search, #captcha-form",
        "result_sel": "a:has(h3)",
    },
    "reddit": {
        "url": lambda q: f"https://old.reddit.com/search/?q={quote_plus(q)}&sort=relevance",
        "extract": extract_reddit,
        "wait": "body",
        "result_sel": "div.search-result-link, div.search-result",
    },
}


def is_excluded(url: str) -> bool:
    reg = registrable_domain(url)
    if not reg:
        return True
    if reg in EXCLUDED_DOMAINS:
        return True
    # engine sub-hosts already covered; also kill obvious google/bing/brave subs
    host = urlparse(url).netloc.lower()
    for bad in ("google.", "bing.", "brave.", "yahoo.", "duckduckgo."):
        if host.startswith(bad) or f".{bad}" in host:
            return True
    return False


def classify(url: str, title: str, snippet: str, alias_alnum: list[str]) -> str | None:
    hay_url = alnum(urlparse(url).netloc + urlparse(url).path)
    hay_txt = alnum(f"{title} {snippet}")
    for a in alias_alnum:
        if a and a in hay_url:
            return "likely"
    for a in alias_alnum:
        if a and a in hay_txt:
            return "possible"
    return None


def run_query(page, engine: str, query: str, cfg: dict, max_per: int,
              alias_alnum: list[str], results: list, log) -> str:
    url = cfg["url"](query)
    status = "ok"
    try:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
    except PWTimeout:
        log(f"    [{engine}] goto timeout")
        return "blocked"
    except Exception as e:
        log(f"    [{engine}] goto error: {e}")
        return "blocked"

    # let the page shell settle
    try:
        page.wait_for_selector(cfg["wait"], timeout=6000)
    except Exception:
        pass

    # EARLY block check: if the page is already a consent/captcha/block wall,
    # bail out now instead of burning the (expensive) result-item wait on a
    # page that will never have results. Keeps a fully-blocked run fast.
    try:
        html = page.content()
    except Exception:
        html = ""
    blk = detect_status(engine, page, html)
    if blk:
        return blk

    # nudge lazy loaders, then wait specifically for organic result items to
    # appear (they are JS-injected on Google/Bing).
    try:
        page.mouse.wheel(0, 2400)
    except Exception:
        pass
    try:
        page.wait_for_selector(cfg.get("result_sel", "body"), timeout=6000)
    except Exception:
        pass
    time.sleep(random.uniform(0.6, 1.2))

    # re-read after results may have rendered, and re-check for a late block
    try:
        html = page.content()
    except Exception:
        pass
    blk = detect_status(engine, page, html)
    if blk:
        return blk

    try:
        raw = cfg["extract"](page)
    except Exception as e:
        log(f"    [{engine}] extract error: {e}")
        raw = []

    kept = 0
    seen_norm = set()
    for (u, title, snip) in raw:
        if kept >= max_per:
            break
        if not u or not u.startswith(("http://", "https://")):
            continue
        try:
            nu = norm_url(u)
        except Exception:
            nu = u
        if nu in seen_norm:
            continue
        if is_excluded(nu):
            continue
        bucket = classify(nu, title, snip, alias_alnum)
        if bucket is None:
            # keep only alias-matching hits (likely/possible); skip pure noise
            continue
        seen_norm.add(nu)
        results.append({
            "engine": engine,
            "query": query,
            "url": nu,
            "registrable": registrable_domain(nu),
            "lowvalue_sub": is_lowvalue_subdomain(nu),
            "title": title,
            "snippet": snip,
            "bucket": bucket,
            "status": "ok",
        })
        kept += 1

    if kept == 0 and not raw:
        return "empty"
    if kept == 0:
        return "empty"
    return status


def _write_outputs(out_prefix: str, results: list, status_summary: dict) -> dict:
    """Persist <out>.json, <out>.links.txt, <out>.status.json. Returns the
    per-status counts. Called BEFORE browser teardown so a slow/hanging close()
    can never lose results."""
    out_json = f"{out_prefix}.json"
    out_links = f"{out_prefix}.links.txt"
    out_status = f"{out_prefix}.status.json"

    with open(out_json, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    seen, uniq_links = set(), []
    for r in results:
        if r["bucket"] in ("likely", "possible") and r["url"] not in seen:
            seen.add(r["url"])
            uniq_links.append(r["url"])
    with open(out_links, "w") as f:
        f.write("\n".join(uniq_links) + ("\n" if uniq_links else ""))

    nested: dict = {}
    counts: dict = {}
    for key, st in status_summary.items():
        eng, q = key.split("||", 1)
        nested.setdefault(eng, {})[q] = st
        counts[st] = counts.get(st, 0) + 1
    with open(out_status, "w") as f:
        json.dump({"per_query": nested, "status_counts": counts}, f,
                  indent=2, ensure_ascii=False)
    return counts


def main():
    ap = argparse.ArgumentParser(description="Anti-piracy web-search leak finder")
    ap.add_argument("--name", default="", help="full legal/stage name")
    ap.add_argument("--aliases", default="", help="comma-separated aliases/usernames")
    ap.add_argument("--out", required=True, help="output prefix (e.g. tarita.search)")
    ap.add_argument("--engines", default="google,reddit")
    ap.add_argument("--max-per-query", type=int, default=20)
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--no-incogniton", action="store_true",
                    help="Use local headless Chrome instead of the Incogniton profile.")
    ap.add_argument("--profile-id", default=None, help="Override INCOGNITON_PROFILE_ID.")
    args = ap.parse_args()

    import browser_common
    browser_common.load_dotenv()

    aliases = [a.strip() for a in args.aliases.split(",") if a.strip()]
    alias_alnum = sorted({alnum(a) for a in aliases if alnum(a)}, key=len, reverse=True)
    engines = [e.strip().lower() for e in args.engines.split(",") if e.strip()]
    engines = [e for e in engines if e in ENGINES]
    if not engines:
        print("No valid engines.", file=sys.stderr)
        sys.exit(1)

    queries = build_queries(args.name, aliases)

    def log(*a):
        print(*a, flush=True)

    log(f"[web_search] name={args.name!r} aliases={aliases} "
        f"engines={engines} queries={len(queries)} max/q={args.max_per_query}")

    results: list = []
    status_summary: dict = {}

    # Flush whatever we have on SIGTERM/SIGINT (e.g. a `timeout` wrapper or Ctrl-C)
    # so a long, mostly-blocked run never loses its partial results.
    def _on_signal(signum, frame):
        try:
            _write_outputs(args.out, results, status_summary)
            log(f"\n[web_search] signal {signum}: flushed "
                f"{len(results)} partial results to {args.out}.*")
        except Exception as e:
            log(f"[web_search] signal flush error: {e}")
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
            # Rotate engines: outer loop over engines, inner over queries, so a
            # single engine getting blocked doesn't starve the others.
            for engine in engines:
                cfg = ENGINES[engine]
                if mode == "incogniton":
                    ctx, page = shared_ctx, shared_ctx.new_page()   # profile's own context
                else:
                    ctx = browser.new_context(user_agent=UA, locale="en-US",
                                              viewport={"width": 1366, "height": 900})
                    ctx.set_default_timeout(30000)
                    page = ctx.new_page()
                log(f"\n=== ENGINE: {engine} ({mode}) ===")
                for qi, query in enumerate(queries, 1):
                    st = "error"
                    try:
                        st = run_query(page, engine, query, cfg,
                                       args.max_per_query, alias_alnum, results, log)
                        # visible browser (Incogniton/headful): STOP + voice-ping the
                        # operator to solve the wall, wait until the accurate per-engine
                        # detector clears, then retry the query once.
                        if st in ("captcha", "consent", "blocked") and (mode == "incogniton" or args.headful):
                            def _still_blocked(_e=engine):
                                try:
                                    return bool(detect_status(_e, page, page.content()))
                                except Exception:
                                    return False
                            if browser_common.alert_and_wait(page, log=log,
                                                             blocked_check=_still_blocked):
                                st = run_query(page, engine, query, cfg,
                                               args.max_per_query, alias_alnum, results, log)
                    except Exception as e:
                        log(f"    [{engine}] query crashed, continuing: {e}")
                        st = "error"
                    status_summary[f"{engine}||{query}"] = st
                    n = sum(1 for r in results if r["engine"] == engine and r["query"] == query)
                    log(f"  [{engine} {qi}/{len(queries)}] {st:8s} +{n:2d}  {query}")
                    time.sleep(random.uniform(1.0, 2.0))
                try:
                    page.close()
                    if mode != "incogniton":
                        ctx.close()
                except Exception:
                    pass
        finally:
            # Write outputs BEFORE browser teardown: a captcha/challenge page can
            # make browser.close() slow or hang, and we must never lose results.
            try:
                counts = _write_outputs(args.out, results, status_summary)
            except Exception as e:
                log(f"[web_search] output write error: {e}")
                counts = {}
            try:
                browser.close()
            except Exception:
                pass

    out_json = f"{args.out}.json"
    out_links = f"{args.out}.links.txt"
    out_status = f"{args.out}.status.json"
    uniq_links = [r["url"] for r in results if r["bucket"] in ("likely", "possible")]
    uniq_links = list(dict.fromkeys(uniq_links))

    # ---- console report ----
    likely = sum(1 for r in results if r["bucket"] == "likely")
    possible = sum(1 for r in results if r["bucket"] == "possible")
    per_engine = {}
    for r in results:
        per_engine[r["engine"]] = per_engine.get(r["engine"], 0) + 1
    log("\n" + "=" * 60)
    log(f"RESULTS: {len(results)} hits ({likely} likely, {possible} possible), "
        f"{len(uniq_links)} unique links")
    log(f"per-engine hits: {per_engine}")
    log(f"status counts:   {counts}")
    log(f"wrote: {out_json}, {out_links}, {out_status}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
expand_variants.py — turn a CONFIRMED slug into the extra indexed URLs Bruqi's
newest data shows we were missing: language-prefixed mirrors and fapello-family
re-upload variants. Each is a separately-indexed page => a separate takedown URL.

Gated + verified (devil's-advocate #3): we only expand a slug that is already
confirmed, and we keep a URL only if it returns HTTP 200 AND the handle actually
appears in the page (title or body), so we don't export 404s / soft-404 redirects.

    python3 expand_variants.py --slugs taritafit --out tarita.variants
    python3 expand_variants.py --from-crawl tarita.crawl.json --out tarita.variants

Outputs <out>.json (verified {url,domain,slug,kind,title}) and <out>.links.txt.
"""
import argparse, concurrent.futures as cf, gzip, json, re, ssl, sys
import urllib.parse, urllib.request, urllib.error
from netloc import registrable_domain

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
HDRS = {"user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        "accept-language": "en-US,en;q=0.9", "accept-encoding": "identity"}

# language-prefixed mirror families (domain -> langs) seen dominating Bruqi's newest links
LANG_MIRRORS = {
    "picazor.com":      ["en", "es", "de", "fr", "it", "pt", "nl", "pl", "zh", "ar", "ko", "ru"],
    "thothd.com":       ["en", "es", "de", "fr", "pt", "it"],
    "m.thothd.com":     ["en", "es", "de", "fr", "pt", "it"],
    "thothd.to":        ["en", "es", "de", "fr", "pt", "it"],
    "leakgallery.com":  ["en", "it", "nl", "fr", "de", "es", "pt"],
    "megaporn.ws":      ["en", "es", "de", "fr", "it", "pt", "zh", "tr"],
}
# fapello-family: also serves /{slug}-1/ /{slug}-2/ re-upload variants (+ /{page}/ pagination)
FAPELLO_FAMILY = ["fapello.com", "fapeza.com", "fapexy.com", "nudogram.com", "fapachi.com",
                  "fapmenu.com", "fapodrop.com", "fapellas.com", "fapomania.com", "fapullo.com",
                  "fapello.ru", "fapello.pics", "onlytreon.com", "nudostar.tv", "leakedmodels.com"]
FAPELLO_TMPL = ["https://{d}/{s}/", "https://{d}/{s}-1/", "https://{d}/{s}-2/",
                "https://{d}/{s}/2/", "https://{d}/{s}-1/2/", "https://{d}/models/{s}/"]


def norm(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def fetch(url, timeout=10):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HDRS),
                                    timeout=timeout, context=CTX) as r:
            raw = r.read(120000)
            if r.headers.get("content-encoding") == "gzip":
                raw = gzip.decompress(raw)
            return r.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def verify(url, slug, timeout):
    """Keep only if 200 AND the handle really appears (title or >=2 body occurrences)."""
    st, body = fetch(url, timeout)
    if st != 200 or len(body) < 200:
        return None
    ns = norm(slug)
    m = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    title = (m.group(1).strip() if m else "")[:120]
    in_title = ns in norm(title)
    occ = norm(body).count(ns)
    if in_title or occ >= 2:
        return {"url": url, "domain": registrable_domain(url), "slug": slug,
                "title": title, "in_title": in_title, "occ": occ}
    return None


def candidates(slug):
    enc = urllib.parse.quote(slug, safe="._-")
    out = []
    for dom, langs in LANG_MIRRORS.items():
        for lg in langs:
            out.append((f"https://{dom}/{lg}/{enc}", "lang-mirror"))
    for dom in FAPELLO_FAMILY:
        for t in FAPELLO_TMPL:
            out.append((t.format(d=dom, s=enc), "fapello-variant"))
    return out


def slugs_from_crawl(path):
    """Pull confirmed handle-like slugs out of a crawl json (normalised, brand tokens)."""
    data = json.load(open(path, encoding="utf-8"))
    found = set()
    for r in data:
        for s in r.get("slugs", []):
            n = norm(s)
            if "taritafit" in n or "taritafitness" in n:
                found.add("taritafit")
    return sorted(found)


def main():
    ap = argparse.ArgumentParser(description="Expand a confirmed slug into verified language/fapello variant URLs.")
    ap.add_argument("--slugs", help="Comma list of confirmed slugs.")
    ap.add_argument("--from-crawl", help="Pull confirmed slugs from a crawl json.")
    ap.add_argument("--out", default="variants")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--timeout", type=int, default=10)
    args = ap.parse_args()

    slugs = []
    if args.slugs:
        slugs += [s.strip() for s in args.slugs.split(",") if s.strip()]
    if args.from_crawl:
        slugs += slugs_from_crawl(args.from_crawl)
    slugs = list(dict.fromkeys(slugs))
    if not slugs:
        ap.error("Provide --slugs or --from-crawl with a confirmed slug.")

    cand = [(u, kind, s) for s in slugs for (u, kind) in candidates(s)]
    print(f"Probing {len(cand)} candidate variant URLs for slugs {slugs} ...", file=sys.stderr)
    hits = []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(verify, u, s, args.timeout): (u, kind) for (u, kind, s) in cand}
        done = 0
        for fut in cf.as_completed(futs):
            done += 1
            print(f"\r  {done}/{len(cand)}", end="", file=sys.stderr, flush=True)
            r = fut.result()
            if r:
                r["kind"] = futs[fut][1]
                hits.append(r)
    print("", file=sys.stderr)

    hits.sort(key=lambda x: (x["domain"], x["url"]))
    json.dump(hits, open(f"{args.out}.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    with open(f"{args.out}.links.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(h["url"] for h in hits) + ("\n" if hits else ""))
    bydom = {}
    for h in hits:
        bydom.setdefault(h["domain"], 0)
        bydom[h["domain"]] += 1
    print(f"VERIFIED {len(hits)} variant URLs across {len(bydom)} domains -> {args.out}.json / .links.txt",
          file=sys.stderr)
    for d in sorted(bydom, key=lambda x: -bydom[x]):
        print(f"  {d:22} {bydom[d]}", file=sys.stderr)


if __name__ == "__main__":
    main()

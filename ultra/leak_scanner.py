#!/usr/bin/env python3
"""
Leak scanner — reverse-engineered from Bruqi's detection.

Given a creator's name(s)/aliases, it checks every known leak domain the same
way Bruqi does: for each domain it hits either a PROFILE url (e.g.
nudostar.tv/models/{name}) or a SEARCH url (e.g. fapeza.com/search/{name}),
then reports a hit when the page returns 200 and actually mentions the name.

The per-domain check URLs live in bruqi_detection_map.json, which was derived
and live-verified from 22k real Bruqi findings (covers ~98% of them).

Usage
-----
    python3 leak_scanner.py jdoeex jdoeex2 alexsmith3
    python3 leak_scanner.py --names-file aliases.txt
    python3 leak_scanner.py jdoeex --method profile     # only profile checks
    python3 leak_scanner.py jdoeex --out scan-jdoeex   # output prefix

Outputs <prefix>.json / .csv / .links.txt of the hits (domain, alias, url, hits).
"""

import argparse
import concurrent.futures as cf
import csv
import json
import os
import re
import sys
import urllib.parse

import fetch_common
import leak_evidence

HERE = os.path.dirname(os.path.abspath(__file__))
HEADERS = fetch_common.HEADERS


def norm(s):
    """Lowercase, keep only alphanumerics — so jdoeex.1 / jdoeex_1 / jdoeex1 all match."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def fetch(url, timeout):
    """(status, body). Transport lives in fetch_common — see appDMCA #34 for why it
    is curl_cffi and not urllib."""
    status, _final, body = fetch_common.http_get(url, timeout, max_bytes=250000)
    return status, body


def check(domain, info, alias, timeout, min_occ):
    tmpl = info["check_url"]
    enc = urllib.parse.quote(alias, safe="._-")
    url = tmpl.replace("{name}", enc).replace("{lang}", "en")
    status, body = fetch(url, timeout)
    # Blocked is not absent. A challenge/403 means the host refused us and we learned
    # NOTHING about this creator; a 404 or a "not found" 200 means it answered and she
    # is not there. Collapsing the two into hit=False is how a blocked domain gets
    # reported to a creator as "no leaks found" (appDMCA #34).
    blocked = fetch_common.is_blocked(status, body)
    occ = norm(body).count(norm(alias)) if body else 0
    hit = status == 200 and occ >= min_occ and not blocked
    # Classify the evidence so search-echo false positives (a search page that
    # 200s and echoes the handle but hosts none of the creator's content) can be
    # dropped downstream. Reuses the body we already fetched — no extra request.
    evidence = leak_evidence.classify(url, info["method"], body, alias) if hit else None
    content_occ = 0
    if evidence in ("search-verified", "search-echo"):
        content_occ = leak_evidence.content_matches(
            body, leak_evidence.handle_variants(alias))[0]
    return {
        "domain": domain,
        "method": info["method"],
        "alias": alias,
        "url": url,
        "status": status,
        "occurrences": occ,
        "hit": hit,
        "blocked": blocked,
        "title": fetch_common.page_title(body) if blocked else "",
        "evidence": evidence,
        "content_matches": content_occ,
    }


def main():
    p = argparse.ArgumentParser(description="Scan known leak domains for a creator's name/aliases.")
    p.add_argument("names", nargs="*", help="Aliases / usernames to check.")
    p.add_argument("--names-file", help="File with one alias per line.")
    p.add_argument("--map", default=os.path.join(HERE, "bruqi_detection_map.json"))
    p.add_argument("--method", choices=["profile", "search", "all"], default="all")
    p.add_argument("--out", default="data/leak-scan")
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--timeout", type=int, default=15)
    p.add_argument("--min-occ", type=int, default=1, help="Min name occurrences in page to count as a hit.")
    p.add_argument("--include-unverified", action="store_true", help="Also try domains whose check URL wasn't verified.")
    p.add_argument("--variations", action="store_true",
                   help="Auto-expand each name into near-miss handles (username_variations.py).")
    p.add_argument("--var-max", type=int, default=40, help="Max variations per name when --variations.")
    args = p.parse_args()

    aliases = list(args.names)
    if args.names_file:
        with open(args.names_file, encoding="utf-8") as fh:
            aliases += [ln.strip() for ln in fh if ln.strip()]
    aliases = list(dict.fromkeys(aliases))  # dedupe, keep order
    if args.variations:
        from username_variations import expand_all
        aliases = expand_all(aliases, args.var_max)
    if not aliases:
        p.error("Provide at least one alias (positional) or --names-file.")

    dmap = json.load(open(args.map, encoding="utf-8"))
    domains = {
        d: v for d, v in dmap.items()
        if v.get("check_url")
        and (args.include_unverified or v.get("verified"))
        and (args.method == "all" or v.get("method") == args.method)
    }

    tasks = [(d, info, a) for d, info in domains.items() for a in aliases]
    print(f"Scanning {len(domains)} domains x {len(aliases)} aliases = {len(tasks)} checks ...", file=sys.stderr)
    print(f"  {fetch_common.backend_note()}", file=sys.stderr)

    results = []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(check, d, info, a, args.timeout, args.min_occ) for d, info, a in tasks]
        done = 0
        seen_hit_domains = set()
        for fut in cf.as_completed(futs):
            r = fut.result()
            results.append(r)
            done += 1
            if (r.get("hit") and leak_evidence.is_real(r.get("evidence"))
                    and r["domain"] not in seen_hit_domains):
                seen_hit_domains.add(r["domain"])
                print(f"\n  FOUND {r['domain']} ({r.get('occurrences', 0)} matches)",
                      file=sys.stderr, flush=True)
            print(f"\r  {done}/{len(tasks)}", end="", file=sys.stderr, flush=True)
    print("", file=sys.stderr)

    hits = [r for r in results if r["hit"]]
    # one row per (domain, alias) hit; collapse to best alias per domain for summary
    by_domain = {}
    for h in hits:
        by_domain.setdefault(h["domain"], []).append(h)

    cols = ["domain", "method", "alias", "url", "status", "occurrences"]
    with open(f"{args.out}.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for h in sorted(hits, key=lambda x: x["domain"]):
            w.writerow([h[c] for c in cols])
    json.dump(hits, open(f"{args.out}.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    with open(f"{args.out}.links.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(sorted({h["url"] for h in hits})) + "\n")

    # A dead network makes fetch() return status 0 for EVERY check, so the scan writes an empty
    # hits file and prints "FOUND on 0/375" — indistinguishable from "this creator has no leaks".
    # If almost every fetch failed to connect, that's a connectivity problem, not a clean result:
    # exit nonzero so the pipeline aborts (fatal on a core step) instead of crawling/reporting nothing.
    #
    # A BLOCKED run is the same false-clean result reached a different way, and the original guard
    # missed it: from a datacenter IP the hosts answer, with 403s, so status is never 0 and the scan
    # exits 0 having learned nothing (appDMCA #34). Count refusals alongside dead connections.
    dead = sum(1 for r in results if r.get("status") == 0)
    blocked = sum(1 for r in results if r.get("blocked"))
    unusable = dead + blocked
    if results and unusable / len(results) > 0.9:
        print(f"\n!! ABORT: {unusable}/{len(results)} checks returned nothing usable "
              f"({dead} failed to connect, {blocked} were refused by the host) — this is a network "
              f"or bot-wall problem, not a genuine 'no leaks' result. Do NOT report it as clean.",
              file=sys.stderr)
        if blocked > dead and fetch_common.BACKEND != "curl_cffi":
            print(f"   {fetch_common.backend_note()}", file=sys.stderr)
        sys.exit(3)

    # Below the abort threshold, blocked domains are still holes in the result — name them, so a
    # thin scan is never mistaken for a thorough one.
    if blocked:
        bl = sorted({r["domain"] for r in results if r.get("blocked")})
        print(f"\n!! {blocked} check(s) blocked across {len(bl)} domain(s) — NOT scanned, not clean: "
              f"{', '.join(bl[:12])}{' …' if len(bl) > 12 else ''}", file=sys.stderr)

    print(f"\nFOUND on {len(by_domain)} / {len(domains)} domains "
          f"({len(hits)} alias-hits). Files: {args.out}.csv / .json / .links.txt", file=sys.stderr)
    for d in sorted(by_domain, key=lambda x: -len(by_domain[x])):
        al = ",".join(sorted({h["alias"] for h in by_domain[d]}))
        print(f"  {d:26} [{by_domain[d][0]['method']:7}]  via: {al}", file=sys.stderr)


if __name__ == "__main__":
    main()

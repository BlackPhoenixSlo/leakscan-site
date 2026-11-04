#!/usr/bin/env python3
"""
Ownership verification — confirm a creator put our one-time code in their public
Instagram / OnlyFans bio.

IG serves a login wall and OnlyFans a JS-only SPA shell to anonymous requests, so
the reliable read is through the LOGGED-IN Incogniton anti-detect browser
(connect_incogniton.open_incogniton). Run as a SUBPROCESS by public_app so the
heavy Playwright/Incogniton deps stay out of the stdlib web server.

Usage:
  python3 bio_verify.py --handle jakabasej --code bruqi-ab12cd \
      --platforms instagram,onlyfans --out result.json
  python3 bio_verify.py --handle jakabasej --code bruqi-ab12cd --http-only   # no browser

Result JSON (also written to --out):
  {"verified": bool, "matched_platform": str|null,
   "checked": [{"platform","url","ok","found","error"}]}
Progress lines go to STDERR (so the caller can stream them as SSE); the machine
result is written to --out (and echoed to stdout for standalone use).
"""

import argparse
import json
import os
import re
import sys

PROFILE_URLS = {
    "instagram": "https://www.instagram.com/{handle}/",
    "onlyfans": "https://onlyfans.com/{handle}",
}
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")


def norm_code(s):
    """Lowercase + keep only alphanumerics, so 'bruqi-ab12cd', 'bruqi ab12cd' and
    'BRUQIAB12CD' all match the same bio text."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def code_in_text(code, text):
    """True if the code (normalization-insensitive) appears in text."""
    nc = norm_code(code)
    return bool(nc) and nc in norm_code(text)


def _fetch_http(url, timeout=20):
    import ssl
    import urllib.request
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read(600000).decode("utf-8", "replace")


def _fetch_incogniton(url, profile_id, timeout=45):
    """Load the profile in the logged-in Incogniton profile and return its
    rendered text + HTML (so the code is found whether it's visible text or in
    an embedded JSON blob)."""
    from playwright.sync_api import sync_playwright
    from connect_incogniton import open_incogniton
    with sync_playwright() as pw:
        browser, context = open_incogniton(pw, profile_id)
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            page.wait_for_timeout(2500)  # let the bio render
            text = ""
            try:
                text = page.inner_text("body")
            except Exception:
                pass
            html = page.content()
            return (text or "") + "\n" + (html or "")
        finally:
            page.close()
            browser.close()


def check_platform(platform, handle, code, http_only, profile_id):
    url = PROFILE_URLS[platform].format(handle=handle)
    entry = {"platform": platform, "url": url, "ok": False, "found": False, "error": None}
    try:
        print(f"Checking {platform} bio: {url}", file=sys.stderr, flush=True)
        content = _fetch_http(url) if http_only else _fetch_incogniton(url, profile_id)
        entry["ok"] = True
        entry["found"] = code_in_text(code, content)
        print(f"  {platform}: {'CODE FOUND' if entry['found'] else 'code not found'}",
              file=sys.stderr, flush=True)
    except Exception as e:
        entry["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        print(f"  {platform} error: {entry['error']}", file=sys.stderr, flush=True)
    return entry


def verify(handle, code, platforms, http_only=False, profile_id=None):
    """Return the result dict. Stops at the first platform that confirms."""
    handle = re.sub(r"[^A-Za-z0-9._-]", "", handle or "")[:60]
    checked, matched = [], None
    for p in platforms:
        if p not in PROFILE_URLS:
            continue
        e = check_platform(p, handle, code, http_only, profile_id)
        checked.append(e)
        if e["found"]:
            matched = p
            break
    return {"verified": matched is not None, "matched_platform": matched, "checked": checked}


def main():
    ap = argparse.ArgumentParser(description="Verify an ownership code in an IG/OF bio.")
    ap.add_argument("--handle", required=True)
    ap.add_argument("--code", required=True)
    ap.add_argument("--platforms", default="instagram,onlyfans")
    ap.add_argument("--http-only", action="store_true",
                    help="Plain HTTP fetch (no Incogniton browser).")
    ap.add_argument("--profile-id",
                    default=os.environ.get("INCOGNITON_SOCIAL_PROFILE_ID")
                    or os.environ.get("INCOGNITON_PROFILE_ID"))
    ap.add_argument("--out")
    args = ap.parse_args()

    platforms = [x.strip() for x in args.platforms.split(",") if x.strip()]
    result = verify(args.handle, args.code, platforms,
                    http_only=args.http_only, profile_id=args.profile_id)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
    print(json.dumps(result))
    return 0 if result["verified"] else 2


if __name__ == "__main__":
    sys.exit(main())

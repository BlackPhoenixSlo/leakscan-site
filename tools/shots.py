#!/usr/bin/env python3
"""Screenshot pages at phone + desktop, light + dark, top-of-page + full-page.

Usage: python3 tools/shots.py OUT_DIR URL [URL ...]
Writes OUT_DIR/<name>-<phone|desktop>-<light|dark>-<top|full>.png, where <name> is the
URL's last path segment without .html ("index" for a directory URL).
Scrolls each page top to bottom first so scroll-triggered fade-ins and lazy iframes load.
"""
import pathlib, sys
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

VIEWPORTS = {
    "phone": dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True),
    "desktop": dict(viewport={"width": 1440, "height": 900}, device_scale_factor=1),
}


def name_of(url):
    seg = urlsplit(url).path.rstrip("/").split("/")[-1] if not urlsplit(url).path.endswith("/") else ""
    return (seg[:-5] if seg.endswith(".html") else seg) or "index"


def settle(page):
    page.evaluate("document.documentElement.style.scrollBehavior = 'auto'")
    h = page.evaluate("document.documentElement.scrollHeight")
    y = 0
    while y < h:
        page.evaluate(f"window.scrollTo(0, {y})")
        page.wait_for_timeout(120)
        y += 500
        h = page.evaluate("document.documentElement.scrollHeight")
    page.wait_for_timeout(700)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(500)


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    out = pathlib.Path(argv[0]).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for url in argv[1:]:
            for vp, opts in VIEWPORTS.items():
                for scheme in ("light", "dark"):
                    ctx = browser.new_context(color_scheme=scheme, **opts)
                    page = ctx.new_page()
                    page.goto(url, wait_until="load")
                    settle(page)
                    base = out / f"{name_of(url)}-{vp}-{scheme}"
                    page.screenshot(path=f"{base}-top.png")
                    page.screenshot(path=f"{base}-full.png", full_page=True)
                    ctx.close()
                    print(f"{base}-{{top,full}}.png")
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])

#!/usr/bin/env python3
"""Screenshot pages at phone + desktop, light + dark, top-of-page + full-page.

Usage: python3 tools/shots.py OUT_DIR URL [URL ...]
Writes OUT_DIR/<name>-<phone|desktop>-<light|dark>-<top|full>.png, where <name> is the
URL path relative to the URLs' common directory, "/" -> "-", without .html, "index" for a
directory URL: `/` + `/showcase/` + `/showcase/blog/post-1.html` give `index`,
`showcase-index`, `showcase-blog-post-1`.
Scrolls each page top to bottom first so scroll-triggered fade-ins and lazy iframes load.
"""
import pathlib, posixpath, sys
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

VIEWPORTS = {
    "phone": dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True),
    "desktop": dict(viewport={"width": 1440, "height": 900}, device_scale_factor=1),
}


def names_of(urls):
    """URL -> file-name stem, unique within one invocation (see module docstring)."""
    paths = [urlsplit(u).path or "/" for u in urls]
    paths = [p + "index.html" if p.endswith("/") else p for p in paths]
    root = posixpath.commonpath([posixpath.dirname(p) for p in paths])
    stems = [posixpath.relpath(p, root).removesuffix(".html").replace("/", "-") for p in paths]
    return dict(zip(urls, stems))


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
        names = names_of(argv[1:])
        for url in argv[1:]:
            for vp, opts in VIEWPORTS.items():
                for scheme in ("light", "dark"):
                    ctx = browser.new_context(color_scheme=scheme, **opts)
                    page = ctx.new_page()
                    page.goto(url, wait_until="load")
                    settle(page)
                    base = out / f"{names[url]}-{vp}-{scheme}"
                    page.screenshot(path=f"{base}-top.png")
                    page.screenshot(path=f"{base}-full.png", full_page=True)
                    ctx.close()
                    print(f"{base}-{{top,full}}.png")
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])

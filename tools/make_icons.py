#!/usr/bin/env python3
"""Render raster assets with Playwright (no other deps):
  tools/og.html          -> site/assets/og-jack.jpg (1200x630, JPEG q80, ~QQ KB; check.py caps rasters at 100 KB)
  site/assets/favicon.svg -> site/assets/apple-touch-icon.png (180) + favicon-32.png
Usage: python3 tools/make_icons.py
New og image look -> new file name (link-preview caches key on the image URL), then update every og:image/twitter:image.
"""
import pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "site" / "assets"


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1200, "height": 630})
        pg.goto((ROOT / "tools" / "og.html").as_uri())
        pg.screenshot(path=str(ASSETS / "og-jack.jpg"), type="jpeg", quality=80)
        svg = (ASSETS / "favicon.svg").read_text()
        for size, name in ((180, "apple-touch-icon.png"), (32, "favicon-32.png")):
            pg = b.new_page(viewport={"width": size, "height": size})
            sized = svg.replace('width="32" height="32"', f'width="{size}" height="{size}"', 1)
            pg.set_content(f'<body style="margin:0;background:#a8431c">{sized}</body>')
            pg.screenshot(path=str(ASSETS / name))
        b.close()


if __name__ == "__main__":
    main()

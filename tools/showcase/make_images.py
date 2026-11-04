#!/usr/bin/env python3
"""Build site/showcase/imgs/*.webp from Pexels originals (credits: CREDITS.md).

    python3 tools/showcase/make_images.py [--cache /tmp/showcase-px/src] [NAME.webp ...]

Each image is cropped to the aspect ratio _make_placeholders.SPECS gives for
its filename, at SPECS size (never upscaled), then saved as WebP at the
highest quality that fits its weight budget, stepping the size down if even
q=60 does not fit. Give file names to rebuild only those. Downloads stay in the cache dir, outside the repo.
The demo creator is fictional; the photos are one Pexels series of one model (a potter in her studio), so the
site reads as one real person. Output is capped at MAX_W px wide and BUDGET bytes (page weight).
"""
import argparse
import io
import os
import sys
import urllib.request

from PIL import Image

import _sitelib as site
from _make_placeholders import SPECS

OUT = site.PUBLIC / "imgs"
HERO_BUDGET = 180_000          # the two homepage heroes
BUDGET = 180_000               # everything else
MAX_W = 1600                   # declared width/height stay the SPECS design size (aspect); files are smaller

# filename: (pexels id, focal point x,y as 0..1 of the original[, "flip"])
# "flip" mirrors the photo, used to put the subject on the right third.
IMAGES = {
    "hero-wide.webp":          (5302896, (0.62, 0.42)),
    "portrait.webp":           (5302893, (0.50, 0.42)),
    "studio-portrait.webp":    (5302902, (0.50, 0.40)),
    "headshot.webp":           (5302902, (0.50, 0.30)),
    "og.webp":                 (5302896, (0.62, 0.40)),
    "editorial-01.webp":       (5302909, (0.50, 0.50)),
    "editorial-02.webp":       (5302907, (0.76, 0.50)),
    "editorial-03.webp":       (6312194,  (0.50, 0.50)),
    "editorial-04.webp":       (33126633, (0.50, 0.50)),
    "outdoors.webp":           (5302895, (0.50, 0.50)),
    "behind-the-scenes.webp":  (5302910, (0.50, 0.50)),
    "about-hero.webp":         (5302908, (0.50, 0.50)),
    "timeline-hero.webp":      (38806951, (0.50, 0.50)),
    "verify-hero.webp":        (8063803,  (0.50, 0.50)),
    "blog-why-this-site.webp": (5302892, (0.62, 0.45)),
    "blog-where-to-find-me.webp": (5302900, (0.55, 0.45)),
    "blog-impersonators.webp": (5302899, (0.62, 0.45)),
}
HEROES = {"hero-wide.webp", "portrait.webp"}


def fetch(pid, cache, width):
    path = os.path.join(cache, f"{pid}-{width}.jpg")
    if not os.path.exists(path):
        url = (f"https://images.pexels.com/photos/{pid}/pexels-photo-{pid}.jpeg"
               f"?auto=compress&cs=tinysrgb&w={width}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=90) as r, open(path, "wb") as f:
            f.write(r.read())
    return path


def crop(im, aspect, focal):
    W, H = im.size
    aw, ah = aspect
    if W / H > aw / ah:
        w, h = round(H * aw / ah), H
    else:
        w, h = W, round(W * ah / aw)
    x = min(max(round(focal[0] * W - w / 2), 0), W - w)
    y = min(max(round(focal[1] * H - h / 2), 0), H - h)
    return im.crop((x, y, x + w, y + h))


def encode(im, budget):
    """Highest quality WebP under budget; shrink 10% at a time if needed."""
    scale = 1.0
    while True:
        size = (round(im.width * scale), round(im.height * scale))
        r = im if scale == 1.0 else im.resize(size, Image.LANCZOS)
        for q in range(86, 59, -4):
            buf = io.BytesIO()
            r.save(buf, "WEBP", quality=q, method=6)
            if buf.tell() <= budget:
                return buf.getvalue(), r.size, q
        scale *= 0.9


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="/tmp/showcase-px/src")
    ap.add_argument("only", nargs="*", help="rebuild only these files")
    a = ap.parse_args()
    unknown = set(a.only) - set(IMAGES)
    if unknown:
        sys.exit(f"unknown image(s): {', '.join(sorted(unknown))}")
    os.makedirs(a.cache, exist_ok=True)
    for name, (pid, focal, *opts) in IMAGES.items():
        if a.only and name not in a.only:
            continue
        w, h = SPECS[name][:2]
        src = Image.open(fetch(pid, a.cache, 2600 if w > 2400 else 2400)).convert("RGB")
        if "flip" in opts:
            src = src.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        im = crop(src, (w, h), focal)
        tw = min(w, MAX_W)
        if im.width > tw:
            im = im.resize((tw, round(tw * h / w)), Image.LANCZOS)
        data, size, q = encode(im, HERO_BUDGET if name in HEROES else BUDGET)
        (OUT / name).write_bytes(data)
        print(f"{name:28} {size[0]}x{size[1]}  q{q}  {len(data) // 1024} KB  (pexels {pid})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Responsive variants: imgs/<W>/<name> is imgs/<name> downscaled to W px wide.

Pages opt in per <img> with srcset="imgs/720/x.webp 720w, imgs/x.webp 1400w" + sizes;
src stays the full-size file (the lightbox and personalize.js read src). There is no
list of variants: whatever a srcset references under imgs/<digits>/ is one.

    build()     write every referenced variant from its full-size file (make_images.py and
                _make_placeholders.py call this last, so variants never outlive a photo swap)
    problems()  what check_pages.py fails on (missing/stale variant, w descriptor wider than its file,
                no sizes, weight)
"""
import io
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from PIL import Image, ImageChops, ImageStat

import _sitelib as site

IMGS = site.PUBLIC / "imgs"
VARIANT_BUDGET = 60_000    # a 720 px card photo; the full-size files are ~80-190 KB
FULL_BUDGET = 200_000      # make_images.py aims at 180 KB; timeline-hero is 193 KB
QUALITY = 80
STALE_DIFF = 8.0           # mean |grey diff| 0..255 at 32 px; same photo re-encoded ~1, another photo ~30+


class _Imgs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.imgs = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("img", "source") and a.get("srcset"):
            self.imgs.append(a)

    handle_startendtag = handle_starttag


def _srcsets():
    """(page, attrs, [(file Path, descriptor)]) for every <img>/<source> with a srcset."""
    for page in sorted(site.PUBLIC.rglob("*.html")):
        p = _Imgs()
        p.feed(page.read_text(encoding="utf-8"))
        for a in p.imgs:
            cands = []
            for part in a["srcset"].split(","):
                bits = part.split()
                if bits:
                    cands.append(((page.parent / urlsplit(bits[0]).path).resolve(), bits[1] if len(bits) > 1 else ""))
            yield page, a, cands


def _base_of(f: Path):
    """imgs/720/x.webp -> (imgs/x.webp, 720); None for anything else."""
    if f.parent.parent == IMGS.resolve() and f.parent.name.isdigit():
        return IMGS / f.name, int(f.parent.name)
    return None


def variants():
    seen = {}
    for _, _, cands in _srcsets():
        for f, _ in cands:
            b = _base_of(f)
            if b:
                seen[f] = b
    return seen


def build():
    for f, (base, w) in sorted(variants().items()):
        im = Image.open(base).convert("RGB")
        im = im.resize((w, round(w * im.height / im.width)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=QUALITY, method=6)
        f.parent.mkdir(exist_ok=True)
        f.write_bytes(buf.getvalue())
        print(f"variant {f.relative_to(site.PUBLIC)}  {im.width}x{im.height}  {len(buf.getvalue()) // 1024} KB")


def _thumb(path):
    return Image.open(path).convert("L").resize((32, 32), Image.BILINEAR)


def problems():
    errs, done = [], set()
    rel = lambda p: PurePosixPath(p.relative_to(site.PUBLIC.resolve())).as_posix()
    for page, a, cands in _srcsets():
        where = f"{page.relative_to(site.PUBLIC)}: srcset {a['srcset']!r}"
        if any(d.endswith("w") for _, d in cands) and not a.get("sizes") and "media" not in a:
            errs.append(f"{where} has w descriptors but no sizes (browser assumes 100vw)")
        for f, d in cands:
            if not f.exists():
                errs.append(f"{where}: {f.name} missing (python3 tools/showcase/make_images.py --variants)")
                continue
            w = Image.open(f).width
            # > is a lie the browser trusts (blurry); < is fine (placeholders are wider than the photos)
            if d.endswith("w") and int(d[:-1]) > w:
                errs.append(f"{where}: {rel(f)} is {w} px wide, descriptor says {d}")
            b = _base_of(f)
            if not b or f in done:
                continue
            done.add(f)
            base, want = b
            if w != want:
                errs.append(f"{rel(f)} is {w} px wide, its directory says {want}")
            if f.stat().st_size > VARIANT_BUDGET:
                errs.append(f"{rel(f)}: {f.stat().st_size} bytes > {VARIANT_BUDGET}")
            diff = sum(ImageStat.Stat(ImageChops.difference(_thumb(f), _thumb(base))).mean)
            if diff > STALE_DIFF:
                errs.append(f"{rel(f)} is not {rel(base.resolve())} downscaled (diff {diff:.0f}): "
                            "photo swapped without rebuilding variants (make_images.py --variants)")
    for f in sorted(IMGS.glob("*")):
        if f.suffix in (".webp", ".jpg", ".jpeg", ".png") and f.stat().st_size > FULL_BUDGET:
            errs.append(f"imgs/{f.name}: {f.stat().st_size} bytes > {FULL_BUDGET}")
    return errs

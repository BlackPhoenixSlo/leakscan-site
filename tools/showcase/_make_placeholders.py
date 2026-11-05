#!/usr/bin/env python3
"""Generate labelled placeholder images for the site.

Every image on a freshly-cloned site must be a placeholder, not a leftover
photograph of the previous client. These render as obvious "PLACEHOLDER"
cards with the shot direction printed on them, so nobody can mistake one for
a real photo and ship it.

To finish the site, overwrite the .webp files in site/showcase/imgs/ at the
same filenames and aspect ratios. No HTML changes are needed.

    python3 tools/showcase/_make_placeholders.py          # write placeholders
    python3 tools/showcase/_make_placeholders.py --list   # just print the list

Showcase adaptation: the demo creator is fictional, so no shot may show an
identifiable face. Every direction below asks for hands, work, studio or
place. The real images are made by make_images.py (Pexels, see CREDITS.md).

The *list* of images is read from the site, not kept here: this script asks
_sitelib which images the pages actually reference. Delete a page and its
placeholder stops being generated. Reference an image with no entry in SPECS
below and this script stops with an error naming it, rather than quietly
leaving you an image nobody shot. Only the editorial part — what the picture
should be — lives in this file, because nothing can derive that.
"""
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import _sitelib as site
import _variants

OUT = site.PUBLIC / "imgs"
CSS = site.PUBLIC / "css" / "base.css"

# Referenced images that are not photographs and need no placeholder.
NOT_A_PHOTO = {"favicon.png", "favicon.svg"}

BLOG_DIRECTION = (
    "16:9 article header. Any on-brand SFW image — it appears at the top of the "
    "post and as the social share card when the post is shared."
)

# filename -> (width, height, label, shot direction)
# Dimensions are the design intent; the width/height attributes in the HTML
# must match them, which check_pages.py verifies.
SPECS = {
    # --- Hero / identity -------------------------------------------------
    "portrait.webp": (2400, 3200, "HERO PORTRAIT",
        "Vertical 3:4. Her at work, face in frame. Subject high in frame with headroom — "
        "the nav sits over the top. Natural light. This is the mobile hero."),
    "hero-wide.webp": (2560, 1440, "HERO — WIDE",
        "16:9 desktop hero. COMPOSE WITH THE SUBJECT ON THE RIGHT THIRD and open space "
        "on the left — the headline sits in that negative space. Her at work."),
    "headshot.webp": (480, 480, "AVATAR — SQUARE",
        "1:1. Crops to a circle on the links page (shown at most 110px wide, so 480 "
        "covers 3x screens). Top-down wheel shot, centred."),
    "og.webp": (1200, 630, "SOCIAL SHARE CARD",
        "1200x630 exactly. This is what renders in every link preview on X, Discord, "
        "iMessage. Subject off-centre, leave room — platforms crop the edges."),
    "studio-portrait.webp": (2400, 3200, "SECOND PORTRAIT",
        "3:4. Used in the homepage About teaser. Different look/setting from the hero."),

    # --- Gallery ---------------------------------------------------------
    "editorial-01.webp": (1400, 2100, "GALLERY 01",
        "2:3 portrait. Clothed/editorial. The most on-brand look for this client."),
    "editorial-02.webp": (1400, 2100, "GALLERY 02",
        "2:3 portrait. Second look — different outfit and location from 01."),
    "editorial-03.webp": (1400, 2100, "GALLERY 03", "2:3 portrait. Third look."),
    "editorial-04.webp": (1400, 2100, "GALLERY 04", "2:3 portrait. Fourth look."),
    "outdoors.webp": (1400, 2100, "OUTDOORS / LANDSCAPE",
        "2:3. Her somewhere recognisably tied to where she is from. "
        "The single most on-brand shot on the list."),
    "behind-the-scenes.webp": (1400, 2100, "BEHIND THE SCENES",
        "2:3. The unglamorous reality of shooting content — phone on a tripod, ring light. "
        "SFW and deliberately un-posed."),

    # --- Page heroes. Named for the page they appear on. ------------------
    "about-hero.webp": (2400, 1350, "PAGE HERO — ABOUT",
        "16:9 banner. Sits behind the 'About' page title with a dark overlay, "
        "so mid-tones work better than a bright shot."),
    "timeline-hero.webp": (2400, 1350, "PAGE HERO — TIMELINE",
        "16:9 banner. Behind the timeline page title, dark overlay."),
    "verify-hero.webp": (2400, 1350, "PAGE HERO — VERIFY",
        "16:9 banner. Behind the account-verification page title, dark overlay."),

    # --- Blog headers ----------------------------------------------------
    "blog-why-this-site.webp": (1920, 1080, "BLOG — WHY THIS SITE EXISTS", BLOG_DIRECTION),
    "blog-impersonators.webp": (1920, 1080, "BLOG — IMPERSONATORS", BLOG_DIRECTION),
    "blog-where-to-find-me.webp": (1920, 1080, "BLOG — WHERE TO ACTUALLY FIND ME", BLOG_DIRECTION),
}


def css_var(name):
    """Read a hex value straight out of base.css's :root block, so the
    placeholder palette can never drift from the site's actual theme."""
    m = re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{3,6}});", CSS.read_text(encoding="utf-8"))
    if not m:
        raise ValueError(f"--{name} not found in {CSS}")
    return m.group(1)


FONT      = "Helvetica-Bold"
FONT_BODY = "Helvetica"


def palette():
    """The six colours a placeholder is drawn in, read at call time.

    Deliberately not module-level constants: check_pages.py imports SPECS
    from here for image dimensions, and computing the palette on import made
    that check die with a bare traceback whenever base.css was mid-edit.
    Editorial data should cost nothing to import.
    """
    return {name: css_var(name) for name in
            ("surface", "surface-2", "border", "text", "text-muted", "accent")}


def card(path, w, h, label, direction, colors):
    """One placeholder: dark panel, accent rule, label, wrapped shot direction."""
    scale = min(w, h) / 1000
    pad = int(min(w, h) * 0.07)
    lab_pt = max(20, int(min(w, h) * 0.052))
    dir_pt = max(14, int(min(w, h) * 0.030))
    dim_pt = max(12, int(min(w, h) * 0.026))
    wrap_at = max(24, int(w / (dir_pt * 0.56)))
    body = "\n".join(textwrap.wrap(direction, wrap_at))

    # Vertical rhythm, all keyed off the accent rule. Each baseline is placed
    # a full em clear of its neighbour so nothing collides at any aspect ratio.
    x = pad * 2
    rule_y = int(h * 0.46)
    rule_h = max(3, int(6 * scale))
    label_base = rule_y - int(lab_pt * 0.45)
    eyebrow_base = label_base - int(lab_pt * 1.15)
    body_base = rule_y + rule_h + int(dir_pt * 2.0)

    BG, PANEL = colors["surface"], colors["surface-2"]
    BORDER, TEXT = colors["border"], colors["text"]
    MUTED, ACCENT = colors["text-muted"], colors["accent"]

    cmd = [
        "magick", "-size", f"{w}x{h}", f"xc:{BG}",
        # inner panel
        "-fill", PANEL, "-stroke", BORDER, "-strokewidth", str(max(2, int(3 * scale))),
        "-draw", f"rectangle {pad},{pad} {w-pad},{h-pad}",
        # accent rule under the label
        "-stroke", "none", "-fill", ACCENT,
        "-draw", f"rectangle {x},{rule_y} {x + int(w*0.14)},{rule_y + rule_h}",
        # "PLACEHOLDER" eyebrow
        "-font", FONT, "-pointsize", str(dim_pt), "-fill", ACCENT,
        "-annotate", f"+{x}+{eyebrow_base}", "PLACEHOLDER — REPLACE",
        # label
        "-font", FONT, "-pointsize", str(lab_pt), "-fill", TEXT,
        "-annotate", f"+{x}+{label_base}", label,
        # shot direction
        "-font", FONT_BODY, "-pointsize", str(dir_pt), "-fill", MUTED,
        "-interline-spacing", str(int(dir_pt * 0.45)),
        "-annotate", f"+{x}+{body_base}", body,
        # dimensions, bottom-left
        "-font", FONT_BODY, "-pointsize", str(dim_pt), "-fill", BORDER,
        "-annotate", f"+{x}+{h-pad*2}", f"{w} x {h}",
        "-quality", "82", str(path),
    ]
    subprocess.run(cmd, check=True)


def main() -> int:
    site.require_public()
    listing = "--list" in sys.argv
    wanted = [n for n in (Path(rel).name for rel in site.referenced_images())
              if n not in NOT_A_PHOTO]

    unknown = [n for n in wanted if n not in SPECS]
    if unknown:
        print("The site references images with no entry in SPECS:", file=sys.stderr)
        for n in unknown:
            print(f"    {n}", file=sys.stderr)
        print("\nAdd a (width, height, label, shot direction) for each, so whoever\n"
              "shoots the photo knows what it is for.", file=sys.stderr)
        return 1

    if listing:
        for name in wanted:
            w, h, label, _ = SPECS[name]
            print(f"{name}  {w}x{h}  {label}")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    colors = palette()
    for name in wanted:
        card(OUT / name, *SPECS[name], colors)
    _variants.build()  # imgs/<W>/ copies follow the placeholders, never the old photos

    unused = sorted(set(SPECS) - set(wanted))
    print(f"Wrote {len(wanted)} placeholders to {OUT}")
    if unused:
        print(f"({len(unused)} spec(s) unused by this client: {', '.join(unused)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

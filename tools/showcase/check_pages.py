#!/usr/bin/env python3
"""Assert the page set is stated consistently everywhere it is stated.

Deleting or adding a page means editing the nav, the footer and the
SiteNavigationElement list in index.html's JSON-LD. NEW_CLIENT.md used to ask a human to remember all of them. This is that checklist as a program, for the
same reason _check_accounts.py exists: "N places must agree on one list" is a
machine's job, and the failure is invisible in a browser — the page looks fine
while Google reads a nav that no longer matches the site.

    python3 tools/showcase/check_pages.py

Showcase adaptation: no sitemap.xml and no netlify.toml ship with the
showcase, so those two legs are gone. Two showcase-only rules replace them:
every page is <meta name="robots" content="noindex, nofollow"> (the demo must
not rank), and every page carries the demo ribbon linking back to the
LeakScan landing page one level above site/showcase/. Every page also has
exactly one <h1> and no skipped heading levels (h2 -> h4). A page using
[data-fade] sets html.js in an inline <head> script, and the CSS hides
[data-fade] only under .js, so the content shows with JS off or main.js down.

Silent and exit 0 when every statement of the page set agrees.

Everything here reads the page through a parser — the HTML through Page below,
the JSON-LD and the sitemap through _sitelib. Nothing pattern-matches markup:
a regex cannot tell that a tag sits inside an HTML comment, so commenting out
an <img> used to make this script report a dimension mismatch on a tag the
browser never renders.

This deliberately compares link *sets*, not bytes. The homepage footer carries
an extra social-icon strip and 404.html uses root-relative links; neither is
drift, and a byte comparison would flag both while missing an actual missing
page.
"""

import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import _sitelib as site
from _make_placeholders import SPECS

# Pages that legitimately do not carry the site chrome.
NO_CHROME: set[str] = set()

ROBOTS = "noindex, nofollow"
RIBBON_CLASS = "demo-ribbon"


class Page(HTMLParser):
    """One pass over a page: its chrome links, every link, every sized image.

    Three checks used to ask three different questions of the same file with
    three different regexes. They ask this instead.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nav: list[str] = []
        self.footer: list[str] = []
        self.links: list[str] = []
        self.images: list[tuple[str, int, int]] = []
        self.has_footer = False
        self.robots: list[str] = []
        self.ribbon: list[str] = []
        self.headings: list[int] = []
        self.fades = False
        self.js_flag = False
        self._inline_script = False
        self._depth = {"nav": 0, "footer": 0}
        self._ribbon_tag: str | None = None
        self._ribbon_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._depth:
            self._depth[tag] += 1
            self.has_footer |= tag == "footer"
        a = dict(attrs)
        self.fades |= "data-fade" in a
        self._inline_script = tag == "script" and "src" not in a

        if len(tag) == 2 and tag[0] == "h" and tag[1] in "123456":
            self.headings.append(int(tag[1]))

        if tag == "meta" and (a.get("name") or "").lower() == "robots":
            self.robots.append((a.get("content") or "").strip())

        # The demo ribbon: links inside the element carrying RIBBON_CLASS.
        if self._ribbon_tag:
            if tag == self._ribbon_tag:
                self._ribbon_depth += 1
            if tag == "a" and a.get("href"):
                self.ribbon.append(a["href"])
        elif RIBBON_CLASS in (a.get("class") or "").split():
            self._ribbon_tag, self._ribbon_depth = tag, 1

        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
            if self._depth["nav"]:
                self.nav.append(a["href"])
            elif self._depth["footer"]:
                self.footer.append(a["href"])

        if tag == "img" and a.get("src") and a.get("width") and a.get("height"):
            try:
                self.images.append(
                    (Path(urlsplit(a["src"]).path).name,
                     int(a["width"]), int(a["height"])))
            except ValueError:
                pass  # a non-numeric width is an HTML defect, not page drift

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in self._depth and self._depth[tag]:
            self._depth[tag] -= 1

    def handle_data(self, data):
        if self._inline_script and "classList.add('js')" in data:
            self.js_flag = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._inline_script = False
        if tag in self._depth and self._depth[tag]:
            self._depth[tag] -= 1
        if self._ribbon_tag == tag:
            self._ribbon_depth -= 1
            if not self._ribbon_depth:
                self._ribbon_tag = None


def read(path: Path) -> Page:
    parser = Page()
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    parser.close()
    return parser


def normalise(href: str, page: Path) -> str | None:
    """A link's target as a path relative to public/, or None if external.

    Blog posts link with ../, 404.html links with /, everything else links
    bare. All three name the same page and must compare equal.
    """
    target = site.resolve(href, page, site.site_domain())
    if target is None:
        return None
    return target.relative_to(site.PUBLIC).as_posix()


def paths_of(hrefs, page: Path) -> set[str]:
    return {n for n in (normalise(h, page) for h in hrefs) if n}


def pages():
    for path in site.site_files():
        if path.suffix != ".html":
            continue
        rel = path.relative_to(site.PUBLIC).as_posix()
        if rel in NO_CHROME:
            continue
        yield rel, path


def json_ld(path: Path, errors: list[str]):
    """Parsed JSON-LD, or a named failure. Broken structured data is
    check_ready.py's finding; this script must still say which file it choked
    on rather than ending in a traceback."""
    try:
        return site.ld_blocks(path)
    except json.JSONDecodeError as e:
        rel = path.relative_to(site.PUBLIC).as_posix()
        errors.append(f"{rel}: JSON-LD will not parse ({e}) — see check_ready.py")
        return []


def check_chrome(parsed, paths):
    """Every page must state the same nav and the same footer as index.html."""
    errors, sets = [], {"nav": {}, "footer": {}}
    for rel, page in parsed.items():
        if not page.nav:
            errors.append(f"{rel} has no <nav> links")
        if not page.has_footer:
            errors.append(f"{rel} has no <footer> — every page carries the site footer")
        # A footer with no links (404.html keeps a bare copyright line) is a
        # deliberate variant, not drift. Only pages that state the page set
        # are compared against each other.
        sets["nav"][rel] = paths_of(page.nav, paths[rel])
        sets["footer"][rel] = paths_of(page.footer, paths[rel])

    agreed = {}
    for label, by_page in sets.items():
        present = {r: s for r, s in by_page.items() if s}
        canonical = present.get("index.html")
        if canonical is None:
            # index.html defines the page set. Falling back to some other page
            # would silently measure the whole site against an arbitrary one.
            if present:
                errors.append(f"index.html states no {label} — it defines the page set")
            agreed[label] = set()
            continue
        for rel, s in sorted(present.items()):
            for missing in sorted(canonical - s):
                errors.append(f"{label}: {rel} is missing {missing}")
            for extra in sorted(s - canonical):
                errors.append(f"{label}: {rel} has {extra}, which index.html does not")
        agreed[label] = canonical
    return errors, agreed["nav"], agreed["footer"]


def check_ld_nav(index, nav_set):
    """The JSON-LD SiteNavigationElement list must be the nav."""
    errors = []
    urls = [n["url"] for n in site.ld_find(json_ld(index, errors), "SiteNavigationElement")
            if n.get("url")]
    ld = paths_of(urls, index)
    errors += [f"index.html SiteNavigationElement is missing {r}"
               for r in sorted(nav_set - ld)]
    errors += [f"index.html SiteNavigationElement claims {r}, not in the nav"
               for r in sorted(ld - nav_set)]
    return errors


def check_blog(parsed):
    """Every blog post file must be both listed in the ItemList and carded."""
    blog_dir = site.PUBLIC / "blog"
    blog = site.PUBLIC / "blog.html"
    posts = {p.relative_to(site.PUBLIC).as_posix()
             for p in blog_dir.glob("post-*.html")} if blog_dir.is_dir() else set()
    if not posts or not blog.exists():
        return []
    errors = []
    items = [i["url"] for lst in site.ld_find(json_ld(blog, errors), "ItemList")
             for i in lst.get("itemListElement", []) if i.get("url")]
    listed = paths_of(items, blog)
    carded = paths_of(parsed["blog.html"].links, blog)
    errors += [f"blog.html ItemList does not include {r}" for r in sorted(posts - listed)]
    errors += [f"blog.html has no card linking to {r}" for r in sorted(posts - carded)]
    return errors


def check_showcase(parsed, paths):
    """Showcase-only rules: noindex, one h1 + no level skips, ribbon back to LeakScan.

    The ribbon's back link must resolve to the landing page's own index.html
    (the directory above site/showcase/), from either depth — `../` on root
    pages, `../../` from blog/ posts.
    """
    errors = []
    landing = (site.PUBLIC.parent / "index.html").resolve()
    for rel, page in sorted(parsed.items()):
        if page.robots != [ROBOTS]:
            errors.append(f"{rel}: robots meta is {page.robots or 'missing'}, "
                          f"must be exactly one '{ROBOTS}'")
        if page.headings.count(1) != 1:
            errors.append(f"{rel}: {page.headings.count(1)} <h1> elements (want exactly 1)")
        for prev, cur in zip([0] + page.headings, page.headings):
            if cur > prev + 1:
                errors.append(f"{rel}: heading skips h{prev} -> h{cur}" if prev
                              else f"{rel}: first heading is h{cur}, not h1")
                break
        if page.fades and not page.js_flag:
            errors.append(f"{rel}: uses [data-fade] but no inline "
                          f"document.documentElement.classList.add('js') script")
        if not page.ribbon:
            errors.append(f"{rel}: no demo ribbon (class=\"{RIBBON_CLASS}\") with a link")
            continue
        back = []
        for href in page.ribbon:
            p = urlsplit(href).path
            if p and not urlsplit(href).scheme and not p.startswith("/"):
                t = paths[rel].parent / p
                back.append((t / "index.html" if p.endswith("/") else t).resolve())
        if landing not in back:
            errors.append(f"{rel}: demo ribbon does not link back to the LeakScan "
                          f"landing ({', '.join(page.ribbon)})")
    return errors


def check_fade_css():
    """Every CSS rule hiding [data-fade] must be scoped under .js (see docstring)."""
    import re
    errors = []
    for css in sorted((site.PUBLIC / "css").glob("*.css")):
        text = re.sub(r"/\*.*?\*/", "", css.read_text(encoding="utf-8"), flags=re.S)
        for sel in re.findall(r"([^{}]+)\{", text):
            for part in sel.split(","):
                part = part.strip()
                if "[data-fade]" in part and not part.startswith(".js "):
                    errors.append(f"css/{css.name}: '{part}' not scoped under .js "
                                  f"(content invisible without JS)")
    return errors


def check_image_dims(parsed):
    """A declared width/height must match the placeholder it was designed for."""
    return [
        f"{rel}: <img {name}> declares {w}x{h}, "
        f"but _make_placeholders.py specifies {SPECS[name][0]}x{SPECS[name][1]}"
        for rel, page in parsed.items()
        for name, w, h in page.images
        if name in SPECS and (w, h) != SPECS[name][:2]
    ]


def main() -> int:
    site.require_public()
    paths = dict(pages())
    parsed = {rel: read(path) for rel, path in paths.items()}

    errors, nav_set, footer_set = check_chrome(parsed, paths)
    errors += check_ld_nav(site.PUBLIC / "index.html", nav_set)
    errors += check_blog(parsed)
    errors += check_image_dims(parsed)
    errors += check_showcase(parsed, paths)
    errors += check_fade_css()

    for e in errors:
        print(f"FAIL  {e}")
    if errors:
        print(f"\n{len(errors)} inconsistency(ies).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""One model of the site, shared by every check and generator.

There is exactly one interesting question about this site — *which files does
it actually reference?* — and it used to be answered in three places: by regex
in check_deploy.py, by a hand-maintained list in _make_placeholders.py, and by
a checklist in NEW_CLIENT.md. They drifted, which is how five orphaned blog
images and a placeholder labelled for a page that does not exist got shipped.
Everything that needs that answer now imports it from here.

The extractors parse each format properly rather than pattern-matching text.
That is not tidiness: a regex over raw HTML cannot see that a tag is inside a
comment, so commenting out an <img> while leaving the file on disk used to
keep that file "referenced" and let it deploy unnoticed. Commenting a tag out
is the ordinary way a human removes an image, and it is exactly how the zane
branch came to carry the previous client's photographs.

There is deliberately no JavaScript extractor. A quoted string in a .js file
looks like a path but is usually a comparison, not a link: main.js matches
location against 'blog.html' to highlight the nav, and reading that as a
reference made deleting the blog — which NEW_CLIENT.md tells you to do —
fail the deploy gate with a broken link that does not exist. An asset a
script really does load shows up as an unreferenced file instead, which
fails in the safe direction and has an escape hatch in deploy-allowlist.txt.
"""

import re
import sys
import json
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, unquote
from xml.etree import ElementTree

# Showcase adaptation: the template's public/ is site/showcase/ of the
# leakscan-site repo, served under /leakscan-site/showcase/ on GitHub Pages.
TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent.parent
PUBLIC = ROOT / "site" / "showcase"

# An unsubstituted template placeholder is not a broken reference — the file it
# names does not exist yet by design. check_ready.py is what reports these.
TOKEN = re.compile(r"\{\{[A-Z0-9_]+\}\}")

SHIPPABLE_EXT = (
    "html|htm|css|js|xml|txt|json|webmanifest|"
    "webp|jpg|jpeg|png|svg|gif|ico|avif|"
    "mp4|mov|webm|pdf|woff2?"
)
HAS_EXT = re.compile(rf"\.(?:{SHIPPABLE_EXT})$", re.I)

CSS_URL = re.compile(r"""url\(\s*['"]?([^'")]+)['"]?\s*\)""", re.I)
QUOTED_PATH = re.compile(rf"""["']((?:https?:)?//?[^"'\s]+|[^"'\s]+\.(?:{SHIPPABLE_EXT}))["']""", re.I)
BARE_URL = re.compile(r"""https?://[^\s"'<>)]+""")

# Attributes that can name a shipped file.
REF_ATTRS = ("href", "src", "poster", "action", "data-src")
# <meta content="..."> is a reference only for these keys. Every other meta tag
# holds prose, and reading a description as a path produces pure noise.
META_REF_KEYS = {"og:image", "og:url", "og:image:secure_url", "twitter:image"}

# Host configuration, not content. These name paths (robots.txt Disallow,
# _headers rules) precisely for files that are *meant* to be unlinked, so
# counting them as references would exempt the very files worth catching.
# They are still text that ships, and still carry tokens — see text_files().
CONFIG_FILES = {"robots.txt", "_headers", "_redirects"}

# Every shipped file a human writes into. Deliberately wider than EXTRACTORS:
# "which files declare references" and "which files can hold an unsubstituted
# token" are different questions, and check_ready.py needs the second one —
# base.css shipped a live {{BRAND_NAME}} while the gate only read .html/.xml.
TEXT_EXT = {".html", ".htm", ".css", ".js", ".xml", ".txt", ".json",
            ".webmanifest", ".svg"}


class _HTMLRefs(HTMLParser):
    """Collect every local path an HTML document points at.

    Comments never reach handle_data or handle_starttag, so commented-out
    markup contributes nothing — which is the whole reason this is a parser
    and not a regex.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.refs: list[str] = []
        self._in: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._in = tag
        a = {k.lower(): (v or "") for k, v in attrs}

        for name in REF_ATTRS:
            if a.get(name):
                self.refs.append(a[name])

        # srcset is a comma-separated list of "url 2x" descriptors.
        for part in a.get("srcset", "").split(","):
            head = part.strip().split()
            if head:
                self.refs.append(head[0])

        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key in META_REF_KEYS and a.get("content"):
                self.refs.append(a["content"])

        if a.get("style"):
            self.refs += CSS_URL.findall(a["style"])

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in ("script", "style"):
            self._in = None

    def handle_endtag(self, tag):
        if tag == self._in:
            self._in = None

    def handle_data(self, data):
        if self._in == "style":
            self.refs += CSS_URL.findall(data)
        elif self._in == "script":
            # JSON-LD and inline JS: only accept things already shaped like a
            # path or URL, so page copy sitting in a JSON string stays out.
            self.refs += QUOTED_PATH.findall(data)


def _refs_html(text):
    parser = _HTMLRefs()
    parser.feed(text)
    parser.close()
    return parser.refs


def _refs_css(text):
    return CSS_URL.findall(re.sub(r"/\*.*?\*/", " ", text, flags=re.S))


def _refs_xml(text):
    """sitemap.xml / feed.xml. Element text for <loc>/<link>/<guid>, plus href
    attributes (RSS carries its self-link as an atom:link)."""
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        # Malformed XML is reported by check_ready.py; fall back to something
        # rather than silently contributing no references at all.
        return BARE_URL.findall(text)
    out = []
    for el in root.iter():
        name = el.tag.rsplit("}", 1)[-1].lower()
        if name in ("loc", "link", "guid", "url") and (el.text or "").strip():
            out.append(el.text.strip())
        for attr in ("href", "src", "url"):
            if el.get(attr):
                out.append(el.get(attr))
    return out


def _refs_plain(text):
    return BARE_URL.findall(text)


EXTRACTORS = {
    ".html": _refs_html,
    ".htm": _refs_html,
    ".css": _refs_css,
    ".xml": _refs_xml,
    ".svg": _refs_xml,      # SVG is XML; an <image href> in a logo is a real reference
    ".txt": _refs_plain,
}


def site_files():
    """Every file that would be served, in stable order."""
    for path in sorted(PUBLIC.rglob("*")):
        if path.is_file() and path.name != ".DS_Store":
            yield path


def content_files():
    """Files whose references count. Host configuration is excluded."""
    for path in site_files():
        if path.name in CONFIG_FILES:
            continue
        if path.suffix.lower() in EXTRACTORS:
            yield path


def text_files():
    """Every shipped file a human writes into, config included.

    This is what check_ready.py reads. It is not content_files(): robots.txt
    declares no references but does carry {{SITE_DOMAIN}}, and a stylesheet
    carries neither yet must still be checked for unfilled tokens.
    """
    for path in site_files():
        if path.suffix.lower() in TEXT_EXT or path.name in CONFIG_FILES:
            yield path


@lru_cache(maxsize=None)
def _canonical():
    """(host, base path) of index.html's canonical URL, or (None, "/") before
    {{SITE_DOMAIN}} is filled in. The showcase lives in a subfolder, so the
    base path ("/leakscan-site/showcase/") matters as much as the host."""
    index = PUBLIC / "index.html"
    if not index.exists():
        return None, "/"
    m = re.search(
        r"""rel=["']canonical["']\s+href=["']?https?://([^/"'\s>]+)(/[^"'\s>]*)?""",
        index.read_text(encoding="utf-8", errors="ignore"),
    )
    if not m or TOKEN.search(m.group(0)):
        return None, "/"
    base = m.group(2) or "/"
    return m.group(1).replace("www.", ""), base if base.endswith("/") else base + "/"


def site_domain():
    """The canonical host, read out of the site itself. None before
    {{SITE_DOMAIN}} has been filled in."""
    return _canonical()[0]


def site_base():
    """The path the site is served under, e.g. "/leakscan-site/showcase/"."""
    return _canonical()[1]


# Marks a root-relative reference ("/about.html"). Under a subfolder it points
# at the landing site, not at the showcase, so it is reported as broken.
ROOT_RELATIVE = PUBLIC / "__root-relative__"


def references(path: Path):
    """Raw reference strings in one file."""
    extract = EXTRACTORS.get(path.suffix.lower())
    if not extract:
        return []
    return extract(path.read_text(encoding="utf-8", errors="ignore"))


def resolve(ref: str, from_file: Path, domain: str | None):
    """Map one reference onto a path under public/, or None if it is not a
    local file: external host, anchor, mailto:, or an unfilled token."""
    ref = ref.strip()
    if not ref or ref.startswith(("#", "data:", "mailto:", "tel:", "javascript:", "//")):
        return None

    parts = urlsplit(ref)
    base = site_base()
    if parts.scheme or parts.netloc:
        # Absolute URL. Only a first-party one under the showcase base path
        # names a file we ship — the landing page on the same host is not
        # ours. On an unfilled template the host is still {{SITE_DOMAIN}}.
        host = parts.netloc.replace("www.", "")
        path = "/" + unquote(parts.path).lstrip("/")
        if TOKEN.search(host):
            pass
        elif domain and host == domain and (path + "/").startswith(base):
            path = "/" + path[len(base):] if len(path) >= len(base) else "/"
        else:
            return None
        rooted = True
    else:
        path = unquote(parts.path)
        rooted = False
    if not path:
        return None
    # A token inside the path names a file that does not exist yet by design.
    # check_ready.py is what reports these.
    if TOKEN.search(path):
        return None

    if rooted:
        target = PUBLIC / path.lstrip("/")
    elif path.startswith("/"):
        # Root-relative: fine on a site at the domain root, wrong under
        # /showcase/. Resolve the showcase's own base path, flag the rest.
        if base != "/" and path.startswith(base):
            target = PUBLIC / path[len(base):]
        else:
            return ROOT_RELATIVE / path.lstrip("/")
    else:
        target = from_file.parent / path
    if path.endswith("/"):
        target = target / "index.html"

    target = Path(target).resolve()
    # A reference that climbs out of public/ is not a shipped file.
    try:
        target.relative_to(PUBLIC)
    except ValueError:
        return None
    return target


def scan():
    """Walk the site once.

    Returns (referenced, broken) where `referenced` is the set of resolved
    paths under public/ that some content file points at, and `broken` is a
    list of (source, ref, target) for references that resolve nowhere.
    """
    domain = site_domain()
    referenced: set[Path] = set()
    broken: list[tuple[Path, str, Path]] = []
    for path in content_files():
        for ref in references(path):
            target = resolve(ref, path, domain)
            if target is None:
                continue
            if target.exists():
                referenced.add(target)
            else:
                broken.append((path, ref, target))
    return referenced, broken


def referenced_images():
    """Relative names of every image under imgs/ that the site references.

    _make_placeholders.py builds from this rather than its own list, so a page
    deleted from the site stops generating a placeholder automatically.
    """
    referenced, _ = scan()
    return sorted(
        p.relative_to(PUBLIC).as_posix()
        for p in referenced
        if p.parent == PUBLIC / "imgs"
    )


class _LDScripts(HTMLParser):
    """The raw text of every <script type="application/ld+json"> in a page.

    A parser, not a regex, for the same reason as everything else here: a
    commented-out JSON-LD block must not count as one the page publishes.
    """

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.blocks: list[str] = []
        self._collecting = False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        self._collecting = (
            tag == "script" and a.get("type", "").lower() == "application/ld+json"
        )

    def handle_endtag(self, tag):
        if tag == "script":
            self._collecting = False

    def handle_data(self, data):
        if self._collecting and data.strip():
            self.blocks.append(data)


def ld_blocks(path: Path):
    """Every parsed application/ld+json block in a page.

    Raises json.JSONDecodeError on malformed JSON — including on a template
    that has not been filled in yet, which is the point.

    Every {{TOKEN}} in this site's structured data sits inside a string
    literal, so an unfilled block is still valid JSON and parses with its
    tokens intact. Keep it that way: a token in raw value position would
    need this function to repair the JSON before reading it, and a template
    that asks an operator to hand-write JSON syntax will eventually get it
    wrong. Use several string tokens instead of one that expands to markup.
    """
    parser = _LDScripts()
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    parser.close()
    return [json.loads(b) for b in parser.blocks]


def ld_find(blocks, type_name: str):
    """Every node of one @type anywhere in a page's JSON-LD, at any depth."""
    out = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("@type") == type_name:
                out.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(blocks)
    return out


def require_public():
    if not PUBLIC.is_dir():
        sys.exit(f"{PUBLIC} does not exist")

#!/usr/bin/env python3
"""Gate for site/. Silent + exit 0 when green; prints each problem + exit 1 otherwise.

Checks every HTML file under site/ (except site/showcase/**):
- local href/src/srcset/poster targets exist (pages under site/showcase/ have their own gates in tools/showcase/)
- absolute URLs under SITE_URL resolve to local files too; no leading-slash internal links
- no third-party resource loads (scripts, styles, images, frames, icons)
- #fragment links point at an existing id
- <html lang>, viewport meta, <title>, meta description, og:title/description/image, twitter:card
- <title> <= 65 chars, meta description <= 160 chars (longer gets cut in Google results)
- every CTA (<a> with class btn/channel/mobile-cta) to Telegram/WhatsApp prefills a message (text=), mailto has body=
- exactly one <h1>, no duplicate ids, every <img> has alt + width + height
- every <iframe> has a title and tabindex="-1" (keeps the embedded demo's ~35 links out of the landing page's Tab
  order; the link next to it is the keyboard route)
- every JSON-LD block parses; FAQPage Q&A text equals the visible <details> FAQ
- indexable page (no robots noindex) has canonical == SITE_URL + path (and og:url, if present, equal)
- sitemap.xml lists exactly the indexable pages; robots.txt Sitemap line points at it
- no `{{` in any shipped text file
- every file under site/assets, site/css, site/js is referenced by some page
- every raster (.png/.jpg/.webp) under site/ (except showcase/) is <= RASTER_BUDGET bytes
- every third-party host site/showcase/** loads is in DISCLOSED and privacy.html names it (the homepage iframes the
  demo, so its loads are the landing site's too); privacy.html names no host the demo no longer loads
"""
import json, pathlib, re, sys
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, unquote

SITE_URL = "https://blackphoenixslo.github.io/leakscan-site/"

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
MUST_BE_REFERENCED = ("assets", "css", "js")
TEXT_EXT = {".html", ".css", ".js", ".xml", ".txt", ".svg", ".json", ".webmanifest"}
RESOURCE_TAGS = {"script", "img", "iframe", "source", "video", "audio", "embed", "object", "track"}
CTA_CLASSES = {"btn", "channel", "mobile-cta"}
CHAT = ("https://t.me/", "https://wa.me/")
RASTER_BUDGET = 100_000   # og.png re-rendered by make_icons.py is ~165 KB until shrunk (see its docstring)
RASTER_EXT = {".png", ".jpg", ".jpeg", ".webp"}
DISCLOSED = {"fonts.googleapis.com": "Google Fonts", "fonts.gstatic.com": "Google Fonts"}  # host -> privacy.html wording
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

problems = []


def bad(msg):
    problems.append(msg)


def shipped(p):
    rel = p.relative_to(SITE).as_posix()
    return not (rel == "showcase" or rel.startswith("showcase/"))


def page_url(rel):
    """site-relative path of a page -> its public URL."""
    if rel == "index.html":
        return SITE_URL
    if rel.endswith("/index.html"):
        return SITE_URL + rel[: -len("index.html")]
    return SITE_URL + rel


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lang = None
        self.refs = []          # (tag, attr, value)
        self.ids = []
        self.h1 = 0
        self.metas = {}
        self.links = []         # (rel, href)
        self.imgs = []
        self.iframes = []
        self.jsonld = []
        self.title = False
        self.title_text = ""
        self.ctas = []          # (class, href)
        self._in_ld = None
        self._faq = []          # [question, answer]
        self._stack = []
        self._cap = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag not in VOID:
            self._stack.append(tag)
        if tag == "html":
            self.lang = a.get("lang")
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "h1":
            self.h1 += 1
        if tag == "title":
            self.title = True
        if tag == "meta":
            key = a.get("name") or a.get("property")
            if key:
                self.metas.setdefault(key, a.get("content", ""))
        if tag == "link":
            self.links.append(((a.get("rel") or "").lower(), a.get("href")))
        if tag == "img":
            self.imgs.append(a)
        if tag == "iframe":
            self.iframes.append(a)
        if tag == "a" and set((a.get("class") or "").split()) & CTA_CLASSES:
            self.ctas.append((a.get("class"), a.get("href") or ""))
        if tag == "script" and a.get("type") == "application/ld+json":
            self._in_ld = []
        if tag == "details":
            self._faq.append(["", ""])
        if tag == "summary" and self._faq:
            self._cap = 0
        if tag == "p" and self._faq and "details" in self._stack and self._cap is None:
            self._cap = 1
        for k in ("href", "src", "poster", "xlink:href"):
            if a.get(k) is not None:
                self.refs.append((tag, k, a[k], (a.get("rel") or "").lower()))
        if a.get("srcset"):
            for part in a["srcset"].split(","):
                if part.strip():
                    self.refs.append((tag, "srcset", part.split()[0], ""))
        if tag == "meta" and (a.get("content") or "").startswith(SITE_URL):
            self.refs.append((tag, "content", a["content"], ""))

    def handle_endtag(self, tag):
        if self._stack and tag in self._stack:
            while self._stack and self._stack.pop() != tag:
                pass
        if tag == "script" and self._in_ld is not None:
            self.jsonld.append("".join(self._in_ld))
            self._in_ld = None
        if tag in ("summary", "p"):
            self._cap = None

    def handle_data(self, data):
        if self._stack and self._stack[-1] == "title":
            self.title_text += data
        if self._in_ld is not None:
            self._in_ld.append(data)
        if self._cap is not None and self._faq:
            self._faq[-1][self._cap] += data

    @property
    def faq(self):
        return [(" ".join(q.split()), " ".join(a.split())) for q, a in self._faq]


def local_target(page_rel, value):
    """Return (site-relative file path or None, fragment) for a local/own-site URL; None if external."""
    if value.startswith(SITE_URL):
        rest = value[len(SITE_URL):]
        base = SITE_URL
        joined = SITE_URL + rest
    else:
        sp = urlsplit(value)
        if sp.scheme or value.startswith("//"):
            return None
        base = page_url(page_rel)
        joined = urljoin(base, value)
    if not joined.startswith(SITE_URL):
        return ("../outside", "")
    sp = urlsplit(joined)
    path = unquote(sp.path)[len(urlsplit(SITE_URL).path):]
    if path == "" or path.endswith("/"):
        path += "index.html"
    return (path, sp.fragment)


def main():
    pages = sorted(p for p in SITE.rglob("*.html") if shipped(p))
    parsed = {}
    for p in pages:
        rel = p.relative_to(SITE).as_posix()
        pg = Page()
        pg.feed(p.read_text(encoding="utf-8"))
        parsed[rel] = pg

    referenced = set()
    for rel, pg in parsed.items():
        if not pg.lang:
            bad(f"{rel}: <html> has no lang attribute")
        if "viewport" not in pg.metas:
            bad(f"{rel}: no viewport meta")
        if not pg.title:
            bad(f"{rel}: no <title>")
        for m in ("description", "og:title", "og:description", "og:image", "twitter:card"):
            if not pg.metas.get(m):
                bad(f"{rel}: missing meta {m}")
        if len(pg.title_text.strip()) > 65:
            bad(f"{rel}: <title> is {len(pg.title_text.strip())} chars (max 65)")
        if len(pg.metas.get("description", "")) > 160:
            bad(f"{rel}: meta description is {len(pg.metas['description'])} chars (max 160)")
        for cls, href in pg.ctas:
            q = urlsplit(href).query
            if href.startswith(CHAT) and "text=" not in q or href.startswith("mailto:") and "body=" not in q:
                bad(f"{rel}: CTA <a class={cls!r}> {href} has no prefilled message")
        if pg.h1 != 1:
            bad(f"{rel}: {pg.h1} <h1> elements (want exactly 1)")
        seen = set()
        for i in pg.ids:
            if i in seen:
                bad(f"{rel}: duplicate id '{i}'")
            seen.add(i)
        for img in pg.imgs:
            for k in ("alt", "width", "height"):
                if k not in img:
                    bad(f"{rel}: <img src={img.get('src')!r}> has no {k}")
        for fr in pg.iframes:
            if not (fr.get("title") or "").strip():
                bad(f"{rel}: <iframe src={fr.get('src')!r}> has no title")
            if fr.get("tabindex") != "-1":
                bad(f"{rel}: <iframe src={fr.get('src')!r}> needs tabindex=\"-1\" (else Tab walks every link inside it)")
        for block in pg.jsonld:
            try:
                data = json.loads(block)
            except ValueError as e:
                bad(f"{rel}: JSON-LD does not parse: {e}")
                continue
            if isinstance(data, dict) and data.get("@type") == "FAQPage":
                ld = [(q["name"], q["acceptedAnswer"]["text"]) for q in data.get("mainEntity", [])]
                if ld != pg.faq:
                    bad(f"{rel}: FAQPage JSON-LD does not match the visible FAQ")

        for tag, attr, value, linkrel in pg.refs:
            v = value.strip()
            if v.startswith(("mailto:", "tel:", "data:")):
                continue
            if v.startswith("/") and not v.startswith("//"):
                bad(f"{rel}: internal link with leading slash: {v}")
                continue
            if v.startswith("#"):
                if v[1:] and v[1:] not in pg.ids:
                    bad(f"{rel}: #{v[1:]} does not match any id")
                continue
            tgt = local_target(rel, v)
            if tgt is None:
                loads = tag in RESOURCE_TAGS or (tag == "link" and linkrel not in ("canonical", "alternate"))
                if loads and attr != "content":
                    bad(f"{rel}: third-party resource <{tag} {attr}={v}>")
                continue
            path, frag = tgt
            f = SITE / path
            if path.startswith("../") or not f.is_file():
                bad(f"{rel}: broken link {attr}={v}")
                continue
            referenced.add(path)
            if frag and path.endswith(".html") and path in parsed and frag not in parsed[path].ids:
                bad(f"{rel}: {v} points at missing id '{frag}'")

    indexable = {rel for rel, pg in parsed.items() if "noindex" not in pg.metas.get("robots", "")}
    for rel in sorted(indexable):
        pg = parsed[rel]
        canon = [h for r, h in pg.links if "canonical" in r.split()]
        want = page_url(rel)
        if canon != [want]:
            bad(f"{rel}: canonical {canon} != [{want}]")
        if pg.metas.get("og:url") and pg.metas["og:url"] != want:
            bad(f"{rel}: og:url {pg.metas['og:url']} != {want}")

    sm = SITE / "sitemap.xml"
    if not sm.is_file():
        bad("sitemap.xml missing")
    else:
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sm.read_text(encoding="utf-8"))
        want = sorted(page_url(r) for r in indexable)
        if sorted(locs) != want or len(locs) != len(set(locs)):
            bad(f"sitemap.xml lists {sorted(locs)}, want {want}")
    rb = SITE / "robots.txt"
    if not rb.is_file() or f"Sitemap: {SITE_URL}sitemap.xml" not in rb.read_text(encoding="utf-8"):
        bad(f"robots.txt missing or has no 'Sitemap: {SITE_URL}sitemap.xml'")

    for f in sorted(SITE.rglob("*")):
        if not f.is_file() or not shipped(f):
            continue
        rel = f.relative_to(SITE).as_posix()
        if f.suffix in TEXT_EXT and "{{" in f.read_text(encoding="utf-8", errors="replace"):
            bad(f"{rel}: contains '{{{{'")
        if rel.split("/")[0] in MUST_BE_REFERENCED and rel not in referenced:
            bad(f"{rel}: not referenced by any page")
        if f.suffix.lower() in RASTER_EXT and f.stat().st_size > RASTER_BUDGET:
            bad(f"{rel}: {f.stat().st_size} bytes > {RASTER_BUDGET} (shrink it, see tools/make_icons.py)")

    demo_hosts = set()
    for p in sorted((SITE / "showcase").rglob("*.html")):
        pg = Page()
        pg.feed(p.read_text(encoding="utf-8"))
        for tag, attr, value, linkrel in pg.refs:
            u = urlsplit(value.strip())
            loads = tag in RESOURCE_TAGS or (tag == "link" and linkrel not in ("canonical", "alternate"))
            if loads and attr != "content" and u.scheme in ("http", "https", "") and u.netloc \
                    and not value.strip().startswith(SITE_URL):
                demo_hosts.add(u.netloc)
    privacy = (SITE / "privacy.html").read_text(encoding="utf-8")
    for host in sorted(demo_hosts):
        if host not in DISCLOSED:
            bad(f"showcase loads third-party host {host}: disclose it in privacy.html and add it to DISCLOSED")
        elif DISCLOSED[host] not in privacy:
            bad(f"showcase loads {host} but privacy.html does not mention {DISCLOSED[host]!r}")
    for host, words in DISCLOSED.items():
        if host not in demo_hosts and words in privacy and not any(DISCLOSED[h] == words for h in demo_hosts):
            bad(f"privacy.html mentions {words!r} but nothing under showcase/ loads {host} any more")

    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

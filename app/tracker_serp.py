"""Google web / images / videos SERPs: URL builder (`since` d|w|m is the `tbs=qdr:` past-day / week / month filter),
page classification, result unwrapping and the link parser, plus the query templates. Copied from leakhunt 7ccbdd3
(the laptop leak tools; read-only source) google (serp_url, classify_serp, is_goto, unwrap, serp_links) and search
(VERTICALS, TEMPLATES, FILE_HOST_TEMPLATES); serp_links rewritten from bs4 onto html.parser with bs4's html.parser
tree rules (void and self-closed tags hold nothing, an end tag closes the nearest open tag of its name, script /
style / template / rt / rp text and comments are no text). Not copied: the backend's paging, counters and stats, /goto
resolution (a /goto link is dropped). Local: is_media_url is tracker_rules'. Stdlib only.

The Browserbase session (Session) is copied from the same commit's serp (LOADS_PER_SESSION, WALLS, SerpSession's
settle), google (GoogleSession's ready selector, consent click-through, /sorry/ wait), browser (BLOCKED_TYPES,
_block_assets, a page per load) and adapters (BrowserbaseFetcher's create and release), on bb_client (media_gather's
REST helpers, shared) with playwright imported lazily (the service image has playwright but no browsers: remote CDP
only). Proxies are never requested and the CAPTCHA solver is always on. The walls / retry / reservation loop is the
caller's (tracker_lanes), so every navigation is charged first."""
import re
import time
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import bb_client
from tracker_rules import is_media_url

VERTICALS = ("web", "images", "videos")
TEMPLATES = ('"{h}"', '"{h}" leaked', '"{h}" onlyfans')  # the bare handle first, then the intent words
FILE_HOST_TEMPLATES = ('"{h}" mega.nz', '"{h}" site:t.me')

GOOGLE_SEARCH = "https://www.google.com/search"
_GOOGLE_HOST = re.compile(r"(^|\.)google\.[a-z]{2,3}(\.[a-z]{2})?$")
_OWN_HOST = re.compile(r"(^|\.)(gstatic\.com|googleusercontent\.com|googleapis\.com|schema\.org|w3\.org)$")
# Google's own wording for an empty result: web/videos "did not match any documents", images "It looks like there
# aren't any 'images' matches on this topic" (curly or straight apostrophe), older "No results found for".
_NO_RESULTS = ("did not match any", "no results found for", "looks like there aren")
# #rso holds the results, #search is the results shell (empty results too), #captcha-form / #recaptcha are the
# /sorry/ wall's. Text markers alone are unsafe: every SERP's scripts contain "captcha", "/sorry/" and "enablejs".
_IDS = re.compile(r"""\sid=["']?(rso|search|captcha-form|recaptcha)["'\s>]""")


def serp_url(query, vertical="web", page=0, since=None):
    params = {"q": query, "safe": "off", "hl": "en", "num": "10"}
    if vertical == "images":
        params["tbm"] = "isch"
    else:
        params["start"] = str(10 * page)
        if vertical == "videos":
            params["tbm"] = "vid"
    if since:
        params["tbs"] = f"qdr:{since}"
    return f"{GOOGLE_SEARCH}?{urlencode(params)}"


def classify_serp(final_url, html):
    """"consent" | "captcha" | "unknown" (walls) | "no_results" | "results". Only a "results" page (#rso, no
    no-results wording) without result links means the markup changed; "unknown" has neither #rso nor #search."""
    parts = urlsplit(final_url)
    low = html.lower()
    ids = set(_IDS.findall(html))
    if (parts.hostname or "").startswith("consent.google."):
        return "consent"
    if ("/sorry/" in parts.path or ids & {"captcha-form", "recaptcha"}
            or ("rso" not in ids and "unusual traffic" in low)):
        return "captcha"
    if any(t in low for t in _NO_RESULTS):
        return "no_results"
    if "rso" in ids:
        return "results"
    return "no_results" if "search" in ids else "unknown"


def is_goto(url):
    p = urlsplit(url)
    return bool(_GOOGLE_HOST.search(p.hostname or "")) and p.path == "/goto"


def unwrap(url):
    """The result URL behind a SERP href: /url?q=, /imgres?imgrefurl= and translate.google.*/translate?u= unwrapped,
    a /goto kept as-is; Google's own pages, gstatic, schema/policy links, YouTube account pages and media files give
    None."""
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    if p.scheme not in ("http", "https") or not host:
        return None
    if _GOOGLE_HOST.search(host):
        if p.path == "/goto":
            return url
        qs = parse_qs(p.query)
        inner = {"/url": (qs.get("q") or qs.get("url") or [""])[0], "/imgres": (qs.get("imgrefurl") or [""])[0],
                 "/translate": (qs.get("u") or [""])[0]}
        return unwrap(inner[p.path]) if inner.get(p.path, "").startswith("http") else None
    if _OWN_HOST.search(host) or is_media_url(url):
        return None
    if host.endswith("youtube.com") and (host.startswith("accounts.") or p.path.startswith("/account")):
        return None
    return url


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "keygen", "link", "menuitem", "meta", "param",
         "source", "track", "wbr", "basefont", "bgsound", "command", "frame", "image", "isindex", "nextid", "spacer"}
_NO_TEXT = {"script", "style", "template", "rt", "rp"}


class _El:
    __slots__ = ("name", "attrs", "parent", "children")

    def __init__(self, name, attrs, parent):
        self.name, self.attrs, self.parent, self.children = name, attrs, parent, []

    def get(self, key):
        return self.attrs.get(key)

    def _walk(self):
        stack = self.children[::-1]
        while stack:
            c = stack.pop()
            yield c
            if isinstance(c, _El):
                stack.extend(c.children[::-1])

    def descendants(self):
        return (c for c in self._walk() if isinstance(c, _El))

    def strings(self):
        return (c for c in self._walk() if isinstance(c, str))

    def find(self, name):
        return next((d for d in self.descendants() if d.name == name), None)

    def parents(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent


class _Tree(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = self.cur = _El("[document]", {}, None)
        self.split, self.voids = False, []
        self.feed(html)
        self.close()

    def _open(self, tag, attrs):
        el = _El(tag, {k: "" if v is None else v for k, v in attrs}, self.cur)
        self.cur.children.append(el)
        return el

    def handle_starttag(self, tag, attrs):
        el = self._open(tag, attrs)
        if tag in _VOID:
            self.voids.append(tag)
        else:
            self.cur = el

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs)

    def handle_endtag(self, tag):
        if tag in self.voids:  # bs4 drops the end tag of a void element it already closed, string run intact
            self.voids.remove(tag)
            return
        self.split = True
        node = self.cur
        while node is not None and node.name != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        if self.cur.name in _NO_TEXT or any(p.name in _NO_TEXT for p in self.cur.parents()):
            return
        if self.cur.children and isinstance(self.cur.children[-1], str) and not self.split:
            self.cur.children[-1] += data
        else:
            self.cur.children.append(data)
        self.split = False

    def handle_comment(self, data):
        self.split = True

    handle_decl = handle_pi = unknown_decl = handle_comment


def _heading(el):
    return el.name == "h3" or el.get("role") == "heading"


def _title(el):
    """The anchor's h3 (or role=heading) text, else the nearest one up to 3 ancestors away. "" if none, or if the
    nearest ancestor with a heading holds several (a container of many results, not this link's own)."""
    node = el
    for _ in range(4):
        if node is None:
            break
        heads = []
        for d in node.descendants():
            if _heading(d):
                heads.append(d)
                if len(heads) == 2:
                    break
        if heads:
            return " ".join(s.strip() for s in heads[0].strings() if s.strip()) if len(heads) == 1 else ""
        node = node.parent
    return ""


def _tile_title(tile):
    """An images tile's text for its source page: aria-label, title attribute, image alt, else the caption text."""
    img = tile.find("img")
    for text in (tile.get("aria-label"), tile.get("title"), img.get("alt") if img else "", " ".join(tile.strings())):
        if text := " ".join(str(text or "").split()):
            return text[:200]
    return ""


def serp_links(html, base=GOOGLE_SEARCH):
    """(url, title) for every result link on a SERP, first occurrence per url; /goto links still unresolved.
    Images tiles: an anchor's href or the landing page in `data-lpage`, titled from the tile (see _tile_title)."""
    out = {}
    for el in _Tree(html).root.descendants():
        if not ("data-lpage" in el.attrs or (el.name == "a" and "href" in el.attrs)):
            continue
        raw = el.get("data-lpage") or el.get("href") or ""
        url = unwrap(urljoin(base, raw))
        if url and not out.get(url):
            tile = el if "data-lpage" in el.attrs else next((p for p in el.parents() if "data-lpage" in p.attrs), None)
            if tile is None and urlsplit(urljoin(base, raw)).path == "/imgres":
                tile = el
            out[url] = (_tile_title(tile) if tile is not None else "") or _title(el)
    return list(out.items())


LOADS_PER_SESSION = 12  # then a fresh session (a new IP)
WALLS = ("captcha", "consent", "unknown")
BLOCKED_TYPES = {"image", "media", "font", "stylesheet"}
IMAGES_BLOCKED = {"media", "font"}  # the images parser reads tile attributes; images stay until a parser test shows otherwise
SESSION_S = 300
SOLVE_WAIT_S = 30
LOAD_S = 30
ROTATE_S = SESSION_S - 2 * (LOAD_S + SOLVE_WAIT_S + 10)  # rotate before a worst-case load could outlive it
READY = "#rso a[href], [data-lpage], #search:not(:has(#rso)), #captcha-form, #recaptcha"
READY_JS = "s => !!document.querySelector(s)"
READY_MS, READY_POLL_MS = 2000, 250
_clock = time.monotonic


def _playwright():
    """Started sync Playwright; a module-level seam so tests inject a fake."""
    from playwright.sync_api import sync_playwright
    return sync_playwright().start()


def _block(route, types):
    if route.request.resource_type in types:
        route.abort()
    else:
        route.continue_()


def block_assets(route):
    """Web and videos loads."""
    _block(route, BLOCKED_TYPES)


def block_fonts_media(route):
    """Images loads."""
    _block(route, IMAGES_BLOCKED)


def blocker(vertical):
    return block_fonts_media if vertical == "images" else block_assets


class Session:
    """One Browserbase session: create() (Playwright first, so a broken one bills nothing; then the REST create and
    CDP), page(vertical) -> a fresh page with that vertical's asset blocker routed, load(page, url) -> (final_url, html),
    release().
    `loads` counts this session's navigations; stale() = LOADS_PER_SESSION loads or ROTATE_S old. The key is never
    logged."""

    def __init__(self, key, project):
        self.key, self.project, self.loads = key, project, 0
        self.id = self._pw = self._browser = self.born = None

    def create(self):
        self._pw = _playwright()
        d = bb_client.gated(lambda: bb_client.create(self.key, self.project, SESSION_S, _clock() + SESSION_S,
                                                     who="tracker browserbase"))
        if not d:
            raise RuntimeError("browserbase create failed")
        self.id, self.born = d["id"], _clock()
        self._browser = self._pw.chromium.connect_over_cdp(d["connectUrl"])
        return self

    def stale(self):
        return self.loads >= LOADS_PER_SESSION or _clock() - self.born >= ROTATE_S

    def page(self, vertical="web"):
        ctx = self._browser.contexts[0] if self._browser.contexts else self._browser.new_context()
        page = ctx.new_page()
        try:
            page.route("**/*", blocker(vertical))
        except Exception:
            close_page(page)
            raise
        return page

    def load(self, page, url):
        self.loads += 1
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=LOAD_S * 1000)
            _settle(page)
            return page.url, page.content()
        finally:
            close_page(page)

    def release(self):
        for close in (getattr(self._browser, "close", None), getattr(self._pw, "stop", None)):
            try:
                close and close()
            except Exception:
                pass
        if self.id:
            bb_client.release(self.key, self.project, self.id, who="tracker browserbase")
        self.id = self._pw = self._browser = None


def close_page(page):
    try:
        page.close()
    except Exception:
        pass


def _settle(page):
    if (urlsplit(page.url).hostname or "").startswith("consent.google."):
        try:
            page.locator("button").filter(has_text=re.compile(r"reject all|accept all", re.I)).first.click(timeout=5000)
            page.wait_for_load_state("domcontentloaded")
        except Exception:
            pass
    waited = 0
    while "/sorry/" in urlsplit(page.url).path and waited < SOLVE_WAIT_S:
        page.wait_for_timeout(1000)
        waited += 1
    if "/sorry/" in urlsplit(page.url).path:
        return
    deadline = time.monotonic() + READY_MS / 1000
    while not page.evaluate(READY_JS, READY) and time.monotonic() < deadline:
        page.wait_for_timeout(READY_POLL_MS)

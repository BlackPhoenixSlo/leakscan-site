"""The page kind the Leak judge and Jev see (`policy_kind`), copied from leakhunt 7ccbdd3 (the laptop leak tools;
read-only source) siteparse: Handles (minus query_forms), classify_url, url_kind, policy_kind and their word tables.
Local: is_media_url is tracker_rules'. Stdlib only."""
import re
from urllib.parse import parse_qsl, unquote_plus, urlsplit

from tracker_rules import is_media_url

LISTING_WORDS = {
    **dict.fromkeys(("model", "models", "pornstar", "pornstars", "performer", "performers", "channel", "channels",
                     "user", "users", "profile", "profiles", "creator", "creators", "star", "stars", "actor", "actors",
                     "member", "members", "u", "c", "amateur", "amateurs", "girls", "boys", "studio", "studios",
                     "uploader"), "profile"),
    **dict.fromkeys(("tag", "tags", "category", "categories"), "tag"),
    **dict.fromkeys(("search", "s"), "search"),
    **dict.fromkeys(("page", "uploads"), "listing"),
}
LISTING_KINDS = ("profile", "numbered", "tag", "search", "listing")
NAMED_MIN = 6
CONTENT_WORDS = {
    "video": "video", "videos": "video", "watch": "video", "v": "video", "view": "video", "clip": "video",
    "clips": "video", "movies": "video", "movie": "video", "embed": "video",
    "photo": "image", "photos": "image", "pics": "image", "pictures": "image", "gallery": "image",
    "galleries": "image", "album": "image", "albums": "image",
    "post": "post", "posts": "post",
}
PLURAL_CONTENT = {"videos", "photos", "clips", "movies", "posts", "galleries", "albums", "pics", "pictures"}
SKIP_WORDS = {
    "login", "signup", "sign-up", "register", "upload", "dmca", "terms", "privacy", "contact", "faq", "static",
    "assets", "feed", "rss", "cdn-cgi", "wp-json", "wp-admin", "wp-login.php", "out", "go", "away", "logout", "2257",
    "tos", "cart", "checkout", "premium", "signin",
}
SEARCH_KEYS = {"q", "s", "search", "query", "k", "keyword", "keywords", "search_query"}
ID_KEYS = {"id", "v", "vid", "video_id", "post_id", "pid"}
FORUM_SCRIPTS = {"viewtopic.php", "showthread.php", "showpost.php"}
FORUM_KEYS = {"t", "p", "topic", "threadid", "postid"}
TAB_WORDS = {"video", "videos", "photo", "photos", "pics", "pictures", "images", "short", "shorts", "clips", "gallery",
             "galleries", "albums", "posts", "media", "gifs", "reels"}

PAGE_KINDS = ("content", *LISTING_KINDS, "media", "other")
DEDICATED = ("profile", "numbered")
CLIENT_KINDS = tuple(f"client_{k}" for k in DEDICATED)
GENERIC_LISTINGS = tuple(k for k in LISTING_KINDS if k not in DEDICATED)


def _tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower())


class Handles:
    """Handle forms reduced to one concatenated key ('zane walker' == 'zane-walker' == 'zanewalker')."""

    def __init__(self, handles):
        self.raw = [h.strip() for h in handles if h.strip()]
        self.key_of = ["".join(_tokens(h)) for h in self.raw]
        self.keys = {k for k in self.key_of if len(k) >= 4}
        self.maxlen = max((len(k) for k in self.keys), default=0)

    def match(self, text):
        """Keys whose tokens appear consecutively in `text` (no matching inside longer words)."""
        toks, found = _tokens(text), set()
        for i in range(len(toks)):
            acc = ""
            for tok in toks[i: i + 8]:
                acc += tok
                if len(acc) > self.maxlen:
                    break
                if acc in self.keys:
                    found.add(acc)
        return sorted(found)

    def is_key(self, text):
        return "".join(_tokens(text)) in self.keys

    def named(self, *texts):
        """Substring mode, by index in `raw`: handles of NAMED_MIN+ letters and digits whose key occurs in a text."""
        blob = "|".join("".join(_tokens(unquote_plus(t))) for t in texts if t)
        return {i for i, k in enumerate(self.key_of) if len(k) >= NAMED_MIN and k in blob}


def _after_id(rest):
    if len(rest) >= 2 and rest[0].isdigit() and not rest[1].isdigit() and rest[1].lower() not in LISTING_WORDS:
        return rest[1:]
    return rest


def _listing_kind(word, rest):
    kind = LISTING_WORDS[word]
    if kind != "profile":
        return kind
    rest = _after_id(rest)
    if not rest or rest[0].isdigit():
        return "listing"
    tail = rest[1:]
    if not tail or (len(tail) == 2 and tail[0] == "page" and tail[1].isdigit()):
        return "profile"
    return "numbered" if len(tail) == 1 and tail[0].isdigit() else "listing"


def _listing_at(segs):
    return next(((i, s) for i, s in enumerate(segs[:3]) if s in LISTING_WORDS), None)


def _segments(url):
    return [s for s in unquote_plus(urlsplit(url).path).split("/") if s]


def _is_tab(segs):
    return (len(segs) == 2 and segs[1] in TAB_WORDS and not segs[0].isdigit()
            and segs[0] not in CONTENT_WORDS and segs[0] not in LISTING_WORDS and segs[0] not in TAB_WORDS)


def is_forum_thread(segs, query):
    last = segs[-1] if segs else ""
    if last in FORUM_SCRIPTS:
        return bool(FORUM_KEYS & set(query))
    if re.fullmatch(r"topic\d+(?:-\d+)?\.html", last):
        return True
    for i, s in enumerate(segs[:-1]):
        if s == "threads" and re.fullmatch(r"[^/]*\.\d+", segs[i + 1]):
            tail = segs[i + 2:]
            return not tail or (len(tail) == 1 and bool(re.fullmatch(r"(page|post)-\d+", tail[0])))
    return False


def classify_url(url):
    """(role, kind, reason) from the URL alone."""
    parts = urlsplit(url)
    segs = [s.lower() for s in _segments(url)]
    query = dict(parse_qsl(parts.query))
    if is_media_url(url) or any(s in SKIP_WORDS for s in segs):
        return "other", "unknown", "skip"
    if is_forum_thread(segs, query):
        return "content", "post", "forum"
    for i, s in enumerate(segs):
        if s in CONTENT_WORDS and i + 1 < len(segs):
            nxt = segs[i + 1]
            if nxt in LISTING_WORDS or (s in PLURAL_CONTENT and re.fullmatch(r"\d{1,3}", nxt)):
                continue
            return "content", CONTENT_WORDS[s], f"path:/{s}/"
        if re.match(r"^(video|watch)[\d._-]", s):
            return "content", "video", "path:video-id"
    if segs[:1] == ["watch"] and "v" in query:
        return "content", "video", "path:/watch?v="
    if segs and segs[-1] in CONTENT_WORDS and ID_KEYS & set(query):
        return "content", CONTENT_WORDS[segs[-1]], f"path:/{segs[-1]}?id="
    if _is_tab(segs):
        return "listing", "listing", "tab"
    if at := _listing_at(segs):
        i, s = at
        return "listing", _listing_kind(s, segs[i + 1:]), f"path:/{s}/"
    if SEARCH_KEYS & set(query):
        return "listing", "search", "query"
    if any(re.fullmatch(r"-?\d{6,}", s) for s in segs) or (
        len(segs) >= 2 and any(re.fullmatch(r"\d{3,}", s) for s in segs)
    ):
        return "content", "unknown", "numeric-id+slug"
    if any(
        re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*-\d{3,}(?:\.html?)?|\d{3,}-[a-z][a-z0-9-]*(?:\.html?)?", s) for s in segs
    ):
        return "content", "unknown", "slug-id"
    if 1 <= len(segs) <= 2 and segs[-1].count("-") >= 3 and not re.fullmatch(r"[\d-]+", segs[-1]):
        return "content", "post", "long-slug"
    return "other", "unknown", ""


def url_kind(url, h=None):
    """One of PAGE_KINDS from the URL alone."""
    url = url if "://" in url else f"https://{url}"
    role, kind, reason = classify_url(url)
    parts = urlsplit(url)
    segs = [s for s in parts.path.split("/") if s]
    if reason == "tab":
        return "profile" if h is not None and h.is_key(unquote_plus(segs[0])) else kind
    if role != "other":
        return kind if role == "listing" else "content"
    if is_media_url(url):
        return "media"
    exact = h is not None and len(segs) == 1 and not parts.query and h.is_key(unquote_plus(segs[0]))
    return "profile" if exact else "other"


def _name_segment(url):
    segs = _segments(url)
    at = _listing_at([s.lower() for s in segs])
    if not at:
        return None
    rest = segs[at[0] + 1:]
    rest = _after_id(rest) if LISTING_WORDS[at[1]] == "profile" else rest
    return rest[0] if rest else None


def policy_kind(url, h):
    """url_kind, with a DEDICATED page whose name segment is a client handle as client_profile / client_numbered."""
    url = url if "://" in url else f"https://{url}"
    kind = url_kind(url, h)
    if kind not in DEDICATED:
        return kind
    name = _name_segment(url)
    client = kind == "profile" if name is None else bool(h.match(name) or h.named(name))
    return CLIENT_KINDS[DEDICATED.index(kind)] if client else kind

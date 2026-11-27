"""Leak tracker host / URL / probe rules, copied from leakhunt 7ccbdd3 (the laptop leak tools; read-only source) so
the service and the tools agree: urls.url_key, availability.status_to_availability, fetch.is_blocked_response +
is_media_url, _vendor/fetch_common.is_blocked, _vendor/site_probe.GONE, registry.link_kind / host_class and the data
files tracker_data/{link_only,excluded_domains,not_leak_hosts}.json (fake_aggregators.txt is app/'s, identical).
netloc.canon_url is app/netloc's (identical); registrable_domain is app/netloc's too (leakhunt's adds cc second
levels like com.pl). Local: host_class answers "page" for a host leakhunt calls registry / unknown, and GONE reads
only the page's <title> / first <h1> (leakhunt pairs it with a name check the shared probe can't make). Stdlib only."""
import json
import os
import re
from urllib.parse import urlsplit

from netloc import canon_url, registrable_domain

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "tracker_data")

MEDIA_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp", ".heic", ".svg",
    ".mp4", ".m4v", ".webm", ".mov", ".mkv", ".avi", ".flv", ".wmv", ".m3u8", ".ts", ".mpd",
)
CHALLENGE_TITLES = (
    "just a moment",
    "attention required",
    "checking your browser",
    "access denied",
    "ddos-guard",
    "verifying you are human",
    "one moment, please",
    "security check",
    "are you human",
    "bot verification",
)
CHALLENGE_BODY = (
    "cf-browser-verification",
    "_cf_chl_opt",
    "enable javascript and cookies to continue",
    "please wait while we verify",
    "ddos-guard.net",
    "please enable cookies",
)
MIN_REAL_PAGE_BYTES = 30_000
BLOCKING_STATUSES = (401, 403, 429, 503)
GONE = re.compile(r"(not found|no longer available|has been removed|page not found|"
                  r"does(?:n'?t| not) exist|no results|nothing found|0 results)", re.I)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def url_key(url, keep_fragment=False):
    """The dedupe key: canon_url, plus the fragment when asked (a mega.nz file key lives there; Google's
    `#:~:text=` highlight is not part of the address)."""
    frag = url.partition("#")[2].partition(":~:")[0]
    return canon_url(url) + (f"#{frag}" if keep_fragment and frag else "")


def is_media_url(url):
    return urlsplit(url).path.rstrip("/").lower().endswith(MEDIA_EXTENSIONS)


def page_title(html):
    m = _TITLE_RE.search(html or "")
    return re.sub(r"\s+", " ", m.group(1)).strip()[:120] if m else ""


def is_blocked(status, body=""):
    """True when the host refused us; False when it answered (404 and a "not found" 200 included)."""
    title = page_title(body).lower()
    if title and any(m in title for m in CHALLENGE_TITLES):
        return True
    if status in BLOCKING_STATUSES:
        return True
    if status and 200 <= status < 300:
        low = (body or "").lower()
        return len(body or "") < MIN_REAL_PAGE_BYTES and any(m in low for m in CHALLENGE_BODY)
    return False


def is_blocked_response(status, html=""):
    return status in (403, 421, 429, 503) or bool(status and is_blocked(status, html or ""))


def is_removal_page(html):
    h1 = _H1_RE.search(html or "")
    return bool(GONE.search(page_title(html)) or (h1 and GONE.search(_TAG_RE.sub(" ", h1.group(1)))))


def status_to_availability(status, html=""):
    """-> live | dead | blocked | unknown. 404 / 410 and a 200 removal page are dead."""
    if status in (404, 410):
        return "dead"
    if is_blocked_response(status, html):
        return "blocked"
    if status == 200:
        return "dead" if is_removal_page(html) else "live"
    return "unknown"


def _norm_domain(domain):
    return (domain or "").strip().lower().removeprefix("www.").rstrip(".")


def _load_domain_list(path):
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as fh:
        if path.endswith(".json"):
            raw = json.load(fh)
            items = raw.get("domains", list(raw)) if isinstance(raw, dict) else raw
        else:
            items = [ln.split("#", 1)[0] for ln in fh.read().splitlines()]
    return {_norm_domain(d) for d in items if isinstance(d, str) and d.strip() and "@" not in d}


with open(os.path.join(DATA, "link_only.json"), encoding="utf-8") as _fh:
    LINK_ONLY = json.load(_fh)["hosts"]
SKIP = (_load_domain_list(os.path.join(HERE, "fake_aggregators.txt"))
        | _load_domain_list(os.path.join(DATA, "excluded_domains.json"))
        | _load_domain_list(os.path.join(DATA, "not_leak_hosts.json")))


def _keys(domain):
    d = _norm_domain(domain)
    reg = registrable_domain(d) or d
    return [d] if reg == d else [d, reg]


def link_kind(domain):
    """"filehost" | "telegram" for a link-only host (any subdomain of one), else None."""
    d = _norm_domain(domain)
    d = registrable_domain(d) or d
    return LINK_ONLY.get(d) or LINK_ONLY.get(d.split(".", 1)[0] + ".*")


def host_of(url):
    try:
        return _norm_domain(urlsplit(url).hostname or "")
    except ValueError:
        return ""


def host_class(domain):
    """"skip" (aggregator, excluded own-platform / social, or a host that never carries leaks), "filehost" /
    "telegram" (link-only: never probed) or "page"."""
    if not _norm_domain(domain) or any(k in SKIP for k in _keys(domain)):
        return "skip"
    return link_kind(domain) or "page"

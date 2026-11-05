"""leakshaven.com lookup for the quick scan: creator match -> pack list -> mega[] items.

Endpoints (public JSON API the site's own JS uses, behind Cloudflare, no challenge for plain HTTPS):
  GET {BASE}/content/suggest?term=<t>&take=8   autocomplete: [{title, modelId, matchedSearch, matchedSource, ...}]
  GET {BASE}/content?search=<title>&count=30&sorting=NEWEST
                                               packs: {content: [{id, shortCode, title, createdAt, deleted,
                                                        info: {images, videos, size, updatedAt}}]}
The Mega folder URL itself comes from GET /content/<id>/url, which requires reCAPTCHA + Turnstile tokens
(403 without) -> not fetched. Each item's url is the pack's public share page (SHARE/<shortCode>), the page
that holds the Mega button and the takedown target. Two requests per scan, <= TIMEOUT s total, never raises,
never logs handles or URLs.
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ENABLED = os.environ.get("LEAKSHAVEN_ENABLED", "1").lower() in ("1", "true", "yes")
BASE = os.environ.get("LEAKSHAVEN_BASE", "https://api.leakshaven.com").rstrip("/")
SHARE = "https://s.leakshaven.com"
TIMEOUT = min(float(os.environ.get("LEAKSHAVEN_TIMEOUT", "8")), 8.0)
CACHE_TTL = 6 * 3600
MAX_PACKS = 30
VIA = "leakshaven.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")
_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")


class Skip(Exception):
    """Lookup ended without a result (reason is a short log token, never user data)."""


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lstrip("@").lower()


def _get(path, params, deadline):
    left = deadline - time.monotonic()
    if left <= 0.2:
        raise Skip("timeout")
    req = urllib.request.Request(f"{BASE}{path}?{urllib.parse.urlencode(params)}", headers={
        "User-Agent": UA, "Accept": "application/json",
        "Origin": "https://leakshaven.com", "Referer": "https://leakshaven.com/"})
    try:
        with urllib.request.urlopen(req, timeout=left) as r:
            return json.loads(r.read(2_000_000).decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise Skip(f"http{e.code}")
    except (TimeoutError, OSError) as e:
        raise Skip("timeout" if "timed out" in str(e) else "net")
    except ValueError:
        raise Skip("badjson")


def match(suggestions, aliases, names=()):
    """Pure: suggest items -> the matched creator's display title, or None. A hit is a social-handle
    match (matchedSource != name, matchedSearch == an alias) or an exact title == alias / name."""
    al = {_norm(a) for a in aliases if _norm(a)}
    nm = al | {_norm(n) for n in names if _norm(n)}
    for it in suggestions if isinstance(suggestions, list) else []:
        if not isinstance(it, dict) or not isinstance(it.get("title"), str) or not it["title"].strip():
            continue
        src = _norm(it.get("matchedSource"))
        if src and src != "name" and _norm(it.get("matchedSearch")) in al:
            return it["title"]
        if _norm(it["title"]) in nm:
            return it["title"]
    return None


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def packs(data):
    """Pure: /content response -> mega[] items (live packs only, deduped by pack id, capped)."""
    out, seen = [], set()
    items = data.get("content") if isinstance(data, dict) else None
    for p in items if isinstance(items, list) else []:
        if not isinstance(p, dict) or p.get("deleted"):
            continue
        pid, code = p.get("id"), p.get("shortCode")
        if not isinstance(pid, str) or pid in seen or not isinstance(code, str) or not _CODE_RE.match(code):
            continue
        seen.add(pid)
        info = p.get("info") if isinstance(p.get("info"), dict) else {}
        ts = info.get("updatedAt") or p.get("createdAt")
        out.append({
            "url": f"{SHARE}/{code}", "host": VIA, "via": VIA,
            "title": (p.get("title") or "")[:200] if isinstance(p.get("title"), str) else "",
            "size": _int(info.get("size")), "images": _int(info.get("images")),
            "videos": _int(info.get("videos")),
            "age": ts[:19] + "Z" if isinstance(ts, str) and _TS_RE.match(ts) else None,
            "status": "live",
        })
        if len(out) >= MAX_PACKS:
            break
    return out


def lookup(term, aliases, names=()):
    """term + alias set -> (mega items, reason). One suggest + one pack-list call, <= TIMEOUT s.
    reason: ok | nomatch | short | <Skip token>. Never raises."""
    term = _norm(term)
    if len(term) <= 2:                       # the site's own autocomplete needs > 2 chars
        return [], "short"
    deadline = time.monotonic() + TIMEOUT
    try:
        title = match(_get("/content/suggest", {"term": term, "take": 8}, deadline), [term, *aliases], names)
        if not title:
            return [], "nomatch"
        return packs(_get("/content", {"search": title, "count": MAX_PACKS, "sorting": "NEWEST"}, deadline)), "ok"
    except Skip as e:
        return [], str(e)
    except Exception as e:                   # never break the scan
        return [], f"err:{type(e).__name__}"


def hit_rows(items, alias=None):
    """mega[] items -> scan hit rows (one per pack) so the report's Sites / Links counts include them."""
    return [{"domain": VIA, "url": it["url"], "occurrences": 1, "method": "leakshaven",
             "evidence": "aggregator", "alias": alias, "live": True} for it in items]

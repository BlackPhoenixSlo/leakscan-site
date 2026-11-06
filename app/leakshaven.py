"""leakshaven.com lookup for the quick scan: creator match -> pack list -> mega[] items.

Endpoints (public JSON API the site's own JS uses, behind Cloudflare, no challenge for plain HTTPS):
  GET {BASE}/content/suggest?term=<t>&take=8   autocomplete: [{title, modelId, matchedSearch, matchedSource, ...}]
  GET {BASE}/content?search=<title>&count=30&sorting=NEWEST
                                               packs: {content: [{id, shortCode, title, createdAt, deleted, modelId?,
                                                        info: {images, videos, size, updatedAt}}],
                                                       richProfileId, richProfileName}
`search` is free text: it can return another creator's packs. A pack is kept only when it is the matched creator's:
its own modelId equals hers; or it has none, the response's richProfileId is hers AND the pack title holds every word
of her name (richProfileId alone scopes the profile, not each pack of a free-text search); nothing attributable -> [].
The Mega folder URL itself comes from GET /content/<id>/url, which requires reCAPTCHA + Turnstile tokens
(403 without) -> not fetched. Each item's url is the pack's public share page (SHARE/<shortCode>), the page
that holds the Mega button and the takedown target. Two requests per scan, <= TIMEOUT s wall clock, <= 2 req/s
per process, never raises, never logs handles or URLs. mega[] is the only carrier of these items (never hit rows).
"""
import concurrent.futures as _cf
import hashlib
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


def _env_timeout(raw, cap=8.0):
    """LEAKSHAVEN_TIMEOUT -> seconds in (0, cap]; junk / <= 0 -> cap (the scan budget is 8 s, never more)."""
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return cap
    return min(v, cap) if math.isfinite(v) and v > 0 else cap


ENABLED = os.environ.get("LEAKSHAVEN_ENABLED", "1").lower() in ("1", "true", "yes")
BASE = os.environ.get("LEAKSHAVEN_BASE", "https://api.leakshaven.com").rstrip("/")
SHARE = "https://s.leakshaven.com"
TIMEOUT = _env_timeout(os.environ.get("LEAKSHAVEN_TIMEOUT", "8"))
CACHE_TTL = 6 * 3600
CACHE_FIELD = "mega_key"          # scans.extra_json key: cache_key() of a fresh ok/nomatch lookup (never served)
MIN_GAP = 0.5                     # s between requests, whole process: <= 2 req/s vs their 10 rps limit
MAX_PACKS = 30
VIA = "leakshaven.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")
_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
_RATE_LOCK = threading.Lock()
_next_at = 0.0


class Skip(Exception):
    """Lookup ended without a result (reason is a short log token, never user data)."""


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lstrip("@").lower()


def cache_key(platform, term, aliases, names=()):
    """Everything the lookup's answer depends on -> opaque key (a scan of X with instagram=Y never serves
    a scan of X without it, nor another platform's)."""
    parts = [_norm(platform), _norm(term), sorted({_norm(a) for a in aliases if _norm(a)}),
             sorted({_norm(n) for n in names if _norm(n)})]
    return "v1:" + hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:32]


def _slot(deadline):
    """Wait for this process's next request slot (MIN_GAP apart); Skip('busy') if it is past the deadline."""
    global _next_at
    with _RATE_LOCK:
        now = time.monotonic()
        at = max(now, _next_at)
        if at > deadline - 0.2:
            raise Skip("busy")
        _next_at = at + MIN_GAP
    if at > now:
        time.sleep(at - now)


def _get(path, params, deadline):
    _slot(deadline)
    left = deadline - time.monotonic()
    if left <= 0.2:
        raise Skip("timeout")
    req = urllib.request.Request(f"{BASE}{path}?{urllib.parse.urlencode(params)}", headers={
        "User-Agent": UA, "Accept": "application/json",
        "Origin": "https://leakshaven.com", "Referer": "https://leakshaven.com/"})
    try:
        with urllib.request.urlopen(req, timeout=left) as r:   # closed at the deadline: a dripping server can't hold it
            body = b""
            while len(body) < 2_000_000:
                if time.monotonic() > deadline:
                    raise Skip("timeout")
                chunk = r.read1(65536)
                if not chunk:
                    break
                body += chunk
            return json.loads(body[:2_000_000].decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise Skip(f"http{e.code}")
    except TimeoutError:
        raise Skip("timeout")
    except urllib.error.URLError as e:
        raise Skip("timeout" if isinstance(e.reason, TimeoutError) else "net")
    except OSError:
        raise Skip("net")
    except ValueError:
        raise Skip("badjson")


def _model_id(v):
    return v if isinstance(v, str) and v.strip() else None


def match(suggestions, aliases, names=()):
    """Pure: suggest items -> the matched creator {title, modelId}, or None. A social-handle match
    (matchedSource != name, matchedSearch == an alias) wins; else an exact title == alias / name, only when
    exactly one creator has that title (two same-named creators -> can't tell them apart -> None)."""
    al = {_norm(a) for a in aliases if _norm(a)}
    nm = al | {_norm(n) for n in names if _norm(n)}
    items = [it for it in (suggestions if isinstance(suggestions, list) else [])
             if isinstance(it, dict) and isinstance(it.get("title"), str) and it["title"].strip()
             and _model_id(it.get("modelId"))]
    pick = lambda it: {"title": it["title"], "modelId": it["modelId"]}
    for it in items:
        src = _norm(it.get("matchedSource"))
        if src and src != "name" and _norm(it.get("matchedSearch")) in al:
            return pick(it)
    for it in items:
        t = _norm(it["title"])
        if t in nm and len({x["modelId"] for x in items if _norm(x["title"]) == t}) == 1:
            return pick(it)
    return None


def _int(v):
    """size / images / videos -> non-negative int (int, float or numeric string), else None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        try:
            v = float(v.strip())
        except ValueError:
            return None
    if isinstance(v, float):
        if not math.isfinite(v):
            return None
        v = int(v)
    return v if isinstance(v, int) and v >= 0 else None


def _words(s):
    return {w for w in re.split(r"[^a-z0-9]+", _norm(s)) if len(w) >= 2}


def packs(data, who):
    """Pure: /content response + the matched creator (match(): {title, modelId}) -> mega[] items (her live packs
    only, deduped by pack id, capped). A pack counts as hers when its own modelId is hers; one without a modelId
    only when the response's richProfileId is hers and its title holds every word (2+ chars) of her title.
    Nothing attributable -> []."""
    out, seen = [], set()
    model_id = _model_id((who or {}).get("modelId")) if isinstance(who, dict) else None
    if not isinstance(data, dict) or not model_id:
        return out
    items = data.get("content")
    name = _words(who.get("title"))
    scoped = _model_id(data.get("richProfileId")) == model_id and bool(name)
    for p in items if isinstance(items, list) else []:
        if not isinstance(p, dict) or p.get("deleted"):
            continue
        own = _model_id(p.get("modelId"))
        if own != model_id and (own or not scoped or not name <= _words(p.get("title"))):
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


def _lookup(term, aliases, names, deadline):
    try:
        who = match(_get("/content/suggest", {"term": term, "take": 8}, deadline), [term, *aliases], names)
        if not who:
            return [], "nomatch"
        return packs(_get("/content", {"search": who["title"], "count": MAX_PACKS, "sorting": "NEWEST"},
                          deadline), who), "ok"
    except Skip as e:
        return [], str(e)
    except Exception as e:                   # never break the scan
        return [], f"err:{type(e).__name__}"


def start(term, aliases, names=()):
    """term + alias set -> Future of (mega items, reason): one suggest + one pack-list call in a daemon thread of its
    own that gives up at TIMEOUT s from now (it closes a response still dripping at the deadline; a daemon never holds
    up the process exit). Wait for it with result(). reason: ok | nomatch | short | timeout | busy | net | http<code>
    | badjson | err:<type>. The worker never raises."""
    fut = _cf.Future()
    term = _norm(term)
    if len(term) <= 2:                       # the site's own autocomplete needs > 2 chars
        fut.set_result(([], "short"))
        return fut
    deadline = time.monotonic() + TIMEOUT
    threading.Thread(target=lambda: fut.set_result(_lookup(term, aliases, names, deadline)),
                     name="leakshaven", daemon=True).start()
    return fut


def result(fut, timeout):
    """start()'s Future -> (mega items, reason) within `timeout` s; still running then -> ([], "timeout")."""
    try:
        return fut.result(timeout=max(0.0, timeout))
    except _cf.TimeoutError:
        return [], "timeout"


# ---------- the aggregator rule (one place; public_app scan_end / scan_row apply it, the site's stub reuses them) ----------
def host(v):
    """A domain (port allowed) or an http(s) URL -> its lowercase host without "www." ('' if none)."""
    v = str(v or "").strip().lower()
    try:
        v = urllib.parse.urlsplit(v if "//" in v else "//" + v).hostname or ""
    except ValueError:
        return ""
    return v[4:] if v.startswith("www.") else v


def off_aggregators(items, mega, url_key="url"):
    """hit rows (url_key "url") / CSE results ("link") minus those on a mega[] item's host / via, by `domain` or
    URL host, suffix- and port-aware (s.leakshaven.com:8443 is leakshaven.com): aggregator hosts never show."""
    agg = {host(x.get(k)) for x in mega or [] if isinstance(x, dict) for k in ("host", "via")} - {""}
    on = lambda h: any(h == a or h.endswith("." + a) for a in agg)
    return [h for h in items or [] if not (isinstance(h, dict) and (on(host(h.get("domain"))) or on(host(h.get(url_key)))))]

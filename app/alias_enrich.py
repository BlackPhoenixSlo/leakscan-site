"""Alias enrichment for the quick scan: read a few leak pages the first CSE pass found and pull out
the SAME creator's other handles (OnlyFans / Fansly / Instagram / X / TikTok / Patreon links, @tokens,
the page's person name), so the scan can re-search under them and the profile gets more socials.

discover(rows, results, known, names=()) -> {aliases, socials, names, reasons, pages, cand, kept, secs}
  - pages: <= MAX_PAGES hit pages, highest-occurrence domains first, one per domain, pages only
    (no videos, no official/social hosts); fetched in a thread pool, <= FETCH_TIMEOUT each,
    <= FETCH_TOTAL overall, body capped at BODY_CAP, redirects only within the same site.
  - same-creator gate: a candidate is kept only if its normalised form is similar to a known
    handle/name (containment or edit distance <= 2), or it is the ONLY account of its platform
    linked from a page whose title/h1 names a known handle/name.
  - reasons are counters only (no handles, no URLs) so they are safe to log.
Stdlib only; never raises.
"""
import concurrent.futures as _cf
import html as _html
import ipaddress
import os
import re
import time
import urllib.parse
import urllib.request

import leak_scanner          # HEADERS + TLS context of the existing page fetcher
import profile_extract
from netloc import registrable_domain

MAX_PAGES = 4
FETCH_TIMEOUT = 6.0          # s per page
FETCH_TOTAL = 6.0            # s for all pages (parallel); must stay <= 12
BODY_CAP = 1024 * 1024
MIN_LEN = 4
# Test hook: the local real-path run serves its fake leak site on 127.0.0.1 (declared bypass).
ALLOW_LOOPBACK = os.environ.get("ALIAS_FETCH_ALLOW_LOOPBACK", "0").lower() in ("1", "true", "yes")

PLATFORMS = ("onlyfans", "fansly", "instagram", "x", "tiktok", "patreon")
_SKIP_HOSTS = {"instagram.com", "tiktok.com", "x.com", "twitter.com", "youtube.com", "youtu.be", "reddit.com",
               "facebook.com", "onlyfans.com", "fansly.com", "patreon.com", "linktr.ee", "google.com"}
# generic words and site names that are never a creator's handle
BANNED = {"onlyfans", "fansly", "instagram", "twitter", "tiktok", "patreon", "leaked", "leaks", "leak", "free",
          "porn", "nude", "nudes", "naked", "video", "videos", "photos", "photo", "pics", "gallery", "models",
          "model", "home", "login", "signup", "register", "explore", "search", "share", "intent", "official",
          "premium", "content", "creator", "creators", "download", "telegram", "discord", "support", "help",
          "privacy", "terms", "about", "contact", "watch", "online", "latest", "update", "updates", "page",
          "profile", "account", "accounts", "post", "posts", "media", "hd", "new", "only", "fans", "tags", "tag"}
_BAD_SUB = ("leak", "porn", "nude", "free", "onlyfans", "fansly", "xxx", "sex")
_NAME_STOP = BANNED | {"of", "the", "and", "by", "from", "on", "in", "a", "an", "aka", "vip", "full", "set",
                       "pack", "mega", "uncensored", "exclusive", "hot", "sexy", "best"}

_HREF_RE = re.compile(r"""<a\b[^>]*?\bhref\s*=\s*["']([^"'<>\s]{1,400})["']""", re.I)
_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.I | re.S)
_H1_RE = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_AT_RE = re.compile(r"(?<![\w.@/])@([A-Za-z0-9._]{3,40})")
_SPLIT_RE = re.compile(r"\s+[|\-–—:•·/]\s+|\s*[|•·]\s*|\(|\)|\[|\]")
_WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'À-ɏ]{1,20}$")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _text(frag):
    return re.sub(r"\s+", " ", _html.unescape(_TAG_RE.sub(" ", frag or ""))).strip()


def edit_distance(a, b, cap=3):
    """Levenshtein distance, early-out once it exceeds cap (returns cap+1)."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def similar(cand, known_norms):
    """Normalised containment (shorter >= 6 chars and a prefix of / >= 2/3 of the longer) or edit
    distance <= 2 (both >= 6 chars)."""
    c = norm(cand)
    if len(c) < MIN_LEN:
        return False
    for k in known_norms:
        if not k:
            continue
        if c == k:
            return True
        short, long_ = (c, k) if len(c) <= len(k) else (k, c)
        if len(short) >= 6 and short in long_ and (long_.startswith(short) or 3 * len(short) >= 2 * len(long_)):
            return True
        if len(c) >= 6 and len(k) >= 6 and edit_distance(c, k) <= 2:
            return True
    return False


def banned(h, site_words=()):
    n = norm(h)
    if len(n) < MIN_LEN or n.isdigit() or n in BANNED or any(b in n for b in _BAD_SUB):
        return True
    return any(w and len(w) >= 4 and w in n for w in site_words)


def name_variants(name):
    """'Mira Example' -> ['miraexample', 'mira_example', 'mira.example']."""
    w = [x.lower() for x in name.split()]
    return list(dict.fromkeys(["".join(w), "_".join(w), ".".join(w)]))


def person_name(text):
    """First title/h1 segment that reads like a 2-3 word person name, generic words stripped."""
    for seg in _SPLIT_RE.split(text or ""):
        words = [x for x in re.split(r"\s+", (seg or "").strip()) if x]
        words = [x for x in words if x.lower().strip("'") not in _NAME_STOP]
        if 2 <= len(words) <= 3 and all(_WORD_RE.match(x) and x[0].isupper() for x in words):
            return " ".join(words)
    return None


# ── fetching ────────────────────────────────────────────────────────────────
def _host_allowed(url):
    try:
        pu = urllib.parse.urlparse(url)
    except ValueError:
        return False
    host = (pu.hostname or "").lower()
    if pu.scheme not in ("http", "https") or not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return ALLOW_LOOPBACK
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    if ip.is_loopback:
        return ALLOW_LOOPBACK
    return not (ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


class _SameSite(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if registrable_domain(newurl) != registrable_domain(req.full_url) or not _host_allowed(newurl):
            return None                                   # never follow a redirect off the site
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SameSite, urllib.request.HTTPSHandler(context=leak_scanner.CTX))


def urlopen(req, timeout):
    """Page fetch wire (tests patch this)."""
    return _OPENER.open(req, timeout=timeout)


def fetch_page(url, timeout=FETCH_TIMEOUT, cap=BODY_CAP, deadline=None):
    """GET one leak page -> html text ('' on any failure / non-html / oversize stop). Never raises."""
    if not _host_allowed(url):
        return ""
    deadline = deadline or (time.monotonic() + timeout)
    try:
        req = urllib.request.Request(url, headers=leak_scanner.HEADERS)
        with urlopen(req, timeout=max(0.5, min(timeout, deadline - time.monotonic()))) as r:
            if (getattr(r, "status", None) or r.getcode()) != 200:
                return ""
            ctype = (r.headers.get("Content-Type") or "text/html").lower()
            if "html" not in ctype:
                return ""
            buf = b""
            while len(buf) < cap and time.monotonic() < deadline:
                chunk = r.read(min(65536, cap - len(buf)))
                if not chunk:
                    break
                buf += chunk
        return buf[:cap].decode("utf-8", "replace")
    except Exception:
        return ""


# ── extraction ──────────────────────────────────────────────────────────────
def social_of(href):
    """Link -> (platform, handle) for the six creator platforms, else None."""
    a = profile_extract._account_of(_html.unescape(href or ""))
    if not a or a[0] not in PLATFORMS:
        return None
    if a[0] == "tiktok" and "/@" not in href:
        return None
    return a


def extract(page_html):
    """-> {title, h1, socials:[(platform, handle)], ats:[handle], name}"""
    title = _text((_TITLE_RE.search(page_html) or [None, ""])[1])[:300]
    h1 = _text((_H1_RE.search(page_html) or [None, ""])[1])[:300]
    desc = ""
    for m in profile_extract._META_RE.finditer(page_html[:200000]):
        attrs = {k.lower(): v for k, v in profile_extract._ATTR_RE.findall(m.group(0))}
        if (attrs.get("name") or attrs.get("property") or "").lower() in ("description", "og:description"):
            desc = _html.unescape(attrs.get("content") or "")[:500]
            break
    socials, seen = [], set()
    for href in _HREF_RE.findall(page_html):
        a = social_of(href)
        if a and (a[0], a[1].lower()) not in seen:
            seen.add((a[0], a[1].lower()))
            socials.append(a)
    ats = list(dict.fromkeys(h.rstrip(".") for h in _AT_RE.findall(f"{title} {h1} {desc}")))
    name = person_name(h1) or person_name(title)
    return {"title": title, "h1": h1, "socials": socials, "ats": ats, "name": name}


def pick_pages(rows, results, cap=MAX_PAGES):
    """Highest-occurrence domains first, one page per domain, pages only."""
    import public_app    # lazy: result_kind lives there (no import cycle at load time)
    by_dom = {}
    for it in results or []:
        link = it.get("link") or ""
        d = registrable_domain(it.get("host") or link)
        if not d or d in _SKIP_HOSTS or d in by_dom or public_app.result_kind(it) != "page":
            continue
        by_dom[d] = link
    out = []
    for r in rows or []:
        d = registrable_domain(r.get("domain") or "")
        if d in by_dom and by_dom[d] not in out:
            out.append(by_dom[d])
        if len(out) >= cap:
            break
    return out


def discover(rows, results, known, names=(), fetch=None, budget=FETCH_TOTAL):
    """First-pass rows/results + known handles (scanned + declared) -> discovered aliases/socials."""
    t0 = time.monotonic()
    fetch = fetch or fetch_page
    out = {"aliases": [], "socials": [], "names": [], "reasons": {}, "pages": 0, "cand": 0, "kept": 0, "secs": 0.0}
    why = out["reasons"]
    bump = lambda k: why.__setitem__(k, why.get(k, 0) + 1)
    pages = pick_pages(rows, results)
    if not pages or budget <= 0:
        out["secs"] = round(time.monotonic() - t0, 2)
        return out
    deadline = t0 + min(budget, 12.0)
    ex = _cf.ThreadPoolExecutor(max_workers=len(pages))
    futs = {ex.submit(fetch, u, min(FETCH_TIMEOUT, budget), BODY_CAP, deadline): u for u in pages}
    done, _ = _cf.wait(futs, timeout=max(0.1, deadline - time.monotonic()))
    ex.shutdown(wait=False, cancel_futures=True)
    parsed = []
    for f, u in futs.items():                       # page order (= occurrence rank), not finish order
        try:
            body = f.result() if f in done else ""
        except Exception:
            body = ""
        if body:
            parsed.append((registrable_domain(u), extract(body)))
        else:
            bump("fetch_fail")
    out["pages"] = len(parsed)
    known_l = {k.lower() for k in known if k}
    known_n = {norm(k) for k in list(known) + list(names) if k}
    site_words = {norm(d.split(".")[0]) for d, _ in parsed} | {
        norm(registrable_domain(r.get("domain") or "").split(".")[0]) for r in rows or []}
    site_words = {w for w in site_words if not any(w in k for k in known_n)}   # her own site stays

    def on_identity(p):
        hay = norm(p["title"] + " " + p["h1"])
        return any(k and len(k) >= MIN_LEN and k in hay for k in known_n)

    socials, aliases, disp, pending = [], [], [], []
    seen_s, seen_a = set(), set(known_n)

    def add_alias(h):
        n = norm(h)
        if n not in seen_a and h.lower() not in known_l:
            seen_a.add(n)
            aliases.append(h)

    def keep_social(dom, plat, h, reason):
        bump(reason)
        if (plat, h.lower()) not in seen_s:
            seen_s.add((plat, h.lower()))
            socials.append({"platform": plat, "handle": h, "url": profile_extract._canonical_url(plat, h),
                            "source_domain": dom})
            add_alias(h)

    # pass 1: links -- similar to a known handle/name, or the ONLY account of its platform on a page
    # whose title/h1 names her (a "related models" sidebar links many -> none pass that way)
    for dom, p in parsed:
        ident = on_identity(p)
        per_plat = {}
        for plat, h in p["socials"]:
            per_plat.setdefault(plat, []).append(h)
        for plat, hs in per_plat.items():
            for h in hs:
                out["cand"] += 1
                if banned(h, site_words):
                    bump("banned")
                elif similar(h, known_n):
                    keep_social(dom, plat, h, "similar")
                elif ident and len(hs) == 1:
                    keep_social(dom, plat, h, "identity_page")
                else:
                    pending.append(h)
        if p["name"] and (ident or similar(p["name"], known_n)):
            disp.append(p["name"])
    known_n |= {norm(s["handle"]) for s in socials}
    # pass 2: @tokens, person-name variants, leftover links -- similarity gate only
    cands = list(pending)
    for _, p in parsed:
        news = list(p["ats"]) + (name_variants(p["name"]) if p["name"] else [])
        out["cand"] += len(news)
        cands += news
    for h in dict.fromkeys(cands):
        if not profile_extract.valid_handle(h) or banned(h, site_words):
            bump("banned")
        elif similar(h, known_n):
            bump("similar")
            add_alias(h)
        else:
            bump("dissimilar")
    out.update(aliases=aliases, socials=socials, names=list(dict.fromkeys(disp))[:4],
               kept=len(socials) + len({norm(a) for a in aliases} - {norm(x["handle"]) for x in socials}),
               secs=round(time.monotonic() - t0, 2))
    return out


def reasons_str(reasons):
    return ",".join(f"{k}:{v}" for k, v in sorted(reasons.items())) or "-"

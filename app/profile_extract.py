"""
Per-scan public profile for the quick scan (stdlib only).

collect_sources() gathers raw public evidence for a handle (Instagram crawler-UA
og tags + best-effort web_profile_info, generic og tags for tiktok/patreon/
fansly, the scan's own Google items), extract_profile() turns it into one small
SFW profile JSON via a single DeepSeek JSON-mode call, validated against a fixed
schema; fallback_profile() builds the same shape without any LLM.

Outbound fetches: fixed https hosts only, short timeouts, byte caps, no
redirects. No user-controlled URL is ever fetched: page URLs are built from the
re-validated handle, avatar URLs must sit on a fixed CDN allowlist.
"""

import concurrent.futures as _cf
import html as _html
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

HANDLE_RE = re.compile(r"^[A-Za-z0-9._-]{1,60}$")
FETCH_TIMEOUT = 6
HTML_CAP = 512 * 1024
AVATAR_CAP = 256 * 1024
GOOGLE_CAP = 20
LLM_TIMEOUT = float(os.environ.get("PROFILE_LLM_TIMEOUT", "15"))
LLM_MAX_TOKENS = 800
PROFILE_BUDGET = float(os.environ.get("PROFILE_BUDGET", "20"))

IG_APP_ID = "936619743392459"
CRAWLER_UA = "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Only these hosts are ever fetched for profile pages.
FETCH_HOSTS = frozenset({"www.instagram.com", "www.tiktok.com", "www.patreon.com", "fansly.com"})
OG_PAGES = {  # platform -> profile page template (generic og only)
    "tiktok": "https://www.tiktok.com/@{h}",
    "patreon": "https://www.patreon.com/{h}",
    "fansly": "https://fansly.com/{h}",
}
# Avatar images may only come from these CDN suffixes.
AVATAR_HOST_SUFFIXES = ("cdninstagram.com", "fbcdn.net", "tiktokcdn.com", "tiktokcdn-us.com", "tiktokcdn-eu.com",
                        "patreonusercontent.com", "fansly.com")

# accounts[].platform -> allowed registrable domains
ACCOUNT_DOMAINS = {
    "instagram": ("instagram.com",), "tiktok": ("tiktok.com",), "x": ("x.com", "twitter.com"),
    "youtube": ("youtube.com",), "onlyfans": ("onlyfans.com",), "fansly": ("fansly.com",),
    "patreon": ("patreon.com",), "linktree": ("linktr.ee",), "beacons": ("beacons.ai",),
    "twitch": ("twitch.tv",), "manyvids": ("manyvids.com",), "threads": ("threads.net",),
}
_DOMAIN_TO_PLATFORM = {d: p for p, ds in ACCOUNT_DOMAINS.items() for d in ds}
_PATH_SKIP = {"p", "reel", "reels", "stories", "explore", "tv", "accounts", "direct", "watch",
              "video", "search", "hashtag", "i", "intent", "share", "home", "login", "tag",
              "channel", "c", "user", "status", "posts", "shorts", "about"}

CAPS = {"display_name": 60, "first_name": 40, "tagline": 90, "profession": 60,
        "location": 60, "bio": 300, "about_short": 420}
MAX_ACCOUNTS = 8
_UNSAFE_RE = re.compile(r"\b(?:leak\w*|nudes?|naked|porn\w*|xxx|nsfw|sex\w*|explicit|"
                        r"adult|18\+|onlyfans\s+leaks?)", re.I)
_SITE_RE = re.compile(r"^[a-z0-9-]{1,40}\.com$")
_FOLLOWERS_RE = re.compile(r"([\d][\d,.]*)\s*([KMB])?\s*Followers", re.I)
_META_RE = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR_RE = re.compile(r'([a-zA-Z:_-]+)\s*=\s*"([^"]*)"')


# ----------------------------------------------------------------- fetching
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def urlopen(req, timeout=FETCH_TIMEOUT):
    """Default fetcher: urllib without redirects."""
    return _OPENER.open(req, timeout=timeout)


def valid_handle(h):
    return bool(h) and isinstance(h, str) and bool(HANDLE_RE.match(h))


def _host_ok(url, hosts=None, suffixes=None):
    try:
        pu = urllib.parse.urlparse(url or "")
    except ValueError:
        return False
    host = (pu.hostname or "").lower()
    if pu.scheme != "https" or not host or pu.port not in (None, 443):
        return False
    if hosts is not None:
        return host in hosts
    return any(host == s or host.endswith("." + s) for s in suffixes or ())


def _get(fetch, url, headers, cap, timeout):
    """GET a fixed-host https URL -> (bytes, content_type) or None. Never raises."""
    if not _host_ok(url, hosts=FETCH_HOSTS) and not _host_ok(url, suffixes=AVATAR_HOST_SUFFIXES):
        return None
    try:
        req = urllib.request.Request(url, headers=headers)
        with fetch(req, timeout=timeout) as r:
            status = getattr(r, "status", None) or r.getcode()
            if status != 200:
                return None
            body = r.read(cap + 1)
            ctype = (r.headers.get("Content-Type") or "").lower()
        return body, ctype
    except Exception:
        return None


def parse_og(html_text):
    """{'title','description','image'} from og meta tags (attribute order agnostic)."""
    out = {}
    for tag in _META_RE.findall(html_text or ""):
        attrs = {k.lower(): v for k, v in _ATTR_RE.findall(tag)}
        prop = (attrs.get("property") or attrs.get("name") or "").lower()
        if prop in ("og:title", "og:description", "og:image") and "content" in attrs:
            key = prop[3:]
            if key not in out:
                out[key] = unicodedata.normalize("NFKC", _html.unescape(attrs["content"])).strip()
    return out


def parse_followers(s):
    """'686M Followers' -> 686000000; '1,234 Followers' -> 1234; else None."""
    m = _FOLLOWERS_RE.search(s or "")
    if not m:
        return None
    try:
        num = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return int(num * {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[(m.group(2) or "").upper()])


def name_from_title(title, handle):
    """'Mira Example (@mira.example) • Instagram…' -> 'Mira Example' (only for this handle)."""
    m = re.search(r"([^()|•·\-–—]{1,80}?)\s*\(@" + re.escape(handle) + r"\)", title or "", re.I)
    if not m:
        return None
    name = m.group(1).strip(" \t\"'")
    return name or None


def _names_handle(og, handle):
    """Platforms serve generic og for unknown profiles: only trust og that names the handle."""
    return handle.lower() in ((og.get("title") or "") + " " + (og.get("description") or "")).lower()


def _ig_html(fetch, handle):
    got = _get(fetch, f"https://www.instagram.com/{handle}/",
               {"User-Agent": CRAWLER_UA, "Accept": "text/html"}, HTML_CAP, FETCH_TIMEOUT)
    if not got:
        return None
    og = parse_og(got[0][:HTML_CAP].decode("utf-8", "replace"))
    if not og.get("title") or not _names_handle(og, handle):
        return None
    return {"full_name": name_from_title(og.get("title"), handle),
            "followers": parse_followers(og.get("description")),
            "avatar_url": og.get("image"), "biography": None, "bio_links": []}


def _ig_api(fetch, handle):
    got = _get(fetch, "https://www.instagram.com/api/v1/users/web_profile_info/?username=" + handle,
               {"User-Agent": BROWSER_UA, "X-IG-App-ID": IG_APP_ID, "Accept": "application/json"},
               HTML_CAP, FETCH_TIMEOUT)
    if not got:
        return None
    try:
        user = (json.loads(got[0].decode("utf-8", "replace")).get("data") or {}).get("user")
    except Exception:
        return None
    if not isinstance(user, dict):
        return None
    links = [l.get("url") for l in (user.get("bio_links") or []) if isinstance(l, dict)]
    if user.get("external_url"):
        links.insert(0, user["external_url"])
    try:
        followers = int((user.get("edge_followed_by") or {}).get("count"))
    except (TypeError, ValueError):
        followers = None
    return {"full_name": (user.get("full_name") or "").strip() or None, "followers": followers,
            "avatar_url": user.get("profile_pic_url_hd") or user.get("profile_pic_url"),
            "biography": (user.get("biography") or "").strip() or None,
            "bio_links": [u for u in links if isinstance(u, str) and u][:10]}


def _og_page(fetch, platform, handle):
    url = OG_PAGES[platform].format(h=handle)
    got = _get(fetch, url, {"User-Agent": CRAWLER_UA, "Accept": "text/html"}, HTML_CAP, FETCH_TIMEOUT)
    if not got:
        return None
    og = parse_og(got[0][:HTML_CAP].decode("utf-8", "replace"))
    if not og.get("title") or not _names_handle(og, handle):
        return None
    return {"url": url, "title": og.get("title"), "description": og.get("description"),
            "image": og.get("image")}


def _short_platform(platform):
    return (platform or "").lower().split(".")[0]


def collect_sources(platform, handle, cse_items, fetch=urlopen):
    """Raw public evidence for one handle. Fetches run in parallel; each fails soft."""
    src = {"handle": handle, "platform": _short_platform(platform),
           "instagram": None, "og": None, "google": []}
    for it in (cse_items or [])[:200]:
        link = it.get("link") if isinstance(it, dict) else None
        if not link:
            continue
        src["google"].append({"title": (it.get("title") or "")[:200], "link": link[:300],
                              "snippet": (it.get("snippet") or "")[:300]})
    # Official-platform items first: they carry the useful name/bio facts.
    src["google"].sort(key=lambda g: _account_of(g["link"]) is None)
    src["google"] = src["google"][:GOOGLE_CAP]
    if not valid_handle(handle):
        return src
    og_targets = ["tiktok"]
    if src["platform"] in OG_PAGES and src["platform"] not in og_targets:
        og_targets.append(src["platform"])
    with _cf.ThreadPoolExecutor(max_workers=2 + len(og_targets)) as ex:
        f_html = ex.submit(_ig_html, fetch, handle)
        f_api = ex.submit(_ig_api, fetch, handle)
        f_og = {p: ex.submit(_og_page, fetch, p, handle) for p in og_targets}
        html_res, api_res = f_html.result(), f_api.result()
        og = {p: f.result() for p, f in f_og.items()}
    if html_res or api_res:
        ig = dict(html_res or {})
        for k, v in (api_res or {}).items():   # API fields win when present
            if v not in (None, [], ""):
                ig[k] = v
        for k in ("full_name", "followers", "avatar_url", "biography", "bio_links"):
            ig.setdefault(k, [] if k == "bio_links" else None)
        src["instagram"] = ig
    og = {p: v for p, v in og.items() if v}
    src["og"] = og or None
    return src


def avatar_candidates(sources):
    out = []
    ig = sources.get("instagram") or {}
    if ig.get("avatar_url"):
        out.append(ig["avatar_url"])
    for v in (sources.get("og") or {}).values():
        if v.get("image"):
            out.append(v["image"])
    return [u for u in out if _host_ok(u, suffixes=AVATAR_HOST_SUFFIXES)]


def _image_ext(data):
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def fetch_avatar(sources, fetch=urlopen, timeout=FETCH_TIMEOUT):
    """First allowlisted og avatar -> (bytes, ext) or None. ≤256KB, image/* + magic check."""
    for url in avatar_candidates(sources)[:2]:
        got = _get(fetch, url, {"User-Agent": BROWSER_UA, "Accept": "image/*"}, AVATAR_CAP, timeout)
        if not got:
            continue
        data, ctype = got
        if len(data) > AVATAR_CAP or not ctype.startswith("image/"):
            continue
        ext = _image_ext(data)
        if ext:
            return data, ext
    return None


# --------------------------------------------------------------- prompting
SYSTEM_PROMPT = """You write a short public profile of an online creator for a demo website.
You receive SOURCES: raw public data (Instagram page data, other profile page tags, Google results).

HARD RULES:
- Use ONLY facts present in the SOURCES. If a field is not supported by the sources, use null.
- Never invent a location, profession, age, or real name. A display name is allowed only if it \
appears in the sources.
- accounts: only profiles whose URL appears in the sources (or the scanned account itself).
- Write in the third person. Safe-for-work copy only: no sexual or adult wording, no mention of \
leaks, piracy, scans or removals.
- Output JSON only, one object, exactly these keys:
{"display_name": str|null, "first_name": str|null, "tagline": str|null (<=90 chars),
 "profession": str|null, "location": str|null, "bio": str|null (<=300 chars),
 "about_short": str|null (<=420 chars, 2-3 sentences), "followers": int|null,
 "accounts": [{"platform": "instagram|tiktok|x|youtube|onlyfans|fansly|patreon|linktree|beacons|twitch|threads", "handle": str, "url": "https://..."}],
 "site_domain": str|null (lowercase, like "firstnamelastname.com" or "username.com"),
 "confidence": number 0..1 (how sure you are these sources describe one person)}"""


def build_prompt(sources):
    """-> chat messages. Sources go in as JSON so nothing is paraphrased away."""
    payload = {
        "scanned_account": {"platform": sources.get("platform"), "handle": sources.get("handle")},
        "instagram": sources.get("instagram"),
        "other_profile_pages": sources.get("og"),
        "google_results": sources.get("google") or [],
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "SOURCES:\n" + json.dumps(payload, ensure_ascii=False)},
    ]


def deepseek_json(messages, timeout=LLM_TIMEOUT, api_key=None, model=None):
    """One non-streaming DeepSeek JSON-mode call -> parsed dict. Raises on any failure."""
    import chat_proxy   # DEEPSEEK_URL lives there (single source)
    key = (api_key if api_key is not None else os.environ.get("DEEPSEEK_API_KEY", "")).strip()
    if not key:
        raise RuntimeError("no DEEPSEEK_API_KEY")
    mdl = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    body = {"model": mdl, "stream": False, "temperature": 0.2, "max_tokens": LLM_MAX_TOKENS,
            "response_format": {"type": "json_object"}, "messages": messages}
    if mdl.startswith("deepseek-v4"):
        body["thinking"] = {"type": "disabled"}
    req = urllib.request.Request(
        chat_proxy.DEEPSEEK_URL, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read(1_000_000).decode("utf-8"))
    content = d["choices"][0]["message"]["content"]
    out = json.loads(content)
    if not isinstance(out, dict):
        raise ValueError("not an object")
    return out


# --------------------------------------------------------------- validation
def _account_of(url):
    """Profile URL on a known platform -> (platform, handle) or None."""
    try:
        pu = urllib.parse.urlparse(url or "")
    except ValueError:
        return None
    host = (pu.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    host = host[2:] if host.startswith("m.") else host
    plat = _DOMAIN_TO_PLATFORM.get(host)
    if not plat:
        return None
    seg = [s for s in pu.path.split("/") if s]
    if not seg:
        return None
    h = seg[0].lstrip("@")
    if plat == "youtube" and not seg[0].startswith("@"):
        return None
    if h.lower() in _PATH_SKIP or not valid_handle(h):
        return None
    return plat, h


def _evidence_accounts(sources):
    """{(platform, handle_lower): (canonical_url, handle)} for accounts backed by the sources."""
    found = {}
    h, plat = sources.get("handle"), sources.get("platform")

    def add(p, handle):
        if p in ACCOUNT_DOMAINS and valid_handle(handle):
            found.setdefault((p, handle.lower()), (_canonical_url(p, handle), handle))
    if plat in ACCOUNT_DOMAINS and valid_handle(h):
        add(plat, h)                                  # the scanned account itself
    if sources.get("instagram") and valid_handle(h):
        add("instagram", h)
        for u in sources["instagram"].get("bio_links") or []:
            a = _account_of(u)
            if a:
                add(*a)
    for p in (sources.get("og") or {}):
        add(p, h)
    for g in sources.get("google") or []:
        a = _account_of(g.get("link"))
        if a and h and a[1].lower() == h.lower():
            add(*a)
    return found


def _canonical_url(platform, handle):
    dom = ACCOUNT_DOMAINS[platform][0]
    if platform in ("tiktok", "youtube"):
        return f"https://www.{dom}/@{handle}"
    return f"https://{dom}/{handle}"


def _text(v, cap):
    if not isinstance(v, str):
        return None
    v = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", v)).strip()
    if not v or _UNSAFE_RE.search(v):
        return None
    if len(v) > cap:
        v = v[:cap - 1].rsplit(" ", 1)[0].rstrip(",;:- ") + "…"
    return v


def _site_from(name, handle):
    base = re.sub(r"[^a-z0-9]", "", (name or "").lower()) or re.sub(r"[^a-z0-9]", "", (handle or "").lower())
    return f"{base[:40]}.com" if base else None


def _source_followers(sources):
    """Followers from IG page data, else from a Google snippet of the IG profile itself."""
    ig = sources.get("instagram") or {}
    if isinstance(ig.get("followers"), int):
        return ig["followers"]
    h = (sources.get("handle") or "").lower()
    for g in sources.get("google") or []:
        a = _account_of(g.get("link"))
        if a and a[0] == "instagram" and a[1].lower() == h:
            n = parse_followers(g.get("snippet"))
            if n:
                return n
    return None


def _source_urls(sources, accounts):
    out = [a["url"] for a in accounts]
    have = {(a["platform"], a["handle"].lower()) for a in accounts}
    h = (sources.get("handle") or "").lower()
    for g in sources.get("google") or []:
        a = _account_of(g.get("link"))
        if a and a[1].lower() == h and (a[0], h) not in have:
            have.add((a[0], h))
            out.append(g["link"])
    return out[:10]


def validate_profile(raw, sources, generated_by="deepseek", avatar=False):
    """LLM dict -> schema-clean profile. Unknown keys dropped, types coerced,
    lengths capped, accounts restricted to evidence-backed profiles."""
    raw = raw if isinstance(raw, dict) else {}
    handle = sources.get("handle") or ""
    p = {k: _text(raw.get(k), cap) for k, cap in CAPS.items()}
    if p["display_name"] is None:
        p["display_name"] = _text(source_name(sources), CAPS["display_name"])
    evidence = _evidence_accounts(sources)
    accounts, seen = [], set()
    for a in raw.get("accounts") if isinstance(raw.get("accounts"), list) else []:
        if not isinstance(a, dict):
            continue
        plat, h, url = a.get("platform"), a.get("handle"), a.get("url")
        if not (isinstance(plat, str) and isinstance(h, str) and isinstance(url, str)):
            continue
        plat, h = plat.lower().strip(), h.strip().lstrip("@")
        if plat not in ACCOUNT_DOMAINS or not valid_handle(h) or (plat, h.lower()) in seen:
            continue
        if not _host_ok(url, suffixes=ACCOUNT_DOMAINS[plat]) or len(url) > 200:
            continue
        if (plat, h.lower()) not in evidence:
            continue                                   # not backed by any source
        seen.add((plat, h.lower()))
        url, h = evidence[(plat, h.lower())]
        accounts.append({"platform": plat, "handle": h, "url": url})
    for (plat, hl), (url, h) in evidence.items():     # evidence-backed accounts the LLM skipped
        if (plat, hl) not in seen:
            seen.add((plat, hl))
            accounts.append({"platform": plat, "handle": h, "url": url})
    site = raw.get("site_domain")
    site = site.strip().lower() if isinstance(site, str) else None
    if not site or not _SITE_RE.match(site):
        site = _site_from(p["display_name"], handle)
    try:
        conf = float(raw.get("confidence"))
        conf = min(1.0, max(0.0, conf)) if conf == conf else 0.0
    except (TypeError, ValueError):
        conf = 0.0
    p.update({
        "username": handle, "platform": sources.get("platform") or None,
        "followers": _source_followers(sources), "accounts": accounts[:MAX_ACCOUNTS],
        "site_domain": site, "avatar": bool(avatar),
        "sources": _source_urls(sources, accounts[:MAX_ACCOUNTS]),
        "confidence": round(conf, 2), "generated_by": generated_by,
    })
    if p["first_name"] is None and p["display_name"]:
        p["first_name"] = _text(p["display_name"].split(" ")[0], CAPS["first_name"])
    return p


def source_name(sources):
    """Display name stated by the sources: IG full_name, else '<Name> (@handle)' in a title."""
    handle = sources.get("handle") or ""
    name = (sources.get("instagram") or {}).get("full_name")
    titles = [v.get("title") for v in (sources.get("og") or {}).values()] + \
             [g.get("title") for g in sources.get("google") or []]
    for t in titles:
        if name:
            break
        name = name_from_title(t, handle)
    return name


def fallback_profile(sources, avatar=False):
    """No-LLM profile: only directly-extracted facts."""
    handle = sources.get("handle") or ""
    ig = sources.get("instagram") or {}
    name = source_name(sources)
    raw = {"display_name": name, "bio": ig.get("biography"),
           "confidence": 0.6 if ig else (0.3 if name else 0.1)}
    p = validate_profile(raw, sources, generated_by="fallback", avatar=avatar)
    if p["display_name"] is None and handle:
        p["display_name"] = handle
    return p


def extract_profile(sources, llm=deepseek_json, timeout=LLM_TIMEOUT, avatar=False):
    """One LLM call -> validated profile; any failure -> fallback_profile."""
    try:
        raw = llm(build_prompt(sources), timeout=timeout)
        return validate_profile(raw, sources, generated_by="deepseek", avatar=avatar)
    except Exception:
        return fallback_profile(sources, avatar=avatar)


def build_profile(platform, handle, cse_items, fetch=None, llm=None, budget=PROFILE_BUDGET):
    """collect -> avatar -> extract inside a total time budget.
    Returns (profile, avatar_bytes_and_ext_or_None, sources)."""
    fetch, llm = fetch or urlopen, llm or deepseek_json   # resolved per call (patchable)
    t0 = time.monotonic()
    sources = collect_sources(platform, handle, cse_items, fetch=fetch)
    remaining = lambda: budget - (time.monotonic() - t0)
    av = fetch_avatar(sources, fetch=fetch, timeout=min(FETCH_TIMEOUT, max(1, remaining() - 3))) \
        if remaining() > 4 else None
    llm_timeout = min(LLM_TIMEOUT, remaining() - 0.5)
    if llm_timeout < 2:
        return fallback_profile(sources, avatar=bool(av)), av, sources
    return extract_profile(sources, llm=llm, timeout=llm_timeout, avatar=bool(av)), av, sources

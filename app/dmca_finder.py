#!/usr/bin/env python3
"""
DMCA / abuse contact finder — where do I send the takedown for this domain?

For each domain it:
  1. Fetches the likely contact pages (/dmca, /abuse, /copyright, /contact,
     /legal, /terms, /report, /takedown, /static/dmca, ... + the homepage) and
     scrapes every email it can see — `mailto:` links, "name [at] site [dot] com"
     obfuscation, **Cloudflare `__cf_email__` / `/cdn-cgi/l/email-protection`
     hex obfuscation**, whole-email HTML-entity encoding, `String.fromCharCode`
     built addresses, emails split by `<wbr>`/comments/zero-width chars,
     **CSS `::before`/`::after` content injection** (e.g. `.email::before{content:
     "admincrew"}` + `<span class="email">@site.com</span>` -> admincrew@site.com),
     and bracketed **`name [at] site.com`** (literal-dot domain).
  When a site exposes NO address but takes notices via a web form, it records the
  `contact_form` URL (a <form> with a message/complaint field, on /dmca or /contact).
  2. Falls back to RDAP (the modern WHOIS) at rdap.org for the registrar/registry
     **abuse** contact — useful when the site hides its own email.
  3. Picks a best_email by priority: dmca@ > abuse@ > copyright@ > legal@ >
     takedown@ > support@ > info@ > contact@ > anything else, and records which
     page each address came from so you can verify before sending.

Input (any of):
  * positional domains
  * --in FILE         one domain per line
  * (default)         every domain in bruqi_detection_map.json

Outputs <prefix>.csv (domain, best_email, all_emails, dmca_page, rdap_abuse,
registrar) and <prefix>.txt (domain<TAB>best_email). Stdlib only.

Usage
-----
    python3 dmca_finder.py nudostar.tv fapeza.com wildskirts.com
    python3 dmca_finder.py --in domains.txt --out contacts
    python3 dmca_finder.py                       # all mapped domains
    python3 dmca_finder.py fapeza.com --no-rdap  # skip WHOIS/RDAP
"""

import argparse
import concurrent.futures as cf
import csv
import gzip
import json
import os
import re
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
HEADERS = {
    "accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "accept-encoding": "identity",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
}

# candidate paths most likely to carry a takedown/abuse address — homepage FIRST
# so the site-wide footer (often the only place an abuse address lives) is always scanned.
# `/static/*`, `/pages/*`, `/p/*` cover the common CMS layouts (camcaps-style sites put
# their DMCA page at /static/dmca) for the cases where the footer doesn't link it.
PATHS = ["/", "/dmca", "/dmca/", "/dmca.html", "/dmca.php", "/dmca-policy",
         "/dmca-takedown", "/dmca-notice", "/copyright", "/copyright-policy",
         "/copyright-infringement", "/abuse", "/report-abuse", "/legal", "/contact",
         "/contact-us", "/contact.html", "/contacts", "/report", "/takedown", "/removal",
         "/content-removal", "/2257", "/terms", "/terms-of-service", "/tos",
         "/privacy", "/about",
         "/static/dmca", "/static/copyright", "/static/2257", "/static/contact",
         "/static/terms", "/static/about", "/pages/dmca", "/page/dmca", "/p/dmca",
         "/info/dmca", "/info/contact-us", "/info/contact", "/info/abuse",
         "/info/2257", "/info/copyright", "/info/terms"]

EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
# obfuscated "dmca [at] site [dot] com" — require BRACKETED or whitespace-padded
# "at" AND a literal "dot" word, so we don't match "informATion.You" as inform@ion.you.
_AT = r"(?:\(\s*at\s*\)|\[\s*at\s*\]|\{\s*at\s*\}|\s+at\s+)"
_DOT = r"(?:\(\s*dot\s*\)|\[\s*dot\s*\]|\{\s*dot\s*\}|\s+dot\s+)"
OBFUS = re.compile(rf"([a-z0-9._%+\-]+)\s*{_AT}\s*([a-z0-9\-]+(?:\s*{_DOT}\s*[a-z0-9\-]+)+)", re.I)
# bracketed "[at]"/"(at)"/"{at}" is a high-confidence email marker (never normal prose),
# so allow a NORMAL literal-dot domain after it: `dmcamasterfap [at] protonmail.com`,
# `contact [at] reddxxx.com` — which the obfuscated-dot-only OBFUS above misses.
_BRACKET_AT = r"(?:\(\s*at\s*\)|\[\s*at\s*\]|\{\s*at\s*\})"
_DOTSEG = r"(?:\(\s*dot\s*\)|\[\s*dot\s*\]|\{\s*dot\s*\}|\.)"
OBFUS_BRACKET = re.compile(
    rf"([a-z0-9._%+\-]+)\s*{_BRACKET_AT}\s*([a-z0-9][a-z0-9\-]*(?:\s*{_DOTSEG}\s*[a-z0-9\-]+)+)", re.I)
DOT_SUB = re.compile(_DOT, re.I)
MAILTO = re.compile(r"""mailto:([^"'>?\s]+)""", re.I)
# Cloudflare email obfuscation: <span class="__cf_email__" data-cfemail="HEX"> and
# <a href="/cdn-cgi/l/email-protection#HEX">. First hex byte is an XOR key for the rest.
CF_EMAIL = re.compile(r"""(?:data-cfemail=["']|/cdn-cgi/l/email-protection#)([0-9a-fA-F]{6,})""")
# JS-assembled addresses: String.fromCharCode(100,109,99,97,64,...)
FROMCHARCODE = re.compile(r"fromCharCode\s*\(([0-9,\sx]+)\)", re.I)
# CSS pseudo-element obfuscation: <style>.email::before{content:"admincrew"}</style> +
# <span class="email">@site.com</span>  ->  admincrew@site.com. The local part (or the
# domain) is injected via CSS `content`, so the full address never appears as page text.
CSS_STYLE = re.compile(r"<style[^>]*>(.*?)</style>", re.I | re.S)
CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
CSS_CONTENT = re.compile(r"content\s*:\s*(['\"])(.*?)\1", re.I | re.S)


def cf_decode(hexstr):
    """Decode a Cloudflare-obfuscated email hex string (XOR by its first byte)."""
    try:
        key = int(hexstr[:2], 16)
        return "".join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))
    except (ValueError, IndexError):
        return ""


# zero-width / soft-hyphen / word-joiner chars sites slip into addresses to break
# scrapers — dropped (not spaced) so `dmca<zwsp>@<zwsp>site.com` reassembles cleanly.
_ZW = frozenset({0x200b, 0x200c, 0x200d, 0xfeff, 0x00ad, 0x2060, 0x180e})
_ZW_KILL = {c: None for c in _ZW}


def _safe_chr(cp):
    """Codepoint -> char for entity/charcode decoding. Zero-width chars vanish (so they
    can't split an address); control chars become spaces (token boundaries)."""
    if cp in _ZW:
        return ""
    if cp < 0x20 or cp == 0x7f:
        return " "
    try:
        return chr(cp)
    except (ValueError, OverflowError):
        return " "


def _css_unescape(s):
    """Decode CSS `\\HH` hex escapes (e.g. `\\0040` -> @) used inside content: strings."""
    return re.sub(r"\\([0-9a-fA-F]{1,6})\s?", lambda m: _safe_chr(int(m.group(1), 16)), s)


def emails_from_css(html):
    """Reconstruct emails hidden via CSS ::before/::after `content` injection — the
    local part (or domain) lives in a <style> rule, only the rest is real page text."""
    found = set()
    inject = {}   # selector-token -> {'before': str, 'after': str}
    for block in CSS_STYLE.findall(html):
        for sel, body in CSS_RULE.findall(block):
            m = CSS_CONTENT.search(body)
            if not m:
                continue
            val = _css_unescape(m.group(2))
            if not val.strip():
                continue
            for s in sel.split(","):
                s = s.strip()
                if re.search(r"::?before\b", s):
                    pseudo = "before"
                elif re.search(r"::?after\b", s):
                    pseudo = "after"
                else:
                    continue
                base = re.sub(r"::?(?:before|after)\b", "", s).strip()
                toks = re.findall(r"[.#]?[A-Za-z0-9_-]+", base)
                if toks:
                    inject.setdefault(toks[-1], {"before": "", "after": ""})[pseudo] += val
    for key, ba in inject.items():
        if key.startswith("."):
            pat = rf'<[a-zA-Z]+[^>]*class\s*=\s*["\'][^"\']*\b{re.escape(key[1:])}\b[^"\']*["\'][^>]*>([^<]*)'
        elif key.startswith("#"):
            pat = rf'<[a-zA-Z]+[^>]*id\s*=\s*["\']{re.escape(key[1:])}["\'][^>]*>([^<]*)'
        else:
            pat = rf'<{re.escape(key)}\b[^>]*>([^<]*)'
        for text in re.findall(pat, html, re.I):
            cand = ba["before"] + re.sub(r"\s+", "", text) + ba["after"]
            for e in EMAIL.findall(cand):
                e = clean_email(e)
                if e:
                    found.add(e)
    return found


def normalize_html(html):
    """Decode the @/. obfuscations crawlers use so the regexes see plain text,
    and turn other JS `\\uXXXX` escapes into spaces so they act as token boundaries
    (stops `copyright@github.com\\u003ecopyright@...` running two addresses together)."""
    html = html.replace("\\u0040", "@").replace("\\u002e", ".").replace("\\u002E", ".")
    html = re.sub(r"\\u[0-9a-fA-F]{4}", " ", html)
    # Decode ALL numeric HTML entities, not just @ and . — sites encode the whole
    # address (`&#100;&#109;&#99;&#97;@...`) to dodge naive scrapers.
    html = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: _safe_chr(int(m.group(1), 16)), html)
    html = re.sub(r"&#0*(\d+);", lambda m: _safe_chr(int(m.group(1) or "0")), html)
    html = re.sub(r"&commat;", "@", html, flags=re.I)
    html = re.sub(r"&period;", ".", html, flags=re.I)
    return html


# footer / header / nav link discovery: catch non-standard takedown pages
# (e.g. /pages/dmca-notice, /p/copyright) the fixed PATHS list would miss.
ANCHOR = re.compile(r"""<a\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""", re.I | re.S)
LINK_KW = re.compile(r"dmca|abuse|copyright|takedown|complaint|infringement|legal|2257|report|contact", re.I)
DMCA_HINT = re.compile(r"\bdmca\b|digital millennium|takedown|copyright|infringement", re.I)


def discover_contact_links(base, html):
    """URLs linked from the page (footer/header/menu) whose href or anchor text
    looks takedown-related — same site only, highest-value keywords first."""
    out, seen = [], set()
    for href, text in ANCHOR.findall(html):
        text = re.sub(r"<[^>]+>", " ", text)
        if not (LINK_KW.search(href) or LINK_KW.search(text)):
            continue
        try:
            absu = urllib.parse.urljoin(f"https://{base}/", href.strip()).split("#")[0]
            host = urllib.parse.urlparse(absu).netloc.lower().split(":")[0]
        except ValueError:
            continue   # malformed href (bad [..] netloc -> "Invalid IPv6 URL"); skip
        if not absu.startswith("http"):
            continue
        if not (host == base or host.endswith("." + base) or host == "www." + base):
            continue
        if absu not in seen:
            seen.add(absu)
            out.append(absu)
    # rank: dmca/copyright/takedown links before generic contact/terms
    out.sort(key=lambda u: 0 if re.search(r"dmca|copyright|takedown|abuse|infringe", u, re.I) else 1)
    return out[:15]

# contact/complaint FORM detection — many sites take takedowns ONLY via a web form
# (no email anywhere). A real complaint form has a <textarea> (the message) or fields
# named message/describe/url/infringement/etc — which search & login forms don't.
FORM = re.compile(r"<form\b[^>]*>(.*?)</form>", re.I | re.S)
HAS_TEXTAREA = re.compile(r"<textarea\b", re.I)
FORM_FIELD = re.compile(r"""(?:name|id|placeholder)\s*=\s*["'][^"']*"""
                        r"""(?:message|complain|describ|content|infring|copyright|detail|comment|subject|reason|takedown)"""
                        r"""[^"']*["']""", re.I)


def page_has_form(html):
    """True if the page has a contact/complaint form (a <form> with a textarea or a
    message/infringement-type field) — i.e. somewhere you can actually file a notice."""
    for body in FORM.findall(html):
        if HAS_TEXTAREA.search(body) or FORM_FIELD.search(body):
            return True
    return False


def _form_rank(url):
    """Prefer a form on a dmca/report page over a generic /contact form."""
    p = urllib.parse.urlparse(url).path.lower()
    if re.search(r"dmca|copyright|takedown|abuse|2257|infring|complain|report|removal", p):
        return 0
    if "contact" in p:
        return 1
    return 2


# noise: asset filenames, library/CDN sample addresses, placeholders
BAD_DOMAIN_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".css", ".js", ".ico")
BAD_SUBSTR = ("sentry.io", "wixpress.com", "example.com", "example.org", "yourdomain",
              "domain.com", "email.com", "yoursite", "sentry-next", "@2x", "@3x",
              "godaddy.com/", "schema.org", "w3.org", "googleapis.com")
# priority: lower index = better takedown target
PRIORITY = ["dmca", "abuse", "copyright", "takedown", "legal", "compliance",
            "complaints", "support", "admin", "info", "contact", "help", "hello"]
# auto-responder / unmonitored mailboxes — kept in the list but never chosen as best
NOREPLY = re.compile(r"no-?reply|do-?not-?reply|donotreply|mailer-daemon|postmaster|bounce", re.I)

MIN_INTERVAL = 0.0
_HOST_LOCK = threading.Lock()
_HOST_NEXT = {}


def _throttle(host):
    if MIN_INTERVAL <= 0:
        return
    with _HOST_LOCK:
        start = max(time.monotonic(), _HOST_NEXT.get(host, 0.0))
        _HOST_NEXT[host] = start + MIN_INTERVAL
    delay = start - time.monotonic()
    if delay > 0:
        time.sleep(delay)


def fetch(url, timeout, accept_json=False):
    host = urllib.parse.urlparse(url).netloc
    _throttle(host)
    hdrs = dict(HEADERS)
    if accept_json:
        hdrs["accept"] = "application/json,*/*"
    try:
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            raw = r.read(600000)
            if r.headers.get("content-encoding") == "gzip":
                raw = gzip.decompress(raw)
            return r.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def clean_email(e):
    e = e.strip().strip(".,;:<>()[]'\"").lower()
    if e.count("@") != 1 or "\\" in e or " " in e:
        return None
    local, dom = e.split("@")
    if not local or "." not in dom or dom.startswith(".") or dom.endswith("."):
        return None
    if dom.endswith(BAD_DOMAIN_EXT):
        return None
    if any(b in e for b in BAD_SUBSTR):
        return None
    if len(local) > 64 or re.fullmatch(r"[0-9a-f]{16,}", local):  # tracking hashes
        return None
    return e


def emails_from(html):
    found = set()
    for m in MAILTO.findall(html):
        e = clean_email(urllib.parse.unquote(m.split("?")[0]))
        if e:
            found.add(e)
    # Cloudflare __cf_email__ / email-protection hex (the common case on CF-fronted sites)
    for h in CF_EMAIL.findall(html):
        e = clean_email(cf_decode(h))
        if e:
            found.add(e)
    # CSS ::before/::after content injection (e.g. fapmenu.com: .email::before{content:"admincrew"})
    found |= emails_from_css(html)
    # JS String.fromCharCode(...) assembled addresses
    for nums in FROMCHARCODE.findall(html):
        s = "".join(_safe_chr(int(n, 16) if n.lower().startswith("0x") else int(n))
                    for n in re.findall(r"0x[0-9a-fA-F]+|\d+", nums))
        for e in EMAIL.findall(s):
            e = clean_email(e)
            if e:
                found.add(e)
    # plaintext + a variant with anti-scraper splits removed (<wbr>, HTML comments,
    # zero-width chars), so `dmca@cam<wbr>caps.to` and `dmca<!---->@site.com` reassemble
    deob = re.sub(r"<wbr\s*/?>|<!--.*?-->", "", html, flags=re.I | re.S).translate(_ZW_KILL)
    for text in (html, deob):
        for e in EMAIL.findall(text):
            e = clean_email(e)
            if e:
                found.add(e)
        for local, dom in OBFUS.findall(text):
            dom = re.sub(r"\s*[\[(]?\s*(?:dot|\.)\s*[\])]?\s*", ".", dom, flags=re.I)
            e = clean_email(f"{local}@{dom}")
            if e:
                found.add(e)
        for local, dom in OBFUS_BRACKET.findall(text):
            dom = re.sub(r"\s*[\[(]?\s*(?:dot|\.)\s*[\])]?\s*", ".", dom, flags=re.I)
            e = clean_email(f"{local}@{dom}")
            if e:
                found.add(e)
    return found


def score(email):
    local = email.split("@", 1)[0]
    base = next((i for i, kw in enumerate(PRIORITY) if kw in local), len(PRIORITY) + 1)
    if NOREPLY.search(local):
        base += 100   # demote unmonitored mailboxes below any real contact
    return base


def rdap_abuse(registrable, timeout):
    """Registrar/registry abuse email + registrar name via RDAP (modern WHOIS)."""
    status, body = fetch(f"https://rdap.org/domain/{registrable}", timeout, accept_json=True)
    if status != 200 or not body:
        return "", ""
    try:
        data = json.loads(body)
    except Exception:
        return "", ""
    abuse, registrar = [], ""

    def vcard_email(ent):
        out = []
        va = ent.get("vcardArray")
        if isinstance(va, list) and len(va) == 2:
            for item in va[1]:
                if isinstance(item, list) and len(item) >= 4 and item[0] == "email":
                    val = item[3]
                    out.append(val if isinstance(val, str) else (val[0] if val else ""))
        return [x for x in out if x]

    def walk(entities):
        nonlocal registrar
        for ent in entities or []:
            roles = ent.get("roles") or []
            if "registrar" in roles and not registrar:
                for item in (ent.get("vcardArray", ["", []])[1] or []):
                    if isinstance(item, list) and item[0] == "fn":
                        registrar = item[3] if isinstance(item[3], str) else registrar
            if "abuse" in roles:
                abuse.extend(vcard_email(ent))
            walk(ent.get("entities"))

    walk(data.get("entities"))
    best = ""
    for e in abuse:
        c = clean_email(e)
        if c:
            best = c
            break
    return best, registrar


def registrable(host):
    host = host.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def find_for(domain, args):
    base = registrable(domain)
    emails = {}        # email -> page it was first seen on
    dmca_page = ""
    form_url = ""
    form_rank = 9
    good_enough = PRIORITY.index("legal")   # dmca/abuse/copyright/takedown/legal -> stop early

    def _dedicated(u):   # is this a real takedown page, not just the homepage footer?
        return bool(re.search(r"dmca|copyright|takedown|infring|abuse", urllib.parse.urlparse(u).path, re.I))

    def scan(url):
        nonlocal dmca_page, form_url, form_rank
        status, html = fetch(url, args.timeout)
        if status != 200 or not html:
            return status, ""
        html = normalize_html(html)
        if DMCA_HINT.search(html[:30000]):
            # prefer a dedicated /dmca-style URL over the homepage footer mention
            if not dmca_page or (_dedicated(url) and not _dedicated(dmca_page)):
                dmca_page = url
        # remember where a takedown can be filed via web form (best on a dmca/report page)
        if page_has_form(html):
            r = _form_rank(url)
            if not form_url or r < form_rank:
                form_url, form_rank = url, r
        for e in emails_from(html):
            emails.setdefault(e, url)
        return status, html

    # 1) homepage first — its footer/header is where a site-wide abuse address lives,
    #    and its menu/nav links point at the real (often non-standard) takedown pages.
    deadline = time.monotonic() + args.domain_budget
    home = f"https://{base}/"
    home_status, home_html = scan(home)
    discovered = discover_contact_links(base, home_html) if home_html else []

    # 2) walk discovered links + fixed guesses, stopping once we have a solid target.
    #    Per-domain time budget: a slow/dead site with no email otherwise grinds all ~36
    #    paths at the socket timeout each, stalling the whole run on one straggler.
    seen = {home}
    for url in discovered + [f"https://{base}{p}" for p in PATHS[1:]]:
        if url in seen:
            continue
        seen.add(url)
        if emails and min(score(e) for e in emails) <= good_enough:
            break
        if time.monotonic() > deadline:
            break
        scan(url)

    # no address found but the site clearly links a takedown page (e.g. /dmca/)? keep it —
    # you can file via its web form even without a scrapeable email.
    if not dmca_page:
        for u in discovered:
            if re.search(r"dmca|copyright|takedown|2257|infring", urllib.parse.urlparse(u).path, re.I):
                dmca_page = u
                break

    rdap_email, registrar = ("", "")
    if not args.no_rdap:
        rdap_email, registrar = rdap_abuse(base, args.timeout)

    ranked = sorted(emails, key=lambda e: (score(e), e))
    best = ranked[0] if ranked else rdap_email
    return {
        "domain": base,
        "best_email": best,
        "all_emails": ";".join(ranked),
        "dmca_page": dmca_page,
        "contact_form": form_url,
        "rdap_abuse": rdap_email,
        "registrar": registrar,
        "_home_status": home_status,
        "_src": emails,
        "_discovered": discovered,
    }


def browser_rescan(blocked, args):
    """Second pass for domains whose homepage the stdlib fetch couldn't read (403 /
    Cloudflare / JS-only): re-fetch with a real headless Chromium, which passes the
    browser-integrity check, then re-scrape footer emails + discovered takedown links.
    Optional — needs Playwright; silently skips if it isn't installed. Sequential
    (one shared browser) since blocked domains are a minority."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("  (playwright not installed — `pip install playwright && playwright install chromium` "
              "to enable; skipping browser pass)", file=sys.stderr)
        return
    print(f"Browser pass for {len(blocked)} blocked domain(s) ...", file=sys.stderr)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(user_agent=HEADERS["user-agent"])
        page = ctx.new_page()

        def get(u):
            try:
                page.goto(u, timeout=args.timeout * 1000, wait_until="domcontentloaded")
                return page.content()
            except Exception:
                return ""

        for i, r in enumerate(blocked, 1):
            base = r["domain"]
            html = get(f"https://{base}/")
            if not html:
                print(f"  [{i}/{len(blocked)}] {base}: still blocked", file=sys.stderr)
                continue
            found = {}
            for e in emails_from(normalize_html(html)):
                found.setdefault(e, f"https://{base}/")
            links = discover_contact_links(base, html)
            for lu in links[:6]:
                lh = get(lu)
                if not lh:
                    continue
                nlh = normalize_html(lh)
                for e in emails_from(nlh):
                    found.setdefault(e, lu)
                if not r["dmca_page"] and DMCA_HINT.search(nlh[:30000]):
                    r["dmca_page"] = lu
            if not r["dmca_page"]:
                for u in links:
                    if re.search(r"dmca|copyright|takedown|2257|infring", urllib.parse.urlparse(u).path, re.I):
                        r["dmca_page"] = u
                        break
            if found:
                ranked = sorted(found, key=lambda e: (score(e), e))
                r["all_emails"] = ";".join(ranked)
                r["best_email"] = ranked[0]    # a real site address beats the RDAP fallback
                r["_via_browser"] = True
                print(f"  [{i}/{len(blocked)}] {base}: {r['best_email']} (via browser)", file=sys.stderr)
            else:
                print(f"  [{i}/{len(blocked)}] {base}: no email even via browser"
                      + (f" — DMCA page {r['dmca_page']}" if r['dmca_page'] else ""), file=sys.stderr)
        browser.close()


def load_domains(positional, infile, mapfile):
    doms = list(positional or [])
    if infile:
        with open(infile, encoding="utf-8") as fh:
            doms += [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    if not doms and os.path.exists(mapfile):
        doms = list(json.load(open(mapfile, encoding="utf-8")).keys())
    # normalize, dedupe on registrable
    out, seen = [], set()
    for d in doms:
        d = registrable(d.replace("https://", "").replace("http://", "").split("/")[0])
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out


def main():
    p = argparse.ArgumentParser(description="Find DMCA/abuse takedown contacts for leak domains.")
    p.add_argument("domains", nargs="*", help="Domains to look up.")
    p.add_argument("--in", dest="infile", help="File with one domain per line.")
    p.add_argument("--map", default=os.path.join(HERE, "bruqi_detection_map.json"),
                   help="Fallback domain source when none are given.")
    p.add_argument("--out", default="data/dmca-contacts", help="Output prefix.")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--timeout", type=int, default=12)
    p.add_argument("--politeness", type=float, default=0.4,
                   help="Min seconds between requests to the SAME host.")
    p.add_argument("--no-rdap", action="store_true", help="Skip RDAP/WHOIS abuse lookup.")
    p.add_argument("--domain-budget", type=float, default=45.0,
                   help="Max seconds to spend walking one domain's pages before moving on "
                        "(stops a slow/dead straggler from stalling the whole run).")
    p.add_argument("--browser", action="store_true",
                   help="Re-fetch homepages that returned 403/blocked with a headless browser "
                        "(passes Cloudflare integrity checks). Needs Playwright.")
    args = p.parse_args()

    global MIN_INTERVAL
    MIN_INTERVAL = max(0.0, args.politeness)
    # hard floor on every socket op (DNS/connect/TLS/read) so one wedged host can't hang
    # the whole run — urlopen(timeout=) alone misses some phases on pathological sites.
    socket.setdefaulttimeout(args.timeout + 5)

    domains = load_domains(args.domains, args.infile, args.map)
    if not domains:
        p.error("Provide domains (positional), --in FILE, or a valid --map.")

    cols = ["domain", "best_email", "all_emails", "dmca_page", "contact_form", "rdap_abuse", "registrar"]

    def write_outputs(rows):
        """Dump CSV/TXT/JSON from whatever's done so far — called incrementally so a
        slow straggler at the end never costs us the results we already have."""
        rows = sorted(rows, key=lambda r: r["domain"])
        tmp = f"{args.out}.csv.tmp"
        with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            for r in rows:
                w.writerow([r[c] for c in cols])
        os.replace(tmp, f"{args.out}.csv")   # atomic — never leave a half-written file
        with open(f"{args.out}.txt", "w", encoding="utf-8") as fh:
            fh.write("\n".join(f"{r['domain']}\t{r['best_email']}" for r in rows if r["best_email"]) + "\n")
        json.dump([{k: v for k, v in r.items() if not k.startswith("_")} for r in rows],
                  open(f"{args.out}.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    print(f"Finding DMCA contacts for {len(domains)} domains ...", file=sys.stderr)
    results = []
    n = len(domains)
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(find_for, d, args): d for d in domains}
        done = 0
        for fut in cf.as_completed(futs):
            r = fut.result()
            results.append(r)
            done += 1
            tag = r["best_email"] or (("form:" + r["contact_form"]) if r.get("contact_form") else "—")
            print(f"  [{done}/{n}] {r['domain']:24} {tag}", file=sys.stderr)
            # save continuously once most are in (every 10), and every domain over the
            # last 5 — so the inevitable slow straggler can't strand the whole run
            if done % 10 == 0 or done >= n - 5:
                write_outputs(results)

    # optional browser pass: re-fetch blocked homepages that yielded no *site* email
    # (best_email may already hold an RDAP/registrar fallback — a site address beats it)
    if args.browser:
        blocked = [r for r in results if r.get("_home_status") in (0, 403, 503) and not r["all_emails"]]
        if blocked:
            browser_rescan(blocked, args)

    write_outputs(results)

    got = sum(1 for r in results if r["best_email"])
    pages = sum(1 for r in results if not r["best_email"] and r["dmca_page"])
    via_b = sum(1 for r in results if r.get("_via_browser"))
    print(f"\nDONE. {got}/{len(results)} domains with a contact"
          + (f" ({via_b} recovered via browser)" if via_b else "")
          + (f"; {pages} more have a DMCA page but no address." if pages else "")
          + f" Files: {args.out}.csv / .txt / .json", file=sys.stderr)


if __name__ == "__main__":
    main()

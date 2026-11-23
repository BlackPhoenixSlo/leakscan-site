"""One HTTP transport for every scanner in this tree, and one answer to "did the
host refuse us, or did it answer?".

WHY THIS EXISTS (appDMCA #34)
-----------------------------
Every scanner here used to define its own ``fetch()`` over ``urllib.request`` — a
Chrome user-agent string on top of Python's TLS. That is fine from the operator's
residential IP and expensive from a datacenter one. Measured over the 375-domain
detection map (appDMCA #31), same URLs, same UA:

    Mac (residential)  plain urllib    8/375 domains blocked      77/20343 leaks (0%)
    VPS (datacenter)   plain urllib   45/375 domains blocked    6677/20343 leaks (33%)
    VPS (datacenter)   curl_cffi      24/375 domains blocked     110/20343 leaks (1%)

A third of the corpus, recovered by changing nothing but the TLS handshake —
picazor.com (2549 leaks), fapeza.com (1628), fapexy.com (1177), wildskirts.com
(477), leakedmodels.com (263), fapello.com (225) among them. Cloudflare is
fingerprinting the JA3, not reading the User-Agent header.

``deploy/vps/deploy_stream.sh`` ships this tree to the VPS, so the datacenter row
is the one that describes production.

IMPERSONATION IS THE POINT
--------------------------
``curl_cffi`` works by reproducing Chrome's TLS/JA3 fingerprint AND its exact
header set and ordering. Passing a hand-rolled header dict alongside
``impersonate=`` overwrites that ordering and gives the fingerprint away, which is
the whole thing we are paying for. So ``http_get`` sends only the *extra* headers a
caller genuinely needs (e.g. ``accept: application/json``) and lets curl_cffi own
the rest. The stdlib fallback, which has no fingerprint to protect, sends the full
``HEADERS`` dict as before.

The fallback is deliberate but must not be silent: if ``curl_cffi`` is missing, the
process is back to the 33%-blocked path. Check ``BACKEND`` and say so.
"""
from __future__ import annotations

import gzip
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

# ── transport ────────────────────────────────────────────────────────────────
try:
    from curl_cffi import requests as _curl
    BACKEND = "curl_cffi"
except Exception:                     # not installed — degrade, loudly at the caller
    _curl = None
    BACKEND = "urllib"

IMPERSONATE = "chrome"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")

# Used verbatim by the stdlib fallback; curl_cffi supplies its own (see module note).
HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/json,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "accept-encoding": "identity",
    "user-agent": UA,
}

DEFAULT_MAX_BYTES = 900_000


def http_get(url, timeout=15, extra_headers=None, max_bytes=DEFAULT_MAX_BYTES):
    """GET `url`. Returns ``(status, final_url, body)``.

    ``status`` is 0 for a transport failure (DNS, timeout, reset) — distinct from
    any HTTP status the host actually returned. Never raises.

    Unlike the urllib version this replaces, the body of a NON-200 is kept rather
    than discarded: ``is_blocked`` needs it to tell a bot wall from a plain refusal.
    """
    if _curl is not None:
        try:
            r = _curl.get(url, impersonate=IMPERSONATE, timeout=timeout,
                          headers=extra_headers or None, allow_redirects=True,
                          verify=False)
            body = r.text or ""
            return r.status_code, str(r.url or url), body[:max_bytes]
        except Exception:
            return 0, url, ""

    hdrs = dict(HEADERS, **(extra_headers or {}))
    try:
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            raw = r.read(max_bytes)
            if r.headers.get("content-encoding") == "gzip":
                raw = gzip.decompress(raw)
            return r.status, r.geturl(), raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            raw = e.read(max_bytes)
            body = raw.decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, url, body
    except Exception:
        return 0, url, ""


# ── blocked vs absent ────────────────────────────────────────────────────────
# The distinction the scanners were missing entirely. A 404, or a 200 reading
# "creator not found", is NOT a block — the host let us in and she simply is not
# there. Collapsing the two is how a blocked domain gets reported to a creator as
# "no leaks found".
#
# Keyed on <title> first (an interstitial always names itself there), backed by
# status. Body markers only corroborate; they are never the case on their own,
# because Cloudflare injects /cdn-cgi/challenge-platform/scripts/jsd/main.js into
# ordinary SUCCESSFUL responses on every proxied site.
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

# A real gallery/search page on these hosts runs well past this; an interstitial
# is a few KB with no grid.
MIN_REAL_PAGE_BYTES = 30_000

BLOCKING_STATUSES = (401, 403, 429, 503)

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def page_title(html):
    m = _TITLE_RE.search(html or "")
    return re.sub(r"\s+", " ", m.group(1)).strip()[:120] if m else ""


def is_blocked(status, body=""):
    """True when the HOST REFUSED US. False when it answered — including 404 and a
    "not found" 200. A transport failure (status 0) is neither: it is a dead
    network, which callers already handle separately."""
    title = page_title(body).lower()
    if title and any(m in title for m in CHALLENGE_TITLES):
        return True
    if status in BLOCKING_STATUSES:
        return True
    if status and 200 <= status < 300:
        low = (body or "").lower()
        return len(body or "") < MIN_REAL_PAGE_BYTES and any(m in low for m in CHALLENGE_BODY)
    return False


def backend_note():
    """One line for a scanner to print at startup. The fallback is the 33%-blocked
    path, so it should never be discovered after the fact from a thin result set."""
    if BACKEND == "curl_cffi":
        return f"fetch backend: curl_cffi (impersonate={IMPERSONATE})"
    return ("fetch backend: urllib FALLBACK — curl_cffi is not installed. From a "
            "datacenter IP this loses ~33% of the corpus to Cloudflare (appDMCA #34). "
            "pip install curl_cffi")

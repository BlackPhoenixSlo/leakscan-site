#!/usr/bin/env python3
"""
Public, no-upsell leak-scan web app.

Serves the landing page + share views, runs live scans via leak_scanner.py
(streamed over SSE), persists them to SQLite, and mints shareable /s/<slug>
links. Binds to 127.0.0.1 ONLY — put a reverse proxy (Caddy) in front for
public exposure (M7). The internal admin server.py stays on its own port and is
never proxied. Stdlib only.

Routes (public surface — no admin routes here):
  GET  /                       landing page
  GET  /healthz                liveness + verified-domain count + kb flag
  GET  /static/<file>          frontend assets (traversal-safe)
  GET  /s/<slug>               share view shell (noindex)
  GET  /api/scan-result/<slug> saved scan JSON (noindex)
  GET  /api/profile/<slug>     quick-scan public profile JSON (noindex)
  GET  /api/avatar/<slug>      quick-scan profile avatar image (404 if none)
  GET  /api/media/<slug>       quick-scan SFW photos {status: pending|ready|none, images[]}
  GET  /api/media/<slug>/<n>.jpg  one gathered photo (404 if none)
  POST /api/public-scan        live scan (SSE, rate-limited)  # one-project: scan reuse (body {"fresh": true} skips reuse)
  POST /api/chat               (M5) DeepSeek chat proxy; body {"kb":"landing"} -> landing
                               FAQ mode (kb_landing.md + LANDING_SYSTEM_PROMPT)
  GET  /api/chat-kb?kb=landing landing KB monitor {kb, ok, bytes, updated} (no content)
"""

import base64
import concurrent.futures as _cf
import glob
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import web_common as wc
import db
import ratelimit
import chat_proxy
import cse_scanner
import leak_evidence
import media_gather
import profile_extract
import report_live
from netloc import registrable_domain

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_ROOT = os.path.join(HERE, "public_static")
MAP_FILE = os.path.join(HERE, "bruqi_detection_map.json")
KB_FILE = os.path.join(HERE, "kb.json")
# Landing-site "Ask AI" popup KB (mirrors the GitHub Pages landing page).
KB_LANDING_FILE = os.environ.get("KB_LANDING_FILE", os.path.join(HERE, "kb_landing.md"))
SCANNER = os.path.join(HERE, "leak_scanner.py")
PIPELINE = os.path.join(HERE, "pipeline_steps.py")
BIO_VERIFY = os.path.join(HERE, "bio_verify.py")
VERIFY_TIMEOUT = int(os.environ.get("VERIFY_TIMEOUT", "120"))
VERIFY_PLATFORMS = ("instagram", "onlyfans")
# IG/OnlyFans bio-ownership check. OFF by default ("for now we do not do any ig
# bio checks"): the verify endpoints return 404 and bio_verify.py never runs.
BIO_VERIFY_ENABLED = os.environ.get("BIO_VERIFY_ENABLED", "0").lower() in ("1", "true", "yes")

wc.load_env(os.path.join(HERE, ".env"))

PORT = int(os.environ.get("PUBLIC_PORT", "8080"))
# Bind host. Default 127.0.0.1 (loopback-only; put Caddy/Traefik in front). In a
# container with no published port, set PUBLIC_HOST=0.0.0.0 so the in-network
# reverse proxy (Traefik) can reach it — the container is still not host-exposed.
PUBLIC_HOST = os.environ.get("PUBLIC_HOST", "127.0.0.1")
# CSE-images-only big scan: on a stdlib-only host (the VPS, no PIL/Pillow), phase 2
# runs ONLY build_cse + export (skips the gallery step, which needs PIL). The preview
# then falls back to the CSE thumbnails; the confirmed-leak counts/links still come
# from the export. Keeps the whole path stdlib.
BIG_SCAN_CSE_IMAGES_ONLY = os.environ.get("BIG_SCAN_CSE_IMAGES_ONLY", "0").lower() in ("1", "true", "yes")
VAR_MAX = int(os.environ.get("VAR_MAX", "6"))            # fast default deep scan
VAR_MAX_PLUS = int(os.environ.get("VAR_MAX_PLUS", "20"))  # "additional" wider pass
SCAN_TIMEOUT = int(os.environ.get("SCAN_TIMEOUT", "900"))
# Big scan = the real pipeline_steps.py, split into two phases so a flaky crawl
# can never cost us the screenshots. Each phase has its own wall-clock budget.
PIPE_DISCOVERY_TIMEOUT = int(os.environ.get("PIPE_DISCOVERY_TIMEOUT", "900"))
PIPE_SHOTS_TIMEOUT = int(os.environ.get("PIPE_SHOTS_TIMEOUT", "300"))
SHOTS_CAP = int(os.environ.get("SHOTS_CAP", "10"))            # screenshots embedded per report
SHOT_MAX_BYTES = int(os.environ.get("SHOT_MAX_BYTES", "1500000"))  # skip a single oversized screenshot
SHOTS_TOTAL_MAX = int(os.environ.get("SHOTS_TOTAL_MAX", "6000000"))  # cap TOTAL embedded bytes / scan row
CSE_IMAGES = int(os.environ.get("CSE_IMAGES", "18"))     # google preview thumbnails
CSE_DEEP_CALLS = int(os.environ.get("CSE_DEEP_CALLS", "15"))  # deep CSE widening budget (total)
CSE_PREFIXES = [p.strip() for p in os.environ.get("CSE_PREFIXES", "leaks,porn").split(",") if p.strip()]
# Deep-report dropdown links: 0 = UNLIMITED (print EVERY leak URL per site — pages matter for
# Google delisting, not just media). Set the env knobs to a positive number to re-cap.
PER_DOMAIN_LINKS = int(os.environ.get("PER_DOMAIN_LINKS", "0"))  # 0 = no per-site cap
LINKS_CAP = int(os.environ.get("LINKS_CAP", "0"))               # 0 = no total ceiling
GALLERY_CAP = int(os.environ.get("GALLERY_CAP", "24"))  # curated photos embedded (preview strip + Google grids)

# ── Quick-scan (fast/low report) tuning ──────────────────────────────────────
# Deeper CSE pass: 6–8 exclude-reset widening calls (was a 2-pass). More calls =
# more distinct leak hosts per quick scan (costs more CSE quota per scan).
CSE_QUICK_CALLS = max(1, min(int(os.environ.get("CSE_QUICK_CALLS", "8")), 12))
MIN_SITES_FOR_FALLBACK = int(os.environ.get("MIN_SITES_FOR_FALLBACK", "7"))
FALLBACK_EXTRA_PAGES = int(os.environ.get("FALLBACK_EXTRA_PAGES", "1"))
# Google-index figure on the report/poster. Google's raw totalResults is inflated
# to millions and not credible, so by default we REPLACE it with a grounded
# estimate = urls*ESTIMATE_URL_MULT + sites*ESTIMATE_SITES_MULT (optionally capped
# by GOOGLE_INDEX_MAX). Set USE_TOTAL_RESULTS_QUERY=1 to show Google's raw number.
USE_TOTAL_RESULTS_QUERY = os.environ.get("USE_TOTAL_RESULTS_QUERY", "0").lower() in ("1", "true", "yes")
ESTIMATE_URL_MULT = float(os.environ.get("ESTIMATE_URL_MULT", "10.0"))
ESTIMATE_SITES_MULT = float(os.environ.get("ESTIMATE_SITES_MULT", "30.0"))
GOOGLE_INDEX_MAX = int(os.environ.get("GOOGLE_INDEX_MAX", "0"))   # 0 = no cap
# Display multipliers/caps for the fast report + poster (applied client-side).
DISPLAY_PER_DOMAIN_MULT = int(os.environ.get("DISPLAY_PER_DOMAIN_MULT", "6"))
DISPLAY_TOTAL_MULT = int(os.environ.get("DISPLAY_TOTAL_MULT", "6"))
STATS_TOP_DOMAINS = int(os.environ.get("STATS_TOP_DOMAINS", "8"))
TOP_LEAK_URL_MAX_LEN = int(os.environ.get("TOP_LEAK_URL_MAX_LEN", "80"))
# Thumbnail proxy (the poster needs same-origin images to avoid canvas taint):
# only these host suffixes may be fetched (SSRF guard), capped at THUMB_MAX_BYTES.
THUMB_HOSTS = ("gstatic.com", "googleusercontent.com", "ggpht.com")
THUMB_MAX_BYTES = int(os.environ.get("THUMB_MAX_BYTES", "3000000"))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None   # block redirects — SSRF hardening for the thumbnail proxy


_THUMB_OPENER = urllib.request.build_opener(_NoRedirect)

PLATFORMS = {"onlyfans.com", "fansly.com", "instagram.com", "tiktok.com",
             "patreon.com", "manyvids.com"}

SCAN_LIMITER = ratelimit.Limiter(
    rate_per_min=int(os.environ.get("RATE_PER_MIN", "5")),
    burst=int(os.environ.get("RATE_BURST", "5")),
    max_concurrent=int(os.environ.get("MAX_CONCURRENT", "2")),
)
RESULT_LIMITER = ratelimit.Limiter(rate_per_min=60, burst=30, max_concurrent=1000)
# Own bucket for /api/thumb: a results page loads ~30 thumbs at once. Token-only (no release).
THUMB_LIMITER = ratelimit.Limiter(rate_per_min=120, burst=60, max_concurrent=1000)
CHAT_LIMITER = ratelimit.Limiter(
    rate_per_min=int(os.environ.get("CHAT_RATE_PER_MIN", "20")),
    burst=int(os.environ.get("CHAT_BURST", "10")),
    max_concurrent=int(os.environ.get("CHAT_MAX_CONCURRENT", "3")),
)
GLOBAL_SCANS = ratelimit.GlobalCap(int(os.environ.get("MAX_GLOBAL_SCANS", "4")))
VERIFY_LIMITER = ratelimit.Limiter(
    rate_per_min=int(os.environ.get("VERIFY_RATE_PER_MIN", "10")),
    burst=int(os.environ.get("VERIFY_BURST", "6")),
    max_concurrent=int(os.environ.get("VERIFY_MAX_CONCURRENT", "2")),
)

# Cross-origin callers allowed to use the API (static landing site runs the quick scan).
CORS_ORIGINS = frozenset(o.strip().rstrip("/") for o in os.environ.get(
    "CORS_ORIGINS", "https://blackphoenixslo.github.io").split(",") if o.strip())

# Quick-scan public profile (name/bio/handles/avatar for the landing mockups).
PROFILE_ENABLED = os.environ.get("PROFILE_ENABLED", "1").lower() in ("1", "true", "yes")
# One extra CSE call for official accounts, only when the scan's items have none.
PROFILE_CSE_EXTRA = os.environ.get("PROFILE_CSE_EXTRA", "0").lower() in ("1", "true", "yes")
PROFILE_ACCOUNT_SITES = ("instagram.com", "tiktok.com", "x.com", "twitter.com",
                         "youtube.com", "linktr.ee", "beacons.ai")
AVATAR_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def _avatar_dir():
    return os.path.join(os.environ.get("DATA_DIR") or os.path.dirname(os.path.abspath(db.DB_PATH)),
                        "avatars")


def _avatar_path(slug):
    """Existing avatar file for a slug, or None. Slug must already be SLUG_RE-valid."""
    for ext in AVATAR_TYPES:
        p = os.path.join(_avatar_dir(), f"{slug}.{ext}")
        if os.path.isfile(p):
            return p
    return None


def _save_avatar(slug, av):
    if not av or not db.SLUG_RE.match(slug or ""):
        return False
    data, ext = av
    if ext not in AVATAR_TYPES:
        return False
    try:
        os.makedirs(_avatar_dir(), exist_ok=True)
        tmp = os.path.join(_avatar_dir(), f".{slug}.{ext}.tmp")
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, os.path.join(_avatar_dir(), f"{slug}.{ext}"))
        return True
    except OSError as e:
        _event(f"avatar save failed: {type(e).__name__}")
        return False


def _prune_avatars(days=30):
    cutoff, n = time.time() - days * 86400, 0
    for p in glob.glob(os.path.join(_avatar_dir(), "*")):
        try:
            if os.path.getmtime(p) < cutoff:
                os.remove(p)
                n += 1
        except OSError:
            pass
    return n


def _profile_cse_items(handle, items):
    """At most ONE extra CSE call (flagged) aimed at official accounts."""
    if not PROFILE_CSE_EXTRA or not cse_scanner.cse_available():
        return []
    for it in items or []:
        if registrable_domain(it.get("host") or it.get("link") or "") in PROFILE_ACCOUNT_SITES:
            return []
    q = handle + " " + " OR ".join(f"site:{d}" for d in PROFILE_ACCOUNT_SITES)
    try:
        extra, _ = cse_scanner.cse_search(q, pages=1, timeout=5)
        return extra
    except Exception:
        return []


def _quick_profile(handle, platform, items, socials=None, hints=None):  # one-project: hints
    """-> (profile|None, avatar(bytes, ext)|None, sources|None). Never raises, never exceeds
    ~budget+2s. sources go on to media_gather (profile refine with web snippets)."""
    box = {}

    def run():
        try:
            t0 = time.monotonic()
            more = _profile_cse_items(handle, items)
            budget = profile_extract.PROFILE_BUDGET - (time.monotonic() - t0)
            prof, av, src = profile_extract.build_profile(platform, handle, more + list(items or []),
                                                          budget=budget, socials=socials, hints=hints)  # one-project: hints
            box["r"] = (prof, av, src)
        except Exception as e:
            _event(f"profile failed: {type(e).__name__}")
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(profile_extract.PROFILE_BUDGET + 2)
    if "r" not in box:
        if t.is_alive():
            _event("profile timed out")
        return None, None, None
    return box["r"]


SOCIAL_KEYS = ("instagram", "x")
_SOCIAL_URL_RE = re.compile(r"^(?:https?://)?(?:www\.|m\.)?(?:instagram\.com|x\.com|twitter\.com)/+@?([^/?#\s]+)",
                            re.I)
MAX_QUICK_ALIASES = 3


def clean_socials(body):
    """User-declared socials from the scan body -> {"instagram"?: h, "x"?: h}. Accepts @h and
    instagram.com/<h>, x.com/<h>, twitter.com/<h> URL forms; invalid values dropped silently."""
    out = {}
    for k in SOCIAL_KEYS:
        v = body.get(k) if isinstance(body, dict) else None
        if not isinstance(v, str):
            continue
        v = v.strip()[:200]
        m = _SOCIAL_URL_RE.match(v)
        v = (m.group(1) if m else v).lstrip("@").rstrip("/")
        if profile_extract.valid_handle(v):
            out[k] = v
    return out


def quick_aliases(handle_aliases, socials):
    """Scan handle + declared social handles that differ (case-insensitive), cap 3."""
    out, seen = [], set()
    for a in list(handle_aliases[:1]) + [socials[k] for k in SOCIAL_KEYS if k in socials]:
        if a.lower() not in seen:
            seen.add(a.lower())
            out.append(a)
    return out[:MAX_QUICK_ALIASES]


# Quick-scan `results` (Google-style links/images/videos tabs).
RESULTS_CAP = 80
_VIDEO_LINK_RE = re.compile(r"/videos?/|/watch|\.mp4", re.I)
_VIDEO_TITLE_RE = re.compile(r"\b(?:videos?|clips?)\b", re.I)


def result_kind(item):
    """'video' if CSE flagged a videoobject or the link/title looks like a video, else 'page'."""
    if item.get("video") or _VIDEO_LINK_RE.search(item.get("link") or "") \
            or _VIDEO_TITLE_RE.search(item.get("title") or ""):
        return "video"
    return "page"


def _gstatic(u):
    try:
        pu = urllib.parse.urlparse(u or "")
    except ValueError:
        return False
    host = (pu.hostname or "").lower()
    return pu.scheme == "https" and (host == "gstatic.com" or host.endswith(".gstatic.com"))


def shape_results(items, cap=RESULTS_CAP):
    """Raw CSE items -> [{title, link, snippet, thumb, domain, kind}], deduped by link, capped."""
    out, seen = [], set()
    for it in items or []:
        link = it.get("link")
        if not link or link in seen:
            continue
        seen.add(link)
        thumb = it.get("image")
        out.append({
            "title": (it.get("title") or "")[:200],
            "link": link,
            "snippet": (it.get("snippet") or "")[:400],
            "thumb": thumb if _gstatic(thumb) else None,
            "domain": registrable_domain(it.get("host") or link),
            "kind": result_kind(it),
        })
        if len(out) >= cap:
            break
    return out


def _scan_extra_all(slug):
    """A scan's whole extra_json dict, or None if the slug has no row."""
    try:
        with db._db() as c:
            r = c.execute("SELECT extra_json FROM scans WHERE slug = ?", (slug,)).fetchone()
        return None if r is None else (json.loads(r[0] or "{}") or {})
    except Exception:
        return None


def _scan_extra(slug, key):
    """One key from a scan's extra_json (db.get_scan only surfaces a fixed key list)."""
    return (_scan_extra_all(slug) or {}).get(key)


SEC_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "img-src 'self' data: https://*.gstatic.com https://*.googleusercontent.com; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


def _verified_domain_count():
    try:
        dmap = json.load(open(MAP_FILE, encoding="utf-8"))
        return sum(1 for v in dmap.values() if v.get("check_url") and v.get("verified"))
    except Exception:
        return 0


VERIFIED_DOMAINS = _verified_domain_count()


def _dm_config():
    return {
        "instagram": os.environ.get("DM_INSTAGRAM", "").strip(),
        "whatsapp": os.environ.get("DM_WHATSAPP", "").strip(),
        "telegram": os.environ.get("DM_TELEGRAM", "").strip(),
    }


def _event(msg):
    """Secret-safe minimal observability: no handles, URLs, chat text or keys."""
    sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    sys.stderr.flush()


media_gather.log = _event
_MEDIA_PATH_RE = re.compile(r"^([A-Za-z0-9_-]{6,24})(?:/(0|[1-9][0-9]?)\.jpg)?$")


def _ip_hash(ip):
    day = time.strftime("%Y-%m-%d")
    return hashlib.sha256((ip + "|" + day).encode("utf-8")).hexdigest()[:32]


def summarize_hits(hits):
    """Pure: raw leak_scanner hit dicts -> compact public rows (with a live flag),
    sorted by occurrences desc. Search-echo false positives (a search page that
    200s and echoes the handle but links none of the creator's content — the
    "other videos" junk) are dropped: we only surface sites confirmed to host."""
    rows = []
    for h in hits or []:
        if not h.get("hit"):
            continue
        evidence = h.get("evidence")
        if evidence is None:  # older scanner output without a class — verify by url shape
            evidence = leak_evidence.url_shape(h.get("url"), h.get("method"))
            if evidence == "search":            # unknown search shape, unverifiable here
                evidence = "search-echo" if not h.get("content_matches") else "search-verified"
        if not leak_evidence.is_real(evidence):
            continue
        rows.append({
            "domain": h.get("domain"),
            "url": h.get("url"),
            "occurrences": h.get("occurrences", 0),
            "method": h.get("method"),
            "evidence": evidence,
            "alias": h.get("alias"),
            "live": (h.get("status") == 200 and bool(h.get("hit"))),
        })
    rows.sort(key=lambda r: r.get("occurrences", 0), reverse=True)
    return rows


def merge_rows(primary, secondary):
    """Union hit rows by domain. `primary` (slug-scrape, directly confirmed) wins
    on conflict but inherits a live flag / higher occurrence count from either
    source. This lets the deep scan fold in the quick (Google) pass so the full
    scan never surfaces fewer sites than the quick one."""
    by, order = {}, []
    for r in list(primary or []) + list(secondary or []):
        d = r.get("domain")
        if not d:
            continue
        if d not in by:
            by[d] = dict(r)
            order.append(d)
        else:
            cur = by[d]
            cur["occurrences"] = max(cur.get("occurrences", 0) or 0, r.get("occurrences", 0) or 0)
            cur["live"] = bool(cur.get("live")) or bool(r.get("live"))
            if not cur.get("url"):
                cur["url"] = r.get("url")
    merged = [by[d] for d in order]
    merged.sort(key=lambda r: r.get("occurrences", 0), reverse=True)
    return merged


def _cse_safe(handle, on_progress=None):
    """Best-effort Google-CSE pass. Returns (rows, images, google_total).
    Cycles CSE_PREFIXES phrasings ('leaks <h>', 'porn <h>') through ONE shared
    exclude-reset widening under a single CSE_DEEP_CALLS budget, so different
    phrasings surface different leak hosts while every call still -site:-excludes
    every domain seen so far. Two prefixes @15 calls found 44 hosts for cinnanicos
    vs 32 single-query / 16 two-call. Never raises — deep scan survives CSE errors."""
    try:
        if not cse_scanner.cse_available():
            return [], [], None
        queries = [f"{p} {handle}" for p in CSE_PREFIXES] or [handle]
        results, total = cse_scanner.cse_search_wide(
            queries, max_calls=CSE_DEEP_CALLS, on_progress=on_progress)
        return cse_scanner.summarize_cse(results), cse_scanner.cse_images(results, CSE_IMAGES), total
    except Exception:
        return [], [], None


def _deep_aliases(handle, aliases_raw):
    """Base aliases for a deep scan: the handle plus each comma-separated extra
    alias, slugified (spaces removed / underscored) into leak-site handle form.
    e.g. 'Ivette Aguero Tarazona, tarita fit' -> ivetteaguerotarazona,
    ivette_aguero_tarazona, taritafit, tarita_fit. Capped at 10 bases."""
    bases = [handle]
    for part in (aliases_raw or "").split(","):
        p = part.strip()
        if not p:
            continue
        for cand in (re.sub(r"\s+", "", p).lower(), re.sub(r"\s+", "_", p).lower()):
            if cand and re.match(r"^[a-z0-9._-]{1,60}$", cand):
                bases.append(cand)
    seen, out = set(), []
    for b in bases:
        if b.lower() not in seen:
            seen.add(b.lower())
            out.append(b)
    return out[:10]


# ---------------------------------------------------------------- deep jobs
# Deep scans run detached from the HTTP connection so a page reload can't kill
# them. Live progress lives here in-memory; the final result is persisted to
# SQLite under the scan's slug. The browser drives the job by polling
# /api/scan-result/<slug> (slug is kept in the URL hash to survive reloads).
JOBS = {}
JOBS_LOCK = threading.Lock()
JOB_LOG_CAP = 120        # keep only the last N meaningful lines per job
_COUNTER_RE = re.compile(r"^\s*\d+\s*/\s*\d+\s*$")
# The pipeline prints "=== [<step>] <title> ===" banners on stderr as each step
# starts; parse them into a live `phase` so the progress page + waiting-room chat
# can tell the visitor which stage the deep scan is in. Without this the UI goes
# quiet after the site-check counter maxes out and the chat concludes (wrongly)
# that the scan is finished. Ordered — index = "stage N of len".
_PHASE_RE = re.compile(r"^===\s*\[(\w+)\]")
DEEP_PHASES = ("scan", "seed", "crawl", "clean", "triage", "export", "cse", "gallery")


def _job_gc(now):
    for slug in [s for s, j in JOBS.items()
                 if j["status"] != "running" and now - j.get("ts", now) > 3600]:
        del JOBS[slug]


def _job_new(slug, handle, platform, level):
    with JOBS_LOCK:
        _job_gc(time.time())
        JOBS[slug] = {"slug": slug, "handle": handle, "platform": platform,
                      "level": level, "status": "running", "count": "",
                      "found": [], "log": [], "slugs": [], "result": None,
                      "phase": "scan", "ts": time.time(),
                      # monotone memory for the live "candidates found so far" ticker — only ever
                      # grows within a scan, so a checkpoint rewrite (clean_crawl) can't lower it.
                      "live_floor": {"candidates": 0, "sites": 0, "by_domain": {}}}


def _job_set_slugs(slug, slugs):
    """Record the exact handle variations (slugs) being checked, for display."""
    with JOBS_LOCK:
        j = JOBS.get(slug)
        if j:
            j["slugs"] = list(slugs)


def _job_progress(slug, line):
    """Record one progress line. Counter-only lines (e.g. '542/7500') just update
    the live count; meaningful lines (FOUND/status) are kept in a capped log."""
    with JOBS_LOCK:
        j = JOBS.get(slug)
        if not j:
            return
        if _COUNTER_RE.match(line):
            j["count"] = line.strip()
            return
        pm = _PHASE_RE.match(line.strip())
        if pm and pm.group(1) in DEEP_PHASES:
            j["phase"] = pm.group(1)
        m = re.search(r"FOUND\s+(\S+)\s+\((\d+)", line)
        if m and all(f["domain"] != m.group(1) for f in j["found"]):
            j["found"].append({"domain": m.group(1),
                               "occurrences": int(m.group(2))})
        j["log"].append(line)
        if len(j["log"]) > JOB_LOG_CAP:
            del j["log"][:len(j["log"]) - JOB_LOG_CAP]


def _job_snapshot(slug):
    with JOBS_LOCK:
        j = JOBS.get(slug)
        if not j:
            return None
        return {"status": j["status"], "count": j["count"],
                "found": list(j["found"]), "slugs": list(j["slugs"]),
                "handle": j["handle"], "platform": j["platform"],
                "level": j["level"], "phase": j.get("phase", "scan"),
                # last chunk of the pipeline's own stderr — shown as a live console at the
                # bottom of the building report ("show the command outputs").
                "log": j["log"][-40:]}


def _job_finish(slug, status, result):
    with JOBS_LOCK:
        j = JOBS.get(slug)
        if j:
            j["status"] = status
            j["result"] = result
            j["ts"] = time.time()


_LIVE_IMG_RE = re.compile(r"\.(?:jpe?g|png|webp|gif)(?:$|\?)", re.I)
# Site chrome, not content: RTA labels, favicons, sprites, tiny WxH badges (16x16, 88x31, …).
_LIVE_IMG_SKIP = re.compile(r"(?:rta|logo|favicon|sprite|icon|badge|avatar|banner|\b\d{1,3}x\d{1,3}\b)", re.I)
_LIVE_IMG_CAP = 24               # tiles in the streaming candidate-preview grid


def _live_candidate_images(by_domain, cap=_LIVE_IMG_CAP):
    """A small, varied sample of image-like candidate URLs from the growing crawl union.
    Round-robins across domains (one per domain per pass) so the preview grid isn't 24 tiles
    from a single site. Only hotlinkable image extensions — video/HTML media, and obvious site
    chrome (favicons, RTA/logo badges, tiny WxH sprites) are skipped."""
    per_dom = []
    for dom, urls in sorted(by_domain.items(), key=lambda kv: -len(kv[1])):
        imgs = [u for u in urls if _LIVE_IMG_RE.search(u or "") and not _LIVE_IMG_SKIP.search(u or "")]
        if imgs:
            per_dom.append(imgs)
    out, i = [], 0
    while per_dom and len(out) < cap:
        progressed = False
        for imgs in per_dom:
            if i < len(imgs):
                out.append(imgs[i])
                progressed = True
                if len(out) >= cap:
                    break
        if not progressed:
            break
        i += 1
    return out


def _job_set_cse_preview(slug, prefix):
    """Stash the phase-0 CSE pass into job state so the live report can show RELIABLE Google
    thumbnails (base64/gstatic) + top public results + indexed sites while the crawl runs."""
    cse = _load_json_file(os.path.join(HERE, f"{prefix}.cse.json")) or {}
    if not cse:
        return
    prev = {
        "images": (cse.get("images") or [])[:18],
        "img_meta": (cse.get("img_meta") or [])[:14],
        "top_leaks": (cse.get("top_leaks") or [])[:14],
        "cse_sites": [{"domain": s.get("domain"), "url": s.get("url", ""),
                       "occ": s.get("occ", s.get("occurrences", 0))}
                      for s in (cse.get("sites") or []) if s.get("domain")][:40],
        "google_total": cse.get("google_total"),
    }
    with JOBS_LOCK:
        j = JOBS.get(slug)
        if j:
            j["cse_preview"] = prev


def _live_report(slug, snap):
    """Build the LIVE, honest report payload for a running deep scan (returned by the poll route).

    Two lanes, by design (see report_live.py):
      · PROVISIONAL, monotone: `candidates` (media found so far) + `sites_found` + growing
        per-domain candidate links. These only ever grow — a checkpoint rewrite can't lower them.
      · AUTHORITATIVE: the confirmed-leak count + price + hosting come from the export's
        metadata.jsonl — but ONLY once the export step has COMPLETED. We gate on the phase having
        advanced PAST `export` (into cse/gallery), never on file presence: export_dmca writes
        metadata.jsonl non-atomically, so a mid-write read would be a truncated (dishonest) count.
    So the client can show the confirmed-leaks/quote tiles as skeletons that only REVEAL (never
    shrink), while the candidates ticker climbs during the crawl."""
    prefix = report_live.prefix_for(slug)
    with JOBS_LOCK:
        j = JOBS.get(slug)
        floor = dict(j.get("live_floor") or {}) if j else {}
    snapshot = report_live.live_snapshot(prefix, floor)
    with JOBS_LOCK:
        j = JOBS.get(slug)
        if j:                          # persist the grown floor (still monotone)
            j["live_floor"] = {"candidates": snapshot["candidates"],
                               "sites": snapshot["sites_found"],
                               "by_domain": snapshot["by_domain"]}
        cse_prev = dict((j or {}).get("cse_preview") or {})
    out = {"provisional": True, "phase": snap["phase"], "level": "deep",
           "handle": snap["handle"], "slugs": snap["slugs"],
           "candidates": snapshot["candidates"], "sites_found": snapshot["sites_found"],
           "hits": snapshot["hits"], "links_by_domain": snapshot["by_domain"],
           # A growing sample of candidate image URLs so the building report can STREAM a
           # blurred preview grid (honest label: "candidates", not confirmed). Round-robin
           # across domains so the grid shows variety, not 24 tiles from one site.
           "images": _live_candidate_images(snapshot["by_domain"])}
    # Early CSE preview (phase 0): reliable Google thumbnails + top public results + indexed sites,
    # shown the moment the report opens — real evidence while the crawl runs. Its base64/gstatic
    # thumbnails render (hotlinked crawl media doesn't), so they also power the preview grid.
    if cse_prev:
        out["img_meta"] = cse_prev.get("img_meta") or []
        out["top_leaks"] = cse_prev.get("top_leaks") or []
        out["cse_sites"] = cse_prev.get("cse_sites") or []
        out["google_total"] = cse_prev.get("google_total")
        if cse_prev.get("images"):
            out["images"] = cse_prev["images"]      # reliable thumbs beat broken hotlinked media
    # Authoritative confirmed-leak layer — only once export is DONE (phase past export).
    if snap["phase"] in ("cse", "gallery"):
        try:
            n_leaks, links_by_domain, hosting_doms = _load_metadata(prefix)
        except Exception:
            n_leaks, links_by_domain, hosting_doms = 0, {}, set()
        if n_leaks:
            host_reg = {registrable_domain(d) for d in hosting_doms}
            host_reg.discard("")
            out.update({"authoritative": True, "n_leaks": n_leaks,
                        "links_by_domain": links_by_domain, "n_hosting": len(host_reg),
                        "n_sites": len(host_reg), "quote": price_for(n_leaks)})
    return out


# ------------------------------------------------ big scan (= our pipeline)
# The "big scan" runs the real campaign pipeline (pipeline_steps.py) instead of a bare
# presence scan: deep crawl of the hosting sites + Google CSE + curated gallery + DMCA
# export. It is CSE-ONLY — no browser or Incogniton ever touches google.com from the
# server IP. The report's Google-results screenshots are reconstructed client-side from
# the CSE data (thumbnails + indexed sites + top results), matching make_report's layers.
_WEBSCAN_RE = re.compile(r"^webscan_[a-z0-9]+$")

# The pipeline's crawl/seed steps read-modify-write shared repo-root state
# (slugs_cache.json — the crawler's frontier memory, also read by campaign runs)
# WITHOUT a file lock, so two big scans running it at once could corrupt it. Run
# at most one big-scan pipeline at a time; queued scans still hold their slot and
# stream progress. Heavy multi-minute jobs anyway — serial is the safe default.
_BIG_SCAN_LOCK = threading.Lock()


def _load_json_file(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return None


def _pipeline_rows(prefix, handle):
    """Bridge the pipeline's on-disk discovery artifacts into public hit rows +
    the Google index total. Union of leak_scanner presence hits, the deep-crawl
    media map, and the Google-CSE site list (same shape summarize_hits emits)."""
    scan = _load_json_file(os.path.join(HERE, f"{prefix}-scan.json")) or []
    rows = summarize_hits(scan if isinstance(scan, list) else [])
    crawl = (_load_json_file(os.path.join(HERE, f"{prefix}.crawl.clean.json"))
             or _load_json_file(os.path.join(HERE, f"{prefix}.crawl.json")) or [])
    crawl_rows = []
    for e in crawl if isinstance(crawl, list) else []:
        dom, media = e.get("domain"), (e.get("media") or [])
        if not dom or not media:
            continue
        # media_pairs entries are [media_url, page_url]; the page URL is the link.
        page = next((pr[1] for pr in (e.get("media_pairs") or [])
                     if isinstance(pr, (list, tuple)) and len(pr) > 1 and pr[1]), None)
        crawl_rows.append({"domain": dom, "url": page or f"https://{dom}/",
                           "occurrences": len(media), "method": "crawl",
                           "alias": handle, "live": True})
    cse = _load_json_file(os.path.join(HERE, f"{prefix}.cse.json")) or {}
    cse_rows = [{"domain": s.get("domain"), "url": s.get("url"),
                 "occurrences": s.get("occ", 0), "method": "google",
                 "alias": handle, "live": True}
                for s in (cse.get("sites") or []) if s.get("domain")]
    rows = merge_rows(merge_rows(rows, crawl_rows), cse_rows)
    return rows, cse.get("google_total")


def _un(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def price_for(n, lo_n=150, lo_p=250, hi_n=20000, hi_p=2500):
    """Takedown quote scaled to the confirmed-leak count — byte-identical to
    make_report.price_for, so the public deep report and the full-pipeline report always
    quote the SAME fee (150 leaks -> €250 … 20000 -> €2500, rounded to €10)."""
    if n <= lo_n:
        return lo_p
    if n >= hi_n:
        return hi_p
    return int(round((lo_p + (n - lo_n) * (hi_p - lo_p) / (hi_n - lo_n)) / 10.0) * 10)


def _media_count(crawl, strong_tokens):
    """'Media items' stat — count of crawl media whose URL carries a strong handle token
    (mirrors make_report.media_count: photos + videos identified as the creator's)."""
    toks = [_un(t) for t in (strong_tokens or []) if _un(t)]
    if not toks:
        return 0
    n = 0
    for r in crawl if isinstance(crawl, list) else []:
        pairs = r.get("media_pairs") or [[m, ""] for m in (r.get("media") or [])]
        for pr in pairs:
            m = pr[0] if isinstance(pr, (list, tuple)) and pr else pr
            if m and any(t in _un(m) for t in toks):
                n += 1
    return n


def _load_metadata(prefix, per_domain=None, total_cap=None):
    """Bridge the DMCA export's metadata.jsonl (LIKELY bucket) — the SAME confirmed-leak
    source make_report reads — into the deep report. Returns (n_leaks, links_by_domain,
    hosting_domains):
      · n_leaks         — true unique confirmed-leak URL count ('Confirmed leaks' + price basis)
      · links_by_domain — the dropdown export, grouped by domain and capped PER DOMAIN
                          (PER_DOMAIN_LINKS) so EVERY site is represented — not just the few
                          biggest — with LINKS_CAP a high total ceiling for pathological scans
      · hosting_domains — full, uncapped distinct-domain set for the 'sites hosting directly' count
    Never raises: a missing/empty export degrades to (0, {}, set())."""
    # 0 / None = UNLIMITED (print every URL). Only a positive value caps.
    per_domain = per_domain if per_domain is not None else PER_DOMAIN_LINKS
    total_cap = total_cap if total_cap is not None else LINKS_CAP
    path = os.path.join(HERE, "exports", f"{prefix}_latest", "metadata.jsonl")
    n_leaks = 0
    all_by_dom = {}          # domain -> [urls] (metadata is already deduped by norm_url)
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return 0, {}, set()
    try:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if r.get("bucket") != "LIKELY":
                continue
            n_leaks += 1
            dom, url = r.get("domain"), r.get("url")
            if dom and url:
                all_by_dom.setdefault(dom, []).append(url)
    except Exception:
        pass
    finally:
        fh.close()
    # Largest hosts first. per_domain/total_cap of 0 = unlimited → every URL prints (leakgallery
    # included); a positive value re-imposes a budget.
    by_dom, total = {}, 0
    for d in sorted(all_by_dom, key=lambda x: -len(all_by_dom[x])):
        if total_cap and total >= total_cap:
            break
        take = all_by_dom[d][:per_domain] if per_domain else all_by_dom[d]
        if total_cap and total + len(take) > total_cap:
            take = take[:total_cap - total]
        if take:
            by_dom[d] = take
            total += len(take)
    return n_leaks, by_dom, set(all_by_dom)


AUDIT_DL_CAP = int(os.environ.get("AUDIT_DL_CAP", "1000000"))   # effectively unlimited; pure runaway backstop

# Site chrome / non-content assets — NEVER a leak. Favicons, app icons, language flags, tracker
# pixels, RTA age-rating badges, sprite/logo/og-image, and tiny profile-avatar thumbnails
# (picazor 35px_… of OTHER creators). Deliberately conservative: it must not match a real leak
# thumbnail, so it keys on unambiguous chrome tokens, NOT on generic -WxH- responsive suffixes
# (leak sites generate 300x169 / 1024x576 sizes of REAL images).
_ASSET_RE = re.compile(
    r"favicon|fevicon|apple-touch|android-chrome|/flags?/|og[_-]?image|ogimage|"
    r"histats|/sprites?|/static/images/|\brta\b|tpd-b-|star\d+x\d+|\b\d{2,3}px_|/logo|logo\.",
    re.I)


def _is_asset(u):
    return bool(_ASSET_RE.search(u or ""))


def _has_tok(u, toks):
    n = _un(u)
    return any(t and t in n for t in toks)


def _export_urls(prefix):
    """(likely, possible) URL lists from the DMCA export's metadata.jsonl — UNCAPPED, deduped in
    first-seen order. LIKELY = handle in the URL (auto-confirmed); POSSIBLE = name/handle-carrying
    page the pipeline flagged for review. BOTH are things we surfaced, not dropped. [] if absent."""
    path = os.path.join(HERE, "exports", f"{prefix}_latest", "metadata.jsonl")
    likely, possible, seen = [], [], set()
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return likely, possible
    try:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            u, b = r.get("url"), r.get("bucket")
            if not u or u in seen:
                continue
            seen.add(u)
            if b == "LIKELY":
                likely.append(u)
            elif b == "POSSIBLE":
                possible.append(u)
    finally:
        fh.close()
    return likely, possible


def _partition_candidates(crawl, exported_urls, alias_toks, cap=AUDIT_DL_CAP):
    """Split every crawl candidate (media files + crawled pages) into (accepted, removed).

    The old logic dropped everything not literally in the LIKELY set — which wrongly binned the
    POSSIBLE bucket AND all real media on confirmed-hosting sites whose CDN URL is a bare UUID
    (leakgallery/leakedzone/viralxxxporn/fap.onl). Those ARE her leaks. So a candidate is ACCEPTED
    when it is attributable to the creator:
      · the URL itself carries an alias token, OR
      · its crawl source page carries an alias token, OR
      · the URL (or its source page) is in the export's LIKELY∪POSSIBLE set.
    It is REMOVED only when we can positively call it non-content (site asset) or unattributable
    (a media file on a multi-model site whose neither URL nor source page names the creator —
    other performers' thumbnails). This keeps the 'removed' list trustworthy: a real leak in it is
    a bug, not the norm."""
    exp_norm = {report_live._norm_media(u) for u in (exported_urls or [])}

    def attributed(u, src):
        return (_has_tok(u, alias_toks)
                or (src and _has_tok(src, alias_toks))
                or report_live._norm_media(u) in exp_norm
                or (src and report_live._norm_media(src) in exp_norm))

    acc, rem = {}, {}          # norm(url) -> url ; accepted wins over removed
    for r in crawl if isinstance(crawl, list) else []:
        pairs = r.get("media_pairs") or [[m, ""] for m in (r.get("media") or [])]
        items = [(pr[0], pr[1] if isinstance(pr, (list, tuple)) and len(pr) > 1 else "")
                 for pr in pairs if isinstance(pr, (list, tuple)) and pr]
        items += [(p, "") for p in (r.get("pages") or [])]
        for u, src in items:
            if not u:
                continue
            k = report_live._norm_media(u)
            if not k or k in acc:
                continue
            if _is_asset(u):
                rem.setdefault(k, u)
            elif attributed(u, src):
                acc[k] = u
                rem.pop(k, None)
            else:
                rem.setdefault(k, u)
        if len(acc) >= cap and len(rem) >= cap:
            break
    return list(acc.values())[:cap], list(rem.values())[:cap]


# Multi-language leak hosts: each serves the SAME confirmed path under every locale, and each
# locale is a SEPARATELY-indexed page → a separate takedown URL (important for Google delisting).
# Two schemes, both verified live (2026-07-04):
#   PATH   — leakgallery.com/it/<path>   (the subdomain form doesn't resolve)
#   SUBDOM — es.fapello.com/<path>        (the path form is the same page in another language)
LOCALE_PATH_HOSTS = {
    "leakgallery.com": ["it", "es", "fr", "de", "nl", "pt"],
    "picazor.com":     ["es", "de", "fr", "it", "pt", "nl", "pl", "ru", "ko", "zh", "ar"],
    "thothd.com":      ["es", "de", "fr", "pt", "it"],
    "megaporn.ws":     ["es", "de", "fr", "it", "pt", "tr"],
}
LOCALE_SUB_HOSTS = {
    "fapello.com": ["es", "it", "cz", "de", "fr", "nl", "pt", "ru", "pl", "tr"],
    "fapeza.com":  ["es", "it", "de", "fr", "nl", "pt"],
    "fapexy.com":  ["es", "it", "de", "fr", "nl", "pt"],
}
_ALL_LOC_LANGS = {lg for v in list(LOCALE_PATH_HOSTS.values()) + list(LOCALE_SUB_HOSTS.values())
                  for lg in v}
_LOC_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
_LOC_SSL = ssl.create_default_context()
_LOC_SSL.check_hostname = False
_LOC_SSL.verify_mode = ssl.CERT_NONE


def _loc_ok(url, alias_toks, timeout=12):
    """200 AND the handle appears in the page — so we only keep locales that really mirror her."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=_LOC_UA),
                                    timeout=timeout, context=_LOC_SSL) as r:
            if getattr(r, "status", 200) != 200:
                return False
            body = r.read(80000).decode("utf-8", "replace")
    except Exception:
        return False
    return any(t and t in _un(body) for t in alias_toks)


def _loc_verify_langs(build, langs, sample_path, alias_toks):
    """One probe per candidate locale (threaded) on a real confirmed path; keep the ones that
    resolve. Applied to ALL that host's paths afterwards (the CMS mirrors uniformly)."""
    def ok(lg):
        return lg if _loc_ok(build(lg, sample_path), alias_toks) else None
    good = []
    try:
        with _cf.ThreadPoolExecutor(max_workers=8) as ex:
            for r in ex.map(ok, langs):
                if r:
                    good.append(r)
    except Exception:
        pass
    return good


def _locale_expand(links_by_domain, alias_toks, cap=AUDIT_DL_CAP):
    """For every confirmed PAGE URL on a known language-mirror host, emit the same path under each
    VERIFIED locale. Returns {registrable_domain: [new_urls]}. cdn/media hosts are skipped (their
    UUID media has no locale). Deduped against what's already confirmed."""
    from urllib.parse import urlsplit
    existing = set()
    for urls in links_by_domain.values():
        for u in urls:
            existing.add(report_live._norm_media(u))

    path_items, sub_items = {}, {}     # page-host -> [(canonical_path, orig_url)]
    for urls in links_by_domain.values():
        for u in urls:
            try:
                sp = urlsplit(u)
            except Exception:
                continue
            host = (sp.hostname or "").lower()
            if not host:
                continue
            base = host[4:] if host.startswith("www.") else host
            path = (sp.path or "/") + (("?" + sp.query) if sp.query else "")
            if base in LOCALE_PATH_HOSTS and host in (base, "www." + base):
                segs = path.lstrip("/").split("/", 1)
                if segs and segs[0] in _ALL_LOC_LANGS:        # strip an existing /lang/ prefix
                    path = "/" + (segs[1] if len(segs) > 1 else "")
                path_items.setdefault(base, []).append((path, u))
            else:
                labels = host.split(".")
                shost = ".".join(labels[1:]) if len(labels) >= 3 and labels[0] in _ALL_LOC_LANGS else host
                shost = shost[4:] if shost.startswith("www.") else shost
                if shost in LOCALE_SUB_HOSTS and host in (
                        (shost, "www." + shost) + tuple(f"{lg}.{shost}" for lg in _ALL_LOC_LANGS)):
                    sub_items.setdefault(shost, []).append((path, u))

    out = {}
    added = [0]

    def emit(host, variants):
        for v in variants:
            k = report_live._norm_media(v)
            if not k or k in existing:
                continue
            existing.add(k)
            out.setdefault(host, []).append(v)
            added[0] += 1

    for host, items in path_items.items():
        langs = _loc_verify_langs(lambda lg, p, h=host: f"https://{h}/{lg}{p}",
                                  LOCALE_PATH_HOSTS[host], items[0][0], alias_toks)
        for p, _orig in items:
            if added[0] >= cap:
                return out
            emit(host, [f"https://{host}/{lg}{p}" for lg in langs])
    for host, items in sub_items.items():
        langs = _loc_verify_langs(lambda lg, p, h=host: f"https://{lg}.{h}{p}",
                                  LOCALE_SUB_HOSTS[host], items[0][0], alias_toks)
        for p, _orig in items:
            if added[0] >= cap:
                return out
            emit(host, [f"https://{lg}.{host}{p}" for lg in langs])
    return out


def _pipeline_gallery(prefix, cap=None):
    """Curated 'Your leaked content' preview for the deep report: the vetted, handle-verified
    one-per-site leak photos build_gallery.py wrote to <prefix>_gallery.txt, embedded as data:
    URIs (they always render — no hotlink breakage). REPLACES the old CSE-thumbnail preview,
    which surfaced site logos / wrong-person frames ('Deepscan images are false'). Each line is
    'localpath|domain'. Resolves the file at the repo root (fresh run) OR campaigns/<base>/ (once
    triage archived the campaign), and contains reads to this scan's gallery cache dir; bounded
    by the same per-file / total-byte ceilings as the screenshots."""
    cap = cap or GALLERY_CAP
    base = os.path.basename(prefix)
    txt = os.path.join(HERE, f"{prefix}_gallery.txt")
    if not os.path.exists(txt):
        txt = os.path.join(HERE, "campaigns", base, f"{prefix}_gallery.txt")
    try:
        lines = open(txt, encoding="utf-8").read().splitlines()
    except OSError:
        return []
    allowed = [os.path.realpath(os.path.join(HERE, f"{prefix}_gallery_imgs")),
               os.path.realpath(os.path.join(HERE, "campaigns", base, f"{prefix}_gallery_imgs"))]
    out, total = [], 0
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        rel, _, dom = ln.partition("|")
        rel, dom = rel.strip(), dom.strip()
        if not rel:
            continue
        p = os.path.realpath(rel if os.path.isabs(rel) else os.path.join(HERE, rel))
        # containment: only embed files under this scan's gallery cache dir
        if not any(p == a or p.startswith(a + os.sep) for a in allowed):
            continue
        mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                ".webp": "image/webp"}.get(os.path.splitext(p)[1].lower())
        if not mime or not os.path.isfile(p):
            continue
        try:
            b = open(p, "rb").read()
        except Exception:
            continue
        if not b or len(b) > SHOT_MAX_BYTES or total + len(b) > SHOTS_TOTAL_MAX:
            continue
        total += len(b)
        out.append({"img": "data:%s;base64,%s" % (mime, base64.b64encode(b).decode("ascii")),
                    "domain": dom, "link": ("https://" + dom) if dom else ""})
        if len(out) >= cap:
            break
    return out


def _cleanup_webscan(prefix):
    """Delete every repo-root artifact a big-scan pipeline run wrote for `prefix`.
    Guarded to the webscan_* scratch namespace so it can never touch a real
    campaign; each scan uses a unique prefix, so concurrent scans don't collide."""
    base = os.path.basename(prefix)
    if not _WEBSCAN_RE.match(base):
        return
    targets = []
    for pat in (f"{base}.*", f"{base}-*", f"{base}_*"):
        targets += glob.glob(os.path.join(HERE, pat))
    targets += [os.path.join(HERE, "campaigns", base),
                os.path.join(HERE, "exports", f"{base}_latest")]
    for p in targets:
        try:
            if os.path.islink(p) or os.path.isfile(p):
                os.remove(p)
            elif os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
        except Exception:
            pass


def _deep_worker(slug, handle, platform, aliases_raw, ip, plus=False):
    """Run the big scan (= the real pipeline) to completion in the background,
    independent of any HTTP connection. Owns releasing the scan-concurrency slots.
    Never raises. `plus` = the wider pass (full-depth crawl instead of --web)."""
    _event(f"scan start level=deep{'+' if plus else ''} platform={platform}")
    tmp = tempfile.mkdtemp(prefix="pubscan-")
    # Scratch prefix derived from a hash of the (unique) db slug: always matches
    # ^webscan_[a-z0-9]+$ AND is injective, so two concurrent scans can never
    # collapse to the same prefix (which would let one's cleanup delete the
    # other's files, incl. on a case-insensitive filesystem).
    prefix = "webscan_" + hashlib.sha1(slug.encode("utf-8")).hexdigest()[:16]
    try:
        bases = _deep_aliases(handle, aliases_raw)
        strong = ",".join(bases[:3]) or handle
        slugsan = re.sub(r"[^a-z0-9]", "", handle.lower()) or "client"
        _job_set_slugs(slug, bases)
        if len(bases) > 1:
            _job_progress(slug, "Aliases: " + ", ".join(bases))
        names_file = os.path.join(tmp, "names.txt")
        with open(names_file, "w", encoding="utf-8") as fh:
            fh.write("\n".join(bases) + "\n")

        common = [sys.executable, PIPELINE, "--name", handle, "--brand", handle,
                  "--slug", slugsan, "--prefix", prefix, "--aliases-file", names_file,
                  "--strong", strong, "--no-live-chat"]
        web = [] if plus else ["--web"]

        # Phase 0 — CSE pre-flight (BEFORE the crawl). build_cse.py is independent of the crawl
        # (Google Programmable Search by name only) and its thumbnails are base64/gstatic — they
        # ACTUALLY render, unlike hotlinked leak-site media. Running it first means the live report
        # shows real evidence (indexed sites + top public results + leak-image thumbnails) within
        # seconds, while the multi-minute crawl proceeds. Best-effort: any failure just skips the
        # early preview (the phase-2 report still stands). Runs OUTSIDE the big-scan lock (touches
        # no shared frontier state) so a queued scan still previews immediately.
        try:
            _job_progress(slug, "Checking where you already show up on Google…")
            wc.run_subprocess([sys.executable, "build_cse.py", "--name", handle,
                               "--strong", strong, "--out", f"{prefix}.cse.json"],
                              PIPE_SHOTS_TIMEOUT, cwd=HERE,
                              on_line=lambda s: _job_progress(slug, s))
            _job_set_cse_preview(slug, prefix)
        except Exception:
            pass

        # Serialize the actual pipeline run (shared slugs_cache.json is not lock-
        # safe). Queued scans keep their slot and just wait their turn.
        rc1 = None
        if not _BIG_SCAN_LOCK.acquire(blocking=False):
            _job_progress(slug, "Queued — another deep scan is running; you'll pick up shortly…")
            _BIG_SCAN_LOCK.acquire()
        try:
            # Phase 1 — discovery + export: presence scan → deep crawl → clean → triage →
            # DMCA export. Core steps here can abort the run on failure, so they run FIRST
            # and alone. `export` is here (NOT phase 2) on purpose: it produces the headline
            # confirmed-leak layer (metadata.jsonl → the 'Confirmed leaks' count, the price,
            # every dropdown link), and a flaky/slow phase-2 gallery download must never be
            # able to cost us those numbers. rc1 is kept so a hard failure becomes 'failed'.
            _job_progress(slug, f"Deep-crawling the sites that host @{handle} "
                                f"across {VERIFIED_DOMAINS} known leak sites…")
            rc1 = wc.run_subprocess(common + ["--only", "scan,seed,crawl,clean,triage,export"] + web,
                                    PIPE_DISCOVERY_TIMEOUT, cwd=HERE,
                                    on_line=lambda s: _job_progress(slug, s))

            # Phase 2 — Google index (CSE) + curated gallery. CSE-ONLY: no browser, no
            # Incogniton ever touches google.com. The report's Google-results screenshots are
            # reconstructed CLIENT-SIDE from this CSE data (thumbnails + indexed sites + top
            # public results); the preview strip is build_gallery's handle-verified leak photos
            # — so the deep report surfaces the SAME layers make_report.py does, without
            # embedding any multi-MB captures. All-optional: a failure here degrades gracefully
            # (CSE-thumbnail preview, no Google grids) — the phase-1 counts/links still stand.
            #   cse     -> {prefix}.cse.json (indexed sites, top results, thumbnails, google_total)
            #   gallery -> {prefix}_gallery.txt (vetted one-per-site leak photos — the preview)
            shot_src = "cse"
            # cse already ran in phase 0 (its json is on disk) — phase 2 only builds the curated
            # preview gallery. In CSE-images-only mode there's nothing left to do here.
            phase2 = "" if BIG_SCAN_CSE_IMAGES_ONLY else "gallery"
            if phase2:
                _job_progress(slug, "=== [gallery] preview gallery ===")
                _job_progress(slug, "Building your preview gallery…")
                wc.run_subprocess(common + ["--only", phase2, "--google-shots", "cse"] + web,
                                  PIPE_SHOTS_TIMEOUT, cwd=HERE,
                                  on_line=lambda s: _job_progress(slug, s))
        finally:
            _BIG_SCAN_LOCK.release()

        # Bridge the pipeline's artifacts into the public report shape — the SAME layers
        # make_report.py renders: confirmed-leak URLs + price (export), the media count +
        # preview gallery (crawl), and the Google-index breakdown (cse).
        rows, gtotal = _pipeline_rows(prefix, handle)
        # Never lose hits that already streamed live: if the crawl subprocess was
        # killed (timeout) before writing its json, fold every FOUND domain back
        # in. When the json IS present its richer rows win (merge_rows).
        snap = _job_snapshot(slug)
        if snap and snap.get("found"):
            live_rows = [{"domain": f["domain"], "url": "https://" + f["domain"] + "/",
                          "occurrences": f.get("occurrences", 0), "method": "scrape",
                          "alias": handle, "live": True} for f in snap["found"]]
            rows = merge_rows(rows, live_rows)

        crawl = (_load_json_file(os.path.join(HERE, f"{prefix}.crawl.clean.json"))
                 or _load_json_file(os.path.join(HERE, f"{prefix}.crawl.json")) or [])
        cse = _load_json_file(os.path.join(HERE, f"{prefix}.cse.json")) or {}
        strong_tokens = [t for t in strong.split(",") if t]

        # Confirmed-leak layer (export's LIKELY bucket): the 'Confirmed leaks' count, the
        # price basis, and every URL for the dropdowns. Uncapped domain set = hosting count.
        n_leaks, links_by_domain, hosting_doms = _load_metadata(prefix)
        if not n_leaks:                        # export absent/empty -> degrade from the merged rows
            for r in rows:
                u, d = r.get("url"), r.get("domain")
                if u and d:
                    lst = links_by_domain.setdefault(d, [])
                    if u not in lst:
                        lst.append(u)
            hosting_doms = {r["domain"] for r in rows if r.get("domain")}
            n_leaks = sum(len(v) for v in links_by_domain.values()) or len(rows)

        cse_sites = [{"domain": s.get("domain"), "url": s.get("url", ""), "occ": s.get("occ", 0)}
                     for s in (cse.get("sites") or []) if s.get("domain")][:60]
        host_reg = {registrable_domain(d) for d in hosting_doms}
        host_reg.discard("")
        cse_reg = {registrable_domain(s["domain"]) for s in cse_sites}
        cse_reg.discard("")
        n_hosting = len(host_reg) or len({registrable_domain(r["domain"]) for r in rows if r.get("domain")})
        n_sites = len(host_reg | cse_reg) or n_hosting
        n_media = _media_count(crawl, strong_tokens)
        quote = price_for(n_leaks)
        gallery = _pipeline_gallery(prefix)

        # Audit lists — computed now, BEFORE _cleanup_webscan deletes the crawl/export artifacts.
        # accepted = every crawl candidate attributable to the creator (media on confirmed sites,
        # UUID CDN files, name/handle pages) PLUS the export's LIKELY∪POSSIBLE; removed = only
        # site assets + unattributable other-creator media. A human audits `removed` to confirm we
        # dropped nothing real — so it must NOT contain her actual leaks (the earlier bug).
        likely_urls, possible_urls = _export_urls(prefix)
        exported = likely_urls + possible_urls
        alias_toks = [_un(b) for b in (bases or [handle]) if _un(b)]
        part_acc, part_rem = _partition_candidates(crawl, exported, alias_toks)
        # accepted = attributable crawl candidates ∪ everything the export surfaced (some export
        # URLs — variant/search/google-discovered — aren't crawl candidates at all).
        acc_seen, accepted_urls = set(), []
        for u in part_acc + exported + [r.get("url") for r in rows]:
            k = report_live._norm_media(u) if u else ""
            if u and k and k not in acc_seen:
                acc_seen.add(k)
                accepted_urls.append(u)
        removed_urls = [u for u in part_rem if report_live._norm_media(u) not in acc_seen]

        # Locale-mirror expansion: fapello subdomains (es./it./…) + leakgallery/picazor/thothd
        # path locales (/it/…) serve the SAME confirmed path in every language — each a separately
        # indexed page = a separate takedown URL. Fold them into the confirmed links + the accepted
        # export so the count reflects EVERY removable URL (verified per host+locale, then applied).
        _job_progress(slug, "Expanding language-mirror takedown URLs (es./it./… + /lang/ paths)…")
        try:
            loc_by_dom = _locale_expand(links_by_domain, alias_toks)
        except Exception:
            loc_by_dom = {}
        n_locale = sum(len(v) for v in loc_by_dom.values())
        if n_locale:
            for d, locurls in loc_by_dom.items():
                links_by_domain.setdefault(d, []).extend(locurls)
                for u in locurls:
                    k = report_live._norm_media(u)
                    if k and k not in acc_seen:
                        acc_seen.add(k)
                        accepted_urls.append(u)
            n_leaks = sum(len(v) for v in links_by_domain.values())
            quote = price_for(n_leaks)
            _job_progress(slug, f"+{n_locale} language-mirror URLs → {n_leaks} confirmed total")

        extra = {
            "images": (cse.get("images") or [])[:18],
            "img_meta": (cse.get("img_meta") or [])[:14],
            "gallery": gallery,
            "google_total": gtotal,
            "cse_sites": cse_sites,
            "top_leaks": (cse.get("top_leaks") or [])[:14],
            "n_leaks": n_leaks, "n_media": n_media,
            "n_hosting": n_hosting, "n_sites": n_sites, "quote": quote,
            "links_by_domain": links_by_domain,
            "slugs": bases[:40],
            "accepted_urls": accepted_urls, "removed_urls": removed_urls,
            "n_accepted": len(accepted_urls), "n_removed": len(removed_urls),
        }
        # No rows can mean genuinely clean OR a broken run. Phase 1's discovery
        # steps are core, so a non-zero / could-not-start rc with nothing salvaged
        # means the scan never really ran → 'failed' (don't tell a victim "you're
        # clean" when the network was down). rc==0 with no rows is a true 'empty'.
        if rows:
            status = "complete"
        elif rc1 is None or rc1 != 0:
            status = "failed"
        else:
            status = "empty"
        db.finish_scan(slug, rows, status=status, extra=extra)
        result = {
            "slug": slug, "handle": handle, "platform": platform, "level": "deep",
            "status": status, "hit_count": len(rows),
            "domain_count": n_hosting, "hits": rows, **extra,
        }
        _job_finish(slug, status, result)
        _event(f"scan done level=deep leaks={n_leaks} hosting={n_hosting} sites={n_sites} "
               f"media={n_media} gallery={len(gallery)} quote={quote} ({shot_src})")
    except Exception as e:
        try:
            db.finish_scan(slug, [], status="failed")
        except Exception:
            pass
        _job_finish(slug, "failed", None)
        _event(f"deep worker crashed: {type(e).__name__}")
    finally:
        _cleanup_webscan(prefix)
        shutil.rmtree(tmp, ignore_errors=True)
        SCAN_LIMITER.release(ip)
        GLOBAL_SCANS.release()


def _clean_platforms(raw):
    """Whitelist the platform list; default to both. Returns a comma string."""
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.split(",")]
    plats = [p for p in (raw or []) if p in VERIFY_PLATFORMS]
    return ",".join(plats) if plats else ",".join(VERIFY_PLATFORMS)


def _run_bio_verify(handle, code, platforms):
    """Run bio_verify.py as a subprocess (heavy Playwright/Incogniton deps stay
    out of the web server) and return its result dict. Prefers the logged-in
    Incogniton browser; set BIO_VERIFY_HTTP_ONLY=1 to force a plain HTTP read.
    Never raises — returns {'verified': False, ...} with an error on failure."""
    tmp = tempfile.mkdtemp(prefix="bioverify-")
    try:
        out = os.path.join(tmp, "result.json")
        argv = [sys.executable, BIO_VERIFY, "--handle", handle, "--code", code,
                "--platforms", platforms, "--out", out]
        if os.environ.get("BIO_VERIFY_HTTP_ONLY", "") in ("1", "true", "True"):
            argv.append("--http-only")
        try:
            proc = subprocess.run(argv, cwd=HERE, capture_output=True, text=True,
                                  timeout=VERIFY_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"verified": False, "matched_platform": None, "checked": [],
                    "error": "timeout"}
        try:
            return json.load(open(out, encoding="utf-8"))
        except Exception:
            lines = [l for l in (proc.stdout or "").splitlines() if l.strip()]
            if lines:
                try:
                    return json.loads(lines[-1])
                except Exception:
                    pass
            return {"verified": False, "matched_platform": None, "checked": [],
                    "error": "no_result"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# >>> one-project patch (leakscan-site) >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# What this repo adds to upstream public_app.py (bruquiextension) lives in this block; every other line that
# differs from upstream ends in "# one-project" (app/tests/test_one_project.py lists the sites). Re-sync: README.
# 1) Same origin serves the landing site (SITE_DIR, default <repo>/site) and this API. Legacy scan UI
# moves from / to /app/. Paths below that the API owns are untouched.
import alias_enrich
import leakshaven
import site_static
import thumb_sheet

_API_PREFIXES = ("/api/", "/static/", "/s/")
_API_PATHS = ("/healthz", "/favicon.ico")
_PREFILL_KEYS = ("p", "h", "go", "l")


def _one_project_get(h, path):
    """GET/HEAD router for non-API paths. True = handled; False = fall through to legacy routes."""
    query = urllib.parse.urlsplit(h.path).query
    if path == "/app":
        return _redirect(h, 301, "/app/" + ("?" + query if query else ""))
    if path in ("/app/", "/app/index.html"):
        h._render_page("index.html")
        return True
    if path.startswith("/app/"):
        wc.serve_static(h, STATIC_ROOT, path[len("/app/"):],
                        extra_headers={"X-Content-Type-Options": "nosniff"})
        return True
    if path.startswith(_API_PREFIXES) or path in _API_PATHS:
        return False
    if path == "/" and any(k in urllib.parse.parse_qs(query) for k in _PREFILL_KEYS):
        return _redirect(h, 302, "/app/?" + query)  # jackbase.me/scan?p=&h=&go= deep links
    return site_static.serve(h, path)


def _redirect(h, code, location):
    h.send_response(code)
    h.send_header("Location", location)
    h.send_header("Content-Length", "0")
    h.end_headers()
    return True


class _NullWriter:
    def write(self, b):
        return len(b)

    def flush(self):
        pass


def _one_project_head(h):
    """HEAD = GET minus body, non-API paths only."""
    path = urllib.parse.urlparse(h.path).path
    if path.startswith(_API_PREFIXES) or path in _API_PATHS:
        return h.send_error(501, "Unsupported method ('HEAD')")
    real, cls_end = h.wfile, type(h).end_headers

    def end_headers():
        cls_end(h)
        h.wfile = _NullWriter()  # headers flushed; drop any body
    h.end_headers = end_headers
    try:
        h.do_GET()
    finally:
        h.wfile = real
        del h.end_headers


# 2) Quick scan. Alias enrichment: read a few found leak pages for the creator's other handles, re-scan <= 2 of them.
ALIAS_ENRICH = os.environ.get("ALIAS_ENRICH", "1").lower() in ("1", "true", "yes")
ALIAS_NEW_MAX = 2             # new aliases CSE-scanned per scan (each <= CSE_QUICK_CALLS calls)
ALIAS_TOTAL_MAX = 4           # declared + discovered aliases per scan
ALIAS_BUDGET = float(os.environ.get("ALIAS_BUDGET", "12"))          # s: page reads + extra CSE, hard cap
ALIAS_SKIP_AFTER = float(os.environ.get("ALIAS_SKIP_AFTER", "45"))  # s into the scan: past this, skip the step


def _alias_cse(alias, deadline, errors=None):
    """One discovered alias -> CSE items tagged alias=<alias> (<= CSE_QUICK_CALLS calls). Never raises."""
    seeds = [alias] + [f"{p} {alias}" for p in CSE_PREFIXES]
    try:
        items, _ = cse_scanner.cse_search_wide(seeds, max_calls=CSE_QUICK_CALLS, tags=[alias] * len(seeds),
                                               deadline=deadline, errors=errors)
        return items
    except Exception as e:
        if errors is not None:
            errors.append(type(e).__name__)
        return []


def enrich_aliases(declared, rows, results, prog, started, errors=None):
    """First-pass rows/results -> (extra CSE items, discovered aliases scanned, leak-page socials, names).
    Bounded: skipped with 0 hits or when the scan already ran ALIAS_SKIP_AFTER s; <= ALIAS_BUDGET s."""
    none = ([], [], [], [])
    if not ALIAS_ENRICH or not rows:
        return none
    if time.monotonic() - started > ALIAS_SKIP_AFTER:
        _event("alias_enrich skipped: budget")
        if errors is not None:
            errors.append("alias_budget")
        return none
    t0 = time.monotonic()
    deadline = t0 + ALIAS_BUDGET
    prog("Checking other names…")
    d = alias_enrich.discover(rows, results, declared, budget=min(alias_enrich.FETCH_TOTAL, ALIAS_BUDGET))
    low = {a.lower() for a in declared}
    room = max(0, min(ALIAS_NEW_MAX, ALIAS_TOTAL_MAX - len(declared)))
    new = [a for a in d["aliases"] if a.lower() not in low][:room]
    extra = []
    if new and deadline - time.monotonic() > 2:
        prog("Also searching Google for " + ", ".join("@" + a for a in new) + "…")
        with _cf.ThreadPoolExecutor(max_workers=len(new)) as ex:
            for items in ex.map(lambda a: _alias_cse(a, deadline, errors), new):
                extra += items
    else:
        new = []
    _event(f"alias_enrich pages={d['pages']} cand={d['cand']} kept={d['kept']} new={len(new)} "
           f"items={len(extra)} secs={time.monotonic() - t0:.1f} reasons={alias_enrich.reasons_str(d['reasons'])}")
    return extra, new, d["socials"], d["names"]


def leakshaven_start(handle, platform, socials, aliases, names, prog, fresh=False):
    """Starts the leakshaven.com step (it runs next to the profile step) -> join() returning (mega items, cache
    key to store or None). Cache: a scan of this handle from the last 6 h whose lookup had the same inputs
    (leakshaven.cache_key: platform, search term, aliases, names), unless `fresh`; else one suggest + one pack-list
    request in a worker thread (<= leakshaven.TIMEOUT s). Never raises; one log line."""
    if not leakshaven.ENABLED:
        return lambda: ([], None)
    term = socials.get("instagram") or handle
    key = leakshaven.cache_key(platform, term, aliases, names)
    try:
        ex = None if fresh else db.recent_extra(handle, leakshaven.CACHE_FIELD, key, leakshaven.CACHE_TTL)
    except Exception:
        ex = None
    if ex is not None:
        mega = ex.get("mega") if isinstance(ex.get("mega"), list) else []
        _event(f"leakshaven cache=hit packs={len(mega)}")
        return lambda: (mega, None)   # only a fresh fetch is a cache source: TTL can't roll forward
    prog("Checking leak aggregators…")
    t0 = time.monotonic()
    fut, done = leakshaven.start(term, aliases, names), {}
    fut.add_done_callback(lambda _: done.setdefault("at", time.monotonic()))   # secs = the lookup's own time

    def join():
        mega, reason = leakshaven.result(fut, t0 + leakshaven.TIMEOUT - time.monotonic())
        _event(f"leakshaven {reason} packs={len(mega)} secs={done.get('at', time.monotonic()) - t0:.1f}")
        return mega, key if reason in ("ok", "nomatch") else None
    return join


def merge_items(results, extra):
    """CSE items unioned by link; first sighting (and its alias tag) wins."""
    seen = {it.get("link") for it in results}
    out = list(results)
    for it in extra:
        if it.get("link") and it["link"] not in seen:
            seen.add(it["link"])
            out.append(it)
    return out


def scan_begin(handle, platform, aliases, socials, rows, results, prog, started, fresh=False, errors=None):
    """_scan_cse after its first CSE pass: alias enrichment (its items merged into results / rows), then the
    leakshaven step starts (it runs next to the profile step) -> (op, rows, results); op feeds the other hooks."""
    extra, found, found_socials, names = enrich_aliases(aliases, rows, results, prog, started, errors)
    if extra:
        results = merge_items(results, extra)
        rows = cse_scanner.summarize_cse(results)
    mine = {v.lower() for v in socials.values()}
    info = {"declared": list(aliases), "discovered": found,
            "socials": [s for s in found_socials if s["handle"].lower() not in mine]}
    join = leakshaven_start(handle, platform, socials, list(aliases) + found + [s["handle"] for s in info["socials"]],
                            names, prog, fresh)
    return {"aliases": info, "hints": {"names": names, "aliases": found}, "join": join}, rows, results


def _estimate(n_results, n_rows):
    """The grounded Google-index estimate (upstream's formula, one place): _scan_cse's google_total, and what each
    result / hit row added to it when the aggregator rule takes one out again (off_aggregators)."""
    return int(round(n_results * ESTIMATE_URL_MULT + n_rows * ESTIMATE_SITES_MULT))


def scan_end(op, handle, rows, results, google_total):
    """_scan_cse after the profile step: joins the leakshaven step. Packs go to mega[] only (never hit rows); a hit
    row / CSE result on a pack's host neither shows nor counts, nor does anything taken from it: the preview images are
    re-picked from the results left, and media_gather's cse_items are only those (off_aggregators). The profile step
    ran next to the lookup (it can't wait for it) on every result, a pack page's title / snippet as text evidence like
    any leak page's, and media_gather's refine reuses those sources (text only); it shows no host, url or thumb of
    one. -> (rows, results, status, pub, mega_key): pub = what the stored row's extra_json and the live result both
    take (it replaces upstream's images / results / google_total, adds aliases / mega); mega_key goes to the stored row
    only (never served)."""
    mega, key = op["join"]()
    rows, results, google_total = off_aggregators(mega, rows, results, google_total)
    pub = {"images": cse_scanner.good_images(results, handle, CSE_IMAGES), "results": shape_results(results),
           "google_total": google_total, "aliases": op["aliases"], "mega": mega}
    return rows, results, "empty" if not rows else "complete", pub, key


def off_aggregators(mega, hits, results, google_total):
    """The aggregator rule, one place: hit rows / CSE results on a mega[] item's host (leakshaven.off_aggregators)
    neither show nor count -> (hits, results, google_total). google_total loses what _estimate gave each dropped row
    and result, never below 0; it stands when it is Google's raw number (USE_TOTAL_RESULTS_QUERY) or sits at the
    GOOGLE_INDEX_MAX cap (the uncapped figure is gone)."""
    kept_h, kept_r = leakshaven.off_aggregators(hits, mega), leakshaven.off_aggregators(results, mega, "link")
    gone = _estimate(len(results or []) - len(kept_r), len(hits or []) - len(kept_h))
    gt = google_total
    if (gone and not USE_TOTAL_RESULTS_QUERY and isinstance(gt, (int, float)) and not isinstance(gt, bool)
            and not 0 < GOOGLE_INDEX_MAX <= gt):
        google_total = max(0, int(round(gt - gone)))
    return kept_h, kept_r, google_total


def off_row(row):
    """A stored scan row (db.get_scan's dict) under the aggregator rule, for scans stored before it (their hit rows can
    hold packs, their results Google hits on a pack's host, their images those results' thumbs): what is left is
    recounted (hit_count, domain_count, status, google_total). Such a row kept only its shaped results
    (<= RESULTS_CAP), so their part of the images / google_total repair is a lower bound. Mutates and returns row."""
    if row and row.get("mega"):
        n, res = len(row["hits"]), row.get("results") or []
        row["hits"], row["results"], row["google_total"] = off_aggregators(
            row["mega"], row["hits"], row.get("results"), row.get("google_total"))
        gone = {r.get("thumb") for r in res if r not in row["results"]} - {None}
        if gone and isinstance(row.get("images"), list):
            row["images"] = [u for u in row["images"] if u not in gone]
        if len(row["hits"]) < n:
            row["hit_count"], row["domain_count"] = len(row["hits"]), db.domain_count(row["hits"])
            if row["status"] == "complete" and not row["hits"]:
                row["status"] = "empty"
    return row


def scan_row(slug):
    """db.get_scan + the aggregator rule (off_row)."""
    return off_row(db.get_scan(slug))


# whole-scan reuse: a repeat quick scan (same platform, handle, aliases, declared socials) inside SCAN_REUSE_TTL gets its
# own new row + slug holding a fresh scan's result, no external call. Only a whole fresh result stores the key
# (scan_reuse_value), a reused row never does, nor the leakshaven key: the TTL can't roll forward. Body fresh:true skips it.
# `as_of` (SSE result, /api/scan-result): when the data was really scanned, the source's created_at on a reuse.
SCAN_REUSE_TTL = int(os.environ.get("SCAN_REUSE_TTL", str(leakshaven.CACHE_TTL)))   # s; 0 = off
SCAN_REUSE_FIELD = "scan_key"                                                       # scans.extra_json, never served


# Retention (db.retain_scans has the tiers). >= 1 day: a reuse source (6 h) is always whole; small never under big.
RETAIN_BIG_DAYS = max(1.0, float(os.environ.get("RETAIN_BIG_DAYS", "3")))
RETAIN_SMALL_DAYS = max(RETAIN_BIG_DAYS, float(os.environ.get("RETAIN_SMALL_DAYS", "30")))
RETAIN_EVERY_S = 86400


def _db_bytes():
    return sum(os.path.getsize(p) for p in (db.DB_PATH, db.DB_PATH + "-wal") if os.path.exists(p))


def _drop_files(slug):
    """A scan's avatar and media dir -> files or dirs removed."""
    n = media_gather.drop_media(slug)
    p = _avatar_path(slug)
    if p:
        os.remove(p)
        n += 1
    return n


def run_retention():
    """One pass, never raises: the tiers, their files, the orphans (files whose row is gone or that crashed mid-run, a day
    past big so a scan's own file can't go before its row; media-cache keeps its own TTL), VACUUM if rows changed. One
    log line, no handles."""
    t0, before = time.time(), _db_bytes()
    n, files = None, 0
    try:
        n = db.retain_scans(RETAIN_BIG_DAYS, RETAIN_SMALL_DAYS, repair=off_row)
        for slug in n["slugs"]:
            try:
                files += _drop_files(slug)
            except OSError:
                pass
        files += _prune_avatars(RETAIN_BIG_DAYS + 1) + media_gather.prune(RETAIN_BIG_DAYS + 1)
        if n["trimmed"] or n["summary"]:
            db.vacuum()
        _event(f"retention trimmed={n['trimmed']} summary={n['summary']} corrupt={n['corrupt']} errors={n['errors']} "
               f"files={files} db_before={before} db_after={_db_bytes()} secs={time.time() - t0:.1f}")
    except Exception as e:
        _event(f"retention failed: {type(e).__name__} {'rows done' if n else 'no rows'} secs={time.time() - t0:.1f}")
    return n


def _retention_loop():
    while True:
        run_retention()
        time.sleep(RETAIN_EVERY_S)


def _summary_hits(scan):
    """A summary row has no hits: the chat's scan context reads its top_domains, not "no public leaks were found"."""
    if scan and scan.get("retention") == "summary":
        scan["hits"] = [{"domain": t.get("domain"), "occurrences": t.get("n")} for t in scan.get("top_domains") or []]
    return scan


def scan_reuse_key(platform, handle, aliases, socials):
    """Everything a quick scan's result depends on -> opaque key (instagram=y and x=y are different scans)."""
    return leakshaven.cache_key(platform, handle, aliases, [f"{k}={socials[k]}" for k in sorted(socials)])


def scan_reuse_value(key, status, errors, mega_key, profile):
    """What a fresh row stores under SCAN_REUSE_FIELD: the key for a whole result, else None. Not whole: no rows; any
    Google call failed or the alias step was skipped (few rows would pass for few leaks, `errors`); the aggregator lookup
    failed or came from its own cache (a TTL on top of its TTL; mega_key None); the profile is the LLM-less fallback."""
    whole = (status == "complete" and not errors and (mega_key or not leakshaven.ENABLED)
             and (not PROFILE_ENABLED or (profile or {}).get("generated_by") == "deepseek"))
    return key if whole and SCAN_REUSE_TTL > 0 else None


def _read_avatar(slug):
    """A saved avatar as _save_avatar takes it -> (bytes, ext) | None."""
    p = _avatar_path(slug)
    try:
        with open(p or "", "rb") as fh:
            return fh.read(), p.rsplit(".", 1)[1]
    except OSError:
        return None


def scan_reuse_serve(h, key, handle, platform, ip, aliases, socials):
    """A recent whole scan under `key` -> its result as this visitor's own new row and the SSE a fresh scan ends with;
    no external call -> True. None (or any failure) -> False: the caller scans. The visitor's own typing of her handle,
    aliases and socials stands; nothing of the source's row but its result (never its ip hash, verify fields or key)."""
    try:
        src = db.recent_scan(handle, SCAN_REUSE_FIELD, key, SCAN_REUSE_TTL)
        if not src:
            return False
        ex, rows, avatar = src["extra"], src["hits"], _read_avatar(src["slug"])
        profile = ex.get("profile")
        if isinstance(profile, dict):
            profile = {**profile, "avatar": bool(avatar)}
        pub = {"images": ex.get("images") or [], "results": ex.get("results") or [], "google_total": ex.get("google_total"),
               "aliases": {**(ex.get("aliases") or {}), "declared": list(aliases)}, "mega": ex.get("mega") or []}
        slug = db.insert_scan(rows, handle=handle, level="low", platform=platform, status="complete",
                              client_ip_hash=_ip_hash(ip),
                              extra={"profile": profile, "socials": socials, "reused_from": src["slug"], "as_of": src["created_at"], **pub})
        if avatar and not _save_avatar(slug, avatar) and profile:
            profile["avatar"] = False
        media = {"status": media_gather.adopt(slug, src["slug"])}
    except Exception as e:
        _event(f"scan reuse failed: {type(e).__name__}")
        return False
    _event(f"scan reuse hit level=low platform={platform} aliases={len(aliases)} hits={len(rows)} "
           f"age={src['age_s']}s media={media['status']}")
    wc.sse(h, "progress", "Loading a recent scan…")
    wc.sse(h, "result", json.dumps({
        "slug": slug, "handle": handle, "platform": platform, "level": "low",
        "status": "complete", "hit_count": len(rows), "domain_count": db.domain_count(rows),
        "profile": profile, "media": media, "socials": socials, "hits": rows, "as_of": src["created_at"], **pub,
    }, ensure_ascii=False))
    wc.sse(h, "done", "end")
    return True


# 3) the one video rule (replaces upstream's): the landing / scan page read `kind` only (no client-side URL sniffing)
_VIDEO_LINK_RE = re.compile(r"\.(?:mp4|m3u8|webm|mov|mkv)(?:[?#]|$)|/(?:videos?|watch|embed|clips?|vod)(?:[/?#.-]|$)", re.I)
# <<< one-project patch <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    # ------------------------------------------------------------------- CORS
    def _cors_origin(self):
        hdrs = getattr(self, "headers", None)
        o = ((hdrs.get("Origin") if hdrs else None) or "").rstrip("/")
        return o if o in CORS_ORIGINS else None

    def end_headers(self):
        # Every response path (_json, _html, SSE via wc.sse_start, /api/thumb, static) ends here.
        o = self._cors_origin()
        if o:
            self.send_header("Access-Control-Allow-Origin", o)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Expose-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        """CORS preflight. Not rate-limited; unknown origin -> bare 204."""
        self.send_response(204)
        if self._cors_origin():
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ------------------------------------------------------------- responders
    def _html(self, body, code=200, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        for k, v in SEC_HEADERS.items():
            self.send_header(k, v)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200, extra=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _render_page(self, filename, extra=None):
        try:
            html = open(os.path.join(STATIC_ROOT, filename), encoding="utf-8").read()
        except FileNotFoundError:
            return wc.send_simple(self, 404, "Not found")
        cfg = {"dm": _dm_config(), "verifiedDomains": VERIFIED_DOMAINS,
               "kb": os.path.isfile(KB_FILE),
               "display": {"perDomainMult": DISPLAY_PER_DOMAIN_MULT,
                           "totalMult": DISPLAY_TOTAL_MULT,
                           "topDomains": STATS_TOP_DOMAINS,
                           "urlMaxLen": TOP_LEAK_URL_MAX_LEN}}
        inject = ('<script id="app-config" type="application/json">'
                  + json.dumps(cfg) + "</script>")
        self._html(html.replace("<!--APP_CONFIG-->", inject).encode("utf-8"), 200, extra)

    def api_thumb(self):
        """Same-origin proxy for Google-hosted CSE thumbnails so the client can
        draw them into the shareable poster <canvas> WITHOUT tainting it (remote
        images taint the canvas → toBlob throws). SSRF-guarded: https only, an
        allowlisted Google thumbnail host only, redirects blocked, size-capped."""
        if not THUMB_LIMITER.allow(wc.client_ip(self), concurrency=False):
            return self._json({"error": "rate_limited"}, 429)
        qs = urllib.parse.urlparse(self.path).query
        u = (urllib.parse.parse_qs(qs).get("u") or [""])[0]
        pu = urllib.parse.urlparse(u) if u else None
        host = (pu.hostname or "").lower() if pu else ""
        ok_host = any(host == h or host.endswith("." + h) for h in THUMB_HOSTS)
        if not pu or pu.scheme != "https" or not ok_host:
            return wc.send_simple(self, 400, "Bad thumbnail URL")
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*"})
            with _THUMB_OPENER.open(req, timeout=8) as r:
                ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if not ctype.startswith("image/"):
                    return wc.send_simple(self, 415, "Not an image")
                data = r.read(THUMB_MAX_BYTES + 1)
        except Exception:
            return wc.send_simple(self, 502, "Thumbnail fetch failed")
        if len(data) > THUMB_MAX_BYTES:
            return wc.send_simple(self, 413, "Thumbnail too large")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if not self._cors_origin():  # one-project: api_thumb Vary (a plain and a CORS pixel-reading load never share a cache entry)
            self.send_header("Vary", "Origin")  # one-project: api_thumb Vary
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_json_capped(self, cap):
        try:
            n = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            n = 0
        if n > cap:
            self._json({"error": "payload_too_large"}, 413)
            return None
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    # ----------------------------------------------------------------- routing
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if _one_project_get(self, path):  # one-project: landing site
            return  # one-project: landing site
        if path in ("/", "/index.html"):
            return self._render_page("index.html")
        if path == "/healthz":
            return self._json({"ok": True, "domains": VERIFIED_DOMAINS,
                               "kb": os.path.isfile(KB_FILE)})
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if path == "/api/thumb":
            return self.api_thumb()
        if path.startswith("/api/thumb-sheet/"):  # one-project: thumb sheet
            return thumb_sheet.serve(self, path[len("/api/thumb-sheet/"):], scan_row, _THUMB_OPENER, THUMB_HOSTS, THUMB_MAX_BYTES)  # one-project: thumb sheet
        if path == "/api/chat-kb":
            return self.api_chat_kb()
        if path.startswith("/static/"):
            wc.serve_static(self, STATIC_ROOT, path[len("/static/"):],
                            extra_headers={"X-Content-Type-Options": "nosniff"})
            return
        if path.startswith("/s/"):
            slug = path[len("/s/"):]
            if not db.SLUG_RE.match(slug):
                return wc.send_simple(self, 404, "Not found")
            return self._render_page("share.html",
                                     extra={"X-Robots-Tag": "noindex, nofollow"})
        if path.startswith("/api/scan-result/"):
            return self.api_scan_result(path[len("/api/scan-result/"):])
        if path.startswith("/api/profile/"):
            return self.api_profile(path[len("/api/profile/"):])
        if path.startswith("/api/avatar/"):
            return self.api_avatar(path[len("/api/avatar/"):])
        if path.startswith("/api/media/"):
            return self.api_media(path[len("/api/media/"):])
        if path.startswith("/api/scan-links/"):
            return self.api_scan_links(path[len("/api/scan-links/"):])
        return wc.send_simple(self, 404, "Not found")

    def do_HEAD(self):  # one-project: HEAD
        return _one_project_head(self)  # one-project: HEAD

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/public-scan":
            return self.api_public_scan()
        if path == "/api/chat":
            return self.api_chat()
        if path == "/api/verify-start":
            return self.api_verify_start()
        if path == "/api/verify-check":
            return self.api_verify_check()
        return wc.send_simple(self, 404, "Not found")

    # ------------------------------------------------------ ownership (bio code)
    def api_verify_start(self):
        """Mint a one-time bio code the creator pastes into their IG/OnlyFans bio."""
        if not BIO_VERIFY_ENABLED:
            return self._json({"error": "verification_disabled"}, 404)
        ip = wc.client_ip(self)
        body = self._read_json_capped(2048)
        if body is None:
            return
        if not VERIFY_LIMITER.allow(ip, concurrency=False):
            return self._json({"error": "rate_limited"}, 429)
        aliases = wc.clean_aliases(body.get("handle") or "", max_aliases=1)
        if not aliases:
            return self._json({"error": "bad_handle"}, 400)
        code = db.new_verify_code()
        _event("verify-start")
        return self._json({
            "handle": aliases[0], "code": code, "platforms": list(VERIFY_PLATFORMS),
            "instructions": (f"Add {code} anywhere in your Instagram or OnlyFans bio, "
                             f"then click Verify. You can remove it once verified."),
        })

    def api_verify_check(self):
        """Check the code is live in the creator's bio; on success flip the scan's
        ownership_verified flag (unlocks takedown filing)."""
        if not BIO_VERIFY_ENABLED:
            return self._json({"error": "verification_disabled"}, 404)
        ip = wc.client_ip(self)
        body = self._read_json_capped(2048)
        if body is None:
            return
        if not VERIFY_LIMITER.allow(ip):
            return self._json({"error": "rate_limited"}, 429)
        wc.sse_start(self)
        try:
            handle = (wc.clean_aliases(body.get("handle") or "", max_aliases=1) or [""])[0]
            code = re.sub(r"[^A-Za-z0-9-]", "", (body.get("code") or ""))[:40]
            slug = body.get("slug")
            platforms = _clean_platforms(body.get("platforms"))
            if not handle or not code:
                return wc.sse_fail(self, "Enter your handle and the code from your scan.")
            pretty = platforms.replace(",", " & ")
            wc.sse(self, "progress", f"Reading your {pretty} bio for {code}…")
            _event("verify-check start")
            result = _run_bio_verify(handle, code, platforms)
            if result.get("verified") and slug and db.SLUG_RE.match(slug or ""):
                try:
                    db.mark_verified(slug)
                except Exception:
                    pass
            _event(f"verify-check done verified={bool(result.get('verified'))}")
            wc.sse(self, "result", json.dumps(result, ensure_ascii=False))
            wc.sse(self, "done", "end")
        finally:
            VERIFY_LIMITER.release(ip)

    # -------------------------------------------------------------- chat proxy
    def api_chat(self):
        ip = wc.client_ip(self)
        body = self._read_json_capped(32768)  # 32 KB
        if body is None:
            return  # 413 already sent
        if not CHAT_LIMITER.allow(ip):
            return self._json({"error": "rate_limited"}, 429)
        try:
            wc.sse_start(self)
            slug = body.get("slug")
            scan = scan_row(slug) if slug else None  # one-project: aggregator rule
            _summary_hits(scan)  # one-project: retention
            landing = body.get("kb") == "landing"   # unknown kb values -> default scan-app mode
            kb_text = chat_proxy.load_kb(KB_LANDING_FILE if landing else KB_FILE)
            if landing and not kb_text:
                # No grounding -> no answer (the landing prompt must never improvise facts).
                return wc.sse_fail(self, "The assistant is unavailable right now. "
                                         "Please DM me on Telegram, WhatsApp or email.")
            ctx = chat_proxy.scan_summary(scan)
            sc = None if landing else body.get("scan_context")   # live scan status: scan app only
            if isinstance(sc, str) and sc.strip():
                # 2000 (was 900): the deep scan's live context now teaches the model the
                # full stage list + not-finished rule — truncating it re-introduces the
                # "375/375 checks done => the scan is finished" hallucination.
                ctx = (ctx + "\n\nLIVE STATUS: " + sc.strip()[:2000]).strip()
            msgs = chat_proxy.build_messages(
                kb_text, ctx, body.get("messages") or [],
                chat_proxy.LANDING_SYSTEM_PROMPT if landing else chat_proxy.SYSTEM_PROMPT)
            if not any(m["role"] == "user" for m in msgs):
                return wc.sse_fail(self, "Ask me anything about your scan or getting leaks removed.")
            _event("chat start")
            chat_proxy.stream_chat(self, msgs)
            _event("chat done")
        finally:
            CHAT_LIMITER.release(ip)

    def api_chat_kb(self):
        """Monitoring: is the landing KB deployed? Size + mtime only, never content."""
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        kb = (qs.get("kb") or [""])[0]
        if kb != "landing":
            return self._json({"error": "unknown_kb"}, 404)
        try:
            st = os.stat(KB_LANDING_FILE)
            size, updated = st.st_size, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime))
        except OSError:
            size, updated = 0, None
        return self._json({"kb": kb, "ok": bool(chat_proxy.load_kb(KB_LANDING_FILE)),
                           "bytes": size, "updated": updated})

    # ------------------------------------------------------------- scan result
    def api_scan_result(self, slug):
        ip = wc.client_ip(self)
        if not RESULT_LIMITER.allow(ip, concurrency=False):
            return self._json({"error": "rate_limited"}, 429)
        noindex = {"X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer"}
        snap = _job_snapshot(slug)
        # A deep scan still running in THIS process -> stream live progress so a
        # reconnecting/reloaded page can pick the scan back up.
        if snap and snap["status"] == "running":
            payload = {
                "slug": slug, "status": "running", "level": snap["level"],
                "handle": snap["handle"], "platform": snap["platform"],
                "count": snap["count"], "found": snap["found"],
                "slugs": snap["slugs"], "phase": snap["phase"],
                "log": snap["log"],
            }
            # Deep scans get the live building-report payload (provisional candidates ticker +
            # authoritative confirmed layer once export is done). Cheap: one cached crawl read.
            if snap["level"] == "deep":
                try:
                    payload["live"] = _live_report(slug, snap)
                except Exception:
                    pass          # never let the live layer break the poll
            return self._json(payload, 200, extra=noindex)
        row = scan_row(slug)  # one-project: aggregator rule
        if not row:
            return self._json({"error": "not_found"}, 404, extra=noindex)
        # A 'running' row with no in-memory job = orphaned by a restart -> failed.
        if row["status"] == "running" and not snap:
            return self._json({"slug": slug, "status": "failed"}, 200, extra=noindex)
        pub = {k: row[k] for k in ("slug", "level", "platform", "handle",
                                   "created_at", "status", "hit_count",
                                   "domain_count", "ownership_verified")}
        pub["as_of"] = row["created_at"]  # one-project: scan reuse
        pub["hits"] = row["hits"]
        pub["images"] = row.get("images", [])
        pub["google_total"] = row.get("google_total")
        pub["slugs"] = row.get("slugs", [])
        for key in ("img_meta", "gallery", "cse_sites", "top_leaks", "n_leaks",
                    "n_media", "n_hosting", "n_sites", "quote", "links_by_domain",
                    "n_accepted", "n_removed"):   # counts only — the URL lists come from /api/scan-links
            if key in row:
                pub[key] = row[key]
        pub["mega"] = row.get("mega") or []  # one-project: mega[]
        pub.update({k: row[k] for k in ("retention", "top_domains") if k in row})  # one-project: retention
        if row["level"] == "low":
            ex = _scan_extra_all(slug) or {}
            pub["as_of"] = ex.get("as_of") or row["created_at"]  # one-project: scan reuse
            pub["results"] = row.get("results") or []  # one-project: aggregator rule (scan_row filtered them)
            pub["profile"] = ex.get("profile")
            pub["socials"] = ex.get("socials") or {}
            pub["aliases"] = ex.get("aliases") or {"declared": [], "discovered": [], "socials": []}  # one-project: aliases
            pub["media"] = {"status": media_gather.public_view(slug)["status"]}
        return self._json(pub, 200, extra=noindex)

    def api_profile(self, slug):
        """Cheap poll: {slug, profile} for a saved scan (profile may be null)."""
        noindex = {"X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer"}
        if not RESULT_LIMITER.allow(wc.client_ip(self), concurrency=False):
            return self._json({"error": "rate_limited"}, 429, extra=noindex)
        ex = _scan_extra_all(slug) if db.SLUG_RE.match(slug or "") else None
        if ex is None:
            return self._json({"error": "not_found"}, 404, extra=noindex)
        return self._json({"slug": slug, "profile": ex.get("profile")}, 200, extra=noindex)

    def api_avatar(self, slug):
        """Avatar saved at scan time. Only <DATA_DIR>/avatars/<valid slug>.<ext>; no proxying."""
        if not THUMB_LIMITER.allow(wc.client_ip(self), concurrency=False):
            return self._json({"error": "rate_limited"}, 429)
        p = _avatar_path(slug) if db.SLUG_RE.match(slug or "") else None
        if not p:
            return self._json({"error": "not_found"}, 404)
        try:
            with open(p, "rb") as fh:
                data = fh.read(profile_extract.AVATAR_CAP + 1)
        except OSError:
            return self._json({"error": "not_found"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", AVATAR_TYPES[p.rsplit(".", 1)[1]])
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def api_media(self, rest):
        """/api/media/<slug> -> {slug,status,images,updated_at}; /api/media/<slug>/<n>.jpg -> file."""
        noindex = {"X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer"}
        m = _MEDIA_PATH_RE.match(rest or "")
        if m and m.group(2) is not None:
            if not THUMB_LIMITER.allow(wc.client_ip(self), concurrency=False):
                return self._json({"error": "rate_limited"}, 429)
            p = media_gather.image_path(m.group(1), int(m.group(2)))
            try:
                with open(p, "rb") as fh:
                    data = fh.read(media_gather.MAX_BYTES + 1)
            except (OSError, TypeError):
                return self._json({"error": "not_found"}, 404)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if not RESULT_LIMITER.allow(wc.client_ip(self), concurrency=False):
            return self._json({"error": "rate_limited"}, 429, extra=noindex)
        if not m or _scan_extra_all(m.group(1)) is None:
            return self._json({"error": "not_found"}, 404, extra=noindex)
        return self._json(media_gather.public_view(m.group(1)), 200,
                          extra={**noindex, "Cache-Control": "no-cache"})

    def api_scan_links(self, slug):
        """Plain-text download of a completed deep scan's audit lists:
          /api/scan-links/<slug>?set=accepted  -> every confirmed (LIKELY) leak URL
          /api/scan-links/<slug>?set=removed   -> every crawl candidate we DROPPED
        One URL per line, so a human can eyeball the full triage — including the long
        'removed' tail (sometimes thousands) — and confirm nothing real was cut."""
        noindex = {"X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer"}
        if not RESULT_LIMITER.allow(wc.client_ip(self)):
            return self._json({"error": "rate_limited"}, 429, extra=noindex)
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        which = (qs.get("set") or ["accepted"])[0]
        if which not in ("accepted", "removed"):
            return self._json({"error": "bad_set"}, 400, extra=noindex)
        row = db.get_scan(slug)
        if not row:
            return self._json({"error": "not_found"}, 404, extra=noindex)
        urls = row.get("accepted_urls" if which == "accepted" else "removed_urls") or []
        handle = re.sub(r"[^A-Za-z0-9._-]", "", row.get("handle") or "scan") or "scan"
        header = ("# %s leaks for @%s — %d URL(s)\n"
                  "# %s\n\n") % (
            which, handle, len(urls),
            "confirmed as yours (DMCA-ready)" if which == "accepted"
            else "candidates we dropped — review to confirm none are real")
        text = header + "\n".join(urls) + ("\n" if urls else "")
        fname = "%s-%s-leaks.txt" % (handle, which)
        self._download(text, fname, extra=noindex)

    def _download(self, text, filename, code=200, extra=None):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", 'attachment; filename="%s"' % filename)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # --------------------------------------------------------------- live scan
    def api_public_scan(self):
        ip = wc.client_ip(self)
        body = self._read_json_capped(2048)
        if body is None:
            return  # 413 already sent
        if not SCAN_LIMITER.allow(ip):
            return self._json({"error": "rate_limited"}, 429)

        level = "deep" if body.get("level") == "deep" else "low"
        platform = (body.get("platform") or "onlyfans.com").strip().lower()
        if platform not in PLATFORMS:
            platform = "onlyfans.com"
        aliases = wc.clean_aliases(body.get("handle") or "", max_aliases=1)

        # Deep scans run detached in the background so a reload can't kill them.
        # We mint the slug NOW, spawn the worker, and return it as plain JSON;
        # the browser then polls /api/scan-result/<slug>. The worker owns
        # releasing both concurrency slots when it finishes.
        if level == "deep":
            if not GLOBAL_SCANS.acquire():
                SCAN_LIMITER.release(ip)
                return self._json({"error": "busy"}, 429)
            if not aliases:
                SCAN_LIMITER.release(ip)
                GLOBAL_SCANS.release()
                return self._json({"error": "bad_handle"}, 400)
            handle = aliases[0]
            plus = bool(body.get("plus"))
            # The worker owns releasing both slots in its finally — but only once it
            # actually runs. If minting the row or starting the thread fails first,
            # release here so a failed spawn can't permanently leak a scan slot.
            try:
                slug = db.create_pending(handle=handle, level="deep",
                                         platform=platform, client_ip_hash=_ip_hash(ip))
                _job_new(slug, handle, platform, "deep")
                threading.Thread(
                    target=_deep_worker,
                    args=(slug, handle, platform, body.get("aliases") or "", ip, plus),
                    daemon=True,
                ).start()
            except Exception:
                SCAN_LIMITER.release(ip)
                GLOBAL_SCANS.release()
                return self._json({"error": "unavailable"}, 503)
            return self._json({"slug": slug, "level": "deep", "status": "running",
                               "handle": handle, "platform": platform}, 200)

        # Low (CSE) scans are a couple of API calls -> keep the fast SSE path.
        # Declared socials widen the leak search (extra aliases) and feed the profile.
        socials = clean_socials(body)
        wc.sse_start(self)
        try:
            if not aliases:
                return wc.sse_fail(self, "Enter a valid handle (letters, digits, . _ - only).")
            self._scan_cse(aliases[0], platform, ip, aliases=quick_aliases(aliases, socials),
                           socials=socials, fresh=body.get("fresh") is True)  # one-project: scan reuse
        finally:
            SCAN_LIMITER.release(ip)

    def _scan_cse(self, handle, platform, ip, aliases=None, socials=None, fresh=False):  # one-project: scan reuse
        """Level 1: Google Custom Search — fast, no scraping, anyone. Runs a 6–8
        call exclude-reset widening (CSE_QUICK_CALLS) across a few phrasings so the
        quick scan surfaces many more distinct leak hosts than the old 2-pass, with
        a shallow depth fallback when too few sites turn up."""
        aliases, socials = aliases or [handle], socials or {}
        reuse_key, errors = scan_reuse_key(platform, handle, aliases, socials), []  # one-project: scan reuse
        if not fresh and scan_reuse_serve(self, reuse_key, handle, platform, ip, aliases, socials):  # one-project: scan reuse
            return  # one-project: scan reuse
        started = time.monotonic()  # one-project: scan_begin
        _event(f"scan start level=low platform={platform} aliases={len(aliases)}")
        if not cse_scanner.cse_available():
            return wc.sse_fail(self, "Quick search isn't configured right now. Try the deep scan.")
        prog = lambda m: wc.sse(self, "progress", m)
        try:
            # each alias's bare query first, then the prefixed seeds; +1 call per extra alias
            seeds = [(a, a) for a in aliases] + [(f"{p} {a}", a) for a in aliases for p in CSE_PREFIXES]
            results, raw_total = cse_scanner.cse_search_wide(
                [q for q, _ in seeds], max_calls=CSE_QUICK_CALLS + len(aliases) - 1, on_progress=prog,
                tags=[a for _, a in seeds], errors=errors)  # one-project: scan reuse
            rows = cse_scanner.summarize_cse(results)
            if len(rows) < MIN_SITES_FOR_FALLBACK and FALLBACK_EXTRA_PAGES > 0:
                try:
                    results = results + cse_scanner.cse_paginate(
                        handle, pages=FALLBACK_EXTRA_PAGES, on_progress=prog, errors=errors)  # one-project: scan reuse
                    rows = cse_scanner.summarize_cse(results)
                except Exception:
                    pass
        except Exception:
            return wc.sse_fail(self, "Quick search is temporarily unavailable. Please try again.")
        op, rows, results = scan_begin(handle, platform, aliases, socials, rows, results, prog, started, fresh, errors)  # one-project: scan_begin
        # images / status / shaped below: upstream's, dead here (scan_end's pub replaces them, pack hosts dropped)  # one-project: scan_end
        images = cse_scanner.good_images(results, handle, CSE_IMAGES)
        # Replace Google's inflated raw totalResults with a grounded estimate.
        if USE_TOTAL_RESULTS_QUERY:
            try:
                google_total = int(raw_total) if raw_total else 0
            except (TypeError, ValueError):
                google_total = 0
        else:
            google_total = _estimate(len(results), len(rows))  # one-project: estimate
            if GOOGLE_INDEX_MAX > 0:
                google_total = min(google_total, GOOGLE_INDEX_MAX)
        status = "empty" if not rows else "complete"
        shaped = shape_results(results)
        profile, avatar, sources = None, None, None
        if PROFILE_ENABLED:
            prog("Reading your public profile…")
            profile, avatar, sources = _quick_profile(handle, platform, results, socials, hints=op["hints"])  # one-project: hints
            profile = profile_extract.merge_found_accounts(profile, op["aliases"]["socials"], socials, platform)  # one-project: hints
        rows, results, status, pub, mega_key = scan_end(op, handle, rows, results, google_total)  # one-project: scan_end
        slug = db.insert_scan(rows, handle=handle, level="low", platform=platform,
                              status=status, client_ip_hash=_ip_hash(ip),
                              extra={"images": images, "google_total": google_total,
                                     "results": shaped, "profile": profile, "socials": socials, **pub, leakshaven.CACHE_FIELD: mega_key,  # one-project: scan_end
                                     SCAN_REUSE_FIELD: scan_reuse_value(reuse_key, status, errors, mega_key, profile)})  # one-project: scan reuse
        if avatar and not _save_avatar(slug, avatar) and profile:
            profile["avatar"] = False
        media = {"status": media_gather.start(slug, platform, handle, profile, results,
                                              sources=sources, socials=socials)}
        _event(f"scan done level=low hits={len(rows)} images={len(pub['images'])} calls={CSE_QUICK_CALLS} "  # one-project: scan_end
               f"aliases={len(aliases)}+{len(pub['aliases']['discovered'])} socials={len(socials)}+{len(pub['aliases']['socials'])} "  # one-project: aliases
               f"profile={(profile or {}).get('generated_by')} avatar={bool(avatar)} media={media['status']}")
        wc.sse(self, "result", json.dumps({
            "slug": slug, "handle": handle, "platform": platform, "level": "low",
            "status": status, "hit_count": len(rows), "domain_count": db.domain_count(rows),  # one-project: domain_count
            "google_total": google_total, "images": images, "hits": rows,
            "results": shaped, "profile": profile, "media": media, "socials": socials,
            "as_of": db._now(),  # one-project: scan reuse
            **pub,  # one-project: scan_end
        }, ensure_ascii=False))
        wc.sse(self, "done", "end")


def _sweep_webscan_scratch():
    """Remove any webscan_* pipeline scratch left at the repo root by a big scan
    whose process was killed before its finally-cleanup ran. Run once at startup;
    reuses the same guarded deletion as the per-scan cleanup."""
    swept = 0
    for p in glob.glob(os.path.join(HERE, "webscan_*")):
        base = os.path.basename(p)
        # strip the artifact suffix (webscan_<hash>.crawl.json / _images / -scan.json)
        m = re.match(r"^(webscan_[a-z0-9]+)", base)
        if m:
            _cleanup_webscan(m.group(1))
            swept += 1
    return swept


def main():
    db.init_db()
    try:
        n = _sweep_webscan_scratch()
        if n:
            _event(f"swept {n} orphaned webscan scratch artifact(s)")
    except Exception as e:
        _event(f"webscan sweep skipped: {type(e).__name__}")
    try:
        reaped = db.reap_running()
        if reaped:
            _event(f"reaped {reaped} orphaned running scans")
    except Exception as e:
        _event(f"reap skipped: {type(e).__name__}")
    try:
        threading.Thread(target=_retention_loop, daemon=True, name="retention").start()  # one-project: retention
    except Exception as e:
        _event(f"prune skipped: {type(e).__name__}")
    srv = ThreadingHTTPServer((PUBLIC_HOST, PORT), Handler)
    srv.daemon_threads = True
    _event(f"public app on http://{PUBLIC_HOST}:{PORT}  "
           f"(verified domains: {VERIFIED_DOMAINS}, kb: {os.path.isfile(KB_FILE)}, "
           f"var_max: {VAR_MAX}, cse_only: {BIG_SCAN_CSE_IMAGES_ONLY})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()

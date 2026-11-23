#!/usr/bin/env python3
"""
browser_common.py — shared browser acquisition for the search/image scrapers.

Routes all scraping through the Incogniton anti-detect profile by default (real
residential proxy + fingerprint => defeats the datacenter-IP/headless captcha
walls that block plain headless Chrome). Falls back to the installed Chrome only
if Incogniton is unreachable (or --no-incogniton). Also: a tiny .env loader and a
macOS captcha operator-alert (Incogniton runs a VISIBLE window, so /sorry/ walls
can be solved by hand — the alert pings you to go do it).
"""
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")


def load_dotenv(path=None):
    """Minimal KEY=VALUE .env loader (no dependency). Does not overwrite existing env."""
    path = path or os.path.join(_HERE, ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _resolve_ws_bounded(profile_id, timeout):
    """Resolve the Incogniton CDP ws in a SUBPROCESS with a hard timeout, so the
    tool can never hang on the connect module's internal 90s GUI-capture wait.
    Returns the ws string or None."""
    import subprocess
    pid = profile_id or ""
    # resolve_cdp_ws() print()s diagnostics to stdout; we capture stdout as the ws
    # URL, so divert the library's chatter to stderr and emit ONLY the ws on stdout.
    # (Without this, stdout = "[*] Using override…\n<ws>" → connect_over_cdp gets an
    # Invalid URL and silently falls back to local Chrome — which defeats Incogniton.)
    code = ("import sys, browser_common; browser_common.load_dotenv();"
            "from connect_incogniton import resolve_cdp_ws;"
            "pid=sys.argv[1] or None;"
            "_out=sys.stdout; sys.stdout=sys.stderr;"
            "ws=resolve_cdp_ws(pid);"
            "sys.stdout=_out; sys.stdout.write(ws or '')")
    try:
        r = subprocess.run([sys.executable, "-c", code, pid], cwd=_HERE,
                           capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "").strip() or None
    except Exception:
        return None


def acquire_browser(pw, *, headful=True, use_incogniton=True, profile_id=None, log=print):
    """Return (browser, context, mode). mode ∈ {'incogniton','chrome'}.
    With Incogniton we reuse the profile's OWN context (proxy+fingerprint).
    The Incogniton attempt is time-bounded (INCOGNITON_MAX_WAIT, default 100s) so a
    missing/failed profile never hangs the run — it falls back to local Chrome."""
    if use_incogniton:
        wait = int(os.environ.get("INCOGNITON_MAX_WAIT", "100") or 100)
        log(f"[browser] resolving Incogniton profile (up to {wait}s; Quick-Launch it if prompted)…")
        ws = _resolve_ws_bounded(profile_id, wait)
        if ws:
            try:
                browser = pw.chromium.connect_over_cdp(ws)
                ctx = browser.contexts[0] if browser.contexts else browser.new_context()
                try:
                    ctx.set_default_timeout(30000)
                except Exception:
                    pass
                log("[browser] routed through Incogniton profile (residential proxy + fingerprint)")
                return browser, ctx, "incogniton"
            except Exception as e:
                log(f"[browser] Incogniton CDP connect failed ({e}); falling back to local Chrome")
        else:
            log("[browser] Incogniton not reachable in time; falling back to local Chrome "
                "(run capture_incogniton_flags.py to enable it — see its output).")
        # INCOGNITON_ONLY (set by the public site's big scan): never fall back to a
        # local browser — a local Chrome would scrape google.com from the server IP.
        # Raise instead so the caller degrades to the synthetic screenshot strip.
        if os.environ.get("INCOGNITON_ONLY", "").lower() in ("1", "true", "yes"):
            raise RuntimeError("INCOGNITON_ONLY: Incogniton unreachable, refusing local-Chrome fallback")
    browser = pw.chromium.launch(channel="chrome", headless=not headful)
    ctx = browser.new_context(user_agent=DEFAULT_UA, locale="en-US",
                              viewport={"width": 1366, "height": 900})
    ctx.set_default_timeout(30000)
    return browser, ctx, "chrome"


# ── captcha operator alert (macOS) ──────────────────────────────────────────
_BLOCK_HINTS = ("/sorry/", "captcha", "unusual traffic", "are you a robot",
                "verify you are human", "whoa there", "blocked")


def looks_blocked(page):
    """Generic check: does this page look like a bot-wall right now?"""
    try:
        url = (page.url or "").lower()
        if "/sorry/" in url or "ipv4.google" in url:
            return True
        title = (page.title() or "").lower()
        if any(h in title for h in ("captcha", "blocked", "whoa there", "just a moment")):
            return True
        html = (page.content() or "").lower()[:20000]
        return ("g-recaptcha" in html or "captcha-card" in html or "recaptcha/api" in html
                or "please verify you're a human" in html)
    except Exception:
        return False


def alert_and_wait(page, *, log=print, max_wait=600, blocked_check=None):
    """If CAPTCHA_ALERT is on, audibly ping the operator (repeating every
    CAPTCHA_ALERT_INTERVAL seconds) and poll until the wall clears or times out.
    Returns True if the wall was solved (no longer blocked), False otherwise.

    blocked_check: optional callable() -> bool used as the authoritative
    "is this page still blocked?" predicate. Callers that already detected the
    wall with an accurate per-engine detector (detect_block / detect_status)
    MUST pass it — the generic looks_blocked() fallback misses Brave/Google
    consent+captcha walls, which made this silently no-op before."""
    if os.environ.get("CAPTCHA_ALERT", "1") not in ("1", "true", "True"):
        return False
    is_blocked = blocked_check if callable(blocked_check) else (lambda: looks_blocked(page))
    try:
        if not is_blocked():
            return False
    except Exception:
        return False
    say = os.environ.get("CAPTCHA_ALERT_SAY", "Captcha. Come solve it in the browser.")
    interval = float(os.environ.get("CAPTCHA_ALERT_INTERVAL", "20") or 20)
    is_mac = sys.platform == "darwin"
    log(f"[captcha] bot-wall detected at {page.url} — pinging operator to solve it…")
    waited, last_ping = 0.0, -1e9
    while waited < max_wait:
        try:
            still = is_blocked()
        except Exception:
            still = False
        if not still:
            log("[captcha] cleared — continuing.")
            return True
        if is_mac and (waited - last_ping) >= interval:
            try:
                subprocess.Popen(["afplay", "/System/Library/Sounds/Ping.aiff"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.Popen(["say", say], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            last_ping = waited
        time.sleep(2)
        waited += 2
    log("[captcha] operator did not solve in time — recording as blocked and moving on.")
    return False

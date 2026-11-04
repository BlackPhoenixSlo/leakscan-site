import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv(Path(__file__).resolve().parent / ".env")

INCOGNITON_API = "http://localhost:35000"
PROFILE_ID = os.environ.get(
    "INCOGNITON_PROFILE_ID",
    "16722083-6a11-4f70-9c15-ca54b688a237",
)

_CACHE_DIR = Path.home() / ".incogniton_cdp"

# CDP readiness polling — cold-start can be slow + port may shift mid-wait
CDP_WAIT_TIMEOUT = 120       # total seconds to wait for CDP to come up
CDP_POLL_INTERVAL = 2        # seconds between readiness probes
CDP_REBIND_EVERY = 6         # every N polls, re-query Incogniton for current port

# Launch retry (if Incogniton API returns transient error)
LAUNCH_MAX_ATTEMPTS = 3
LAUNCH_BACKOFF = 4           # seconds between launch retries

# --- Free-plan direct-launch fallback -------------------------------------
# The automation API on :35000 is paywalled. But Incogniton's own Chromium
# honours --remote-debugging-port, and the profile's full fingerprint is
# carried by a --encodeddata=<hex> flag that the app writes to its logs each
# time the profile is launched. So on the free plan we skip the API entirely:
# launch that binary ourselves with the scraped encodeddata + a debug port,
# then connect Playwright over CDP. No proxy is applied (free accounts run
# proxy-less anyway — see "launched without proxy by non-paid user" in logs).
INCOGNITON_SUPPORT = Path.home() / "Library/Application Support/Incogniton"
INCOGNITON_LOG_DIR = INCOGNITON_SUPPORT / "logs"
# Override the CDP port (default 9222) or the fingerprint payload via env.
CDP_PORT = int(os.environ.get("INCOGNITON_CDP_PORT", "9222"))
_ENC_RE = re.compile(r"--encodeddata=([0-9a-fA-F]+)")
DIRECT_LAUNCH_TIMEOUT = 30   # seconds to wait for our own browser's CDP


def _is_fingerprinted(argv: list[str]) -> bool:
    """True only if this launch command actually carries the profile fingerprint.

    A real Incogniton profile launch passes --encodeddata=<hex> (the blob that
    encodes both the spoofed fingerprint AND the profile's data-dir). A browser
    started with only --remote-debugging-port — e.g. OUR OWN previous relaunch,
    or a plain default browser — has no fingerprint and opens Incogniton's
    DEFAULT profile. Capturing/caching/replaying such a command is exactly how
    the cache gets poisoned into always opening the wrong ("old") profile, so we
    refuse to treat a fingerprint-less command as a valid launch spec anywhere."""
    return any(a.startswith("--encodeddata=") for a in (argv or []))


def _http_get_json(url: str, timeout: int = 30):
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        print(f"[!] Non-JSON response from {url}: {resp.text[:200]}")
        return None


def _extract_ws(data: dict) -> str | None:
    if not isinstance(data, dict):
        return None
    return (
        data.get("puppeteerUrl")
        or data.get("url")
        or data.get("webSocketDebuggerUrl")
        or data.get("wsEndpoint")
    )


def _get_active_ws(profile_id: str) -> str | None:
    """If profile already launched, return its existing WS endpoint. Don't re-launch."""
    for ep in (
        f"{INCOGNITON_API}/automation/active",
        f"{INCOGNITON_API}/profile/active",
        f"{INCOGNITON_API}/profile/status/{profile_id}",
    ):
        try:
            data = _http_get_json(ep, timeout=5)
        except requests.exceptions.RequestException:
            continue
        if not data:
            continue
        # Payload shape varies across Incogniton versions — handle list + dict.
        items = data if isinstance(data, list) else data.get("profiles") or data.get("data") or [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            pid = item.get("profileID") or item.get("id") or item.get("profile_id")
            if pid != profile_id:
                continue
            ws = _extract_ws(item)
            if ws:
                print(f"[*] Profile {profile_id} already active — reusing CDP: {ws}")
                return ws
    return None


def _launch(profile_id: str) -> str | None:
    launch_url = f"{INCOGNITON_API}/automation/launch/puppeteer/{profile_id}"
    for attempt in range(1, LAUNCH_MAX_ATTEMPTS + 1):
        print(f"[*] Launch attempt {attempt}/{LAUNCH_MAX_ATTEMPTS} → {launch_url}")
        try:
            data = _http_get_json(launch_url, timeout=60)
        except requests.exceptions.RequestException as e:
            print(f"[!] Launch request failed: {e}")
            if attempt < LAUNCH_MAX_ATTEMPTS:
                time.sleep(LAUNCH_BACKOFF)
            continue

        if not data:
            if attempt < LAUNCH_MAX_ATTEMPTS:
                time.sleep(LAUNCH_BACKOFF)
            continue

        err = data.get("error") or data.get("message")
        ws = _extract_ws(data)

        # Already running is not an error — try to discover existing endpoint
        if err and "already" in str(err).lower():
            print(f"[*] Incogniton says: {err} — checking active sessions")
            ws = _get_active_ws(profile_id) or ws
            if ws:
                return ws

        if ws:
            return ws

        if err:
            print(f"[!] Incogniton error: {err}")
        if attempt < LAUNCH_MAX_ATTEMPTS:
            time.sleep(LAUNCH_BACKOFF)
    return None


def _cache_file(profile_id: str) -> Path:
    return _CACHE_DIR / f"{profile_id}.json"


def _save_cached_ws(profile_id: str, ws: str) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_file(profile_id).write_text(json.dumps({"ws": ws, "ts": time.time()}))
    except Exception as e:
        print(f"[!] cache save failed: {e}")


def _load_cached_ws(profile_id: str) -> str | None:
    path = _cache_file(profile_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return data.get("ws") or None
    except Exception:
        return None


def _clear_cached_ws(profile_id: str) -> None:
    try:
        _cache_file(profile_id).unlink(missing_ok=True)
    except Exception:
        pass


def _fmt_host(host: str) -> str:
    """Bracket a bare IPv6 literal so it's valid inside an http URL.
    urlparse().hostname strips the brackets ('::1'), but requests/CDP URLs need
    them back ('[::1]'). Leaves hostnames / IPv4 untouched."""
    if host and ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def _probe_cdp(host: str, port: int) -> bool:
    """HTTP probe /json/version — real CDP readiness signal, not just TCP listen."""
    try:
        r = requests.get(f"http://{_fmt_host(host)}:{port}/json/version", timeout=2)
        return r.status_code == 200
    except requests.exceptions.RequestException:
        return False


def _wait_for_cdp(ws_endpoint: str, profile_id: str,
                  timeout: int = CDP_WAIT_TIMEOUT) -> str | None:
    """Probe CDP readiness. Every CDP_REBIND_EVERY polls, re-query Incogniton
    in case the port changed. Returns a working endpoint or None on timeout."""
    current = ws_endpoint
    deadline = time.time() + timeout
    poll = 0
    print(f"[*] Waiting up to {timeout}s for CDP at {current}...")
    while time.time() < deadline:
        parsed = urlparse(current)
        host = parsed.hostname or "localhost"
        port = parsed.port
        if port and _probe_cdp(host, port):
            print(f"[*] CDP live at {host}:{port}")
            return current
        poll += 1
        if poll % CDP_REBIND_EVERY == 0:
            latest = _get_active_ws(profile_id)
            if latest and latest != current:
                print(f"[*] Port shifted: {current} → {latest}")
                current = latest
        time.sleep(CDP_POLL_INTERVAL)
    print(f"[!] Timed out waiting for CDP at {current}")
    return None


def _api_listening() -> bool:
    """Quick TCP probe of the automation API port. On the free plan nothing
    listens here, so we skip the slow API launch retries and go direct."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            return s.connect_ex(("localhost", 35000)) == 0
        except OSError:
            return False


def _find_browser_binary() -> Path | None:
    """Newest IncognitonBrowser Chromium under the support dir's browser/<ver>/."""
    matches = sorted(
        INCOGNITON_SUPPORT.glob(
            "browser/*/mac/IncognitonBrowser.app/Contents/MacOS/IncognitonBrowser"
        ),
        reverse=True,
    )
    return matches[0] if matches else None


def _enc_cache(profile_id: str) -> Path:
    return _CACHE_DIR / f"{profile_id}.enc"


def _find_encodeddata(profile_id: str) -> str | None:
    """The fingerprint payload Incogniton hands its Chromium. Sources, in order:
    1. INCOGNITON_ENCODEDDATA env override.
    2. Our own cache from a previous run (survives log rotation).
    3. Scrape the newest --encodeddata=<hex> out of Incogniton's logs — written
       every time the profile is launched from the app GUI.
    The scraped value is cached for next time."""
    env = os.environ.get("INCOGNITON_ENCODEDDATA")
    if env:
        return env.strip()

    logs = sorted(
        INCOGNITON_LOG_DIR.glob("Incogniton-*.log*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for log in logs:
        try:
            text = log.read_text(errors="ignore")
        except OSError:
            continue
        # Only borrow an --encodeddata from a log that also references THIS
        # profile — otherwise we'd mislabel another profile's fingerprint as ours
        # (newer Incogniton no longer logs the blob, so this stays empty there and
        # we fall through to a live GUI capture instead of guessing).
        if profile_id not in text:
            continue
        found = _ENC_RE.findall(text)
        if found:
            enc = found[-1]  # last occurrence in newest log = most recent launch
            try:
                _CACHE_DIR.mkdir(parents=True, exist_ok=True)
                _enc_cache(profile_id).write_text(enc)
            except OSError:
                pass
            return enc

    cached = _enc_cache(profile_id)
    if cached.exists():
        return cached.read_text().strip() or None
    return None


def _argv_cache(profile_id: str) -> Path:
    return _CACHE_DIR / f"{profile_id}.argv.json"


def _iter_main_browsers():
    """Yield (binary, flags) for every live MAIN IncognitonBrowser process,
    skipping --type= renderer/gpu helper children."""
    try:
        out = subprocess.run(
            ["ps", "-axww", "-o", "command="],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return
    marker = "/MacOS/IncognitonBrowser"
    for cmd in out.splitlines():
        i = cmd.find(marker)
        if i == -1 or "--type=" in cmd:   # skip helper/renderer children
            continue
        binary = cmd[: i + len(marker)]
        rest = cmd[i + len(marker):].strip()
        # Split before each "--flag" so values that contain spaces (e.g. the
        # --user-agent string or a --user-data-dir under "Application Support")
        # survive intact.
        flags = [f for f in re.split(r"\s+(?=--)", rest) if f] if rest else []
        yield binary, flags


def _argv_profile_id(argv: list[str]) -> str | None:
    """The profile id a command targets, read from --user-data-dir (whose last
    path segment IS the profile id in current Incogniton versions)."""
    for a in argv:
        if a.startswith("--user-data-dir="):
            return a.split("=", 1)[1].rstrip("/").rsplit("/", 1)[-1]
    return None


def _argv_is_profile(argv: list[str], profile_id: str) -> bool:
    """Does this command launch the requested profile? Proven by --user-data-dir.
    Legacy launches that carried only --encodeddata (no data-dir) can't be
    disambiguated, so we trust their fingerprint."""
    pid = _argv_profile_id(argv)
    return pid == profile_id if pid is not None else True


def _running_profile_argv(profile_id: str) -> list[str] | None:
    """Full argv of the live, GUI-launched MAIN browser for THIS profile — the
    most update-proof fingerprint source (copies whatever flags this app version
    passes: encoding, proxy, lang, user-agent…). It must carry a fingerprint
    (--encodeddata) AND match the profile (--user-data-dir), so it ignores our
    OWN bare --remote-debugging-port relaunch and any OTHER profile that happens
    to be open — that's what kept poisoning the cache into opening the default
    ("old") profile."""
    for binary, flags in _iter_main_browsers():
        argv = [binary, *flags]
        if _is_fingerprinted(argv) and _argv_is_profile(argv, profile_id):
            return argv
    return None


def _cdp_port_profile(port: int) -> str | None:
    """Profile id of the live browser bound to --remote-debugging-port=<port>,
    or None if nothing matches / it carries no --user-data-dir. Lets us refuse to
    reuse a stale default/bare browser that merely happens to hold the port."""
    flag = f"--remote-debugging-port={port}"
    for binary, flags in _iter_main_browsers():
        if flag in flags:
            return _argv_profile_id([binary, *flags])
    return None


def _save_argv(profile_id: str, argv: list[str]) -> None:
    if not _is_fingerprinted(argv):
        return  # never cache a fingerprint-less command — that poisons the cache
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _argv_cache(profile_id).write_text(json.dumps(argv))
    except OSError:
        pass


def _load_argv(profile_id: str) -> list[str] | None:
    path = _argv_cache(profile_id)
    if not path.exists():
        return None
    try:
        argv = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    # Reject a fingerprint-less cache entry (e.g. an old bare-binary capture):
    # replaying it opens the default profile, not this one.
    if isinstance(argv, list) and argv and _is_fingerprinted(argv):
        return argv
    return None


def _ensure_debug_port(argv: list[str], port: int) -> list[str]:
    """Replay a captured launch command but force our remote-debugging port on."""
    cleaned = [a for a in argv if not a.startswith("--remote-debugging-port")]
    return [*cleaned, f"--remote-debugging-port={port}"]


def _kill_running_browser() -> None:
    """Quit any live IncognitonBrowser so the profile's data-dir lock releases
    before we relaunch it with a debug port."""
    subprocess.run(["pkill", "-f", "MacOS/IncognitonBrowser"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)


def _launch_spec(profile_id: str) -> tuple[list[str] | None, str]:
    """Best available command to launch the fingerprinted browser, most
    update-proof first:
      1. a live GUI-launched process (copies this version's exact flags),
      2. the argv we cached from a previous capture,
      3. reconstruct [binary, --encodeddata] from the logs/cache (older path)."""
    argv = _running_profile_argv(profile_id)
    if argv:
        _save_argv(profile_id, argv)
        return argv, "live GUI process"
    argv = _load_argv(profile_id)
    if argv:
        return argv, "cached launch args"
    binary = _find_browser_binary()
    enc = _find_encodeddata(profile_id)
    if binary and enc:
        return [str(binary), f"--encodeddata={enc}"], "scraped --encodeddata"
    return None, ""


def _prompt_capture(profile_id: str, wait: int = 90) -> tuple[list[str] | None, str]:
    """Self-heal when nothing is cached (e.g. right after an Incogniton update):
    ask the user to Quick-Launch the profile once, then snapshot its argv."""
    print("\n[!] No fingerprint payload found — Incogniton may have just updated.")
    print("    → In the Incogniton app, click 'Quick Launch' on this profile now.")
    print(f"    Waiting up to {wait}s to capture its launch command...")
    deadline = time.time() + wait
    while time.time() < deadline:
        argv = _running_profile_argv(profile_id)
        if argv:
            _save_argv(profile_id, argv)
            print("[*] Captured launch command from the GUI session.")
            return argv, "captured GUI session"
        time.sleep(2)
    print("[!] Timed out — no GUI launch detected.")
    return None, ""


def _direct_launch(profile_id: str, port: int = CDP_PORT) -> str | None:
    """Free-plan path: drive Incogniton's own fingerprinted Chromium over CDP
    without the paywalled API. We replay the app's real launch command (captured
    live, so it survives version/flag changes) with a debug port forced on."""
    if _probe_cdp("localhost", port):
        bound = _cdp_port_profile(port)
        if bound == profile_id:
            print(f"[*] CDP already live on :{port} for {profile_id} — reusing")
            return f"http://localhost:{port}"
        print(f"[*] CDP on :{port} serves {bound or 'the default profile'}, "
              f"not {profile_id} — relaunching the right profile")

    argv, source = _launch_spec(profile_id)
    if not argv:
        argv, source = _prompt_capture(profile_id)
    if not argv:
        return None

    argv = _ensure_debug_port(argv, port)
    # If the spec came from a running instance it holds the data-dir lock with
    # no debug port — kill it so our relaunch (with the port) can take over.
    _kill_running_browser()

    print(f"[*] Free-plan direct launch ({source}) on CDP port {port}")
    subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + DIRECT_LAUNCH_TIMEOUT
    while time.time() < deadline:
        if _probe_cdp("localhost", port):
            print(f"[*] CDP live at localhost:{port}")
            return f"http://localhost:{port}"
        time.sleep(1)
    print(f"[!] Browser launched but CDP never came up on :{port}")
    return None


def resolve_cdp_ws(profile_id: str | None = None) -> str | None:
    """Resolve a live CDP WebSocket endpoint for an Incogniton profile
    (cached → automation API → free-plan direct launch → wait for port).
    Returns None on failure. Reusable by other tools (web_search/collect_images);
    unlike connect_to_incogniton() it never sys.exit()s."""
    profile_id = profile_id or PROFILE_ID
    # Explicit endpoint override — pins the exact CDP listener to use. Needed when
    # a stray browser squats on 127.0.0.1:<port> and Incogniton is on [::1]:<port>
    # (localhost would resolve IPv4-first → wrong browser). Verified live first.
    forced = (os.environ.get("INCOGNITON_CDP_WS") or "").strip()
    if forced:
        parsed = urlparse(forced)
        if parsed.hostname and parsed.port and _probe_cdp(parsed.hostname, parsed.port):
            print(f"[*] Using INCOGNITON_CDP_WS override: {forced}")
            return forced
        print(f"[!] INCOGNITON_CDP_WS={forced} not reachable — ignoring override")
    ws_endpoint = None
    cached = _load_cached_ws(profile_id)
    if cached:
        parsed = urlparse(cached)
        alive = bool(parsed.hostname and parsed.port and _probe_cdp(parsed.hostname, parsed.port))
        if alive and _cdp_port_profile(parsed.port) == profile_id:
            ws_endpoint = cached
        else:
            _clear_cached_ws(profile_id)
    if not ws_endpoint and _api_listening():
        ws_endpoint = _get_active_ws(profile_id) or _launch(profile_id)
    if not ws_endpoint:
        ws_endpoint = _direct_launch(profile_id)
    if not ws_endpoint:
        return None
    ws_endpoint = _wait_for_cdp(ws_endpoint, profile_id)
    if not ws_endpoint:
        return None
    _save_cached_ws(profile_id, ws_endpoint)
    return ws_endpoint


def open_incogniton(pw, profile_id: str | None = None):
    """Given a sync_playwright instance `pw`, connect over CDP to the Incogniton
    profile and return (browser, context) using the profile's OWN context so the
    residential proxy + anti-detect fingerprint are used. Raises RuntimeError if
    Incogniton isn't reachable."""
    ws = resolve_cdp_ws(profile_id)
    if not ws:
        raise RuntimeError("Incogniton CDP endpoint unavailable — is the Incogniton app "
                           "running and INCOGNITON_PROFILE_ID set in .env?")
    browser = pw.chromium.connect_over_cdp(ws)
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    return browser, context


def connect_to_incogniton():
    """Connect Playwright to Incogniton. If the profile is already running, reuse
    its CDP endpoint instead of re-launching. Waits for the (possibly-shifting)
    CDP port to open before connecting."""
    profile_id = PROFILE_ID

    # 1. Try cached endpoint from previous run — probe /json/version to verify alive
    ws_endpoint = None
    cached = _load_cached_ws(profile_id)
    if cached:
        parsed = urlparse(cached)
        alive = bool(parsed.hostname and parsed.port
                     and _probe_cdp(parsed.hostname, parsed.port))
        # Alive isn't enough: a stale default/bare browser can squat on the port.
        # Only reuse if the browser bound to it is actually THIS profile.
        if alive and _cdp_port_profile(parsed.port) == profile_id:
            print(f"[*] Reusing cached live CDP for {profile_id}: {cached}")
            ws_endpoint = cached
        else:
            reason = "dead" if not alive else "serves a different profile"
            print(f"[*] Cached endpoint {cached} {reason} — clearing")
            _clear_cached_ws(profile_id)

    # 2/3. Automation API path — only if it's actually listening (paid plans).
    # On the free plan port 35000 is dead, so we skip straight to direct launch
    # rather than burning ~12s on connection-refused retries.
    if not ws_endpoint and _api_listening():
        ws_endpoint = _get_active_ws(profile_id) or _launch(profile_id)

    # 4. Free-plan fallback: launch Incogniton's own Chromium ourselves over CDP.
    if not ws_endpoint:
        if not _api_listening():
            print("[*] Automation API (:35000) unavailable — using free-plan direct launch")
        ws_endpoint = _direct_launch(profile_id)

    if not ws_endpoint:
        print("[!] Could not obtain CDP WebSocket endpoint.")
        sys.exit(1)

    print(f"[*] CDP endpoint: {ws_endpoint}")

    # 4. Wait for CDP to come up; recover if Incogniton shifts port mid-wait
    ws_endpoint = _wait_for_cdp(ws_endpoint, profile_id)
    if not ws_endpoint:
        sys.exit(1)
    _save_cached_ws(profile_id, ws_endpoint)

    # 4. Connect Playwright over CDP
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(ws_endpoint)
            print("[*] Playwright connected over CDP")

            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()

            target_url = "https://bot.sannysoft.com/"
            print(f"[*] Navigating to {target_url}")
            page.goto(target_url, wait_until="networkidle")

            screenshot_path = "incogniton_fingerprint_test.png"
            page.screenshot(path=screenshot_path, full_page=True)
            print(f"[*] Screenshot saved: {screenshot_path}")

            page.close()
            # sync API: use close() — disconnects CDP client, Incogniton browser stays open
            browser.close()
            print("[*] Playwright disconnected. Incogniton browser left open.")
        except Exception as e:
            print(f"[!] CDP session error: {e}")
            sys.exit(1)


if __name__ == "__main__":
    connect_to_incogniton()

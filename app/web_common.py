"""
Shared stdlib helpers for the PUBLIC leak-scan app (public_app.py).

These mirror the exact SSE / static-serve / validation idioms already proven in
server.py, so both apps behave identically. They take a `handler`
(BaseHTTPRequestHandler) argument instead of being methods, so any handler can
reuse them without a class hierarchy. Stdlib only — no third-party deps.
"""

import os
import re
import shutil
import signal
import subprocess
import threading
import urllib.parse

# --------------------------------------------------------------------------- env
def load_env(path=".env"):
    """Minimal .env loader (dotenv-lite): KEY=value lines, `#` comments, optional
    surrounding quotes. Uses setdefault so real environment vars always win.
    Missing file is a no-op."""
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k:
                    os.environ.setdefault(k, v)
    except FileNotFoundError:
        pass


# ------------------------------------------------------------- alias validation
# Mirror of server.py:45,47,138-149 — length-capped, char-allowlisted.
ALIAS_RE = re.compile(r"^[A-Za-z0-9._\-]{1,60}$")
MAX_ALIASES = 25


def clean_aliases(raw, max_aliases=MAX_ALIASES):
    """Split on whitespace/commas, keep only ALIAS_RE-valid tokens, dedupe
    case-insensitively, cap the count. Returns a list (possibly empty)."""
    out = []
    for a in re.split(r"[\s,]+", (raw or "").strip()):
        a = a.strip()
        if a and ALIAS_RE.match(a):
            out.append(a)
    seen, res = set(), []
    for a in out:
        if a.lower() not in seen:
            seen.add(a.lower())
            res.append(a)
    return res[:max_aliases]


# ------------------------------------------------------------------------ SSE
# Mirror of server.py:315-333, 502-504.
def sse_start(h):
    h.send_response(200)
    h.send_header("Content-Type", "text/event-stream; charset=utf-8")
    h.send_header("Cache-Control", "no-cache")
    h.send_header("Connection", "close")
    h.send_header("X-Accel-Buffering", "no")  # defense vs nginx re-buffering SSE
    h.end_headers()
    h.close_connection = True


def sse(h, event, data):
    """Emit one SSE event. Returns False if the client has disconnected."""
    msg = f"event: {event}\n"
    for line in str(data).split("\n"):
        msg += f"data: {line}\n"
    msg += "\n"
    try:
        h.wfile.write(msg.encode("utf-8"))
        h.wfile.flush()
        return True
    except (BrokenPipeError, ConnectionResetError, ValueError):
        return False


def sse_fail(h, msg):
    sse(h, "failed", msg)
    sse(h, "done", "end")


# --------------------------------------------------------- subprocess streamer
def stream_subprocess(h, argv, timeout, cwd=None, on_progress=None):
    """Run `argv`, forwarding each stderr line to the browser as an SSE
    'progress' event (mirrors server.py:507-536). A watchdog Timer kills the
    process after `timeout`s; if the client disconnects mid-stream the process
    is killed too.

    Returns the process return code on normal completion, or None if it could
    not start or was killed by a client disconnect. The caller reads the tool's
    output file afterwards (the scanners write results to <out>.json, not stdout).
    """
    try:
        proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE)
    except Exception as e:
        sse_fail(h, f"could not start scan: {e}")
        return None

    killer = threading.Timer(timeout, proc.kill)
    killer.daemon = True
    killer.start()
    disconnected = False
    buf = b""
    try:
        while True:
            chunk = proc.stderr.read1(1024)
            if not chunk:
                break
            buf += chunk
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            for ln in parts:
                s = ln.decode("utf-8", "replace").rstrip()
                if not s.strip():
                    continue
                if on_progress:
                    on_progress(s)
                if not sse(h, "progress", s):
                    proc.kill()
                    disconnected = True
                    return None
        if buf.strip():
            s = buf.decode("utf-8", "replace").rstrip()
            if on_progress:
                on_progress(s)
            sse(h, "progress", s)
    finally:
        killer.cancel()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    return None if disconnected else proc.returncode


def run_subprocess(argv, timeout, cwd=None, on_line=None, env=None):
    """Headless variant of stream_subprocess for background jobs: run `argv` and
    invoke on_line(str) for each stderr line. No HTTP handler and no client-
    disconnect kill — the job outlives any single connection (this is what lets a
    scan survive a page reload). A watchdog Timer still kills it after `timeout`s.
    `env`, when given, replaces the child environment (pass a full dict, e.g.
    {**os.environ, "INCOGNITON_CDP_WS": ws}). The child runs in its OWN process
    group (start_new_session) so a watchdog timeout kills the WHOLE tree — e.g. a
    pipeline orchestrator plus its crawler workers / chromium grandchildren —
    instead of orphaning them. Returns the process return code, or None on start
    failure."""
    try:
        proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, env=env, start_new_session=True)
    except Exception:
        return None

    def _kill_tree():
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    killer = threading.Timer(timeout, _kill_tree)
    killer.daemon = True
    killer.start()
    buf = b""
    try:
        while True:
            chunk = proc.stderr.read1(1024)
            if not chunk:
                break
            buf += chunk
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            for ln in parts:
                s = ln.decode("utf-8", "replace").rstrip()
                if s.strip() and on_line:
                    on_line(s)
        if buf.strip() and on_line:
            on_line(buf.decode("utf-8", "replace").rstrip())
    finally:
        killer.cancel()
        try:
            proc.wait(timeout=5)
        except Exception:
            _kill_tree()
    return proc.returncode


# ---------------------------------------------------------------- static serve
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}


def serve_static(h, root, rel, extra_headers=None):
    """Serve a file from `root` only. Path-traversal safe via realpath prefix
    check (mirror of server.py:222-243, scoped to `root`). Returns True on a
    200, False on 404 / client-disconnect."""
    root = os.path.realpath(root)
    rel = urllib.parse.unquote(rel).lstrip("/")
    full = os.path.realpath(os.path.join(root, rel))
    if not (full == root or full.startswith(root + os.sep)) or not os.path.isfile(full):
        send_simple(h, 404, "Not found")
        return False
    ext = os.path.splitext(full)[1].lower()
    ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
    try:
        h.send_response(200)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(os.path.getsize(full)))
        h.send_header("Cache-Control", "no-cache")
        for k, v in (extra_headers or {}).items():
            h.send_header(k, v)
        h.end_headers()
        with open(full, "rb") as fh:
            shutil.copyfileobj(fh, h.wfile, length=65536)
        return True
    except (BrokenPipeError, ConnectionResetError):
        return False


def send_simple(h, code, msg):
    body = msg.encode("utf-8")
    try:
        h.send_response(code)
        h.send_header("Content-Type", "text/plain; charset=utf-8")
        h.send_header("Content-Length", str(len(body)))
        h.end_headers()
        h.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        pass


# ------------------------------------------------------------------ client IP
def client_ip(h):
    """Real client IP. Prefer the proxy-set X-Real-IP (Caddy). Behind Traefik,
    which uses X-Forwarded-For instead, set TRUST_XFF=1: the LAST X-Forwarded-For
    hop is the one Traefik appended (the real peer) and is NOT client-spoofable —
    a client-supplied XFF only becomes earlier entries. Safe ONLY because the
    container has no published port, so every connection arrives via Traefik.
    Falls back to the socket peer for local dev."""
    xr = h.headers.get("X-Real-IP")
    if xr:
        return xr.strip()
    if os.environ.get("TRUST_XFF", "").lower() in ("1", "true", "yes"):
        xff = h.headers.get("X-Forwarded-For")
        if xff:
            hops = [p.strip() for p in xff.split(",") if p.strip()]
            if hops:
                return hops[-1]
    try:
        return h.client_address[0]
    except Exception:
        return "0.0.0.0"

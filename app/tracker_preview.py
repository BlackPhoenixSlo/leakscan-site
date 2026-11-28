"""Media Leak previews (ticket 70, cadence-previews "Service slice B"): a `media` Leak keeps the https thumbnail URL
Google's results page served for its tile (leaks.thumb_url / thumb_query_id / thumb_seen_at), only on THUMB_HOSTS, and
the thumb route fetches it at request time. This module is the only place the service requests a thumbnail URL; the
URL, its query id and its rank never leave the service, and logs hold counts only.

A query id is `<vertical>|<field key>` of the full-pass query that returned the tile (query_id()); a thumb whose query
leaves the plan, or whose Leak's Google visibility turns false, is cleared (tracker_lanes._visibility)."""
import concurrent.futures
import os
import re
import socket
import threading
import time
from urllib.parse import urlsplit

import tracker_db
import tracker_probe

THUMB_HOSTS = ("gstatic.com", "googleusercontent.com", "ggpht.com")
VERTICALS = ("images", "videos")
MAX_BYTES = 3 * 1024 * 1024
TOTAL_S = 5.0
PORT = 443
URL_MAX = 2048
_HOST = re.compile(r"^[a-z0-9.-]+$")
_MAGIC = ((b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "image/png"), (b"GIF87a", "image/gif"),
          (b"GIF89a", "image/gif"))
_LOCK = threading.Lock()
_counts = {}
_DNS = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="thumb-dns")


def on():
    """TRACKER_PREVIEWS: on unless 0 / off / false / no (owner 2026-11-28: on by default)."""
    return os.environ.get("TRACKER_PREVIEWS", "1").strip().lower() not in ("0", "off", "false", "no")


def query_id(vertical, field_key):
    return f"{vertical}|{field_key}"


def allowed(url):
    """https, a subdomain of a THUMB_HOSTS entry on a DNS-label boundary, no userinfo, no port, printable ASCII."""
    if not isinstance(url, str) or len(url) > URL_MAX or not url.isascii() or not url.isprintable() or " " in url:
        return False
    try:
        p = urlsplit(url)
    except ValueError:
        return False
    host = p.hostname or ""
    return (p.scheme == "https" and p.netloc.lower() == host and bool(_HOST.match(host))
            and any(host.endswith("." + h) for h in THUMB_HOSTS))


def store_thumb(c, leak_id, url, query_id, seen_at):
    """The capture's write: an allowed url for a media Leak, a query_id() of an images / videos query and an ISO
    seen_at overwrite its thumb; anything else stores nothing. -> True when stored."""
    if (not allowed(url) or not isinstance(query_id, str) or query_id.partition("|")[0] not in VERTICALS
            or tracker_db.parse(seen_at) is None):
        return False
    return c.execute("UPDATE leaks SET thumb_url = ?, thumb_query_id = ?, thumb_seen_at = ? WHERE leak_id = ? AND kind = 'media'",
                     (url, query_id, seen_at, leak_id)).rowcount > 0


def clear_thumb(c, leak_id):
    c.execute("UPDATE leaks SET thumb_url = NULL, thumb_query_id = NULL, thumb_seen_at = NULL "
              "WHERE leak_id = ? AND thumb_url IS NOT NULL", (leak_id,))


def prune(c, watch_id, query_ids):
    """Clear every thumb of watch_id whose query id is not in query_ids (the current plan's) -> rows cleared."""
    ids = sorted(query_ids)
    return c.execute(f"UPDATE leaks SET thumb_url = NULL, thumb_query_id = NULL, thumb_seen_at = NULL WHERE watch_id = ? "
                     f"AND thumb_url IS NOT NULL AND thumb_query_id NOT IN ({','.join('?' * len(ids))})",
                     (watch_id, *ids)).rowcount


def preview(row, visible):
    """The read's `preview` for a leaks row and its Google visibility: {vertical, seen_at} | None."""
    if row["kind"] != "media" or not row["thumb_url"] or not row["thumb_query_id"] or visible is not True or not on():
        return None
    return {"vertical": row["thumb_query_id"].partition("|")[0], "seen_at": row["thumb_seen_at"]}


def sniff(data):
    for magic, ctype in _MAGIC:
        if data.startswith(magic):
            return ctype
    return "image/webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else None


def _resolve(host, port):
    return [ai[4][0] for ai in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


def _connect(ip, host, timeout):
    """tracker_probe's pinned HTTPS connection: TLS verified against host (SNI + certificate), TCP to ip."""
    return tracker_probe._HTTPS(ip, host, PORT, timeout)


def _count(outcome):
    with _LOCK:
        _counts[outcome] = _counts.get(outcome, 0) + 1
        n = _counts[outcome]
    tracker_probe.log(f"tracker thumb {outcome}={n}")


def _fetch(url):
    if not allowed(url):
        return "host"
    p, deadline = urlsplit(url), time.monotonic() + TOTAL_S
    try:
        ips = _DNS.submit(_resolve, p.hostname, PORT).result(timeout=TOTAL_S)
    except (OSError, concurrent.futures.TimeoutError):
        return "dns"
    if not ips or not all(tracker_probe.ip_ok(ip) for ip in ips):
        return "address"
    left = deadline - time.monotonic()
    if left <= 0:
        return "slow"
    conn = _connect(ips[0], p.hostname, left)
    timer = threading.Timer(left, conn.kill)
    timer.daemon = True
    timer.start()
    try:
        conn.request("GET", (p.path or "/") + (f"?{p.query}" if p.query else ""), headers={
            "User-Agent": tracker_probe.UA, "Accept": "image/avif,image/webp,image/*;q=0.8", "Accept-Encoding": "identity"})
        r = conn.getresponse()
        if r.status != 200:
            return "status"
        if int(r.getheader("Content-Length") or 0) > MAX_BYTES:
            return "size"
        body = b""
        while len(body) <= MAX_BYTES:
            chunk = r.read(min(65536, MAX_BYTES + 1 - len(body)))
            if not chunk:
                break
            body += chunk
            if time.monotonic() > deadline:
                return "slow"
        if conn.killed:
            return "slow"
        if len(body) > MAX_BYTES:
            return "size"
        ctype = sniff(body)
        return (ctype, body) if ctype else "type"
    except OSError:
        return "slow" if conn.killed else "error"
    finally:
        timer.cancel()
        conn.close()


def fetch(url):
    """GET a stored thumb under the fetch-time checks (module docstring, ticket 70) -> (content type, bytes) or None.
    Never raises; each outcome is logged as a running count."""
    try:
        res = _fetch(url)
    except Exception:
        res = "error"
    if isinstance(res, tuple):
        _count("served")
        return res
    _count(f"refused_{res}")
    return None

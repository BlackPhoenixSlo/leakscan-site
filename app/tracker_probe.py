"""Origin probe + Probe state (spec "Daily pass (service)"). Only kind `page` is probed. A url_key is fetched at most
once per UTC day across tenants, passes and restarts: a key some Leak already probed today hands that result to its
other Leaks instead. The fetcher is a seam: fetch(url) -> (status, body text), status 0 = no answer (-> unknown);
set_fetcher() in tests, TRACKER_FETCHER=stub (app/tests/tracker_stub_fetch.py) for the Seam 6 tracer.

Probe state rule (one row per Leak, overwritten; a status event only when origin_status changes):
  dead     consecutive_dead += 1; 0 -> 1 is a first-dead (first_dead += 1, dead_since = now); 2 in a row -> gone.
  live     a live right after a single dead (consecutive_dead == 1) is a flap; clears the streak and dead_since.
  blocked / unknown   change nothing but probes / last_status / last_probe_at (neither break nor extend a streak).
So a flap is a first-dead whose next settled (live | dead) probe is live, and the flap-rate denominator is
first_dead minus the Leaks still at consecutive_dead == 1 (their next settled probe hasn't come)."""
import concurrent.futures as _cf
import functools
import http.client
import ipaddress
import os
import socket
import ssl
import sys
import threading
import time
from urllib.parse import urljoin, urlsplit

import tracker_db as tdb
import tracker_rules as rules

TOTAL_S = 15.0
MAX_REDIRECTS = 5
MAX_BODY = 256 * 1024
PER_HOST = 8
WORKERS = 16
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")
_REDIRECTS = (301, 302, 303, 307, 308)
_LOCK = threading.Lock()
_inflight = set()
_override = None
_NOT_GLOBAL6 = tuple(ipaddress.ip_network(n) for n in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32"))


def log(msg):
    """Same shape as public_app._event: no handles, URLs or keys."""
    sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    sys.stderr.flush()


@functools.lru_cache(maxsize=1)
def _host_ips():
    try:
        return frozenset(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        return frozenset()


def _self_ips():
    return {s.strip() for s in os.environ.get("TRACKER_SELF_IPS", "").split(",") if s.strip()} | _host_ips()


def ip_ok(ip):
    """A public unicast address that isn't one of the service's own (TRACKER_SELF_IPS + this host's names). NAT64,
    6to4 and Teredo addresses are refused: they embed an IPv4 address the check would not see."""
    try:
        a = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    a = getattr(a, "ipv4_mapped", None) or a
    if a.version == 6 and any(a in n for n in _NOT_GLOBAL6):
        return False
    return a.is_global and not a.is_multicast and str(a) not in _self_ips()


def _resolve(host, port):
    return [ai[4][0] for ai in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


class _Killable:
    """kill() (the hop's deadline timer) shuts the socket down, so a server dripping bytes can't outlast the deadline.
    Its own reference: http.client drops conn.sock once the response owns the socket."""
    killed, _s = False, None

    def _hold(self, s):
        self._s = s
        if self.killed:
            raise OSError("deadline")
        return s

    def kill(self):
        self.killed = True
        try:
            if self._s:
                self._s.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


class _HTTP(_Killable, http.client.HTTPConnection):
    def __init__(self, ip, host, port, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = self._hold(socket.create_connection((self._ip, self.port), self.timeout))


class _HTTPS(_Killable, http.client.HTTPSConnection):
    def __init__(self, ip, host, port, timeout):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self):
        sock = self._hold(socket.create_connection((self._ip, self.port), self.timeout))
        self.sock = self._hold(self._context.wrap_socket(sock, server_hostname=self.host, do_handshake_on_connect=False))
        self.sock.do_handshake()


class Fetcher:
    """GET over http / https only, <= MAX_REDIRECTS redirects followed by hand, <= MAX_BODY bytes read, TOTAL_S in
    all. Every hop's host is resolved and each address checked (ip_ok) before connecting to the checked address;
    a refused hop, a bad scheme, too many redirects or any error -> (0, ""). Never raises."""

    def __init__(self, resolve=_resolve, allow=ip_ok, total=TOTAL_S, max_redirects=MAX_REDIRECTS, max_body=MAX_BODY):
        self.resolve, self.allow, self.total = resolve, allow, total
        self.max_redirects, self.max_body = max_redirects, max_body

    def __call__(self, url):
        deadline = time.monotonic() + self.total
        try:
            for _ in range(self.max_redirects + 1):
                p = urlsplit(url)
                if p.scheme not in ("http", "https") or not p.hostname:
                    return 0, ""
                port = p.port or (443 if p.scheme == "https" else 80)
                ips = self.resolve(p.hostname, port)
                if not ips or not all(self.allow(ip) for ip in ips):
                    return 0, ""
                left = deadline - time.monotonic()
                if left <= 0:
                    return 0, ""
                conn = (_HTTPS if p.scheme == "https" else _HTTP)(ips[0], p.hostname, port, left)
                timer = threading.Timer(left, conn.kill)
                timer.daemon = True
                timer.start()
                try:
                    conn.request("GET", (p.path or "/") + (f"?{p.query}" if p.query else ""), headers={
                        "User-Agent": UA, "Accept": "text/html,*/*;q=0.8", "Accept-Encoding": "identity"})
                    r = conn.getresponse()
                    if r.status in _REDIRECTS and r.getheader("Location"):
                        url = urljoin(url, r.getheader("Location"))
                        continue
                    body = b""
                    while len(body) < self.max_body:
                        if time.monotonic() > deadline:
                            return 0, ""
                        chunk = r.read(min(65536, self.max_body - len(body)))
                        if not chunk:
                            break
                        body += chunk
                    if conn.killed:
                        return 0, ""
                    return r.status, body.decode(r.headers.get_content_charset() or "utf-8", "replace")
                finally:
                    timer.cancel()
                    conn.close()
            return 0, ""
        except Exception:
            return 0, ""


def set_fetcher(fn):
    """fn(url) -> (status, body), or None for the default (TRACKER_FETCHER=stub | Fetcher())."""
    global _override
    _override = fn


def fetcher():
    if _override:
        return _override
    if os.environ.get("TRACKER_FETCHER") == "stub":
        tests = os.path.join(tdb.HERE, "tests")
        if tests not in sys.path:
            sys.path.insert(0, tests)
        import tracker_stub_fetch
        return tracker_stub_fetch.FETCH
    return Fetcher()


def classify(fetch, url):
    if rules.is_media_url(url):
        return "unknown"
    try:
        status, body = fetch(url.partition("#")[0])
    except Exception:
        return "unknown"
    return rules.status_to_availability(status, body)


def step(st, status, at):
    """Pure: probe_state dict + one probe -> (new state, status event data or None). Rule: module docstring."""
    st, ev, old = dict(st), None, st.get("origin_status")
    st.update(probes=st["probes"] + 1, last_probe_at=at, last_status=status)
    if status == "live":
        if st["consecutive_dead"] == 1:
            st["flaps"] += 1
        st.update(consecutive_dead=0, dead_since=None, last_live_at=at)
        if old != "live":
            st["origin_status"], ev = "live", {"from": old, "to": "live", "dead_since": None}
    elif status == "dead":
        st["consecutive_dead"] += 1
        if st["consecutive_dead"] == 1:
            st.update(first_dead=st["first_dead"] + 1, dead_since=at)
        if st["consecutive_dead"] >= 2 and old != "gone":
            st["origin_status"], ev = "gone", {"from": old, "to": "gone", "dead_since": st["dead_since"]}
    return st, ev


_FRESH = {"last_probe_at": None, "last_live_at": None, "consecutive_dead": 0, "last_status": None,
          "origin_status": None, "probes": 0, "first_dead": 0, "flaps": 0, "dead_since": None}
_LIVE_PAGES = ("FROM leaks l JOIN watches w ON w.watch_id = l.watch_id LEFT JOIN probe_state p ON p.leak_id = l.leak_id "
               "WHERE l.kind = 'page' AND w.paused = 0 AND w.deleted_at IS NULL")


def record(c, r, status, at, **extra):
    """One settled result for one Leak: r = a row with its leak_id and probe_state columns (NULL when it has none). Writes
    the new state and, when origin_status changes, the status event (extra merged into its data). -> False, and writes
    nothing, when the Leak was already settled this UTC day."""
    old = {k: r[k] for k in _FRESH} if r["probes"] is not None else dict(_FRESH)
    if (old["last_probe_at"] or "")[:10] == at[:10]:
        return False
    st, ev = step(old, status, at)
    c.execute("INSERT OR REPLACE INTO probe_state (leak_id, " + ", ".join(_FRESH) + ") VALUES (?"
              + ", ?" * len(_FRESH) + ")", (r["leak_id"], *(st[k] for k in _FRESH)))
    if ev:
        tdb.add_event(c, r["leak_id"], "status", {**ev, **extra}, at)
    return True


def apply(key, status, at=None):
    """One probe result -> every probe-able Leak with this url_key not probed this UTC day. -> Leaks updated."""
    at = at or tdb.now()
    with tdb.db() as c:
        return sum(record(c, r, status, at) for r in c.execute(f"SELECT l.leak_id, p.* {_LIVE_PAGES} AND l.url_key = ?",
                                                                 (key,)).fetchall())


def _today_status(c, key, today):
    r = c.execute("SELECT p.last_status FROM leaks l JOIN probe_state p ON p.leak_id = l.leak_id WHERE l.url_key = ? "
                  "AND substr(p.last_probe_at, 1, 10) = ? LIMIT 1", (key, today)).fetchone()
    return r and r[0]


def run(watch_ids):
    """Probe every page Leak of these (unpaused, undeleted) watches not probed today -> {keys, fetched, reused}.
    A key in flight in another thread of this process is left to it (it applies to every Leak with the key)."""
    if not watch_ids:
        return {"keys": 0, "fetched": 0, "reused": 0}
    today = tdb.day()
    with tdb.db() as c:
        due = {}
        for r in c.execute(f"SELECT l.url_key, l.url {_LIVE_PAGES} AND l.watch_id IN ({','.join('?' * len(watch_ids))}) "
                           "AND (p.last_probe_at IS NULL OR substr(p.last_probe_at, 1, 10) < ?) ORDER BY l.created_at",
                           (*watch_ids, today)):
            due.setdefault(r["url_key"], r["url"])
    reused, todo = 0, {}
    with _LOCK:
        with tdb.db() as c:
            for key, url in due.items():
                if key in _inflight:
                    continue
                done = _today_status(c, key, today)
                if done:
                    reused += 1
                    todo[key] = (url, done)
                else:
                    _inflight.add(key)
                    todo[key] = (url, None)
    for key, (_, done) in todo.items():
        if done:
            apply(key, done)
    fetch, hosts = fetcher(), {}
    fresh = [(k, u) for k, (u, done) in todo.items() if not done]
    for _, u in fresh:
        hosts.setdefault(rules.registrable_domain(u) or u, threading.BoundedSemaphore(PER_HOST))

    def one(item):
        key, url = item
        try:
            with hosts[rules.registrable_domain(url) or url]:
                apply(key, classify(fetch, url))
        finally:
            with _LOCK:
                _inflight.discard(key)

    try:
        with _cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            list(ex.map(one, fresh))
    finally:
        with _LOCK:
            _inflight.difference_update(k for k, _ in fresh)
    return {"keys": len(due), "fetched": len(fresh), "reused": reused}

"""
Abuse guards for the public app: a per-IP token-bucket + concurrency limiter,
and a process-wide cap on concurrent long-running jobs (scan subprocesses).

ThreadingHTTPServer spawns one thread per connection with NO built-in cap, so
these are the real backpressure. Inject `clock` for deterministic tests.
Stdlib only, thread-safe.
"""

import threading
import time


class Limiter:
    """Per-IP token bucket + optional per-IP concurrency cap.

    allow(ip)                 -> consume a token AND a concurrency slot (call
                                 release(ip) when the request finishes).
    allow(ip, concurrency=False) -> token only (for cheap GETs; no release needed).
    """

    def __init__(self, rate_per_min=5, burst=5, max_concurrent=2,
                 prune_after=600, clock=time.time):
        self.rate = rate_per_min / 60.0        # tokens per second
        self.burst = float(burst)
        self.max_concurrent = max_concurrent
        self.prune_after = prune_after
        self._clock = clock
        self._lock = threading.Lock()
        self._b = {}                            # ip -> {tokens, last, inflight}
        self._last_prune = clock()

    def _bucket(self, ip, now):
        b = self._b.get(ip)
        if b is None:
            b = {"tokens": self.burst, "last": now, "inflight": 0}
            self._b[ip] = b
        return b

    def _prune(self, now):
        # Cheap amortized prune; bounds memory on a public endpoint hit by many IPs.
        if now - self._last_prune < 300:
            return
        self._last_prune = now
        dead = [ip for ip, b in self._b.items()
                if b["inflight"] <= 0 and now - b["last"] > self.prune_after]
        for ip in dead:
            del self._b[ip]

    def allow(self, ip, concurrency=True):
        with self._lock:
            now = self._clock()
            self._prune(now)
            b = self._bucket(ip, now)
            b["tokens"] = min(self.burst, b["tokens"] + (now - b["last"]) * self.rate)
            b["last"] = now
            if concurrency and b["inflight"] >= self.max_concurrent:
                return False
            if b["tokens"] < 1.0:
                return False
            b["tokens"] -= 1.0
            if concurrency:
                b["inflight"] += 1
            return True

    def release(self, ip):
        with self._lock:
            b = self._b.get(ip)
            if b and b["inflight"] > 0:
                b["inflight"] -= 1

    def refund(self, ip):
        """Hands back the token of an allow() that gave the caller nothing."""
        with self._lock:
            b = self._b.get(ip)
            if b:
                b["tokens"] = min(self.burst, b["tokens"] + 1.0)


class GlobalCap:
    """Process-wide cap on concurrent long-running jobs (scan subprocesses),
    independent of source IP — stops a fleet of IPs from exhausting CPU/threads.
    Non-blocking: acquire() returns False when saturated."""

    def __init__(self, max_concurrent=4):
        self._sem = threading.BoundedSemaphore(max_concurrent)

    def acquire(self):
        return self._sem.acquire(blocking=False)

    def release(self):
        try:
            self._sem.release()
        except ValueError:
            pass

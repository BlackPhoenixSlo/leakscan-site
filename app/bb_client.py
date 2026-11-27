"""Browserbase REST, shared by media_gather and tracker_serp: call, create (one retry on 429), gated (one create at
a time process-wide, >= CREATE_GAP s apart: the org's 25 creates/min) and release. Each caller passes its own creds;
proxies are only ever requested when a caller asks. The key is never logged. Stdlib only."""
import json
import sys
import threading
import time
import urllib.error
import urllib.request

BB_API = "https://api.browserbase.com/v1"
CREATE_GAP = 2.5
GATE = threading.Lock()
LAST = [0.0]


def _stderr(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def call(method, path, key, body, timeout=15):
    req = urllib.request.Request(BB_API + path, data=json.dumps(body).encode(), method=method,
                                 headers={"X-BB-API-Key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def create(key, proj, timeout, deadline, proxies=False, *, call=call, log=_stderr, who="browserbase"):
    """-> {id, connectUrl} or None."""
    body = {"projectId": proj, "browserSettings": {"solveCaptchas": True}, "timeout": timeout}
    if proxies:
        body["proxies"] = True
    for attempt in (0, 1):
        try:
            d = call("POST", "/sessions", key, body)
            return {"id": d["id"], "connectUrl": d["connectUrl"]}
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:   # 25 creates/min shared with other tools: retry once
                try:
                    wait = float(e.headers.get("Retry-After") or 10)
                except ValueError:
                    wait = 10.0
                wait = min(wait, deadline - time.monotonic() - 30)
                if wait >= 0:
                    time.sleep(wait)
                    continue
            log(f"{who} create failed: {e.code}")
            return None
        except Exception as e:
            log(f"{who} create failed: {type(e).__name__}")
            return None
    return None


def gated(fn, gap=None):
    """fn() (a create) under the process-wide gate, >= gap (default CREATE_GAP) s after the previous one."""
    with GATE:
        wait = LAST[0] + (CREATE_GAP if gap is None else gap) - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            return fn()
        finally:
            LAST[0] = time.monotonic()


def release(key, proj, sid, *, call=call, log=_stderr, who="browserbase"):
    for _ in range(2):
        try:
            call("POST", f"/sessions/{sid}", key, {"projectId": proj, "status": "REQUEST_RELEASE"})
            return True
        except Exception:
            pass
    log(f"{who} release failed")
    return False

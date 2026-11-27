"""Stand-in for tracker_probe's fetcher (loaded only with TRACKER_FETCHER=stub; tests may set_fetcher(FETCH) too).
Every URL answers 200 with a plain page unless TRACKER_STUB_FETCH names a JSON file {url | "*": status |
[status, body]}, re-read each call so another process (tracker_cli daily) sees the same answers. CALLS lists the
URLs this process fetched. All data synthetic; nothing leaves the box."""
import json
import os
import threading

PAGE = "<html><head><title>Synthetic page</title></head><body><h1>Gallery</h1></body></html>"
CALLS = []
_LOCK = threading.Lock()


def table():
    path = os.environ.get("TRACKER_STUB_FETCH")
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def FETCH(url):
    with _LOCK:
        CALLS.append(url)
    t = table()
    v = t.get(url, t.get("*", 200))
    status, body = (v, None) if isinstance(v, int) else v
    return status, PAGE if body is None and status == 200 else body or ""

"""Local stand-in for api.leakshaven.com (wire shape of /content/suggest + /content), used by
tests/test_leakshaven.py and the local real-path run (LEAKSHAVEN_BASE=http://127.0.0.1:PORT).
All data is synthetic (fake handle, fake pack ids).

  python3 tests/leakshaven_stub.py PORT [ok|nomatch|other|404|403|slow]
"""
import json
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HANDLE = "demo_creator_x"
TITLE = "Demo Creator X"
MODEL = "00000000-0000-4000-8000-000000000002"
OTHER = "00000000-0000-4000-8000-000000000003"                 # another creator with the same display title
WHO = {"title": TITLE, "modelId": MODEL}                         # what match() picks for HANDLE
SUGGEST = [
    {"title": "Other Demo", "modelId": "00000000-0000-4000-8000-000000000001", "matchedSearch": "demo_creator_xy",
     "matchedSource": "instagram", "nationality": ["XX"], "ethnicity": "x", "birthDate": "2000-01-01",
     "media": {"url": "https://img.invalid/a.jpg", "aspectRatio": 1.0, "blurHash": None}},
    {"title": TITLE, "modelId": OTHER, "matchedSearch": "someone_else_x",
     "matchedSource": "instagram", "nationality": ["XX"], "ethnicity": "x", "birthDate": "2000-01-01",
     "media": {"url": "https://img.invalid/c.jpg", "aspectRatio": 1.0, "blurHash": None}},
    {"title": TITLE, "modelId": MODEL, "matchedSearch": HANDLE,
     "matchedSource": "instagram", "nationality": ["XX"], "ethnicity": "x", "birthDate": "2000-01-01",
     "media": {"url": "https://img.invalid/b.jpg", "aspectRatio": 1.0, "blurHash": None}},
]


def _pack(i, **kw):
    p = {"createdAt": f"2026-11-0{i}T10:00:00.000Z", "id": f"fakepack-{i:04d}", "shortCode": f"fk{i:04d}",
         "media": "https://img.invalid/p.jpg", "mediaAspectRatio": 1.0, "mediaType": "image", "tags": [],
         "title": f"{TITLE} pack {i}", "views": 10 * i, "isTrending": False, "blurHash": "x", "deleted": False,
         "isPremium": False, "info": {"images": 100 + i, "size": 4_000_000_000 + i, "updatedAt":
                                      f"2026-11-0{i}T12:00:00.000Z", "videos": 300 + i}}
    p.update(kw)
    return p


# `search=<title>` is free text: the same-titled other creator's packs come back too and must be dropped
CONTENT = {"content": [_pack(1), _pack(2), _pack(1),                         # dup id -> dropped
                       _pack(3, deleted=True),                                # deleted -> dropped
                       _pack(4, shortCode="../evil"),                         # bad code -> dropped
                       _pack(6, modelId=OTHER),                               # other creator -> dropped
                       _pack(7, modelId=MODEL, info={"images": "12", "size": 5.0e9, "videos": 3.0}),
                       _pack(5, info={}, createdAt="nonsense")],              # meta missing -> nulls
           "count": 8, "cursorId": "x", "richProfileId": MODEL, "richProfileName": TITLE}
# the search resolved to the other creator: nothing is attributable to MODEL
CONTENT_OTHER = {"content": [_pack(1), _pack(2)], "count": 2, "cursorId": "x", "richProfileId": OTHER,
                 "richProfileName": TITLE}


class Stub(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=0, mode="ok"):
        super().__init__(("127.0.0.1", port), _H)
        self.mode, self.calls, self.slow = mode, [], 3.0

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server_address[1]}"

    def start(self):
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        self.server.calls.append((u.path, q))
        mode = self.server.mode
        if mode == "404":
            return self._send({"statusCode": 404, "message": "Not Found"}, 404)
        if mode == "403":
            return self._send({"statusCode": 403, "message": "Forbidden resource"}, 403)
        if mode == "slow":
            time.sleep(self.server.slow)
        if u.path == "/content/suggest":
            return self._send([] if mode == "nomatch" else SUGGEST)
        if u.path == "/content" and q.get("search") == TITLE and q.get("sorting") == "NEWEST":
            return self._send(CONTENT_OTHER if mode == "other" else CONTENT)
        self._send({"content": []})


if __name__ == "__main__":
    s = Stub(int(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "ok")
    print(f"leakshaven stub on {s.base} mode={s.mode}", flush=True)
    s.serve_forever()

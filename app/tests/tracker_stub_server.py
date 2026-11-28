"""Seam 6: the Removal service's public server on loopback with every upstream stubbed (Google CSE ->
upstream_stub, the Mega aggregator -> leakshaven_stub, Origin probes -> tracker_stub_fetch, Browserbase -> a closed
loopback port with the host's BROWSERBASE_* unset), a temp TRACKER_DB and
the Quick scan DB, the seed inline and the scheduler thread off. Prints the base URL, then TRACKER_DB=<path> and
TRACKER_STUB_FETCH=<path> for other processes (tracker_cli with TRACKER_FETCHER=stub). Test-only routes:
  POST /__tracker/daily?at=<ISO>    one daily pass at that moment -> its counts (JSON)
  POST /__tracker/fetch             body {url | "*": status | [status, body]} -> the stub fetcher's answers
                                    (a [200, html] answer is a listing page for the listing recheck)
  POST /__tracker/mega              body {suggest?, title?, content?} -> the Mega index stub's next answers (a pack
                                    with "deleted": true is how a Mega `deleted` day is staged)
  python3 app/tests/tracker_stub_server.py --port N [--db PATH]"""
import argparse
import json
import os
import sys
import tempfile
import urllib.parse
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--db")
    a = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="tracker-stub-")
    os.environ.update(TRACKER_DB=a.db or os.path.join(tmp, "tracker.db"), TRACKER_SEED_INLINE="1",
                      TRACKER_FETCHER="stub", TRACKER_SCHEDULER="0", TRACKER_STUB_FETCH=os.path.join(tmp, "fetch.json"),
                      GOOGLE_API_KEY="fake", GOOGLE_CSE_ID="fake", SCAN_REUSE_TTL="0")
    for k in ("BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID"):
        os.environ.pop(k, None)
    import bb_client
    import cse_scanner
    import db
    import leakshaven
    import leakshaven_stub
    import media_gather
    import public_app
    import tracker_db
    import tracker_scheduler
    import upstream_stub

    cse, agg = upstream_stub.Stub().start(), leakshaven_stub.Stub().start()
    cse_scanner.CSE_ENDPOINT = cse.base + "/customsearch/v1"
    bb_client.BB_API = "http://127.0.0.1:9"
    db.DB_PATH = os.path.join(tmp, "public.db")
    public_app.PROFILE_ENABLED = public_app.ALIAS_ENRICH = media_gather.MEDIA_ENABLED = False
    leakshaven.BASE, leakshaven.ENABLED, leakshaven.MIN_GAP = agg.base, True, 0.0
    db.init_db()
    tracker_db.init()

    class Handler(public_app.Handler):
        def do_POST(self):
            u = urllib.parse.urlsplit(self.path)
            if u.path == "/__tracker/daily":
                at = urllib.parse.parse_qs(u.query).get("at", [None])[0]
                return self._json(tracker_scheduler.daily_pass(at))
            if u.path == "/__tracker/fetch":
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}"
                with open(os.environ["TRACKER_STUB_FETCH"], "w", encoding="utf-8") as fh:
                    fh.write(body.decode())
                return self._json({"ok": True})
            if u.path == "/__tracker/mega":
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                for k in ("suggest", "title", "content"):
                    if k in body:
                        setattr(agg, k, body[k])
                return self._json({"ok": True})
            return super().do_POST()

        def _json(self, obj):
            b = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"http://127.0.0.1:{srv.server_address[1]}", flush=True)
    print(f"TRACKER_DB={os.environ['TRACKER_DB']}", flush=True)
    print(f"TRACKER_STUB_FETCH={os.environ['TRACKER_STUB_FETCH']}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

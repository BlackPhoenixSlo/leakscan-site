#!/usr/bin/env python3
"""Volume proof of /api/thumb-sheet/<slug>: the real app/public_app.py Handler + real SQLite + real disk cache, many clients over real sockets.

    python3 ~/.slop/gate.py run -- nice -n 10 python3 tools/thumb_sheet_load.py OUT [--users 200] [--reports 30] [--seeded 1000] [--ramp 10] [--break-singleflight]

Declared bypass: upstream (Google's thumb host) is faked at the wire: public_app._THUMB_OPENER (replaced from here, no service code touched) sends the same request
to a local HTTP server with thumb-sized bodies and the latency measured on real gstatic (median ~143 ms). Rows seeded by SQL; every act goes through the real endpoint.

Waves: 1 cold (--users clients over --ramp s, one IP each, hot reports); 2 warm (the same again); 3 one IP flooding its bucket. Asserts: no 5xx; nothing dropped (every thumb of a
report is a cell, or dead when upstream said 404, or absent, then per-thumb in the client, only in a sheet marked partial: upstream said 503 / the build ran out of time, reported); cells byte-identical, in the client's order; upstream fetched
each thumb at most once (single-flight, disk cache), never more than THUMB_SHEET_POOL at a time; p95; disk under its bound; the flood gets 429s, no 5xx.
--break-singleflight: every request builds its own sheet: only the fetch-count and warm checks may go red. Writes results.json + SHA.txt to OUT; exit 1 on a FAIL."""
import argparse, collections, hashlib, http.client, http.server, json, os, pathlib, random, sqlite3, statistics, subprocess, sys, tempfile, threading, time, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOST = "https://encrypted-tbn0.gstatic.com/images?q=tbn:"
ORIGIN = "https://blackphoenixslo.github.io"


def body_of(key):   # deterministic: the client checks every cell against it
    h = hashlib.sha256(key.encode()).digest()
    return (h * (200 + h[0] % 200))[: 2000 + (h[1] * 60)]


class Upstream(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    calls, lock, inflight, peak = collections.Counter(), threading.Lock(), 0, 0

    def log_message(self, *a):
        pass

    def do_GET(self):
        C = Upstream
        if self.path == "/__stats":
            b = json.dumps({"calls": C.calls, "peak": C.peak}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            return self.wfile.write(b)
        key = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)["q"][0].split(":")[1]
        with C.lock:
            C.calls[key] += 1
            C.inflight += 1
            C.peak = max(C.peak, C.inflight)
        time.sleep(min(0.3, max(0.06, random.lognormvariate(-1.95, 0.35))))
        with C.lock:
            C.inflight -= 1
        code = 404 if key.endswith("D") else 503 if key.endswith("E") else 200
        b = body_of(key) if code == 200 else b"no"
        self.send_response(code)
        self.send_header("Content-Type", "image/jpeg" if code == 200 else "text/plain")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


def serve(args):
    """The server side (own process): the real Handler; upstream faked at the wire."""
    sys.path.insert(0, str(ROOT / "app"))
    import public_app
    import thumb_sheet
    up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{up.server_address[1]}"
    real = urllib.request.build_opener(public_app._NoRedirect)

    class WireOpener:
        def open(self, req, timeout=None):
            q = urllib.parse.urlsplit(req.full_url).query
            return real.open(urllib.request.Request(f"{base}/images?{q}", headers=dict(req.header_items())), timeout=timeout)
    public_app._THUMB_OPENER = WireOpener()
    if args.break_singleflight:
        thumb_sheet.sheet = lambda urls, o, m, born=None: thumb_sheet._build(urls, o, m)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), public_app.Handler)
    srv.request_queue_size = 512
    print(json.dumps({"port": srv.server_address[1], "up": up.server_address[1]}), flush=True)
    srv.serve_forever()


def seed(db_path, n, hot):
    """n rows by SQL, the first `hot` of them with a report's shape (44 thumbs; 2 dead upstream; every other report 1 failing upstream)."""
    rows, want = [], {}
    for r in range(n):
        slug = f"load{r:06d}aa"
        ids = [f"r{r}x{i}" + ("D" if i in (5, 30) else "E" if i == 17 and r % 2 else "") for i in range(44)] if r < hot else []
        urls = [HOST + i for i in ids]
        images, results = urls[:18], [{"thumb": u, "link": f"https://x.example/{i}", "domain": "x.example"} for i, u in enumerate(urls[10:])]
        rows.append((slug, "low", "onlyfans.com", "demo", "2026-11-06T00:00:00Z", "complete", "[]", json.dumps({"images": images, "results": results})))
        want[slug] = ids
    c = sqlite3.connect(db_path)
    c.executemany("INSERT INTO scans (slug, level, platform, handle, created_at, status, result_json, extra_json) VALUES (?,?,?,?,?,?,?,?)", rows)
    c.commit()
    c.close()
    return {k: want[k] for k in list(want)[:hot]}


def get(port, slug, ip):
    t = time.perf_counter()
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    try:
        c.request("GET", f"/api/thumb-sheet/{slug}", headers={"X-Real-IP": ip, "Origin": ORIGIN})
        r = c.getresponse()
        return r.status, r.read(), dict(r.getheaders()), time.perf_counter() - t
    finally:
        c.close()


def verify(body, ids, complete):
    """→ (thumbs lost: absent from a sheet that says it is complete, wrong bytes or wrong dead, out of order, absent though upstream answers = the deadline cut them)."""
    n = int(body[:8])
    m = json.loads(body[8:8 + n])
    at, bad, by = 8 + n, 0, {u: i for i, u in enumerate(HOST + x for x in ids)}
    cells = [c[0] for c in m["cells"]]
    for src, _, size in m["cells"]:
        bad += body[at:at + size] != body_of(src[len(HOST):])
        at += size
    bad += at != len(body)
    dead_ok = {HOST + x for x in ids if x.endswith("D")}
    gaps = [u for u in by if u not in cells and u not in m["dead"]]
    wrong_dead = [u for u in m["dead"] if u not in dead_ok]
    order = cells != sorted(cells, key=by.get)
    return (gaps if complete else []), bad + len(wrong_dead), order, [u for u in gaps if not u.endswith("E")]


def wave(name, port, want, users, ramp, rnd):
    hot = list(want)
    weights = [1 / (i + 1) for i in range(len(hot))]
    out, lock = [], threading.Lock()

    def user(i):
        time.sleep(rnd.uniform(0, ramp) if ramp else 0)
        slug = hot[i] if i < len(hot) else rnd.choices(hot, weights)[0]   # every report once, so a warm wave has no first build
        st, b, h, dt = get(port, slug, f"10.{i >> 8 & 255}.{i & 255}.9")
        v = verify(b, want[slug], "max-age=86400" in (h.get("Cache-Control") or "")) if st == 200 else ([], 0, False, [])
        with lock:
            out.append((st, dt, v, h.get("Access-Control-Allow-Origin"), h.get("Cache-Control")))
    ts = [threading.Thread(target=user, args=(i,)) for i in range(users)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    lat = sorted(x[1] for x in out)
    return {"wave": name, "users": users, "status": dict(collections.Counter(x[0] for x in out)), "p50_ms": round(statistics.median(lat) * 1000), "p95_ms": round(lat[int(len(lat) * .95) - 1] * 1000), "max_ms": round(lat[-1] * 1000),
            "dropped": sum(len(x[2][0]) for x in out), "wrong_bytes_or_dead": sum(x[2][1] for x in out), "out_of_order": sum(x[2][2] for x in out),
            "cut_by_deadline": sum(len(x[2][3]) for x in out), "cors_ok": all(x[3] == ORIGIN for x in out if x[0] == 200),
            "partial_responses": sum(1 for x in out if x[0] == 200 and "max-age=300" in (x[4] or ""))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?")
    ap.add_argument("--users", type=int, default=200)
    ap.add_argument("--reports", type=int, default=30)
    ap.add_argument("--seeded", type=int, default=1000)
    ap.add_argument("--ramp", type=float, default=10)
    ap.add_argument("--cache-bytes", type=int, default=20000000)
    ap.add_argument("--break-singleflight", action="store_true")
    ap.add_argument("--serve", action="store_true")
    a = ap.parse_args()
    if a.serve:
        return serve(a)
    out = pathlib.Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    sha = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    fails, checks = [], {}

    def check(name, ok, detail=""):
        checks[name] = bool(ok)
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}", flush=True)
        if not ok:
            fails.append(name)

    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "PUBLIC_DB": f"{tmp}/t.db", "DATA_DIR": tmp, "THUMB_SHEET_CACHE_BYTES": str(a.cache_bytes)}
        subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'app'); import db; db.init_db()"], cwd=ROOT, env=env, check=True)
        want = seed(f"{tmp}/t.db", a.seeded, a.reports)
        unique = sum(len(v) for v in want.values())
        p = subprocess.Popen([sys.executable, __file__, "--serve"] + (["--break-singleflight"] if a.break_singleflight else []), env=env, stdout=subprocess.PIPE, cwd=ROOT)
        try:
            ports = json.loads(p.stdout.readline())
            rnd = random.Random(7)
            cold = wave("cold", ports["port"], want, a.users, a.ramp, rnd)
            stats = lambda: json.loads(urllib.request.urlopen(f"http://127.0.0.1:{ports['up']}/__stats").read())
            s1 = stats()
            warm = wave("warm", ports["port"], want, a.users, a.ramp / 2, rnd)
            s2 = stats()
            print(json.dumps(cold), "\n", json.dumps(warm), flush=True)
            flood = collections.Counter(get(ports["port"], next(iter(want)), "10.99.99.99")[0] for _ in range(100))
            size = sum(f.stat().st_size for f in pathlib.Path(tmp, "thumb-sheets").glob("*"))
            n_up, top = sum(s2["calls"].values()), max(s2["calls"].values())
            check("no 5xx, cold + warm", not [c for w in (cold, warm) for c in w["status"] if int(c) >= 500], [cold["status"], warm["status"]])
            check("nothing dropped, bytes identical, the client's order", not any(w["dropped"] or w["wrong_bytes_or_dead"] or w["out_of_order"] for w in (cold, warm)), {k: cold[k] for k in ("dropped", "wrong_bytes_or_dead", "out_of_order", "cut_by_deadline", "partial_responses")})
            check("CORS: every 200 readable by the site's origin", cold["cors_ok"] and warm["cors_ok"])
            check("single-flight: upstream asked at most once per thumb", top == 1 and n_up <= unique, f"{n_up} fetches, {unique} thumbs in {a.reports} reports for {a.users} users, top {top}")
            check("warm wave: no upstream fetch", sum(s2["calls"].values()) == sum(s1["calls"].values()), sum(s2["calls"].values()) - sum(s1["calls"].values()))
            check("pool: upstream never above THUMB_SHEET_POOL (8) at once", s2["peak"] <= 8, s2["peak"])
            check("disk under its bound", size <= a.cache_bytes, f"{size} B of {a.cache_bytes}")
            check("flood: own bucket answers 429, no 5xx", flood[429] > 0 and not [c for c in flood if c >= 500], dict(flood))
            res = {"sha": sha, "args": vars(a), "cold": cold, "warm": warm, "flood": dict(flood), "upstream_fetches": n_up, "upstream_peak": s2["peak"], "disk_bytes": size, "checks": checks, "fails": fails}
            (out / "results.json").write_text(json.dumps(res, indent=1, default=str))
            (out / "SHA.txt").write_text(sha + "\n")
        finally:
            p.terminate()
    print("p95 cold", cold["p95_ms"], "ms, warm", warm["p95_ms"], "ms;", "FAILS" if fails else "all green", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

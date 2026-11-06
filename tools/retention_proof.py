#!/usr/bin/env python3
"""Retention under load: a mass-seeded DB, public_app.run_retention() while real HTTP readers and scan inserts hit the real
public_app.Handler. This repo has no slop/ harness: this script is its stand-in for this flow (declared).

    python3 tools/retention_proof.py OUT_DIR [--rows 20000] [--readers 16] [--scanners 4] [--break-key] [--break-cutoff]

Seeded by SQL (real shapes: tools/fixtures/scan-sample.json, deep rows ~1 MB, ages, NULL / corrupt extra, running, pre-aggregator-
rule rows). Acts only through endpoints. The expected tiers below are written out again, NOT read from db.py: moving a key in
db.py must turn this red. Declared bypasses: Google CSE + DeepSeek + leakshaven are app/tests wire stubs; profile pages a fake at
their urlopen; media gathering off; limiters widened. A socket guard refuses any non-loopback connect. All data synthetic.
--break-key moves `gallery` to the small tier, --break-cutoff has big_days back at 30: only their checks may go red.
OUT_DIR gets report.json (checks, timings, sizes), run.log. Exit 1 on any red check."""
import argparse
import collections
import concurrent.futures as cf
import http.client
import json
import os
import random
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIG = {"images", "results", "gallery", "img_meta", "excluded"}
SMALL = {"mega", "cse_sites", "mega_key", "scan_key", "reused_from"}
FIXTURE = json.load(open(os.path.join(ROOT, "tools", "fixtures", "scan-sample.json"), encoding="utf-8"))
DAY = 86400
RATE = 100   # reads/s in total. The API speaks HTTP/1.0: each request is a socket in TIME_WAIT for 30 s, and the machine has 16k ports for every session
AGES = {"young": (0.1, 2.9), "mid": (3.1, 29.9), "old": (30.1, 90)}


def iso(age_days, now):
    return (now - timedelta(days=age_days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def shape(i, now):
    """Row i, deterministic: its kind, age class and columns. The check recomputes this."""
    rng = random.Random(i)
    age = rng.choice(("young", "mid", "mid", "old", "old", "old"))
    roll = rng.random()
    kind = ("deep" if roll < .01 else "null" if roll < .02 else "corrupt" if roll < .03 else "running" if roll < .035 else
            "empty" if roll < .055 else "prerule" if roll < .065 else "reused" if roll < .2 else "low")
    slug = f"seed{i:08d}"
    days = rng.uniform(*AGES[age])
    hits = [dict(h, url=h["url"] + f"?{i}") for h in FIXTURE["hits"]]
    ex = {"images": [u + f"?{i}" for u in FIXTURE["images"]] * 12, "results": FIXTURE["results"], "profile": {**FIXTURE["profile"], "avatar": True},
          "aliases": FIXTURE["aliases"], "socials": {"instagram": f"ig{i}"}, "google_total": FIXTURE["google_total"], "mega": [],
          "scan_key": f"key{i}", "mega_key": f"mk{i}", "a_future_field": i}
    status = "complete"
    if kind == "deep":
        ex.update(gallery=[{"u": f"https://g.example/{j}", "w": 1} for j in range(9000)], img_meta={f"u{j}": {"w": 1} for j in range(5000)},
                  accepted_urls=[f"https://a.example/{j}" for j in range(8000)], links_by_domain={"a.example": [f"https://a.example/{j}" for j in range(8000)]},
                  removed_urls=["https://r.example/1"], cse_sites=[{"d": "a.example"}], top_leaks=[{"u": "x"}], n_leaks=3, n_media=1, n_hosting=1, n_sites=2,
                  quote={"p": 1}, slugs=["s"], excluded=["e"], mega_ok=True)
    elif kind == "reused":
        ex.pop("scan_key")
        ex.update(reused_from=f"seed{max(0, i - 1):08d}", as_of=iso(days, now))
    elif kind == "running":
        status = "running"
    elif kind == "empty":
        hits, status = [], "empty"
    elif kind == "prerule":
        hits = hits + [{"domain": "leakshaven.com", "url": f"https://leakshaven.com/p{i}", "occurrences": 2}]
        ex["mega"] = [{"url": "https://s.leakshaven.com/AAA", "host": "leakshaven.com", "via": "leakshaven.com", "title": "x", "status": "live"}]
        ex["results"] = FIXTURE["results"] + [{"link": "https://leakshaven.com/r", "domain": "leakshaven.com", "title": "t", "thumb": None}]
    extra = json.dumps(ex, ensure_ascii=False, separators=(",", ":"))
    if kind == "null":
        extra = None
    elif kind == "corrupt":
        extra = '{"images": ["cut off'
    return {"slug": slug, "level": "deep" if kind == "deep" else "low", "platform": "onlyfans.com", "handle": f"h{i}", "created_at": iso(days, now),
            "status": status, "result_json": json.dumps(hits, ensure_ascii=False), "hit_count": len(hits),
            "domain_count": len({h["domain"] for h in hits}), "ownership_verified": 1 if i % 97 == 0 else 0, "verify_code": f"v{i}",
            "verify_platform": "onlyfans.com", "client_ip_hash": f"ip{i}", "extra_json": extra, "_kind": kind, "_age": age, "_days": days}


def want_top(hits, cap=20):
    by = {}
    for h in hits:
        occ = h.get("occurrences")
        by[h["domain"]] = by.get(h["domain"], 0) + (occ if isinstance(occ, int) and occ > 0 else 1)
    return [{"domain": d, "n": n} for d, n in sorted(by.items(), key=lambda kv: -kv[1])[:cap]]


def load(args):
    """Separate process: the visitors. Reads + scans until the stop file; one JSON line per request, to a file."""
    sample = json.load(open(args.load[1]))
    port, stop, out = int(args.load[0]), args.load[2], open(args.load[3], "w", buffering=1)
    lock = threading.Lock()

    def http_(method, path, body=None):
        t0 = time.time()
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
            c.request(method, path, body=json.dumps(body) if body else None, headers={"Content-Type": "application/json"} if body else {})
            r = c.getresponse()
            data = r.read()
            c.close()
            return r.status, data, t0, time.time()
        except OSError as e:
            return 0, str(e).encode(), t0, time.time()

    def emit(kind, st, t0, t1, slug=None):
        with lock:
            out.write(json.dumps({"k": kind, "s": st, "t0": t0, "t1": t1, "slug": slug}) + "\n")

    def reader(seed):
        rng = random.Random(seed)
        while not os.path.exists(stop):
            slug = rng.choice(sample)
            for kind, path in (("result", f"/api/scan-result/{slug}"), ("profile", f"/api/profile/{slug}"), ("media", f"/api/media/{slug}"), ("avatar", f"/api/avatar/{slug}")):
                st, _d, t0, t1 = http_("GET", path)
                emit(kind, st, t0, t1)
                time.sleep(args.readers / RATE)

    def scanner(seed):
        n = 0
        while not os.path.exists(stop):
            n += 1
            body = {"handle": args.handle, "platform": "onlyfans.com", "level": "low"}
            if n % 2:
                body["fresh"] = True    # half fresh, half reuse: both paths insert a row
            st, data, t0, t1 = http_("POST", "/api/public-scan", body)
            slug = None
            for block in data.decode(errors="replace").split("\n\n"):
                if block.startswith("event: result"):
                    slug = json.loads("\n".join(x[6:] for x in block.split("\n")[1:] if x.startswith("data: "))).get("slug")
            emit("scan", st, t0, t1, slug)
            time.sleep(0.5)

    threads = [threading.Thread(target=reader, args=(i,)) for i in range(args.readers)] + [threading.Thread(target=scanner, args=(i,)) for i in range(args.scanners)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def p95(v):
    return round(sorted(v)[int(len(v) * .95) - 1], 4) if v else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?")
    ap.add_argument("--rows", type=int, default=20000)
    ap.add_argument("--readers", type=int, default=16)
    ap.add_argument("--scanners", type=int, default=4)
    ap.add_argument("--handle", default="")
    ap.add_argument("--break-key", action="store_true")
    ap.add_argument("--break-cutoff", action="store_true")
    ap.add_argument("--load", nargs=4)
    args = ap.parse_args()
    if args.load:
        return load(args)

    os.makedirs(args.out, exist_ok=True)
    sys.path[:0] = [os.path.join(ROOT, "app"), os.path.join(ROOT, "app", "tests")]
    tmp = tempfile.mkdtemp(prefix="retention-proof-")
    os.environ.update(GOOGLE_API_KEY="fake", GOOGLE_CSE_ID="fake", DEEPSEEK_API_KEY="fake", PUBLIC_DB=os.path.join(tmp, "public.db"), DATA_DIR=tmp)
    outside, connect = [], socket.socket.connect

    def guarded(self, addr):
        if self.family != socket.AF_UNIX and addr[0] not in ("127.0.0.1", "::1", "localhost"):
            outside.append(str(addr))
            raise OSError("blocked non-loopback")
        return connect(self, addr)
    socket.socket.connect = guarded

    import chat_proxy
    import cse_scanner
    import db
    import leakshaven
    import leakshaven_stub as ls
    import media_gather as mg
    import profile_extract as pe
    import public_app
    import ratelimit
    import upstream_stub as stub
    from test_profile import FakeFetch, ig_routes

    up, lsv = stub.Stub().start(), ls.Stub().start()
    cse_scanner.CSE_ENDPOINT, chat_proxy.DEEPSEEK_URL = up.base + "/customsearch/v1", up.base + "/chat/completions"
    leakshaven.BASE, leakshaven.ENABLED, leakshaven.MIN_GAP = lsv.base, True, 0.0
    public_app.PROFILE_ENABLED, public_app.ALIAS_ENRICH, mg.MEDIA_ENABLED = True, False, False
    public_app.SCAN_REUSE_TTL = 21600
    pe.urlopen = FakeFetch(ig_routes())
    wide = lambda: ratelimit.Limiter(rate_per_min=10 ** 7, burst=10 ** 7, max_concurrent=10000)
    public_app.SCAN_LIMITER, public_app.RESULT_LIMITER, public_app.THUMB_LIMITER = wide(), wide(), wide()
    db.DB_PATH = os.environ["PUBLIC_DB"]
    db.init_db()
    log = open(os.path.join(args.out, "run.log"), "w", buffering=1)
    events = []
    public_app._event = lambda m: (events.append(m), log.write(m + "\n"))
    if args.break_key:
        db.RETAIN_BIG = tuple(k for k in db.RETAIN_BIG if k != "gallery")
        db.RETAIN_SMALL = db.RETAIN_SMALL + ("gallery",)
    if args.break_cutoff:
        public_app.RETAIN_BIG_DAYS = 30.0

    # ---------- seed by SQL, files for a sample
    now = datetime.now(timezone.utc)
    t0 = time.time()
    conn = sqlite3.connect(db.DB_PATH)
    cols = ("slug", "level", "platform", "handle", "created_at", "status", "result_json", "hit_count", "domain_count", "ownership_verified",
            "verify_code", "verify_platform", "client_ip_hash", "extra_json")
    q = f"INSERT INTO scans ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
    sizes = collections.Counter()
    for start in range(0, args.rows, 2000):
        batch = [shape(i, now) for i in range(start, min(start + 2000, args.rows))]
        conn.executemany(q, [[r[c] for c in cols] for r in batch])
        conn.commit()
        for r in batch:
            sizes[r["_kind"]] += 1
    conn.close()
    seed_s = time.time() - t0
    bytes_seeded = public_app._db_bytes()
    log.write(f"seeded {args.rows} in {seed_s:.1f}s {bytes_seeded} bytes {dict(sizes)}\n")
    rng = random.Random(7)
    with_files = rng.sample(range(args.rows), min(1000, args.rows))
    mdir, adir = os.path.join(tmp, "media"), public_app._avatar_dir()
    os.makedirs(adir, exist_ok=True)
    for i in with_files:
        r = shape(i, now)
        d = os.path.join(mdir, r["slug"])
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.json"), "w") as fh:
            json.dump({"status": "ready", "images": [], "updated_at": 1}, fh)
        with open(os.path.join(d, "0.jpg"), "wb") as fh:
            fh.write(b"x" * 2000)
        a = os.path.join(adir, f"{r['slug']}.jpg")
        with open(a, "wb") as fh:
            fh.write(b"x" * 2000)
        mt = time.time() - r["_days"] * DAY
        for p in (os.path.join(d, "0.jpg"), os.path.join(d, "index.json"), d, a):
            os.utime(p, (mt, mt))
    croot = os.path.join(tmp, "media-cache")
    os.makedirs(croot, exist_ok=True)
    pinned = next(shape(i, now)["slug"] for i in with_files if shape(i, now)["_age"] != "young" and shape(i, now)["_kind"] != "running")
    for name, age in (("alive", 6 * DAY), ("stale", mg.CACHE_TTL + 60)):
        with open(os.path.join(croot, name + ".json"), "w") as fh:
            json.dump({"ts": time.time() - age, "slug": pinned, "images": [{"n": 0}]}, fh)
        os.utime(os.path.join(croot, name + ".json"), (time.time() - age,) * 2)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), public_app.Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]

    def get(path):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
        c.request("GET", path)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    # ---------- what is served before: every pre-rule / corrupt / null row, plus a sample (a corrupt result_json row raises on read, on main too: not seeded)
    by_kind = collections.defaultdict(list)
    for i in range(0, args.rows, 5):    # every 5th row, at most 800 of a kind
        r = shape(i, now)
        by_kind[r["_kind"]].append(r["slug"])
    sample = [s for v in by_kind.values() for s in v[:800]]
    sample_prerule = [f"seed{i:08d}" for i in range(args.rows) if shape_kind(i) == "prerule"][:600]
    sample = list(dict.fromkeys(sample + sample_prerule))
    keep = ("hit_count", "domain_count", "google_total", "status", "handle", "platform", "created_at", "aliases", "socials", "level", "ownership_verified")
    served = {}

    def snap(slug):
        st, data = get(f"/api/scan-result/{slug}")
        return slug, st, (json.loads(data) if st == 200 else None)
    with cf.ThreadPoolExecutor(8) as ex:
        for slug, st, d in ex.map(snap, sample):
            assert st == 200, (slug, st)
            if d["status"] != "failed":
                served[slug] = {k: d.get(k) for k in keep}

    # ---------- visitors on, baseline, retention under them, a tail
    stop = os.path.join(tmp, "stop")
    sample_file, req_log = os.path.join(tmp, "sample.json"), os.path.join(args.out, "requests.jsonl")
    with open(sample_file, "w") as fh:
        json.dump(sample, fh)
    visitors = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--load", str(port), sample_file, stop, req_log, "--readers", str(args.readers),
                                 "--scanners", str(args.scanners), "--handle", stub.HANDLE], stdout=log, stderr=log)
    time.sleep(10)
    # the worst VACUUM: nothing trimmed yet, every byte live, visitors on. Scans overlapping it must wait it out, not fail.
    vac_full = {"bytes": public_app._db_bytes(), "t0": time.time()}
    db.vacuum()
    vac_full.update(t1=time.time(), after=public_app._db_bytes())
    time.sleep(3)
    vac = {}
    real_vacuum = db.vacuum

    def timed_vacuum(path=None):
        vac["t0"] = time.time()
        vac["wal_before"] = public_app._db_bytes()
        real_vacuum(path)
        vac["t1"] = time.time()
    db.vacuum = timed_vacuum
    run_t0 = time.time()
    n1 = public_app.run_retention()
    run_t1 = time.time()
    db.vacuum = real_vacuum
    bytes_after = public_app._db_bytes()
    time.sleep(5)
    with open(stop, "w"):
        pass
    visitors.wait(timeout=240)
    time.sleep(1)

    reqs = [json.loads(x) for x in open(req_log)]
    n2 = public_app.run_retention()     # idempotent: 0 rows; files too
    dump = lambda: sqlite3.connect(db.DB_PATH).execute("SELECT * FROM scans ORDER BY slug").fetchall()
    d1 = dump()
    n3 = public_app.run_retention()
    d2 = dump()

    # ---------- invariants
    checks = {}

    def check(name, ok, detail=""):
        checks[name] = bool(ok)
        line = f"{'PASS' if ok else 'FAIL'} {name}" + (f": {str(detail)[:300]}" if not ok and detail != "" else "")
        print(line, flush=True)
        log.write(line + "\n")

    inserted = [r["slug"] for r in reqs if r["k"] == "scan" and r["s"] == 200 and r["slug"]]
    c = sqlite3.connect(db.DB_PATH)
    c.row_factory = sqlite3.Row
    total = c.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
    check("rows: count = seeded + scans answered, nothing deleted", total == args.rows + len(inserted), (total, args.rows, len(inserted)))
    missing = [s for s in inserted if not c.execute("SELECT 1 FROM scans WHERE slug=?", (s,)).fetchone()]
    check("rows: every scan answered during the run is stored (no lost insert)", inserted and not missing, missing[:5])
    bad_new = c.execute("SELECT COUNT(*) FROM scans WHERE slug NOT LIKE 'seed%' AND retention != 'full'").fetchone()[0]
    check("rows: scans of today stay full", not bad_new, bad_new)
    bad = collections.defaultdict(list)
    tiers = collections.Counter()
    for i in range(args.rows):
        s = shape(i, now)
        r = c.execute("SELECT * FROM scans WHERE slug=?", (s["slug"],)).fetchone()
        tier = "full" if s["_kind"] == "running" or s["_age"] == "young" else "trimmed" if s["_age"] == "mid" else "summary"
        tiers[tier] += 1
        if r["retention"] != tier:
            bad["tier"].append((s["slug"], s["_kind"], s["_age"], r["retention"]))
            continue
        for k in ("slug", "level", "platform", "handle", "created_at", "ownership_verified"):
            if r[k] != s[k]:
                bad["forever columns"].append((s["slug"], k))
        if s["_kind"] != "prerule":   # those are baked, checked against what was served
            for k in ("status", "hit_count", "domain_count"):
                if r[k] != s[k]:
                    bad["forever columns"].append((s["slug"], k))
        nulled = (r["client_ip_hash"], r["verify_code"], r["verify_platform"]) == (None, None, None)
        if nulled != (tier == "summary"):
            bad["null columns"].append(s["slug"])
        if tier == "full":
            if (r["result_json"], r["extra_json"]) != (s["result_json"], s["extra_json"]):
                bad["full unchanged"].append(s["slug"])
            continue
        if s["_kind"] == "corrupt":
            if r["extra_json"] != s["extra_json"]:
                bad["corrupt extra keeps its bytes"].append(s["slug"])
            continue
        hits = json.loads(s["result_json"])
        if tier == "summary" and r["result_json"] != "[]":
            bad["hits"].append(s["slug"])
        if tier == "trimmed" and s["_kind"] != "prerule" and r["result_json"] != s["result_json"]:
            bad["hits"].append(s["slug"])
        got = json.loads(r["extra_json"]) if r["extra_json"] else None
        if s["_kind"] == "null":
            if tier == "trimmed" and got is not None:
                bad["null extra"].append(s["slug"])
            continue
        was = json.loads(s["extra_json"])
        want = {k: v for k, v in was.items() if k not in BIG and (tier != "summary" or k not in SMALL)}
        want["profile"] = {**was["profile"], "avatar": False}
        if tier == "summary":
            want["top_domains"] = want_top([h for h in hits if h["domain"] != "leakshaven.com"] if s["_kind"] == "prerule" else hits)
        if s["_kind"] == "prerule":
            got = {k: v for k, v in got.items() if k != "google_total"}
            want.pop("google_total", None)
        if got != want:
            diff = sorted(k for k in set(got) | set(want) if got.get(k) != want.get(k))
            bad["tier keys"].append((s["slug"], s["_kind"], tier, diff))
    for name in ("tier", "tier keys", "forever columns", "null columns", "full unchanged", "corrupt extra keeps its bytes", "hits", "null extra"):
        check(f"tiers: {name}", not bad[name], (len(bad[name]), bad[name][:3]))
    after = {}
    with cf.ThreadPoolExecutor(8) as ex:
        for slug, st, d in ex.map(snap, list(served)):
            after[slug] = (st, d)
    moved = [(s, k, served[s][k], after[s][1].get(k)) for s in served if after[s][0] == 200 for k in keep if after[s][1].get(k) != served[s][k]]
    check("served: every report stays 200", all(v[0] == 200 for v in after.values()))
    check("served: counts and forever fields stable, before = after", not moved, (len(moved), moved[:3]))
    prerule_served = [s for s in sample_prerule if s in served]
    check("served: pre-rule rows in the sample", args.rows < 500 or prerule_served, len(prerule_served))
    gone, kept = [], []
    for i in with_files:
        s = shape(i, now)
        there = os.path.exists(os.path.join(mdir, s["slug"])), os.path.exists(os.path.join(adir, f"{s['slug']}.jpg"))
        if s["slug"] == pinned:
            continue
        should = s["_kind"] == "running" or s["_age"] == "young"
        if there != (should, should) and not (s["_kind"] == "running" and s["_days"] > 4):   # a running row's old files: the mtime sweep, as on main at 30 d
            (kept if should else gone).append((s["slug"], s["_kind"], s["_age"], there))
    check("files: rows past big lost media + avatar", not gone, (len(gone), gone[:3]))
    check("files: rows under big kept them", not kept, (len(kept), kept[:3]))
    check("files: media-cache keeps its own TTL", sorted(os.listdir(croot)) == ["alive.json"], os.listdir(croot))
    g = mg._Gallery("cachehit0")
    check("files: a live entry still hits past big, its row's report says none",
          g.from_cache("alive") and g.images == [{"n": 0}] and os.path.isfile(os.path.join(g.dir, "0.jpg")) and mg.public_view(pinned)["status"] == "none", pinned)
    fives = [r for r in reqs if r["s"] >= 500 or r["s"] == 0]
    check("load: no 5xx, no connection error", reqs and not fives, (len(fives), fives[:3]))
    during = [r for r in reqs if run_t0 <= r["t0"] <= run_t1]
    check("load: traffic really ran during retention", len(during) > 50 and any(r["k"] == "scan" for r in during), len(during))
    if vac:
        vac_scans = [r for r in reqs if r["k"] == "scan" and r["t0"] < vac["t1"] and r["t1"] > vac["t0"]]
        check("load: a scan insert overlapping VACUUM is stored (a VACUUM under 1 s may overlap none)", all(r["s"] == 200 for r in vac_scans) and (vac_scans or vac["t1"] - vac["t0"] < 1), len(vac_scans))
    vac_full_scans = [r for r in reqs if r["k"] == "scan" and r["t0"] < vac_full["t1"] and r["t1"] > vac_full["t0"]]
    check("load: scans overlapping the worst VACUUM are stored", (vac_full_scans or vac_full["t1"] - vac_full["t0"] < 1) and all(r["s"] == 200 and r["slug"] in inserted for r in vac_full_scans), len(vac_full_scans))
    bytes_settled = public_app._db_bytes()
    check("bytes: retention shrinks the DB and the WAL is gone", args.rows < 500 or bytes_settled < bytes_seeded / 2 and not os.path.getsize(db.DB_PATH + "-wal"), (bytes_seeded, bytes_settled))
    check("idempotent: a second run touches 0 rows", (n2["trimmed"], n2["summary"], n2["corrupt"], n2["errors"], n3["trimmed"], n3["summary"]) == (0, 0, 0, 0, 0, 0), (n2, n3))
    check("idempotent: the table is identical", d1 == d2)
    check("run: no row raised", n1 and not n1["errors"], n1 and n1["errors"])
    check("run: one log line, no handle", sum(e.startswith("retention ") for e in events) == 3 and not any(f"h{i}" in e.split() for e in events for i in (0, 1)), events)
    check("nothing left loopback", not outside, outside[:3])

    pct = lambda kind, a, b: p95([r["t1"] - r["t0"] for r in reqs if r["k"] == kind and a <= r["t0"] <= b])
    first = min(r["t0"] for r in reqs) if reqs else 0
    report = {"rows": args.rows, "kinds": sizes, "tiers": tiers, "inserts": len(inserted), "requests": len(reqs), "seed_s": round(seed_s, 1),
              "retention_s": round(run_t1 - run_t0, 2), "vacuum_s": round(vac["t1"] - vac["t0"], 2) if vac else None,
              "db_bytes": {"seeded": bytes_seeded, "right_after_run": bytes_after, "settled": bytes_settled},
              "worst_vacuum": {"secs": round(vac_full["t1"] - vac_full["t0"], 2), "bytes_before": vac_full["bytes"], "bytes_after": vac_full["after"], "scans_overlapping": len(vac_full_scans),
                               "their_max_s": round(max((r["t1"] - r["t0"] for r in vac_full_scans), default=0), 2)}, "first_run": {k: v for k, v in (n1 or {}).items() if k != "slugs"},
              "files_slugs": len((n1 or {}).get("slugs") or []), "second_run": {k: v for k, v in n2.items() if k != "slugs"},
              "second_run_s": events[-2].split("secs=")[-1] if len(events) > 1 else None, "p95_s": {
                  k: {"before": pct(k, first, run_t0), "during": pct(k, run_t0, run_t1), "after": pct(k, run_t1, 1e12)} for k in ("result", "profile", "media", "avatar", "scan")},
              "max_s_during": max((r["t1"] - r["t0"] for r in during), default=None), "statuses": collections.Counter(str(r["s"]) for r in reqs),
              "events": events, "checks": checks, "bypasses": "CSE, DeepSeek, leakshaven: app/tests wire stubs; profile pages: fake urlopen; media gathering off; limiters widened"}
    with open(os.path.join(args.out, "report.json"), "w") as fh:
        json.dump(report, fh, indent=1, default=dict)
    print(json.dumps({k: report[k] for k in ("rows", "tiers", "inserts", "requests", "retention_s", "vacuum_s", "worst_vacuum", "db_bytes", "p95_s", "max_s_during", "statuses")}, default=dict), flush=True)
    srv.shutdown()
    up.shutdown()
    lsv.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    os.remove(req_log)    # counts are in report.json; it can be GBs
    sys.exit(0 if all(checks.values()) else 1)


def shape_kind(i):
    """shape()'s kind, without building the row."""
    rng = random.Random(i)
    rng.choice(("young", "mid", "mid", "old", "old", "old"))
    roll = rng.random()
    return "prerule" if .055 <= roll < .065 else None


if __name__ == "__main__":
    main()

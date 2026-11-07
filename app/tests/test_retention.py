"""Retention (db.retain_scans, public_app.run_retention): the tiers on the real DB functions and what the real Handler serves
afterwards. Mass + concurrency: tools/retention_proof.py. All data synthetic."""
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import chat_proxy
import db
import media_gather as mg
import public_app
import ratelimit
import test_thumb_sheet
import thumb_sheet

MEGA = [{"url": "https://s.leakshaven.com/AAA", "host": "leakshaven.com", "via": "leakshaven.com", "title": "x", "status": "live"}]
HITS = [{"domain": "a.example", "url": "https://a.example/1", "occurrences": 5, "live": True},
        {"domain": "b.example", "url": "https://b.example/1", "occurrences": 9, "live": True},
        {"domain": "a.example", "url": "https://a.example/2", "occurrences": 6, "live": True},
        {"domain": "c.example", "url": "https://c.example/1", "live": True}]
BIG = {"images": ["https://t.example/1.jpg"], "results": [{"link": "https://g.example/1", "domain": "g.example", "title": "t", "thumb": None}],
       "gallery": [{"u": 1}], "img_meta": {"a": 1}, "excluded": ["x"]}
SMALL = {"mega": MEGA, "cse_sites": [{"d": 1}], "mega_key": "k", "scan_key": "sk", "reused_from": "abcdefgh"}
FOREVER = {"google_total": 1240, "socials": {"instagram": "mira"}, "aliases": {"declared": ["h"], "discovered": [], "socials": []},
           "slugs": ["s"], "top_leaks": [{"u": 1}], "quote": {"p": 1}, "n_leaks": 3, "n_media": 2, "n_hosting": 1, "n_sites": 4, "mega_ok": True,
           "accepted_urls": ["https://a.example/1"], "links_by_domain": {"a.example": ["u"]}, "removed_urls": ["u2"], "as_of": "2020-01-01T00:00:00Z",
           "a_future_field": {"keep": "me"}}
PROFILE = {"display_name": "Mira", "avatar": True, "bio": "b"}
SHEET_THUMB = "https://encrypted-tbn0.gstatic.com/images?q=tbn:"


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.object(db, "DB_PATH", os.path.join(self.tmp.name, "t.db")),
                  mock.patch.dict(os.environ, DATA_DIR=self.tmp.name),
                  mock.patch.object(public_app, "RESULT_LIMITER", ratelimit.Limiter(rate_per_min=10000, burst=1000, max_concurrent=100))):
            p.start()
            self.addCleanup(p.stop)
        db.init_db()

    def seed(self, days, hits=HITS, status="complete", level="low", extra="default", **cols):
        ex = {**BIG, **SMALL, **FOREVER, "profile": PROFILE} if extra == "default" else extra
        slug = db.insert_scan(hits, handle="h", level=level, platform="onlyfans.com", status=status,
                              extra=ex if isinstance(ex, dict) else None, client_ip_hash="ip")
        with db._db() as c:
            c.execute("UPDATE scans SET created_at=?, verify_code='v', verify_platform='p' WHERE slug=?", (ago(days), slug))
            if not isinstance(ex, dict):
                c.execute("UPDATE scans SET extra_json=? WHERE slug=?", (ex, slug))
        return slug

    def raw(self, slug):
        with db._db() as c:
            return dict(c.execute("SELECT * FROM scans WHERE slug=?", (slug,)).fetchone())

    def run_tiers(self):
        return db.retain_scans(3, 30, repair=public_app.off_row)


class TestTiers(Base):
    def test_full_under_big_days(self):
        s = self.seed(2.9)
        before = self.raw(s)
        n = self.run_tiers()
        self.assertEqual((n["trimmed"], n["summary"], n["slugs"]), (0, 0, []))
        self.assertEqual(self.raw(s), before)

    def test_trimmed(self):
        s = self.seed(3.1)
        before, n = self.raw(s), self.run_tiers()
        self.assertEqual((n["trimmed"], n["summary"], n["slugs"]), (1, 0, [s]))
        r = self.raw(s)
        ex = json.loads(r["extra_json"])
        self.assertEqual(r["retention"], "trimmed")
        self.assertEqual(ex, {**SMALL, **FOREVER, "profile": {**PROFILE, "avatar": False}})
        self.assertEqual(r["result_json"], before["result_json"])
        for k in set(before) - {"extra_json", "retention"}:
            self.assertEqual(r[k], before[k], k)

    def test_summary_straight_from_full(self):
        s = self.seed(30.1)
        before, n = self.raw(s), self.run_tiers()
        self.assertEqual((n["trimmed"], n["summary"], n["slugs"]), (0, 1, [s]))
        r = self.raw(s)
        self.assertEqual(json.loads(r["extra_json"]), {**FOREVER, "profile": {**PROFILE, "avatar": False}, "top_domains": [
            {"domain": "a.example", "n": 11}, {"domain": "b.example", "n": 9}, {"domain": "c.example", "n": 1}]})
        self.assertEqual((r["result_json"], r["retention"]), ("[]", "summary"))
        self.assertEqual((r["client_ip_hash"], r["verify_code"], r["verify_platform"]), (None, None, None))
        for k in ("slug", "level", "platform", "handle", "created_at", "status", "hit_count", "domain_count", "ownership_verified"):
            self.assertEqual(r[k], before[k], k)

    def test_trimmed_then_summary_same_as_straight(self):
        a, b = self.seed(10), self.seed(30.1)
        self.run_tiers()
        with db._db() as c:
            c.execute("UPDATE scans SET created_at=? WHERE slug=?", (ago(31), a))
        n = self.run_tiers()
        self.assertEqual((n["summary"], n["slugs"]), (1, []))    # its files went at 'trimmed'
        self.assertEqual(self.raw(a)["extra_json"], self.raw(b)["extra_json"])

    def test_idempotent_and_reads_no_old_row(self):
        for d in (1, 10, 40):
            self.seed(d)
        self.run_tiers()
        with db._db() as c:
            before = [dict(r) for r in c.execute("SELECT * FROM scans ORDER BY slug")]
        with mock.patch.object(db, "_retain_one", side_effect=AssertionError("touched")):
            n = self.run_tiers()
        self.assertEqual((n["trimmed"], n["summary"], n["errors"]), (0, 0, 0))
        with db._db() as c:
            self.assertEqual([dict(r) for r in c.execute("SELECT * FROM scans ORDER BY slug")], before)

    def test_running_skipped(self):
        s = self.seed(40, status="running")
        before = self.raw(s)
        self.assertEqual(self.run_tiers()["summary"], 0)
        self.assertEqual(self.raw(s), before)

    def test_null_and_corrupt_extra_never_raise(self):
        null_t, null_s = self.seed(10, extra=None), self.seed(40, extra=None)
        bad_t, bad_s = self.seed(10, extra="{not json"), self.seed(40, extra="[1,2")
        arr = self.seed(40, extra="[]")
        n = self.run_tiers()
        self.assertEqual((n["trimmed"], n["summary"], n["corrupt"], n["errors"]), (2, 3, 3, 0))
        self.assertIsNone(self.raw(null_t)["extra_json"])
        self.assertEqual(json.loads(self.raw(null_s)["extra_json"])["top_domains"][0]["domain"], "a.example")
        self.assertEqual(self.raw(bad_t)["extra_json"], "{not json")
        self.assertEqual((self.raw(bad_s)["extra_json"], self.raw(bad_s)["result_json"]), ("[1,2", "[]"))
        self.assertEqual(self.raw(arr)["extra_json"], "[]")
        self.assertEqual(self.run_tiers()["corrupt"], 0)         # marked: not read again

    def test_corrupt_result_json(self):
        t, s = self.seed(10), self.seed(40)
        with db._db() as c:
            c.execute("UPDATE scans SET result_json='{bad' WHERE slug IN (?,?)", (t, s))
        n = self.run_tiers()
        self.assertEqual(n["errors"], 0)
        self.assertEqual(self.raw(t)["result_json"], "{bad")
        self.assertEqual(self.raw(s)["result_json"], "[]")
        self.assertEqual(json.loads(self.raw(s)["extra_json"])["top_domains"], [])

    def test_a_row_that_raises_waits_for_the_next_run(self):
        a, b = self.seed(10), self.seed(10)
        real, boom = db.retain_row, {a}

        def flaky(extra, hits, tier):
            if boom:
                boom.clear()
                raise ValueError("x")
            return real(extra, hits, tier)
        with mock.patch.object(db, "retain_row", flaky):
            n = self.run_tiers()
        self.assertEqual((n["trimmed"], n["errors"]), (1, 1))
        self.assertEqual(self.run_tiers()["trimmed"], 1)
        self.assertEqual({self.raw(a)["retention"], self.raw(b)["retention"]}, {"trimmed"})

    def test_top_domains_cap_and_occurrence_rule(self):
        hits = [{"domain": f"d{i}.example", "occurrences": i + 1} for i in range(30)] + [{"domain": "x.example", "occurrences": True},
                {"domain": None}, "junk", {"domain": "y.example", "occurrences": -3}]
        top = db.top_domains(hits)
        self.assertEqual(len(top), 20)
        self.assertEqual(top[0], {"domain": "d29.example", "n": 30})
        self.assertEqual({t["n"] for t in db.top_domains(hits, 100) if t["domain"] in ("x.example", "y.example")}, {1})

    def test_migration_on_a_table_from_before(self):
        p = os.path.join(self.tmp.name, "old.db")
        import sqlite3
        c = sqlite3.connect(p)
        c.executescript(db._SCHEMA)
        c.execute("INSERT INTO scans (slug,handle,created_at,status,result_json) VALUES ('abcdefgh','h',?,'complete','[]')", (ago(5),))
        c.commit()
        c.close()
        db.init_db(p)
        db.init_db(p)
        self.assertEqual(db.get_scan("abcdefgh", path=p)["retention"], "full")
        self.assertEqual(db.retain_scans(3, 30, path=p)["trimmed"], 1)


class TestServing(Base):
    """The real Handler, before and after a run."""

    def setUp(self):
        super().setUp()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), public_app.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)

    def get(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=20)
        c.request("GET", path)
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, json.loads(body) if r.getheader("Content-Type", "").startswith("application/json") else body

    def files(self, slug):
        os.makedirs(os.path.join(mg.data_dir(), "media", slug), exist_ok=True)
        with open(os.path.join(mg.data_dir(), "media", slug, "0.jpg"), "wb") as fh:
            fh.write(b"jpg")
        with open(os.path.join(mg.data_dir(), "media", slug, "index.json"), "w") as fh:
            json.dump({"status": "ready", "images": [{"n": 0}]}, fh)
        os.makedirs(public_app._avatar_dir(), exist_ok=True)
        with open(os.path.join(public_app._avatar_dir(), f"{slug}.jpg"), "wb") as fh:
            fh.write(b"jpg")

    def test_each_tier_stays_200_counts_stand(self):
        young, mid, old, nothing = self.seed(1), self.seed(10), self.seed(40), self.seed(40, hits=[], status="empty")
        before = {s: self.get(f"/api/scan-result/{s}")[1] for s in (young, mid, old, nothing)}
        self.assertEqual(before[young]["retention"], "full")
        for s in (mid, old, nothing):
            self.files(s)
        public_app.run_retention()
        for s, tier in ((young, "full"), (mid, "trimmed"), (old, "summary"), (nothing, "summary")):
            st, r = self.get(f"/api/scan-result/{s}")
            self.assertEqual((st, r["retention"]), (200, tier))
            for k in ("hit_count", "domain_count", "google_total", "status", "handle", "platform", "created_at", "aliases", "socials"):
                self.assertEqual(r[k], before[s][k], (tier, k))
        mid_r, old_r = self.get(f"/api/scan-result/{mid}")[1], self.get(f"/api/scan-result/{old}")[1]
        self.assertEqual((mid_r["images"], mid_r["results"], mid_r["hits"]), ([], [], before[mid]["hits"]))
        self.assertEqual(mid_r["mega"], MEGA)
        self.assertEqual((old_r["hits"], old_r["mega"]), ([], []))
        self.assertEqual(old_r["top_domains"][0], {"domain": "a.example", "n": 11})
        self.assertFalse(old_r["profile"]["avatar"])

    def test_deep_audit_lists_download_at_every_tier(self):
        """retain_row keeps a deep row's lists for good, so the download must find them at each tier: real row shape on prod."""
        lists = {"accepted_urls": [f"https://a.example/{i}" for i in range(202)], "removed_urls": [f"https://r.example/{i}" for i in range(83)],
                 "n_accepted": 202, "n_removed": 83, "links_by_domain": {"a.example": ["https://a.example/0"]}}
        rows = {s: tier for s, tier in ((self.seed(1, level="deep", extra={**BIG, **SMALL, **lists}), "full"),
                                        (self.seed(10, level="deep", extra={**BIG, **SMALL, **lists}), "trimmed"),
                                        (self.seed(40, level="deep", extra={**BIG, **SMALL, **lists}), "summary"))}
        public_app.run_retention()
        for s, tier in rows.items():
            for which, key in (("accepted", "accepted_urls"), ("removed", "removed_urls")):
                st, body = self.get(f"/api/scan-links/{s}?set={which}")
                text = body.decode()
                self.assertEqual(st, 200, tier)
                self.assertIn(f"{len(lists[key])} URL(s)", text.splitlines()[0], tier)
                self.assertEqual([x for x in text.splitlines() if x.startswith("https://")], lists[key], tier)
            st, r = self.get(f"/api/scan-result/{s}")
            self.assertEqual((st, r["retention"], r["n_accepted"], r["n_removed"]), (200, tier, 202, 83))   # the report's buttons
            self.assertNotIn("accepted_urls", r)                                                            # counts only: the lists stay behind /api/scan-links
            self.assertNotIn("removed_urls", r)

    def test_audit_download_of_a_row_without_lists(self):
        st, body = self.get(f"/api/scan-links/{self.seed(1, extra={'google_total': 1})}?set=accepted")
        self.assertEqual(st, 200)
        self.assertIn("0 URL(s)", body.decode().splitlines()[0])
        self.assertEqual(self.get("/api/scan-links/nosuchslug1?set=accepted")[0], 404)

    def test_audit_download_holds_no_concurrency_slot(self):
        """It answered 429 for good after max_concurrent downloads from one address: allow() took a slot no one released."""
        s = self.seed(1, level="deep", extra={"accepted_urls": ["https://a.example/1"], "n_accepted": 1})
        with mock.patch.object(public_app, "RESULT_LIMITER", ratelimit.Limiter(rate_per_min=10000, burst=1000, max_concurrent=2)):
            self.assertEqual([self.get(f"/api/scan-links/{s}?set=accepted")[0] for _ in range(4)], [200] * 4)

    def test_files_and_answers_as_for_none(self):
        s, keep = self.seed(10), self.seed(1)
        self.files(s)
        self.files(keep)
        self.assertEqual(self.get(f"/api/avatar/{s}")[0], 200)
        public_app.run_retention()
        self.assertFalse(os.path.exists(os.path.join(mg.data_dir(), "media", s)))
        self.assertEqual(self.get(f"/api/avatar/{s}")[0], 404)
        self.assertEqual(self.get(f"/api/media/{s}/0.jpg")[0], 404)
        st, m = self.get(f"/api/media/{s}")
        self.assertEqual((st, m["status"], m["images"]), (200, "none", []))
        st, p = self.get(f"/api/profile/{s}")
        self.assertEqual((st, p["profile"]["avatar"], p["profile"]["display_name"]), (200, False, "Mira"))
        self.assertTrue(os.path.exists(os.path.join(mg.data_dir(), "media", keep)))
        self.assertEqual(self.get(f"/api/avatar/{keep}")[0], 200)

    def test_media_cache_and_orphans_go_at_big(self):
        self.assertEqual(mg.CACHE_TTL, 3 * 86400)
        croot, mroot = os.path.join(mg.data_dir(), "media-cache"), os.path.join(mg.data_dir(), "media")
        adir = public_app._avatar_dir()
        os.makedirs(croot)
        os.makedirs(adir, exist_ok=True)
        now = time.time()
        for name, age in (("keep", 2.9), ("stale", 3.1)):
            open(os.path.join(croot, name), "w").close()
            os.utime(os.path.join(croot, name), (now - age * 86400,) * 2)
        for name, age in (("orphan000", 3.1), ("young0000", 2.9)):
            os.makedirs(os.path.join(mroot, name))
            os.utime(os.path.join(mroot, name), (now - age * 86400,) * 2)
            open(os.path.join(adir, name + ".jpg"), "w").close()
            os.utime(os.path.join(adir, name + ".jpg"), (now - age * 86400,) * 2)
        public_app.run_retention()
        self.assertEqual(sorted(os.listdir(croot)), ["keep"])
        self.assertEqual(sorted(os.listdir(mroot)), ["young0000"])
        self.assertEqual(sorted(os.listdir(adir)), ["young0000.jpg"])

    def test_row_under_big_keeps_rendering(self):
        s = self.seed(2.9, extra={**BIG, "profile": PROFILE})
        self.files(s)
        d = os.path.join(mg.data_dir(), "media", s)
        os.utime(d, (time.time() - 2.9 * 86400,) * 2)
        public_app.run_retention()
        self.assertEqual(self.get(f"/api/media/{s}/0.jpg")[0], 200)
        self.assertEqual(self.get(f"/api/avatar/{s}")[0], 200)

    def test_live_media_cache_entry_keeps_its_photos_until_its_ttl(self):
        """The gather ends minutes after its row is stored: a sweep in between keeps the photos for the entry, and the next sweep takes them. Index gone must not restart their clock."""
        s = self.seed(3.01, extra={**BIG, "profile": PROFILE})
        self.files(s)
        croot, d = os.path.join(mg.data_dir(), "media-cache"), os.path.join(mg.data_dir(), "media", s)
        os.makedirs(croot)
        entry = os.path.join(croot, "onlyfans-mira.json")
        with open(entry, "w") as fh:
            json.dump({"ts": time.time() - 2.99 * 86400, "slug": s, "images": [{"n": 0}]}, fh)
        os.utime(entry, (time.time() - 2.99 * 86400,) * 2)
        born = time.time() - 3.01 * 86400
        os.utime(d, (born, born))
        public_app.run_retention()
        self.assertEqual(self.get(f"/api/media/{s}")[1]["status"], "none")      # the report: as for any expired row
        self.assertEqual(self.get(f"/api/avatar/{s}")[0], 404)
        self.assertAlmostEqual(os.path.getmtime(d), born, delta=2)              # the clock: as it was
        g = mg._Gallery("repeat000")
        self.assertTrue(g.from_cache("onlyfans-mira"))                          # the repeat scan: a hit, no gather
        self.assertEqual((g.images, os.path.isfile(os.path.join(g.dir, "0.jpg"))), ([{"n": 0}], True))
        with open(entry, "w") as fh:
            json.dump({"ts": time.time() - mg.CACHE_TTL - 60, "slug": s, "images": [{"n": 0}]}, fh)
        os.utime(entry, (time.time() - mg.CACHE_TTL - 60,) * 2)
        public_app.run_retention()
        self.assertFalse(os.path.exists(d))                                     # expired: the next run takes them
        self.assertFalse(os.path.exists(entry))
        self.assertTrue(os.path.isfile(os.path.join(g.dir, "0.jpg")))           # the repeat's own copy stays, from its own scan

    def test_sheets_are_swept_with_no_sheet_written(self):
        d = thumb_sheet.cache_dir()
        os.makedirs(d)
        now = time.time()
        ages = {"old.full": 3.1 * 86400, "young.full": 2.9 * 86400, "old.gaps": 301, "young.gaps": 200, "x.1.tmp": 301, "y.1.tmp": 200}
        for name, age in ages.items():
            open(os.path.join(d, name), "w").close()
            os.utime(os.path.join(d, name), (now - age,) * 2)
        with mock.patch.object(public_app, "_event") as log:
            public_app.run_retention()
        self.assertEqual(sorted(os.listdir(d)), ["y.1.tmp", "young.full", "young.gaps"])
        self.assertIn(" files=3 ", log.call_args_list[0].args[0])
        self.assertEqual(thumb_sheet.sweep(), 0)

    def test_sweep_without_a_dir(self):
        self.assertEqual(thumb_sheet.sweep(), 0)

    def test_sweep_is_bounded_by_bytes_oldest_first(self):
        d = thumb_sheet.cache_dir()
        os.makedirs(d)
        now = time.time()
        for name, age in (("a.full", 300), ("b.full", 200), ("c.full", 100)):
            with open(os.path.join(d, name), "wb") as fh:
                fh.write(b"x" * 10)
            os.utime(os.path.join(d, name), (now - age,) * 2)
        with mock.patch.object(thumb_sheet, "CACHE_MAX_BYTES", 15):
            self.assertEqual(thumb_sheet.sweep(), 2)
        self.assertEqual(os.listdir(d), ["c.full"])

    def sheet_row(self, days):
        return self.seed(days, extra={"images": [SHEET_THUMB], "results": []})

    def test_a_sheet_lives_as_long_as_its_row_and_a_rebuild_adds_nothing(self):
        """Stamped with the row's age, not the build's: a sheet first asked for at 2.9 d goes with its row."""
        up = test_thumb_sheet.Up()
        s = self.sheet_row(2.9)
        with mock.patch.object(public_app, "_THUMB_OPENER", up), mock.patch.object(thumb_sheet, "LIMITER", ratelimit.Limiter(rate_per_min=6000, burst=1000, max_concurrent=1000)):
            st, body = self.get(f"/api/thumb-sheet/{s}")
            self.assertEqual((st, test_thumb_sheet.parse(body)[0]["dead"]), (200, []))
            self.assertEqual(len(up.calls), 1)
            f = os.path.join(thumb_sheet.cache_dir(), os.listdir(thumb_sheet.cache_dir())[0])
            self.assertAlmostEqual(time.time() - os.path.getmtime(f), 2.9 * 86400, delta=60)
            public_app.run_retention()
            self.assertTrue(os.path.exists(f))                                  # under big: kept, and served from disk
            self.assertEqual(self.get(f"/api/thumb-sheet/{s}")[0], 200)
            self.assertEqual(len(up.calls), 1)
            late = self.sheet_row(3.01)                                         # not trimmed yet: past big all the same
            os.remove(f)
            self.assertEqual(self.get(f"/api/thumb-sheet/{late}")[0], 404)      # the client's per-thumb path
            self.assertEqual(os.listdir(thumb_sheet.cache_dir()), [])

    def test_a_sweep_racing_builds_never_breaks_a_sheet(self):
        up, bad, done = test_thumb_sheet.Up(), [], []
        lists = [[f"{SHEET_THUMB}{i}"] for i in range(8)]
        stop = threading.Event()

        def sweeper():
            while not stop.is_set():
                thumb_sheet.sweep()

        def builder(i):
            for n in range(40):
                urls = lists[(i + n) % len(lists)]
                got = thumb_sheet.sheet(urls, up, 10 ** 6, time.time() - 2 * 86400)
                if not got or test_thumb_sheet.parse(got[0])[0]["cells"][0][0] != urls[0]:
                    bad.append(urls)
            done.append(i)
        with mock.patch.object(thumb_sheet, "CACHE_MAX_BYTES", 50):    # next to every file over the bound: the sweep is always busy
            t = threading.Thread(target=sweeper)
            t.start()
            ts = [threading.Thread(target=builder, args=(i,)) for i in range(4)]
            for x in ts:
                x.start()
            for x in ts:
                x.join()
            stop.set()
            t.join()
        self.assertEqual((bad, sorted(done)), ([], [0, 1, 2, 3]))

    def test_pre_rule_row_keeps_what_was_served(self):
        """A row stored before the aggregator rule: off_row recounts from mega + results, which go. What was served stays."""
        pack = [{"domain": "leakshaven.com", "url": "https://leakshaven.com/p", "occurrences": 2}]
        ex = {**BIG, **SMALL, **FOREVER, "profile": PROFILE, "results": BIG["results"] + [
            {"link": "https://leakshaven.com/r", "domain": "leakshaven.com", "title": "t", "thumb": None}]}
        mid, old = self.seed(10, hits=HITS + pack, extra=ex), self.seed(40, hits=HITS + pack, extra=ex)
        before = {s: self.get(f"/api/scan-result/{s}")[1] for s in (mid, old)}
        self.assertEqual(before[mid]["hit_count"], len(HITS))    # the repair is in play
        self.assertLess(before[mid]["google_total"], FOREVER["google_total"])
        self.assertEqual(self.raw(mid)["hit_count"], len(HITS) + 1)
        public_app.run_retention()
        for s in (mid, old):
            r = self.get(f"/api/scan-result/{s}")[1]
            for k in ("hit_count", "domain_count", "google_total", "status"):
                self.assertEqual(r[k], before[s][k], k)
        self.assertEqual(self.raw(mid)["hit_count"], len(HITS))  # baked
        self.assertEqual(self.get(f"/api/scan-result/{mid}")[1]["hits"], before[mid]["hits"])
        self.assertNotIn("leakshaven.com", [t["domain"] for t in self.get(f"/api/scan-result/{old}")[1]["top_domains"]])

    def test_a_summary_row_of_nothing_never_zeroes_a_hit_row(self):
        s = self.seed(40)
        n = self.raw(s)["hit_count"]
        public_app.run_retention()
        public_app.run_retention()
        self.assertEqual(self.get(f"/api/scan-result/{s}")[1]["hit_count"], n)
        self.assertEqual(self.raw(s)["status"], "complete")

    def test_chat_context_of_a_summary_row_is_not_no_leaks(self):
        s = self.seed(40)
        public_app.run_retention()
        ctx = chat_proxy.scan_summary(public_app._summary_hits(public_app.scan_row(s)))
        self.assertNotIn("no public leaks", ctx)
        self.assertIn("a.example (11 matches)", ctx)

    def test_run_never_raises_and_logs_one_line_without_handles(self):
        self.seed(10)
        lines = []
        with mock.patch.object(public_app, "_event", lines.append):
            self.assertEqual(public_app.run_retention()["trimmed"], 1)
            with mock.patch.object(db, "retain_scans", side_effect=RuntimeError("boom")):
                self.assertIsNone(public_app.run_retention())
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[0], r"^retention trimmed=1 summary=0 corrupt=0 errors=0 files=\d+ db_before=\d+ db_after=\d+ secs=")
        self.assertIn("retention failed: RuntimeError", lines[1])
        self.assertNotIn("handle", "".join(lines))

    def test_vacuum_only_after_a_run_that_changed_rows(self):
        with mock.patch.object(db, "vacuum") as v:
            public_app.run_retention()
            v.assert_not_called()
            self.seed(10)
            public_app.run_retention()
            v.assert_called_once()
            public_app.run_retention()
            v.assert_called_once()

    def test_reuse_lookup_never_sees_a_trimmed_row(self):
        self.assertGreaterEqual(public_app.RETAIN_BIG_DAYS * 86400, public_app.SCAN_REUSE_TTL)


if __name__ == "__main__":
    unittest.main()

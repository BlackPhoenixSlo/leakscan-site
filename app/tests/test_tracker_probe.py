"""Origin probe + Probe state + the daily pass + `tracker report` (Seam 5). Probes go to tracker_stub_fetch or a
loopback HTTP server; no real target is ever fetched. All data synthetic."""
import threading
import time
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tracker_fixture import Base, tdb, tracker_probe, tracker_scheduler, tracker_stub_fetch
import tracker_report
import tracker_view

A, B, C = "https://leaksite.example/mia_vale/1", "https://tube.example/v/mia_vale", "https://forum.example/t/miavale"


class TestRule(Base):
    def probe(self, *answers, day0=2):
        for i, a in enumerate(answers):
            self.clock(f"2026-11-{day0 + i:02d}T05:00:00Z")
            self.answers({"*": a})
            tracker_probe.run([self.w])

    def setUp(self):
        super().setUp()
        self.w = self.watch(self.tenant())
        self.l = self.leak(self.w, A)

    def test_two_dead_in_a_row_with_blocked_and_unknown_between(self):
        self.probe(200, 404, 403, 0)
        st = self.state(self.l)
        self.assertEqual((st["origin_status"], st["consecutive_dead"], st["last_status"]), ("live", 1, "unknown"))
        self.assertEqual(st["dead_since"], "2026-11-03T05:00:00Z")
        self.probe(410, day0=6)
        st = self.state(self.l)
        self.assertEqual((st["origin_status"], st["consecutive_dead"], st["probes"], st["first_dead"]), ("gone", 2, 5, 1))
        gone = self.events(self.l, "status")[-1]["data"]
        self.assertEqual(gone, {"from": "live", "to": "gone", "dead_since": "2026-11-03T05:00:00Z"})

    def test_dead_since_set_kept_cleared_and_never_on_a_single_dead(self):
        self.probe(404)
        self.assertEqual(self.state(self.l)["dead_since"], "2026-11-02T05:00:00Z")
        self.assertEqual(self.events(self.l, "status"), [])
        self.probe(503, day0=3)
        self.assertEqual(self.state(self.l)["dead_since"], "2026-11-02T05:00:00Z")
        self.probe(200, day0=4)
        st = self.state(self.l)
        self.assertEqual((st["dead_since"], st["consecutive_dead"], st["flaps"]), (None, 0, 1))
        self.assertEqual([e["data"]["to"] for e in self.events(self.l, "status")], ["live"])

    def test_removal_pages_read_dead(self):
        for body in ("<title>Page not found</title>", "<title>x</title><h1>This video has been removed</h1>",
                     "<title>Video no longer available</title>"):
            self.assertEqual(tracker_probe.classify(lambda u: (200, body), A), "dead", body)
        self.assertEqual(tracker_probe.classify(lambda u: (200, "<title>Mia Vale gallery</title>"), A), "live")
        self.assertEqual(tracker_probe.classify(lambda u: (200, "<title>Just a moment...</title>"), A), "blocked")
        self.assertEqual(tracker_probe.classify(lambda u: 1 / 0, A), "unknown")
        self.assertEqual(tracker_probe.classify(lambda u: (200, ""), A + ".mp4"), "unknown")

    def test_came_back(self):
        self.probe(200, 404, 404, 200)
        st = self.state(self.l)
        self.assertEqual(st["origin_status"], "live")
        self.assertEqual([(e["data"]["from"], e["data"]["to"]) for e in self.events(self.l, "status")],
                         [(None, "live"), ("live", "gone"), ("gone", "live")])
        self.assertEqual(self.events(self.l, "status")[-1]["at"], "2026-11-05T05:00:00Z")
        self.assertEqual((st["first_dead"], st["flaps"]), (1, 0))

    def test_one_probe_per_leak_per_utc_day(self):
        self.answers({"*": 404})
        tracker_probe.run([self.w])
        self.clock("2026-11-02T23:59:00Z")
        tracker_probe.run([self.w])
        self.assertEqual(self.state(self.l)["consecutive_dead"], 1)
        self.assertEqual(len(tracker_stub_fetch.CALLS), 1)

    def test_link_only_leaks_are_never_probed(self):
        self.leak(self.w, "https://mega.nz/folder/abc#k", kind="filehost")
        tracker_probe.run([self.w])
        self.assertEqual(tracker_stub_fetch.CALLS, [A])


class TestDaily(Base):
    def test_one_fetch_per_url_key_across_tenants(self):
        w1, w2 = self.watch(self.tenant("A")), self.watch(self.tenant("B"))
        l1, l2 = self.leak(w1, A), self.leak(w2, A + "/")
        self.leak(w2, B)
        r = tracker_scheduler.daily_pass()
        key = tracker_probe.rules.url_key
        self.assertEqual(sorted(map(key, tracker_stub_fetch.CALLS)), sorted([key(A), key(B)]))
        self.assertEqual((r["keys"], r["fetched"]), (2, 2))
        self.assertEqual(self.state(l1)["last_status"], self.state(l2)["last_status"])
        self.assertEqual({x["outcome"] for x in self.rows("SELECT outcome FROM daily_scans")}, {"ok"})

    def test_a_later_tenant_reuses_the_days_probe(self):
        wa = self.watch(self.tenant("A"))
        la = self.leak(wa, A)
        self.answers({"*": 404})
        tracker_probe.run([wa])
        self.clock("2026-11-02T09:00:00Z")
        self.answers({"*": 200})
        wb = self.watch(self.tenant("B"))
        lb = self.leak(wb, A + "/")
        r = tracker_probe.run([wb])
        self.assertEqual(tracker_stub_fetch.CALLS, [A])
        self.assertEqual((r["fetched"], r["reused"]), (0, 1))
        self.assertEqual((self.state(lb)["last_status"], self.state(lb)["consecutive_dead"]), ("dead", 1))
        self.assertEqual(self.state(la)["last_status"], "dead")

    def test_a_restart_mid_pass_fetches_no_url_key_twice(self):
        w = self.watch(self.tenant())
        for u in (A, B, C):
            self.leak(w, u)
        with tdb.db() as c:
            c.execute("INSERT INTO daily_scans (watch_id, day, started_at) VALUES (?,?,?)", (w, "2026-11-02", "2026-11-02T04:00:00Z"))
        tracker_probe.apply(tracker_probe.rules.url_key(A), "live")
        tracker_probe._inflight.clear()
        tracker_scheduler.daily_pass()
        self.assertEqual(tracker_stub_fetch.CALLS, [])
        self.clock("2026-11-02T06:01:00Z")
        tracker_scheduler.daily_pass()
        tracker_scheduler.daily_pass()
        self.assertEqual(sorted(tracker_stub_fetch.CALLS), sorted([B, C]))
        self.assertEqual(self.rows("SELECT outcome FROM daily_scans")[0]["outcome"], "ok")
        self.clock("2026-11-03T04:00:00Z")
        tracker_scheduler.daily_pass()
        self.assertEqual(len(tracker_stub_fetch.CALLS), 5)

    def test_an_unfinished_row_from_an_earlier_day_finishes_failed(self):
        w = self.watch(self.tenant())
        with tdb.db() as c:
            c.execute("INSERT INTO daily_scans (watch_id, day, started_at) VALUES (?,?,?)", (w, "2026-11-01", tdb.now()))
        tracker_scheduler.daily_pass()
        self.assertEqual([(r["day"], r["outcome"]) for r in self.rows("SELECT * FROM daily_scans ORDER BY day")],
                         [("2026-11-01", "failed"), ("2026-11-02", "ok")])

    def test_paused_watch_skipped_rows_readable(self):
        w = self.watch(self.tenant(), paused=True, paused_at=self.T0)
        l = self.leak(w, A)
        tracker_scheduler.daily_pass()
        self.assertEqual(tracker_stub_fetch.CALLS, [])
        self.assertEqual(self.rows("SELECT * FROM daily_scans"), [])
        self.assertIsNone(self.state(l))
        self.assertEqual(len(self.rows("SELECT * FROM leaks WHERE watch_id = ?", w)), 1)

    def test_nothing_before_daily_at_and_nothing_without_watches(self):
        self.clock("2026-11-02T03:59:00Z")
        self.assertIsNone(tracker_scheduler.daily_pass())
        self.clock("2026-11-02T04:00:00Z")
        r = tracker_scheduler.daily_pass()
        self.assertEqual((r["seeded"], r["probed"], r["fetched"]), (0, 0, 0))
        self.assertEqual(self.rows("SELECT * FROM daily_scans"), [])

    def test_explicit_at_drives_the_clock(self):
        w = self.watch(self.tenant())
        self.leak(w, A)
        tracker_scheduler.daily_pass("2026-11-09T06:00:00Z")
        self.assertEqual(self.rows("SELECT day FROM daily_scans")[0]["day"], "2026-11-09")
        self.assertEqual(tdb.now(), self.T0)
        self.assertEqual(tracker_view.next_check_at(tdb.parse("2026-11-09T06:00:00Z")), "2026-11-10T04:00:00Z")

    def test_daily_at_env_and_its_fallback(self):
        with mock.patch.dict("os.environ", TRACKER_DAILY_AT="06:00"):
            self.assertIsNone(tracker_scheduler.daily_pass("2026-11-09T05:59:00Z"))
            self.assertIsNotNone(tracker_scheduler.daily_pass("2026-11-09T06:00:00Z"))
            self.assertEqual(tracker_view.next_check_at(tdb.parse("2026-11-09T05:00:00Z")), "2026-11-09T06:00:00Z")
        for bad in ("4am", "25:00", "04:60", ""):
            with mock.patch.dict("os.environ", TRACKER_DAILY_AT=bad):
                self.assertIsNone(tracker_scheduler.daily_pass("2026-11-10T03:59:00Z"), bad)
                self.assertIsNotNone(tracker_scheduler.daily_pass("2026-11-10T04:00:00Z"), bad)
                self.assertEqual(tracker_view.next_check_at(tdb.parse("2026-11-10T03:00:00Z")), "2026-11-10T04:00:00Z")


class TestReport(Base):
    def test_flap_counts_with_denominator_per_tenant(self):
        ta, tb = self.tenant("A"), self.tenant("B")
        w = self.watch(ta)
        self.watch(tb)
        la, lb, lc = self.leak(w, A), self.leak(w, B), self.leak(w, C)
        with tdb.db() as c:
            c.execute("INSERT INTO pending_hits (watch_id, url_key, url, title, source, seen_at) VALUES "
                      "(?,?,?,?,?,?)", (w, "p.example/x", "https://p.example/x", "Mia Vale", "google_web", tdb.now()))
        script = {A: [200, 404, 200, 404, 404], B: [200, 404, 503, 503, 0], C: [200, 200, 404, 200, 0]}
        for i in range(5):
            self.clock(f"2026-11-{2 + i:02d}T05:00:00Z")
            self.answers({u: s[i] for u, s in script.items()})
            tracker_probe.run([w])
        # A: first-dead x2 (one flap, one gone); B: first-dead still unsettled; C: first-dead, flap
        n = tracker_report.counts(ta)
        self.assertEqual((n["probes"], n["first_dead"], n["flaps"], n["settled"]), (15, 4, 2, 3))
        self.assertEqual(n["pills"], {"live": 2, "cached": 1, "gone": 0, "listed": 0, "not_checked": 0})
        self.assertEqual((n["admitted"], n["pending"]), (3, 1))
        out = tracker_report.text()
        self.assertIn("flap rate 2/3 = 66.7%", out)
        self.assertIn("seed admitted 3  pending 1", out)
        block_b = out.split(f"tenant {tb}")[1]
        self.assertIn("probes 0  first_dead 0  flaps 0", block_b)
        self.assertIn("flap rate 0/0 (no settled observations)", block_b)
        self.assertNotIn("%", block_b)


class _Upstream(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        p, port = self.path, self.server.server_address[1]
        if p.startswith("/hop/"):
            n = int(p.split("/")[2])
            self.send_response(302)
            self.send_header("Location", f"/hop/{n - 1}" if n > 1 else "/page")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif p == "/to-private":
            self.send_response(301)
            self.send_header("Location", f"http://private.test:{port}/page")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif p.startswith("/drip-"):
            try:
                if p == "/drip-head":
                    self.wfile.write(b"HTTP/1.1 200 OK\r\nX-Slow: ")
                else:
                    self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n<title>")
                for _ in range(40):
                    self.wfile.flush()
                    time.sleep(0.25)
                    self.wfile.write(b"a")
            except OSError:
                pass
            self.close_connection = True
        elif p == "/big":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<title>big</title>" + b"x" * (1024 * 1024))
        else:
            b = b"<html><title>ok</title></html>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)


class TestBounds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
        cls.srv.daemon_threads = True
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.port = cls.srv.server_address[1]
        hosts = {"public.test": "127.0.0.1", "private.test": "10.0.0.7"}
        cls.resolve = staticmethod(lambda h, p: [hosts.get(h, "127.0.0.1")])
        # the loopback stub plays a public host; every other address goes through the real check
        cls.allow = staticmethod(lambda ip: ip == "127.0.0.1" or tracker_probe.ip_ok(ip))

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def url(self, path, host="public.test"):
        return f"http://{host}:{self.port}{path}"

    def fetcher(self, **kw):
        return tracker_probe.Fetcher(resolve=self.resolve, allow=self.allow, **kw)

    def test_private_and_loopback_refused_after_dns(self):
        self.assertEqual(tracker_probe.Fetcher()(f"http://127.0.0.1:{self.port}/page"), (0, ""))
        self.assertEqual(tracker_probe.Fetcher(resolve=self.resolve)(self.url("/page")), (0, ""))
        self.assertEqual(self.fetcher()(self.url("/page", "private.test")), (0, ""))
        for ip in ("127.0.0.1", "10.1.2.3", "192.168.0.1", "169.254.169.254", "::1", "fe80::1", "::ffff:10.0.0.1",
                   "0.0.0.0", "100.64.0.1", "64:ff9b::a00:1", "64:ff9b::5db8:d822", "64:ff9b:1::5db8:d822",
                   "2002:a00:1::1", "2002:5db8:d822::1", "2001:0:4136:e378:8000:63bf:3fff:fdd2"):
            self.assertFalse(tracker_probe.ip_ok(ip), ip)
        for ip in ("93.184.216.34", "2606:4700:4700::1111"):
            self.assertTrue(tracker_probe.ip_ok(ip), ip)

    def test_private_redirect_refused(self):
        self.assertEqual(self.fetcher()(self.url("/to-private")), (0, ""))
        self.assertEqual(tracker_probe.classify(self.fetcher(), self.url("/to-private")), "unknown")

    def test_redirect_count(self):
        self.assertEqual(self.fetcher()(self.url("/hop/5"))[0], 200)
        self.assertEqual(self.fetcher()(self.url("/hop/6")), (0, ""))

    def test_body_size(self):
        status, body = self.fetcher()(self.url("/big"))
        self.assertEqual((status, len(body)), (200, tracker_probe.MAX_BODY))

    def test_total_deadline_holds_against_a_drip(self):
        for path in ("/drip-head", "/drip-body"):
            t0 = time.monotonic()
            self.assertEqual(self.fetcher(total=1.5)(self.url(path)), (0, ""), path)
            self.assertLess(time.monotonic() - t0, 2.0, path)

    def test_scheme(self):
        self.assertEqual(self.fetcher()("ftp://public.test/x"), (0, ""))
        self.assertEqual(self.fetcher()("file:///etc/passwd"), (0, ""))

    def test_self_ips(self):
        with mock.patch.dict("os.environ", TRACKER_SELF_IPS="93.184.216.34"):
            self.assertFalse(tracker_probe.ip_ok("93.184.216.34"))


if __name__ == "__main__":
    unittest.main()

"""The vendored Leak judge pieces: Jev (tracker_jev over tracker_llm.post_json) against a stub HTTP endpoint on
loopback, never a real model call; the judge prompt, verdict parser and band (tracker_verdicts); policy_kind
(tracker_pagekind). Ported from leakhunt 7ccbdd3's tests (test_jev, test_judge). Hit admission (tracker_judge): the
URL / title / weak-alias table and the own-profile, own-host and aggregator drops. Fictional creators only."""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import public_app
import tracker_jev as jev
import tracker_judge
import tracker_llm
import tracker_verdicts as tv
from tracker_fixture import Base, tdb
from tracker_pagekind import CLIENT_KINDS, GENERIC_LISTINGS, Handles, policy_kind

SECRET = "apikey_s3cr3t-never-printed"
HANDLE = "mia_vale"
HOST = "vids.example"


class FakeTypeSafe:
    """POST /v1/systemone: the answer to the request's one question by substring of the page URL from `p` (0.5
    otherwise). A failure is a status (sent with retry-after 0) or (status, headers, body): `first` holds failures
    sent before any answer, one per request; `broken` maps a URL substring to the failure every request for it gets."""

    def __init__(self, p=None, first=None, usage=True, broken=None):
        self.p, self.first, self.usage, self.broken = p or {}, list(first or []), usage, broken or {}
        self.bodies, self.headers, self.lock = [], [], threading.Lock()

    def __call__(self, body, headers):
        with self.lock:
            self.bodies.append(body)
            self.headers.append(headers)
            url = body["state"]["page"]["url"]
            r = self.first.pop(0) if self.first else next((v for k, v in self.broken.items() if k in url), None)
        if r is not None:
            return r if isinstance(r, tuple) else (r, {"retry-after": "0"}, b"{}")
        p = next((v for k, v in self.p.items() if k in url), 0.5)
        name = next(iter(body["questions"]))
        out = {"model": "jev-1.13.0", "answers": {name: {"type": "noul", "noul": p}}}
        if self.usage:
            out["usage"] = {"input_tokens": 1000, "output_tokens": 0}
        return 200, {}, json.dumps(out).encode()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        status, headers, out = self.server.app(json.loads(raw), {k.lower(): v for k, v in self.headers.items()})
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


class Stubbed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.srv.daemon_threads = True
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def patch(self, target, attr, value):
        p = mock.patch.object(target, attr, value)
        p.start()
        self.addCleanup(p.stop)

    def setUp(self):
        env = mock.patch.dict(os.environ, {jev.KEY_ENV: SECRET})
        env.start()
        self.addCleanup(env.stop)
        self.patch(jev, "URL", f"{self.base}/v1/systemone")
        self.sleeps = []
        self.patch(jev, "sleep", self.sleeps.append)

    def serve(self, app):
        self.srv.app = app
        return app


def row(fid, url, **ev):
    return {"id": fid, "url": url, "source": "google", "evidence": ev}


def rows(n):
    return [row(i, f"https://x.example/{i}") for i in range(1, n + 1)]


class Jev(Stubbed):
    def test_the_band_is_inclusive_at_0_2_and_0_8(self):
        self.assertEqual((jev.LO, jev.HI), (0.2, 0.8))
        self.assertEqual([jev.band(p) for p in (0.0, 0.2, 0.2001, 0.5, 0.7999, 0.8, 1.0)],
                         ["reject", "reject", None, None, None, "accept", "accept"])

    def test_band_cases_through_the_stub_endpoint(self):
        ps = [0.0, 0.2, 0.2001, 0.5, 0.7999, 0.8, 1.0]
        ts = self.serve(FakeTypeSafe({f"x.example/{i}": p for i, p in enumerate(ps, 1)}))
        s = jev.leak_probability(rows(len(ps)), [HANDLE])
        self.assertEqual((s.p, s.failed, s.error), (dict(enumerate(ps, 1)), 0, None))
        fake, middle, real = [], [], []
        for fid, p in sorted(s.p.items()):
            {"reject": fake, "accept": real, None: middle}[tv.jev_verdict(p, "content")].append(fid)
        self.assertEqual((fake, middle, real), ([1, 2], [3, 4, 5], [6, 7]))
        self.assertEqual(len(ts.bodies), len(ps))
        self.assertEqual((s.calls, s.tokens), (len(ps), 1000 * len(ps)))
        self.assertAlmostEqual(s.usd, len(ps) * 1000 * 0.042 / 1e6)

    def test_one_pinned_noul_per_row_and_the_request_shape(self):
        ts = self.serve(FakeTypeSafe({"mia_vale": 0.93, "other": 0.07}))
        items = [row(1, f"https://{HOST}/v/mia_vale/", title="mia_vale solo", matched=[HANDLE], kind="video",
                     found_via=f"https://{HOST}/model/mia_vale"), row(2, f"https://{HOST}/v/other/")]
        s = jev.leak_probability(items, [HANDLE])
        self.assertEqual((s.p, s.failed, s.error), ({1: 0.93, 2: 0.07}, 0, None))
        self.assertTrue(len(ts.bodies) == 2 and all(b["model"] == "jev-1.13.0" for b in ts.bodies))
        body = next(b for b in ts.bodies if b["state"]["page"]["url"].endswith("/mia_vale/"))
        self.assertEqual(body["questions"], {"leak": jev.QUESTION})
        self.assertEqual(body["state"], {"client_handles": [HANDLE], "page": {
            "url": f"https://{HOST}/v/mia_vale/", "title": "mia_vale solo", "handles_matched_by_code": [HANDLE],
            "page_kind": "video", "policy_kind": "content", "discovered_by": "google",
            "found_on": f"https://{HOST}/model/mia_vale"}})
        self.assertEqual(ts.headers[0]["authorization"], f"Bearer {SECRET}")
        self.assertEqual(ts.headers[0]["content-type"], "application/json")
        self.assertEqual(jev.leak_probability([], [HANDLE]), jev.Scores())

    def test_retries_429_and_5xx_without_a_pause_after_the_last_attempt(self):
        self.patch(jev, "WORKERS", 1)
        ts = self.serve(FakeTypeSafe({"x.example": 0.9}, first=[429, 529]))
        self.assertEqual(jev.leak_probability(rows(1), [HANDLE]).p, {1: 0.9})
        self.assertEqual((len(ts.bodies), self.sleeps), (3, [0.0, 0.0]))
        self.sleeps.clear()
        ts = self.serve(FakeTypeSafe({"x.example": 0.9}, first=[503] * jev.ATTEMPTS + [422]))
        s = jev.leak_probability(rows(3), [HANDLE])
        self.assertEqual((s.p, s.failed, s.error), ({3: 0.9}, 2, None))
        self.assertEqual((len(self.sleeps), len(ts.bodies)), (jev.ATTEMPTS - 1, jev.ATTEMPTS + 2))

    def test_retry_after_is_honoured_capped_and_sanitised(self):
        self.assertEqual(jev.retry_wait("2.5", 1.0), 2.5)
        self.assertEqual(jev.retry_wait("600", 1.0), jev.MAX_WAIT)
        self.assertEqual(jev.retry_wait("-1", 1.0), 0.0)
        for bad in ("nan", "inf", "soon", "", None):
            self.assertEqual(jev.retry_wait(bad, 4.0), 4.0)
        self.patch(jev, "WORKERS", 1)
        self.serve(FakeTypeSafe(first=[(429, {"retry-after": "nan"}, b""), (503, {"retry-after": "99"}, b"")]))
        self.assertEqual(jev.leak_probability(rows(1), [HANDLE]).p, {1: 0.5})
        self.assertEqual(self.sleeps, [jev.BACKOFF, jev.MAX_WAIT])

    def test_malformed_answers_lose_only_their_row_and_are_still_billed(self):
        self.patch(jev, "WORKERS", 1)
        bad = [json.dumps(b).encode() for b in ([1, 2], {"usage": "x"},
                                                 {"answers": {"leak": {"noul": True}}, "usage": {"input_tokens": 7}},
                                                 {"answers": {"leak": {"noul": 1.5}}, "usage": {"input_tokens": "a"}},
                                                 {"answers": {"leak": "yes"}})] + [b"not json"]
        self.serve(FakeTypeSafe({"x.example": 0.95}, first=[(200, {}, b) for b in bad]))
        s = jev.leak_probability(rows(len(bad) + 1), [HANDLE])
        self.assertEqual((s.p, s.failed, s.error), ({len(bad) + 1: 0.95}, len(bad), None))
        self.assertTrue(s.calls == len(bad) + 1 and s.usd > 0)

    def test_a_crash_on_one_row_loses_only_that_row(self):
        self.serve(FakeTypeSafe({"x.example": 0.9}))
        s = jev.leak_probability([*rows(2), {"id": 3, "url": None, "evidence": "not a dict"}], [HANDLE])
        self.assertEqual((s.p, s.failed), ({1: 0.9, 2: 0.9}, 1))

    def test_an_outage_trips_the_breaker_after_a_few_rows(self):
        self.patch(jev, "WORKERS", 1)
        ts = self.serve(FakeTypeSafe(first=[503] * 100))
        s = jev.leak_probability(rows(20), [HANDLE])
        self.assertTrue(s.p == {} and s.failed == 20 and "down for the last 3 findings" in s.error)
        self.assertEqual(len(ts.bodies), jev.BREAKER * jev.ATTEMPTS)

    def test_a_wave_ending_in_timeouts_trips_the_breaker(self):
        ts = self.serve(FakeTypeSafe({"x.example": 0.9}))
        slow = ("x.example/6", "x.example/7", "x.example/8")

        def post(url, body, headers, timeout):
            if body["state"]["page"]["url"].endswith(slow):
                raise TimeoutError("slow")
            return tracker_llm.post_json(url, body, headers, timeout)

        s = jev.leak_probability(rows(20), [HANDLE], post=post)
        self.assertIn("down for the last 3 findings", s.error)
        self.assertEqual((sorted(s.p), s.failed, len(ts.bodies)), ([1, 2, 3, 4, 5], 15, 5))

    def test_a_dead_endpoint_is_down_not_a_crash(self):
        self.patch(jev, "WORKERS", 1)
        self.patch(jev, "URL", "http://127.0.0.1:9/v1/systemone")
        s = jev.leak_probability(rows(5), [HANDLE])
        self.assertTrue(s.p == {} and s.failed == 5 and "down for the last 3 findings" in s.error)

    def test_a_redirect_is_not_followed_and_the_finding_fails(self):
        hits = []

        class Other(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                hits.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            do_GET = do_POST

        other = ThreadingHTTPServer(("127.0.0.1", 0), Other)
        threading.Thread(target=other.serve_forever, daemon=True).start()
        self.addCleanup(other.server_close)
        self.addCleanup(other.shutdown)
        loc = {"Location": f"http://127.0.0.1:{other.server_address[1]}/steal"}
        ts = self.serve(FakeTypeSafe(first=[(302, loc, b"")] * 3))
        s = jev.leak_probability(rows(1), [HANDLE])
        self.assertEqual((s.p, s.failed, s.error, len(ts.bodies)), ({}, 1, None, 1))
        status, headers, _ = tracker_llm.post_json(jev.URL, ts.bodies[0], {"Authorization": f"Bearer {SECRET}"}, 5)
        self.assertEqual((status, headers["Location"]), (302, loc["Location"]))
        self.assertEqual(hits, [])

    def test_no_wave_starts_after_the_batch_deadline(self):
        self.patch(jev, "BATCH_S", 0.0)
        self.serve(FakeTypeSafe({"x.example": 0.9}))
        s = jev.leak_probability(rows(20), [HANDLE])
        self.assertTrue(len(s.p) == jev.WORKERS and s.failed == 20 - jev.WORKERS and "took over 0 s" in s.error)

    def test_no_key_and_a_rejected_key_are_clear_errors_without_the_key(self):
        with mock.patch.dict(os.environ, {jev.KEY_ENV: ""}):
            with self.assertRaisesRegex(jev.JevError, "TYPESAFE_API_KEY is not set"):
                jev.leak_probability(rows(1), [HANDLE])
        self.patch(jev, "WORKERS", 1)
        ts = self.serve(FakeTypeSafe(first=[(401, {}, SECRET.encode())] * 10))
        s = jev.leak_probability(rows(5), [HANDLE])
        self.assertTrue("401" in s.error and SECRET not in s.error and len(ts.bodies) == 1)
        self.assertEqual((s.p, s.failed), ({}, 5))

    def test_a_rejected_key_mid_wave_keeps_the_waves_answers_and_stops(self):
        ts = self.serve(FakeTypeSafe({"x.example": 0.9}, broken={"x.example/5": 401}))
        s = jev.leak_probability(rows(20), [HANDLE])
        self.assertTrue("401" in s.error and SECRET not in s.error)
        self.assertEqual((sorted(s.p), s.failed, len(ts.bodies)), ([1, 2, 3, 4, 6, 7, 8], 13, jev.WORKERS))
        self.assertTrue(s.calls == 7 and s.usd > 0)

    def test_usage_missing_is_estimated_and_a_bogus_count_capped(self):
        self.serve(FakeTypeSafe(usage=False))
        est = jev.leak_probability(rows(1), [HANDLE]).tokens
        self.assertGreater(est, 100)
        big = json.dumps({"answers": {"leak": {"noul": 0.9}}, "usage": {"input_tokens": 10 ** 12}}).encode()
        self.serve(FakeTypeSafe(first=[(200, {}, big)]))
        s = jev.leak_probability(rows(1), [HANDLE])
        self.assertEqual((s.p, s.tokens), ({1: 0.9}, jev.TOKEN_CAP * est))


class Judge(unittest.TestCase):
    def test_a_client_page_is_never_rejected_by_the_band(self):
        self.assertEqual(tv.jev_verdict(0.1, "content"), "reject")
        for kind in CLIENT_KINDS:
            self.assertIsNone(tv.jev_verdict(0.1, kind))
            self.assertEqual(tv.jev_verdict(0.9, kind), "accept")
        self.assertIsNone(tv.jev_verdict(0.5, "content"))

    def test_policy_kind(self):
        h = Handles([HANDLE, "Mia Vale"])
        for url, kind in [(f"https://{HOST}/models/mia-vale/2", "client_numbered"),
                          (f"https://{HOST}/models/mia_vale", "client_profile"),
                          (f"https://{HOST}/models/rowan-ash/2", "numbered"),
                          (f"https://{HOST}/models/rowan-ash", "profile"),
                          (f"https://{HOST}/tags/mia-vale", "tag"),
                          (f"https://{HOST}/search?q=mia+vale", "search"),
                          (f"https://{HOST}/video/123/mia-vale-solo", "content"),
                          (f"{HOST}/mia_vale", "client_profile"),
                          (f"https://{HOST}/rowan-ash", "other")]:
            with self.subTest(url=url):
                self.assertEqual(policy_kind(url, h), kind)

    def test_the_prompts_name_every_kind_they_act_on(self):
        for kind in (*CLIENT_KINDS, *GENERIC_LISTINGS):
            self.assertIn(f'"{kind}"', tv.SYSTEM)
            self.assertIn(kind, jev.ACCEPT + jev.REJECT)
        prompt = tv.system([HANDLE, "Mia Vale"])
        self.assertIn('known by these handles: ["mia_vale", "Mia Vale"].', prompt)
        self.assertIn('"reason": "<at most 8 words>"}]}', prompt)

    def test_verdicts_keep_well_formed_entries_for_this_batch(self):
        out = {"verdicts": [{"id": "1", "verdict": " Accept ", "reason": "x" * 200}, {"id": 2, "verdict": "maybe"},
                            {"id": 9, "verdict": "reject"}, {"id": None, "verdict": "reject"}, "junk",
                            {"id": 3, "verdict": "unsure"}]}
        self.assertEqual(tv.verdicts(out, {1, 2, 3}), {1: ("accept", "x" * tv.REASON_CHARS), 3: ("unsure", "")})
        self.assertEqual(tv.verdicts([{"id": 1, "verdict": "reject", "reason": "other"}], {1}),
                         {1: ("reject", "other")})
        with self.assertRaises(ValueError):
            tv.verdicts({"nope": 1}, {1})

    def test_judge_batch(self):
        rows_ = [row(1, f"https://{HOST}/models/mia_vale", title="Mia Vale", matched=[HANDLE], kind="profile",
                     found_via="https://www.google.com/search?q=x"), row(2, f"https://{HOST}/tags/rowan-ash")]
        seen = []

        def ask(system, user):
            seen.append((system, json.loads(user)))
            return {"verdicts": [{"id": 1, "verdict": "accept", "reason": "client profile"},
                                 {"id": 2, "verdict": "reject", "reason": "tag page"}]}

        self.assertEqual(tv.judge_batch(rows_, [HANDLE], ask),
                         {1: ("accept", "client profile"), 2: ("reject", "tag page")})
        system, user = seen[0]
        self.assertEqual(system, tv.system([HANDLE]))
        self.assertEqual(user["items"][0], {"id": 1, "url": f"https://{HOST}/models/mia_vale", "title": "Mia Vale",
                                            "matched": [HANDLE], "kind": "profile", "policy_kind": "client_profile",
                                            "source": "google", "via": "https://www.google.com/search?q=x"})
        self.assertEqual(user["items"][1]["policy_kind"], "tag")

        def fail(system, user):
            raise RuntimeError("no DEEPSEEK_API_KEY")

        def refused(system, user):
            raise OSError("refused")

        for bad in (fail, refused, lambda s, u: "text", lambda s, u: {"verdicts": "x"}, lambda s, u: {}[0]):
            self.assertEqual(tv.judge_batch(rows_, [HANDLE], bad), {})


WATCH = {"watch_id": "w_mia", "username": "mia_vale", "aliases_json": json.dumps(["miavale_x", "Mia-V", "rv"])}
SITE = "https://leaksite.example"


class Admission(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(public_app, "CORS_ORIGINS", frozenset({"https://removal.example"}))
        p.start()
        self.addCleanup(p.stop)

    def test_needles(self):
        self.assertEqual(tracker_judge.needles(WATCH), ("miavale", ["miavale", "miavalex"], ["miav"]))
        self.assertEqual(tracker_judge.needles({**WATCH, "username": "m.v_a"})[:2], ("", ["miavalex"]))

    def test_url_title_and_weak_alias_table(self):
        table = [
            (f"{SITE}/video/mia_vale-beach-101", "", "leak"),
            (f"{SITE}/v/Mia.Vale/", "Set", "leak"),
            (f"{SITE}/v/mia%5Fvale-7", "", "leak"),
            (f"{SITE}/post/miavale_x-99", "anything", "leak"),
            (f"{SITE}/post/miav-99", "Mia_Vale gym set", "leak"),
            (f"{SITE}/post/miav-99", "gym set", None),
            (f"{SITE}/post/123", "miav gym set", None),
            (f"{SITE}/post/123", "new mia_vale shower set", "pending"),
            (f"{SITE}/post/123", "MiaVale_X clips", "pending"),
            (f"{SITE}/post/123", "Mia Vale clips", None),
            (f"{SITE}/post/rv-1", "rv", None),
            (f"{SITE}/post/123", "", None),
            ("https://mega.nz/folder/AbC#mia_vale", "", "leak"),
        ]
        self.assertEqual([(u, t, tracker_judge.admission(WATCH, u, t)) for u, t, _ in table], table)

    def test_own_profile_own_host_and_aggregator_drops(self):
        for url in ("https://onlyfans.com/mia_vale", "https://www.instagram.com/mia_vale/", "https://x.com/mia_vale",
                    "https://twitter.com/miavale_x", "https://removal.example/r/mia_vale",
                    "https://www.removal.example/mia_vale", "https://cdn.removal.example/mia_vale.html",
                    "https://s.leakshaven.com/mia_vale", "https://leakshaven.com/model/mia_vale",
                    "https://ahvideoscdn.net/mia_vale-1.html"):
            self.assertIsNone(tracker_judge.admission(WATCH, url, "mia_vale"), url)
        self.assertEqual(tracker_judge.admission(WATCH, "https://notremoval.example/mia_vale", ""), "leak")


class AdmitHit(Base):
    def test_writes_a_site_search_leak_or_a_pending_hit(self):
        wid = self.watch(self.tenant(), aliases=("miavale_x", "miav"))
        with tdb.db() as c:
            w = c.execute("SELECT * FROM watches WHERE watch_id = ?", (wid,)).fetchone()
            got = [tracker_judge.admit_hit(c, w, u, t, "site_search", self.T0, first_scan=f) for u, t, f in (
                (f"{SITE}/video/mia_vale-101#top", "Beach", False), ("https://mega.nz/file/X1#mia_vale", "", True),
                (f"{SITE}/video/101", "mia_vale beach", False), ("https://onlyfans.com/mia_vale", "mia_vale", False),
                (f"{SITE}/video/mia_vale-101", "again", False))]
        self.assertEqual(got, ["leak", "leak", "pending", None, "leak"])
        leaks = self.rows("SELECT leak_id, url_key, leak_site, kind, title FROM leaks ORDER BY kind")
        self.assertEqual([{k: r[k] for k in ("url_key", "leak_site", "kind", "title")} for r in leaks], [
            {"url_key": "mega.nz/file/x1#mia_vale", "leak_site": "mega.nz", "kind": "filehost", "title": ""},
            {"url_key": "leaksite.example/video/mia_vale-101", "leak_site": "leaksite.example", "kind": "page",
             "title": "Beach"}])
        self.assertEqual([[e["data"] for e in self.events(r["leak_id"])] for r in leaks],
                         [[{"source": "site_search", "first_scan": True}],
                          [{"source": "site_search", "first_scan": False}]])
        self.assertEqual(self.rows("SELECT url, title, source FROM pending_hits"),
                         [{"url": f"{SITE}/video/101", "title": "mia_vale beach", "source": "site_search"}])

    def test_media_key_and_landing_key(self):
        wid = self.watch(self.tenant(), aliases=("miavale_x", "miav"))
        with tdb.db() as c:
            w = c.execute("SELECT * FROM watches WHERE watch_id = ?", (wid,)).fetchone()
            got = [tracker_judge.admit_media(c, w, u, t, v, self.T0, first_scan=True) for u, t, v in (
                (f"{SITE}/Gallery/mia_vale-7#t", "Pics", "images"), (f"{SITE}/Gallery/mia_vale-7", "again", "images"),
                (f"{SITE}/clip/mia_vale-8", "Clip", "videos"), ("https://mega.nz/file/X1#mia_vale", "", "images"))]
            landing = tracker_judge.admit(c, wid, f"{SITE}/Gallery/mia_vale-7", "leaksite.example/gallery/mia_vale-7",
                                          "leaksite.example", "page", "Pics", "google_web", self.T0)
        self.assertEqual(got[1], got[0])
        self.assertEqual([k for _, k in got], ["leaksite.example/gallery/mia_vale-7#google_images"] * 2 + [
            "leaksite.example/clip/mia_vale-8#google_videos", "mega.nz/file/x1#mia_vale#google_images"])
        self.assertTrue(landing[1])
        self.assertNotIn(landing[0], {lid for lid, _ in got})
        got = [lid for lid, _ in got]
        rows = self.rows("SELECT url_key, landing_key, leak_site, kind, title FROM leaks WHERE kind = 'media' "
                         "ORDER BY url_key")
        self.assertEqual(rows, [
            {"url_key": "leaksite.example/clip/mia_vale-8#google_videos", "landing_key": "leaksite.example/clip/mia_vale-8",
             "leak_site": "leaksite.example", "kind": "media", "title": "Clip"},
            {"url_key": "leaksite.example/gallery/mia_vale-7#google_images",
             "landing_key": "leaksite.example/gallery/mia_vale-7", "leak_site": "leaksite.example", "kind": "media",
             "title": "Pics"},
            {"url_key": "mega.nz/file/x1#mia_vale#google_images", "landing_key": "mega.nz/file/x1#mia_vale",
             "leak_site": "mega.nz", "kind": "media", "title": ""}])
        self.assertEqual([e["type"] for e in self.events(got[0])], ["seen", "google_seen"])
        self.assertEqual(self.events(got[2])[0]["data"], {"source": "google_videos", "first_scan": True})
        self.assertEqual(self.rows("SELECT * FROM pending_hits"), [])


if __name__ == "__main__":
    unittest.main()

"""Alias enrichment (app/alias_enrich.py + the quick-scan hook). Declared bypasses (all synthetic data):
  - leak-page fetches -> alias_enrich.urlopen / discover(fetch=) fakes serving tests/fixtures/alias_leak_*.html
  - Google CSE + DeepSeek -> tests/upstream_stub.py HTTP stub (CSE_ENDPOINT / DEEPSEEK_URL)
  - profile page fetches -> profile_extract.urlopen offline; media gather off (MEDIA_ENABLED=False)."""
import http.client
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import alias_enrich as ae  # noqa: E402
import chat_proxy  # noqa: E402
import cse_scanner  # noqa: E402
import db  # noqa: E402
import media_gather as mg  # noqa: E402
import profile_extract as pe  # noqa: E402
import public_app  # noqa: E402
import ratelimit  # noqa: E402
import upstream_stub as stub  # noqa: E402

H = stub.HANDLE                     # mira.example
FIX = stub.FIXTURES


def _fx(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


PAGE_A, PAGE_B, PAGE_C = _fx("alias_leak_a.html"), _fx("alias_leak_b.html"), _fx("alias_leak_listing.html")
URLS = ["https://leaksite-a.example/m/mira", "https://leaksite-b.example/g/mira", "https://leaksite-c.example/top"]
PAGES = dict(zip(URLS, (PAGE_A, PAGE_B, PAGE_C)))
OTHERS = {"nova.sample", "other.creator9", "someone_else", "mira.draws"}


def first_pass(urls=URLS):
    res = [{"link": u, "host": cse_scanner._host(u), "title": "t", "snippet": ""} for u in urls]
    return cse_scanner.summarize_cse(res), res


def fake_fetch(pages):
    return lambda url, timeout, cap, deadline: pages.get(url, "")


class _Resp(io.BytesIO):
    def __init__(self, body, ctype="text/html; charset=utf-8", status=200):
        super().__init__(body)
        self.status, self.headers = status, {"Content-Type": ctype}

    def getcode(self):
        return self.status


class TestExtract(unittest.TestCase):
    def test_all_link_forms(self):
        e = ae.extract(PAGE_A + PAGE_B)
        got = {(p, h) for p, h in e["socials"]}
        for want in (("onlyfans", "miraexample_vip"), ("fansly", "miraexample"), ("instagram", "mira.studio"),
                     ("x", "leaksitea"), ("tiktok", "mira.example"), ("patreon", "mira.example"),
                     ("x", "mira_example")):                              # twitter.com -> x
            self.assertIn(want, got)
        self.assertNotIn(("instagram", "explore"), got)                    # platform paths skipped
        self.assertEqual(ae.social_of("https://www.tiktok.com/mira.example"), None)   # tiktok needs /@

    def test_at_tokens_title_h1_meta(self):
        e = ae.extract(PAGE_A)
        self.assertEqual(e["ats"], ["miraexample_vip", "mira.draws"])     # title + meta description
        self.assertEqual(e["h1"], "Mira Example")

    def test_name_normalisation(self):
        self.assertEqual(ae.name_variants("Mira Example"), ["miraexample", "mira_example", "mira.example"])
        self.assertEqual(ae.person_name("Mira Example (@x) OnlyFans Leaks - Leaksite A"), "Mira Example")
        self.assertEqual(ae.person_name("Mira Example leaked gallery | Leaksite B"), "Mira Example")
        self.assertIsNone(ae.person_name("Top creators this week - 2024"))
        self.assertEqual(ae.extract(PAGE_B)["name"], "Mira Example")

    def test_banned_tokens(self):
        for h in ("onlyfans", "leaked", "free", "porn", "12345678", "abc", "miraleaks", "freemira", "LeakSiteA"):
            self.assertTrue(ae.banned(h, {"leaksitea"}), h)
        self.assertFalse(ae.banned("mira.studio", {"leaksitea"}))

    def test_similarity_keeps_same_creator(self):
        k = {ae.norm(H)}
        for h in ("mira_example", "miraexample_vip", "miraexample2", "mira.exampel", "MiraExampleOfficial"):
            self.assertTrue(ae.similar(h, k), h)

    def test_drops_other_creators_dissimilar_handles(self):
        k = {ae.norm(H)}
        for h in ("nova.sample", "mira", "example", "mira.draws", "someone_else"):
            self.assertFalse(ae.similar(h, k), h)


class TestDiscover(unittest.TestCase):
    def test_keeps_same_creator(self):
        rows, res = first_pass()
        d = ae.discover(rows, res, [H], fetch=fake_fetch(PAGES))
        for a in ("miraexample_vip", "mira.studio", "miraexample2"):
            self.assertIn(a, d["aliases"])
        self.assertNotIn(H, d["aliases"])                                   # known handle is not "new"
        self.assertEqual(d["aliases"][0], "miraexample_vip")
        socials = {(s["platform"], s["handle"]) for s in d["socials"]}
        self.assertIn(("instagram", "mira.studio"), socials)               # sole IG on a page naming her
        self.assertIn(("x", "mira_example"), socials)
        self.assertEqual(d["names"], ["Mira Example"])
        self.assertEqual(d["pages"], 3)
        for s in d["socials"]:
            self.assertEqual(set(s), {"platform", "handle", "url", "source_domain"})
            self.assertTrue(s["url"].startswith("https://") and "?" not in s["url"])

    def test_drops_other_creators(self):
        rows, res = first_pass()
        d = ae.discover(rows, res, [H], fetch=fake_fetch(PAGES))
        self.assertEqual(d["aliases"], ["miraexample_vip", "mira.studio", "miraexample2"])
        found = {a.lower() for a in d["aliases"]} | {s["handle"].lower() for s in d["socials"]}
        self.assertFalse(found & OTHERS, found & OTHERS)                  # sidebar / listing / @token of others
        self.assertNotIn("leaksitea", found)                              # the site's own X account
        self.assertNotIn("onlyfans", found)
        self.assertNotIn("freeleaks4u", found)
        self.assertGreaterEqual(d["reasons"].get("dissimilar", 0), 3)

    def test_drops_other_creators_listing_page_only(self):
        rows, res = first_pass([URLS[2]])
        d = ae.discover(rows, res, [H], fetch=fake_fetch(PAGES))
        self.assertEqual((d["aliases"], d["socials"]), ([], []))

    def test_reasons_safe_to_log(self):
        rows, res = first_pass()
        d = ae.discover(rows, res, [H], fetch=fake_fetch(PAGES))
        line = ae.reasons_str(d["reasons"])
        self.assertRegex(line, r"^[a-z_]+:\d+(,[a-z_]+:\d+)*$")

    def test_page_pick_one_per_domain_pages_only(self):
        res = [{"link": "https://a.example/v/1", "host": "a.example", "title": "t"},
               {"link": "https://a.example/v/2", "host": "a.example", "title": "t"},
               {"link": "https://b.example/videos/9", "host": "b.example", "title": "t"},     # video
               {"link": "https://www.instagram.com/mira.example/", "host": "instagram.com", "title": "t"},
               {"link": "https://c.example/p", "host": "c.example", "title": "t"},
               {"link": "https://d.example/p", "host": "d.example", "title": "t"},
               {"link": "https://e.example/p", "host": "e.example", "title": "t"},
               {"link": "https://f.example/p", "host": "f.example", "title": "t"}]
        rows = cse_scanner.summarize_cse(res)
        self.assertEqual(ae.pick_pages(rows, res), ["https://a.example/v/1", "https://c.example/p",
                                                    "https://d.example/p", "https://e.example/p"])

    def test_timeouts_bounded(self):
        rows, res = first_pass()

        def slow(url, timeout, cap, deadline):
            time.sleep(3)
            return PAGE_A
        t0 = time.monotonic()
        d = ae.discover(rows, res, [H], fetch=slow, budget=0.5)
        self.assertLess(time.monotonic() - t0, 1.5)
        self.assertEqual((d["pages"], d["aliases"]), (0, []))
        self.assertEqual(d["reasons"].get("fetch_fail"), 3)

    def test_fetch_size_cap_and_ctype(self):
        saved = ae.urlopen
        try:
            ae.urlopen = lambda req, timeout: _Resp(b"<p>" + b"a" * (3 * ae.BODY_CAP))
            self.assertLessEqual(len(ae.fetch_page("https://big.example/p")), ae.BODY_CAP)
            ae.urlopen = lambda req, timeout: _Resp(b"\x89PNG", ctype="image/png")
            self.assertEqual(ae.fetch_page("https://img.example/p"), "")

            def boom(req, timeout):
                raise OSError("timed out")
            ae.urlopen = boom
            self.assertEqual(ae.fetch_page("https://down.example/p"), "")
        finally:
            ae.urlopen = saved

    def test_no_offsite_redirect_no_private_hosts(self):
        h = ae._SameSite()
        req = urllib.request.Request("https://a.leak.example/p")
        self.assertIsNone(h.redirect_request(req, None, 302, "Found", {}, "https://evil.example/x"))
        self.assertIsNotNone(h.redirect_request(req, None, 302, "Found", {}, "https://www.leak.example/p2"))
        for u in ("http://127.0.0.1/p", "http://localhost/p", "http://10.0.0.5/p", "http://169.254.169.254/x",
                  "file:///etc/passwd", "ftp://a.example/x"):
            self.assertEqual(ae.fetch_page(u), "", u)


class TestQuickScanEnrich(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.saved = (db.DB_PATH, cse_scanner.CSE_ENDPOINT, chat_proxy.DEEPSEEK_URL, public_app.SCAN_LIMITER,
                     public_app.RESULT_LIMITER, pe.urlopen, mg.MEDIA_ENABLED, ae.urlopen, dict(os.environ))
        db.DB_PATH = os.path.join(cls.tmp.name, "t.db")
        db.init_db()
        cls.up = stub.Stub().start()
        cse_scanner.CSE_ENDPOINT = cls.up.base + "/customsearch/v1"
        chat_proxy.DEEPSEEK_URL = cls.up.base + "/chat/completions"
        os.environ.update(GOOGLE_API_KEY="fake", GOOGLE_CSE_ID="fake", DEEPSEEK_API_KEY="fake")
        public_app.SCAN_LIMITER = ratelimit.Limiter(rate_per_min=1000, burst=1000, max_concurrent=100)
        public_app.RESULT_LIMITER = ratelimit.Limiter(rate_per_min=10000, burst=1000, max_concurrent=1000)
        pe.urlopen = lambda req, timeout=None: (_ for _ in ()).throw(OSError("offline"))
        mg.MEDIA_ENABLED = False
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), public_app.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        (db.DB_PATH, cse_scanner.CSE_ENDPOINT, chat_proxy.DEEPSEEK_URL, public_app.SCAN_LIMITER,
         public_app.RESULT_LIMITER, pe.urlopen, mg.MEDIA_ENABLED, ae.urlopen, env) = cls.saved
        os.environ.clear()
        os.environ.update(env)
        cls.up.shutdown()
        cls.tmp.cleanup()

    def setUp(self):
        self.up.mode = "valid"
        # first pass: the stub's 24 synthetic sites; site1-3 serve the fixture pages
        self.up.alias_items = {
            "miraexample_vip": [{"title": "miraexample_vip set", "link": "https://aliasleak.example/miraexample_vip"},
                                {"title": "dup", "link": "https://site1.example/models/mira.example"}],
            "mira.studio": [{"title": "mira.studio pics", "link": "https://studioleak.example/mira.studio"}],
            "miraexample2": [{"title": "never scanned", "link": "https://third.example/x"}]}
        self.n0 = len(self.up.calls)
        self.fetched = []
        pages = {"https://site1.example/models/mira.example": PAGE_A,
                 "https://site2.example/models/mira.example": PAGE_B,
                 "https://site3.example/models/mira.example": PAGE_C}

        def fetch(req, timeout):
            self.fetched.append(req.full_url)
            if req.full_url in pages:
                return _Resp(pages[req.full_url].encode())
            raise OSError("offline")
        ae.urlopen = fetch

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=60)
        c.request(method, path, body=json.dumps(body) if body is not None else None,
                  headers={"Content-Type": "application/json"} if body is not None else {})
        r = c.getresponse()
        d = r.read()
        c.close()
        return r, d

    def scan(self, body):
        _, data = self.req("POST", "/api/public-scan", body)
        events = {}
        for block in data.decode().split("\n\n"):
            lines = block.strip().split("\n")
            if lines and lines[0].startswith("event: "):
                events.setdefault(lines[0][7:], []).append("\n".join(l[6:] for l in lines[1:] if l.startswith("data: ")))
        self.assertIn("result", events, data[:400])
        return json.loads(events["result"][0]), events

    def cse_queries(self):
        return [c[1].split(" -site:")[0] for c in self.up.calls[self.n0:] if c[0] == "cse"]

    def test_scan_discovers_rescans_and_merges(self):
        res, ev = self.scan({"handle": H, "platform": "onlyfans.com", "level": "low"})
        self.assertIn("Checking other names…", ev["progress"])
        self.assertEqual(res["aliases"]["declared"], [H])
        disc = res["aliases"]["discovered"]
        self.assertEqual((len(disc), disc[0]), (2, "miraexample_vip"))   # cap 2 new
        q = self.cse_queries()
        extra = [x for x in q if any(a in x for a in disc)]
        self.assertLessEqual(len(extra), 2 * public_app.CSE_QUICK_CALLS)
        self.assertFalse([x for x in q if "miraexample2" in x])
        alias = {h["domain"]: h["alias"] for h in res["hits"]}
        self.assertEqual(alias["aliasleak.example"], "miraexample_vip")
        self.assertEqual(alias["site1.example"], H)                       # first sighting wins
        self.assertEqual(res["hit_count"], len(res["hits"]))
        self.assertEqual(res["domain_count"], len(res["hits"]))
        links = [r["link"] for r in res["results"]]
        self.assertEqual(len(links), len(set(links)))                     # merged by URL
        self.assertLessEqual(len(self.fetched), ae.MAX_PAGES)
        # socials -> profile.accounts after the evidence-backed ones, flagged
        accs = res["profile"]["accounts"]
        leak = [a for a in accs if a.get("source") == "leak_page"]
        self.assertTrue(leak)
        self.assertEqual(accs[:len(accs) - len(leak)], [a for a in accs if "source" not in a])
        self.assertIn({"platform": "instagram", "handle": "mira.studio", "url": "https://instagram.com/mira.studio",
                       "source": "leak_page"}, leak)
        self.assertFalse([a for a in leak if a["platform"] == "onlyfans"])   # scanned platform = declared
        # display-name candidates reach the profile LLM evidence
        llm = [c[1] for c in self.up.calls[self.n0:] if c[0] == "llm"]
        payload = json.loads(llm[0]["messages"][1]["content"].split("\n", 1)[1])
        self.assertEqual(payload["other_names"]["names"], ["Mira Example"])
        self.assertEqual(payload["other_names"]["aliases"], disc)
        sr = json.loads(self.req("GET", f"/api/scan-result/{res['slug']}")[1])
        self.assertEqual(sr["aliases"], res["aliases"])
        self.assertEqual(sr["profile"]["accounts"], accs)
        # discovered Instagram feeds the media step when none was declared
        prof = {"accounts": [a for a in accs if a["platform"] != "instagram" or a.get("source")]}
        self.assertEqual(mg.ig_handle("onlyfans.com", H, prof, res["socials"]), "mira.studio")

    def test_drops_other_creators_in_scan(self):
        res, _ = self.scan({"handle": H, "platform": "onlyfans.com", "level": "low"})
        self.assertEqual(res["aliases"]["discovered"], ["miraexample_vip", "mira.studio"])
        alias = {h["domain"]: h["alias"] for h in res["hits"]}
        self.assertEqual(alias["studioleak.example"], "mira.studio")
        leak = {a["handle"].lower() for a in res["profile"]["accounts"] if a.get("source") == "leak_page"}
        self.assertFalse(leak & OTHERS, leak & OTHERS)
        self.assertFalse({s["handle"].lower() for s in res["aliases"]["socials"]} & OTHERS)

    def test_scanned_instagram_wins_over_discovered(self):
        self.up.mode = "sparse"     # LLM finds no IG account: the scanned IG handle must still feed media
        try:
            res, _ = self.scan({"handle": H, "platform": "instagram.com", "level": "low"})
        finally:
            self.up.mode = "valid"
        self.assertIn("mira.studio", res["aliases"]["discovered"])
        accs = res["profile"]["accounts"]
        self.assertFalse([a for a in accs if a["platform"] == "instagram" and a.get("source") == "leak_page"])
        self.assertEqual(mg.ig_handle("instagram.com", H, res["profile"], res["socials"]), H)

    def test_declared_instagram_wins_over_discovered(self):
        res, _ = self.scan({"handle": H, "platform": "onlyfans.com", "level": "low", "instagram": "mira.ig"})
        self.assertEqual(res["aliases"]["declared"], [H, "mira.ig"])
        self.assertEqual(len(res["aliases"]["discovered"]), 2)
        accs = res["profile"]["accounts"]
        self.assertEqual(accs[0], {"platform": "instagram", "handle": "mira.ig", "url": "https://instagram.com/mira.ig"})
        self.assertFalse([a for a in accs if a["platform"] == "instagram" and a.get("source") == "leak_page"])
        self.assertEqual(mg.ig_handle("onlyfans.com", H, res["profile"], res["socials"]), "mira.ig")

    def test_total_alias_cap(self):
        res, _ = self.scan({"handle": H, "platform": "onlyfans.com", "level": "low",
                            "instagram": "mira.ig", "x": "mira_x"})
        self.assertEqual(len(res["aliases"]["declared"]) + len(res["aliases"]["discovered"]), 4)

    def test_no_enrichment_without_hits(self):
        self.up.alias_items = {H: []}
        res, ev = self.scan({"handle": H, "platform": "onlyfans.com", "level": "low"})
        self.assertEqual(res["hit_count"], 0)
        self.assertEqual(self.fetched, [])
        self.assertNotIn("Checking other names…", ev.get("progress", []))
        self.assertEqual(res["aliases"], {"declared": [H], "discovered": [], "socials": []})

    def test_budget_spent_skips_step(self):
        prog = []
        rows, res = first_pass()
        out = public_app.enrich_aliases([H], rows, res, prog.append, time.monotonic() - public_app.ALIAS_SKIP_AFTER - 1)
        self.assertEqual(out, ([], [], [], []))
        self.assertEqual((prog, self.fetched), ([], []))

    def test_step_bounded_by_budget(self):
        saved = public_app.ALIAS_BUDGET
        public_app.ALIAS_BUDGET = 1.5

        def slow(req, timeout):
            time.sleep(min(timeout, 5))
            raise OSError("slow")
        ae.urlopen = slow
        try:
            rows, res = first_pass()
            t0 = time.monotonic()
            public_app.enrich_aliases([H], rows, res, lambda m: None, time.monotonic())
            self.assertLess(time.monotonic() - t0, 2.5)
        finally:
            public_app.ALIAS_BUDGET = saved


if __name__ == "__main__":
    unittest.main()

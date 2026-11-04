"""Quick-scan public profile: extraction, validation, avatar, and the scan wiring.
Paid upstreams (CSE, DeepSeek) are faked at the HTTP wire by tests/upstream_stub.py;
profile-page fetches (instagram/tiktok/CDN) are faked at the urlopen boundary.
All fixtures are synthetic."""
import http.client
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import chat_proxy
import cse_scanner
import db
import profile_extract as pe
import public_app
import ratelimit
import upstream_stub as stub

H = stub.HANDLE
ORIGIN = "https://blackphoenixslo.github.io"
AVATAR_URL = "https://scontent.cdninstagram.com/v/t51/avatar_s150x150.jpg?x=1&amp;y=2"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 2000
IG_HTML = f"""<!DOCTYPE html><html><head>
<meta property="og:type" content="profile" />
<meta property="og:image" content="{AVATAR_URL}" />
<meta property="og:title" content="Mira Example (&#064;{H}) &#x2022; Instagram photos and videos" />
<meta property="og:url" content="https://www.instagram.com/{H}/" />
<meta property="og:description" content="12.5K Followers, 310 Following, 214 Posts - See Instagram photos and videos from Mira Example (&#064;{H})" />
</head><body>{'x' * 1000}</body></html>""".encode()
TT_HTML = (b'<html><head><meta content="Mira Example (@mira.example) | TikTok" property="og:title">'
           b'<meta property="og:description" content="Studio vlogs."></head></html>')


class _Resp(io.BytesIO):
    def __init__(self, status, ctype, body):
        super().__init__(body)
        self.status, self.headers = status, {"Content-Type": ctype}

    def getcode(self):
        return self.status


class FakeFetch:
    """urlopen stand-in: url -> (status, content-type, body); unknown URL -> error."""
    def __init__(self, routes):
        self.routes, self.seen = routes, []

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.seen.append(url)
        if url not in self.routes:
            raise OSError("unreachable " + url)
        return _Resp(*self.routes[url])


def ig_routes(avatar=(200, "image/jpeg", JPEG)):
    return {
        f"https://www.instagram.com/{H}/": (200, "text/html; charset=utf-8", IG_HTML),
        f"https://www.tiktok.com/@{H}": (200, "text/html", TT_HTML),
        AVATAR_URL.replace("&amp;", "&"): avatar,
    }


def raw_items():
    return [{**it, "host": cse_scanner._host(it["link"])} for it in stub.CSE_ITEMS]


def sources(**kw):
    return pe.collect_sources("onlyfans.com", H, raw_items(), fetch=FakeFetch(kw.get("routes", ig_routes())))


class TestCollect(unittest.TestCase):
    def test_ig_og_tiktok_google(self):
        s = sources()
        self.assertEqual(s["instagram"]["full_name"], "Mira Example")
        self.assertEqual(s["instagram"]["followers"], 12500)
        self.assertEqual(s["instagram"]["avatar_url"], AVATAR_URL.replace("&amp;", "&"))
        self.assertEqual(s["og"]["tiktok"]["title"], "Mira Example (@mira.example) | TikTok")
        self.assertEqual(len(s["google"]), 20)
        self.assertIn("instagram.com", s["google"][0]["link"])       # official accounts first

    def test_only_fixed_hosts_and_valid_handle(self):
        f = FakeFetch({})
        s = pe.collect_sources("fansly.com", H, [], fetch=f)
        self.assertIsNone(s["instagram"])
        hosts = {u.split("/")[2] for u in f.seen}
        self.assertEqual(hosts, {"www.instagram.com", "www.tiktok.com", "fansly.com"})
        f2 = FakeFetch({})
        for bad in ("../etc", "a/b", "x?y=1", "a b", "", "h" * 61):
            pe.collect_sources("instagram.com", bad, [], fetch=f2)
        self.assertEqual(f2.seen, [])

    def test_generic_og_ignored(self):
        generic = (b'<meta property="og:title" content="Visit TikTok to discover profiles!">'
                   b'<meta property="og:description" content="Watch, follow, and discover more.">')
        routes = ig_routes()
        routes[f"https://www.tiktok.com/@{H}"] = (200, "text/html", generic)
        routes[f"https://www.instagram.com/{H}/"] = (200, "text/html", generic)
        s = pe.collect_sources("onlyfans.com", H, [], fetch=FakeFetch(routes))
        self.assertIsNone(s["og"])
        self.assertIsNone(s["instagram"])
        self.assertNotIn("tiktok", [a["platform"] for a in pe.fallback_profile(s)["accounts"]])

    def test_failures_are_soft(self):
        s = pe.collect_sources("onlyfans.com", H, raw_items(), fetch=FakeFetch({
            f"https://www.instagram.com/{H}/": (200, "text/html", b"<html>login</html>")}))
        self.assertIsNone(s["instagram"])
        self.assertIsNone(s["og"])


class TestPrompt(unittest.TestCase):
    def test_prompt_has_sources_and_rules(self):
        msgs = pe.build_prompt(sources())
        sysm, user = msgs[0]["content"], msgs[1]["content"]
        self.assertIn("Use ONLY facts present in the SOURCES", sysm)
        self.assertIn("Never invent a location, profession, age, or real name", sysm)
        self.assertIn("no mention of leaks", sysm)
        self.assertIn("JSON only", sysm)
        self.assertIn("Mira Example", user)
        self.assertIn("https://linktr.ee/mira.example", user)
        self.assertIn('"followers": 12500', user)


class TestExtract(unittest.TestCase):
    def test_valid(self):
        p = pe.extract_profile(sources(), llm=lambda m, timeout: dict(stub.VALID), avatar=True)
        self.assertEqual(p["generated_by"], "deepseek")
        self.assertEqual(p["display_name"], "Mira Example")
        self.assertEqual(p["username"], H)
        self.assertEqual(p["platform"], "onlyfans")
        self.assertEqual(p["followers"], 12500)
        self.assertEqual(p["site_domain"], "miraexample.com")
        self.assertTrue(p["avatar"])
        self.assertEqual(p["confidence"], 0.86)
        plats = [a["platform"] for a in p["accounts"]]
        self.assertEqual(plats[:2], ["instagram", "tiktok"])
        self.assertIn("onlyfans", plats)          # scanned account
        self.assertIn("linktree", plats)          # backed by a Google result
        self.assertEqual(set(p), {"display_name", "first_name", "username", "platform", "tagline",
                                  "profession", "location", "bio", "about_short", "followers",
                                  "accounts", "site_domain", "avatar", "sources", "confidence",
                                  "generated_by"})

    def test_dirty_is_stripped(self):
        p = pe.extract_profile(sources(), llm=lambda m, timeout: json.loads(json.dumps(stub.DIRTY)))
        self.assertEqual(p["generated_by"], "deepseek")
        self.assertLessEqual(len(p["display_name"]), 60)
        self.assertLessEqual(len(p["bio"]), 300)
        self.assertIsNone(p["tagline"])            # unsafe wording
        self.assertIsNone(p["location"])           # dict
        self.assertIsNone(p["about_short"])        # int
        self.assertEqual(p["followers"], 12500)    # source value, not the invented one
        self.assertEqual(p["confidence"], 1.0)
        self.assertEqual(p["site_domain"], "mmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmm.com")
        self.assertFalse(p["avatar"])
        for k in ("age", "real_name"):
            self.assertNotIn(k, p)
        self.assertLessEqual(len(p["accounts"]), 8)
        for a in p["accounts"]:
            self.assertTrue(a["url"].startswith("https://"), a)
            self.assertRegex(a["handle"], r"^[A-Za-z0-9._-]{1,60}$")
            self.assertEqual(a["handle"].lower(), H)       # nothing not in the sources
            dom = a["url"].split("/")[2]
            self.assertTrue(any(dom == d or dom.endswith("." + d)
                                for d in pe.ACCOUNT_DOMAINS[a["platform"]]), a)
        self.assertNotIn("https://evil.example", p["sources"])
        for u in p["sources"]:
            self.assertIn(H, u)                     # only this handle's own accounts

    def test_null_name_filled_from_sources(self):
        p = pe.extract_profile(sources(), llm=lambda m, timeout: {"display_name": None})
        self.assertEqual(p["display_name"], "Mira Example")
        self.assertEqual(len(p["sources"]), len(set(p["sources"])))
        self.assertEqual(len([u for u in p["sources"] if "instagram.com" in u]), 1)

    def test_llm_error_falls_back(self):
        def boom(m, timeout):
            raise TimeoutError("slow")
        p = pe.extract_profile(sources(), llm=boom)
        self.assertEqual(p["generated_by"], "fallback")
        self.assertEqual(p["display_name"], "Mira Example")
        self.assertEqual(p["followers"], 12500)

    def test_fallback_without_ig_uses_google_title(self):
        s = pe.collect_sources("onlyfans.com", H, raw_items(), fetch=FakeFetch({}))
        p = pe.fallback_profile(s)
        self.assertEqual(p["display_name"], "Mira Example")
        self.assertEqual(p["followers"], 12500)    # from the IG Google snippet
        p2 = pe.fallback_profile(pe.collect_sources("onlyfans.com", H, [], fetch=FakeFetch({})))
        self.assertEqual(p2["display_name"], H)
        self.assertIsNone(p2["followers"])


class TestAvatar(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(pe.fetch_avatar(sources(), fetch=FakeFetch(ig_routes())), (JPEG, "jpg"))

    def test_rejects(self):
        for bad in ((200, "image/jpeg", b"\xff\xd8\xff" + b"0" * (pe.AVATAR_CAP + 1)),  # too big
                    (200, "text/html", JPEG),                                         # wrong type
                    (200, "image/svg+xml", b"<svg/>"),                                # not jpg/png/webp
                    (404, "image/jpeg", JPEG)):
            self.assertIsNone(pe.fetch_avatar(sources(), fetch=FakeFetch(ig_routes(bad))), bad)

    def test_host_allowlist(self):
        s = sources()
        s["instagram"]["avatar_url"] = "https://evil.example/a.jpg"
        f = FakeFetch({})
        self.assertIsNone(pe.fetch_avatar(s, fetch=f))
        self.assertEqual(f.seen, [])


class TestScanWiring(unittest.TestCase):
    """Real Handler over HTTP; CSE + DeepSeek via the local wire stub."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.saved = (db.DB_PATH, cse_scanner.CSE_ENDPOINT, chat_proxy.DEEPSEEK_URL,
                     public_app.SCAN_LIMITER, pe.urlopen, pe.LLM_TIMEOUT, dict(os.environ))
        db.DB_PATH = os.path.join(cls.tmp.name, "t.db")
        db.init_db()
        cls.up = stub.Stub().start()
        cse_scanner.CSE_ENDPOINT = cls.up.base + "/customsearch/v1"
        chat_proxy.DEEPSEEK_URL = cls.up.base + "/chat/completions"
        os.environ.update(GOOGLE_API_KEY="fake", GOOGLE_CSE_ID="fake", DEEPSEEK_API_KEY="fake")
        os.environ.pop("DATA_DIR", None)
        public_app.SCAN_LIMITER = ratelimit.Limiter(rate_per_min=1000, burst=1000, max_concurrent=100)
        pe.urlopen = FakeFetch(ig_routes())
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), public_app.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.up.shutdown()
        (db.DB_PATH, cse_scanner.CSE_ENDPOINT, chat_proxy.DEEPSEEK_URL,
         public_app.SCAN_LIMITER, pe.urlopen, pe.LLM_TIMEOUT, env) = cls.saved
        os.environ.clear()
        os.environ.update(env)
        public_app.PROFILE_ENABLED = True
        cls.tmp.cleanup()

    def setUp(self):
        self.up.mode = "valid"
        public_app.PROFILE_ENABLED = True
        pe.LLM_TIMEOUT = 15

    def req(self, method, path, body=None, origin=ORIGIN):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=30)
        hdrs = {"Origin": origin} if origin else {}
        if body is not None:
            hdrs["Content-Type"] = "application/json"
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=hdrs)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r, data

    def scan(self):
        r, data = self.req("POST", "/api/public-scan", {"handle": H, "platform": "onlyfans.com"})
        events = {}
        for block in data.decode().split("\n\n"):
            lines = block.strip().split("\n")
            if lines and lines[0].startswith("event: "):
                events.setdefault(lines[0][7:], []).append(
                    "\n".join(l[6:] for l in lines[1:] if l.startswith("data: ")))
        return events

    def test_scan_includes_profile_and_endpoints(self):
        ev = self.scan()
        self.assertIn("Reading your public profile…", ev["progress"])
        res = json.loads(ev["result"][0])
        prof = res["profile"]
        self.assertEqual(prof["generated_by"], "deepseek")
        self.assertEqual(prof["display_name"], "Mira Example")
        self.assertTrue(prof["avatar"])
        slug = res["slug"]
        r, d = self.req("GET", f"/api/profile/{slug}")
        self.assertEqual(r.status, 200)
        self.assertEqual(json.loads(d), {"slug": slug, "profile": prof})
        self.assertEqual(r.getheader("Access-Control-Allow-Origin"), ORIGIN)
        r, d = self.req("GET", f"/api/scan-result/{slug}")
        self.assertEqual(json.loads(d)["profile"], prof)
        r, d = self.req("GET", f"/api/avatar/{slug}")
        self.assertEqual((r.status, d), (200, JPEG))
        self.assertEqual(r.getheader("Content-Type"), "image/jpeg")
        self.assertEqual(r.getheader("Cache-Control"), "public, max-age=86400")
        self.assertEqual(r.getheader("Access-Control-Allow-Origin"), ORIGIN)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp.name, "avatars", f"{slug}.jpg")))
        llm = [c for c in self.up.calls if c[0] == "llm"][-1][1]
        self.assertEqual(llm["response_format"], {"type": "json_object"})
        self.assertFalse(llm["stream"])

    def test_dirty_llm_stripped_end_to_end(self):
        self.up.mode = "dirty"
        prof = json.loads(self.scan()["result"][0])["profile"]
        self.assertIsNone(prof["tagline"])
        self.assertNotIn("age", prof)
        self.assertEqual(prof["followers"], 12500)

    def test_llm_timeout_uses_fallback(self):
        self.up.mode, self.up.timeout_sleep = "timeout", 3
        pe.LLM_TIMEOUT = 1
        res = json.loads(self.scan()["result"][0])
        self.assertEqual(res["status"], "complete")
        self.assertEqual(res["profile"]["generated_by"], "fallback")
        self.assertEqual(res["profile"]["display_name"], "Mira Example")

    def test_disabled(self):
        public_app.PROFILE_ENABLED = False
        ev = self.scan()
        res = json.loads(ev["result"][0])
        self.assertEqual(res["status"], "complete")
        self.assertIsNone(res["profile"])
        self.assertNotIn("Reading your public profile…", ev["progress"])
        r, d = self.req("GET", f"/api/profile/{res['slug']}")
        self.assertEqual((r.status, json.loads(d)["profile"]), (200, None))
        r, _ = self.req("GET", f"/api/avatar/{res['slug']}")
        self.assertEqual(r.status, 404)

    def test_unknown_and_invalid_slugs(self):
        for path in ("/api/avatar/nosuchslug1", "/api/profile/nosuchslug1",
                     "/api/avatar/..%2F..%2Fetc%2Fpasswd", "/api/avatar/../t.db",
                     "/api/profile/bad!slug", "/api/avatar/", "/api/avatar/a.jpg"):
            r, _ = self.req("GET", path)
            self.assertIn(r.status, (400, 404), path)


if __name__ == "__main__":
    unittest.main()

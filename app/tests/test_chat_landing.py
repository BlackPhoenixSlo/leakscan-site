"""Landing-site FAQ mode of POST /api/chat ({"kb":"landing"}) + GET /api/chat-kb.

DeepSeek is faked at the HTTP wire by tests/upstream_stub.py (stream:true SSE);
chat_proxy.DEEPSEEK_URL is pointed at it (declared bypass). The app runs for real on a
loopback ThreadingHTTPServer with a temp SQLite DB.
"""
import http.client
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
sys.path.append(os.path.join(os.path.dirname(HERE), "version2site"))  # report_live (as test_media)
import chat_proxy  # noqa: E402
import db  # noqa: E402
import public_app  # noqa: E402
import ratelimit  # noqa: E402
import upstream_stub as stub  # noqa: E402

ORIGIN = "https://blackphoenixslo.github.io"


def parse_sse(raw):
    """-> [(event, data)]"""
    out = []
    for block in raw.split("\n\n"):
        ev, data = None, []
        for ln in block.split("\n"):
            if ln.startswith("event: "):
                ev = ln[7:]
            elif ln.startswith("data: "):
                data.append(ln[6:])
        if ev:
            out.append((ev, "\n".join(data)))
    return out


class LandingChat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.tmp.name, "t.db")
        db.init_db()
        cls.up = stub.Stub().start()
        cls._url = chat_proxy.DEEPSEEK_URL
        chat_proxy.DEEPSEEK_URL = cls.up.base + "/chat/completions"
        cls._key = os.environ.get("DEEPSEEK_API_KEY")
        os.environ["DEEPSEEK_API_KEY"] = "test-key"
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), public_app.Handler)
        cls.srv.daemon_threads = True
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.slug = db.insert_scan(
            [{"domain": "leak-a.example", "url": "https://leak-a.example/p/1", "occurrences": 9},
             {"domain": "leak-b.example", "url": "https://leak-b.example/p/2", "occurrences": 3}],
            handle="mira.example", platform="onlyfans")

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.up.shutdown()
        chat_proxy.DEEPSEEK_URL = cls._url
        if cls._key is None:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        else:
            os.environ["DEEPSEEK_API_KEY"] = cls._key
        cls.tmp.cleanup()

    def setUp(self):
        self._lim, self._kbf = public_app.CHAT_LIMITER, public_app.KB_LANDING_FILE
        public_app.CHAT_LIMITER = ratelimit.Limiter(rate_per_min=600, burst=50, max_concurrent=5)
        with self.up.lock:
            self.up.calls.clear()

    def tearDown(self):
        public_app.CHAT_LIMITER, public_app.KB_LANDING_FILE = self._lim, self._kbf

    # ---------------------------------------------------------------- helpers
    def chat(self, body):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        c.request("POST", "/api/chat", body=json.dumps(body),
                  headers={"Content-Type": "application/json", "Origin": ORIGIN})
        r = c.getresponse()
        raw = r.read().decode("utf-8")
        c.close()
        return r, raw

    def get(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        c.request("GET", path, headers={"Origin": ORIGIN})
        r = c.getresponse()
        raw = r.read().decode("utf-8")
        c.close()
        return r, raw

    def llm_messages(self):
        with self.up.lock:
            calls = [b for k, b in self.up.calls if k == "llm"]
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["stream"])
        return calls[0]["messages"]

    Q = [{"role": "user", "content": "How much does it cost?"}]

    # ------------------------------------------------------------------ tests
    def test_landing_uses_landing_prompt_and_kb(self):
        r, raw = self.chat({"kb": "landing", "messages": self.Q})
        self.assertEqual(r.status, 200)
        msgs = self.llm_messages()
        self.assertEqual(msgs[0], {"role": "system", "content": chat_proxy.LANDING_SYSTEM_PROMPT})
        self.assertIn("Section anchor list", msgs[1]["content"])        # kb_landing.md content
        self.assertIn("€250/month or €500 one-time", msgs[1]["content"])
        self.assertNotIn('"domains"', msgs[1]["content"])               # not the scan-app kb.json
        self.assertEqual(msgs[-1], self.Q[0])

    def test_sse_stream_and_cors(self):
        r, raw = self.chat({"kb": "landing", "messages": self.Q})
        self.assertEqual(r.getheader("Content-Type"), "text/event-stream; charset=utf-8")
        self.assertEqual(r.getheader("Access-Control-Allow-Origin"), ORIGIN)
        ev = parse_sse(raw)
        self.assertEqual([e for e, _ in ev][-1], "done")
        toks = [json.loads(d) for e, d in ev if e == "token"]
        self.assertGreaterEqual(len(toks), 2)
        text = "".join(toks)
        self.assertIn("€250/month or €500 one-time", text)
        self.assertIn("\n", text)                                       # JSON-encoded newline survives
        self.assertIn("[Pricing](#pricing)", text)
        self.assertNotIn("failed", [e for e, _ in ev])

    def test_default_path_unchanged(self):
        for body in ({"messages": self.Q}, {"kb": "nope", "messages": self.Q}):
            with self.up.lock:
                self.up.calls.clear()
            r, raw = self.chat(body)
            self.assertEqual(r.status, 200)
            msgs = self.llm_messages()
            self.assertEqual(msgs[0]["content"], chat_proxy.SYSTEM_PROMPT)
            ctx = msgs[1]["content"] if msgs[1]["role"] == "system" else ""
            self.assertNotIn("Section anchor list", ctx)
            self.assertEqual(parse_sse(raw)[-1][0], "done")

    def test_default_keeps_scan_context(self):
        self.chat({"messages": self.Q, "scan_context": "stage 2 crawling"})
        self.assertIn("LIVE STATUS: stage 2 crawling", self.llm_messages()[1]["content"])

    def test_landing_ignores_scan_context(self):
        self.chat({"kb": "landing", "messages": self.Q, "scan_context": "SECRET-LIVE-STATUS"})
        blob = json.dumps(self.llm_messages())
        self.assertNotIn("SECRET-LIVE-STATUS", blob)
        self.assertNotIn("LIVE STATUS", blob)

    def test_landing_slug_adds_scan_summary(self):
        self.chat({"kb": "landing", "slug": self.slug, "messages": self.Q})
        ctx = self.llm_messages()[1]["content"]
        self.assertIn("SCAN CONTEXT:", ctx)
        self.assertIn("total matches: 2 across 2 sites", ctx)
        self.assertIn("Section anchor list", ctx)

    def test_landing_bad_slug_ignored(self):
        r, raw = self.chat({"kb": "landing", "slug": "../../x", "messages": self.Q})
        self.assertEqual(parse_sse(raw)[-1][0], "done")
        self.assertNotIn("SCAN CONTEXT:", self.llm_messages()[1]["content"])

    def test_landing_missing_kb_fails_closed(self):
        public_app.KB_LANDING_FILE = os.path.join(self.tmp.name, "missing.md")
        r, raw = self.chat({"kb": "landing", "messages": self.Q})
        ev = parse_sse(raw)
        self.assertEqual([e for e, _ in ev], ["failed", "done"])
        with self.up.lock:
            self.assertEqual(self.up.calls, [])                         # never reached DeepSeek

    def test_rate_limited_429(self):
        public_app.CHAT_LIMITER = ratelimit.Limiter(rate_per_min=1, burst=1, max_concurrent=5)
        r1, _ = self.chat({"kb": "landing", "messages": self.Q})
        r2, raw2 = self.chat({"kb": "landing", "messages": self.Q})
        self.assertEqual(r1.status, 200)
        self.assertEqual(r2.status, 429)
        self.assertEqual(json.loads(raw2), {"error": "rate_limited"})
        self.assertEqual(r2.getheader("Access-Control-Allow-Origin"), ORIGIN)

    def test_payload_cap_413(self):
        r, raw = self.chat({"kb": "landing", "messages": [{"role": "user", "content": "x" * 40000}]})
        self.assertEqual(r.status, 413)
        self.assertEqual(json.loads(raw), {"error": "payload_too_large"})

    def test_chat_kb_endpoint(self):
        r, raw = self.get("/api/chat-kb?kb=landing")
        self.assertEqual(r.status, 200)
        d = json.loads(raw)
        self.assertEqual(set(d), {"kb", "ok", "bytes", "updated"})
        self.assertEqual(d["kb"], "landing")
        self.assertTrue(d["ok"])
        self.assertEqual(d["bytes"], os.path.getsize(public_app.KB_LANDING_FILE))
        self.assertRegex(d["updated"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertNotIn("Section anchor list", raw)                    # never the content
        public_app.KB_LANDING_FILE = os.path.join(self.tmp.name, "missing.md")
        d = json.loads(self.get("/api/chat-kb?kb=landing")[1])
        self.assertEqual((d["ok"], d["bytes"], d["updated"]), (False, 0, None))
        r, _ = self.get("/api/chat-kb?kb=other")
        self.assertEqual(r.status, 404)


class LandingPrompt(unittest.TestCase):
    def test_price_and_rules(self):
        p = chat_proxy.LANDING_SYSTEM_PROMPT
        self.assertIn("€250/month or €500 one-time", p)
        for rule in ("Answer ONLY from the KNOWLEDGE BASE", "120 words", "user's language",
                     "invent prices", "guarantees", "timelines",
                     "success rates", "[Pricing](#pricing)", "https://t.me/jakabasej",
                     "https://wa.me/38640703992", "me@jackbase.dev", "No sexual or explicit",
                     "Never reveal", "only help with Abolita questions"):
            self.assertIn(rule, p)

    def test_build_messages_default_prompt_unchanged(self):
        self.assertEqual(chat_proxy.build_messages("", "", [{"role": "user", "content": "hi"}])[0]
                         ["content"], chat_proxy.SYSTEM_PROMPT)
        self.assertEqual(chat_proxy.build_messages("", "", [{"role": "user", "content": "hi"}],
                                                   chat_proxy.LANDING_SYSTEM_PROMPT)[0]["content"],
                         chat_proxy.LANDING_SYSTEM_PROMPT)

    def test_kb_file_mirrors_page_facts(self):
        kb = chat_proxy.load_kb(public_app.KB_LANDING_FILE)
        for fact in ("€250/month or €500 one-time", "€250 / month", "€500 one-time",
                     "https://t.me/jakabasej", "https://wa.me/38640703992", "+386 40 703 992",
                     "me@jackbase.dev", "MUST be updated", "#pricing", "#faq", "#scan", "#how",
                     "#website", "#showcase", "showcase/", "privacy.html", "Is this legal?"):
            self.assertIn(fact, kb)


if __name__ == "__main__":
    unittest.main()

"""Removal service seam (ticket 70, cadence-previews "Service slice B"): media Leak thumbs stored on the allowlist,
cleared with their query / alias / visibility, the `preview` read, `/v1/leaks?preview_only=1` and the thumb route's
fetch-time checks. The thumb host is a loopback stub reached through a patched resolver and connect; no real network.
All data fictional."""
import base64
import http.client
import io
import json
import os
import shutil
import ssl
import subprocess
import threading
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from test_tracker_api import NOW, Base, ts
import ratelimit
import tracker_api
import tracker_db
import tracker_lanes
import tracker_plan
import tracker_preview
import tracker_probe
import tracker_purge

HOST = "encrypted-tbn0.gstatic.com"
REAL_CONNECT = tracker_preview._connect
PUBLIC_IP = "142.250.64.78"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 24
BODIES = {"/a.png": PNG, "/a.jpg": b"\xff\xd8\xff\xe0" + b"\0" * 16, "/a.gif": b"GIF89a" + b"\0" * 16,
          "/a.webp": b"RIFF\x0c\x00\x00\x00WEBPVP8 " + b"\0" * 8,
          "/page.html": b"<!doctype html><html><body>not an image</body></html>"}
DATA = {m: b + b"\0" * 128 for m, b in (("image/jpeg", BODIES["/a.jpg"]), ("image/png", PNG),
                                        ("image/webp", BODIES["/a.webp"]), ("image/gif", BODIES["/a.gif"]))}


def uri(mime, body):
    return f"data:{mime};base64,{base64.b64encode(body).decode()}"


class _Stub(BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        _Stub.hits.append((self.headers.get("Host", "").split(":")[0], self.path))
        if self.path == "/redirect.png":
            self.send_response(302)
            self.send_header("Location", "/a.png")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/big.png":
            self.send_response(200)
            self.end_headers()
            try:
                self.wfile.write(PNG + b"\0" * tracker_preview.MAX_BYTES)
            except OSError:
                pass
            return
        if self.path == "/slow.png":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(PNG)
            for _ in range(40):
                time.sleep(0.05)
                try:
                    self.wfile.write(b"\0")
                    self.wfile.flush()
                except OSError:
                    return
            return
        body = BODIES.get(self.path.partition("?")[0])
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", "text/html" if self.path.endswith(".html") else "image/png")
        self.send_header("Content-Length", str(len(body or b"")))
        self.end_headers()
        self.wfile.write(body or b"")


class TestPreview(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stub = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
        threading.Thread(target=cls.stub.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.stub.shutdown()
        cls.stub.server_close()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        os.environ.pop("TRACKER_PREVIEWS", None)
        _Stub.hits = []
        self.dns, self.resolved, self.connects, self.timeouts = {}, [], [], []
        for p in (mock.patch.object(tracker_preview, "_resolve", self.resolve),
                  mock.patch.object(tracker_preview, "_connect", self.connect),
                  mock.patch.dict(tracker_preview._counts, clear=True),
                  mock.patch.object(tracker_api, "_THUMBS", ratelimit.Limiter(rate_per_min=6000, burst=1000, max_concurrent=16))):
            p.start()
            self.addCleanup(p.stop)
        self.put("w_mia_00001")
        self.put("w_ash_00002", account_id="acc-2", username="rowanash", aliases=[])
        self.put("w_bee_00001", self.b)
        self.media("w_mia_00001", "lk_m1", "/a.png", seen=ts(NOW - timedelta(days=2)))
        self.media("w_ash_00002", "lk_ash", "/a.png", seen=ts(NOW - timedelta(days=2)))
        self.media("w_bee_00001", "lk_bee", "/a.png", seen=ts(NOW - timedelta(days=2)))

    def resolve(self, host, port):
        self.resolved.append((host, port))
        return self.dns.get(host, [PUBLIC_IP])

    def connect(self, ip, host, timeout):
        self.connects.append((ip, host))
        self.timeouts.append(timeout)
        return tracker_probe._HTTP("127.0.0.1", host, self.stub.server_address[1], timeout)

    def media(self, wid, lid, path, seen, vertical="images", query="handle", visible=True):
        self.leak(wid, lid, f"https://pics.example-leaks.test/{lid}", kind="media", seen=seen, source=f"google_{vertical}",
                  key_suffix=f"#google_{vertical}")
        with tracker_db.db() as c:
            if visible is not None:
                tracker_db.add_event(c, lid, "google_seen", {"visible": visible}, at=seen)
            if path:
                self.assertTrue(tracker_preview.store_thumb(c, lid, f"https://{HOST}{path}", f"{vertical}|{query}", seen))

    def row(self, lid):
        with tracker_db.db() as c:
            return dict(c.execute("SELECT * FROM leaks WHERE leak_id = ?", (lid,)).fetchone() or {})

    def set_url(self, lid, url):
        with tracker_db.db() as c:
            c.execute("UPDATE leaks SET thumb_url = ? WHERE leak_id = ?", (url, lid))

    def items(self, wid="w_mia_00001", key=None):
        return {x["leak_id"]: x for x in self.req("GET", f"/v1/creators/{wid}/leaks", key=key or self.a)[2]["leaks"]}

    def thumb(self, wid="w_mia_00001", lid="lk_m1", key=None):
        st, r, _ = self.req("GET", f"/v1/creators/{wid}/leaks/{lid}/thumb", key=key or self.a)
        return st, r

    def assert_refused(self, st, r, msg=None, code=404):
        self.assertEqual((st, r.getheader("Cache-Control"), r.getheader("X-Content-Type-Options")), (code, "no-store", "nosniff"), msg)
        self.assertIn("json", r.getheader("Content-Type"), msg)

    def test_store_allowlist(self):
        """[ ] An allowlisted https tile stores thumb_url; a refused data: tile or a foreign host stores nothing."""
        self.leak("w_mia_00001", "lk_m2", "https://pics.example-leaks.test/m2", kind="media", key_suffix="#google_videos")
        self.leak("w_mia_00001", "lk_page", "https://example-leaks.test/page")
        seen = ts(NOW)
        with tracker_db.db() as c:
            for url in ("data:image/png;base64,/9j/4AAQ", "http://encrypted-tbn0.gstatic.com/images?q=tbn:x",
                        "https://example-leaks.test/a.png", "https://encrypted-tbn0.gstatic.com.evil/images?q=tbn:x",
                        "https://googleusercontent.com.evil/x.png", "https://evilgstatic.com/x.png", "https://gstatic.com/x.png",
                        "https://user@encrypted-tbn0.gstatic.com/x.png", "https://encrypted-tbn0.gstatic.com:8443/x.png",
                        "https://encrypted-tbn0.gstatic.com:443/x.png", "https://encrypted-tbn0.gstatic.com./x.png",
                        "https://142.250.64.78/x.png", "https://[::1]/x.png", "https://encrypted-tbn0.gstatic.com/a b.png",
                        "https://encrypted-tbn0.gstatic.com/é.png", "https://lh3.googleusercontent.com/" + "a" * 2100, None):
                self.assertFalse(tracker_preview.store_thumb(c, "lk_m2", url, "videos|handle", seen), url)
            self.assertFalse(tracker_preview.store_thumb(c, "lk_page", f"https://{HOST}/a.png", "images|handle", seen))
            self.assertFalse(tracker_preview.store_thumb(c, "lk_m2", f"https://{HOST}/a.png", "web|handle", seen))
            self.assertFalse(tracker_preview.store_thumb(c, "lk_m2", f"https://{HOST}/a.png", "videos|handle", None))
        self.assertEqual({k: self.row("lk_m2")[k] for k in ("thumb_url", "thumb_query_id", "thumb_seen_at")},
                         {"thumb_url": None, "thumb_query_id": None, "thumb_seen_at": None})
        self.assertIsNone(self.row("lk_page")["thumb_url"])
        later = ts(NOW + timedelta(days=7))
        with tracker_db.db() as c:
            for url in ("https://lh3.googleusercontent.com/p/x=w200", "https://yt3.ggpht.com/x.jpg",
                        "https://encrypted-tbn3.gstatic.com/images?q=tbn:ANd9Gc"):
                self.assertTrue(tracker_preview.store_thumb(c, "lk_m2", url, "videos|alias:miavalex", later), url)
            self.assertFalse(tracker_preview.store_thumb(c, "lk_m1", "data:image/png;base64,iVBOR", "images|handle", later))
        self.assertEqual((self.row("lk_m2")["thumb_url"], self.row("lk_m2")["thumb_query_id"], self.row("lk_m2")["thumb_seen_at"]),
                         ("https://encrypted-tbn3.gstatic.com/images?q=tbn:ANd9Gc", "videos|alias:miavalex", later))
        self.assertEqual(self.row("lk_m1")["thumb_url"], f"https://{HOST}/a.png")

    def blob_media(self, lid, src, wid="w_mia_00001", query="handle"):
        seen = ts(NOW - timedelta(days=1))
        self.media(wid, lid, None, seen)
        with tracker_db.db() as c:
            return tracker_preview.store_thumb(c, lid, src, f"images|{query}", seen)

    def raw_thumb(self, lid):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        c.request("GET", f"/v1/creators/w_mia_00001/leaks/{lid}/thumb", headers={"Authorization": f"Bearer {self.a}"})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, r.getheader("Content-Type"), r.getheader("Cache-Control"), r.getheader("X-Content-Type-Options"), data

    def test_data_thumbs_stored_and_served_byte_exact(self):
        """A data: jpeg / png / webp / gif tile is decoded at capture into thumb_blob + thumb_mime and served as stored."""
        for i, (mime, body) in enumerate(DATA.items()):
            lid = f"lk_d{i}"
            self.assertTrue(self.blob_media(lid, uri(mime, body)), mime)
            r = self.row(lid)
            self.assertEqual((r["thumb_url"], r["thumb_mime"], bytes(r["thumb_blob"])), (None, mime, body))
            self.assertEqual(self.items()[lid]["preview"], {"vertical": "images", "seen_at": ts(NOW - timedelta(days=1))})
            self.assertEqual(self.raw_thumb(lid), (200, mime, "no-store", "nosniff", body))
        self.assertEqual((self.resolved, self.connects, _Stub.hits), ([], [], []))
        self.assertEqual(tracker_preview._counts, {"served_stored": 4})
        with tracker_db.db() as c:
            self.assertTrue(tracker_preview.store_thumb(c, "lk_d0", f"https://{HOST}/a.png", "images|handle", ts(NOW)))
        self.assertEqual({k: self.row("lk_d0")[k] for k in ("thumb_url", "thumb_mime", "thumb_blob")},
                         {"thumb_url": f"https://{HOST}/a.png", "thumb_mime": None, "thumb_blob": None})

    def test_bad_data_thumbs_store_nothing(self):
        """A MIME / magic mismatch, svg+xml, text/html, non-base64, junk base64 or an oversize data: tile stores nothing;
        the length is bounded before any decode."""
        jpg = DATA["image/jpeg"]
        bad = [uri("image/png", jpg), uri("image/jpeg", PNG), uri("image/svg+xml", b"<svg/>"), uri("text/html", b"<b>x</b>"),
               "data:image/jpeg,%FF%D8%FF", "data:image/jpeg;base64,@@@@", "data:image/jpeg;base64,/9j/4A",
               uri("image/jpeg", b"not a jpeg"), "data:image/gif;base64,R0lGODlhAQABAIAAAP///////yH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==", "data:;base64,/9j/4AAQ", " " + uri("image/jpeg", jpg)]
        self.assertFalse(self.blob_media("lk_bad", bad[0]))
        with tracker_db.db() as c:
            for u in bad:
                self.assertFalse(tracker_preview.store_thumb(c, "lk_bad", u, "images|handle", ts(NOW)), u)
                self.assertFalse(tracker_preview.storable(u), u)
        with mock.patch.object(tracker_preview, "MAX_BYTES", len(jpg) - 1):
            self.assertIsNone(tracker_preview.data_thumb(uri("image/jpeg", jpg)))
        with mock.patch.object(tracker_preview.base64, "b64decode", side_effect=AssertionError("decoded")):
            self.assertIsNone(tracker_preview.data_thumb("data:image/jpeg;base64,/9j/" + "A" * tracker_preview.DATA_MAX))
        self.assertEqual({k: self.row("lk_bad")[k] for k in ("thumb_url", "thumb_mime", "thumb_blob", "thumb_query_id")},
                         dict.fromkeys(("thumb_url", "thumb_mime", "thumb_blob", "thumb_query_id")))
        self.assertIsNone(self.items()["lk_bad"]["preview"])
        self.assert_refused(*self.thumb(lid="lk_bad"))

    def test_data_thumb_clear_prune_purge(self):
        """clear_thumb and prune drop the blob with the rest of the thumb; the purge drops the row."""
        for lid, wid, query in (("lk_c", "w_mia_00001", "handle"), ("lk_p", "w_mia_00001", "alias:gone"),
                                ("lk_k", "w_mia_00001", "handle"), ("lk_ashd", "w_ash_00002", "handle")):
            self.assertTrue(self.blob_media(lid, uri("image/png", DATA["image/png"]), wid, query))
        with tracker_db.db() as c:
            tracker_preview.clear_thumb(c, "lk_c")
            self.assertEqual(tracker_preview.prune(c, "w_mia_00001", {"images|handle"}), 1)
        empty = dict.fromkeys(("thumb_url", "thumb_mime", "thumb_blob", "thumb_query_id", "thumb_seen_at"))
        for lid in ("lk_c", "lk_p"):
            self.assertEqual({k: self.row(lid)[k] for k in empty}, empty, lid)
        self.assertEqual(bytes(self.row("lk_k")["thumb_blob"]), DATA["image/png"])
        self.assertEqual(self.req("DELETE", "/v1/watches/w_ash_00002", key=self.a)[0], 204)
        self.assertEqual(tracker_purge.run(NOW + timedelta(days=31))["deleted_ids"], ["w_ash_00002"])
        self.assertEqual(self.row("lk_ashd"), {})

    def test_data_thumb_previews_off(self):
        self.assertTrue(self.blob_media("lk_d", uri("image/png", DATA["image/png"])))
        with mock.patch.dict(os.environ, TRACKER_PREVIEWS="0"):
            self.assertIsNone(self.items()["lk_d"]["preview"])
            self.assert_refused(*self.thumb(lid="lk_d"))
        self.assertEqual(tracker_preview._counts, {})

    def test_data_thumb_route_makes_no_fetch(self):
        """A stored blob is served without a request, a resolve or the fetch rate cap."""
        self.assertTrue(self.blob_media("lk_d", uri("image/gif", DATA["image/gif"])))
        never, cap = mock.Mock(side_effect=AssertionError("network")), mock.Mock()
        with mock.patch.multiple(tracker_preview, fetch=never, _fetch=never, _resolve=never, _connect=never), \
                mock.patch.object(tracker_api, "_THUMBS", cap):
            for _ in range(3):
                self.assertEqual(self.raw_thumb("lk_d")[::4], (200, DATA["image/gif"]))
        self.assertEqual((never.call_count, cap.method_calls, self.resolved, self.connects, _Stub.hits), (0, [], [], [], []))

    def test_clear_query_alias_visibility_and_purge(self):
        """[ ] The query removed, the alias removed or visibility false clears it; the purge drops it."""
        seen = ts(NOW - timedelta(days=1))
        self.media("w_mia_00001", "lk_alias", "/a.png", seen, query="alias:miavalex")
        self.media("w_mia_00001", "lk_ig", "/a.png", seen, vertical="videos", query="instagram")
        with tracker_db.db() as c:
            c.execute("UPDATE leaks SET google_fields_json = '[[\"images\",\"handle\"]]' WHERE leak_id = 'lk_m1'")
            self.assertEqual(tracker_preview.prune(c, "w_mia_00001", {"images|handle", "images|alias:miavalex"}), 1)
        self.assertIsNone(self.row("lk_ig")["thumb_url"])
        self.assertEqual(self.put("w_mia_00001", aliases=[])[0], 200)
        w = self.watch("w_mia_00001")
        full = tracker_plan.build(w, w["platform"])
        with tracker_db.db() as c:
            tracker_lanes._visibility(c, w, full, {}, set(), ts(NOW), True)
        self.assertIsNone(self.row("lk_alias")["thumb_url"])
        self.assertEqual(self.row("lk_m1")["thumb_url"], f"https://{HOST}/a.png")
        with tracker_db.db() as c:
            tracker_lanes._visibility(c, w, full, {}, {("images", "handle")}, ts(NOW), True)
        self.assertEqual((self.row("lk_m1")["thumb_url"], self.row("lk_m1")["thumb_query_id"], self.row("lk_m1")["thumb_seen_at"]),
                         (None, None, None))
        self.assertEqual(self.req("DELETE", "/v1/watches/w_ash_00002", key=self.a)[0], 204)
        self.assertTrue(self.row("lk_ash")["thumb_url"])
        self.assertEqual(tracker_purge.run(NOW + timedelta(days=31))["deleted_ids"], ["w_ash_00002"])
        self.assertEqual(self.row("lk_ash"), {})

    def test_preview_field(self):
        """[ ] TRACKER_PREVIEWS unset -> preview non-null for a qualifying media Leak; null with TRACKER_PREVIEWS=0, for
        non-media and without thumb_url; the read has no URL field."""
        seen = ts(NOW - timedelta(days=1))
        self.media("w_mia_00001", "lk_bare", None, seen)
        self.media("w_mia_00001", "lk_hidden", "/a.png", seen, visible=False)
        self.media("w_mia_00001", "lk_unknown", "/a.png", seen, visible=None)
        self.media("w_mia_00001", "lk_vid", "/a.jpg", seen, vertical="videos")
        self.leak("w_mia_00001", "lk_page", "https://example-leaks.test/page", google=True)
        self.set_url("lk_page", f"https://{HOST}/a.png")
        self.media("w_mia_00001", "lk_noq", None, seen)
        self.set_url("lk_noq", f"https://{HOST}/a.png")
        got = self.items()
        self.assertEqual({k: x["preview"] for k, x in got.items()},
                         {"lk_m1": {"vertical": "images", "seen_at": ts(NOW - timedelta(days=2))}, "lk_bare": None,
                          "lk_hidden": None, "lk_unknown": None, "lk_vid": {"vertical": "videos", "seen_at": seen}, "lk_page": None,
                          "lk_noq": None})
        self.assert_refused(*self.thumb(lid="lk_noq"))
        all_ = self.req("GET", "/v1/leaks?watch_id=w_mia_00001", key=self.a)[2]["leaks"]
        self.assertEqual({x["leak_id"]: x["preview"] for x in all_}, {k: x["preview"] for k, x in got.items()})
        text = json.dumps([got, all_, self.req("GET", "/v1/creators/w_mia_00001", key=self.a)[2],
                           self.req("GET", "/v1/creators", key=self.a)[2]])
        for leaked in (HOST, "gstatic", "thumb", "images|handle", "rank", "query_id"):
            self.assertNotIn(leaked, text)
        self.assertIsNone(self.req("GET", "/v1/creators/w_mia_00001", key=self.a)[2]["preview_leak"])
        self.leak("w_mia_00001", "lk_live", "https://example-leaks.test/live", probe={"origin": "live", "at": ts(NOW)})
        self.assertIsNone(self.req("GET", "/v1/creators/w_mia_00001", key=self.a)[2]["preview_leak"]["preview"])
        self.assertEqual(self.thumb()[0], 200)
        for off in ("0", "off"):
            with mock.patch.dict(os.environ, TRACKER_PREVIEWS=off):
                self.assertEqual({x["preview"] for x in self.items().values()}, {None}, off)
                self.assertEqual(self.req("GET", "/v1/leaks?watch_id=w_mia_00001&preview_only=1", key=self.a)[2]["leaks"], [])
                self.assert_refused(*self.thumb(), off)
        self.assertEqual(len(_Stub.hits), 1)

    def test_preview_only(self):
        """[ ] /v1/leaks?preview_only=1 returns only preview Leaks in seen_at order."""
        d = lambda h: ts(NOW - timedelta(hours=h))
        self.media("w_mia_00001", "lk_m3", "/a.png", d(5))
        self.media("w_mia_00001", "lk_m4", "/a.png", d(5))
        self.media("w_ash_00002", "lk_m5", "/a.gif", d(1), vertical="videos")
        self.media("w_mia_00001", "lk_bare", None, d(0))
        self.leak("w_mia_00001", "lk_page", "https://example-leaks.test/page", seen=d(0), google=True)
        with tracker_db.db() as c:
            self.assertTrue(tracker_preview.store_thumb(c, "lk_m1", f"https://{HOST}/a.webp", "images|handle", d(3)))
        ids = "watch_id=w_mia_00001&watch_id=w_ash_00002&watch_id=w_bee_00001"
        b = self.req("GET", f"/v1/leaks?{ids}&preview_only=1", key=self.a)[2]
        self.assertEqual([x["leak_id"] for x in b["leaks"]], ["lk_m5", "lk_m1", "lk_m3", "lk_m4", "lk_ash"])
        self.assertEqual([x["preview"]["seen_at"] for x in b["leaks"]], [d(1), d(3), d(5), d(5), d(48)])
        self.assertTrue(all("events" not in x and x["watch_id"] for x in b["leaks"]))
        got, cur = [], ""
        while True:
            b = self.req("GET", f"/v1/leaks?{ids}&preview_only=1&limit=1" + (f"&cursor={cur}" if cur else ""), key=self.a)[2]
            got += [x["leak_id"] for x in b["leaks"]]
            cur = b["next_cursor"]
            if not cur:
                break
        self.assertEqual(got, ["lk_m5", "lk_m1", "lk_m3", "lk_m4", "lk_ash"])
        self.assertEqual([x["leak_id"] for x in self.req("GET", f"/v1/leaks?{ids}&preview_only=0", key=self.a)[2]["leaks"]][:2],
                         ["lk_bare", "lk_page"])
        for bad in ("2", "true"):
            st, _, b = self.req("GET", f"/v1/leaks?{ids}&preview_only={bad}", key=self.a)
            self.assertEqual((st, b), (422, {"error": "invalid", "field": "preview_only"}), bad)

    def test_thumb_serves_image(self):
        """The thumb route: the stored URL fetched at request time, pinned to the checked address, fixed image type."""
        for path, ctype in (("/a.png", "image/png"), ("/a.jpg", "image/jpeg"), ("/a.gif", "image/gif"), ("/a.webp", "image/webp"),
                            ("/a.png?q=tbn:ANd9Gc", "image/png")):
            self.set_url("lk_m1", f"https://{HOST}{path}")
            c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
            c.request("GET", "/v1/creators/w_mia_00001/leaks/lk_m1/thumb", headers={"Authorization": f"Bearer {self.a}"})
            r = c.getresponse()
            data = r.read()
            c.close()
            self.assertEqual((r.status, r.getheader("Content-Type"), r.getheader("Cache-Control"), r.getheader("X-Content-Type-Options"),
                              data), (200, ctype, "no-store", "nosniff", BODIES[path.partition("?")[0]]), path)
            self.assertEqual(_Stub.hits[-1], (HOST, path))
        self.assertEqual(set(self.resolved), {(HOST, 443)})
        self.assertEqual(set(self.connects), {(PUBLIC_IP, HOST)})

    def test_thumb_refusals(self):
        """[ ] The thumb route refuses a private address after DNS, a redirect, port 8443, userinfo, a lookalike host
        (googleusercontent.com.evil), an oversize or slow body and HTML bytes, each as 404 with no-store."""
        for ips in (["10.0.0.7"], ["127.0.0.1"], ["169.254.169.254"], ["::1"], ["fe80::1"], [PUBLIC_IP, "192.168.1.4"],
                    ["::ffff:10.0.0.7"], ["64:ff9b::a00:7"], ["0.0.0.0"], ["100.64.0.1"], ["224.0.0.1"], ["240.0.0.1"],
                    ["2001::1"], []):
            self.dns[HOST] = ips
            self.assert_refused(*self.thumb(), ips)
        self.assertEqual((self.connects, _Stub.hits), ([], []))
        del self.dns[HOST]
        self.resolved = []
        for url in (f"https://{HOST}:8443/a.png", f"https://user:pw@{HOST}/a.png", f"https://u@{HOST}/a.png",
                    "https://lh3.googleusercontent.com.evil/a.png", f"http://{HOST}/a.png", "data:image/png;base64,iVBOR",
                    "https://example-leaks.test/a.png"):
            self.set_url("lk_m1", url)
            self.assert_refused(*self.thumb(), url)
        self.assertEqual((self.resolved, self.connects, _Stub.hits), ([], [], []))
        for path in ("/redirect.png", "/page.html", "/big.png", "/missing.png"):
            self.set_url("lk_m1", f"https://{HOST}{path}")
            self.assert_refused(*self.thumb(), path)
        self.assertEqual([p for _, p in _Stub.hits], ["/redirect.png", "/page.html", "/big.png", "/missing.png"])
        self.set_url("lk_m1", f"https://{HOST}/slow.png")
        with mock.patch.object(tracker_preview, "TOTAL_S", 0.5):
            t0 = time.monotonic()
            self.assert_refused(*self.thumb(), "slow")
            self.assertLess(time.monotonic() - t0, 1.5)
        self.assertEqual(tracker_preview._counts, {"refused_address": 14, "refused_host": 7, "refused_status": 2, "refused_type": 1,
                                                   "refused_size": 1, "refused_slow": 1})

    def test_thumb_scope(self):
        """[ ] Another tenant's Leak, or another watch's, answers 404; a deleted watch 410."""
        self.assertEqual(self.thumb()[0], 200)
        _Stub.hits = []
        self.assert_refused(*self.thumb("w_bee_00001", "lk_bee"))
        self.assert_refused(*self.thumb("w_mia_00001", "lk_bee"))
        self.assert_refused(*self.thumb("w_mia_00001", "lk_m1", key=self.b))
        self.assert_refused(*self.thumb("w_mia_00001", "lk_ash"))
        self.assert_refused(*self.thumb("w_mia_00001", "lk_none"))
        self.assert_refused(*self.thumb("w_none_0001", "lk_m1"))
        self.assert_refused(*self.thumb(key="ltk_" + "0" * 40), code=401)
        self.req("DELETE", "/v1/watches/w_ash_00002", key=self.a)
        st, r = self.thumb("w_ash_00002", "lk_ash")
        self.assert_refused(st, r, code=410)
        self.assertEqual(self.req("GET", "/v1/creators/w_ash_00002/leaks/lk_ash/thumb", key=self.a)[2], {"error": "watch_deleted"})
        self.assertEqual(self.req("HEAD", "/v1/creators/w_mia_00001/leaks/lk_m1/thumb", key=self.a)[0], 405)
        self.assertEqual(_Stub.hits, [])

    def test_dns_inside_total_cap(self):
        """DNS counts against the 5 s cap: a hung resolver is cut at the cap; a slow one leaves connect only what's left."""
        def slow(host, port):
            time.sleep(self.delay)
            return [PUBLIC_IP]

        with mock.patch.object(tracker_preview, "_resolve", slow), mock.patch.object(tracker_preview, "TOTAL_S", 0.4):
            self.delay = 2.0
            t0 = time.monotonic()
            self.assert_refused(*self.thumb(), "hung dns")
            self.assertLess(time.monotonic() - t0, 1.2)
            self.assertEqual((tracker_preview._counts, self.connects), ({"refused_dns": 1}, []))
            self.delay = 0.2
            self.assertEqual(self.thumb()[0], 200)
        self.assertLess(self.timeouts[0], 0.25)

    def test_tls_verified(self):
        """The real connect: tracker_probe's pinned HTTPS on 443 with certificate and hostname checks; a loopback TLS stub
        with a self-signed certificate for HOST is refused before any request reaches it."""
        c = REAL_CONNECT(PUBLIC_IP, HOST, 1)
        self.assertIsInstance(c, tracker_probe._HTTPS)
        self.assertEqual((c.port, c._ip, c.host, c._context.verify_mode, c._context.check_hostname),
                         (443, PUBLIC_IP, HOST, ssl.CERT_REQUIRED, True))
        if not shutil.which("openssl"):
            self.skipTest("no openssl to mint a self-signed certificate")
        cert, key = (os.path.join(self.tmp.name, n) for n in ("cert.pem", "key.pem"))
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert, "-days", "1",
                        "-subj", f"/CN={HOST}", "-addext", f"subjectAltName=DNS:{HOST}"], check=True, capture_output=True)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        tls = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
        tls.socket = ctx.wrap_socket(tls.socket, server_side=True)
        threading.Thread(target=tls.serve_forever, daemon=True).start()
        self.addCleanup(tls.server_close)
        self.addCleanup(tls.shutdown)
        self.dns[HOST] = ["127.0.0.1"]
        with mock.patch.object(tracker_preview, "_connect", REAL_CONNECT), \
                mock.patch.object(tracker_preview, "PORT", tls.server_address[1]), \
                mock.patch.object(tracker_probe, "ip_ok", lambda ip: True):
            self.assert_refused(*self.thumb(), "self-signed")
        self.assertEqual((tracker_preview._counts, _Stub.hits), ({"refused_error": 1}, []))
        trusting = tracker_probe._HTTPS("127.0.0.1", HOST, tls.server_address[1], 5)
        trusting._context = ssl.create_default_context(cafile=cert)
        trusting.request("GET", "/a.png")
        self.assertEqual(trusting.getresponse().read(), PNG)
        trusting.close()

    def test_previews_off_deleted_watch(self):
        """ASSUMPTION: previews off answers 404 before the watch lookup, so a deleted watch reads 404, not 410."""
        self.req("DELETE", "/v1/watches/w_ash_00002", key=self.a)
        self.assert_refused(*self.thumb("w_ash_00002", "lk_ash"), code=410)
        with mock.patch.dict(os.environ, TRACKER_PREVIEWS="0"):
            self.assert_refused(*self.thumb("w_ash_00002", "lk_ash"))
        self.assertEqual(_Stub.hits, [])

    def test_rate_cap(self):
        """The per-tenant rate cap answers 429 before any fetch, no Retry-After (ASSUMPTION, like put_watch's cap); another
        tenant keeps its own budget."""
        with mock.patch.object(tracker_api, "_THUMBS", ratelimit.Limiter(rate_per_min=1, burst=1, max_concurrent=1)):
            self.assertEqual(self.thumb()[0], 200)
            st, r = self.thumb()
            self.assert_refused(st, r, code=429)
            self.assertIsNone(r.getheader("Retry-After"))
            self.assertEqual(self.thumb("w_bee_00001", "lk_bee", key=self.b)[0], 200)
        self.assertEqual(len(_Stub.hits), 2)

    def test_logs_counts_only(self):
        """[ ] Logs hold counts only: no URL, key or handle."""
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            self.thumb()
            self.dns[HOST] = ["10.0.0.7"]
            self.thumb()
            del self.dns[HOST]
            for path in ("/redirect.png", "/page.html"):
                self.set_url("lk_m1", f"https://{HOST}{path}")
                self.thumb()
        log = err.getvalue()
        self.assertIn("tracker thumb served=1", log)
        self.assertIn("tracker thumb refused_address=1", log)
        for leaked in (HOST, "gstatic", "http", ".png", self.a, "miavale", "lk_m1", "w_mia_00001", PUBLIC_IP):
            self.assertNotIn(leaked, log)

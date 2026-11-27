"""Removal service seam (Phase 3 `test_tracker_offer_video`): GET /v1/offer-video/{part} and /v1/me `video`, from tiny
synthetic files in a temp TRACKER_OFFER_VIDEO_DIR (git holds no footage)."""
import http.client
import json
import os
import unittest
from unittest import mock

from test_tracker_api import Base
import tracker_api

VIDEO = bytes(range(256)) * 4
FILES = {"offer.mp4": VIDEO, "poster.webp": b"RIFF\x0c\x00\x00\x00WEBPVP8 ", "captions.vtt": b"WEBVTT\n\n00:00.000 --> 00:02.000\nHi\n"}
CUES = [{"t_s": 3, "kind": "google"}, {"t_s": 9.5, "kind": "google_images"}, {"t_s": 16, "kind": "mega"},
        {"t_s": 22, "kind": "forum"}, {"t_s": 28, "kind": "x"}, {"t_s": 40, "kind": "end"}]
TYPES = {"video": ("video/mp4", "offer.mp4"), "poster": ("image/webp", "poster.webp"), "captions": ("text/vtt", "captions.vtt")}


class TestOfferVideo(Base):
    def setUp(self):
        super().setUp()
        self.dir = os.path.join(self.tmp.name, "offer-video")
        os.makedirs(self.dir)
        for name, data in FILES.items():
            self.write(name, data)
        self.cues({"duration_s": 42, "cues": CUES})
        p = mock.patch.dict(os.environ, TRACKER_OFFER_VIDEO_DIR=self.dir)
        p.start()
        self.addCleanup(p.stop)

    def write(self, name, data):
        with open(os.path.join(self.dir, name), "wb") as f:
            f.write(data)

    def cues(self, doc):
        self.write("cues.json", json.dumps(doc).encode() if not isinstance(doc, bytes) else doc)

    def get(self, part, key=None, rng=None):
        st, r, _ = self.req("GET", f"/v1/offer-video/{part}", key=key or self.a, headers={"Range": rng} if rng else None)
        return st, r

    def raw(self, part, key=None, rng=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        h = {"Authorization": f"Bearer {key or self.a}"}
        if rng:
            h["Range"] = rng
        c.request("GET", f"/v1/offer-video/{part}", headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, r, data

    def video(self, key=None):
        return self.req("GET", "/v1/me", key=key or self.a)[2]["video"]

    def test_each_part_fixed_type(self):
        for part, (ctype, name) in TYPES.items():
            with mock.patch.object(tracker_api, "CHUNK", 7):
                st, r, data = self.raw(part)
            self.assertEqual((st, r.getheader("Content-Type"), data), (200, ctype, FILES[name]), part)
            self.assertEqual(r.getheader("Content-Length"), str(len(FILES[name])))
        self.assertEqual(self.raw("poster", rng="bytes=0-3")[0], 200)

    def test_other_part_404(self):
        for part in ("cues", "offer.mp4", "VIDEO", "..%2ftracker.db", "video/x", "", "captions.vtt"):
            st, r, b = self.req("GET", f"/v1/offer-video/{part}", key=self.a)
            self.assertEqual((st, b), (404, {"error": "not_found"}), part)
        self.assertEqual(self.req("POST", "/v1/offer-video/video", {}, self.a)[0], 405)
        for name, part in (("poster.webp", "poster"), ("offer.mp4", "video"), ("captions.vtt", "captions")):
            os.remove(os.path.join(self.dir, name))
            self.assertEqual(self.req("GET", f"/v1/offer-video/{part}", key=self.a)[::2], (404, {"error": "not_found"}), part)
        with mock.patch.dict(os.environ, TRACKER_OFFER_VIDEO_DIR=""):
            self.write("poster.webp", FILES["poster.webp"])
            self.assertEqual(self.get("poster")[0], 404)

    def test_range_206(self):
        st, r, data = self.raw("video", rng="bytes=0-99")
        self.assertEqual((st, r.getheader("Content-Range"), r.getheader("Content-Length"), data),
                         (206, "bytes 0-99/1024", "100", VIDEO[:100]))
        self.assertEqual((r.getheader("Content-Type"), r.getheader("Accept-Ranges")), ("video/mp4", "bytes"))
        for rng, cr, part in (("bytes=1000-", "bytes 1000-1023/1024", VIDEO[1000:]), ("bytes=-24", "bytes 1000-1023/1024", VIDEO[1000:]),
                              ("bytes=1020-5000", "bytes 1020-1023/1024", VIDEO[1020:]), ("bytes=5-5", "bytes 5-5/1024", VIDEO[5:6])):
            st, r, data = self.raw("video", rng=rng)
            self.assertEqual((st, r.getheader("Content-Range"), data), (206, cr, part), rng)

    def test_bad_or_multiple_range_416(self):
        for rng in ("bytes=0-1,5-9", "bytes=0-99, 200-299", "bytes=1024-", "bytes=2000-3000", "bytes=50-10", "bytes=-0",
                    "bytes=-", "bytes=abc", "items=0-1", "bytes 0-1"):
            st, r, b = self.req("GET", "/v1/offer-video/video", key=self.a, headers={"Range": rng})
            self.assertEqual((st, r.getheader("Content-Range"), b), (416, "bytes */1024", {"error": "range_not_satisfiable"}), rng)

    def test_me_video_and_no_captions_null(self):
        self.assertEqual(self.video(), {"duration_s": 42, "has_poster": True, "cues": CUES})
        os.remove(os.path.join(self.dir, "poster.webp"))
        self.assertEqual(self.video()["has_poster"], False)
        os.remove(os.path.join(self.dir, "captions.vtt"))
        self.assertIsNone(self.video())
        self.assertEqual(self.get("captions")[0], 404)
        self.assertEqual(self.get("video")[0], 200)
        with mock.patch.dict(os.environ, TRACKER_OFFER_VIDEO_DIR=""):
            self.assertIsNone(self.video())

    def test_cues_match_file_and_equal_for_two_tenants(self):
        a, b = self.video(), self.video(self.b)
        self.assertEqual((a, a["cues"]), (b, CUES))
        self.assertEqual(self.raw("video", key=self.b)[2], self.raw("video")[2])
        self.cues({"duration_s": 30.5, "cues": CUES[:2]})
        self.assertEqual(self.video(self.b), {"duration_s": 30.5, "has_poster": True, "cues": CUES[:2]})

    def test_invalid_cue_file_cues_null(self):
        bad = [list(reversed(CUES)), CUES[:-1] + [{"t_s": 42.5, "kind": "end"}], [{"t_s": i, "kind": "google"} for i in range(13)],
               CUES[:-1] + [{"t_s": 40, "kind": "tiktok"}], [{"t_s": -1, "kind": "google"}], [{"t_s": "3", "kind": "google"}],
               [{"t_s": True, "kind": "google"}], [3], {"t_s": 3, "kind": "google"}, None]
        for cues in bad:
            self.cues({"duration_s": 42, "cues": cues})
            self.assertEqual(self.video(), {"duration_s": 42, "has_poster": True, "cues": None}, cues)
        self.cues({"duration_s": 42, "cues": [{"t_s": i, "kind": "x"} for i in range(12)]})
        self.assertEqual(len(self.video()["cues"]), 12)
        for doc in ({"duration_s": 0, "cues": CUES}, {"cues": CUES}, {"duration_s": "42", "cues": CUES}, [], b"{not json"):
            self.cues(doc)
            self.assertIsNone(self.video(), doc)
        os.remove(os.path.join(self.dir, "cues.json"))
        self.assertIsNone(self.video())

    def test_nosniff_and_no_store_everywhere(self):
        os.remove(os.path.join(self.dir, "poster.webp"))
        cases = [self.raw(p)[1] for p in TYPES] + [self.raw("video", rng="bytes=0-9")[1], self.raw("video", rng="bytes=9999-")[1],
                                                    self.raw("poster")[1], self.raw("nope")[1]]
        cases.append(self.req("GET", "/v1/offer-video/video")[1])
        cases.append(self.req("POST", "/v1/offer-video/video", {}, self.a)[1])
        self.assertEqual([r.status for r in cases], [200, 404, 200, 206, 416, 404, 404, 401, 405])
        for r in cases:
            self.assertEqual((r.getheader("X-Content-Type-Options"), r.getheader("Cache-Control")), ("nosniff", "no-store"), r.status)

    def test_head_and_other_methods_never_serve(self):
        for part in (*TYPES, "nope"):
            for m, key, want in (("HEAD", None, 401), ("HEAD", self.a, 405), ("PUT", None, 401),
                                 ("DELETE", self.a, 405)):
                c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
                c.request(m, f"/v1/offer-video/{part}", headers={"Authorization": f"Bearer {key}"} if key else {})
                r = c.getresponse()
                data = r.read()
                c.close()
                self.assertEqual(r.status, want, (m, part))
                self.assertNotEqual(r.getheader("Content-Type"), TYPES.get(part, ("",))[0], (m, part))
                self.assertNotIn(b"WEBVTT", data)
                self.assertEqual(data[:4] if m != "HEAD" else data, b'{"er' if m != "HEAD" else b"", (m, part))

    def test_401_no_key(self):
        for part in TYPES:
            st, r, b = self.req("GET", f"/v1/offer-video/{part}")
            self.assertEqual((st, b, r.getheader("WWW-Authenticate")), (401, {"error": "unauthorized"}, "Bearer"), part)
            self.assertEqual(self.req("GET", f"/v1/offer-video/{part}", key="ltk_" + "x" * 40)[0], 401)


if __name__ == "__main__":
    unittest.main()

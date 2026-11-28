"""Media Leaks (Phase 2 ticket 28): images / videos results of the full Google pass become `media` Leaks beside their
landing page's, from the pages the pass already loads (FakePW tiles, see test_tracker_google.tile), with the tile's
thumbnail kept only through tracker_preview.store_thumb; the pill follows the landing Leak's Origin status; the stub
fetcher records every URL the probe asks for. No real network, no paid call. Fictional creators only."""
import base64
import json
import os
from unittest import mock

from tracker_fixture import tdb, tracker_stub_fetch
from test_tracker_google import CREATE, Google, at
from test_tracker_lanes import SITE
from test_tracker_serp import fixture
import tracker_budget
import tracker_lanes
import tracker_probe
import tracker_report
import tracker_serp

IMG, VID = f"{SITE}/gallery/mia_vale-i1", f"{SITE}/clip/mia_vale-v1"
THUMB = "https://encrypted-tbn0.gstatic.com/images?q=tbn:mia-i1"
VTHUMB = "https://i.ytimg.com/vi/mia-v1/default.jpg"


class Media(Google):
    def media(self, url, vertical="images"):
        r = self.rows("SELECT * FROM leaks WHERE watch_id = ? AND kind = 'media' AND url_key LIKE ?", self.w,
                      f"%#google_{vertical}")
        return next((x for x in r if x["url"] == url), None)

    def items(self):
        return {(x["url"], x["kind"]): x for x in self.get(f"/v1/creators/{self.w}/leaks")[1]["leaks"]}

    def landing(self, url):
        return self.rows("SELECT leak_id FROM leaks WHERE watch_id = ? AND url = ? AND kind = 'page'", self.w,
                         url)[0]["leak_id"]

    def probe(self, d, status):
        self.clock(at(d))
        self.answers({IMG: status})
        tracker_probe.run([self.w])


class TestMediaLeaks(Media):
    def test_images_loads_block_fonts_and_media_and_tiles_keep_their_thumbs(self):
        self.pw.links[("images", '"mia_vale"')] = [(IMG, "Mia pics", THUMB)]
        self.day(2)
        blocks = dict(zip((u for _, u in self.pw.navs), self.pw.blocks))
        isch = [u for u in blocks if "tbm=isch" in u]
        self.assertTrue(isch)
        for u in isch:
            self.assertEqual(blocks[u].keywords, {"types": {"media", "font"}})
        self.assertEqual([b for _, b in self.bb.creates], [CREATE] * len(self.bb.creates))
        self.assert_charged()
        self.assertEqual(self.media(IMG)["thumb_url"], THUMB)
        self.assertEqual(tracker_serp.serp_results(fixture("google_images_mia.html")), [
            ("https://leaksite.example/mia_vale/gallery/3", "Mia Vale gallery leaksite.example", None),
            ("https://pics.example/p/mia-vale-2", "Mia Vale post two", None),
            ("https://img.example/s/3", "Rowan Ash alt text", "https://encrypted-tbn0.gstatic.com/images?q=tbn:x"),
            ("https://board.example/t/4", "Mia Vale set four", None),
            ("https://quiet.example/q/5", "", None)])

    def test_media_result_stores_a_media_leak_with_landing_key_and_the_suffix(self):
        self.pw.links.update({("images", '"mia_vale"'): [(IMG, "Mia pics", THUMB), (f"{SITE}/post/1", "unrelated"),
                                                         (f"{SITE}/post/2", "mia_vale set")],
                              ("videos", '"mia_vale"'): [(VID, "Mia clip", VTHUMB)]})
        self.day(2)
        img, vid = self.media(IMG), self.media(VID, "videos")
        self.assertEqual({k: img[k] for k in ("url_key", "landing_key", "leak_site", "title", "thumb_url",
                                              "thumb_query_id", "thumb_seen_at")},
                         {"url_key": "leaksite.example/gallery/mia_vale-i1#google_images",
                          "landing_key": "leaksite.example/gallery/mia_vale-i1", "leak_site": "leaksite.example",
                          "title": "Mia pics", "thumb_url": THUMB, "thumb_query_id": "images|handle",
                          "thumb_seen_at": at(2)})
        self.assertEqual((vid["url_key"], vid["landing_key"], vid["thumb_url"]),
                         ("leaksite.example/clip/mia_vale-v1#google_videos", "leaksite.example/clip/mia_vale-v1", None))
        self.assertEqual(len(self.rows("SELECT * FROM leaks WHERE kind = 'media'")), 2)
        self.assertEqual(self.rows("SELECT url FROM pending_hits"), [{"url": f"{SITE}/post/2"}])
        items = self.items()
        self.assertEqual({k: items[(IMG, "media")][k] for k in ("leak_site", "kind", "title", "sources",
                                                                "found_on_first_scan", "preview")},
                         {"leak_site": "leaksite.example", "kind": "media", "title": "Mia pics",
                          "sources": ["google_images"], "found_on_first_scan": True,
                          "preview": {"vertical": "images", "seen_at": at(2)}})
        self.assertEqual(items[(VID, "media")]["sources"], ["google_videos"])
        self.assertEqual(json.loads(img["google_fields_json"]), [["images", "handle"]])
        later = f"{SITE}/gallery/mia_vale-i2"
        self.pw.links[("images", '"mia_vale"')] = [(IMG, "Mia pics", THUMB), (later, "Mia more", THUMB + "2")]
        self.day(9)
        self.assertEqual(len(self.rows("SELECT * FROM leaks WHERE kind = 'media'")), 3)
        self.assertEqual(self.media(IMG)["thumb_seen_at"], at(9))
        self.assertFalse(self.items()[(later, "media")]["found_on_first_scan"])

    def test_pill_follows_the_landing_leaks_origin_status(self):
        self.pw.links[("images", '"mia_vale"')] = [(IMG, "Mia pics", THUMB)]
        self.day(2)
        pills = lambda: (self.items()[(IMG, "page")]["pill"], self.items()[(IMG, "media")]["pill"])
        self.assertEqual(pills(), ("not_checked", "not_checked"))
        self.probe(3, 200)
        self.assertEqual(pills(), ("live", "live"))
        media = self.items()[(IMG, "media")]
        self.assertEqual((media["origin_status"], media["last_probe_at"]), ("live", at(3)))
        self.assertEqual(tracker_report.counts(self.t)["pills"]["live"], 2)
        self.probe(4, 404)
        self.probe(5, 404)
        self.assertEqual(pills(), ("cached", "cached"))
        self.pw.links.clear()
        self.day(9)
        self.assertEqual(pills(), ("gone", "gone"))
        self.assertEqual(tracker_report.counts(self.t)["pills"]["gone"], 2)
        self.assertEqual(self.items()[(IMG, "media")]["preview"], None)

    def test_the_stub_records_no_request_to_the_media_url(self):
        self.pw.links.update({("images", '"mia_vale"'): [(IMG, "Mia pics", THUMB)],
                              ("videos", '"mia_vale"'): [(VID, "Mia clip", VTHUMB)]})
        self.day(2)
        self.assertEqual(tracker_stub_fetch.CALLS, [])
        self.clock(at(3))
        tracker_probe.run([self.w])
        self.assertEqual(sorted(tracker_stub_fetch.CALLS), sorted([IMG, VID]))
        self.assertNotIn(THUMB, str(self.pw.navs))
        self.assertEqual(self.rows("SELECT * FROM probe_state p JOIN leaks l ON l.leak_id = p.leak_id "
                                   "WHERE l.kind = 'media'"), [])
        self.assert_charged()

    def test_media_adds_no_reserve_call(self):
        calls = []
        real = tracker_budget.reserve

        def spy(*a, **kw):
            calls.append((a, kw))
            return real(*a, **kw)

        with mock.patch.object(tracker_lanes.tracker_budget, "reserve", spy):
            self.day(2)
            plain = (list(calls), self.used(), len(self.pw.navs))
            calls.clear()
            self.pw.links.update({("images", '"mia_vale"'): [(IMG, "Mia pics", THUMB)],
                                  ("videos", '"mia_vale"'): [(VID, "Mia clip", VTHUMB)]})
            self.day(9)
        self.assertEqual(len(self.rows("SELECT * FROM leaks WHERE kind = 'media'")), 2)
        self.assertEqual(calls, plain[0])
        self.assertEqual((self.used() - plain[1], len(self.pw.navs) - plain[2]), (plain[1], plain[2]))
        self.assert_charged()

    def test_a_refused_thumb_still_creates_the_leak_with_preview_null(self):
        other, data = f"{SITE}/gallery/mia_vale-i3", f"{SITE}/gallery/mia_vale-i4"
        self.pw.links[("images", '"mia_vale"')] = [(IMG, "Mia pics", "https://cdn.example/mia-i1.jpg"),
                                                   (other, "Mia set", "http://encrypted-tbn0.gstatic.com/x"),
                                                   (data, "Mia data", "data:image/gif;base64,R0lGOD")]
        self.day(2)
        for u in (IMG, other, data):
            self.assertEqual((self.media(u)["thumb_url"], self.items()[(u, "media")]["preview"]), (None, None), u)
        cached = self.rows("SELECT results_json FROM serp_cache WHERE vertical = 'images' AND text = '\"mia_vale\"' "
                           "AND page = 0")[0]["results_json"]
        self.assertEqual(json.loads(cached), [[IMG, "Mia pics"], [other, "Mia set"], [data, "Mia data"]])
        self.assertNotIn("cdn.example", cached)

    def test_data_tiles_store_decoded_thumbs_and_bad_ones_none(self):
        jpg = b"\xff\xd8\xff\xe0" + b"\0" * 128
        good = "data:image/jpeg;base64," + base64.b64encode(jpg).decode()
        bad = {"svg": "data:image/svg+xml;base64,PHN2Zy8+", "html": "data:text/html;base64,PGI+eDwvYj4=",
               "mismatch": "data:image/png;base64," + base64.b64encode(jpg).decode(), "raw": "data:image/jpeg,xyz",
               "junk": "data:image/jpeg;base64,@@@@", "placeholder": "data:image/gif;base64,R0lGODlhAQABAIAAAP///////yH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="}
        urls = {k: f"{SITE}/gallery/mia_vale-{k}" for k in ("good", *bad)}
        self.pw.links[("images", '"mia_vale"')] = [(urls["good"], "Mia good", good)] + [
            (urls[k], f"Mia {k}", v) for k, v in bad.items()]
        self.day(2)
        items = self.items()
        self.assertEqual((bytes(self.media(urls["good"])["thumb_blob"]), self.media(urls["good"])["thumb_mime"]),
                         (jpg, "image/jpeg"))
        self.assertIsNotNone(items[(urls["good"], "media")]["preview"])
        for k in bad:
            m = self.media(urls[k])
            self.assertEqual((m["thumb_blob"], m["thumb_url"], items[(urls[k], "media")]["preview"]), (None, None, None), k)
        cached = self.rows("SELECT results_json FROM serp_cache WHERE vertical = 'images' AND text = '\"mia_vale\"' "
                           "AND page = 0")[0]["results_json"]
        self.assertEqual(json.loads(cached), [[urls["good"], "Mia good", good]] + [[urls[k], f"Mia {k}"] for k in bad])

    def test_a_new_images_landing_counts_once_as_new(self):
        base = [(f"{SITE}/gallery/mia_vale-i0", "Mia pics zero")]
        self.pw.links[("images", '"mia_vale"')] = base
        self.day(2)
        before = self.get(f"/v1/creators/{self.w}")[1]
        self.pw.links[("images", '"mia_vale"')] = base + [(IMG, "Mia pics", THUMB)]
        self.day(9)
        after = self.get(f"/v1/creators/{self.w}")[1]
        self.assertEqual(len(self.rows("SELECT * FROM leaks WHERE kind = 'media'")), 2)
        self.assertEqual((before["this_week"]["new"], before["offer_counts"]["new_7d"]), (0, 0))
        self.assertEqual((after["this_week"]["new"], after["offer_counts"]["new_7d"]), (1, 1))
        self.assertEqual((before["this_week"]["first_scan"], after["counts"]["new_today"]), (1, 1))

    def test_removed_alias_clears_its_media_thumb(self):
        self.pw.links[("images", '"miavale_x"')] = [(IMG, "Mia pics", THUMB)]
        self.day(2)
        self.assertEqual(self.media(IMG)["thumb_query_id"], "images|alias:miavalex")
        with tdb.db() as c:
            c.execute("UPDATE watches SET aliases_json = ? WHERE watch_id = ?", (json.dumps(["miav"]), self.w))
        self.day(9)
        self.assertIsNone(self.media(IMG)["thumb_url"])
        self.assertIsNotNone(self.media(IMG))

    def test_previews_off_store_the_thumb_and_serve_none(self):
        self.pw.links[("images", '"mia_vale"')] = [(IMG, "Mia pics", THUMB)]
        with mock.patch.dict(os.environ, TRACKER_PREVIEWS="0"):
            self.day(2)
            self.assertIsNone(self.items()[(IMG, "media")]["preview"])
        self.assertEqual(self.media(IMG)["thumb_url"], THUMB)

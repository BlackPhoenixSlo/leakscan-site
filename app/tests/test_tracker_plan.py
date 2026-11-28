"""tracker_plan: identity -> full-pass plan, loads, trim order (spec Service seams, ticket 21).
Pure, fictional Creators only."""
import json
import os
import sys
import unittest
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tracker_admission
import tracker_plan as tp
from tracker_plan import QuerySpec

H = '"mia_vale"'
STRONG = ["rowanash", "vale.mia", "mia-official", "miavee", "rowan_mia"]


def ident(aliases=(), instagram=None, x=None, username="mia_vale", display_name="Juniper Sol"):
    return {"username": username, "aliases_json": json.dumps(list(aliases)), "instagram": instagram, "x": x,
            "display_name": display_name, "platform": "onlyfans"}


def rows(plan):
    return [(q.vertical, q.text, q.pages, q.field) for q in plan.queries]


HANDLE_ROWS = [("web", H, 2, "handle"), ("web", H + " leaked", 2, "handle"), ("web", H + " onlyfans", 1, "handle"),
               ("images", H, 1, "handle"), ("videos", H, 1, "handle"), ("web", H + " mega.nz", 1, "handle"),
               ("web", H + " site:t.me", 1, "handle")]
FULL = ident(STRONG, instagram="mia.vale.ig", x="miavale_x")


class TestBuild(unittest.TestCase):
    def test_handle_only_plan(self):
        p = tp.build(ident(), "onlyfans")
        self.assertEqual(rows(p), HANDLE_ROWS)
        self.assertEqual(p.loads, 9)
        self.assertEqual({q.lane for q in p.queries}, {"google_full"})
        self.assertIn(("web", '"mia_vale" fansly', 1, "handle"), rows(tp.build(ident(), "fansly")))

    def test_loads_table(self):
        for name, identity, loads in (
                ("handle only", ident(), 9),
                ("instagram", ident(instagram="mia.vale.ig"), 10),
                ("instagram + x", ident(instagram="mia.vale.ig", x="miavale_x"), 11),
                ("1 strong", ident(["rowanash"]), 13),
                ("1 weak", ident(["miav"]), 10),
                ("5 strong", ident(STRONG), 29),
                ("5 strong + ig + x", FULL, 31),
                ("5 weak + ig + x", ident(["miav", "mvee", "rowa", "ashm", "valm"], "mia.vale.ig", "miavale_x"), 16),
                ("3 strong 2 weak + ig + x", ident(["rowanash", "miav", "miavee", "mvee", "vale.mia"], "ig_mia", "x_mia"), 25),
                ("username = ig = x", ident(instagram="mia_vale", x="mia_vale"), 9),
                ("ig, x norm()-equal handle", ident(instagram="mia.vale", x="MiaVale"), 9),
                ("x = ig", ident(instagram="rowan_ash", x="rowanash"), 10),
                ("alias = handle, alias dupes, ig = alias", ident(["mia.vale", "rowanash", "Rowan.Ash", "miav", "mi_av"],
                                                                  "rowanash", "miavale_x"), 15),
                ("alias norm() under 4", ident(["m.i.a"]), 9)):
            with self.subTest(name):
                self.assertEqual(tp.build(identity, "onlyfans").loads, loads)
                self.assertLessEqual(loads, tracker_admission.PLAN_MAX)

    def test_strong_alias_alone_in_web_images_videos(self):
        p = tp.build(ident(["rowanash"]), "onlyfans")
        self.assertEqual(rows(p)[7:], [("web", '"rowanash"', 1, "alias:0"), ("web", '"rowanash" leaked', 1, "alias:0"),
                                       ("images", '"rowanash"', 1, "alias:0"), ("videos", '"rowanash"', 1, "alias:0")])

    def test_weak_alias_only_beside_handle(self):
        for alias in ("miav", "vee.x"):
            with self.subTest(alias):
                p = tp.build(ident([alias]), "onlyfans")
                self.assertEqual(rows(p)[7:], [("web", f'{H} "{alias}"', 1, "alias:0")])
                self.assertTrue(all(H in q.text for q in p.queries if alias in q.text))

    def test_instagram_and_x_in_web_only(self):
        p = tp.build(ident(instagram="mia.vale.ig", x="miavale_x"), "onlyfans")
        self.assertEqual(rows(p)[7:], [("web", '"mia.vale.ig"', 1, "instagram"), ("web", '"miavale_x"', 1, "x")])

    def test_dedup_keeps_first(self):
        p = tp.build(ident(["mia.vale", "rowanash", "Rowan.Ash", "miav", "mi_av"], "rowanash", "miavale_x"), "onlyfans")
        self.assertEqual(p.values, {"handle": "mia_vale", "alias:1": "rowanash", "alias:3": "miav", "x": "miavale_x"})

    def test_display_name_absent_everywhere(self):
        for identity in (ident(display_name="Juniper Sol"), FULL | {"display_name": "Juniper Sol"},
                         ident(["miav"], "mia.vale.ig", "miavale_x", display_name="Juniper Sol")):
            p = tp.build(identity, "onlyfans")
            self.assertFalse([q.text for q in p.queries if "Juniper" in q.text or "Sol" in q.text])
            self.assertNotIn("display_name", {q.field for q in p.queries})

    def test_urls(self):
        p = tp.build(ident(), "onlyfans")
        web, images = p.queries[0], p.queries[3]
        self.assertEqual([parse_qs(urlsplit(u).query)["start"] for u in web.urls()], [["0"], ["10"]])
        self.assertEqual([parse_qs(urlsplit(u).query)["tbm"] for u in images.urls()], [["isch"]])
        self.assertEqual(QuerySpec("google_full", "web", H, 1, "handle", start=1).urls()[0],
                         web.urls()[1])


class TestTrim(unittest.TestCase):
    def test_trim_order(self):
        p = tp.build(FULL, "onlyfans")
        a = [{"field": f"alias:{i}", "value": v} for i, v in enumerate(STRONG)]
        x, ig = {"field": "x", "value": "miavale_x"}, {"field": "instagram", "value": "mia.vale.ig"}
        groups = [a[4], a[3], a[2], a[1], a[0], x, ig]
        cuts = [(H + " site:t.me", 0), (H + " mega.nz", 0), ("videos " + H, 0), ("images " + H, 0),
                (H + " onlyfans", 0), (H + " leaked", 0), (H, 1)]
        full = p.queries
        for n, loads, dropped, cut in (
                (99, 31, [], []), (31, 31, [], []), (30, 27, groups[:1], []), (27, 27, groups[:1], []),
                (26, 23, groups[:2], []), (12, 11, groups[:5], []), (11, 11, groups[:5], []), (10, 10, groups[:6], []),
                (9, 9, groups, []), (8, 8, groups, cuts[:1]), (7, 7, groups, cuts[:2]), (6, 6, groups, cuts[:3]),
                (5, 5, groups, cuts[:4]), (4, 4, groups, cuts[:5]), (3, 2, groups, cuts[:6]), (2, 2, groups, cuts[:6]),
                (1, 1, groups, cuts)):
            with self.subTest(n=n):
                t = p.trim(n)
                self.assertEqual(t.plan.loads, loads)
                self.assertEqual(t.dropped, dropped)
                groups_cut = [q for d in dropped for q in full if q.field == d["field"]]
                self.assertEqual(t.cut[:len(groups_cut)], groups_cut)
                self.assertEqual([(q.text if q.vertical == "web" else f"{q.vertical} {q.text}", q.start)
                                  for q in t.cut[len(groups_cut):]], cut)
                self.assertEqual(t.plan.loads + sum(q.pages for q in t.cut), 31)
                self.assertEqual(set(t.plan.values), {"handle"} | {q.field for q in t.plan.queries})
                self.assertEqual(t.plan.trim(n).dropped, [], "trimming twice reports no drop again")

    def test_trim_1_is_handle_web_page_1(self):
        for identity in (ident(), FULL):
            with self.subTest(identity["aliases_json"]):
                t = tp.build(identity, "onlyfans").trim(1)
                self.assertEqual(t.plan.queries, (QuerySpec("google_full", "web", H, 1, "handle"),))
                self.assertEqual(t.cut[-1], QuerySpec("google_full", "web", H, 1, "handle", start=1))

    def test_trim_0_is_empty(self):
        t = tp.build(FULL, "onlyfans").trim(0)
        self.assertEqual((t.plan.queries, t.plan.loads), ((), 0))
        self.assertEqual(t.dropped[-1], {"field": "handle", "value": "mia_vale"})
        self.assertEqual(t.plan.values, {})
        self.assertEqual(sum(q.pages for q in t.cut), 31)
        self.assertEqual(t.cut[-1], QuerySpec("google_full", "web", H, 1, "handle"))

    def test_weak_and_strong_aliases_drop_last_added_first(self):
        p = tp.build(ident(["rowanash", "miav", "miavee"]), "onlyfans")
        self.assertEqual(p.loads, 18)
        self.assertEqual(p.trim(14).dropped, [{"field": "alias:2", "value": "miavee"}])
        self.assertEqual(p.trim(13).dropped, [{"field": "alias:2", "value": "miavee"}, {"field": "alias:1", "value": "miav"}])

    def test_trim_keeps_plan_order(self):
        t = tp.build(FULL, "onlyfans").trim(19)
        self.assertEqual(rows(t.plan)[:7], HANDLE_ROWS)
        self.assertEqual([q.field for q in t.plan.queries[7:]], ["alias:0"] * 4 + ["alias:1"] * 4 + ["instagram", "x"])


if __name__ == "__main__":
    unittest.main()

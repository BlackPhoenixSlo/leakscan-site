"""tracker_serp (vendored Google SERP URL builder, page classifier, link parser, query templates) on synthetic markup
and saved fictional SERPs; the expected items are what leakhunt 7ccbdd3's bs4 parser gives on the same pages."""
import os
import sys
import unittest
from urllib.parse import parse_qs, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import tracker_serp as ts
from tracker_serp import classify_serp, serp_results, serp_url

G = "https://www.google.com"
FIXTURES = os.path.join(HERE, "fixtures")


def fixture(name, sub="tracker_serp"):
    with open(os.path.join(FIXTURES, sub, name), encoding="utf-8") as f:
        return f.read()


def links(html):
    return [(u, t) for u, t, _ in serp_results(html)]


def result(href, title=""):
    return f'<div class="g"><a href="{href}"><h3>{title}</h3></a></div>' if title else f'<a href="{href}">x</a>'


def chrome():
    return ('<a href="/search?q=x&tbm=isch">Images</a><a href="https://policies.google.com/privacy">Privacy</a>'
            '<a href="https://support.google.com/websearch">Help</a><a href="https://accounts.google.com/x">Sign in</a>'
            '<a href="https://www.gstatic.com/a.js">g</a><a href="https://schema.org/WebPage">s</a>')


def serp(*results):
    return f"<html><body><div id='rso'>{''.join(results)}</div>{chrome()}</body></html>"


NO_RESULTS = serp("<p>Your search - <b>\"miavale\"</b> - did not match any documents.</p>")
SORRY = "<html><body>Our systems have detected unusual traffic from your computer network.</body></html>"
CONSENT = "<html><body><form action='https://consent.google.com/save'><button>Accept all</button></form></body></html>"
SHELL_ONLY = "<html><body><div id='search'><div id='center_col'></div></div></body></html>"
JS_WALL = ("<html><head><title>Google Search</title></head><body><noscript><meta http-equiv='refresh' "
           "content='0;url=/httpservice/retry/enablejs'></noscript>Please click here</body></html>")
CAPTCHA_200 = "<html><body><div id='recaptcha'></div><form id='captcha-form' action='index'></form></body></html>"


class Parser(unittest.TestCase):
    def test_web_links_unwrap_url_q_keep_goto_and_drop_google_chrome(self):
        html = serp(result(f"{G}/url?q=https://example-e.test/a%3Fx%3D1&sa=U", "Mia A"),
                    result("/goto?url=CAESEnc", "Mia B"),
                    result("https://example-f.test/b", "Mia C"), result("https://example-f.test/b", ""),
                    result("https://example-g.test/clip.mp4", "media"),
                    '<div><h3>Mia D</h3><span><a href="https://example-h.test/d">more</a></span></div>',
                    result("https://example-i.test/i"))
        self.assertEqual(links(html), [
            ("https://example-e.test/a?x=1", "Mia A"), (f"{G}/goto?url=CAESEnc", "Mia B"),
            ("https://example-f.test/b", "Mia C"), ("https://example-h.test/d", "Mia D"),
            ("https://example-i.test/i", "")])

    def test_images_links_come_from_landing_page_metadata(self):
        html = serp('<div data-lpage="https://example-e.test/gallery/1"><img src="data:x"></div>',
                    result(f"{G}/imgres?imgurl=https://cdn.test/p.jpg&imgrefurl=https://example-f.test/post/2"),
                    result("https://cdn.test/full.jpg"))
        self.assertEqual([u for u, _ in links(html)],
                         ["https://example-e.test/gallery/1", "https://example-f.test/post/2"])

    def test_images_tiles_carry_their_caption_aria_label_or_alt_as_title(self):
        html = serp('<div data-lpage="https://example-e.test/gallery/1"><img src="data:x" alt="">'
                    '<div>Mia Vale gallery</div><span>example-e.test</span></div>',
                    '<div data-lpage="https://example-f.test/post/2" aria-label="Mia post  two"><img alt="no"></div>',
                    '<div data-lpage="https://example-g.test/p/3"><a href="https://example-g.test/p/3">'
                    '<img src="data:x" alt="Mia alt text"></a></div>',
                    f'<a href="{G}/imgres?imgurl=https://cdn.test/p.jpg&imgrefurl=https://example-h.test/s/4" '
                    'title="Mia set four"><img src="data:x"></a>',
                    '<div data-lpage="https://example-i.test/q/5"><img src="data:x"></div>')
        self.assertEqual(links(html), [
            ("https://example-e.test/gallery/1", "Mia Vale gallery example-e.test"),
            ("https://example-f.test/post/2", "Mia post two"), ("https://example-g.test/p/3", "Mia alt text"),
            ("https://example-h.test/s/4", "Mia set four"), ("https://example-i.test/q/5", "")])

    def test_videos_keep_watch_pages_and_drop_account_pages(self):
        html = serp(result("https://www.youtube.com/watch?v=abc", "Mia clip"),
                    result("https://accounts.youtube.com/accounts/SetSID"), result("https://www.youtube.com/account"),
                    result("https://vids.test/v/9", "Mia on vids"))
        self.assertEqual(links(html), [("https://www.youtube.com/watch?v=abc", "Mia clip"),
                                            ("https://vids.test/v/9", "Mia on vids")])

    def test_thumbs_are_the_results_own_https_image(self):
        t = "https://encrypted-tbn0.gstatic.com/images?q=tbn:"
        html = serp(f'<div data-lpage="https://example-e.test/g/1"><img src="data:x" data-src="{t}e"></div>',
                    f'<div class="g"><a href="https://example-f.test/v/2"><h3>Mia clip</h3></a><img src="{t}f"></div>',
                    f'<div class="g"><a href="https://example-g.test/v/3"><h3>Mia two</h3></a><img src="{t}g1">'
                    f'<img src="{t}g2"></div>',
                    '<div class="g"><a href="https://example-h.test/v/4"><h3>Mia http</h3></a>'
                    '<img src="http://example-h.test/t.jpg"></div>')
        self.assertEqual([(u, th) for u, _, th in serp_results(html)],
                         [("https://example-e.test/g/1", f"{t}e"), ("https://example-f.test/v/2", f"{t}f"),
                          ("https://example-g.test/v/3", None), ("https://example-h.test/v/4", None)])

    def test_a_result_never_takes_its_neighbours_thumb(self):
        t = "https://encrypted-tbn0.gstatic.com/images?q=tbn:"
        html = serp('<div><div class="g"><a href="https://example-a.test/v/1"><h3>Mia one</h3></a></div>'
                    f'<div class="g"><a href="https://example-b.test/v/2"><h3>Mia two</h3></a><img src="{t}b"></div>'
                    '</div>')
        self.assertEqual([(u, th) for u, _, th in serp_results(html)],
                         [("https://example-a.test/v/1", None), ("https://example-b.test/v/2", f"{t}b")])

    def test_script_style_template_text_and_comments_are_no_title(self):
        html = serp('<div class="g"><a href="https://a.example/1"><h3>Mia<!-- c --> Vale<script>x()</script>'
                    '<template><b>hidden</b></template><style>.a{}</style></h3></a></div>')
        self.assertEqual(links(html), [("https://a.example/1", "Mia Vale")])

    def test_deep_markup_does_not_hit_the_recursion_limit(self):
        html = serp("<div>" * 3000 + result("https://deep.example/v/1", "Mia deep") + "</div>" * 3000)
        self.assertEqual(links(html), [("https://deep.example/v/1", "Mia deep")])


class SavedPages(unittest.TestCase):
    def test_web(self):
        html = fixture("google_web_mia.html")
        self.assertEqual(classify_serp(f"{G}/search?q=x", html), "results")
        self.assertEqual(links(html), [
            ("https://leaksite.example/mia_vale/12?ref=g", "Mia\xa0Vale  leaked set 12"),
            ("https://tube.example/v/mia-vale-solo", "Mia Vale solo clip"),
            ("https://forum.example/threads/mia-vale.123/", "Rowan Ash forum thread"),
            ("https://forum.example/t/miavale", ""),
            ("https://www.google.com/goto?url=CAESEmia", "Mia Vale goto title"),
            ("https://foreign.example/mia-vale", ""),
            ("https://www.youtube.com/watch?v=mia01", "Mia Vale interview")])

    def test_images(self):
        html = fixture("google_images_mia.html")
        self.assertEqual(classify_serp(f"{G}/search?q=x&tbm=isch", html), "results")
        self.assertEqual(links(html), [
            ("https://leaksite.example/mia_vale/gallery/3", "Mia Vale gallery leaksite.example"),
            ("https://pics.example/p/mia-vale-2", "Mia Vale post two"),
            ("https://img.example/s/3", "Rowan Ash alt text"),
            ("https://board.example/t/4", "Mia Vale set four"),
            ("https://quiet.example/q/5", "")])

    def test_videos(self):
        html = fixture("google_videos_mia.html")
        self.assertEqual(classify_serp(f"{G}/search?q=x&tbm=vid", html), "results")
        self.assertEqual(links(html), [
            ("https://www.youtube.com/watch?v=mia42", "Mia Vale backstage"),
            ("https://vids.example/v/9/mia-vale", "Mia Vale on vids"),
            ("https://clips.example/watch/rowan-ash-77", "Rowan Ash clip 77"),
            ("https://www.google.com/goto?url=CAESEvid", "Mia Vale goto clip")])

    def test_the_sources_redacted_pages(self):
        web = fixture("google_web_results.html")
        self.assertEqual(links(web), [("https://www.google.com/goto?url=RESULT-A", "PLACEHOLDER A"),
                                           ("https://www.google.com/goto?url=TRANSLATE-A", "PLACEHOLDER A"),
                                           ("https://www.google.com/goto?url=RESULT-B", "PLACEHOLDER B")])
        self.assertEqual(links(fixture("google_images_empty.html")), [])

    def test_the_quick_scans_saved_pages_parse_the_same(self):
        web, images = links(fixture("google_web.html", "")), links(fixture("google_images.html", ""))
        self.assertEqual((len(web), web[0]), (8, ("https://www.google.com/goto?url=CAESVwHEIkXX",
                                                  "Mira Example (@mira.example) • Instagram photos and videos")))
        self.assertEqual((len(images), images[0]),
                         (7, ("https://www.instagram.com/p/AAA/", "Mira Example on Instagram")))


class Classify(unittest.TestCase):
    def test_classify_serp(self):
        for url, html, kind in [
            ("https://consent.google.com/ml?continue=x", CONSENT, "consent"),
            (f"{G}/sorry/index?continue=x", "<html>captcha</html>", "captcha"),
            (f"{G}/search?q=x", SORRY, "captcha"),
            (f"{G}/search?q=x", NO_RESULTS, "no_results"),
            (f"{G}/search?q=x", serp(result("https://a.test/1", "Mia 1")), "results"),
            (f"{G}/search?q=x", serp(result("https://a.test/1", "unusual traffic")), "results"),
            (f"{G}/search?q=x", fixture("google_web_results.html"), "results"),
            (f"{G}/search?q=x&tbm=isch", fixture("google_images_empty.html"), "no_results"),
            (f"{G}/search?q=x&tbm=isch", SHELL_ONLY, "no_results"),
            (f"{G}/search?q=x", CAPTCHA_200, "captcha"),
            (f"{G}/search?q=x", JS_WALL, "unknown"),
            (f"{G}/search?q=x", "<html><body></body></html>", "unknown"),
        ]:
            with self.subTest(kind=kind, html=html[:60]):
                self.assertEqual(classify_serp(url, html), kind)


class NoResultsWording(unittest.TestCase):
    def test_per_vertical_only_googles_wording_confirms_empty(self):
        web_empty = "<html><body><div id='search'><p>Your search - <b>\"rowan_ash\"</b> - did not match any documents.</p></div></body></html>"
        vid_empty = web_empty.replace("rowan_ash", "mia_vale leaked")
        for vertical, url, empty, full in [
            ("web", f"{G}/search?q=x", web_empty, fixture("google_web_mia.html")),
            ("images", f"{G}/search?q=x&tbm=isch", fixture("google_images_empty.html"), fixture("google_images_mia.html")),
            ("videos", f"{G}/search?q=x&tbm=vid", vid_empty, fixture("google_videos_mia.html")),
        ]:
            with self.subTest(vertical=vertical):
                self.assertEqual((classify_serp(url, empty), ts.says_no_results(empty), links(empty)),
                                 ("no_results", True, []))
                self.assertEqual((classify_serp(url, SHELL_ONLY), ts.says_no_results(SHELL_ONLY)), ("no_results", False))
                self.assertEqual((classify_serp(url, full), ts.says_no_results(full)), ("results", False))


class Url(unittest.TestCase):
    def test_serp_url_parameters(self):
        q = parse_qs(urlsplit(serp_url('"mia vale"', "web", 2, "w")).query)
        self.assertEqual(q, {"q": ['"mia vale"'], "safe": ["off"], "hl": ["en"], "num": ["10"], "start": ["20"],
                             "tbs": ["qdr:w"]})
        self.assertEqual(parse_qs(urlsplit(serp_url("x", "videos", 1)).query)["tbm"], ["vid"])
        q = parse_qs(urlsplit(serp_url("x", "images")).query)
        self.assertTrue(q["tbm"] == ["isch"] and "start" not in q)

    def test_past_day_filter(self):
        for vertical in ts.VERTICALS:
            url = serp_url('"mia vale" leaked', vertical, since="d")
            self.assertTrue(url.startswith("https://www.google.com/search?"))
            self.assertEqual(parse_qs(urlsplit(url).query)["tbs"], ["qdr:d"])
        self.assertNotIn("tbs", parse_qs(urlsplit(serp_url("x")).query))

    def test_query_templates(self):
        self.assertEqual([t.format(h="mia_vale") for t in ts.TEMPLATES],
                         ['"mia_vale"', '"mia_vale" leaked', '"mia_vale" onlyfans'])
        self.assertEqual([t.format(h="mia_vale") for t in ts.FILE_HOST_TEMPLATES],
                         ['"mia_vale" mega.nz', '"mia_vale" site:t.me'])
        self.assertEqual(ts.VERTICALS, ("web", "images", "videos"))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""End-to-end proof of the on-site free scan against the local stub (never the production API or jackbase.me).

    cd ~/leakhunt && uv run python ~/leakscan-site/tools/scan_e2e.py OUT_DIR [--omit-results]

Starts tools/scan_stub.py on a free port (--omit-results is passed through: break-it run), then for phone (390x844)
and desktop (1440x900): home → fill the hero form → submit → scan/?p=&h= → progress → report. Asserts summary numbers
equal the fixture, tab item counts (All 10 → all pages after "More results", Images ≤ 30, Videos), device toggle swaps
frames, Reveal unblurs, CTA hrefs carry the report link + handle, every hit URL is listed, `?r=<slug>` reopens without
a new scan, and the stub `failed` / 429 / busy / empty / not-found paths show their UI. Every non-loopback request is
aborted and must not happen at all. Screenshots of each state go to OUT_DIR. One PASS/FAIL line per check; exit 1 on
any FAIL.
"""
import json, pathlib, re, socket, subprocess, sys, time
from urllib.parse import parse_qs, quote, urlsplit
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
FX = json.loads((ROOT / "tools" / "fixtures" / "scan-sample.json").read_text())
REPORT_BASE = "https://blackphoenixslo.github.io/leakscan-site/scan/?r="
out = pathlib.Path(sys.argv[1]).expanduser()
out.mkdir(parents=True, exist_ok=True)
omit = "--omit-results" in sys.argv
fails = []

PAGES = [r for r in FX["results"] if r["kind"] != "video"]
VIDEOS = [r for r in FX["results"] if r["kind"] == "video"]
IMAGES = min(30, len(dict.fromkeys(FX["images"] + [r["thumb"] for r in FX["results"] if r["thumb"]])))


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name}{': ' + str(detail) if detail != '' else ''}", flush=True)
    if not ok:
        fails.append(name)


def digits(s):
    return int(re.sub(r"\D", "", s) or 0)


with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
stub = subprocess.Popen([sys.executable, str(ROOT / "tools" / "scan_stub.py"), "--port", str(port), "--delay", "0.25"]
                        + (["--omit-results"] if omit else []), stderr=subprocess.DEVNULL, stdout=subprocess.PIPE)
stub.stdout.readline()
base = f"http://127.0.0.1:{port}/"

try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for vp_name, vp in (("phone", {"width": 390, "height": 844}), ("desktop", {"width": 1440, "height": 900})):
            ctx = browser.new_context(viewport=vp, device_scale_factor=2 if vp_name == "phone" else 1,
                                      is_mobile=vp_name == "phone", has_touch=vp_name == "phone")
            outside, posts, errors = [], [], []

            def route(r, _req, outside=outside):
                if urlsplit(r.request.url).hostname in ("127.0.0.1", "localhost"):
                    r.continue_()
                else:
                    outside.append(r.request.url)
                    r.abort()

            ctx.route("**/*", route)
            page = ctx.new_page()
            page.on("request", lambda q, posts=posts: q.method == "POST" and posts.append(q.url))
            page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
            shot = lambda name, full=False, page=page, v=vp_name: page.screenshot(path=str(out / f"{v}-{name}.png"), full_page=full)

            # 1. home → form → scan page
            page.goto(base, wait_until="load")
            page.locator("#scan .scan-handle").fill("@demo.creator")
            page.locator("#scan select[name=p]").select_option("fansly.com")
            with page.expect_navigation(url=re.compile(r"/scan/\?")):
                page.locator("#scan button").click()
            q = parse_qs(urlsplit(page.url).query)
            check(f"{vp_name} lands on scan/?p=&h=", q.get("p") == ["fansly.com"] and q.get("h") == ["@demo.creator"], page.url)

            # 2. progress
            page.wait_for_selector("#progress-log li", timeout=5000)
            check(f"{vp_name} progress visible", page.locator("#progress").is_visible()
                  and "demo.creator" in page.locator("#scan-title").inner_text())
            shot("1-progress")

            # 3. report
            page.wait_for_selector("#report:not([hidden])", timeout=15000)
            page.wait_for_timeout(600)
            slug = parse_qs(urlsplit(page.url).query).get("r", [""])[0]
            check(f"{vp_name} url becomes ?r=<slug>", bool(re.fullmatch(r"[A-Za-z0-9]{12}", slug)), page.url)
            stat = lambda k: digits(page.locator(f"[data-stat={k}]").inner_text())
            got = (stat("domains"), stat("pages"), stat("google"))
            want = (FX["domain_count"], FX["hit_count"], FX["google_total"])
            check(f"{vp_name} summary numbers match fixture", got == want, f"{got} vs {want}")
            check(f"{vp_name} title shows handle", page.locator("#scan-title").inner_text() == "@demo.creator")
            shot("2-report-full", full=True)

            # 4. device + tabs (both devices, all three tabs)
            default = "phone" if vp_name == "phone" else "computer"
            check(f"{vp_name} default device {default}", page.locator(f".frame-{default}").count() == 1
                  and page.locator("#device input:checked").get_attribute("value") == default)
            for device in (default, "computer" if default == "phone" else "phone"):
                if page.locator("#device input:checked").get_attribute("value") != device:
                    page.locator(f"#device label:has(input[value={device}])").click()
                    page.wait_for_timeout(300)
                other = "computer" if device == "phone" else "phone"
                check(f"{vp_name} toggle shows {device} frame only", page.locator(f".frame-{device}").is_visible()
                      and page.locator(f".frame-{other}").count() == 0)
                if device == "computer":
                    check(f"{vp_name} computer url bar", "google.com/search?q=demo.creator+leaks" in page.locator(".bw-url").inner_text())
                    box = page.locator(".frame-computer").bounding_box()
                    check(f"{vp_name} computer frame fits viewport", box["x"] >= 0 and box["x"] + box["width"] <= vp["width"] + 1,
                          f"x={box['x']:.0f} w={box['width']:.0f}")
                g = page.locator("#google")
                # All
                page.locator("#g-tab-all").click()
                n0 = page.locator("#g-panel .g-r").count()
                page.evaluate("window.scrollTo(0, document.getElementById('google').offsetTop)")
                g.screenshot(path=str(out / f"{vp_name}-3-{device}-all.png"))
                for _ in range(10):
                    if page.locator("[data-more=all]").count() == 0:
                        break
                    page.locator("[data-more=all]").click()
                n1 = page.locator("#g-panel .g-r").count()
                check(f"{vp_name}/{device} All tab count", (n0, n1) == (min(10, len(PAGES)), len(PAGES)), f"{n0}→{n1} want 10→{len(PAGES)}")
                check(f"{vp_name}/{device} tab aria-selected", page.locator("#g-tab-all").get_attribute("aria-selected") == "true"
                      and page.locator("#g-tab-images").get_attribute("aria-selected") == "false")
                # Images
                page.locator("#g-tab-images").click()
                while page.locator("[data-more=images]").count():
                    page.locator("[data-more=images]").click()
                ni = page.locator("#g-panel .g-tile").count()
                check(f"{vp_name}/{device} Images tab count", ni == IMAGES, f"{ni} want {IMAGES}")
                page.wait_for_timeout(500)
                g.screenshot(path=str(out / f"{vp_name}-4-{device}-images.png"))
                # Videos
                page.locator("#g-tab-videos").click()
                nv = page.locator("#g-panel .g-v").count()
                check(f"{vp_name}/{device} Videos tab count", nv == len(VIDEOS), f"{nv} want {len(VIDEOS)}")
                page.wait_for_timeout(300)
                g.screenshot(path=str(out / f"{vp_name}-5-{device}-videos.png"))

            # 5. keyboard: arrow keys move between tabs
            page.locator("#g-tab-videos").focus()
            page.keyboard.press("ArrowLeft")
            check(f"{vp_name} ArrowLeft selects Images", page.locator("#g-tab-images").get_attribute("aria-selected") == "true"
                  and page.evaluate("document.activeElement.id") == "g-tab-images")

            # 6. reveal
            blur = lambda: page.eval_on_selector("#g-panel .g-img img", "e => getComputedStyle(e).filter")
            before = blur()
            page.locator("#reveal").click()
            page.wait_for_timeout(400)
            after = blur()
            check(f"{vp_name} blurred by default, Reveal unblurs", "blur" in before and after == "none"
                  and page.locator("#reveal").get_attribute("aria-pressed") == "true", f"{before} → {after}")
            page.locator("#google").screenshot(path=str(out / f"{vp_name}-6-revealed.png"))
            page.locator("#reveal").click()

            # 7. CTAs + links
            link = REPORT_BASE + slug
            hrefs = page.eval_on_selector_all("#send [data-msg]", "els => els.map(e => e.href)")
            check(f"{vp_name} CTA hrefs carry report link + handle", len(hrefs) == 3 and all(
                (quote(link, safe="") in h or quote(link, safe="").replace("%20", "+") in h) and "demo.creator" in h for h in hrefs)
                  and hrefs[0].startswith("https://t.me/jakabasej?text=") and hrefs[1].startswith("https://wa.me/38640703992?text=")
                  and hrefs[2].startswith("mailto:me@jackbase.dev?") and "body=" in hrefs[2], hrefs)
            deep = page.locator("#deep-link").get_attribute("href")
            check(f"{vp_name} deep-scan link", deep == "https://jackbase.me/scan?p=fansly.com&h=demo.creator&l=deep&go=1", deep)
            listed = set(page.eval_on_selector_all("#links-list a", "els => els.map(e => e.href)"))
            check(f"{vp_name} every hit url listed", all(h["url"] in listed for h in FX["hits"]),
                  f"{sum(h['url'] in listed for h in FX['hits'])}/{len(FX['hits'])}")
            check(f"{vp_name} per-site rows == domain_count", page.locator("#sites-body tr").count() == FX["domain_count"])
            page.locator("#send").scroll_into_view_if_needed()
            page.locator("#send").screenshot(path=str(out / f"{vp_name}-7-cta.png"))

            # 8. reopen ?r=<slug> in a fresh page: no new scan
            n_posts = len(posts)
            p2 = ctx.new_page()
            p2.on("request", lambda q, posts=posts: q.method == "POST" and posts.append(q.url))
            p2.goto(base + "scan/?r=" + slug)
            p2.wait_for_selector("#report:not([hidden])", timeout=5000)
            check(f"{vp_name} ?r= reopens without a new scan", len(posts) == n_posts
                  and digits(p2.locator("[data-stat=domains]").inner_text()) == FX["domain_count"])
            p2.screenshot(path=str(out / f"{vp_name}-8-reopen.png"))
            p2.close()

            # 9. error / empty paths
            for h, kind, want in (("stub-fail", "failed", "didn’t finish"), ("stub-429", "rate_limited", "limit"),
                                  ("stub-busy", "busy", "busy")):
                page.goto(base + f"scan/?p=onlyfans.com&h={h}")
                page.wait_for_selector("#error:not([hidden])", timeout=10000)
                msg = page.eval_on_selector_all("#error [data-msg]", "els => els.map(e => e.href)")
                check(f"{vp_name} {kind} error UI", page.locator("#error").get_attribute("data-kind") == kind
                      and want in page.locator("#error-title").inner_text() and len(msg) == 3 and all(h in m for m in msg),
                      page.locator("#error-title").inner_text())
                shot(f"9-error-{kind}")
            page.goto(base + "scan/?p=onlyfans.com&h=stub-empty")
            page.wait_for_selector("#report:not([hidden])", timeout=10000)
            check(f"{vp_name} empty status UI", page.locator("#empty").is_visible() and not page.locator("#google").is_visible()
                  and "Nothing indexed for this handle right now" in page.locator("#empty").inner_text())
            shot("9-empty")
            page.goto(base + "scan/?r=doesNotExist")
            page.wait_for_selector("#error:not([hidden])", timeout=5000)
            check(f"{vp_name} not_found UI", page.locator("#error").get_attribute("data-kind") == "not_found")
            page.goto(base + "scan/?p=onlyfans.com&h=" + quote("bad handle!"))
            check(f"{vp_name} bad handle → form + message", page.locator("#scan-form").is_visible()
                  and page.locator("#form-error").is_visible())
            page.goto(base + "scan/?p=instagram.com&h=" + quote("https://instagram.com/demo.creator/"))
            page.wait_for_selector("#progress:not([hidden])", timeout=5000)
            check(f"{vp_name} URL pasted as handle → cleaned", page.locator("#scan-title").inner_text() == "Scanning Google for @demo.creator")
            page.wait_for_selector("#report:not([hidden])", timeout=15000)

            check(f"{vp_name} no request left loopback", not outside, outside)
            check(f"{vp_name} no JS errors", not errors, errors)
            ctx.close()
        browser.close()
finally:
    stub.terminate()

(out / "e2e-summary.json").write_text(json.dumps({"fails": fails, "omit_results": omit}, indent=1))
sys.exit(1 if fails else 0)

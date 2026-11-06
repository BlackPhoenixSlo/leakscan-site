"""Scenario `scan` (see tools/scan_e2e.py for what it proves)."""
import json
import re
from urllib.parse import parse_qs, quote, urlsplit

from .common import ALSO, BARE_HOVER, TILES, bring, cfg, check, digits, hover, new_ctx, scan_images, served, tiles_ok, video_stills

# titles whose "open ↗" pill wrapped onto a line with no title text (its vertical centre off the last text line)
GO_ALONE = """() => [...document.querySelectorAll('#panel-google .g-title .g-go')].filter(go => {
  const r = document.createRange(), host = go.closest('.g-title'), g = go.getBoundingClientRect();
  if (!g.height) return false;
  const w = document.createTreeWalker(host, NodeFilter.SHOW_TEXT); let last = null, t;
  while ((t = w.nextNode())) if (!go.contains(t) && t.textContent.trim()) last = t;
  if (!last) return true;
  r.selectNodeContents(last); const rs = [...r.getClientRects()], lr = rs[rs.length - 1];
  return Math.abs((lr.top + lr.bottom) / 2 - (g.top + g.bottom) / 2) > 12;
}).map(go => go.closest('.g-title').textContent.slice(0, 50))"""


def open_all_sites(page):
    """Show every site row, open each, press every "Show N more" → every link href in the list."""
    while page.locator("#lx-more").is_visible():
        page.locator("#lx-more").click()
    page.evaluate("document.querySelectorAll('#lx-list details').forEach(d => d.open = true)")
    page.wait_for_timeout(100)
    while page.locator(".lx-lmore").count():
        page.evaluate("document.querySelectorAll('.lx-lmore').forEach(b => b.click())")
    return set(page.eval_on_selector_all("#lx-list a", "els => els.map(e => e.href)"))


def scan_flow(browser, vp_name, vp):
    ctx, net = new_ctx(browser, vp_name, vp)
    posts = []
    page = ctx.new_page()
    page.on("request", lambda q, posts=posts: q.method == "POST" and posts.append(q.url))
    shot = lambda name, full=False, page=page, v=vp_name: page.screenshot(path=str(cfg.out / f"{v}-{name}.png"), full_page=full)

    # 1. a scan/?p=&h= link (older links + the no-JS hero form land here; the JS hero form scans in place: `inline`)
    bodies = []
    page.on("request", lambda q, bodies=bodies: q.method == "POST" and "/api/public-scan" in q.url and bodies.append(json.loads(q.post_data)))
    page.goto(cfg.base + "scan/?p=fansly.com&h=%40demo.creator", wait_until="load")

    # 2. progress
    page.wait_for_selector("#progress-log li:not(:empty)", timeout=5000)
    check(f"{vp_name} progress visible", page.locator("#progress").is_visible()
          and "demo.creator" in page.locator("#scan-title").inner_text())
    check(f"{vp_name} scan/?p=&h= posts platform + clean handle, no socials",
          bodies == [{"platform": "fansly.com", "handle": "demo.creator", "level": "low"}], bodies)
    shot("1-progress")

    # 3. report
    page.wait_for_selector("#report:not([hidden])", timeout=15000)
    page.wait_for_timeout(600)
    slug = parse_qs(urlsplit(page.url).query).get("r", [""])[0]
    check(f"{vp_name} url becomes ?r=<slug>", bool(re.fullmatch(r"[A-Za-z0-9]{12}", slug)), page.url)
    d = served(slug)   # the oracle: what the API sent for this report
    pages = [r for r in d.get("results", []) if r.get("kind") != "video"]
    videos = [r for r in d.get("results", []) if r.get("kind") == "video"]
    stat = lambda k: digits(page.locator(f"[data-stat={k}]").inner_text())
    got = (stat("domains"), stat("pages"), stat("google"))
    want = (d["domain_count"], d["hit_count"], d["google_total"])
    check(f"{vp_name} summary numbers = the served result's", got == want, f"{got} vs {want}")
    check(f"{vp_name} title shows handle", page.locator("#scan-title").inner_text() == "@demo.creator")
    check(f"{vp_name} aliases: header says Also found as the discovered handles", page.locator("#scan-aliases").is_visible()
          and page.locator("#scan-aliases").inner_text() == ALSO, page.locator("#scan-aliases").inner_text())
    aff = page.evaluate("""() => {
        const hint = document.querySelector('.g-hint'), deco = [...document.querySelectorAll('.g-tab-deco')];
        return {hint: hint && hint.offsetParent !== null ? hint.innerText.trim() : null,
          deco: deco.map(e => [e.tagName, e.tabIndex, e.getAttribute('aria-hidden'), +getComputedStyle(e).opacity, getComputedStyle(e).cursor]),
          tabs: [...document.querySelectorAll('.g-tab')].map(e => getComputedStyle(e).cursor),
          seg: [...document.querySelectorAll('#device label')].map(e => getComputedStyle(e).cursor)};
    }""")
    bare = page.evaluate(BARE_HOVER)
    check(f"{vp_name} scan page: no :hover rule outside @media (hover: hover) (no sticky tint after a tap)", not bare, bare)
    want_hint = "Tap All · Images · Videos to switch, tap any result to open it." if vp_name == "phone" else "Click All · Images · Videos to switch, click any result to open it."
    check(f"{vp_name} scan page: hint next to the frame says Tap on touch / Click with a mouse", aff["hint"] == want_hint, aff["hint"])
    check(f"{vp_name} scan page: decorative tabs muted, not focusable; real tabs + device toggle pointer",
          aff["deco"] and all(d[0] == "SPAN" and d[1] == -1 and d[2] == "true" and d[3] < .6 and d[4] == "default" for d in aff["deco"])
          and set(aff["tabs"]) == {"pointer"} and set(aff["seg"]) == {"pointer"}, aff)

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
            small = vp_name == "phone"   # 1060 px frame at 350 px: tabs / tiles too small to tap
            check(f"{vp_name} computer frame hint fits the scale", page.locator("#g-hint").inner_text().strip() == (
                "Shrunk to fit this screen. Switch to Phone to tap results." if small else want_hint), page.locator("#g-hint").inner_text())
            if small:
                page.locator("#g-hint [data-device-go]").click()
                page.wait_for_timeout(300)
                check(f"{vp_name} hint 'Switch to Phone' = the Phone toggle", page.locator(".frame-phone").count() == 1
                      and page.locator("#device input:checked").get_attribute("value") == "phone" and page.locator("#g-hint").inner_text().strip() == (
                          # Playwright's full-page screenshot flips the touch context to hover + fine pointer: ask the page
                          want_hint.replace("Tap", "Click").replace(" tap ", " click ") if page.evaluate("matchMedia('(hover: hover) and (pointer: fine)').matches") else want_hint),
                      [page.locator(".frame-phone").count(), page.locator("#device input:checked").get_attribute("value"), page.locator("#g-hint").inner_text()])
                page.locator("#device label:has(input[value=computer])").click()
                page.wait_for_timeout(300)
        g = page.locator("#google")
        # All
        page.locator("#tab-google-all").click()
        n0 = page.locator("#panel-google .g-r").count()
        page.evaluate("window.scrollTo(0, document.getElementById('google').offsetTop)")
        g.screenshot(path=str(cfg.out / f"{vp_name}-3-{device}-all.png"))
        for _ in range(10):
            if page.locator("[data-more=all]").count() == 0:
                break
            page.locator("[data-more=all]").click()
        n1 = page.locator("#panel-google .g-r").count()
        first = (1 <= n0 <= min(10, len(pages))) if device == "phone" else n0 == min(10, len(pages))   # phone: first look fitted to ~1.5 screens
        check(f"{vp_name}/{device} All tab count (More reaches every result)", first and n1 == len(pages),
              f"{n0}→{n1} want {'≤' if device == 'phone' else ''}10→{len(pages)}")
        check(f"{vp_name}/{device} every result title carries open ↗", page.locator("#panel-google .g-r a.g-title .g-go").count() == n1)
        alone = page.evaluate(GO_ALONE)
        check(f"{vp_name}/{device} open ↗ never sits alone on a line (it rides on the title's last word)", not alone, alone[:3])
        check(f"{vp_name}/{device} tab aria-selected", page.locator("#tab-google-all").get_attribute("aria-selected") == "true"
              and page.locator("#tab-google-images").get_attribute("aria-selected") == "false")
        # Images
        page.locator("#tab-google-images").click()
        while page.locator("[data-more=images]").count():
            page.locator("[data-more=images]").click()
        tl = page.evaluate(TILES, "#panel-google .g-tile")
        srcs, sent = {t[0] for t in tl}, scan_images(d)
        vid = set(page.evaluate("() => [...document.querySelectorAll('#panel-google .g-tile .g-vid img')].map(i => decodeURIComponent(i.getAttribute('src').split('u=')[1] || ''))"))
        check(f"{vp_name}/{device} Images tab: every served image once ({len(sent)}, no cap; video results' stills with a play badge), "
              "result tiles first, each opens its own result", len(tl) == len(sent) and srcs == sent and not tiles_ok(tl, d, videos=True)
              and vid == srcs & video_stills(d) and vid, (len(tl), len(sent), len(vid), tiles_ok(tl, d, videos=True)))
        page.wait_for_timeout(500)
        go = lambda: page.eval_on_selector("#panel-google .g-tile-a .g-go", "e => [+getComputedStyle(e).opacity, getComputedStyle(e.querySelector('.g-go-w')).display]")
        if vp_name == "phone":   # touch: a small ↗ that is always there. Fresh page: element shots taller than the
            # viewport make Playwright drop touch emulation ((hover: none) stops matching) for the rest of the page's life
            p3 = ctx.new_page()
            p3.goto(cfg.base + "scan/?r=" + slug)
            p3.wait_for_selector("#report:not([hidden])", timeout=5000)
            if p3.locator("#device input:checked").get_attribute("value") != device:
                p3.locator(f"#device label:has(input[value={device}])").click()
                p3.wait_for_timeout(300)
            p3.locator("#tab-google-images").click()
            p3.wait_for_timeout(400)
            g0 = p3.eval_on_selector("#panel-google .g-tile-a .g-go", "e => [+getComputedStyle(e).opacity, getComputedStyle(e.querySelector('.g-go-w')).display]")
            check(f"{vp_name}/{device} tiles: persistent ↗ badge on touch", g0[0] > .8 and g0[1] == "none", g0)
            bring(p3, "#panel-google .g-tile-a", "center")
            p3.screenshot(path=str(cfg.out / f"{vp_name}-4b-{device}-touch-badges.png"))
            p3.close()
        else:
            g0 = go()
            hover(page, "#panel-google .g-tile-a")
            page.wait_for_timeout(300)
            g1 = go()
            check(f"{vp_name}/{device} tiles: 'open ↗' only on hover", g0[0] == 0 and g1[0] == 1 and g1[1] != "none", (g0, g1))
            g.screenshot(path=str(cfg.out / f"{vp_name}-4b-{device}-tile-hover.png"))
            page.mouse.move(0, 0)
        g.screenshot(path=str(cfg.out / f"{vp_name}-4-{device}-images.png"))
        # Videos
        page.locator("#tab-google-videos").click()
        nv0 = page.locator("#panel-google .g-v").count()
        while page.locator("[data-more=videos]").count():
            page.locator("[data-more=videos]").click()
        nv = page.locator("#panel-google .g-v").count()
        check(f"{vp_name}/{device} Videos tab count (first look {5 if device == 'phone' else 8}, More reaches every video)",
              nv0 == min(5 if device == "phone" else 8, len(videos)) and nv == len(videos), f"{nv0}→{nv} want {len(videos)}")
        page.wait_for_timeout(300)
        g.screenshot(path=str(cfg.out / f"{vp_name}-5-{device}-videos.png"))

    # 5. keyboard: arrow keys move between tabs
    page.locator("#tab-google-videos").focus()
    page.keyboard.press("ArrowLeft")
    check(f"{vp_name} ArrowLeft selects Images", page.locator("#tab-google-images").get_attribute("aria-selected") == "true"
          and page.evaluate("document.activeElement.id") == "tab-google-images")

    # 6. reveal
    blur = lambda: page.eval_on_selector("#panel-google .g-img img", "e => getComputedStyle(e).filter")
    before = blur()
    page.locator("#reveal").click()
    page.wait_for_timeout(400)
    after = blur()
    check(f"{vp_name} blurred by default, Reveal unblurs", "blur" in before and after == "none"
          and page.locator("#reveal").get_attribute("aria-pressed") == "true", f"{before} → {after}")
    page.locator("#google").screenshot(path=str(cfg.out / f"{vp_name}-6-revealed.png"))
    page.locator("#reveal").click()

    # 7. CTAs + links
    link = cfg.base + "scan/?r=" + slug
    hrefs = page.eval_on_selector_all("#send [data-msg]", "els => els.map(e => e.href)")
    check(f"{vp_name} CTA hrefs carry report link + handle", len(hrefs) == 3 and all(
        (quote(link, safe="") in h or quote(link, safe="").replace("%20", "+") in h) and "demo.creator" in h for h in hrefs)
          and hrefs[0].startswith("https://t.me/jakabasej?text=") and hrefs[1].startswith("https://wa.me/38640703992?text=")
          and hrefs[2].startswith("mailto:me@jackbase.dev?") and "body=" in hrefs[2], hrefs)
    deep = page.locator("#deep-link").get_attribute("href")
    check(f"{vp_name} deep-scan link", deep == "https://jackbase.me/scan?p=fansly.com&h=demo.creator&l=deep&go=1", deep)
    listed = open_all_sites(page)
    check(f"{vp_name} every hit url listed", all(h["url"] in listed for h in d["hits"]),
          f"{sum(h['url'] in listed for h in d['hits'])}/{len(d['hits'])}")
    check(f"{vp_name} per-site rows == domain_count", page.locator("#lx-list .lx-site").count() == d["domain_count"])
    bring(page, "#send", "center")
    page.locator("#send").screenshot(path=str(cfg.out / f"{vp_name}-7-cta.png"))

    # 8. reopen ?r=<slug> in a fresh page: no new scan
    n_posts = len(posts)
    p2 = ctx.new_page()
    p2.on("request", lambda q, posts=posts: q.method == "POST" and posts.append(q.url))
    p2.goto(cfg.base + "scan/?r=" + slug)
    p2.wait_for_selector("#report:not([hidden])", timeout=5000)
    check(f"{vp_name} ?r= reopens without a new scan", len(posts) == n_posts
          and digits(p2.locator("[data-stat=domains]").inner_text()) == d["domain_count"])
    p2.screenshot(path=str(cfg.out / f"{vp_name}-8-reopen.png"))
    # full-page shots drop Playwright's touch emulation ((hover: none) stops matching), so take it here, on the throwaway page
    p2.screenshot(path=str(cfg.out / f"{vp_name}-2-report-full.png"), full_page=True)
    p2.goto(cfg.base + "scan/?r=evilR3port01")
    p2.wait_for_selector("#report:not([hidden])", timeout=5000)
    check(f"{vp_name} aliases: malicious discovered handles never shown", p2.locator("#scan-aliases").is_hidden()
          and "alert(1)" not in p2.locator("#scan-aliases").evaluate("e => e.textContent"))
    p2.close()

    # 9. error / empty paths
    for h, kind, want in (("stub-fail", "failed", "didn’t finish"), ("stub-429", "rate_limited", "limit"),
                          ("stub-busy", "busy", "busy")):
        page.goto(cfg.base + f"scan/?p=onlyfans.com&h={h}")
        page.wait_for_selector("#error:not([hidden])", timeout=10000)
        msg = page.eval_on_selector_all("#error [data-msg]", "els => els.map(e => e.href)")
        check(f"{vp_name} {kind} error UI", page.locator("#error").get_attribute("data-kind") == kind
              and want in page.locator("#error-title").inner_text() and len(msg) == 3 and all(h in m for m in msg),
              page.locator("#error-title").inner_text())
        shot(f"9-error-{kind}")
    page.goto(cfg.base + "scan/?p=onlyfans.com&h=stub-empty")
    page.wait_for_selector("#report:not([hidden])", timeout=10000)
    check(f"{vp_name} empty status UI", page.locator("#empty").is_visible() and not page.locator("#google").is_visible()
          and "Nothing indexed for this handle right now" in page.locator("#empty").inner_text())
    check(f"{vp_name} aliases: none discovered -> header line hidden", page.locator("#scan-aliases").is_hidden())
    shot("9-empty")
    page.goto(cfg.base + "scan/?r=doesNotExist")
    page.wait_for_selector("#error:not([hidden])", timeout=5000)
    check(f"{vp_name} not_found UI", page.locator("#error").get_attribute("data-kind") == "not_found")
    page.goto(cfg.base + "scan/?p=onlyfans.com&h=" + quote("bad handle!"))
    check(f"{vp_name} bad handle → form + message", page.locator("#scan-form").is_visible()
          and page.locator("#form-error").is_visible())
    page.goto(cfg.base + "scan/?p=instagram.com&h=" + quote("https://instagram.com/demo.creator/"))
    page.wait_for_selector("#progress:not([hidden])", timeout=5000)
    check(f"{vp_name} URL pasted as handle → cleaned", page.locator("#scan-title").inner_text() == "Scanning Google for @demo.creator")
    page.wait_for_selector("#report:not([hidden])", timeout=15000)

    check(f"{vp_name} no request left loopback", not net["outside"], net["outside"])
    check(f"{vp_name} no JS errors", not net["errors"], net["errors"])
    ctx.close()

#!/usr/bin/env python3
"""Drive the hero free-scan form in Chromium and assert where it sends the visitor.

    python3 tools/check_scan_form.py BASE_URL OUT_DIR
    (fallback: cd ~/leakhunt && uv run python ~/leakscan-site/tools/check_scan_form.py BASE_URL OUT_DIR)

Phone (390x844) + desktop (1440x900), each with JS on and off: type `@Some.Name` + `@some.ig`, submit.
JS off: the navigation goes to the on-site scan page BASE_URL/scan/? with h=@Some.Name, ig=@some.ig (no go=, no p=).
JS on: no navigation (the scan runs in place, js/inline-scan.js; tools/scan_e2e.py --only inline covers the rest).
With JS the empty Instagram/X field is folded behind "+ Add Instagram or X" (one click opens + focuses it); without JS
it shows and the toggle doesn't. Controls (OnlyFans field, Instagram/X field, button) are >= 44px tall, stacked on phone;
on desktop the OnlyFans field + button share a row, Instagram/X gets the next. At 390, 600, 960, 1024, 1440 px both placeholders and a
20-character handle fit their input unclipped (canvas text width vs the input's content box). Every non-local request is aborted
(so the scan page's API call never leaves the machine). Saves hero-before / settled screenshots to OUT_DIR.
Prints one line per check; exit 1 if any fails.
"""
import pathlib, sys
from urllib.parse import parse_qs, urljoin, urlsplit
from playwright.sync_api import sync_playwright

base, out = sys.argv[1], pathlib.Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
fails = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name}{': ' + detail if detail else ''}")
    if not ok:
        fails.append(name)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for vp_name, vp in (("phone", {"width": 390, "height": 844}), ("desktop", {"width": 1440, "height": 900})):
        for js in (True, False):
            tag = f"{vp_name}-{'js' if js else 'nojs'}"
            ctx = browser.new_context(viewport=vp, java_script_enabled=js, color_scheme="light")
            blocked = []

            def route(r, _req, blocked=blocked):
                if urlsplit(r.request.url).hostname in ("127.0.0.1", "localhost"):
                    r.continue_()
                else:
                    blocked.append(r.request.url)
                    r.abort()

            ctx.route("**/*", route)
            page = ctx.new_page()
            page.goto(base, wait_until="load")
            form = page.locator("form#scan")
            form.scroll_into_view_if_needed()
            inp, soc, btn = page.locator("#scan input[name=h]"), page.locator("#scan input[name=ig]"), page.locator("#scan button")
            more = page.locator(".scan-more button")
            if js:
                check(f"{tag} Instagram/X folded behind '+ Add Instagram or X'", not soc.is_visible() and more.is_visible()
                      and more.inner_text() == "+ Add Instagram or X", f"field {soc.is_visible()}, toggle {more.is_visible()}")
                page.screenshot(path=str(out / f"form-{vp_name}-folded.png"))
                more.click()
                check(f"{tag} toggle opens + focuses it, toggle goes", soc.is_visible() and not more.is_visible()
                      and page.evaluate("document.activeElement.name") == "ig" and more.get_attribute("aria-expanded") == "true")
            else:
                check(f"{tag} Instagram/X shown, no toggle", soc.is_visible() and not more.is_visible())
            boxes = [el.bounding_box() for el in (page.locator("#scan .scan-prefix").nth(0), page.locator("#scan .scan-prefix").nth(1), btn)]
            check(f"{tag} tap targets >= 44px", all(b["height"] >= 44 for b in boxes),
                  ", ".join(f"{b['height']:.0f}" for b in boxes))
            tops = {round(b["y"]) for b in boxes}
            if vp_name == "desktop":
                ys = [round(b["y"]) for b in boxes]
                check(f"{tag} OnlyFans + button row, then Instagram/X row", ys[0] == ys[2] < ys[1], str(ys))
            else:
                check(f"{tag} stacked", len(tops) == 3, str(sorted(tops)))
            if js:  # nojs shots are identical apart from reveal; keep the evidence folder small
                page.screenshot(path=str(out / f"form-{vp_name}-before.png"))
            inp.fill("@Some.Name")
            soc.fill("@some.ig")
            if js:
                page.screenshot(path=str(out / f"form-{vp_name}-filled.png"))
            target = urljoin(base, "scan/")
            if js:
                before = page.url
                btn.click()
                page.wait_for_timeout(1500)
                check(f"{tag} scans in place (no navigation)", urlsplit(page.url).path == urlsplit(before).path, page.url)
            else:
                with page.expect_navigation(url=target + "?*"):
                    btn.click()
                url = page.url
                q = parse_qs(urlsplit(url).query)
                check(f"{tag} url", url.startswith(target + "?") and q == {"h": ["@Some.Name"], "ig": ["@some.ig"]}
                      and "h=%40Some.Name" in url, url)
            check(f"{tag} nothing left the machine", all("jackbase.me" not in u for u in blocked), str(blocked))
            page.screenshot(path=str(out / f"form-{tag}-settled.png"))
            ctx.close()
    # nothing clipped: placeholder and a typed 20-char handle fit each input at every layout width
    FIT = """() => { const c = document.createElement('canvas').getContext('2d');
      return [...document.querySelectorAll('#scan input')].map(i => { const cs = getComputedStyle(i); c.font = cs.font;
        const room = i.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
        return [i.name, Math.round(room), Math.round(Math.max(c.measureText(i.placeholder).width, c.measureText('sophiera.official.x1').width))]; }); }"""
    for w in (390, 600, 960, 1024, 1440):
        page = browser.new_page(viewport={"width": w, "height": 900})
        page.route("**/*", lambda r, _q: r.continue_() if urlsplit(r.request.url).hostname in ("127.0.0.1", "localhost") else r.abort())
        page.goto(base, wait_until="load")
        page.locator(".scan-more button").click()
        fit = page.evaluate(FIT)
        check(f"{w}px placeholders + 20-char handle fit (name, room, need)", all(room >= need for _n, room, need in fit), str(fit))
        page.close()
    browser.close()

sys.exit(1 if fails else 0)

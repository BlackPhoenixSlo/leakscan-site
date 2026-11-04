#!/usr/bin/env python3
"""Drive the hero free-scan form in Chromium and assert where it sends the visitor.

    python3 tools/check_scan_form.py BASE_URL OUT_DIR
    (fallback: cd ~/leakhunt && uv run python ~/leakscan-site/tools/check_scan_form.py BASE_URL OUT_DIR)

Phone (390x844) + desktop (1440x900), each with JS on and off: type `@Some.Name`, pick Instagram, submit.
Asserts the navigation goes to https://jackbase.me/scan? with p=instagram.com, h=@Some.Name, go=1, and that the
controls are >= 44px tall, stacked on phone and in one row on desktop. Requests to jackbase.me are answered locally
(never reach the app); every other non-local request is aborted. Saves hero-before / settled screenshots to OUT_DIR.
Prints one line per check; exit 1 if any fails.
"""
import pathlib, sys
from urllib.parse import parse_qs, urlsplit
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
            hits = []

            def route(r, _req, hits=hits):
                u = r.request.url
                if urlsplit(u).hostname == "jackbase.me":
                    hits.append(u)
                    r.fulfill(status=200, content_type="text/html",
                              body=f"<!doctype html><title>intercepted</title><p>Intercepted (not sent): {u}</p>")
                elif urlsplit(u).hostname in ("127.0.0.1", "localhost"):
                    r.continue_()
                else:
                    r.abort()

            ctx.route("**/*", route)
            page = ctx.new_page()
            page.goto(base, wait_until="load")
            form = page.locator("form#scan")
            form.scroll_into_view_if_needed()
            sel, inp, btn = page.locator("#scan select[name=p]"), page.locator("#scan .scan-handle"), page.locator("#scan button")
            boxes = [el.bounding_box() for el in (sel, inp, btn)]
            check(f"{tag} tap targets >= 44px", all(b["height"] >= 44 for b in boxes),
                  ", ".join(f"{b['height']:.0f}" for b in boxes))
            tops = {round(b["y"]) for b in boxes}
            if vp_name == "desktop":
                check(f"{tag} one row", len(tops) == 1, str(sorted(tops)))
            else:
                check(f"{tag} stacked", len(tops) == 3, str(sorted(tops)))
            if js:  # nojs shots are identical apart from reveal; keep the evidence folder small
                page.screenshot(path=str(out / f"form-{vp_name}-before.png"))
            inp.fill("@Some.Name")
            sel.select_option("instagram.com")
            if js:
                page.screenshot(path=str(out / f"form-{vp_name}-filled.png"))
            with page.expect_navigation(url="https://jackbase.me/**"):
                btn.click()
            url = page.url
            q = parse_qs(urlsplit(url).query)
            check(f"{tag} url", url.startswith("https://jackbase.me/scan?")
                  and q.get("p") == ["instagram.com"] and q.get("h") == ["@Some.Name"] and q.get("go") == ["1"]
                  and "h=%40Some.Name" in url, url)
            check(f"{tag} one jackbase request, intercepted", len(hits) == 1, str(hits))
            page.screenshot(path=str(out / f"form-{tag}-settled.png"))
            ctx.close()
    browser.close()

sys.exit(1 if fails else 0)

#!/usr/bin/env python3
"""Drive the hero free-scan form in Chromium and assert where it sends the visitor.

    python3 tools/check_scan_form.py BASE_URL OUT_DIR
    (fallback: cd ~/leakhunt && uv run python ~/leakscan-site/tools/check_scan_form.py BASE_URL OUT_DIR)

Phone (390x844) + desktop (1440x900), each with JS on and off: type `@Some.Name` + `@some.ig`, submit.
JS off: the navigation goes to the on-site scan page BASE_URL/scan/? with h=@Some.Name, ig=@some.ig (no go=, no p=).
JS on: no navigation (the scan runs in place, js/inline-scan.js; tools/scan_e2e.py --only inline covers the rest).
Controls (OnlyFans field, Instagram/X field, button) are >= 44px tall, stacked on phone and in one row on desktop. Every non-local request is aborted
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
            boxes = [el.bounding_box() for el in (page.locator("#scan .scan-prefix").nth(0), page.locator("#scan .scan-prefix").nth(1), btn)]
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
    browser.close()

sys.exit(1 if fails else 0)

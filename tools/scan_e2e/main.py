"""Runs the scenarios for both viewports against a fresh stub; writes e2e-summary.json; exit 1 on any FAIL."""
import json
import sys

from playwright.sync_api import sync_playwright

from .common import MEASURED, VIEWPORTS, cfg, check, configure, fails, start_stub
from .askai import askai
from .inline import inline_flow, thumb_paint
from .personalize import personalize_flow
from .pip import pip_flow
from .removals import removals_flow
from .huge import huge_flow
from .scan import scan_flow
from .tabs import tabs_flow


def flow(fn, vp_name, *args):
    """One scenario part; an exception in it (a Playwright timeout, a missing element) is a FAIL line for that part
    and the run goes on with the next one: one stuck page never hides every check after it."""
    try:
        fn(*args)
    except Exception as e:   # noqa: BLE001 - reported, never swallowed
        check(f"{vp_name} {fn.__name__}: ran to the end", False, f"{type(e).__name__}: {(str(e).splitlines() or [''])[0][:300]}")


def run(argv=None):
    configure(sys.argv[1:] if argv is None else argv)
    stub = start_stub()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for vp_name, vp in VIEWPORTS:
                if "scan" in cfg.scenarios:
                    flow(scan_flow, vp_name, browser, vp_name, vp)
                    flow(huge_flow, vp_name, browser, vp_name, vp)
                if "personalize" in cfg.scenarios:
                    flow(personalize_flow, vp_name, browser, vp_name, vp)
                if "askai" in cfg.scenarios:
                    flow(askai, vp_name, browser, vp_name, vp)
                if "inline" in cfg.scenarios:
                    flow(inline_flow, vp_name, browser, vp_name, vp)
                    flow(thumb_paint, vp_name, pw, vp_name, vp)
                if "tabs" in cfg.scenarios:
                    flow(tabs_flow, vp_name, browser, vp_name, vp)
                if "removals" in cfg.scenarios:
                    flow(removals_flow, vp_name, browser, vp_name, vp)
                if "pip" in cfg.scenarios:
                    flow(pip_flow, vp_name, pw, browser, vp_name, vp)
            if "pip" in cfg.scenarios:
                flow(pip_flow, "phone-webkit", pw, browser, "phone", None, "webkit")   # iPhone 13 (Playwright device), WebKit
            browser.close()
    finally:
        stub.terminate()

    (cfg.out / "e2e-summary.json").write_text(json.dumps({"fails": fails, "omit_results": cfg.omit, "omit_profile": cfg.omit_profile,
                                                          "scenarios": cfg.scenarios, "breaks": sorted(cfg.broken),
                                                          "measured": MEASURED}, indent=1))
    return 1 if fails else 0

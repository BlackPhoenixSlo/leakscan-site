"""Runs the scenarios for both viewports, each against its own fresh stub, unless reused (reuse.py); writes e2e-summary.json; exit 1 on any FAIL."""
import importlib
import json
import sys
import time

from . import reach, reuse
from .common import MEASURED, VIEWPORTS, cfg, check, configure, fails, start_stub

BEFORE_VP = {"thumb_paint": lambda pw, browser: (pw,), "pip_flow": lambda pw, browser: (pw, browser)}   # first args of a part; default (browser,)


def flow(fn, vp_name, *args):
    """One scenario part; an exception in it (a Playwright timeout, a missing element) is a FAIL line for that part
    and the run goes on with the next one: one stuck page never hides every check after it."""
    try:
        fn(*args)
    except Exception as e:   # noqa: BLE001 - reported, never swallowed
        check(f"{vp_name} {fn.__name__}: ran to the end", False, f"{type(e).__name__}: {(str(e).splitlines() or [''])[0][:300]}")


def scenario(s, parts, pw, browser, state):
    """One scenario, every viewport, a fresh stub; its reach measured unless it's a break run → its summary row."""
    n, t0, code, measure = len(fails), time.time(), reuse.code_key(s, {}), reuse.cacheable()
    seen, log = set(), cfg.out / f"reach-{s}.log"
    log.unlink(missing_ok=True)
    stub = start_stub(log if measure else None)
    reach.record(seen.add if measure else None)   # the harness's own reads: personalize reads site/index.html
    try:
        for vp_name, vp in VIEWPORTS:
            for fn in parts:
                flow(fn, vp_name, *BEFORE_VP.get(fn.__name__, lambda _pw, b: (b,))(pw, browser), vp_name, vp)
        if s == "pip":
            flow(parts[0], "phone-webkit", pw, browser, "phone", None, "webkit")   # iPhone 13 (Playwright device), WebKit
    finally:
        reach.record(None)
        stub.terminate()
        stub.wait()   # the next stub binds the same port
        stub.stdout.close()
    if not measure:
        print(f"{s}: ran {'RED' if fails[n:] else 'green'} {time.time() - t0:.0f} s (break run: no cache)", flush=True)
        return {"status": "ran", "secs": round(time.time() - t0, 1), "fails": fails[n:]}
    return reuse.finish(s, code, t0, seen | set(log.read_text().split("\n")) - {""}, fails[n:], state)


def run(argv=None):
    configure(sys.argv[1:] if argv is None else argv)
    state, t0 = reuse.git_state(), time.time()
    todo, per = reuse.plan()
    try:
        old = json.loads((cfg.out / "e2e-summary.json").read_text()).get("per_scenario", {})
    except (OSError, ValueError):
        old = {}

    def save():
        (cfg.out / "e2e-summary.json").write_text(json.dumps({"fails": fails, "omit_results": cfg.omit, "omit_profile": cfg.omit_profile,
                                                              "scenarios": cfg.scenarios, "breaks": sorted(cfg.broken), "measured": MEASURED,
                                                              "sha": state[0], "dirty": state[1], "secs": round(time.time() - t0, 1), "per_scenario": reuse.summary_rows(old, per)}, indent=1))
    if todo:
        reuse.enter_gate()
        from playwright.sync_api import sync_playwright   # lazily: a full hit needs no browser
        parts = {s: [getattr(importlib.import_module("." + f.split(".")[0], __package__), f.split(".")[1]) for f in reuse.FLOWS[s]] for s in todo}
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for s in todo:
                per[s] = scenario(s, parts[s], pw, browser, state)
                save()   # a green scenario of a run killed later is still reusable
            browser.close()
    save()
    return 1 if fails else 0

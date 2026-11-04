#!/usr/bin/env python3
"""
pipeline_steps.py — the whole leak→report→export→publish pipeline as a plain Python
list of steps. One source of truth for (a) the CLI runner below and (b) the web-UI
"Run whole pipeline" button (server.py streams each step's output over SSE).

Each step: dict(id, title, desc, cmd(ctx)->argv | None, optional=bool).
`cmd` returns the argv to run, or None to skip. `ctx` carries the run parameters
(name, brand, aliases_file, slug, strong tokens, domains, engines, fast).

    python3 pipeline_steps.py --name "Ivette Aguero Tarazona" --brand "Tarita Fit" \
        --slug taritafit --aliases-file tarita-aliases.txt --prefix tarita
    python3 pipeline_steps.py --list          # just print the step list
    python3 pipeline_steps.py ... --only scan,crawl,expand,export,report
    python3 pipeline_steps.py ... --fast       # 80/20 mode (capped crawl, skip images)
"""
import argparse, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable or "python3"
NODE = "node"


def _p(ctx, *parts):
    return os.path.join(HERE, *parts)


def _camp_dir(c):
    return os.path.join("campaigns", os.path.basename(c["prefix"]))


def _resolve(c, name):
    """An artifact may live at the repo ROOT (a fresh full run — leak_crawler etc. write there,
    and run_az.sh tidies into campaigns/<base>/ only AFTER the pipeline finishes) OR under
    campaigns/<base>/ (a `--only <step>` re-run against an already-archived campaign). Return
    whichever exists; default to the bare root name when neither does yet (mid-fresh-run)."""
    if os.path.exists(_p(c, name)):
        return name
    camp = os.path.join(_camp_dir(c), name)
    return camp if os.path.exists(_p(c, camp)) else name


def _opt(c, flag, name):
    """[flag, resolved_path] if the artifact exists (root or campaigns/<base>/), else []."""
    r = _resolve(c, name)
    return [flag, r] if os.path.exists(_p(c, r)) else []


def _out(c, name):
    """Where a step should WRITE a deliverable.
    · FULL run (run_az.sh, no --only): the repo ROOT — run_az.sh moves every output into
      campaigns/<base>/ and rewrites gallery paths afterward, so writing to root is required.
    · PARTIAL run (`--only report`/`--only pdf` against an already-archived campaign): beside the
      campaign, so the output isn't orphaned at the root with no mover to tidy it.
    The distinguishing signal is `--only` (partial), NOT whether campaigns/<base>/ happens to
    exist — a run_az.sh RE-run of an existing model is still a full run and must write to root."""
    if c.get("only") and os.path.isdir(_p(c, _camp_dir(c))):
        return os.path.join(_camp_dir(c), name)
    return name


def _crawl_file(c):
    """Prefer the cleaned crawl (trap/aggregator/theme URLs stripped) when present; resolve
    repo-root (fresh run) vs campaigns/<base>/ (re-run) — mirrors _triage_file."""
    for name in (f"{c['prefix']}.crawl.clean.json", f"{c['prefix']}.crawl.json"):
        r = _resolve(c, name)
        if os.path.exists(_p(c, r)):
            return r
    return f"{c['prefix']}.crawl.json"


def _triage_file(c):
    """slug_triage.py always writes campaigns/<name>/triage/<name>.triage.json (by --campaign)."""
    base = os.path.basename(c["prefix"])
    return os.path.join("campaigns", base, "triage", f"{base}.triage.json")


def _keep_file(c):
    """campaigns/<name>/recovery_keep.txt — HUMAN-vision-confirmed HER domains (via
    recovery_demo.py). A persistent per-campaign artifact (never at root). Gates the class-2/3
    recovery: present -> apply, absent -> skip (a fresh model has none until someone eyeballs the
    demo). Returns the path or None."""
    p = os.path.join(_camp_dir(c), "recovery_keep.txt")
    return p if os.path.exists(_p(c, p)) else None


def _incogniton_running():
    """Fast, side-effect-free check that the Incogniton desktop app is up (macOS): only used
    to decide the `--google-shots=auto` fallback. NEVER launches a browser. On any uncertainty
    (pgrep missing / non-mac) returns True, so we still ATTEMPT the real capture (today's
    behavior) rather than silently downgrading to the synthetic strip."""
    try:
        r = subprocess.run(["pgrep", "-f", "MacOS/IncognitonBrowser"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return r.returncode == 0
    except Exception:
        return True


def _gcapture_cmd(c):
    """gcapture argv, gated by the --google-shots mode. Incogniton is NEVER removed — it's the
    preferred capture. `cse` skips the real pass entirely (headless CSE synthetic strip only);
    `auto` skips it ONLY when the Incogniton app is confirmed offline (so local Chrome never
    hammers google.com and gets IP-walled); `browser` always attempts it (legacy behavior)."""
    mode = c.get("google_shots", "auto")
    if mode == "cse":
        return None                                   # CSE-only: no browser touches google.com
    if mode == "auto" and not c.get("_incogniton_up", True):
        return None                                   # Incogniton offline -> fall back to CSE strip
    if not (os.path.exists(_p(c, "google_shots.py")) and not c.get("fast")):
        return None
    return ([PY, "google_shots.py", "--query", c["strong"].split(",")[0].strip(),
             "--name", c["name"], "--aliases", c.get("alias_csv") or c["strong"],
             "--out-dir", f"{c['prefix']}_images", "--max", "13", "--per-query", "8",
             "--links-out", f"{c['prefix']}.google_links.txt"]
            # ATTENDED run: on a captcha wall, ping the operator and WAIT (instead of the
            # unattended per-query skip) — one solve usually clears the whole session.
            + (["--solve", "--solve-wait", str(c.get("solve_wait") or 300)]
               if c.get("solve") else [])
            # site-brand domains from the hosts Google actually surfaces her on (CSE),
            # falling back to crawl media-count only if no CSE scan exists.
            + (["--from-cse", f"{c['prefix']}.cse.json"]
               if os.path.exists(_p(c, f"{c['prefix']}.cse.json"))
               else (["--from-crawl", _crawl_file(c)]
                     if os.path.exists(_p(c, _crawl_file(c))) else [])))


def _has_real_capture(c):
    """True if gcapture (6b) already wrote a REAL shots.json — entries whose local_path starts
    with 'shots/' (live Incogniton screenshots) rather than the synthetic 'google_images_N.png'.
    When present, gshots (6d) renders only 3 grids and MERGES them into shots.json (real records
    kept, make_report interleaves) instead of the full 6-grid fallback strip."""
    import json
    sj = _p(c, _resolve(c, f"{c['prefix']}_images/shots.json"))
    if not os.path.exists(sj):
        return False
    try:
        data = json.load(open(sj, encoding="utf-8"))
    except Exception:
        return False
    return any(str(s.get("local_path", "")).startswith("shots/") for s in data)


# ── THE PIPELINE, AS A LIST ─────────────────────────────────────────────────
STEPS = [
    dict(id="scan", title="1 · Presence scan",
         desc="leak_scanner.py — which of the 375 known piracy domains host this creator",
         cmd=lambda c: [PY, "leak_scanner.py", "--names-file", c["aliases_file"],
                        "--out", f"{c['prefix']}-scan"]),
    dict(id="seed", title="1b · Seed slug frontier",
         desc="discovery_seed.py — harvest profile-shape URLs the discovery stages (scan/CSE/web "
              "search, incl. prior runs) already found into <prefix>.seed_slugs.json + the slug "
              "cache, so the crawl VISITS real profile pages its own echo-page discovery can't "
              "reach (fapello.com/julia-filippo-58) and the Q1 sibling probe fills the family.",
         cmd=lambda c: ([PY, "discovery_seed.py", "--campaign", os.path.basename(c["prefix"]),
                         "--name", c["name"], "--tokens", c["strong"],
                         "--out", _out(c, f"{c['prefix']}.seed_slugs.json")]
                        # web isolates the slug cache per scan (mirrors the crawl step) so a public
                        # scan never merges its harvested slugs into the shared slugs_cache.json.
                        + (["--cache", f"{c['prefix']}.slugs_cache.json"] if c.get("web") else [])
                        if os.path.exists(_p(c, "discovery_seed.py")) else None),
         optional=True),
    dict(id="crawl", title="2 · Deep crawl",
         desc="leak_crawler.py — real slugs → FULL gallery depth (grid-walk / idx_max) → media",
         # web mode with NO scan-hit domains = the presence scan found nothing, so there is
         # nothing to deep-crawl. SKIP rather than fall through to the crawler's full default
         # domain set — that inversion (a 0-hit handle triggering the heaviest crawl) is a
         # public-endpoint cost/DoS amplifier. A normal (non-web) run still crawls all domains.
         cmd=lambda c: None if (c.get("web") and not c.get("domains")) else
                       [PY, "leak_crawler.py", "--names-file", c["aliases_file"],
                        "--out", f"{c['prefix']}.crawl", "--workers", "10", "--politeness", "0.4"]
                       + _opt(c, "--seed-slugs", f"{c['prefix']}.seed_slugs.json") + [
                        # budget was 25s to stop dead hosts stalling the tail — but the crawl is
                        # already restricted to scan-hit (live) domains, so raise it so the deep
                        # numbered-post walk (fapello ~172 posts ≈ 70s, etc.) COMPLETES instead of
                        # being cut off mid-gallery. That truncation was the "we don't collect all
                        # the leaks" bug; the depth fix only pays off with room to finish.
                        "--per-domain-budget", "120", "--timeout", "8",
                        "--item-depth", "400",   # full per-slug post depth; per-site idx_max caps it
                        "--expand"]              # Q1 cross-site slug propagation (no-op w/o an alt identity)
                       + (["--domains", c["domains"]] if c.get("domains") else [])
                       # fast = 80/20: shallow grid + tight budget + capped post depth. --fast also
                       # force-disables --expand inside leak_crawler, so it stays cheap.
                       + (["--fast", "--timeout", "8", "--max-pages", "3",
                           "--per-domain-budget", "45", "--item-depth", "60"] if c.get("fast") else [])
                       # web = public_app's "big scan": bound the crawl for latency (last-wins over
                       # the 120/400 base, same trick --fast uses) but WITHOUT the crawler's --fast
                       # flag, so the screenshot steps (gcapture/gshots/gallery) still run — unlike
                       # --fast, which disables them. Ignored when --fast is also set (fast wins).
                       # Caps ~2x the original 4/40/80 (raised 2026-07-04): a bounded --web crawl of
                       # the deep hosts was the real ceiling on the public number (~6.2k), NOT the
                       # triage/alias layer — leakgallery/fapeza carry the handle in-URL and were
                       # always kept; they were just crawled shallowly. 8 pages / 90s / 200 items
                       # roughly doubles per-domain reach (~10-12k) for ~1.5-2x wall-clock. Must stay
                       # under PIPE_DISCOVERY_TIMEOUT (raised to 900s in tandem) or the crawl truncates.
                       + (["--timeout", "8", "--max-pages", "8",
                           "--per-domain-budget", "90", "--item-depth", "200"]
                          if c.get("web") and not c.get("fast") else [])
                       # web isolates the slug cache PER SCAN (<prefix>.slugs_cache.json, cleaned
                       # with the scratch) so concurrent public scans never corrupt — or bleed
                       # another person's cached slugs into — the shared repo-root slugs_cache.json.
                       + (["--slug-cache", f"{c['prefix']}.slugs_cache.json"] if c.get("web") else [])),
    dict(id="seedurl", title="2a · Class-3 seed-URL recovery",
         desc="seed_url_crawl.py — direct-fetch the discovered profile URLs the crawl got 0 media "
              "from, for confirmed clean hosts (GLOBAL recovery_hosts.txt + per-campaign "
              "recovery_keep.txt, vision-vetted via recovery_demo.py); merge into crawl.json so "
              "clean/gallery/report pick them up. No recovery_hosts.txt at all -> skipped.",
         cmd=lambda c: ([PY, "seed_url_crawl.py", "--campaign", os.path.basename(c["prefix"]),
                         "--name", c["name"], "--tokens", c["strong"],
                         "--crawl", f"{c['prefix']}.crawl.json"]
                        + (["--keep-file", _keep_file(c)] if _keep_file(c) else [])
                        if os.path.exists(_p(c, "recovery_hosts.txt"))
                        and os.path.exists(_p(c, "seed_url_crawl.py"))
                        and os.path.exists(_p(c, f"{c['prefix']}.crawl.json")) else None),
         optional=True),
    dict(id="clean", title="2b · Clean crawl",
         desc="clean_crawl.py — strip crawler traps (recursive pagination, search/tag aggregators, "
              "theme assets) + fake-aggregator hosts (fake_aggregators.txt) that SEO-name other "
              "people's content with the handle (ahvideoscdn.net) so they never reach gallery/DMCA/report. "
              "--keep-file (if vetted) provenance-keeps confirmed-HER hashed-CDN media pass-4 would strip.",
         cmd=lambda c: ([PY, "clean_crawl.py", f"{c['prefix']}.crawl.json",
                         f"{c['prefix']}.crawl.clean.json", "--strong", c["strong"]]
                        + (["--block-file", "fake_aggregators.txt"]
                           if os.path.exists(_p(c, "fake_aggregators.txt")) else [])
                        + (["--keep-file", _keep_file(c)] if _keep_file(c) else [])
                        if os.path.exists(_p(c, "clean_crawl.py"))
                        and os.path.exists(_p(c, f"{c['prefix']}.crawl.json")) else None),
         optional=True),
    dict(id="triage", title="2c · Per-tile echo triage",
         desc="slug_triage.py — classify each result-tile slug as her vs padding; DROP = search page "
              "echoes AND crawl found 0 handle-carrying files. Non-destructive artifact; feeds "
              "export_dmca --triage so echo-only domains (xxbrits) never reach the DMCA form.",
         cmd=lambda c: ([PY, "slug_triage.py", "--campaign", os.path.basename(c["prefix"]),
                         "--name", c["name"], "--render", "off"]
                        if os.path.exists(_p(c, "slug_triage.py"))
                        and os.path.exists(_p(c, f"{c['prefix']}-scan.json")) else None),
         optional=True),
    dict(id="expand", title="3 · Language + re-upload variants",
         desc="expand_variants.py — picazor/thothd/leakgallery /{lang}/ mirrors + fapello name-1/-2 (verified)",
         cmd=lambda c: [PY, "expand_variants.py", "--slugs", c["strong"],
                        "--from-crawl", f"{c['prefix']}.crawl.json",
                        "--out", f"{c['prefix']}.variants"]),
    dict(id="dmca", title="4 · Takedown contacts",
         desc="dmca_finder.py — best abuse/DMCA email per confirmed domain",
         cmd=lambda c: [PY, "dmca_finder.py", "--in", f"{c['prefix']}-verified-domains.txt",
                        "--out", f"{c['prefix']}.takedown"] if os.path.exists(
                            _p(c, f"{c['prefix']}-verified-domains.txt")) else None,
         optional=True),
    dict(id="search", title="5 · Incognito web search (off)",
         desc="web_search.py — Google + Reddit incognito, likely/possible links",
         cmd=lambda c: ([PY, "web_search.py", "--name", c["name"], "--aliases", c["alias_csv"],
                         "--out", f"{c['prefix']}.search"] if os.path.exists(_p(c, "web_search.py"))
                        and not c.get("fast") else None),
         optional=True),
    dict(id="images", title="6 · Image collection (off)",
         desc="collect_images.py — 5-10 images/query from Google Images, name-verified",
         cmd=lambda c: ([PY, "collect_images.py", "--name", c["name"], "--aliases", c["alias_csv"],
                         "--out-dir", f"{c['prefix']}_images"] if os.path.exists(_p(c, "collect_images.py"))
                        and not c.get("fast") else None),
         optional=True),
    dict(id="cse", title="6a · Google CSE scan",
         desc="build_cse.py — headless Google Programmable Search (API, no browser): sites Google "
              "indexes her on + top public results + base64 thumbnails -> {prefix}.cse.json "
              "(the report's 'Also all over Google' section). Reliable — no /sorry captcha wall.",
         cmd=lambda c: ([PY, "build_cse.py", "--name", c["name"], "--strong", c["strong"],
                         "--out", f"{c['prefix']}.cse.json"]
                        if os.path.exists(_p(c, "build_cse.py")) else None),
         optional=True),
    dict(id="gcapture", title="6b · REAL Google pass — screenshots + frames + links (Incogniton)",
         desc="google_shots.py — ONE real google.com &udm=2 pass yielding ALL THREE Google outputs: "
              "site-brand keyword search screenshots (`juliafilippo fapello`, not site:) -> shots.json, "
              "the result thumbnails -> {prefix}_images/google/<query>/ (+ index.json), and the "
              "source-page URLs -> {prefix}.google_links.txt. Replaces the redundant `search`+`images` "
              "incognito scrapes. Real (Incogniton) — OVERWRITES the synthetic gshots shots.json when it "
              "captures; if Google walls it (Incogniton down) it writes nothing and the synthetic gshots "
              "strip + crawl-only gallery remain the fallback. Gated by --google-shots: skipped when "
              "=cse, or when =auto and the Incogniton app is offline (then the 6d CSE strip is used).",
         cmd=_gcapture_cmd,
         optional=True),
    dict(id="gallery", title="6c · Leaked-image gallery",
         desc="build_gallery.py — NUDE-FIRST, one-per-site 'Your leaked content' gallery from "
              "deep-crawl media (handle-verified) + AUTO-picked Google frames (skin-vetted; drops "
              "text/memes/clothed) that gcapture just downloaded. Drops blocked wrong-person/hardcore "
              "sites ({prefix}_gallery_block.txt) and near-dupes -> {prefix}_gallery.txt. A hand-vetted "
              "{prefix}_google_keep.txt overrides the auto pick. make_report --gallery-file leads the "
              "report with it.",
         cmd=lambda c: ([PY, "build_gallery.py", "--crawl", _crawl_file(c),
                         "--strong", c["strong"], "--out", _out(c, f"{c['prefix']}_gallery.txt"),
                         "--cache", _out(c, f"{c['prefix']}_gallery_imgs")]
                        + _opt(c, "--block-file", f"{c['prefix']}_gallery_block.txt")
                        # google frames fold in AUTOMATICALLY (--google-auto skin-vets them);
                        # a hand-made {prefix}_google_keep.txt, if present, takes precedence.
                        + (["--google-root", _resolve(c, f"{c['prefix']}_images/google"), "--google-auto"]
                           if os.path.isdir(_p(c, _resolve(c, f"{c['prefix']}_images/google"))) else [])
                        + _opt(c, "--google-keep", f"{c['prefix']}_google_keep.txt")
                        if os.path.exists(_p(c, "build_gallery.py"))
                        and os.path.exists(_p(c, _crawl_file(c))) else None),
         optional=True),
    dict(id="gshots", title="6d · Synthetic Google strip (full fallback / mixed-in illustrative grids)",
         desc="build_google_shots.py — render the CSE data as a modern (2025) dark-mode Google Images "
              "masonry screenshot strip (local HTML -> PNG headless, NOT live Google). Runs AFTER the "
              "gallery so it can use the CURATED gallery tiles. With NO real capture (Incogniton "
              "offline / --google-shots=cse) it is the full 6-grid fallback strip; with a real "
              "capture it renders 3 grids and MERGES them into shots.json (real records kept) so "
              "make_report interleaves them at slots 2/5/8, each tile badged 'illustrative'.",
         cmd=lambda c: ([PY, "build_google_shots.py",
                         "--cse", _resolve(c, f"{c['prefix']}.cse.json"),
                         "--out-dir", _resolve(c, f"{c['prefix']}_images"),
                         "--images-dir", _resolve(c, f"{c['prefix']}_images")]
                        + (["--image-queries", "3"] if _has_real_capture(c) else [])
                        + _opt(c, "--gallery-file", f"{c['prefix']}_gallery.txt")
                        + _opt(c, "--raw", f"{c['prefix']}.cse.raw.json")
                        # gallery.txt now EXISTS (gallery ran) so the strip is curated-gallery-first;
                        # forced in cse mode even under --fast (there it's the only Google-results
                        # producer).
                        if os.path.exists(_p(c, "build_google_shots.py"))
                        and os.path.exists(_p(c, _resolve(c, f"{c['prefix']}.cse.json")))
                        and (not c.get("fast") or c.get("google_shots") == "cse") else None),
         optional=True),
    dict(id="export", title="7 · DMCA export (LIKELY / POSSIBLE)",
         desc="export_dmca.py — paste-ready live_for_dmca_form.txt (chunk 400) + verify_*.txt + metadata",
         cmd=lambda c: [PY, "export_dmca.py", "--crawl", _crawl_file(c),
                        "--name", c["name"], "--slug", c["prefix"], "--strong", c["strong"]]
                       # expand is off by default now — only feed --variants if a prior run
                       # actually produced the file (export tolerates its absence). _opt resolves
                       # root (fresh run) vs campaigns/<base>/ (re-run) so `--only export` isn't empty.
                       + _opt(c, "--variants", f"{c['prefix']}.variants.json")
                       + _opt(c, "--search", f"{c['prefix']}.search.json")
                       # gcapture's one-pass source links join the LIKELY/POSSIBLE buckets
                       + _opt(c, "--google-links", f"{c['prefix']}.google_links.txt")
                       # triage suppresses echo-only domains (search echoes + crawl 0) from the export
                       + (["--triage", _triage_file(c)]
                          if os.path.exists(_p(c, _triage_file(c))) else [])),
    dict(id="report", title="8 · Client report (HTML)",
         desc="make_report.py — stats, price, blurred DRAG gallery, Google layer, live-chat (on by default), 3-tier links",
         cmd=lambda c: [PY, "make_report.py", "--prefix", c["prefix"], "--slug", c["prefix"],
                        "--name", c["name"], "--brand", c["brand"], "--strong", c["strong"],
                        # _crawl_file/_out resolve root (fresh run) vs campaigns/<base>/ (re-run) so
                        # `--only report` reads the archived crawl and writes beside it, not orphaned at root.
                        "--crawl", _crawl_file(c), "--out", _out(c, f"{c['prefix']}-report.html"),
                        # honor THIS model's aliases for the hero chips (make_report defaults to
                        # tarita's file → without this a cinnanicos report shows tarita's handles)
                        "--aliases-file", _resolve(c, f"{c['prefix']}-aliases.txt")
                        if os.path.exists(_p(c, _resolve(c, f"{c['prefix']}-aliases.txt")))
                        else c["aliases_file"]]
                       + _opt(c, "--cse", f"{c['prefix']}.cse.json")
                       # triage also cleans the CSE 'Also on Google' sites (echo-only domains)
                       + (["--triage", _triage_file(c)]
                          if os.path.exists(_p(c, _triage_file(c))) else [])
                       + (["--images-dir", _resolve(c, f"{c['prefix']}_images")]
                          if os.path.isdir(_p(c, _resolve(c, f"{c['prefix']}_images"))) else [])
                       + _opt(c, "--gallery-file", f"{c['prefix']}_gallery.txt")
                       + (["--live-chat"] if c.get("live_chat") else ["--no-live-chat"])),
    dict(id="protect", title="9 · Password-protect (opt)",
         desc="protect_report.js — AES-GCM gate; password = handle + leak count",
         cmd=lambda c: ([NODE, "protect_report.js", f"{c['prefix']}-report.html",
                         f"{c['prefix']}-report-protected.html", c["password"]]
                        if c.get("password") else None),
         optional=True),
    dict(id="pdf", title="10 · PDF snapshot (opt)",
         desc="report_to_pdf.py — flatten the report to one PDF (reveals the gallery, unwraps the "
              "drag-rows so EVERY tile prints). Renders the PLAINTEXT report → keep LOCAL, never publish.",
         cmd=lambda c: ([PY, "report_to_pdf.py",
                         "--in", _resolve(c, f"{c['prefix']}-report.html"),
                         "--out", _out(c, f"{c['prefix']}-report.pdf")]
                        if os.path.exists(_p(c, _resolve(c, f"{c['prefix']}-report.html"))) else None),
         optional=True),
]

# Steps that rarely earn their runtime on a normal run — SKIPPED on a bare full run,
# still runnable by naming them explicitly (e.g. `--only search,images`).
#  · expand  — /{lang}/ mirror + fapello -1/-2 guesses mostly duplicate the deep crawl.
#  · search + images — the two REDUNDANT incognito Google passes. `gcapture` now does all
#    three Google jobs (screenshot + frames + links) in ONE real pass, so these are dead
#    weight by default. `--only search,images` still runs them for a full/paid deep-coverage
#    run (web_search's link set + collect_images' multi-engine scrape).
OFF_BY_DEFAULT = {"expand", "search", "images"}


def build_ctx(args):
    alias_csv = ""
    if args.aliases_file and os.path.exists(args.aliases_file):
        alias_csv = ",".join(ln.strip() for ln in open(args.aliases_file) if ln.strip())
    return {
        "name": args.name, "brand": args.brand, "slug": args.slug, "prefix": args.prefix,
        "aliases_file": args.aliases_file, "alias_csv": alias_csv, "strong": args.strong,
        "domains": args.domains, "fast": args.fast, "password": args.password,
        "web": getattr(args, "web", False),
        "live_chat": args.live_chat,
        # Google-results capture mode: browser (always try Incogniton, legacy), cse (headless
        # synthetic strip only, no browser), auto (Incogniton if the app is up, else CSE strip).
        "google_shots": getattr(args, "google_shots", "auto"),
        # attended gcapture: wait for the operator on captcha walls instead of skipping.
        # DEFAULT ON — pass --no-solve for a fully unattended run.
        "solve": getattr(args, "solve", True),
        "solve_wait": getattr(args, "solve_wait", 300),
        # partial (`--only …`) runs write deliverables next to the archived campaign; full runs
        # (run_az.sh) write to root and let run_az.sh tidy. See _out().
        "only": args.only,
    }


def _ensure_alias_file(ctx):
    """slug_triage/slug_probe resolve the alias variants via campaigns/<base>/<base>-aliases.txt
    or the repo-root <base>-aliases.txt — NOT via --aliases-file. A web/live scan passes a temp
    names file, so neither existed and triage ran on the bare handle: display-name tiles
    ("Sophie Rain") stopped token-matching, crawl corroboration counted 0 handle-carrying files,
    and the per-tile gate DROPped genuinely-hosting domains as pure echo (leakgallery 4.0k +
    fapeza 852 rows wiped from the sophieraiin webscan export). Materialize the root copy from
    the names file we were given so EVERY entry path triages with the full alias set. Never
    overwrites an existing (possibly hand-curated) alias file; webscan_* copies are removed by
    the public app's `{base}-*` scratch cleanup."""
    src = ctx.get("aliases_file")
    if not src or not os.path.exists(src):
        return
    base = os.path.basename(ctx["prefix"])
    dst = _p(None, f"{base}-aliases.txt")
    camp = _p(None, "campaigns", base, f"{base}-aliases.txt")
    if os.path.exists(dst) or os.path.exists(camp) or os.path.abspath(src) == dst:
        return
    try:
        shutil.copyfile(src, dst)
        print(f"[aliases] materialized {base}-aliases.txt from {os.path.basename(src)} "
              f"(slug_triage tile-matching needs the variants)", file=sys.stderr)
    except OSError:
        pass


def _hit_domains(prefix):
    """Unique domains from <prefix>-scan.csv (so crawl only visits sites that hit)."""
    import csv
    path = _p(None, f"{prefix}-scan.csv")
    if not os.path.exists(path):
        return ""
    doms = []
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        d = r.get("domain")
        if d and d not in doms:
            doms.append(d)
    return ",".join(doms)


def run(args):
    ctx = build_ctx(args)
    _ensure_alias_file(ctx)
    # Decide the Google-results capture mode ONCE, up front, so the operator sees why the
    # real (6b) pass runs or is skipped. Incogniton is never removed — only deferred to CSE.
    gmode = ctx.get("google_shots", "auto")
    if gmode == "auto":
        ctx["_incogniton_up"] = _incogniton_running()
        print(f"[google-shots] mode=auto · Incogniton "
              f"{'up → real capture (6b)' if ctx['_incogniton_up'] else 'offline → CSE strip (6d)'}",
              file=sys.stderr)
    else:
        print(f"[google-shots] mode={gmode} · "
              f"{'headless CSE strip only (6d), no browser' if gmode == 'cse' else 'always attempt Incogniton (6b)'}",
              file=sys.stderr)
    only = set(s.strip() for s in args.only.split(",")) if args.only else None
    for step in STEPS:
        if only and step["id"] not in only:
            continue
        # off-by-default steps run ONLY when explicitly named in --only, never on a full run
        if not only and step["id"] in OFF_BY_DEFAULT:
            print(f"\n=== [{step['id']}] {step['title']} ===\n    (off by default — "
                  f"run with `--only {step['id']}` to force)", file=sys.stderr)
            continue
        # hand the scan's hit-domains to the crawl so it doesn't walk all 375
        if step["id"] == "crawl" and not ctx.get("domains"):
            ctx["domains"] = _hit_domains(ctx["prefix"])
        argv = step["cmd"](ctx)
        print(f"\n=== [{step['id']}] {step['title']} ===\n    {step['desc']}", file=sys.stderr)
        if argv is None:
            print("    (skipped — prerequisite missing or disabled)", file=sys.stderr)
            continue
        print("    $ " + " ".join(os.path.basename(a) if a.endswith((".py", ".js")) else a for a in argv),
              file=sys.stderr)
        if args.dry_run:
            continue
        r = subprocess.run(argv, cwd=HERE)
        if r.returncode != 0 and not step.get("optional"):
            # A core step (scan/crawl/export/report) hard-failed. Continuing would build the
            # client deliverable from stale or empty upstream data — worse than stopping. Abort
            # loudly so the operator re-runs instead of shipping a wrong/empty report.
            print(f"\n!! FATAL: core step '{step['id']}' exited {r.returncode} — aborting the run so "
                  f"downstream steps don't build a report from stale/empty data.\n"
                  f"   Fix the cause and re-run (optionally `--only {step['id']},…` to resume).",
                  file=sys.stderr)
            sys.exit(r.returncode)


def main():
    ap = argparse.ArgumentParser(description="Run (or list) the whole leak→report pipeline.")
    ap.add_argument("--name", default="Ivette Aguero Tarazona")
    ap.add_argument("--brand", default="Tarita Fit")
    ap.add_argument("--slug", default="taritafit")
    ap.add_argument("--prefix", default="tarita")
    ap.add_argument("--aliases-file", default="tarita-aliases.txt")
    ap.add_argument("--strong", default="taritafit,taritafitness")
    ap.add_argument("--domains", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--live-chat", action=argparse.BooleanOptionalAction, default=True,
                    help="Bake a live DeepSeek assistant into the report (needs DEEPSEEK_API_KEY in "
                         ".env). ON BY DEFAULT (pass --no-live-chat to disable); degrades to canned "
                         "replies when no key is set. SECURITY: only the password-protected output "
                         "should be published.")
    ap.add_argument("--only", default="", help="Comma list of step ids to run.")
    ap.add_argument("--google-shots", choices=["auto", "cse", "browser"], default="auto",
                    help="Google-results capture mode. auto (default): real Incogniton pass when the "
                         "Incogniton app is up, else the headless CSE strip. cse: CSE strip only — no "
                         "browser touches google.com. browser: always attempt the Incogniton pass "
                         "(legacy). Incogniton is never removed; cse/offline just defer to the CSE strip.")
    ap.add_argument("--solve", action=argparse.BooleanOptionalAction, default=True,
                    help="ATTENDED gcapture (6b), DEFAULT ON: on a Google captcha wall, keep the browser "
                         "open, ping you audibly and WAIT for you to solve it (up to --solve-wait per "
                         "query) instead of the unattended skip. One solve usually clears the whole "
                         "session. Pass --no-solve for a fully unattended run that skips walled queries.")
    ap.add_argument("--solve-wait", type=int, default=300,
                    help="Seconds to wait per captcha wall in --solve mode (default 300).")
    ap.add_argument("--fast", action="store_true", help="80/20 mode: capped crawl, skip search/images.")
    ap.add_argument("--web", action="store_true",
                    help="public_app 'big scan' preset: bound the crawl for latency (like --fast) "
                         "but KEEP the screenshot steps (gcapture/gshots/gallery) that --fast disables. "
                         "Pair with --only scan,seed,crawl,clean,triage,cse,gcapture,gallery,gshots "
                         "--google-shots auto --no-solve. Ignored when --fast is also passed.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true", help="Print the step list and exit.")
    args = ap.parse_args()
    if args.list:
        for s in STEPS:
            tag = "(off)" if s["id"] in OFF_BY_DEFAULT else ("(opt)" if s.get("optional") else "     ")
            print(f"{s['id']:8} {s['title']:34} {tag}  {s['desc']}")
        return
    run(args)


if __name__ == "__main__":
    main()

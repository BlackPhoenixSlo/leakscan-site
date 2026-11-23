# HANDOFF: the Abolita free scan, for another app

For a developer (or their coding agent) who wants the free-scan feature inside their own app. Everything needed is in
this repo: `app/` (backend, Python stdlib + 3 packages) and `site/` (frontend, plain JS, no build). The backend files
in `app/` originally came from a private repo; `app/` is self-contained and nothing here needs that repo.
Checked against the code at `main` 9b85dfe (2026-11-23). If this file and the code disagree, the code wins.
The deep "ultra scan" (live streaming report, full 8-step pipeline) is a separate server in `ultra/`: section 7.

## 1. The feature

The user types an OnlyFans handle (+ optional Instagram or X). A quick scan runs (streamed progress). The
result is a report: link / site / image counts, a Google look-alike (All / Images / Videos tabs, blurred thumbs,
Reveal), sites ranked by link count, Mega packs found, an "Also found as" alias line. The same stored result then
personalizes the landing page, the demo site and a video page.

| URL | What | Checked (GET, 2026-11-23) |
|---|---|---|
| https://abolita.com/ | landing; hero form scans in place (`/?scan=<handle>&ig=<social>` = scan at once) | 200 |
| https://abolita.com/scan/ | full report page: `?h=<handle>&ig=<social>` runs a scan, `?r=<slug>` reopens one | 200 |
| https://abolita.com/video/ | personalized video: `?r=<slug>` (else last scan) or `?name=<text>`, `?t=<sec>` | 200 |
| https://scan.srv1395798.hstgr.cloud | API host (same container as abolita.com); `/healthz` → `{"ok": true, "domains": 375, "kb": true}` | 200 |
| https://www.abolita.com/ | 301 → apex | 301 |

Do not run real scans against these hosts to test: each one spends the owner's Google CSE / Browserbase / DeepSeek
money. Use the stub (section 4).

## 2. File map

### Backend `app/` (copy the whole folder; it is one process, `public_app.py`)

| File | Role in the quick scan |
|---|---|
| `public_app.py` | entry: HTTP server, every route, CORS, rate limits, the quick-scan pipeline (`_scan_cse`), reuse, retention loop |
| `web_common.py` | SSE helpers, client IP, handle cleaning, static serving |
| `db.py` | sqlite (`PUBLIC_DB`), slugs (`^[A-Za-z0-9_-]{6,24}$`), retention tiers |
| `ratelimit.py` | per-IP token bucket + concurrency cap |
| `cse_scanner.py` | Google Custom Search calls, hit rows, preview images |
| `alias_enrich.py` | reads a few found leak pages for her other handles, CSE-scans ≤ 2 of them |
| `leakshaven.py` | Mega pack lookup (public leakshaven.com JSON API) → `mega[]` |
| `profile_extract.py` | public profile (name, bio, accounts, avatar) via DeepSeek |
| `media_gather.py` | her SFW photos for the demo site, via a Browserbase remote browser (background, after the result) |
| `thumb_sheet.py` | optional: one request for all of a report's thumbs |
| `site_static.py` | serves `site/` from the same origin (`SITE_DIR`) |
| `netloc.py`, `leak_evidence.py`, `report_live.py`, `chat_proxy.py` | helpers imported by `public_app.py` |
| `bruqi_detection_map.json`, `kb.json`, `kb_landing.md`, `aliases.txt`, `fake_aggregators.txt` | data files (known leak domains, chat knowledge base, pipeline lists) |
| `public_static/` | legacy scan UI at `/app/` and share page `/s/<slug>`; not needed by `site/` |
| rest (`leak_scanner.py`, `leak_crawler.py`, `pipeline_steps.py`, `make_report.py`, …) | deep scan only (`level: "deep"`, spawned as subprocesses); the site never starts one. Keep them: `public_app.py`/`alias_enrich.py` import some |
| `tests/` | pytest suite; Google / DeepSeek / Browserbase faked at the wire |

### Frontend `site/` (no build; scripts are plain ES2017 globals, load order matters)

| Piece | Files | Needs |
|---|---|---|
| Transport, validators, API origin (always first) | `js/scan-engine.js` | none; `window.LeakScanEngine` |
| Full report page | `scan/index.html`, `js/scan.js`, `css/styles.css`, `css/scan.css` | engine |
| Hero scan in place + Google phone | `js/inline-scan.js`, `js/free-phone.js`, `js/strip-drift.js`, `js/main.js` (tabs) | engine; markup from `index.html` (`#scan` form, `.report-card`, `#free`) |
| Personalization (landing mockups, demo site `showcase/`) | `js/personalize.js` (+ `showcase/` if you want the demo site) | engine |
| Mega / X / Reddit / leak-site removal panels | `js/removals.js`, `css/removals.css`, `img/removals/` | engine |
| Personalized video | `video/index.html` (+ `jack*.webm/mp4`, `jack-poster.webp`, `img/`, `transcript.json`), `js/video-overlays.js`, `css/video.css`, `js/removals.js` | engine |
| Mini player of the video | `js/pip.js`, `css/pip.css` | `video/` same origin |
| Fonts / icons | `fonts/`, `assets/` | |

Skip: `faq/`, `removals/*.html`, `compare/` (marketing / SEO pages), `privacy.html` / `imprint.html` (write your own),
`js/analytics.js` (Google Ads conversion ids of the owner; inert only when `ADS_ID` is ''), `js/chat.js` + `css/chat.css`
+ `POST /api/chat` (optional "Ask AI" chat, spends DeepSeek), `tools/` (tests, stub, screenshots; keep `tools/scan_stub.py`
for UI work).

API origin rule (`js/scan-engine.js` line 8): `<body data-api="https://your-api">` wins; else on `*.github.io` the VPS
API host; else same origin. Results render with `textContent` / `createElement` only; leak URLs are shown as host /
path, never injected.

## 3. API contract (from `app/public_app.py`)

All JSON is UTF-8. Result routes send `X-Robots-Tag: noindex, nofollow` and `Referrer-Policy: no-referrer`.

### `POST /api/public-scan`

Request (JSON, ≤ 2048 bytes else 413 `{"error":"payload_too_large"}`):

| Field | Rule |
|---|---|
| `handle` | first whitespace/comma token matching `^[A-Za-z0-9._-]{1,60}$` |
| `platform` | one of `onlyfans.com fansly.com instagram.com tiktok.com patreon.com manyvids.com`, else `onlyfans.com` |
| `level` | `"low"` (the site always sends this). `"deep"` = background pipeline, JSON `{slug, level, status:"running", handle, platform}`, then poll `scan-result` |
| `instagram`, `x` | optional; `@h` or `instagram.com/h`, `x.com/h`, `twitter.com/h`; invalid = silently dropped |
| `fresh` | `true` = skip reuse of a recent identical scan |

Before the stream (plain JSON): `429 {"error":"rate_limited"}` (per-IP bucket or 2 scans already in flight from that
IP); deep only: `429 {"error":"busy"}` (global cap `MAX_GLOBAL_SCANS`), `400 {"error":"bad_handle"}`,
`503 {"error":"unavailable"}`.

Low scan answer: `200 text/event-stream`, events `progress` (text), then either one `result` (JSON) or one `failed`
(text: invalid handle, CSE not configured, Google not answering), then `done` (`end`). The client must POST and read
the body as a stream (`EventSource` can't POST; see `streamScan` in `js/scan-engine.js`, 240 s timeout). A failed
Google call with no hits stores nothing and refunds the rate-limit token.

Captured from the stub (`curl -sN -X POST -H 'Content-Type: application/json' -d
'{"platform":"onlyfans.com","handle":"demo_creator","level":"low","instagram":"demo.ig"}' http://127.0.0.1:8931/api/public-scan`),
lists trimmed to one item (real counts: images 18, hits 32, results 60, mega 2):

```
event: progress
data: call 1/8 [demo_creator]: +10 results, +4 domains
...
event: result
data: {...}

event: done
data: end
```

```json
{
 "slug": "fWBqnteVN1wV", "handle": "demo_creator", "platform": "onlyfans.com", "level": "low",
 "status": "complete", "hit_count": 32, "domain_count": 22, "google_total": 1240,
 "images": ["https://encrypted-tbn0.gstatic.com/images?q=tbn:DEMO0001placeholder"],
 "hits": [{"domain": "leakvault.example", "url": "https://leakvault.example/gallery/1000/demo-creator",
           "occurrences": 9, "method": "google", "alias": null, "live": true,
           "title": "demo.creator leaks - Free Gallery - Leakvault"}],
 "results": [{"title": "demo.creator Free Gallery - Leakvault",
              "link": "https://leakvault.example/free-gallery/2000/demo-creator",
              "snippet": "demo.creator free gallery on Leakvault. ...",
              "thumb": "https://encrypted-tbn0.gstatic.com/images?q=tbn:DEMO0001placeholder",
              "domain": "leakvault.example", "kind": "page"}],
 "profile": {"display_name": "Mira Example", "first_name": "Mira", "username": "demo.creator",
             "platform": "onlyfans.com", "tagline": "illustrator of quiet city mornings", "profession": "illustrator",
             "location": "Lisbon, Portugal", "bio": "...", "about_short": "...", "followers": 12000,
             "accounts": [{"platform": "instagram", "handle": "mira.example", "url": "https://www.instagram.com/mira.example/"}],
             "site_domain": "miraexample.com", "avatar": true, "sources": ["synthetic fixture"],
             "confidence": 0.9, "generated_by": "fixture"},
 "aliases": {"declared": ["demo_creator", "demo.ig"], "discovered": ["demo.creator.vip", "demostudio"],
             "socials": [{"platform": "fansly", "handle": "demo.creator.vip",
                          "url": "https://fansly.com/demo.creator.vip", "source_domain": "leakvault.example"}]},
 "as_of": "2026-11-23T11:17:27Z",
 "mega": [{"url": "https://s.leakshaven.com/DEMOpack0", "host": "leakshaven.com", "via": "leakshaven.com",
           "title": "demo.creator MEGA pack 2026", "size": 6657199309, "images": 412, "videos": 88,
           "age": "2026-11-20T11:07:24Z", "status": "live"}],
 "socials": {"instagram": "demo.ig"}
}
```

Notes: `hits` = one row per host (the Sites list); `results` = Google items (≤ 80, `kind` `page` | `video`, `thumb`
only gstatic) = All / Videos tabs; `images` = Google thumb URLs = Images tab; `status` `complete` | `empty`;
`google_total` is an estimate, not Google's number; `profile` may be `null`. The real API also sends
`media: {"status": "pending"|"ready"|"none"}` (the stub omits it). Hosts in `mega[]` never appear in `hits` / `results`.

### GET routes

| Route | Answer | Limit bucket |
|---|---|---|
| `/api/scan-result/<slug>` | the stored result: `slug level platform handle created_at as_of status hit_count domain_count ownership_verified hits images google_total slugs mega`, low scans also `results profile socials aliases media{status}`, after retention `retention` (`full`/`trimmed`/`summary`) + `top_domains`. 404 `{"error":"not_found"}`; deep running → `{status:"running", phase, log, …}`; orphaned → `{status:"failed"}` | result |
| `/api/profile/<slug>` | `{slug, profile}` (poll after `media.profile_updated_at` moves) | result |
| `/api/avatar/<slug>` | image bytes saved at scan time, else 404 | thumb |
| `/api/media/<slug>` | `{slug, status: pending\|ready\|none, images:[{src, w, h, source}], updated_at, profile_updated_at}`; site polls every 3 s ≤ 90 s | result |
| `/api/media/<slug>/<n>.jpg` | photo `n` (0-11) | thumb |
| `/api/thumb?u=<https url>` | proxy for Google thumbs only (`gstatic.com`, `googleusercontent.com`, `ggpht.com`; no redirects, ≤ 3 MB); 400 / 415 / 413 / 502 otherwise. Needed so the page can read pixels (CORS) and blur / filter logos | thumb |
| `/api/thumb-sheet/<slug>` | optional batch of a report's thumbs (format: `app/thumb_sheet.py` docstring); any non-200 = client falls back to `/api/thumb` | 30/min, burst 20 |
| `/api/scan-links/<slug>?set=accepted\|removed` | deep scans: text download | result |
| `/healthz` | `{ok, domains, kb}` | none |

### Limits, CORS

| Bucket (per client IP) | Default |
|---|---|
| scan `POST /api/public-scan` | 5/min, burst 5, 2 in flight (`RATE_PER_MIN`, `RATE_BURST`, `MAX_CONCURRENT`); deep also `MAX_GLOBAL_SCANS`=4 |
| result | 60/min, burst 30 |
| thumb | 120/min, burst 60 (a report loads ~30 thumbs; a 429 here is not a dead thumb) |

Client IP = `X-Real-IP`, else last `X-Forwarded-For` hop when `TRUST_XFF=1`, else the socket peer. All 429s are JSON
`{"error":"rate_limited"}`.

CORS: only origins listed in `CORS_ORIGINS` (comma list, exact match) get `Access-Control-Allow-Origin` + `Vary:
Origin`; preflight `OPTIONS` → 204 with `GET, POST, OPTIONS` / `Content-Type`, max-age 86400. Unknown origin → bare
204, so the browser blocks the call (checked live: `Origin: https://example.com` gets no ACAO header).

## 4. Run it locally

Deps: Python 3.12+ (image: 3.13), `pip install pytest Pillow curl_cffi playwright` (CI's list; Playwright browsers not
needed by the app).

| Mode | Command | Keys |
|---|---|---|
| Stub (UI work) | `python3 tools/scan_stub.py [--port 8930]` → http://127.0.0.1:8930/ | none, stdlib only; synthetic fixture `tools/fixtures/scan-sample.json` |
| Real app | `SITE_DIR=site PUBLIC_PORT=18084 PUBLIC_DB=/tmp/public.db python3 app/public_app.py` | none = scans end in `failed` "Quick search isn't configured right now" with no outside call |
| Docker | `docker build -f deploy/Dockerfile .` ; compose: `deploy/docker-compose.yml` (Traefik labels and the external `n8n_default` network are the owner's VPS: drop them) | `.env` one level above `deploy/` |
| Tests | `python3 -m pytest -q app/tests` and `python3 tools/check.py` (CI: `.github/workflows/ci.yml`) | none |

Stub: injects `<body data-api>` pointing at the other loopback name (so calls are cross-origin like production);
preloaded slugs `demoR3port01`, `demoNoProf01`, `demoHuge0001`, `demoVideos01`, `demoAged1`, `demoTrimmed1`, `demoSummary1`, …;
magic handles `stub-fail` (`failed` event), `stub-429`, `stub-busy`, `stub-empty`, `stub-mixed`, `stub-huge`,
`stub-videos`. Full list: docstring of `tools/scan_stub.py`. Differences from the real API: an invalid handle or
social gets `400 bad_handle` (real: `failed` event / dropped social); results carry no `media` field.

Env vars (`deploy/.env.example`; container defaults in `deploy/Dockerfile`):

| Var | Does |
|---|---|
| `GOOGLE_API_KEY`, `GOOGLE_CSE_ID` | Google Custom Search; without both the quick scan can't run |
| `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL` | profile extraction + refine (and chat); without it `profile` is the non-LLM `fallback_profile` |
| `BROWSERBASE_API_KEY`, `BROWSERBASE_PROJECT_ID`, `BROWSERBASE_PROXIES` | remote browser for her photos (`media`); code default proxies on, example sets 0 |
| `MEDIA_ENABLED`, `MEDIA_BROWSERBASE`, `MEDIA_BUDGET`, `MEDIA_MAX`, `MEDIA_GOOGLE` | photo step on/off, seconds per gather, photos per scan (≤ 12), `browser`/`cse`/`off` |
| `PROFILE_ENABLED`, `PROFILE_CSE_EXTRA`, `PROFILE_LLM_TIMEOUT`, `PROFILE_BUDGET` | profile step |
| `ALIAS_ENRICH`, `ALIAS_BUDGET`, `LEAKSHAVEN_ENABLED`, `LEAKSHAVEN_TIMEOUT` | alias step, Mega lookup |
| `CORS_ORIGINS` | browser origins allowed cross-origin (default `https://blackphoenixslo.github.io`) |
| `PUBLIC_ORIGIN` | prefix of `/api/media/…` photo srcs. **Code default is the owner's API host**: self-hosting, set it to your API origin, or empty for same-origin relative srcs (the frontend accepts only `<API>/api/media/…` or same-origin) |
| `PUBLIC_DB`, `DATA_DIR`, `SITE_DIR`, `PUBLIC_HOST`, `PUBLIC_PORT`, `TRUST_XFF` | storage, site root (missing dir = site off), bind, proxy trust |
| `SCAN_REUSE_TTL` | seconds a finished scan is reused for identical inputs (21600; 0 = off) |
| `RETAIN_BIG_DAYS`, `RETAIN_SMALL_DAYS` | retention (3 / 30 days) |
| `RATE_*`, `MAX_*`, `CHAT_*`, `VERIFY_*`, `CSE_*`, `DISPLAY_*`, … | caps and tuning; defaults listed in the example file |
| `LEAKSCAN_PORT`, `LEAKSCAN_HOST`, `SITE_HOST`, `SITE_HOST_WWW` | compose / Traefik routing only |
| `DM_TELEGRAM`, `DM_INSTAGRAM`, `DM_WHATSAPP` | contacts in the legacy `/app/` UI |

Do not use `deploy/push.sh`: it deploys to the owner's VPS.

## 5. Integration options

| Option | How | Catch |
|---|---|---|
| (a) Call the hosted API | your page loads the `site/js` modules with `<body data-api="https://scan.srv1395798.hstgr.cloud">` | the owner must add your origin to `CORS_ORIGINS`; every scan spends the owner's keys; per-IP limits are his; your users' scans land in his DB |
| (b) Self-host `app/` | run the container with your own keys, `CORS_ORIGINS=<your app origin>`, `PUBLIC_ORIGIN=<your API origin>` | you pay Google / DeepSeek / Browserbase; you own the data |
| (c) Port the frontend | copy the files in section 2 for the pieces you want, keep the markup classes their scripts query, point `data-api` at (a) or (b) | the scripts target the markup in `site/index.html`, `site/scan/index.html`, `site/video/index.html`; re-skin with CSS, don't rename hooks |

Recommended: **(b) + (c)**. Run `app/` as its own container with your keys and your app's origin in `CORS_ORIGINS`,
then embed `scan-engine.js` + `scan.js` (report) + `inline-scan.js` / `free-phone.js` (in-place scan) + `video/` with
`data-api` set to it. Build the UI against `tools/scan_stub.py` first (zero keys), switch `data-api` to your container
last. (a) only for a demo, after the owner has added your origin.

## 6. Costs, safety, retention

| Per quick scan | Spend |
|---|---|
| Google CSE | 8 calls (+1 per declared social), +1 fallback page when < 7 sites, + ≤ 16 for discovered aliases: worst case 25 (+1 `PROFILE_CSE_EXTRA`) |
| DeepSeek | 1 profile call + 1 refine call in the photo step; chat, if used, per message |
| Browserbase | one remote-browser session, ≤ `MEDIA_BUDGET` s (90), more with proxies (`MEDIA_GOOGLE=cse`: CSE image calls instead of the browser's Google step) |
| leakshaven.com | 2 free public requests |
| repeat of the same inputs within `SCAN_REUSE_TTL` | 0 outside calls |

- Rate limits above are the only abuse guard; there is no login. Keep them, behind a proxy set `TRUST_XFF=1` or `X-Real-IP`.
- Retention by row age: after 3 days images / results / photos / avatar are deleted; after 30 days only counts +
  top domains stay, IP hash nulled. Rows are never deleted. IPs are stored hashed only.
- Consent: the scan searches for adult-content leaks of a named person and stores the result under an unguessable but
  shareable slug (`secrets.token_urlsafe(9)`). Only let creators scan their own handles (or with their written consent); don't run it on
  people who didn't ask. Show your own privacy notice (`site/privacy.html` is the owner's).
- The results contain links to pirated adult content: never render leak pages or unblurred thumbs by default (the
  site blurs until Reveal).

## 7. Ultra scan (`ultra/`, the live deep scan)

https://jackbase.me/leakscan → 301 `www.` → 302 → `http://72.62.92.114:6767/` ("Live leak report"). One visitor types a
handle and watches the full pipeline run live: progress bar over 8 steps, a wall of found media streaming in, links
grouped by site (copy / download / mail), Google look-alike grids, a downloadable card with QR, optional chat. Every
scan gets its own shareable `/s/<slug>` page. Not the quick scan of sections 1-6: no sqlite, no CORS, its own page.

`ultra/` is self-contained (stdlib `http.server` + SSE, one process, spawns `pipeline_steps.py` subprocesses with
`cwd=ultra/`). Copied from the deployed build (2026-11-23) with two changes: creator names / handles in comments,
examples and CLI defaults replaced by placeholders (`janedoee`, `jdoeex`, `examplefit`, …), and `/asset` serves image
types only. Several modules share a name with `app/` but are newer; keep the two folders apart.

### Files

| File | Role |
|---|---|
| `live_stream_site.py` | entry: HTTP server, every route, the page (HTML/CSS/JS inline), sessions, the two-phase scan driver |
| `pipeline_steps.py` | the pipeline as a list of steps (`--only a,b,c`); each step spawns one script below |
| `leak_scanner.py` | step `scan`: which of the ~375 domains in `bruqi_detection_map.json` host the handle |
| `build_linkcards.py` | synthetic "leak index" browser screenshots (Playwright; skipped without it) |
| `discovery_seed.py`, `leak_crawler.py`, `seed_url_crawl.py`, `clean_crawl.py`, `slug_triage.py`, `expand_variants.py` | seed, deep crawl, clean, triage, mirror variants |
| `build_cse.py`, `cse_scanner.py` | step `cse`: Google Custom Search (web + image) |
| `build_gallery.py`, `build_google_shots.py`, `google_shots.py` | gallery + Google-Images style grids (from CSE data; the Incogniton browser path is off on the VPS) |
| `export_dmca.py`, `make_report.py`, `report_to_pdf.py`, `dmca_finder.py` | DMCA export (LIKELY / POSSIBLE), report, abuse contacts |
| `title_aliases.py`, `username_variations.py`, `slug_probe.py`, `web_search.py`, `collect_images.py`, `recovery_demo.py` | alias harvest, variants, helpers imported by the steps |
| `chat_proxy.py` | `POST /api/chat` → DeepSeek; reads `kb.json` if present (not shipped here; chat runs without it) |
| `web_common.py`, `fetch_common.py`, `netloc.py`, `leak_evidence.py`, `browser_common.py`, `connect_incogniton.py` | SSE, fetch (curl_cffi, urllib fallback), host rules, browser glue |
| `bruqi_detection_map.json`, `fake_aggregators.txt` | known leak domains + URL templates; SEO-spam hosts to drop |
| `fixtures/demo.crawl.json` | synthetic crawl (`*.example` hosts) for the offline demo report below |

Scan output lands in `ultra/webscans/`, session sidecars in `ultra/.live_sessions/` (both git-ignored).

### The 8 steps (progress bar ← `pipeline_steps.py` ids)

| # | Bar label | Step ids | Script |
|---|---|---|---|
| 1 | Presence scan | `scan` | `leak_scanner.py` |
| 2 | Google & CSE | `cse`, `gshots` (`gcapture`, `images` off) | `build_cse.py`, `build_google_shots.py` |
| 3 | Seed frontier | `seed` (`seedurl`) | `discovery_seed.py` |
| 4 | Deep crawl | `crawl` | `leak_crawler.py` |
| 5 | Clean & dedupe | `clean` | `clean_crawl.py` |
| 6 | Triage | `triage` | `slug_triage.py` |
| 7 | Gallery | `gallery` | `build_gallery.py` |
| 8 | Export & report | `export` (`report`) | `export_dmca.py` |

Run order per scan: title-harvest aliases (`title_aliases.py`, plain HTTP) → phase 1 = `scan` ‖ `cse` (two concurrent
subprocesses; partial crawl waves start on domains as `scan` prints `FOUND <domain>`) → phase 2 =
`seed,crawl,clean,triage,gallery,gshots,export` with `--resume-crawl`. One pipeline subprocess at a time across all
sessions (a second scan shows "queued"). The exact commands are printed in the scan console.

### API contract (from `ultra/live_stream_site.py`)

`?job=<slug>` binds a call to a scan; without it the call hits the empty landing session.

| Route | Answer |
|---|---|
| `GET /`, `GET /s/<slug>` | the page (same shell; JS reads the slug from the path). A misread `/s…` link 302s to the right slug or `/` |
| `GET /healthz` | `ok` (never gated) |
| `GET /api/state` | snapshot: `seq total pages domain_count elapsed mode source status done domains recent asset_counts report by_domain dm chat_enabled scan_enabled scan{running status handle prefix seq rc cmd phase lines} prefix slug`; 404 unknown job |
| `GET /api/stream` | SSE: `snapshot` (state + assets), then `batch` `{events:[{seq,t,domain,url,kind}], state}`, `: ping` every 10 s, `done` |
| `GET /api/scan/stream` | SSE of the scan console: `snapshot`, `lines` `{lines, scan}`, `end` (final scan snapshot) |
| `GET /api/assets` | `{gallery, cse, grids, linkcards, …}` asset catalog |
| `GET /api/links?bucket=LIKELY\|POSSIBLE&fmt=txt\|download&diff=1` | found URLs, one per line (`download` = attachment) |
| `GET /api/sessions` | every scan on the server: `[{slug, handle, prefix, created, state: running\|queued\|done, status, total, viewers}]` |
| `GET /asset?p=<path>&w=<px>` | an image under `ultra/` (downscaled with Pillow when `w`) |
| `GET /media?u=<url>&w=<px>` | remote image proxy + thumbnail (refuses private / loopback hosts) |
| `GET /qr?u=<this server's /s/<slug> URL>&sz=4..16` | PNG QR (needs `qrcode`, else 404) |
| `POST /api/scan` `{handle, aliases[≤12], no_cse, no_variations}` | `{ok, slug, share:"/s/<slug>"}`; 400 `handle required`; 429 `busy` when `MAX_LIVE_SCANS` slots are taken; 503 when `SCAN_ENABLED=0` |
| `POST /api/scan/cancel?job=<slug>` | `{ok:true}` |
| `POST /api/sessions/delete` `{slug}` | cancel + forget + wipe that scan's files |
| `POST /api/mail?job=<slug>` `{email, bucket}` | mails the links as an attachment via `SMTP_*`; `{ok:false,"error":"email not configured on this host"}` without them |
| `POST /api/chat` `{messages, scan_context}` | SSE DeepSeek answer; 503 without `DEEPSEEK_API_KEY` |

Access: `LIVE_TOKEN` set = every route but `/healthz` needs `?t=<token>` once (then a cookie). There is no per-IP rate
limit and no auth on the session routes (anyone who can reach it can list, open, cancel and delete every scan, and
start scans until the slots are full). Self-hosting on a public address: set `LIVE_TOKEN` or put it behind your app's
auth.

### Run it locally (no keys)

Deps: Python 3.12+, `pip install Pillow curl_cffi` (the deployed image: `python:3.13-slim` + those two,
`CMD python3 live_stream_site.py --no-open`, `HOST=0.0.0.0`). Optional: `qrcode` (card QR), `beautifulsoup4` +
`playwright` (browser-only steps; they skip without them).

| Mode | Command | Outside calls |
|---|---|---|
| Demo report (UI work) | see below, then http://127.0.0.1:8095/s/demoReport01 | none (fixture hosts are `*.example`) |
| Landing only | `cd ultra && SCAN_ENABLED=0 python3 live_stream_site.py --no-open --port 8095` | none |
| Real scan | `cd ultra && python3 live_stream_site.py --no-open --port 8095`, then Start | crawls ~375 public leak sites from your IP; CSE / chat only with their keys |

Demo report = a finished scan rebuilt from disk (65 links on 4 sites; also listed under "Live scans on this server"):

```
cd ultra && mkdir -p .live_sessions webscans
cp fixtures/demo.crawl.json webscans/webscan_demo.crawl.json
echo '{"slug":"demoReport01","handle":"democreator","prefix":"webscans/webscan_demo"}' > .live_sessions/demoReport01.json
SCAN_ENABLED=0 python3 live_stream_site.py --no-open --port 8095
```

No tests ship for `ultra/`.

### Env

| Var | Does |
|---|---|
| `GOOGLE_API_KEY`, `GOOGLE_CSE_ID` | step `cse` (web + image search); without them `cse` stops at "CSE not configured" with no Google call |
| `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`, `CHAT_MAX_TOKENS` | chat (700 tokens/answer, last 8 turns) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `SMTP_FROM_NAME` | "mail me the links" |
| `DM_INSTAGRAM`, `DM_WHATSAPP`, `DM_TELEGRAM` | contact buttons |
| `SCAN_ENABLED` (code default 1 when `pipeline_steps.py` exists), `MAX_LIVE_SCANS` (4; VPS 2), `SESSION_TTL` (21600 s), `LIVE_TOKEN` | scan on/off, slots, idle GC, access gate |
| `HOST`, `PORT` (127.0.0.1:8090), `TRUST_XFF`, `WEBSCAN_DIR`, `REPORT_PREFIX`, `PER_DOMAIN_LINKS`, `LINKS_CAP` | bind, scratch dir, single-campaign mode, link caps |
| `INCOGNITON_*`, `CAPTCHA_ALERT*`, `SHOT_*` | desktop-browser screenshot path (off on the VPS: `INCOGNITON_DISABLE=1`) |

### Costs per ultra scan

| Service | Spend |
|---|---|
| Google CSE (paid after the free daily quota) | step `cse`: up to 2 + 15 web + 6 image = **≤ 23 calls**; `no_cse` = 0 |
| DeepSeek | 0 per scan; 1 call per chat message |
| SMTP | 1 mail per "mail me" |
| Browserbase | none (not used by this build) |
| Leak sites | free, but a full crawl is minutes of outbound requests to ~375 adult hosts from the server's IP |

Same consent and display rules as section 6: scan only creators who asked, blur by default.

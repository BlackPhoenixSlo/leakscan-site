# HANDOFF: the Abolita free scan, for another app

For a developer (or their coding agent) who wants the free-scan feature inside their own app. Everything needed is in
this repo: `app/` (backend, Python stdlib + 3 packages) and `site/` (frontend, plain JS, no build). The backend files
in `app/` originally came from a private repo; `app/` is self-contained and nothing here needs that repo.
Checked against the code at `main` 9b85dfe (2026-11-23). If this file and the code disagree, the code wins.

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

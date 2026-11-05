# leakscan-site

Google Ads landing site for Abolita: personal leak-removal service for creators. Static HTML/CSS/JS, no build, no
cookies, no third-party requests on the landing pages. `site/` is what ships. `site/showcase/` is the demo of
the official site each client gets (fictional creator, built from the tessa template); the landing page links and
iframes it as `showcase/`. The demo loads Google Fonts (so the homepage does too, via the iframe); `privacy.html`
discloses that and `tools/check.py` keeps the two in sync. Its own
gates live in `tools/showcase/` (`check_ready.py`, `check_pages.py`, `check_deploy.py`, `_check_accounts.py`).

- Landing page (`site/index.html`), top to bottom: `#top` hero (scan form, live report card) · `#free` one Google
  phone (All / Images / Videos tabs; after a scan her real results, `js/inline-scan.js`) · `#why` · `#how` (7 steps) ·
  `#website` · `#showcase` (demo iframe with a "Full screen" in-page pop-out: Esc / button / backdrop close, page
  behind inert, focus back to the button; then the Before / After Google phones, real ARIA tabs, `js/main.js`) ·
  `#pricing` · `#faq` · `#removals` · `#contact`. `tools/check.py` fails if a section id is missing here.
- `#removals` "Where I remove from" (`js/removals.js` + `css/removals.css`, own files): four mock panels (Mega, X,
  Reddit, a leak site), each a live leak vs. its removed state. Remove / Show again animates the compare edge; the
  handle drags (pointer anywhere on the stage, arrow / PageUp / PageDown / Home / End on the handle); "Reveal images"
  unblurs the `img/removals/` thumbs. Personalized from the same shared scan result as the hero card (`?r=` or last
  scan, and after an in-page scan by wrapping `LeakScanPersonalize.apply`): Mega from the result's top-level `mega[]`
  (always present, `[]` = none; first item's `title`, `size` in bytes, `images`, `videos`, `age` ISO UTC; its `url` is
  an aggregator page and is never shown), else a mega.nz hit's title; X poster + text, Reddit subreddit + title, the
  most-seen other host, `/api/thumb` thumbs. textContent only; leak URLs are read for host / path, never rendered.
- Free scan: the hero form (`#scan`) scans in place with JS (see "Inline scan" below); without JS it GETs
  `h=<onlyfans>&ig=<instagram or x>` to `scan/` (`site/scan/index.html` +
  `css/scan.css` + `js/scan.js`, noindex, not in the sitemap). The page POSTs to Jaka's scan API
  (same origin, except on `*.github.io` → `https://scan.srv1395798.hstgr.cloud`; set once at the top of `js/scan-engine.js`
  and `js/personalize.js`, overridden by `<body data-api>`), reads the
  SSE stream (progress → result → done), then renders the report: summary, a Google look-alike (All / Images / Videos,
  Phone / Computer, thumbnails via `/api/thumb`, blurred until Reveal), per-site table, all links (copy / .txt) and the
  prefilled message CTAs. The URL becomes `scan/?r=<slug>`, which reopens the report via `GET /api/scan-result/<slug>`;
  the report link in the messages is `scan/?r=<slug>` on the host serving the page (resolved from `js/scan-engine.js`'s URL).
  Without JS it links to https://jackbase.me/scan.
- Personalization (`js/personalize.js`): after a scan the landing page and the demo site (`showcase/`) show her data.
  Slug: `?r=` → `localStorage['leakscan.last']` (written by `scan.js`) → none (page unchanged, no API call). One
  `GET /api/scan-result/<slug>` per tab (sessionStorage cache, 8 s timeout, failure = defaults; on the landing the hero
  card's request from `js/scan-engine.js` is shared, and a `?r=` link opened with the card below the fold scrolls it up); every value is
  validated and rendered with textContent / built elements, never leak titles or snippets. Landing: hero line +
  Reset, both "Your website" phones (name, top-4 leak domains by occurrences, blurred `/api/thumb` thumbs, IG / TikTok /
  site rows hidden when unknown), hero card handles, showcase url bar + iframe `showcase/?r=`. Slots are `data-p="…"`.
  Demo: only with `profile` (else Orla stays); name / bio / facts / links from `data-p-tpl` templates, everything not
  marked is hidden (no pottery next to her name), avatar via `/api/avatar/<slug>` when `profile.avatar`, `?r=` kept on
  links. Photos arrive later: `GET /api/media/<slug>` polled every 3 s for ≤ 90 s (stops on ready / none / 2nd 404),
  swapped in with fade, fixed boxes; only `<API>/api/media/…` or same-origin `/api/media/…` srcs. The scan report card
  links to `../?r=<slug>#website` + `../showcase/?r=<slug>` and shows "Gathering photos…" → "Photos ready".
  `window.LeakScanPersonalize = {apply(result), applySlug(slug), pollMedia(slug, cb)}` re-personalizes in place
  (idempotent) for a future inline scan.
  Privacy: the slug lives only in this browser (localStorage, plus the cached result in sessionStorage); "Reset page"
  clears it. Nothing is sent anywhere except the API reads above.
- Scan stub: `python3 tools/scan_stub.py [--port 8930]` serves `site/` plus the API routes from the synthetic fixture
  `tools/fixtures/scan-sample.json` (magic handles `stub-fail`, `stub-429`, `stub-busy`, `stub-empty`, `stub-mixed` (live true / false / missing);
  echoes `instagram` / `x` as `socials`; `--omit-results`
  for break-it runs; `--omit-profile` drops `profile`; `--media normal|relative|scanhost|none|404`, or per slug
  `POST /__stub/media?slug=&mode=`; preloaded slugs `demoR3port01`, `demoNoProf01` (no profile), `evilR3port01`
  (malicious values); `/api/profile`, `/api/avatar`, `/api/media` routes). It injects `data-api` pointing at itself (other loopback name, so CORS is exercised).
  E2E: `cd ~/leakhunt && uv run python ~/leakscan-site/tools/scan_e2e.py OUT_DIR` (starts its own stub; phone + desktop;
  form → progress → report, tab counts, device toggle, Reveal, CTAs, `?r=` reopen, error paths; never calls prod).
  `--only scan|personalize|askai|inline|tabs|removals` (`tabs`: phone tabs + demo pop-out; `removals`: the panels,
  toggle, drag, keys, `mega[]` / hit personalization). Break-it flags (each turns only its own checks red):
  `--break-allowlist`, `--break-drift`, `--break-phones`, `--break-thumbs`, `--break-remove`. `personalize` covers the flow above (no-slug text identical to the page without personalize.js / inline-scan.js, phones, demo pages,
  media swap / none / 404, scan-only, malicious fixture, localStorage + Reset, public API). Checks named `profile: …`
  need `profile`; `--omit-profile` turns only those red.
- Ask-AI popup: `js/chat.js` + `css/chat.css`, markup at the end of `index.html` (launcher + `<dialog id="askai">`; also
  opened by any `[data-askai-open]` link; on phones (<720px) the launcher stays hidden while the hero is on screen). Chips and typed questions that fuzzy-match an FAQ question (or "what does it
  cost") are answered instantly from the page's own FAQ / pricing text, no network. Everything else streams from
  `POST <API>/api/chat` (`{kb:"landing", messages (last 8), slug?}` → SSE `token`/`done`/`failed`; API origin =
  `<body data-api>`, else the scan server on github.io, else same origin; from file:// or on any error → contacts). Answers are built as DOM nodes;
  links are live only for existing `#ids` and `https://` t.me, wa.me, blackphoenixslo.github.io, abolita.com, jackbase.me,
  the scan server, plus `mailto:me@jackbase.dev`. Chat lives in sessionStorage only. Stub: `/api/chat` with magic words
  `stub-fail` / `stub-429`. E2E: `scan_e2e.py OUT_DIR --only askai` (`--break-allowlist` for the break-it run).
- Preview: `python3 -m http.server 8920 --directory site` → http://127.0.0.1:8920/
- Gate: `python3 tools/check.py` (silent + exit 0 when green; prints each problem + exit 1). Runs in CI on every push/PR.
  `.github/workflows/ci.yml` also runs `python3 -m pytest -q app/tests`.
  Covers links/assets resolve, no unreferenced files in `assets/ css/ js/`, canonicals, sitemap, JSON-LD (+ FAQ sync),
  one h1, unique ids, img alt/size, lang, viewport, meta/OG/Twitter, no third-party resources. Full list: docstring.
- Shots: `python3 tools/shots.py OUT_DIR URL...` → phone (390x844 @2x) + desktop (1440x900), light + dark, top + full.
  File names are the URL path relative to the URLs' common directory (`/` -> `index`, `/showcase/` ->
  `showcase-index`), so one run never overwrites itself. Needs Playwright with Chromium; system `python3` works here,
  fallback: `cd ~/leakhunt && uv run python ~/leakscan-site/tools/shots.py OUT_DIR URL...`.
  Evidence goes outside the repo: `~/.leakscan-site/evidence/<branch>/<UTC>-<sha7>/`.
- Raster assets: `python3 tools/make_icons.py` renders `site/assets/og.png` (from `tools/og.html`),
  `apple-touch-icon.png` and `favicon-32.png` (from `site/assets/favicon.svg`).
- Deploy: VPS = `deploy/push.sh` (see "One project, one origin" below). Push to `main` →
  `.github/workflows/pages.yml` runs the gate and deploys `site/` to GitHub Pages
  (https://blackphoenixslo.github.io/leakscan-site/), the fallback during the DNS transition. `netlify.toml` publishes `site/` if connected to Netlify.
- Improvement loop: `LOOP.md`.

## One project, one origin (VPS)

One container serves everything from the same origin (test host https://abolita.srv1395798.hstgr.cloud, later
https://abolita.com; the API host https://scan.srv1395798.hstgr.cloud is the same container):

| Path | Served by |
| --- | --- |
| `/api/*`, `/static/*`, `/s/<slug>`, `/healthz` | scan backend `app/public_app.py` (unchanged behaviour) |
| `/app/` | legacy scan UI (`app/public_static/`, was `/`) |
| `/?p=&h=&go=&l=` | 302 → `/app/?<same query>` (old jackbase.me/scan deep links) |
| everything else (`/`, `/scan/`, `/showcase/…`, `/privacy.html`) | landing site `site/` via `app/site_static.py` |

- `app/` = the backend, flat like prod (`HERE`-relative paths): `public_app.py` + its import closure + every script
  it spawns for deep scans + data files (`kb.json`, `bruqi_detection_map.json`, `aliases.txt`, `fake_aggregators.txt`,
  `public_static/`). `public_app.py`, `cse_scanner.py`, `profile_extract.py`, `media_gather.py` and `app/tests/` come
  from `bruquiextension` (re-sync: `git -C ~/bruquiextension show origin/main:public_app.py > app/public_app.py`, then
  re-apply the block between `>>> one-project patch` / `<<< one-project patch` and the two `# one-project hook`
  lines; `media_gather.py` carries one `# one-project` line: `PUBLIC_ORIGIN` defaults to empty = relative media src).
  The rest is the prod tree snapshot.
- `app/site_static.py`: stdlib static server for `site/` (`SITE_DIR`, default `<repo>/site`; realpath-confined, no
  dotfiles, dir → `index.html`, missing → `404.html`, html `no-cache`, assets `max-age=86400`, GET/HEAD). If
  `SITE_DIR` is missing it logs once and `/` falls back to the legacy UI.
- Local run: `SITE_DIR=site PUBLIC_PORT=18084 python3 app/public_app.py` → http://127.0.0.1:18084/ (no API keys =
  scans fail upstream; the tests fake Google CSE / DeepSeek / Browserbase at the wire).
- Tests: `python3 -m pytest -q app/tests` (needs `pytest Pillow`) and `python3 tools/check.py`; both run in
  `.github/workflows/ci.yml` on every push/PR.
- Image: `deploy/Dockerfile` (python:3.13-slim + Pillow, curl_cffi, playwright package without browsers; `app/` →
  `/app`, `site/` → `/site`). Compose: `deploy/docker-compose.yml` (project `leakscan`, container `leakscan-app`,
  volume `leakscan-data:/data` kept as-is, env `/root/leakscan/.env`, Traefik routers `leakscan` (API host),
  `leakscan-site` (`SITE_HOST`) and `leakscan-site-www` (`SITE_HOST_WWW`, 301 → apex); one router per host so a host
  without DNS only fails its own certificate). Every env var: `deploy/.env.example`.
- Deploy: `deploy/push.sh root@72.62.92.114` (backup → rsync `app/ site/` + deploy files → `docker compose up -d
  --build` with `LEAKSCAN_PORT=8081` → health wait → `deploy/smoke.sh` on the VPS and over https). Idempotent.
  After the first push the old root-level `/root/leakscan/*.py`, `public_static/`, `Dockerfile` and
  `docker-compose.yml` are dead (the image builds from `app/` + `site/`) and can be deleted.
- GitHub Pages (`pages.yml`) keeps deploying `site/` as the fallback during the DNS transition.

### DNS cut-over to abolita.com

1. At the registrar: `A @ → 72.62.92.114`; `CNAME www → abolita.com` (or `A www → 72.62.92.114`).
2. In `/root/leakscan/.env`: `SITE_HOST=abolita.com` and `SITE_HOST_WWW=www.abolita.com`; keep
   `CORS_ORIGINS=https://blackphoenixslo.github.io` while the Pages copy is still in use.
3. Re-run `deploy/push.sh root@72.62.92.114`; Traefik fetches the certificates (`mytlschallenge`).
4. Then follow "Move to a custom domain" below for canonicals/sitemap (steps 2-4; step 1 is this section).

## Inline scan

- Hero form = OnlyFans username (`onlyfans.com/` prefix) + optional Instagram or X (`@` prefix, name `ig`) + "Scan now".
  The network comes only from a pasted URL (`instagram.com/<h>` → instagram, `x.com|twitter.com/<h>` → x); a bare name
  is sent as `instagram`. Body: `{platform: "onlyfans.com", handle, level: "low", instagram? | x?}`. Same two fields on
  `scan/`, which also reads `h=`, `ig=`, `x=` (and old `p=`).
- `js/scan-engine.js` (`window.LeakScanEngine`): the one SSE / fetch transport, API origin rule, error mapping, message
  links and `leakscan.last` writer, used by `js/scan.js` and `js/inline-scan.js`.
- `js/inline-scan.js`: with JS the form never leaves the page. The hero card turns into the live report (progress →
  first 5 links: domain + title, badge Live = `live: true`, Indexed = Google result, else Found; "N links found";
  Open full report `scan/?r=`; Send me the report; demo photo status), the "Free scan report" illustration shows the
  real per-site counts, `LeakScanPersonalize.apply()` does the phones / showcase / demo (`socials` win the IG / X rows),
  URL becomes `?r=<slug>` (reload restores the card). Errors stay inline (busy / bad handle / failed + DM links); a
  new scan resets everything, "Reset page" too. Own elements only, never personalize's `data-p` slots.
- Proof: `tools/scan_e2e.py OUT --only inline`; `tools/check_scan_form.py BASE OUT` (layout, no-JS GET).

## Alias enrichment (quick scan)

- After the first CSE pass, `app/alias_enrich.py` reads up to 4 found leak pages (top domains, one page each, no
  videos / socials; <= 6 s each and in total, 1 MB cap, redirects only within the same site, no private IPs) and pulls
  the creator's other handles: links to onlyfans / fansly / instagram / x|twitter / tiktok `@` / patreon, `@handle`
  in title / h1 / meta description, and the title / h1 person name (`Mira Example` -> `miraexample`, `mira_example`,
  `mira.example`). Kept only when it plausibly is her: normalised containment / edit distance <= 2 to a known handle,
  or the only account of its platform on a page whose title / h1 names her. Site names, generic words
  (`leaked`, `free`, `porn`…), numbers-only and < 4 chars are dropped.
- `public_app` then CSE-scans <= 2 new aliases (<= 8 calls each; <= 4 aliases per scan incl. declared), merges hits by
  URL (`alias` = handle it was found under), whole step <= 12 s (`ALIAS_BUDGET`), skipped with 0 hits or after
  `ALIAS_SKIP_AFTER` s; off with `ALIAS_ENRICH=0`. Log: `alias_enrich pages= cand= kept= new= items= secs= reasons=`.
  Worst case quick scan: 8 (+1 per declared alias) + 1 fallback page + 16 = 25 CSE calls (+1 with `PROFILE_CSE_EXTRA`).
- API (additive): result + `/api/scan-result/<slug>` carry `aliases: {declared, discovered, socials:[{platform,
  handle, url, source_domain}]}`; leak-page socials are appended to `profile.accounts` with `source: "leak_page"`
  (declared first; a declared or scanned platform never gets a discovered handle), so the media step's Instagram uses a
  discovered one only when none was declared; names / aliases go into the profile LLM evidence as `other_names`.
- UI: hero card + `scan/` header "Also found as @a, @b"; personalize fills platforms nothing else knows from
  `aliases.socials`. Tests: `app/tests/test_alias_enrich.py` (synthetic pages `app/tests/fixtures/alias_leak_*.html`).
- Media fix (same PR): the Browserbase session opens google.com once (consent + captcha settle, <= 25 s) before the
  web-text query, and retries a raw=0 web-text query once after the Images step.

## Replace before launch

- **Jaka's photo**: `site/assets/avatar-jaka.svg` is an initials placeholder (used 3x in `site/index.html`). Add a square
  photo, e.g. `site/assets/jaka.webp` (at least 176x176), then
  `sed -i '' 's#assets/avatar-jaka.svg#assets/jaka.webp#g' site/index.html && rm site/assets/avatar-jaka.svg`
  and run the gate.
- **Imprint**: add registration number (matična številka) and tax number (davčna številka) to `site/imprint.html`
  if you want them shown.

## Move to a custom domain

1. `echo leakscan.example > site/CNAME` (your domain), and set it in repo Settings → Pages; point DNS at GitHub Pages.
2. Change `SITE_URL` at the top of `tools/check.py` to `https://leakscan.example/`.
3. Rewrite absolute URLs (canonicals, OG, JSON-LD, sitemap, robots, 404):
   `grep -rl 'https://blackphoenixslo.github.io/leakscan-site/' site tools | xargs sed -i '' 's#https://blackphoenixslo.github.io/leakscan-site/#https://leakscan.example/#g'`
4. `python3 tools/check.py` must stay silent. Internal links are relative, so nothing else changes.
5. VPS host change (`SITE_HOST` in `deploy/.env.example`, e.g. abolita.com): name the new host in `site/privacy.html`
   (hosting item); `tools/check.py` fails until it does.

Note: noindex pages (`showcase/**`, `scan/`, `404.html`) are kept out of search by their own
`<meta name="robots" content="noindex…">`, never by `robots.txt`: a Disallow stops crawlers from reading the noindex, so
the bare URL can still be indexed (robots.txt applies at a domain root, e.g. the VPS host). `tools/check.py` fails on a
Disallow that covers a noindex page.

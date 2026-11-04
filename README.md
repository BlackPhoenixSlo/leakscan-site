# leakscan-site

Google Ads landing site for LeakScan: personal leak-removal service for creators. Static HTML/CSS/JS, no build, no
cookies, no third-party requests on the landing pages. `site/` is what ships. `site/showcase/` is the demo of
the official site each client gets (fictional creator, built from the tessa template); the landing page links and
iframes it as `showcase/`. The demo loads Google Fonts (so the homepage does too, via the iframe); `privacy.html`
discloses that and `tools/check.py` keeps the two in sync. Its own
gates live in `tools/showcase/` (`check_ready.py`, `check_pages.py`, `check_deploy.py`, `_check_accounts.py`).

- Free scan: the hero form (`#scan`, plain GET) sends `p=<platform>&h=<handle>` to `scan/` (`site/scan/index.html` +
  `css/scan.css` + `js/scan.js`, noindex, not in the sitemap). The page POSTs to Jaka's scan API
  (same origin, except on `*.github.io` → `https://scan.srv1395798.hstgr.cloud`; set once at the top of `js/scan.js`
  and `js/personalize.js`, overridden by `<body data-api>`), reads the
  SSE stream (progress → result → done), then renders the report: summary, a Google look-alike (All / Images / Videos,
  Phone / Computer, thumbnails via `/api/thumb`, blurred until Reveal), per-site table, all links (copy / .txt) and the
  prefilled message CTAs. The URL becomes `scan/?r=<slug>`, which reopens the report via `GET /api/scan-result/<slug>`.
  Without JS it links to https://jackbase.me/scan.
- Personalization (`js/personalize.js`): after a scan the landing page and the demo site (`showcase/`) show her data.
  Slug: `?r=` → `localStorage['leakscan.last']` (written by `scan.js`) → none (page unchanged, no API call). One
  `GET /api/scan-result/<slug>` per tab (sessionStorage cache, 8 s timeout, failure = defaults); every value is
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
  `tools/fixtures/scan-sample.json` (magic handles `stub-fail`, `stub-429`, `stub-busy`, `stub-empty`; `--omit-results`
  for break-it runs; `--omit-profile` drops `profile`; `--media normal|relative|none|404`, or per slug
  `POST /__stub/media?slug=&mode=`; preloaded slugs `demoR3port01`, `demoNoProf01` (no profile), `evilR3port01`
  (malicious values); `/api/profile`, `/api/avatar`, `/api/media` routes). It injects `data-api` pointing at itself (other loopback name, so CORS is exercised).
  E2E: `cd ~/leakhunt && uv run python ~/leakscan-site/tools/scan_e2e.py OUT_DIR` (starts its own stub; phone + desktop;
  form → progress → report, tab counts, device toggle, Reveal, CTAs, `?r=` reopen, error paths; never calls prod).
  `--only scan|personalize`; `personalize` covers the flow above (no-slug text identical to main, phones, demo pages,
  media swap / none / 404, scan-only, malicious fixture, localStorage + Reset, public API). Checks named `profile: …`
  need `profile`; `--omit-profile` turns only those red.
- Preview: `python3 -m http.server 8920 --directory site` → http://127.0.0.1:8920/
- Gate: `python3 tools/check.py` (silent + exit 0 when green; prints each problem + exit 1). Runs in CI on every push/PR.
  Covers links/assets resolve, no unreferenced files in `assets/ css/ js/`, canonicals, sitemap, JSON-LD (+ FAQ sync),
  one h1, unique ids, img alt/size, lang, viewport, meta/OG/Twitter, no third-party resources. Full list: docstring.
- Shots: `python3 tools/shots.py OUT_DIR URL...` → phone (390x844 @2x) + desktop (1440x900), light + dark, top + full.
  File names are the URL path relative to the URLs' common directory (`/` -> `index`, `/showcase/` ->
  `showcase-index`), so one run never overwrites itself. Needs Playwright with Chromium; system `python3` works here,
  fallback: `cd ~/leakhunt && uv run python ~/leakscan-site/tools/shots.py OUT_DIR URL...`.
  Evidence goes outside the repo: `~/.leakscan-site/evidence/<branch>/<UTC>-<sha7>/`.
- Raster assets: `python3 tools/make_icons.py` renders `site/assets/og.png` (from `tools/og.html`),
  `apple-touch-icon.png` and `favicon-32.png` (from `site/assets/favicon.svg`).
- Deploy: push to `main` → `.github/workflows/pages.yml` runs the gate and deploys `site/` to GitHub Pages
  (https://blackphoenixslo.github.io/leakscan-site/). `netlify.toml` publishes `site/` if connected to Netlify.
- Improvement loop: `LOOP.md`.

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

Note: `robots.txt` (`Disallow: /showcase/`) only takes effect at a domain root; under the github.io sub-path crawlers
ignore it, so the showcase pages should also carry `<meta name="robots" content="noindex">` themselves.

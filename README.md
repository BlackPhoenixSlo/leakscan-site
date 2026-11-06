# leakscan-site

Google Ads landing site for Abolita: personal leak-removal service for creators. Static HTML/CSS/JS, no build, no
cookies, no third-party requests on the landing pages. `site/` is what ships. `site/showcase/` is the demo of
the official site each client gets (fictional creator, built from the tessa template); the landing page links and
iframes it as `showcase/`. Landing fonts are self-hosted in `site/fonts/` (Bodoni Moda display + Jost body, OFL, Latin subset, 2 preloaded,
metric-matched fallbacks so the swap doesn't shift; Bodoni only for large headings at opsz 24, numbers / prices in
Jost, italic only for the hero's "Me."); the demo uses system fonts (no Google Fonts); `tools/check.py` fails if it loads any
third-party host that `privacy.html` does not disclose. Its own
gates live in `tools/showcase/` (`check_ready.py`, `check_pages.py`, `check_deploy.py`, `_check_accounts.py`).
Card photos ship 720 px `srcset` copies in `showcase/imgs/720/` (`make_images.py --variants` rebuilds them from
the full-size files; `check_pages.py` fails on a stale, missing or over-60 KB copy and any full-size photo > 200 KB).

- Landing page (`site/index.html`), top to bottom, primary path first (scan, evidence, process, price, FAQ, contact):
  header: phones / tablets get a compact "Free scan" button beside the menu ("Scan" under 375px) ·
  `#top` hero (left: scan form with visible field labels, the Fansly / Patreon line (message me: the scan takes an
  OnlyFans username only), one privacy line with "What's stored" in a `<details class="more">` (`privacy.html`'s facts;
  check.py's FAQ match skips `.more`), then the track-record numbers; right: live report card, "Meet Jaka" poster
  `.meet` under it where the player docks) · `#free` one Google phone (All / Images / Videos tabs; after a scan her
  real results, `js/inline-scan.js`) and a "message to me" link, no repeat of the offer · `#why` ·
  `#removals` · `#how` (4 steps in 2 stages once she starts, 2x2 from 1100px, stacked on phones, then the "nobody can promise every
  page" note) · `#pricing` (the one place the free start is spelled out: heading + one line; per plan: price, then
  Covers / Runs / Re-uploads, the one-time plan says weekly re-scans / report / tracking are monthly-only; buttons
  aligned at the foot = plan-specific Telegram messages; one "Both plans" line under them) · `#website`, the add-on in both plans: the three things
  you get, then `#showcase` inside it (demo iframe with a "Full screen" in-page pop-out: Esc / button / backdrop
  close, page behind inert, focus back to the button; one Before / After Google phone at a time, picked by real ARIA
  tabs `.ba-tabs`, `js/main.js`; without JS both show; desktop: demo left, phone right) · `#faq` (desktop: sticky
  head with Telegram / WhatsApp buttons; "Will my own accounts be affected?" open) · `#contact`. `tools/check.py`
  fails if a section id is missing here. One container width for every section on desktop.
  Phones: `#removals` is the page's only swipe row (one per view, the next peeks 14px, arrows + dots, `js/swipe.js`,
  static `.swipe-nav` markup: no shift). The "Free scan" bar shows once the scan form and the report card are both
  off screen, hides over the demo, `#contact`, the footer and any focused control under it; safe-area aware.
  Light theme: header + hero on blush paper, flat surfaces (no gradients, no button glows), cards / fields = 1px line +
  one soft shadow; dark: velvet. Section heads vary: eyebrow only on hero, pricing, website. Phones: "Meet Jaka" video
  full width, caption under it; its poster is CSS (name, "60-second intro · 0:57", play mark; links to `video/`).
  Jaka's portrait everywhere = the CSS `.mono` "J" disc (no photo). Eyebrow rule line only in the hero. FAQ leads with
  privacy, what you need, timing; the Ask-AI line sits under the list. Phone demo frame 300px (cut above its buttons).
- `#removals` "Where I remove from" (`js/removals.js` + `css/removals.css`, own files): four mock panels (Mega, X,
  Reddit, a leak site drawn after fapello.com's profile page: light shell, ring avatar, name + aliases, pills, counters,
  photo grid cropped like a screenshot; removed = same shell + DMCA 404), each a live leak vs. its removed state (the
  removed layer's chrome is cloned from the live one, `data-rm-copy`). Velvet section right after `#why`, head left like every section; 2x2 on desktop, a swipe row (scroll-snap, arrows + dots) on phones. On screen each edge glides by itself (1-2 s CSS
  transition) to a random 55-85 % (the leak side: the button keeps reading Remove) and holds 1-3 s, per card, never in step; paused off screen / tab hidden, none under
  reduced motion; a card's first input (Remove press, stage tap, handle key) stops its sweep for good. Remove / Show again animates the compare edge; idle, the knob sits in the stage's bottom corner with
  no edge line. The edge drags from the knob at once, from elsewhere on the stage only after a sideways move (a tap or a
  vertical swipe leaves it); arrow / PageUp / PageDown / Home / End on the handle. "Reveal images" unblurs the
  `img/removals/` thumbs. Personalized from the same shared scan result as the hero card (`?r=` or last scan, and after
  an in-page scan on the `leakscan:result` event); each panel is all hers or all the demo, never a mix: Mega from the
  result's top-level `mega[]` (always present, `[]` = none; first item's `size` in bytes, `images`, `videos`, `age` ISO
  UTC; its `url` / `title` are an aggregator's and never shown), X poster, Reddit subreddit, the most-seen other host
  (wordmark = the host without its TLD; aggregator hosts left out; a poster / subreddit / host with adult or leak words is skipped), her name (+ the leak-site profile's
  `<handle>, <name>` aliases), `/api/thumb` thumbs (a dead one hides its tile). textContent only; leak URLs are read for host / path, never rendered.
- Video page `site/video/` (noindex, not in the sitemap; `css/video.css` + `js/video-overlays.js`, own files): Jack's
  face video (full frame, Jack on the left half; `jack.webm` = his real one take, 56.9 s, + `jack.mp4` for old iPhones; cues + `transcript.json` from his words by `tools/video/cues_from_take.py`, CUES.md) with his words as word-by-word captions on his left half (`.vo-capt`, CC toggle) and 5
  overlay prefabs drawn on the video's right half, no panel of their own (640x720 box scaled to 960x1080, vertically centred; Google phone, Google
  Images (tap "Images" → grid), X, Reddit, Mega: pop in + word card → his "they get removed" = shake + flash + "GONE." → the
  #removals compare wipe with rolling counters → "Removed" slam + CSS confetti → slide out; reduced motion = fades;
  WebAudio-synthesized pop / whoosh + thud after the play gesture, `?sfx=0` off; Google / Images after = the landing
  after-phone: her `<name>.com` + Instagram + TikTok, her own unblurred photos), driven by `video.currentTime`
  against `data-cue-live / -removed / -out` (+ google-images `-tap`) on each `.vo-pf`. Two modes: named = `?name=`
  (1-40 letters / digits / space . - _) or the shared scan result (`?r=` / last scan, via `LeakScanRemovals.model`
  from `js/removals.js`, the same validators: texts; site / Instagram / TikTok from its profile, as personalize.js; with a scan result the
  cards show her production images: real Google domains / titles / counts, `/api/thumb` thumbs blurred in every card,
  `/api/media/<slug>` own photos in the after states, text only on failure): one take `jack.webm` for both modes
  (the name bar runs the landing's `/api/public-scan`, holding the take before the first card while it runs), never speaks (no AI overvoice: Jack's voice only), "for
  <name>" pill at the start + from `data-cue-say`; generic = "SophieStar", no pill, end card `cta-steps` at `data-cue-cta` (default `-say`):
  a phone replica of the landing, one 10 s take (hero, camera zooms onto the onlyfans.com/ field and types the name
  as a handle → scan card → report card → "Rewatch this video with YOUR content" + name flip; keeps looping after the
  take ends) over a name form. Name bar under the stage (theater / full screen: a pill opens it; pulsing "type your
  name" hint until focus): submit = in-place rebuild at once (named mode, `?name=` via replaceState, no
  interstitial, take restarts from 0 playing), then Change / Reset. `?t=<sec>` seeks. Space = play / pause. Every width: cards inside the 16:9
  stage's right half (phones too, no stacking); full screen button = the stage (Fullscreen API), iPhone = rotated CSS
  theater (Esc / X / back closes); touch: own play bar, tap-to-play + "Rotate for full size" hint. Script (one take):
  `site/video/SCRIPT.md`; cue sheet + SFX + where the webm goes: `site/video/CUES.md`. Gate: `tools/video/check_video.py`
  (CI). Proof: `tools/video/cue_shots.py OUT` (both modes, cue shots, right-half geometry at both widths, full frame: video box = stage box + transparent overlay (`--break-full`), after state,
  counters, end card + form + cta-steps, name bar + in-place swap (`--break-swap`), snap, reduced motion, sfx, no overvoice (`--break-voice`), production images (`prod`, `--break-img`), player: tap / theater / full
  screen, scan-stub texts + thumbs); cues from a take (`.webm` / `.mp4`)
  (whisper / faster-whisper word timestamps → `data-cue-*` diff, untested on a real take):
  `tools/video/cues_from_take.py TAKE` (all via `cd ~/leakhunt && uv run python …`; `tools/video/serve.py` = local
  server with Range, which `<video>` seeking needs).
- Mini player (`js/pip.js` + `css/pip.css`): a 16:9 player of `video/` (CLS 0), on by default (landing and `scan/?r=`);
  `?pip=0` off. Landing: docked (absolute, scrolls with the page) right-aligned just below the hero card, exactly over the
  `.meet-pic` poster (at rest a "Meet Jaka" caption bar; the controls on hover / focus, or for 4 s after a tap) (example report,
  or the scan report card after a scan) at 55% of its width, never over a link / button / pill (else over the card's
  bottom-right, never > 25% of it); once the hero scrolls out it floats bottom-right, and re-docks on scroll back unless the
  user dragged, resized, tucked or closed it. Created after load + first scroll / pointer / key or idle; same-origin
  iframe of `video/?r=&name=` made embed-only from the host (injected style; `<video>` driven directly: muted start, tap =
  unmute, then play / pause); icon-only 30 px bar under the picture. Drag drops it where released (kept on-screen, under
  the sticky header / report nav); a fling / drag past the left or right edge tucks it (paused) with a `>` / `<` tab
  (tap / drag inward = back; Esc tucks, Enter on the tab returns); corner grip / pinch resizes (min 160 px, max 60% of
  the width, 90% on phones); expand = `video/?r=&t=`; x closes for the session; spot / size / tucked / closed in
  sessionStorage `leakscan.pip`. E2E: `scan_e2e.py OUT --only pip` (phone, desktop, WebKit iPhone 13; `--break-tuck`,
  `--break-dock`).
- Free scan: the hero form (`#scan`) scans in place with JS (see "Inline scan" below); without JS it GETs
  `h=<onlyfans>&ig=<instagram or x>` to `scan/` (`site/scan/index.html` +
  `css/scan.css` + `js/scan.js`, noindex, not in the sitemap). The page POSTs to Jaka's scan API
  (same origin, except on `*.github.io` → `https://scan.srv1395798.hstgr.cloud`; set once in `js/scan-engine.js`
  (`E.API`), overridden by `<body data-api>`), reads the
  SSE stream (progress → result → done), then renders the report: summary, a sticky section nav (Google / Sites N /
  Send report), a Google look-alike (All / Images / Videos, Phone / Computer, thumbnails via `/api/thumb`, blurred until
  Reveal; the Phone frame, ~80% of the screen tall, is pinned while page scroll scrolls its screen 1:1, then the page
  moves on; All's first look is fitted to <= 1.5 screens of that scrolling, More adds the rest; its Images block is one
  swipe strip of every image, video results' stills included with a play badge (snap, edge peek, arrow keys; desktop: arrows on hover); the Images tab (3 columns) starts
  with 4 rows (12; desktop 3 rows of 8), "Show more images" +24; the Videos tab with 5 (desktop 8), "Show more videos" +12;
  "Show fewer" back to the first look; on the phone the More button fades / slides in as it enters the screen and the
  next scroll carries on to the page below; a dead thumb's slot goes to the next image, else to the last tile when it is
  off screen, else it stays an empty tile: nothing on screen moves (`E.gallery`); screens
  < 600 px tall get a static frame, no inner scroll box), "Where the copies are" (every site, most links first: 10 sites, +25 per click; a
  site's links built only when opened, 10 then +50, removed again on close; one filter over domains + URLs; Copy all /
  .txt always carry every link) and the prefilled message CTAs. Built incrementally so 1,000 links on 100 sites stay
  ~580 elements; `performance.measure('leakscan:report')` = result event → first frame of the report. The URL becomes
  `scan/?r=<slug>`, which reopens the report via `GET /api/scan-result/<slug>`;
  the report link in the messages is `scan/?r=<slug>` on the host serving the page (resolved from `js/scan-engine.js`'s URL).
  Without JS it links to https://jackbase.me/scan.
- Personalization (`js/personalize.js`): after a scan the landing page and the demo site (`showcase/`) show her data.
  Slug: `?r=` → `localStorage['leakscan.last']` (written by `scan-engine.js`) → none (page unchanged, no API call):
  `E.currentSlug()`, the one lookup for every script. One
  `GET /api/scan-result/<slug>` per tab (sessionStorage cache, 8 s timeout, failure = defaults; on the landing the hero
  card's request from `js/scan-engine.js` is shared, and a `?r=` link opened with the card below the fold scrolls it up); every value is
  validated and rendered with textContent / built elements, never leak titles or snippets. Landing: hero line +
  Reset, the phone sticky bar ("Free scan: type your handle" → "DM me on Telegram", `t.me/jakabasej` prefilled like
  #contact's with her report link + @handle), both "Your website" phones (name, top-4 leak domains by occurrences, blurred `/api/thumb` thumbs, IG / TikTok /
  site rows hidden when unknown), hero card handles, showcase url bar + iframe `showcase/?r=` (until the iframe has
  loaded a page with `?r=`, a load without it, the lazy iframe's own first load of `showcase/` landing after the src
  change: Chrome's race, is sent on to its `?r=` src; after that first `?r=` load nothing in it is redirected). Slots are `data-p="…"`.
  Demo: once its scan result is in, its internal links keep `?r=` (scan-only too, so clicking around stays on her scan); the content changes
  only with `profile` (else Orla stays): name / bio / facts / links from `data-p-tpl` templates, everything not
  marked is hidden (no pottery next to her name), avatar via `/api/avatar/<slug>` when `profile.avatar`. Blog: Orla's posts (`blog/post-*.html`, in the ItemList + `feed.xml`) are hidden then and three
  first-person starter posts show instead (`blog/own-1..3.html`, cards `data-p-show hidden` in `blog.html`; not in the
  ItemList / feed: demo content): why this site, a normal week, real vs fake accounts. Any creator; swaps = name /
  first name, profession, location, follower count (`profile.followers`, 2 significant figures, < 100 = dropped),
  IG / TikTok handles, site; each optional swap drops its clause when unknown. Body stays ads-safe (no paid-platform
  names, nothing explicit); at setup the owner adds her photos and changes a few words. Photos arrive later: `GET /api/media/<slug>` polled every 3 s for ≤ 90 s (stops on ready / none / 2nd 404),
  swapped in with fade, fixed boxes; only `<API>/api/media/…` or same-origin `/api/media/…` srcs. The scan report card
  links to `../?r=<slug>#website` + `../showcase/?r=<slug>` and shows "Gathering photos…" → "Photos ready".
  An in-page scan re-personalizes in place (idempotent) through the `leakscan:result` event that `scan-engine.js`
  dispatches on `document` with the result (`js/removals.js` listens too); the only export is
  `window.LeakScanPersonalize = {pollMedia(slug, cb)}` (the report card's / hero card's photo status).
  Privacy: the slug lives only in this browser (localStorage, plus the cached result in sessionStorage); "Reset page"
  clears it. Nothing is sent anywhere except the API reads above.
- Scan stub: `python3 tools/scan_stub.py [--port 8930]` serves `site/` plus the API routes from the synthetic fixture
  `tools/fixtures/scan-sample.json` (magic handles `stub-fail`, `stub-429`, `stub-busy`, `stub-empty`, `stub-mixed` (live true / false / missing),
  `stub-huge` (1,000 links on 100 sites, deterministic; preloaded as `demoHuge0001`);
  echoes `instagram` / `x` as `socials`; `--omit-results`
  for break-it runs; `--omit-profile` drops `profile`; `--media normal|relative|scanhost|none|404`, or per slug
  `POST /__stub/media?slug=&mode=`; preloaded slugs `demoR3port01`, `demoNoProf01` (no profile), `evilR3port01`
  (malicious values), `demoBrokenT1` (404 / blank thumbs), `demoDeadTail1` (24 live thumbs, then dead ones),
  `demoRemove1` (x / reddit / mega hits + stale aggregator pack rows), `demoPackImg1` (a Google result on a pack's
  host with a thumb, stored before the aggregator rule; served through the API's own `off_row`); `mega[]` has the backend's exact shape; `/api/profile`, `/api/avatar`, `/api/media` routes). It injects `data-api` pointing at itself (other loopback name, so CORS is exercised).
  E2E: `cd ~/leakhunt && uv run python ~/leakscan-site/tools/scan_e2e.py OUT_DIR` (starts its own stub; phone + desktop;
  form → progress → report, tab counts, device toggle, Reveal, CTAs, `?r=` reopen, error paths; `stub-huge` at CPU x4:
  render < 1.5 s, DOM budget, show more / open / filter / export, pinned phone → sites scroll (frame >= 78% of the screen; All <= 1.5 screens, Images first 12 (+24), Videos first 5 (desktop 8, +12), Show fewer back, wheel / touch past the screen's end moves the page, More rises in; All's image strip: every image, one row, scrollWidth > clientWidth, snap, touch swipe, keys, desktop arrows), short screens, section nav (no history entries),
  keyboard focus, CLS 0 over the whole flow,
  no sideways scroll at 320 / 360 px, no 5xx / console errors; never calls prod).
  The entry is thin: the scenarios live in `tools/scan_e2e/` (one module each, shared helpers + the one break-it
  registry in `common.py`). `--only scan|personalize|askai|inline|tabs|removals` (`tabs`: phone tabs + demo pop-out;
  `removals`: the panels, toggle, drag, keys, `mega[]` / hit personalization, no aggregator host / share url anywhere
  in the DOM, a pack-host result's thumb in no view and no count). An exception in a scenario part is a FAIL line for
  it and the run goes on. Break-it flags (each turns only its own checks red): `--break-allowlist`, `--break-drift`,
  `--break-phones`, `--break-thumbs`, `--break-people` (logo tiles kept), `--break-remove`, `--break-incremental` (every explorer step 1e9: only
  `incremental:` checks), `--break-sweep` (removals' ambient sweep never steps: only `sweep:`), `--break-tgcta` (no
  Telegram sticky bar after a scan: only `tgcta:`), `--break-fprow` (leak-site profile head stacked again: only `fp:
  first tile row`). `personalize` covers the flow above (no-slug text identical to the page without personalize.js / inline-scan.js, phones, demo pages,
  blog: Orla's posts without a profile, starter cards + post pages with one,
  media swap / none / 404, scan-only, malicious fixture, localStorage + Reset, public API). Checks named `profile: …`
  need `profile`; `--omit-profile` turns only those red.
- Ask-AI popup: `js/chat.js` + `css/chat.css`, markup at the end of `index.html` (launcher + `<dialog id="askai">`; also
  opened by any `[data-askai-open]` link; the launcher stays hidden while the hero is on screen). Chips and typed questions that fuzzy-match an FAQ question (or "what does it
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
  `public_static/`). `public_app.py`, `cse_scanner.py`, `profile_extract.py`, `media_gather.py`, `db.py`,
  `chat_proxy.py` and part of `app/tests/` come from `bruquiextension` (base `bb294d0`). Every local change to those
  six files is the file's block between `>>> one-project patch` / `<<< one-project patch` (none in `cse_scanner.py`)
  or a line ending in `# one-project: <site>`; `app/tests/test_one_project.py` lists the sites, goes red when one is
  missing, and (with `~/bruquiextension` checked out, read only) when a line differs from `bb294d0` outside both.
  The aggregator rule (`host`, `off_aggregators`) lives in this repo's own `app/leakshaven.py`.
  Re-sync = re-apply the block + every `# one-project` line; a 3-way merge does it, per file F of the six:
  `git -C ~/bruquiextension show bb294d0:F > /tmp/base; git -C ~/bruquiextension show origin/main:F > /tmp/new;
  git merge-file app/F /tmp/base /tmp/new`, resolve conflicts, run the tests, bump the base sha here.
  The rest is the prod tree snapshot.
- `app/site_static.py`: stdlib static server for `site/` (`SITE_DIR`, default `<repo>/site`; realpath-confined, no
  dotfiles, dir → `index.html`, missing → `404.html`, html / js / css `no-cache` + Last-Modified → 304 (a deploy reaches returning visitors at once), other assets `max-age=86400`, GET/HEAD, single
  `Range` → 206 for `<video>`). If
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

- Hero form = OnlyFans username (`onlyfans.com/` prefix) + optional Instagram or X (`@` prefix, name `ig`) + "Find my leaks".
  The network comes only from a pasted URL (`instagram.com/<h>` → instagram, `x.com|twitter.com/<h>` → x); a bare name
  is sent as `instagram`. Body: `{platform: "onlyfans.com", handle, level: "low", instagram? | x?}`. Same two fields on
  `scan/`, which also reads `h=`, `ig=`, `x=` (and old `p=`).
- `js/scan-engine.js` (`window.LeakScanEngine`, loaded first on every page that uses it): the one SSE / fetch
  transport, API origin rule, error mapping, message links and `leakscan.last` writer; the shared validators
  (`E.clean`), `E.currentSlug()`, the report model, the image gallery, `E.watchThumb` (one broken-thumb rule: 404 /
  < 16 px = dead, the tile goes; image tiles also when `E.isPhoto` says no person photo: a thumb drawn at 48x48 with
  little soft texture or almost no skin, a site logo / banner / icon, pixels read via a CORS load of `/api/thumb`;
  refused → once more on `E.fresh`'s URL (`?c=1&u=`: a copy cached before the API sent ACAO / Vary would refuse
  forever), then plain (unreadable = kept); thresholds + measured confusion: comment there; a video still on the scan page's Videos
  tab / the #free Videos rows that fails that check falls back to its grey box, the row stays; a landing Links / Sites
  row icon shows its thumb only once it passed, else another photo of the same site that passed, else the neutral
  letter, never another site's photo; `E.photo(src, fn)` = that one verdict for row icons / video stills, `E.put(img,
  src)` = the exact URL + mode the passing load used: its cached copy, one request per image, a plain reload would be a
  2nd cache entry: ~2x requests, past the `/api/thumb` burst → 429, photos dropped), `E.tablist` (tabs: click, ←/→, Home / End, `hidden` panels), the one `[data-reveal]`
  handler (blur via `--leak-blur`), the `leakscan:result` event. Used by every script below and `js/scan.js`.
  `js/strip-drift.js` (the hero strip's idle drift) and `js/free-phone.js` (the #free phone) are split out of
  `js/inline-scan.js`.
- `js/inline-scan.js`: with JS the form never leaves the page. The hero card turns into the live report (progress →
  first 5 links: domain + title, badge Live = `live: true`, Indexed = Google result, else Found; "N links found";
  Open full report `scan/?r=`; Send me the report; demo photo status; its image strip / Images tab / #free phone list the
  real images first, then video results' stills, no badge; the #free grid skips stills its Videos tab shows), the #free phone shows her Google results
  (`js/free-phone.js`), the `leakscan:result` event has personalize do the phones / showcase / demo (`socials` win the IG / X rows),
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

- **Jaka's photo** (optional): the page uses a CSS "J" monogram (`.mono`) and a CSS video poster; to use a real
  portrait, add a clothed, camera-facing square photo and swap the `.mono` spans for `<img>`, then run the gate.
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

Note: noindex pages (`showcase/**`, `scan/`, `video/`, `404.html`) are kept out of search by their own
`<meta name="robots" content="noindex…">`, never by `robots.txt`: a Disallow stops crawlers from reading the noindex, so
the bare URL can still be indexed (robots.txt applies at a domain root, e.g. the VPS host). `tools/check.py` fails on a
Disallow that covers a noindex page.

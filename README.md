# leakscan-site

Google Ads landing site for Abolita: personal leak-removal service for creators. Static HTML/CSS/JS, no build, no
cookies or third-party requests on the landing pages except `js/analytics.js` (Google Ads, see below). `site/` is what ships. `site/showcase/` is the demo of
the official site each client gets (fictional creator, built from the tessa template); the landing page links and
iframes it as `showcase/`. Landing fonts are self-hosted in `site/fonts/` (Young Serif display + Schibsted Grotesk body,
OFL, Latin subset, both preloaded, metric-matched fallbacks so the swap doesn't shift); the demo uses system fonts (no
Google Fonts); `tools/check.py` fails if it loads any
third-party host that `privacy.html` does not disclose. Its own
gates live in `tools/showcase/` (`check_ready.py`, `check_pages.py`, `check_deploy.py`, `_check_accounts.py`).
Card photos ship 720 px `srcset` copies in `showcase/imgs/720/` (`make_images.py --variants` rebuilds them from
the full-size files; `check_pages.py` fails on a stale, missing or over-60 KB copy and any full-size photo > 200 KB).

- Landing page (`site/index.html`), top to bottom: `#top` hero (scan form, live report card; the mini player docks
  by `.hero .report-card`) · `#why` (Jaka's letter with his photo `assets/jaka.webp`, three rules, the record) · `#how`
  (You 1-3, Me 4-5) · `#website` (its two points, then `#showcase` inside it: a demo preview card, live iframe 440px tall
  (`data-src` until the page has loaded and it is within 800px of the screen: `js/main.js`; Chrome's own lazy distance started it
  during load and held the video player)
  with a "Full screen" in-page pop-out: Esc / button / backdrop close, page behind inert, focus back to the button;
  under 560px a still of the demo's top, `assets/demo/top.webp`, opens the same pop-out; then `#free`, the page's one
  Google phone block `.ba`: Before / After one at a time via real ARIA tabs `.ba-tabs`, `js/main.js`; Before = the
  scan's phone `.phone-free` (All / Images / Videos tabs, lists scroll inside the screen + Show more; after a scan her
  real results, `js/inline-scan.js` + `js/free-phone.js`, "Send it to me" link), After = her own pages first (search "<name> nude leaks", each tab scrolling inside the
  screen with "Show more" for its next `.m-batch`, `js/main.js`); no JS = both) · `#pricing` (Monthly on the deep card, One-time outlined, plan-specific Telegram CTAs) · `#faq` · `#removals`
  (the deep room; phones: one column, desktop: 2x2) · `#contact`. `tools/check.py` fails if a section
  id is missing here.
- Look: every colour / radius / face is a token in `css/styles.css` `:root` (paper `--bg`, the `--fold` band under
  `#how` and `#pricing`, the `--deep` mulberry room for `#removals` and the Monthly card, `--accent` mulberry; dark via
  `prefers-color-scheme`). Young Serif for h1 / h2 / big numbers (weight 400, no synthesis), Schibsted Grotesk for the
  rest; one section rhythm (36 / 60 / 80 px), one h2 scale, 6px buttons, no shadows except what floats (hero card, sticky pill).
- `#removals` "Where I remove from" (`js/removals.js` + `css/removals.css`, own files): four mock panels (Mega, X,
  Reddit, a leak site drawn after fapello.com's profile page: light shell, ring avatar, name + aliases, pills, counters,
  photo grid cropped like a screenshot; removed = same shell + DMCA 404), each a live leak vs. its removed state (the
  removed layer's chrome is cloned from the live one, `data-rm-copy`, same geometry). Each edge starts mid-stage (50 % ± 8 px, per card); on
  screen it glides by itself (1-2 s CSS transition) to a random 42-58 % and holds 1-3 s, per card, never in step; paused off screen / tab hidden, none under
  reduced motion; a card's first input (Preview removal press, stage tap, handle key) stops its sweep for good. Preview removal / Show again animates the edge to all removed / all live; all live, the knob sits in the stage's bottom corner with
  no edge line. The edge drags from the knob at once, from elsewhere on the stage only after a sideways move (a tap or a
  vertical swipe leaves it); arrow / PageUp / PageDown / Home / End on the handle. "Show demo images" (`data-reveal-t` labels) unblurs the
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
- Search landing pages (indexed, in the sitemap; plain static HTML + `css/guides.css`, no JS of their own, edit the HTML directly): hubs
  `faq/`, `removals/` and `compare/`, and their child pages. Each ends in the same free-scan + DM CTA. Legal and process claims link the
  primary source they were checked against; facts about Abolita come only from `index.html`. Comparisons are dated: re-check them against
  the other service's own pages before changing them. Linked from the homepage footer.
- Mini player (`js/pip.js` + `css/pip.css`): a 16:9 player of `video/` (CLS 0), on by default (landing and `scan/?r=`); a phone's
  mini plays `jack-360.*` (`video/?mini=1`), expanding adds a muted 720p layer over it at the same second (no request before the tap; the mini stays the clock, the
  sound and the overlays' master, and shows through whenever the 720p stalls; minimizing drops the layer and its download); a computer's mini and `/video/` directly stay 720p;
  `?pip=0` off. Landing: docked (absolute, scrolls with the page) over the bottom-right of the hero card (Weekly report,
  or the scan report card after a scan) at 55% of its width, never > 25% of the card, never over a link / button / pill
  (else just below the card); once the hero scrolls out it floats bottom-right, and re-docks on scroll back unless the
  user dragged, resized, tucked or closed it. Created after load + first scroll / pointer / key or idle; same-origin
  iframe of `video/?r=&name=` made embed-only from the host (injected style; `<video>` driven directly: muted start, tap =
  unmute, then play / pause); icon-only 30 px bar under the picture. Drag drops it where released (kept on-screen, under
  the sticky header / report nav); a fling / drag past the left or right edge tucks it (paused) with a `>` / `<` tab
  (tap / drag inward = back; Esc tucks, Enter on the tab returns); corner grip / pinch resizes (min 160 px, max 60% of
  the width, 90% on phones); expand = `video/?r=&t=`; x hides it behind a tab (tap = back); nothing stored: every
  page load (reload, new page) starts on the home spot at default size. A phone's first paint already has Jack's still on the player's spot (`.pip-still`, an
  inline script + data URI after `<body>` in `index.html` and `scan/index.html`, keep the two the same; `pip.js` replaces
  it when it mounts; not on a computer, where the dock spot needs the card). E2E: `scan_e2e.py OUT --only pip` (phone,
  desktop, WebKit iPhone 13; `--break-tuck`, `--break-dock`, `--break-still`).
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
  #contact's with her report link + @handle), the After phone (search "<name> nude leaks", her own pages, the Removed rows = her top-4 leak domains by occurrences, IG / TikTok /
  site rows hidden when unknown; the Before phone is the scan's own, `js/free-phone.js`), hero card handles, showcase url bar + iframe `showcase/?r=` (its `data-src` until `js/main.js` starts it; until the iframe has
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
  opened by any `[data-askai-open]` link; on phones (<720px) the launcher stays hidden while the hero is on screen). Chips and typed questions that fuzzy-match an FAQ question (or "what does it
  cost") are answered instantly from the page's own FAQ / pricing text, no network. Everything else streams from
  `POST <API>/api/chat` (`{kb:"landing", messages (last 8), slug?}` → SSE `token`/`done`/`failed`; API origin =
  `<body data-api>`, else the scan server on github.io, else same origin; from file:// or on any error → contacts). Answers are built as DOM nodes;
  links are live only for existing `#ids` and `https://` t.me, wa.me, blackphoenixslo.github.io, abolita.com, jackbase.me,
  the scan server, plus `mailto:me@jackbase.dev`. Chat lives in sessionStorage only. Stub: `/api/chat` with magic words
  `stub-fail` / `stub-429`. E2E: `scan_e2e.py OUT_DIR --only askai` (`--break-allowlist` for the break-it run).
- Google Ads + consent banner: `js/analytics.js` only (one `defer` script per page, `data-cookie-settings` = reopen link,
  shipped `hidden`; `showcase/` and `404.html` have neither: a client's demo, and no relative paths). Paste `ADS_ID`, `LABEL_SCAN`, `LABEL_CONTACT` at
  its top; while `ADS_ID` is empty it does nothing, in a frame too. gtag.js directly, no GTM; Consent Mode v2, denied by default everywhere
  (US auto-grant: the marked commented line, off). Scan conversion = the `leakscan:result` event, contact = delegated click on
  Jaka's t.me / wa.me / mailto links, once per page load. gtag.js copies `document.title` into conversion hits whatever `page_title` says
  (measured), so no page that loads it may put a handle or name in its title. Proof (sub-path, real gtag.js, beacons recorded + aborted):
  `tools/analytics_e2e.py OUT` (`--break-order`).
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
- Raster assets: `python3 tools/make_icons.py` renders `site/assets/og-jack.jpg` (from `tools/og.html`),
  `apple-touch-icon.png` and `favicon-32.png` (from `site/assets/favicon.svg`).
- Deploy: VPS = `deploy/push.sh` (see "One project, one origin" below). Push to `main` →
  `.github/workflows/pages.yml` runs the gate and deploys `site/` to GitHub Pages
  (https://blackphoenixslo.github.io/leakscan-site/), the fallback during the DNS transition. `netlify.toml` publishes `site/` if connected to Netlify.
- Improvement loop: `LOOP.md`.

## E2E result reuse

`tools/scan_e2e.py` doesn't rerun a scenario whose inputs are unchanged since a green run, in any worktree:

```
cd ~/leakhunt
uv run python <worktree>/tools/scan_e2e.py OUT                      # every scenario, reusing what it can
uv run python <worktree>/tools/scan_e2e.py OUT --only pip --only askai
uv run python <worktree>/tools/scan_e2e.py OUT --changed [REF]      # only what the diff reaches; REF default: merge-base with origin/main
uv run python <worktree>/tools/scan_e2e.py OUT --no-reuse           # run anyway; a green run still fills
```

- A hit prints `<scenario>: reused green from <run folder>`, starts no stub and no browser, and takes no machine slot. Misses
  wait for the machine gate on their own (`~/.slop/gate.py`, re-exec at nice 10); invoking through the gate as before still works.
  Unselected: `skip <scenario>: diff doesn't reach it`. Selected scenarios still go through reuse.
- **Before a deploy: a full `--no-reuse` run.** CI runs only `check.py`, `check_video.py` and `app/tests`, so nothing else
  catches a stale hit.
- Key (`tools/scan_e2e/reuse.py`) = env (Playwright's `browsers.json`, its version, Python major.minor, platform) + code (entry,
  `common` / `main` / `reuse` / `reach`, the scenario's modules + their imports, the stub, `tools/fixtures/**`; Python by its ast: no
  comments, no module docstring, no `BREAKS` in `common.py`) + reach: `{path: sha or null}` of everything the scenario read,
  measured by an audit hook in the stub and the harness (`tools/scan_e2e/reach.py`), 404s and listed dirs included. No hand-kept
  map: with every recorded file unchanged a deterministic scenario reads the same things.
- Never reused or filled: a red run (it also evicts the green it would have hit), a `--break-*` / `--omit-*` run (these never read
  the cache either), a run during which a reached file changed, an entry whose run folder is gone or now says something else.
- Cache: `~/.leakscan-site/e2e-reuse/` (`E2E_REUSE_DIR` overrides): `<scenario>/<code_key>/<reach_key>.json`, `map/<scenario>.json` =
  union of the paths over all complete runs on any branch, red ones too (`--changed` reads it; no map = selected). Safe to delete.
- `NOT_CACHEABLE` in `reuse.py` is empty, audited: no check moves with the calendar and no request leaves loopback. Timing
  budgets are load-sensitive, not calendar-sensitive, so they stay cacheable: a green under load stays green.
- Limits: a new file shadowing an imported module is not seen (the import system's own listdir isn't recorded). A hit needs the same
  env: `uv run` from `~/leakhunt` and the system `python3` have different Playwrights, so they don't share entries. A file the
  scenario only sometimes loads (a lazy image) is a dep only of the runs that loaded it.
- What to expect (measured 2026-11-06): the saving is same-content reruns (another worktree, a retry, a docs or test-only commit), not
  typical edits. `index.html` loads all landing JS and the player mounts everywhere, so every `site/js/*.js` reaches 6 or 7 of the 7
  scenarios, and every `app/*.py` the stub imports reaches all 7. Narrow: `site/showcase/` sub-pages (`personalize` only). Skips one:
  `index.html`, `main.js`, `chat.js`, `inline-scan.js` (`scan`), `scan.js`, `scan.css` (`askai`). A red scenario reruns every time.
- Proof: `tools/scan_e2e/reuse_proof.py EVIDENCE_DIR [--only s ...] [--break-key]` (temp worktrees + temp cache, the real CLI).

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

- Hero form = OnlyFans username (`onlyfans.com/` prefix) + optional Instagram or X (`@` prefix, name `ig`) + "Scan now".
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
  real images first, then video results' stills, no badge), the #free phone shows her Google results (`js/free-phone.js`:
  search "<handle> nude leaks"; each tab scrolls inside the fixed screen, "Show more" adds the next batch), the `leakscan:result` event has personalize do the phones / showcase / demo (`socials` win the IG / X rows),
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

## Scan reuse (quick scan)

- A quick scan with the same platform, handle, aliases and socials as a recent one makes no external call: it gets its
  own row + slug (`extra.reused_from` = source slug) and that scan's result, avatar and photos. Any visitor's scan can be
  the source. `SCAN_REUSE_TTL` s (21600; 0 = off), measured from the fresh scan: reused rows carry no key, so it can't roll
  forward. `{"fresh": true}` in `POST /api/public-scan` skips it (no UI); its result is a new source.
- Only whole results are sources (`extra.scan_key`): status complete, no failed CSE call, alias step not skipped, leakshaven
  answered live, profile from the LLM. Log: `scan reuse hit level=low platform= aliases= hits= age=Ns media=`, and no
  `scan start` / `scan done` line for a hit. Tests: `app/tests/test_scan_reuse.py`.

## Replace before launch

- **Jaka's photo**: `site/assets/jaka.webp` (192x192, a frame of his own take) is used in the hero card, #why and
  scan/. Swap it for a portrait shot if wanted (same name, square, at least 176x176).
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

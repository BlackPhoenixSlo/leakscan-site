#!/usr/bin/env python3
"""End-to-end proof of the on-site free scan against the local stub (never the production API or jackbase.me).

    cd ~/leakhunt && uv run python ~/leakscan-site/tools/scan_e2e.py OUT_DIR [--only scan|personalize|askai|inline|tabs|removals|pip|sheet]
        [--omit-results] [--omit-profile] [--break-allowlist] [--break-drift] [--break-phones] [--break-thumbs] [--break-people] [--break-remove]
        [--break-incremental] [--break-sweep] [--break-tgcta] [--break-fprow] [--break-tuck]
        [--break-dock] [--break-pull] [--break-pipvis] [--break-pipfollow] [--break-pipload] [--break-sheet500]

Starts tools/scan_stub.py on a free port (--omit-results / --omit-profile are passed through: break-it runs), then
for phone (390x844) and desktop (1440x900) runs the scenarios below. Expected values come from what the stub serves
(GET /api/scan-result/<slug>) or the fixture's profile, never from a client rule re-derived here.

scan: home → fill the hero form → submit → scan/?p=&h= → progress → report. Asserts summary numbers
equal the fixture, tab item counts (All 10 → all pages after "More results"; Images every served image, video stills
with a play badge; Videos 4 phone / 8 desktop first, More reaches every video), device toggle swaps
frames, Reveal unblurs, CTA hrefs carry the report link + handle, every hit URL is listed, `?r=<slug>` reopens without
a new scan, and the stub `failed` / 429 / busy / empty / not-found paths show their UI. Then `stub-huge` (1000 links on
100 sites, CPU x4, scan_e2e/huge.py): render time, DOM budget, the All tab's Images strip (one row of every image,
swipe / keys / desktop arrows, snap), sites / links shown in steps, filter, export, the pinned
phone scrolling into the sites, CLS 0 (whole flow), no 5xx / console errors; --break-incremental (scan.js with every
step 1e9) turns only the `incremental:` checks red. Every non-loopback request is
aborted and must not happen at all. Screenshots of each state go to OUT_DIR. One PASS/FAIL line per check; exit 1 on
any FAIL.

personalize (js/personalize.js): landing without a slug has byte-identical visible text to the same page without personalize.js and calls no
API; `?r=<slug>` fills both "Your website" phones (name, top leak domains by occurrences, blurred stub thumbs, IG /
TikTok / site rows), the showcase url bar and iframe src; the demo iframe reaches its ?r= page (waited for, ≤ 25 s; scrolls are
instant here: Playwright's own follow the site's smooth scroll-behavior without waiting) and every showcase page shows the profile
and no pottery / Orla / she-her text; demo photos poll /api/media (pending → ready swap, no layout jump; none / 404
keep the placeholders; same-origin relative srcs are accepted and stop polling); scan-only results personalize the phones but leave the demo as Orla
(blog.html too: Orla's 3 posts; with a profile the 3 starter posts blog/own-*.html, cards + pages); the demo's links keep
?r= (scan-only too), a page opened inside it stays (About with ?r=, links.html without: no bounce), and a stale load of
showcase/ without ?r= before its first ?r= load (Chrome's lazy-iframe race, forced: the ?r= request held) is sent on;
the malicious fixture never reaches the DOM; scan → report card → landing → localStorage → Reset; the public
leakscan:result event re-personalizes in place and idempotently (the only export is pollMedia). Checks that need the
profile are named "profile: …" (the --omit-profile break run must turn only those red). Non-loopback requests are
aborted and none may be attempted (the demo uses system fonts).

sheet (app/thumb_sheet.py, E.sheet in js/scan-engine.js; phone, desktop, WebKit iPhone 13): the same report with /api/thumb-sheet off (404, an API
without it: every other scenario runs so) and on: the landing (hero, #free phone, the phones, removals panels, the video's kept / dropped photos; end card
count = the report's) and scan/?r= (Images, Videos) show exactly the same, DEAD / BLANK / LOGO dropped alike (E.isPhoto on the same bytes); server's log: one sheet for
page + iframe, no /api/thumb (a thumb the sheet does not name, and only that, goes there); tiles are <img>s on blob URLs; blur, Reveal; a tile paints before the sheet's body ends; a sheet cut halfway: same landing, only the rest asks /api/thumb.
--break-sheet500: the stub answers 500: the views stay the same, only the request-count, blob and read-as-it-arrives checks go red.

askai (js/chat.js, the "Ask AI before you DM me" popup): launcher covers no hero text at load (phone: hidden while
the hero is on screen), visible and clear of the hero CTA (desktop) / sticky bar (phone),
open/close/Esc/backdrop/focus return/focus trap, FAQ chips and fuzzy-typed questions answered with zero network
requests, other questions streamed from the stub's /api/chat (request body: kb, slug, history cap), link rules (anchor
scrolls, allowlisted hosts only), failed / 429 / no-API (file://) fallbacks, retry, sessionStorage restore, reduced
motion, JS off. No request leaves loopback, the lazy showcase iframe included (system fonts: no Google Fonts). --break-allowlist serves chat.js with its host allowlist disabled: only `links:` checks may go red.

inline (js/inline-scan.js): the hero form scans in place; the card becomes the report: Links / Images / Sites tabs
(counts from the fixture, switching never resizes the card), whole-row links, a film strip of what Google Images shows
(blurred, ↗, links to its result or the full report) that drifts by itself after ~4 s idle, stops for good on a
pointerdown and never moves under prefers-reduced-motion (no layout shift: card box + PerformanceObserver), the #free
phone's Images tab with her tiles; errors, reload, reset; a shared ?r= link makes one /api/scan-result
request and (phone) scrolls the card under the nav, not with #website. --break-drift serves strip-drift.js with the
drift speed 0: only `drift:` checks may go red. --break-phones serves personalize.js without the phone links: only
`phones:` checks may go red.

tabs (the owner's three asks): (1) report card ?r=demoBrokenT1 (stub: three page-result thumbs answer 404 / a 1×1
blank, two are a flat site logo, a video still leads images[]): failed / blank / logo tiles leave the strip, the Images grid and the #free phone, the
next image takes the slot, the label / tab / "+N more" / phone counts say what shows (clean count minus the dead
thumbs seen on the wire); ?r=demoDeadTail1 (24 live thumbs, then 8 dead ones past the strip): sampled from load, no
count ever says more than 24 and all settle at 24; every tile is painted, video stills only after the real images, result tiles first (judged on the page, never a
re-derived list); the scan page's grid refills its slots; the scan page with > 80 results, a mostly-video report and
thumbs failing late on the strip: every thumb in strip + Images tab, nothing on screen moves (E.gallery `still`); (2) #website copy → demo iframe → Before / After phones (in #showcase), their All / Images / Videos tabs switch
on click and keys without moving anything, the demo pops out to a full-screen layer (Esc / button / backdrop close,
focus back, page scroll locked, nothing behind it moves, "Open the demo site" link kept); (3) the #free phone: same
tabs, the illustration without a scan, her "<handle> nude leaks" search / rows / tiles / videos + Reveal with ?r=, each tab
scrolling inside the phone (no trap at its end) with "Show more" batches up to every item; (4) the Before / After phones,
without a scan and with ?r=: both search "<name> nude leaks", equal height, each tab's first items overflow the screen and
scroll inside it, "Show more" adds groups (kept, no repeat) until it goes, the page never moves; with ?r= the after phone's
Removed rows = the before phone's 4 leak sites; no horizontal overflow.
Screenshots: <vp>-t*.png. --break-thumbs serves scan-engine.js with the gallery drop disabled: only `thumbs:` checks may go red.
--break-people serves scan-engine.js with E.isPhoto always true (logos kept): only `thumbs:` checks may go red.

removals (js/removals.js, the #removals "Where I remove from" panels): section placed after #faq and directly before
#contact; demo defaults (Orla Brennick), neutral mock copy (no onlyfans / leaked / leaks); leak-side images blurred by
default (+ Reveal); idle, the handle covers nothing and no edge line shows; Remove flips all 4 panels (Mega / X / Reddit /
leak site) to their removed state and Show again back, with zero layout shift; a sideways drag on the stage moves the
compare edge + clip, a tap does not; arrow keys on the handle; reduced motion = no transition; no horizontal overflow
(390); ?r=demoRemove1 personalizes each panel all-or-nothing from the backend's top-level `mega` list + x.com /
reddit.com / top other host hits (leak words skipped, no third-party title), thumbs via /api/thumb, still blurred, no URL
rendered, her Mega panel without the demo's own file row; no aggregator host / pack url anywhere on the landing, scan
page or demo site (stale pack rows included: leakshaven.com and s.leakshaven.com hits, a result whose url host is
S.LeakShaven.com; case-insensitive); no mega[] / no x / reddit hits → those panels all the demo; evil values dropped. Screenshots of every panel
live + removed, light + dark. demoPackImg1 (a Google result on a pack's host WITH a thumb, stored before the rule,
served through the API's own off_row): that thumb shows in no view (hero strip / grid, #free phone, scan page) and every
image count equals demoR3port01's. --break-remove serves removals.js without the Remove click handler: only `toggle:`
checks may go red.
The leak-site panel (`fp:`) = a fapello-style profile page: light shell + search on both layers (the removed layer's
copied from the live one), gradient-ring avatar, name / aliases (scanned with ?r=), pills, Follow / Discuss, counters,
>= 6 loaded tiles (phone 112 px / 2 columns, desktop 160 px / 4) cropped by the stage, the first tile row whole inside it
(phone 390 / 320), removed = 404 + DMCA line; the wordmark = the host without its TLD, never cut at 320-390; no sideways
scroll at 320 / 360. --break-fprow serves removals.css with the old centred (column) profile head: only the `fp: first
tile row` checks may go red. Ambient sweep (`sweep:`): no input, on-screen edges glide (CSS transition 1-2 s) to random
15-85 stops, per card (not in lockstep), none off screen / while document.hidden (overridden in the page: headless pages
are always visible) / under reduced motion, CLS 0; a Remove press (before its click), a stage tap (which leaves the edge
where it is), handle keys each stop only that card for good; reduced motion switched on mid-visit stops every edge. The
toggle / drag / key checks first stop every sweep with End on each handle (real input; the edge back at 100).
--break-sweep serves removals.js with the sweep never stepping: only `sweep:` checks may go red. `sweep: toggle: Remove
tap …` is both (--break-remove drops the Remove handler, which also stops the sweep).
personalize also proves the phone sticky bar (`tgcta:`): no slug = "Free scan: type your handle" → #scan; ?r=<slug> =
"DM me on Telegram" → t.me/jakabasej with the #contact prefill + her absolute report link + @handle; Reset = the original
bar. --break-tgcta serves personalize.js without the bar swap: only `tgcta:` checks may go red.

pip (js/pip.js, the mini player of site/video/): ?pip=0 and scan/ without ?r= show none and load no /video/. vis (always on
screen, Jack's iPhone report): landing with no interaction, dark + light, fresh / after a stored scan of sophieraiin
(localStorage, seeded as personalize.js stores it: bypass, declared) / with an old "closed" flag: box + poster bytes < 1 s
after DOMContentLoaded, first video frame < 3 s (Chromium: CDP Fast 4G; WebKit unthrottled, declared), CLS 0 over the whole
load, fully inside the visual viewport top-right under the header at 0.5 / 1 / 2 s (wide: or docked, fully on screen),
elementFromPoint at the inputs / Scan now / "Scanned" line = not the player, close X on the picture's top-right (>= 40 px)
→ tab at the top-right corner (kept across a reload) → tap = back, same box; scrolled to the form / down: same spot.
follow (Jack: "it didn't follow, it got hidden"): a rAF sampler records the rect every frame while scrolling 3 screens
down and back, slowly and with fast flicks (Chromium phone: CDP touch gestures, flicks with momentum; desktop: wheel;
WebKit: script scrollBy per frame, declared): phone = the same rect ±1 px in every frame; desktop = fully on screen in
every frame, the same rect whenever floating; URL-bar collapse / expand (viewport height -94 px and back, x2, at the top
and 2 screens down: window + visualViewport resize) = no jump; dropped mid-screen, scrolled + URL bar = stays; X → tab at
the top-right corner, same tab rect in every frame while scrolling, tap → back to the prior spot (home / dropped).
Screenshot strip <vp>-pip-strip-*.png (0 / 1 / 2 / 3 screens, back to 0, after X, after the tab tap). Mounted before the page's load event (no lazy wait). Landing: a phone never docks (top-right, clear of
the form); wide: docked (absolute) over the bottom-right of the hero card (Weekly report, or the scan report card after
an in-page / ?r= scan) at 55% of the card width while that whole spot is on screen, coverage <= 25%, no live element
under it (elementFromPoint grid), start spot off the screen corner, else just below the card; else floating top-right
at normal size clear of Scan now / CTA bar / Ask-AI; scroll back re-docks unless dragged / resized / tucked. scan/?r=:
floating top-right. 16:9, same-origin embed (no name bar / player UI), muted + playing, tap expands; bar under the
picture = play / sound / expand, 40 px buttons, no link; on the picture only the X (top-right) and the 28 px resize
corner (top-left). X = hidden behind the right edge tab, never removed.
Expanded (YouTube style): tap → full width (phone) / min(960, 70vw) centred right under the header, sound on, same URL;
the page scrolls under it (CDP touch scroll / wheel; WebKit: script scroll, declared), content right below it; chevron /
Esc → mini; pull down follows the finger (15% → snaps back, 50% or a quick flick → mini); mini flung down → hidden with a
'<' tab, tap → back; no new page / window.open anywhere. Free drop (stays mid-screen, kept on-screen under the header); fling or
drag past the left / right edge tucks with a '>' / '<' tab (tap / inward drag = back where it was); corner grip / pinch
resizes (16:9, min 168 px, max 60% / 90% phone width); Esc tucks, Enter on the tab returns; spot / size / tucked kept in
sessionStorage; CLS 0; reduced motion = no transitions; no request
off loopback, no console errors. Phone (Chromium, real touch via CDP), desktop 1440, WebKit iPhone 13 (taps are touch,
drags use the mouse). take: inside the iframe (seeks via Range, as Pages): currentSrc = the first <source> the engine
plays (jack.webm / jack.mp4), duration ~56.9 s, the 3 s frame is the real take (luminance / colourfulness, vs the
placeholder's), google card off at 9 s / on at 11.5 s in the picture's right half, caption 'real' at 2.95 s (hidden under
260 px, #72), floating and docked. Screenshots: <vp>-pip-*.png. --break-tuck serves pip.js with tuck() emptied: only `tuck:` checks
may go red; --break-dock serves it with no dock anchor (card = null): only `dock:` checks may go red; --break-pull serves it with no
drag-down on the expanded player: only `pull:` checks may go red; --break-pipvis serves it with the old dock rule (on the
card whatever the screen: off-screen on a phone): only `vis:` / `follow:` / phone dock-spot checks may go red; --break-pipfollow
serves it with #79's floating spot (re-computed off the form at the current scroll, every scroll): only `follow:` checks may go red.
--break-pipload serves it with the iframe started at once (before the load event): only the `vis:` load-event checks may go red.
Declared bypass: the tabs and huge flows start with the player put away, as after its X (common.PIP_AWAY): floating it
stays top-right while scrolling (by design) and covers what sits there, e.g. the demo's full-screen button.

A scenario part that raises (a Playwright timeout, a missing element) prints one FAIL line for it and the run goes on.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))   # tools/: the scan_e2e/ package beside this file
from scan_e2e.main import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(run())

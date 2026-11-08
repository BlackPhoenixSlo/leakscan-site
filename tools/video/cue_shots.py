#!/usr/bin/env python3
"""Real-path proof for site/video/: serve site/ (Range-capable, tools/video/serve.py), open video/?t=<cue> in BOTH modes,
generic (no name, no scan) and named (?name=NAME), at phone 390x844 and desktop 1440x900, wait until the <video> has
seeked there, screenshot, and assert: only the cue's prefab is on screen, in the right state (wipe --p 100 live / 0
removed), the mode's name in it ("JakaBasej" / NAME), html[data-vo-mode], at both widths (phone too: no stacking) it
sits inside the stage's right half, vertically centred (left >= 50 %, centre within 5 % of the middle: Jack on the left stays uncovered), the rolling
counters (google "About 4,120 results" → "About 3 results", mega "52 GB · 318 videos" → "0 GB · 0 videos"), no request
leaves 127.0.0.1, no console error, jack.webm is the playing source. Each prefab
is shot live (settled; google-images after its tap + grid) and removed (removed + 2 s).
After state (removed): google lists the name's site (<name>.com) + instagram.com and no leak host; google-images shows
>= 4 loaded, unblurred photos of her own (not .rm-img), no "No results".
Plus:
- end card (data-cue-cta, default data-cue-say): generic shows the "Type your name" card + form, named shows the
  named cta-steps take (no title / form, no pill); the form rebuilds in place: ?name=<trimmed> (replaceState, same document, named), an invalid name stays put with a message
- snap (google removed + 0.1 s): "GONE." word card, shake offset, flash; live + 0.25 s: "GOOGLE" word card
- reduced motion (prefers-reduced-motion: reduce): no shake / scale, no flash / particles, the after layer fades
- frame-1920-generic-google-live.png / frame-1920-named-mega-removed.png (counter at 0, stamp, particles) /
  frame-1920-generic-cta.png: the full 1920x1080 frame = the framing proofs
- sfx: AudioContext wrapped (declared) to log oscillators / noise sources: none before the play gesture, a pop at the
  live cue, whoosh + thud at the removed cue, nothing with ?sfx=0
- no AI overvoice: window.speechSynthesis.speak + SpeechSynthesisUtterance hooked in every context (declared: count only,
  never speaks); Space = the play gesture; named: played 0 .. 2.4 s and across data-cue-say → 0 calls, 0 utterances, volume
  untouched, "for NAME" pill at the start (at data-cue-say = data-cue-cta the named flow instead); generic → 0 calls, no
  pill; data-cue-say moved past the end (declared) → the named flow / end card on `ended`, still 0 calls
- the name bar's scan (declared, wire boundary, every context): POST /api/public-scan answers an SSE `failed` (serve.py has
  no API), so a rebuild stays text only
- personalized (tools/scan_stub.py, ?r=demoRemove1): named mode, texts from the scan result in every prefab; every
  .rm-img = the scan's thumbs via <API>/api/thumb, loaded, still blurred; the after photos = the stub's /api/media ones,
  unblurred; shots drawn with the pure draw(t) (the stub has no Range); and ?name= keeps the default photos (video/img/leak-*)
- prod (production images, PROD_HANDLE's already-scanned result PROD_SLUG, no new scan): declared bypasses at the wire
  boundary (Playwright routes, outside service code): GET /api/scan-result|thumb|media on 127.0.0.1 → proxied read-only to
  the production API (thumb: gstatic u= only, else a local 404); POST /api/public-scan → an SSE built from that same saved
  result (progress + result + done), held until the loading state is shot. 1920x1080 + phone 390x844: the name bar
  submit → the wait pill + the take held before the first card → ?r=<slug>; iPhone theater: ?r=<slug>. Asserts: real
  counts (= report() / js/inline-scan.js, recomputed here) in the cta-steps report + Google count, real domains / titles;
  img: every thumb loaded (naturalWidth > 0) via /api/thumb, blurred; her /api/media photos unblurred in the after state;
  no leak URL in the DOM text, every request to 127.0.0.1, jack.webm the playing source
- cta-steps (generic end card, one 10 s take in a phone replica of the landing; phases past the take's end drawn with the pure
  draw(t), declared): cta + 0.3 hero (logo loaded, the site's h1, empty onlyfans.com/ field, camera at rest), + 2.2 the
  camera zoomed onto the field (scale >= 2.2) typing a proper prefix, + 3.05 the field typed handle(DEMO) ("jakabasej")
  in full, + 3.75 "Scan now" pressed (camera pulled back), + 5.6 the scan card mid-scan (bar 10-90 %, "Searching <place>,
  step N of 9…", "@<handle>"), the places walk Google → … → Mega with N rising, + 7.4 "N links found" rolling, + 8.3
  the report ("87 links found", tabs Links 87 / Images 12 / Sites 31, 5 *.example rows, "+ 82 more"), + 9.65 the toast
  "Rewatch this video with YOUR content" + the name flipped in (frame-1920-generic-cta-<n>-<phase>.png); after the take
  ends the post-roll clock keeps it looping to the flip (frame-1920-generic-cta-flip-postroll.png); phone portrait +
  iPhone theater: every phase shot (phone-{portrait,theater}-generic-cta-<n>-<phase>.png), typed handle on screen >= 11 px
  portrait / >= 20 px theater, the toast's letters >= 11 px portrait
- named flow (?name=NAME, data-cue-cta): the same take with handle(NAME) typed (no scan result: the placeholder rows), '@<handle(NAME)>' on the scan / report cards, the toast
  = only the compact contact row (Telegram @jakabasej / WhatsApp +386 40 703 992 / me@jackbase.dev), never NAME, no
  title / form / flip / pill; held to cta + 14.6 (named loop 15 s), looping after the take ends; 1920 + phone portrait + iPhone
  theater phases (frame-1920-named-cta-*.png, phone-{portrait,theater}-named-cta-*.png), contacts >= 8 px portrait
- no half-width UI (phone portrait, iPhone theater, 1920): touch play bar = the full stage width at its bottom, thin (<= 34 px),
  no .vo-ui box 40-60 % of the stage wide, the full screen button in the stage's top-right quarter (off Jack's left half)
--break-named serves video-overlays.js with named mode's cta-steps off (ctac = null): only the "named flow:" checks go red.
- player: phone (touch): no native controls, own play bar, a tap on the stage plays + "Rotate for full size" hint;
  proof-phone-portrait-generic-google-live.png = the whole 390x844 screen, card inside the stage's right half;
  iPhone theater (declared: Fullscreen API removed by an init script, as on iPhone Safari): the button rotates the stage
  90deg over the screen (proof-phone-theater-generic-google-live.png; the card in its right half = the screen's lower
  half), scroll locked, Esc / back / X each close it; desktop: the button puts the STAGE in full screen, the card on the
  right half of the centred 16:9 picture
--break-thumbs serves video-overlays.js without the thumb src assignment: only the thumbs check goes red.
--break-img serves video-overlays.js with report()'s image field wrong (it.title for it.src): only the "prod img:" checks go red.
- name bar + in-place swap (phone 390x844, desktop 1440x900, frame 1920x1156 = a 1920x1080 stage + the bar), speech hooked
  (declared: counts calls): generic at 0 s the bar sits under the stage, in view, with the pulsing "type your name" pill (gone after the
  first focus); an invalid name is rejected inline (message, URL unchanged); phone: in theater (declared: Fullscreen API
  removed, as iPhone) the "Your name" pill closes it and focuses the input; played past 2.4 s, SWAP_NAME + Enter →
  at once (no rebuild card: no .vo-rb in the page, no pause event): ?name=<encoded> (replaceState, same document), named
  mode, within 1 s playing from < 1 s ({vp}-swap-settled.png); 0 speak calls (desktop: also across data-cue-say), "for" pill; google at its live cue
  shows SWAP_NAME; cta-steps never shown (MutationObserver); Change re-opens the input prefilled; Reset → generic, URL
  without query, restarted, end card back. Proof PNGs: frame-1920-swap-bar-generic-0s.png (page), frame-1920-swap-settled.png,
  frame-1920-swap-google-live.png (1920x1080 stage).
- full frame (1920x1080, 1280x800, phone 390x844, iPhone theater, desktop full screen): the <video> box == the stage box,
  the drawn picture (object-fit + videoWidth / Height) covers the whole stage (full screen: the centred 16:9 picture, the
  overlay = its right half); .vo-over / .vo-box = the stage's right half, transparent (no background, no shadow: the
  cards are drawn straight on the video); at a card-free, still time (7.2 s; the intro fill hidden, declared) the screen's right half = the video frame's right half
  (screenshot, native controls + player UI off (declared), vs drawImage(video), 8x8 grid, mean |diff| < 3, every cell < 24) -> full-frame-<vp>.png
--break-full serves css/video.css with the old split layout appended (the video in the left half, an opaque panel behind
  the cards): only the "full frame:" checks go red.
--break-thumbs serves video-overlays.js without the thumb src assignment: only the thumbs check goes red.
--break-steps serves index.html without the cta-steps phone (.vo-steps): only the "cta-steps:" checks go red.
--break-swap serves video-overlays.js with the submit's rebuild(n) call removed: only the "swap:" checks go red.
--break-demo serves video-overlays.js with the old demo name (DEMO = 'Orla Brennick'): only the typed-handle checks (generic "cta-steps: typed …
  DEMO", the "named flow" / "prod … end card" jakabasej ones) go red.
- prod real images: every leak image on every card (.rm-img) blurred exactly BLUR_PX = 2px (video cards: blur(2px);
  removals.css / the report / styles.css .live-ico untouched), the after photos unblurred; the cards use people photos only:
  "prod logos:" the landing report (?r=PROD_SLUG, js/inline-scan.js gallery() + E.isPhoto, same proxy) and the video drop
  the same thumbs (its Images tab = the video's kept count, every landing tile in the video's kept set, none dropped by
  the video); per card a trigger (live + 0.15) + settled (live settled, removed + 2) shot: prod-<label>-<card>-<state>.png
- no "Tessa" in the DOM text (generic + named; the test name is Jaka Basej)
- persona (generic = the demo persona "JakaBasej"), 1920x1080 + phone 390x844 + iPhone theater: at every card's live +
  removed cue the card's text has "JakaBasej", no "Your name" / "Tessa"; google / google-images after state = jakabasej.com
  + instagram.com › jakabasej; the end card (cta + 0.6) and its flip (cta + 9.65, + the post-roll) stay "JakaBasej", a name
  typed in the end card form (not submitted) flips in instead; named ?name=Jaka%20Basej: every card has "Jaka Basej", no
  "JakaBasej" -> persona-<view>-<mode>-<card>-<state>.png
--break-persona serves video-overlays.js with GENERIC = 'Your name' (the old placeholder): only the "persona:" checks go red.
--skip-prod skips the production-image part (break runs: no production GETs); hers() then runs only with --hers-raw (thumbs / media 404).
- hers (hers(), checks "hers …"): her result (PROD_SLUG, --hers-raw = its saved JSON, else one read-only production GET; declared: served
  locally for /api/scan-result, thumb / media proxied read-only, POST /api/public-scan = an SSE of that same result) via ?r= AND via the
  last scan (the landing's in-page scan → leakscan.last → /video/ with no query), 1920 + phone 390x844 + iPhone theater; pure draw(t)
  (declared) + shots at 5 / 12 / 16.5 / 19 / 23 / 26 / 31 / 40 / 47 s (hers-<r|last>-<view>-t<t>.png): every card 10-34.6 s shows >= 1
  field of her result (host / title / count / her thumb loaded), the wall = her top sites first, no JakaBasej / Your name / Orla Brennick
  on screen or in a slot, the "for <name>" pill at 1 s; "hers handle": the intro (3 / 3.5 / 6 / 9.5 s) and the end card (36 / 37.85 /
  40 s) type onlyfans.com/<her handle> + "@<her handle>"; "hers end" (47 s): her report: '@<handle>', Images = her kept people
  photos, rows = her hosts + titles (no *.example, no URL), "+N more", 9 of her photos blurred exactly 2px, the contact footer <= 20 %
  of the phone, no "This is what I'd clear"; never "jakabasej" outside the contact footer (on screen or in the DOM text);
  "hers counts": the end card's Links / Images / Sites == the landing report's for the same result (?r=: the landing ?r=;
  last: the landing's own scan; pip: the landing around the mini player); the landing's mini player (?pip=1, iframe loaded before the scan)
  turns hers in place on the storage event (hers-pip-<1920|phone>-t12.png), then its intro / end card shot in the iframe at
  3 / 6 / 9.5 / 36 / 40 / 47 s (hers-pip-<view>-t<t>.png, + the whole landing at 47 s: hers-pip-<view>-t47-page.png).
--break-herend serves video-overlays.js with the old demo end in personalized mode (rr = null, jakabasej typed): only the
  "hers handle" / "hers end" / "hers counts" / "prod end card" / prod report checks (and the named flow's typed handle, unless
  --name slugs to jakabasej) go red.
--break-burst serves video-overlays.js with photoOnly probing every thumb at once (the pre-pacing burst): the "hers paced"
  checks go red.
--break-hers serves video-overlays.js with a loaded result never applied: the "hers" checks (and the stub's ?r= "personalized" ones) go red.
--break-voice serves video-overlays.js with the old overvoice (speechSynthesis.speak(name) 0.5 s in): only the "no overvoice"
  / swap speak checks go red. --only voice = the speech + desktop swap part.
--break-logos serves video-overlays.js with its E.isPhoto test off (logos kept): only the "prod logos:" check goes red.
- fills (fill(), 1920x1080 + phone 390x844 portrait + iPhone theater, generic + named): the intro (.vo-intro, data-cue-in ..
  -out, 0.3-9.8 s) and the gap card (.vo-sites, 28.2-34.6 s). Real seeks + shots at 0.5 / 3 / 3.5 / 6 / 9.5 / 10.2 / 29 /
  32 / 34.5 / 35 s (fill-<view>-<mode>-t<t>.png): 0.5 the hero, 3 typing, 3.5 "jakabasej" typed in full (both modes,
  >= 11 px on screen), 6 the scan card ("@jakabasej", "Searching <place>, step N of 9…"), 9.5 "Building YOUR video…"
  (>= 11 px) while it slides out, 10.2 google alone (intro gone), 29 / 32 the sites wall, counter rolling, 34.5 "10,000+",
  every name struck, 35 the end card alone. Timeline (pure draw(t), declared: every 0.1 s 0-36 s): intro visible exactly
  0.3-9.8, sites exactly 28.2-34.6, counter "10,000+" by 34 s, never two right-half cards at once (the "for NAME" pill is
  not a card), the pill (named 0-2 s) never overlaps the intro, captions stay on the left half (right edge <= 50 %), never
  over a fill. Scan hold (1920, POST /api/public-scan held unanswered, declared): the name bar submit → the take holds on
  the intro's "Building YOUR video…" beat (intro out - 0.5) with the wait pill (fill-1920-hold.png). Reduced motion: the
  fills fade, no pop (transform none). Checks are prefixed "intro:" / "sites:" / "fills:".
--break-intro serves index.html with the intro's data-cue-in / -out removed (the intro never shows): only the "intro:"
  checks go red. --only fill = this part.
- google anim (gsearch(), checks "google …"; 1920x1080 + phone 390x844, generic + ?r=PROD_SLUG = her saved result, declared:
  served locally, thumb / media 404, no production): real seeks + shots at 10.1 / 10.2 / 11 / 12 / 12.36 / 12.9 / 13.6 / 14.9 /
  15.4 s (ganim-<vp>-<mode>-t<t>.png). "google query": both search boxes read "<name> nude leaks" (JakaBasej / her display
  name); "google titles": the 4 Google rows (+ the 2 Google Images ones) = "<name> OnlyFans leaks / nude photos / leaked videos /
  nudes: full leak", hosts only (?r=: her top hosts, no URL); "google slide": google + google-images enter by translateX
  only (pure draw: offset > 100 px at live + 0.02 → 0 by live + 0.45, scale 1 throughout; x still pops; reduced motion: no
  offset); "google timing": google's removed cue = G_REMOVED_OLD − 0.5 (12.36), the wipe's first frame (--p < 100, pure draw
  0.01 s steps) = removed + 0.25, inside his "they" .. "removed" and done by "removed"'s end + 0.4. With --base REF: "google
  post": from google-images live + 0.5 to the end (pure draw, 0.05 s steps, 1920, both modes) every card's / descendant's
  style, every card's text but google / google-images, the captions == REF's files (index.html, video-overlays.js,
  video.css served from git, declared). --only google = this part.
--break-gtime serves index.html with google's old removed cue (G_REMOVED_OLD): only the "google timing" checks go red.
- blur (blur(), checks "blur …"; 1920x1080 + phone 390x844, generic + ?r=PROD_SLUG = her saved result, declared: served locally,
  every /api/thumb = a local photo (img/removals/editorial-01.webp, so her kept photos fill the cards + the end-card report),
  media 404, no production): every leak image on every card (.rm-img / .vo-real, computed filter) = blur(2px) saturate(0.95),
  .vo-real scale(1.2) kept, the after state's own photos (.vo-own) unblurred; shots at 11 / 15.5 / 47 s (blur-<vp>-<mode>-t<t>.png).
  With --base REF: the same images' computed filters == REF's but blur(5px) → blur(2px). --only blur = this part.
--break-blur serves css/video.css with blur(5px) back: only the "blur" checks go red.
Usage: cd ~/leakhunt && uv run python ~/leakscan-site/tools/video/cue_shots.py OUT_DIR [--name "Jaka Basej"] [--base REF] [--break-gtime] [--break-blur] [--break-thumbs] [--break-steps] [--break-swap] [--break-demo] [--break-full] [--break-named] [--break-img] [--break-logos] [--break-persona] [--break-captions] [--break-voice] [--break-intro] [--skip-prod] [--only prod|captions|voice|fill|hers|google|blur]
Prints one line per shot / check + 'FAIL …' lines; exit 1 on any failure."""
import argparse, json, pathlib, re, socket, subprocess, sys, time, urllib.parse, urllib.request
sys.path[:0] = [str(pathlib.Path(__file__).resolve().parent), str(pathlib.Path(__file__).resolve().parent.parent)]
from scan_e2e import thin
from serve import serve
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2]


def take_len():   # the take's length (s): the end-of-take checks seek just before it
    try:
        return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                     str(ROOT / "site/video/jack.webm")], capture_output=True, text=True, timeout=20).stdout)
    except Exception:
        return 40.0


END = take_len()
GENERIC = "JakaBasej"   # the generic demo persona (js/video-overlays.js GENERIC)
GENERIC_SITE, GENERIC_IG = "jakabasej.com", "jakabasej"
CTA_TEXT = "Type your name in the link → this video rebuilds with YOUR leaks"
VIEWPORTS = {"phone": dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True),
             "desktop": dict(viewport={"width": 1440, "height": 900})}
SEEKED = ("t => { const v = document.querySelector('video'); return v.readyState >= 3 && !v.seeking"
          " && Math.abs(v.currentTime - t) < 0.05 }")
# demoRemove1 (tools/scan_stub.py): what its scan result must put in the [data-vo] slots
WANT_TEXT = {"name": "Mira Example", "site": "miraexample.com", "ig": "mira.example", "tt": "mira.draws", "x-at": "@demo_reposter", "x-l1": "Mira Example leaked full set", "sub": "r/demo_leaksub",
             "rd-title": "Mira Example new pack in comments", "mega-title": "demo.creator MEGA pack 2026",
             "mega-meta": "6.2 GB · 412 images · 88 videos · 3 days ago"}
COUNT = {("google", "live"): "About 4,120 results", ("google", "removed"): "About 3 results",
         ("mega", "live"): "52 GB · 318 videos", ("mega", "removed"): "0 GB · 0 videos"}
OWN = "() => [...document.querySelectorAll('.vo-own')].map(i => [i.getAttribute('src'), i.naturalWidth, getComputedStyle(i).filter])"
# the after layer of the visible prefab: [text, [[src, naturalWidth, filter] of its <img>]]
AFTER = """() => { const g = [...document.querySelectorAll('.vo-pf[data-prefab]')].find(e => !e.hasAttribute('data-off')).querySelector('.rm-gone');
  return [g.textContent.replace(/\\s+/g, ' '), [...g.querySelectorAll('img')].map(i => [i.getAttribute('src'), i.naturalWidth, getComputedStyle(i).filter, i.classList.contains('rm-img')])]; }"""
VISIBLE = """() => { const s = document.querySelector('.vo-stage').getBoundingClientRect();
  return [...document.querySelectorAll('.vo-pf')].filter(e => !e.hasAttribute('data-off')).map(e => { const r = e.getBoundingClientRect(), rs = e.querySelector('.rm-stage');
    return [e.dataset.prefab || e.className, rs ? getComputedStyle(rs).getPropertyValue('--p').trim() : null, e.textContent.replace(/\\s+/g, ' '),
            [(r.left - s.left) / s.width, (r.top - s.top) / s.height, (r.right - s.left) / s.width, (r.bottom - s.top) / s.height],
            [...e.querySelectorAll('.vo-roll')].map(x => x.textContent)]; }); }"""
# the visible prefab's effect state: [--x, --f, kw-live [text, opacity], kw-gone [...], transform, flash display, burst display, stamp opacity, max particle opacity, .rm-gone [opacity, clip-path]]
FX = """pid => { const e = document.querySelector(`.vo-pf[data-prefab="${pid}"]`), cs = getComputedStyle(e), kw = c => { const k = e.querySelector(c); return [k.textContent, +getComputedStyle(k).opacity]; };
  const g = getComputedStyle(e.querySelector('.rm-gone'));
  return [+e.style.getPropertyValue('--x'), +e.style.getPropertyValue('--f'), kw('.vo-kw-live'), kw('.vo-kw-gone'), cs.transform,
          getComputedStyle(e.querySelector('.vo-rs'), '::after').display, getComputedStyle(e.querySelector('.vo-burst')).display,
          +getComputedStyle(e.querySelector('.vo-stamp')).opacity, Math.max(...[...e.querySelectorAll('.vo-burst i')].map(i => +getComputedStyle(i).opacity)),
          [+g.opacity, g.clipPath], e.offsetWidth, e.offsetHeight]; }"""
LEAK_HOSTS = re.compile(r"\.example\b|leak|pirate|forum-dump|free-galleries", re.I)
IMGS = "() => [...document.querySelectorAll('.rm-img')].map(i => [i.getAttribute('src'), i.naturalWidth, getComputedStyle(i).filter])"
PIP_EMBED = re.search(r"var EMBED = '([^']+)'", (ROOT / "site/js/pip.js").read_text(encoding="utf-8"))[1]   # the mini player's embed style
PIP_CAPT = """() => { const s = document.querySelector('.vo-stage').getBoundingClientRect(), c = document.querySelector('.vo-capt');
  const r = getComputedStyle(c).display === 'none' ? [] : [...c.querySelectorAll('span')].map(e => e.getBoundingClientRect()).filter(x => x.width);
  return r.length ? (Math.max(...r.map(x => x.right)) - s.left) / s.width : null; }"""
SAY_STUB = """window.__said = []; window.__utt = 0; if ('speechSynthesis' in window) speechSynthesis.speak = u => {
  __said.push([u && u.text, document.querySelector('video')?.currentTime]); };   /* the page must never call it (no AI overvoice) */
  if (window.SpeechSynthesisUtterance) { const U = window.SpeechSynthesisUtterance; window.SpeechSynthesisUtterance = class extends U {
  constructor(...a) { super(...a); __utt++; } }; }"""
SFX_STUB = """window.__sfx = []; window.__actx = 0; { const A = window.AudioContext; if (A) window.AudioContext = class extends A {
  constructor(...a) { super(...a); __actx++; }
  createOscillator() { __sfx.push(['osc', +document.querySelector('video').currentTime.toFixed(2)]); return super.createOscillator(); }
  createBufferSource() { __sfx.push(['noise', +document.querySelector('video').currentTime.toFixed(2)]); return super.createBufferSource(); } }; }"""
# cta-steps state (null without the phone): scene opacities, camera scales (--cz per scene page), hero, typed handle + its
# on-screen px (font x --k x camera), scan line, report, the end toast (+ its smallest on-screen px) and the flipped name
STEPS = """() => { const c = document.querySelector('.vo-cta'), s = c && c.querySelector('.vo-steps'); if (!s) return null;
  const q = x => s.querySelector(x), mi = q('.vo-mi-t'), k = +document.querySelector('.vo-box').style.getPropertyValue('--k'), logo = q('.vo-hd img'),
        cz = [...s.querySelectorAll('.vo-pg')].map(e => +e.style.getPropertyValue('--cz')), fs = e => parseFloat(getComputedStyle(e).fontSize), sp = x => x.replace(/\\s+/g, ' ').trim();
  return {off: c.hasAttribute('data-off'), so: [...s.querySelectorAll('.vo-step')].map(e => +getComputedStyle(e).opacity), cz,
          h1: sp(q('.vo-h1').textContent), logo: logo.complete && logo.naturalWidth > 0, typed: mi.textContent, px: +(fs(mi) * k * cz[0]).toFixed(1),
          btn: q('.vo-mbtn').textContent.trim(), press: +s.style.getPropertyValue('--press'), ms: q('.vo-ms').textContent, bar: +s.style.getPropertyValue('--bar'),
          at: q('.vo-sc-scan .vo-at').textContent, count: sp(q('.vo-mc').textContent), tabs: [...s.querySelectorAll('.vo-tabs2 > span')].map(e => sp(e.textContent)),
          rows: [...s.querySelectorAll('.vo-dom')].map(e => e.textContent), rowon: [...s.querySelectorAll('.vo-row')].map(e => e.style.display !== 'none'), more: q('.vo-more').textContent, end: sp(q('.vo-end-h').textContent),
          eo: +getComputedStyle(q('.vo-end')).opacity, endpx: +(Math.min(fs(q('.vo-end-h')), fs(q('.vo-end-f'))) * k).toFixed(1), mini: q('.vo-mini-n').textContent,
          shown: [...s.querySelectorAll('.vo-end > span')].filter(e => getComputedStyle(e).display !== 'none').map(e => sp(e.textContent)),
          contacts: [...s.querySelectorAll('.vo-end-c > span')].map(a => sp(a.textContent)),
          inbox: (() => { const e = q('.vo-end').getBoundingClientRect(); return [...s.querySelectorAll('.vo-end > .vo-nm, .vo-end-c > span')].every(x => { const r = x.getBoundingClientRect();
            return r.width > 0 && r.left >= e.left - .5 && r.right <= e.right + .5 && x.scrollWidth <= x.clientWidth + 1; }); })(),
          nmpx: +(Math.min(...[...s.querySelectorAll('.vo-end > .vo-nm')].map(fs)) * k).toFixed(1),
          chrome: [...c.querySelectorAll(':scope > .vo-cta-t, :scope > .vo-cta-f')].map(e => getComputedStyle(e).display)}; }"""
DEMO, LEAKS = "Jaka Basej", 87
TABS = [LEAKS, 12, 31]   # = js TABS: the placeholder report's Links / Images / Sites
CONTACTS = ["Telegram @jakabasej", "WhatsApp +386 40 703 992", "me@jackbase.dev"]   # = site/imprint.html
def named_end(s, nm):   # the named toast: only the compact contact row (never NAME), nothing generic, no title / form
    return (s and s["shown"] == ["".join(CONTACTS)] and s["contacts"] == CONTACTS and s["inbox"] and nm not in "".join(s["shown"])
            and s["chrome"] == ["none", "none"])
HERO_H1 = "Leaked content, taken down by a real person. Me."
handle = lambda n: re.sub(r"[^\w.]", "", n.lower()) or "creator"   # = js handle(): "Jaka Basej" → "jakabasej"
# the phases (s into the loop) shot on every viewport
PHASES = (("1-hero", 0.3), ("2-zoom", 1.6), ("3-typed", 3.05), ("4-press", 3.75), ("5-scanning", 5.6), ("6-report", 8.3), ("7-flip", 9.65))
DRAW = "t => { document.querySelector('video').pause(); window.VideoOverlays.draw(t); }"
PROGRESS = re.compile(r"Searching (Google|Google Images|X|Reddit|Mega), step ([1-9]) of 9…")
# [stage rect, .vo-over rect, visible card rect, stage transform, data-vo-full, html overflow, video.controls]
GEOM = """() => { const r = e => { const b = e.getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; }, st = document.querySelector('.vo-stage'),
  card = [...document.querySelectorAll('.vo-pf')].find(e => !e.hasAttribute('data-off'));
  return [r(st), r(document.querySelector('.vo-over')), card ? r(card.querySelector('.vo-phone, .vo-panel, .vo-steps') || card) : null, getComputedStyle(st).transform,
          document.documentElement.dataset.voFull || null, getComputedStyle(document.documentElement).overflow, document.querySelector('video').controls]; }"""
IPHONE_FS = ("Object.defineProperty(Document.prototype, 'fullscreenEnabled', { get: () => false });"
             "Element.prototype.requestFullscreen = undefined; Element.prototype.webkitRequestFullscreen = undefined;")
SWAP_NAME = "Jaka Basej"
SWAP_VIEWPORTS = {"phone": VIEWPORTS["phone"], "desktop": VIEWPORTS["desktop"], "frame-1920": dict(viewport={"width": 1920, "height": 1156})}
# [stage rect, bar rect, input rect, button rect, hint [display, rect, animation], innerHeight, video.currentTime]
BAR = """() => { const r = e => { const b = e.getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; }, h = document.querySelector('.vo-nb-hint'), hs = getComputedStyle(h);
  return [r(document.querySelector('.vo-stage')), r(document.querySelector('.vo-nb')), r(document.querySelector('#vo-nb-in')), r(document.querySelector('.vo-nb-f button')),
          [hs.display, r(h), hs.animationName], innerHeight, document.querySelector('video').currentTime]; }"""
CTA_WATCH = """() => { window.__ctaSeen = false; const c = document.querySelector('.vo-cta');
  new MutationObserver(() => { if (!c.hasAttribute('data-off')) __ctaSeen = true; }).observe(c, { attributes: true }); }"""
fails = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
    if not ok:
        fails.append(name)
    return ok


def after_ok(pid, name, txt, imgs):   # name None (generic): the site is persona()'s check
    site = re.sub(r"[^a-z0-9-]", "", name.lower()) + ".com" if name else ".com"
    if pid == "google":
        return site in txt and "instagram.com" in txt and not LEAK_HOSTS.search(txt)
    own = [i for i in imgs if i[1] > 0 and i[2] == "none" and not i[3]]
    return len(own) >= 4 and "No results" not in txt and site in txt and "Instagram" in txt and not LEAK_HOSTS.search(txt)


def guard(ctx, base_ok, seen=None):
    """abort + record every request outside the local server(s); seen collects every URL"""
    ext = []

    def route(r):
        if seen is not None:
            seen.append(r.request.url)
        if any(r.request.url.startswith(b) for b in base_ok):
            r.fallback()   # → a --break-* route (registered earlier), else the network
        else:
            ext.append(r.request.url)
            r.abort()
    ctx.route("**/*", route)
    return ext


def console(pg, errs):
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errs.append(str(e)))


BREAK = {}   # --break-* routes, applied to every context


SCAN_FAILED = "event: failed\ndata: no scan API in this test\n\n"


def ctx_new(b, **kw):
    ctx = b.new_context(**kw)
    # declared bypass, wire boundary: the name bar's POST /api/public-scan → an SSE `failed` (text only); prod() overrides it
    ctx.route("**/api/public-scan", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=SCAN_FAILED))
    for pat, body, ctype in BREAK.values():   # one-arg handler (playwright passes (route, request) to two-arg ones)
        ctx.route(pat, (lambda body, ctype: lambda r: r.fulfill(body=body, content_type=ctype))(body, ctype))
    return ctx


def goto(pg, base, query, t):
    pg.goto(f"{base}video/?{query}{'&' if query else ''}t={t:g}")
    pg.wait_for_function(SEEKED, arg=t, timeout=15000)
    pg.wait_for_timeout(1200)   # the native loading spinner fades out


def stage_attr(html, k):
    m = re.search(r'class="vo-stage"[^>]*\b%s="([\d.]+)"' % re.escape(k), html)
    return float(m[1]) if m else None


def personalized(b, out, break_thumbs):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    stub = subprocess.Popen([sys.executable, str(ROOT / "tools" / "scan_stub.py"), "--port", str(port)],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        stub.stdout.readline()
        base, api = f"http://127.0.0.1:{port}/", f"http://localhost:{port}"   # the stub injects the other loopback name as data-api
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        ext, errs = guard(ctx, (base, api + "/")), []
        if break_thumbs:   # wire boundary: same bytes minus the thumb src assignment
            js = (ROOT / "site/js/video-overlays.js").read_text(encoding="utf-8")
            assert "im.setAttribute('src', src);" in js, "break: marker not found"
            js = js.replace("im.setAttribute('src', src);", "", 1)
            ctx.route("**/js/video-overlays.js", lambda r: r.fulfill(body=js, content_type="application/javascript"))
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"{base}video/?r=demoRemove1&t=15.3")
        try:
            pg.wait_for_function("() => document.querySelector('[data-vo=name]').textContent === 'Mira Example'", timeout=8000)
            pg.wait_for_function("() => [...document.querySelectorAll('.rm-img')].every(i => i.complete && i.src.includes('/api/thumb'))", timeout=12000)
            pg.wait_for_function("() => window.VideoOverlays.photos.settled", timeout=60000)   # paced probes done: no late draw(currentTime) over the draw(t) shots
        except Exception:
            pass
        pg.wait_for_timeout(500)
        txt = pg.evaluate("() => Object.fromEntries([...document.querySelectorAll('[data-vo]')].reverse().map(e => [e.dataset.vo, e.textContent]))")
        got = {k: txt.get(k) for k in WANT_TEXT}
        check("personalized ?r=demoRemove1: texts from the scan result (name, X, Reddit, Mega)", got == WANT_TEXT, got)
        check("personalized ?r=demoRemove1: named mode", pg.evaluate("() => document.documentElement.dataset.voMode") == "named")
        im = pg.evaluate(IMGS)
        check(f"personalized ?r=demoRemove1: all {len(im)} .rm-img = scan thumbs via {api}/api/thumb, loaded, blurred",
              len(im) >= 13 and all(s.startswith(api + "/api/thumb?u=") and w > 0 and "blur(" in f for s, w, f in im), im[:3])
        try:
            pg.wait_for_function("() => [...document.querySelectorAll('.vo-own')].every(i => i.src.includes('/api/media/') && i.complete && i.naturalWidth > 0)", timeout=12000)
        except Exception:
            pass
        own = pg.evaluate(OWN)
        check(f"personalized ?r=demoRemove1: the {len(own)} after photos = the scan's own photos ({api}/api/media/demoRemove1/<n>.jpg), unblurred",
              len(own) == 6 and all(s.startswith(api + "/api/media/demoRemove1/") and w > 0 and f == "none" for s, w, f in own), own[:3])
        # evidence shots drawn with the pure draw(t) (the stub has no Range, so the page's <video> can't seek to a cue)
        cues = {m[1]: (float(m[2]), float(m[3]), float(m[6] or 0), float(m[4])) for m in re.finditer(
            r'data-prefab="([\w-]+)" data-cue-live="([\d.]+)" data-cue-removed="([\d.]+)" data-cue-out="([\d.]+)"( data-cue-tap="([\d.]+)")?',
            (ROOT / "site/video/index.html").read_text(encoding="utf-8"))}
        for pid, state in (("google-images", "live"), ("x", "live"), ("google", "removed"), ("google-images", "removed")):
            live, rem, tap, off = cues[pid]
            pg.evaluate(DRAW, (min(rem - 0.1, tap + 1.0) if tap else live + 1.0) if state == "live" else min(rem + 2.0, off - 0.45))
            pg.wait_for_timeout(800)   # decode + paint of the blurred thumbs
            pg.screenshot(path=str(out / f"desktop-personalized-demoRemove1-{pid}-{state}.png"))
            if state == "removed":
                txt, imgs = pg.evaluate(AFTER)
                check(f"personalized ?r=demoRemove1: {pid} after state = miraexample.com + Instagram, no leak host",
                      after_ok(pid, "miraexample", txt, imgs) and ("mira.example" in txt or pid == "google-images"), txt)
        check("personalized: no request outside the stub, no JS error", not ext and not errs, (ext, errs))
        ctx.close()
    finally:
        stub.terminate()


# ---------- prod: production images from an already-scanned result (read-only, no new scan) ----------
PROD = "https://scan.srv1395798.hstgr.cloud"   # = js/scan-engine.js's API on github.io
PROD_SLUG, PROD_HANDLE = "MT4kpWQI3QXp", "sophieraiin"
PROD_SLUG2 = "2_YPj7TbK4rm"   # an older scan of the same handle: other counts than the placeholder's (the ?r= / theater run)
VIDEO_RE = re.compile(r"\.(?:mp4|m3u8|webm|mov|mkv)(?:[?#]|$)|/(?:videos?|watch|embed|clips?|vod)(?:[/?#.-]|$)", re.I)
GSTATIC = re.compile(r"^https://[a-z0-9-]+\.gstatic\.com/[^\s\"'<>\\]*$")
# REAL count = the g-count slot's value (__src), not its roll frame (the read happens mid-play)
REAL = """() => { const q = s => [...document.querySelectorAll(s)], im = i => [i.getAttribute('src'), i.naturalWidth, getComputedStyle(i).filter];
  return {g: q('.vo-pf[data-prefab="google"] .rm-live .rm-img').map(im), grows: q('.vo-pf[data-prefab="google"] .rm-live .m-site').map(e => e.textContent),
          grid: q('.vo-gi .rm-live .vo-grid .rm-img').map(im), rep: q('.vo-cta .vo-steps .vo-real').map(im), all: q('.rm-img').map(im),
          own: q('.vo-own').map(im), count: (e => e && (e.__src || e.textContent))(document.querySelector('[data-vo="g-count"]')), photos: window.VideoOverlays.photos,
          cards: q('.vo-pf[data-prefab]').map(e => [e.dataset.prefab, [...e.querySelectorAll('.rm-img, .vo-real')].map(im)])}; }"""
BLUR = lambda f: float(m[1]) if (m := re.search(r"blur\(([\d.]+)px\)", f or "")) else 0.0
BLUR_PX = 2   # px: the video cards' leak-image blur, exact (css/video.css .vo .rm-img / .vo-real; owner's call)
# the landing report (?r=, js/inline-scan.js) once its probes settled: [Images tab count, every strip / grid tile src]
LANDING = """() => { const n = document.querySelector('#tab-report-images .live-tab-n');
  return [n ? +n.textContent : null, [...document.querySelectorAll('.live-strip-track .gi-img, .live-grid .gi-img')].map(i => i.getAttribute('src'))]; }"""


def prod_expect(raw):
    """= video-overlays.js report() (the landing card's counts, js/inline-scan.js), recomputed: links, images, sites, titled rows' domains, Google count"""
    def dom(v):
        d = re.sub(r"^www\.", "", v.strip().lower()) if isinstance(v, str) else ""
        return d if len(d) <= 80 and re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", d) else None

    def link(u):
        if not isinstance(u, str) or len(u) > 600 or not re.fullmatch(r"https?://[^\s\"'<>\\]+", u, re.I):
            return None
        x = urllib.parse.urlsplit(u)
        if x.username or x.password:
            return None
        return x, urllib.parse.urlunsplit((x.scheme.lower(), x.netloc.lower(), x.path or "/", x.query, x.fragment))

    def txt(v):
        if not isinstance(v, str):
            return None
        t = re.sub(r"\s+", " ", re.sub(r"[\u0000-\u001f\u007f​-‏ -‮]", " ", v)).strip()
        return t if t and len(t) <= 200 and not re.search(r"[<>{}]|javascript:|data:|https?://|www\.", t, re.I) else None
    seen, doms, rows, res = set(), [], [], []

    def add(u, d, title):
        x = link(u)
        if not x or x[1] in seen:
            return
        d = dom(d) or dom(x[0].hostname or "")
        if not d:
            return
        seen.add(x[1])
        rows.append((d, txt(title)))
        if d not in doms:
            doms.append(d)
    for h in (raw.get("hits") or [])[:1000]:
        if h:
            add(h.get("url"), h.get("domain"), h.get("title"))
    for r in (raw.get("results") or [])[:200]:
        if not r:
            continue
        add(r.get("link"), r.get("domain"), r.get("title"))
        x = link(r.get("link"))
        d = x and (dom(r.get("domain")) or dom(x[0].hostname or ""))
        if d:
            th = r.get("thumb")
            res.append({"link": x[1], "thumb": th if isinstance(th, str) and len(th) <= 600 and GSTATIC.match(th) else None, "kind": r.get("kind")})
    ok = lambda u: isinstance(u, str) and len(u) <= 600 and GSTATIC.match(u)
    by, imgs = {}, []
    for r in res:
        if r["thumb"] and r["thumb"] not in by:
            by[r["thumb"]] = r
    vid = lambda r: bool(r) and (r["kind"] == "video" or bool(VIDEO_RE.search(r["link"] or "")))
    for u, r in [(u, by.get(u)) for u in (raw.get("images") or [])[:200]] + [(r["thumb"], r) for r in res]:
        if ok(u) and u not in imgs and not vid(r):
            imgs.append(u)
    g = raw.get("google_total")
    return {"tabs": [len(rows), min(len(imgs), 60), len(doms)], "rows": [d for d, t in rows if t][:5],
            "count": f"About {g:,} results" if isinstance(g, int) and 0 < g < 1e9 else None}


def prod(b, base, out, cues, cta):
    def stored(slug):   # read-only GET of a stored result → (raw, expected, its leak URL paths)
        raw = json.load(urllib.request.urlopen(f"{PROD}/api/scan-result/{slug}", timeout=30))
        (out / f"prod-scan-result-{slug}.json").write_text(json.dumps(raw, indent=1))
        leaks = {u for u in [h.get("url") for h in raw.get("hits") or []] + [r.get("link") for r in raw.get("results") or []] if isinstance(u, str)}
        paths = {urllib.parse.urlsplit(u).path for u in leaks} - {""}
        want = prod_expect(raw)
        print(f"prod: {raw.get('handle')} {slug} want {want}")
        return raw, want, {x for x in paths if len(x) >= 8 and x.strip("/").lower() != PROD_HANDLE}   # onlyfans.com/<handle> is typed on screen
    raw = stored(PROD_SLUG)[0]
    sse = "".join(f"event: {e}\ndata: {d}\n\n" for e, d in [("progress", "Searching Google, step 1 of 9"), ("progress", "Searching Google, step 6 of 9"),
                                                             ("result", json.dumps(raw)), ("done", "")])
    proxied, cache = [], {}

    def proxy(r):   # declared bypass: the page's same-origin API GETs → the production API, read-only
        u = urllib.parse.urlsplit(r.request.url)
        if r.request.method != "GET":
            return r.abort()
        if u.path == "/api/thumb" and not GSTATIC.match(urllib.parse.parse_qs(u.query).get("u", [""])[0]):
            return r.fulfill(status=404, body="")   # never ask production for a non-gstatic thumb
        key = u.path + ("?" + u.query if u.query else "")
        if key not in cache:   # memoized: each production GET once per run (the video's probe, its slots, the landing: same URLs; no 429s)
            proxied.append(u.path.split("/")[2])
            res = r.fetch(url=PROD + key, timeout=30000)
            hit = (res.status, {k: v for k, v in res.headers.items() if k.lower() in ("content-type", "cache-control")}, res.body())
            if res.status != 200 or "/api/media/" in key and key.count("/") == 3:   # only stable answers (the media index may still grow)
                return r.fulfill(status=hit[0], headers=hit[1], body=hit[2])
            cache[key] = hit
        st, hd, body = cache[key]
        r.fulfill(status=st, headers=hd, body=body)

    def run(label, opts, theater, slug):
        _, want, paths = stored(slug)
        ctx = ctx_new(b, **opts)
        ctx.add_init_script(SAY_STUB)
        if theater:
            ctx.add_init_script(IPHONE_FS)
        for pat in ("**/api/scan-result/**", "**/api/thumb?**", "**/api/media/**"):
            ctx.route(pat, proxy)
        held = []
        ctx.route("**/api/public-scan", lambda r: held.append(r))   # answered below, after the loading state is shot
        seen = []
        ext = guard(ctx, (base,), seen)
        pg = ctx.new_page()
        errs = []
        console(pg, errs)
        if theater:   # the shared link: ?r=<slug> → GET /api/scan-result
            pg.goto(f"{base}video/?r={slug}")
            pg.wait_for_function("() => document.querySelector('video').readyState >= 3", timeout=15000)
            pg.locator(".vo-fs").tap()
            pg.wait_for_function("() => document.documentElement.dataset.voFull === 'theater'", timeout=3000)
            pg.evaluate("() => { document.querySelector('video').currentTime = 6; }")   # never played here: her photos wait for 5 s of the take
        else:   # the name bar: the landing's scan, the loading state, then her result
            pg.goto(f"{base}video/")
            pg.wait_for_function("() => document.querySelector('video').readyState >= 3", timeout=15000)
            gen = pg.evaluate(IMGS)
            check(f"prod ({label}): generic before the submit: default photos (video/img/leak-*)", len(gen) == 13 and all(x[0].startswith("img/leak-") for x in gen), gen[:2])
            pg.fill("#vo-nb-in", PROD_HANDLE)
            pg.press("#vo-nb-in", "Enter")
            t0 = time.monotonic()
            while not held and time.monotonic() - t0 < 5:
                pg.wait_for_timeout(100)
            hold = cues["intro"][1] - 0.5   # = js holdAt(): the intro's "Building YOUR video…" beat
            if label == "1920":   # the take plays its intro, then holds on its Building beat while the scan runs
                try:
                    pg.wait_for_function("() => document.querySelector('video').paused", timeout=(hold + 6) * 1000)
                except Exception:
                    pass
            pg.wait_for_timeout(400)
            w = pg.evaluate("() => [document.documentElement.hasAttribute('data-vo-wait'), document.querySelector('.vo-wait').textContent, getComputedStyle(document.querySelector('.vo-wait')).display, document.querySelector('video').paused, +document.querySelector('video').currentTime.toFixed(2)]")
            pg.locator(".vo-stage").screenshot(path=str(out / f"prod-{label}-loading.png"))
            ok = bool(held) and w[:3] == [True, f"Scanning @{PROD_HANDLE}…", "block"]
            if label == "1920":
                ok = ok and w[3] and abs(w[4] - hold) < 0.6
            check(f"prod ({label}): submit '{PROD_HANDLE}' → one POST /api/public-scan, the wait pill"
                  + (f", the take held at ~{hold:g} s (the intro's Building beat)" if label == "1920" else "") + f" -> prod-{label}-loading.png", ok, (len(held), w))
            for r in held:
                r.fulfill(status=200, content_type="text/event-stream", body=sse)
        try:
            pg.wait_for_function("s => location.search === '?r=' + s || document.documentElement.dataset.voMode === 'named'", arg=slug, timeout=15000)
            pg.wait_for_function("""() => window.VideoOverlays.photos.kept.length > 0 && window.VideoOverlays.photos.settled && [...document.querySelectorAll('.rm-img, .vo-real')].every(i => i.complete)
                && [...document.querySelectorAll('.vo-own')].every(i => i.src.includes('/api/media/') && i.complete)""", timeout=30000)
        except Exception:
            pass
        pg.wait_for_timeout(600)
        st = pg.evaluate("() => [location.search, document.documentElement.dataset.voMode, document.documentElement.hasAttribute('data-vo-wait'), document.querySelector('video').currentSrc, document.querySelector('[data-vo=name]').textContent]")
        check(f"prod ({label}): her result → named ({st[4]!r}), ?r={slug}, no wait pill, jack.webm the source",
              st[0] == f"?r={slug}" and st[1] == "named" and not st[2] and st[3].endswith("/video/jack.webm"), st)
        if not theater and label == "1920":
            v = pg.evaluate("() => [document.querySelector('video').paused, document.querySelector('video').currentTime]")
            check(f"prod ({label}): the held take plays on after the result", v[0] is False, v)
        real = pg.evaluate(REAL)
        thumb = lambda xs, n: len(xs) >= n and all(x[0].startswith("/api/thumb?u=") and x[1] > 0 and BLUR(x[2]) == BLUR_PX for x in xs)
        check(f"prod img ({label}): Google: 3 real thumbs on the first row, loaded, blurred", len(real["g"]) == 3 and thumb(real["g"], 3), real["g"])
        check(f"prod img ({label}): Google Images: 6 real thumbs, loaded, blurred", len(real["grid"]) == 6 and thumb(real["grid"], 6), real["grid"][:2])
        check(f"prod img ({label}): cta-steps report: 9 of her people photos (rows + strip), loaded, blurred, all kept ones", len(real["rep"]) == 9 and thumb(real["rep"], 9)
              and all(x[0] in real["photos"]["kept"] for x in real["rep"]), real["rep"][:2])
        check(f"prod img ({label}): every .rm-img = a real /api/thumb one, loaded, blurred", thumb(real["all"], 13), [x for x in real["all"] if not x[0].startswith("/api/thumb")][:2])
        check(f"prod ({label}): Google rows = her real domains, count {want['count']!r}", real["grows"] == want["rows"][:4] and real["count"] == want["count"], (real["grows"], real["count"]))
        weak = [(c, x[0][-24:], x[2]) for c, xs in real["cards"] for x in xs if BLUR(x[2]) != BLUR_PX]
        n_leak = sum(len(xs) for _, xs in real["cards"])
        check(f"prod blur ({label}): every leak image on every card ({n_leak} on {', '.join(c for c, xs in real['cards'] if xs)}) blurred exactly {BLUR_PX}px",
              n_leak >= 22 and not weak, weak[:3] or sorted({x[2] for _, xs in real["cards"] for x in xs}))
        kept, dropped = real["photos"]["kept"], real["photos"]["dropped"]
        print(f"prod ({label}): people photos kept {len(kept)}, dropped {len(dropped)} (logos / banners / icons / dead)")
        own = real["own"]
        check(f"prod ({label}): after photos = her own (/api/media/{slug}/<n>.jpg), loaded, unblurred",
              len(own) == 6 and all(x[0].startswith(f"/api/media/{slug}/") and x[1] > 0 and x[2] == "none" for x in own), own[:2])
        live, rem, _ = cues["google-images"]
        for pid in ("google", "google-images", "x", "reddit", "mega"):   # per card: trigger + settled, live and removed
            l0, r0, _ = cues[pid]
            settled = min(r0 - 0.1, float(TAP or l0 + 0.6) + 1.0) if pid == "google-images" else l0 + min(1.3, r0 - l0 - 0.1)
            for state, t in (("trigger", l0 + 0.15), ("settled", settled), ("removed-trigger", r0 + 0.1), ("removed-settled", r0 + 2.0)):
                pg.evaluate(DRAW, t)
                pg.wait_for_timeout(300)
                (pg if theater else pg.locator(".vo-stage")).screenshot(path=str(out / f"prod-{label}-{pid}-{state}.png"))
        for name, t in (("cta-typed", cta + 3.05), ("google-live", cues["google"][0] + 1.3), ("google-images-live", min(rem - 0.1, float(TAP or live + 0.6) + 1.0)), ("google-images-removed", rem + 2.0),
                        ("x-live", cues["x"][0] + 1.0), ("report", cta + 8.6), ("end", cta + 9.65)):
            pg.evaluate(DRAW, t)
            pg.wait_for_timeout(500)
            f = out / f"prod-{label}-{name}.png"
            (pg if theater else pg.locator(".vo-stage")).screenshot(path=str(f))
            if name in ("cta-typed", "end"):
                s2 = pg.evaluate(STEPS)
                ok = s2["typed"] == PROD_HANDLE and s2["at"] == "@" + PROD_HANDLE if name == "cta-typed" else named_end(s2, st[4])
                check(f"prod end card ({label}): " + (f"typed onlyfans.com/{PROD_HANDLE} + '@{PROD_HANDLE}' (her handle, not {handle(DEMO)!r})" if name == "cta-typed"
                      else f"ends on the contact row only (no {st[4]!r})") + f" -> {f.name}", ok, s2 and (s2["typed"], s2["at"], s2["shown"]))
            if name == "report":
                s2 = pg.evaluate(STEPS)
                tabs = rep_tabs = [int(re.sub(r"\D", "", x)) for x in s2["tabs"]]
                rows = [r for r, v in zip(s2["rows"], s2["rowon"]) if v]
                check(f"prod ({label}): report = hers: '@{PROD_HANDLE}', Images = her kept photos ({len(kept)}), Links / Sites {tabs[0]} / {tabs[2]}, her rows {rows[:3]}…, no *.example, "
                      f"'+ {tabs[0] - len(rows)} more' -> {f.name}", s2["at"] == "@" + PROD_HANDLE and tabs[1] == len(kept) and 0 < len(rows) <= 5
                      and not any(r.endswith(".example") for r in rows) and s2["more"] == f"+ {tabs[0] - len(rows)} more in the full report", (tabs, s2["at"], s2["more"], rows))
        text = pg.evaluate("() => document.body.innerText + ' ' + document.querySelector('.vo').textContent")
        bad = [x for x in paths if x in text][:3] + re.findall(r"https?://\S+", text)[:3]
        check(f"prod ({label}): no leak URL in the DOM text ({len(paths)} paths checked, no http(s)://)", not bad, bad)
        if label == "1920":   # the landing report on the same result, same proxy: it must drop the same thumbs
            lctx = ctx_new(b, **opts)   # own context: the landing's own requests (its Google Fonts css: aborted, declared) are not the video's
            for pat in ("**/api/scan-result/**", "**/api/thumb?**", "**/api/media/**"):
                lctx.route(pat, proxy)
            lext = guard(lctx, (base,))
            lp = lctx.new_page()
            lp.goto(f"{base}?r={slug}")
            try:   # its probes settled: the Images tab says what is left
                lp.wait_for_function("k => { const n = document.querySelector('#tab-report-images .live-tab-n'); return n && +n.textContent === k; }", arg=len(kept), timeout=20000)
            except Exception:
                pass
            lp.wait_for_timeout(1500)
            n_l, tiles = lp.evaluate(LANDING)
            lp.locator("#tab-report-images").first.click()
            lp.wait_for_timeout(1200)
            card = lp.locator(".live-card, .hero-card, #hero-card").first
            (card if card.count() else lp).screenshot(path=str(out / "prod-landing-report-images.png"))
            ks = set(kept)
            check(f"prod logos: the video cards and the landing report (?r={slug}) drop the same thumbs: landing Images {n_l} == video kept {len(kept)}"
                  f" (of {len(kept) + len(dropped)}, {len(dropped)} dropped), all {len(tiles)} landing tiles in the video's kept set -> prod-landing-report-images.png",
                  n_l == len(kept) and tiles and all(t in ks for t in tiles) and not ks & set(dropped), (n_l, len(kept), [t[-30:] for t in tiles if t not in ks][:3]))
            lt = landing_tabs(lp)
            check(f"prod ({label}): end-card report counts == the landing report's (?r={slug}): video {rep_tabs} == landing {lt}", rep_tabs == lt, (rep_tabs, lt))
            (out / "prod-photos.json").write_text(json.dumps({"slug": slug, "kept": kept, "dropped": dropped, "landing_count": n_l, "landing_tiles": tiles}, indent=1))
            print(f"prod logos: landing page requests outside 127.0.0.1 aborted (declared, the landing's own, not the video's): {sorted(set(lext))}")
            lctx.close()
        check(f"prod ({label}): every request to 127.0.0.1 (production only through the declared proxy), no console error",
              not ext and all(u.startswith(base) for u in seen) and not errs, (ext[:3], errs[:3]))
        ctx.close()
    TAP = re.search(r'data-prefab="google-images"[^>]*data-cue-tap="([\d.]+)"', (ROOT / "site/video/index.html").read_text(encoding="utf-8"))
    TAP = TAP and TAP[1]
    run("1920", dict(viewport={"width": 1920, "height": 1080}), False, PROD_SLUG)
    run("phone", VIEWPORTS["phone"], False, PROD_SLUG)
    run("theater", VIEWPORTS["phone"], True, PROD_SLUG2)
    print(f"prod: proxied read-only GETs to production (memoized): " + ", ".join(f"{k} x{proxied.count(k)}" for k in sorted(set(proxied))))


# ---------- hers: her result in every card, the intro + end card type HER handle, the end card = her report (?r=, the last scan, the pip) ----------
HERS_TS = (1, 3, 3.5, 6, 9.5, 12, 16.5, 19, 23, 26, 31, 36, 37.85, 40, 47)   # 1 = the "for <name>" pill (no shot); 3.5 / 37.85 = her handle typed in full
HERS_END = (3, 3.5, 6, 9.5, 36, 37.85, 40, 47)
PIP_TS = (3, 6, 9.5, 36, 40, 47)   # the pip iframe's shots   # her handle / her end-card report checks (chk_end)
HERS_CARD = {12: "google", 16.5: "google-images", 19: "x", 23: "reddit", 26: "mega", 31: "sites"}
PERSONA_RE = re.compile(r"JakaBasej|jakabasej\.com|Your name|Orla|Brennick|brennick")   # case-sensitive: the hero copy says "in your name"
HERS_JS = """t => { const v = document.querySelector('video'); v.pause(); window.VideoOverlays.draw(t);
  const on = [...document.querySelectorAll('.vo-pf')].filter(e => !e.hasAttribute('data-off')), c = document.querySelector('.vo-cta');
  const s = c.querySelector('.vo-steps').getBoundingClientRect(), e = c.querySelector('.vo-end').getBoundingClientRect();
  const ix = Math.max(0, Math.min(s.right, e.right) - Math.max(s.left, e.left)) * Math.max(0, Math.min(s.bottom, e.bottom) - Math.max(s.top, e.top));
  return {on: on.map(e => e.dataset.prefab), text: on.map(e => e.innerText).join(' | '), over: document.querySelector('.vo-over').innerText,
    imgs: on.flatMap(e => [...e.querySelectorAll('img.rm-img')].map(i => [i.getAttribute('src'), i.naturalWidth])),
    sites: [...document.querySelectorAll('.vo-sites-l b')].map(b => b.textContent), slots: [...document.querySelectorAll('[data-vo]')].map(e => e.textContent).join(' | '),
    cta: c.innerText, contacts: [...c.querySelectorAll('.vo-end-c > span')].map(x => x.textContent), eo: +getComputedStyle(c.querySelector('.vo-end')).opacity,
    cov: +(ix / (s.width * s.height)).toFixed(3), mode: document.documentElement.dataset.voMode, search: location.search, ...(() => {
      const p = on.find(e => e.querySelector('.vo-steps')), q = x => p && p.querySelector(x), im = i => [i.getAttribute('src'), i.naturalWidth, getComputedStyle(i).filter];
      const rows = p ? [...p.querySelectorAll('.vo-row')].filter(r => r.style.display !== 'none') : [], all = document.getElementById('vo').cloneNode(true);
      all.querySelectorAll('.vo-end-c').forEach(x => x.remove());   // the contact footer's Telegram @jakabasej is contact info
      const n = x => (x.toLowerCase().match(/jakabasej/g) || []).length, foot = on.includes(c) ? c.querySelector('.vo-end-c').innerText : '';
      return {typed: q('.vo-mi-t') ? q('.vo-mi-t').textContent : null, at: q('.vo-sc-scan .vo-at') ? q('.vo-sc-scan .vo-at').textContent : null,
        tabs: p ? [...p.querySelectorAll('.vo-tabs2 b')].map(b => +b.textContent) : [], rows: rows.map(r => [r.querySelector('.vo-dom').textContent, r.querySelector('.vo-ttl').textContent]),
        more: q('.vo-more') ? q('.vo-more').textContent : null, real: p ? [...p.querySelectorAll('.vo-rows .vo-real, .vo-strip .vo-real')].map(im) : [],
        kept: window.VideoOverlays.photos.kept, jkOn: n(on.map(e => e.innerText).join(' ')) - n(foot), jkDom: n(all.textContent)}; })()}; }"""
# the landing report's Links / Images / Sites tab counts once settled (E.gallery: "24+" / "…" until every image is checked)
LANDING_TABS = """() => ['links', 'images', 'sites'].map(k => { const n = document.querySelector('#tab-report-' + k + ' .live-tab-n'); return n ? n.textContent.trim() : null; })"""


def landing_tabs(pg, timeout=60000):
    """the landing report's tab counts [Links, Images, Sites] once its image probes settled (None if never)"""
    try:
        pg.wait_for_function("() => ['links', 'images', 'sites'].every(k => /^\\d+$/.test((document.querySelector('#tab-report-' + k + ' .live-tab-n') || {}).textContent || ''))", timeout=timeout)
    except Exception:
        pass
    pg.wait_for_timeout(1500)
    return [int(x) if x and x.isdigit() else x for x in pg.evaluate(LANDING_TABS)]


def hers_expect(raw):
    """her result's fields as the cards may show them: hosts (most links first, = js report().hosts), titles, counts, thumbs"""
    rows, n, seen = [], {}, set()
    agg = {h.strip().lower().removeprefix("www.") for m in raw.get("mega") or [] if isinstance(m, dict) for h in (m.get("host"), m.get("via")) if isinstance(h, str) and h.strip()}
    under = lambda h, a: h == a or h.endswith("." + a)   # = js/scan-engine.js withoutAggregators(): mega[] share hosts never show
    def add(u, d, title):
        if not isinstance(u, str) or not re.fullmatch(r"https?://[^\s\"'<>\\]+", u, re.I) or u in seen:
            return
        x = urllib.parse.urlsplit(u)
        d = (d if isinstance(d, str) else "").strip().lower().removeprefix("www.") or (x.hostname or "").removeprefix("www.")
        if not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", d) or any(under(h, a) for h in (d, (x.hostname or "").lower().removeprefix("www.")) for a in agg):
            return
        seen.add(u)
        n[d] = n.get(d, 0) + 1
        rows.append((d, title if isinstance(title, str) else None))
    for h in (raw.get("hits") or [])[:1000]:
        if h:
            add(h.get("url"), h.get("domain"), h.get("title"))
    for r in (raw.get("results") or [])[:200]:
        if r:
            add(r.get("link"), r.get("domain"), r.get("title"))
    hosts = sorted(n, key=lambda d: -n[d])   # stable: first seen on a tie
    g, megas = raw.get("google_total"), [m for m in raw.get("mega") or [] if isinstance(m, dict)]   # any of her folders (js/removals.js picks one)
    counts = ([f"About {g:,} results"] if isinstance(g, int) and g > 0 else []) + [f"{n} {u}" for mg in megas for k, us in (("images", ("images", "files")), ("videos", ("videos", "files"))) if isinstance(mg.get(k), int) and mg[k] > 0
                                                                            for n in {f"{mg[k]}", f"{mg[k]:,}"} for u in us]
    thumbs = {u for u in (raw.get("images") or []) if isinstance(u, str)} | {r.get("thumb") for r in raw.get("results") or [] if r and isinstance(r.get("thumb"), str)}
    pr = raw.get("profile") or {}
    return {"hosts": hosts, "titles": [t.strip() for _, t in rows if t and len(t.strip()) >= 12], "counts": counts, "thumbs": thumbs,
            "name": pr.get("display_name") or raw.get("handle"), "handle": raw.get("handle")}


def hers(b, base, out, raw_file, no_prod):
    """her result everywhere: ?r=PROD_SLUG and the last scan (the landing's in-page scan → /video/ with no query, and the landing's
    mini player iframe ?pip=1 loaded BEFORE the scan → turns hers on the storage event), 1920 + phone 390x844 + iPhone theater"""
    if raw_file:
        raw = json.loads(pathlib.Path(raw_file).read_text(encoding="utf-8"))
    else:   # read-only GET of the stored result (no new scan)
        raw = json.load(urllib.request.urlopen(f"{PROD}/api/scan-result/{PROD_SLUG}", timeout=30))
    (out / f"hers-scan-result-{PROD_SLUG}.json").write_text(json.dumps(raw, indent=1))
    X = hers_expect(raw)
    print(f"hers: {X['handle']} {PROD_SLUG}: {len(X['hosts'])} hosts, top {X['hosts'][:4]}, counts {X['counts']}, {len(X['thumbs'])} thumbs, "
          f"thumbs/media {'404 (no production, declared)' if no_prod else 'proxied read-only to production'}")
    body = json.dumps(raw).encode()
    sse = "".join(f"event: {e}\ndata: {d}\n\n" for e, d in [("progress", "Searching Google, step 1 of 9"), ("result", json.dumps(raw)), ("done", "")])
    memo, proxied = {}, []

    def api(r):   # declared bypass, wire boundary: scan-result = her saved result; thumb / media → production read-only GET (memoized), or 404
        u = urllib.parse.urlsplit(r.request.url)
        if r.request.method != "GET":
            return r.abort()
        if u.path.startswith("/api/scan-result/"):
            return r.fulfill(body=body, content_type="application/json") if u.path.endswith("/" + PROD_SLUG) else r.fulfill(status=404, body="{}")
        if no_prod or u.path == "/api/thumb" and not GSTATIC.match(urllib.parse.parse_qs(u.query).get("u", [""])[0]):
            return r.fulfill(status=404, body="")
        key = u.path + ("?" + u.query if u.query else "")
        if key not in memo:
            proxied.append(u.path.split("/")[2])
            res = r.fetch(url=PROD + key, timeout=30000)
            memo[key] = (res.status, {k: v for k, v in res.headers.items() if k.lower() in ("content-type", "cache-control")}, res.body())
        st, hd, bd = memo[key]
        r.fulfill(status=st, headers=hd, body=bd)

    def context(opts, theater):
        ctx = ctx_new(b, **opts)
        if theater:
            ctx.add_init_script(IPHONE_FS)
        for pat in ("**/api/scan-result/**", "**/api/thumb?**", "**/api/media/**"):
            ctx.route(pat, api)
        ctx.route("**/api/public-scan", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=sse))   # declared: her saved result as the SSE
        seen = []
        return ctx, guard(ctx, (base,), seen), seen

    def settle(pg):
        try:
            pg.wait_for_function("() => document.documentElement.dataset.voMode === 'named'", timeout=10000)
            if not no_prod:
                pg.wait_for_function("() => window.VideoOverlays.photos.kept.length > 0 && window.VideoOverlays.photos.settled && [...document.querySelectorAll('.rm-img')].every(i => i.complete)", timeout=90000)
        except Exception:
            pass
        pg.wait_for_timeout(500)

    def mine(text, imgs):   # the fields of her result in this text / these images
        f = [h for h in X["hosts"] if h in text][:3] + [c for c in X["counts"] if c in text][:2] + [t[:30] for t in X["titles"] if t in text][:1]
        th = [s for s, w in imgs if w > 0 and s.startswith("/api/thumb?u=") and urllib.parse.parse_qs(urllib.parse.urlsplit(s).query).get("u", [""])[0] in X["thumbs"]]
        return f + ([f"{len(th)} of her thumbs"] if th else [])

    ends = {}

    def chk_end(label, t, s, shot):   # her handle typed (intro + end card), her report at the settled end, no "jakabasej" outside the contact footer
        hh, ok, msg = X["handle"], s["jkOn"] == 0 and s["jkDom"] == 0, f"hers handle ({label}) t={t:g}: "
        card = "intro" if t < 10 else "cta-steps"
        ok = ok and s["on"] == [card]
        if t in (3, 36):
            ok, msg = ok and hh.startswith(s["typed"] or "") and (t == 36 or 0 < len(s["typed"]) < len(hh)), msg + f"{card} typing a prefix of onlyfans.com/{hh} ({s['typed']!r})"
        elif t in (3.5, 37.85):
            ok, msg = ok and s["typed"] == hh, msg + f"{card} typed onlyfans.com/{hh} in full"
        elif t in (6, 40):
            ok, msg = ok and s["at"] == "@" + hh, msg + f"{card} scan card '@{hh}' ({s['at']!r})"
        elif t == 9.5:
            ok, msg = ok and "Building YOUR video" in s["text"], msg + "'Building YOUR video…' over her intro"
        if t == 47:
            hosts, rows = set(X["hosts"]), [d for d, _ in s["rows"]]
            ok = (ok and s["at"] == "@" + hh and len(s["tabs"]) == 3 and s["tabs"][1] == len(s["kept"]) and 0 < len(rows) <= 5 and all(d in hosts for d in rows)
                  and all(t2 and not re.search(r"https?://|www\.", t2) for _, t2 in s["rows"]) and s["more"] == f"+ {s['tabs'][0] - len(rows)} more in the full report"
                  and len(s["real"]) == 9 and all(x[1] > 0 and x[0] in s["kept"] and BLUR(x[2]) == BLUR_PX for x in s["real"])
                  and s["eo"] > .9 and s["contacts"] == CONTACTS and s["cov"] <= .20 and "clear for" not in s["cta"].lower())
            msg = (f"hers end ({label}) t=47: her report '@{hh}' Links / Images / Sites {s['tabs']} (Images = her kept photos), her rows {rows[:3]}…, none *.example, "
                   f"{s['more']!r}, {len(s['real'])} of her people photos blurred exactly {BLUR_PX}px, contact footer {s['cov']:.1%} of the phone (<= 20 %)")
        check(msg + f", no 'jakabasej' outside the contact footer (on screen {s['jkOn']}, DOM {s['jkDom']}) -> {shot}", ok,
              {k: s[k] for k in ("on", "typed", "at", "tabs", "rows", "more", "jkOn", "jkDom", "cov", "eo")} | {"real": s["real"][:2]})

    def sweep(pg, label, theater):
        for t in HERS_TS:
            s = pg.evaluate(HERS_JS, t)
            pg.wait_for_timeout(350)
            if t != 1:
                f = out / f"hers-{label}-t{t:g}.png"
                (pg if theater else pg.locator(".vo-stage")).screenshot(path=str(f))
            bad = PERSONA_RE.findall(s["over"]) + PERSONA_RE.findall(s["slots"])
            check(f"hers ({label}) t={t:g}: named, no placeholder persona text (JakaBasej / Your name / Orla Brennick) on screen or in a slot",
                  s["mode"] == "named" and not bad, (s["mode"], bad[:3]))
            if t == 1:
                check(f"hers ({label}) t=1: the 'for {X['name']}' pill (her result's name)", "for" in s["text"] and X["name"] in s["text"], s["text"][:80])
            hh = X["handle"]
            if t in HERS_END:
                ends[label] = s
                chk_end(label, t, s, f.name)
            if t in HERS_CARD:
                pid, got = HERS_CARD[t], mine(s["text"], s["imgs"])
                check(f"hers ({label}) t={t:g}: {pid} shows her result ({', '.join(got[:4]) or 'nothing'}) -> {f.name}", s["on"] == [pid] and len(got) >= 1, (s["on"], s["text"][:200]))
            if t == 31:
                k = min(12, len(X["hosts"]))
                check(f"hers ({label}) t=31: the 10,000+ wall = her {k} top sites first (most links), then his whiteboard names",
                      s["sites"][:k] == X["hosts"][:k] and len(s["sites"]) == 12, s["sites"])
        txt = pg.evaluate("() => document.body.innerText")
        check(f"hers ({label}): no URL in the page text", not re.findall(r"https?://\S+", txt), re.findall(r"https?://\S+", txt)[:2])

    for label, opts, theater in (("1920", dict(viewport={"width": 1920, "height": 1080}), False), ("phone", VIEWPORTS["phone"], False), ("theater", VIEWPORTS["phone"], True)):
        # a: the shared link ?r=<slug>
        ctx, ext, seen = context(opts, theater)
        pg = ctx.new_page()
        errs, tq = [], []
        console(pg, errs)
        pg.on("request", lambda r: "/api/thumb?" in r.url and tq.append(time.monotonic()))
        t0 = time.monotonic()
        pg.goto(f"{base}video/?r={PROD_SLUG}")
        pg.wait_for_function("() => document.documentElement.dataset.voMode === 'named'", timeout=10000)
        pg.wait_for_timeout(max(0, (t0 + 5.5 - time.monotonic()) * 1000))
        early = [x for x in tq if x - t0 < 5.5]   # the probes before PROBE_MAX (6 s: then the kept ones show, local routing = no HTTP cache)
        burst = max((sum(1 for y in early if 0 <= y - x < 1) for x in early), default=0)
        settle(pg)
        check(f"hers paced (r-{label}): the video's /api/thumb probes <= 3 per 1 s window before 5.5 s ({burst}, {len(early)} in all; /api/thumb refills 2/s: a burst = 429s = photos dropped)",
              0 < burst <= 3, (burst, len(early)))
        if theater:
            pg.locator(".vo-fs").tap()
            pg.wait_for_function("() => document.documentElement.dataset.voFull === 'theater'", timeout=3000)
        sweep(pg, f"r-{label}", theater)
        check(f"hers (r-{label}): every request to 127.0.0.1, no console error", not ext and not errs, (ext[:3], errs[:3]))
        lpg = ctx.new_page()   # the landing report on the same result (?r=, same proxy; its own font requests aborted, declared)
        lpg.goto(f"{base}?r={PROD_SLUG}&pip=0")
        lt = landing_tabs(lpg)
        lpg.locator(".live-card, #hero-card, .hero-card").first.screenshot(path=str(out / f"hers-r-{label}-landing-report.png")) if lpg.locator(".live-card, #hero-card, .hero-card").count() else lpg.screenshot(path=str(out / f"hers-r-{label}-landing-report.png"))
        vt = ends.get(f"r-{label}", {}).get("tabs")
        check(f"hers counts (r-{label}): end-card Links / Images / Sites {vt} == the landing report's {lt} (?r={PROD_SLUG}) -> hers-r-{label}-t47.png, hers-r-{label}-landing-report.png", vt == lt and bool(lt), (vt, lt))
        ctx.close()
        # b: the last scan: the landing's in-page scan (her saved result as the SSE), then /video/ opened directly, no query
        ctx, ext, seen = context(opts, theater)
        lp = ctx.new_page()
        lp.goto(f"{base}?pip=0")
        lp.fill("#scan .scan-handle", PROD_HANDLE)
        lp.locator("#scan button[type=submit]").click()
        try:
            lp.wait_for_function("s => (JSON.parse(localStorage.getItem('leakscan.last') || 'null') || {}).slug === s", arg=PROD_SLUG, timeout=15000)
        except Exception:
            pass
        last = lp.evaluate("() => [location.search, localStorage.getItem('leakscan.last')]")
        check(f"hers (last-{label}): the landing's scan stored leakscan.last = {PROD_SLUG}", PROD_SLUG in (last[1] or ""), last)
        lt = landing_tabs(lp)
        lp.close()
        pg = ctx.new_page()
        errs = []
        console(pg, errs)
        pg.goto(f"{base}video/")
        settle(pg)
        if theater:
            pg.locator(".vo-fs").tap()
            pg.wait_for_function("() => document.documentElement.dataset.voFull === 'theater'", timeout=3000)
        check(f"hers (last-{label}): /video/ with no query plays hers", pg.evaluate("() => location.search") == "" and pg.evaluate("() => document.documentElement.dataset.voMode") == "named")
        sweep(pg, f"last-{label}", theater)
        vt = ends.get(f"last-{label}", {}).get("tabs")
        check(f"hers counts (last-{label}): end-card Links / Images / Sites {vt} == the landing report's {lt} (the landing's own scan)", vt == lt and bool(lt), (vt, lt))
        check(f"hers (last-{label}): video requests all to 127.0.0.1 (landing fonts etc. aborted, declared), no console error on /video/",
              all(u.startswith(base) for u in seen if "/video/" in u or "/api/" in u) and not errs, errs[:3])
        ctx.close()
    # c: the landing's mini player (?pip=1), its iframe loaded BEFORE her scan: the scan → storage event → hers, in place; then her
    # intro + end card inside the iframe, its report counts vs the landing's own report around it (1920 + phone 390x844)
    for label, opts in (("1920", dict(viewport={"width": 1920, "height": 1080})), ("phone", VIEWPORTS["phone"])):
        ctx, ext, seen = context(opts, False)
        lp = ctx.new_page()
        lp.goto(f"{base}?pip=1")
        lp.mouse.wheel(0, 200)   # the first scroll mounts the player
        lp.wait_for_timeout(300)
        lp.mouse.wheel(0, -200)
        fr = None
        for i in range(60):
            if label == "phone" and i % 8 == 4:   # phone: the docked player hangs off the hero card, below the fold: bring it near the screen
                lp.evaluate("() => { const f = document.querySelector('.pip, [class*=pip]'); (f || document.querySelector('#scan')).scrollIntoView({block: 'center'}); }")
            fr = next((f for f in lp.frames if "/video/" in f.url), None)
            if fr:
                break
            lp.wait_for_timeout(250)
        before = None
        if fr:
            fr.wait_for_load_state()
            fr.wait_for_function("() => window.VideoOverlays", timeout=10000)
            before = fr.evaluate("() => document.documentElement.dataset.voMode")
        check(f"hers (pip-{label}): the landing's mini player iframe loaded before the scan, generic ({fr and fr.url})", fr is not None and before == "generic", (fr and fr.url, before))
        lp.fill("#scan .scan-handle", PROD_HANDLE)
        lp.locator("#scan button[type=submit]").click()
        s = None
        if fr:
            try:
                fr.wait_for_function("() => document.documentElement.dataset.voMode === 'named'", timeout=15000)
                if not no_prod:
                    fr.wait_for_function("() => window.VideoOverlays.photos.kept.length > 0 && window.VideoOverlays.photos.settled && [...document.querySelectorAll('.rm-img')].every(i => i.complete)", timeout=90000)
            except Exception:
                pass
            lp.wait_for_timeout(800)
            s = fr.evaluate(HERS_JS, 31)
            fr.evaluate(HERS_JS, 12)
            lp.wait_for_timeout(400)
        lp.screenshot(path=str(out / f"hers-pip-{label}-t12.png"))
        k = min(12, len(X["hosts"]))
        check(f"hers (pip-{label}): after the landing scan the mini player turns hers in place (iframe {fr and urllib.parse.urlsplit(fr.url).query or 'no query'}): named, her sites wall -> hers-pip-{label}-t12.png",
              s is not None and s["mode"] == "named" and s["sites"][:k] == X["hosts"][:k], s and (s["mode"], s["sites"][:3]))
        lt = landing_tabs(lp)
        ifr = lp.locator("iframe[src*='video/']").first
        for t in PIP_TS if fr else ():
            s = fr.evaluate(HERS_JS, t)
            lp.wait_for_timeout(350)
            f = out / f"hers-pip-{label}-t{t:g}.png"
            (ifr if ifr.count() else lp).screenshot(path=str(f))
            if t == 47:
                lp.screenshot(path=str(out / f"hers-pip-{label}-t47-page.png"))   # the mini player's end card over the landing's own report (Jack's view)
                ends[f"pip-{label}"] = s
            chk_end(f"pip-{label}", t, s, f.name)
        vt = ends.get(f"pip-{label}", {}).get("tabs")
        check(f"hers counts (pip-{label}): the mini player's end-card Links / Images / Sites {vt} == the landing report's around it {lt} -> hers-pip-{label}-t47-page.png", vt == lt and bool(lt), (vt, lt))
        ctx.close()
    print(f"hers: production GETs (read-only, memoized): " + (", ".join(f"{k} x{proxied.count(k)}" for k in sorted(set(proxied))) or "none"))


def play(pg, until):
    """click the page (not the <video>), Space = play: the user gesture; wait until currentTime > until (or ended)"""
    pg.mouse.click(5, 5)
    pg.keyboard.press("Space")
    pg.wait_for_function(f"() => document.querySelector('video').currentTime > {until} || document.querySelector('video').ended", timeout=10000)


def speech(b, base, out, name, cues):
    """no AI overvoice: the page never calls speechSynthesis.speak (named or generic); the "for <name>" pill stays"""
    say = cues["say"]
    for label, query, t, until in (("start", f"name={name}", 0, 1.0), ("end", f"name={name}", say - 0.6, say + 0.6)):
        ctx = ctx_new(b, viewport={"width": 1440, "height": 900})
        ctx.add_init_script(SAY_STUB)
        pg = ctx.new_page()
        goto(pg, base, query, t)
        play(pg, until)
        pg.wait_for_timeout(100)
        pill = pg.evaluate("() => { const e = document.querySelector('.vo-for'); return [e.hasAttribute('data-off'), e.innerText.replace(/\\s+/g, ' ').trim()]; }")
        pg.screenshot(path=str(out / f"desktop-named-{label}-{name}.png"))
        if label == "start":
            pg.wait_for_function("() => document.querySelector('video').currentTime > 2.4", timeout=10000)
        else:
            pg.wait_for_timeout(400)
        said, utt, vol = pg.evaluate("() => [__said, __utt, document.querySelector('video').volume]")
        span = "0 .. 2.4 s" if label == "start" else f"data-cue-say {say} ± 0.6"
        check(f"no overvoice ?name={name} ({label}, played {span}): speechSynthesis.speak called 0 times, 0 utterances, volume 1",
              said == [] and utt == 0 and vol == 1, (said, utt, vol))
        if label == "start":
            check(f"pill ?name={name} (start, 1.0 s): 'for {name}' pill on screen", not pill[0] and pill[1].endswith(f"for {name}"), pill)
        else:   # data-cue-say = data-cue-cta: the named flow carries the name, no pill
            vis = [v[0] for v in pg.evaluate(VISIBLE)]
            check(f"named flow: ?name={name} ({label}): cta-steps on screen at data-cue-say, no pill", vis == ["cta-steps"] and pill[0], (vis, pill))
        ctx.close()
    # generic: never spoken, no pill, the end card instead
    ctx = ctx_new(b, viewport={"width": 1440, "height": 900})
    ctx.add_init_script(SAY_STUB)
    pg = ctx.new_page()
    goto(pg, base, "", say - 0.6)
    play(pg, say + 0.6)
    got = pg.evaluate("() => [__said, document.querySelector('.vo-for').hasAttribute('data-off'), (document.querySelector('.vo-cta')?.hasAttribute('data-off') ?? 'missing')]")
    check("no overvoice, generic (no ?name, no scan): speak called 0 times, no pill, end card shown", got == [[], True, False], got)
    ctx.close()
    # data-cue-say past the end of the take (declared: moved to 99): the video's `ended` brings the name / the end card
    for query in (f"name={name}", ""):
        ctx = ctx_new(b, viewport={"width": 1440, "height": 900})
        ctx.add_init_script(SAY_STUB)
        pg = ctx.new_page()
        goto(pg, base, query, round(END - 0.8, 2))
        pg.evaluate("() => document.querySelector('.vo-stage').setAttribute('data-cue-say', '99')")
        play(pg, 99)
        pg.wait_for_timeout(300)
        got = pg.evaluate("() => [__said.map(s => s[0]), document.querySelector('.vo-for').hasAttribute('data-off'), (document.querySelector('.vo-cta')?.hasAttribute('data-off') ?? 'missing')]")
        check(f"{'named flow: ' if query else ''}ended before data-cue-say ({'named' if query else 'generic'}): {'the named flow' if query else 'end card'} at the end, speak called 0 times", got == [[], True, False], got)
        ctx.close()


def sfx(b, base, cues):
    g = cues["google"]
    for label, query, t, until, want in (("pop at live", "", g[0] - 0.4, g[0] + 0.3, [["osc", g[0]]]),
                                         ("whoosh + thud at removed", "", g[1] - 0.3, g[1] + 0.4, [["noise", g[1]], ["osc", g[1]]]),
                                         ("?sfx=0: silent", "sfx=0", g[1] - 0.3, g[1] + 0.4, [])):
        ctx = ctx_new(b, viewport={"width": 1440, "height": 900})
        ctx.add_init_script(SFX_STUB)
        pg = ctx.new_page()
        goto(pg, base, query, t)
        before = pg.evaluate("() => [__actx, __sfx.length]")
        play(pg, until)
        pg.keyboard.press("Space")
        got, n = pg.evaluate("() => [__sfx, __actx]")
        ok = before == [0, 0] and len(got) == len(want) and all(k == w[0] and w[1] <= v < w[1] + 0.2 for (k, v), w in zip(got, want))
        check(f"sfx: {label} (no AudioContext before the play gesture; logged {got}, {n} context)", ok and n == (0 if not want else 1), (before, got, n))
        ctx.close()


def cta_steps(pg, base, out, cta, name_q):
    """the generic end card's 10 s take, on the 1920x1080 page (pg); returns the handle the hero typed in full"""
    shot = lambda ph: pg.locator(".vo-stage").screenshot(path=str(out / f"frame-1920-generic-cta-{ph}.png"))
    goto(pg, base, "", round(cta + 0.3, 2))
    shot("1-hero")
    s = pg.evaluate(STEPS)
    check("cta-steps: cta + 0.3 = the hero in the phone (logo, the site's h1, empty field, camera at rest) -> frame-1920-generic-cta-1-hero.png",
          s and s["so"][0] > .9 and s["so"][1:] == [0, 0] and s["h1"] == HERO_H1 and s["logo"] and s["typed"] == "" and s["cz"][0] < 1, s)
    goto(pg, base, "", round(cta + 3.05, 2))
    shot("3-typed")
    s = pg.evaluate(STEPS)
    full = s["typed"] if s else ""
    check(f"cta-steps: typed at cta + 3.05: the onlyfans.com/ field holds handle(DEMO) {handle(DEMO)!r} in full, camera zoomed on it -> frame-1920-generic-cta-3-typed.png",
          s and s["so"][0] > .9 and s["typed"] == handle(DEMO) and s["cz"][0] >= 2.2, s)
    goto(pg, base, "", round(cta + 2.2, 2))
    s0 = pg.evaluate(STEPS)
    check("cta-steps: cta + 2.2 = the camera zoomed onto the field (scale >= 2.2), typing a proper prefix of the handle",
          s0 and s0["so"][0] > .9 and s0["cz"][0] >= 2.2 and 0 < len(s0["typed"]) < len(full) and full.startswith(s0["typed"]), (s0, full))
    ph = dict(PHASES)
    for name in ("2-zoom", "4-press", "5-scanning", "6-report", "7-flip"):   # past the take's end: the pure draw(t) (declared)
        pg.evaluate(DRAW, cta + ph[name])
        shot(name)
        s = pg.evaluate(STEPS)
        if name == "4-press":
            check("cta-steps: cta + 3.75 'Scan now' pressed, the camera pulled back to the form -> frame-1920-generic-cta-4-press.png",
                  s and s["so"][0] > .9 and s["btn"] == "Scan now" and s["press"] > .5 and s["cz"][0] < 1.2, s)
        if name == "5-scanning":
            check(f"cta-steps: cta + 5.6 = the scan card (hero / report off): '@{full}', bar 10-90 %, 'Searching <place>, step N of 9…' -> frame-1920-generic-cta-5-scanning.png",
                  s and s["so"] == [0, 1, 0] and s["at"] == "@" + full and .1 < s["bar"] < .9 and PROGRESS.fullmatch(s["ms"] or ""), s)
        if name == "6-report":
            check(f"cta-steps: cta + 8.3 = the report: '{LEAKS} links found', tabs Links 87 / Images 12 / Sites 31, 5 *.example rows, '+ 82 more' -> frame-1920-generic-cta-6-report.png",
                  s and s["so"][2] > .9 and s["so"][:2] == [0, 0] and s["count"] == f"{LEAKS} links found" and s["tabs"] == ["Links 87", "Images 12", "Sites 31"]
                  and len(s["rows"]) == 5 and all(r.endswith(".example") for r in s["rows"]) and s["more"] == "+ 82 more in the full report", s)
        if name == "7-flip":
            check(f"cta-steps: cta + 9.65 = 'Rewatch this video with YOUR content' + the name flip -> frame-1920-generic-cta-7-flip.png",
                  s and s["so"][2] > .9 and s["eo"] > .9 and s["end"] == "Rewatch this video with YOUR content" and s["mini"], s)
    walk = []
    for dt in (4.5, 5.0, 5.5, 6.0, 6.4, 7.4):
        pg.evaluate(DRAW, cta + dt)
        s = pg.evaluate(STEPS)
        walk.append((s["ms"], s["count"]) if s else (None, ""))
    m = [PROGRESS.fullmatch(w[0] or "") for w in walk[:-1]]
    roll = re.fullmatch(r"(\d+) links found", walk[-1][1])
    check(f"cta-steps: the scan walks Google → … → Mega, step N rising; at + 7.4 'N links found' rolling to {LEAKS}",
          all(m) and len({x[1] for x in m}) >= 4 and m[0][1] == "Google" and m[-1][1] == "Mega" and [int(x[2]) for x in m] == sorted(int(x[2]) for x in m)
          and roll and 0 < int(roll[1]) < LEAKS, walk)
    # past the end: the post-roll clock keeps the loop going (the real take ends ~3.5 s after the cue)
    pg.goto(f"{base}video/?t={END - 0.6:g}")
    pg.wait_for_function(SEEKED, arg=round(END - 0.6, 3), timeout=15000)
    play(pg, END - 0.1)
    pg.wait_for_function("() => document.querySelector('video').ended", timeout=8000)
    try:
        pg.wait_for_function("() => { const c = document.querySelector('.vo-cta'), s = c.querySelectorAll('.vo-step'); return s.length === 3 && +getComputedStyle(s[2]).opacity > .9"
                             " && +getComputedStyle(c.querySelector('.vo-end')).opacity > .9"
                             " && c.querySelector('.vo-steps').style.getPropertyValue('--fp') === '1.000'; }", timeout=12000)   # scoped: the intro holds a clone
    except Exception:
        pass
    f = out / "frame-1920-generic-cta-flip-postroll.png"
    pg.locator(".vo-stage").screenshot(path=str(f))
    s = pg.evaluate(STEPS)
    check(f"cta-steps: after the video ends it keeps looping to the end: the toast + the flip -> {f.name}",
          s and full and s["so"][2] > .9 and s["eo"] > .5 and pg.evaluate("() => document.querySelector('video').ended"), s)
    check(f"persona: post-roll flip stays {GENERIC!r} (nothing typed) -> {f.name}", s and s["mini"] == GENERIC, s and s["mini"])
    return full


def named_flow(pg, base, out, cta, name_q):
    """named mode (?name=NM) at data-cue-cta: the same take with handle(NM), ending on the contact row (1920 page)"""
    nm = urllib.parse.unquote(name_q.split("=", 1)[1])
    shot = lambda ph: pg.locator(".vo-stage").screenshot(path=str(out / f"frame-1920-named-cta-{ph}.png"))
    goto(pg, base, name_q, round(cta + 0.3, 2))
    shot("1-hero")
    s = pg.evaluate(STEPS)
    vis = [v[0] for v in pg.evaluate(VISIBLE)]
    check(f"named flow: cta + 0.3 = cta-steps only (no pill), the hero, empty field, no title / form -> frame-1920-named-cta-1-hero.png",
          vis == ["cta-steps"] and s and s["so"][0] > .9 and s["typed"] == "" and s["chrome"] == ["none", "none"], (vis, s and s["chrome"]))
    ph = dict(PHASES)
    for name in ("2-zoom", "3-typed", "4-press", "5-scanning", "6-report", "7-flip"):
        pg.evaluate(DRAW, cta + ph[name])
        shot(name)
        s = pg.evaluate(STEPS)
        if name == "3-typed":
            check(f"named flow: cta + 3.05 the field holds her handle {handle(nm)!r}, camera zoomed -> frame-1920-named-cta-3-typed.png",
                  s and s["typed"] == handle(nm) and s["cz"][0] >= 2.2, s and s["typed"])
        if name == "5-scanning":
            check(f"named flow: cta + 5.6 the scan card for '@{handle(nm)}', 'Searching <place>, step N of 9…'", s and s["so"] == [0, 1, 0] and s["at"] == "@" + handle(nm)
                  and PROGRESS.fullmatch(s["ms"] or ""), s and (s["at"], s["ms"]))
        if name == "6-report":
            check(f"named flow: cta + 8.3 the report '{LEAKS} links found' for '@{handle(nm)}' (?name=: no scan result, the placeholder rows)", s and s["so"][2] > .9 and s["count"] == f"{LEAKS} links found" and s["at"] == "@" + handle(nm), s and (s["count"], s["at"]))
        if name == "7-flip":
            check(f"named flow: cta + 9.65 the contact row Telegram / WhatsApp / email only (no {nm!r}), no 'Rewatch', no flip -> frame-1920-named-cta-7-flip.png",
                  s and s["eo"] > .9 and named_end(s, nm), s and (s["shown"], s["contacts"], s["chrome"]))
    pg.evaluate(DRAW, cta + 13.5)
    shot("8-hold")
    s = pg.evaluate(STEPS)
    check("named flow: the end is held (cta + 13.5: toast + contacts still up) -> frame-1920-named-cta-8-hold.png", s and s["eo"] > .9 and named_end(s, nm), s and s["eo"])
    pg.evaluate(DRAW, cta + 15.3)
    s = pg.evaluate(STEPS)
    check("named flow: then it loops (cta + 15.3 = the hero again, toast off)", s and s["so"][0] > .9 and s["eo"] < .1 and s["typed"] == "", s and (s["so"], s["eo"]))
    pg.goto(f"{base}video/?{name_q}&t={END - 0.6:g}")
    pg.wait_for_function(SEEKED, arg=round(END - 0.6, 3), timeout=15000)
    play(pg, END - 0.1)
    pg.wait_for_function("() => document.querySelector('video').ended", timeout=8000)
    t0 = pg.evaluate("() => document.documentElement.dataset.voT")
    pg.wait_for_timeout(1500)
    f = out / "frame-1920-named-cta-postroll.png"
    pg.locator(".vo-stage").screenshot(path=str(f))
    s = pg.evaluate(STEPS)
    t1 = pg.evaluate("() => [document.documentElement.dataset.voT, document.querySelector('video').ended, document.querySelector('.vo-for').hasAttribute('data-off')]")
    check(f"named flow: after the take ends it keeps playing (clock {t0} → {t1[0]}), cta-steps with '@{handle(nm)}', pill off -> {f.name}",
          s and not s["off"] and t1[1] and t1[2] and float(t1[0]) > float(t0) + 1 and s["at"] == "@" + handle(nm), (t0, t1, s and s["at"]))


def cta_phone(b, base, out, cta, full):
    """every phase on an iPhone: portrait (the stage = the top 390x219) and the rotated theater; the typed handle readable"""
    ctx = ctx_new(b, **VIEWPORTS["phone"])
    ctx.add_init_script(IPHONE_FS)
    pg = ctx.new_page()
    goto(pg, base, "", round(cta + 3.05, 2))
    for view in ("portrait", "theater"):
        if view == "theater":
            pg.locator(".vo-fs").tap()
            pg.wait_for_function("() => document.documentElement.dataset.voFull === 'theater'", timeout=3000)
            pg.wait_for_timeout(400)
        for name, u in PHASES:
            pg.evaluate(DRAW, cta + u)
            pg.screenshot(path=str(out / f"phone-{view}-generic-cta-{name}.png"))
        pg.evaluate(DRAW, cta + 3.05)
        s = pg.evaluate(STEPS)
        lo = 11 if view == "portrait" else 20
        check(f"cta-steps (phone {view}): typed {full!r} in full, on-screen glyphs >= {lo} px" + (", the toast's >= 11 px" if view == "portrait" else "")
              + f" -> phone-{view}-generic-cta-*.png", s and full and s["so"][0] > .9 and s["typed"] == full and s["px"] >= lo
              and (view == "theater" or s["endpx"] >= 11), s)
    ctx.close()


def named_phone(b, base, out, cta, name_q):
    """the named flow on an iPhone: portrait + the rotated theater, every phase shot, her handle + toast readable"""
    nm = urllib.parse.unquote(name_q.split("=", 1)[1])
    ctx = ctx_new(b, **VIEWPORTS["phone"])
    ctx.add_init_script(IPHONE_FS)
    pg = ctx.new_page()
    goto(pg, base, name_q, round(cta + 3.05, 2))
    for view in ("portrait", "theater"):
        if view == "theater":
            pg.locator(".vo-fs").tap()
            pg.wait_for_function("() => document.documentElement.dataset.voFull === 'theater'", timeout=3000)
            pg.wait_for_timeout(400)
        for name, u in PHASES:
            pg.evaluate(DRAW, cta + u)
            pg.screenshot(path=str(out / f"phone-{view}-named-cta-{name}.png"))
        pg.evaluate(DRAW, cta + 3.05)
        s3 = pg.evaluate(STEPS)
        pg.evaluate(DRAW, cta + 9.65)
        s = pg.evaluate(STEPS)
        lo = 11 if view == "portrait" else 20
        check(f"named flow (phone {view}): typed her handle {handle(nm)!r} >= {lo} px, the contact row (no {nm!r}) >= 8 px -> phone-{view}-named-cta-*.png",
              s3 and s3["typed"] == handle(nm) and s3["px"] >= lo and named_end(s, nm) and s["nmpx"] >= 8, (s3 and (s3["typed"], s3["px"]), s and (s["shown"], s["nmpx"])))
    ctx.close()


def persona(b, base, out, pf, tap, cta, name_q, nm):
    """generic = the demo persona GENERIC on every card (1920, phone portrait, iPhone theater); named = nm on every card"""
    for view, opts in (("1920", dict(viewport={"width": 1920, "height": 1080})), ("phone", VIEWPORTS["phone"]), ("theater", VIEWPORTS["phone"])):
        ctx = ctx_new(b, **opts)
        if view == "theater":
            ctx.add_init_script(IPHONE_FS)
        pg = ctx.new_page()
        for mode, query in (("generic", ""), ("named", name_q)):
            who, other = (GENERIC, nm) if mode == "generic" else (nm, GENERIC)
            goto(pg, base, query, 1.0)
            if view == "theater":
                pg.locator(".vo-fs").tap()
                pg.wait_for_function("() => document.documentElement.dataset.voFull === 'theater'", timeout=3000)
                pg.wait_for_timeout(300)
            bad = []
            for pid, live, rem, off in pf:
                tl = round(live + min(1.3, rem - live - 0.1), 2)
                if pid == "google-images":
                    tl = round(min(rem - 0.1, max(tl, (float(tap[1]) if tap else live + 0.6) + 1.0)), 2)
                for state, t in (("live", tl), ("removed", round(min(rem + 2.0, off - 0.45), 2))):
                    pg.evaluate("t => { const v = document.querySelector('video'); v.pause(); v.currentTime = t; }", t)
                    pg.wait_for_function(SEEKED, arg=t, timeout=15000)
                    pg.wait_for_timeout(250)
                    pg.screenshot(path=str(out / f"persona-{view}-{mode}-{pid}-{state}.png"))
                    st = pg.evaluate(VISIBLE)
                    tx = st[0][2] if len(st) == 1 else ""
                    ok = who in tx and other not in tx and "Your name" not in tx and "tessa" not in tx.lower()   # "Type your name" (the form) stays
                    if ok and mode == "generic" and state == "removed" and pid in ("google", "google-images"):
                        at = pg.evaluate(AFTER)[0]
                        ok = GENERIC_SITE in at and ("instagram.com › " + GENERIC_IG if pid == "google" else "Instagram") in at
                    if not ok:
                        bad.append((pid, state, tx[:120]))
            check(f"persona: {view} {mode}: every card live + removed shows {who!r}, no {other!r} / 'Your name' / 'Tessa'"
                  + (f", after = {GENERIC_SITE} + instagram {GENERIC_IG}" if mode == "generic" else "") + f" -> persona-{view}-{mode}-*.png", not bad, bad)
            if mode == "generic":   # the end card + its flip: stays GENERIC; a typed (not submitted) name flips in
                res = []
                for ph, t in (("end", cta + 0.6), ("flip", cta + 9.65)):
                    pg.evaluate(DRAW, t)
                    pg.screenshot(path=str(out / f"persona-{view}-generic-{ph}.png"))
                    st, s = pg.evaluate(VISIBLE), pg.evaluate(STEPS)
                    tx = st[0][2] if len(st) == 1 else ""
                    res.append((ph, s and s["mini"], "Your name" in tx or "tessa" in tx.lower()))
                pg.evaluate("n => { const i = document.querySelector('#vo-name'); i.value = n; }", "Mia Lune")
                pg.evaluate(DRAW, cta + 9.65)
                pg.screenshot(path=str(out / f"persona-{view}-generic-flip-typed.png"))
                s = pg.evaluate(STEPS)
                pg.evaluate("() => { document.querySelector('#vo-name').value = ''; }")
                check(f"persona: {view} end card: {GENERIC!r} at cta + 0.6 + the flip (no 'Your name' / 'Tessa'), a typed 'Mia Lune' flips in -> persona-{view}-generic-{{end,flip,flip-typed}}.png",
                      [r[1:] for r in res] == [(GENERIC, False), (GENERIC, False)] and s and s["mini"] == "Mia Lune", (res, s and s["mini"]))
        ctx.close()


# offset layout (theater-proof) of the stage, the play bar, the full screen button, every visible .vo-ui box
UI = """() => { const st = document.querySelector('.vo-stage'), o = e => { let x = 0, y = 0, w = e.offsetWidth, h = e.offsetHeight; for (; e && e !== st; e = e.offsetParent) { x += e.offsetLeft; y += e.offsetTop; } return [x, y, w, h]; };
  const ctl = document.querySelector('.vo-ctl');
  return [o(st).slice(2), getComputedStyle(ctl).display, o(ctl), o(document.querySelector('.vo-fs')),
          [...document.querySelectorAll('.vo-ui > *')].filter(e => getComputedStyle(e).display !== 'none').map(e => [e.className, o(e)]), getComputedStyle(ctl).backgroundImage]; }"""


def ui_full(b, base, out, name_q):
    """no half-width UI: the play bar = the stage width, the button off Jack's left half (phone portrait, iPhone theater, 1920)"""
    for vp, opts, how in (("phone", VIEWPORTS["phone"], None), ("theater", VIEWPORTS["phone"], "theater"), ("1920", dict(viewport={"width": 1920, "height": 1156}), None)):
        ctx = ctx_new(b, **opts)
        ctx.add_init_script(IPHONE_FS)
        pg = ctx.new_page()
        goto(pg, base, name_q, 20.4)
        if how:
            pg.locator(".vo-fs").tap()
            pg.wait_for_function("() => document.documentElement.dataset.voFull === 'theater'", timeout=3000)
            pg.wait_for_timeout(400)
        f = out / f"ui-{vp}-named-20.4s.png"
        pg.screenshot(path=str(f))
        (sw, sh), disp, ctl, fs, boxes, grad = pg.evaluate(UI)
        half = [c for c, r in boxes if .4 * sw <= r[2] <= .6 * sw]
        fs_ok = fs[0] >= sw / 2 and fs[1] + fs[3] <= sh / 4
        if vp == "1920":   # desktop: native controls (full width), no own bar
            check(f"no half-width UI ({vp}): no own play bar (native controls), no .vo-ui box 40-60 % wide, full screen button in the top-right quarter -> {f.name}",
                  disp == "none" and not half and fs_ok, (disp, half, fs))
        else:
            check(f"no half-width UI ({vp}): play bar = the full stage width ({ctl[2]:.0f} of {sw:.0f}) at its bottom, <= 34 px, gradient across it -> {f.name}",
                  disp == "flex" and abs(ctl[0]) <= 1 and abs(ctl[2] - sw) <= 1 and abs(ctl[1] + ctl[3] - sh) <= 1 and ctl[3] <= 34 and "gradient" in grad, (disp, ctl, sw, sh))
            check(f"no half-width UI ({vp}): no .vo-ui box 40-60 % of the stage wide; the full screen button in the top-right quarter (off Jack's left half)",
                  not half and fs_ok, (half, fs, sw, sh))
        ctx.close()


def swap(b, base, out, cues, cta, vp, opts):
    """the name bar: generic → SWAP_NAME in place (no reload), Change, Reset; vp = phone | desktop | frame-1920"""
    want_q = "?name=" + urllib.parse.quote(SWAP_NAME)
    ctx = ctx_new(b, **opts)
    ctx.add_init_script(SAY_STUB)
    if vp == "phone":
        ctx.add_init_script(IPHONE_FS)
    seen = []
    ext = guard(ctx, (base,), seen)
    pg = ctx.new_page()
    errs = []
    console(pg, errs)
    pg.goto(f"{base}video/")
    pg.wait_for_function("() => document.querySelector('video').readyState >= 3", timeout=15000)
    pg.wait_for_timeout(1200)
    pg.screenshot(path=str(out / f"{vp}-swap-bar-generic-0s.png"))
    st, bar, inp, btn, hint, vh, t = pg.evaluate(BAR)
    check(f"bar ({vp}): generic at {t:g} s: the name bar right under the stage, full width, input + button in view -> {vp}-swap-bar-generic-0s.png",
          t == 0 and abs(bar[1] - (st[1] + st[3])) <= 1 and abs(bar[2] - st[2]) <= 1 and bar[1] + bar[3] <= vh + 1
          and all(r[3] > 20 and r[1] + r[3] <= vh + 1 for r in (inp, btn)), (st, bar, inp, btn, vh, t))
    check(f"bar ({vp}): the pulsing '👇 type your name' pill on the input, in view", hint[0] != "none" and hint[2] == "vo-nb-pulse"
          and hint[1][3] > 0 and hint[1][1] >= st[1] + st[3] - hint[1][3] and hint[1][1] + hint[1][3] <= vh
          and pg.evaluate("() => document.querySelector('.vo-nb-hint').textContent") == "\U0001F447 type your name", hint)
    pg.fill("#vo-nb-in", "<b>")
    pg.press("#vo-nb-in", "Enter")
    pg.wait_for_timeout(300)
    bad = pg.evaluate("() => { const e = document.querySelector('.vo-nb-err'); return [e.hidden, e.textContent, document.querySelector('#vo-nb-in').getAttribute('aria-invalid'), document.documentElement.dataset.voMode, getComputedStyle(document.querySelector('.vo-nb-hint')).display]; }")
    check(f"bar ({vp}): invalid '<b>' rejected inline (message, aria-invalid), URL + mode unchanged; the hint gone after the first focus",
          not bad[0] and "1-40" in bad[1] and bad[2] == "true" and bad[3] == "generic" and bad[4] == "none" and pg.url == f"{base}video/", (bad, pg.url))
    pg.fill("#vo-nb-in", "")
    if vp == "phone":   # iPhone theater: the pill opens the bar
        pg.locator(".vo-fs").tap()
        pg.wait_for_function("() => document.documentElement.dataset.voFull === 'theater'", timeout=3000)
        pg.wait_for_timeout(300)
        pg.screenshot(path=str(out / "phone-swap-theater-pill.png"))
        pill = pg.evaluate("() => { const b = document.querySelector('.vo-nb-pill').getBoundingClientRect(); return [getComputedStyle(document.querySelector('.vo-nb-pill')).display, b.width > 0]; }")
        pg.locator(".vo-nb-pill").tap()
        pg.wait_for_timeout(500)
        got = pg.evaluate("() => [document.documentElement.dataset.voFull || null, document.activeElement && document.activeElement.id]")
        check("bar (phone): theater shows the 'Your name' pill; a tap closes the theater and focuses the bar input -> phone-swap-theater-pill.png",
              pill == ["block", True] and got == [None, "vo-nb-in"], (pill, got))
        pg.evaluate("() => document.activeElement.blur()")
    pg.evaluate(CTA_WATCH)
    play(pg, 2.4)
    before = pg.evaluate("() => document.querySelector('video').currentTime")
    pg.fill("#vo-nb-in", SWAP_NAME)
    pg.evaluate("() => { window.__same = 1; window.__pauses = 0; document.querySelector('video').addEventListener('pause', () => __pauses++); }")
    t0 = time.monotonic()
    pg.press("#vo-nb-in", "Enter")
    now = pg.evaluate("() => [document.querySelector('.vo-rb'), location.search, document.documentElement.dataset.voMode, document.querySelector('video').currentTime < 1]")
    check(f"swap ({vp}): Enter → at once, no rebuild card (no .vo-rb in the page): {want_q}, named mode, back at 0", now == [None, want_q, "named", True], now)
    done = False
    try:
        pg.wait_for_function("""q => { const v = document.querySelector('video'); return location.search === q && document.documentElement.dataset.voMode === 'named'
            && !v.paused && v.currentTime > 0 && v.currentTime < 1; }""", arg=want_q, timeout=1000)
        done = True
    except Exception:
        pass
    pg.wait_for_timeout(300)
    pg.locator(".vo-stage").screenshot(path=str(out / f"{vp}-swap-settled.png"))
    dt = time.monotonic() - t0
    got = pg.evaluate("() => [location.search, document.documentElement.dataset.voMode, !document.querySelector('video').paused, document.querySelector('video').currentTime, window.__same === 1, document.querySelector('.vo-nb-n').textContent]")
    pauses = pg.evaluate("() => __pauses")
    check(f"swap ({vp}): {dt:.2f} s after Enter: {want_q}, same document, named mode, restarted from {before:.1f} s, playing within 1 s, never paused, bar 'Rebuilt for {SWAP_NAME}' -> {vp}-swap-settled.png",
          done and got[4] and got[5] == SWAP_NAME and pauses == 0, (got, dt, pauses))
    pg.wait_for_function("() => document.querySelector('video').currentTime > 1.2", timeout=5000)
    said = pg.evaluate("() => [__said, __utt]")
    pill = pg.evaluate("() => { const e = document.querySelector('.vo-for'); return [e.hasAttribute('data-off'), e.innerText.replace(/\\s+/g, ' ').trim()]; }")
    check(f"swap ({vp}): restarted named, 0 speak calls / utterances, 'for {SWAP_NAME}' pill",
          said == [[], 0] and not pill[0] and pill[1].endswith(f"for {SWAP_NAME}"), (said, pill))
    g = cues["google"]
    tg = round(g[0] + 1.3, 2)
    pg.evaluate("t => { const v = document.querySelector('video'); v.pause(); v.currentTime = t; }", tg)
    pg.wait_for_function(SEEKED, arg=tg, timeout=15000)
    pg.wait_for_timeout(1200)
    pg.locator(".vo-stage").screenshot(path=str(out / f"{vp}-swap-google-live.png"))
    vis = pg.evaluate(VISIBLE)
    check(f"swap ({vp}): google at its live cue (t={tg:g}) shows {SWAP_NAME!r} -> {vp}-swap-google-live.png",
          [v[0] for v in vis] == ["google"] and SWAP_NAME in vis[0][2] and GENERIC not in vis[0][2], [(v[0], v[2][:80]) for v in vis])
    if vp == "desktop":   # the end say cue too
        say = cues["say"]
        pg.evaluate("t => { document.querySelector('video').currentTime = t; }", say - 0.6)
        pg.wait_for_function(SEEKED, arg=say - 0.6, timeout=15000)
        pg.evaluate("() => document.querySelector('video').play()")
        pg.wait_for_function(f"() => document.querySelector('video').currentTime > {say + 0.6}", timeout=5000)
        said = pg.evaluate("() => [__said, __utt]")
        check(f"swap (desktop): played across data-cue-say {say}: 0 speak calls / utterances", said == [[], 0], said)
        pg.evaluate("() => document.querySelector('video').pause()")
    tc = round(cta + 0.6, 2)
    early = pg.evaluate("() => __ctaSeen")
    pg.evaluate("t => { const v = document.querySelector('video'); v.pause(); v.currentTime = t; }", tc)
    pg.wait_for_function(SEEKED, arg=tc, timeout=15000)
    pg.wait_for_timeout(300)
    vis = [v[0] for v in pg.evaluate(VISIBLE)]
    pg.evaluate(DRAW, cta + 9.65)
    s = pg.evaluate(STEPS)
    check(f"named flow: swap ({vp}): {'' if vp == 'desktop' else 'no cta-steps before its cue; '} at cta + 0.6 = {tc:g} the named flow ({vis}), ending on the contact row (no {SWAP_NAME!r})",
          (early is False or vp == "desktop") and vis == ["cta-steps"] and named_end(s, SWAP_NAME) and pg.evaluate("() => document.documentElement.dataset.voMode") == "named", (early, vis, s and s["shown"]))
    pg.evaluate("() => document.querySelector('.vo-nb-chg').click()")   # DOM click: hidden (no swap) must fail the check, not abort
    pg.wait_for_timeout(200)
    ch = pg.evaluate("() => [getComputedStyle(document.querySelector('.vo-nb-f')).display, document.querySelector('#vo-nb-in').value, document.activeElement.id]")
    check(f"swap ({vp}): Change re-opens the input, prefilled with {SWAP_NAME!r}, focused", ch[0] != "none" and ch[1:] == [SWAP_NAME, "vo-nb-in"], ch)
    pg.evaluate("() => document.activeElement.blur()")
    pg.evaluate("() => document.querySelector('.vo-nb-rst').click()")
    try:
        pg.wait_for_function("""() => { const v = document.querySelector('video'); return location.search === '' && document.documentElement.dataset.voMode === 'generic'
            && !v.paused && v.currentTime < 2 && document.querySelector('[data-vo=name]').textContent !== '""" + SWAP_NAME + """'; }""", timeout=3000)
    except Exception:
        pass
    got = pg.evaluate("() => [location.search, document.documentElement.dataset.voMode, document.querySelector('[data-vo=name]').textContent, !document.querySelector('video').paused, document.querySelector('video').currentTime, getComputedStyle(document.querySelector('.vo-nb-f')).display, window.__same === 1]")
    pg.evaluate("t => { const v = document.querySelector('video'); v.pause(); v.currentTime = t; }", tc)
    pg.wait_for_function(SEEKED, arg=tc, timeout=15000)
    pg.wait_for_timeout(300)
    vis = [v[0] for v in pg.evaluate(VISIBLE)]
    check(f"swap ({vp}): Reset → generic in place (URL without query, {SWAP_NAME!r} gone, restarted + playing, the form back), end card back at {tc:g}",
          got[0] == "" and got[1] == "generic" and got[2] != SWAP_NAME and got[3] is True and got[4] < 2 and got[5] != "none" and got[6] and vis == ["cta-steps"], (got, vis))
    check(f"bar ({vp}): no console errors, no request outside the local server", not errs and not ext, (errs, sorted(set(ext))))
    ctx.close()


def player(b, base, out, cues):
    """phone merged layout, tap-to-play + hint, iPhone theater, desktop full screen"""
    g = cues["google"]
    t = round(g[0] + 1.3, 2)
    near = lambda a, b, tol=2: abs(a - b) <= tol
    ctx = ctx_new(b, **VIEWPORTS["phone"])
    pg = ctx.new_page()
    goto(pg, base, "", t)
    pg.screenshot(path=str(out / "proof-phone-portrait-generic-google-live.png"))
    st, ov, card, tr, full, _, ctl = pg.evaluate(GEOM)
    check("player: phone portrait: stage 16:9 full width, .vo-over = its right half, the card inside it (not below) -> proof-phone-portrait-generic-google-live.png",
          near(st[2], 390) and near(st[3], 390 * 9 / 16) and near(ov[0], st[0] + st[2] / 2) and near(ov[1], st[1]) and near(ov[3], st[3])
          and card and card[0] >= ov[0] - 1 and card[1] >= st[1] - 1 and card[1] + card[3] <= st[1] + st[3] + 1, (st, ov, card))
    vis = pg.evaluate("() => [document.documentElement.hasAttribute('data-vo-touch'), getComputedStyle(document.querySelector('.vo-ctl')).display, getComputedStyle(document.querySelector('.vo-fs')).display]")
    check("player: phone = touch: native controls off, own play bar + Rotate button shown", ctl is False and vis == [True, "flex", "flex"], (ctl, vis))
    pg.locator(".vo-stage").tap(position={"x": 97, "y": 140})
    pg.wait_for_function("() => !document.querySelector('video').paused", timeout=5000)
    pg.wait_for_timeout(400)
    pg.screenshot(path=str(out / "phone-generic-tap-played-hint.png"))
    h = pg.evaluate("() => { const e = document.querySelector('.vo-hint'); return [getComputedStyle(e).display, e.textContent, document.documentElement.hasAttribute('data-vo-playing')]; }")
    check("player: phone: a tap on the stage plays, 'Rotate for full size' hint shown", h == ["block", "Rotate for full size", True], h)
    ctx.close()
    # iPhone Safari: no element full screen → theater (declared: the Fullscreen API removed by an init script)
    ctx = ctx_new(b, **VIEWPORTS["phone"])
    ctx.add_init_script(IPHONE_FS)
    pg = ctx.new_page()
    goto(pg, base, "", t)
    n0 = pg.evaluate("history.length")

    def open_theater():
        pg.locator(".vo-fs").tap()
        pg.wait_for_function("() => document.documentElement.dataset.voFull === 'theater'", timeout=3000)
        pg.wait_for_timeout(300)
    open_theater()
    pg.screenshot(path=str(out / "proof-phone-theater-generic-google-live.png"))
    st, ov, card, tr, full, ovf, ctl = pg.evaluate(GEOM)
    m = [float(x) for x in re.findall(r"-?[\d.e]+", tr)[:4]]
    rotated = len(m) == 4 and near(m[0], 0, .01) and near(m[1], 1, .01) and near(m[2], -1, .01) and near(m[3], 0, .01)
    # rotated 90deg clockwise: the stage's right half = the lower half of the screen box
    check("player: iPhone theater: stage rotated 90deg, filling the 390 px width (693 px tall), scroll locked, no native controls, "
          "card in its right half (= the lower half) -> proof-phone-theater-generic-google-live.png",
          rotated and near(st[2], 390) and near(st[3], 390 * 16 / 9, 3) and ovf == "hidden" and ctl is False
          and card and card[1] >= st[1] + st[3] / 2 - 1 and card[1] + card[3] <= st[1] + st[3] + 1 and card[0] >= st[0] - 1, (tr, st, card, ovf, ctl))
    pg.keyboard.press("Escape")
    closed = lambda: pg.evaluate("() => !document.documentElement.dataset.voFull && getComputedStyle(document.documentElement).overflow !== 'hidden'")
    pg.wait_for_timeout(300)
    c1 = closed()
    open_theater()
    pg.evaluate("history.back()")
    pg.wait_for_timeout(500)
    c2 = closed()
    open_theater()
    pg.locator(".vo-fs").tap()
    pg.wait_for_timeout(500)
    c3 = closed() and pg.evaluate("history.length") == n0 + 1 and pg.url.endswith(f"t={t:g}")
    check("player: iPhone theater closes on Esc / back / the X (scroll unlocked, page stays)", c1 and c2 and c3, (c1, c2, c3, pg.url))
    ctx.close()
    # desktop: the STAGE goes full screen (cards stay), on the right half of the centred 16:9 picture
    ctx = ctx_new(b, **VIEWPORTS["desktop"])
    pg = ctx.new_page()
    goto(pg, base, "", t)
    pg.locator(".vo-fs").click()
    try:
        pg.wait_for_function("() => document.fullscreenElement === document.querySelector('.vo-stage')", timeout=4000)
    except Exception:
        pass
    pg.wait_for_timeout(500)
    pg.screenshot(path=str(out / "desktop-fullscreen-generic-google-live.png"))
    st, ov, card, tr, full, _, ctl = pg.evaluate(GEOM)
    vw, vh = pg.evaluate("() => [innerWidth, innerHeight]")
    pw = min(vw, vh * 16 / 9)
    check("player: desktop full screen = the stage (data-vo-full=fs); .vo-over = the right half of the centred 16:9 picture, card inside, native controls kept",
          full == "fs" and near(ov[0], (vw + pw) / 2 - pw / 2) and near(ov[2], pw / 2) and near(ov[3], pw * 9 / 16) and near(ov[1], (vh - pw * 9 / 16) / 2)
          and card and card[0] >= ov[0] and card[0] + card[2] <= ov[0] + ov[2] + 1 and ctl is True, (full, [vw, vh], ov, card, ctl))
    pg.locator(".vo-fs").click()
    pg.wait_for_timeout(400)
    check("player: desktop: the X leaves full screen", pg.evaluate("() => !document.fullscreenElement && !document.documentElement.dataset.voFull"))
    ctx.close()


# layout box (offset*, so the theater's rotation does not matter) of the stage / video / .vo-over, the drawn picture's size
# (object-fit), the overlay layers' paint, the screen rects of the stage + .vo-over, data-vo-full
FULL = """() => { const st = document.querySelector('.vo-stage'), v = document.querySelector('.vo-video'), ov = document.querySelector('.vo-over'),
  bx = document.querySelector('.vo-box'), lay = e => [e.offsetLeft, e.offsetTop, e.offsetWidth, e.offsetHeight], fit = getComputedStyle(v).objectFit,
  sc = fit === 'cover' ? Math.max(v.offsetWidth / v.videoWidth, v.offsetHeight / v.videoHeight) : fit === 'contain' || fit === 'scale-down'
     ? Math.min(v.offsetWidth / v.videoWidth, v.offsetHeight / v.videoHeight) : NaN, r = e => { const b = e.getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; },
  paint = e => { const c = getComputedStyle(e); return [c.backgroundColor, c.backgroundImage, c.boxShadow, c.filter, c.backdropFilter || 'none']; };
  return [lay(st), lay(v), fit === 'fill' ? [v.offsetWidth, v.offsetHeight] : [v.videoWidth * sc, v.videoHeight * sc], lay(ov), paint(ov), paint(bx),
          r(st), r(ov), document.documentElement.dataset.voFull || null]; }"""
# the stage region x0..x1, y0..y1 (fractions) as an 8x8 RGB grid, on the screenshot vs the same region of the video frame drawn alone
PIX = """async ([png, box]) => { const v = document.querySelector('.vo-video'), st = document.querySelector('.vo-stage').getBoundingClientRect(), dpr = devicePixelRatio;
  const mean = (src, sx, sy, sw, sh) => { const c = document.createElement('canvas'); c.width = 8; c.height = 8; const g = c.getContext('2d');
    g.imageSmoothingQuality = 'high'; g.drawImage(src, sx, sy, sw, sh, 0, 0, 8, 8); return [...g.getImageData(0, 0, 8, 8).data].filter((x, i) => i % 4 < 3); };
  const img = await createImageBitmap(await (await fetch('data:image/png;base64,' + png)).blob());
  const [x0, y0, x1, y1] = box;
  return [mean(img, (st.left + x0 * st.width) * dpr, (st.top + y0 * st.height) * dpr, (x1 - x0) * st.width * dpr, (y1 - y0) * st.height * dpr),
          mean(v, x0 * v.videoWidth, y0 * v.videoHeight, (x1 - x0) * v.videoWidth, (y1 - y0) * v.videoHeight)]; }"""


def full_frame(b, base, out):
    """the video fills the whole stage, the cards are drawn on its right half (transparent overlay layer)"""
    import base64
    near = lambda a, b, tol=1.5: abs(a - b) <= tol
    clear = lambda p: p[0] in ("rgba(0, 0, 0, 0)", "transparent") and p[1] == "none" and p[2] == "none" and p[3] == "none" and p[4] == "none"
    for vp, opts, how in (("1920", dict(viewport={"width": 1920, "height": 1156}), None), ("1280", dict(viewport={"width": 1280, "height": 800}), None),
                          ("phone", VIEWPORTS["phone"], None), ("theater", VIEWPORTS["phone"], "theater"), ("fullscreen", VIEWPORTS["desktop"], "fs")):
        ctx = ctx_new(b, **opts)
        if how == "theater":
            ctx.add_init_script(IPHONE_FS)
        pg = ctx.new_page()
        goto(pg, base, "", 7.2)   # card-free (before google's live cue) and still: his hand out of the right half (6.9-7.5 s, the take's stillest right half)
        if how:
            pg.locator(".vo-fs").click()
            pg.wait_for_function("w => document.documentElement.dataset.voFull === w", arg=how, timeout=4000)
            pg.wait_for_timeout(500)
        shot = out / f"full-frame-{vp}.png"
        pg.screenshot(path=str(shot))
        if how is None:   # declared: native controls + the player UI layer + the intro fill (cued 0.3-9.8, fill() checks it) off for the pixel probe (bar gradient, top-right button; ui_full checks their geometry)
            pg.evaluate("() => { document.querySelector('.vo-video').controls = false; document.querySelector('.vo-ui').style.visibility = 'hidden';"
                        " const i = document.querySelector('.vo-intro'); if (i) i.style.visibility = 'hidden'; }")
            pg.wait_for_timeout(300)
            png = pg.screenshot()
        st, vb, pic, ov, pov, pbx, sr, orr, full = pg.evaluate(FULL)
        check(f"full frame: {vp}: the <video> box == the stage box -> {shot.name}", all(near(x, y) for x, y in zip(vb, [0, 0, st[2], st[3]])), (st, vb))
        if how == "fs":   # the whole take, centred: the overlay = the right half of that picture
            check(f"full frame: {vp}: the 16:9 picture centred in the full-screen stage, .vo-over = its right half, transparent",
                  near(pic[0] / pic[1], 16 / 9, .02) and near(orr[0], sr[0] + (st[2] - pic[0]) / 2 + pic[0] / 2) and near(orr[2], pic[0] / 2) and near(orr[3], pic[1])
                  and clear(pov) and clear(pbx), (st, pic, orr, pov, pbx))
            ctx.close()
            continue
        check(f"full frame: {vp}: the drawn picture covers the whole stage (object-fit)", pic[0] >= st[2] - 1.5 and pic[1] >= st[3] - 1.5, (st, pic))
        check(f"full frame: {vp}: .vo-over / .vo-box = the stage's right half, transparent (no background / shadow / filter)",
              near(ov[0], st[2] / 2) and near(ov[1], 0) and near(ov[2], st[2] / 2) and near(ov[3], st[3]) and clear(pov) and clear(pbx), (st, ov, pov, pbx))
        if how is None:   # the theater is rotated on screen: its geometry above is enough
            a_, v_ = pg.evaluate(PIX, [base64.b64encode(png).decode(), [.56, .1, .96, .9]])
            d = [abs(x - y) for x, y in zip(a_, v_)]   # real footage: fine moving detail (the phone on his whiteboard) moves single cells
            check(f"full frame: {vp}: the screen's right half (no card at 7.2 s, intro fill hidden) = the video frame's right half (mean |diff| < 3, max < 24)",
                  sum(d) / len(d) < 3 and max(d) < 24, (round(sum(d) / len(d), 2), max(d)))
        ctx.close()


# captions (site/video/transcript.json → js/video-overlays.js captions(t)): [shown, words, highlighted, band, plain, box, cards, transform]
# box / cards in stage fractions [x0, y0, x1, y1] of the UNROTATED stage (theater: the stage is turned 90deg clockwise)
CAPT = """() => { const st = document.querySelector('.vo-stage'), s = st.getBoundingClientRect(), th = document.documentElement.dataset.voFull === 'theater';
  const fr = r => th ? [(r.top - s.top) / s.height, (s.right - r.right) / s.width, (r.bottom - s.top) / s.height, (s.right - r.left) / s.width]
                     : [(r.left - s.left) / s.width, (r.top - s.top) / s.height, (r.right - s.left) / s.width, (r.bottom - s.top) / s.height];
  const c = document.querySelector('.vo-capt'), cs = getComputedStyle(c), on = c.querySelector('.on');
  return [cs.display !== 'none', [...c.children].map(e => e.textContent), on ? on.textContent : null, c.dataset.band || null, c.hasAttribute('data-plain'),
          fr(c.getBoundingClientRect()), [...document.querySelectorAll('.vo-pf')].filter(e => !e.hasAttribute('data-off')).map(e => fr(e.getBoundingClientRect())), cs.transform]; }"""
TRANSCRIPT = json.loads((ROOT / "site/video/transcript.json").read_text(encoding="utf-8"))
WORDS = TRANSCRIPT["words"]


def said(t, before=1.2, after=0.4):   # the transcript words around t (the shot log: what Jack says at that moment)
    return " ".join(w[0] for w in WORDS if w[2] >= t - before and w[1] <= t + after)


def word_at(t):   # the word he is saying (or just said) at t; None before the first word / > 0.5 s after the last one said
    k = max((i for i, w in enumerate(WORDS) if w[1] <= t), default=None)
    return None if k is None or t > WORDS[k][2] + 0.5 else WORDS[k][0]


def overlap(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def captions(b, base, out, name_q):
    """every word: drawn at its middle (pure draw(t), declared), the highlighted caption word = the transcript's word at t,
    the caption inside the stage's left half (x1 <= .5), in its band (lo: the lower third, y0 >= .62; hi: top, y1 <= .2), no
    overlap with a visible card; real seeks (?t=) at low-face / card / end moments shot; CC toggle + localStorage; reduced
    motion = plain lines; at 1920x1080, phone 390x844, iPhone theater; generic + named (captions never personalized)"""
    views = (("1920", dict(viewport={"width": 1920, "height": 1080}), False), ("phone", VIEWPORTS["phone"], False), ("theater", VIEWPORTS["phone"], True))
    for vp, opts, th in views:
        for mode, query in (("generic", ""), ("named", name_q)):
            if vp != "1920" and mode == "named":
                continue
            ctx = ctx_new(b, **opts)
            if th:
                ctx.add_init_script(IPHONE_FS)
            ext = guard(ctx, (base,))
            pg = ctx.new_page()
            errs = []
            console(pg, errs)
            goto(pg, base, query, 3)
            pg.wait_for_function("() => document.querySelector('.vo-capt').children.length || document.querySelector('.vo-capt').hasAttribute('data-off')", timeout=5000)
            if th:
                pg.locator(".vo-fs").tap()
                pg.wait_for_function("() => document.documentElement.dataset.voFull === 'theater'", timeout=3000)
                pg.wait_for_timeout(300)
            wrong, outside, band_bad, hits, shown = [], [], [], [], 0
            for i, w in enumerate(WORDS):
                t = round((w[1] + w[2]) / 2, 3)
                pg.evaluate(DRAW, t)
                on, words, hl, band, plain, box, cards, tr = pg.evaluate(CAPT)
                shown += on
                if not on or hl != w[0] or w[0] not in words:
                    wrong.append((t, w[0], hl, words))
                if on and not (box[0] >= -0.001 and box[2] <= 0.5 + 1e-3):
                    outside.append((t, [round(x, 3) for x in box]))
                if on and not ((band == "lo" and box[1] >= 0.62 and box[3] <= 0.86) or (band == "hi" and box[1] >= 0.02 and box[3] <= 0.2)):
                    band_bad.append((t, band, [round(x, 3) for x in box]))
                if on and any(overlap(box, c) > 0 for c in cards):
                    hits.append((t, [round(x, 3) for x in box], cards))
            check(f"captions {vp} {mode}: at each of the {len(WORDS)} words (its middle) the highlighted caption word = the transcript's word", not wrong, wrong[:4])
            check(f"captions {vp} {mode}: inside the stage's left half (x1 <= .5)", shown and not outside, outside[:3])
            check(f"captions {vp} {mode}: in their band (lo = the lower third y .62-.86, hi = top band y .02-.2)", shown and not band_bad, band_bad[:3])
            check(f"captions {vp} {mode}: never over a visible card", not hits, hits[:2])
            # real seeks: the drawn frame (video + captions), the face-low moments (hi band) and card cues
            for t in (1.6, 7.7, 12.95, 22.95, 30.2, 36.2, 51.3):
                if th:
                    pg.evaluate("t => { const v = document.querySelector('video'); v.currentTime = t; }", t)
                    pg.wait_for_function(SEEKED, arg=t, timeout=15000)
                    pg.wait_for_timeout(600)
                else:
                    goto(pg, base, query, t)
                on, words, hl, band, plain, box, cards, tr = pg.evaluate(CAPT)
                f = out / f"capt-{vp}-{mode}-t{t:05.2f}.png"
                (pg.locator(".vo-stage") if vp == "phone" else pg).screenshot(path=str(f))
                print(f"captions {vp} {mode} t={t:g}: shown={on} {band} {' '.join(words)!r} highlighted={hl!r} | said: {said(t)!r} -> {f.name}")
                want = word_at(t)
                check(f"captions {vp} {mode} t={t:g} (seek): shows {want!r}", (want is None and not on) or (on and hl == want), (on, hl, words))
            if vp == "1920" and mode == "generic":
                goto(pg, base, "", 12.95)
                st0 = pg.evaluate("() => [document.querySelector('.vo-ccb').getAttribute('aria-pressed'), getComputedStyle(document.querySelector('.vo-capt')).display]")
                pg.click(".vo-ccb")
                st1 = pg.evaluate("() => [document.querySelector('.vo-ccb').getAttribute('aria-pressed'), getComputedStyle(document.querySelector('.vo-capt')).display, localStorage.getItem('leakscan.cc')]")
                pg.screenshot(path=str(out / "capt-1920-cc-off.png"))
                goto(pg, base, "", 12.95)
                st2 = pg.evaluate("() => [document.querySelector('.vo-ccb').getAttribute('aria-pressed'), getComputedStyle(document.querySelector('.vo-capt')).display]")
                pg.click(".vo-ccb")
                st3 = pg.evaluate("() => [document.querySelector('.vo-ccb').getAttribute('aria-pressed'), getComputedStyle(document.querySelector('.vo-capt')).display, localStorage.getItem('leakscan.cc')]")
                check("captions: CC on by default; click → off (saved '0'), still off after a reload; click → on (saved '1') -> capt-1920-cc-off.png",
                      st0 == ["true", "block"] and st1 == ["false", "none", "0"] and st2 == ["false", "none"] and st3 == ["true", "block", "1"], (st0, st1, st2, st3))
            check(f"captions {vp} {mode}: no console errors, no requests outside the local server", not errs and not ext, (errs[:2], ext[:2]))
            ctx.close()
    # reduced motion: plain lines (no highlight, no pop), the line holds the word
    ctx = ctx_new(b, viewport={"width": 1920, "height": 1080}, reduced_motion="reduce")
    pg = ctx.new_page()
    goto(pg, base, "", 13.1)
    lines = TRANSCRIPT["lines"]
    bad = []
    for ln in lines:
        w = WORDS[ln[0]]
        t = round((w[1] + w[2]) / 2, 3)
        pg.evaluate(DRAW, t)
        on, words, hl, band, plain, box, cards, tr = pg.evaluate(CAPT)
        want = [x[0] for x in WORDS[ln[0]:ln[1] + 1]]
        if not (on and plain and hl is None and words == want and tr == "none" and box[2] <= 0.5 + 1e-3):
            bad.append((t, words, want, plain, hl, tr))
    pg.evaluate(DRAW, 13.1)
    pg.screenshot(path=str(out / "capt-1920-reduced.png"))
    check(f"captions reduced motion: each of the {len(lines)} lines plain (no highlight / pop), its words, left half -> capt-1920-reduced.png", not bad, bad[:3])
    ctx.close()
    # the landing's mini player (js/pip.js: an iframe of ../video/, min(320px, 45vw), its embed style): the stage = the frame
    for w in (320, 260, 175):
        ctx = ctx_new(b, viewport={"width": w, "height": round(w * 9 / 16)})
        pg = ctx.new_page()
        goto(pg, base, "", 0)
        pg.add_style_tag(content=PIP_EMBED)
        pg.wait_for_timeout(300)
        edge, shown = 0.0, 0
        for x in WORDS:
            pg.evaluate(DRAW, (x[1] + x[2]) / 2)
            g = pg.evaluate(PIP_CAPT)
            if g is not None:
                shown, edge = shown + 1, max(edge, g)
        pg.evaluate(DRAW, 13.1)
        pg.screenshot(path=str(out / f"capt-pip-{w}.png"))
        if w >= 260:
            check(f"captions mini player {w}px: every word shown, each chunk inside the left half (right edge {edge:.3f} <= .5) -> capt-pip-{w}.png",
                  shown == len(WORDS) and edge <= 0.5, (shown, edge))
        else:
            check(f"captions mini player {w}px (< 260): no captions (unreadable) -> capt-pip-{w}.png", shown == 0, shown)
        ctx.close()


# the fills' state: visible cards (.vo-pf[data-prefab], not the pill), rects (stage fractions) of the intro / pill / captions /
# sites, the intro's typed handle + its on-screen px, scan line, the build beat, the sites counter / strikes / names + px
FILL = """() => { const s = document.querySelector('.vo-stage').getBoundingClientRect(), k = +document.querySelector('.vo-box').style.getPropertyValue('--k'),
  th = document.documentElement.dataset.voFull === 'theater',
  R = e => { const r = e.getBoundingClientRect(); return th ? [(r.top - s.top) / s.height, 1 - (r.right - s.left) / s.width, (r.bottom - s.top) / s.height, 1 - (r.left - s.left) / s.width]
    : [(r.left - s.left) / s.width, (r.top - s.top) / s.height, (r.right - s.left) / s.width, (r.bottom - s.top) / s.height]; },
  on = e => !!e && !e.hasAttribute('data-off') && +getComputedStyle(e).opacity > 0, fs = e => parseFloat(getComputedStyle(e).fontSize),
  i = document.querySelector('.vo-intro'), si = document.querySelector('.vo-sites'), f = document.querySelector('.vo-for'), c = document.querySelector('.vo-capt'), q = x => i.querySelector(x);
  return {cards: [...document.querySelectorAll('.vo-pf[data-prefab]')].filter(on).map(e => e.dataset.prefab), io: +getComputedStyle(i).opacity,
    intro: on(i) ? R(i) : null, pill: on(f) ? R(f.querySelector('.vo-cap')) : null, capt: c && getComputedStyle(c).display !== 'none' && c.textContent.trim() ? R(c) : null,
    typed: q('.vo-mi-t').textContent, typedpx: +(fs(q('.vo-mi-t')) * k * +q('.vo-sc-hero .vo-pg').style.getPropertyValue('--cz')).toFixed(1),
    at: q('.vo-sc-scan .vo-at').textContent, ms: q('.vo-ms').textContent, so: [...i.querySelectorAll('.vo-step')].map(e => +(+getComputedStyle(e).opacity).toFixed(2)),
    build: +getComputedStyle(q('.vo-build')).opacity, buildtxt: q('.vo-build-h').textContent, buildpx: +(fs(q('.vo-build-h')) * k).toFixed(1), titlepx: +(fs(q('.vo-intro-t')) * k).toFixed(1),
    sites: on(si) ? R(si) : null, n: si.querySelector('.vo-sites-n').textContent, struck: [...si.querySelectorAll('li')].map(l => +l.style.getPropertyValue('--k')),
    names: [...si.querySelectorAll('li b')].map(b => b.textContent), namepx: +(fs(si.querySelector('li b')) * k).toFixed(1), npx: +(fs(si.querySelector('.vo-sites-n')) * k).toFixed(1),
    tf: [getComputedStyle(i).transform, getComputedStyle(q('.vo-build')).transform, getComputedStyle(si).transform]}; }"""
FILL_SHOTS = (0.5, 3, 3.5, 6, 9.5, 10.2, 29, 32, 34.5, 35)
FILL_AT = "t => { const v = document.querySelector('video'); v.pause(); window.VideoOverlays.draw(t); return (" + FILL + ")(); }"
inter = lambda a, b: bool(a and b) and a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def fill(b, base, out, name_q, nm, intro, sites, cta):
    """the intro (intro = (in, out)) + the sites gap card (sites = (in, out)): real seeks + shots, the 0.1 s timeline, the scan hold"""
    for view, opts in (("1920", dict(viewport={"width": 1920, "height": 1080})), ("phone", VIEWPORTS["phone"]), ("theater", VIEWPORTS["phone"])):
        ctx = ctx_new(b, **opts)
        if view == "theater":
            ctx.add_init_script(IPHONE_FS)
        ext = guard(ctx, (base,))
        pg = ctx.new_page()
        errs = []
        console(pg, errs)
        lim = 11   # px on screen: portrait (k = .305) and theater (bigger) alike
        for mode, query in (("generic", ""), ("named", name_q)):
            want = handle(nm if mode == "named" else DEMO)   # named: her handle (= js herHandle(), no scan result: a slug of the name)
            goto(pg, base, query, 0.5)
            if view == "theater":
                pg.locator(".vo-fs").tap()
                pg.wait_for_function("() => document.documentElement.dataset.voFull === 'theater'", timeout=3000)
                pg.wait_for_timeout(300)
            at = {}
            for t in FILL_SHOTS:   # real seeks
                pg.evaluate("t => { const v = document.querySelector('video'); v.pause(); v.currentTime = t; }", t)
                pg.wait_for_function(SEEKED, arg=t, timeout=15000)
                pg.wait_for_timeout(250)
                f = out / f"fill-{view}-{mode}-t{t:05.2f}.png"
                (pg if view == "theater" else pg.locator(".vo-stage")).screenshot(path=str(f))
                at[t] = pg.evaluate(FILL)
                print(f"fill {view} {mode} t={t:g}: cards={at[t]['cards']} typed={at[t]['typed']!r} ms={at[t]['ms']!r} build={at[t]['build']:.2f} n={at[t]['n']!r} | said: {said(t)!r} -> {f.name}")
            v = f"{view} {mode}"
            a = at[0.5]
            check(f"intro: {v} 0.5 s: the intro alone (hero scene, field empty) -> fill-{view}-{mode}-t00.50.png", a["cards"] == ["intro"] and a["so"][0] == 1 and a["typed"] == "", (a["cards"], a["so"], a["typed"]))
            a = at[3]
            check(f"intro: {v} 3 s: typing a prefix of {want!r}", a["cards"] == ["intro"] and 0 < len(a["typed"]) < len(want) and want.startswith(a["typed"]), (a["cards"], a["typed"]))
            a = at[3.5]
            check(f"intro: {v} 3.5 s: onlyfans.com/{want} typed in full, >= {lim} px on screen ({a['typedpx']}), title >= {lim} px ({a['titlepx']})",
                  a["cards"] == ["intro"] and a["typed"] == want and a["typedpx"] >= lim and a["titlepx"] >= lim, (a["typed"], a["typedpx"], a["titlepx"]))
            a = at[6]
            check(f"intro: {v} 6 s: the scan card '@{want}', {a['ms']!r}", a["cards"] == ["intro"] and a["so"][1] == 1 and a["at"] == "@" + want and bool(PROGRESS.fullmatch(a["ms"])), (a["so"], a["at"], a["ms"]))
            a = at[9.5]
            check(f"intro: {v} 9.5 s: 'Building YOUR video…' up ({a['buildpx']} px >= {lim}), the card sliding out (opacity {a['io']:.2f})",
                  a["cards"] == ["intro"] and a["build"] == 1 and a["buildtxt"] == "Building YOUR video…" and a["buildpx"] >= lim and 0 < a["io"] < 1, (a["cards"], a["build"], a["io"]))
            a = at[10.2]
            check(f"fills: {v} 10.2 s: google alone (the intro handed off)", a["cards"] == ["google"] and a["intro"] is None, a["cards"])
            for t in (29, 32):
                a = at[t]
                check(f"sites: {v} {t} s: the sites card alone, counter rolling ({a['n']!r}), names >= {lim} px ({a['namepx']}), counter ({a['npx']})",
                      a["cards"] == ["sites"] and a["n"] not in ("0", "10,000+") and a["namepx"] >= lim and a["npx"] >= lim, (a["cards"], a["n"], a["namepx"]))
            a = at[34.5]
            check(f"sites: {v} 34.5 s: '10,000+', every site struck + Removed", a["cards"] == ["sites"] and a["n"] == "10,000+" and all(x == 1 for x in a["struck"]), (a["cards"], a["n"], a["struck"]))
            a = at[35]
            check(f"fills: {v} 35 s: the end card alone (sites out)", a["cards"] == ["cta-steps"] and a["sites"] is None, a["cards"])
            # the timeline, every 0.1 s (pure draw(t))
            iv, sv, two, ov, cap, n34 = [], [], [], [], [], None
            for i in range(0, 361):
                t = round(i * 0.1, 2)
                a = pg.evaluate(FILL_AT, t)
                if "intro" in a["cards"]:
                    iv.append(t)
                if "sites" in a["cards"]:
                    sv.append(t)
                if len(a["cards"]) > 1:
                    two.append((t, a["cards"]))
                if inter(a["pill"], a["intro"]):
                    ov.append(t)
                if a["capt"] and (a["capt"][2] > .5 + 1e-3 or inter(a["capt"], a["intro"]) or inter(a["capt"], a["sites"])):
                    cap.append((t, [round(x, 3) for x in a["capt"]]))
                if t == 34.0:
                    n34 = a["n"]
            check(f"intro: {v} timeline: visible exactly {intro[0]:g}-{intro[1]:g} s (every 0.1 s)", bool(iv) and abs(iv[0] - (intro[0] + .1)) < .06 and abs(iv[-1] - (intro[1] - .1)) < .06, iv[:1] + iv[-1:])
            check(f"sites: {v} timeline: visible exactly {sites[0]:g}-{sites[1]:g} s, counter '10,000+' by 34 s", bool(sv) and abs(sv[0] - (sites[0] + .1)) < .06 and abs(sv[-1] - (sites[1] - .1)) < .06 and n34 == "10,000+", (sv[:1] + sv[-1:], n34))
            check(f"fills: {v} timeline 0-36 s: never two right-half cards at once", not two, two[:3])
            check(f"fills: {v} timeline: the 'for NAME' pill never overlaps the intro" + (" (generic: no pill)" if mode == "generic" else ""), not ov, ov[:3])
            check(f"fills: {v} timeline: captions on the left half, never over a fill", not cap, cap[:3])
        check(f"fills: {view}: no console errors, no requests outside the local server", not errs and not ext, (errs[:2], sorted(set(ext))[:2]))
        ctx.close()
    # the scan hold: the name bar's scan still running → the take holds on the intro's "Building YOUR video…" beat
    ctx = ctx_new(b, viewport={"width": 1920, "height": 1080})
    held = []
    ctx.route("**/api/public-scan", lambda r: held.append(r))   # declared: held unanswered (the scan keeps running)
    pg = ctx.new_page()
    goto(pg, base, "", 0.5)
    pg.fill("#vo-nb-in", nm)
    pg.press("#vo-nb-in", "Enter")
    hold = intro[1] - 0.5
    try:
        pg.wait_for_function("() => { const v = document.querySelector('video'); return v.paused && v.currentTime > 1; }", timeout=(hold + 8) * 1000)
    except Exception:
        pass
    pg.wait_for_timeout(300)
    a, w = pg.evaluate(FILL), pg.evaluate("() => [document.querySelector('video').paused, +document.querySelector('video').currentTime.toFixed(2), getComputedStyle(document.querySelector('.vo-wait')).display]")
    pg.locator(".vo-stage").screenshot(path=str(out / "fill-1920-hold.png"))
    check(f"intro: scan hold: the take held at ~{hold:g} s on 'Building YOUR video…' with the wait pill -> fill-1920-hold.png",
          bool(held) and w[0] and abs(w[1] - hold) < 0.3 and a["cards"] == ["intro"] and a["build"] == 1 and w[2] == "block", (len(held), w, a["cards"], a["build"]))
    for r in held:
        r.fulfill(status=200, content_type="text/event-stream", body=SCAN_FAILED)
    pg.wait_for_timeout(300)
    ctx.close()
    # reduced motion: plain fades, no pop
    ctx = ctx_new(b, viewport={"width": 1920, "height": 1080}, reduced_motion="reduce")
    pg = ctx.new_page()
    goto(pg, base, "", 0.5)
    tf = [pg.evaluate(FILL_AT, t)["tf"] for t in (0.45, 6.9, 28.4)]
    plain = lambda x: x == "none" or re.fullmatch(r"matrix\(1, 0, 0, 1, [-\d.]+, [-\d.]+\)", x)
    check("fills: reduced motion: the intro / build beat / sites card fade, no pop or slide (plain translate)", plain(tf[0][0]) and tf[1][1] == "none" and plain(tf[2][2]), tf)
    ctx.close()


def sources(p, b, base, out):
    """the take: jack.webm plays in Chromium, 56.9 s (= transcript.json's duration); WebKit with jack.webm unreachable
    (declared: routed to 404, as an iPhone that cannot play WebM skips it) plays jack.mp4, same length"""
    dur = TRANSCRIPT["duration"]
    wk = p.webkit.launch()
    for eng, br, block in (("chromium", b, False), ("webkit", wk, True), ("webkit-as-is", wk, False)):
        ctx = br.new_context(viewport={"width": 1280, "height": 720})
        ctx.route("**/api/public-scan", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=SCAN_FAILED))
        if block:
            ctx.route("**/video/jack.webm", lambda r: r.fulfill(status=404, body="no webm here"))
        pg = ctx.new_page()
        pg.goto(f"{base}video/")
        try:
            pg.wait_for_function("() => document.querySelector('video').readyState >= 1", timeout=20000)
            pg.evaluate("() => { const v = document.querySelector('video'); v.muted = true; return v.play(); }")
            pg.wait_for_function("() => document.querySelector('video').currentTime > 1", timeout=20000)
            st = pg.evaluate("() => { const v = document.querySelector('video'); return [v.currentSrc, v.duration, v.currentTime, v.videoWidth, v.videoHeight]; }")
        except Exception as e:
            st = ["", 0, 0, 0, 0, str(e)[:200]]
        pg.screenshot(path=str(out / f"source-{eng}.png"))
        want = "/video/jack.mp4" if block else "/video/jack.webm" if eng == "chromium" else "/video/jack."
        print(f"source {eng}: {st}")
        check(f"source {eng}{' (webm blocked, declared)' if block else ''}: plays {want.rsplit('/', 1)[1]}*, {st[1]:.2f} s ~ the take's {dur} s, advancing",
              want in (st[0] or "") and abs(st[1] - dur) < 0.2 and st[2] > 1, st)
        ctx.close()
    wk.close()


G_REMOVED_OLD = 12.86   # google's removed cue before Jack's ask (PR #81: on "removed"); now 0.5 s sooner, while he says it
OVERT = ("OnlyFans leaks", "nude photos", "leaked videos", "nudes: full leak")   # = js OVERT
GSLIDE = """([pid, t]) => { if (t != null) window.VideoOverlays.draw(t); const e = document.querySelector(`.vo-pf[data-prefab="${pid}"]`), m = new DOMMatrix(getComputedStyle(e).transform);
  return [e.hasAttribute('data-off'), +(m.e + e.offsetWidth / 2).toFixed(2), +m.a.toFixed(4), +m.d.toFixed(4), +getComputedStyle(e).opacity]; }"""
GTEXT = """() => { const q = (c, s) => [...document.querySelectorAll(`.vo-pf[data-prefab="${c}"] ${s}`)].map(e => e.textContent.replace(/\\s+/g, ' ').trim());
  return {q: [q('google', '.vo-q')[0], q('google-images', '.vo-q')[0]], g: q('google', '.rm-live .m-title'), gh: q('google', '.rm-live .m-site'),
          gi: q('google-images', '.vo-serp .m-title'), gih: q('google-images', '.vo-serp .m-site'), mode: document.documentElement.dataset.voMode,
          cue: +document.querySelector('.vo-pf[data-prefab="google"]').getAttribute('data-cue-removed')}; }"""
GWIPE = """([a, b]) => { const e = document.querySelector('.vo-pf[data-prefab="google"]'); document.querySelector('video').pause();
  for (let i = Math.round(a * 100); i <= Math.round(b * 100); i++) { window.VideoOverlays.draw(i / 100); if (+e.style.getPropertyValue('--p') < 100) return i / 100; } return null; }"""
GSTATE = """([a, b, dt]) => { const out = [], txt = e => e.textContent.replace(/\\s+/g, ' '); document.querySelector('video').pause();
  for (let i = Math.round(a / dt); i * dt <= b + 1e-9; i++) { const t = +(i * dt).toFixed(2); window.VideoOverlays.draw(t);
    out.push([t, [...document.querySelectorAll('.vo-pf')].filter(e => !e.hasAttribute('data-off')).map(e => [e.dataset.prefab || e.className, e.getAttribute('style'),
      [...e.querySelectorAll('[style]')].map(x => x.getAttribute('style')).join('|'), /^google/.test(e.dataset.prefab || '') ? '' : txt(e)]),
      txt(document.querySelector('.vo-capt'))]); }
  return out; }"""


def gsearch(b, base, out, cues, raw_file, base_ref):
    """the Google + Google Images cards up to the images' removal: query, overt titles, slide-in entrance, the earlier clear"""
    raw = json.loads(pathlib.Path(raw_file).read_text(encoding="utf-8")) if raw_file else None
    X = hers_expect(raw) if raw else None
    body = json.dumps(raw).encode() if raw else b"{}"

    def api(r):   # declared bypass, wire boundary: scan-result = her saved result (no production), thumb / media 404
        u = urllib.parse.urlsplit(r.request.url)
        if u.path.startswith("/api/scan-result/") and raw and u.path.endswith("/" + PROD_SLUG):
            return r.fulfill(body=body, content_type="application/json")
        return r.fulfill(status=404, body="{}")

    def context(opts, rm=False, ref=None):
        ctx = ctx_new(b, **opts, **({"reduced_motion": "reduce"} if rm else {}))
        if ref:   # declared: REF's page / js / css (git show), the rest from the worktree
            for path, pat, ct in (("site/video/index.html", lambda u: urllib.parse.urlsplit(u).path.endswith("/video/"), "text/html"),
                                  ("site/js/video-overlays.js", "**/js/video-overlays.js", "application/javascript"), ("site/css/video.css", "**/css/video.css", "text/css")):
                src = subprocess.run(["git", "-C", str(ROOT), "show", f"{ref}:{path}"], capture_output=True, text=True, check=True).stdout
                ctx.route(pat, (lambda src, ct: lambda r: r.fulfill(body=src, content_type=ct))(src, ct))
        for pat in ("**/api/scan-result/**", "**/api/thumb?**", "**/api/media/**"):
            ctx.route(pat, api)
        return ctx, guard(ctx, (base,))

    def named(pg):
        try:
            pg.wait_for_function("() => document.documentElement.dataset.voMode === 'named'", timeout=10000)
        except Exception:
            pass
        pg.wait_for_timeout(300)

    g, gi = cues["google"], cues["google-images"]
    modes = [("generic", "", GENERIC)] + ([("hers", f"r={PROD_SLUG}", X["name"])] if X else [])
    for vp, opts in (("1920", dict(viewport={"width": 1920, "height": 1080})), ("phone", VIEWPORTS["phone"])):
        for mode, query, nm in modes:
            ctx, ext = context(opts)
            pg = ctx.new_page()
            errs = []
            console(pg, errs)
            for t in (10.1, 10.2, 11, 12, g[1], 12.9, 13.6, 14.9, 15.4):
                goto(pg, base, query, t)
                if mode == "hers":
                    named(pg)
                f = out / f"ganim-{vp}-{mode}-t{t:05.2f}.png"
                (pg if vp == "1920" else pg.locator(".vo-stage")).screenshot(path=str(f))
                print(f"google anim {vp} {mode} t={t:g}: {[s[0] for s in pg.evaluate(VISIBLE)]} | said: {said(t)!r} -> {f.name}")
            tx = pg.evaluate(GTEXT)
            lbl = f"{vp} {mode}"
            check(f"google query ({lbl}): both search boxes read {nm + ' nude leaks'!r}", tx["q"] == [nm + " nude leaks"] * 2, tx["q"])
            hosts = prod_expect(raw)["rows"][:4] if mode == "hers" else None
            want = [f"{nm} {o}" for o in OVERT]
            check(f"google titles ({lbl}): Google rows {want}, Google Images rows the first 2" + (f", her hosts {hosts}" if hosts else ""),
                  tx["g"] == want and tx["gi"] == want[:2] and (not hosts or tx["gh"] == hosts and tx["gih"] == hosts[:2])
                  and not any(re.search(r"https?:|www\.|/", x) for x in tx["g"] + tx["gh"] + tx["gi"] + tx["gih"]), tx)
            if vp == "1920":
                pg.evaluate(DRAW, g[0])
                sl = {pid: [pg.evaluate(GSLIDE, [pid, cues[pid][0] + d]) for d in (0.02, 0.1, 0.2, 0.3, 0.45, 0.6)] for pid in ("google", "google-images", "x")}
                ok = all(s[0][1] > 100 and s[-2][1] == 0 and s[-1][1] == 0 and all(x[2] == 1 and x[3] == 1 and not x[0] for x in s) for s in (sl["google"], sl["google-images"]))
                check(f"google slide ({lbl}): google + google-images slide in from the right (translateX > 100 px at live + 0.02 → 0 by + 0.45), no scale pop",
                      ok, {k: [(x[1], x[2]) for x in v] for k, v in sl.items()})
                check(f"google slide ({lbl}): x still pops (scale != 1 at live + 0.1: scope = google / google-images only)", sl["x"][1][2] != 1, [x[2] for x in sl["x"]])
                w0 = pg.evaluate(GWIPE, [g[0], g[1] + 1.5])
                ri = next(i for i, w in enumerate(WORDS) if w[1] > g[0] and w[0].lower().startswith("removed"))
                they, rmw = WORDS[ri - 2], WORDS[ri]
                check(f"google timing ({lbl}): removed cue {tx['cue']} = {G_REMOVED_OLD} − 0.5", abs(tx["cue"] - (G_REMOVED_OLD - 0.5)) < 0.005, tx["cue"])
                check(f"google timing ({lbl}): the wipe starts at removed + 0.25 (measured {w0}, ease-in: <= + 0.05), while he says {they[0]!r} ({they[1]}) .. {rmw[0]!r} ({rmw[1]}), done by {rmw[2] + 0.4:.2f}",
                      w0 is not None and abs(w0 - (tx["cue"] + 0.25)) <= 0.05 and they[1] <= w0 <= rmw[1] and w0 + 0.95 <= rmw[2] + 0.4, (w0, they, rmw))
            check(f"google ({lbl}): mode {('named' if mode == 'hers' else 'generic')!r}, no console errors (hers: but the declared thumb / media 404s), no requests outside the local server",
                  tx["mode"] == ("named" if mode == "hers" else "generic") and not ext and not [e for e in errs if not (mode == "hers" and "status of 404" in e)], (tx["mode"], errs[:2], ext[:2]))
            ctx.close()
    ctx, _ = context(dict(viewport={"width": 1440, "height": 900}), rm=True)
    pg = ctx.new_page()
    goto(pg, base, "", round(g[0] + 0.1, 2))
    s = pg.evaluate(GSLIDE, ["google", None])
    check("google slide (reduced motion): no offset, no scale at live + 0.1", s[1] == 0 and s[2] == 1, s)
    ctx.close()
    if base_ref:
        a0, end = round(gi[0] + 0.5, 2), round(END - 0.05, 2)   # its entrance (0.45 s) done
        for mode, query, _ in modes:
            st = []
            for ref in (base_ref, None):
                ctx, _ = context(dict(viewport={"width": 1920, "height": 1080}), ref=ref)
                pg = ctx.new_page()
                goto(pg, base, query, a0)
                if mode == "hers":
                    named(pg)
                st.append(pg.evaluate(GSTATE, [a0, end, 0.05]))
                ctx.close()
            diff = [(x[0], x, y) for x, y in zip(*st) if x != y]
            (out / f"google-post-{mode}.json").write_text(json.dumps({"base": base_ref, "n": len(st[1]), "diff": diff[:5]}, indent=1))
            check(f"google post ({mode}): {a0} .. {end} s every card's state + texts (but google / google-images) + captions == {base_ref} ({len(st[1])} frames)",
                  len(st[0]) == len(st[1]) > 100 and not diff, [d[0] for d in diff][:20])


BLURS = """() => { const f = i => [i.className, (i.getAttribute('src') || '').slice(-40), i.naturalWidth, getComputedStyle(i).filter, getComputedStyle(i).transform];
  return {cards: [...document.querySelectorAll('.vo-pf[data-prefab]')].map(e => [e.dataset.prefab, [...e.querySelectorAll('.rm-img, .vo-real')].map(f)]),
          stray: [...document.querySelectorAll('.rm-img, .vo-real')].filter(i => !i.closest('.vo-pf[data-prefab]')).map(f),
          own: [...document.querySelectorAll('.vo-own')].map(f), mode: document.documentElement.dataset.voMode}; }"""


def blur(b, base, out, raw_file, base_ref):
    """every leak image on every video card: computed blur exactly BLUR_PX (no image load needed; her thumbs = a local photo, declared)"""
    raw = json.loads(pathlib.Path(raw_file).read_text(encoding="utf-8")) if raw_file else None
    body = json.dumps(raw).encode() if raw else b"{}"
    photo = (ROOT / "site/img/removals/editorial-01.webp").read_bytes()

    def api(r):   # declared bypass, wire boundary: scan-result = her saved result, every thumb = one local photo, media 404
        u = urllib.parse.urlsplit(r.request.url)
        if u.path.startswith("/api/scan-result/") and raw and u.path.endswith("/" + PROD_SLUG):
            return r.fulfill(body=body, content_type="application/json")
        if u.path == "/api/thumb":
            return r.fulfill(body=photo, content_type="image/webp")
        return r.fulfill(status=404, body="{}")

    def page(opts, ref=None):
        ctx = ctx_new(b, **opts)
        if ref:   # declared: REF's css/video.css (git show)
            src = subprocess.run(["git", "-C", str(ROOT), "show", f"{ref}:site/css/video.css"], capture_output=True, text=True, check=True).stdout
            ctx.route("**/css/video.css", lambda r: r.fulfill(body=src, content_type="text/css"))
        for pat in ("**/api/scan-result/**", "**/api/thumb?**", "**/api/media/**"):
            ctx.route(pat, api)
        return ctx, guard(ctx, (base,))

    def load(pg, query, t, mode):
        goto(pg, base, query, t)
        if mode == "hers":
            try:
                pg.wait_for_function("() => document.documentElement.dataset.voMode === 'named' && document.querySelectorAll('.vo-real').length >= 9", timeout=15000)
            except Exception:
                pass
            pg.wait_for_timeout(300)
        return pg.evaluate(BLURS)

    modes = [("generic", "")] + ([("hers", f"r={PROD_SLUG}")] if raw else [])
    for vp, opts in (("1920", dict(viewport={"width": 1920, "height": 1080})), ("phone", VIEWPORTS["phone"])):
        for mode, query in modes:
            ctx, ext = page(opts)
            pg = ctx.new_page()
            errs = []
            console(pg, errs)
            for t in (11, 15.5, 47):
                s = load(pg, query, t, mode)
                f = out / f"blur-{vp}-{mode}-t{t}.png"
                (pg if vp == "1920" else pg.locator(".vo-stage")).screenshot(path=str(f))
                print(f"blur {vp} {mode} t={t}: {[s[0] for s in pg.evaluate(VISIBLE)]} -> {f.name}")
            lbl = f"{vp} {mode}"
            imgs = [(c, x) for c, xs in s["cards"] for x in xs] + [("-", x) for x in s["stray"]]
            per = {c: len(xs) for c, xs in s["cards"] if xs}
            bad = [(c, x[0], x[1], x[3]) for c, x in imgs if BLUR(x[3]) != BLUR_PX or "saturate(0.95)" not in x[3]]
            real = [x for c, x in imgs if "vo-real" in x[0]]
            need = {"google", "google-images"} | ({"cta-steps"} if mode == "hers" else set())
            check(f"blur ({lbl}): every leak image on every card ({len(imgs)} on {per}{', stray ' + str(len(s['stray'])) if s['stray'] else ''}) = blur({BLUR_PX}px) saturate(0.95)",
                  len(imgs) >= 13 and need <= set(per) and not bad, bad[:6])
            if mode == "hers":
                check(f"blur ({lbl}): all {len(real)} .vo-real (intro + end-card report) = her (local stand-in) photos loaded, blur({BLUR_PX}px), scale(1.2) kept",
                      len(real) >= 18 and all(x[2] > 0 and BLUR(x[3]) == BLUR_PX and x[4].startswith("matrix(1.2, 0, 0, 1.2") for x in real), [(x[2], x[3], x[4]) for x in real][:4])
            check(f"blur ({lbl}): the after state's {len(s['own'])} own photos (.vo-own) unblurred", len(s["own"]) >= 4 and not [x for x in s["own"] if "blur" in x[3]], [x[3] for x in s["own"]][:4])
            check(f"blur ({lbl}): mode {('named' if mode == 'hers' else 'generic')!r}, no console errors (but the declared media 404s), no requests outside the local server",
                  s["mode"] == ("named" if mode == "hers" else "generic") and not ext and not [e for e in errs if "status of 404" not in e], (s["mode"], errs[:2], ext[:2]))
            ctx.close()
    if base_ref:   # the same images' computed filters vs REF's css: only the blur radius moved
        for mode, query in modes:
            st = []
            for ref in (base_ref, None):
                ctx, _ = page(dict(viewport={"width": 1920, "height": 1080}), ref=ref)
                pg = ctx.new_page()
                st.append(load(pg, query, 47, mode))
                ctx.close()
            norm = lambda s, px: [[c, [[x[0], x[1], x[3].replace(f"blur({px}px)", "blur(R)"), x[4]] for x in xs]] for c, xs in s["cards"]] + [s["stray"], [x[3] for x in s["own"]]]
            was = sorted({x[3] for c, xs in st[0]["cards"] for x in xs})
            check(f"blur base ({mode}): computed filters == {base_ref}'s ({was}) but blur(5px) → blur({BLUR_PX}px), same images / transforms / own photos",
                  norm(st[0], 5) == norm(st[1], BLUR_PX) and was == ["blur(5px) saturate(0.95)"], was)


PROOFS = re.compile(thin.NAMED.pattern + r"|^(?:proof-|full-frame-|frame-1920-(?:generic-google-live|named-mega-removed|generic-cta\.|swap-))")   # the shots the docstring above calls proofs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--name", default="Jaka Basej")
    ap.add_argument("--break-thumbs", action="store_true")
    ap.add_argument("--break-steps", action="store_true")
    ap.add_argument("--break-swap", action="store_true")
    ap.add_argument("--break-demo", action="store_true")
    ap.add_argument("--break-full", action="store_true")
    ap.add_argument("--break-named", action="store_true")
    ap.add_argument("--break-img", action="store_true")
    ap.add_argument("--break-logos", action="store_true")
    ap.add_argument("--break-persona", action="store_true")
    ap.add_argument("--skip-prod", action="store_true")
    ap.add_argument("--break-captions", action="store_true")
    ap.add_argument("--break-voice", action="store_true")
    ap.add_argument("--break-intro", action="store_true")
    ap.add_argument("--break-hers", action="store_true")
    ap.add_argument("--break-herend", action="store_true")
    ap.add_argument("--break-burst", action="store_true")
    ap.add_argument("--hers-raw", help="her saved scan result (JSON) instead of the read-only production GET")
    ap.add_argument("--only", choices=["prod", "captions", "voice", "fill", "hers", "google", "blur"], help="run only this part (iteration)")
    ap.add_argument("--base", help="google post: compare the cards after google-images' entrance with this git ref's page / js / css")
    ap.add_argument("--break-gtime", action="store_true")
    ap.add_argument("--break-blur", action="store_true")
    ap.add_argument("--keep-all", action="store_true", help="every frame of a green run too (scan_e2e/thin.py)")
    a = ap.parse_args()
    t0, rc = time.time(), run(a)
    out = pathlib.Path(a.out).expanduser()
    if not rc and not a.keep_all and not any(v for k, v in vars(a).items() if k.startswith("break_")):
        print("thinned", thin.thin(out, t0, thin.ends(out, t0), PROOFS), "frames of a green run: --keep-all keeps them")
    return rc


def run(a):
    out = pathlib.Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    html = (ROOT / "site/video/index.html").read_text(encoding="utf-8")
    if a.break_steps:   # wire boundary: index.html minus the cta-steps animation (the end card + form stay)
        broken, k = re.subn(r'\n        <div class="vo-steps".*?\n        </div>\n(?=        <form class="vo-cta-f")', "\n", html, flags=re.S)
        assert k == 1, "break: .vo-steps block not found"
        BREAK["steps"] = (lambda u: urllib.parse.urlsplit(u).path.endswith("/video/"), broken, "text/html")
    if a.break_swap:   # wire boundary: video-overlays.js minus the submit's in-place rebuild (validation stays)
        js = (ROOT / "site/js/video-overlays.js").read_text(encoding="utf-8")
        broken, k = re.subn(r"(inp\.blur\(\);)\n\s*rebuild\(n\);", r"\1", js)
        assert k == 1, "break: rebuild(n) call not found"
        BREAK["swap"] = ("**/js/video-overlays.js", broken, "application/javascript")
    if a.break_demo:   # wire boundary: video-overlays.js with the old demo name
        js = (ROOT / "site/js/video-overlays.js").read_text(encoding="utf-8")
        broken, k = re.subn(r"DEMO = '[^']*'", "DEMO = 'Orla Brennick'", js)
        assert k == 1, "break: DEMO not found"
        BREAK["demo"] = ("**/js/video-overlays.js", broken, "application/javascript")
    if a.break_full:   # wire boundary: css/video.css + the old split layout (video in the left half, an opaque panel behind the cards)
        css = (ROOT / "site/css/video.css").read_text(encoding="utf-8") + "\n.vo-video { width: 50%; object-fit: contain; } .vo-over { background: #353b43; }\n"
        BREAK["full"] = ("**/css/video.css", css, "text/css")
    if a.break_named:   # wire boundary: video-overlays.js with named mode's cta-steps off (the old "generic only")
        js = (ROOT / "site/js/video-overlays.js").read_text(encoding="utf-8")
        broken, k = re.subn(r"ctac = cta\(true\);", "ctac = null;", js)
        assert k == 1, "break: ctac = cta(true) not found"
        BREAK["named"] = ("**/js/video-overlays.js", broken, "application/javascript")
    if a.break_img:   # wire boundary: video-overlays.js with report()'s image field wrong (it.title for it.src)
        js = (ROOT / "site/js/video-overlays.js").read_text(encoding="utf-8")
        broken, k = re.subn(r"return it\.src; \}\)\.filter", "return it.title; }).filter", js)
        assert k == 1, "break: report()'s it.src not found"
        BREAK["img"] = ("**/js/video-overlays.js", broken, "application/javascript")
    if a.break_logos:   # wire boundary: video-overlays.js with the people-photo test off (every loaded thumb kept)
        js = (ROOT / "site/js/video-overlays.js").read_text(encoding="utf-8")
        broken, k = re.subn(r"E\.photo\(u, ", "(function (s, f) { var im = new Image(); im.onload = function () { f(im.naturalWidth >= 16 && im.naturalHeight >= 16); }; "
                            "im.onerror = function () { f(false); }; im.src = E.thumb(s); })(u, ", js)   # E.photo minus its E.isPhoto
        assert k == 1, "break: photoOnly's E.photo(u, …) not found"
        BREAK["logos"] = ("**/js/video-overlays.js", broken, "application/javascript")
    if a.break_persona:   # wire boundary: video-overlays.js with the old generic placeholder
        js = (ROOT / "site/js/video-overlays.js").read_text(encoding="utf-8")
        broken, k = re.subn(r"GENERIC = '[^']*'", "GENERIC = 'Your name'", js)
        assert k == 1, "break: GENERIC not found"
        BREAK["persona"] = ("**/js/video-overlays.js", broken, "application/javascript")
    if a.break_captions:   # wire boundary: transcript.json with every word 2 s late (captions out of sync)
        tj = dict(TRANSCRIPT, words=[[w[0], round(w[1] + 2, 2), round(w[2] + 2, 2)] for w in WORDS])
        BREAK["captions"] = ("**/video/transcript.json", json.dumps(tj), "application/json")
    if a.break_voice:   # wire boundary: video-overlays.js with the old AI overvoice back (the name spoken once, 0.5 s in)
        js = (ROOT / "site/js/video-overlays.js").read_text(encoding="utf-8")
        broken, k = re.subn(r"draw\(t\); sounds\(t\);", "draw(t); if (who && t > 0.5 && !window.__v) { window.__v = 1; "
                            "speechSynthesis.speak(new SpeechSynthesisUtterance(who)); } sounds(t);", js)
        assert k == 1, "break: the play loop's draw(t); sounds(t); not found"
        BREAK["voice"] = ("**/js/video-overlays.js", broken, "application/javascript")
    if a.break_intro:   # wire boundary: index.html with the intro's own cues removed (the intro never shows)
        broken, k = re.subn(r'(data-prefab="intro") data-cue-in="[\d.]+" data-cue-out="[\d.]+"', r"\1", BREAK["steps"][1] if "steps" in BREAK else html)
        assert k == 1, "break: the intro's data-cue-in / -out not found"
        BREAK["intro"] = (lambda u: urllib.parse.urlsplit(u).path.endswith("/video/"), broken, "text/html")
    if a.break_hers:   # wire boundary: video-overlays.js with a loaded result never applied (?r= / the last scan stay generic)
        js = (ROOT / "site/js/video-overlays.js").read_text(encoding="utf-8")
        broken, k = re.subn(r"if \(g === gen && \(who === null \|\| real\)\) useResult\(raw\);", "", js)
        assert k == 1, "break: load()'s useResult(raw) not found"
        BREAK["hers"] = ("**/js/video-overlays.js", broken, "application/javascript")
    if a.break_herend:   # wire boundary: video-overlays.js with the old demo end in personalized mode (jakabasej typed, the placeholder report)
        js = BREAK["hers"][1] if "hers" in BREAK else (ROOT / "site/js/video-overlays.js").read_text(encoding="utf-8")
        broken, k = re.subn(r"rr = c\.named \? real : null, bs = box\.style, h = c\.named \? herHandle\(\) : handle\(demoName\(\)\)", "rr = null, bs = box.style, h = handle(c.named ? DEMO : demoName())", js)
        assert k == 1, "break: steps()' rr / h not found"
        BREAK["herend"] = ("**/js/video-overlays.js", broken, "application/javascript")
    if a.break_burst:   # wire boundary: video-overlays.js's photoOnly unpaced (every probe at once)
        js = (ROOT / "site/js/video-overlays.js").read_text(encoding="utf-8")
        broken, k = re.subn(r"for \(var k = 0; k < LANES; k\+\+\) lane\(\);", "for (var k = 0; k < list.length; k++) lane();", js)
        assert k == 1, "break: photoOnly's lanes not found"
        BREAK["burst"] = ("**/js/video-overlays.js", broken, "application/javascript")
    if a.break_gtime:   # wire boundary: index.html with google's old removed cue (the page's cues and these checks' both)
        html, k = re.subn(r'(data-prefab="google" data-cue-live="[\d.]+" data-cue-removed=")[\d.]+"', r'\g<1>%s"' % G_REMOVED_OLD, BREAK["steps"][1] if "steps" in BREAK else html)
        assert k == 1, "break: google's data-cue-removed not found"
        BREAK["gtime"] = (lambda u: urllib.parse.urlsplit(u).path.endswith("/video/"), html, "text/html")
    if a.break_blur:   # wire boundary: css/video.css with the old blur(5px) on .vo .rm-img / .vo-real
        css, k = re.subn(r"filter: blur\(2px\)", "filter: blur(5px)", BREAK["full"][1] if "full" in BREAK else (ROOT / "site/css/video.css").read_text(encoding="utf-8"))
        assert k == 2, f"break: {k} blur(2px) in video.css"
        BREAK["blur"] = ("**/css/video.css", css, "text/css")
    fl = {k: tuple(map(float, re.search(r'data-prefab="%s" data-cue-in="([\d.]+)" data-cue-out="([\d.]+)"' % k, html).groups())) for k in ("intro", "sites")}
    pf = [(m[1], float(m[2]), float(m[3]), float(m[4])) for m in re.finditer(
        r'data-prefab="([\w-]+)" data-cue-live="([\d.]+)" data-cue-removed="([\d.]+)" data-cue-out="([\d.]+)"', html)]
    tap = re.search(r'data-prefab="google-images"[^>]*data-cue-tap="([\d.]+)"', html)
    cues = {p[0]: p[1:] for p in pf}
    cues["say"] = stage_attr(html, "data-cue-say")
    cues["intro"] = fl["intro"]
    cta = stage_attr(html, "data-cue-cta") or cues["say"]
    name_q = "name=" + urllib.parse.quote(a.name)
    with serve() as base, sync_playwright() as p:
        b = p.chromium.launch()
        if a.only == "captions":
            captions(b, base, out, name_q)
            sources(p, b, base, out)
            for f in fails:
                print("FAIL", f)
            return 1 if fails else 0
        if a.only == "voice":
            speech(b, base, out, a.name, cues)
            swap(b, base, out, cues, cta, "desktop", SWAP_VIEWPORTS["desktop"])
            for f in fails:
                print("FAIL", f)
            return 1 if fails else 0
        if a.only == "fill":
            fill(b, base, out, name_q, a.name, fl["intro"], fl["sites"], cta)
            for f in fails:
                print("FAIL", f)
            return 1 if fails else 0
        if a.only == "hers":
            hers(b, base, out, a.hers_raw, a.skip_prod)
            for f in fails:
                print("FAIL", f)
            return 1 if fails else 0
        if a.only == "google":
            gsearch(b, base, out, cues, a.hers_raw, a.base)
            for f in fails:
                print("FAIL", f)
            return 1 if fails else 0
        if a.only == "blur":
            blur(b, base, out, a.hers_raw, a.base)
            for f in fails:
                print("FAIL", f)
            return 1 if fails else 0
        if a.only == "prod":
            prod(b, base, out, cues, cta)
            for f in fails:
                print("FAIL", f)
            return 1 if fails else 0
        for mode, query, who in (("generic", "", GENERIC), ("named", name_q, a.name)):
            for vp, opts in VIEWPORTS.items():
                ctx = ctx_new(b, **opts)
                seen = []
                ext = guard(ctx, (base,), seen)
                pg = ctx.new_page()
                errs = []
                console(pg, errs)
                for pid, live, rem, off in pf:
                    tl = round(live + min(1.3, rem - live - 0.1), 2)
                    if pid == "google-images":   # after the tap + grid
                        tl = round(min(rem - 0.1, max(tl, (float(tap[1]) if tap else live + 0.6) + 1.0)), 2)
                    for state, t in (("live", tl), ("removed", min(rem + 2.0, off - 0.45))):
                        goto(pg, base, query, t)
                        shot = out / f"{vp}-{mode}-t{t:05.2f}-{pid}-{state}.png"
                        if vp == "phone":
                            pg.locator(".vo-stage").screenshot(path=str(shot))
                        else:
                            pg.screenshot(path=str(shot))
                        st = pg.evaluate(VISIBLE)
                        vis = [s[0] for s in st]
                        ok = vis == [pid] and float(st[0][1]) == (100 if state == "live" else 0) and (mode == "generic" or who in st[0][2])   # generic name: persona()
                        box = [round(x, 3) for x in st[0][3]] if st else None
                        corner = (box and box[0] >= .5 and box[1] >= 0 and box[2] <= 1 and box[3] <= 1
                                                   and abs((box[1] + box[3]) / 2 - .5) <= .05)
                        print(f"{vp} {mode} t={t:g} {pid} {state}: visible={vis} p={[s[1] for s in st]} box={box} rolls={st[0][4] if st else None} | said: {said(t)!r} -> {shot.name}")
                        if not ok:
                            check(f"{vp} {mode} t={t:g}: only {pid} {state}" + (f" with {who!r}" if mode == "named" else ""), False, [(s[0], s[1]) for s in st])
                        if not corner:
                            check(f"{vp} {mode} t={t:g}: {pid} on the right half, vertically centred (left >= .5, centre .5 +- .05)", False, box)
                        if (pid, state) in COUNT and st and COUNT[(pid, state)] not in st[0][4]:
                            check(f"{vp} {mode} t={t:g}: {pid} {state} counter reads {COUNT[(pid, state)]!r}", False, st[0][4])
                        if state == "removed" and pid in ("google", "google-images"):
                            txt, imgs = pg.evaluate(AFTER)
                            check(f"{vp} {mode} t={t:g}: {pid} after state = {who}'s site + Instagram"
                                  + (", >= 4 unblurred own photos" if pid == "google-images" else "") + ", no leak host",
                                  after_ok(pid, who if mode == "named" else None, txt, imgs), (txt[:160], imgs[:2]))
                        if state == "removed" and pid == "google-images":   # generic persona JakaBasej = he; a named creator = her
                            cap = pg.locator(".vo-gi .vo-st-gone").inner_text().strip()
                            want = "No leaks: only " + ("his" if mode == "generic" else "her") + " own photos"
                            check(f"{vp} {mode} t={t:g}: google-images after caption reads {want!r}", cap == want, cap)
                # the end card / pill
                t = round(cta + 0.6, 2)
                goto(pg, base, query, t)
                shot = out / f"{vp}-{mode}-t{t:05.2f}-end.png"
                (pg.locator(".vo-stage") if vp == "phone" else pg).screenshot(path=str(shot))
                st = pg.evaluate(VISIBLE)
                got = [(s[0], s[2].strip()) for s in st]
                ok = len(st) == 1 and st[0][0] == "cta-steps" and (CTA_TEXT in st[0][2] if mode == "generic" else (pg.evaluate(STEPS) or {}).get("chrome") == ["none", "none"])
                if st:   # both widths: the right half
                    box = st[0][3]
                    ok = ok and box[0] >= .5 and box[2] <= 1 and abs((box[1] + box[3]) / 2 - .5) <= .05
                check(f"{'' if mode == 'generic' else 'named flow: '}{vp} {mode} t={t:g}: end = {'the Type-your-name card + form' if mode == 'generic' else 'cta-steps without title / form, no pill'}, right half -> {shot.name}", ok, got)
                mode_attr = pg.evaluate("() => document.documentElement.dataset.voMode")
                if vp == "desktop":
                    tx = pg.evaluate("() => document.documentElement.textContent + ' ' + document.title")
                    check(f"{vp} {mode}: no 'Tessa' in the DOM text" + (f", {a.name!r} shown" if mode == "named" else ""),
                          "tessa" not in tx.lower() and (mode == "generic" or a.name in tx), re.findall(r".{20}tessa.{20}", tx, re.I)[:2])
                check(f"{vp} {mode}: html[data-vo-mode={mode}]", mode_attr == mode, mode_attr)
                check(f"{vp} {mode}: no console errors", not errs, errs)
                check(f"{vp} {mode}: no requests outside the local server", not ext, sorted(set(ext)))
                src = pg.evaluate("() => document.querySelector('video').currentSrc")
                check(f"{vp} {mode}: jack.webm is the playing source", (src or "").endswith("/video/jack.webm"), src)
                if vp == "desktop" and mode == "named":   # defaults stay for ?name= (no scan photos without a scan)
                    im = pg.evaluate(IMGS)
                    check(f"?name={a.name}: all {len(im)} .rm-img keep the default photos (video/img/leak-*), blurred",
                          len(im) == 13 and all(s.startswith("img/leak-") and "blur(" in f for s, w, f in im), im[:3])
                if vp == "desktop" and mode == "generic":   # the video's own default photos (site/video/img/): leak-* blurred, own-* not
                    im, own = pg.evaluate(IMGS), pg.evaluate(OWN)
                    check(f"generic: {len(im)} .rm-img = video/img/leak-*, loaded, blurred; {len(own)} .vo-own = video/img/own-*, loaded, unblurred",
                          len(im) == 13 and len(own) == 6 and all(s.startswith("img/leak-") and w > 0 and "blur(" in f for s, w, f in im)
                          and all(s.startswith("img/own-") and w > 0 and "blur" not in f for s, w, f in own), (im[:2], own[:2]))
                    vimg = sorted({u for u in seen if "/video/img/" in u})
                    st = {u.rsplit("/", 1)[1]: pg.request.get(u).status for u in vimg}
                    old = sorted({u for u in seen if "/img/removals/" in u or "/assets/phone/" in u})
                    check(f"generic: requests: {len(vimg)} video/img files, all 200 {st}; none of the landing's img/removals / assets/phone",
                          len(vimg) == 12 and set(st.values()) == {200} and not old, (st, old[:3]))
                    # the form: trimmed + collapsed name → ?name=; an invalid one stays
                    if check("end card form: #vo-name present", pg.locator("#vo-name").count() == 1):
                        pg.fill("#vo-name", "<b>")
                        pg.press("#vo-name", "Enter")
                        pg.wait_for_timeout(300)
                        msg = pg.evaluate("() => document.querySelector('#vo-name').validationMessage")
                        check("end card form: invalid name '<b>' → no rebuild, a message", "name=" not in pg.url and bool(msg), (pg.url, msg))
                        pg.fill("#vo-name", f"  {a.name}   Q ")
                        pg.screenshot(path=str(out / "desktop-generic-end-form-typed.png"))
                        pg.evaluate("() => { window.__same = 1; }")
                        pg.press("#vo-name", "Enter")
                        want = f"/video/?name={urllib.parse.quote(a.name + ' Q')}"
                        try:
                            pg.wait_for_function("u => location.href.endsWith(u) && document.documentElement.dataset.voMode === 'named'", arg=want, timeout=4000)
                        except Exception:
                            pass
                        nm = pg.evaluate("() => [document.querySelector('[data-vo=name]').textContent, window.__same === 1]")
                        check(f"swap: end card form: '{a.name} Q' → in place (same document), {want}, named mode, texts", pg.url.endswith(want) and nm == [f"{a.name} Q", True], (pg.url, nm))
                        pg.screenshot(path=str(out / "desktop-generic-end-form-submitted.png"))
                    # the snap: word cards, shake, flash
                    g = cues["google"]
                    goto(pg, base, "", round(g[0] + 0.25, 2))
                    fx = pg.evaluate(FX, "google")
                    check(f"word card at google live + 0.25: 'GOOGLE' popped", fx[2][0] == "GOOGLE" and fx[2][1] > .9, fx[2])
                    goto(pg, base, "", round(g[1] + 0.08, 2))
                    pg.screenshot(path=str(out / "desktop-generic-snap-google.png"))
                    fx = pg.evaluate(FX, "google")
                    check("snap at google removed + 0.08: 'GONE.' card, shake offset, flash on", fx[3][0] == "GONE." and fx[3][1] > .9 and abs(fx[0]) > 1 and fx[1] > .2 and fx[5] == "block", fx[:6])
                ctx.close()
        # reduced motion: plain fades
        ctx = ctx_new(b, viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
        pg = ctx.new_page()
        g, m = cues["google"], cues["mega"]
        goto(pg, base, "", round(g[1] + 0.08, 2))
        pg.screenshot(path=str(out / "desktop-generic-reduced-snap-google.png"))
        fx = pg.evaluate(FX, "google")
        tr = re.findall(r"-?[\d.]+", fx[4])
        plain = len(tr) == 6 and tr[:4] == ["1", "0", "0", "1"] and abs(float(tr[4]) + fx[10] / 2) < 1 and abs(float(tr[5]) + fx[11] / 2) < 1
        check("reduced motion, snap: no shake / scale (plain translate(-50%, -50%)), no flash", plain and fx[5] == "none", (fx[4], fx[5]))
        goto(pg, base, "", round(m[1] + 0.25 + 0.475, 2))
        fx = pg.evaluate(FX, "mega")
        check("reduced motion, mid-wipe: after layer fades (opacity ~0.5, no clip-path)", 0.2 < fx[9][0] < 0.8 and fx[9][1] == "none", fx[9])
        goto(pg, base, "", round(m[1] + 1.6, 2))
        fx = pg.evaluate(FX, "mega")
        check("reduced motion, stamp: no particles (burst display none), stamp unscaled", fx[6] == "none" and fx[7] == 1, (fx[6], fx[7]))
        ctx.close()
        player(b, base, out, cues)
        full_frame(b, base, out)
        for vp, opts in SWAP_VIEWPORTS.items():
            swap(b, base, out, cues, cta, vp, opts)
        for f in ("bar-generic-0s", "settled", "google-live"):
            print(f"swap proof -> frame-1920-swap-{f}.png")
        # the framing proofs: the whole 1920x1080 frame
        ctx = ctx_new(b, viewport={"width": 1920, "height": 1080})
        pg = ctx.new_page()
        for mode, pid, t in (("generic", "google", cues["google"][0] + 1), ("named", "mega", cues["mega"][1] + 1.6), ("generic", "cta", cta + 0.6)):
            goto(pg, base, name_q if mode == "named" else "", round(t, 2))
            f = out / f"frame-1920-{mode}-{pid}-{'live' if pid == 'google' else 'removed' if pid == 'mega' else 'card'}.png"
            pg.locator(".vo-stage").screenshot(path=str(f))
            print(f"framing proof t={t:g} -> {f.name}")
            if pid == "mega":
                fx = pg.evaluate(FX, "mega")
                rolls = pg.evaluate(VISIBLE)[0][4]
                check("frame mega removed (named): counter at 0, stamp on, particles flying", "0 GB · 0 videos" in rolls and fx[7] == 1 and fx[8] > .3 and fx[6] == "block", (rolls, fx[6:9]))
        full = cta_steps(pg, base, out, cta, name_q)
        named_flow(pg, base, out, cta, name_q)
        ctx.close()
        cta_phone(b, base, out, cta, full)
        named_phone(b, base, out, cta, name_q)
        ui_full(b, base, out, name_q)
        speech(b, base, out, a.name, cues)
        sfx(b, base, cues)
        persona(b, base, out, pf, tap, cta, name_q, a.name)
        personalized(b, out, a.break_thumbs)
        captions(b, base, out, name_q)
        sources(p, b, base, out)
        fill(b, base, out, name_q, a.name, fl["intro"], fl["sites"], cta)
        gsearch(b, base, out, cues, a.hers_raw, a.base)
        blur(b, base, out, a.hers_raw, a.base)
        if a.hers_raw or not a.skip_prod:
            hers(b, base, out, a.hers_raw, a.skip_prod)
        if not a.skip_prod:
            prod(b, base, out, cues, cta)
    for f in fails:
        print("FAIL", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

# Video cue sheet

The video is **full frame** (the whole 16:9 stage); Jack sits in its **left half** and leaves the right half empty: every
overlay is drawn **on the video's right half** (transparent layer, no panel; a 640x720 design box scaled to 960x1080 of the
1920x1080 frame, card vertically centred), so his face stays uncovered. Same at **every width**: on a phone in
portrait the small 16:9 video carries the card in its right half (no stacking). Bigger: rotate the phone (the stage
fills the landscape screen) or the stage's full screen button: desktop / Android = `stage.requestFullscreen()` (the
stage, not the `<video>`, so the cards stay; Android also locks landscape), iPhone Safari (no element full screen) =
"theater": the stage fixed, rotated 90deg over the portrait screen, scroll locked; Esc / the X / back closes it. Touch
devices: native controls off (iOS's would cover the card), own play / pause + seek bar across the full stage width (thin, bottom; the cards draw over it), the full screen button top right (icon only on touch), the first tap on
the stage plays and shows a "Rotate for full size" pill (6 s). The script, line by line with its prefab and
cue: `SCRIPT.md`. Cues = `data-cue-*` in `index.html` (seconds into `jack.webm`, Jack's real one take for both modes:
56.9 s, 1280x720 VP9 + Opus; `jack.mp4` = the same take, 1280x720 H.264 + AAC, faststart, the second `<source>` for
iPhones before iOS 17.4), set from his words by `tools/video/cues_from_take.py`.

**Removed cue = "they get removed".** The take has no finger snaps (no snap gesture on screen, no transient above the
speech; the tool still looks for them: a snap >= 9 dB over the speech near the removal word wins), so each removed cue
sits on his word "removed".

## Captions (`transcript.json`, `.vo-capt`)

His words as spoken (never personalized), as HTML over the video, drawn by `draw(t)` like the cards (exact on seek /
`?t=`): 1-3 words at a time (chunks: <= 16 letters, split on punctuation and pauses > 0.4 s), bold uppercase white with a
black stroke, the word he is saying yellow + a 0.15 s pop, the chunk pops in (0.12 s) and stays to its last word + 0.5 s.
Where: his left half (x 2-48 %), the lower third (bottom 16 %, above the touch play bar), or the top band (top 4 %)
for the chunks where his face is down there (the tool's face track: 5-8 s, 27-33 s). Reduced motion: plain lines
(<= 30 letters, two rows max), no pop / highlight. CC button (under the full screen button, on by default, `localStorage`
`leakscan.cc` = `0` off). The "Rotate for full size" hint sits on the right half (the lower third is the captions').
Small stages (the landing's mini player, `js/pip.js`): the 14 px floor shrinks with the stage so a chunk stays in the left
half; under 260 px wide (`data-vo-tiny`) no captions.

## What a prefab does (`js/video-overlays.js`)

- live: pops in from the right (0.45 s, scale 0.6 → 1.08 → 1) + a yellow / black word card top-right for 0.6 s
  (`GOOGLE`, `IMAGES`, `X`, `REDDIT`, `MEGA 52 GB`).
- removed (the snap): 0.25 s shake + white flash + `GONE.` / `CLEAN.` / `NOTHING.` word card, then the compare wipe
  (0.95 s); meanwhile the counters roll: Google "About 4,120 results" → "About 3 results", Mega "52 GB · 318 videos" →
  "0 GB · 0 videos" (and its folder file counts → 0). Then the "Removed" stamp slams in (scale 2 → 1, 0.2 s) with a
  12-piece confetti burst (CSS, 0.6 s).
- out: slides out down / right (0.4 s, gone at the out cue).
- `google-images` taps "Images" at `data-cue-tap` (default live + 0.6) and shows the leak grid 0.3 s later.
- prefers-reduced-motion: no shake / pop / slam / particles; the wipe becomes a fade (`css/video.css`).
- Sound: a synthesized pop at live and whoosh + thud at removed (WebAudio, no files), only while playing
  after the viewer's play gesture, low volume; `?sfx=0` turns it off.

Room rules (`tools/video/check_video.py` checks them): prefabs never overlap; removed − live >= 0.45 s
(`google-images` >= 1.2 s: tap + grid; its tap in live + 0.45 .. removed − 0.7), out − removed >= 1.95 s.

After states ("Removed" stamp kept on all 5): `google` = the landing after-phone's results, her site first
(`<name>.com`; `?name=SophieStar` → `sophiestar.com`; a scan → its `profile.site_domain`, else `<handle>.com`), then
`instagram.com › <handle>`, TikTok, her blog; no leak rows. `google-images` = her own photos, not blurred (the landing
after-phone's `assets/phone/photo-*.jpg`, also for a scan), captioned with her site / Instagram. X / Reddit / Mega: the
leak is gone.

## Two modes, one take

| | generic (no `?name=`, no scan result) | named (`?name=`, `?r=<slug>`, the last scan, or the name bar) |
|---|---|---|
| take | `jack.webm` | `jack.webm` (the same take) |
| texts | demo persona "SophieStar" (search box, posts, after state `sophiestar.com` + instagram.com › sophiestar, @sophiestar) | her name / scan texts |
| images | default blurred thumbs | after a scan result: her real ones (below); `?name=` alone: the defaults |
| voice | Jack only | Jack only: the page never speaks (no `speechSynthesis`, no AI overvoice; he talks from 0.58 s); "for <name>" pill 0-2 s and from `data-cue-say` (52.98 s, after his last word) |
| end | `cta-steps`: the "Type your name in the link → this video rebuilds with YOUR leaks" card at `data-cue-cta` (default `data-cue-say`), stays: a phone-shaped replica of the landing (dark, the site's tokens / fonts / logo), one 10 s take from its cue (0-4.1 s the hero: the camera zooms onto the `onlyfans.com/` field, types "Jaka Basej" as the handle `jakabasej` (the viewer's own once typed in the form), pulls back, "Scan now" pressed; 4.1-6.8 s the scan card "FREE SCAN · ONLYFANS @handle", "Searching Google, step N of 9…" walking Google → Google Images → X → Reddit → Mega, bar, skeleton rows; 6.8-9.8 s the report card: zoom onto "N links found" rolling to 87, pull back over tabs Links 87 / Images 12 / Sites 31, 5 placeholder `*.example` rows with grey blurred thumbs + Live pills, "+ 82 more in the full report", the blurred Google Images strip; from 8.75 s "Rewatch this video with YOUR content" + "for SophieStar" flipping to the name typed in the form, else staying SophieStar), still looping after the take ends; under it the real form = the name bar's rebuild (below) | the same take, also typing `jakabasej` ("@jakabasej" on the scan / report cards; the report's counts / rows / thumbs = hers), no title / form / flip, ending on "This is what I'd clear for <name>" + Telegram @jakabasej / WhatsApp +386 40 703 992 / me@jackbase.dev (text, no links: the page loads / links nothing external), held 5 s per loop (15 s), still looping after the take ends |

**Production images** (named, from a scan result: `?r=<slug>` → `GET <API>/api/scan-result/<slug>`, or the name bar's scan
→ the landing's own `POST <API>/api/public-scan` for `onlyfans.com/<handle>`; `<API>` = js/scan-engine.js's host): the
cards are filled like the landing hero card (js/inline-scan.js): Google = her real result domains + titles (letter
favicons, the first row with 3 thumbs), "About N results" = the scan's Google total; Google Images = 6 of her real Google
thumbs with their domains, every X / Reddit / Mega photo too: `<API>/api/thumb?u=<gstatic>` only, people photos only (each
probed like the landing report's gallery(): >= 16 px + `E.isPhoto`, so the same logos / banners / icons drop out;
`VideoOverlays.photos` = {kept, dropped}), always blurred (video cards: `blur(5px) saturate(.95)` on `.rm-img` /
`.vo-real`, the floor = styles.css `.live-ico`); the Images count = the kept ones; the cta-steps report = her real counts (Links = hits + results by URL, Images, Sites, "+ N more")
+ 5 titled rows + thumbs. After state: her own SFW photos (`GET <API>/api/media/<slug>` → `<API>/api/media/<slug>/<n>.jpg`,
unblurred `.vo-own`), else the default photos. Leak URLs are read for their host only, never rendered. A failed scan /
read = text only. While the name bar's scan runs: a yellow status pill ("Searching Google, step N of 9…"); the take plays
its intro and holds just before the first card (at most 45 s) until the result lands, then the URL becomes `?r=<slug>`.

**Name bar** (both modes, under the stage; full screen / theater: a "Your name" pill top right, next to the X, opens it): generic =
"Type your name" input (1-40 letters / digits / space . - _, textContent only) + "Rebuild this video with my name", a pulsing
yellow "👇 type your name" pill on it from 0 s until the first focus (SCRIPT.md line 9 points at it). Submit (or the end
card's form, same function) = in place, no reload: named mode, every prefab re-personalized, cta-steps with her name, "for <name>"
pill, `?name=` via `history.replaceState`, a pop, and at once (no interstitial card)
the take restarts from 0, playing (the submit is the gesture), + the scan above. Then the bar reads "Rebuilt for <name>" + Change (the input again) / Reset (generic,
URL without query, restart). `?name=` on load works as before.

If the take ends before a say / end-card cue, they come on `ended`. No spoken name: Jack's own voice only (the old
`speechSynthesis` overvoice, its volume ducking and `data-cue-say-start` are gone; check_video.py and cue_shots.py assert 0
`speechSynthesis.speak` calls).

## After recording (a new take)

1. Encode (nice 10): `ffmpeg -i TAKE.MOV -vf scale=1280:720 -c:v libvpx-vp9 -crf 34 -b:v 0 -g 30 -keyint_min 30 -row-mt 1
   -tile-columns 1 -deadline good -cpu-used 2 -pix_fmt yuv420p -pass 1|2 … -c:a libopus -b:a 96k site/video/jack.webm` (two
   passes; 1080p only if it stays <= 20 MB) and `ffmpeg -i TAKE.MOV -vf scale=1280:720 -c:v libx264 -profile:v main -crf 23
   -maxrate 2500k -bufsize 5000k -g 30 -c:a aac -b:a 128k -movflags +faststart site/video/jack.mp4`.
2. Cues + captions, one line, free + local (a throwaway venv outside the repo: `uv venv ~/.cache/leakscan-whisper && uv pip
   install --python ~/.cache/leakscan-whisper faster-whisper 'opencv-python-headless<5'`):
   `~/.cache/leakscan-whisper/bin/python tools/video/cues_from_take.py site/video/jack.webm --apply --evidence DIR`
   (whisper medium word timestamps, edges pulled off silence, a second pass over a dropped last phrase, snaps, face track →
   every `data-cue-*` in `index.html` + `transcript.json`; prints the cue table + notes; DIR gets the raw transcript).
   Or edit `data-cue-*` by hand (rules: `SCRIPT.md`).
3. `python3 tools/video/check_video.py` and `cd ~/leakhunt && uv run python ~/leakscan-site/tools/video/cue_shots.py OUT
   --skip-prod` (both modes at every cue with the words he says there, geometry, counters, end card + form, snap, reduced
   motion, sfx, no overvoice (0 `speechSynthesis.speak` calls, `--break-voice`), scan-stub texts + photos, captions at every word, webm + mp4 sources; `--only captions` = the
   captions + sources part, `--break-captions` = the transcript 2 s late: only the caption word checks go red).

Test any moment: `?t=12.5`.

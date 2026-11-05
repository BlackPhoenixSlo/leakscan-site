# Video cue sheet

Jack is on the **left half**; every overlay fills the **right half** (a 640x720 design box scaled to 960x1080 of the
1920x1080 frame, card vertically centred), so his face stays uncovered. Same at **every width**: on a phone in
portrait the small 16:9 video carries the card in its right half (no stacking). Bigger: rotate the phone (the stage
fills the landscape screen) or the stage's full screen button: desktop / Android = `stage.requestFullscreen()` (the
stage, not the `<video>`, so the cards stay; Android also locks landscape), iPhone Safari (no element full screen) =
"theater": the stage fixed, rotated 90deg over the portrait screen, scroll locked; Esc / the X / back closes it. Touch
devices: native controls off (iOS's would cover the card), own play / pause + seek bar on Jack's half, the first tap on
the stage plays and shows a "Rotate for full size" pill (6 s). The script, line by line with its prefab and
default cue: `SCRIPT.md`. Default cues = `data-cue-*` in `index.html` (seconds into `jack.mp4`, guessed for a ~40 s
take until the real recording exists; the placeholder is 44 s).

**Removed cue = the snap.** Jack snaps his fingers on every removal; the removed cue sits on the word right after it
("Gone" / "Now" / "Hours" / "Nothing" / "Gone").

## What a prefab does (web page and clips: same code, `js/video-overlays.js`)

- live: pops in from the right (0.45 s, scale 0.6 → 1.08 → 1) + a yellow / black word card top-right for 0.6 s
  (`GOOGLE`, `IMAGES`, `X`, `REDDIT`, `MEGA 52 GB`).
- removed (the snap): 0.25 s shake + white flash + `GONE.` / `CLEAN.` / `NOTHING.` word card, then the compare wipe
  (0.95 s); meanwhile the counters roll: Google "About 4,120 results" → "About 3 results", Mega "52 GB · 318 videos" →
  "0 GB · 0 videos" (and its folder file counts → 0). Then the "Removed" stamp slams in (scale 2 → 1, 0.2 s) with a
  12-piece confetti burst (CSS, 0.6 s).
- out: slides out down / right (0.4 s, gone at the out cue).
- `google-images` taps "Images" at `data-cue-tap` (default live + 0.6) and shows the leak grid 0.3 s later.
- prefers-reduced-motion: no shake / pop / slam / particles; the wipe becomes a fade (`css/video.css`).
- Sound (web page only): a synthesized pop at live and whoosh + thud at removed (WebAudio, no files), only while playing
  after the viewer's play gesture, low volume; `?sfx=0` turns it off.

Room rules (`tools/video/check_video.py` checks them): prefabs never overlap; removed − live >= 0.45 s
(`google-images` >= 1.2 s: tap + grid; its tap in live + 0.45 .. removed − 0.7), out − removed >= 1.95 s.

After states ("Removed" stamp kept on all 5): `google` = the landing after-phone's results, her site first
(`<name>.com`; `?name=Tessa` → `tessa.com`; a scan → its `profile.site_domain`, else `<handle>.com`), then
`instagram.com › <handle>`, TikTok, her blog; no leak rows. `google-images` = her own photos, not blurred (the landing
after-phone's `assets/phone/photo-*.jpg`, also for a scan), captioned with her site / Instagram. X / Reddit / Mega: the
leak is gone.

## Two modes, two takes (web page)

| | generic (no `?name=`, no scan result) | named (`?name=` or a scan result) |
|---|---|---|
| take | `jack.mp4` (Script A) | `jack-named.mp4` (Script B) if the server has it (HEAD probe), else `jack.mp4` |
| texts | "Your name" (search box, posts, after state `yourname.com`) | her name / scan texts + scan thumbs |
| speech | none | her name at `data-cue-say-start` (0.3 s, in Script B's 1.5 s opening gap) and at `data-cue-say` (end), each once, + "for <name>" pill 2 s |
| end | `cta-steps`: the "Type your name in the link → this video rebuilds with YOUR leaks" card at `data-cue-cta` (default `data-cue-say`), stays: 3 steps on an 8 s loop from its cue (1 "Type your name": a mock input types the name letter by letter, the viewer's own once typed in the form; 2 "Run the free scan": bar + "Scanning Google · X · Reddit · Mega…", "N leaks found" rolls to 37; 3 "Rewatch this video with YOUR content": a mini of this page flips "Your name" → the name with a pop), still looping after the take ends; under it the real form reloads the page with `?name=` (1-40 letters / digits / space . - _) | the pill (never the steps) |

Script B is Script A with a 1.5 s silent gap before line 1 and its own line 9, so while `jack-named.mp4` plays every
prefab cue and `data-cue-say` move by `data-cue-named-shift` (1.5). If the take ends before a say / end-card cue,
they come on `ended`. Speech: `speechSynthesis`, rate 0.95, page language, only after the play gesture, video ducked to
25 % meanwhile, pause / seek cancels it. Not in the CapCut clips (CapCut has no per-viewer name).

## After recording

1. Export both raw takes as H.264 MP4 (1920x1080, "faststart"): `site/video/jack.mp4` (A), `site/video/jack-named.mp4`
   (B); delete the placeholder `jack.webm` and its `<source>` line in `index.html`.
2. Cues: `cd ~/leakhunt && uv run python ~/leakscan-site/tools/video/cues_from_take.py site/video/jack.mp4 --apply`,
   then the same with `jack-named.mp4 --named --apply` (shift, named say; pins the end card). Needs `openai-whisper` or
   `faster-whisper` in that env (it prints the install line and exits 2 otherwise). Untested on a real take: check the
   diff, or read the timestamps off the CapCut playhead and edit `data-cue-*` by hand (rules above, `SCRIPT.md`).
3. `python3 tools/video/check_video.py` and `cd ~/leakhunt && uv run python ~/leakscan-site/tools/video/cue_shots.py OUT
   --name Tessa` (both modes at every cue, right-half geometry, counters, end card + form, snap, reduced motion, sfx,
   speech, the named take, scan-stub texts + photos).

Test any moment: `?t=12.5`; one prefab alone: `?prefab=mega&state=removed&bg=green`.

## CapCut

1. Render the clips: `cd ~/leakhunt && uv run python ~/leakscan-site/tools/video/render_prefabs.py OUT [--name X]`
   (no `--name` = generic "Your name", for the Script A video; 6 clips, `cta-steps` below) → per prefab `ID.mov` (ProRes 4444, real alpha),
   `ID-green.mp4` (#00FF00), stills `ID-live.png` / `ID-removed.png` (settled) and `ID-in.png` / `ID-snap.png` /
   `ID-burst.png` / `ID-out.png` (0.1 / 2.5 / 4.0 / 5.8 s). Each clip: 1920x1080, 6 s, silent: pops in 0-0.45 s, the
   **snap at 2.4 s** (shake + flash), wipe 2.65-3.6 s, "Removed" stamp at 3.6 s + confetti, slides out 5.6-6 s.
2. Track 1: Jack's take. Track 2 (overlay): drop `ID.mov` (alpha, nothing to key). With `ID-green.mp4` instead:
   select it → Cutout → Chroma key → pick the green → Intensity ~10-20, Shadow ~10.
3. Keep it full frame (Scale 100 %, Position 0 / 0): the card is already on the right half.
4. Place the clip so its 2.4 s mark sits on Jack's snap (clip start = snap − 2.4 s). If the platform word comes earlier
   than 2.4 s before it, extend the live part (split at ~1.6 s, Freeze frame there); if later, trim the head after the
   0.45 s pop-in instead (`google-images` taps at 0.6 s: for a later "Tap Images", split at 0.5 s and freeze there).
5. Let the clip run to its end (the slide-out is in the clip). **No CapCut In / Out animation needed**; if the line
   ends earlier, cut at the "out" mark and add CapCut Out: Fade out 0.3 s for that one.
6. Repeat for `google-images`, `x`, `reddit`, `mega`. Lines 1, 2 and 8 have no clip.
6b. Line 9 (generic upload only): `cta-steps.mov` / `cta-steps-green.mp4`, 8 s = one loop of the 3 steps (pops in at
   0 s, step 1 typing 0-2.6 s, step 2 scan 2.6-5.3 s, step 3 the mini page flip 5.3-8 s), no form, no slide-out: start
   it on the line 9 cue and loop / freeze its last frame to the end. Stills: `cta-steps-step1/2/3.png`,
   `-in / -typing / -scanning / -flip.png`. Not rendered with `--name` (named never shows it).
7. Sound effects (CapCut → Audio → Sound effects, free; search these names, pick by ear, volume ~30 %): **"Pop"** on
   each clip's pop-in (0 s), **"Whoosh"** on the snap (2.4 s), **"Impact"** as the stamp lands (3.6-3.8 s), **"Ding"**
   (or "Cash register") on the confetti (3.8 s). Keep Jack's real finger snap audible; the SFX sit under it.

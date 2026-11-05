# Video cue sheet

Jack fills the frame; every overlay is one small card in the **bottom-right corner** (520x540 px of the 1920x1080 frame,
40 px from the right / bottom edge), so his face stays uncovered. Default cues = `data-cue-*` in `index.html`
(seconds into `jack.mp4`, guessed for a ~32 s take until the real recording exists).

| # | Script line (key words **bold**) | Prefab | live (slides in 0.4 s) | removed (wipe 1.2 s, then stamp) | out (slid out by) |
|---|---|---|---|---|---|
| 1 | "Hey, this is me, Jack. I show my face…" | none | – | – | – |
| 2 | "What I do: here are leaks on **Google** [All results → tap Images → grid]. A few days after, there are **no leaks** here." | `google` | 0.3 s before "**Google**" (7) | on "A **few** days after" (8.4) | 10.4 |
| 2 | (same line, continued) | `google-images` | right after `google` (10.4); taps "Images" at +0.6 s, grid by +1.2 s | on "**no**" of "no leaks here" (11.8, >= live + 1.2) | end of line (14) |
| 3 | "Leaks on **X**. A few hours later, there are **no leaks**." | `x` | on "Leaks on" (14) | on "**no**" (15.8) | end of line (18) |
| 4 | "A few leaks on **Reddit**. There are **no leaks** on Reddit." | `reddit` | on "A few leaks" (18) | on "**no**" (20.2) | end of line (22.5) |
| 5 | "You have **Mega** files with 50 or more gigabytes of videos. They are **gone** in a day." | `mega` | on "**Mega**" (22.5) | on "**gone**" (26) | end of line (29) |
| 6 | "A lot more, but that's enough… write the name in the description… populate with your content." | none | – | – | – |
| 7 | (silent ~1.5 s gap) "This is for…" → the browser says the name | `data-cue-say` on `.vo-stage` | right after "This is for…" (31) | – | pill out after 2 s |

Rule: live ≈ 0.3 s before the platform word (the slide lands on it); removed exactly on "no" / "gone" (the wipe
runs while he finishes the sentence); out = the card has slid away (starts 0.4 s before), next card can come in on
the same second. Prefabs never overlap; removed − live >= 0.4 s (google-images >= 1.2 s: tap + grid), out − removed
>= 1.95 s (wipe + stamp + slide-out). `tools/video/check_video.py` checks all of it.

`google` + `google-images` are two prefabs (two clips) on the one script line: same cue contract as every other
prefab, no extra cue; the Images tap / grid swap is timed from its own live cue.

## The spoken name (web page only)

Line 7: after "…populate with your content", leave a **~1.5 s silent gap**, say "This is for…", then pause ~1.5 s.
On the web page, when a personalized name exists (`?name=` or a scan result; never the default Orla), the browser
speaks it at `data-cue-say` (`speechSynthesis`, rate 0.95, page language; once per playback, only after the viewer
pressed play; the video is ducked to 25 % volume meanwhile; pause / seek cancels it) and a "for <name>" pill slides
into the same corner for 2 s (so it still reads where the browser has no voice). Set `data-cue-say` to the second
right after "This is for…". Not in the CapCut clips (CapCut has no per-viewer name).

## CapCut

1. Render the clips: `cd ~/leakhunt && uv run python ~/leakscan-site/tools/video/render_prefabs.py OUT [--name X]`
   → per prefab `ID.mov` (ProRes 4444, real alpha), `ID-green.mp4` (#00FF00), stills `ID-live.png` / `ID-removed.png`
   (settled) and `ID-in.png` / `ID-out.png` (mid slide). Each clip: 1920x1080, 6 s; slides in 0-0.4 s, the wipe
   starts at **2.4 s**, "Removed" stamp at 3.6 s, slides out 5.6-6 s.
2. Track 1: Jack's take. Track 2 (overlay): drop `ID.mov` (alpha, nothing to key). With `ID-green.mp4` instead:
   select it → Cutout → Chroma key → pick the green → Intensity ~10-20, Shadow ~10.
3. Keep it full frame (Scale 100 %, Position 0 / 0): the card is already in the bottom-right corner.
4. Place the clip so its 2.4 s mark sits on the "removed" word (clip start = that word − 2.4 s). If the platform word
   comes earlier than 2.4 s before it, extend the live part (split at ~1.6 s, Freeze frame there); if later, trim
   the head after the 0.4 s slide-in instead (`google-images` needs its first 1.2 s: tap + grid).
5. Let the clip run to its end (the slide-out is in the clip). **No CapCut In / Out animation needed**; if the line
   ends earlier, cut at the "out" mark and add CapCut Out: Fade out 0.3 s for that one.
6. Repeat for `google-images`, `x`, `reddit`, `mega`. Lines 1, 6 and 7 have no clip.

## Web page (`site/video/?name=…`)

The page plays the **raw** take (no CapCut overlays burned in) and draws the same prefabs itself, personalized:
`?name=` sets the texts; a scan result (`?r=<slug>` / the last scan) sets the texts **and** swaps every photo for
the creator's own thumbs (blurred, like #removals). After recording:
1. Export the raw take as H.264 MP4 (1920x1080, "faststart"), save it as `site/video/jack.mp4`; delete the
   placeholder `jack.webm` and its `<source>` line in `index.html`.
2. Read the real word timestamps off the take (CapCut playhead) and edit `data-cue-live / -removed / -out` on each
   `.vo-pf` and `data-cue-say` on `.vo-stage` in `index.html`, same rules as the table.
3. `python3 tools/video/check_video.py` (cues ascending, gaps, no overlap, say after the last out, noindex, no
   external URLs) and `cd ~/leakhunt && uv run python ~/leakscan-site/tools/video/cue_shots.py OUT --name Tessa`
   (screenshots at every cue, corner geometry, scan-stub texts + photos, the spoken name).
Test any moment: `?t=12.5`; one prefab alone: `?prefab=mega&state=removed&bg=green`.

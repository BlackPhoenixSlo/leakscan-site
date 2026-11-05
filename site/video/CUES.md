# Video cue sheet

Jack sits on the left half; every overlay sits on the right half. Default cues = `data-cue-*` in `index.html`
(seconds into `jack.mp4`, guessed for a ~32 s take until the real recording exists).

| # | Script line (key words **bold**) | Prefab | live (fades in 0.45 s) | removed (wipe 1.2 s, then stamp) | out |
|---|---|---|---|---|---|
| 1 | "Hey, this is me, Jack. I show my face…" | none | – | – | – |
| 2 | "What I do: here are leaks on **Google**. A few days after, there are **no leaks** here." | `google` | 0.3 s before "**Google**" (7.5) | on "**no**" of "no leaks here" (10.5) | end of line (13.5) |
| 3 | "Leaks on **X**. A few hours later, there are **no leaks**." | `x` | on "Leaks on" (13.5) | on "**no**" (15.8) | end of line (18) |
| 4 | "A few leaks on **Reddit**. There are **no leaks** on Reddit." | `reddit` | on "A few leaks" (18) | on "**no**" (20.2) | end of line (22.5) |
| 5 | "You have **Mega** files with 50 or more gigabytes of videos. They are **gone** in a day." | `mega` | on "**Mega**" (22.5) | on "**gone**" (26) | end of line (29) |
| 6 | "A lot more, but that's enough… write the name in the description…" | none | – | – | – |

Rule: live ≈ 0.3 s before the platform word (the fade lands on it); removed exactly on "no" / "gone" (the wipe
runs while he finishes the sentence); out when the next line starts. Prefabs never overlap (the gate checks).

## CapCut

1. Render the clips: `cd ~/leakhunt && uv run python ~/leakscan-site/tools/video/render_prefabs.py OUT [--name X]`
   → per prefab `ID.mov` (ProRes 4444, real alpha), `ID-green.mp4` (#00FF00), `ID-first.png` / `ID-last.png`.
   Each clip: 1920x1080, 6 s; live from 0 s, the wipe starts at **2.4 s**, "Removed" stamp at 3.6 s, hold to 6 s.
2. Track 1: Jack's take. Track 2 (overlay): drop `ID.mov` (alpha, nothing to key). With `ID-green.mp4` instead:
   select it → Cutout → Chroma key → pick the green → Intensity ~10-20, Shadow ~10.
3. Keep it full frame (Scale 100 %, Position 0 / 0): the prefab is already on the right half.
4. Place the clip so its 2.4 s mark sits on the "removed" word (clip start = that word − 2.4 s). If the platform word
   comes earlier than 2.4 s before it, extend the head with Freeze frame on the first frame; if later, trim the head.
5. Cut the clip when the line ends (the "out" column); add Animation → In: Fade in 0.3 s and Out: Fade out 0.3 s.
6. Repeat for `x`, `reddit`, `mega`. Lines 1 and 6 have no overlay.

## Web page (`site/video/?name=…`)

The page plays the **raw** take (no CapCut overlays burned in) and draws the same prefabs itself, personalized.
After recording:
1. Export the raw take as H.264 MP4 (1920x1080, "faststart"), save it as `site/video/jack.mp4`; delete the
   placeholder `jack.webm` and its `<source>` line in `index.html`.
2. Read the real word timestamps off the take (CapCut playhead) and edit `data-cue-live / -removed / -out` on each
   `.vo-pf` in `index.html`, same rules as the table.
3. `python3 tools/video/check_video.py` (cues ascending, no overlap, noindex, no external URLs) and
   `cd ~/leakhunt && uv run python ~/leakscan-site/tools/video/cue_shots.py OUT --name Tessa` (screenshots at every cue).
Test any moment: `?t=12.5`; one prefab alone: `?prefab=mega&state=removed&bg=green`.

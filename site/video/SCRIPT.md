# Jack's video: the script

Two takes, same face, same lines 1-8. `[beat]` = a short pause, `[snap]` = Jack snaps his fingers on camera: **every
snap is a removed cue** (the card shakes, flashes, then wipes to the after state).

## Script A (generic): `jack.mp4`

1. "Your leaks are on Google right now. Watch me delete them."
2. "Hey, I'm Jack. Real face, real person, not a bot site."
3. "Step one. Google. Leaks. [beat] Three days later… [snap] Gone. Your real site and your Instagram are the only things left."
4. "Google Images? Same thing. [beat] Tap Images… nudes. [snap] Now it's just your normal photos."
5. "X. Leaks. [snap] Hours later. Nothing."
6. "Reddit. Leaks. [snap] Nothing."
7. "Mega folders. Fifty gigabytes of your videos. [snap] Gone in a day."
8. "I do this every single day. That's enough for one video."
9. "Type your name in the link below, or in the box under the video, and this exact video rebuilds itself with YOUR leaks. Go check it."

## Script B (named): `jack-named.mp4`

Same 1-8, but line 1 starts after a **1.5 s silent gap** (the browser speaks her name in it), and line 9 is:

9. "Everything you just saw was pulled from YOUR name. Message me below, I start today."

Leave ~2 s of silence after line 9 in both takes (the name / the end card land there).

## Line → prefab → cue

Default seconds = guesses for a ~40 s Script A take (`data-cue-*` in `index.html`, `jack.mp4` time). Script B runs
`data-cue-named-shift` (1.5 s) behind: while `jack-named.mp4` plays, every prefab cue and `data-cue-say` move by it.
After recording: `tools/video/cues_from_take.py` (CUES.md) reads these key words off the take.

| # | Key word (cue) | Prefab | live | tap | removed = the snap | out |
|---|---|---|---|---|---|---|
| 1 | (B only: the 1.5 s gap) | named: the name spoken + "for <name>" pill, `data-cue-say-start` | 0.3 | – | – | pill 2 s |
| 2 | – | none | – | – | – | – |
| 3 | live 0.3 s before "**Google**. Leaks."; removed on "**Gone**" | `google` | 6.7 | – | 10 | 13.5 |
| 4 | "Google **Images**?"; tap on "**Tap** Images"; removed on "**Now**" | `google-images` | 13.5 | 15.6 | 17 | 19.2 |
| 5 | "**X**. Leaks."; removed on "**Hours** later" | `x` | 19.2 | – | 20.6 | 22.8 |
| 6 | "**Reddit**. Leaks."; removed on "**Nothing**" | `reddit` | 22.8 | – | 24.2 | 26.2 |
| 7 | "**Mega** folders"; removed on "**Gone** in a day" | `mega` | 26.2 | – | 29.6 | 31.8 |
| 8 | – | none | – | – | – | – |
| 9 | last word's end + 0.5 | A: `cta-steps`, the "Type your name" end card (`data-cue-cta`, default `data-cue-say`): 3 steps on an 8 s loop (1 types a name, 2 scans "… 37 leaks found", 3 a mini of this page flips "Your name" → the name) over the real form; CapCut: `cta-steps.mov`. B: the name spoken + pill (`data-cue-say`), no steps | 40.5 | – | – | stays, loops past the end (pill 2 s) |

Rules: live = 0.3 s before the platform word; removed = the word right after the snap; out = the next platform word
− 0.2 s (mega: end of "Gone in a day" + 0.5), at least removed + 1.95 s; the next card comes in no earlier than the
last one is out.

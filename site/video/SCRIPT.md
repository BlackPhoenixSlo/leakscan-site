# Jack's video: the script

One take, ~40 s, for both modes: `site/video/jack.webm`. `[beat]` = a short pause, `[snap]` = Jack snaps his fingers on
camera: **every snap is a removed cue** (the card shakes, flashes, then wipes to the after state).

**Start: 1.5 s silent, looking at the camera** (named mode: the browser speaks her name in it). **End: hold 2 s** after
line 9 (named: her name is spoken there; the end card keeps looping).

1. "Your leaks are on Google right now. Watch me delete them."
2. "Hey, I'm Jack. Real face, real person, not a bot site."
3. "Step one. Google. Leaks. [beat] Three days later… [snap] Gone. Your real site and your Instagram are the only things left."
4. "Google Images? Same thing. [beat] Tap Images… nudes. [snap] Now it's just your normal photos."
5. "X. Leaks. [snap] Hours later. Nothing."
6. "Reddit. Leaks. [snap] Nothing."
7. "Mega folders. Fifty gigabytes of your videos. [snap] Gone in a day."
8. "I do this every single day. That's enough for one video."
9. "Type your name under this video and it rebuilds with YOUR leaks. Already see yours? Message me below, I start today."

## Line → prefab → cue

Default seconds = guesses for a 40 s take (`data-cue-*` in `index.html`). When the take arrives: CUES.md "After recording".

| # | Key word (cue) | Prefab | live | tap | removed = the snap | out |
|---|---|---|---|---|---|---|
| – | the 1.5 s silent start | named: the name spoken + "for <name>" pill, `data-cue-say-start` | 0.2 | – | – | pill 2 s |
| 1-2 | – | none | – | – | – | – |
| 3 | live 0.3 s before "**Google**. Leaks."; removed on "**Gone**" | `google` | 6.2 | – | 9.4 | 12.8 |
| 4 | "Google **Images**?"; tap on "**Tap** Images"; removed on "**Now**" | `google-images` | 12.8 | 14.6 | 16 | 18.2 |
| 5 | "**X**. Leaks."; removed on "**Hours** later" | `x` | 18.2 | – | 19.6 | 21.6 |
| 6 | "**Reddit**. Leaks."; removed on "**Nothing**" | `reddit` | 21.6 | – | 23 | 25 |
| 7 | "**Mega** folders"; removed on "**Gone** in a day" | `mega` | 25 | – | 28.2 | 30.4 |
| 8 | – | none | – | – | – | – |
| 9 | "**Type** your name" − 0.2 | `cta-steps` (`data-cue-cta`): the landing in a phone, one 10 s take (zoom onto the onlyfans.com/ field, types the handle, "Scan now" → "Searching Google, step N of 9…" → the report + tabs + rows); generic: "Rewatch this video with YOUR content", "Your name" flips to the name, + the form; named: `jakabasej` typed too, her real counts / rows / thumbs (after a scan), "This is what I'd clear for <name>" + the contact row | 32.6 | – | – | stays, loops past the end |
| end | last word's end + 0.3 (the 2 s hold) | named: the name spoken again, `data-cue-say` | 37.8 | – | – | – |

Rules: live = 0.3 s before the platform word; removed = the word right after the snap; out = the next platform word
− 0.2 s (mega: end of "Gone in a day" + 0.5), at least removed + 1.95 s; the next card comes in no earlier than the
last one is out.

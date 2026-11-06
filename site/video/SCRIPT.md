# Jack's video: the script

The script Jack was given (his real take, 56.9 s, says it in his own words: below). One take for both modes:
`site/video/jack.webm` (+ `jack.mp4`, the same take for iPhones without WebM). `[beat]` = a short pause, `[snap]` = Jack snaps his fingers on
camera: **every snap is a removed cue** (the card shakes, flashes, then wipes to the after state).

**Start: talking straight away** (his real take: "Hey" at 0.58 s; the page never speaks: no AI overvoice, named mode
only adds the "for <name>" pill). **End: hold 2 s** after line 9 (named: the "for <name>" pill; the end card keeps looping).

1. "Your leaks are on Google right now. Watch me delete them."
2. "Hey, I'm Jack. Real face, real person, not a bot site."
3. "Step one. Google. Leaks. [beat] Three days later… [snap] Gone. Your real site and your Instagram are the only things left."
4. "Google Images? Same thing. [beat] Tap Images… nudes. [snap] Now it's just your normal photos."
5. "X. Leaks. [snap] Hours later. Nothing."
6. "Reddit. Leaks. [snap] Nothing."
7. "Mega folders. Fifty gigabytes of your videos. [snap] Gone in a day."
8. "I do this every single day. That's enough for one video."
9. "Type your name under this video and it rebuilds with YOUR leaks. Already see yours? Message me below, I start today."

## What he said (the real take, faster-whisper medium, `transcript.json`; seconds into jack.webm)

> Hey, it's me Jack, a real face, not a bot. I remove leaks, check, fuck leaks. I remove from the Google, you see links,
> they get removed. You see images on the Google, they get removed. You see stuff on the X, they get removed. You see
> stuff on the Reddit, they get removed. You see stuff on the mega, they get removed. If you see stuff of any of these
> websites and a lot more, like 10,000 of them, they get removed. You can put your name on the website and you will see
> all of the links that I can get in eight seconds. I usually spend three or four hours per week on you. And the whole
> website is gonna change to be personalized directly for you. Wubba lubba dub dub.

No silent opening ("Hey" at 0.58 s), no finger snaps (no snap gesture on screen, no transient above the speech): every
removal is his "they get removed", so the removed cue = "removed". He ends at 52.3 s, then holds ~3 s and walks off.

## Line → prefab → cue (mapped by meaning; `tools/video/cues_from_take.py` writes these `data-cue-*`)

| # (script) | what he says | prefab | live | tap | removed | out |
|---|---|---|---|---|---|---|
| start | "Hey, it's me Jack…" (0.58) | named: "for <name>" pill (nothing spoken) | 0 | – | – | pill 2 s |
| 1-2 | "Hey, it's me Jack, a real face, not a bot. I remove leaks, check, fuck leaks." | `intro` fill (`data-cue-in` / `-out`): the landing in a phone types `jakabasej` (named: her handle), "Scan now", the scan card, "Building YOUR video…" | 0.3 | – | – | 9.8 |
| 3 | "I remove from the **Google** (10.30), you see links, **they** (12.44) get **removed** (12.86)." | `google` (removed: "removed" − 0.5, the wipe on "they get removed") | 10 | – | 12.36 | 14.81 |
| 4 | "You see **images** (14.16) on the Google, they get **removed** (16.00)." | `google-images` (tap: end of "images", clamped) | 14.81 | 15.26 | 16.01 | 17.96 |
| 5 | "You see stuff on the **X** (18.08), they get **removed** (19.52)." | `x` | 17.96 | – | 19.52 | 21.47 |
| 6 | "You see stuff on the **Reddit** (21.60), they get **removed** (22.88)." | `reddit` | 21.47 | – | 22.88 | 24.88 |
| 7 | "You see stuff on the **mega** (25.08), they get **removed** (26.06)." | `mega` | 24.88 | – | 26.06 | 28.01 |
| 8 | "If you see stuff of any of these websites and a lot more, like 10,000 of them, they get removed." (27.1-34.3) | `sites` fill: his whiteboard's site names struck "Removed" in turn, the counter rolling to 10,000+ | 28.2 | – | – | 34.6 |
| 9 | "**You can put your name on the website** (35.01) and you will see all of the links that I can get in eight seconds. I usually spend three or four hours per week on you. And the whole website is gonna change to be personalized directly for you." | `cta-steps` (`data-cue-cta` = the end of line 8 + 0.5): the landing in a phone, one 10 s take (types the name, scans, the report), looping to the end and past it | 34.77 | – | – | stays |
| end | "Wubba lubba dub dub." (50.9-52.3), then the hold | named: "for <name>" pill (= the named flow), `data-cue-say` (last word + 0.3) | 52.98 | – | – | – |

Rules: live = 0.3 s before the platform word, never before the last card is out; removed = the snap if one stands
>= 9 dB above the speech, else the removal word ("removed"); removed − live >= 0.45 s (google-images 1.2); out = the next
platform word − 0.2 (mega: its "removed" + 0.5), at least removed + 1.95 s. He talks faster than the animations, so
google / google-images / x / mega are held to removed + 1.95 and the next card comes in at that out (google-images
arrives 0.65 s after "images").

# Design plan: landing v3 (track "fable")

Subject: one person (Jaka) who finds leaked copies of a creator's content and gets them taken down, by hand.
Audience: OnlyFans creators arriving from a Google ad, on a phone, worried. Job: run the scan, then message Jaka.
Mood: a discreet private service, not a SaaS. Calm paper, one ink colour, a warm letterpress voice.

## Tokens

Colour (light / dark), all text pairs >= 4.5:1, measured:

| role | light | dark | note |
| --- | --- | --- | --- |
| paper (bg) | `#ECEEF0` cool mist | `#17151C` | not cream, not black |
| sheet (surface) | `#FFFFFF` | `#211E28` | cards, form fields |
| ink | `#1C1B22` | `#EEEBF2` | 14.7 / 15.3 on paper |
| muted | `#4E4F59` | `#BAB4C4` | 7.0 / 9.0 on paper |
| mulberry (accent) | `#8C1D52` | `#EC8DB9` | 7.5 / 7.8; the only colour that acts |
| status | live `#AE2A22`, cached `#835800`, dead/removed `#1D6A55` | `#FF958A` `#EBC36E` `#72D1AE` | report chips only |

Mulberry: a berry ink, the colour of a signature on the authorization. No competitor in this market uses it (they are
all SaaS blue / purple). One accent, used for action (buttons, links, focus) and the strike that marks a removed link.

Type (self-hosted woff2, OFL, subset latin + curly quotes, dashes, €, ‑, ↗):
- **Young Serif** (display, 400 only, used >= 32 px): a sturdy letterpress serif. Says "a person made this", warm but
  firm. Never bold-synthesised (`font-synthesis: none`). Headings h1/h2 only.
- **Schibsted Grotesk** (variable 400-800): a newspaper grotesk built for plain, straight talk. Body, UI, h3, numbers
  (tabular figures in prices and the report).
- Scale (1.25, 17 px body): 13.6 / 15 / 17 / 21 / 26.5 (h3 sans 600) / 33 (h2 phone) / 44 (h2 desktop) / 40-68 (h1).
- Fallbacks tuned with size-adjust / ascent-override (Arial for the grotesk, Georgia Bold for the serif); `swap`.

Layout: one container, 1200 px max (content 1120), left aligned throughout. Radius by rank: 20 (cards that hold a
mock), 12 (inner panels, fields), pill only for chips / buttons. Shadow only on the hero card and floating things.

## Layout (desktop 1440)

```
hero    | h1 serif 2 lines              | Weekly report card (ledger)  |
        | lead (Jaka, 2-3 lines)        |  rows: struck when dead      |
        | [onlyfans.com/ username     ] |  Jaka's note                 |
        | [@ IG or X     ][Scan now   ] |                              |
        | note / talk first / 3 assurances |  [mini player docks under] |
#free   | h2 + the free offer, once      | Google phone (her results)   |
#why    | portrait + letter (serif h2)   | three rules, hairline list ; stat line
#how    5 numbered steps in one row (sequence = numbers earned)
#removals h2 left + lede right ; 2x2 mock panels (phones: each panel scaled to .73)
#website| h2                             | paragraph + 3 points          |
#showcase browser frame (full width) ; before/after: text column | phone -> phone
#pricing h2 + shared inclusions ; monthly (ink card) | one-time (outlined)
#faq    | h2 + Ask the AI (sticky)       | questions, hairline list      |
#contact| portrait + h2 + line           | Telegram / WhatsApp / Email   |
```

Phone (390): same order, stacked; before/after = the only swipe row (peek + "Swipe" hint); target <= 9,000 px.

## Principles
1. The memorable thing is the hero ledger: real-looking links, the removed ones struck through in mulberry, drawn once
   on load (the only ambient motion besides the removals sweep; none under reduced motion).
2. Say each thing once: the free offer lives in #free; pricing, steps and FAQ don't re-pitch it.
3. Jaka's voice: first person, short sentences, facts from the repo only. No eyebrows, no "→", no middle-dot strings,
   no accent word in headlines, curly quotes everywhere, U+2011 in compounds that must not split.
4. No section template: each section gets the device its content needs (ledger, phone, panels, letter, steps, plans,
   list, channels). Hairlines and fills, not a card around everything.

## Review against the AI-tells list
- Cream + serif + terracotta: paper is cool mist, accent is mulberry; the serif is low-contrast letterpress, not a
  high-contrast didone. Kept the serif because it carries the "person, not software" point.
- Near-black + acid accent: dark mode is a violet-grey with a dusty rose; no neon.
- Broadsheet hairlines everywhere: hairlines only for lists (FAQ, rules); sections differ.
- SaaS card kit: cards only where a thing is an object (report, plans, mock panels); radius varies by rank.
- Template chrome: removed every eyebrow; no mono labels (the report uses the grotesk with tabular figures);
  buttons carry icons, never arrows.
Revised: first draft had a small sentence-case kicker over each h2; cut (it was an eyebrow by another name).

## Notes
- Phone 390 ends at 11,972 px (measured; from 15,973). Over the ~9,000 goal: #removals is ~2,460 by itself (e2e fixes 4
  stacked panels with a 372 px stage); removing anything else meant dropping content the sales story needs. Inferred.
- Section order kept as on main: tools/scan_e2e/removals.py asserts #removals sits after #faq, directly before #contact.
- Removals cards: the Remove button moved onto the title row (grid areas, removals.css only): about 150 px less on phone.
- pip.js: dock sets --w + move() before setMode('dock'); the card's text (rows, Jaka's note) counts as an obstacle, so the
  player docks just under the card (spot 2); the hero reserves that room below 1100 px, the card's margin above it.
- Hero is two columns from 1100 px only: at 960 / 1024 the Instagram field clipped a 20‑char handle (check_scan_form).
- CLS 0 at 390 and 1440 (measured): launcher shifts with `translate`, not `bottom`; the report-foot avatar is flex:none.
- The showcase h2 is a sans caption so #website's serif h2 is the section's voice (two serif h2s stacked read as a repeat).
- Left as is (JS-written, hook text): "Free scan report · OnlyFans" and "Open full report →" in the live card.
- Logo: Young Serif "A" on mulberry (path from the font, OFL); favicons re-rendered; og.png not regenerated.
## Round 2 notes
- Phone 390: 8,975 px (measured; round 1 11,972). 1440: 8,065. CLS 0 both; no sideways scroll at 320 / 360 / 390.
- Order: hero, free, why, how, removals, website, showcase, pricing, faq, contact. e2e edits (minimal, reported):
  removals.py order -> ["how", "website", "main"]; FP_STATE reads tile / layer offsetHeight (layout px, the phone panels are
  transform-scaled) so 112 / 372 still hold; inline.py checks the pill "shown again" at #faq (it now steps aside over the
  plan buttons); askai.py: launcher hidden in the hero at every width, scroll to #how first on desktop too;
  personalize.py tg_shot shoots at #faq.
- Sticky pill: visibility-hidden when off (a full-page capture showed the parked pill over the report card).
- Removed layers share the live layers' boxes (Reddit notice in the media slot, leak-site 404 in one pane).
- Pip bar in the palette (deep mulberry, pink mute); no poster: the player autoplays its own intro, a poster would not show.
- Dark mode dims the always-light mocks with filter: brightness(.93) (#fff -> ~#ededed); computed colours stay exact (e2e).
## Round 4 notes (design-runs/direction-r4.md, "the docket")
- Phone 390: 8,064 px (measured; r3 ~8,600, target ~7,400). 1440: 6,644. CLS 0 both; scrollWidth = width at 320 / 360 / 390.
  Over target: hero 1,106 (the docket carries the 16:9 video slot + the player's 40 px bar, 3 assurance lines, the
  honest "Example report" foot), why 807, showcase 1,123, pricing 994. The rest is within ~60 px of the doc.
- Hero: the docket = form header row (one row at >= 720 px), note + assurances, example rows left, .pip-slot right.
  pip.js docks the player exactly on .pip-slot; without a slot it keeps the old off-the-card spots.
- The live report is a paper sheet laid in the docket (page tokens), so inline.py's placeholder checks hold.
  Wide docket (>= 960 px): its Images grid is 2 x 8 (16 tiles, --live-grid-rows / --live-grid-cols read by
  inline-scan.js), so the settled card fits 1440x800 with the Send buttons.
- Shared ?r= link on a phone: brought up when the card sits below mid-screen (was: below the fold; the docket put it
  above the fold at 844).
- #removals: one stage, 4 tabs (E.tablist; the doc said radiogroup, tabs fit 4 panels in the DOM better). First glide
  6 s after a panel is first visible. The removed message sits in the layer's right half, shows at p <= 50 and waits
  for the glide to end: 0 seam cuts in 20 s samples of every panel (measured).
- Lead wraps to 3 lines at 1440 (46ch), so the docket starts at y~444, not 412.
- Ask-AI launcher text unchanged ("Ask AI before you DM me"): askai.py asserts it verbatim.

## Round 5 notes
- Demo frame: iframe 560 px, no fade; the demo hero (name, tagline, both buttons) fits at 390 and 1440.
- Phone mocks (#free, before/after): flex column-wrap panels, wrappers display:contents, 4 px flex gap (no trailing
  margin): an item that doesn't fit whole wraps off-screen. Image tiles fixed height (84 / 96 px). Screens 442 / 358 px.
- Dark mocks: #26222B surface, #9DB7FF links, #E8E6EC text; light values unchanged.
- Thumbs: blurred photo crops from assets/phone/ (no gradient art).
- Docket: "570 of 633" proof line (already in #why) in the left column's foot at >= 960, baseline with the video
  caption; hidden once a scan is live.
- Pip poster (landing only): portrait + "Jaka, 57 s" + play mark over the muted autoplay; first pointerdown / key on
  the player removes it and restarts the take at 0 (intro kept). Start offset (a) rejected: the intro covers 0.3-9.8 s,
  every frame in it has overlays. Not a control: pip.py overPic stays 0.
- Secondary h2s (removals, FAQ, contact, before/after h3) clamp 28-40 px; why/how/pricing keep 52.

## Round 6 notes
- design-runs/tools/build.py retired: site/index.html is the source (static, no build). Edit it directly.
- Pip poster: until the first play only the poster (one play mark, "Jaka, 57 s · Tap to watch"); bar + grip
  visibility:hidden (40 px kept: CLS 0, slot rule holds). Tap / Enter / Space on it = expand with sound. Under 260 px
  wide (phone floating) the mark + caption sit in the bar's strip. pip.py had no bar-before-play assertion: unchanged.
- Said once: authorization line in the hero lead + pricing note only; "570 of 633" in the docket only.
- Removals: idle knob parked 8 px inside the corner; dark 8 px frame drawn as box-shadow (same inner box as light,
  so the knob clears the 390 px X thumbs). Stage height stays 372 (removals.py fp crop asserts it). Facts list
  (notice / recipients / report) from 1200 px only, where the left column has room.
- Demo: GALWAY vs headband not fixable without touching showcase/ (demo hero min-height 600 in a 560 frame): left.

## Round 7 notes
- e2e FAILs on 5af3448, all fixed in the site; no check edited.
  - tabs: gallery sync re-entered from add() (cached thumb) and appended duplicates; skip srcs already in the box (scan-engine.js).
  - personalize + inline "phones": phone BA hid the off screen with display:none; now both stacked in one cell, visibility.
  - inline #website: smooth fragment scroll stopped short; html.arriving = instant first landing.
  - inline card fit (phone) and lcol 630 (desktop): live-card margins.
  - askai disclaimer + #contact label: copy restored.
- Judge: proof line under the video on phone (short copy, one 14 px line) and 16 px under the rows on desktop; pip poster 16:9 full column;
  #free mock 460 px (520 pushed h2 to 4 lines / #free > 640); FAQ side block (photo, "I answer every message myself", Telegram);
  contact h2 breaks after "scan?"; hero labels 14 px, label + value centred on one left edge; dark frame inside the column;
  stage tooltip; #how without the caps tier, step 3 "(optional)"; dark --muted #c8c1d2, --deep-muted #dcc6d3, docket field
  edge #8f6a80 (3.7:1); Mega mock without "Trending" / "Open link" (removals.py asserts neither).

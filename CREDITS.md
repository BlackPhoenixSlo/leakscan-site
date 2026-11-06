# Credits

- **Icons**: [Lucide](https://lucide.dev) v0.546.0, ISC License. Copyright (c) for portions of Lucide are held by
  Cole Bemis 2013-2023 as part of Feather (MIT). All other copyright (c) for Lucide are held by Lucide Contributors 2025.
  Used as an inline SVG sprite in `site/*.html`; the logo/favicon shield is Lucide `shield-check`.
- **Fonts** (self-hosted in `site/fonts/`, subset to Latin + punctuation with fontTools; no font CDN at runtime):
  - Young Serif, by Jack Halten Fahnestock. SIL Open Font License 1.1. `young-serif.woff2` (23 KB).
  - Schibsted Grotesk, by Schibsted Media Group with Bakken & Bæck. SIL Open Font License 1.1. `schibsted-grotesk.woff2`
    (variable, weights 400 to 800, 39 KB).
  License texts: `site/fonts/OFL-*.txt`. The demo site and video page keep their own stacks.
  The showcase demo uses system font stacks too (display: Georgia; body: system-ui), no web fonts.
- **Photos**: the showcase demo (`site/showcase/imgs/`) uses Pexels photos (Pexels License), credited per file in
  `tools/showcase/CREDITS.md`. The landing page reuses small crops of those same photos (the fictional demo creator's
  "own" pictures) in two places: `site/assets/phone/` (After phone, Images / Videos tabs) and `site/img/removals/`
  (blurred thumbnails in the `#removals` mock-ups). The `/video/` demo reuses those same crops in its cards.
  `site/assets/jaka.webp` (Jaka's photo) is a frame of his own take (`site/video/jack.mp4` at 45.0 s, cropped with
  ffmpeg). `site/assets/demo/` holds `top.webp`, a screenshot of the demo site's top (`site/showcase/`, the photos above), the
  phone still that opens the demo full screen. Everything else on the landing pages is CSS/SVG drawn for this site (device mockups, gradient thumbnails). Google's name and colours appear only inside illustrative mockups.
- **Video**: `site/video/` ships Jack's own recording (one 56.9 s take, his face and voice, no stock footage):
  `jack.webm` (VP9) + `jack.mp4` (H.264), and `transcript.json` (his words, transcribed locally; see `site/video/CUES.md`).
  The link-preview image in `site/assets/` (`og-jack.jpg`, from `tools/og.html`) uses one frame of that same take (1.47 s).

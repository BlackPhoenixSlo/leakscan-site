# Credits

- **Icons**: [Lucide](https://lucide.dev) v0.546.0, ISC License. Copyright (c) for portions of Lucide are held by
  Cole Bemis 2013-2023 as part of Feather (MIT). All other copyright (c) for Lucide are held by Lucide Contributors 2025.
  Used as an inline SVG sprite in `site/*.html`; the logo/favicon shield is Lucide `shield-check`.
- **Brand marks**: [Simple Icons](https://simpleicons.org) v16.36.0, CC0 1.0: the X, MEGA and Reddit glyphs (`i-logo-*` in the
  sprites of `site/index.html`, `site/video/index.html`), shown only in the illustrative `#removals` / `/video/` mockups.
  The marks and names are trademarks of their owners; no endorsement implied.
- **Fonts** (self-hosted in `site/fonts/`, subset to Latin + punctuation with fontTools; no font CDN at runtime):
  - Young Serif, by Jack Halten Fahnestock. SIL Open Font License 1.1. `young-serif.woff2` (23 KB).
  - Schibsted Grotesk, by Schibsted Media Group with Bakken & Bæck. SIL Open Font License 1.1. `schibsted-grotesk.woff2`
    (variable, weights 400 to 800, 39 KB).
  License texts: `site/fonts/OFL-*.txt`. The demo site and video page keep their own stacks.
  The showcase demo uses system font stacks too (display: Georgia; body: system-ui), no web fonts.
- **Photos**: the showcase demo (`site/showcase/imgs/`) uses Pexels photos (Pexels License), credited per file in
  `tools/showcase/CREDITS.md`. The landing page reuses small crops of those same photos (the fictional demo creator's
  "own" pictures) in two places: `site/assets/phone/` (After phone, Images / Videos tabs) and `site/img/removals/`
  (blurred thumbnails in the `#removals` mock-ups).
  The `/video/` demo's default cards use their own Pexels photos (Pexels License), square WebP crops in `site/video/img/`:
  blurred "leak" thumbs = men in swimsuits, the after state's own photos = men in suits. None of them is affiliated with LeakScan.
  - `leak-1.webp`: [Portrait of a Shirtless Man Standing on a Beach](https://www.pexels.com/photo/18126932/), Maksim Darling
  - `leak-2.webp`: [A Man at the Beach](https://www.pexels.com/photo/8567521/), Baset Alhasan
  - `leak-3.webp`: [Shirtless Man in Shorts Holding a Paddle Board and Paddle Standing on Beach](https://www.pexels.com/photo/6737861/), Gaspar Zaldo
  - `leak-4.webp`: [A Man Sitting on a Beach](https://www.pexels.com/photo/12474404/), Collis Torrington
  - `leak-5.webp`: [A Shirtless Man Wearing Shorts on a Wooden Boardwalk](https://www.pexels.com/photo/13069429/), Alvin Caal
  - `leak-6.webp`: [Man on the Beach](https://www.pexels.com/photo/935974/), nappy
  - `own-1.webp`: [Professional Portrait of a Confident Man in Suit](https://www.pexels.com/photo/30033723/), Mustapha Damilola
  - `own-2.webp`: [Smiling Man in Suit Portrait](https://www.pexels.com/photo/20715518/), Ali Drabo
  - `own-3.webp`: [Elegant young bearded businessman in suit and tie in downtown](https://www.pexels.com/photo/4195342/), Dinielle De Veyra
  - `own-4.webp`: [Man in Blue Business Suit with Arms Crossed](https://www.pexels.com/photo/7144180/), Antoni Shkraba
  - `own-5.webp`: [Man in Suit with Tie](https://www.pexels.com/photo/18642682/), Joseph Okon
  - `own-6.webp`: [Professional Business Portrait of a Man in Suit](https://www.pexels.com/photo/39974539/), Sam Agdasi
  `site/assets/jaka.webp` (Jaka's photo) is a frame of his own take (`site/video/jack.mp4` at 45.0 s, cropped with
  ffmpeg). `site/assets/demo/` holds `top.webp`, a screenshot of the demo site's top (`site/showcase/`, the photos above), the
  phone still that opens the demo full screen. Everything else on the landing pages is CSS/SVG drawn for this site (device mockups, gradient thumbnails). Google's name and colours appear only inside illustrative mockups.
- **Video**: `site/video/` ships Jack's own recording (one 56.9 s take, his face and voice, no stock footage):
  `jack.webm` (VP9) + `jack.mp4` (H.264), and `transcript.json` (his words, transcribed locally; see `site/video/CUES.md`).
  The link-preview image in `site/assets/` (`og-jack.jpg`, from `tools/og.html`) uses one frame of that same take (1.47 s).

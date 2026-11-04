# Improvement loop

Every 2 hours, 50 runs max. Each run: review the live site, make one or more real improvements, PR, merge once green,
verify live, append a row here. Stop at run 50.

| run | date (UTC) | PR | what changed | evidence folder |
|---|---|---|---|---|
| 1 | 2026-11-04 | #4 | hide showcase demo ribbon when framed (Back link nested landing in iframe); shots.py unique names; check.py checks showcase/ link; README/CREDITS fixes | 20261104T004756Z-798c458 |
| 2 | 2026-11-04 | #5 | Telegram CTAs prefill message (plan-specific on pricing); price in hero; meta desc <=160; softened ranking claims; check.py: title/desc length + CTA prefill | 20261104T024636Z-6d885bd |
| 3 | 2026-11-04 | #7 | og.png 165->61 KB (quantized, recipe in make_icons.py) + check.py raster budget 100 KB; hero check icon on first line; showcase timeline/links/verify consistency (go-live before posts, patron first-pick, "most" fakes) | 20261104T045045Z-2a21b6f |
| 4 | 2026-11-04 | #8 | a11y: demo iframe tabindex=-1 (Tab stops hero->demo link 32->1 phone, 37->1 desktop); mobile menu closes on focus-out; showcase lightbox visibility:hidden when closed; check.py: iframe title + tabindex gate. Perf audited (5 req, 19.5 KB, CLS 0), no change | 20261104T065055Z-141091b |
| 5 | 2026-11-04 | #9 | showcase gallery keyboard-operable (img in real button, focus ring on item), lightbox focus to close/back to opener, Tab kept inside, Esc only when open; backlog: inline CSS no, showcase 404 keep | loop/run-5/20261104T084510Z-6c91d7a |
| 6 | 2026-11-04 | #10 | privacy.html discloses showcase Google Fonts (homepage iframe + /showcase/ hit fonts.googleapis/gstatic; policy said no outside requests); check.py gate keeps showcase third-party hosts and privacy in sync; README/CREDITS corrected | loop/run-6/20261104T104622Z-a81b3a4 |
| 7 | 2026-11-04 | #11 | showcase a11y: menu toggle 32x23->44x44, lightbox close 19x32->44x44 (no visual shift), fact-card h4->h2/h3 (no level skips); headshot.webp 1200->480 px, 185->25 KB, make_images.py rebuilds named files. Audited: WCAG AA contrast 8 pages light+dark clean | loop/run-7/20261104T125701Z-8809efc |
| 8 | 2026-11-04 | #12 | showcase blog.html had no h1: heading h2->h1, cards h3->h2, look unchanged; check_pages.py gate: one h1 + no heading skips per showcase page. Audited live: 21 URLs 200, landing CLS 0, no console errors | loop/run-8/20261104T144722Z-1a9fe8e |
| 9 | 2026-11-04 | #13 | a11y: Tab-focused controls stayed opacity 0 (reveal observer -8% band: FAQ summary desktop, "Open the demo site" phone); focusin now reveals the block. Tab walk hidden focus stops 1->0 phone+desktop. Audited: 404 nested path, reduced-motion, OG/sitemap, showcase focus clean | loop/run-9/20261104T165434Z-dd9efec |
| 10 | 2026-11-04 | #14 | showcase content invisible with JS off (20 [data-fade] blocks, 5 pages, opacity 0 ungated): fade now scoped under html.js set inline in head; check_pages.py gate (inline flag + .js-scoped CSS). Audited: 15 URLs 200, 320px + landscape no overflow, contact hrefs ok | loop/run-10/20261104T184516Z-6d7da1b |
| 11 | 2026-11-04 | #17 | check.py: every outside host in site/js/*.js (scan API, jackbase.me) must be named in privacy.html (was ungated; break-once 3 faults red). Audited live: 19 URLs 200, pages ok light+dark; backlog open items owner-only | loop/run-11/20261104T204655Z-5257adb |
| 12 | 2026-11-05 | #27 | phone Ask-AI launcher hidden while hero on screen (covered hero text/WhatsApp at 360-600px, now 0/6 widths); report link in DMs = serving host via script URL, not hardcoded github.io (Pages unchanged); e2e 343/0, break-once 6 targeted red. Audited live: 36 URLs 200, meta/JSON-LD/sitemap brand consistent | loop/run-12/20261104T224837Z-4c9ed2f |

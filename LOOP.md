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

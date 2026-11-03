# leakscan-site

Landing site for LeakScan: personal leak-removal service for creators (Google Ads landing).
Static HTML/CSS, no build. `site/` is what ships. `site/showcase/` is a demo of the official site each client gets
(built from the `template` branch of `tessa_site`).

- Preview: `python3 -m http.server 8920 --directory site` → http://127.0.0.1:8920/
- Gate: `python3 tools/check.py` (silent when green; any output = fail)
- Deploy: GitHub Pages from `main` via `.github/workflows/pages.yml`; `netlify.toml` publishes `site/` if connected to Netlify.
- Improvement loop: `LOOP.md`

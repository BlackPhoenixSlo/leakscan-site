#!/usr/bin/env python3
"""
report_to_pdf.py — render the self-contained client report HTML to a single PDF.

Renders the PLAINTEXT `<prefix>-report.html` (NOT the AES-GCM protected one — that
is an encrypted gate that never paints). A PDF is a flat snapshot, so we transform
the DOM before printing so nothing that only works on-screen is lost on paper:

  • REVEAL   — the gallery images are CSS-blurred with a tap/reveal toggle a PDF
    can't use, so by default we reveal everything (--keep-blur to keep the blur).
  • UNWRAP   — the galleries are horizontal drag-rows / marquees; only the tiles in
    view would print, so we flex-wrap them and show each image uncropped.
  • BOT→FAQ  — the live "Ask about your report" chat is dead in a PDF, so we drop it
    and drop in a static Frequently-Asked-Questions card built from kb.json.
  • REORDER  — clean report flow: hero → the numbers → evidence → detail → all links
    → FAQ → one DM call-to-action → footer (de-dupes the repeated CTA/chat blocks).
  • DECHROME — hide the reveal toggle, "tap to reveal" pills and download/copy
    buttons that do nothing on paper.

Headless Chromium via Playwright (same interpreter the pipeline already uses).
    python3 report_to_pdf.py --in cinnanicos-report.html --out cinnanicos-report.pdf
    python3 report_to_pdf.py --in cinnanicos-report.html --keep-blur

SECURITY: the input HTML carries the baked DeepSeek key inside a <script> (scripts
are NOT rendered, so the key does not appear in the PDF) and the PDF shows the
revealed NSFW evidence — treat it like the plaintext report: keep it LOCAL / send
on a secure channel, never publish it.
"""
import argparse
import html
import json
import os
import pathlib
import sys

# reveal blurred media
REVEAL_CSS = """
.gt img,.mt img{filter:none !important;transform:none !important}
.gt .lk2,.mt .lk2,.lk2{display:none !important}
.rvd{background:var(--ok) !important}
"""

# unwrap the horizontal scrollers, hide dead on-paper chrome, style the FAQ card.
# NB: break-inside:avoid is applied ONLY to small tiles — never to a <section>/.card,
# or a multi-page gallery would get shoved onto a fresh page and blank the one above it.
PRINT_CSS = """
html,body{background:#0e1020 !important}
.dragrow,.galrow{display:flex !important;flex-wrap:wrap !important;
  overflow:visible !important;width:auto !important;cursor:default !important}
.strip{overflow:visible !important}
.strip .track{animation:none !important;width:auto !important;
  display:flex !important;flex-wrap:wrap !important}
.gt{width:47% !important;height:auto !important;max-height:none !important}
.gt img{height:auto !important;object-fit:contain !important}
.mt,.mt.port{width:30% !important;height:auto !important}
.mt img{width:100% !important;height:auto !important;object-fit:contain !important}
.gt,.mt,.stat,.bar{break-inside:avoid}
/* chrome that only works with a mouse/JS — pointless in a PDF */
.toggle,.pill.warn,.qr,.btn,.cform{display:none !important}
/* FAQ card (replaces the live chat) */
.faqcard .faqlist{display:flex;flex-direction:column;gap:0;margin-top:12px}
.faqcard .fitem{padding:12px 0;border-bottom:1px solid rgba(124,92,255,.14);break-inside:avoid}
.faqcard .fitem:first-child{padding-top:4px}
.faqcard .fitem:last-child{border-bottom:0;padding-bottom:2px}
.faqcard .fq{color:#eef0ff;font-weight:650;font-size:14.5px}
.faqcard .fa{color:#c7cbf0;font-size:13.5px;line-height:1.6;margin-top:3px}
.faqcard .fq::before{content:"Q  ";color:var(--acc2);font-weight:800}
.faqcard .fa::before{content:"A  ";color:var(--acc);font-weight:800}
.faqcard{break-inside:auto}
/* "All detected leak links" — collapsed <details> look like dead UI on paper;
   rebuilt (in JS) as a clean 2-column site → count table */
.linksgrid{column-count:2;column-gap:30px;margin-top:14px}
.linksgrid .grow{break-inside:avoid;-webkit-column-break-inside:avoid;padding:7px 2px}
.linksgrid .gdom{font-weight:600}
.linksgrid .gurls{font-variant-numeric:tabular-nums}

/* ── finishing touches ─────────────────────────────────────────────── */
*{-webkit-print-color-adjust:exact;print-color-adjust:exact}
/* freshness: a short gradient accent under every section heading */
.card h2::after,.sec h2::after{content:"";display:block;width:36px;height:3px;
  margin:9px 0 1px;border-radius:2px;background:linear-gradient(90deg,var(--acc),var(--acc2))}
/* readability: never strand a heading (or its lead) at the foot of a page */
h1,h2,.lead,.sechead{break-after:avoid}
.stat,.bar,.gt,.mt,.grow{break-inside:avoid}
/* emotional + conversion: a calm reassurance note that warms into the CTA */
.reassure{text-align:center;max-width:660px;margin:26px auto 6px;padding:18px 24px;border-radius:16px;
  background:radial-gradient(130% 130% at 50% 0,rgba(56,217,199,.11),rgba(124,92,255,.06));
  border:1px solid rgba(56,217,199,.22);break-inside:avoid}
.reassure b{display:block;font-size:16.5px;margin-bottom:5px;color:#fff}
.reassure span{color:var(--mut);font-size:13.5px;line-height:1.65}
/* a hairline lead-in above the closing footer */
footer{border-top:1px solid var(--line);padding-top:20px}
"""


def _faq_html(kb_path):
    """Build the FAQ card's inner HTML from kb.json (faq list). '' if unavailable."""
    try:
        faq = json.load(open(kb_path, encoding="utf-8")).get("faq", [])
    except Exception:
        return ""
    rows = "".join(
        f'<div class="fitem"><div class="fq">{html.escape(x.get("q", ""))}</div>'
        f'<div class="fa">{html.escape(x.get("a", ""))}</div></div>'
        for x in faq if x.get("q") and x.get("a"))
    if not rows:
        return ""
    return ('<h2>\U0001f4ac Frequently asked questions</h2>'
            '<p class="lead">How takedowns work — and how you can act yourself.</p>'
            f'<div class="faqlist">{rows}</div>')


# DOM surgery: drop the chat, de-dupe the CTA, move the numbers up, drop in the FAQ.
REORDER_JS = """
(faqHtml) => {
  // 1. remove the live chat widgets — a chat box does nothing in a PDF
  document.querySelectorAll('.chat').forEach(el => el.remove());
  // 2. de-duplicate the DM call-to-action — keep only the last one
  const ctas = [...document.querySelectorAll('.ctabar')];
  ctas.slice(0, -1).forEach(el => el.remove());
  const lastCta = ctas.length ? ctas[ctas.length - 1] : null;
  // 3. numbers first — move the stat grid up to sit right under the hero
  const hero = document.querySelector('.hero');
  const stats = document.querySelector('.stats');
  if (hero && stats) hero.after(stats);
  // 4. drop the FAQ card in just before the final CTA (evidence → FAQ → CTA → footer)
  if (faqHtml) {
    const faq = document.createElement('section');
    faq.className = 'card faqcard';
    faq.innerHTML = faqHtml;
    const footer = document.querySelector('footer');
    if (lastCta) lastCta.parentNode.insertBefore(faq, lastCta);
    else if (footer) footer.parentNode.insertBefore(faq, footer);
    else document.querySelector('.wrap').appendChild(faq);
  }
  // 5. the gallery lead still says "auto-scrolling / hover to pause" — wrong on paper
  document.querySelectorAll('.lead').forEach(p => {
    if (/auto-scroll|hover to pause/i.test(p.textContent))
      p.textContent = 'Actual copies of your leaked content found across the piracy sites & Google.';
  });
  // 6. "All detected leak links": the collapsed <details> rows print as dead
  //    disclosure triangles with ragged counts — rebuild as a clean 2-col table
  const linkCard = [...document.querySelectorAll('.card')].find(
    c => /All detected leak links/i.test((c.querySelector('h2') || {}).textContent || ''));
  if (linkCard) {
    const rows = [...linkCard.querySelectorAll('details.lg')].map(d => {
      const sum = d.querySelector('summary');
      const cnt = ((d.querySelector('.mut') || {}).textContent || '');       // "· 200"
      const num = (cnt.match(/\\d[\\d,]*/) || [''])[0];
      const dom = (sum ? sum.textContent.replace(cnt, '') : '')
        .trim().replace(/[·•]\\s*$/, '').trim();
      return { dom, num };
    }).filter(r => r.dom);
    if (rows.length) {
      const grid = document.createElement('div');
      grid.className = 'linksgrid';
      grid.innerHTML = rows.map(r =>
        '<div class="grow"><span class="gdom">' + r.dom +
        '</span><span class="gurls">' + r.num + '</span></div>').join('');
      linkCard.querySelectorAll('details.lg').forEach(d => d.remove());
      linkCard.appendChild(grid);
      const lead = linkCard.querySelector('.lead');
      if (lead) lead.textContent =
        'Every confirmed leak, grouped by site — ' + rows.length + ' sites in total.';
    }
  }
  // 7. a calm reassurance note right before the CTA (emotional + conversion)
  const reassure = document.createElement('section');
  reassure.className = 'reassure';
  reassure.innerHTML =
    "<b>You're not alone — and you're in control.</b>" +
    "<span>This is your content, and you have every right to have it removed. " +
    "We handle every takedown, every host, every re-upload — from start to finish.</span>";
  const cta2 = document.querySelector('.ctabar');
  if (cta2) cta2.parentNode.insertBefore(reassure, cta2);
  else {
    const footer = document.querySelector('footer');
    if (footer) footer.parentNode.insertBefore(reassure, footer);
  }
}
"""


def render(inp, out, reveal=True, fmt="A4", kb_path="kb.json"):
    from playwright.sync_api import sync_playwright

    src = pathlib.Path(inp).resolve()
    if not src.exists():
        sys.exit(f"input not found: {src}")
    head = src.read_text(encoding="utf-8", errors="replace")[:4000]
    if "AES-GCM" in head or "decryptReport" in head or "Password Required" in head:
        sys.exit(f"{src.name} looks PASSWORD-PROTECTED (encrypted) — render the plaintext "
                 f"'<prefix>-report.html' instead.")

    faq_html = _faq_html(pathlib.Path(kb_path))
    css = PRINT_CSS + (REVEAL_CSS if reveal else "")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1240, "height": 1650})
        page.goto(src.as_uri(), wait_until="load")
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(700)
        if reveal:
            page.evaluate(
                "() => { const r = document.getElementById('reveal'); if (r) r.checked = true; }")
        page.evaluate(REORDER_JS, faq_html)
        page.add_style_tag(content=css)
        page.wait_for_timeout(300)
        page.emulate_media(media="screen")  # keep the dark theme + gradients
        page.pdf(
            path=str(pathlib.Path(out).resolve()),
            format=fmt,
            print_background=True,
            prefer_css_page_size=False,
            margin={"top": "8mm", "bottom": "8mm", "left": "8mm", "right": "8mm"},
        )
        browser.close()
    kb = os.path.getsize(out) / 1024
    print(f"{out}: {kb:.0f} KB  (reveal={reveal}, faq={'yes' if faq_html else 'no'}, {fmt})")


def main():
    ap = argparse.ArgumentParser(description="Render the client report HTML to a PDF.")
    ap.add_argument("--in", dest="inp", required=True, help="plaintext <prefix>-report.html")
    ap.add_argument("--out", default="", help="output .pdf (default: <in>.pdf)")
    ap.add_argument("--format", default="A4", help="paper size (A4, Letter, ...)")
    ap.add_argument("--kb", default="kb.json", help="knowledge base json for the FAQ card")
    ap.add_argument("--keep-blur", action="store_true",
                    help="keep the gallery images blurred (default: reveal everything)")
    args = ap.parse_args()
    out = args.out or (os.path.splitext(args.inp)[0] + ".pdf")
    render(args.inp, out, reveal=not args.keep_blur, fmt=args.format, kb_path=args.kb)


if __name__ == "__main__":
    main()

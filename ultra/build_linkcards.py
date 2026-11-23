#!/usr/bin/env python3
"""build_linkcards.py — synthetic "leak index" screenshots for the client report.

The presence scan ({prefix}-scan.json) already knows WHICH known piracy domains host the
creator and the exact search/tag URL on each (e.g. https://fapfappy.com/search/janedoee).
This renders the strongest confirmed-hit domains as a modern browser window screenshot: the
address bar shows a real per-site URL (built from the handle, like `janedoee` on a used
domain), and the page body is a result list of the real, useful links where the leaks live —
so the report can lead with "here is where this creator is reposted" evidence.

No live browser touches those sites (cse-mode parity): the card is local HTML rendered to PNG
headless via Playwright, exactly like build_google_shots.py. Self-contained, never raises fatal.

    python3 build_linkcards.py --scan janedoee-scan.json --name janedoee \
        --out-dir janedoee_images --cards 1 --rows 14
"""
import argparse, html, json, os, re
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright


def esc(s):
    return html.escape(s or "", quote=True)


def host(u):
    h = (urlsplit(u).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _dot(dom):
    """Deterministic favicon-dot color from the domain (so each row reads as a distinct site)."""
    palette = ["#8ab4f8", "#f28b82", "#fdd663", "#81c995", "#c58af9", "#78d9ec", "#ff8bcb", "#f6ae5c"]
    return palette[sum(ord(c) for c in (dom or "x")) % len(palette)]


def _load_hits(scan_path):
    """Confirmed hits from the presence scan, strongest first (verified content matches, then
    raw occurrences). Each carries the real per-site URL where the creator surfaces."""
    try:
        data = json.load(open(scan_path, encoding="utf-8"))
    except Exception:
        return []
    hits = [x for x in data if isinstance(x, dict) and x.get("hit") and x.get("url")]
    # one row per domain (the scan can list a domain twice under different aliases)
    seen, uniq = set(), []
    hits.sort(key=lambda x: (-(x.get("content_matches") or 0), -(x.get("occurrences") or 0)))
    for x in hits:
        d = host(x["url"]) or (x.get("domain") or "")
        if d in seen:
            continue
        seen.add(d)
        uniq.append(x)
    return uniq


def _cap_name(name):
    n = (name or "").strip()
    return " ".join(w[:1].upper() + w[1:] for w in n.split()) or "This creator"


def card_html(chrome_url, name, rows):
    """A modern browser window: traffic-light chrome + address bar + a result list of the real
    per-site leak URLs. Dark theme, 1040px wide (matches build_google_shots' render width)."""
    cap = _cap_name(name)
    rr = ""
    for r in rows:
        dom = host(r["url"]) or (r.get("domain") or "")
        cm = r.get("content_matches") or 0
        occ = r.get("occurrences") or 0
        badge = (f'<span class="vf">&#10003; verified · {cm} matches</span>' if cm else
                 (f'<span class="vf">{occ} results</span>' if occ else ""))
        title = f"{cap} — {dom} (leaked)"
        rr += (f'<div class="row"><div class="fav" style="background:{_dot(dom)}"></div>'
               f'<div class="meta"><div class="site">{esc(dom)}{badge}</div>'
               f'<div class="ttl">{esc(title)}</div>'
               f'<div class="url">{esc(r["url"][:96])}</div></div>'
               f'<div class="open">Open &#8250;</div></div>')
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0}}
body{{background:#0b0e14;color:#e8eaed;font:14px/1.5 -apple-system,Segoe UI,Roboto,Arial,sans-serif;width:1040px;padding:22px}}
.win{{border:1px solid #232a38;border-radius:14px;overflow:hidden;background:#0e131c;box-shadow:0 24px 60px -20px rgba(0,0,0,.7)}}
.chrome{{display:flex;align-items:center;gap:12px;padding:12px 16px;background:#151b26;border-bottom:1px solid #232a38}}
.lights{{display:flex;gap:7px}}.lights i{{width:12px;height:12px;border-radius:50%;display:block}}
.lights .r{{background:#ff5f57}}.lights .y{{background:#febc2e}}.lights .g{{background:#28c840}}
.addr{{flex:1;display:flex;align-items:center;gap:9px;background:#0b0f17;border:1px solid #2a3040;border-radius:20px;padding:8px 15px;color:#cdd3df;font:13px ui-monospace,SFMono-Regular,Menlo,monospace}}
.addr .lk{{color:#78d9ec}}.addr .pth{{color:#e8eaed}}
.tag{{font:700 10px ui-monospace,monospace;color:#ff6b6b;border:1px solid #4a2230;background:rgba(74,34,48,.3);padding:3px 8px;border-radius:6px;letter-spacing:.4px}}
.head{{padding:16px 20px 6px;border-bottom:1px solid #1a2130}}
.head h2{{font-size:17px;font-weight:800;letter-spacing:-.2px}}
.head .sub{{color:#8b93a7;font-size:13px;margin-top:3px}}
.list{{padding:6px 0 10px}}
.row{{display:flex;align-items:center;gap:13px;padding:12px 20px;border-bottom:1px solid #141a26}}
.row:last-child{{border-bottom:0}}
.fav{{width:26px;height:26px;border-radius:7px;flex:0 0 auto}}
.meta{{flex:1;min-width:0}}
.site{{font-size:12px;color:#9aa3b6;display:flex;align-items:center;gap:9px}}
.vf{{color:#81c995;font:700 11px ui-monospace,monospace}}
.ttl{{color:#8ab4f8;font-size:15.5px;font-weight:600;margin:1px 0}}
.url{{color:#6f778c;font:12px ui-monospace,SFMono-Regular,Menlo,monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.open{{flex:0 0 auto;color:#cdd3df;font-size:13px;background:#1b2230;border:1px solid #2a3040;border-radius:9px;padding:6px 12px}}
</style></head><body>
<div class="win">
  <div class="chrome"><div class="lights"><i class="r"></i><i class="y"></i><i class="g"></i></div>
    <div class="addr"><span class="lk">https://</span><span class="pth">{esc(chrome_url)}</span></div>
    <span class="tag">LEAK INDEX</span></div>
  <div class="head"><h2>{esc(_cap_name(name))} — content indexed on {len(rows)} sites</h2>
    <div class="sub">Real, de-duplicated links from the presence scan · open any to view the reposted content</div></div>
  <div class="list">{rr}</div>
</div>
</body></html>'''


def main():
    ap = argparse.ArgumentParser(description="Render synthetic 'leak index' browser screenshots.")
    ap.add_argument("--scan", required=True, help="{prefix}-scan.json from the presence scan")
    ap.add_argument("--name", required=True, help="creator handle / display name")
    ap.add_argument("--out-dir", required=True, help="dir to write linkcard_*.png (e.g. {prefix}_images)")
    ap.add_argument("--cards", type=int, default=1, help="how many cards to render (top domains lead)")
    ap.add_argument("--rows", type=int, default=14, help="link rows per card")
    a = ap.parse_args()

    hits = _load_hits(a.scan)
    if not hits:
        print(f"[linkcards] no confirmed hits in {a.scan} — nothing to render")
        return
    os.makedirs(a.out_dir, exist_ok=True)

    written = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1040, "height": 900}, device_scale_factor=2)
        for i in range(max(1, a.cards)):
            lead = hits[i] if i < len(hits) else hits[0]
            chrome_url = (lead["url"].split("://", 1)[-1])            # strip scheme for the address bar
            # each card leads with a distinct domain but lists the strongest links overall, so a
            # single-card report still shows the full "where the leaks are" picture.
            rows = ([lead] + [h for h in hits if h is not lead])[: max(1, a.rows)]
            html_str = card_html(chrome_url, a.name, rows)
            out = os.path.join(a.out_dir, f"linkcard_{i + 1}.png")
            pg.set_content(html_str, wait_until="networkidle")
            pg.wait_for_timeout(250)
            pg.screenshot(path=out, full_page=True)
            written.append(out)
            print(f"[linkcards] wrote {out}  ({host(lead['url'])} + {len(rows)} links)")
        b.close()

    # a tiny manifest so callers can label the lead domain without re-parsing the PNG
    try:
        json.dump([{"png": os.path.basename(w), "domain": host(hits[j]["url"]),
                    "url": hits[j]["url"]} for j, w in enumerate(written)],
                  open(os.path.join(a.out_dir, "linkcards.json"), "w"), indent=2)
    except Exception:
        pass
    print(f"[linkcards] {len(written)} card(s) -> {a.out_dir}/")


if __name__ == "__main__":
    main()

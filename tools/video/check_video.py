#!/usr/bin/env python3
"""Gate for site/video/ (Jack's video page). Silent + exit 0 when green; prints each problem + exit 1.

- exactly the 5 prefabs google, google-images, x, reddit, mega (in script order), each with numeric data-cue-live <
  data-cue-removed < data-cue-out, and no overlap: each prefab is out before the next one comes in (cues ascending);
  room for the animations (js/video-overlays.js): removed - live >= 0.4 s slide-in (google-images: >= 1.2 s, its tap +
  grid), out - removed >= 1.95 s (wipe 1.2 + stamp 0.35 + slide-out 0.4)
- after state (the .rm-gone layer) = the landing after-phone: google lists her site (data-vo=site) + instagram.com, no
  leak host (*.example, data-vo=host); google-images shows >= 4 of her own photos (<img>, not the blurred .rm-img) and no
  "No results" / copyright notice
- .vo-stage has a numeric data-cue-say after the last prefab's out (the spoken name)
- the page is noindex and not in sitemap.xml
- no external requests: no http(s):// or protocol-relative src/href/poster in the page, no http(s):// URL in
  js/video-overlays.js or css/video.css (the og:image <meta content> is a URL, not a load)
- the <video> sources exist and the placeholder / real video is <= VIDEO_BUDGET bytes each
Usage: python3 tools/video/check_video.py
"""
import pathlib, re, sys
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
PAGE = SITE / "video" / "index.html"
ORDER = ["google", "google-images", "x", "reddit", "mega"]
MIN_LIVE = {"google-images": 1.2}   # seconds from live to removed (default: the 0.4 s slide-in)
MIN_HOLD = 1.95                     # seconds from removed to out: wipe + stamp + slide-out
CUES = ("data-cue-live", "data-cue-removed", "data-cue-out")
VIDEO_BUDGET = 60_000_000   # the real recording replaces the ~0.2 MB placeholder; keep the repo sane


class P(HTMLParser):
    def __init__(self):
        super().__init__()
        self.prefabs, self.refs, self.robots, self.sources, self.say = [], [], "", [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "vo-stage" in (a.get("class") or "").split():
            self.say = a.get("data-cue-say")
        if "data-prefab" in a:
            self.prefabs.append(a)
        if tag == "meta" and a.get("name") == "robots":
            self.robots = a.get("content") or ""
        if tag == "source":
            self.sources.append(a.get("src") or "")
        for k in ("src", "href", "poster", "srcset"):
            if a.get(k):
                self.refs.append((tag, k, a[k]))


def gone_layer(html, pid):
    """the inner HTML of prefab pid's after layer (.rm-gone … up to its .rm-handle), '' if missing"""
    m = re.search(r'data-prefab="%s".*?class="rm-layer rm-gone[^"]*">(.*?)<span class="rm-handle">' % re.escape(pid), html, re.S)
    return m.group(1) if m else ""


def after_state(html):
    bad = []
    g = gone_layer(html, "google")
    if re.search(r"\.example\b|data-vo=\"host\"", g) or 'data-vo="site"' not in g or "instagram.com" not in g:
        bad.append("video/index.html: google after state must list her site (data-vo=site) + instagram.com and no leak host")
    gi = gone_layer(html, "google-images")
    own = [i for i in re.findall(r"<img\b[^>]*>", gi) if "rm-img" not in i]
    if len(own) < 4 or re.search(r"No results|Digital Millennium", gi):
        bad.append(f"video/index.html: google-images after state needs >= 4 unblurred photos (got {len(own)}), no 'No results' / notice")
    return bad


def main():
    bad = []
    p = P()
    html = PAGE.read_text(encoding="utf-8")
    p.feed(html)
    bad += after_state(html)
    ids = [a.get("data-prefab") for a in p.prefabs]
    if ids != ORDER:
        bad.append(f"video/index.html: prefabs {ids}, want {ORDER}")
    prev_out, prev_id = None, None
    for a in p.prefabs:
        pid = a.get("data-prefab")
        try:
            live, rem, out = (float(a[k]) for k in CUES)
        except (KeyError, TypeError, ValueError):
            bad.append(f"video/index.html: prefab {pid} needs numeric {', '.join(CUES)} (got "
                       f"{[a.get(k) for k in CUES]})")
            continue
        if not 0 <= live < rem < out:
            bad.append(f"video/index.html: prefab {pid} cues not ascending: live {live} < removed {rem} < out {out}")
        if rem - live < MIN_LIVE.get(pid, 0.4):
            bad.append(f"video/index.html: prefab {pid}: removed {rem} - live {live} < {MIN_LIVE.get(pid, 0.4)} s")
        if out - rem < MIN_HOLD:
            bad.append(f"video/index.html: prefab {pid}: out {out} - removed {rem} < {MIN_HOLD} s")
        if prev_out is not None and live < prev_out:
            bad.append(f"video/index.html: prefab {pid} comes in at {live} before {prev_id} is out at {prev_out}")
        prev_out, prev_id = out, pid
    try:
        say = float(p.say)
        if prev_out is not None and say < prev_out:
            bad.append(f"video/index.html: data-cue-say {say} before the last prefab is out at {prev_out}")
    except (TypeError, ValueError):
        bad.append(f"video/index.html: .vo-stage needs a numeric data-cue-say (got {p.say!r})")
    if "noindex" not in p.robots:
        bad.append("video/index.html: no <meta name=robots content=noindex>")
    if "video/" in (SITE / "sitemap.xml").read_text(encoding="utf-8"):
        bad.append("sitemap.xml lists video/ (noindex page)")
    for tag, k, v in p.refs:
        if re.match(r"(https?:)?//", v.strip()):
            bad.append(f"video/index.html: external <{tag} {k}={v}>")
    for f in (SITE / "js" / "video-overlays.js", SITE / "css" / "video.css"):
        for u in re.findall(r"https?://[^\s'\")]+", f.read_text(encoding="utf-8")):
            bad.append(f"{f.relative_to(SITE)}: external URL {u}")
    if not p.sources:
        bad.append("video/index.html: <video> has no <source>")
    for s in p.sources:
        f = PAGE.parent / s
        if not f.is_file():
            bad.append(f"video/index.html: <source src={s}> missing")
        elif f.stat().st_size > VIDEO_BUDGET:
            bad.append(f"video/{s}: {f.stat().st_size} bytes > {VIDEO_BUDGET}")
    for b in bad:
        print(b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

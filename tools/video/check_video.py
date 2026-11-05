#!/usr/bin/env python3
"""Gate for site/video/ (Jack's video page). Silent + exit 0 when green; prints each problem + exit 1.

- exactly the 5 prefabs google, google-images, x, reddit, mega (in script order), each with numeric data-cue-live <
  data-cue-removed < data-cue-out, and no overlap: each prefab is out before the next one comes in (cues ascending);
  room for the animations (js/video-overlays.js): removed - live >= 0.45 s pop-in (google-images: >= 1.2 s, its tap +
  grid; an optional data-cue-tap sits in live + 0.45 .. removed - 0.7), out - removed >= 1.95 s (snap shake 0.25 + wipe
  0.95 + stamp slam 0.2 + slide-out 0.4, room for the confetti); each prefab has its live + gone word card (.vo-kw)
- after state (the .rm-gone layer) = the landing after-phone: google lists her site (data-vo=site) + instagram.com, no
  leak host (*.example, data-vo=host); google-images shows >= 4 of her own photos (<img>, not the blurred .rm-img) and no
  "No results" / copyright notice
- both modes: .vo-stage has numeric data-cue-say (named: the name at the end, after the last prefab's out),
  data-cue-say-start (named: the name in the take's opening gap, its 2 s pill out before the first prefab) and
  data-cue-named-shift >= 0 (jack-named.mp4 runs that much behind jack.mp4); the generic end card (.vo-cta) exists with
  the exact ask + a form (input name=name) and its cue (data-cue-cta, default data-cue-say) is after the last out; the
  "for <name>" pill (.vo-for) exists; js/video-overlays.js keeps the generic name "Your name", the jack-named.mp4 probe
  and the ?sfx=0 switch
- css/video.css has a prefers-reduced-motion: reduce block that drops the particles (.vo-burst) and the shake
- the page is noindex and not in sitemap.xml
- no external requests: no http(s):// or protocol-relative src/href/poster in the page, no http(s):// URL in
  js/video-overlays.js or css/video.css (the og:image <meta content> is a URL, not a load); no audio / font files
  (sound is synthesized, fonts are the system stack): no .mp3/.wav/.ogg/.m4a/.woff/.ttf/.otf reference, no @font-face / @import
- the <video> sources exist and the placeholder / real video is <= VIDEO_BUDGET bytes each
Usage: python3 tools/video/check_video.py
"""
import pathlib, re, sys
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
PAGE = SITE / "video" / "index.html"
ORDER = ["google", "google-images", "x", "reddit", "mega"]
MIN_LIVE = {"google-images": 1.2}   # seconds from live to removed (default: the 0.45 s pop-in)
IN = 0.45
CTA_TEXT = "Type your name in the link → this video rebuilds with YOUR leaks"
MIN_HOLD = 1.95                     # seconds from removed to out: wipe + stamp + slide-out
CUES = ("data-cue-live", "data-cue-removed", "data-cue-out")
VIDEO_BUDGET = 60_000_000   # the real recording replaces the ~0.2 MB placeholder; keep the repo sane


class P(HTMLParser):
    def __init__(self):
        super().__init__()
        self.prefabs, self.refs, self.robots, self.sources, self.stage, self.classes, self.inputs = [], [], "", [], {}, [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        self.classes += cls
        if "vo-stage" in cls:
            self.stage = a
        if tag == "input":
            self.inputs.append(a)
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


def stage_cue(p, k):
    try:
        return float(p.stage[k])
    except (KeyError, TypeError, ValueError):
        return None


def modes(html, p, last_out):
    """the two modes: named (say start / end, shift, pill) and generic (the end card + form at data-cue-cta / -say)"""
    bad = []
    say, start, shift = stage_cue(p, "data-cue-say"), stage_cue(p, "data-cue-say-start"), stage_cue(p, "data-cue-named-shift")
    first_live = float(p.prefabs[0]["data-cue-live"]) if p.prefabs and p.prefabs[0].get("data-cue-live", "").replace(".", "", 1).isdigit() else None
    if say is None:
        bad.append(f"video/index.html: .vo-stage needs a numeric data-cue-say (got {p.stage.get('data-cue-say')!r})")
    elif last_out is not None and say < last_out:
        bad.append(f"video/index.html: data-cue-say {say} before the last prefab is out at {last_out}")
    if start is None:
        bad.append(f"video/index.html: .vo-stage needs a numeric data-cue-say-start (got {p.stage.get('data-cue-say-start')!r})")
    elif first_live is not None and start + 2 > first_live:
        bad.append(f"video/index.html: data-cue-say-start {start} + 2 s pill overlaps the first prefab at {first_live}")
    if shift is None or shift < 0:
        bad.append(f"video/index.html: .vo-stage needs data-cue-named-shift >= 0 (got {p.stage.get('data-cue-named-shift')!r})")
    cta = stage_cue(p, "data-cue-cta") if "data-cue-cta" in p.stage else say
    if cta is None:
        bad.append(f"video/index.html: data-cue-cta {p.stage.get('data-cue-cta')!r} not numeric")
    elif last_out is not None and cta < last_out:
        bad.append(f"video/index.html: end card cue {cta} before the last prefab is out at {last_out}")
    m = re.search(r'<div class="vo-pf vo-cta"[^>]*>(.*?)</form>', html, re.S)
    if not m or CTA_TEXT not in m[1] or not any(i.get("name") == "name" for i in p.inputs) or "<form" not in m[1]:
        bad.append(f"video/index.html: generic end card .vo-cta missing (with {CTA_TEXT!r} + a form, input name=name)")
    if "vo-for" not in p.classes:
        bad.append("video/index.html: named \"for <name>\" pill .vo-for missing")
    for pf in p.prefabs:
        g = re.search(r'data-prefab="%s".*?<span class="vo-kw"><span class="vo-kw-live">(.+?)</span><span class="vo-kw-gone">(.+?)</span>' % re.escape(pf.get("data-prefab", "")), html, re.S)
        if not g:
            bad.append(f"video/index.html: prefab {pf.get('data-prefab')} has no .vo-kw (live + gone word card)")
    js = (SITE / "js" / "video-overlays.js").read_text(encoding="utf-8")
    for need, what in (("'Your name'", "the generic name"), ("'jack-named.mp4'", "the named-take probe"), ("q.get('sfx') !== '0'", "the ?sfx=0 switch")):
        if need not in js:
            bad.append(f"js/video-overlays.js: {what} ({need}) missing")
    css = (SITE / "css" / "video.css").read_text(encoding="utf-8")
    rm = re.search(r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}", css, re.S)
    if not rm or ".vo-burst" not in rm[1] or "translate(-50%, -50%)" not in rm[1]:
        bad.append("css/video.css: no prefers-reduced-motion: reduce block dropping the particles (.vo-burst) + shake")
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
        if rem - live < MIN_LIVE.get(pid, IN):
            bad.append(f"video/index.html: prefab {pid}: removed {rem} - live {live} < {MIN_LIVE.get(pid, IN)} s")
        if a.get("data-cue-tap") is not None:
            try:
                tap = float(a["data-cue-tap"])
                if not live + IN <= tap <= rem - 0.7:
                    bad.append(f"video/index.html: prefab {pid}: data-cue-tap {tap} outside live + {IN} .. removed - 0.7")
            except ValueError:
                bad.append(f"video/index.html: prefab {pid}: data-cue-tap {a['data-cue-tap']!r} not numeric")
        if out - rem < MIN_HOLD:
            bad.append(f"video/index.html: prefab {pid}: out {out} - removed {rem} < {MIN_HOLD} s")
        if prev_out is not None and live < prev_out:
            bad.append(f"video/index.html: prefab {pid} comes in at {live} before {prev_id} is out at {prev_out}")
        prev_out, prev_id = out, pid
    bad += modes(html, p, prev_out)
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
    for f in (PAGE, SITE / "js" / "video-overlays.js", SITE / "css" / "video.css"):
        for u in re.findall(r"[\w./-]+\.(?:mp3|wav|ogg|m4a|woff2?|ttf|otf)\b|@font-face|@import", f.read_text(encoding="utf-8"), re.I):
            bad.append(f"{f.relative_to(SITE)}: audio / font file or import {u} (sound is synthesized, fonts are the system stack)")
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

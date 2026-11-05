#!/usr/bin/env python3
"""Gate for site/video/ (Jack's video page). Silent + exit 0 when green; prints each problem + exit 1.

- exactly 6 prefabs: the 5 cued ones google, google-images, x, reddit, mega (in script order) + cta-steps (the generic
  end card .vo-cta, no cues of its own: data-cue-cta; a phone replica of the landing: 3 .vo-step scenes (hero with the
  site's h1 + the onlyfans.com/ field + "Scan now", scan card, report card with tabs + *.example placeholder rows only) +
  the "Rewatch this video with YOUR content" toast with the name flip + the real form inside it; js hides it in named mode); tools/video/render_prefabs.py renders
  the same 6. The 5 cued ones each have numeric data-cue-live <
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
- name bar (.vo-nb) under the stage, outside it: label "Your name", input name=name maxlength=40, button "Rebuild this
  video with my name", the "👇 type your name" hint pill (.vo-nb-hint, pulsing) + Change / Reset; the full screen pill
  (.vo-nb-pill in .vo-ui), no rebuild interstitial card (.vo-rb / rbCard gone); js: one rebuild() for both forms,
  history.replaceState, no reload
- css/video.css has a prefers-reduced-motion: reduce block that drops the particles (.vo-burst) and the shake
- merged at every width: css/video.css has no max-width media query (the old < 900px "card below the video" stacking)
  and never puts .vo-over in the flow; full screen + theater CSS present (.vo-stage:fullscreen; [data-vo-full="theater"]
  .vo-stage fixed + rotate(90deg), body scroll lock); the page has the .vo-ui full screen button
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
CTA_STEPS = "cta-steps"
SCENES = ["vo-sc-hero", "vo-sc-scan", "vo-sc-rep"]
SCENE_SLOTS = ("vo-mi-t", "vo-mbtn", "vo-ms", "vo-mb", "vo-mc-n", "vo-tabs2", "vo-mini-n")
HERO_H1 = "Leaked content, taken down by a real person. <em>Me.</em>"
END_TEXT = "Rewatch this video with <em>YOUR</em> content"
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
    first_live = float(p.prefabs[0]["data-cue-live"]) if p.prefabs and "data-cue-live" in p.prefabs[0] and p.prefabs[0].get("data-cue-live", "").replace(".", "", 1).isdigit() else None
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
    for pf in (a for a in p.prefabs if "data-cue-live" in a):
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


def steps_and_player(html, p):
    """cta-steps (6th prefab, generic only), the render list, no stacking, full screen + theater"""
    bad = []
    ids = [a.get("data-prefab") for a in p.prefabs]
    if ids != ORDER + [CTA_STEPS]:
        bad.append(f"video/index.html: prefabs {ids}, want {ORDER + [CTA_STEPS]} (6)")
    m = re.search(r'<div class="vo-pf vo-cta" data-prefab="cta-steps"[^>]*>(.*?)</form>', html, re.S)
    if not m:
        bad.append("video/index.html: cta-steps must be the generic end card (.vo-cta data-prefab=cta-steps) with the form inside")
    else:
        scenes = re.findall(r'<div class="vo-step (vo-sc-[\w-]+)"', m[1])
        doms = re.findall(r'<b class="vo-dom">([^<]*)</b>', m[1])
        if scenes != SCENES or not all(k in m[1] for k in SCENE_SLOTS) or HERO_H1 not in m[1] or END_TEXT not in m[1] or "onlyfans.com/" not in m[1]:
            bad.append(f"video/index.html: cta-steps needs the 3 scenes {SCENES} (hero h1 + onlyfans.com/ field, scan, report) + slots {SCENE_SLOTS} + the rewatch toast, got {scenes}")
        if not doms or not all(d.endswith(".example") for d in doms):
            bad.append(f"video/index.html: cta-steps report rows must be *.example placeholders, got {doms}")
    cta_tag = re.search(r'<div class="vo-pf vo-cta"[^>]*>', html)
    if cta_tag and "data-cue-" in cta_tag[0]:
        bad.append("video/index.html: cta-steps has its own data-cue-* (its cue is the stage's data-cue-cta)")
    js = (SITE / "js" / "video-overlays.js").read_text(encoding="utf-8")
    pers = re.search(r"function personal\(n\) \{(.*?)\n  \}", js, re.S)
    if not pers or "ctaEl.setAttribute('data-off', '')" not in pers[1] or "ctac = null" not in pers[1]:
        bad.append("js/video-overlays.js: personal() must hide cta-steps (named mode never shows it)")
    if "function steps(c, t)" not in js or "SOLO_CTA" not in js:
        bad.append("js/video-overlays.js: cta-steps loop (steps()) / its solo clip (SOLO_CTA) missing")
    rp = re.search(r"PREFABS = \(([^)]*)\)", (ROOT / "tools" / "video" / "render_prefabs.py").read_text(encoding="utf-8"))
    if not rp or re.findall(r'"([\w-]+)"', rp[1]) != ORDER + [CTA_STEPS]:
        bad.append(f"tools/video/render_prefabs.py: PREFABS must be the 6 {ORDER + [CTA_STEPS]}")
    css = (SITE / "css" / "video.css").read_text(encoding="utf-8")
    if re.search(r"@media[^{]*max-width", css) or re.search(r"\.vo-over \{[^}]*position: relative", css):
        bad.append("css/video.css: a max-width media query / .vo-over in the flow: the cards must stay in the stage's right half at every width")
    th = re.search(r'\[data-vo-full="theater"\] \.vo-stage \{([^}]*)\}', css)
    if not th or "position: fixed" not in th[1] or "rotate(90deg)" not in th[1] or not re.search(r'html\[data-vo-full="theater"\][^{]*body \{ overflow: hidden', css) \
            or ".vo-stage:fullscreen" not in css:
        bad.append("css/video.css: theater (fixed + rotate(90deg) stage, body scroll lock) / .vo-stage:fullscreen CSS missing")
    if 'class="vo-fs"' not in html or "requestFullscreen" not in js:
        bad.append("video/index.html / js: the .vo-fs full screen button (stage.requestFullscreen, else theater) missing")
    return bad


def name_bar(html):
    bad = []
    m = re.search(r'<div class="vo-nb">(.*?)\n  </div>\n</main>', html, re.S)
    stage_end = html.find('<div class="vo-nb">') > html.find('<div class="vo-ui">') >= 0
    need = ('<label for="vo-nb-in">Your name</label>', 'name="name"', 'maxlength="40"', ">Rebuild this video with my name</button>",
            'class="vo-nb-hint"', "&#x1F447; type your name", 'class="vo-nb-chg"', 'class="vo-nb-rst"')
    if not m or not stage_end or not all(k in m[1] for k in need):
        bad.append("video/index.html: the name bar .vo-nb (after the stage, before </main>) needs " + ", ".join(k for k in need if not m or k not in m[1]))
    if 'class="vo-nb-pill"' not in html:
        bad.append("video/index.html: the full screen name pill (.vo-nb-pill) missing")
    if "vo-rb" in html or "vo-rb" in (SITE / "css" / "video.css").read_text(encoding="utf-8") or "rbCard" in (SITE / "js" / "video-overlays.js").read_text(encoding="utf-8"):
        bad.append("video/index.html / css / js: the rebuild card (.vo-rb, rbCard) is dropped: submit rebuilds at once")
    css = (SITE / "css" / "video.css").read_text(encoding="utf-8")
    if "@keyframes vo-nb-pulse" not in css or "[data-vo-full] .vo-nb-pill" not in css or "--nb-h" not in css:
        bad.append("css/video.css: hint pulse (@keyframes vo-nb-pulse), [data-vo-full] .vo-nb-pill, the --nb-h room under the stage missing")
    js = (SITE / "js" / "video-overlays.js").read_text(encoding="utf-8")
    if "function rebuild(n)" not in js or "history.replaceState" not in js or "location.assign" in js or js.count("rebuild(n);") != 1 \
            or "onName(nbForm, nbErr)" not in js or "onName(form, null)" not in js:
        bad.append("js/video-overlays.js: both name forms must share one in-place rebuild(n) (history.replaceState, no location.assign reload)")
    return bad


def main():
    bad = []
    p = P()
    html = PAGE.read_text(encoding="utf-8")
    p.feed(html)
    bad += after_state(html)
    bad += steps_and_player(html, p)
    bad += name_bar(html)
    cued = [a for a in p.prefabs if "data-cue-live" in a]
    if [a.get("data-prefab") for a in cued] != ORDER:
        bad.append(f"video/index.html: cued prefabs {[a.get('data-prefab') for a in cued]}, want {ORDER}")
    prev_out, prev_id = None, None
    for a in cued:
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

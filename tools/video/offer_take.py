#!/usr/bin/env python3
"""Build the Tracker's offer-video dir (TRACKER_OFFER_VIDEO_DIR) from Jack's take on site/video/.

  python3 tools/video/offer_take.py OUT_DIR   ->  offer.mp4, poster.webp, captions.vtt, cues.json

captions = transcript.json's chunks as spoken; cues = the page's data-cue-live per prefab, end = data-cue-cta.
reddit reads as the CRM's `forum` scene (phase-03 has no reddit kind).
"""
import json, re, shutil, sys
from pathlib import Path

V = Path(__file__).resolve().parents[2] / "site" / "video"
KIND = {"google": "google", "google-images": "google_images", "x": "x", "reddit": "forum", "mega": "mega"}
HOLD = 0.5


def ts(s):
    m, ms = divmod(round(s * 1000), 60000)
    return f"00:{m:02d}:{ms // 1000:02d}.{ms % 1000:03d}"


def vtt(t):
    w, ch = t["words"], t["chunks"]
    out = ["WEBVTT", ""]
    for i, (a, b, _) in enumerate(ch):
        end = w[b][2] + HOLD
        if i + 1 < len(ch):
            end = min(end, w[ch[i + 1][0]][1])
        out += [f"{ts(w[a][1])} --> {ts(max(end, w[b][2]))}", " ".join(x[0] for x in w[a:b + 1]), ""]
    return "\n".join(out)


def cues(page, duration):
    cs = [{"t_s": float(t), "kind": KIND[p]} for p, t in re.findall(r'data-prefab="([^"]+)" data-cue-live="([0-9.]+)"', page)]
    cs.append({"t_s": float(re.search(r'data-cue-cta="([0-9.]+)"', page).group(1)), "kind": "end"})
    assert [c["kind"] for c in cs] == ["google", "google_images", "x", "forum", "mega", "end"], cs
    return {"duration_s": duration, "cues": sorted(cs, key=lambda c: c["t_s"])}


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    t = json.loads((V / "transcript.json").read_text())
    shutil.copyfile(V / "jack.mp4", out / "offer.mp4")
    shutil.copyfile(V / "jack-poster.webp", out / "poster.webp")
    (out / "captions.vtt").write_text(vtt(t))
    (out / "cues.json").write_text(json.dumps(cues((V / "index.html").read_text(), t["duration"]), indent=1) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])

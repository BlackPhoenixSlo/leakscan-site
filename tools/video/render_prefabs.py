#!/usr/bin/env python3
"""Render the 5 video overlay prefabs (site/video/?prefab=…) as CapCut-ready clips, 1920x1080, 30 fps, 6 s each:
pop in (0-0.45 s, + word card) → live → the snap at 2.4 s (shake + flash + "GONE." card, 0.25 s) → compare wipe
(2.65-3.6 s, counters roll down) → "Removed" stamp slams in (3.6 s) + confetti → slide out (5.6-6 s). Silent: SFX are
added in CapCut (site/video/CUES.md). No --name = the generic clips ("Your name"); --name X = named. The card sits in the
right half of the frame (vertically centred, same place as on the web page), so the clip drops on top of Jack's video with no
repositioning and needs no CapCut in / out animation.

Per prefab ID (google, google-images, x, reddit, mega) in OUT_DIR:
  ID.mov          ProRes 4444 with real alpha (yuva444p10le): frames = page.screenshot(omit_background=True) of
                  ?prefab=ID&bg=none, one per frame via VideoOverlays.seek(t) (exact, no real-time jitter)
  ID-green.mp4    H.264 yuv420p on chroma #00FF00 (the same frames composited by ffmpeg) for CapCut's Chroma key
  ID-live.png / ID-removed.png   the settled states (1.6 s / 5.4 s) on green, screenshots of
                  ?prefab=ID&state=live|removed&bg=green (so the chroma mode itself is exercised too)
  ID-in.png / ID-snap.png / ID-burst.png / ID-out.png   mid pop-in (0.1 s) / mid shake (2.5 s) / confetti (4.0 s) /
                  mid slide-out (5.8 s), stills from ID-green.mp4
Usage: cd ~/leakhunt && uv run python ~/leakscan-site/tools/video/render_prefabs.py OUT_DIR [--name X] [--keep-frames]
Needs ffmpeg with prores_ks + libx264."""
import argparse, pathlib, shutil, subprocess, sys, urllib.parse
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from serve import serve
from playwright.sync_api import sync_playwright

PREFABS = ("google", "google-images", "x", "reddit", "mega")
FPS, SECONDS, W, H = 30, 6, 1920, 1080


def ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--name")
    ap.add_argument("--keep-frames", action="store_true")
    a = ap.parse_args()
    out = pathlib.Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    extra = "&name=" + urllib.parse.quote(a.name) if a.name else ""
    with serve() as base, sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": W, "height": H})
        pg = ctx.new_page()
        ready = "() => window.VideoOverlays && [...document.images].every(i => i.complete) && document.fonts.status === 'loaded'"
        for pid in PREFABS:
            for state, name in (("live", "live"), ("removed", "removed")):
                pg.goto(f"{base}video/?prefab={pid}&state={state}&bg=green{extra}")
                pg.wait_for_function(ready)
                pg.screenshot(path=str(out / f"{pid}-{name}.png"))
            frames = out / f"frames-{pid}"
            frames.mkdir(exist_ok=True)
            pg.goto(f"{base}video/?prefab={pid}&bg=none{extra}")
            pg.wait_for_function(ready)
            for i in range(FPS * SECONDS):
                pg.evaluate(f"VideoOverlays.seek({i / FPS})")
                pg.screenshot(path=str(frames / f"f{i:04d}.png"), omit_background=True)
            seq = ["-framerate", str(FPS), "-i", str(frames / "f%04d.png")]
            ff(*seq, "-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le", "-alpha_bits", "16",
               "-vendor", "apl0", str(out / f"{pid}.mov"))
            ff("-f", "lavfi", "-i", f"color=c=0x00FF00:s={W}x{H}:r={FPS}", *seq, "-filter_complex",
               "[0][1]overlay=shortest=1,format=yuv420p", "-c:v", "libx264", "-crf", "14", "-preset", "medium",
               "-movflags", "+faststart", str(out / f"{pid}-green.mp4"))
            for t, name in ((0.1, "in"), (2.5, "snap"), (4.0, "burst"), (5.8, "out")):
                ff("-ss", str(t), "-i", str(out / f"{pid}-green.mp4"), "-frames:v", "1", str(out / f"{pid}-{name}.png"))
            if not a.keep_frames:
                shutil.rmtree(frames)
            print(pid, "ok")
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

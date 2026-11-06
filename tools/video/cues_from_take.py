#!/usr/bin/env python3
"""Cues + captions from Jack's recorded take: transcribe it with word timestamps (faster-whisper, else openai-whisper; both
optional, install them in a throwaway venv), refine each word's edges on the audio level, look for finger snaps, track
his face (opencv, optional), then print a unified diff of site/video/index.html with the new data-cue-* values (--apply
writes it + site/video/transcript.json, the words the page's captions show).

Mapping by meaning (Jack's real take does not read SCRIPT.md word for word; site/video/CUES.md has the table):
- platform word: google = the first "Google"; google-images = the next "Images"; x = "X" / "ex" / "Twitter"; reddit; mega.
- removal word = the first of removed / gone / deleted / nothing / hours / now after the platform word (before the next one).
- live = platform word - 0.3 (never before the last card is out); removed = the snap if one stands clearly above the
  speech within removal word -0.4 .. +0.3 s, else the removal word's start (google: - 0.5) (removed - live >= 0.45, google-images >= 1.2);
  google-images data-cue-tap = "Tap", else the end of "Images" (clamped to live + 0.45 .. removed - 0.7); out = the next
  platform word - 0.2, mega: its removal word's end + 0.5, always >= removed + 1.95.
- data-cue-cta (the end card) = the end of the line before the "put / type your name" line + 0.5 (>= the mega out);
  data-cue-say = the last word's end + 0.3 (the "for <name>" pill from there on; nothing is spoken by the page).
Captions (transcript.json): words [text, start, end] (as spoken); chunks [first, last, band] of 1-3 words (<= 16 letters,
split on punctuation / pauses > 0.4 s) for the word-by-word captions, lines (<= 30 letters) for reduced motion; band
"lo" = the left half's lower third, "hi" = its top band when his face is down there during the chunk (face track).
Usage: python tools/video/cues_from_take.py TAKE [--model medium] [--words WORDS.json] [--apply] [--evidence DIR]
       TAKE: anything ffmpeg reads (.webm / .mov / .mp4). WORDS.json = [{"word": " Google.", "start": 7.0, "end": 7.4}, ...]
       skips the transcription. Needs ffmpeg + numpy; whisper only without --words.
Exit: 0 patch printed (empty = cues already match), 1 take / words unusable, 2 no whisper installed."""
import argparse, difflib, json, pathlib, re, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PAGE = ROOT / "site" / "video" / "index.html"
TRANSCRIPT = ROOT / "site" / "video" / "transcript.json"
ORDER = ["google", "google-images", "x", "reddit", "mega"]
PLATFORM = {"google": {"google"}, "google-images": {"images", "image"}, "x": {"x", "ex", "twitter"}, "reddit": {"reddit"}, "mega": {"mega"}}
REMOVAL = {"removed", "gone", "deleted", "nothing", "hours", "now"}
CTA_WORDS = {"name", "type"}
LEAD, OUT_LEAD, MIN_HOLD, IN, TAP_MIN, TAP_MAX = 0.3, 0.2, 1.95, 0.45, 0.45, 0.7
MIN_LIVE = {"google-images": 1.2}
EARLY = {"google": 0.5}   # removed = the removal word - this (no snap): the google wipe runs while he says "they get removed"
SR = 16000
HINT = ("no speech-to-text installed. Throwaway venv, then re-run with its python:\n"
        "  uv venv ~/.cache/leakscan-whisper && uv pip install --python ~/.cache/leakscan-whisper faster-whisper 'opencv-python-headless<5'")
CHUNK_WORDS, CHUNK_CHARS, LINE_CHARS, PAUSE = 3, 16, 30, 0.4
BANDS = {"lo": (0.70, 0.84), "hi": (0.04, 0.17)}   # caption bands (stage height fractions) over the left half x 0 .. 0.5


def norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())


def audio(take):
    """mono float32 at 16 kHz via ffmpeg (no PyAV: faster-whisper's decoder breaks on some PyAV builds)"""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(take), "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def transcribe(a, model):
    """[{word, start, end, seg}], raw segments"""
    try:
        from faster_whisper import WhisperModel
        m = WhisperModel(model, device="cpu", compute_type="int8")

        def run(x):
            segs, _ = m.transcribe(x, word_timestamps=True, language="en", beam_size=5)
            return [{"start": s.start, "end": s.end, "text": s.text, "words": [{"word": w.word, "start": w.start, "end": w.end, "p": w.probability} for w in s.words]} for s in segs]
    except ImportError:
        try:
            import whisper
        except ImportError:
            print(HINT, file=sys.stderr)
            sys.exit(2)
        m = whisper.load_model(model)

        def run(x):
            r = m.transcribe(x, word_timestamps=True, language="en")
            return [{"start": s["start"], "end": s["end"], "text": s["text"], "words": [{"word": w["word"], "start": w["start"], "end": w["end"], "p": w.get("probability")} for w in s.get("words", [])]} for s in r["segments"]]
    segs = run(a)
    end = max((w["end"] for s in segs for w in s["words"]), default=0)
    if len(a) / SR - end > 2:   # whisper drops a short last phrase after a long one: a second pass over the rest
        off = end + 0.05
        for s in run(a[int(off * SR):]):
            for w in s["words"]:
                w["start"] += off
                w["end"] += off
            s["start"] += off
            s["end"] += off
            segs.append(s)
    words = [dict(w, seg=i) for i, s in enumerate(segs) for w in s["words"]]
    return words, segs


def rms_db(a, hop=0.01):
    import numpy as np
    h = int(SR * hop)
    n = len(a) // h
    return 20 * np.log10(np.sqrt((a[:n * h].reshape(n, h) ** 2).mean(1)) + 1e-9)


def refine(words, a):
    """join split tokens ("10" ",000"), then pull each word's edges off silence (whisper stretches words over pauses)"""
    import numpy as np
    out = []
    for w in words:
        if out and not w["word"].startswith(" ") and w.get("seg") == out[-1].get("seg"):
            out[-1]["word"] += w["word"]
            out[-1]["end"] = w["end"]
        else:
            out.append(dict(w))
    if a is None:
        return out
    r = rms_db(a)
    thr = float(np.percentile(r, 10)) + 18
    fr = lambda t: min(len(r) - 1, max(0, int(t / 0.01)))
    for w in out:
        s, e = fr(w["start"]), fr(w["end"])
        if e - s > 8 and r[s] < thr:
            k = next((i for i in range(s, e - 5) if r[i] >= thr), None)
            if k is not None:
                w["start"] = k * 0.01
        s = fr(w["start"])
        if e - s > 8 and r[e] < thr:
            k = next((i for i in range(e, s + 5, -1) if r[i] >= thr), None)
            if k is not None:
                w["end"] = (k + 5) * 0.01
    return out


def snaps(a, words):
    """finger-snap candidates: sharp high-frequency transients (> 3 kHz, <= 16 ms wide) standing >= 9 dB above the
    loudest speech transients (the 99.5th percentile of the high band during words). [(t, dB, over speech)]"""
    import numpy as np
    F = np.fft.rfft(a)
    F[np.fft.rfftfreq(len(a), 1 / SR) < 3000] = 0
    h = np.fft.irfft(F, len(a))
    hop = int(SR * 0.002)
    n = len(h) // hop
    e = 20 * np.log10(np.sqrt((h[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
    inword = np.zeros(n, bool)
    for w in words:
        inword[int(w["start"] / 0.002):int(w["end"] / 0.002)] = True
    speech = float(np.percentile(e[inword], 99.5)) if inword.any() else float(e.max())
    out = []
    for i in range(30, n - 30):
        if e[i] < e[i - 10:i + 11].max():
            continue
        width = int((e[i - 10:i + 25] > e[i] - 6).sum()) * 2
        if e[i] - e[i - 20:i - 5].mean() > 15 and e[i] - e[i + 15:i + 30].mean() > 12 and width <= 16:
            out.append((round(i * 0.002, 3), round(float(e[i]), 1), round(float(e[i] - speech), 1)))
    return [s for s in out if s[2] >= 9], out


def faces(take, fps=5):
    """[(t, x0, y0, x1, y1)] of his face (largest Haar box, frame fractions), [] without opencv"""
    try:
        import cv2
        cc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    except (ImportError, AttributeError):
        print("note: no opencv (pip 'opencv-python-headless<5'): captions all in the lower band", file=sys.stderr)
        return []
    cap = cv2.VideoCapture(str(take))
    step = max(1, round((cap.get(cv2.CAP_PROP_FPS) or 30) / fps))
    out, i = [], 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if i % step == 0:
            H, W = f.shape[:2]
            k = 640 / W
            g = cv2.cvtColor(cv2.resize(f, (640, round(H * k))), cv2.COLOR_BGR2GRAY)
            fs = cc.detectMultiScale(g, 1.1, 6, minSize=(60, 60))
            if len(fs):
                x, y, w, h = max(fs, key=lambda r: r[2] * r[3])
                gw, gh = g.shape[1], g.shape[0]
                out.append((round(i / (cap.get(cv2.CAP_PROP_FPS) or 30), 2), round(x / gw, 3), round(y / gh, 3), round((x + w) / gw, 3), round((y + h) / gh, 3)))
        i += 1
    return out


def band_for(s, e, fc):
    """'lo' unless his face (any box within s - 0.3 .. e + 0.3, the nearest one if none) reaches into the lower band"""
    near = [f for f in fc if s - 0.3 <= f[0] <= e + 0.3] or sorted(fc, key=lambda f: abs(f[0] - s))[:1]

    def hit(b):
        y0, y1 = BANDS[b]
        return max((max(0, min(f[4], y1) - max(f[2], y0)) * max(0, min(f[3], 0.5) - f[1]) for f in near), default=0)
    lo, hi = hit("lo"), hit("hi")
    return "hi" if lo > 0 and hi < lo else "lo"


def group(words, fc):
    """caption chunks (1-3 words) and reduced-motion lines: [[first, last, band]]"""
    def split(maxw, maxc):
        out, cur = [], []
        for i, w in enumerate(words):
            t = w["word"].strip()
            if cur:
                p = words[cur[-1]]
                if (len(cur) >= maxw or re.search(r"[.!?,;:]$", p["word"].strip()) or w["start"] - p["end"] > PAUSE
                        or sum(len(words[k]["word"].strip()) + 1 for k in cur) + len(t) > maxc):
                    out.append(cur)
                    cur = []
            cur.append(i)
        if cur:
            out.append(cur)
        return [[c[0], c[-1], band_for(words[c[0]]["start"], words[c[-1]]["end"] + 0.5, fc)] for c in out]
    return split(CHUNK_WORDS, CHUNK_CHARS), split(99, LINE_CHARS)


def cues(words, snap_list=()):
    """{pid: {live, removed, out[, tap]}}, cta, say, notes, mapping rows"""
    n = [norm(w["word"]) for w in words]
    got, notes, rows, i = {}, [], [], 0
    for pid in ORDER:
        j = next((k for k in range(i, len(words)) if n[k] in PLATFORM[pid]), None)
        if j is None:
            raise ValueError(f"{pid}: platform word not found after word {i} ({' '.join(n[i:i + 12])} …)")
        r = next((k for k in range(j + 1, len(words)) if n[k] in REMOVAL), None)
        if r is None:
            raise ValueError(f"{pid}: no removal word after {words[j]['word']!r} at {words[j]['start']:.2f}")
        rs = words[r]["start"]
        sn = [s for s in snap_list if rs - 0.4 <= s[0] <= rs + 0.3]
        c = {"pf": j, "r": r, "live": words[j]["start"] - LEAD, "removed": min(sn, key=lambda s: abs(s[0] - rs))[0] if sn else rs - EARLY.get(pid, 0),
             "by": "snap" if sn else "word"}
        if pid == "google-images":
            tap = next((k for k in range(j, r) if n[k] == "tap"), None)
            c["tap"] = words[tap]["start"] if tap is not None else words[j]["end"]
        got[pid], i = c, r + 1
    for a, b in zip(ORDER, ORDER[1:]):
        got[a]["out"] = words[got[b]["pf"]]["start"] - OUT_LEAD
    got["mega"]["out"] = words[got["mega"]["r"]]["end"] + 0.5
    prev_out = None
    for pid in ORDER:
        c = got[pid]
        for k in ("live", "removed", "out", "tap"):
            if k in c:
                c[k] = round(c[k], 2)   # the page's 2-decimal cues: the rules below hold on the written values
        if prev_out is not None and c["live"] < prev_out:
            c["live"] = prev_out   # the next card comes in on the same second the last one is out
        need = MIN_LIVE.get(pid, IN)
        if c["removed"] < c["live"] + need:
            notes.append(f"{pid}: removed {c['removed']:.2f} < live + {need}: moved to {c['live'] + need:.2f}")
            c["removed"] = round(c["live"] + need, 2)
        if c["out"] < c["removed"] + MIN_HOLD:
            notes.append(f"{pid}: out {c['out']:.2f} < removed + {MIN_HOLD}: moved to {c['removed'] + MIN_HOLD:.2f} (he talks faster than the animation)")
            c["out"] = round(c["removed"] + MIN_HOLD, 2)
        if "tap" in c:
            c["tap"] = round(min(max(c["tap"], c["live"] + TAP_MIN), c["removed"] - TAP_MAX), 2)
        prev_out = c["out"]
        rows.append((pid, words[c["pf"]]["word"].strip(), words[c["r"]]["word"].strip(), c))
    t9 = next((k for k in range(got["mega"]["r"] + 1, len(words)) if n[k] in CTA_WORDS), None)
    if t9 is None:
        notes.append("no 'name' / 'type' after the mega removal: data-cue-cta = the mega out")
        cta = prev_out
    else:
        seg = words[t9].get("seg")
        first = next((k for k in range(t9, -1, -1) if k == 0 or words[k - 1].get("seg") != seg), t9) if seg is not None else t9
        cta = max(prev_out, words[first - 1]["end"] + 0.5) if first > 0 and seg is not None else max(prev_out, words[t9]["start"] - 0.2)
        rows.append(("cta-steps", " ".join(w["word"].strip() for w in words[first:t9 + 1]), "", {"live": cta}))
    return got, cta, max(cta, words[-1]["end"] + 0.3), notes, rows


def fmt(x):
    return f"{round(x, 2):g}"


def patch(html, got, cta, say):
    def stage(h, k, v):
        h2, n = re.subn(r'(<div class="vo-stage"[^>]*?)\s%s="[^"]*"' % k, r'\1 %s="%s"' % (k, v), h, count=1)
        return h2 if n else re.sub(r'<div class="vo-stage"', f'<div class="vo-stage" {k}="{v}"', h, count=1)
    for pid in ORDER:
        c = got[pid]
        html = re.sub(r'(data-prefab="%s") data-cue-live="[^"]*" data-cue-removed="[^"]*" data-cue-out="[^"]*"' % re.escape(pid),
                      r'\1 data-cue-live="%s" data-cue-removed="%s" data-cue-out="%s"' % (fmt(c["live"]), fmt(c["removed"]), fmt(c["out"])), html, count=1)
        if pid == "google-images":
            html = re.sub(r'(data-prefab="google-images"[^>]*?) data-cue-tap="[^"]*"', r"\1", html, count=1)
            html = re.sub(r'(data-prefab="google-images" [^>]*?data-cue-out="[^"]*")', r'\1 data-cue-tap="%s"' % fmt(c["tap"]), html, count=1)
    html = re.sub(r'(<div class="vo-stage"[^>]*?)\sdata-cue-say-start="[^"]*"', r"\1", html, count=1)   # gone with the spoken name
    return stage(stage(html, "data-cue-cta", fmt(cta)), "data-cue-say", fmt(say))


def transcript_json(words, chunks, lines, dur):
    w = ",\n  ".join(json.dumps([x["word"].strip(), round(x["start"], 2), round(x["end"], 2)], ensure_ascii=False) for x in words)
    c = json.dumps(chunks, separators=(",", ":"))
    ln = json.dumps(lines, separators=(",", ":"))
    return ('{"take": "jack.webm", "duration": %s, "note": "tools/video/cues_from_take.py: words [text, start, end] as spoken; '
            'chunks / lines [first, last, band lo|hi]",\n "words": [\n  %s\n ],\n "chunks": %s,\n "lines": %s\n}\n') % (round(dur, 2), w, c, ln)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("take")
    ap.add_argument("--model", default="medium")
    ap.add_argument("--words", help="word timestamps JSON instead of transcribing")
    ap.add_argument("--apply", action="store_true", help="write site/video/index.html + transcript.json")
    ap.add_argument("--evidence", help="dir for the raw transcript / text / snaps / faces / cue table")
    a = ap.parse_args()
    take = pathlib.Path(a.take).expanduser()
    segs, samples, fc = None, None, []
    if a.words:
        words = json.loads(pathlib.Path(a.words).read_text(encoding="utf-8"))
        dur = max(w["end"] for w in words) + 1
    else:
        if not take.is_file():
            print(f"{take}: no such file", file=sys.stderr)
            return 1
        if not shutil.which("ffmpeg"):
            print("needs ffmpeg", file=sys.stderr)
            return 1
        try:
            import numpy  # noqa: F401
        except ImportError:
            print(HINT, file=sys.stderr)
            return 2
        samples = audio(take)
        if len(samples) < SR or float(abs(samples).max()) < 1e-3:
            print(f"{take}: no (audible) audio track: nothing to transcribe", file=sys.stderr)
            return 1
        dur = len(samples) / SR
        words, segs = transcribe(samples, a.model)
        fc = faces(take)
    words = refine([w for w in words if norm(w.get("word", ""))], samples)
    if not words:
        print("no words in the take", file=sys.stderr)
        return 1
    strong, cand = snaps(samples, words) if samples is not None else ([], [])
    try:
        got, cta, say, notes, rows = cues(words, strong)
    except ValueError as e:
        print(f"key word missing: {e}", file=sys.stderr)
        return 1
    say = min(say, dur - 0.3) if samples is not None else say
    print(f"note: snaps: {len(strong)} clear of the speech ({len(cand)} transient candidates)" + ("" if strong else ": removed = the removal word"), file=sys.stderr)
    for nt in notes:
        print("note:", nt, file=sys.stderr)
    chunks, lines = group(words, fc)
    old = PAGE.read_text(encoding="utf-8")
    new = patch(old, got, cta, say)
    rel = str(PAGE.relative_to(ROOT))
    sys.stdout.writelines(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "a/" + rel, "b/" + rel))
    table = ["| prefab | platform word | removal word | live | tap | removed (by) | out |", "|---|---|---|---|---|---|---|"]
    for pid, pw, rw, c in rows:
        table.append(f"| {pid} | {pw} | {rw} | {fmt(c['live'])} | {fmt(c['tap']) if 'tap' in c else '-'} | "
                     + (f"{fmt(c['removed'])} ({c['by']}) | {fmt(c['out'])} |" if "out" in c else "- | stays |"))
    table.append(f"| stage | cta {fmt(cta)} · say {fmt(say)} | | | | | |")
    print("\n".join(table), file=sys.stderr)
    if a.evidence:
        ev = pathlib.Path(a.evidence).expanduser()
        ev.mkdir(parents=True, exist_ok=True)
        if segs is not None:
            (ev / "transcript-whisper.json").write_text(json.dumps({"model": a.model, "segments": segs}, indent=1), encoding="utf-8")
        (ev / "transcript.txt").write_text(" ".join(w["word"].strip() for w in words) + "\n", encoding="utf-8")
        (ev / "transcript-words.txt").write_text("\n".join(f"{w['start']:6.2f} {w['end']:6.2f} {w['word'].strip()}" for w in words) + "\n", encoding="utf-8")
        (ev / "snaps.json").write_text(json.dumps({"clear": strong, "candidates": cand}, indent=1), encoding="utf-8")
        (ev / "faces.json").write_text(json.dumps(fc), encoding="utf-8")
        (ev / "cues.md").write_text("\n".join(table + [""] + ["note: " + x for x in notes]) + "\n", encoding="utf-8")
    if a.apply:
        TRANSCRIPT.write_text(transcript_json(words, chunks, lines, dur), encoding="utf-8")
        if new != old:
            PAGE.write_text(new, encoding="utf-8")
        print(f"wrote {rel} + {TRANSCRIPT.relative_to(ROOT)}; now: python3 tools/video/check_video.py", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

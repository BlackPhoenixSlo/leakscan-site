#!/usr/bin/env python3
"""Cue patch from a recorded take: transcribe it with word timestamps (openai-whisper, else faster_whisper; both
optional, from ~/leakhunt's uv env), find the key words of site/video/SCRIPT.md and print a unified diff of
site/video/index.html with the new data-cue-* values (`git apply`-able; --apply writes it). UNTESTED on a real take
(none recorded yet): proven only on the placeholder (exits 2 without whisper) and on --words fixtures.

Rules (SCRIPT.md): live = 0.3 s before the platform word ("Google" / "X" / "Reddit" followed by "Leaks", "Images" after
"Google", "Mega"); removed = the word after Jack's [snap] ("Gone" / "Now" / "Hours" / "Nothing" / "Gone"); out = the
next platform word - 0.2 s (mega: its sentence end + 0.5), never < removed + 1.95 (the next live never before it);
google-images data-cue-tap = "Tap"; data-cue-cta (the end card) = line 9's "Type" - 0.2 (else the mega out);
data-cue-say (named: the name spoken in the 2 s end hold) = the last word's end + 0.3.
Usage: cd ~/leakhunt && uv run python ~/leakscan-site/tools/video/cues_from_take.py site/video/jack.webm [--model base]
       [--words WORDS.json] [--apply]       (any ffmpeg-readable take: .webm, .mp4, .mov)
WORDS.json = [{"word": "Google.", "start": 7.0, "end": 7.4}, ...] skips the transcription.
Exit: 0 patch printed (empty = cues already match), 1 take / words unusable, 2 no whisper installed."""
import argparse, difflib, json, pathlib, re, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PAGE = ROOT / "site" / "video" / "index.html"
ORDER = ["google", "google-images", "x", "reddit", "mega"]
SNAP = {"google": "gone", "google-images": "now", "x": "hours", "reddit": "nothing", "mega": "gone"}
PLATFORM = {"google": {"google"}, "x": {"x", "ex"}, "reddit": {"reddit"}, "mega": {"mega"}}
LEAKS = {"leaks", "leak", "leaked"}
LEAD, OUT_LEAD, MIN_HOLD, IN = 0.3, 0.2, 1.95, 0.45
HINT = ("no speech-to-text installed. Install one into ~/leakhunt's env, then re-run:\n"
        "  cd ~/leakhunt && uv pip install openai-whisper     # or: uv pip install faster-whisper")


def norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())


def transcribe(take, model):
    try:
        import whisper
        r = whisper.load_model(model).transcribe(str(take), word_timestamps=True, language="en")
        return [{"word": w["word"], "start": w["start"], "end": w["end"]} for s in r["segments"] for w in s.get("words", [])]
    except ImportError:
        pass
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print(HINT, file=sys.stderr)
        sys.exit(2)
    segs, _ = WhisperModel(model, device="cpu", compute_type="int8").transcribe(str(take), word_timestamps=True, language="en")
    return [{"word": w.word, "start": w.start, "end": w.end} for s in segs for w in s.words]


def has_whisper():
    for mod in ("whisper", "faster_whisper"):
        try:
            __import__(mod)
            return True
        except ImportError:
            pass
    return False


def find(words, i, pid):
    """index of prefab pid's platform word at/after i, or None"""
    n = [norm(w["word"]) for w in words]
    for j in range(i, len(words)):
        if pid == "google-images":
            if n[j] == "images" and j and n[j - 1] == "google":
                return j
        elif n[j] in PLATFORM[pid] and (pid == "mega" or LEAKS & set(n[j + 1:j + 3])):
            return j
    return None


def cues(words):
    """{pid: {live, removed, out[, tap]}}, cta, say, notes"""
    n = [norm(w["word"]) for w in words]
    got, notes, i = {}, [], 0
    for pid in ORDER:
        j = find(words, i, pid)
        if j is None:
            raise ValueError(f"{pid}: platform word not found after word {i} ({' '.join(n[i:i + 12])} …)")
        r = next((k for k in range(j + 1, len(words)) if n[k] == SNAP[pid]), None)
        if r is None:
            raise ValueError(f"{pid}: snap word {SNAP[pid]!r} not found after {words[j]['word']!r} at {words[j]['start']}")
        c = {"pf": j, "live": words[j]["start"] - LEAD, "removed": words[r]["start"]}
        if pid == "google-images":
            tap = next((k for k in range(j + 1, r) if n[k] == "tap"), None)
            if tap is not None:
                c["tap"] = words[tap]["start"]
            else:
                notes.append("google-images: no 'Tap' before the snap: data-cue-tap left out (live + 0.6)")
        got[pid], i = c, r + 1
        c["r"] = r
    for a, b in zip(ORDER, ORDER[1:]):
        got[a]["out"] = words[got[b]["pf"]]["start"] - OUT_LEAD
    r = got["mega"]["r"]
    end = next((k for k in range(r, len(words)) if re.search(r"[.!?]$", words[k]["word"].strip())), None)
    got["mega"]["out"] = (words[end]["end"] if end is not None else words[r]["end"] + 1.5) + 0.5
    prev_out = None
    for pid in ORDER:
        c = got[pid]
        if prev_out is not None and c["live"] < prev_out:
            c["live"] = prev_out   # the next card comes in on the same second the last one is out
        if c["out"] < c["removed"] + MIN_HOLD:
            notes.append(f"{pid}: out {c['out']:.2f} < removed + {MIN_HOLD}: moved to {c['removed'] + MIN_HOLD:.2f} (Jack talks faster than the animation)")
            c["out"] = c["removed"] + MIN_HOLD
        if "tap" in c and not c["live"] + IN <= c["tap"] <= c["removed"] - 0.7:
            c["tap"] = min(max(c["tap"], c["live"] + IN), c["removed"] - 0.7)
            notes.append(f"{pid}: data-cue-tap clamped to {c['tap']:.2f}")
        prev_out = c["out"]
    t9 = next((k for k in range(got["mega"]["r"] + 1, len(words)) if n[k] == "type"), None)
    cta = max(prev_out, words[t9]["start"] - 0.2) if t9 is not None else prev_out
    if t9 is None:
        notes.append("line 9: no 'Type' after the mega snap: data-cue-cta = the mega out")
    return got, cta, max(cta, words[-1]["end"] + 0.3), notes


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
            if "tap" in c:
                html = re.sub(r'(data-prefab="google-images" [^>]*?data-cue-out="[^"]*")', r'\1 data-cue-tap="%s"' % fmt(c["tap"]), html, count=1)
    return stage(stage(html, "data-cue-cta", fmt(cta)), "data-cue-say", fmt(say))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("take")
    ap.add_argument("--model", default="base")
    ap.add_argument("--words", help="word timestamps JSON instead of transcribing")
    ap.add_argument("--apply", action="store_true", help="write site/video/index.html")
    a = ap.parse_args()
    take = pathlib.Path(a.take).expanduser()
    if a.words:
        words = json.loads(pathlib.Path(a.words).read_text(encoding="utf-8"))
    else:
        if not take.is_file():
            print(f"{take}: no such file", file=sys.stderr)
            return 1
        if not has_whisper():
            print(HINT, file=sys.stderr)
            return 2
        if shutil.which("ffprobe"):
            st = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(take)],
                                capture_output=True, text=True).stdout.strip()
            if not st:
                print(f"{take}: no audio track (the placeholder?): nothing to transcribe", file=sys.stderr)
                return 1
        words = transcribe(take, a.model)
    words = [w for w in words if norm(w.get("word", ""))]
    if not words:
        print("no words in the take", file=sys.stderr)
        return 1
    try:
        got, cta, say, notes = cues(words)
    except ValueError as e:
        print(f"script key word missing: {e} (SCRIPT.md wording?)", file=sys.stderr)
        return 1
    for nt in notes:
        print("note:", nt, file=sys.stderr)
    old = PAGE.read_text(encoding="utf-8")
    new = patch(old, got, cta, say)
    rel = str(PAGE.relative_to(ROOT))
    sys.stdout.writelines(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "a/" + rel, "b/" + rel))
    if a.apply and new != old:
        PAGE.write_text(new, encoding="utf-8")
        print(f"wrote {rel}; now: python3 tools/video/check_video.py", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

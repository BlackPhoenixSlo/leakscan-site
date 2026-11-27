"""Offer video (Phase 3 story 60): the service's one generic captioned take, the same for every tenant, read from fixed
files under TRACKER_OFFER_VIDEO_DIR (unset -> no take). cues.json is {"duration_s": n, "cues": [{"t_s", "kind"}]}."""
import json
import math
import os
import re

PARTS = {"video": ("offer.mp4", "video/mp4", True), "poster": ("poster.webp", "image/webp", False),
         "captions": ("captions.vtt", "text/vtt", False)}
CUES_FILE, CUES_MAX, CUES_CAP = "cues.json", 12, 64 * 1024
KINDS = ("google", "google_images", "mega", "forum", "x", "end")
RANGE = re.compile(r"bytes=(\d*)-(\d*)")


def path(name):
    d = os.environ.get("TRACKER_OFFER_VIDEO_DIR")
    return os.path.join(d, name) if d else None


def _has(name):
    p = path(name)
    return bool(p) and os.path.isfile(p)


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0


def cues(raw, duration):
    """Kept only when sorted by t_s, inside duration, at most CUES_MAX and every kind known; else None."""
    if not isinstance(raw, list) or len(raw) > CUES_MAX:
        return None
    out = []
    for c in raw:
        if not isinstance(c, dict) or c.get("kind") not in KINDS or not _num(c.get("t_s")) or c["t_s"] > duration:
            return None
        if out and c["t_s"] < out[-1]["t_s"]:
            return None
        out.append({"t_s": c["t_s"], "kind": c["kind"]})
    return out


def meta():
    """/v1/me `video`: null unless the take, its captions and a cues.json with duration_s > 0 exist."""
    if not (_has(PARTS["video"][0]) and _has(PARTS["captions"][0])):
        return None
    try:
        with open(path(CUES_FILE), "rb") as f:
            doc = json.loads(f.read(CUES_CAP))
    except (OSError, ValueError):
        return None
    d = doc.get("duration_s") if isinstance(doc, dict) else None
    if not _num(d) or d <= 0:
        return None
    return {"duration_s": d, "has_poster": _has(PARTS["poster"][0]), "cues": cues(doc.get("cues"), d)}


def byte_range(header, size):
    """One `bytes=` range -> inclusive (start, end), the end clamped to size; None without a header; ValueError when
    malformed, multiple or unsatisfiable."""
    if header is None:
        return None
    m = RANGE.fullmatch(header.strip())
    if not m or not (m[1] or m[2]):
        raise ValueError(header)
    if m[1]:
        start, end = int(m[1]), min(int(m[2]), size - 1) if m[2] else size - 1
    else:
        start, end = size - int(m[2]), size - 1
    if start < 0:
        start = 0
    if start >= size or start > end:
        raise ValueError(header)
    return start, end

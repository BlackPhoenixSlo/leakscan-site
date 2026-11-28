"""Hit admission (Phase 2 spec "Hit admission and the Leak judge"), shared by every discovery lane: one hit (url, title)
-> a Leak, a hidden Pending hit, or nothing. Also the needle normalisation and the Leak / Pending hit writes the seed and
the lanes share.

Dropped first: hosts the host rules skip (tracker_rules.host_class: the Creator's own OnlyFans / Instagram / X, every
other excluded or never-a-leak host, fake_aggregators.txt), then the Mega index aggregator (leakshaven.VIA) and the
service's own hosts (public_app.CORS_ORIGINS), subdomains included. Needles are norm()ed: the handle (>= HANDLE_MIN),
strong aliases (>= STRONG_MIN), weak aliases (HANDLE_MIN .. STRONG_MIN - 1). A URL holding the handle or a strong alias,
or a weak alias while the title holds the handle -> Leak; a title holding the handle or a strong alias -> Pending hit;
anything else -> None. The display name is never a needle.

An images / videos result is also a `media` Leak (admit_media) when admit_hit judged its landing page `leak`, keyed
url_key(landing) + "#google_images" | "#google_videos" with landing_key set; the media itself (its image or video file)
is never requested."""
import json
import re
import sys
from urllib.parse import unquote

import leakshaven
import tracker_db as tdb
import tracker_rules as rules

HANDLE_MIN, STRONG_MIN = 4, 5
MEDIA = {"images": "google_images", "videos": "google_videos"}
GOOGLE = ("google_web", *MEDIA.values())


def norm(s):
    return re.sub(r"[_.\-]", "", unquote(s or "").lower())


def app_attr(name):
    """public_app.<name>. `python3 app/public_app.py` runs as __main__: importing public_app would load a second copy."""
    return getattr(sys.modules.get("__main__"), name, None) or getattr(__import__("public_app"), name)


def _blocked():
    return {leakshaven.host(o) for o in app_attr("CORS_ORIGINS")} - {""} | {leakshaven.VIA}


def needles(w):
    """-> (handle, [handle + strong aliases], [weak aliases]), all norm()ed; a handle under HANDLE_MIN is ''."""
    handle = norm(w["username"])
    handle = handle if len(handle) >= HANDLE_MIN else ""
    aliases = dict.fromkeys(norm(a) for a in json.loads(w["aliases_json"] or "[]") if isinstance(a, str))
    strong = [handle] * bool(handle) + [a for a in aliases if len(a) >= STRONG_MIN and a != handle]
    return handle, strong, [a for a in aliases if HANDLE_MIN <= len(a) < STRONG_MIN]


def _verdict(w, url, title, host, kind):
    if kind == "skip" or any(host == h or host.endswith("." + h) for h in _blocked()):
        return None
    handle, strong, weak = needles(w)
    u, t = norm(url), norm(title)
    if any(n in u for n in strong) or (handle and handle in t and any(n in u for n in weak)):
        return "leak"
    return "pending" if any(n in t for n in strong) else None


def admission(w, url, title):
    """watch row + hit -> "leak" | "pending" | None (module docstring)."""
    host = rules.host_of(url)
    return _verdict(w, url, title, host, rules.host_class(host))


def admit(c, watch_id, url, key, site, kind, title, source, at, first_scan=True, landing_key=None):
    """A Leak with its seen{source, first_scan} event (and google_seen for a GOOGLE source) -> (leak_id, True), or
    (the known Leak's leak_id, False) when url_key is known; a known Leak a GOOGLE hit names gets google_seen{visible:
    true} when its last google_seen isn't visible."""
    leak_id = tdb.new_id("lk_")
    if c.execute("INSERT OR IGNORE INTO leaks (leak_id, watch_id, url_key, url, leak_site, kind, title, created_at, "
                 "landing_key) VALUES (?,?,?,?,?,?,?,?,?)",
                 (leak_id, watch_id, key, url, site, kind, title, at, landing_key)).rowcount:
        tdb.add_event(c, leak_id, "seen", {"source": source, "first_scan": first_scan}, at)
        if source in GOOGLE:
            tdb.add_event(c, leak_id, "google_seen", None, at)
        return leak_id, True
    known = c.execute("SELECT leak_id FROM leaks WHERE watch_id = ? AND url_key = ?", (watch_id, key)).fetchone()[0]
    if source in GOOGLE:
        last = c.execute("SELECT data_json FROM leak_events WHERE leak_id = ? AND type = 'google_seen' "
                         "ORDER BY id DESC LIMIT 1", (known,)).fetchone()
        if last is None or tdb.visible_of(json.loads(last[0] or "{}")) is not True:
            tdb.add_event(c, known, "google_seen", {"visible": True}, at)
    return known, False


def pend(c, watch_id, url, key, title, source, at):
    """A Pending hit unless the watch already has that url_key as a Leak -> 1 | 0."""
    return c.execute("INSERT OR IGNORE INTO pending_hits (watch_id, url_key, url, title, source, seen_at) "
                     "SELECT ?,?,?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM leaks WHERE watch_id = ? AND url_key = ?)",
                     (watch_id, key, url, title, source, at, watch_id, key)).rowcount


def leak_key(url, kind=None):
    """The url_key a hit's Leak or Pending hit is stored under."""
    return rules.url_key(url, keep_fragment=(kind or rules.host_class(rules.host_of(url))) != "page")


def admit_hit(c, w, url, title, source, at, first_scan=False):
    """admission(), then the Leak or the Pending hit -> the verdict."""
    host = rules.host_of(url)
    kind = rules.host_class(host)
    verdict = _verdict(w, url, title, host, kind)
    if verdict:
        key = leak_key(url, kind)
        if verdict == "leak":
            admit(c, w["watch_id"], url, key, rules.registrable_domain(host) or host, kind, title, source, at, first_scan)
        else:
            pend(c, w["watch_id"], url, key, title, source, at)
    return verdict


def admit_media(c, w, url, title, vertical, at, first_scan=False):
    """An images / videos result whose landing page (url, title) admit_hit judged `leak` -> (its media Leak's leak_id,
    new or known; that Leak's url_key)."""
    host = rules.host_of(url)
    landing = leak_key(url, rules.host_class(host))
    key = f"{landing}#{MEDIA[vertical]}"
    return admit(c, w["watch_id"], url, key, rules.registrable_domain(host) or host, "media", title, MEDIA[vertical],
                 at, first_scan, landing_key=landing)[0], key

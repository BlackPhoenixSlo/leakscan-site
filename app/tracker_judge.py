"""Hit admission (Phase 2 spec "Hit admission and the Leak judge"), shared by every discovery lane: one hit (url, title)
-> a Leak, a hidden Pending hit, or nothing.

Dropped first: hosts the host rules skip (tracker_rules.host_class: the Creator's own OnlyFans / Instagram / X, every
other excluded or never-a-leak host, fake_aggregators.txt), the Mega index aggregator (leakshaven.off_aggregators) and
the service's own hosts (public_app.CORS_ORIGINS). Needles are tracker_seed.norm()ed: the handle (>= HANDLE_MIN), strong
aliases (>= STRONG_MIN), weak aliases (HANDLE_MIN .. STRONG_MIN - 1). A URL holding the handle or a strong alias, or a
weak alias while the title holds the handle -> Leak; a title holding the handle or a strong alias -> Pending hit;
anything else -> None. The display name is never a needle."""
import json
import sys

import leakshaven
import tracker_rules as rules
import tracker_seed


def _own_hosts():
    # same lookup as tracker_seed._quick_candidates: public_app may be running as __main__
    origins = getattr(sys.modules.get("__main__"), "CORS_ORIGINS", None) or __import__("public_app").CORS_ORIGINS
    return {leakshaven.host(o) for o in origins} - {""}


def needles(w):
    """-> (handle, [handle + strong aliases], [weak aliases]), all norm()ed; a handle under HANDLE_MIN is ''."""
    handle = tracker_seed.norm(w["username"])
    handle = handle if len(handle) >= tracker_seed.HANDLE_MIN else ""
    aliases = dict.fromkeys(tracker_seed.norm(a) for a in json.loads(w["aliases_json"] or "[]") if isinstance(a, str))
    strong = [handle] * bool(handle) + [a for a in aliases if len(a) >= tracker_seed.STRONG_MIN and a != handle]
    return handle, strong, [a for a in aliases if tracker_seed.HANDLE_MIN <= len(a) < tracker_seed.STRONG_MIN]


def admission(w, url, title):
    """watch row + hit -> "leak" | "pending" | None (module docstring)."""
    host = rules.host_of(url)
    if (rules.host_class(host) == "skip" or not leakshaven.off_aggregators([{"url": url}], [{"via": leakshaven.VIA}])
            or any(host == h or host.endswith("." + h) for h in _own_hosts())):
        return None
    handle, strong, weak = needles(w)
    u, t = tracker_seed.norm(url), tracker_seed.norm(title)
    if any(n in u for n in strong) or (handle and handle in t and any(n in u for n in weak)):
        return "leak"
    return "pending" if any(n in t for n in strong) else None


def admit_hit(c, w, url, title, source, at, first_scan=False):
    """admission(), then the Leak (seen{source, first_scan}) or the Pending hit written like the seed's -> the verdict."""
    verdict = admission(w, url, title)
    if verdict:
        host = rules.host_of(url)
        kind = rules.host_class(host)
        key = rules.url_key(url, keep_fragment=kind != "page")
        if verdict == "leak":
            tracker_seed._admit(c, w["watch_id"], url, key, rules.registrable_domain(host) or host, kind, title, source,
                                at, first_scan)
        else:
            tracker_seed._pend(c, w["watch_id"], url, key, title, source, at)
    return verdict

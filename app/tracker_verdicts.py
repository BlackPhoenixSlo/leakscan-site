"""The Leak judge's prompt and verdict logic, copied from leakhunt 7ccbdd3 (the laptop leak tools; read-only source)
judge: SYSTEM (the judge prompt, catalogued here: README "Leak tracker"), REASON_CHARS, the prompt items, the
verdict parser and Jev's band with its client-page guard. Local: no Store; the mirror fields (`mirror_of`) are
never sent (the service has no mirror findings), the prompt keeps their line as measured. Stdlib only."""
import json

from tracker_jev import band
from tracker_pagekind import CLIENT_KINDS, GENERIC_LISTINGS, Handles, policy_kind


def _either(kinds):
    return " or ".join(f'"{k}"' for k in kinds)


SYSTEM = ("""You review URLs found while hunting leaked copies of one creator's content for DMCA takedowns.
The creator ("the client") is known by these handles: {handles}.
For each item decide whether the URL should be removed: a content page (a single video, image, gallery or post)
about the client, or the leak site's page for the client.
- "accept": the client's handle or an obvious variant of it (case, separators, added suffixes such as
  "_xxx", "of", "leaks") appears in the url, title, matched list or evidence, and the page is content;
  or "policy_kind" is """ + _either(CLIENT_KINDS) + """ (the site's profile page for the client, or a
  numbered page of it): removable.
- "reject": clearly a different person; a tag, category, search-results or other listing page ("policy_kind"
  """ + _either(GENERIC_LISTINGS) + """); a generic feed item unrelated to the client; or a search echo (the site
  just repeats the query back).
- "unsure": anything else. When in doubt, say unsure.
"via" is the page the link was found on. A link listed on the client's own performer / model / channel /
tag page (its URL or title names the client) is strong evidence: accept it unless the title names only
other people. Search-result pages are weaker: there, the title or URL itself must name the client.
An item with "mirror_of" is a copy, at the same path on a site that mirrors that accepted page's site, with the
availability a probe found: accept it only if it is live and its title shows the same content as the accepted page.
Return {{"verdicts": [{{"id": <item id>, "verdict": "accept"|"reject"|"unsure", "reason": "<at most 8 words>"}}]}}
with one entry per item.""")

REASON_CHARS = 80


def system(handles):
    return SYSTEM.format(handles=json.dumps(handles))


def kinds(rows, handles):
    """policy_kind per row id."""
    h = Handles(handles)
    return {r["id"]: policy_kind(r["url"], h) for r in rows}


def item(f, kind):
    ev = f.get("evidence") or {}
    return {"id": f["id"], "url": f["url"], "title": ev.get("title") or "", "matched": ev.get("matched") or [],
            "kind": ev.get("kind") or "", "policy_kind": kind,
            "source": f.get("source") or "", "via": ev.get("found_via") or ""}


def verdicts(out, ids):
    """id -> (verdict, reason) for well-formed entries about ids in this batch; raises ValueError on a bad envelope."""
    rows = out.get("verdicts") if isinstance(out, dict) else out
    if not isinstance(rows, list):
        raise ValueError("no verdicts list")
    got = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            fid = int(r.get("id"))
        except (TypeError, ValueError):
            continue
        verdict = str(r.get("verdict", "")).strip().lower()
        if fid in ids and verdict in ("accept", "reject", "unsure"):
            got[fid] = (verdict, str(r.get("reason") or "").strip()[:REASON_CHARS])
    return got


def jev_verdict(p, kind):
    """The verdict Jev's p settles on its own, else None (the LLM judges it): a CLIENT_KINDS page is never rejected
    by the band, which was not re-measured after the profile-page policy."""
    v = band(p)
    return None if v == "reject" and kind in CLIENT_KINDS else v


def judge_batch(rows, handles, ask):
    """One LLM batch: {id: (verdict, reason)} from `ask(system, user) -> parsed JSON` (profile_extract.deepseek_json's
    failures: OSError, RuntimeError, LookupError, ValueError); {} when the call or its envelope fails. A row with no
    verdict is left for the next round."""
    row_kinds = kinds(rows, handles)
    items = [item(f, row_kinds[f["id"]]) for f in rows]
    try:
        out = ask(system(handles), json.dumps({"items": items}, ensure_ascii=False))
        return verdicts(out, {i["id"] for i in items})
    except (OSError, RuntimeError, LookupError, ValueError, TypeError, AttributeError):
        return {}

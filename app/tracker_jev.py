"""TypeSafe Jev: P(a pending finding is a leaked copy of the client's content), one probability per finding. Copied from
leakhunt 7ccbdd3 (the laptop leak tools; read-only source) jev, rewritten from httpx onto tracker_llm.post_json
(urllib): `post` replaces the httpx client. Local: no on/off switch, budget check, spend ledger or family /
max_usd; Scores carries the billed calls and input tokens instead.

One Noul question per finding, one finding per request; the model is pinned because the LO/HI band was measured
on this version. Findings go out in waves of WORKERS. A finding whose request fails or whose answer is malformed
is absent from the result, so the caller hands it to the LLM judge. The batch stops after a wave, and
`Scores.error` says why, when the last BREAKER findings (in wave order, across waves) found TypeSafe down
(retries spent on transport errors, 429 or 5xx), when the wave met a rejected key, or when the next wave would
start after BATCH_S seconds. The key never appears in errors. Stdlib only."""
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import NamedTuple

from tracker_llm import cost, post_json
from tracker_pagekind import CLIENT_KINDS, GENERIC_LISTINGS, Handles, policy_kind

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"
KEY_ENV = "TYPESAFE_API_KEY"
LO, HI = 0.2, 0.8
WORKERS = 8
TIMEOUT = 10.0
ATTEMPTS = 4
BACKOFF = 1.0
MAX_WAIT = 30.0
BREAKER = 3
BATCH_S = 300.0
TOKEN_CAP = 4
sleep = time.sleep

WHO = "the creator known by `client_handles`"
ACCEPT = ("`page` is a single content page (one video, image, gallery or post) about the client: a handle in "
          "`client_handles` or an obvious variant of one (case, separators, added suffixes such as _xxx, of, leaks) "
          "appears in `page.url` or `page.title`; or `page.found_on` is the client's own performer, model, channel "
          "or tag page (its URL or title names the client) and `page.title` does not name only other people; or "
          f"`page.policy_kind` is {' or '.join(CLIENT_KINDS)} (the site's profile page for the client, or a "
          "numbered page of it).")
REJECT = ("Clearly a different person; or a tag, category, search-results or other listing page "
          f"(`page.policy_kind` {', '.join(GENERIC_LISTINGS)}); or a generic feed item unrelated to the client; or a "
          "search page that only repeats the searched name back.")
VERDICT = (f"Should `page` be reported as a leaked copy of content by {WHO} (the client)? `page.found_on` is the "
           "page the link was found on; a link listed on the client's own performer/model/channel/tag page is strong "
           "evidence, a link from a search-results page is weak evidence.")
QUESTION = {"type": "noul", "instructions": VERDICT,
            "criteria": {"true": ACCEPT, "false": REJECT + " Or the evidence is too thin to tell."}}


class JevError(Exception):
    pass


@dataclass
class Scores:
    p: dict = field(default_factory=dict)  # finding id -> P(leak), answered findings only
    usd: float = 0.0
    failed: int = 0  # findings sent with no usable answer, and findings never sent once the batch stopped
    error: str = None
    calls: int = 0  # billed requests (200s)
    tokens: int = 0  # their input tokens


class _Answer(NamedTuple):
    id: int
    p: float = None
    tokens: int = 0
    down: bool = False
    refused: str = None


def band(p):
    """"reject" at p <= LO, "accept" at p >= HI, else None."""
    return "reject" if p <= LO else "accept" if p >= HI else None


def api_key():
    if key := os.environ.get(KEY_ENV, "").strip():
        return key
    raise JevError(f"{KEY_ENV} is not set")


def state(handles, f):
    """The request state for one finding {id, url, source, evidence: {title, matched, kind, found_via}}."""
    ev = f.get("evidence") or {}
    return {"client_handles": handles,
            "page": {"url": f["url"], "title": ev.get("title") or "",
                     "handles_matched_by_code": ev.get("matched") or [], "page_kind": ev.get("kind") or "",
                     "policy_kind": policy_kind(f["url"], Handles(handles)),
                     "discovered_by": f.get("source") or "", "found_on": ev.get("found_via") or ""}}


def _body(request_state, name="leak", question=QUESTION):
    return {"model": MODEL, "state": request_state, "questions": {name: question}}


def _estimate(body):
    return len(json.dumps(body)) // 4


def retry_wait(header, default):
    """The pause a retry-after header asks for, within [0, MAX_WAIT]; `default` when absent or not a number."""
    try:
        wait = float(header)
    except (TypeError, ValueError):
        return default
    return min(max(wait, 0.0), MAX_WAIT) if math.isfinite(wait) else default


def _post(post, key, body):
    """(status, headers, bytes) of a 200 or a 4xx no retry fixes; None when every attempt met a transport error,
    429 or 5xx. Raises JevError on 401/403."""
    for attempt in range(ATTEMPTS):
        wait = BACKOFF * 2 ** attempt
        try:
            resp = post(URL, body, {"Authorization": f"Bearer {key}"}, TIMEOUT)
        except OSError:
            resp = None
        if resp is not None:
            status, headers, _ = resp
            if status in (401, 403):
                raise JevError(f"TypeSafe HTTP {status}: check {KEY_ENV}")
            if status != 429 and status < 500:
                return resp  # a 422 body echoes the input, so the caller keeps only a 200's answer
            wait = retry_wait(headers.get("retry-after") if headers else None, wait)
        if attempt < ATTEMPTS - 1:
            sleep(wait)
    return None


def _answer(raw, body, name):
    """(probability, or None when malformed; input tokens billed, estimated at ~4 chars each when absent, capped at
    TOKEN_CAP times that estimate) from a 200's body."""
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    data = data if isinstance(data, dict) else {}
    est = _estimate(body)
    usage = data.get("usage")
    tin = usage.get("input_tokens") if isinstance(usage, dict) else None
    if isinstance(tin, bool) or not isinstance(tin, int) or tin <= 0:
        tin = est
    tin = min(tin, TOKEN_CAP * est)
    answers = data.get("answers")
    answer = answers.get(name) if isinstance(answers, dict) else None
    p = answer.get("noul") if isinstance(answer, dict) else None
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not 0.0 <= p <= 1.0:
        return None, tin
    return float(p), tin


def leak_probability(items, handles, *, post=post_json):
    """Jev's P(leak) for findings `items`. Raises JevError with no key; anything after that loses only the findings
    it touched (`Scores.failed`, `Scores.error`)."""
    return ask([(int(f["id"]), lambda f=f: state(handles, f)) for f in items], "leak", QUESTION, post=post)


def ask(items, name, question, *, post=post_json):
    """Jev's probability for one Noul `question` per item (id, a function giving its request state, called in the
    worker so a bad item loses only itself), in waves of WORKERS requests through `post`."""
    if not items:
        return Scores()
    key = api_key()

    def one(item):
        fid, make_state = item
        try:
            body = _body(make_state(), name, question)
            resp = _post(post, key, body)
            if resp is None:
                return _Answer(fid, down=True)
            return _Answer(fid, *_answer(resp[2], body, name)) if resp[0] == 200 else _Answer(fid)
        except JevError as e:
            return _Answer(fid, refused=str(e))
        except Exception:  # one bad finding loses only itself
            return _Answer(fid)

    got = []
    error, run, deadline = None, 0, time.monotonic() + BATCH_S
    with ThreadPoolExecutor(WORKERS) as pool:
        for start in range(0, len(items), WORKERS):
            if start and time.monotonic() >= deadline:
                error = f"TypeSafe took over {BATCH_S:.0f} s; the LLM judges the rest"
                break
            wave = list(pool.map(one, items[start:start + WORKERS]))
            got += wave
            for a in wave:
                run = run + 1 if a.down else 0
            error = next((a.refused for a in wave if a.refused), None)
            if not error and run >= BREAKER:
                error = f"TypeSafe was down for the last {run} findings; the LLM judges the rest"
            if error:
                break
    p = {a.id: a.p for a in got if a.p is not None}
    billed = [a.tokens for a in got if a.tokens]
    return Scores(p, cost(MODEL, sum(billed), 0), len(items) - len(p), error, len(billed), sum(billed))

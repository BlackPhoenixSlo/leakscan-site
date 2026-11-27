"""Query plan (spec "Interfaces" tracker_plan, "Full Google pass" table, "Google fresh pass"). Pure: a row-shaped Leak
identity (username, aliases_json, instagram, x) -> the weekly full pass's ordered queries, their loads and trim order,
and the daily fresh query. The display name is never read. Aliases are classed by tracker_judge.norm() length, the rule
matching uses (decision P2-D7): >= STRONG_MIN is searched alone, HANDLE_MIN .. STRONG_MIN - 1 only beside the handle.
An alias or social whose norm() is under HANDLE_MIN (aliases only) or equals the handle's or an earlier kept value's is
not searched. Field `alias:<i>` is the alias's index in aliases_json (appended, so the highest index is the last
added). Phase 1 allows at most 5 aliases, so the plan is at most 9 + 5 * 4 + 2 = PLAN_MAX loads. A handle-only fresh
query has the same text, vertical and page as the full pass's handle web page 1, so a SERP cache key needs `since`
(or the URL)."""
import json
from dataclasses import dataclass, replace

import tracker_serp as serp
from tracker_judge import HANDLE_MIN, STRONG_MIN, norm

LANE = "google_full"
PLAN_MAX = 31
WORD_LIMIT = 32
_BARE, _LEAKED = serp.TEMPLATES[:2]


@dataclass(frozen=True)
class QuerySpec:
    lane: str
    vertical: str
    text: str
    pages: int
    field: str
    start: int = 0
    since: str = None

    def urls(self):
        return [serp.serp_url(self.text, self.vertical, p, self.since) for p in range(self.start, self.start + self.pages)]


@dataclass(frozen=True)
class Trim:
    plan: "Plan"
    dropped: list
    cut: list


@dataclass(frozen=True)
class Plan:
    queries: tuple
    values: dict

    @property
    def loads(self):
        return sum(q.pages for q in self.queries)

    def trim(self, n):
        """-> Trim(plan with loads <= n holding only the fields still searched, dropped [{field, value}] in drop
        order, cut = every removed QuerySpec in removal order). Handle queries are cut from the bottom of the table,
        then the web query's page 2 (start=1); its page 1 and the handle field go only at n <= 0, the pass waiting."""
        qs, values, dropped, cut = list(self.queries), dict(self.values), [], []
        load = lambda: sum(q.pages for q in qs)

        def drop(f):
            dropped.append({"field": f, "value": values.pop(f)})
            cut.extend(q for q in qs if q.field == f)
            qs[:] = [q for q in qs if q.field != f]

        for f in _drop_order(values):
            if load() <= n:
                break
            drop(f)
        while load() > n and len(qs) > 1:
            cut.append(qs.pop())
        if load() > n and qs[0].pages > 1:
            cut.append(replace(qs[0], pages=qs[0].pages - 1, start=1))
            qs[0] = replace(qs[0], pages=1)
        if load() > n:
            drop("handle")
        return Trim(Plan(tuple(qs), values), dropped, cut)


def _drop_order(values):
    aliases = [f for f in values if f.startswith("alias:")]
    return [*reversed(aliases), *(f for f in ("x", "instagram") if f in values)]


def _q(vertical, template, value, field, pages=1, **kw):
    return QuerySpec(LANE, vertical, template.format(h=value, **kw), pages, field)


def _fields(identity):
    """-> ({field: value} in plan order, {alias field: strong?})."""
    h = identity["username"]
    values, strong, seen = {"handle": h}, {}, {norm(h)}
    for i, a in enumerate(json.loads(identity["aliases_json"] or "[]")):
        n = norm(a)
        if n not in seen and len(n) >= HANDLE_MIN:
            values[f"alias:{i}"], strong[f"alias:{i}"] = a, len(n) >= STRONG_MIN
            seen.add(n)
    for f in ("instagram", "x"):
        if identity[f] and norm(identity[f]) not in seen:
            values[f] = identity[f]
            seen.add(norm(identity[f]))
    return values, strong


def build(identity, platform):
    values, strong = _fields(identity)
    h = values["handle"]
    qs = [_q("web", _BARE, h, "handle", 2), _q("web", _LEAKED, h, "handle", 2), _q("web", '"{h}" {p}', h, "handle", p=platform),
          _q("images", _BARE, h, "handle"), _q("videos", _BARE, h, "handle"),
          *(_q("web", t, h, "handle") for t in serp.FILE_HOST_TEMPLATES)]
    for f, v in values.items():
        if f in strong and strong[f]:
            qs += [_q("web", _BARE, v, f), _q("web", _LEAKED, v, f), _q("images", _BARE, v, f), _q("videos", _BARE, v, f)]
        elif f in strong:
            qs.append(_q("web", '"{h}" "{w}"', h, f, w=v))
        elif f != "handle":
            qs.append(_q("web", _BARE, v, f))
    return Plan(tuple(qs), values)


def fresh(identity):
    """The daily past-day web query, page 1: handle, strong aliases and socials OR-joined, weak aliases left out,
    trimmed in the full pass's drop order to WORD_LIMIT whitespace words ("OR" counted); the handle is always kept."""
    values, strong = _fields(identity)
    terms = {f: v for f, v in values.items() if strong.get(f, True)}
    text = lambda: " OR ".join(_BARE.format(h=v) for v in terms.values())
    for f in _drop_order(terms):
        if len(text().split()) <= WORD_LIMIT:
            break
        del terms[f]
    return QuerySpec("google_fresh", "web", text(), 1, "fresh", since="d")

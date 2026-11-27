"""Query plan (spec "Interfaces" tracker_plan, "Full Google pass" table, "Google fresh pass"). Pure: a row-shaped Leak
identity (username, aliases_json, instagram, x) -> the weekly full pass's ordered queries, their loads and trim order,
and the daily fresh OR query. The display name is never read. Aliases are classed like tracker_judge.needles: norm()
length >= STRONG_MIN is searched alone, HANDLE_MIN .. STRONG_MIN - 1 only beside the handle, anything shorter or equal
to the handle not at all. Field `alias:<i>` is the alias's index in aliases_json (appended, so the highest index is
the last added). Phase 1 allows at most 5 aliases, so the plan is at most 9 + 5 * 4 + 2 = 31 loads."""
import json
from dataclasses import dataclass, replace

import tracker_serp as serp
from tracker_judge import HANDLE_MIN, STRONG_MIN, norm

LANE = "google_full"
WORD_LIMIT = 32
FRESH_SINCE = "d"
_BARE, _LEAKED = serp.TEMPLATES[:2]


@dataclass(frozen=True)
class QuerySpec:
    lane: str
    vertical: str
    text: str
    pages: int
    field: str
    start: int = 0

    def urls(self):
        return [serp.serp_url(self.text, self.vertical, p) for p in range(self.start, self.start + self.pages)]


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
        """-> Trim(plan with loads <= n, dropped [{field, value}] in drop order, cut handle QuerySpecs in cut order).
        Handle queries are cut from the bottom of the table, then the web query's page 2 (start=1); its page 1 goes
        only at n <= 0, the pass waiting."""
        qs, dropped, cut = list(self.queries), [], []
        load = lambda: sum(q.pages for q in qs)
        for f in _drop_order(self.values):
            if load() <= n:
                break
            dropped.append({"field": f, "value": self.values[f]})
            qs = [q for q in qs if q.field != f]
        while load() > n and len(qs) > 1:
            cut.append(qs.pop())
        if load() > n and qs[0].pages > 1:
            cut.append(replace(qs[0], pages=qs[0].pages - 1, start=1))
            qs[0] = replace(qs[0], pages=1)
        if load() > n:
            dropped.append({"field": "handle", "value": self.values["handle"]})
            cut.append(qs.pop())
        return Trim(Plan(tuple(qs), self.values), dropped, cut)


def _drop_order(values):
    aliases = [f for f in values if f.startswith("alias:")]
    return [*reversed(aliases), *(f for f in ("x", "instagram") if f in values)]


def _q(vertical, template, value, field, pages=1, **kw):
    return QuerySpec(LANE, vertical, template.format(h=value, **kw), pages, field)


def _fields(identity):
    """-> ({field: value} in plan order, {alias field: strong?})."""
    h = identity["username"]
    values, strong = {"handle": h}, {}
    for i, a in enumerate(json.loads(identity["aliases_json"] or "[]")):
        n = norm(a)
        if n != norm(h) and len(n) >= HANDLE_MIN:
            values[f"alias:{i}"], strong[f"alias:{i}"] = a, len(n) >= STRONG_MIN
    for f in ("instagram", "x"):
        if identity[f]:
            values[f] = identity[f]
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
    """The daily past-day web query: handle, strong aliases and socials OR-joined, weak aliases left out, trimmed in
    the full pass's drop order to WORD_LIMIT whitespace words ("OR" counted); the handle is always kept."""
    values, strong = _fields(identity)
    terms = {f: v for f, v in values.items() if strong.get(f, True)}
    text = lambda: " OR ".join(_BARE.format(h=v) for v in terms.values())
    for f in _drop_order(terms):
        if len(text().split()) <= WORD_LIMIT:
            break
        del terms[f]
    return text()


def fresh_url(identity):
    return serp.serp_url(fresh(identity), "web", 0, since=FRESH_SINCE)

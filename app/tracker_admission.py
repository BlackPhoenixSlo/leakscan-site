"""Weekly slot admission (spec "Interfaces" tracker_admission). Weekday 0 = Monday (date.weekday()). Every
non-deleted watch, paused or not, costs 1 fresh load each day plus its plan_loads on its weekly_slot day, so resuming
never needs admission. Admission binds on create only: an identity edit recomputes plan_loads and is never refused,
runtime trimming and tracker_budget.reserve hold the cap after that."""
from typing import NamedTuple

PLAN_MAX = 31


class Slot(NamedTuple):
    weekday: int


class Waitlist(NamedTuple):
    pass


class CreatorCap(NamedTuple):
    cap: int


def plan_loads(identity):
    """Weekly plan loads of a watch (row-shaped identity). ASSUMPTION until ticket 21's tracker_plan: the max plan."""
    return PLAN_MAX


def projected(c):
    p = [c.execute("SELECT COUNT(*) FROM watches WHERE deleted_at IS NULL").fetchone()[0]] * 7
    for d, n in c.execute("SELECT weekly_slot, SUM(plan_loads) FROM watches WHERE deleted_at IS NULL "
                          "AND weekly_slot IS NOT NULL GROUP BY weekly_slot"):
        p[d] += n or 0
    return p


def _least(p):
    return min(range(7), key=p.__getitem__)


def _fits(c, plan):
    """-> least-loaded weekday if a new watch with `plan` weekly loads fits the global daily load cap, else None."""
    p = projected(c)
    cap = c.execute("SELECT daily_loads FROM tracker_limits WHERE id = 1").fetchone()[0]
    d = _least(p)
    return d if p[d] + plan + 1 <= cap and max(p) + 1 <= cap else None


def accepting_new(c):
    return _fits(c, PLAN_MAX) is not None


def admit(c, tenant_id, identity):
    """Inside the caller's watch-create transaction -> Slot(weekday) | Waitlist() | CreatorCap(cap)."""
    cap = c.execute("SELECT creators_max FROM tenants WHERE tenant_id = ?", (tenant_id,)).fetchone()[0]
    if c.execute("SELECT COUNT(*) FROM watches WHERE tenant_id = ? AND deleted_at IS NULL", (tenant_id,)).fetchone()[0] >= cap:
        return CreatorCap(cap)
    d = _fits(c, plan_loads(identity))
    return Waitlist() if d is None else Slot(d)


def backfill(c):
    """Slot every non-deleted watch without one, in created_at order, least-loaded first; never refuses."""
    p = projected(c)
    for w in c.execute("SELECT * FROM watches WHERE deleted_at IS NULL AND weekly_slot IS NULL "
                       "ORDER BY created_at, watch_id").fetchall():
        n, d = plan_loads(w), _least(p)
        p[d] += n
        c.execute("UPDATE watches SET weekly_slot = ?, plan_loads = ? WHERE watch_id = ?", (d, n, w["watch_id"]))

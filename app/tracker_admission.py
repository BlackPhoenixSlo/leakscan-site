"""Weekly slot admission (spec "Interfaces" tracker_admission). Weekday 0 = Monday (date.weekday()). Every
non-deleted watch, paused or not, costs its plan_loads on its weekly_slot day, so resuming never needs admission;
refresh and carry loads are not planned (reservations trim them). Admission binds on create only: an identity edit
recomputes plan_loads and is never refused, runtime trimming and tracker_budget.reserve hold the cap after that."""
from dataclasses import dataclass

import tracker_plan
from tracker_plan import PLAN_MAX


@dataclass(frozen=True)
class Slot:
    weekday: int
    plan_loads: int


@dataclass(frozen=True)
class Waitlist:
    pass


@dataclass(frozen=True)
class CreatorCap:
    cap: int


def plan_loads(identity):
    """Weekly plan loads of a watch (row-shaped identity)."""
    return tracker_plan.build(identity, identity["platform"]).loads


def projected(c):
    p = [0] * 7
    for d, n in c.execute("SELECT weekly_slot, SUM(plan_loads) FROM watches WHERE deleted_at IS NULL "
                          "AND weekly_slot IS NOT NULL GROUP BY weekly_slot"):
        p[d] += n
    return p


def _least(p):
    return min(range(7), key=p.__getitem__)


def _fits(c, plan):
    """-> least-loaded weekday if a new watch with `plan` weekly loads fits the global daily load cap, else None."""
    p = projected(c)
    cap = c.execute("SELECT daily_loads FROM tracker_limits WHERE id = 1").fetchone()[0]
    d = _least(p)
    return d if p[d] + plan <= cap else None


def accepting_new(c):
    return _fits(c, PLAN_MAX) is not None


def admit(c, tenant_id, identity):
    """Inside the caller's watch-create transaction -> Slot(weekday, plan_loads) | Waitlist() | CreatorCap(cap)."""
    cap = c.execute("SELECT creators_max FROM tenants WHERE tenant_id = ?", (tenant_id,)).fetchone()[0]
    if c.execute("SELECT COUNT(*) FROM watches WHERE tenant_id = ? AND deleted_at IS NULL", (tenant_id,)).fetchone()[0] >= cap:
        return CreatorCap(cap)
    plan = plan_loads(identity)
    d = _fits(c, plan)
    return Waitlist() if d is None else Slot(d, plan)


def backfill(c):
    """Slot every non-deleted watch without one, in created_at order, least-loaded first; never refuses."""
    p = projected(c)
    for w in c.execute("SELECT * FROM watches WHERE deleted_at IS NULL AND weekly_slot IS NULL "
                       "ORDER BY created_at, watch_id").fetchall():
        n, d = plan_loads(w), _least(p)
        p[d] += n
        c.execute("UPDATE watches SET weekly_slot = ?, plan_loads = ? WHERE watch_id = ?", (d, n, w["watch_id"]))

"""Load reservation (spec "Interfaces" tracker_budget): every paid call holds budget before it is made.

`load` counts against the global UTC day (tracker_limits.daily_loads) and the tenant's UTC month
(tenants.month_loads); `judge_call` against the global day only (tracker_limits.daily_judge). A watch ranked past
tenants.creators_max among its tenant's non-deleted watches (created_at, then watch_id) reserves nothing and is
never paused. Spend = held for held/expired rows, used for settled ones. One unit is one outbound attempt."""
from dataclasses import dataclass
from datetime import timedelta
from typing import NamedTuple

import tracker_db as tdb

UNITS = ("load", "judge_call")
STALE = timedelta(hours=2)
_SPENT = "COALESCE(SUM(CASE WHEN state = 'settled' THEN used ELSE held END), 0)"


@dataclass
class Reservation:
    id: str
    tenant_id: str
    watch_id: str
    unit: str
    held: int
    used: int = 0


class Refused(NamedTuple):
    reason: str
    next_on: str


def _next_day(d):
    return tdb.day(tdb.parse(d) + timedelta(days=1))


def _next_month(d):
    y, m = int(d[:4]), int(d[5:7])
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}-01"


def spent(c, unit, day=None, tenant_id=None, month=None):
    q, args = f"SELECT {_SPENT} FROM load_reservation WHERE unit = ?", [unit]
    if day:
        q, args = q + " AND day = ?", args + [day]
    if tenant_id:
        q, args = q + " AND tenant_id = ? AND month = ?", args + [tenant_id, month]
    return c.execute(q, args).fetchone()[0]


def reserve(c, tenant_id, watch_id, unit, n, partial=False):
    """Hold n units (partial=True: min(n, room), > 0) -> Reservation, or Refused(reason, next_on) holding nothing.
    Commits its own BEGIN IMMEDIATE transaction on c, so c must not be inside one."""
    if unit not in UNITS or n < 1:
        raise ValueError(f"bad reserve {unit} {n}")
    c.execute("BEGIN IMMEDIATE")
    try:
        out = _reserve(c, tenant_id, watch_id, unit, n, partial)
        c.commit()
    except BaseException:
        c.rollback()
        raise
    return out


def _reserve(c, tenant_id, watch_id, unit, n, partial):
    d = tdb.day()
    month = d[:7]
    w = c.execute("SELECT created_at FROM watches WHERE watch_id = ? AND tenant_id = ? AND deleted_at IS NULL",
                  (watch_id, tenant_id)).fetchone()
    if w is None:
        raise ValueError(f"unknown watch {watch_id}")
    cap, month_loads = c.execute("SELECT creators_max, month_loads FROM tenants WHERE tenant_id = ?",
                                 (tenant_id,)).fetchone()
    rank = c.execute("SELECT COUNT(*) FROM watches WHERE tenant_id = ? AND deleted_at IS NULL AND "
                     "(created_at < ? OR (created_at = ? AND watch_id <= ?))",
                     (tenant_id, w[0], w[0], watch_id)).fetchone()[0]
    if rank > cap:
        return Refused("creator_cap", _next_day(d))
    daily_loads, daily_judge = c.execute("SELECT daily_loads, daily_judge FROM tracker_limits WHERE id = 1").fetchone()
    room = (daily_loads if unit == "load" else daily_judge) - spent(c, unit, day=d)
    reason, next_on = "cap_global", _next_day(d)
    if unit == "load":
        tenant_room = month_loads - spent(c, unit, tenant_id=tenant_id, month=month)
        if tenant_room <= room:
            room, reason, next_on = tenant_room, "cap_tenant_month", _next_month(d)
    grant = min(n, room) if partial else (n if n <= room else 0)
    if grant <= 0:
        return Refused(reason, next_on)
    r = Reservation(tdb.new_id("rs_"), tenant_id, watch_id, unit, grant)
    c.execute("INSERT INTO load_reservation (id, tenant_id, watch_id, unit, day, month, held, created_at) "
              "VALUES (?,?,?,?,?,?,?,?)", (r.id, tenant_id, watch_id, unit, d, month, grant, tdb.now()))
    return r


def consume(r, k=1):
    """Mark k more units used, just before k outbound attempts -> True, or False (nothing used) when that would pass
    the hold or the hold is no longer `held`; the caller then makes no call."""
    with tdb.db() as c:
        ok = c.execute("UPDATE load_reservation SET used = used + ? WHERE id = ? AND state = 'held' AND used + ? <= held",
                       (k, r.id, k)).rowcount == 1
    if ok:
        r.used += k
    return ok


def settle(r):
    """Close a held reservation: only `used` keeps counting -> True, or False if it was already settled or expired."""
    with tdb.db() as c:
        return c.execute("UPDATE load_reservation SET state = 'settled', settled_at = ? WHERE id = ? AND state = 'held'",
                         (tdb.now(), r.id)).rowcount == 1


def expire_stale(now=None):
    """Holds older than 2 h nobody settled become `expired` and keep counting in full -> how many."""
    now = now or tdb.now_dt()
    now = tdb.parse(now) if isinstance(now, str) else now
    with tdb.db() as c:
        return c.execute("UPDATE load_reservation SET state = 'expired' WHERE state = 'held' AND created_at < ?",
                         (tdb.fmt(now - STALE),)).rowcount

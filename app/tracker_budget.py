"""Load reservation (spec "Interfaces" tracker_budget). Spend = `used` for settled rows, `held` for held and expired
ones, so a crashed worker's hold keeps counting. The caps bind at reserve time only: a hold taken before midnight or
before a cap was lowered can still be consumed in full (overshoot bounded by the open holds). Purge folds a watch's
spend into a watch-less carry row, so deleting a watch never reopens day or month room."""
from dataclasses import dataclass
from datetime import timedelta
from typing import NamedTuple

import tracker_db as tdb

UNITS = ("load", "judge_call")
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
    next_on: str | None


def _next_day(d):
    return tdb.day(tdb.parse(d) + timedelta(days=1))


def _next_month(d):
    y, m = int(d[:4]), int(d[5:7])
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}-01"


def day_spent(c, unit, day):
    return c.execute(f"SELECT {_SPENT} FROM load_reservation WHERE unit = ? AND day = ?", (unit, day)).fetchone()[0]


def month_loads_spent(c, tenant_id, month):
    return c.execute(f"SELECT {_SPENT} FROM load_reservation WHERE unit = 'load' AND tenant_id = ? AND month = ?",
                     (tenant_id, month)).fetchone()[0]


def reserve(tenant_id, watch_id, unit, n, partial=False):
    """Hold n units (partial=True: min(n, room), > 0) -> Reservation, or Refused(reason, next_on) holding nothing.
    reason: cap_global | cap_tenant_month | creator_cap | gone (watch deleted or missing); next_on None = no date."""
    if unit not in UNITS or n < 1:
        raise ValueError(f"bad reserve {unit} {n}")
    with tdb.db() as c:
        c.execute("BEGIN IMMEDIATE")
        return _reserve(c, tenant_id, watch_id, unit, n, partial)


def _reserve(c, tenant_id, watch_id, unit, n, partial):
    now = tdb.now_dt()
    d = tdb.day(now)
    month = d[:7]
    w = c.execute("SELECT created_at FROM watches WHERE watch_id = ? AND tenant_id = ? AND deleted_at IS NULL",
                  (watch_id, tenant_id)).fetchone()
    if w is None:
        return Refused("gone", None)
    cap, month_loads = c.execute("SELECT creators_max, month_loads FROM tenants WHERE tenant_id = ?",
                                 (tenant_id,)).fetchone()
    rank = c.execute("SELECT COUNT(*) FROM watches WHERE tenant_id = ? AND deleted_at IS NULL AND "
                     "(created_at < ? OR (created_at = ? AND watch_id <= ?))",
                     (tenant_id, w[0], w[0], watch_id)).fetchone()[0]
    if rank > cap:
        return Refused("creator_cap", None)
    daily_loads, daily_judge = c.execute("SELECT daily_loads, daily_judge FROM tracker_limits WHERE id = 1").fetchone()
    room = (daily_loads if unit == "load" else daily_judge) - day_spent(c, unit, d)
    reason, next_on = "cap_global", _next_day(d)
    if unit == "load":
        tenant_room = month_loads - month_loads_spent(c, tenant_id, month)
        if tenant_room <= room:
            room, reason, next_on = tenant_room, "cap_tenant_month", _next_month(d)
    grant = min(n, room) if partial else (n if n <= room else 0)
    if grant <= 0:
        return Refused(reason, next_on)
    r = Reservation(tdb.new_id("rs_"), tenant_id, watch_id, unit, grant)
    c.execute("INSERT INTO load_reservation (id, tenant_id, watch_id, unit, day, month, held, created_at) "
              "VALUES (?,?,?,?,?,?,?,?)", (r.id, tenant_id, watch_id, unit, d, month, grant, tdb.fmt(now)))
    return r


def consume(r, k=1):
    """Mark k more units used, just before k outbound attempts -> True, or False (nothing used) when that would pass
    the hold or the hold is no longer `held`; the caller then makes no call."""
    if k < 1:
        raise ValueError(f"bad consume {k}")
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
    """Holds older than 2 h (now: ISO ts) nobody settled become `expired` and keep counting in full -> how many."""
    with tdb.db() as c:
        return c.execute("UPDATE load_reservation SET state = 'expired' WHERE state = 'held' AND created_at < ?",
                         (tdb.plus(now or tdb.now(), hours=-2),)).rowcount


def fold(c, watch_id, now):
    """Inside the purge transaction, before the watch's rows go: add its spend to the carry row per
    (tenant, unit, day) (watch_id NULL, settled, used = held)."""
    c.execute(f"INSERT INTO load_reservation (id, tenant_id, watch_id, unit, day, month, held, used, state, created_at, "
              f"settled_at) SELECT 'carry_' || tenant_id || '_' || unit || '_' || day, tenant_id, NULL, unit, day, month, "
              f"{_SPENT}, {_SPENT}, 'settled', ?, ? FROM load_reservation WHERE watch_id = ? "
              f"GROUP BY tenant_id, unit, day, month HAVING {_SPENT} > 0 "
              f"ON CONFLICT(id) DO UPDATE SET held = held + excluded.held, used = used + excluded.used",
              (now, now, watch_id))

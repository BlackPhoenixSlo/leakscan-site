"""Watch purge (spec "Purge (service)"): a deleted watch whose purge_after has passed loses its row and every row keyed
by its watch_id, one transaction per watch, and its id goes to deleted_ids (never pruned). Never touches the Quick
scan tables or tenants."""
import tracker_budget
import tracker_db as tdb
from tracker_probe import log

WATCH_TABLES = [("pending_hits", "watch_id"), ("daily_scans", "watch_id"), ("load_reservation", "watch_id")]
_LEAK_TABLES = ("leak_events", "probe_state")


def due(now=None):
    with tdb.db() as c:
        return [r[0] for r in c.execute("SELECT watch_id FROM watches WHERE deleted_at IS NOT NULL AND purge_after IS "
                                        "NOT NULL AND purge_after <= ? ORDER BY purge_after, watch_id",
                                        (now or tdb.now(),))]


def _purge(c, watch_id, now):
    tenant = c.execute("SELECT tenant_id FROM watches WHERE watch_id = ?", (watch_id,)).fetchone()[0]
    for t in _LEAK_TABLES:
        c.execute(f"DELETE FROM {t} WHERE leak_id IN (SELECT leak_id FROM leaks WHERE watch_id = ?)", (watch_id,))
    c.execute("DELETE FROM leaks WHERE watch_id = ?", (watch_id,))
    tracker_budget.fold(c, watch_id, now)
    for t, col in WATCH_TABLES:
        c.execute(f"DELETE FROM {t} WHERE {col} = ?", (watch_id,))
    c.execute("DELETE FROM watches WHERE watch_id = ?", (watch_id,))
    c.execute("INSERT OR REPLACE INTO deleted_ids (watch_id, tenant_id, deleted_at) VALUES (?,?,?)",
              (watch_id, tenant, now))


def run(now=None, dry_run=False):
    """Purge every due watch (purge_after <= now: ts or datetime, default tracker_db.now()) -> {watches: due ids, deleted_ids: ids purged, errors: n}.
    dry_run lists what is due and deletes nothing. A failing watch rolls back alone and is retried next run."""
    now = tdb.fmt(now) if hasattr(now, "astimezone") else now or tdb.now()
    ids = due(now)
    out = {"watches": ids, "deleted_ids": [], "errors": 0}
    if dry_run:
        return out
    for wid in ids:
        try:
            with tdb.db() as c:
                _purge(c, wid, now)
            out["deleted_ids"].append(wid)
        except Exception as e:
            out["errors"] += 1
            log(f"tracker purge row failed: {type(e).__name__}")
    if ids:
        log(f"tracker purge due={len(ids)} purged={len(out['deleted_ids'])} errors={out['errors']}")
    return out

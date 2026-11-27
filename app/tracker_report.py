"""`tracker_cli report` (spec "Measures"): plain counts per tenant, no bound, no sample file. The flap rate is flaps /
first-dead observations with a settled next probe (first_dead minus the Leaks still at consecutive_dead == 1; see
tracker_probe), both numbers printed; no observations prints zeros and no rate."""
import json

import tracker_db as tdb
from tracker_view import PILLS, pill


def counts(tenant_id):
    with tdb.db() as c:
        live = "FROM watches w WHERE w.tenant_id = ? AND w.deleted_at IS NULL"
        watches = c.execute(f"SELECT count(*) {live}", (tenant_id,)).fetchone()[0]
        leaks = c.execute(f"SELECT l.leak_id, l.kind, p.origin_status, p.probes, p.first_dead, p.flaps, p.consecutive_dead "
                          f"FROM leaks l JOIN watches w ON w.watch_id = l.watch_id LEFT JOIN probe_state p ON "
                          f"p.leak_id = l.leak_id WHERE w.tenant_id = ? AND w.deleted_at IS NULL", (tenant_id,)).fetchall()
        events = {}
        for e in c.execute("SELECT e.leak_id, e.type, e.data_json FROM leak_events e JOIN leaks l ON l.leak_id = e.leak_id "
                           "JOIN watches w ON w.watch_id = l.watch_id WHERE w.tenant_id = ? AND w.deleted_at IS NULL "
                           "ORDER BY e.id", (tenant_id,)):
            events.setdefault(e[0], []).append({"type": e[1], "data": json.loads(e[2] or "{}")})
        pending = c.execute("SELECT count(*) FROM pending_hits h JOIN watches w ON w.watch_id = h.watch_id "
                            "WHERE w.tenant_id = ? AND w.deleted_at IS NULL", (tenant_id,)).fetchone()[0]
    by = dict.fromkeys(PILLS, 0)
    for r in leaks:
        by[pill(r["kind"], r["origin_status"], events.get(r["leak_id"], []))] += 1
    first_dead = sum(r["first_dead"] or 0 for r in leaks)
    return {"watches": watches, "pills": by, "probes": sum(r["probes"] or 0 for r in leaks), "first_dead": first_dead,
            "flaps": sum(r["flaps"] or 0 for r in leaks),
            "settled": first_dead - sum(1 for r in leaks if r["consecutive_dead"] == 1),
            "admitted": len(leaks), "pending": pending}


def text():
    """The report, one block per tenant (label order)."""
    with tdb.db() as c:
        tenants = c.execute("SELECT tenant_id, label FROM tenants ORDER BY label, tenant_id").fetchall()
    out = []
    for t in tenants:
        n = counts(t["tenant_id"])
        rate = f"{n['flaps']}/{n['settled']} = {n['flaps'] / n['settled']:.1%}" if n["settled"] else \
            f"{n['flaps']}/{n['settled']} (no settled observations)"
        out += [f"tenant {t['tenant_id']} {t['label']}",
                f"  watches {n['watches']}",
                "  leaks " + " ".join(f"{k}={v}" for k, v in n["pills"].items()),
                f"  probes {n['probes']}  first_dead {n['first_dead']}  flaps {n['flaps']}",
                f"  flap rate {rate}",
                f"  seed admitted {n['admitted']}  pending {n['pending']}"]
    return "\n".join(out) + "\n" if out else "no tenants\n"

#!/usr/bin/env python3
"""Leak tracker owner CLI (spec "Measures"): tenants, keys, purge, report, daily pass. Uses TRACKER_DB.

  python3 app/tracker_cli.py tenant add <label> [--max N] | tenant cap <tenant_id> <n> | tenant list
  python3 app/tracker_cli.py key issue <tenant_id> | key revoke <tenant_id>
  python3 app/tracker_cli.py purge [--dry-run] | report | daily [--at ISO]
"""
import argparse
import json
import sys

import tracker_db


def _tenant(c, tenant_id):
    if not c.execute("SELECT 1 FROM tenants WHERE tenant_id = ?", (tenant_id,)).fetchone():
        sys.exit(f"unknown tenant {tenant_id}")


def tenant_add(a):
    tid = tracker_db.new_id("tn_")
    with tracker_db.db() as c:
        c.execute("INSERT INTO tenants (tenant_id, label, creators_max, created_at) VALUES (?,?,?,?)",
                  (tid, a.label, a.max, tracker_db.now()))
    print(tid)


def tenant_cap(a):
    with tracker_db.db() as c:
        _tenant(c, a.tenant_id)
        c.execute("UPDATE tenants SET creators_max = ? WHERE tenant_id = ?", (a.n, a.tenant_id))


def tenant_list(a):
    with tracker_db.db() as c:
        for r in c.execute("SELECT t.tenant_id, t.label, t.creators_max, "
                           "(SELECT COUNT(*) FROM watches w WHERE w.tenant_id = t.tenant_id AND w.deleted_at IS NULL), "
                           "(SELECT COUNT(*) FROM tenant_keys k WHERE k.tenant_id = t.tenant_id AND k.revoked_at IS NULL) "
                           "FROM tenants t ORDER BY t.created_at, t.tenant_id"):
            print(f"{r[0]}\t{r[1]}\tmax={r[2]}\tused={r[3]}\tkeys={r[4]}")


def key_issue(a):
    key = tracker_db.new_key()
    with tracker_db.db() as c:
        _tenant(c, a.tenant_id)
        c.execute("INSERT INTO tenant_keys (key_hash, tenant_id, issued_at) VALUES (?,?,?)",
                  (tracker_db.key_hash(key), a.tenant_id, tracker_db.now()))
    print(key)


def key_revoke(a):
    with tracker_db.db() as c:
        _tenant(c, a.tenant_id)
        n = c.execute("UPDATE tenant_keys SET revoked_at = ? WHERE tenant_id = ? AND revoked_at IS NULL",
                      (tracker_db.now(), a.tenant_id)).rowcount
    print(f"revoked {n}")


def purge(a):
    import tracker_purge
    print(json.dumps(tracker_purge.run(tracker_db.now(), dry_run=a.dry_run), indent=2, sort_keys=True))


def report(a):
    import tracker_report
    print(tracker_report.text())


def daily(a):
    import tracker_scheduler
    at = tracker_db.parse(a.at) if a.at else None
    if a.at and at is None:
        sys.exit(f"bad --at {a.at}")
    out = tracker_scheduler.daily_pass(at)
    if out is not None:
        print(json.dumps(out, indent=2, sort_keys=True, default=str))


def main(argv=None):
    p = argparse.ArgumentParser(prog="tracker_cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tenant").add_subparsers(dest="sub", required=True)
    x = t.add_parser("add")
    x.add_argument("label")
    x.add_argument("--max", type=int, default=5)
    x.set_defaults(fn=tenant_add)
    x = t.add_parser("cap")
    x.add_argument("tenant_id")
    x.add_argument("n", type=int)
    x.set_defaults(fn=tenant_cap)
    t.add_parser("list").set_defaults(fn=tenant_list)
    k = sub.add_parser("key").add_subparsers(dest="sub", required=True)
    for name, fn in (("issue", key_issue), ("revoke", key_revoke)):
        x = k.add_parser(name)
        x.add_argument("tenant_id")
        x.set_defaults(fn=fn)
    x = sub.add_parser("purge")
    x.add_argument("--dry-run", action="store_true")
    x.set_defaults(fn=purge)
    sub.add_parser("report").set_defaults(fn=report)
    x = sub.add_parser("daily")
    x.add_argument("--at")
    x.set_defaults(fn=daily)
    a = p.parse_args(argv)
    tracker_db.init()
    a.fn(a)


if __name__ == "__main__":
    main()

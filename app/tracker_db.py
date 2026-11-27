"""Leak tracker store: its own SQLite file (TRACKER_DB), never the Quick scan's public.db.

Times are UTC ISO strings `YYYY-MM-DDTHH:MM:SSZ` (sortable as text). `now()` is the one clock; tests and
`tracker_cli daily --at` set it with `set_clock`. Derived Leak fields are computed from leak_events +
probe_state, never stored (spec "Schema (Removal service)"). Stdlib only, one connection per call.

Shared vocabulary (tracker_api / tracker_view read it, tracker_seed / tracker_probe write it):
  kind              page | mega | filehost | telegram. Every kind but `page` is link-only; only `page` is probed in P1.
  leak_site         registrable host of the Leak url (netloc.registrable), mega items: leakshaven.com.
  probe_state.last_status    raw last probe: live | dead | blocked | unknown.
  probe_state.origin_status  settled: NULL (no settled probe yet) | live | gone (gone = 2 dead in a row).
  leak_events       seen{source: google_web|mega_index, first_scan: bool}; google_seen{};
                    status{from: NULL|live|gone, to: live|gone, dead_since: ts|NULL} only when origin_status changes.
  daily_scans.outcome        NULL while running | ok | failed.
  load_reservation  a budget hold (tracker_budget): unit load | judge_call; state held | settled | expired;
                    watch_id NULL = a purged watch's carried spend.
"""
import contextlib
import hashlib
import json
import os
import secrets
import sqlite3
import string
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
TS = "%Y-%m-%dT%H:%M:%SZ"
KEY_PREFIX = "ltk_"
_B62 = string.ascii_letters + string.digits

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
  tenant_id    TEXT PRIMARY KEY,
  label        TEXT NOT NULL,
  creators_max INTEGER NOT NULL DEFAULT 5,
  created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tenant_keys (
  key_hash   TEXT PRIMARY KEY,
  tenant_id  TEXT NOT NULL,
  issued_at  TEXT NOT NULL,
  revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS watches (
  watch_id     TEXT PRIMARY KEY,
  tenant_id    TEXT NOT NULL,
  account_id   TEXT NOT NULL,
  platform     TEXT NOT NULL,
  username     TEXT NOT NULL,
  verified     INTEGER NOT NULL DEFAULT 0,
  display_name TEXT,
  aliases_json TEXT NOT NULL DEFAULT '[]',
  instagram    TEXT,
  x            TEXT,
  paused       INTEGER NOT NULL DEFAULT 0,
  paused_at    TEXT,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL,
  seeded_at    TEXT,
  deleted_at   TEXT,
  purge_after  TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_watches_account ON watches(tenant_id, account_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_watches_tenant ON watches(tenant_id);
CREATE TABLE IF NOT EXISTS leaks (
  leak_id    TEXT PRIMARY KEY,
  watch_id   TEXT NOT NULL,
  url_key    TEXT NOT NULL,
  url        TEXT NOT NULL,
  leak_site  TEXT NOT NULL,
  kind       TEXT NOT NULL,
  title      TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (watch_id, url_key)
);
CREATE INDEX IF NOT EXISTS idx_leaks_url_key ON leaks(url_key);
CREATE TABLE IF NOT EXISTS leak_events (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  leak_id   TEXT NOT NULL,
  at        TEXT NOT NULL,
  type      TEXT NOT NULL,
  data_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_leak ON leak_events(leak_id, id);
CREATE TABLE IF NOT EXISTS probe_state (
  leak_id          TEXT PRIMARY KEY,
  last_probe_at    TEXT,
  last_live_at     TEXT,
  consecutive_dead INTEGER NOT NULL DEFAULT 0,
  last_status      TEXT,
  origin_status    TEXT,
  probes           INTEGER NOT NULL DEFAULT 0,
  first_dead       INTEGER NOT NULL DEFAULT 0,
  flaps            INTEGER NOT NULL DEFAULT 0,
  dead_since       TEXT
);
CREATE TABLE IF NOT EXISTS deleted_ids (
  watch_id   TEXT PRIMARY KEY,
  tenant_id  TEXT NOT NULL,
  deleted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_hits (
  watch_id TEXT NOT NULL,
  url_key  TEXT NOT NULL,
  url      TEXT NOT NULL,
  title    TEXT,
  source   TEXT NOT NULL,
  seen_at  TEXT NOT NULL,
  UNIQUE (watch_id, url_key)
);
CREATE TABLE IF NOT EXISTS daily_scans (
  watch_id    TEXT NOT NULL,
  day         TEXT NOT NULL,
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  outcome     TEXT,
  PRIMARY KEY (watch_id, day)
);
CREATE TABLE IF NOT EXISTS tracker_limits (
  id          INTEGER PRIMARY KEY CHECK (id = 1),
  daily_loads INTEGER NOT NULL,
  daily_judge INTEGER NOT NULL
);
INSERT OR IGNORE INTO tracker_limits (id, daily_loads, daily_judge) VALUES (1, 300, 2000);
CREATE TABLE IF NOT EXISTS load_reservation (
  id         TEXT PRIMARY KEY,
  tenant_id  TEXT NOT NULL,
  watch_id   TEXT,
  unit       TEXT NOT NULL CHECK (unit IN ('load', 'judge_call')),
  day        TEXT NOT NULL,
  month      TEXT NOT NULL,
  held       INTEGER NOT NULL,
  used       INTEGER NOT NULL DEFAULT 0,
  state      TEXT NOT NULL DEFAULT 'held' CHECK (state IN ('held', 'settled', 'expired')),
  created_at TEXT NOT NULL,
  settled_at TEXT,
  CHECK (held > 0 AND used >= 0 AND used <= held)
);
CREATE INDEX IF NOT EXISTS idx_resv_day ON load_reservation(day, unit);
CREATE INDEX IF NOT EXISTS idx_resv_month ON load_reservation(tenant_id, month, unit);
CREATE INDEX IF NOT EXISTS idx_resv_watch ON load_reservation(watch_id);
CREATE INDEX IF NOT EXISTS idx_resv_state ON load_reservation(state, created_at);
"""
_COLUMNS = [("tenants", "month_loads", "INTEGER NOT NULL DEFAULT 1000")]

_clock = None


def path():
    return os.environ.get("TRACKER_DB", os.path.join(HERE, "tracker.db"))


@contextlib.contextmanager
def db():
    """One connection per call; commits on clean exit (a raise rolls the whole block back)."""
    conn = sqlite3.connect(path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(_SCHEMA)
        c.execute("BEGIN IMMEDIATE")
        for table, col, decl in _COLUMNS:
            if col not in {r[1] for r in c.execute(f"PRAGMA table_info({table})")}:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def set_clock(fn):
    """fn() -> aware UTC datetime, or None for the real clock."""
    global _clock
    _clock = fn


def now_dt():
    return (_clock() if _clock else datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)


def fmt(dt):
    return dt.astimezone(timezone.utc).strftime(TS)


def parse(s):
    """ISO-8601 (Z or offset; naive = UTC) -> aware UTC datetime, or None."""
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def now():
    return fmt(now_dt())


def day(dt=None):
    return (dt or now_dt()).strftime("%Y-%m-%d")


def plus(ts, **delta):
    return fmt(parse(ts) + timedelta(**delta))


def new_id(prefix):
    return prefix + secrets.token_hex(8)


def new_key():
    return KEY_PREFIX + "".join(secrets.choice(_B62) for _ in range(40))


def key_hash(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def add_event(c, leak_id, type_, data=None, at=None):
    c.execute("INSERT INTO leak_events (leak_id, at, type, data_json) VALUES (?,?,?,?)",
              (leak_id, at or now(), type_, json.dumps(data or {}, separators=(",", ":"))))

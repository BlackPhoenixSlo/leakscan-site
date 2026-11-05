"""
SQLite persistence for public scans (shareable /s/<slug>).

Level-aware from the start (see the 3-tier design):
  'low'     — CSE scan, anyone, no verification
  'deep'    — slug-scrape (leak_scanner.py), gated on ownership (bio-code)
  'deepest' — operator pipeline (DmcaTG/updates/ui_server.py), hand-off

All queries are parameterized (never f-strings). One connection per call
(ThreadingHTTPServer = one thread per request). WAL enabled for concurrent
readers. Stdlib only.
"""

import contextlib
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("PUBLIC_DB", os.path.join(HERE, "public.db"))
SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{6,24}$")
LEVELS = ("low", "deep", "deepest")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
  slug               TEXT PRIMARY KEY,
  level              TEXT    NOT NULL DEFAULT 'low',
  platform           TEXT    NOT NULL DEFAULT '',
  handle             TEXT    NOT NULL,
  created_at         TEXT    NOT NULL,
  status             TEXT    NOT NULL,
  result_json        TEXT    NOT NULL,
  hit_count          INTEGER NOT NULL DEFAULT 0,
  domain_count       INTEGER NOT NULL DEFAULT 0,
  ownership_verified INTEGER NOT NULL DEFAULT 0,
  verify_code        TEXT,
  verify_platform    TEXT,
  client_ip_hash     TEXT,
  extra_json         TEXT
);
CREATE INDEX IF NOT EXISTS idx_scans_created ON scans(created_at);
CREATE INDEX IF NOT EXISTS idx_scans_handle  ON scans(handle);
"""


@contextlib.contextmanager
def _db(path=None):
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path=None):
    """Create the schema + indexes and enable WAL. Idempotent."""
    p = path or DB_PATH
    conn = sqlite3.connect(p)
    try:
        conn.execute("PRAGMA journal_mode=WAL")  # persistent file property
        conn.executescript(_SCHEMA)
        # migration: add extra_json to a pre-existing table
        cols = [r[1] for r in conn.execute("PRAGMA table_info(scans)").fetchall()]
        if "extra_json" not in cols:
            conn.execute("ALTER TABLE scans ADD COLUMN extra_json TEXT")
        conn.commit()
    finally:
        conn.close()
    return p


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_slug():
    """Short, URL-safe, unguessable (~72 bits)."""
    return secrets.token_urlsafe(9)


def new_verify_code():
    """Human-typeable ownership code for a creator's IG/OnlyFans bio."""
    return "bruqi-" + secrets.token_hex(3)


def insert_scan(hits, *, handle, level="low", platform="", status=None,
                ownership_verified=False, verify_code=None, verify_platform=None,
                client_ip_hash=None, extra=None, path=None):
    """Persist a completed scan; returns its slug. `hits` is a list of hit
    dicts (each with at least a 'domain'). `extra` is an optional dict of
    level-specific data (e.g. {"images": [...], "google_total": "..."}). Retries
    on the astronomically unlikely slug collision."""
    hits = hits or []
    hit_count = len(hits)
    domain_count = len({h.get("domain") for h in hits if h.get("domain")})
    if status is None:
        status = "empty" if hit_count == 0 else "complete"
    payload = json.dumps(hits, ensure_ascii=False, separators=(",", ":"))
    extra_json = json.dumps(extra, ensure_ascii=False, separators=(",", ":")) if extra else None
    with _db(path) as c:
        for _ in range(5):
            slug = new_slug()
            try:
                c.execute(
                    "INSERT INTO scans (slug, level, platform, handle, created_at, "
                    "status, result_json, hit_count, domain_count, ownership_verified, "
                    "verify_code, verify_platform, client_ip_hash, extra_json) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (slug, level, platform, handle, _now(), status, payload,
                     hit_count, domain_count, 1 if ownership_verified else 0,
                     verify_code, verify_platform, client_ip_hash, extra_json),
                )
                return slug
            except sqlite3.IntegrityError:
                continue
    raise RuntimeError("could not mint a unique slug after 5 tries")


def create_pending(*, handle, level="deep", platform="", client_ip_hash=None,
                    path=None):
    """Insert a placeholder row for a scan that will run in the background.
    Returns its slug immediately (status='running', empty results). The worker
    calls finish_scan() when done. This is what makes a scan survive a reload:
    the slug exists before the scan completes."""
    with _db(path) as c:
        for _ in range(5):
            slug = new_slug()
            try:
                c.execute(
                    "INSERT INTO scans (slug, level, platform, handle, created_at, "
                    "status, result_json, hit_count, domain_count, ownership_verified, "
                    "verify_code, verify_platform, client_ip_hash, extra_json) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (slug, level, platform, handle, _now(), "running", "[]",
                     0, 0, 0, None, None, client_ip_hash, None),
                )
                return slug
            except sqlite3.IntegrityError:
                continue
    raise RuntimeError("could not mint a unique slug after 5 tries")


def finish_scan(slug, hits, *, status=None, extra=None, path=None):
    """Fill in a pending (running) scan row with its final results. Returns True
    if a row was updated."""
    if not slug or not SLUG_RE.match(slug):
        return False
    hits = hits or []
    hit_count = len(hits)
    domain_count = len({h.get("domain") for h in hits if h.get("domain")})
    if status is None:
        status = "empty" if hit_count == 0 else "complete"
    payload = json.dumps(hits, ensure_ascii=False, separators=(",", ":"))
    extra_json = json.dumps(extra, ensure_ascii=False, separators=(",", ":")) if extra else None
    with _db(path) as c:
        cur = c.execute(
            "UPDATE scans SET status=?, result_json=?, hit_count=?, domain_count=?, "
            "extra_json=? WHERE slug=?",
            (status, payload, hit_count, domain_count, extra_json, slug),
        )
    return cur.rowcount > 0


def update_extra(slug, patch, path=None):
    """Merge `patch` into a scan's extra_json (top-level keys replaced). Read-modify-write in
    one IMMEDIATE transaction. No schema change. Returns True if the row exists."""
    if not slug or not SLUG_RE.match(slug) or not isinstance(patch, dict):
        return False
    conn = sqlite3.connect(path or DB_PATH, timeout=10, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT extra_json FROM scans WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            return False
        try:
            extra = json.loads(row[0] or "{}") or {}
        except ValueError:
            extra = {}
        extra.update(patch)
        conn.execute("UPDATE scans SET extra_json = ? WHERE slug = ?",
                     (json.dumps(extra, ensure_ascii=False, separators=(",", ":")), slug))
        conn.execute("COMMIT")
        return True
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def reap_running(path=None):
    """Mark any 'running' rows as failed. A running row that survives a process
    restart is orphaned (its in-memory worker is gone), so we flip it at startup
    to stop clients polling it forever. Returns rows reaped."""
    with _db(path) as c:
        cur = c.execute("UPDATE scans SET status='failed' WHERE status='running'")
    return cur.rowcount


def get_scan(slug, path=None):
    """Return the scan row as a dict (with `hits` parsed) or None. Validates the
    slug shape before touching the DB."""
    if not slug or not SLUG_RE.match(slug):
        return None
    with _db(path) as c:
        row = c.execute("SELECT * FROM scans WHERE slug = ?", (slug,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["hits"] = json.loads(d.pop("result_json") or "[]")
    d["ownership_verified"] = bool(d["ownership_verified"])
    extra = {}
    try:
        extra = json.loads(d.pop("extra_json", None) or "{}")
    except Exception:
        d.pop("extra_json", None)
    d["images"] = extra.get("images", [])
    d["google_total"] = extra.get("google_total")
    d["slugs"] = extra.get("slugs", [])
    # Deep-report layers (present only on deep scans): confirmed-leak counts/price,
    # curated gallery, Google-index breakdown, and every dropdown link. Pass through
    # whatever the worker stored so a share/reload renders the full report.
    for key in ("img_meta", "gallery", "cse_sites", "top_leaks", "n_leaks",
                "n_media", "n_hosting", "n_sites", "quote", "links_by_domain",
                "excluded", "mega"):
        if key in extra:
            d[key] = extra[key]
    return d


def recent_extra(handle, key, max_age_s, path=None):
    """extra_json of the newest scan of `handle` (case-insensitive) younger than max_age_s that has `key`
    set truthy, else None. Per-handle cache over the scans table (idx_scans_handle)."""
    since = (datetime.now(timezone.utc) - timedelta(seconds=max_age_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _db(path) as c:
        rows = c.execute("SELECT extra_json FROM scans WHERE handle = ? COLLATE NOCASE AND created_at >= ? "
                         "ORDER BY created_at DESC LIMIT 10", (handle, since)).fetchall()
    for r in rows:
        try:
            ex = json.loads(r[0] or "{}") or {}
        except ValueError:
            continue
        if ex.get(key):
            return ex
    return None


def mark_verified(slug, path=None):
    """Flip ownership_verified after the bio-code check passes. Returns True if a
    row was updated."""
    if not slug or not SLUG_RE.match(slug):
        return False
    with _db(path) as c:
        cur = c.execute("UPDATE scans SET ownership_verified = 1 WHERE slug = ?", (slug,))
    return cur.rowcount > 0


def delete_scan(slug, path=None):
    """Let a creator remove their shared scan. Returns True if a row was deleted."""
    if not slug or not SLUG_RE.match(slug):
        return False
    with _db(path) as c:
        cur = c.execute("DELETE FROM scans WHERE slug = ?", (slug,))
    return cur.rowcount > 0


def prune_scans(max_age_days=30, path=None):
    """Retention: delete scans older than the cutoff. Returns rows removed.
    Call at startup (and optionally on a timer)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    with _db(path) as c:
        cur = c.execute("DELETE FROM scans WHERE created_at < ?", (cutoff,))
    return cur.rowcount


if __name__ == "__main__":
    p = init_db()
    print(f"initialized {p}")

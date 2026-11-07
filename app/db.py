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
import time  # one-project: retention
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
    conn = sqlite3.connect(path or DB_PATH, timeout=30)  # one-project: retention (a writer outwaits VACUUM)
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
        _retain_migrate(conn, cols)  # one-project: retention
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


# >>> one-project patch (leakscan-site) >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# What this repo adds to upstream db.py (bruquiextension) lives in this block; every other line that differs from
# upstream ends in "# one-project" (app/tests/test_one_project.py lists the sites). Re-sync: README.
def domain_count(hits):
    """Distinct hit domains: the one definition of a scan's `domain_count`."""
    return len({h.get("domain") for h in hits or [] if h.get("domain")})


def recent_extra(handle, key, value, max_age_s, path=None):
    """extra_json of the newest scan of `handle` (case-insensitive) younger than max_age_s whose extra[key] ==
    value (a truthy value), else None. Per-handle cache over the scans table (idx_scans_handle)."""
    if not value:
        return None
    since = (datetime.now(timezone.utc) - timedelta(seconds=max_age_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _db(path) as c:
        rows = c.execute("SELECT extra_json FROM scans WHERE handle = ? COLLATE NOCASE AND created_at >= ? "
                         "ORDER BY created_at DESC LIMIT 10", (handle, since)).fetchall()
    for r in rows:
        try:
            ex = json.loads(r[0] or "{}") or {}
        except ValueError:
            continue
        if ex.get(key) == value:
            return ex
    return None


def recent_scan(handle, key, value, max_age_s, path=None):
    """Newest complete quick scan of `handle` (case-insensitive) younger than max_age_s whose extra[key] == value (a
    truthy value) -> {slug, created_at, age_s, hits, extra}, else None. One row whatever a handle's other rows hold."""
    if not value or max_age_s <= 0:
        return None
    since = (datetime.now(timezone.utc) - timedelta(seconds=max_age_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _db(path) as c:
        r = c.execute("SELECT slug, strftime('%s', 'now') - strftime('%s', created_at), result_json, extra_json, created_at "
                      "FROM scans WHERE handle = ? COLLATE NOCASE "
                      "AND level = 'low' AND status = 'complete' AND created_at >= ? AND json_extract(extra_json, ?) = ? "
                      "ORDER BY created_at DESC, rowid DESC LIMIT 1", (handle, since, "$." + key, value)).fetchone()
    return r and {"slug": r[0], "created_at": r[4], "age_s": r[1], "hits": json.loads(r[2] or "[]"), "extra": json.loads(r[3] or "{}")}


# Retention, by row age (created_at), a row is never deleted. Default-keep: a key in neither list stays forever (so does
# every column but RETAIN_NULL), so a future field is never silently lost.
RETAIN_BIG = ("images", "results", "gallery", "img_meta", "excluded")              # past big_days: gone (+ files, profile.avatar=false)
RETAIN_SMALL = ("mega", "cse_sites", "mega_key", "scan_key", "reused_from")        # past small_days: gone (+ result_json = [])
RETAIN_NULL = ("client_ip_hash", "verify_code", "verify_platform")                 # past small_days: NULL
TOP_DOMAINS = 20
RETAIN_BATCH = 100                                                                 # rows per write transaction: writers get a turn


def _retain_migrate(conn, cols):
    """The `retention` marker ('full' | 'trimmed' | 'summary'), indexed: a daily run reads only rows newly over a cutoff."""
    if "retention" not in cols:
        conn.execute("ALTER TABLE scans ADD COLUMN retention TEXT NOT NULL DEFAULT 'full'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scans_retention ON scans(retention, created_at)")


def top_domains(hits, n=TOP_DOMAINS):
    """[{domain, n}], most seen first: a domain's occurrences summed, a row without a number counts 1 (rankHosts in
    site/js/scan-engine.js, which reads this list once the hits are gone)."""
    by = {}
    for h in hits if isinstance(hits, list) else []:
        d = h.get("domain") if isinstance(h, dict) else None
        if d and isinstance(d, str):
            occ = h.get("occurrences")
            by[d] = by.get(d, 0) + (occ if type(occ) in (int, float) and occ > 0 else 1)
    return [{"domain": d, "n": c} for d, c in sorted(by.items(), key=lambda kv: -kv[1])[:n]]


def retain_row(extra, hits, tier):
    """What a scan keeps at a tier ('trimmed' | 'summary'), the one place that says so -> (extra, hits). Pure."""
    out = {k: v for k, v in extra.items() if k not in RETAIN_BIG}
    if isinstance(out.get("profile"), dict):
        out["profile"] = {**out["profile"], "avatar": False}
    if tier == "summary":
        out = {k: v for k, v in out.items() if k not in RETAIN_SMALL}
        out["top_domains"] = top_domains(hits)
        hits = []
    return out, hits


def _json_or_none(text, kind):
    try:
        v = json.loads(text)
    except (TypeError, ValueError):
        return None
    return v if isinstance(v, kind) else None


def _retain_one(c, slug, tier, repair):
    """One row, inside the batch's transaction -> (was it 'full', was its extra_json corrupt). Corrupt extra_json keeps its
    bytes (nothing to read a key from); corrupt result_json keeps its bytes until 'summary'."""
    r = c.execute("SELECT result_json, extra_json, status, hit_count, domain_count, retention FROM scans WHERE slug = ?",
                  (slug,)).fetchone()
    text, ex_text, status, hit_count, domain_count, was = r
    hits, extra = _json_or_none(text, list), {} if ex_text is None else _json_or_none(ex_text, dict)
    n_hits = len(hits or [])
    if repair and hits is not None and extra is not None and was == "full":
        # what the API serves now, baked in: off_row recounts from `mega` + `results`, which go. A row stored after the
        # aggregator rule comes back the same.
        row = repair({"hits": hits, "results": extra.get("results"), "mega": extra.get("mega"), "images": extra.get("images"),
                      "google_total": extra.get("google_total"), "status": status, "hit_count": hit_count,
                      "domain_count": domain_count})
        hits, status, hit_count, domain_count = row["hits"], row["status"], row["hit_count"], row["domain_count"]
        if "google_total" in extra:
            extra = {**extra, "google_total": row["google_total"]}
        if len(hits) != n_hits:
            text = json.dumps(hits, ensure_ascii=False)
    if extra is not None:
        extra, kept = retain_row(extra, hits or [], tier)
        if ex_text is not None or extra:
            ex_text = json.dumps(extra, ensure_ascii=False, separators=(",", ":"))
    if tier == "summary":
        text = "[]"
    nulls = ", ".join(f"{k} = NULL" for k in RETAIN_NULL) + ", " if tier == "summary" else ""
    c.execute(f"UPDATE scans SET {nulls}result_json = ?, extra_json = ?, status = ?, hit_count = ?, domain_count = ?, "
              "retention = ? WHERE slug = ?", (text, ex_text, status, hit_count, domain_count, tier, slug))
    return was == "full", extra is None


def retain_scans(big_days, small_days, path=None, repair=None):
    """Apply the tiers to rows newly over a cutoff, `running` rows skipped; never deletes a row. repair(row): the API's
    off_row (db can't import it). -> {trimmed, summary, corrupt, errors, slugs: rows that just left 'full': their files go}.
    A row that raises stays as it was, for the next run."""
    now = datetime.now(timezone.utc)
    big, small = ((now - timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%SZ") for d in (big_days, small_days))
    out = {"trimmed": 0, "summary": 0, "corrupt": 0, "errors": 0, "slugs": []}
    with _db(path) as c:
        todo = c.execute("SELECT slug, created_at FROM scans WHERE status != 'running' AND "
                         "((retention = 'full' AND created_at < ?) OR (retention = 'trimmed' AND created_at < ?))",
                         (big, small)).fetchall()
    for i in range(0, len(todo), RETAIN_BATCH):
        conn = sqlite3.connect(path or DB_PATH, timeout=30, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            for slug, created in todo[i:i + RETAIN_BATCH]:
                tier = "summary" if created < small else "trimmed"
                try:
                    full, corrupt = _retain_one(conn, slug, tier, repair)
                except Exception:
                    out["errors"] += 1
                    continue
                out[tier] += 1
                out["corrupt"] += corrupt
                if full:
                    out["slugs"].append(slug)
            conn.execute("COMMIT")
        finally:
            conn.close()
        time.sleep(0.01)
    return out


def vacuum(path=None):
    """Give retention's freed pages back to the disk, and the WAL VACUUM wrote. Writers wait (timeout), readers don't."""
    conn = sqlite3.connect(path or DB_PATH, timeout=30, isolation_level=None)
    try:
        conn.execute("VACUUM")
        for _ in range(10):   # busy while a reader sits on the old pages: VACUUM wrote the whole DB to the WAL
            if not conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
                break
            time.sleep(0.5)
    finally:
        conn.close()


def scan_extra(slug, path=None):
    """A scan's extra_json dict ({} when none / no such row)."""
    with _db(path) as c:
        r = c.execute("SELECT extra_json FROM scans WHERE slug = ?", (slug,)).fetchone()
    return json.loads(r[0] or "{}") if r else {}
# <<< one-project patch <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<


def insert_scan(hits, *, handle, level="low", platform="", status=None,
                ownership_verified=False, verify_code=None, verify_platform=None,
                client_ip_hash=None, extra=None, path=None):
    """Persist a completed scan; returns its slug. `hits` is a list of hit
    dicts (each with at least a 'domain'). `extra` is an optional dict of
    level-specific data (e.g. {"images": [...], "google_total": "..."}). Retries
    on the astronomically unlikely slug collision."""
    hits = hits or []
    hit_count = len(hits)
    n_domains = domain_count(hits)  # one-project: domain_count
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
                     hit_count, n_domains, 1 if ownership_verified else 0,  # one-project: domain_count
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
    n_domains = domain_count(hits)  # one-project: domain_count
    if status is None:
        status = "empty" if hit_count == 0 else "complete"
    payload = json.dumps(hits, ensure_ascii=False, separators=(",", ":"))
    extra_json = json.dumps(extra, ensure_ascii=False, separators=(",", ":")) if extra else None
    with _db(path) as c:
        cur = c.execute(
            "UPDATE scans SET status=?, result_json=?, hit_count=?, domain_count=?, "
            "extra_json=? WHERE slug=?",
            (status, payload, hit_count, n_domains, extra_json, slug),  # one-project: domain_count
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
                "excluded", "mega", "results", "top_domains", "n_accepted", "n_removed"):  # one-project: get_scan
        if key in extra:
            d[key] = extra[key]
    return d


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


# upstream's prune_scans (deleted whole rows) is gone: retain_scans  # one-project: retention


if __name__ == "__main__":
    p = init_db()
    print(f"initialized {p}")

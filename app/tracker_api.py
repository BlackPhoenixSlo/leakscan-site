"""Tracker API v1 under /v1/ (spec "Contracts (Tracker API v1)"): Bearer key per tenant, JSON in/out, no CORS.
Ids of another tenant answer 404 like unknown ones, so a key never learns another tenant's ids exist."""
import base64
import json
import os
import re
import sys
import urllib.parse
from datetime import timedelta

import ratelimit
import tracker_admission
import tracker_db
import tracker_judge
import tracker_preview
import tracker_seed
import tracker_video
import tracker_view

BODY_CAP = 64 * 1024
CHUNK = 64 * 1024
LIMIT_DEFAULT, LIMIT_MAX, IDS_MAX = 50, 200, 500
PURGE_DAYS = 30
PLATFORMS = ("onlyfans", "fansly")
WATCH_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
USERNAME = re.compile(r"^[A-Za-z0-9_.-]{2,64}$")
INSTAGRAM = re.compile(r"^[A-Za-z0-9_.]{1,30}$")
X_HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
NOT_FOUND = {"error": "not_found"}
GONE = {"error": "watch_deleted"}
RATE_LIMITED = {"error": "rate_limited"}
WAITLIST = {"error": "waitlist"}
_THUMBS = ratelimit.Limiter(rate_per_min=600, burst=120, max_concurrent=16)


class _Err(Exception):
    def __init__(self, code, body):
        super().__init__(code)
        self.code, self.body = code, body


class _Take:
    def __init__(self, f, ctype, ranged):
        self.f, self.ctype, self.ranged = f, ctype, ranged


class _Blob:
    def __init__(self, data, ctype):
        self.data, self.ctype = data, ctype


def _invalid(field):
    raise _Err(422, {"error": "invalid", "field": field})


def _new_watches_last_hour(c, ts):
    """New watches by capped tenants (all but TRACKER_UNCAPPED_TENANTS) in the hour before ts, deleted ones included:
    TRACKER_PUBLIC_PER_HOUR bounds paid seeds across every public tenant, so DELETE + PUT can't churn past it."""
    free = sorted(tracker_db.env_set("TRACKER_UNCAPPED_TENANTS"))
    since = tracker_db.fmt(tracker_db.parse(ts) - timedelta(hours=1))
    return c.execute(f"SELECT COUNT(*) FROM watches WHERE created_at > ? AND tenant_id NOT IN ({','.join('?' * len(free))})",
                     (since, *free)).fetchone()[0], free


def _log(msg):
    sys.stderr.write(f"tracker_api: {msg}\n")
    sys.stderr.flush()


def is_v1(path):
    return path == "/v1" or path.startswith("/v1/")


def _no_store(h):
    h.send_header("Cache-Control", "no-store")
    h.send_header("X-Content-Type-Options", "nosniff")


def _send(h, code, obj, headers=(), ctype="application/json; charset=utf-8"):
    body = b"" if obj is None else obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode("utf-8")
    h.send_response(code)
    if obj is not None:
        h.send_header("Content-Type", ctype)
    if code == 401:
        h.send_header("WWW-Authenticate", "Bearer")
    for k, v in headers:
        h.send_header(k, v)
    h.send_header("Content-Length", str(len(body)))
    _no_store(h)
    if h.close_connection:
        h.send_header("Connection", "close")
    h.end_headers()
    if h.command == "HEAD":
        return
    try:
        h.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        pass


def _stream(h, take):
    with take.f as f:
        size = os.fstat(f.fileno()).st_size
        try:
            rng = tracker_video.byte_range(h.headers.get("Range"), size) if take.ranged else None
        except ValueError:
            return _send(h, 416, {"error": "range_not_satisfiable"}, [("Content-Range", f"bytes */{size}")])
        start, end = rng or (0, size - 1)
        h.send_response(206 if rng else 200)
        h.send_header("Content-Type", take.ctype)
        h.send_header("Content-Length", str(end - start + 1))
        if take.ranged:
            h.send_header("Accept-Ranges", "bytes")
        if rng:
            h.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        _no_store(h)
        h.end_headers()
        f.seek(start)
        left = end - start + 1
        try:
            while left > 0:
                chunk = f.read(min(CHUNK, left))
                if not chunk:
                    break
                h.wfile.write(chunk)
                left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError as e:
            _log(f"offer-video stream failed: {type(e).__name__}")
        if left:
            h.close_connection = True


def _auth(h):
    scheme, _, key = (h.headers.get("Authorization") or "").partition(" ")
    if scheme.lower() == "bearer" and key.strip():
        with tracker_db.db() as c:
            t = c.execute("SELECT t.* FROM tenant_keys k JOIN tenants t ON t.tenant_id = k.tenant_id "
                          "WHERE k.key_hash = ? AND k.revoked_at IS NULL", (tracker_db.key_hash(key.strip()),)).fetchone()
        if t:
            return t
    raise _Err(401, {"error": "unauthorized"})


def _state(c, tenant_id, watch_id):
    """-> (live|deleted|foreign|none, watch row or None), as the caller's tenant sees watch_id."""
    w = c.execute("SELECT * FROM watches WHERE watch_id = ?", (watch_id,)).fetchone()
    if w:
        return ("foreign" if w["tenant_id"] != tenant_id else "deleted" if w["deleted_at"] else "live"), w
    d = c.execute("SELECT tenant_id FROM deleted_ids WHERE watch_id = ?", (watch_id,)).fetchone()
    return ("none" if not d else "deleted" if d[0] == tenant_id else "foreign"), None


def _own(c, t, watch_id):
    st, w = _state(c, t["tenant_id"], watch_id) if WATCH_ID.match(watch_id) else ("none", None)
    if st == "deleted":
        raise _Err(410, GONE)
    if st != "live":
        raise _Err(404, NOT_FOUND)
    return w


def _identity(raw):
    try:
        b = json.loads(raw or b"null")
    except ValueError:
        b = None
    if not isinstance(b, dict):
        raise _Err(422, {"error": "invalid_json", "field": None})
    acc, user = b.get("account_id"), b.get("username")
    if not isinstance(acc, str) or not acc.strip() or len(acc) > 64:
        _invalid("account_id")
    if b.get("platform") not in PLATFORMS:
        _invalid("platform")
    if not isinstance(user, str) or not USERNAME.match(user):
        _invalid("username")
    if not isinstance(b.get("verified"), bool):
        _invalid("verified")
    name = b.get("display_name")
    if name is not None and (not isinstance(name, str) or len(name) > 64):
        _invalid("display_name")
    aliases = b.get("aliases") or []
    if not isinstance(aliases, list) or len(aliases) > 5 or not all(isinstance(a, str) and 4 <= len(a) <= 64 for a in aliases):
        _invalid("aliases")
    if any(len(tracker_judge.norm(a)) < tracker_judge.HANDLE_MIN for a in aliases):
        _invalid("aliases")
    folded = [a.casefold() for a in aliases]
    if len(set(folded)) != len(folded) or user.casefold() in folded:
        _invalid("aliases")
    for f, rx in (("instagram", INSTAGRAM), ("x", X_HANDLE)):
        v = b.get(f)
        if v is not None and (not isinstance(v, str) or not rx.match(v)):
            _invalid(f)
    if not isinstance(b.get("paused"), bool):
        _invalid("paused")
    return {"account_id": acc, "platform": b["platform"], "username": user, "verified": int(b["verified"]),
            "display_name": name, "aliases_json": json.dumps(aliases), "instagram": b.get("instagram"),
            "x": b.get("x"), "paused": int(b["paused"])}


def _limit(q):
    s = (q.get("limit") or [None])[0]
    if s is None:
        return LIMIT_DEFAULT
    if not re.fullmatch(r"\d{1,4}", s) or not 1 <= int(s) <= LIMIT_MAX:
        _invalid("limit")
    return int(s)


def _cursor(q):
    s = (q.get("cursor") or [""])[0]
    if not s:
        return None
    try:
        first_seen, _, leak_id = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode("utf-8").partition("|")
    except ValueError:
        first_seen, leak_id = "", ""
    if not leak_id or tracker_db.parse(first_seen) is None:
        _invalid("cursor")
    return first_seen, leak_id


def _first_seen(x):
    return x["first_seen_at"]


def _preview_seen(x):
    return x["preview"]["seen_at"]


def _page(items, q, events, at=_first_seen):
    """items newest at() first, then leak_id; the cursor is the last item's at() and leak_id."""
    limit, cur = _limit(q), _cursor(q)
    if cur:
        items = [x for x in items if at(x) < cur[0] or (at(x) == cur[0] and x["leak_id"] > cur[1])]
    page, more = items[:limit], len(items) > limit
    nxt = base64.urlsafe_b64encode(f"{at(page[-1])}|{page[-1]['leak_id']}".encode()).decode().rstrip("=") if more else None
    drop = ("events",) if not events else ("watch_id",)
    return {"leaks": [{k: v for k, v in x.items() if k not in drop} for x in page], "next_cursor": nxt}


def me(t, q, raw):
    with tracker_db.db() as c:
        used = c.execute("SELECT COUNT(*) FROM watches WHERE tenant_id = ? AND deleted_at IS NULL", (t["tenant_id"],)).fetchone()[0]
        accepting = tracker_admission.accepting_new(c)
    return 200, {"tenant_id": t["tenant_id"], "label": t["label"], "brand": os.environ.get("TRACKER_BRAND") or None,
                 "contact_url": os.environ.get("TRACKER_CONTACT_URL") or None, "creators_max": t["creators_max"],
                 "creators_used": used, "accepting_new": accepting, "notices_updated_at": None,
                 "video": tracker_video.meta()}


def put_watch(t, q, raw, watch_id):
    if not WATCH_ID.match(watch_id):
        _invalid("watch_id")
    v, tid, ts = _identity(raw), t["tenant_id"], tracker_db.now()
    with tracker_db.db() as c:
        c.execute("BEGIN IMMEDIATE")
        st, w = _state(c, tid, watch_id)
        if st == "deleted":
            raise _Err(410, GONE)
        if st == "foreign":
            raise _Err(404, NOT_FOUND)
        holder = c.execute("SELECT watch_id FROM watches WHERE tenant_id = ? AND account_id = ? AND deleted_at IS NULL AND watch_id <> ?",
                           (tid, v["account_id"], watch_id)).fetchone()
        if holder:
            raise _Err(409, {"error": "account_taken", "watch_id": holder[0]})
        if w is None:
            a = tracker_admission.admit(c, tid, v)
            if isinstance(a, tracker_admission.CreatorCap):
                raise _Err(409, {"error": "creator_cap", "creators_max": a.cap})
            if isinstance(a, tracker_admission.Waitlist):
                raise _Err(409, WAITLIST)
            n, free = _new_watches_last_hour(c, ts)
            if tid not in free and n >= int(os.environ.get("TRACKER_PUBLIC_PER_HOUR") or 10):
                raise _Err(429, RATE_LIMITED)
            v.update(watch_id=watch_id, tenant_id=tid, paused_at=ts if v["paused"] else None, created_at=ts, updated_at=ts,
                     weekly_slot=a.weekday, plan_loads=a.plan_loads)
            c.execute(f"INSERT INTO watches ({', '.join(v)}) VALUES ({', '.join('?' * len(v))})", list(v.values()))
        else:
            v.update(paused_at=w["paused_at"] if bool(w["paused"]) == bool(v["paused"]) else ts if v["paused"] else None, updated_at=ts,
                     plan_loads=tracker_admission.plan_loads(v))
            c.execute(f"UPDATE watches SET {', '.join(k + ' = ?' for k in v)} WHERE watch_id = ?", [*v.values(), watch_id])
    if w is None and not v["paused"]:
        try:
            tracker_seed.start(watch_id)
        except Exception as e:
            _log(f"seed start failed: {type(e).__name__}")
    with tracker_db.db() as c:
        seeded = c.execute("SELECT seeded_at FROM watches WHERE watch_id = ?", (watch_id,)).fetchone()[0] is not None
    return 200, {"watch_id": watch_id, "created": w is None, "seeded": seeded}


def delete_watch(t, q, raw, watch_id):
    if WATCH_ID.match(watch_id):
        requested, now = tracker_db.parse((q.get("requested_at") or [""])[0]), tracker_db.now_dt()
        with tracker_db.db() as c:
            c.execute("BEGIN IMMEDIATE")
            st, w = _state(c, t["tenant_id"], watch_id)
            if st == "live":
                at = min(max(requested or now, tracker_db.parse(w["created_at"])), now)
                c.execute("UPDATE watches SET deleted_at = ?, purge_after = ? WHERE watch_id = ?",
                          (tracker_db.fmt(now), tracker_db.fmt(at + timedelta(days=PURGE_DAYS)), watch_id))
            elif st == "none":
                c.execute("INSERT OR IGNORE INTO deleted_ids (watch_id, tenant_id, deleted_at) VALUES (?,?,?)",
                          (watch_id, t["tenant_id"], tracker_db.fmt(now)))
    return 204, None


def creators(t, q, raw):
    now = tracker_db.now_dt()
    with tracker_db.db() as c:
        ws = c.execute("SELECT * FROM watches WHERE tenant_id = ? AND deleted_at IS NULL ORDER BY created_at, watch_id",
                       (t["tenant_id"],)).fetchall()
        return 200, {"as_of": tracker_db.fmt(now),
                     "creators": [tracker_view.creator(c, w, now, tracker_view.leaks(c, [w["watch_id"]], now)) for w in ws]}


def creator_one(t, q, raw, watch_id):
    now = tracker_db.now_dt()
    with tracker_db.db() as c:
        w = _own(c, t, watch_id)
        ls = tracker_view.leaks(c, [watch_id], now)
        return 200, {**tracker_view.creator(c, w, now, ls), "lanes": tracker_view.lanes(c, w), "taken_down": None,
                     "preview_leak": tracker_view.preview_leak(ls)}


def creator_leaks(t, q, raw, watch_id):
    now = tracker_db.now_dt()
    with tracker_db.db() as c:
        _own(c, t, watch_id)
        return 200, _page(tracker_view.leaks(c, [watch_id], now), q, events=True)


def all_leaks(t, q, raw):
    ids, only = q.get("watch_id") or [], q.get("preview_only") or ["0"]
    if not 1 <= len(ids) <= IDS_MAX:
        _invalid("watch_id")
    if only not in (["0"], ["1"]):
        _invalid("preview_only")
    ids, now = sorted({i for i in ids if WATCH_ID.match(i)}), tracker_db.now_dt()
    with tracker_db.db() as c:
        live = [r[0] for r in c.execute(f"SELECT watch_id FROM watches WHERE tenant_id = ? AND deleted_at IS NULL "
                                        f"AND watch_id IN ({','.join('?' * len(ids))})", [t["tenant_id"], *ids])] if ids else []
        ls = tracker_view.leaks(c, live, now)
    if only == ["1"]:
        ls = sorted((x for x in ls if x["preview"]), key=lambda x: x["leak_id"])
        ls.sort(key=_preview_seen, reverse=True)
        return 200, _page(ls, q, events=False, at=_preview_seen)
    return 200, _page(ls, q, events=False)


def thumb(t, q, raw, watch_id, leak_id):
    """The media Leak's thumbnail, fetched now under tracker_preview's checks; previews off, a Leak of another watch
    or tenant, one without a preview, or any refused fetch -> 404."""
    if not tracker_preview.on():
        raise _Err(404, NOT_FOUND)
    with tracker_db.db() as c:
        _own(c, t, watch_id)
        row = c.execute("SELECT * FROM leaks WHERE leak_id = ? AND watch_id = ?", (leak_id, watch_id)).fetchone()
        seen = row and c.execute("SELECT data_json FROM leak_events WHERE leak_id = ? AND type = 'google_seen' "
                                 "ORDER BY id DESC LIMIT 1", (leak_id,)).fetchone()
    vis = tracker_db.visible_of(json.loads(seen[0] or "{}")) if seen else None
    if not row or not tracker_preview.preview(row, vis):
        raise _Err(404, NOT_FOUND)
    if not _THUMBS.allow(t["tenant_id"]):
        raise _Err(429, RATE_LIMITED)
    try:
        got = tracker_preview.fetch(row["thumb_url"])
    finally:
        _THUMBS.release(t["tenant_id"])
    if not got:
        raise _Err(404, NOT_FOUND)
    return _Blob(got[1], got[0])


def offer_video(t, q, raw, part):
    name, ctype, ranged = tracker_video.PARTS.get(part, (None, None, False))
    p = tracker_video.path(name) if name else None
    if not p:
        raise _Err(404, NOT_FOUND)
    try:
        return _Take(open(p, "rb"), ctype, ranged)
    except OSError:
        raise _Err(404, NOT_FOUND) from None


ROUTES = (
    (re.compile(r"^/v1/me$"), {"GET": me}),
    (re.compile(r"^/v1/watches/([^/]+)$"), {"PUT": put_watch, "DELETE": delete_watch}),
    (re.compile(r"^/v1/creators$"), {"GET": creators}),
    (re.compile(r"^/v1/creators/([^/]+)$"), {"GET": creator_one}),
    (re.compile(r"^/v1/creators/([^/]+)/leaks$"), {"GET": creator_leaks}),
    (re.compile(r"^/v1/creators/([^/]+)/leaks/([^/]+)/thumb$"), {"GET": thumb}),
    (re.compile(r"^/v1/leaks$"), {"GET": all_leaks}),
    (re.compile(r"^/v1/offer-video/([^/]+)$"), {"GET": offer_video}),
)


def _dispatch(h, method, u):
    if h.headers.get("Transfer-Encoding") is not None:
        h.close_connection = True
        raise _Err(411, {"error": "length_required"})
    try:
        n = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        n = -1
    if n < 0 or n > BODY_CAP:
        h.close_connection = True
        raise _Err(413, {"error": "payload_too_large"})
    prev = h.connection.gettimeout()
    h.connection.settimeout(30)
    try:
        raw = h.rfile.read(n) if n else b""
    finally:
        h.connection.settimeout(prev)
    t = _auth(h)
    for rx, methods in ROUTES:
        m = rx.match(u.path)
        if m:
            if method not in methods:
                raise _Err(405, {"error": "method_not_allowed"})
            return methods[method](t, urllib.parse.parse_qs(u.query), raw, *m.groups())
    raise _Err(404, NOT_FOUND)


def handle(h, method):
    """Entry from public_app.Handler for GET/HEAD/POST/PUT/DELETE; non-/v1 paths keep the stock 501 for PUT/DELETE.
    No route takes HEAD, so it answers 401/404/405 without a body."""
    u = urllib.parse.urlsplit(h.path)
    if not is_v1(u.path):
        return h.send_error(501, f"Unsupported method ({method!r})")
    try:
        res = _dispatch(h, method, u)
    except _Err as e:
        res = e.code, e.body
    except Exception as e:
        _log(f"{method} failed: {type(e).__name__}")
        res = 500, {"error": "internal"}
    if isinstance(res, _Take):
        return _stream(h, res)
    if isinstance(res, _Blob):
        return _send(h, 200, res.data, ctype=res.ctype)
    code, obj = res
    _send(h, code, obj)

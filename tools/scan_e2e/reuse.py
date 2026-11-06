"""Per-scenario result reuse. A scenario's key = env + code (what it imports, the stub, the fixtures) + reach: {path: sha or
null} of everything it read last time, measured (reach.py). All recorded paths unchanged → a deterministic scenario reads the
same things, so a new dep can only appear through a changed recorded file: sound without a hand-kept map.

    <cache>/<scenario>/<code_key>/<reach_key>.json   {reach, run, sha, dirty, at, secs}   green only, atomic, no locks
    <cache>/map/<scenario>.json                      union of the paths over every complete run on any branch: --changed

Break runs (--break-* / --omit-*) neither read nor fill. A red run evicts what would have hit it."""
import ast
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import pathlib
import platform
import subprocess
import sys
import tempfile
import time

from .common import FLOWS, ROOT, cfg

CACHE = pathlib.Path(os.environ.get("E2E_REUSE_DIR") or "~/.leakscan-site/e2e-reuse").expanduser()
BASE = ("tools/scan_e2e.py", "tools/scan_stub.py", *(f"tools/scan_e2e/{m}.py" for m in ("__init__", "common", "main", "reuse", "reach")))
NOT_CACHEABLE = {}   # scenario → reason; audited 2026-11-06: none (README, "E2E result reuse")


def sha(b):
    return hashlib.sha256(b).hexdigest()[:32]


def code_hash(rel):
    """A .py by its ast (no comments, no module docstring, in common.py no BREAKS: break runs never touch the cache), else its bytes."""
    src = (ROOT / rel).read_bytes()
    if not rel.endswith(".py"):
        return sha(src)
    tree = ast.parse(src)
    if ast.get_docstring(tree, clean=False) is not None:
        tree.body.pop(0)
    if rel.endswith("/common.py"):
        tree.body = [n for n in tree.body if not (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "BREAKS")]
    return sha(ast.dump(tree).encode())


def code_inputs(s):
    mods, todo = set(), [f.split(".")[0] for f in FLOWS[s]]
    while todo:
        m = todo.pop()
        if m not in mods:
            mods.add(m)
            todo += [x for n in ast.walk(ast.parse((ROOT / f"tools/scan_e2e/{m}.py").read_bytes())) if isinstance(n, ast.ImportFrom) and n.level == 1
                     for x in ([n.module] if n.module else [a.name for a in n.names])]
    fx = [str(p.relative_to(ROOT)) for p in (ROOT / "tools/fixtures").rglob("*") if p.is_file()]
    return sorted({*BASE, *(f"tools/scan_e2e/{m}.py" for m in mods), *fx})


def env():
    """Pins the browser builds (no launch needed), so a full hit doesn't need Playwright to start."""
    spec = importlib.util.find_spec("playwright")
    pins = pathlib.Path(spec.origin).parent / "driver/package/browsers.json" if spec else None
    return {"browsers": sha(pins.read_bytes()) if pins and pins.exists() else None, "playwright": importlib.metadata.version("playwright") if spec else None,
            "python": "%d.%d" % sys.version_info[:2], "platform": platform.platform()}


def code_key(s, memo):
    for r in ["env", *(inputs := code_inputs(s))]:
        if r not in memo:
            memo[r] = env() if r == "env" else code_hash(r)
    return sha(json.dumps([memo[r] for r in ["env", *inputs]], sort_keys=True).encode())


def tree_hash(r, memo):
    """A recorded path now: file → sha, "dir/" entry → sha of its sorted names, directory → "dir", missing → null."""
    if r not in memo:
        p, h = ROOT / r, None
        if r.endswith("/"):
            h = sha("\n".join(sorted(x for x in os.listdir(p) if x != ".DS_Store")).encode()) if p.is_dir() else None
        elif p.is_dir():
            h = "dir"
        elif p.is_file():
            h = sha(p.read_bytes())
        memo[r] = h
    return memo[r]


def entries(s, ck):
    """Newest first."""
    out = []
    for f in (CACHE / s / ck).glob("*.json"):
        try:
            out.append((f.stat().st_mtime, f, json.loads(f.read_text())))
        except (OSError, ValueError):
            pass   # lost a race with an eviction / another writer's unlink
    return [(f, e) for _, f, e in sorted(out, key=lambda x: x[0], reverse=True)]


def run_ok(e, s, key):
    """The evidence is still there and still says this: pruned or overwritten by a later red run = rerun."""
    try:
        p = json.loads((pathlib.Path(e["run"]) / "e2e-summary.json").read_text())["per_scenario"][s]
    except (OSError, ValueError, KeyError):
        return False
    return p.get("status") == "ran" and not p.get("fails") and p.get("key") == key


def lookup(s, ck, memo):
    """The newest entry the tree still matches → (its file, it)."""
    for f, e in entries(s, ck):
        if all(tree_hash(r, memo) == h for r, h in e["reach"].items()) and run_ok(e, s, f"{ck}/{f.stem}"):
            return f, e
    return None


def atomic(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as w:
        json.dump(obj, w, indent=1, sort_keys=True)
    os.replace(tmp, path)


def load_map(s):
    try:
        return set(json.loads((CACHE / "map" / f"{s}.json").read_text()))
    except (OSError, ValueError):
        return None


def changed_files(ref):
    git = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True, check=True).stdout
    ref = ref or git("merge-base", "origin/main", "HEAD").strip()
    return {p for p in git("diff", "--name-only", "--no-renames", "-z", ref).split("\0") + git("ls-files", "--others", "--exclude-standard", "-z").split("\0") if p}


def reaches(s, changed):
    """Does the diff reach s: a changed path it read (or in a dir it listed), one of its code inputs, or no map yet."""
    m = load_map(s)
    if m is None:
        return True
    code, dirs = set(code_inputs(s)), [d for d in m if d.endswith("/")]
    return any(p in m or p in code or p.startswith("tools/fixtures/") or any(p.startswith(d) for d in dirs) for p in changed)


def cacheable():
    return not (cfg.broken or cfg.omit or cfg.omit_profile)


def plan():
    """→ (scenarios to run, per_scenario so far). Decided before the machine gate: queueing for a full hit is the waste."""
    todo, per, changed, memo, code = [], {}, None if cfg.changed is None else changed_files(cfg.changed), {}, {}
    for s in cfg.scenarios:
        if changed is not None and not reaches(s, changed):
            print(f"skip {s}: diff doesn't reach it", flush=True)
            per[s] = {"status": "skip"}
            continue
        if s in NOT_CACHEABLE and cacheable():
            print(f"{s}: not cacheable ({NOT_CACHEABLE[s]})", flush=True)
        hit = lookup(s, code_key(s, code), memo) if cacheable() and not cfg.no_reuse and s not in NOT_CACHEABLE else None
        if hit is None:
            todo.append(s)
            continue
        f, e = hit
        print(f"{s}: reused green from {e['run']} ({e.get('sha', '?')[:7]}{'+dirty' if e.get('dirty') else ''}, saved {e.get('secs', 0):.0f} s)", flush=True)
        per[s] = {"status": "reused", "secs": 0, "from_run": e["run"], "key": f"{f.parent.name}/{f.stem}", "fails": []}
    return todo, per


def enter_gate():
    """Misses exist and nobody holds the machine for us: wait for a slot now (same argv, same cwd). Scenarios that went green
    in the queue are hits after the re-exec."""
    gate = pathlib.Path("~/.slop/gate.py").expanduser()
    if not os.environ.get("SLOP_GATED") and gate.exists():
        sys.stdout.flush()
        os.execv(sys.executable, [sys.executable, str(gate), "run", "--", "nice", "-n", "10", sys.executable, os.path.abspath(sys.argv[0]), *sys.argv[1:]])


def summary_rows(old, per):
    """A run folder's rows: this run's + an earlier `ran` row it didn't replace. A later --only, or a reuse of that run, into the
    same OUT must not wipe the evidence run_ok() reads."""
    return {**per, **{s: r for s, r in old.items() if r.get("status") == "ran" and per.get(s, {}).get("status") != "ran"}}


def git_state():
    git = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout.strip()
    return git("rev-parse", "HEAD"), bool(git("status", "--porcelain"))


def finish(s, ck, t0, paths, bad, state):
    """After a run of s: map (complete runs, red too), evict (red), fill (green, nothing edited meanwhile) → the summary row."""
    secs, key, memo, paths = round(time.time() - t0, 1), ck, {}, paths - set(code_inputs(s))   # code is keyed by ast; the stub's tracebacks read its source
    if not any(f.endswith("ran to the end") for f in bad):
        atomic(CACHE / "map" / f"{s}.json", sorted((load_map(s) or set()) | paths))
    if bad:
        while hit := lookup(s, ck, memo):
            hit[0].unlink(missing_ok=True)
    else:
        reach = {r: tree_hash(r, memo) for r in paths}
        rk = sha(json.dumps(reach, sort_keys=True).encode())
        key = f"{ck}/{rk}"
        edited = [r for r in paths if (ROOT / r).exists() and (ROOT / r).stat().st_mtime >= t0] + (["the harness"] if code_key(s, {}) != ck else [])
        if edited:
            print(f"{s}: not cached, edited during the run: {sorted(edited)[:5]}", flush=True)
        elif s not in NOT_CACHEABLE:
            atomic(CACHE / s / ck / f"{rk}.json", {"reach": reach, "run": str(cfg.out.resolve()), "sha": state[0], "dirty": state[1], "at": time.time(), "secs": secs})
    print(f"{s}: ran {'green' if not bad else f'RED ({len(bad)} failed)'} {secs:.0f} s", flush=True)
    return {"status": "ran", "secs": secs, "key": key, "fails": bad}

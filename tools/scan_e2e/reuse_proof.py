#!/usr/bin/env python3
"""Proof of the result reuse on the real CLI, one PASS / FAIL line per check (run it under the machine gate, needs HEAD committed):

    cd ~/leakhunt && python3 ~/.slop/gate.py run -- nice -n 10 uv run python <repo>/tools/scan_e2e/reuse_proof.py EVIDENCE_DIR [--only s ...] [--break-key]

Two temp `git worktree`s of HEAD and a temp cache (E2E_REUSE_DIR). --break-key patches their reuse.py at MARKER so a hit ignores one recorded
file: only `c` may go red (a stale hit). Not part of any scenario's key. Writes timings.txt and reach-matrix.txt."""
import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from scan_e2e import reuse  # noqa: E402
from scan_e2e.common import ROOT, SCENARIOS  # noqa: E402

MARKER = 'for r, h in e["reach"].items())'
DROP = "E2E_PROOF_DROP"
CHEAP_RED = ("site/js/chat.js", "return HOSTS.indexOf(h) >= 0;", "return true;")   # on disk, not a --break: a plain run that goes red
KNOWN_RED = {"tabs", "removals", "inline"}   # all red on main at 5c51ad1 (measured), with or without this harness; drop one once it's fixed
reds = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name}{': ' + str(detail) if detail != '' else ''}", flush=True)
    if not ok:
        reds.append(name)


class Proof:
    def __init__(self, base, evid):
        self.a, self.b, self.cache, self.evid, self.times = base / "a", base / "b", base / "cache", evid, {}

    def cli(self, name, wt, *args, gated=True, during=None):
        """The real CLI in worktree wt into EVID/name → run: .rc .out .secs .ran .red .reused .skip .folder. gated=False: as a fresh shell (no SLOP_GATED)."""
        out = self.evid / name
        env = {**os.environ, "E2E_REUSE_DIR": str(self.cache)}
        if not gated:
            env.pop("SLOP_GATED", None), env.pop("SLOP_GATE_PID", None)
        t0 = time.time()
        p = subprocess.Popen([sys.executable, str(wt / "tools/scan_e2e.py"), str(out), *args], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if during:
            threading.Timer(during[0], during[1]).start()
        text = p.communicate()[0]
        (self.evid / f"{name}.log").write_text(text)
        r = type("Run", (), {})()
        r.rc, r.out, r.secs, r.folder = p.returncode, text, round(time.time() - t0, 2), out
        r.ran = dict(re.findall(r"^(\w+): ran (green|RED)", text, re.M))
        r.reused = dict(re.findall(r"^(\w+): reused green from (\S+)", text, re.M))
        r.skip = re.findall(r"^skip (\w+): diff doesn't reach it", text, re.M)
        self.times[name] = r.secs
        print(f"  [{name}] rc={r.rc} {r.secs} s ran={sorted(r.ran)} reused={sorted(r.reused)} skip={r.skip}", flush=True)
        return r

    def edit(self, wt, rel, tail):
        with open(wt / rel, "a") as f:
            f.write(tail)

    def revert(self, *wts):
        for wt in wts or (self.a,):
            subprocess.run(["git", "-C", str(wt), "checkout", "--", "."], check=True)
            subprocess.run(["git", "-C", str(wt), "clean", "-fdq"], check=True)

    def entries(self):
        return sorted(str(p) for s in SCENARIOS for p in (self.cache / s).glob("*/*.json"))

    def maps(self):
        return {s: set(json.loads((self.cache / "map" / f"{s}.json").read_text())) for s in SCENARIOS if (self.cache / "map" / f"{s}.json").exists()}

    def matrix(self):
        maps, site = self.maps(), sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "site").rglob("*") if p.is_file() and p.name != ".DS_Store")
        lines = ["path\t#scenarios\t" + "\t".join(maps)]
        for rel in site + sorted({x for m in maps.values() for x in m} - set(site)):
            lines.append(f"{rel}\t{sum(rel in m for m in maps.values())}\t" + "\t".join("x" if rel in m else "." for m in maps.values()))
        (self.evid / "reach-matrix.txt").write_text("\n".join(lines) + "\n")


def pick_file(maps, green, cost):
    """The site text file the fewest scenarios reach (one, if the map has such), green ones only, the cheapest → (path, its scenarios)."""
    by = {}
    for s, m in maps.items():
        for rel in m:
            if rel.startswith("site/") and rel.endswith((".js", ".css", ".html")):
                by.setdefault(rel, set()).add(s)
    return min(((rel, o) for rel, o in by.items() if o <= set(green)), key=lambda x: (len(x[1]), sum(cost[s] for s in x[1]), x[0]), default=(None, set()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("evidence")
    ap.add_argument("--only", action="append", choices=SCENARIOS)
    ap.add_argument("--break-key", action="store_true")
    a = ap.parse_args()
    evid = pathlib.Path(a.evidence).expanduser().resolve()
    evid.mkdir(parents=True, exist_ok=True)
    base = pathlib.Path(tempfile.mkdtemp(prefix="reuse-proof-")).resolve()
    p = Proof(base, evid)
    git = lambda *x: subprocess.run(["git", "-C", str(ROOT), *x], check=True, capture_output=True, text=True).stdout.strip()
    (evid / "SHA.txt").write_text(git("rev-parse", "HEAD") + "\n")
    print(f"proof of {git('rev-parse', 'HEAD')}{' with --break-key' if a.break_key else ''}, temp cache {p.cache}", flush=True)
    try:
        for wt in (p.a, p.b):
            git("worktree", "add", "-q", "--detach", str(wt), "HEAD")
            if a.break_key:
                f = wt / "tools/scan_e2e/reuse.py"
                src = f.read_text()
                assert MARKER in src, "--break-key: marker not found"
                f.write_text(src.replace(MARKER, 'for r, h in e["reach"].items() if r != os.environ.get("' + DROP + '"))', 1))
                subprocess.run(["git", "-C", str(wt), "commit", "-qam", "break-key", "--no-verify", "--author=proof <proof@example.invalid>"], check=True,
                               env={**os.environ, "GIT_COMMITTER_NAME": "proof", "GIT_COMMITTER_EMAIL": "proof@example.invalid"})
        sel = [x for s in (a.only or SCENARIOS) for x in ("--only", s)]
        cold = p.cli("0-cold", p.a, "--no-reuse", *sel)
        cost = {s: v["secs"] for s, v in json.loads((cold.folder / "e2e-summary.json").read_text())["per_scenario"].items()}
        green = [s for s, v in cold.ran.items() if v == "green"]
        check(f"cold: every scenario ran; red only in {sorted(KNOWN_RED)}", set(cold.ran) == {x for x in (a.only or SCENARIOS)} and not set(cold.ran) - set(green) - KNOWN_RED,
              {s: cold.ran.get(s) for s in (a.only or SCENARIOS)})
        only = [x for s in green for x in ("--only", s)]
        cheap = min(green, key=lambda s: cost[s])

        r = p.cli("a-same-sha", p.a, *only, gated=False)
        check("a: same SHA twice: every green scenario reused, no stub, < 5 s, no gate", set(r.reused) == set(green) and not r.ran and not (r.folder / "stub.err").exists()
              and r.secs < 5 and "gate" not in r.out.lower() and r.rc == 0, f"{r.secs} s")
        r = p.cli("b-other-worktree", p.b, *only, gated=False)
        check("b: a second worktree, same content: hit", set(r.reused) == set(green) and not r.ran and all(v == str(cold.folder) for v in r.reused.values()), set(r.reused.values()))

        maps = p.maps()
        rel, owner = pick_file(maps, green, cost)
        check("c: the map has a file only one scenario reaches", len(owner) == 1, f"{rel} → {sorted(owner)}")
        if rel:
            os.environ[DROP] = rel if a.break_key else ""   # only the cli children read it, and only in a patched reuse.py
            tail = "\n<!-- reuse proof -->\n" if rel.endswith(".html") else "\n/* reuse proof */\n"
            p.edit(p.a, rel, tail)
            r = p.cli("c-one-file", p.a, *only)
            check(f"c: one reached file changed ({rel}): only {sorted(owner)} reruns", set(r.ran) == owner and set(r.reused) == set(green) - owner, f"{r.secs} s, ran {sorted(r.ran)}")
            p.revert()
            r = p.cli("c-reverted", p.a, *only, gated=False)
            check("c2: reverted: the old entry hits again", set(r.reused) == set(green) and not r.ran)
        mod = next((s for s in sorted(green, key=lambda s: cost[s]) if f"tools/scan_e2e/{s}.py" in reuse.code_inputs(s)
                    and not any(f"tools/scan_e2e/{s}.py" in reuse.code_inputs(o) for o in SCENARIOS if o != s)), None)
        if mod:
            p.edit(p.a, f"tools/scan_e2e/{mod}.py", "\nREUSE_PROOF = 1\n")
            r = p.cli("c-module", p.a, *only)
            check(f"c3: a code edit in tools/scan_e2e/{mod}.py: only {mod} reruns", set(r.ran) == {mod} and set(r.reused) == set(green) - {mod})
            p.revert()

        p.edit(p.a, "README.md", "\nreuse proof\n")
        p.edit(p.a, "tools/make_icons.py", "\n# reuse proof\n")
        (p.a / "tools/reuse_proof_new.py").write_text("X = 1\n")
        r = p.cli("d-unrelated", p.a, *only, gated=False)
        check("d: README.md, tools/make_icons.py, a new tools/*.py: nothing reruns", set(r.reused) == set(green) and not r.ran and r.secs < 5, f"{r.secs} s")
        p.revert()

        ask = "askai" if "askai" in green else None
        if ask:
            before = p.entries()
            src = (p.a / CHEAP_RED[0]).read_text()
            (p.a / CHEAP_RED[0]).write_text(src.replace(CHEAP_RED[1], CHEAP_RED[2], 1))
            r1 = p.cli("e-red-1", p.a, "--only", ask)
            r2 = p.cli("e-red-2", p.a, "--only", ask)
            check("e: a red run is not reused nor cached", r1.ran.get(ask) == "RED" and r2.ran.get(ask) == "RED" and not r2.reused and p.entries() == before)
            p.revert()
            r = p.cli("e-red-reverted", p.a, "--only", ask, gated=False)
            check("e2: the older green of the unbroken tree still hits", ask in r.reused and not r.ran)
            map0 = (p.cache / "map" / f"{ask}.json").stat().st_mtime
            r = p.cli("e-break", p.a, "--only", ask, "--break-allowlist")
            check("e3: --break-allowlist runs on a hit, goes red, fills nothing, no reach measured", r.ran.get(ask) == "RED" and not r.reused and r.rc == 1 and p.entries() == before
                  and not (r.folder / f"reach-{ask}.log").exists() and (p.cache / "map" / f"{ask}.json").stat().st_mtime == map0, f"rc={r.rc}")
            r = p.cli("e-omit", p.a, "--only", ask, "--omit-results")
            check("e4: --omit-results runs on a hit and fills nothing", not r.reused and p.entries() == before and (r.folder / "e2e-summary.json").exists(), f"rc={r.rc}")
            r = p.cli("e-no-reuse", p.a, "--only", ask, "--no-reuse")
            check("e5: --no-reuse runs on a hit, a green fills", r.ran.get(ask) == "green" and not r.reused)
            r = p.cli("e-newer", p.a, "--only", ask, gated=False)
            check("e6: then the newest green is the one reused", r.reused.get(ask) == str(p.evid / "e-no-reuse"), r.reused.get(ask))
            before = p.entries()
            stamp = {x: pathlib.Path(x).stat().st_mtime for x in before}
            r = p.cli("h-edited", p.a, "--only", ask, "--no-reuse", during=(4, lambda: os.utime(p.a / "site/js/chat.js")))
            check("h: a reached file touched mid-run: not cached", "not cached, edited during the run" in r.out and p.entries() == before and {x: pathlib.Path(x).stat().st_mtime for x in before} == stamp)
            p.revert()

        src = (p.a / "tools/scan_e2e.py").read_text()
        (p.a / "tools/scan_e2e.py").write_text(src.replace("End-to-end proof", "End-to-end proof (reuse proof edit)", 1))
        src = (p.a / "tools/scan_stub.py").read_text()
        (p.a / "tools/scan_stub.py").write_text(src.replace("Local stand-in", "Local stand-in (reuse proof edit)", 1))
        r = p.cli("f-docstring", p.a, *only, gated=False)
        check("f: docstring-only edits of scan_e2e.py + scan_stub.py: nothing reruns", set(r.reused) == set(green) and not r.ran and r.secs < 5, f"{r.secs} s")
        g = p.cli("g-docstring", p.a, *only, "--changed", "HEAD", gated=False)
        check("g3: --changed: docstring of an input selects every scenario, all reused", set(g.reused) == set(green) and not g.skip)
        p.revert()
        allmaps = p.maps()
        nulls = sorted({x for s in green for f in (p.cache / s).glob("*/*.json") for x, h in json.loads(f.read_text())["reach"].items() if h is None})
        print(f"  recorded 404s: {nulls}", flush=True)
        miss = next((x for x in nulls if x.startswith("site/")), None) or (nulls[0] if nulls else None)
        if miss:
            (p.a / miss).parent.mkdir(parents=True, exist_ok=True)
            (p.a / miss).write_text("# reuse proof\n")
            s404 = min((s for s in green if miss in allmaps[s]), key=lambda s: cost[s])
            r = p.cli("f-404", p.a, "--only", s404)
            check(f"f2: {miss} (a recorded 404) now exists: {s404} misses", s404 in r.ran and not r.reused)
            p.revert()
        (p.a / "site/showcase/imgs/reuse-proof.webp").write_bytes((p.a / "site/showcase/imgs/portrait.webp").read_bytes())
        r = p.cli("f-newimg", p.a, "--only", cheap, "--changed", "HEAD")
        check(f"f3: a new image in a listed dir (site/showcase/imgs/): selected by --changed, {cheap} misses", cheap in r.ran and not r.reused)
        p.revert()

        if rel:
            p.edit(p.a, rel, tail)
            r = p.cli("g-file", p.a, "--changed", "HEAD", *only, gated=False)
            check(f"g1: --changed with {rel}: selects only {sorted(owner)}", set(r.skip) == set(green) - owner and owner <= set(r.reused) and not r.ran, r.skip)
            p.revert()
        p.edit(p.a, "README.md", "\nreuse proof\n")
        r = p.cli("g-readme", p.a, "--changed", "HEAD", *only, gated=False)
        check("g2: --changed with README.md: selects nothing, exit 0", set(r.skip) == set(green) and not r.ran and not r.reused and r.rc == 0)
        p.revert()
        r = p.cli("g-default", p.a, "--changed", *only, gated=False)
        check("g4: --changed default REF: merge-base with origin/main parses, decides", r.rc == 0 and not r.ran and set(r.reused) | set(r.skip) == set(green))
        (p.cache / "map" / f"{green[0]}.json").rename(p.cache / "map.gone")
        p.edit(p.a, "README.md", "\nreuse proof\n")
        r = p.cli("g-nomap", p.a, "--changed", "HEAD", "--only", green[0], gated=False)
        check("g5: --changed: a scenario with no map is selected", green[0] in r.reused and not r.skip)
        (p.cache / "map.gone").rename(p.cache / "map" / f"{green[0]}.json")
        p.revert()
        check("map: tabs has one though it is red (written on any complete run)", "tabs" in allmaps or "tabs" not in (a.only or SCENARIOS), sorted(allmaps))
        p.matrix()
        (evid / "timings.txt").write_text(json.dumps({"wall": p.times, "cold_per_scenario": cost}, indent=1) + "\n")
        shutil.copytree(p.cache, evid / "cache", dirs_exist_ok=True)
    finally:
        for wt in (p.a, p.b):
            subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(wt)], check=False)
        subprocess.run(["git", "-C", str(ROOT), "worktree", "prune"], check=False)
        shutil.rmtree(base, ignore_errors=True)
    print(f"reds: {reds}", flush=True)
    if a.break_key:
        ok = reds and all(x.startswith("c: one reached file") for x in reds)
        print(f"{'PASS' if ok else 'FAIL'} break-key: only check c went red (the stale hit)", flush=True)
        return 0 if ok else 1
    return 1 if reds else 0


if __name__ == "__main__":
    sys.exit(main())

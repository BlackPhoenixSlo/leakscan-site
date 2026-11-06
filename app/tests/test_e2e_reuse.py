"""tools/scan_e2e result reuse: the audit events it relies on really fire (a real stub, a fresh interpreter) and the key's rules. The real-browser proof: tools/scan_e2e/reuse_proof.py."""
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from scan_e2e import reach, reuse  # noqa: E402


def stub_reach(tmp_path, gets):
    log = tmp_path / "reach.log"
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    p = subprocess.Popen([sys.executable, str(ROOT / "tools/scan_stub.py"), "--port", str(port)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         env={**os.environ, reach.ENV: str(log)})
    try:
        p.stdout.readline()
        for path, headers in gets:
            try:
                urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)).read()
            except urllib.error.HTTPError:
                pass
    finally:
        p.terminate()
        p.wait()
        p.stdout.close()
    return set(log.read_text().split())


def test_stub_reach_is_measured_also_after_sigterm(tmp_path):
    got = stub_reach(tmp_path, [("/", {}), ("/nope-reuse.html", {}), ("/js/main.js", {}), ("/video/jack-poster.jpg", {"Range": "bytes=0-9"}),
                                ("/api/thumb?u=https://x.example/DEMO0001", {})])
    for want in ("app/public_app.py", "app/db.py", "tools/video/serve.py", "tools/fixtures/scan-sample.json",   # the import closure, .pyc or .py (twice: pyc on the 2nd)
                 "site/showcase/imgs/",   # THUMB_FILES' glob: a dir entry
                 "site/index.html", "site/js/main.js", "site/video/jack-poster.jpg", "site/nope-reuse.html"):   # a served file, a Range one, a 404
        assert want in got, want
    assert not {p for p in got if "__pycache__" in p or p.endswith(".pyc")}
    assert not {"tools/", "app/", "tools/video/"} & got   # the import system's own listdirs: a new tools/x.py reaches nothing
    assert got == got | stub_reach(tmp_path, [("/", {}), ("/nope-reuse.html", {}), ("/js/main.js", {}), ("/video/jack-poster.jpg", {"Range": "bytes=0-9"}),
                                              ("/api/thumb?u=https://x.example/DEMO0001", {})])


def test_in_process_toggle_reads_only(tmp_path):
    code = f"""
import os, pathlib, sys
sys.path.insert(0, {str(ROOT / 'tools')!r})
from scan_e2e import reach
seen = set()
(pathlib.Path({str(ROOT)!r}) / "README.md").read_text()   # off
reach.record(seen.add)
(pathlib.Path({str(ROOT)!r}) / "site/index.html").read_text()
list((pathlib.Path({str(ROOT)!r}) / "site/showcase/imgs").glob("*.webp"))
os.listdir({str(ROOT / 'site/js')!r})
open({str(ROOT / 'tools/.reuse-test-write')!r}, "w").close(); os.unlink({str(ROOT / 'tools/.reuse-test-write')!r})
open({str(tmp_path / 'outside')!r}, "w").close()
reach.note({str(ROOT / 'site/gone.html')!r})
reach.record(None)
(pathlib.Path({str(ROOT)!r}) / "CREDITS.md").read_text()
print(sorted(seen))
"""
    got = eval(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout)
    assert got == ["site/gone.html", "site/index.html", "site/js/", "site/showcase/imgs/"]


def test_pyc_maps_to_source():
    r = lambda p: reach.rel(os.path.join(reach.ROOT, p))
    assert r("app/__pycache__/public_app.cpython-312.pyc") == "app/public_app.py"
    assert r("app/__pycache__/public_app.cpython-313.pyc.4378204") == "app/public_app.py"   # importlib's temp name
    assert r("tools/__pycache__/x.cpython-312.opt-1.pyc") == "tools/x.py"
    assert reach.rel("/somewhere/else.py") is None and reach.rel(5) is None


def test_key_ignores_docstring_comments_and_breaks(tmp_path, monkeypatch):
    monkeypatch.setattr(reuse, "ROOT", tmp_path)
    f = tmp_path / "tools/scan_e2e/common.py"
    f.parent.mkdir(parents=True)
    base = '"""doc"""\nBREAKS = {"a": 1}\nX = 1  # note\n'
    f.write_text(base)
    h = reuse.code_hash("tools/scan_e2e/common.py")
    for same in ('"""other doc"""\nBREAKS = {"a": 1}\nX = 1\n', '"""doc"""\nBREAKS = {"a": 1, "b": 2}\n# new\nX = 1\n'):
        f.write_text(same)
        assert reuse.code_hash("tools/scan_e2e/common.py") == h
    f.write_text('"""doc"""\nBREAKS = {"a": 1}\nX = 2\n')
    assert reuse.code_hash("tools/scan_e2e/common.py") != h
    g = tmp_path / "tools/scan_e2e/other.py"   # BREAKS is common.py's only
    g.write_text('BREAKS = 1\n')
    h = reuse.code_hash("tools/scan_e2e/other.py")
    g.write_text('BREAKS = 2\n')
    assert reuse.code_hash("tools/scan_e2e/other.py") != h


def test_code_inputs_follow_the_import_closure():
    inp = {s: reuse.code_inputs(s) for s in reuse.FLOWS}
    assert "tools/scan_e2e/huge.py" in inp["scan"] and "tools/scan_e2e/huge.py" in inp["tabs"]   # a part of scan; tabs imports it
    assert "tools/scan_e2e/scan.py" in inp["removals"] and "tools/scan_e2e/scan.py" not in inp["askai"]
    for s in reuse.FLOWS:
        assert {"tools/scan_e2e/common.py", "tools/scan_e2e/reach.py", "tools/scan_stub.py", "tools/fixtures/scan-sample.json"} <= set(inp[s])


def test_tree_hash_and_map(tmp_path, monkeypatch):
    monkeypatch.setattr(reuse, "ROOT", tmp_path)
    monkeypatch.setattr(reuse, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(reuse, "code_inputs", lambda s: ["tools/x.py"])
    d = tmp_path / "site/imgs"
    d.mkdir(parents=True)
    (d / "a.webp").write_text("a")
    th = lambda r: reuse.tree_hash(r, {})
    listing, miss = th("site/imgs/"), th("site/gone.html")
    assert miss is None and th("site") == "dir"
    (d / "b.webp").write_text("b")
    (tmp_path / "site/gone.html").write_text("x")
    assert th("site/imgs/") != listing and th("site/gone.html") is not None
    assert reuse.reaches("scan", {"README.md"})   # no map: selected
    reuse.atomic(tmp_path / "cache/map/scan.json", ["site/a.js", "site/imgs/"])
    assert reuse.reaches("scan", {"site/a.js"}) and reuse.reaches("scan", {"site/imgs/c.webp"}) and reuse.reaches("scan", {"tools/x.py"})
    assert reuse.reaches("scan", {"tools/fixtures/new.json"})
    assert not reuse.reaches("scan", {"README.md", "site/b.js"})

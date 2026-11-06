"""What a process really read under the repo, measured with an audit hook (recorded deps, ccache-manifest style): every
`open` for reading, `os.scandir` / `os.listdir` as a dir entry ("a/b/", hashed by its sorted names: the stub's THUMB_FILES
glob). Stdlib only: the stub installs it before its first import. Not recorded: the import system's own listdir (a new
tools/x.py is no dep of what imports y; a new module can only arrive through an edit of a recorded file; a new file shadowing
a module is the one blind spot). A .pyc counts as its .py."""
import os
import re
import sys

ENV = "E2E_REACH_LOG"   # the stub logs to this file when set
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
PYC = re.compile(r"^(.*/)?__pycache__/([^/]+?)\.[^/.]+-\d+(?:\.opt-\d+)?\.pyc(?:\.\d+)?$")
WRITES = os.O_WRONLY | os.O_RDWR
_sink, _hooked = None, False


def rel(path):
    """Repo-relative path (a .pyc → its .py), None if outside the repo / not a path."""
    try:
        p = os.path.abspath(os.fsdecode(path))
    except (TypeError, ValueError):   # an fd; a hook must never raise into the open() it watches
        return None
    if not p.startswith(ROOT + os.sep):
        return None
    p = p[len(ROOT) + 1:]
    m = PYC.match(p)
    return f"{m.group(1) or ''}{m.group(2)}.py" if m else p


def note(path, is_dir=False):
    """Record one path now, also one that doesn't exist (a 404, hashed as null: adding it later is a miss)."""
    r = rel(path) if _sink else None
    if r is not None:
        _sink(r + "/" if is_dir else r)


def _hook(event, args):
    if _sink is None:
        return
    if event == "open":
        if not (isinstance(args[2], int) and args[2] & WRITES):
            note(args[0])
    elif event in ("os.scandir", "os.listdir") and not sys._getframe(1).f_code.co_filename.startswith("<frozen importlib"):
        note("." if args[0] is None else args[0], True)


def record(sink):
    """sink(relpath) from now on; None = off (an audit hook can't be removed, only silenced)."""
    global _sink, _hooked
    _sink = sink
    if not _hooked:
        _hooked = True
        sys.addaudithook(_hook)


def to_log(path):
    """One line per new path, written at once (the stub dies by SIGTERM: no atexit, nothing buffered)."""
    fd, seen = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644), set()

    def sink(r):
        if r not in seen:
            seen.add(r)
            os.write(fd, (r + "\n").encode())
    record(sink)

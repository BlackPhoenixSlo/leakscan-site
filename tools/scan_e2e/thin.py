"""Green evidence keeps what proves it. A scenario that passed keeps its summary, logs, JSON and proof shots; its other PNGs go. Red, break and
--keep-all runs keep every frame. Only PNGs written since t0 and only directly in `out`: a parent folder given as OUT can't lose another run's frames."""
import re

NAMED = re.compile(r"(?:^|-)(?:trigger|settled|proof)[-.]|-pip-strip-")   # trigger, settled, what a scenario names as proof (`follow:`'s strip)


def since(out, t0):
    shots = sorted((p.stat().st_mtime, p) for p in out.glob("*.png"))
    return [p for m, p in shots if m >= t0]


def ends(out, t0):
    """The first and last shot since t0: a part's trigger and settled state, whatever it calls them."""
    s = since(out, t0)
    return set(s[:1] + s[-1:])


def thin(out, t0, keep, named=NAMED):
    """→ how many went."""
    gone = [p for p in since(out, t0) if p not in keep and not named.search(p.name)]
    for p in gone:
        p.unlink(missing_ok=True)
    return len(gone)

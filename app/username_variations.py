#!/usr/bin/env python3
"""
Username variation generator — creators re-upload under near-miss handles.

Given one handle it emits the realistic variations to throw at a site's search
bar / profile URLs: separator swaps, numeric suffixes, common tag words
(of/onlyfans/vip/leak), light leetspeak, and a vowel-drop. Most-likely first,
deduped, capped.

Use it standalone, or as `--names-file` input to the other tools:

    python3 username_variations.py husvjjal
    python3 username_variations.py husvjjal --max 40 > aliases.txt
    python3 leak_scanner.py --names-file aliases.txt
    python3 site_probe.py --names-file aliases.txt --domains-file sites.txt

It's also importable: `from username_variations import variations`.
The scanner/crawler/probe expose a `--variations` flag that calls this directly.
"""

import argparse
import re
import sys

SEPS = ["", "_", "-", "."]
# tag words creators append when re-uploading
SUFFIX_WORDS = ["1", "2", "3", "01", "02", "x", "xo", "xx", "vip", "of", "onlyfans",
                "free", "official", "real", "tv", "leak", "leaks", "nude", "nudes", "fans"]
PREFIX_WORDS = ["real", "official", "its", "x", "the", "miss", "ms"]
LEET = {"o": "0", "i": "1", "l": "1", "e": "3", "a": "4", "s": "5", "t": "7", "b": "8"}


def variations(name, max_out=60):
    base = (name or "").strip()
    if not base:
        return []
    low = base.lower()
    core = re.sub(r"[^a-z0-9]", "", low)          # alphanumerics only
    parts = [p for p in re.split(r"[^a-z0-9]+", low) if p]

    out = []
    def add(x):
        x = (x or "").strip()
        if x and x not in out:
            out.append(x)

    add(base)
    add(low)
    add(core)

    # separator variants of a multi-part handle: husv_jjal / husv-jjal / husv.jjal
    if len(parts) > 1:
        for s in SEPS:
            add(s.join(parts))

    # numeric / tag-word suffixes (on the core and on the separated form)
    forms = [core] + (["_".join(parts), "-".join(parts)] if len(parts) > 1 else [])
    for f in forms:
        for w in SUFFIX_WORDS:
            add(f + w)
            add(f + "_" + w)

    # prefixes
    for pfx in PREFIX_WORDS:
        add(pfx + core)
        add(pfx + "_" + core)

    # light leetspeak: first-occurrence swap and full swap, one letter at a time
    for ch, repl in LEET.items():
        if ch in core:
            add(core.replace(ch, repl, 1))
            add(core.replace(ch, repl))

    # vowel drop (common in stylized handles) and doubled trailing char
    novow = re.sub(r"[aeiou]", "", core)
    if 3 <= len(novow) < len(core):
        add(novow)
    if core:
        add(core + core[-1])

    return out[:max_out]


def expand_all(names, max_each=60):
    """Expand a list of handles into the union of their variations (order-preserving)."""
    out = []
    for n in names:
        for v in variations(n, max_each):
            if v not in out:
                out.append(v)
    return out


def main():
    p = argparse.ArgumentParser(description="Generate realistic username variations for leak hunting.")
    p.add_argument("names", nargs="+", help="Base handle(s).")
    p.add_argument("--max", type=int, default=60, help="Max variations per input handle.")
    args = p.parse_args()
    for v in expand_all(args.names, args.max):
        print(v)


if __name__ == "__main__":
    main()

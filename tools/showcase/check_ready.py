#!/usr/bin/env python3
"""Refuse to ship a half-filled template.

The template ships with four kinds of deliberate hole:

    {{TOKEN}}           a value to substitute
    <!-- WRITE: ... --> prose that must be written from scratch
    <!-- FILL: ... -->  a list or table to complete

Any of them reaching production is a visible defect — a page reading
"{{BRAND_NAME}}", an empty biography, or worst, a takedown notice with a
blank Schedule A row. This is the last gate before a site goes live.

    python3 tools/showcase/check_ready.py

Showcase adaptation: reads site/showcase/ (no DMCA notice ships here).
Silent and exit 0 when nothing is unfilled; anything printed is a failure.
"""

import json
import re
import sys
from bisect import bisect_left

import _sitelib as site

MARKER = re.compile(r"<!--\s*(WRITE|FILL):", re.I)
FILL_CLASS = re.compile(r'class="[^"]*\bfill\b[^"]*"')
# A content element left empty by the template. Matched across the whole file
# rather than line by line, because the template's own formatting puts the
# opening and closing tags of an unwritten paragraph on separate lines.
EMPTY_EL = re.compile(
    r"<(p|h1|h2|h3|blockquote|time|span|td)(\s[^>]*)?>\s*</\1>", re.I | re.S
)


def scan(paths):
    problems = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.relative_to(site.ROOT)
        newlines = [m.start() for m in re.finditer(r"\n", text)]

        def lineno(pos):
            return bisect_left(newlines, pos) + 1

        for m in site.TOKEN.finditer(text):
            problems.append((rel, lineno(m.start()), f"unsubstituted token {m.group(0)}"))
        for m in MARKER.finditer(text):
            problems.append((rel, lineno(m.start()), f"unresolved {m.group(1).upper()} marker"))
        for m in FILL_CLASS.finditer(text):
            problems.append((rel, lineno(m.start()), 'placeholder cell (class="fill")'))
        for m in EMPTY_EL.finditer(text):
            # Decorative markup (the nav toggle's hamburger bars) is empty on
            # purpose; it says so with aria-hidden.
            if 'aria-hidden="true"' in (m.group(2) or ""):
                continue
            problems.append((rel, lineno(m.start()), f"empty <{m.group(1)}> element"))
    return problems


def check_jsonld(paths):
    """Substitution is the thing most likely to break structured data — an
    apostrophe or a stray newline inside a JSON string literal."""
    bad = []
    for path in paths:
        try:
            site.ld_blocks(path)
        except json.JSONDecodeError as e:
            bad.append((path.relative_to(site.ROOT), f"JSON-LD invalid: {e}"))
    return bad


def main() -> int:
    site.require_public()
    # Every text file that ships, stylesheets included. This was a
    # hand-written {.html, .xml, .txt} and base.css shipped a live
    # {{BRAND_NAME}} straight through the gate.
    paths = list(site.text_files())

    problems = scan(paths)
    bad_json = check_jsonld([p for p in paths if p.suffix == ".html"])

    for rel, msg in bad_json:
        print(f"FAIL  {rel}: {msg}")

    by_file = {}
    for rel, lineno, msg in problems:
        by_file.setdefault(rel, []).append((lineno, msg))

    for rel in sorted(by_file, key=str):
        items = sorted(by_file[rel])
        print(f"\n{rel}  ({len(items)} unfilled)")
        for lineno, msg in items[:12]:
            print(f"    line {lineno}: {msg}")
        if len(items) > 12:
            print(f"    … and {len(items) - 12} more")

    total = len(problems) + len(bad_json)
    if total:
        print(f"\n{total} unfilled item(s). Do not publish the showcase.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

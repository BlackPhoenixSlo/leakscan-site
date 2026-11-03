#!/usr/bin/env python3
"""Refuse to ship anything the site does not actually reference.

Two client sites have already leaked files this way: liviapaige.com served the
whole repo root because the branch had no netlify.toml, and the zane branch
still carried the previous client's photographs under public/imgs/. Neither
leak was text, so no name-denylist would have caught them. The invariant that
does catch them is structural:

    only public/ deploys, and public/ holds only files a page points at.

Showcase adaptation: the showcase is site/showcase/ of leakscan-site and
ships with the landing page (GitHub Pages from site/), so the template's
netlify.toml leg is gone; the invariant is the same one level down:

    site/showcase/ holds only files a showcase page points at.

    python3 tools/showcase/check_deploy.py

Silent and exit 0 when clean. There is no --quiet and no warning tier. A file that ships unreferenced and a
link that goes nowhere are both failures, because a check that routinely
prints noise is a check nobody reads.
"""

import re
import sys

import _sitelib as site

# Files that legitimately ship without any page linking to them, because the
# host asks for them by name rather than following a link. The host
# configuration half of this list is _sitelib's — naming those files twice is
# how two lists that must agree start disagreeing.
# The showcase is noindex and has no robots.txt, sitemap.xml or host config
# of its own (the landing's robots.txt covers /showcase/), so none of those
# are allowlisted: if one appears here it fails as unreferenced.
ALLOWLIST = {
    "404.html",           # demo of the error page; never linked
    "index.html",         # entry point
}
ALLOWLIST_PATTERNS: list[re.Pattern] = []


def glob_to_re(pattern: str) -> re.Pattern:
    """Compile one deploy-allowlist glob.

    fnmatch is not used here on purpose: its `*` silently crosses `/`, so
    `imgs/blog-*.webp` would also exempt `imgs/blog-x/nested/anything.webp`.
    On the file that governs which unreferenced files may ship, a glob must
    mean what it looks like.

        *       anything except a slash
        **      anything, including slashes
        dir/    that directory and everything under it
    """
    if pattern.endswith("/"):
        return re.compile(re.escape(pattern) + ".*$")
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if pattern[i + 1:i + 2] == "*":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out) + "$")


def load_site_allowlist():
    """Per-site globs for files that legitimately ship unlinked.

    Kept in deploy-allowlist.txt next to this script so that every such file
    is an explicit, reviewable decision rather than something that quietly
    rode along.
    """
    path = site.TOOLS / "deploy-allowlist.txt"
    if not path.exists():
        return []
    globs = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            globs.append(glob_to_re(line))
    return globs


SITE_ALLOWLIST = load_site_allowlist()


def is_allowlisted(rel: str) -> bool:
    return (
        rel in ALLOWLIST
        or any(p.match(rel) for p in ALLOWLIST_PATTERNS + SITE_ALLOWLIST)
    )


def main() -> int:
    errors: list[str] = []

    if not site.PUBLIC.is_dir():
        print(f"FAIL  {site.PUBLIC} does not exist — nothing to check.")
        return 1

    referenced, broken = site.scan()

    # --- 1. Every shipped file must be referenced. -----------------------
    shipped = list(site.site_files())
    orphans = [
        (rel, path.stat().st_size)
        for path, rel in ((p, p.relative_to(site.PUBLIC).as_posix()) for p in shipped)
        if path not in referenced and not is_allowlisted(rel)
    ]
    if orphans:
        total = sum(size for _, size in orphans)
        errors.append(
            f"{len(orphans)} file(s) under site/showcase/ are referenced by no page "
            f"but would still be served ({total / 1e6:.1f} MB):"
        )
        errors += [f"      {rel}  ({size / 1e3:.0f} KB)" for rel, size in orphans]

    # --- 2. Internal links must resolve. Root-relative links ("/x") land
    # here too: under /showcase/ they point at the landing, not at us. ---------------------------------
    # A dead link is an error, not a warning. On a site whose entire job is to
    # be the authoritative record, a 404 in the nav or the sitemap is the
    # failure — and warnings that ship by default get ignored.
    if broken:
        errors.append(f"{len(broken)} reference(s) point at a file that does not exist:")
        for src, ref, target in broken:
            errors.append(f"      {src.relative_to(site.PUBLIC)} -> {ref}")

    for e in errors:
        print(e if e.startswith("      ") else f"FAIL  {e}")

    if errors:
        print("\nDo not deploy.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

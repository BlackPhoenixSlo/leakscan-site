#!/usr/bin/env python3
"""Assert every official-account list on the showcase still agrees.

The site's core claim is "this is the complete list of her accounts."
Four places state it, on purpose:

    about.html      `sameAs`  -- the machine-readable owner (what Google reads)
    links.html                -- the canonical human-readable page
    statement.html            -- the formal statement, quoted in takedown reports
    index.html      footer    -- the icon strip, a verification claim of its own

Showcase adaptation. The demo creator is fictional, and a real profile URL
(instagram.com/<handle>) may belong to a real person, so no account on the
showcase points at a third-party platform. Instead each account is a row on
links.html with id="<platform>-<handle>", and every other list points at that
row (`links.html#instagram-brennickclay`; sameAs uses the absolute form). The
account identity is that fragment. This script checks:

  - every list names the same set of accounts as about.html's sameAs
  - every account reference points at links.html, and links.html really has
    an element with that id (no dangling row)
  - no page links a real platform profile URL at all

    python3 tools/showcase/_check_accounts.py

Silent and exit 0 when every list agrees. It reads pages through _sitelib's
parser, so an account commented out of a page is an account removed.
"""
import re
import sys
from html.parser import HTMLParser
from urllib.parse import urlsplit

import _sitelib as site

# Platforms a creator posts from. The fragment prefix names the platform.
PLATFORMS = (
    "tiktok", "instagram", "youtube", "patreon", "x", "threads", "bluesky",
    "snapchat", "twitch", "pinterest", "etsy", "linktree", "substack",
)
ACCOUNT = re.compile(rf"^(?:{'|'.join(PLATFORMS)})-[A-Za-z0-9._]+$")

# Real platform hosts. Linking any of them from the demo is a failure: the
# handle may be a real person's.
REAL_HOSTS = {
    "tiktok.com", "instagram.com", "x.com", "twitter.com", "snapchat.com",
    "onlyfans.com", "fansly.com", "linktr.ee", "link.me", "beacons.ai",
    "throne.com", "youtube.com", "youtu.be", "twitch.tv", "reddit.com",
    "bsky.app", "threads.net", "patreon.com", "pinterest.com", "etsy.com",
    "substack.com", "facebook.com",
}

LINKS = "links.html"
CANDIDATES = ["about.html", LINKS, "statement.html", "index.html"]


class _Ids(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k == "id" and v:
                self.ids.add(v)


def ids_in(rel):
    p = _Ids()
    p.feed((site.PUBLIC / rel).read_text(encoding="utf-8", errors="ignore"))
    p.close()
    return p.ids


def host_of(url):
    return urlsplit(url).netloc.lower().removeprefix("www.")


def scan(rel, errors):
    """Account keys one page states, plus any rule it breaks."""
    path = site.PUBLIC / rel
    found = set()
    for ref in site.references(path):
        h = host_of(ref)
        if any(h == p or h.endswith("." + p) for p in REAL_HOSTS):
            errors.append(f"{rel}: links a real platform profile ({ref}) — "
                          f"the demo creator is fictional")
            continue
        frag = urlsplit(ref).fragment
        if not ACCOUNT.match(frag):
            continue
        if ref.startswith("#"):
            target_ok = rel == LINKS
        else:
            target = site.resolve(ref, path, site.site_domain())
            target_ok = target == (site.PUBLIC / LINKS).resolve()
        if not target_ok:
            errors.append(f"{rel}: account reference {ref} does not point at {LINKS}")
            continue
        found.add(frag)
    return found


def main() -> int:
    site.require_public()
    errors: list[str] = []

    found = {s: scan(s, errors) for s in CANDIDATES if (site.PUBLIC / s).exists()}
    # Real-profile links anywhere on the site, not just the four lists.
    for path in site.content_files():
        rel = path.relative_to(site.PUBLIC).as_posix()
        if rel not in found:
            scan(rel, errors)

    canonical = found.get("about.html", set())
    if not canonical:
        errors.append("about.html states no sameAs accounts — nothing to check against")

    for src, accounts in found.items():
        for key in sorted(canonical - accounts):
            errors.append(f"MISSING from {src}: {key}")
        for key in sorted(accounts - canonical):
            errors.append(f"EXTRA in {src} (not in about.html sameAs): {key}")

    if (site.PUBLIC / LINKS).exists():
        rows = ids_in(LINKS)
        for key in sorted(canonical - rows):
            errors.append(f"{LINKS} has no row with id=\"{key}\" for sameAs to point at")

    for e in errors:
        print(f"FAIL  {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

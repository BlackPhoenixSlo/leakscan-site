"""Re-sync guard (README "Backend"): every local change to a file copied from bruquiextension is a line ending in
`# one-project: <site>` or sits in the file's `>>> one-project patch` block. A re-sync that drops one of them (or
the block) turns this red; a new local change adds its site here."""
import collections
import difflib
import os
import re
import subprocess
import sys
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)

SITES = {
    "public_app.py": {"hints": 4, "landing site": 2, "HEAD": 2, "aggregator rule": 3, "mega[]": 1, "aliases": 2,
                      "scan_begin": 2, "scan_end": 5, "estimate": 1, "domain_count": 1,
                      "api_thumb Vary": 2, "thumb sheet": 2, "scan reuse": 12, "retention": 3},
    "cse_scanner.py": {"deadline": 6, "errors": 7},
    "profile_extract.py": {"hints": 8},
    "media_gather.py": {"NONE_TTL": 3, "warmup": 1, "web retry": 5},
    "db.py": {"domain_count": 4, "get_scan": 1, "retention": 4},
    "chat_proxy.py": {},
}
BLOCK = {"public_app.py": 1, "cse_scanner.py": 0, "profile_extract.py": 1, "media_gather.py": 1, "db.py": 1,
         "chat_proxy.py": 1}
UPSTREAM = os.environ.get("BRUQUI_REPO", os.path.expanduser("~/bruquiextension"))   # read only: `git show` of BASE
BASE = "bb294d0"   # the upstream commit these files were last synced to (README "Backend")
MARK = re.compile(r"^\s*\S.*?#\s*one-project: ([^(\n]+?)\s*(?:\(.*)?$", re.M)


class TestOneProjectSites(unittest.TestCase):
    def test_every_hook_site_and_block_present(self):
        for name, want in SITES.items():
            src = open(os.path.join(APP, name), encoding="utf-8").read()
            self.assertEqual(dict(collections.Counter(MARK.findall(src))), want, name)
            self.assertEqual((src.count(">>> one-project patch"), src.count("<<< one-project patch")),
                             (BLOCK[name], BLOCK[name]), name)

    def test_block_patches_took(self):
        import chat_proxy
        import profile_extract
        self.assertIn("other_names: display names", profile_extract.SYSTEM_PROMPT)   # the str.replace matched
        self.assertNotIn("LeakScan", chat_proxy.LANDING_SYSTEM_PROMPT)
        self.assertIn("helper on the Abolita landing page", chat_proxy.LANDING_SYSTEM_PROMPT)

    def test_every_local_change_is_marked(self):
        """vs upstream BASE (when that checkout is here): every added / changed line is in the file's block or carries
        `# one-project`, and no upstream line was deleted outright."""
        if not os.path.isdir(os.path.join(UPSTREAM, ".git")):
            self.skipTest(f"no upstream checkout at {UPSTREAM}")
        for name in SITES:
            up = subprocess.run(["git", "-C", UPSTREAM, "show", f"{BASE}:{name}"], capture_output=True, text=True,
                                check=True).stdout.splitlines()
            me = open(os.path.join(APP, name), encoding="utf-8").read().splitlines()
            block, on = set(), False
            for i, line in enumerate(me):
                on = on or ">>> one-project patch" in line
                if on:
                    block.add(i)
                on = on and "<<< one-project patch" not in line
            bad = []
            for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, up, me, autojunk=False).get_opcodes():
                if op == "delete":
                    bad += [f"deleted: {up[i].strip()[:80]}" for i in range(i1, i2)]
                elif op in ("replace", "insert"):
                    bad += [f"{j + 1}: {me[j].strip()[:80]}" for j in range(j1, j2)
                            if me[j].strip() and j not in block and "# one-project" not in me[j]]
            self.assertEqual(bad, [], name)


if __name__ == "__main__":
    unittest.main()

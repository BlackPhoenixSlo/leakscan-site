"""The vendored leak-tool modules run on the standard library: no httpx, bs4 or requests import, no CSE / Serper
client, and they import in a process where those packages cannot load."""
import ast
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
VENDORED = ("tracker_pagekind", "tracker_llm", "tracker_jev", "tracker_verdicts", "tracker_serp")
BANNED = ("httpx", "bs4", "requests", "cse_scanner")


def source(name):
    with open(os.path.join(APP, f"{name}.py"), encoding="utf-8") as f:
        return f.read()


def imports(name):
    out = set()
    for node in ast.walk(ast.parse(source(name))):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".")[0])
    return out


class Vendored(unittest.TestCase):
    def test_no_banned_imports(self):
        for name in VENDORED:
            with self.subTest(name):
                self.assertFalse(imports(name) & set(BANNED))

    def test_no_cse_or_serper_client(self):
        for name in VENDORED:
            with self.subTest(name):
                low = source(name).lower()
                self.assertNotIn("serper", low)
                self.assertNotIn("cse_scanner", low)
                self.assertNotIn("googleapis.com/customsearch", low)

    def test_they_import_with_the_banned_packages_blocked(self):
        code = ("import sys\nfor m in %r: sys.modules[m] = None\nsys.path.insert(0, %r)\n"
                "for m in %r: __import__(m)\nprint('ok')" % (BANNED, APP, VENDORED))
        r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "ok"), r.stderr)


if __name__ == "__main__":
    unittest.main()

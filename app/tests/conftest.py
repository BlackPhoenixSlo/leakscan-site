"""Before any test module imports public_app: whole-scan reuse off, these tests repeat scans to exercise the fresh path.
test_scan_reuse.py turns it on for itself."""
import os

os.environ["SCAN_REUSE_TTL"] = "0"

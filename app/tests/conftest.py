"""Before any test module imports public_app: whole-scan reuse off, these tests repeat scans to exercise the fresh path.
test_scan_reuse.py turns it on for itself.
The paid Google lanes run for every tenant with creds (no allowlist), so no test may see a real key: the paid-service
keys are stripped here, and every test gets a Browserbase client pointing at a closed loopback port and a Playwright
that refuses to start (tests that drive the lanes patch their own stubs over these)."""
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SCAN_REUSE_TTL"] = "0"
for _k in ("BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID", "DEEPSEEK_API_KEY", "GOOGLE_API_KEY", "GOOGLE_CSE_ID",
           "GOOGLE_CSE_ID_WEB"):
    os.environ.pop(_k, None)


@pytest.fixture(autouse=True)
def _no_paid_browserbase():
    with mock.patch("bb_client.BB_API", "http://127.0.0.1:9"), \
            mock.patch("tracker_serp._playwright", mock.Mock(side_effect=AssertionError("no Playwright in tests"))):
        yield

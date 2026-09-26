"""Test isolation: never let the suite write to the real ~/.max.

app.config reads MAX_DATA_DIR at import time, so this must run before any
MAX module is imported. pytest loads conftest.py before test modules.
"""

import os
import shutil
import tempfile

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="max-test-")
os.environ["MAX_DATA_DIR"] = _TEST_DATA_DIR


def pytest_unconfigure(config):
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)

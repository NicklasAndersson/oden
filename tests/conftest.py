"""Isolate the test suite from the developer's real ~/.oden config.

oden.config reads config.db at import time, so ODEN_HOME must point at an
empty temp directory before any `oden.*` module is imported anywhere in the
suite. conftest.py is loaded before test modules are collected, which makes
this the right place.
"""

import os
import tempfile

os.environ.setdefault("ODEN_HOME", tempfile.mkdtemp(prefix="oden-test-home-"))

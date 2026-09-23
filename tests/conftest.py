"""Isolate the test suite from the developer's real ~/.oden config.

oden.config reads config.db at import time, so ODEN_HOME must point at an
empty temp directory before any `oden.*` module is imported anywhere in the
suite. conftest.py is loaded before test modules are collected, which makes
this the right place.
"""

import os
import tempfile

_HOME = tempfile.mkdtemp(prefix="oden-test-home-")
os.environ.setdefault("ODEN_HOME", _HOME)
# ODEN_HOME does not cover the log path — it is platform-fixed
# (~/Library/Logs/Oden on macOS). tests/test_s7_watcher.py runs main(), which
# calls configure_logging() and attaches a RotatingFileHandler to the *root*
# logger, so from then on every record in the session lands in the developer's
# real log — and rotates the genuine history away.
os.environ.setdefault("ODEN_LOG_FILE", os.path.join(_HOME, "oden-test.log"))

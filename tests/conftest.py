"""Project-wide pytest bootstrap.

The environment preamble intentionally imports only the standard library and
runs before any backend module.  Database singletons therefore observe the
test-only namespace at import time.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

pytest_plugins = ("tests.support.db",)

# Capture the repository's production location before the test home is forced.
# This is exposed for the isolation meta-suite without importing the backend.
PRODUCTION_DB_PATH = (Path.cwd() / ".protokflow" / "protokflow.db").resolve()

_TEST_HOME = Path(tempfile.mkdtemp(prefix="protokflow-test-")).resolve()
os.environ.setdefault("PROTOKFLOW_TEST_RUN_ID", f"r{uuid4().hex[:8]}")
os.environ["PROTOKFLOW_TEST"] = "1"
os.environ["PROTOKFLOW_HOME"] = str(_TEST_HOME)


def pytest_unconfigure(config: object) -> None:
    """Best-effort cleanup of this pytest process's temporary home."""
    del config
    try:
        shutil.rmtree(_TEST_HOME)
    except OSError:
        pass

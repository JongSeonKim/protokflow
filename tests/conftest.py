"""Project-wide pytest configuration and bootstrap.

Sets up isolated temporary test environments and the ``PROTOKFLOW_HOME``
environment override, ensuring tests never interact with production data. The
database engine is created only through explicit initialization or the shared
fixtures, so no pre-import URL binding is required.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

pytest_plugins = ("tests.fixtures.db", "tests.fixtures.git")

# Resolved path to the repository-local production database, used by meta-tests
# to verify that test executions do not write to or alter production state.
PRODUCTION_DB_PATH = (Path.cwd() / ".protokflow" / "protokflow.db").resolve()

# Create an isolated temporary directory for this test process/worker.
_TEST_HOME = Path(tempfile.mkdtemp(prefix="protokflow-test-")).resolve()
os.environ.setdefault("PROTOKFLOW_TEST_RUN_ID", f"r{uuid4().hex[:8]}")
os.environ["PROTOKFLOW_HOME"] = str(_TEST_HOME)


def pytest_unconfigure(config: object) -> None:
    """Clean up the temporary test home directory when the test session ends."""
    del config
    try:
        shutil.rmtree(_TEST_HOME)
    except OSError:
        pass

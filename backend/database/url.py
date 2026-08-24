"""Database path and URL derivation utilities.

Provides pure functions to derive SQLite database file paths and connection URLs.
Importing this module causes no side effects.
"""

from __future__ import annotations

import os
from pathlib import Path


def create_database_path(*, unittest: bool = False) -> Path:
    """Derive the SQLite database file path.

    Resolves the database directory from `PROTOKFLOW_HOME` (defaulting to `.protokflow`
    under the current working directory). When `unittest=True`, appends run ID and
    worker identifiers to produce an isolated test database filename.
    """
    root = Path(os.environ.get("PROTOKFLOW_HOME", Path.cwd() / ".protokflow"))
    if unittest:
        base = "protokflow_test"
        run_id = os.environ.get("PROTOKFLOW_TEST_RUN_ID", "")
        suffix = os.environ.get("PYTEST_XDIST_WORKER", "")
        parts = [base]
        if run_id:
            parts.append(run_id)
        if suffix and suffix != "master":
            parts.append(suffix)
        filename = "_".join(parts)
    else:
        filename = "protokflow"
    return root / f"{filename}.db"


def create_database_url(*, unittest: bool = False) -> str:
    """Create an async SQLite connection URL (`sqlite+aiosqlite`).

    Ensures the parent directory exists before returning the connection string.
    """
    path = create_database_path(unittest=unittest).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{path}"

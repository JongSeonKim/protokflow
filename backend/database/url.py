"""Database path and URL derivation utilities.

Provides pure functions to derive SQLite database file paths and connection
URLs from a worktree root. Importing this module causes no side effects.
"""

from __future__ import annotations

import os
from pathlib import Path


def create_database_path(*, worktree_root: Path, unittest: bool = False) -> Path:
    """
    Derive the SQLite database file path for a worktree root

    Resolves the database directory from ``PROTOKFLOW_HOME`` (defaulting to
    ``.protokflow`` under the worktree root). When ``unittest=True``, appends
    run ID and worker identifiers to produce an isolated test database filename.

    :param worktree_root: repository worktree root the database belongs to
    :param unittest: derive the isolated test database filename
    :return:
    """
    root = Path(os.environ.get("PROTOKFLOW_HOME", Path(worktree_root) / ".protokflow"))
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


def create_database_url(*, worktree_root: Path, unittest: bool = False) -> str:
    """
    Create an async SQLite connection URL for a worktree root

    Ensures the parent directory exists before returning the connection string.

    :param worktree_root: repository worktree root the database belongs to
    :param unittest: derive the isolated test database filename
    :return:
    """
    path = create_database_path(
        worktree_root=worktree_root, unittest=unittest
    ).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{path}"


def to_sync_url(url: str) -> str:
    """
    Normalize an async SQLite URL to the synchronous dialect

    :param url: sync or async SQLite connection URL
    :return:
    """
    return url.replace("sqlite+aiosqlite://", "sqlite://", 1)


def database_path_from_url(url: str) -> Path:
    """
    Extract the database file path from a SQLite connection URL

    :param url: sync or async SQLite connection URL
    :return:
    """
    _, separator, tail = url.partition(":///")
    if not separator:
        raise ValueError(f"not a file-backed SQLite URL: {url}")
    return Path(tail)

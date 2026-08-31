"""Database path and URL derivation utilities.

Provides pure functions to derive SQLite database file paths and connection
URLs from a worktree root. Importing this module causes no side effects.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.engine import make_url

_ASYNC_SQLITE_DRIVERNAME = "sqlite+aiosqlite"


def _ensure_url_safe_path(path: Path) -> None:
    """Reject paths that cannot survive a SQLite connection URL round trip."""
    if "?" in str(path):
        raise ValueError(f"database path contains URL-reserved characters: {path}")


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
    path = root / f"{filename}.db"
    _ensure_url_safe_path(path)
    return path


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
    return async_sqlite_url(path)


def async_sqlite_url(path: str | Path) -> str:
    """
    Build an async SQLite connection URL for a database file path

    Single owner of the async SQLite URL template so production and the test
    harness derive identical connection strings.

    :param path: resolved database file path
    :return:
    """
    url = make_url(f"{_ASYNC_SQLITE_DRIVERNAME}:///").set(database=str(Path(path)))
    return str(url)


def to_sync_url(url: str) -> str:
    """
    Normalize an async SQLite URL to the synchronous dialect

    :param url: sync or async SQLite connection URL
    :return:
    """
    return str(make_url(url).set(drivername="sqlite"))


def database_path_from_url(url: str) -> Path:
    """
    Extract the database file path from a SQLite connection URL

    :param url: sync or async SQLite connection URL
    :return:
    """
    database = make_url(url).database
    if (
        not database
        or database == ":memory:"
        or database.startswith("file:")
        or not Path(database).is_absolute()
    ):
        raise ValueError(f"not a file-backed SQLite URL: {url}")
    return Path(database)

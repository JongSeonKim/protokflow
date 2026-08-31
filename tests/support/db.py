"""Database utility helpers for isolated SQLite test environments.

Provides path validation, file cleanup (including SQLite WAL/SHM sidecars),
and schema inspection utilities used by the test database harness in
``tests/fixtures/db.py``.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from alembic.util.exc import CommandError
from sqlalchemy import Connection, create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from backend.database.migrate import downgrade_database, upgrade_database
from backend.database.url import async_sqlite_url, to_sync_url


# Prefix used for temporary SQLite test databases to prevent accidental production collisions.
TEST_DATABASE_PREFIX = "protokflow_test_"
_TEST_DATABASE_STEM = re.compile(rf"^{re.escape(TEST_DATABASE_PREFIX)}[^/]+$")


def validate_test_database_path(
    path: str | Path,
    *,
    home: str | Path | None = None,
) -> Path:
    """Validate that a database path is located under the test directory and uses the test prefix."""
    resolved = Path(path).expanduser().resolve(strict=False)
    configured_home = home or os.environ.get("PROTOKFLOW_HOME")
    if not configured_home:
        raise RuntimeError("test database home is not configured")
    test_home = Path(configured_home).expanduser().resolve(strict=False)

    try:
        resolved.relative_to(test_home)
    except ValueError as exc:
        raise RuntimeError(
            f"test database path must be under the test database home: {resolved}"
        ) from exc

    if resolved.suffix != ".db" or not _TEST_DATABASE_STEM.fullmatch(resolved.stem):
        raise RuntimeError(
            f"test database filename must use the {TEST_DATABASE_PREFIX} prefix: "
            f"{resolved.name}"
        )
    return resolved


def database_sidecar_paths(path: str | Path) -> tuple[Path, Path, Path]:
    """Return the primary SQLite database file and its auxiliary WAL/SHM sidecar paths."""
    database = Path(path)
    return (
        database,
        database.with_name(f"{database.name}-wal"),
        database.with_name(f"{database.name}-shm"),
    )


def cleanup_database_files(path: str | Path) -> None:
    """Remove SQLite database and sidecar files, ignoring errors if files are missing or locked."""
    for candidate in database_sidecar_paths(path):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            # Ignore cleanup errors to avoid masking test failures.
            pass


async def reset_test_database_schema(path: str | Path) -> None:
    """
    Reset an isolated test database through the real migration lifecycle

    Validates the path before touching anything. A poisoned database left
    by a failed run is dropped table-by-table on the same file so fixture
    setup can always rebuild through real migrations.

    :param path: isolated test database path
    :return:
    """
    resolved = validate_test_database_path(path)
    url = async_sqlite_url(resolved)
    try:
        await asyncio.to_thread(downgrade_database, url)
    except CommandError, OperationalError:
        await asyncio.to_thread(_drop_all_tables, url)
    await asyncio.to_thread(upgrade_database, url)


def _drop_all_tables(url: str) -> None:
    """Drop every user table in place so a poisoned file can be rebuilt."""
    engine = create_engine(to_sync_url(url))
    try:
        with engine.begin() as connection:
            names = connection.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name NOT LIKE 'sqlite_%'"
                )
            ).scalars()
            for name in names:
                connection.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
    finally:
        engine.dispose()


def table_names(connection: Connection) -> list[str]:
    """Inspect and return the list of table names present in the database."""
    return inspect(connection).get_table_names()

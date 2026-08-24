"""Shared pytest fixtures for isolated SQLite database tests."""

from __future__ import annotations

import os
import re
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from backend.database import db


TEST_DATABASE_PREFIX = "protokflow_test_"
_TEST_DATABASE_STEM = re.compile(rf"^{re.escape(TEST_DATABASE_PREFIX)}[^/]+$")


def validate_test_database_path(
    path: str | Path,
    *,
    home: str | Path | None = None,
) -> Path:
    """Validate the resolved test DB path before any engine can open it."""
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
    """Return the SQLite database and its WAL/SHM sidecar paths."""
    database = Path(path)
    return (
        database,
        database.with_name(f"{database.name}-wal"),
        database.with_name(f"{database.name}-shm"),
    )


def cleanup_database_files(path: str | Path) -> None:
    """Best-effort cleanup after the engine has been disposed."""
    for candidate in database_sidecar_paths(path):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            # A failed cleanup should not mask the test's original failure.
            pass


@pytest.fixture(scope="session", autouse=True)
def _test_database_guard() -> Iterator[None]:
    """Reject any test process whose resolved DB path leaves its namespace."""
    validate_test_database_path(db.create_database_path(unittest=True))
    yield


@pytest.fixture(scope="session")
async def test_engine(_test_database_guard: None) -> AsyncGenerator[AsyncEngine, None]:
    """Provide one isolated SQLite engine per pytest process/xdist worker."""
    del _test_database_guard
    path = validate_test_database_path(db.create_database_path(unittest=True))
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = db.create_database_async_engine(f"sqlite+aiosqlite:///{path}")
    previous_engine = db._active_engine
    db._set_engine_for_testing(engine)
    try:
        yield engine
    finally:
        try:
            await engine.dispose()
        finally:
            db._set_engine_for_testing(previous_engine)
            cleanup_database_files(path)


@pytest.fixture
async def test_db(test_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a clean schema and session, routed through the DB proxies."""
    factory = db.create_database_async_session(test_engine)
    previous_factory = db._active_factory
    db._set_factory_for_testing(factory)
    session: AsyncSession | None = None
    try:
        await db.create_tables()
        session = factory()
        yield session
    finally:
        try:
            if session is not None:
                try:
                    if session.in_transaction():
                        await session.rollback()
                finally:
                    await session.close()
        finally:
            try:
                await db.drop_tables()
            finally:
                db._set_factory_for_testing(previous_factory)


__all__ = [
    "TEST_DATABASE_PREFIX",
    "cleanup_database_files",
    "database_sidecar_paths",
    "test_db",
    "test_engine",
    "validate_test_database_path",
]

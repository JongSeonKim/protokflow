"""Pytest fixtures for isolated SQLite database testing.

Manages per-worker engine and session lifecycle, redirecting global database
proxies in ``backend.database.db`` to an isolated SQLite database for each
test worker and resetting schema state through the migration lifecycle.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator
from pathlib import Path

import pytest

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from backend.database import db
from backend.database.url import create_database_path
from tests.support.db import (
    cleanup_database_files,
    reset_test_database_schema,
    validate_test_database_path,
)


def _test_database_path() -> Path:
    """Derive the isolated test database path for this process and worker."""
    return create_database_path(worktree_root=Path.cwd(), unittest=True)


@pytest.fixture(scope="session", autouse=True)
def _test_database_guard() -> Iterator[None]:
    """Ensure the resolved database path is strictly confined to the test environment."""
    validate_test_database_path(_test_database_path())
    yield


@pytest.fixture(scope="session")
async def test_engine(_test_database_guard: None) -> AsyncGenerator[AsyncEngine, None]:
    """Provide a session-scoped async SQLite engine isolated to this test worker."""
    del _test_database_guard
    path = validate_test_database_path(_test_database_path())
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
    """Provide an async database session with a fresh migration-based schema."""
    factory = db.create_database_async_session(test_engine)
    previous_factory = db._active_factory
    db._set_factory_for_testing(factory)
    session: AsyncSession | None = None
    try:
        await reset_test_database_schema(
            validate_test_database_path(_test_database_path())
        )
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
            db._set_factory_for_testing(previous_factory)

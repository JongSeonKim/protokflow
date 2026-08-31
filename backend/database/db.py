"""Database connection and session management.

Provides explicit worktree-bound database initialization, async SQLite engine
configuration, session factories, and dependency providers for FastAPI.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast

from fastapi import Depends
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.core.conf import settings
from backend.database.migrate import upgrade_database
from backend.database.url import create_database_url, database_path_from_url

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


def _apply_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    """Configure SQLite PRAGMAs (WAL mode, foreign keys, busy timeout) on connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute(f"PRAGMA busy_timeout={settings.DATABASE_SQLITE_BUSY_TIMEOUT_MS}")
    cursor.close()


def create_database_async_engine(url: str) -> AsyncEngine:
    """Create an async database engine configured with SQLite PRAGMA event listeners."""
    engine = create_async_engine(url, future=True)
    event.listen(engine.sync_engine, "connect", _apply_sqlite_pragmas)
    return engine


def create_database_async_session(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession | Any]:
    """Create an async session factory bound to the specified engine."""
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )


def resolve_database_url(*, worktree_root: Path) -> str:
    """
    Resolve the async database URL for a worktree root

    ``PROTOKFLOW_DATABASE_URL`` takes precedence over the derived path so
    test harnesses can redirect the database location.

    :param worktree_root: repository worktree root the database belongs to
    :return:
    """
    return os.environ.get("PROTOKFLOW_DATABASE_URL") or create_database_url(
        worktree_root=worktree_root
    )


def _apply_owner_only_storage_permissions(database_path: Path) -> None:
    """Restrict the database storage layer (body and WAL/SHM sidecars) to the owner."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    database_path.parent.chmod(0o700)
    # Create with owner-only mode when missing; avoid touching the timestamps
    # of an existing database on re-initialization.
    if not database_path.exists():
        database_path.touch(mode=0o600)
    database_path.chmod(0o600)
    for suffix in ("-wal", "-shm"):
        sidecar = database_path.with_name(f"{database_path.name}{suffix}")
        try:
            sidecar.chmod(0o600)
        except FileNotFoundError:
            continue


async def initialize_database(*, worktree_root: Path) -> AsyncEngine:
    """
    Initialize the worktree database and install the active engine and factory

    Applies pending migrations on a worker thread, then publishes the engine
    and session factory as one atomic runtime slot under a process-wide
    initialization lock; re-initialization disposes the previous engine.

    :param worktree_root: repository worktree root the database belongs to
    :return:
    """
    global _active_runtime
    async with _initialization_lock:
        url = resolve_database_url(worktree_root=worktree_root)
        _apply_owner_only_storage_permissions(database_path_from_url(url))
        await asyncio.to_thread(upgrade_database, url)
        engine = create_database_async_engine(url)
        factory = create_database_async_session(engine)
        previous = _active_runtime
        previous_engine = previous.engine if previous is not None else None
        _active_runtime = _DatabaseRuntime(engine=engine, factory=factory)
        if previous_engine is not None and previous_engine is not engine:
            await previous_engine.dispose()
        return engine


async def shutdown_database() -> None:
    """
    Dispose the active engine and clear the active runtime slot

    :return:
    """
    global _active_runtime
    engine = _active_runtime.engine if _active_runtime is not None else None
    _active_runtime = None
    if engine is not None:
        await engine.dispose()


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Provide an async database session for FastAPI dependencies."""
    async with async_db_session() as session:
        yield session


async def get_db_transaction() -> AsyncGenerator[AsyncSession]:
    """Provide an async database session wrapped in an active transaction."""
    async with async_db_session.begin() as session:
        yield session


@dataclass(frozen=True)
class _DatabaseRuntime:
    """Engine and session factory published as one atomic slot."""

    engine: AsyncEngine | None
    factory: async_sessionmaker[AsyncSession | Any] | None


_active_runtime: _DatabaseRuntime | None = None
_initialization_lock = asyncio.Lock()


def _get_active_engine() -> AsyncEngine:
    """Return the active engine, raising before explicit initialization."""
    runtime = _active_runtime
    if runtime is None or runtime.engine is None:
        raise RuntimeError("Database engine is not initialized")
    return runtime.engine


def _set_engine_for_testing(engine: AsyncEngine | None) -> None:
    """Override the active engine for test harness isolation."""
    global _active_runtime
    factory = _active_runtime.factory if _active_runtime is not None else None
    _active_runtime = (
        None
        if engine is None and factory is None
        else _DatabaseRuntime(engine=engine, factory=factory)
    )


def _get_active_factory() -> async_sessionmaker[AsyncSession | Any]:
    """Return the active session factory."""
    runtime = _active_runtime
    if runtime is None or runtime.factory is None:
        raise RuntimeError("Database session factory is not initialized")
    return runtime.factory


class _SessionFactoryProxy:
    """Proxy delegating calls to the currently active session factory."""

    def __call__(self) -> Any:
        return _get_active_factory()()

    def begin(self) -> Any:
        return _get_active_factory().begin()

    def __getattr__(self, name: str) -> Any:
        return getattr(_get_active_factory(), name)


async_db_session = cast(
    "async_sessionmaker[AsyncSession | Any]", _SessionFactoryProxy()
)


def _set_factory_for_testing(factory: Any) -> None:
    """Override the active session factory for test harness isolation."""
    global _active_runtime
    engine = _active_runtime.engine if _active_runtime is not None else None
    _active_runtime = (
        None
        if engine is None and factory is None
        else _DatabaseRuntime(engine=engine, factory=factory)
    )


# Session dependencies
CurrentSession = Annotated[AsyncSession, Depends(get_db)]
CurrentSessionTransaction = Annotated[AsyncSession, Depends(get_db_transaction)]

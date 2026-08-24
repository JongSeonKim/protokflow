"""Database connection and session management.

Provides async SQLite engine configuration, session factories, schema lifecycle
helpers, and dependency providers for FastAPI.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Annotated, Any, cast

from fastapi import Depends
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.app.protokflow import model as _protokflow_model  # noqa: F401  # Register models for metadata
from backend.common.model import MappedBase
from backend.core.conf import settings
from backend.database.url import create_database_path, create_database_url

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


# SQLite schema version expected by the application
EXPECTED_SCHEMA_VERSION = 1


class SchemaVersionMismatch(RuntimeError):
    """Raised when the database schema version does not match EXPECTED_SCHEMA_VERSION."""


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


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Provide an async database session for FastAPI dependencies."""
    async with async_db_session() as session:
        yield session


async def get_db_transaction() -> AsyncGenerator[AsyncSession]:
    """Provide an async database session wrapped in an active transaction."""
    async with async_db_session.begin() as session:
        yield session


async def read_schema_version(conn: AsyncConnection) -> int:
    """Read the current SQLite schema version via `PRAGMA user_version`."""
    return await conn.scalar(text("PRAGMA user_version"))


async def ensure_schema_version(conn: AsyncConnection) -> int:
    """Validate or initialize the SQLite schema version (`PRAGMA user_version`)."""
    current = await read_schema_version(conn)
    if current == 0:
        await conn.exec_driver_sql(f"PRAGMA user_version = {EXPECTED_SCHEMA_VERSION}")
        return EXPECTED_SCHEMA_VERSION
    if current != EXPECTED_SCHEMA_VERSION:
        raise SchemaVersionMismatch(
            f"Database schema version mismatch: PRAGMA user_version is "
            f"{current!r}, but this code expects {EXPECTED_SCHEMA_VERSION!r}. "
            f"Recovery: delete the repository-local database "
            f"({create_database_path()}) and re-index design systems from the "
            f"DESIGN.md files — the DB is a disposable work store."
        )
    return current


async def create_tables() -> None:
    """Create all registered metadata tables and initialize schema version on the active engine."""
    async with _get_active_engine().begin() as conn:
        await conn.run_sync(MappedBase.metadata.create_all)
        await ensure_schema_version(conn)


async def drop_tables() -> None:
    """Drop all registered metadata tables from the active engine."""
    async with _get_active_engine().begin() as conn:
        await conn.run_sync(MappedBase.metadata.drop_all)


# Default database URL: uses PROTOKFLOW_DATABASE_URL if provided, else derives the repo SQLite path.
SQLALCHEMY_DATABASE_URL = (
    os.environ.get("PROTOKFLOW_DATABASE_URL") or create_database_url()
)
async_engine = create_database_async_engine(SQLALCHEMY_DATABASE_URL)


_active_engine: AsyncEngine | None = None
_active_factory: async_sessionmaker[AsyncSession | Any] | None = None


def _get_active_engine() -> AsyncEngine:
    """Return the active engine, defaulting to the module-level async_engine."""
    return _active_engine if _active_engine is not None else async_engine


def _set_engine_for_testing(engine: AsyncEngine | None) -> None:
    """Override the active engine for test harness isolation."""
    global _active_engine
    _active_engine = engine


def _get_active_factory() -> async_sessionmaker[AsyncSession | Any]:
    """Return the active session factory."""
    if _active_factory is None:
        raise RuntimeError("DB session factory is not initialized")
    return _active_factory


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

# Default session factory
_active_factory = create_database_async_session(async_engine)


def _set_factory_for_testing(factory: Any) -> None:
    """Override the active session factory for test harness isolation."""
    global _active_factory
    _active_factory = factory


# Session dependencies
CurrentSession = Annotated[AsyncSession, Depends(get_db)]
CurrentSessionTransaction = Annotated[AsyncSession, Depends(get_db_transaction)]

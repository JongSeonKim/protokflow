"""Database connection layer.

Structure mirrors gsplay-api's backend/database/db.py (user decision), with
SQLite/aiosqlite substitutions the schema doc requires (§6, §9):

- URL builder -> repository-scoped .protokflow/ path builder
- pool tuning/Prometheus listener -> PRAGMA listener (foreign_keys, WAL,
  busy_timeout) attached to every new connection
- bare create_all -> create_all + schema_meta.schema_version boot check (R20)
- create_server_url (CREATE/DROP DATABASE) -> dropped, meaningless for SQLite
"""

from __future__ import annotations

import os
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
from backend.app.protokflow import model as _protokflow_model  # noqa: F401  importing registers all storage tables
from backend.app.protokflow.model.schema_meta import SchemaMeta
from backend.common.model import MappedBase

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


SCHEMA_VERSION_KEY = "schema_version"
EXPECTED_SCHEMA_VERSION = "1"
BUSY_TIMEOUT_MS = 5_000


class SchemaVersionMismatch(RuntimeError):
    """Raised when schema_meta.schema_version differs from the code's (R20)."""


def create_database_path(*, unittest: bool = False) -> Path:
    """
    Create database file path

    Repository-scoped isolation (§1-1): one SQLite file per repository under
    PROTOKFLOW_HOME (default: <cwd>/.protokflow).

    :param unittest: Whether the path is for unit tests (per-run isolation
        suffix, mirroring gsplay-api's test-DB naming)
    :return:
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
    """Create database connection URL (sqlite+aiosqlite)."""
    path = create_database_path(unittest=unittest).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{path}"


def _apply_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    """Force PRAGMAs on every new connection (schema doc §9)."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    cursor.close()


def create_database_async_engine(url: str) -> AsyncEngine:
    """
    Create database async engine

    SQLite needs no pool tuning; the connect listener enforces the PRAGMA
    contract instead (foreign_keys / WAL / busy_timeout).

    :param url: Database connection URL
    :return:
    """
    engine = create_async_engine(url, future=True)
    event.listen(engine.sync_engine, "connect", _apply_sqlite_pragmas)
    return engine


def create_database_async_session(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession | Any]:
    """
    Create database async session

    :param engine: Database async engine
    :return:
    """
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Get database session"""
    async with async_db_session() as session:
        yield session


async def get_db_transaction() -> AsyncGenerator[AsyncSession]:
    """Get database session with transaction"""
    async with async_db_session.begin() as session:
        yield session


async def ensure_schema_version(session: AsyncSession) -> str:
    """Seed or verify schema_meta.schema_version (R20 boot check).

    - Fresh DB: insert the expected version row.
    - Existing DB: version must match, else SchemaVersionMismatch with the
      documented recovery path (DB is disposable; re-index from DESIGN.md).
    """
    row = await session.get(SchemaMeta, SCHEMA_VERSION_KEY)
    if row is None:
        session.add(SchemaMeta(key=SCHEMA_VERSION_KEY, value=EXPECTED_SCHEMA_VERSION))
        await session.commit()
        return EXPECTED_SCHEMA_VERSION
    if row.value != EXPECTED_SCHEMA_VERSION:
        raise SchemaVersionMismatch(
            f"Database schema version mismatch: schema_meta.{SCHEMA_VERSION_KEY} is "
            f"{row.value!r}, but this code expects {EXPECTED_SCHEMA_VERSION!r}. "
            f"Recovery: delete the repository-local database "
            f"({create_database_path()}) and re-index design systems from the "
            f"DESIGN.md files — the DB is a disposable work store."
        )
    return row.value


async def create_tables() -> None:
    """Create database tables (migration-free boot path, §9).

    create_all + schema_version check. On mismatch this raises before any
    tool call touches the DB, with deletion + re-indexing as recovery.
    """
    async with _get_active_engine().begin() as conn:
        await conn.run_sync(MappedBase.metadata.create_all)
    async with async_db_session() as session:
        await ensure_schema_version(session)


async def drop_tables() -> None:
    """Drop database tables"""
    async with _get_active_engine().begin() as conn:
        await conn.run_sync(MappedBase.metadata.drop_all)


_TEST_RUN = os.environ.get("PROTOKFLOW_TEST") == "1"
SQLALCHEMY_DATABASE_URL = create_database_url(unittest=_TEST_RUN)
async_engine = create_database_async_engine(SQLALCHEMY_DATABASE_URL)


_active_engine: AsyncEngine | None = None
_active_factory: async_sessionmaker[AsyncSession | Any] | None = None


def _get_active_engine() -> AsyncEngine:
    """Return the lifecycle engine, falling back to the production singleton."""
    return _active_engine if _active_engine is not None else async_engine


def _set_engine_for_testing(engine: AsyncEngine | None) -> None:
    """Test-only hook for swapping the lifecycle engine.

    Production code must never call this. Test fixtures may set an isolated
    engine for their session scope and pass ``None`` during teardown to restore
    the import-time production singleton.
    """
    global _active_engine
    _active_engine = engine


class _SessionFactoryProxy:
    """Lookup-time forwarder for the active session factory.

    `async_db_session()` and `async_db_session.begin()` are the two public
    surfaces; both re-read `_active_factory` from this module's globals on
    every call. Swapping the factory once redirects every consumer —
    including ones that bound the symbol at import time — without
    per-import-site patching.
    """

    def __call__(self) -> Any:
        factory = _active_factory
        if factory is None:
            raise RuntimeError("DB session factory is not initialized")
        return factory()

    def begin(self) -> Any:
        factory = _active_factory
        if factory is None:
            raise RuntimeError("DB session factory is not initialized")
        return factory.begin()

    def __getattr__(self, name: str) -> Any:
        factory = _active_factory
        if factory is None:
            raise RuntimeError("DB session factory is not initialized")
        return getattr(factory, name)


async_db_session = cast(
    "async_sessionmaker[AsyncSession | Any]", _SessionFactoryProxy()
)

# Eager production singleton — preserves prior import-time behavior.
_active_factory = create_database_async_session(async_engine)


def _set_factory_for_testing(factory: Any) -> None:
    """Test-only hook. Swap the active factory behind the proxy.

    Production code must never call this. A conftest fixture invokes it once
    per test to redirect every `async_db_session()` / `.begin()` consumer
    to a per-test session.
    """
    global _active_factory
    _active_factory = factory


# Session Annotated
CurrentSession = Annotated[AsyncSession, Depends(get_db)]
CurrentSessionTransaction = Annotated[AsyncSession, Depends(get_db_transaction)]

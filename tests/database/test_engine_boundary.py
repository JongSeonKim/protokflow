"""Tests for the database lifecycle engine injection boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import inspect

from backend.database import db


def _database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve()}"


def _table_names(connection: Any) -> list[str]:
    return inspect(connection).get_table_names()


@pytest.mark.asyncio
async def test_active_engine_defaults_to_production_singleton() -> None:
    """Without an override, lifecycle callers use the import-time singleton."""
    db._set_engine_for_testing(None)

    assert db._get_active_engine() is db.async_engine


@pytest.mark.asyncio
async def test_create_tables_uses_injected_engine_and_factory(tmp_path: Path) -> None:
    """DDL and schema seeding stay on the swapped engine/factory pair."""
    engine = db.create_database_async_engine(_database_url(tmp_path / "isolated.db"))
    factory = db.create_database_async_session(engine)
    previous_engine = db._active_engine
    previous_factory = db._active_factory
    db._set_engine_for_testing(engine)
    db._set_factory_for_testing(factory)

    try:
        await db.create_tables()

        async with engine.connect() as connection:
            tables = await connection.run_sync(_table_names)
        assert "schema_meta" in tables

        async with factory() as session:
            row = await session.get(db.SchemaMeta, db.SCHEMA_VERSION_KEY)
        assert row is not None
        assert row.value == db.EXPECTED_SCHEMA_VERSION
    finally:
        db._set_factory_for_testing(previous_factory)
        db._set_engine_for_testing(previous_engine)
        await engine.dispose()


@pytest.mark.asyncio
async def test_drop_tables_uses_injected_engine(tmp_path: Path) -> None:
    """Dropping through the lifecycle boundary removes only the test schema."""
    engine = db.create_database_async_engine(_database_url(tmp_path / "isolated.db"))
    factory = db.create_database_async_session(engine)
    previous_engine = db._active_engine
    previous_factory = db._active_factory
    db._set_engine_for_testing(engine)
    db._set_factory_for_testing(factory)

    try:
        await db.create_tables()
        await db.drop_tables()

        async with engine.connect() as connection:
            tables = await connection.run_sync(_table_names)
        assert tables == []
    finally:
        db._set_factory_for_testing(previous_factory)
        db._set_engine_for_testing(previous_engine)
        await engine.dispose()


@pytest.mark.asyncio
async def test_engine_hook_can_be_cleared(tmp_path: Path) -> None:
    """Clearing the testing hook restores the production singleton."""
    engine = db.create_database_async_engine(_database_url(tmp_path / "isolated.db"))
    try:
        db._set_engine_for_testing(engine)
        assert db._get_active_engine() is engine

        db._set_engine_for_testing(None)
        assert db._get_active_engine() is db.async_engine
    finally:
        db._set_engine_for_testing(None)
        await engine.dispose()

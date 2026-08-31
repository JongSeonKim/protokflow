"""Tests for the explicit worktree-bound database initialization boundary."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.core.registrar import register_init
from backend.database import db
from backend.database.migrate import current_revision, head_revision
from backend.database.url import create_database_path, create_database_url
from tests.support.db import async_sqlite_url


async def _restore_active_slots(
    previous_runtime: Any,
    *created: AsyncEngine,
) -> None:
    previous_factory = previous_runtime.factory if previous_runtime else None
    previous_engine = previous_runtime.engine if previous_runtime else None
    db._set_factory_for_testing(previous_factory)
    db._set_engine_for_testing(previous_engine)
    for engine in created:
        await engine.dispose()


@pytest.fixture
def isolated_database_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Isolate URL derivation from the test-home environment overrides."""
    monkeypatch.delenv("PROTOKFLOW_HOME", raising=False)
    monkeypatch.delenv("PROTOKFLOW_DATABASE_URL", raising=False)
    return tmp_path


def test_different_worktree_roots_derive_isolated_database_paths(
    isolated_database_environment: Path,
) -> None:
    root = isolated_database_environment
    first = create_database_path(worktree_root=root / "alpha")
    second = create_database_path(worktree_root=root / "beta")

    assert first == root / "alpha" / ".protokflow" / "protokflow.db"
    assert second == root / "beta" / ".protokflow" / "protokflow.db"
    assert first != second


def test_create_database_path_rejects_url_reserved_characters(
    isolated_database_environment: Path,
) -> None:
    with pytest.raises(ValueError, match="URL-reserved"):
        create_database_path(worktree_root=isolated_database_environment / "wt?x")


def test_database_url_round_trips_inside_the_worktree_root(
    isolated_database_environment: Path,
) -> None:
    root = isolated_database_environment / "wt #3 %round-trip"
    url = create_database_url(worktree_root=root)
    expected = (root / ".protokflow" / "protokflow.db").resolve()

    assert db.database_path_from_url(url) == expected


def test_database_url_override_takes_precedence_over_worktree_root(
    isolated_database_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = isolated_database_environment
    override = f"sqlite+aiosqlite:///{root / 'override' / 'custom.db'}"
    monkeypatch.setenv("PROTOKFLOW_DATABASE_URL", override)

    assert db.resolve_database_url(worktree_root=root) == override
    assert db.database_path_from_url(override) == root / "override" / "custom.db"


def test_database_path_from_url_requires_a_file_backed_url() -> None:
    with pytest.raises(ValueError, match="file-backed SQLite"):
        db.database_path_from_url("sqlite+aiosqlite:///:memory:")


def test_database_path_from_url_rejects_uri_memory_and_relative_urls() -> None:
    uri_memory = "sqlite+aiosqlite:///file:pfmem?mode=memory&cache=shared&uri=true"

    with pytest.raises(ValueError, match="file-backed SQLite"):
        db.database_path_from_url(uri_memory)
    with pytest.raises(ValueError, match="file-backed SQLite"):
        db.database_path_from_url("sqlite+aiosqlite:///relative/path.db")


def test_database_path_from_url_ignores_the_url_query(
    isolated_database_environment: Path,
) -> None:
    root = isolated_database_environment
    url = f"sqlite+aiosqlite:///{root / 'queried.db'}?mode=ro"

    assert db.database_path_from_url(url) == root / "queried.db"


async def test_initialize_database_migrates_and_applies_owner_only_permissions(
    isolated_database_environment: Path,
) -> None:
    root = isolated_database_environment
    previous_runtime = db._active_runtime
    engine: AsyncEngine | None = None
    try:
        engine = await db.initialize_database(worktree_root=root)
        database_path = root / ".protokflow" / "protokflow.db"

        assert database_path.exists()
        assert database_path.parent.stat().st_mode & 0o777 == 0o700
        assert database_path.stat().st_mode & 0o777 == 0o600
        revision_url = async_sqlite_url(database_path.resolve())
        assert current_revision(revision_url) == head_revision()
        assert db._get_active_engine() is engine

        async with db.async_db_session() as session:
            assert await session.scalar(text("SELECT 1")) == 1
    finally:
        created = (engine,) if engine is not None else ()
        await _restore_active_slots(previous_runtime, *created)


async def test_reinitialization_disposes_previous_engine(
    isolated_database_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = isolated_database_environment
    previous_runtime = db._active_runtime
    second: AsyncEngine | None = None
    try:
        first = await db.initialize_database(worktree_root=root / "first")
        dispose_calls: list[AsyncEngine] = []
        original_dispose = AsyncEngine.dispose

        async def dispose_probe(engine: AsyncEngine) -> None:
            dispose_calls.append(engine)
            await original_dispose(engine)

        monkeypatch.setattr(AsyncEngine, "dispose", dispose_probe)
        second = await db.initialize_database(worktree_root=root / "second")

        assert db._get_active_engine() is second
        assert db._get_active_engine() is not first
        assert dispose_calls == [first]
    finally:
        created = (second,) if second is not None else ()
        await _restore_active_slots(previous_runtime, *created)


async def test_concurrent_initialization_publishes_one_consistent_runtime(
    isolated_database_environment: Path,
) -> None:
    root = isolated_database_environment
    previous_runtime = db._active_runtime
    created: list[AsyncEngine] = []
    try:
        engines = await asyncio.gather(
            db.initialize_database(worktree_root=root / "left"),
            db.initialize_database(worktree_root=root / "right"),
        )
        created.extend(engines)
        runtime = db._active_runtime

        assert runtime is not None
        assert runtime.engine in engines
        assert runtime.factory is not None
        assert runtime.factory.kw["bind"] is runtime.engine
    finally:
        await _restore_active_slots(previous_runtime, *created)


async def test_engine_and_factory_access_before_initialization_errors() -> None:
    previous_runtime = db._active_runtime
    db._set_engine_for_testing(None)
    db._set_factory_for_testing(None)
    try:
        with pytest.raises(RuntimeError, match="not initialized"):
            db._get_active_engine()
        with pytest.raises(RuntimeError, match="not initialized"):
            db._get_active_factory()
        with pytest.raises(RuntimeError, match="not initialized"):
            db.async_db_session()
    finally:
        await _restore_active_slots(previous_runtime)


async def test_factory_is_exposed_only_after_migration_completes(
    isolated_database_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = isolated_database_environment
    previous_runtime = db._active_runtime
    replacement: AsyncEngine | None = None
    try:
        await db.initialize_database(worktree_root=root / "prepared")
        prepared_engine = db._get_active_engine()
        engine_during_migration: list[object] = []
        original_upgrade = db.upgrade_database

        def upgrade_probe(url: str) -> None:
            active = db._active_runtime
            engine_during_migration.append(active.engine if active else None)
            original_upgrade(url)

        monkeypatch.setattr(db, "upgrade_database", upgrade_probe)
        replacement = await db.initialize_database(worktree_root=root / "reinit")

        assert engine_during_migration == [prepared_engine]
        assert db._get_active_engine() is replacement
        assert db._get_active_engine() is not prepared_engine
    finally:
        created = (replacement,) if replacement is not None else ()
        await _restore_active_slots(previous_runtime, *created)


async def test_register_init_lifespan_initializes_and_disposes_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The FastAPI lifespan initializes the database and disposes it on exit."""
    monkeypatch.delenv("PROTOKFLOW_HOME", raising=False)
    monkeypatch.delenv("PROTOKFLOW_DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    previous_runtime = db._active_runtime
    db._set_engine_for_testing(None)
    db._set_factory_for_testing(None)
    dispose_calls: list[AsyncEngine] = []
    original_dispose = AsyncEngine.dispose

    async def dispose_probe(engine: AsyncEngine) -> None:
        dispose_calls.append(engine)
        await original_dispose(engine)

    monkeypatch.setattr(AsyncEngine, "dispose", dispose_probe)
    created: list[AsyncEngine] = []
    try:
        async with register_init(FastAPI()):
            engine = db._get_active_engine()
            created.append(engine)
            database_path = tmp_path / ".protokflow" / "protokflow.db"

            assert database_path.exists()
            revision_url = async_sqlite_url(database_path)
            assert current_revision(revision_url) == head_revision()

        assert db._active_runtime is None
        assert dispose_calls == [engine]
    finally:
        await _restore_active_slots(previous_runtime, *created)

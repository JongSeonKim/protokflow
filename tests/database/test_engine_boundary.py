"""Tests for the explicit worktree-bound database initialization boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.database import db
from backend.database.migrate import current_revision, head_revision
from backend.database.url import create_database_path
from tests.support.db import async_sqlite_url


async def _restore_active_slots(
    previous_engine: AsyncEngine | None,
    previous_factory: Any,
    *created: AsyncEngine,
) -> None:
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
    previous_engine = db._active_engine
    previous_factory = db._active_factory
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
        await _restore_active_slots(previous_engine, previous_factory, *created)


async def test_reinitialization_disposes_previous_engine(
    isolated_database_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = isolated_database_environment
    previous_engine = db._active_engine
    previous_factory = db._active_factory
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
        await _restore_active_slots(previous_engine, previous_factory, *created)


async def test_engine_and_factory_access_before_initialization_errors() -> None:
    previous_engine = db._active_engine
    previous_factory = db._active_factory
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
        await _restore_active_slots(previous_engine, previous_factory)


async def test_factory_is_exposed_only_after_migration_completes(
    isolated_database_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = isolated_database_environment
    previous_engine = db._active_engine
    previous_factory = db._active_factory
    replacement: AsyncEngine | None = None
    try:
        await db.initialize_database(worktree_root=root / "prepared")
        prepared_engine = db._get_active_engine()
        engine_during_migration: list[object] = []
        original_upgrade = db.upgrade_database

        def upgrade_probe(url: str) -> None:
            engine_during_migration.append(db._active_engine)
            original_upgrade(url)

        monkeypatch.setattr(db, "upgrade_database", upgrade_probe)
        replacement = await db.initialize_database(worktree_root=root / "reinit")

        assert engine_during_migration == [prepared_engine]
        assert db._get_active_engine() is replacement
        assert db._get_active_engine() is not prepared_engine
    finally:
        created = (replacement,) if replacement is not None else ()
        await _restore_active_slots(previous_engine, previous_factory, *created)

"""Contract tests for the shared isolated database fixture stack."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.protokflow.model import DesignSystem
from backend.database import db
from backend.database.db import async_db_session as imported_async_db_session
from tests.support import db as db_fixtures
from tests.support.db import table_names


STORAGE_TABLES = {
    "candidates",
    "design_systems",
    "design_tokens",
    "exports",
    "prototype_runs",
    "slot_contents",
    "token_patches",
}


async def test_test_db_creates_all_storage_tables(test_db: AsyncSession) -> None:
    tables = await test_db.connection()
    names = await tables.run_sync(table_names)

    assert STORAGE_TABLES <= set(names)


async def test_test_db_rows_do_not_leak_between_tests(test_db: object) -> None:
    del test_db
    async with db.async_db_session.begin() as session:
        session.add(DesignSystem(slug="fixture-isolation", title="Fixture isolation"))

    async with imported_async_db_session() as session:
        rows = (await session.scalars(select(DesignSystem).limit(2))).all()

    assert len(rows) == 1
    assert rows[0].slug == "fixture-isolation"


async def test_test_db_starts_clean_after_previous_test(test_db: object) -> None:
    del test_db
    async with imported_async_db_session() as session:
        row = await session.scalar(select(DesignSystem.id).limit(1))

    assert row is None


def test_test_database_path_guard_accepts_worker_and_serial_paths() -> None:
    home = Path("/tmp/protokflow-test-home").resolve()

    db_fixtures.validate_test_database_path(
        home / "protokflow_test_r12345678.db", home=home
    )
    db_fixtures.validate_test_database_path(
        home / "protokflow_test_r12345678_gw2.db", home=home
    )


@pytest.mark.parametrize(
    "path",
    [
        Path("/tmp/protokflow-test-home/protokflow.db"),
        Path("/tmp/protokflow-test-home/protokflow_test.db"),
        Path("/tmp/other-home/protokflow_test_r12345678.db"),
    ],
)
def test_test_database_path_guard_rejects_invalid_names_or_home(
    path: Path,
) -> None:
    home = Path("/tmp/protokflow-test-home").resolve()

    with pytest.raises(RuntimeError, match="test database"):
        db_fixtures.validate_test_database_path(path.resolve(), home=home)


async def test_test_engine_path_uses_isolated_home_and_name(
    test_engine: object,
) -> None:
    del test_engine
    path = db.create_database_path(unittest=True)
    assert path.name.startswith("protokflow_test_")
    assert path.parent == Path(os.environ["PROTOKFLOW_HOME"]).resolve()


def test_database_cleanup_removes_db_and_sqlite_sidecars(tmp_path: Path) -> None:
    path = tmp_path / "protokflow_test_r12345678.db"
    for candidate in db_fixtures.database_sidecar_paths(path):
        candidate.touch()

    db_fixtures.cleanup_database_files(path)

    assert all(
        not candidate.exists() for candidate in db_fixtures.database_sidecar_paths(path)
    )


async def test_factory_proxy_begin_and_import_binding_use_test_engine(
    test_db: object,
) -> None:
    del test_db
    async with imported_async_db_session.begin() as session:
        session.add(DesignSystem(slug="proxy-route", title="Proxy route"))

    async with db.async_db_session() as session:
        row = await session.scalar(
            select(DesignSystem).where(DesignSystem.slug == "proxy-route")
        )
        schema_version = await session.scalar(text("PRAGMA user_version"))

    assert row is not None
    assert schema_version == db.EXPECTED_SCHEMA_VERSION

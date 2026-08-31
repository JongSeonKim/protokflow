"""Regression tests for Alembic migrations and model metadata consistency.

These tests are the regression detector for every future schema change: the
migration chain must stay structurally identical to the model metadata.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.util.exc import CommandError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from backend.app.protokflow import model as _protokflow_model  # noqa: F401
from backend.common.model import MappedBase
from backend.database.migrate import (
    current_revision,
    downgrade_database,
    head_revision,
    upgrade_database,
)
from backend.database.url import to_sync_url
from tests.support.db import async_sqlite_url

MODEL_TABLES = {table.name for table in MappedBase.metadata.sorted_tables}

_AUTOCOMPARE_OPTS = {
    "compare_type": True,
    "compare_server_default": True,
    "render_as_batch": True,
}

_INSERT_TOKEN_SQL = text(
    "INSERT INTO design_tokens (id, design_system_id, tier, token_path, "
    "value, origin, created_time) VALUES (:id, :design_system_id, :tier, "
    ":token_path, :value, :origin, :created_time)"
)


def _url(path: Path) -> str:
    return to_sync_url(async_sqlite_url(path.resolve()))


def _schema_signature(path: Path) -> dict[str, dict[str, Any]]:
    engine = create_engine(_url(path))
    try:
        inspector = inspect(engine)
        return {
            name: {
                "columns": sorted(
                    column["name"] for column in inspector.get_columns(name)
                ),
                "primary_key": sorted(
                    inspector.get_pk_constraint(name)["constrained_columns"]
                ),
                "indexes": sorted(
                    index["name"] for index in inspector.get_indexes(name)
                ),
                "unique_indexes": sorted(
                    index["name"]
                    for index in inspector.get_indexes(name)
                    if index["unique"]
                ),
                "foreign_keys": sorted(
                    (
                        foreign_key["referred_table"],
                        tuple(foreign_key["referred_columns"]),
                        tuple(foreign_key["constrained_columns"]),
                    )
                    for foreign_key in inspector.get_foreign_keys(name)
                ),
                "checks": sorted(
                    (check["name"], check["sqltext"])
                    for check in inspector.get_check_constraints(name)
                ),
            }
            for name in sorted(inspector.get_table_names())
        }
    finally:
        engine.dispose()


def _assert_matches_model_metadata(path: Path) -> None:
    engine = create_engine(_url(path))
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts=_AUTOCOMPARE_OPTS)
            diff = compare_metadata(context, MappedBase.metadata)
    finally:
        engine.dispose()
    assert diff == []


def test_fresh_database_upgrade_creates_schema_and_records_head(
    tmp_path: Path,
) -> None:
    path = tmp_path / "fresh.db"
    upgrade_database(_url(path))
    signature = _schema_signature(path)

    assert MODEL_TABLES <= set(signature)
    assert "alembic_version" in signature
    assert current_revision(_url(path)) == head_revision()


def test_upgrade_adopts_legacy_create_all_database(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    engine = create_engine(_url(path))
    try:
        MappedBase.metadata.create_all(engine)
    finally:
        engine.dispose()

    upgrade_database(_url(path))

    assert current_revision(_url(path)) == head_revision()
    _assert_matches_model_metadata(path)


def test_upgrade_head_is_idempotent_on_migrated_database(tmp_path: Path) -> None:
    path = tmp_path / "idempotent.db"
    upgrade_database(_url(path))
    before = _schema_signature(path)
    upgrade_database(_url(path))

    assert _schema_signature(path) == before
    assert current_revision(_url(path)) == head_revision()


def test_migrated_schema_matches_model_metadata(tmp_path: Path) -> None:
    path = tmp_path / "autocompare.db"
    upgrade_database(_url(path))

    _assert_matches_model_metadata(path)


def test_migrated_and_metadata_schemas_are_structurally_identical(
    tmp_path: Path,
) -> None:
    migrated_path = tmp_path / "migrated.db"
    metadata_path = tmp_path / "metadata.db"
    upgrade_database(_url(migrated_path))

    engine = create_engine(_url(metadata_path))
    try:
        MappedBase.metadata.create_all(engine)
    finally:
        engine.dispose()

    migrated_signature = _schema_signature(migrated_path)
    migrated_signature.pop("alembic_version")
    assert migrated_signature == _schema_signature(metadata_path)


def test_schema_signature_captures_check_constraints(tmp_path: Path) -> None:
    path = tmp_path / "check-signature.db"
    upgrade_database(_url(path))
    checks = dict(_schema_signature(path)["design_tokens"]["checks"])

    assert set(checks) >= {"ck_design_tokens_origin", "ck_design_tokens_tier"}


def test_check_constraints_reject_invalid_enum_values(tmp_path: Path) -> None:
    path = tmp_path / "check-values.db"
    upgrade_database(_url(path))
    params = {
        "id": "0" * 26,
        "design_system_id": "1" * 26,
        "tier": "foundation",
        "token_path": "colors.primary",
        "value": "#ffffff",
        "origin": "design_md",
        "created_time": "2026-08-30 00:00:00+00:00",
    }
    engine = create_engine(_url(path))
    try:
        with engine.begin() as connection:
            connection.execute(_INSERT_TOKEN_SQL, params)
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(_INSERT_TOKEN_SQL, {**params, "tier": "bogus"})
    finally:
        engine.dispose()


def test_upgrade_succeeds_when_path_contains_percent(tmp_path: Path) -> None:
    directory = tmp_path / "wt%dir"
    directory.mkdir()
    path = directory / "percent.db"

    upgrade_database(_url(path))

    assert current_revision(_url(path)) == head_revision()


def test_unregistered_revision_is_rejected_with_explicit_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "future.db"
    engine = create_engine(_url(path))
    try:
        with engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            )
            connection.execute(text("INSERT INTO alembic_version VALUES ('deadbeef')"))
    finally:
        engine.dispose()

    with pytest.raises(CommandError, match="deadbeef"):
        upgrade_database(_url(path))


def test_downgrade_base_removes_every_schema_element(tmp_path: Path) -> None:
    path = tmp_path / "downgraded.db"
    upgrade_database(_url(path))
    downgrade_database(_url(path))

    engine = create_engine(_url(path))
    try:
        names = inspect(engine).get_table_names()
    finally:
        engine.dispose()
    assert names == []


def test_current_revision_of_unversioned_database_is_none(tmp_path: Path) -> None:
    path = tmp_path / "unversioned.db"
    path.touch()

    assert current_revision(_url(path)) is None


def test_current_revision_of_empty_version_table_is_none(tmp_path: Path) -> None:
    path = tmp_path / "empty-version.db"
    upgrade_database(_url(path))
    engine = create_engine(_url(path))
    try:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM alembic_version"))
    finally:
        engine.dispose()

    assert current_revision(_url(path)) is None

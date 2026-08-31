"""Programmatic Alembic migration entry points for worktree databases.

All entry points execute against a synchronous SQLite URL so callers can run
them from a worker thread outside the async event loop.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from backend.common.model import MappedBase
from backend.database.url import to_sync_url

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _escape_config_value(value: str) -> str:
    """Escape percent signs so ConfigParser interpolation cannot abort."""
    return value.replace("%", "%%")


def _migration_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", _escape_config_value(str(MIGRATIONS_DIR)))
    config.set_main_option("sqlalchemy.url", _escape_config_value(to_sync_url(url)))
    return config


def upgrade_database(url: str, *, revision: str = "head") -> None:
    """
    Upgrade the database at ``url`` to ``revision``

     Databases created by the legacy ``create_all`` path carry model tables but
     no ``alembic_version`` row; they are stamped to the target revision so the
     first upgrade adopts them instead of failing on existing tables.

     :param url: sync or async SQLite connection URL
     :param revision: target revision, defaults to the chain head
     :return:
    """
    config = _migration_config(url)
    _adopt_legacy_database(url, config, revision)
    command.upgrade(config, revision)


def _adopt_legacy_database(url: str, config: Config, revision: str) -> None:
    """Stamp legacy ``create_all`` databases so migrations can adopt them."""
    if current_revision(url) is not None:
        return
    if not _has_model_tables(url):
        return
    command.stamp(config, revision)


def _has_model_tables(url: str) -> bool:
    """Check whether any model table already exists in the database."""
    engine = create_engine(to_sync_url(url))
    try:
        existing = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    model_tables = {table.name for table in MappedBase.metadata.sorted_tables}
    return bool(existing & model_tables)


def downgrade_database(url: str, *, revision: str = "base") -> None:
    """
    Downgrade the database at ``url`` to ``revision``

    :param url: sync or async SQLite connection URL
    :param revision: target revision, defaults to the chain base
    :return:
    """
    command.downgrade(_migration_config(url), revision)
    if revision == "base":
        _drop_version_table(url)


def _drop_version_table(url: str) -> None:
    engine = create_engine(to_sync_url(url))
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    finally:
        engine.dispose()


def current_revision(url: str) -> str | None:
    """
    Return the recorded Alembic revision of the database

    :param url: sync or async SQLite connection URL
    :return:
    """
    engine = create_engine(to_sync_url(url))
    try:
        try:
            with engine.connect() as connection:
                return connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
        except OperationalError as err:
            if "no such table: alembic_version" not in str(err):
                raise
            return None
    finally:
        engine.dispose()


def head_revision() -> str:
    """
    Return the head revision of the migration chain

    :return:
    """
    head = ScriptDirectory(str(MIGRATIONS_DIR)).get_current_head()
    if head is None:
        raise RuntimeError("migration chain has no head revision")
    return head

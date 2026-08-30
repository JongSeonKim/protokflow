"""Programmatic Alembic migration entry points for worktree databases.

All entry points execute against a synchronous SQLite URL so callers can run
them from a worker thread outside the async event loop.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from backend.database.url import to_sync_url

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _migration_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", to_sync_url(url))
    return config


def upgrade_database(url: str, *, revision: str = "head") -> None:
    """
    Upgrade the database at ``url`` to ``revision``

    :param url: sync or async SQLite connection URL
    :param revision: target revision, defaults to the chain head
    :return:
    """
    command.upgrade(_migration_config(url), revision)


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
                ).scalar_one()
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

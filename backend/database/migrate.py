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

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _to_sync_url(url: str) -> str:
    """Normalize an async SQLite URL to the synchronous dialect."""
    return url.replace("sqlite+aiosqlite://", "sqlite://", 1)


def _migration_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", _to_sync_url(url))
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
    engine = create_engine(_to_sync_url(url))
    try:
        with engine.begin() as connection:
            if inspect(connection).has_table("alembic_version"):
                connection.execute(text("DROP TABLE alembic_version"))
    finally:
        engine.dispose()


def current_revision(url: str) -> str | None:
    """
    Return the recorded Alembic revision of the database

    :param url: sync or async SQLite connection URL
    :return:
    """
    engine = create_engine(_to_sync_url(url))
    try:
        with engine.connect() as connection:
            if not inspect(connection).has_table("alembic_version"):
                return None
            return connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
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

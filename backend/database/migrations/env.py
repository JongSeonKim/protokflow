"""Alembic migration environment for the worktree SQLite database."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from alembic import context
from alembic.config import Config
from alembic.util.exc import CommandError
from sqlalchemy import engine_from_config, pool

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.app.protokflow import model as _protokflow_model  # noqa: E402, F401
from backend.common.model import MappedBase  # noqa: E402
from backend.database.url import to_sync_url  # noqa: E402

config = context.config

target_metadata = MappedBase.metadata


def _resolve_database_url(config: Config) -> str:
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        url = os.environ.get("PROTOKFLOW_DATABASE_URL")
    if not url:
        raise CommandError(
            "database URL must be injected via backend.database.migrate or "
            "PROTOKFLOW_DATABASE_URL"
        )
    return to_sync_url(url)


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live database connection."""
    context.configure(
        url=_resolve_database_url(config),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live synchronous SQLite connection."""
    section: dict[str, Any] = dict(config.get_section(config.config_ini_section) or {})
    section["sqlalchemy.url"] = _resolve_database_url(config)
    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

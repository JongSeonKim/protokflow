"""Tests for the ORM persistence adapter.

The store maps parsed snapshots onto rows of a session its caller owns. The
two invariants the whole storage boundary rests on -- it never commits that
session, and a caller-owned rollback discards everything it wrote -- are
asserted here directly.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.protokflow.core.discovery import DiscoveredDesignFile
from backend.app.protokflow.crud.crud_design_system import design_system_dao
from backend.app.protokflow.crud.crud_design_token import design_token_dao
from backend.app.protokflow.error.storage import (
    TokenReparentingError,
    UnknownDesignSystemError,
)
from backend.app.protokflow.model import DesignSystem
from backend.app.protokflow.storage.design_source import (
    DesignSourceSnapshot,
    SourceMetadata,
    parse_design_file,
)
from backend.app.protokflow.storage.design_system_store import (
    build_design_system,
    build_design_tokens,
    refresh_source_metadata,
    sync_source_snapshot,
)
from backend.database import db

_DESIGN_MD = (
    "---\n"
    "name: Default\n"
    "description: A calm, high-contrast system.\n"
    "version: '1'\n"
    "colors:\n"
    "  primary: '#111111'\n"
    "  secondary: '#222222'\n"
    "---\n"
    "# Guide\n"
)


def _snapshot(tmp_path: Path, text: str = _DESIGN_MD) -> DesignSourceSnapshot:
    """Parse a DESIGN.md fixture into the snapshot the store consumes."""
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_bytes(text.encode("utf-8"))
    return parse_design_file(
        tmp_path, DiscoveredDesignFile(slug="default", path=design_md_path)
    )


@contextmanager
def _commit_recorder(session: AsyncSession) -> Iterator[list[str]]:
    """Record commits and rollbacks issued on a session, in order."""
    events: list[str] = []
    sync_session = session.sync_session
    handlers: dict[str, Callable[..., Any]] = {
        "after_commit": lambda _session: events.append("commit"),
        "after_soft_rollback": lambda _session, _tx: events.append("rollback"),
    }
    for name, handler in handlers.items():
        event.listen(sync_session, name, handler)
    try:
        yield events
    finally:
        for name, handler in handlers.items():
            event.remove(sync_session, name, handler)


async def _tokens_of(slug: str) -> dict[str, str]:
    """Read the committed token set of a slug through a fresh session."""
    async with db.async_db_session() as session:
        system = await design_system_dao.get_by_slug(session, slug)
        assert system is not None
        tokens = await design_token_dao.get_all(session, system.id)
        return {token.token_path: token.value for token in tokens}


async def test_sync_source_snapshot_creates_the_system_and_its_tokens(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """A first sync inserts the design system row and its full token set."""
    del test_db
    snapshot = _snapshot(tmp_path)

    async with db.async_db_session.begin() as session:
        system = await sync_source_snapshot(session, snapshot)
        system_id = system.id

    async with db.async_db_session() as session:
        stored = await design_system_dao.get_by_slug(session, "default")
        assert stored is not None
        assert stored.id == system_id
        assert stored.title == "Default"
        assert stored.source_path == "DESIGN.md"
        assert stored.source_root == tmp_path.as_posix()
        assert stored.source_digest == snapshot.source_digest
        assert stored.source_mtime_ns == snapshot.source_mtime_ns
        assert stored.source_size == snapshot.source_size
        assert stored.synced_at is not None
    assert await _tokens_of("default") == {
        "colors.primary": "#111111",
        "colors.secondary": "#222222",
    }


async def test_resyncing_replaces_the_token_set_without_duplication(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """A second sync upserts the same row and leaves no stale token behind."""
    del test_db
    async with db.async_db_session.begin() as session:
        first = await sync_source_snapshot(session, _snapshot(tmp_path))
        first_id = first.id

    changed = _DESIGN_MD.replace("  secondary: '#222222'\n", "  accent: '#333333'\n")
    async with db.async_db_session.begin() as session:
        second = await sync_source_snapshot(session, _snapshot(tmp_path, changed))

    assert second.id == first_id
    assert await _tokens_of("default") == {
        "colors.primary": "#111111",
        "colors.accent": "#333333",
    }


async def test_sync_source_snapshot_preserves_provenance(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """A file-driven sync owns file-derived columns only."""
    del test_db
    async with db.async_db_session.begin() as session:
        parent = await design_system_dao.create(
            session, DesignSystem(slug="parent", title="Parent")
        )
        system = await sync_source_snapshot(session, _snapshot(tmp_path))
        system.derived_from_id = parent.id
        parent_id = parent.id

    async with db.async_db_session.begin() as session:
        await sync_source_snapshot(session, _snapshot(tmp_path))

    async with db.async_db_session() as session:
        stored = await design_system_dao.get_by_slug(session, "default")
        assert stored is not None
        assert stored.derived_from_id == parent_id


async def test_refresh_source_metadata_touches_only_the_stat_columns(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """A touch-only refresh moves mtime and size and nothing else."""
    del test_db
    snapshot = _snapshot(tmp_path)
    async with db.async_db_session.begin() as session:
        stored = await sync_source_snapshot(session, snapshot)
        before = (stored.id, stored.title, stored.source_digest, stored.synced_at)

    async with db.async_db_session.begin() as session:
        await refresh_source_metadata(
            session,
            "default",
            SourceMetadata(
                source_digest=snapshot.source_digest,
                source_mtime_ns=snapshot.source_mtime_ns + 1_000_000_000,
                source_size=snapshot.source_size,
            ),
        )

    async with db.async_db_session() as session:
        refreshed = await design_system_dao.get_by_slug(session, "default")
        assert refreshed is not None
        assert (
            refreshed.id,
            refreshed.title,
            refreshed.source_digest,
            refreshed.synced_at,
        ) == before
        assert refreshed.source_mtime_ns == snapshot.source_mtime_ns + 1_000_000_000
        assert refreshed.source_size == snapshot.source_size


async def test_refresh_source_metadata_rejects_a_slug_deleted_mid_reconcile(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """Refreshing a row that vanished surfaces rather than recreating it."""
    del test_db
    snapshot = _snapshot(tmp_path)

    async with db.async_db_session.begin() as session:
        with pytest.raises(UnknownDesignSystemError, match="was deleted"):
            await refresh_source_metadata(
                session,
                "default",
                SourceMetadata(
                    source_digest=snapshot.source_digest,
                    source_mtime_ns=snapshot.source_mtime_ns,
                    source_size=snapshot.source_size,
                ),
            )


async def test_the_store_never_commits_the_callers_session(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """Transaction boundaries belong to the caller, not to the store."""
    del test_db
    snapshot = _snapshot(tmp_path)

    async with db.async_db_session() as session:
        with _commit_recorder(session) as events:
            await sync_source_snapshot(session, snapshot)
            await refresh_source_metadata(
                session,
                "default",
                SourceMetadata(
                    source_digest=snapshot.source_digest,
                    source_mtime_ns=snapshot.source_mtime_ns + 1,
                    source_size=snapshot.source_size,
                ),
            )

            assert events == []
            await session.rollback()
            assert events == ["rollback"]

    async with db.async_db_session() as session:
        assert await design_system_dao.get_by_slug(session, "default") is None


async def test_a_caller_owned_rollback_discards_every_store_write(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """Rolling back the caller's transaction leaves no system and no token."""
    del test_db
    snapshot = _snapshot(tmp_path)

    async with db.async_db_session() as session:
        system = await sync_source_snapshot(session, snapshot)
        system_id = system.id
        await session.rollback()

    async with db.async_db_session() as session:
        assert await design_system_dao.get_by_slug(session, "default") is None
        assert list(await design_token_dao.get_all(session, system_id)) == []


async def test_a_caller_owned_rollback_discards_a_metadata_refresh(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """The touch-only path is transactional on the caller's session too."""
    del test_db
    snapshot = _snapshot(tmp_path)
    async with db.async_db_session.begin() as session:
        await sync_source_snapshot(session, snapshot)

    async with db.async_db_session() as session:
        await refresh_source_metadata(
            session,
            "default",
            SourceMetadata(
                source_digest=snapshot.source_digest,
                source_mtime_ns=snapshot.source_mtime_ns + 1_000_000_000,
                source_size=snapshot.source_size + 7,
            ),
        )
        await session.rollback()

    async with db.async_db_session() as session:
        stored = await design_system_dao.get_by_slug(session, "default")
        assert stored is not None
        assert stored.source_mtime_ns == snapshot.source_mtime_ns
        assert stored.source_size == snapshot.source_size


async def test_build_design_system_maps_the_snapshot_without_touching_the_database(
    tmp_path: Path,
) -> None:
    """Model building is pure: no session is involved."""
    snapshot = _snapshot(tmp_path)

    system = build_design_system(snapshot)

    assert system.slug == "default"
    assert system.title == "Default"
    assert system.description == "A calm, high-contrast system."
    assert system.spec_version == "1"
    assert system.source_path == "DESIGN.md"
    assert system.source_digest == snapshot.source_digest


def test_build_design_system_falls_back_to_the_slug_for_an_untitled_source(
    tmp_path: Path,
) -> None:
    """A source without a front-matter name is titled by its slug."""
    untitled = _DESIGN_MD.replace("name: Default\n", "")

    system = build_design_system(_snapshot(tmp_path, untitled))

    assert system.title == "default"


def test_build_design_tokens_parents_every_row_to_the_given_system(
    tmp_path: Path,
) -> None:
    """Every built row names the design system it was built for."""
    tokens = build_design_tokens(_snapshot(tmp_path), "01ARZ3NDEKTSV4RRFFQ69G5FAV")

    assert [token.design_system_id for token in tokens] == [
        "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "01ARZ3NDEKTSV4RRFFQ69G5FAV",
    ]
    assert [token.token_path for token in tokens] == [
        "colors.primary",
        "colors.secondary",
    ]


async def test_token_replacement_rejects_rows_owned_by_another_system(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """Reparenting is refused before the existing token set is deleted."""
    del test_db
    snapshot = _snapshot(tmp_path)
    async with db.async_db_session.begin() as session:
        owner = await sync_source_snapshot(session, snapshot)
        other = await design_system_dao.create(
            session, DesignSystem(slug="other", title="Other")
        )
        owner_id, other_id = owner.id, other.id

    foreign_tokens = build_design_tokens(snapshot, owner_id)
    async with db.async_db_session.begin() as session:
        with pytest.raises(TokenReparentingError, match="colors.primary"):
            await design_token_dao.replace(session, other_id, foreign_tokens)

    assert await _tokens_of("default") == {
        "colors.primary": "#111111",
        "colors.secondary": "#222222",
    }


async def test_token_replacement_accepts_rows_owned_by_the_target_system(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """The positive counterpart: correctly parented rows replace the set."""
    del test_db
    snapshot = _snapshot(tmp_path)
    async with db.async_db_session.begin() as session:
        owner = await sync_source_snapshot(session, snapshot)
        owner_id = owner.id

    changed = _snapshot(tmp_path, _DESIGN_MD.replace("#222222", "#333333"))
    async with db.async_db_session.begin() as session:
        replaced = await design_token_dao.replace(
            session, owner_id, build_design_tokens(changed, owner_id)
        )

    assert len(replaced) == 2
    assert await _tokens_of("default") == {
        "colors.primary": "#111111",
        "colors.secondary": "#333333",
    }

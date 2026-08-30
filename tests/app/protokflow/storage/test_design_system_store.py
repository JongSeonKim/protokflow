import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.protokflow.core.design_md import parse_design_md
from backend.app.protokflow.crud.crud_design_system import design_system_dao
from backend.app.protokflow.crud.crud_design_token import design_token_dao
from backend.app.protokflow.error.storage import TokenReparentingError
from backend.app.protokflow.model import DesignSystem, DesignToken
from backend.app.protokflow.storage.design_source import (  # type: ignore[import-untyped,import-not-found]
    DesignSourceSnapshot,
    SourceMetadata,
)
from backend.app.protokflow.storage.design_system_store import (  # type: ignore[import-untyped,import-not-found]
    build_design_tokens,
    refresh_source_metadata,
    sync_source_snapshot,
)


def _snapshot(*, color: str, token_name: str = "primary") -> DesignSourceSnapshot:
    content = (
        "---\n"
        "name: Default\n"
        "description: A test system\n"
        "version: '1'\n"
        "colors:\n"
        f"  {token_name}: '{color}'\n"
        "---\n"
        "# Guide\n"
    )
    return DesignSourceSnapshot(
        slug="default",
        source_root="/repo",
        source_path="DESIGN.md",
        source_digest=f"digest-{color}-{token_name}",
        source_mtime_ns=100,
        source_size=len(content),
        parsed=parse_design_md(content),
    )


async def test_sync_source_snapshot_replaces_the_complete_token_set(
    test_db: AsyncSession,
) -> None:
    first = await sync_source_snapshot(test_db, _snapshot(color="#111111"))
    replacement = _snapshot(color="#222222", token_name="secondary")

    synced = await sync_source_snapshot(test_db, replacement, existing=first)

    assert synced.id == first.id
    assert [
        (token.token_path, token.value)
        for token in await design_token_dao.get_all(test_db, synced.id)
    ] == [("colors.secondary", "#222222")]
    assert list(await test_db.scalars(select(DesignSystem))) == [synced]


async def test_refresh_source_metadata_changes_only_source_stat_fields(
    test_db: AsyncSession,
) -> None:
    snapshot = _snapshot(color="#111111")
    system = await sync_source_snapshot(test_db, snapshot)
    original = (
        system.source_digest,
        system.title,
        system.description,
        system.source_root,
        system.source_path,
        system.synced_at,
    )

    refreshed = await refresh_source_metadata(
        test_db,
        system.slug,
        SourceMetadata(
            source_digest="unchanged-digest-is-not-persisted",
            source_mtime_ns=200,
            source_size=300,
        ),
    )

    assert refreshed.source_mtime_ns == 200
    assert refreshed.source_size == 300
    assert (
        refreshed.source_digest,
        refreshed.title,
        refreshed.description,
        refreshed.source_root,
        refreshed.source_path,
        refreshed.synced_at,
    ) == original


async def test_store_changes_roll_back_with_the_caller_session(
    test_db: AsyncSession,
) -> None:
    await sync_source_snapshot(test_db, _snapshot(color="#111111"))

    await test_db.rollback()

    assert await design_system_dao.get_by_slug(test_db, "default") is None


async def test_sync_source_snapshot_does_not_commit_the_caller_session(
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_commit() -> None:
        raise AssertionError("store must not commit the caller session")

    monkeypatch.setattr(test_db, "commit", fail_commit)

    system = await sync_source_snapshot(test_db, _snapshot(color="#111111"))

    assert system.slug == "default"
    assert test_db.in_transaction()


def test_build_design_tokens_rejects_mismatched_reparenting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_init = DesignToken.__init__

    def faulty_init(self: DesignToken, *args: object, **kwargs: object) -> None:
        original_init(self, "wrong-system", *args[1:], **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(DesignToken, "__init__", faulty_init)

    with pytest.raises(TokenReparentingError, match="cannot reparent"):
        build_design_tokens(_snapshot(color="#111111"), "system-123")

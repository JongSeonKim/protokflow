"""Tests for design-system CRUD operations."""

from __future__ import annotations

import pytest

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.protokflow.crud.crud_design_system import design_system_dao
from backend.app.protokflow.model import DesignSystem
from tests.support.sentinel import generate_model_sentinels


async def test_upsert_design_system_creates_slug_with_ulid(
    test_db: AsyncSession,
) -> None:
    """Upserting a new slug creates a design system with a 26-char ULID primary key."""
    design_system = DesignSystem(slug="default", title="Default")

    result = await design_system_dao.upsert(test_db, design_system)

    assert result is design_system
    assert len(result.id) == 26
    assert await design_system_dao.get_by_slug(test_db, "default") is result


async def test_upsert_design_system_updates_existing_slug_and_preserves_id(
    test_db: AsyncSession,
) -> None:
    """Upserting an existing slug updates file-driven fields while preserving its primary key."""
    original = await design_system_dao.upsert(
        test_db,
        DesignSystem(
            slug="default",
            title="Old title",
            description="Old description",
            front_matter_raw="name: Old title\n",
        ),
    )
    original_id = original.id

    updated = await design_system_dao.upsert(
        test_db,
        DesignSystem(
            slug="default",
            title="New title",
            description="New description",
            spec_version="1",
            front_matter_raw="name: New title\n",
        ),
    )

    assert updated is original
    assert updated.id == original_id
    assert updated.title == "New title"
    assert updated.description == "New description"
    assert updated.spec_version == "1"
    assert updated.front_matter_raw == "name: New title\n"


async def test_upsert_design_system_preserves_derived_from_id_on_reindex(
    test_db: AsyncSession,
) -> None:
    """Upserting on re-index preserves the derived_from_id provenance pointer."""
    source = await design_system_dao.create(
        test_db, DesignSystem(slug="source", title="Source")
    )
    source_id = source.id
    derived = await design_system_dao.create(
        test_db,
        DesignSystem(slug="derived", title="Derived", derived_from_id=source_id),
    )
    derived_id = derived.id

    await design_system_dao.upsert(
        test_db,
        DesignSystem(slug="derived", title="Re-indexed"),
    )

    test_db.expire_all()
    persisted = await test_db.get(DesignSystem, derived_id)

    assert persisted is not None
    assert persisted.derived_from_id == source_id


async def test_create_design_system_surfaces_duplicate_slug_violation(
    test_db: AsyncSession,
) -> None:
    """Creating two design systems with the same slug raises an IntegrityError."""
    await design_system_dao.create(
        test_db, DesignSystem(slug="duplicate", title="First")
    )

    with pytest.raises(IntegrityError):
        await design_system_dao.create(
            test_db, DesignSystem(slug="duplicate", title="Second")
        )


async def test_deleting_design_system_cascades_to_tokens(test_db: AsyncSession) -> None:
    """Deleting a design system cascades deletion to all its owned design tokens."""
    design_system = await design_system_dao.create(
        test_db, DesignSystem(slug="cascade", title="Cascade")
    )

    from backend.app.protokflow.crud.crud_design_token import design_token_dao
    from backend.app.protokflow.model import DesignToken

    await design_token_dao.replace(
        test_db,
        design_system.id,
        [DesignToken(design_system.id, "foundation", "colors.primary", "#000")],
    )

    await test_db.delete(design_system)
    await test_db.flush()

    assert await test_db.get(DesignSystem, design_system.id) is None
    assert (
        await test_db.scalar(
            select(DesignToken.id).where(
                DesignToken.design_system_id == design_system.id
            )
        )
        is None
    )


async def test_deleting_derived_source_sets_child_reference_null(
    test_db: AsyncSession,
) -> None:
    """Deleting a parent design system sets child derived_from_id references to NULL."""
    source = await design_system_dao.create(
        test_db, DesignSystem(slug="source", title="Source")
    )
    derived = await design_system_dao.create(
        test_db,
        DesignSystem(slug="derived", title="Derived", derived_from_id=source.id),
    )

    await test_db.delete(source)
    await test_db.flush()
    await test_db.refresh(derived)

    assert await test_db.get(DesignSystem, derived.id) is derived
    assert derived.derived_from_id is None


async def test_front_matter_raw_round_trips_comments_and_blank_lines(
    test_db: AsyncSession,
) -> None:
    """Front matter raw text preserves comments, blank lines, and formatting intact."""
    raw = "# heading\n\nname: Default  # inline comment\n\n  # indented comment\n"
    await design_system_dao.create(
        test_db,
        DesignSystem(slug="raw", title="Default", front_matter_raw=raw),
    )

    test_db.expire_all()
    loaded = await design_system_dao.get_by_slug(test_db, "raw")

    assert loaded is not None
    assert loaded.front_matter_raw == raw


async def test_upsert_update_path_persists_every_file_driven_column(
    test_db: AsyncSession,
) -> None:
    """Guard: upsert must persist updates for all file-driven columns to the database."""
    initial = DesignSystem(slug="drift-sentinel", title="Initial Title")
    await design_system_dao.create(test_db, initial)
    test_db.expire_all()

    ownership_excluded = {"id", "slug", "derived_from_id", "unbound_at"}
    file_driven_sentinels = generate_model_sentinels(
        DesignSystem, excluded=ownership_excluded
    )

    assert file_driven_sentinels, "Expected at least one file-driven column to test"

    update_payload = DesignSystem(slug="drift-sentinel", **file_driven_sentinels)
    await design_system_dao.upsert(test_db, update_payload)

    test_db.expire_all()
    persisted = await design_system_dao.get_by_slug(test_db, "drift-sentinel")

    assert persisted is not None
    for col_name, sentinel_val in file_driven_sentinels.items():
        persisted_val = getattr(persisted, col_name)
        assert persisted_val == sentinel_val, (
            f"CRUDDesignSystem.upsert did not persist column {col_name!r}: "
            f"got {persisted_val!r}, expected {sentinel_val!r}. "
            f"If this column is not file-driven, add it to ownership_excluded."
        )


async def test_unbind_orphan_sources_sets_unbound_at_timestamp(
    test_db: AsyncSession,
) -> None:
    """Unbinding orphaned sources stamps unbound_at with the current UTC timestamp."""
    system = await design_system_dao.create(
        test_db,
        DesignSystem(
            slug="orphan",
            title="Orphan",
            source_root="/test/root",
            source_path="orphan.md",
        ),
    )
    assert system.unbound_at is None

    unbound_count = await design_system_dao.unbind_orphan_sources(
        test_db, source_root="/test/root", keep_slugs=[]
    )
    assert unbound_count == 1

    test_db.expire_all()
    loaded = await design_system_dao.get_by_slug(test_db, "orphan")
    assert loaded is not None
    assert loaded.source_path is None
    assert loaded.unbound_at is not None


async def test_upsert_clears_unbound_at_on_reindex(
    test_db: AsyncSession,
) -> None:
    """Re-indexing an unbound design system clears unbound_at back to NULL."""
    await design_system_dao.create(
        test_db,
        DesignSystem(
            slug="rebound",
            title="Rebound",
            source_root="/test/root",
            source_path="rebound.md",
        ),
    )
    await design_system_dao.unbind_orphan_sources(
        test_db, source_root="/test/root", keep_slugs=[]
    )

    test_db.expire_all()
    unbound_system = await design_system_dao.get_by_slug(test_db, "rebound")
    assert unbound_system is not None
    assert unbound_system.unbound_at is not None

    reindexed = await design_system_dao.upsert(
        test_db,
        DesignSystem(
            slug="rebound",
            title="Rebound",
            source_root="/test/root",
            source_path="rebound.md",
        ),
    )
    assert reindexed.unbound_at is None

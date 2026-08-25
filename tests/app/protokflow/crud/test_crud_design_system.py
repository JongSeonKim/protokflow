"""Tests for design-system CRUD operations."""

from __future__ import annotations

import pytest

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.protokflow.crud.crud_design_system import design_system_dao
from backend.app.protokflow.model import DesignSystem


async def test_upsert_design_system_creates_slug_with_ulid(
    test_db: AsyncSession,
) -> None:
    design_system = DesignSystem(slug="default", title="Default")

    result = await design_system_dao.upsert(test_db, design_system)

    assert result is design_system
    assert len(result.id) == 26
    assert await design_system_dao.get_by_slug(test_db, "default") is result


async def test_upsert_design_system_updates_existing_slug_and_preserves_id(
    test_db: AsyncSession,
) -> None:
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
    await design_system_dao.create(
        test_db, DesignSystem(slug="duplicate", title="First")
    )

    with pytest.raises(IntegrityError):
        await design_system_dao.create(
            test_db, DesignSystem(slug="duplicate", title="Second")
        )


async def test_deleting_design_system_cascades_to_tokens(test_db: AsyncSession) -> None:
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
    raw = "# heading\n\nname: Default  # inline comment\n\n  # indented comment\n"
    await design_system_dao.create(
        test_db,
        DesignSystem(slug="raw", title="Default", front_matter_raw=raw),
    )

    test_db.expire_all()
    loaded = await design_system_dao.get_by_slug(test_db, "raw")

    assert loaded is not None
    assert loaded.front_matter_raw == raw

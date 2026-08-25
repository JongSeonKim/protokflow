"""Async SQLAlchemy operations for design systems."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.protokflow.model import DesignSystem


async def get_design_system_by_slug(
    session: AsyncSession, slug: str
) -> DesignSystem | None:
    """Return the design system identified by ``slug``, if it exists."""
    statement = select(DesignSystem).where(DesignSystem.slug == slug)
    return await session.scalar(statement)


async def create_design_system(
    session: AsyncSession, design_system: DesignSystem
) -> DesignSystem:
    """Insert a design system and flush the caller-owned transaction."""
    session.add(design_system)
    await session.flush()
    return design_system


async def upsert_design_system(
    session: AsyncSession, design_system: DesignSystem
) -> DesignSystem:
    """Create or update a design system selected by its unique slug."""
    existing = await get_design_system_by_slug(session, design_system.slug)
    if existing is None:
        return await create_design_system(session, design_system)

    existing.title = design_system.title
    existing.description = design_system.description
    existing.spec_version = design_system.spec_version
    existing.derived_from_id = design_system.derived_from_id
    existing.front_matter_extras = design_system.front_matter_extras
    existing.front_matter_raw = design_system.front_matter_raw
    existing.guide_markdown = design_system.guide_markdown
    existing.source_path = design_system.source_path
    existing.source_digest = design_system.source_digest
    existing.source_mtime_ns = design_system.source_mtime_ns
    existing.source_size = design_system.source_size
    existing.synced_at = design_system.synced_at
    await session.flush()
    return existing

"""CRUD operations for design systems."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.app.protokflow.model import DesignSystem


class CRUDDesignSystem(CRUDPlus[DesignSystem]):
    """Design system CRUD class."""

    async def get_by_slug(self, db: AsyncSession, slug: str) -> DesignSystem | None:
        """
        Get a design system by slug

        :param db: Database session
        :param slug: Unique slug identifier
        :return:
        """
        return await self.select_model_by_column(db, slug=slug)

    async def create(self, db: AsyncSession, obj: DesignSystem) -> DesignSystem:
        """
        Create a design system

        :param db: Database session
        :param obj: Design system instance
        :return:
        """
        db.add(obj)
        await db.flush()

        return obj

    async def upsert(self, db: AsyncSession, obj: DesignSystem) -> DesignSystem:
        """
        Create or update a design system selected by its unique slug

        :param db: Database session
        :param obj: Design system instance carrying the desired state
        File-driven re-index owns file-derived columns only; provenance columns
        (``derived_from_id``) are preserved.
        :return:
        """
        existing = await self.get_by_slug(db, obj.slug)
        if existing is None:
            return await self.create(db, obj)

        existing.title = obj.title
        existing.description = obj.description
        existing.spec_version = obj.spec_version
        existing.front_matter_extras = obj.front_matter_extras
        existing.front_matter_raw = obj.front_matter_raw
        existing.guide_markdown = obj.guide_markdown
        existing.source_path = obj.source_path
        existing.source_root = obj.source_root
        existing.source_digest = obj.source_digest
        existing.source_mtime_ns = obj.source_mtime_ns
        existing.source_size = obj.source_size
        existing.synced_at = obj.synced_at
        await db.flush()

        return existing

    async def delete_orphan_sources(
        self,
        db: AsyncSession,
        *,
        source_root: str,
        keep_slugs: Sequence[str],
    ) -> int:
        """
        Hard-delete file-backed rows of one repository root missing from discovery

        Tokens are removed by the design_tokens foreign key (ON DELETE CASCADE);
        DB-only rows (source_path NULL) and rows bound to other roots are kept.

        :param db: Database session
        :param source_root: Repository root the discovery set belongs to
        :param keep_slugs: Slugs discovered in the current run
        :return: Number of deleted design-system rows
        """
        statement = sa.delete(DesignSystem).where(
            DesignSystem.source_path.is_not(None),
            DesignSystem.source_root == source_root,
        )
        if keep_slugs:
            statement = statement.where(DesignSystem.slug.not_in(keep_slugs))
        result = cast(CursorResult[Any], await db.execute(statement))
        return result.rowcount


design_system_dao: CRUDDesignSystem = CRUDDesignSystem(DesignSystem)

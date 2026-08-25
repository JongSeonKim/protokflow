"""CRUD operations for design systems."""

from __future__ import annotations

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
        :return:
        """
        existing = await self.get_by_slug(db, obj.slug)
        if existing is None:
            return await self.create(db, obj)

        existing.title = obj.title
        existing.description = obj.description
        existing.spec_version = obj.spec_version
        existing.derived_from_id = obj.derived_from_id
        existing.front_matter_extras = obj.front_matter_extras
        existing.front_matter_raw = obj.front_matter_raw
        existing.guide_markdown = obj.guide_markdown
        existing.source_path = obj.source_path
        existing.source_digest = obj.source_digest
        existing.source_mtime_ns = obj.source_mtime_ns
        existing.source_size = obj.source_size
        existing.synced_at = obj.synced_at
        await db.flush()

        return existing


design_system_dao: CRUDDesignSystem = CRUDDesignSystem(DesignSystem)

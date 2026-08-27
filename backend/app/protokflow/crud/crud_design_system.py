"""CRUD operations for design systems."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.app.protokflow.model import DesignSystem
from backend.app.protokflow.model.types import utcnow


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

    async def upsert(
        self,
        db: AsyncSession,
        obj: DesignSystem,
        *,
        existing: DesignSystem | None = None,
    ) -> DesignSystem:
        """
        Create or update a design system selected by its unique slug

        :param db: Database session
        :param obj: Design system instance carrying the desired state
        :param existing: Row already loaded for obj.slug, skipping the lookup
        File-driven re-index owns file-derived columns only; provenance columns
        (``derived_from_id``) are preserved.
        :return:
        """
        if existing is None:
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
        existing.unbound_at = None
        await db.flush()

        return existing

    async def unbind_orphan_sources(
        self,
        db: AsyncSession,
        *,
        source_root: str,
        keep_slugs: Sequence[str],
    ) -> int:
        """
        Clear the source binding of rows of one root missing from discovery

        Only the source_* binding columns and synced_at are cleared, and
        unbound_at is stamped with the current timestamp. An orphaned row
        survives as a DB-only row and a later index run rebinds it by slug
        with its id, tokens and provenance intact while clearing unbound_at.

        Deleting instead would reach far past the file binding it means to
        drop: design_systems.id is referenced by prototype_runs
        (ON DELETE CASCADE, chaining on to candidates, exports, slot_contents
        and token_patches) and by design_systems.derived_from_id
        (ON DELETE SET NULL, silently stripping provenance from derived
        forks). Because token ids are re-issued on every sync, a delete is
        also unrecoverable by re-indexing.

        DB-only rows (source_path NULL) and rows bound to other roots are
        untouched. An empty keep_slugs set unbinds every file-backed row of
        the root — the every-file-deleted path.

        :param db: Database session
        :param source_root: Repository root the discovery set belongs to
        :param keep_slugs: Slugs discovered in the current run
        :return: Number of unbound design-system rows
        """
        statement = (
            sa.update(DesignSystem)
            .where(
                DesignSystem.source_path.is_not(None),
                DesignSystem.source_root == source_root,
                DesignSystem.slug.not_in(keep_slugs),
            )
            .values(
                source_path=None,
                source_root=None,
                source_digest=None,
                source_mtime_ns=None,
                source_size=None,
                synced_at=None,
                unbound_at=utcnow(),
            )
        )
        result = cast(CursorResult[Any], await db.execute(statement))
        return result.rowcount


design_system_dao: CRUDDesignSystem = CRUDDesignSystem(DesignSystem)

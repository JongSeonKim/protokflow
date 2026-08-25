"""CRUD operations for normalized design tokens."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.app.protokflow.model import DesignToken


class CRUDDesignToken(CRUDPlus[DesignToken]):
    """Design token CRUD class."""

    async def get_all(
        self, db: AsyncSession, design_system_id: str
    ) -> Sequence[DesignToken]:
        """
        Get every token owned by a design system in token-path order

        :param db: Database session
        :param design_system_id: Owning design system ID
        :return:
        """
        return await self.select_models_order(
            db, "token_path", design_system_id=design_system_id
        )

    async def replace(
        self, db: AsyncSession, design_system_id: str, tokens: Iterable[DesignToken]
    ) -> Sequence[DesignToken]:
        """
        Replace every token belonging to a design system

        :param db: Database session
        :param design_system_id: Owning design system ID
        :param tokens: Replacement token instances
        :return:
        """
        token_rows = list(tokens)
        await self.delete_model_by_column(
            db, allow_multiple=True, design_system_id=design_system_id
        )
        db.add_all(token_rows)
        await db.flush()

        return token_rows


design_token_dao: CRUDDesignToken = CRUDDesignToken(DesignToken)

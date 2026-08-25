"""Async SQLAlchemy operations for normalized design tokens."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.protokflow.model import DesignToken


async def list_design_tokens(
    session: AsyncSession, design_system_id: str
) -> list[DesignToken]:
    """Return a design system's tokens in stable token-path order."""
    statement = (
        select(DesignToken)
        .where(DesignToken.design_system_id == design_system_id)
        .order_by(DesignToken.token_path)
    )
    return list((await session.scalars(statement)).all())


async def replace_design_tokens(
    session: AsyncSession,
    design_system_id: str,
    tokens: Iterable[DesignToken],
) -> list[DesignToken]:
    """Replace every token belonging to a design system in one flushable unit."""
    token_rows = list(tokens)
    await session.execute(
        delete(DesignToken).where(DesignToken.design_system_id == design_system_id)
    )

    for token in token_rows:
        token.design_system_id = design_system_id
    session.add_all(token_rows)
    await session.flush()
    return token_rows

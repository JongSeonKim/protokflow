"""Tests for design-token CRUD operations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.protokflow.crud.crud_design_system import create_design_system
from backend.app.protokflow.crud.crud_design_token import (
    list_design_tokens,
    replace_design_tokens,
)
from backend.app.protokflow.model import DesignSystem, DesignToken


async def test_replace_design_tokens_removes_previous_rows(
    test_db: AsyncSession,
) -> None:
    design_system = await create_design_system(
        test_db, DesignSystem(slug="tokens", title="Tokens")
    )
    await replace_design_tokens(
        test_db,
        design_system.id,
        [
            DesignToken(design_system.id, "foundation", "colors.primary", "#000"),
            DesignToken(design_system.id, "foundation", "colors.secondary", "#111"),
        ],
    )

    await replace_design_tokens(
        test_db,
        design_system.id,
        [DesignToken(design_system.id, "component", "button.radius", "4px")],
    )

    tokens = await list_design_tokens(test_db, design_system.id)

    assert [(token.token_path, token.value) for token in tokens] == [
        ("button.radius", "4px")
    ]
    assert (
        await test_db.scalar(
            select(DesignToken.id).where(DesignToken.token_path == "colors.primary")
        )
        is None
    )

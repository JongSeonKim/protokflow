"""Tests for design-token CRUD operations."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.protokflow.crud.crud_design_system import design_system_dao
from backend.app.protokflow.crud.crud_design_token import design_token_dao
from backend.app.protokflow.core.errors import TokenReparentingError
from backend.app.protokflow.model import DesignSystem, DesignToken


async def test_replace_design_tokens_removes_previous_rows(
    test_db: AsyncSession,
) -> None:
    design_system = await design_system_dao.create(
        test_db, DesignSystem(slug="tokens", title="Tokens")
    )
    await design_token_dao.replace(
        test_db,
        design_system.id,
        [
            DesignToken(design_system.id, "foundation", "colors.primary", "#000"),
            DesignToken(design_system.id, "foundation", "colors.secondary", "#111"),
        ],
    )

    await design_token_dao.replace(
        test_db,
        design_system.id,
        [DesignToken(design_system.id, "component", "button.radius", "4px")],
    )

    tokens = await design_token_dao.get_all(test_db, design_system.id)

    assert [(token.token_path, token.value) for token in tokens] == [
        ("button.radius", "4px")
    ]
    assert (
        await test_db.scalar(
            select(DesignToken.id).where(DesignToken.token_path == "colors.primary")
        )
        is None
    )


async def test_replace_rejects_tokens_belonging_to_another_design_system(
    test_db: AsyncSession,
) -> None:
    owner = await design_system_dao.create(
        test_db, DesignSystem(slug="owner", title="Owner")
    )
    other = await design_system_dao.create(
        test_db, DesignSystem(slug="other", title="Other")
    )
    await design_token_dao.replace(
        test_db,
        owner.id,
        [DesignToken(owner.id, "foundation", "colors.primary", "#000")],
    )

    with pytest.raises(TokenReparentingError, match="re-parent"):
        await design_token_dao.replace(
            test_db,
            owner.id,
            [DesignToken(other.id, "foundation", "colors.secondary", "#111")],
        )

    tokens = await design_token_dao.get_all(test_db, owner.id)

    assert [(token.token_path, token.value) for token in tokens] == [
        ("colors.primary", "#000")
    ]

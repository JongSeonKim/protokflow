"""Tests for DESIGN.md indexing and persistence."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.protokflow.core.errors import FencedYamlBlockError, YamlAnchorError
from backend.app.protokflow.crud.crud_design_system import design_system_dao
from backend.app.protokflow.crud.crud_design_token import design_token_dao
from backend.app.protokflow.model import DesignSystem
from backend.app.protokflow.service.design_system_service import design_system_service
from backend.database import db


def _design_md(name: str, color: str, guide: str = "# Guide\n") -> str:
    return (
        "---\n"
        f"name: {name}\n"
        "description: A test system\n"
        "version: '1'\n"
        "colors:\n"
        f"  primary: '{color}'\n"
        "---\n"
        f"{guide}"
    )


async def _systems() -> list[DesignSystem]:
    async with db.async_db_session.begin() as session:
        return list(
            (
                await session.scalars(select(DesignSystem).order_by(DesignSystem.slug))
            ).all()
        )


async def test_indexing_discovers_two_systems_and_stores_source_metadata(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    del test_db
    root_bytes = _design_md("Default", "#111111").encode()
    sibling_bytes = _design_md("Admin Dark", "#222222").encode()
    (tmp_path / "DESIGN.md").write_bytes(root_bytes)
    (tmp_path / "design").mkdir()
    (tmp_path / "design" / "admin-dark.md").write_bytes(sibling_bytes)

    indexed = await design_system_service.index_all(repo_root=tmp_path)
    systems = await _systems()

    assert [system.slug for system in indexed] == ["default", "admin-dark"]
    assert [(system.slug, system.title) for system in systems] == [
        ("admin-dark", "Admin Dark"),
        ("default", "Default"),
    ]
    assert {system.source_path for system in systems} == {
        "DESIGN.md",
        "design/admin-dark.md",
    }
    for system, expected in zip(systems, [sibling_bytes, root_bytes], strict=True):
        assert system.source_digest == hashlib.sha256(expected).hexdigest()
        assert system.source_size == len(expected)
        assert isinstance(system.source_mtime_ns, int)
        assert system.synced_at is not None

    async with db.async_db_session.begin() as session:
        token_counts = [
            len(await design_token_dao.get_all(session, system.id))
            for system in systems
        ]
    assert token_counts == [1, 1]


async def test_front_matter_is_optional_and_uses_slug_title_fallback(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    del test_db
    (tmp_path / "design").mkdir()
    (tmp_path / "design" / "plain.md").write_text(
        "# No front matter\n", encoding="utf-8"
    )

    await design_system_service.index_all(repo_root=tmp_path)
    systems = await _systems()

    assert len(systems) == 1
    assert systems[0].title == "plain"
    assert systems[0].front_matter_raw == ""
    async with db.async_db_session.begin() as session:
        assert await design_token_dao.get_all(session, systems[0].id) == []


async def test_indexing_empty_repository_returns_empty_result(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    del test_db

    assert await design_system_service.index_all(repo_root=tmp_path) == []
    assert await _systems() == []


@pytest.mark.parametrize(
    ("filename", "contents", "error"),
    [
        (
            "anchored.md",
            "---\ncolors:\n  primary: &primary '#111'\n---\n# Guide\n",
            YamlAnchorError,
        ),
        (
            "fenced.md",
            "# Guide\n```yaml\ncolors:\n  primary: '#111'\n```\n",
            FencedYamlBlockError,
        ),
    ],
)
async def test_invalid_documents_leave_no_partial_database_state(
    tmp_path: Path,
    test_db: AsyncSession,
    filename: str,
    contents: str,
    error: type[ValueError],
) -> None:
    del test_db
    (tmp_path / "DESIGN.md").write_text(_design_md("Valid", "#000"), encoding="utf-8")
    (tmp_path / "design").mkdir()
    (tmp_path / "design" / filename).write_text(contents, encoding="utf-8")

    with pytest.raises(error):
        await design_system_service.index_all(repo_root=tmp_path)

    assert await _systems() == []


async def test_reindex_is_idempotent_and_does_not_duplicate_tokens(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    del test_db
    (tmp_path / "DESIGN.md").write_text(_design_md("Default", "#111"), encoding="utf-8")

    await design_system_service.index_all(repo_root=tmp_path)
    await design_system_service.index_all(repo_root=tmp_path)

    systems = await _systems()
    assert len(systems) == 1
    async with db.async_db_session.begin() as session:
        tokens = await design_token_dao.get_all(session, systems[0].id)
    assert [(token.token_path, token.value) for token in tokens] == [
        ("colors.primary", "#111")
    ]


async def test_reindex_after_database_recreation_restores_systems_and_tokens(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    del test_db
    (tmp_path / "DESIGN.md").write_text(_design_md("Default", "#111"), encoding="utf-8")
    (tmp_path / "design").mkdir()
    (tmp_path / "design" / "admin-dark.md").write_text(
        _design_md("Admin Dark", "#222"), encoding="utf-8"
    )

    await design_system_service.index_all(repo_root=tmp_path)
    before = await _systems()
    async with db.async_db_session.begin() as session:
        before_tokens = {
            system.slug: [
                (token.tier, token.token_path, token.value)
                for token in await design_token_dao.get_all(session, system.id)
            ]
            for system in before
        }

    await db.drop_tables()
    await db.create_tables()
    await design_system_service.index_all(repo_root=tmp_path)
    after = await _systems()
    async with db.async_db_session.begin() as session:
        after_tokens = {
            system.slug: [
                (token.tier, token.token_path, token.value)
                for token in await design_token_dao.get_all(session, system.id)
            ]
            for system in after
        }

    assert [
        (system.slug, system.title, system.front_matter_raw, system.guide_markdown)
        for system in after
    ] == [
        (system.slug, system.title, system.front_matter_raw, system.guide_markdown)
        for system in before
    ]
    assert after_tokens == before_tokens


async def test_indexing_rolls_back_all_systems_when_persistence_fails(
    tmp_path: Path,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del test_db
    (tmp_path / "DESIGN.md").write_text(_design_md("Default", "#111"), encoding="utf-8")
    (tmp_path / "design").mkdir()
    (tmp_path / "design" / "admin-dark.md").write_text(
        _design_md("Admin Dark", "#222"), encoding="utf-8"
    )

    real_upsert = design_system_dao.upsert
    upsert_calls = 0

    async def fail_on_second_upsert(
        session: AsyncSession, design_system: DesignSystem
    ) -> DesignSystem:
        nonlocal upsert_calls
        upsert_calls += 1
        if upsert_calls == 2:
            raise RuntimeError("test persistence failure")
        return await real_upsert(session, design_system)

    monkeypatch.setattr(design_system_dao, "upsert", fail_on_second_upsert)

    with pytest.raises(RuntimeError, match="test persistence failure"):
        await design_system_service.index_all(repo_root=tmp_path)

    async with db.async_db_session.begin() as session:
        assert await session.scalar(select(func.count(DesignSystem.id))) == 0

"""Tests for DESIGN.md in-place patch write-through."""

from __future__ import annotations

import difflib
import hashlib
import os
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.protokflow.core.design_md import split_front_matter
from backend.app.protokflow.core.errors import (
    MissingSourceFileError,
    UnknownDesignSystemError,
    UnknownTokenPathError,
    UnbackedDesignSystemError,
)
from backend.app.protokflow.crud.crud_design_system import design_system_dao
from backend.app.protokflow.crud.crud_design_token import design_token_dao
from backend.app.protokflow.model import DesignSystem
from backend.app.protokflow.service.design_system_service import design_system_service
from backend.database import db

_DESIGN_MD = (
    "---\n"
    "# Managed by the design platform team.\n"
    "name: Default\n"
    "description: A calm, high-contrast system.\n"
    "version: '1'\n"
    "omitted: [spacing]\n"
    "labels:\n"
    "  team: core\n"
    "colors:\n"
    "  primary: '#111111'  # inline comment on primary\n"
    "  secondary: '#222222'\n"
    "typography:\n"
    "  body:\n"
    "    fontSize: '16px'\n"
    "rounded:\n"
    "  full: 9999\n"
    "---\n"
    "# Guide\n"
    "\n"
    "Use {colors.primary} for key actions.\n"
)


async def _system_by_slug(slug: str) -> DesignSystem:
    async with db.async_db_session() as session:
        system = await design_system_dao.get_by_slug(session, slug)
        assert system is not None
        return system


async def _token_rows(system_id: str) -> dict[str, str]:
    async with db.async_db_session() as session:
        tokens = await design_token_dao.get_all(session, system_id)
        return {token.token_path: token.value for token in tokens}


def _changed_line_count(original: str, patched: str) -> list[tuple[str, str, str]]:
    """Return (tag, original line, patched line) for every non-equal diff region."""
    matcher = difflib.SequenceMatcher(
        None, original.splitlines(), patched.splitlines(), autojunk=False
    )
    return [
        (tag, original.splitlines()[i1], patched.splitlines()[j1])
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]


async def test_patch_changes_exactly_one_line_and_preserves_original_formatting(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    original = _DESIGN_MD.encode()
    design_md_path.write_bytes(original)
    await design_system_service.index_all(repo_root=tmp_path)

    updated = await design_system_service.apply_token_patch(
        repo_root=tmp_path, slug="default", token_patches={"colors.primary": "#0B0E14"}
    )

    patched = design_md_path.read_bytes()
    patched_text = patched.decode("utf-8")
    assert _changed_line_count(_DESIGN_MD, patched_text) == [
        (
            "replace",
            "  primary: '#111111'  # inline comment on primary",
            "  primary: '#0B0E14'  # inline comment on primary",
        )
    ]
    assert "# Managed by the design platform team." in patched_text
    assert "omitted: [spacing]" in patched_text
    assert "team: core" in patched_text
    assert "version: '1'" in patched_text
    assert patched_text.index("name: Default") < patched_text.index("colors:")

    assert updated.slug == "default"
    system = await _system_by_slug("default")
    assert system.front_matter_raw == split_front_matter(patched_text).front_matter_raw
    assert system.guide_markdown == "# Guide\n\nUse {colors.primary} for key actions.\n"
    tokens = await _token_rows(system.id)
    assert tokens["colors.primary"] == "#0B0E14"
    assert tokens["colors.secondary"] == "#222222"
    assert tokens["typography.body.fontSize"] == "16px"
    assert tokens["rounded.full"] == "9999"


async def test_patch_keeps_unquoted_scalar_style(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)

    await design_system_service.apply_token_patch(
        repo_root=tmp_path, slug="default", token_patches={"rounded.full": "12"}
    )

    patched_text = design_md_path.read_text(encoding="utf-8")
    assert "  full: 12\n" in patched_text
    assert "'12'" not in patched_text
    system = await _system_by_slug("default")
    assert (await _token_rows(system.id))["rounded.full"] == "12"


async def test_patch_updates_source_metadata_to_written_file(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)

    await design_system_service.apply_token_patch(
        repo_root=tmp_path, slug="default", token_patches={"colors.primary": "#0B0E14"}
    )

    patched = design_md_path.read_bytes()
    stat = os.stat(design_md_path)
    system = await _system_by_slug("default")
    assert system.source_digest == hashlib.sha256(patched).hexdigest()
    assert system.source_mtime_ns == stat.st_mtime_ns
    assert system.source_size == stat.st_size == len(patched)
    assert system.synced_at is not None


async def test_unknown_token_path_is_rejected_before_any_write(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    original = _DESIGN_MD.encode()
    design_md_path.write_bytes(original)
    await design_system_service.index_all(repo_root=tmp_path)
    system = await _system_by_slug("default")

    with pytest.raises(UnknownTokenPathError, match="colors.nope"):
        await design_system_service.apply_token_patch(
            repo_root=tmp_path, slug="default", token_patches={"colors.nope": "#000"}
        )

    assert design_md_path.read_bytes() == original
    assert (await _token_rows(system.id))["colors.primary"] == "#111111"


async def test_failed_file_write_preserves_original_file_and_database(
    tmp_path: Path,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    original = _DESIGN_MD.encode()
    design_md_path.write_bytes(original)
    await design_system_service.index_all(repo_root=tmp_path)
    system = await _system_by_slug("default")

    def fail_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated disk failure"):
        await design_system_service.apply_token_patch(
            repo_root=tmp_path,
            slug="default",
            token_patches={"colors.primary": "#0B0E14"},
        )

    assert design_md_path.read_bytes() == original
    assert (await _token_rows(system.id))["colors.primary"] == "#111111"
    assert list(tmp_path.iterdir()) == [design_md_path]


async def test_failed_database_persist_leaves_file_ahead_of_database(
    tmp_path: Path,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)
    digest_before = (await _system_by_slug("default")).source_digest

    async def fail_replace(
        session: AsyncSession, design_system_id: str, tokens: object
    ) -> object:
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(design_token_dao, "replace", fail_replace)

    with pytest.raises(RuntimeError, match="simulated commit failure"):
        await design_system_service.apply_token_patch(
            repo_root=tmp_path,
            slug="default",
            token_patches={"colors.primary": "#0B0E14"},
        )

    patched = design_md_path.read_bytes()
    assert b"#0B0E14" in patched
    system = await _system_by_slug("default")
    assert (await _token_rows(system.id))["colors.primary"] == "#111111"
    assert system.source_digest == digest_before
    assert system.source_digest != hashlib.sha256(patched).hexdigest()


async def test_unknown_slug_raises_domain_error(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    del test_db
    (tmp_path / "DESIGN.md").write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)

    with pytest.raises(UnknownDesignSystemError, match="missing-slug"):
        await design_system_service.apply_token_patch(
            repo_root=tmp_path,
            slug="missing-slug",
            token_patches={"colors.primary": "#0B0E14"},
        )


async def test_db_only_system_rejects_patch(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    del test_db
    async with db.async_db_session.begin() as session:
        await design_system_dao.create(
            session, DesignSystem(slug="orphan", title="Orphan")
        )

    with pytest.raises(UnbackedDesignSystemError, match="orphan"):
        await design_system_service.apply_token_patch(
            repo_root=tmp_path, slug="orphan", token_patches={"colors.primary": "#000"}
        )


async def test_missing_source_file_raises_domain_error(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)
    design_md_path.unlink()

    with pytest.raises(MissingSourceFileError, match="DESIGN.md"):
        await design_system_service.apply_token_patch(
            repo_root=tmp_path, slug="default", token_patches={"colors.primary": "#000"}
        )

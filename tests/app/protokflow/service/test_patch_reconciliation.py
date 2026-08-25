"""Tests for reconciliation behavior on the token-patch entry point."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransaction

from backend.app.protokflow.crud.crud_design_system import design_system_dao
from backend.app.protokflow.crud.crud_design_token import design_token_dao
from backend.app.protokflow.error.storage import ConcurrentModificationError
from backend.app.protokflow.service import design_system_service as service_module
from backend.app.protokflow.service.design_system_service import design_system_service
from backend.database import db


_DESIGN_MD = (
    "---\n"
    "name: Default\n"
    "description: A calm, high-contrast system.\n"
    "version: '1'\n"
    "colors:\n"
    "  primary: '#111111'\n"
    "  secondary: '#222222'\n"
    "typography:\n"
    "  body:\n"
    "    fontSize: '16px'\n"
    "rounded:\n"
    "  full: 9999\n"
    "---\n"
    "# Guide\n"
)


async def _system_by_slug(slug: str):
    async with db.async_db_session() as session:
        system = await design_system_dao.get_by_slug(session, slug)
        assert system is not None
        return system


async def _token_rows(system_id: str) -> dict[str, str]:
    async with db.async_db_session() as session:
        tokens = await design_token_dao.get_all(session, system_id)
        return {token.token_path: token.value for token in tokens}


async def test_external_modification_before_entry_is_absorbed_into_patch(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """An external edit before the patch entry is absorbed, then patched on top."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)

    # External modification lands before the patch enters: reconciliation must
    # absorb it instead of rejecting the patch (KTD6).
    external_content = _DESIGN_MD.replace("#222222", "#333333")
    design_md_path.write_text(external_content, encoding="utf-8")

    updated = await design_system_service.apply_token_patch(
        repo_root=tmp_path,
        slug="default",
        token_patches={"colors.primary": "#0B0E14"},
    )

    patched_text = design_md_path.read_text(encoding="utf-8")
    # Both the external change and the patch survive in the file.
    assert "secondary: '#333333'" in patched_text
    assert "primary: '#0B0E14'" in patched_text

    system = await _system_by_slug("default")
    assert (
        system.source_digest == hashlib.sha256(design_md_path.read_bytes()).hexdigest()
    )
    tokens = await _token_rows(system.id)
    assert tokens["colors.primary"] == "#0B0E14"
    assert tokens["colors.secondary"] == "#333333"
    assert updated.source_digest == system.source_digest


async def test_empty_patch_absorbs_external_change_without_rewriting_file(
    tmp_path: Path,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty patch still reconciles, but never rewrites the absorbed file."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)

    external_content = _DESIGN_MD.replace("#222222", "#333333")
    design_md_path.write_text(external_content, encoding="utf-8")
    stat_before = os.stat(design_md_path)

    def fail_write(*args: object, **kwargs: object) -> None:
        raise AssertionError("an empty patch must not rewrite the file")

    monkeypatch.setattr(service_module, "_atomic_write_bytes", fail_write)

    result = await design_system_service.apply_token_patch(
        repo_root=tmp_path,
        slug="default",
        token_patches={},
    )

    # The external change is absorbed into storage without a file rewrite.
    assert design_md_path.read_bytes() == external_content.encode("utf-8")
    assert os.stat(design_md_path).st_mtime_ns == stat_before.st_mtime_ns
    tokens = await _token_rows(result.id)
    assert tokens["colors.secondary"] == "#333333"
    assert (
        result.source_digest
        == hashlib.sha256(external_content.encode("utf-8")).hexdigest()
    )


async def test_file_ahead_state_is_absorbed_by_next_patch(
    tmp_path: Path,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a failed DB commit, the next patch reconciles and applies on top."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)

    real_commit = SessionTransaction.commit
    real_exit = SessionTransaction.__exit__
    exiting = False

    def tracking_exit(self: SessionTransaction, *exc: object) -> None:
        nonlocal exiting
        exiting = True
        try:
            real_exit(self, *exc)  # type: ignore[arg-type]
        finally:
            exiting = False

    def failing_commit(self: SessionTransaction, _to_root: bool = False) -> None:
        if not exiting:
            return real_commit(self, _to_root)
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(SessionTransaction, "__exit__", tracking_exit)
    monkeypatch.setattr(SessionTransaction, "commit", failing_commit)

    with pytest.raises(RuntimeError, match="simulated commit failure"):
        await design_system_service.apply_token_patch(
            repo_root=tmp_path,
            slug="default",
            token_patches={"colors.primary": "#0B0E14"},
        )

    monkeypatch.undo()

    # The file is ahead of the DB; the next patch must reconcile first (KTD9).
    await design_system_service.apply_token_patch(
        repo_root=tmp_path,
        slug="default",
        token_patches={"colors.secondary": "#ABCDEF"},
    )

    patched_text = design_md_path.read_text(encoding="utf-8")
    assert "primary: '#0B0E14'" in patched_text
    assert "secondary: '#ABCDEF'" in patched_text
    system = await _system_by_slug("default")
    assert (
        system.source_digest == hashlib.sha256(design_md_path.read_bytes()).hexdigest()
    )
    tokens = await _token_rows(system.id)
    assert tokens["colors.primary"] == "#0B0E14"
    assert tokens["colors.secondary"] == "#ABCDEF"


async def test_concurrent_modification_in_write_window_raises_and_discards_temp(
    tmp_path: Path,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A change landing between the entry pre-check and the atomic write is a real race."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)
    system_before = await _system_by_slug("default")

    external_content = _DESIGN_MD.replace("#222222", "#333333")
    real_read = service_module.read_source_bytes

    def read_that_lands_external_edit(path: Path) -> tuple[bytes, os.stat_result]:
        if path == design_md_path:
            # An external editor saves between the entry pre-check and the
            # CAS re-read just before the temporary file is created.
            design_md_path.write_text(external_content, encoding="utf-8")
        return real_read(path)

    monkeypatch.setattr(
        service_module, "read_source_bytes", read_that_lands_external_edit
    )

    with pytest.raises(ConcurrentModificationError, match="refetch"):
        await design_system_service.apply_token_patch(
            repo_root=tmp_path,
            slug="default",
            token_patches={"colors.primary": "#0B0E14"},
        )

    # The external edit is preserved and no temporary file leaked.
    assert design_md_path.read_text(encoding="utf-8") == external_content
    assert [path.name for path in tmp_path.iterdir()] == ["DESIGN.md"]
    system_after = await _system_by_slug("default")
    assert system_after.source_digest == system_before.source_digest
    assert (await _token_rows(system_after.id))["colors.primary"] == "#111111"

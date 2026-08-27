"""Tests for external-change reconciliation at storage entry points."""

from __future__ import annotations

import hashlib
import os
import asyncio
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransaction

from backend.app.protokflow.error.design_md import YamlAnchorError
from backend.app.protokflow.crud.crud_design_system import design_system_dao
from backend.app.protokflow.crud.crud_design_token import design_token_dao
from backend.app.protokflow.model import DesignSystem
from backend.app.protokflow.model import DesignToken
from backend.app.protokflow.error.storage import (
    SourceRootMismatchError,
    UnknownDesignSystemError,
)
from backend.app.protokflow.service import design_system_service as service_module
from backend.app.protokflow.storage import design_source as design_source_module
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


async def _system_by_slug(slug: str) -> DesignSystem:
    async with db.async_db_session() as session:
        system = await design_system_dao.get_by_slug(session, slug)
        assert system is not None
        return system


async def _token_rows(system_id: str) -> dict[str, str]:
    async with db.async_db_session() as session:
        tokens = await design_token_dao.get_all(session, system_id)
        return {token.token_path: token.value for token in tokens}


async def _index_default(tmp_path: Path) -> None:
    (tmp_path / "DESIGN.md").write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)


async def test_query_returns_updated_tokens_after_external_content_change(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """An external edit is absorbed by the next query entry point."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)

    external = _DESIGN_MD.replace("#111111", "#999999")
    design_md_path.write_text(external, encoding="utf-8")

    detail = await design_system_service.get(repo_root=tmp_path, slug="default")

    assert detail.stale is False
    tokens = {token.token_path: token.value for token in detail.tokens}
    assert tokens["colors.primary"] == "#999999"
    assert (
        detail.system.source_digest
        == hashlib.sha256(design_md_path.read_bytes()).hexdigest()
    )


async def test_unchanged_file_query_skips_digest_read(
    tmp_path: Path,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A matching (mtime_ns, size) pre-check must not read bytes or hash them."""
    del test_db
    await _index_default(tmp_path)

    def fail_read(*args: object, **kwargs: object) -> object:
        raise AssertionError("an unchanged source must not be read for hashing")

    monkeypatch.setattr(design_source_module, "read_source_bytes", fail_read)

    detail = await design_system_service.get(repo_root=tmp_path, slug="default")

    assert detail.stale is False
    assert {token.token_path for token in detail.tokens} == {
        "colors.primary",
        "colors.secondary",
        "typography.body.fontSize",
        "rounded.full",
    }


async def test_touch_only_change_refreshes_metadata_without_reparse(
    tmp_path: Path,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A touched-but-identical file updates mtime_ns/size only, without reparse."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    await _index_default(tmp_path)
    before = await _system_by_slug("default")
    assert before.source_mtime_ns is not None

    def fail_parse(*args: object, **kwargs: object) -> object:
        raise AssertionError("a touch-only change must not re-enter the parser")

    monkeypatch.setattr(design_source_module, "parse_design_content", fail_parse)

    bumped_ns = before.source_mtime_ns + 1_000_000_000
    os.utime(design_md_path, ns=(bumped_ns, bumped_ns))

    detail = await design_system_service.get(repo_root=tmp_path, slug="default")

    assert detail.stale is False
    assert detail.system.source_mtime_ns == bumped_ns
    assert detail.system.source_size == before.source_size
    assert detail.system.source_digest == before.source_digest
    assert (await _token_rows(detail.system.id))["colors.primary"] == "#111111"


async def test_same_size_content_change_is_detected(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """A same-size rewrite with a moved mtime must be detected by digest."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    await _index_default(tmp_path)
    before = await _system_by_slug("default")
    assert before.source_mtime_ns is not None

    external = _DESIGN_MD.replace("#111111", "#333333")
    assert len(external) == len(_DESIGN_MD)
    design_md_path.write_text(external, encoding="utf-8")
    bumped_ns = before.source_mtime_ns + 1_000_000_000
    os.utime(design_md_path, ns=(bumped_ns, bumped_ns))

    detail = await design_system_service.get(repo_root=tmp_path, slug="default")

    tokens = {token.token_path: token.value for token in detail.tokens}
    assert tokens["colors.primary"] == "#333333"


async def test_one_nanosecond_mtime_delta_still_triggers_digest_check(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """Integer-nanosecond storage must catch a 1ns mtime delta (R21 regression)."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    await _index_default(tmp_path)
    before = await _system_by_slug("default")
    assert before.source_mtime_ns is not None

    external = _DESIGN_MD.replace("#222222", "#333333")
    assert len(external) == len(_DESIGN_MD)
    design_md_path.write_text(external, encoding="utf-8")
    bumped_ns = before.source_mtime_ns + 1
    os.utime(design_md_path, ns=(bumped_ns, bumped_ns))

    detail = await design_system_service.get(repo_root=tmp_path, slug="default")

    tokens = {token.token_path: token.value for token in detail.tokens}
    assert tokens["colors.secondary"] == "#333333"
    assert detail.system.source_mtime_ns == bumped_ns


async def test_mtime_preserving_change_is_boundary_and_index_all_recovers(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """A (mtime_ns, size)-preserving edit is outside stat detection; index recovers."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    await _index_default(tmp_path)
    before = await _system_by_slug("default")
    assert before.source_mtime_ns is not None

    external = _DESIGN_MD.replace("#222222", "#333333")
    design_md_path.write_text(external, encoding="utf-8")
    os.utime(
        design_md_path,
        ns=(before.source_mtime_ns, before.source_mtime_ns),
    )

    detail = await design_system_service.get(repo_root=tmp_path, slug="default")
    assert {token.token_path: token.value for token in detail.tokens}[
        "colors.secondary"
    ] == "#222222"

    await design_system_service.index_all(repo_root=tmp_path)
    assert (await _token_rows((await _system_by_slug("default")).id))[
        "colors.secondary"
    ] == "#333333"


async def test_query_after_source_deletion_returns_stale_db_state(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """A missing source keeps the DB row and reports a derived stale flag."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    await _index_default(tmp_path)
    before = await _system_by_slug("default")
    design_md_path.unlink()

    detail = await design_system_service.get(repo_root=tmp_path, slug="default")

    assert detail.stale is True
    assert detail.system.id == before.id
    assert detail.system.source_digest == before.source_digest
    assert {token.token_path: token.value for token in detail.tokens}[
        "colors.primary"
    ] == "#111111"


async def test_query_rejects_repo_root_that_differs_from_indexed_root(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """source_path resolves against the bound root, so another root is rejected."""
    del test_db
    await _index_default(tmp_path)
    other_root = tmp_path / "other-worktree"
    other_root.mkdir()

    with pytest.raises(SourceRootMismatchError, match="re-index"):
        await design_system_service.get(repo_root=other_root, slug="default")


async def test_query_raises_unknown_slug(tmp_path: Path, test_db: AsyncSession) -> None:
    del test_db
    await _index_default(tmp_path)

    with pytest.raises(UnknownDesignSystemError, match="missing-slug"):
        await design_system_service.get(repo_root=tmp_path, slug="missing-slug")


async def test_unknown_slug_does_not_allocate_a_lock(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """Rejecting an unknown slug must not grow the per-slug lock map."""
    del test_db
    await _index_default(tmp_path)

    with pytest.raises(UnknownDesignSystemError, match="never-seen"):
        await design_system_service.get(repo_root=tmp_path, slug="never-seen")
    with pytest.raises(UnknownDesignSystemError, match="never-seen"):
        await design_system_service.apply_token_patch(
            repo_root=tmp_path,
            slug="never-seen",
            token_patches={"colors.primary": "#0"},
        )

    assert set(design_system_service._locks) == {"default"}


async def test_query_returns_db_only_system_without_reconciliation(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """A DB-only system (source_path NULL) is returned as-is, never stale."""
    del test_db
    await _index_default(tmp_path)
    async with db.async_db_session.begin() as session:
        db_only = await design_system_dao.create(
            session, DesignSystem(slug="derived", title="Derived")
        )
        session.add(DesignToken(db_only.id, "foundation", "colors.accent", "#777777"))

    detail = await design_system_service.get(repo_root=tmp_path, slug="derived")

    assert detail.stale is False
    assert detail.system.slug == "derived"
    assert [(token.token_path, token.value) for token in detail.tokens] == [
        ("colors.accent", "#777777")
    ]


async def test_index_all_cannot_revert_a_completed_patch(
    tmp_path: Path,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A patch landing while an index batch is paused must not be overwritten."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)

    upsert_entered = asyncio.Event()
    release_index = asyncio.Event()
    real_upsert = design_system_dao.upsert
    gate_armed = True

    async def upsert_gate(session: object, obj: DesignSystem, **kwargs: object):
        nonlocal gate_armed
        if gate_armed:
            gate_armed = False
            upsert_entered.set()
            await release_index.wait()
        return await real_upsert(session, obj, **kwargs)  # type: ignore[arg-type]

    async def run_paused_index() -> object:
        return await design_system_service.index_all(repo_root=tmp_path)

    async def run_patch_after_index_enters() -> object:
        await upsert_entered.wait()
        patch_task = asyncio.create_task(
            design_system_service.apply_token_patch(
                repo_root=tmp_path,
                slug="default",
                token_patches={"colors.primary": "#0B0E14"},
            )
        )
        # While the index batch is paused inside its transaction, the patch can
        # only be waiting on the shared lock; once that is observed, let the
        # batch finish so the patch runs against its committed result.
        for _ in range(100):
            if patch_task.done():
                break
            await asyncio.sleep(0.01)
        assert not patch_task.done(), "patch completed while index held the lock"
        release_index.set()
        return await patch_task

    monkeypatch.setattr(design_system_dao, "upsert", upsert_gate)
    indexed, patched = await asyncio.gather(  # type: ignore[misc]
        run_paused_index(), run_patch_after_index_enters()
    )

    # The patch ran after the paused index released the shared lock, so the
    # index's pre-patch parse cannot overwrite the patched state.
    assert indexed is not None and patched is not None
    patched_text = design_md_path.read_text(encoding="utf-8")
    assert "primary: '#0B0E14'" in patched_text
    system = await _system_by_slug("default")
    assert (
        system.source_digest == hashlib.sha256(design_md_path.read_bytes()).hexdigest()
    )
    assert (await _token_rows(system.id))["colors.primary"] == "#0B0E14"


async def test_rejected_reindex_keeps_previous_db_state(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """An anchor introduced externally rejects reindexing and keeps the old row."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    await _index_default(tmp_path)
    before = await _system_by_slug("default")

    anchored = _DESIGN_MD.replace(
        "  primary: '#111111'\n",
        "  primary: &anchor '#111111'\n",
    )
    design_md_path.write_text(anchored, encoding="utf-8")

    with pytest.raises(YamlAnchorError):
        await design_system_service.get(repo_root=tmp_path, slug="default")

    after = await _system_by_slug("default")
    assert after.source_digest == before.source_digest
    assert after.source_mtime_ns == before.source_mtime_ns
    assert (await _token_rows(after.id))["colors.primary"] == "#111111"


async def test_row_deleted_during_reconciliation_is_not_revived(
    tmp_path: Path,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed-source sync rechecks its row inside the service transaction."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    await _index_default(tmp_path)
    system_id = (await _system_by_slug("default")).id
    design_md_path.write_text(
        _DESIGN_MD.replace("#111111", "#999999"), encoding="utf-8"
    )

    real_to_thread = asyncio.to_thread
    deleted = False

    async def observe_then_delete(
        func: object, /, *args: object, **kwargs: object
    ) -> object:
        nonlocal deleted
        result = await real_to_thread(func, *args, **kwargs)  # type: ignore[arg-type]
        if func is service_module.observe_design_source and not deleted:
            deleted = True
            async with db.async_db_session.begin() as session:
                await design_system_dao.delete_model_by_column(session, slug="default")
        return result

    monkeypatch.setattr(service_module.asyncio, "to_thread", observe_then_delete)

    with pytest.raises(UnknownDesignSystemError, match="deleted while.*reconciled"):
        await design_system_service.get(repo_root=tmp_path, slug="default")

    async with db.async_db_session() as session:
        assert await design_system_dao.get_by_slug(session, "default") is None
        assert list(await design_token_dao.get_all(session, system_id)) == []


async def test_reindex_replaces_token_set_without_leftovers(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """Reindexing syncs the full token set; tokens removed on disk disappear."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    await _index_default(tmp_path)

    external = (
        _DESIGN_MD.split("typography:")[0] + "  tertiary: '#777777'\n---\n# Guide\n"
    )
    design_md_path.write_text(external, encoding="utf-8")

    detail = await design_system_service.get(repo_root=tmp_path, slug="default")

    assert {token.token_path: token.value for token in detail.tokens} == {
        "colors.primary": "#111111",
        "colors.secondary": "#222222",
        "colors.tertiary": "#777777",
    }


async def test_index_all_deletes_orphaned_file_backed_rows(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """Rows for files gone from the discovery set are hard-deleted."""
    del test_db
    (tmp_path / "DESIGN.md").write_text(_DESIGN_MD, encoding="utf-8")
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    (design_dir / "admin.md").write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)
    default_id = (await _system_by_slug("default")).id
    admin_id = (await _system_by_slug("admin")).id
    assert await _token_rows(admin_id)

    (design_dir / "admin.md").unlink()
    indexed = await design_system_service.index_all(repo_root=tmp_path)

    assert [system.slug for system in indexed] == ["default"]
    async with db.async_db_session() as session:
        assert await design_system_dao.get_by_slug(session, "admin") is None
        assert await design_system_dao.get_by_slug(session, "default") is not None
        assert list(await design_token_dao.get_all(session, admin_id)) == []
        assert await design_token_dao.get_all(session, default_id)


async def test_index_all_with_empty_discovery_still_deletes_file_backed_rows(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """An empty discovery set still opens the transaction and deletes orphans."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    await _index_default(tmp_path)
    system_id = (await _system_by_slug("default")).id
    design_md_path.unlink()

    assert await design_system_service.index_all(repo_root=tmp_path) == []

    async with db.async_db_session() as session:
        assert await design_system_dao.get_by_slug(session, "default") is None
        assert list(await design_token_dao.get_all(session, system_id)) == []


async def test_index_all_preserves_db_only_rows(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """DB-only rows (source_path NULL) survive batch reindexing."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    await _index_default(tmp_path)
    async with db.async_db_session.begin() as session:
        await design_system_dao.create(
            session, DesignSystem(slug="derived", title="Derived")
        )

    await design_system_service.index_all(repo_root=tmp_path)
    async with db.async_db_session() as session:
        assert await design_system_dao.get_by_slug(session, "derived") is not None
        assert await design_system_dao.get_by_slug(session, "default") is not None

    design_md_path.unlink()
    await design_system_service.index_all(repo_root=tmp_path)
    async with db.async_db_session() as session:
        assert await design_system_dao.get_by_slug(session, "derived") is not None
        assert await design_system_dao.get_by_slug(session, "default") is None


async def test_index_all_orphan_deletion_is_scoped_to_indexed_root(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """Reindexing one repository root must not delete rows bound to another root."""
    del test_db
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    (first_root / "DESIGN.md").write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=first_root)

    await design_system_service.index_all(repo_root=second_root)

    async with db.async_db_session() as session:
        assert await design_system_dao.get_by_slug(session, "default") is not None


async def test_file_ahead_state_is_absorbed_by_next_query(
    tmp_path: Path,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a failed DB commit, the next query re-indexes the file."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    await _index_default(tmp_path)

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

    detail = await design_system_service.get(repo_root=tmp_path, slug="default")

    assert detail.stale is False
    tokens = {token.token_path: token.value for token in detail.tokens}
    assert tokens["colors.primary"] == "#0B0E14"
    assert (
        detail.system.source_digest
        == hashlib.sha256(design_md_path.read_bytes()).hexdigest()
    )

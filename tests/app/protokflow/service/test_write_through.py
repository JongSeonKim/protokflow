"""Tests for DESIGN.md in-place patch write-through."""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from stat import S_IMODE, S_ISDIR

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransaction

from backend.app.protokflow.core.design_md import parse_design_md, split_front_matter
from backend.app.protokflow.crud.crud_design_system import design_system_dao
from backend.app.protokflow.crud.crud_design_token import design_token_dao
from backend.app.protokflow.model import DesignSystem
from backend.app.protokflow.core.errors import UnknownTokenPathError
from backend.app.protokflow.service import design_system_service as service_module
from backend.app.protokflow.service.design_system_service import design_system_service
from backend.app.protokflow.service.errors import (
    ConcurrentModificationError,
    MissingSourceFileError,
    SourceRootMismatchError,
    SourceWriteError,
    UnknownDesignSystemError,
    UnbackedDesignSystemError,
    UnsupportedSourceLinkError,
)
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


def _single_line_byte_diff(original: bytes, patched: bytes) -> tuple[bytes, bytes]:
    """Assert the two documents differ in exactly one whole line; return (old, new).

    Lines are split with keepends and compared as bytes, so a stray change to the
    trailing newline or the EOL style of any untouched line is caught here — a
    ``str.splitlines()`` comparison drops those bytes and would pass regardless.
    """
    original_lines = original.splitlines(keepends=True)
    patched_lines = patched.splitlines(keepends=True)
    assert len(original_lines) == len(patched_lines)
    diffs = [
        (old, new)
        for old, new in zip(original_lines, patched_lines, strict=True)
        if old != new
    ]
    assert len(diffs) == 1
    return diffs[0]


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
    assert _single_line_byte_diff(_DESIGN_MD.encode(), patched) == (
        b"  primary: '#111111'  # inline comment on primary\n",
        b"  primary: '#0B0E14'  # inline comment on primary\n",
    )
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

    with pytest.raises(SourceWriteError, match="simulated disk failure") as excinfo:
        await design_system_service.apply_token_patch(
            repo_root=tmp_path,
            slug="default",
            token_patches={"colors.primary": "#0B0E14"},
        )

    assert isinstance(excinfo.value.__cause__, OSError)
    assert design_md_path.read_bytes() == original
    assert (await _token_rows(system.id))["colors.primary"] == "#111111"
    assert list(tmp_path.iterdir()) == [design_md_path]


async def test_pre_commit_failure_leaves_file_ahead_of_database(
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


async def test_row_deleted_mid_patch_is_not_revived(
    tmp_path: Path,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)
    system_id = (await _system_by_slug("default")).id

    real_to_thread = asyncio.to_thread

    async def to_thread_that_deletes_row(
        func: object, /, *args: object, **kwargs: object
    ):
        if func is service_module._patch_and_write:
            async with db.async_db_session.begin() as session:
                await design_system_dao.delete_model_by_column(session, slug="default")
        return await real_to_thread(func, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service_module.asyncio, "to_thread", to_thread_that_deletes_row)

    with pytest.raises(UnknownDesignSystemError, match="deleted while"):
        await design_system_service.apply_token_patch(
            repo_root=tmp_path,
            slug="default",
            token_patches={"colors.primary": "#0B0E14"},
        )

    assert b"#0B0E14" in design_md_path.read_bytes()
    async with db.async_db_session() as session:
        assert await design_system_dao.get_by_slug(session, "default") is None
        assert list(await design_token_dao.get_all(session, system_id)) == []


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


async def test_patch_rejects_repo_root_that_differs_from_indexed_root(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)

    other_root = tmp_path / "other-worktree"
    other_root.mkdir()

    with pytest.raises(SourceRootMismatchError, match="re-index"):
        await design_system_service.apply_token_patch(
            repo_root=other_root,
            slug="default",
            token_patches={"colors.primary": "#0B0E14"},
        )

    assert design_md_path.read_text(encoding="utf-8") == _DESIGN_MD


async def test_patch_accepts_repo_root_spelling_that_resolves_to_indexed_root(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    del test_db
    (tmp_path / "DESIGN.md").write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)

    root_alias = tmp_path.parent / (tmp_path.name + "-alias")
    root_alias.symlink_to(tmp_path)
    try:
        system = await design_system_service.apply_token_patch(
            repo_root=root_alias,
            slug="default",
            token_patches={"colors.primary": "#0B0E14"},
        )
    finally:
        root_alias.unlink()

    assert (await _token_rows(system.id))["colors.primary"] == "#0B0E14"


async def test_patch_rejects_missing_source_root_and_reindex_rebinds_it(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    del test_db
    (tmp_path / "DESIGN.md").write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)

    async with db.async_db_session.begin() as session:
        system = await design_system_dao.get_by_slug(session, "default")
        assert system is not None
        system.source_root = None

    with pytest.raises(SourceRootMismatchError, match="re-index"):
        await design_system_service.apply_token_patch(
            repo_root=tmp_path,
            slug="default",
            token_patches={"colors.primary": "#0B0E14"},
        )

    await design_system_service.index_all(repo_root=tmp_path)
    system = await design_system_service.apply_token_patch(
        repo_root=tmp_path,
        slug="default",
        token_patches={"colors.primary": "#0B0E14"},
    )

    assert (await _token_rows(system.id))["colors.primary"] == "#0B0E14"


async def test_source_metadata_describes_one_file_version(
    tmp_path: Path,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Digest and stat must come from one observation, even under an external save."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    indexed = _DESIGN_MD.encode()
    design_md_path.write_bytes(indexed)
    external_edit = (
        _DESIGN_MD.replace("#222222", "#333333").encode() + b"\n# appended\n"
    )
    assert len(external_edit) != len(indexed)

    real_parse = service_module._parse_design_content

    def parse_after_external_save(path: Path, content: bytes) -> object:
        # An editor saves a longer document once the bytes have been read.
        design_md_path.write_bytes(external_edit)
        return real_parse(path, content)

    monkeypatch.setattr(
        service_module, "_parse_design_content", parse_after_external_save
    )

    await design_system_service.index_all(repo_root=tmp_path)

    system = await _system_by_slug("default")
    assert system.source_digest == hashlib.sha256(indexed).hexdigest()
    assert system.source_size == len(indexed)


async def test_atomic_write_forces_bytes_and_directory_entry_to_disk(
    tmp_path: Path,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The patched bytes and the rename must both be flushed past the page cache."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)

    synced: list[str] = []
    real_fsync = os.fsync

    def recording_fsync(fd: int) -> None:
        synced.append("dir" if S_ISDIR(os.fstat(fd).st_mode) else "file")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)

    await design_system_service.apply_token_patch(
        repo_root=tmp_path, slug="default", token_patches={"colors.primary": "#0B0E14"}
    )

    assert synced == ["file", "dir"]


async def test_patch_records_metadata_of_the_bytes_it_wrote(
    tmp_path: Path,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A writer replacing the path right after the swap must not steal the bookkeeping."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)

    real_replace = os.replace
    intruder = _DESIGN_MD.encode() + b"\n# written by someone else\n"
    written: list[bytes] = []
    written_mtime_ns: list[int] = []

    def replace_then_intrude(
        src: str | os.PathLike[str], dst: str | os.PathLike[str]
    ) -> None:
        real_replace(src, dst)
        written.append(design_md_path.read_bytes())
        written_mtime_ns.append(os.stat(design_md_path).st_mtime_ns)
        design_md_path.write_bytes(intruder)
        # Stamp an unmistakable mtime so bookkeeping taken from the path after
        # the swap is distinguishable from bookkeeping taken from our own write.
        os.utime(design_md_path, ns=(0, 0))

    monkeypatch.setattr(os, "replace", replace_then_intrude)

    updated = await design_system_service.apply_token_patch(
        repo_root=tmp_path, slug="default", token_patches={"colors.primary": "#0B0E14"}
    )

    assert len(written) == 1
    assert written[0] != intruder
    assert updated.source_mtime_ns == written_mtime_ns[0]
    assert updated.source_size == len(written[0])
    assert updated.source_digest == hashlib.sha256(written[0]).hexdigest()


@pytest.mark.parametrize(
    "token_patches",
    [
        {"colors.primary": "#0B0E14"},
        {
            "colors.primary": "#0B0E14",
            "typography.body.fontSize": "18px",
            "rounded.full": "12",
        },
    ],
    ids=["single-token", "multi-token-across-groups"],
)
async def test_patch_parses_the_document_only_once(
    tmp_path: Path,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    token_patches: dict[str, str],
) -> None:
    """The patched form is derived, not re-parsed, so the hot path pays one parse.

    A multi-token patch spanning several YAML groups must not cost extra parses:
    the sub-16ms hot-reload budget is guarded by keeping the parse count at one
    regardless of how many token paths a single call rewrites.
    """
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)

    parses = 0
    real_parse = service_module.parse_design_md

    def counting_parse(text: str) -> object:
        nonlocal parses
        parses += 1
        return real_parse(text)

    monkeypatch.setattr(service_module, "parse_design_md", counting_parse)

    await design_system_service.apply_token_patch(
        repo_root=tmp_path, slug="default", token_patches=token_patches
    )

    assert parses == 1


async def test_derived_parse_matches_a_full_reparse(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """Deriving the patched form must agree with parsing the emitted bytes."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)

    await design_system_service.apply_token_patch(
        repo_root=tmp_path,
        slug="default",
        token_patches={"colors.primary": "#0B0E14", "rounded.full": "12"},
    )

    reparsed = parse_design_md(design_md_path.read_text(encoding="utf-8"))
    system = await _system_by_slug("default")
    assert system.front_matter_raw == reparsed.front_matter_raw
    assert system.title == reparsed.title
    assert system.description == reparsed.description
    assert system.spec_version == reparsed.spec_version
    assert system.front_matter_extras == reparsed.front_matter_extras
    assert system.guide_markdown == reparsed.guide_markdown
    assert await _token_rows(system.id) == {
        row.token_path: row.value for row in reparsed.tokens
    }


async def test_commit_failure_leaves_file_ahead_of_database(
    tmp_path: Path,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure at the commit itself must still leave the file as the newer copy."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)
    digest_before = (await _system_by_slug("default")).source_digest

    replaced: list[str] = []
    real_replace = design_token_dao.replace

    async def spying_replace(
        db_session: AsyncSession, design_system_id: str, tokens: object
    ) -> object:
        rows = await real_replace(db_session, design_system_id, tokens)  # type: ignore[arg-type]
        replaced.append(design_system_id)
        return rows

    # Session.flush() drives SessionTransaction.commit too, so failing every
    # commit would abort before the token replacement ever runs. Only the commit
    # the transaction context manager performs on exit may fail here.
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

    monkeypatch.setattr(design_token_dao, "replace", spying_replace)
    monkeypatch.setattr(SessionTransaction, "__exit__", tracking_exit)
    monkeypatch.setattr(SessionTransaction, "commit", failing_commit)

    with pytest.raises(RuntimeError, match="simulated commit failure"):
        await design_system_service.apply_token_patch(
            repo_root=tmp_path,
            slug="default",
            token_patches={"colors.primary": "#0B0E14"},
        )

    # Restore the commit before querying, so the assertions use a working session.
    monkeypatch.undo()

    # The real token replacement ran; only the commit failed.
    assert replaced == [(await _system_by_slug("default")).id]

    patched = design_md_path.read_bytes()
    assert b"#0B0E14" in patched
    system = await _system_by_slug("default")
    assert (await _token_rows(system.id))["colors.primary"] == "#111111"
    assert system.source_digest == digest_before
    assert system.source_digest != hashlib.sha256(patched).hexdigest()


async def test_external_modification_raises_concurrent_modification_error(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """An external edit changing the file digest before patch must be rejected."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)
    system_before = await _system_by_slug("default")
    expected_digest = system_before.source_digest

    # External modification: user/editor touches the file directly
    external_content = _DESIGN_MD.replace("#111111", "#999999")
    design_md_path.write_text(external_content, encoding="utf-8")
    found_digest = hashlib.sha256(external_content.encode("utf-8")).hexdigest()

    with pytest.raises(ConcurrentModificationError) as exc_info:
        await design_system_service.apply_token_patch(
            repo_root=tmp_path,
            slug="default",
            token_patches={"colors.primary": "#0B0E14"},
        )

    error_msg = str(exc_info.value)
    assert "default" in error_msg
    assert expected_digest is not None
    assert expected_digest in error_msg
    assert found_digest in error_msg
    assert "refetch" in error_msg

    # Verify external file was not clobbered by the failed patch
    assert design_md_path.read_text(encoding="utf-8") == external_content
    # Verify DB still holds the pre-modification state
    system_after = await _system_by_slug("default")
    assert system_after.source_digest == expected_digest
    assert (await _token_rows(system_after.id))["colors.primary"] == "#111111"


async def test_concurrent_token_patches_are_serialized_without_lost_updates(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """Concurrent in-process patches on the same slug must serialize and preserve all updates."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)

    # Launch two concurrent patches on disjoint tokens
    results = await asyncio.gather(
        design_system_service.apply_token_patch(
            repo_root=tmp_path,
            slug="default",
            token_patches={"colors.primary": "#0B0E14"},
        ),
        design_system_service.apply_token_patch(
            repo_root=tmp_path,
            slug="default",
            token_patches={"typography.body.fontSize": "18px"},
        ),
    )

    assert len(results) == 2
    patched_text = design_md_path.read_text(encoding="utf-8")
    assert "primary: '#0B0E14'" in patched_text
    assert "fontSize: '18px'" in patched_text

    system = await _system_by_slug("default")
    tokens = await _token_rows(system.id)
    assert tokens["colors.primary"] == "#0B0E14"
    assert tokens["typography.body.fontSize"] == "18px"
    assert (
        system.source_digest == hashlib.sha256(patched_text.encode("utf-8")).hexdigest()
    )


async def test_multi_token_patch_across_groups_persists_every_value(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """One call spanning colors, typography, and rounded must persist all patches."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)

    patches = {
        "colors.primary": "#0B0E14",
        "colors.secondary": "#ABCDEF",
        "typography.body.fontSize": "18px",
        "rounded.full": "12",
    }
    await design_system_service.apply_token_patch(
        repo_root=tmp_path, slug="default", token_patches=patches
    )

    patched_text = design_md_path.read_text(encoding="utf-8")
    assert "primary: '#0B0E14'" in patched_text
    assert "secondary: '#ABCDEF'" in patched_text
    assert "fontSize: '18px'" in patched_text
    assert "  full: 12\n" in patched_text  # unquoted scalar style preserved
    assert "'12'" not in patched_text
    # Untouched envelope survives a multi-group patch.
    assert "# Managed by the design platform team." in patched_text
    assert "omitted: [spacing]" in patched_text
    assert "team: core" in patched_text

    system = await _system_by_slug("default")
    assert await _token_rows(system.id) == {
        "colors.primary": "#0B0E14",
        "colors.secondary": "#ABCDEF",
        "typography.body.fontSize": "18px",
        "rounded.full": "12",
    }
    assert (
        system.source_digest == hashlib.sha256(patched_text.encode("utf-8")).hexdigest()
    )


async def test_patch_round_trips_crlf_through_write_through(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """A CRLF document must stay CRLF after write-through; only the target line changes."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    original = _DESIGN_MD.replace("\n", "\r\n").encode()
    design_md_path.write_bytes(original)
    await design_system_service.index_all(repo_root=tmp_path)

    await design_system_service.apply_token_patch(
        repo_root=tmp_path, slug="default", token_patches={"colors.primary": "#0B0E14"}
    )

    patched = design_md_path.read_bytes()
    # Every newline is part of a CRLF pair; the LF-only branch never leaked in.
    assert b"\n" in patched
    assert patched.count(b"\r\n") == patched.count(b"\n")
    assert _single_line_byte_diff(original, patched) == (
        b"  primary: '#111111'  # inline comment on primary\r\n",
        b"  primary: '#0B0E14'  # inline comment on primary\r\n",
    )

    system = await _system_by_slug("default")
    assert (await _token_rows(system.id))["colors.primary"] == "#0B0E14"
    assert system.source_digest == hashlib.sha256(patched).hexdigest()


async def test_patch_writes_through_nested_source_path(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """A system under design/ is patched via its joined path, leaking no .tmp sibling."""
    del test_db
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    nested = design_dir / "admin.md"
    nested.write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)

    assert (await _system_by_slug("admin")).source_path == "design/admin.md"

    await design_system_service.apply_token_patch(
        repo_root=tmp_path, slug="admin", token_patches={"colors.primary": "#0B0E14"}
    )

    assert b"#0B0E14" in nested.read_bytes()
    # No temporary artifact was left behind for discovery to trip over.
    assert [path.name for path in design_dir.iterdir()] == ["admin.md"]
    # Re-indexing rediscovers exactly one system, not a .tmp masquerading as a sibling.
    reindexed = await design_system_service.index_all(repo_root=tmp_path)
    assert sorted(system.slug for system in reindexed) == ["admin"]
    system = await _system_by_slug("admin")
    assert (await _token_rows(system.id))["colors.primary"] == "#0B0E14"


async def test_empty_token_patches_is_a_noop(
    tmp_path: Path,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty patch must not rewrite the file, bump its mtime, or reparse it."""
    del test_db
    design_md_path = tmp_path / "DESIGN.md"
    original = _DESIGN_MD.encode()
    design_md_path.write_bytes(original)
    await design_system_service.index_all(repo_root=tmp_path)
    system_before = await _system_by_slug("default")
    stat_before = os.stat(design_md_path)

    def fail_write(*args: object, **kwargs: object) -> None:
        raise AssertionError("a no-op patch must not touch the file")

    monkeypatch.setattr(service_module, "_atomic_write_bytes", fail_write)

    result = await design_system_service.apply_token_patch(
        repo_root=tmp_path, slug="default", token_patches={}
    )

    assert result.id == system_before.id
    assert result.source_digest == system_before.source_digest
    assert design_md_path.read_bytes() == original
    assert os.stat(design_md_path).st_mtime_ns == stat_before.st_mtime_ns
    assert (await _token_rows(system_before.id))["colors.primary"] == "#111111"


async def test_empty_token_patches_on_unknown_slug_still_raises(
    tmp_path: Path, test_db: AsyncSession
) -> None:
    """The no-op fast path still resolves the slug, so an unknown one is rejected."""
    del test_db
    (tmp_path / "DESIGN.md").write_text(_DESIGN_MD, encoding="utf-8")
    await design_system_service.index_all(repo_root=tmp_path)

    with pytest.raises(UnknownDesignSystemError, match="missing-slug"):
        await design_system_service.apply_token_patch(
            repo_root=tmp_path, slug="missing-slug", token_patches={}
        )


def test_atomic_write_preserves_non_default_file_mode(tmp_path: Path) -> None:
    """copymode carries the target's mode onto the 0o600 mkstemp temp before the swap."""
    target = tmp_path / "DESIGN.md"
    target.write_bytes(b"original\n")
    target.chmod(0o640)
    mode_before = S_IMODE(os.stat(target).st_mode)
    assert mode_before == 0o640  # distinct from mkstemp's default 0o600

    service_module._atomic_write_bytes(target, b"new content\n")

    assert target.read_bytes() == b"new content\n"
    assert S_IMODE(os.stat(target).st_mode) == 0o640


def test_atomic_write_unlinks_temp_when_copymode_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A copymode failure after the temp is written must unlink it and preserve the target."""
    target = tmp_path / "DESIGN.md"
    target.write_bytes(b"original\n")

    def failing_copymode(*args: object, **kwargs: object) -> None:
        raise OSError("simulated copymode failure")

    monkeypatch.setattr(service_module.shutil, "copymode", failing_copymode)

    with pytest.raises(SourceWriteError, match="simulated copymode failure"):
        service_module._atomic_write_bytes(target, b"new content\n")

    assert target.read_bytes() == b"original\n"
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_write_unlinks_temp_when_handle_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write failure into the temp file must unlink it and never touch the target."""
    target = tmp_path / "DESIGN.md"
    target.write_bytes(b"original\n")

    real_fdopen = os.fdopen

    def fdopen_with_failing_write(fd: int, mode: str = "wb") -> object:
        # _atomic_write_bytes always opens the temp descriptor "wb"; wrap that
        # real handle so only its write() fails while flush/fileno/close stay real.
        handle = real_fdopen(fd, "wb")

        class _FailingWriteHandle:
            def __enter__(self) -> _FailingWriteHandle:
                handle.__enter__()
                return self

            def __exit__(self, *exc: object) -> None:
                handle.close()

            def write(self, _data: object) -> int:
                raise OSError("simulated write failure")

            def flush(self) -> None:
                handle.flush()

            def fileno(self) -> int:
                return handle.fileno()

        return _FailingWriteHandle()

    monkeypatch.setattr(service_module.os, "fdopen", fdopen_with_failing_write)

    with pytest.raises(SourceWriteError, match="simulated write failure"):
        service_module._atomic_write_bytes(target, b"new content\n")

    assert target.read_bytes() == b"original\n"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.skipif(
    hasattr(os, "getuid") and os.getuid() == 0,
    reason="root bypasses directory permission bits",
)
def test_atomic_write_wraps_permission_error_on_unwritable_parent(
    tmp_path: Path,
) -> None:
    """mkstemp cannot create the temp in a read-only directory; wrapped with cause."""
    design_dir = tmp_path / "locked"
    design_dir.mkdir()
    target = design_dir / "DESIGN.md"
    target.write_bytes(b"original\n")
    design_dir.chmod(0o500)
    try:
        with pytest.raises(SourceWriteError) as excinfo:
            service_module._atomic_write_bytes(target, b"new content\n")
    finally:
        design_dir.chmod(0o700)

    assert isinstance(excinfo.value.__cause__, PermissionError)
    assert target.read_bytes() == b"original\n"


def test_atomic_write_rejects_symlink_source(tmp_path: Path) -> None:
    """Symlink sources are rejected to prevent replacing the link with a regular file."""
    real_target = tmp_path / "real.md"
    real_target.write_bytes(b"original\n")
    link = tmp_path / "DESIGN.md"
    link.symlink_to(real_target)

    with pytest.raises(UnsupportedSourceLinkError):
        service_module._atomic_write_bytes(link, b"new content\n")

    assert link.is_symlink()
    assert real_target.read_bytes() == b"original\n"
    assert sorted(tmp_path.iterdir()) == sorted([real_target, link])


def test_atomic_write_rejects_hard_linked_source(tmp_path: Path) -> None:
    """Hard-linked sources are rejected to prevent breaking link aliases."""
    target = tmp_path / "DESIGN.md"
    target.write_bytes(b"original\n")
    alias = tmp_path / "alias.md"
    os.link(target, alias)

    with pytest.raises(UnsupportedSourceLinkError):
        service_module._atomic_write_bytes(target, b"new content\n")

    assert target.read_bytes() == b"original\n"
    assert alias.read_bytes() == b"original\n"
    assert os.stat(target).st_ino == os.stat(alias).st_ino

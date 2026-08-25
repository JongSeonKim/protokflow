"""Tests for DESIGN.md in-place patch write-through."""

from __future__ import annotations

import difflib
import hashlib
import os
from pathlib import Path
from stat import S_ISDIR

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransaction

from backend.app.protokflow.core.design_md import parse_design_md, split_front_matter
from backend.app.protokflow.core.errors import (
    MissingSourceFileError,
    UnknownDesignSystemError,
    UnknownTokenPathError,
    UnbackedDesignSystemError,
)
from backend.app.protokflow.crud.crud_design_system import design_system_dao
from backend.app.protokflow.crud.crud_design_token import design_token_dao
from backend.app.protokflow.model import DesignSystem
from backend.app.protokflow.service import design_system_service as service_module
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


async def test_patch_parses_the_document_only_once(
    tmp_path: Path,
    test_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The patched form is derived, not re-parsed, so the hot path pays one parse."""
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
        repo_root=tmp_path, slug="default", token_patches={"colors.primary": "#0B0E14"}
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

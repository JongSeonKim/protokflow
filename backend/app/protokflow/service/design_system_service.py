"""Index DESIGN.md files into the design-system storage tables."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from backend.app.protokflow.core.design_md import (
    ParsedDesignSystem,
    parse_design_md,
    serialize_design_md,
)
from backend.app.protokflow.core.discovery import (
    DiscoveredDesignFile,
    discover_design_files,
)
from backend.app.protokflow.core.errors import (
    InvalidEncodingError,
    MissingSourceFileError,
    UnknownDesignSystemError,
    UnbackedDesignSystemError,
)
from backend.app.protokflow.crud.crud_design_system import design_system_dao
from backend.app.protokflow.crud.crud_design_token import design_token_dao
from backend.app.protokflow.model import DesignSystem, DesignToken
from backend.app.protokflow.model.types import utcnow
from backend.database import db


@dataclass(frozen=True, slots=True)
class _ParsedDesignFile:
    """Parsed source data prepared before opening the database transaction."""

    slug: str
    source_path: str
    source_digest: str
    source_mtime_ns: int
    source_size: int
    parsed: ParsedDesignSystem


def _parse_design_content(path: Path, content: bytes) -> ParsedDesignSystem:
    """Decode and parse DESIGN.md bytes without database access."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise InvalidEncodingError(f"{path} is not valid UTF-8: {error}") from error
    return parse_design_md(text)


def _read_design_file(
    design_file: DiscoveredDesignFile,
) -> tuple[bytes, ParsedDesignSystem]:
    """Read one design file, mapping a missing source to a domain error."""
    try:
        content = design_file.path.read_bytes()
    except (FileNotFoundError, IsADirectoryError) as error:
        raise MissingSourceFileError(
            f"source file for design system '{design_file.slug}' is missing: "
            f"{design_file.path}"
        ) from error
    return content, _parse_design_content(design_file.path, content)


def _parse_design_file(
    repo_root: Path, design_file: DiscoveredDesignFile
) -> _ParsedDesignFile:
    """Read, digest, and parse one discovered file without database access."""
    content, parsed = _read_design_file(design_file)
    stat = design_file.path.stat()
    return _ParsedDesignFile(
        slug=design_file.slug,
        source_path=design_file.path.relative_to(repo_root).as_posix(),
        source_digest=hashlib.sha256(content).hexdigest(),
        source_mtime_ns=stat.st_mtime_ns,
        source_size=stat.st_size,
        parsed=parsed,
    )


def _design_system_from(parsed_file: _ParsedDesignFile) -> DesignSystem:
    """Build a storage model from already validated source data."""
    parsed = parsed_file.parsed
    return DesignSystem(
        slug=parsed_file.slug,
        title=parsed.title or parsed_file.slug,
        description=parsed.description,
        spec_version=parsed.spec_version,
        front_matter_extras=parsed.front_matter_extras,
        front_matter_raw=parsed.front_matter_raw or "",
        guide_markdown=parsed.guide_markdown,
        source_path=parsed_file.source_path,
        source_digest=parsed_file.source_digest,
        source_mtime_ns=parsed_file.source_mtime_ns,
        source_size=parsed_file.source_size,
        synced_at=utcnow(),
    )


async def _persist_design_files(
    parsed_files: list[_ParsedDesignFile],
) -> list[DesignSystem]:
    """Upsert systems and replace their tokens in one caller-visible transaction."""
    if not parsed_files:
        return []
    async with db.async_db_session.begin() as session:
        systems: list[DesignSystem] = []
        for parsed_file in parsed_files:
            design_system = await design_system_dao.upsert(
                session, _design_system_from(parsed_file)
            )
            await design_token_dao.replace(
                session,
                design_system.id,
                [
                    DesignToken(
                        design_system.id,
                        token.tier,
                        token.token_path,
                        token.value,
                    )
                    for token in parsed_file.parsed.tokens
                ],
            )
            systems.append(design_system)
        return systems


def _atomic_write_bytes(path: Path, data: bytes) -> os.stat_result:
    """Write bytes to a file atomically via a same-directory temporary file.

    A partial write must never corrupt a Git-tracked DESIGN.md file, so the
    replacement is prepared beside the target and swapped in with rename.
    Returns the post-replacement file metadata for sync bookkeeping.
    """
    descriptor, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        shutil.copymode(path, temp_path)
        os.replace(temp_path, path)
        return path.stat()
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


class DesignSystemService:
    """Design system service class."""

    @staticmethod
    async def index_all(*, repo_root: Path) -> list[DesignSystem]:
        """
        Index every DESIGN.md file discovered in a repository

        :param repo_root: Repository root path
        :return:
        """
        root = Path(repo_root).resolve()
        parsed_files = [
            _parse_design_file(root, design_file)
            for design_file in discover_design_files(root)
        ]

        return await _persist_design_files(parsed_files)

    @staticmethod
    async def apply_token_patch(
        *,
        repo_root: Path,
        slug: str,
        token_patches: Mapping[str, str],
    ) -> DesignSystem:
        """
        Patch token values in a DESIGN.md file and write the change through to storage

        The file is the recovery source of truth, so the on-disk document is
        patched in-place first and the database is committed afterwards; a
        database failure leaves the file ahead for change detection to re-index.

        :param repo_root: Repository root path
        :param slug: Design system slug
        :param token_patches: Mapping of token paths to new values
        :return:
        """
        root = Path(repo_root).resolve()
        async with db.async_db_session() as session:
            system = await design_system_dao.get_by_slug(session, slug)
        if system is None:
            raise UnknownDesignSystemError(f"design system not found: {slug}")
        if system.source_path is None:
            raise UnbackedDesignSystemError(
                f"design system '{slug}' has no linked DESIGN.md file; "
                f"token patches require a file-backed system"
            )

        source_path = root / system.source_path
        source = DiscoveredDesignFile(slug=slug, path=source_path)
        _, current = await asyncio.to_thread(_read_design_file, source)
        patched_text = serialize_design_md(
            front_matter_raw=current.front_matter_raw,
            closing_fence=current.closing_fence,
            guide_markdown=current.guide_markdown,
            eol=current.eol,
            token_patches=token_patches,
        )

        patched_bytes = patched_text.encode("utf-8")
        stat = await asyncio.to_thread(_atomic_write_bytes, source_path, patched_bytes)
        written = _ParsedDesignFile(
            slug=slug,
            source_path=system.source_path,
            source_digest=hashlib.sha256(patched_bytes).hexdigest(),
            source_mtime_ns=stat.st_mtime_ns,
            source_size=len(patched_bytes),
            parsed=_parse_design_content(source_path, patched_bytes),
        )
        persisted = await _persist_design_files([written])
        return persisted[0]


design_system_service: DesignSystemService = DesignSystemService()

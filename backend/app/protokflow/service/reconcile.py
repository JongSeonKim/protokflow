"""External-change reconciliation for indexed DESIGN.md sources (R21, KTD6)."""

from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.protokflow.core.design_md import (
    ParsedDesignSystem,
    parse_design_md,
)
from backend.app.protokflow.core.discovery import DiscoveredDesignFile
from backend.app.protokflow.error.design_md import InvalidEncodingError
from backend.app.protokflow.crud.crud_design_system import design_system_dao
from backend.app.protokflow.crud.crud_design_token import design_token_dao
from backend.app.protokflow.model import DesignSystem, DesignToken
from backend.app.protokflow.model.types import utcnow
from backend.app.protokflow.error.storage import (
    MissingSourceFileError,
    TokenReparentingError,
    UnknownDesignSystemError,
)
from backend.database import db


@dataclass(frozen=True, slots=True)
class ParsedDesignFile:
    """Parsed source data prepared before opening the database transaction."""

    slug: str
    source_root: str
    source_path: str
    source_digest: str
    source_mtime_ns: int
    source_size: int
    parsed: ParsedDesignSystem


def parse_design_content(path: Path, content: bytes) -> ParsedDesignSystem:
    """Decode and parse DESIGN.md bytes without database access."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise InvalidEncodingError(f"{path} is not valid UTF-8: {error}") from error
    return parse_design_md(text)


def read_source_bytes(
    path: Path, *, slug: str | None = None
) -> tuple[bytes, os.stat_result]:
    """Read one source file's bytes and stat from a single open descriptor.

    The bytes and the metadata are taken from one open descriptor so that a
    digest computed from them always describes the same file version. Reading
    and stat-ing separately lets an external save land between them, which
    pairs the digest of one version with the metadata of another and defeats
    the change pre-check.
    """
    try:
        with path.open("rb") as handle:
            content = handle.read()
            stat = os.fstat(handle.fileno())
    except (FileNotFoundError, IsADirectoryError) as error:
        subject = f"design system '{slug}'" if slug is not None else "source"
        raise MissingSourceFileError(
            f"source file for {subject} is missing: {path}"
        ) from error
    return content, stat


def read_design_file(
    design_file: DiscoveredDesignFile,
) -> tuple[bytes, os.stat_result, ParsedDesignSystem]:
    """Read one design file, mapping a missing source to a domain error."""
    content, stat = read_source_bytes(design_file.path, slug=design_file.slug)
    return content, stat, parse_design_content(design_file.path, content)


def parse_design_file(
    repo_root: Path, design_file: DiscoveredDesignFile
) -> ParsedDesignFile:
    """Read, digest, and parse one discovered file without database access."""
    content, stat, parsed = read_design_file(design_file)
    return ParsedDesignFile(
        slug=design_file.slug,
        source_root=repo_root.as_posix(),
        source_path=design_file.path.relative_to(repo_root).as_posix(),
        source_digest=hashlib.sha256(content).hexdigest(),
        source_mtime_ns=stat.st_mtime_ns,
        source_size=stat.st_size,
        parsed=parsed,
    )


def build_design_system(parsed_file: ParsedDesignFile) -> DesignSystem:
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
        source_root=parsed_file.source_root,
        source_path=parsed_file.source_path,
        source_digest=parsed_file.source_digest,
        source_mtime_ns=parsed_file.source_mtime_ns,
        source_size=parsed_file.source_size,
        synced_at=utcnow(),
    )


def build_design_tokens(
    parsed_file: ParsedDesignFile, design_system_id: str
) -> list[DesignToken]:
    """Build storage token models from validated source data."""
    tokens = [
        DesignToken(
            design_system_id,
            token.tier,
            token.token_path,
            token.value,
        )
        for token in parsed_file.parsed.tokens
    ]
    for token in tokens:
        if token.design_system_id != design_system_id:
            raise TokenReparentingError(
                f"cannot reparent token '{token.token_path}' from design system "
                f"'{token.design_system_id}' to '{design_system_id}'"
            )
    return tokens


async def upsert_parsed_file(
    session: AsyncSession, parsed_file: ParsedDesignFile
) -> DesignSystem:
    """Upsert one parsed file and replace its tokens on the caller's session."""
    design_system = await design_system_dao.upsert(
        session, build_design_system(parsed_file)
    )
    await design_token_dao.replace(
        session,
        design_system.id,
        build_design_tokens(parsed_file, design_system.id),
    )
    return design_system


@dataclass(frozen=True, slots=True)
class ReconciledSystem:
    """Refreshed design-system row plus the query-time staleness verdict."""

    system: DesignSystem
    stale: bool


def stat_source(path: Path) -> os.stat_result | None:
    """Stat a source file, returning None once it is gone from disk."""
    try:
        return path.stat()
    except FileNotFoundError, NotADirectoryError:
        return None


def stat_matches(system: DesignSystem, stat: os.stat_result) -> bool:
    """Return True when stored (mtime_ns, size) still describes the file.

    The early return relies on the write-through invariant that the stored
    digest and stat describe the same bytes: the file is only read and hashed
    after this cheap comparison disagrees (R21).
    """
    return (
        system.source_mtime_ns is not None
        and system.source_size is not None
        and system.source_mtime_ns == stat.st_mtime_ns
        and system.source_size == stat.st_size
    )


async def _refresh_touched_metadata(slug: str, stat: os.stat_result) -> DesignSystem:
    """Record new (mtime_ns, size) for touched-but-identical bytes, no reparse."""
    async with db.async_db_session.begin() as session:
        system = await design_system_dao.get_by_slug(session, slug)
        if system is None:
            raise UnknownDesignSystemError(
                f"design system '{slug}' was deleted while its source was "
                f"being reconciled"
            )
        system.source_mtime_ns = stat.st_mtime_ns
        system.source_size = stat.st_size
        return system


async def reconcile_design_system(
    *, root: Path, system: DesignSystem, for_patch: bool
) -> ReconciledSystem:
    """Absorb external source changes before a service entry point acts.

    Decision order (KTD6): stat pre-check on (mtime_ns, size); on mismatch
    compute sha256 and compare with source_digest — equal means a touched file
    and refreshes metadata only; different means the file changed and the
    system is re-indexed from it. A missing file keeps the DB row and reports
    stale for queries, while patch entries reject it because a patch must
    always write the file.
    """
    if system.source_path is None:
        return ReconciledSystem(system=system, stale=False)

    source_path = root / system.source_path
    stat = await asyncio.to_thread(stat_source, source_path)
    if stat is None:
        if for_patch:
            raise MissingSourceFileError(
                f"source file for design system '{system.slug}' is missing: "
                f"{source_path}"
            )
        return ReconciledSystem(system=system, stale=True)
    if stat_matches(system, stat):
        return ReconciledSystem(system=system, stale=False)

    content, read_stat = await asyncio.to_thread(
        read_source_bytes, source_path, slug=system.slug
    )
    digest = hashlib.sha256(content).hexdigest()
    if system.source_digest is not None and digest == system.source_digest:
        refreshed = await _refresh_touched_metadata(system.slug, read_stat)
        return ReconciledSystem(system=refreshed, stale=False)

    parsed = await asyncio.to_thread(parse_design_content, source_path, content)
    parsed_file = ParsedDesignFile(
        slug=system.slug,
        source_root=root.as_posix(),
        source_path=system.source_path,
        source_digest=digest,
        source_mtime_ns=read_stat.st_mtime_ns,
        source_size=read_stat.st_size,
        parsed=parsed,
    )
    async with db.async_db_session.begin() as session:
        if await design_system_dao.get_by_slug(session, system.slug) is None:
            raise UnknownDesignSystemError(
                f"design system '{system.slug}' was deleted while its source "
                f"was being reconciled"
            )
        refreshed = await upsert_parsed_file(session, parsed_file)
    return ReconciledSystem(system=refreshed, stale=False)

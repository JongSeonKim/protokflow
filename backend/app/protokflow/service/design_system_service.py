"""Index DESIGN.md files into the design-system storage tables."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from backend.app.protokflow.core.design_md import ParsedDesignSystem, parse_design_md
from backend.app.protokflow.core.discovery import (
    DiscoveredDesignFile,
    discover_design_files,
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


def _parse_design_file(
    repo_root: Path, design_file: DiscoveredDesignFile
) -> _ParsedDesignFile:
    """Read, digest, and parse one discovered file without database access."""
    content = design_file.path.read_bytes()
    parsed = parse_design_md(content.decode("utf-8"))
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


class DesignSystemService:
    """Design system service class."""

    @staticmethod
    async def index(
        *, repo_root: Path, design_file: DiscoveredDesignFile
    ) -> DesignSystem:
        """
        Index one discovered DESIGN.md file

        :param repo_root: Repository root path
        :param design_file: Discovered design file
        :return:
        """
        root = Path(repo_root).resolve()
        parsed_file = _parse_design_file(root, design_file)
        return (await _persist_design_files([parsed_file]))[0]

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


design_system_service: DesignSystemService = DesignSystemService()

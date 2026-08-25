"""Index DESIGN.md files into design-system storage and patch tokens back to source."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from backend.app.protokflow.core.design_md import (
    ParsedDesignSystem,
    parse_design_md,
    serialize_design_md,
    split_front_matter,
)
from backend.app.protokflow.core.discovery import (
    DiscoveredDesignFile,
    discover_design_files,
)
from backend.app.protokflow.core.errors import InvalidEncodingError
from backend.app.protokflow.crud.crud_design_system import design_system_dao
from backend.app.protokflow.crud.crud_design_token import design_token_dao
from backend.app.protokflow.model import DesignSystem, DesignToken
from backend.app.protokflow.model.types import utcnow
from backend.app.protokflow.service.errors import (
    ConcurrentModificationError,
    MissingSourceFileError,
    SourceWriteError,
    TokenReparentingError,
    UnknownDesignSystemError,
    UnbackedDesignSystemError,
    UnsupportedSourceLinkError,
)
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
) -> tuple[bytes, os.stat_result, ParsedDesignSystem]:
    """Read one design file, mapping a missing source to a domain error.

    The bytes and the metadata are taken from one open descriptor so that the
    digest, mtime, and size recorded for a design system always describe the
    same file version. Reading and stat-ing separately lets an external save
    land between them, which stores the digest of one version beside the
    metadata of another and defeats the change pre-check.
    """
    try:
        with design_file.path.open("rb") as handle:
            content = handle.read()
            stat = os.fstat(handle.fileno())
    except (FileNotFoundError, IsADirectoryError) as error:
        raise MissingSourceFileError(
            f"source file for design system '{design_file.slug}' is missing: "
            f"{design_file.path}"
        ) from error
    return content, stat, _parse_design_content(design_file.path, content)


def _parse_design_file(
    repo_root: Path, design_file: DiscoveredDesignFile
) -> _ParsedDesignFile:
    """Read, digest, and parse one discovered file without database access."""
    content, stat, parsed = _read_design_file(design_file)
    return _ParsedDesignFile(
        slug=design_file.slug,
        source_path=design_file.path.relative_to(repo_root).as_posix(),
        source_digest=hashlib.sha256(content).hexdigest(),
        source_mtime_ns=stat.st_mtime_ns,
        source_size=stat.st_size,
        parsed=parsed,
    )


def _build_design_system(parsed_file: _ParsedDesignFile) -> DesignSystem:
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


def _build_design_tokens(
    parsed_file: _ParsedDesignFile, design_system_id: str
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
                session, _build_design_system(parsed_file)
            )
            await design_token_dao.replace(
                session,
                design_system.id,
                _build_design_tokens(parsed_file, design_system.id),
            )
            systems.append(design_system)
        return systems


def _fsync_directory(directory: Path) -> None:
    """Flush a directory entry so a completed rename survives a crash.

    Not every platform lets a directory be opened for fsync, and a filesystem
    that refuses is not a write failure, so an unsupported call is ignored.
    """
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _atomic_write_bytes(path: Path, data: bytes) -> os.stat_result:
    """Write bytes to a file atomically via a same-directory temporary file.

    The replacement is written beside the target and swapped in via rename
    to ensure atomic updates. File data and parent directory entries are synced
    to disk around the rename operation.

    Symlinks and hard links are rejected before writing to prevent breaking link
    targets during directory entry replacement. Disk failures raise
    SourceWriteError with the original OSError as __cause__ so callers only
    need to handle the storage-layer exception hierarchy.

    Returns the stat result from the temporary file descriptor before replacement,
    capturing the exact metadata of the written bytes.
    """
    try:
        stat_result = os.lstat(path)
    except FileNotFoundError as error:
        raise MissingSourceFileError(
            f"source file for design system is missing: {path}"
        ) from error
    except OSError as error:
        raise SourceWriteError(
            f"failed to inspect DESIGN.md source before atomic write: {path}: {error}"
        ) from error
    if os.path.islink(path) or stat_result.st_nlink > 1:
        raise UnsupportedSourceLinkError(
            f"DESIGN.md source is a symlink or hard link and cannot be "
            f"atomically replaced: {path}"
        )
    try:
        descriptor, temp_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
    except OSError as error:
        raise SourceWriteError(
            f"failed to create a temporary file beside DESIGN.md source: "
            f"{path}: {error}"
        ) from error
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            stat = os.fstat(handle.fileno())
        shutil.copymode(path, temp_path)
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
        return stat
    except BaseException as error:
        with contextlib.suppress(OSError):
            temp_path.unlink(missing_ok=True)
        if isinstance(error, OSError):
            raise SourceWriteError(
                f"failed to atomically write DESIGN.md source: {path}: {error}"
            ) from error
        raise


def _patched_parse(
    current: ParsedDesignSystem, patched_text: str, token_patches: Mapping[str, str]
) -> ParsedDesignSystem:
    """Derive the parsed form of a patched document without re-parsing it.

    A token path always resolves inside a foundation or component group, while
    the title, description, and spec version come from the modeled scalars and
    the extras from every other key. A value patch therefore cannot reach any
    field except the raw front matter text and the patched token values, so
    re-running the YAML parser over the emitted bytes would only reproduce what
    the caller already holds.
    """
    return replace(
        current,
        front_matter_raw=split_front_matter(patched_text).front_matter_raw,
        tokens=[
            replace(token, value=token_patches[token.token_path])
            if token.token_path in token_patches
            else token
            for token in current.tokens
        ],
    )


def _patch_and_write(
    slug: str,
    source_path_value: str,
    source_path: Path,
    current: ParsedDesignSystem,
    token_patches: Mapping[str, str],
) -> _ParsedDesignFile:
    """Serialize, write, and describe a patched document off the event loop.

    Serialization is the most expensive step in a token patch, so it shares the
    worker thread with the file write instead of blocking the loop that serves
    the preview.
    """
    patched_text = serialize_design_md(
        front_matter_raw=current.front_matter_raw,
        closing_fence=current.closing_fence,
        guide_markdown=current.guide_markdown,
        eol=current.eol,
        token_patches=token_patches,
    )
    patched_bytes = patched_text.encode("utf-8")
    digest = hashlib.sha256(patched_bytes).hexdigest()
    stat = _atomic_write_bytes(source_path, patched_bytes)
    return _ParsedDesignFile(
        slug=slug,
        source_path=source_path_value,
        source_digest=digest,
        source_mtime_ns=stat.st_mtime_ns,
        source_size=stat.st_size,
        parsed=_patched_parse(current, patched_text, token_patches),
    )


class DesignSystemService:
    """Design system service class."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, slug: str) -> asyncio.Lock:
        lock = self._locks.get(slug)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[slug] = lock
        return lock

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

    async def apply_token_patch(
        self,
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
        if not token_patches:
            # An empty patch changes nothing, so it must not rewrite the file or
            # bump its mtime; return the current persisted state unchanged.
            async with db.async_db_session() as session:
                system = await design_system_dao.get_by_slug(session, slug)
            if system is None:
                raise UnknownDesignSystemError(f"design system not found: {slug}")
            return system
        root = Path(repo_root).resolve()
        async with self._lock_for(slug):
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
            content, _, current = await asyncio.to_thread(_read_design_file, source)
            disk_digest = hashlib.sha256(content).hexdigest()
            if system.source_digest is not None and disk_digest != system.source_digest:
                raise ConcurrentModificationError(
                    f"source file for design system '{slug}' was modified concurrently "
                    f"(expected digest '{system.source_digest}', found '{disk_digest}'); "
                    f"refetch latest state and retry"
                )

            written = await asyncio.to_thread(
                _patch_and_write,
                slug,
                system.source_path,
                source_path,
                current,
                token_patches,
            )
            persisted = await _persist_design_files([written])
            return persisted[0]


design_system_service: DesignSystemService = DesignSystemService()

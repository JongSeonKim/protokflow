"""Filesystem adapter for observing and parsing DESIGN.md sources.

This module has no database or service-policy dependencies. It reports
source-file changes; callers decide how to react.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from backend.app.protokflow.core.design_md import ParsedDesignSystem, parse_design_md
from backend.app.protokflow.core.discovery import DiscoveredDesignFile
from backend.app.protokflow.error.design_md import InvalidEncodingError
from backend.app.protokflow.error.storage import MissingSourceFileError


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """The source version fields persisted with a file-backed design system."""

    source_digest: str | None
    source_mtime_ns: int | None
    source_size: int | None


@dataclass(frozen=True, slots=True)
class DesignSourceSnapshot:
    """Parsed source data prepared before opening a database transaction."""

    slug: str
    source_root: str
    source_path: str
    source_digest: str
    source_mtime_ns: int
    source_size: int
    parsed: ParsedDesignSystem


class SourceChange(StrEnum):
    """Outcome categories returned by source observation."""

    UNCHANGED = "unchanged"
    TOUCHED = "touched"
    CHANGED = "changed"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class SourceObservation:
    """Result of a source observation with lazily-populated fields."""

    change: SourceChange
    metadata: SourceMetadata | None = None
    snapshot: DesignSourceSnapshot | None = None


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
    """Read bytes and stat from a single open file descriptor.

    Using one descriptor avoids a TOCTOU gap where a concurrent write
    between separate read and stat calls would leave the digest and
    metadata inconsistent.
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
    """Read and parse one discovered DESIGN.md file."""
    content, stat = read_source_bytes(design_file.path, slug=design_file.slug)
    return content, stat, parse_design_content(design_file.path, content)


def parse_design_file(
    repo_root: Path, design_file: DiscoveredDesignFile
) -> DesignSourceSnapshot:
    """Read, digest, and parse one discovered file without database access."""
    content, stat, parsed = read_design_file(design_file)
    return DesignSourceSnapshot(
        slug=design_file.slug,
        source_root=repo_root.as_posix(),
        source_path=design_file.path.relative_to(repo_root).as_posix(),
        source_digest=hashlib.sha256(content).hexdigest(),
        source_mtime_ns=stat.st_mtime_ns,
        source_size=stat.st_size,
        parsed=parsed,
    )


def stat_source(path: Path) -> os.stat_result | None:
    """Stat a source file, returning ``None`` when it no longer exists."""
    try:
        return path.stat()
    except FileNotFoundError, NotADirectoryError:
        return None


def stat_matches(metadata: SourceMetadata, stat: os.stat_result) -> bool:
    """Return whether persisted `(mtime_ns, size)` still describes the file."""
    return (
        metadata.source_mtime_ns is not None
        and metadata.source_size is not None
        and metadata.source_mtime_ns == stat.st_mtime_ns
        and metadata.source_size == stat.st_size
    )


def observe_design_source(
    root: Path,
    *,
    slug: str,
    source_path: str,
    previous: SourceMetadata,
) -> SourceObservation:
    """Observe a file-backed source and classify its change state.

    The outcome enum is total: a source that disappears between the stat and
    the read — the window a branch switch opens — is reported as ``MISSING``
    like one that was already gone, leaving the query-versus-patch policy to
    the caller instead of raising through it.
    """
    path = root / source_path
    stat = stat_source(path)
    if stat is None:
        return SourceObservation(change=SourceChange.MISSING)
    if stat_matches(previous, stat):
        return SourceObservation(change=SourceChange.UNCHANGED)

    try:
        content, read_stat = read_source_bytes(path, slug=slug)
    except MissingSourceFileError:
        return SourceObservation(change=SourceChange.MISSING)
    digest = hashlib.sha256(content).hexdigest()
    metadata = SourceMetadata(
        source_digest=digest,
        source_mtime_ns=read_stat.st_mtime_ns,
        source_size=read_stat.st_size,
    )
    if previous.source_digest is not None and digest == previous.source_digest:
        return SourceObservation(change=SourceChange.TOUCHED, metadata=metadata)

    return SourceObservation(
        change=SourceChange.CHANGED,
        snapshot=DesignSourceSnapshot(
            slug=slug,
            source_root=root.as_posix(),
            source_path=source_path,
            source_digest=digest,
            source_mtime_ns=read_stat.st_mtime_ns,
            source_size=read_stat.st_size,
            parsed=parse_design_content(path, content),
        ),
    )

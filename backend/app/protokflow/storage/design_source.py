"""Filesystem adapter for observing, parsing, and patching DESIGN.md sources.

This module has no database or service-policy dependencies. It reports
source-file changes and performs atomic write-through of token patches;
callers own transaction lifecycle and decide how to react.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from backend.app.protokflow.core.design_md import (
    ParsedDesignSystem,
    derive_patched_parse,
    parse_design_md,
    serialize_design_md,
)
from backend.app.protokflow.core.discovery import DiscoveredDesignFile
from backend.app.protokflow.error.design_md import InvalidEncodingError
from backend.app.protokflow.error.storage import (
    ConcurrentModificationError,
    MissingSourceFileError,
    SourceWriteError,
    UnsupportedSourceLinkError,
)


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


def atomic_write_bytes(
    path: Path, data: bytes, *, expected_digest: str | None = None
) -> os.stat_result:
    """Write bytes to a file atomically via a same-directory temporary file.

    The replacement is written beside the target and swapped in via rename
    to ensure atomic updates. File data and parent directory entries are synced
    to disk around the rename.

    When ``expected_digest`` is provided, the original is re-read just before
    the temporary file is created and compared against it (compare-and-swap).
    A mismatch raises :class:`ConcurrentModificationError` without replacing
    the file. The residual verify-to-replace window is inherent to POSIX and
    kept minimal.

    Symlinks and hard links are rejected to avoid corrupting link targets.
    Disk failures raise :class:`SourceWriteError` with the original
    :class:`OSError` as ``__cause__``.

    Returns the stat result from the temporary file descriptor before
    replacement.
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
    if expected_digest is not None:
        try:
            current, _ = read_source_bytes(path)
        except MissingSourceFileError:
            raise
        except OSError as error:
            raise SourceWriteError(
                f"failed to re-read DESIGN.md source before atomic write: "
                f"{path}: {error}"
            ) from error
        current_digest = hashlib.sha256(current).hexdigest()
        if current_digest != expected_digest:
            raise ConcurrentModificationError(
                f"source file changed between the entry pre-check and the "
                f"atomic write (expected digest '{expected_digest}', found "
                f"'{current_digest}'); refetch latest state and retry"
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


def write_token_patch(
    slug: str,
    repo_root: Path,
    source_path_value: str,
    current: ParsedDesignSystem,
    token_patches: Mapping[str, str],
    entry_digest: str,
) -> DesignSourceSnapshot:
    """Serialize and atomically write a patched document in a worker thread.

    ``entry_digest`` is the CAS baseline from the entry-point observation.
    A concurrent modification between the CAS check and the atomic rename
    triggers :class:`ConcurrentModificationError`.
    """
    source_path = repo_root / source_path_value
    patched_text = serialize_design_md(
        front_matter_raw=current.front_matter_raw,
        closing_fence=current.closing_fence,
        guide_markdown=current.guide_markdown,
        eol=current.eol,
        token_patches=token_patches,
    )
    patched_bytes = patched_text.encode("utf-8")
    digest = hashlib.sha256(patched_bytes).hexdigest()
    stat = atomic_write_bytes(source_path, patched_bytes, expected_digest=entry_digest)
    return DesignSourceSnapshot(
        slug=slug,
        source_root=repo_root.as_posix(),
        source_path=source_path_value,
        source_digest=digest,
        source_mtime_ns=stat.st_mtime_ns,
        source_size=stat.st_size,
        parsed=derive_patched_parse(current, patched_text, token_patches),
    )

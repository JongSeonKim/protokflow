"""Index DESIGN.md files into storage and write token patches back to source."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from backend.app.protokflow.core.design_md import (
    ParsedDesignSystem,
    serialize_design_md,
    split_front_matter,
)
from backend.app.protokflow.core.discovery import (
    DiscoveredDesignFile,
    discover_design_files,
)
from backend.app.protokflow.crud.crud_design_system import design_system_dao
from backend.app.protokflow.crud.crud_design_token import design_token_dao
from backend.app.protokflow.model import DesignSystem, DesignToken
from backend.app.protokflow.storage.design_source import (
    DesignSourceSnapshot,
    SourceChange,
    SourceMetadata,
    observe_design_source,
    parse_design_file,
    read_design_file,
    read_source_bytes,
)
from backend.app.protokflow.storage.design_system_store import (
    refresh_source_metadata,
    sync_source_snapshot,
)
from backend.app.protokflow.error.storage import (
    ConcurrentModificationError,
    MissingSourceFileError,
    SourceRootMismatchError,
    SourceWriteError,
    UnknownDesignSystemError,
    UnbackedDesignSystemError,
    UnsupportedSourceLinkError,
)
from backend.database import db


@dataclass(frozen=True, slots=True)
class DesignSystemDetail:
    """Query result: the system row, its tokens, and the derived stale flag."""

    system: DesignSystem
    tokens: Sequence[DesignToken]
    stale: bool


@dataclass(frozen=True, slots=True)
class ReconciledSystem:
    """Result of reconciling a persisted system against its source file.

    ``missing`` indicates the source file was absent; callers decide whether
    that means a stale query result or a rejected patch.
    """

    system: DesignSystem
    missing: bool = False
    snapshot: DesignSourceSnapshot | None = None


async def _persist_token_patch(written: DesignSourceSnapshot) -> DesignSystem:
    """Persist a patched file, rejecting revival of a row deleted mid-patch.

    The row is rechecked inside the write transaction. If the system was
    deleted while the file was being patched, the error surfaces instead of
    recreating the row. The patched file remains on disk and is re-imported
    on the next index run.
    """
    async with db.async_db_session.begin() as session:
        existing = await design_system_dao.get_by_slug(session, written.slug)
        if existing is None:
            raise UnknownDesignSystemError(
                f"design system '{written.slug}' was deleted while its source "
                f"file was being patched; the patched file stays ahead and the "
                f"next index run will re-import it"
            )
        return await sync_source_snapshot(session, written, existing=existing)


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


def _atomic_write_bytes(
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


def _patched_parse(
    current: ParsedDesignSystem, patched_text: str, token_patches: Mapping[str, str]
) -> ParsedDesignSystem:
    """Derive the parsed form of a patched document without re-parsing it.

    A token path always resolves inside a foundation or component group, while
    the title, description, and spec version come from the modeled scalars
    and the extras from every other key. A value patch therefore cannot reach
    any field except the raw front matter text and the patched token values, so
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
    stat = _atomic_write_bytes(source_path, patched_bytes, expected_digest=entry_digest)
    return DesignSourceSnapshot(
        slug=slug,
        source_root=repo_root.as_posix(),
        source_path=source_path_value,
        source_digest=digest,
        source_mtime_ns=stat.st_mtime_ns,
        source_size=stat.st_size,
        parsed=_patched_parse(current, patched_text, token_patches),
    )


class DesignSystemService:
    """Design system service class."""

    def __init__(self) -> None:
        self._index_lock = asyncio.Lock()
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, slug: str) -> asyncio.Lock:
        lock = self._locks.get(slug)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[slug] = lock
        return lock

    @staticmethod
    async def _require_known_slug(slug: str) -> None:
        """Reject an unknown slug before it can allocate a per-slug lock."""
        async with db.async_db_session() as session:
            if await design_system_dao.get_by_slug(session, slug) is None:
                raise UnknownDesignSystemError(f"design system not found: {slug}")

    async def _reconcile_source(
        self, root: Path, system: DesignSystem
    ) -> ReconciledSystem:
        """Reconcile a persisted system against its source file.

        Delegates filesystem observation to the storage adapter and manages
        session lifetime and row rechecks here. A row deleted during
        reconciliation surfaces as an error instead of being recreated.
        """
        if system.source_path is None:
            return ReconciledSystem(system=system)

        observation = await asyncio.to_thread(
            observe_design_source,
            root,
            slug=system.slug,
            source_path=system.source_path,
            previous=SourceMetadata(
                source_digest=system.source_digest,
                source_mtime_ns=system.source_mtime_ns,
                source_size=system.source_size,
            ),
        )
        if observation.change is SourceChange.MISSING:
            return ReconciledSystem(system=system, missing=True)
        if observation.change is SourceChange.UNCHANGED:
            return ReconciledSystem(system=system)
        if observation.change is SourceChange.TOUCHED:
            if observation.metadata is None:  # pragma: no cover - adapter invariant
                raise RuntimeError("touch observation missing source metadata")
            async with db.async_db_session.begin() as session:
                refreshed = await refresh_source_metadata(
                    session, system.slug, observation.metadata
                )
            return ReconciledSystem(system=refreshed)

        if observation.snapshot is None:  # pragma: no cover - adapter invariant
            raise RuntimeError("changed observation missing source snapshot")
        async with db.async_db_session.begin() as session:
            existing = await design_system_dao.get_by_slug(session, system.slug)
            if existing is None:
                raise UnknownDesignSystemError(
                    f"design system '{system.slug}' was deleted while its source "
                    f"was being reconciled"
                )
            refreshed = await sync_source_snapshot(
                session, observation.snapshot, existing=existing
            )
        return ReconciledSystem(system=refreshed, snapshot=observation.snapshot)

    async def index_all(self, *, repo_root: Path) -> list[DesignSystem]:
        """
        Index every DESIGN.md file discovered in a repository.

        File-backed rows bound to this repository root that are absent from
        the discovery set are hard-deleted in the same transaction. An empty
        discovery set still triggers orphan deletion.

        :param repo_root: Repository root path
        :return:
        """
        async with self._index_lock:
            root = Path(repo_root).resolve()
            discovered = discover_design_files(root)
            parsed_files = [
                parse_design_file(root, design_file) for design_file in discovered
            ]

            async with db.async_db_session.begin() as session:
                systems = [
                    await sync_source_snapshot(session, parsed_file)
                    for parsed_file in parsed_files
                ]
                await design_system_dao.delete_orphan_sources(
                    session,
                    source_root=root.as_posix(),
                    keep_slugs=[design_file.slug for design_file in discovered],
                )
            return systems

    async def get(self, *, repo_root: Path, slug: str) -> DesignSystemDetail:
        """
        Query one design system with its tokens after reconciling its source.

        A ``(mtime_ns, size)`` pre-check detects external changes. A
        touched-but-identical file refreshes metadata only. A missing file
        keeps the persisted row and returns ``stale=True`` — no staleness
        column is persisted.

        :param repo_root: Repository root path
        :param slug: Design system slug
        :return:
        """
        root = Path(repo_root).resolve()
        await self._require_known_slug(slug)
        async with self._index_lock, self._lock_for(slug):
            async with db.async_db_session() as session:
                system = await design_system_dao.get_by_slug(session, slug)
            if system is None:
                raise UnknownDesignSystemError(f"design system not found: {slug}")
            if system.source_path is not None and (
                system.source_root is None or system.source_root != root.as_posix()
            ):
                raise SourceRootMismatchError(
                    f"design system '{slug}' was indexed from repository root "
                    f"'{system.source_root}' but the query targets "
                    f"'{root.as_posix()}'; re-index against this root to rebind it"
                )
            reconciled = await self._reconcile_source(root, system)
            async with db.async_db_session() as session:
                if await design_system_dao.get_by_slug(session, slug) is None:
                    raise UnknownDesignSystemError(
                        f"design system '{slug}' was deleted while it was being queried"
                    )
                tokens = list(
                    await design_token_dao.get_all(session, reconciled.system.id)
                )
            return DesignSystemDetail(
                system=reconciled.system,
                tokens=tokens,
                stale=reconciled.missing,
            )

    async def apply_token_patch(
        self,
        *,
        repo_root: Path,
        slug: str,
        token_patches: Mapping[str, str],
    ) -> DesignSystem:
        """
        Patch token values in a DESIGN.md file and write the change through to storage.

        Reconciliation runs before the patch, absorbing external changes
        detected since the last entry point. The file is written first and
        the database committed afterward; a failed commit leaves the file
        ahead of the database, and the next reconciliation absorbs the
        difference. A concurrent modification between the CAS check and the
        atomic rename raises :class:`ConcurrentModificationError`.

        A missing source file raises :class:`MissingSourceFileError`.
        A mismatched repository root raises :class:`SourceRootMismatchError`.

        :param repo_root: Repository root path
        :param slug: Design system slug
        :param token_patches: Mapping of token paths to new values
        :return:
        """
        root = Path(repo_root).resolve()
        await self._require_known_slug(slug)
        async with self._index_lock, self._lock_for(slug):
            async with db.async_db_session() as session:
                system = await design_system_dao.get_by_slug(session, slug)
            if system is None:
                raise UnknownDesignSystemError(f"design system not found: {slug}")
            if system.source_path is None:
                raise UnbackedDesignSystemError(
                    f"design system '{slug}' has no linked DESIGN.md file; "
                    f"token patches require a file-backed system"
                )
            if system.source_root is None or system.source_root != root.as_posix():
                raise SourceRootMismatchError(
                    f"design system '{slug}' was indexed from repository root "
                    f"'{system.source_root}' but the patch targets "
                    f"'{root.as_posix()}'; re-index against this root to rebind it"
                )
            source_path_value = system.source_path

            reconciled = await self._reconcile_source(root, system)
            if reconciled.missing:
                raise MissingSourceFileError(
                    f"source file for design system '{slug}' is missing: "
                    f"{root / source_path_value}"
                )
            if not token_patches:
                # Empty patch: no file rewrite or mtime change.
                return reconciled.system

            snapshot = reconciled.snapshot
            if snapshot is None:
                # Stat matched: read once for the parse the patch needs.
                source = DiscoveredDesignFile(slug=slug, path=root / source_path_value)
                content, _, current = await asyncio.to_thread(read_design_file, source)
                entry_digest = hashlib.sha256(content).hexdigest()
            else:
                # Snapshot from reconciliation serves as both patch baseline and CAS digest.
                current = snapshot.parsed
                entry_digest = snapshot.source_digest

            written = await asyncio.to_thread(
                _patch_and_write,
                slug,
                root,
                source_path_value,
                current,
                token_patches,
                entry_digest,
            )
            return await _persist_token_patch(written)


design_system_service: DesignSystemService = DesignSystemService()

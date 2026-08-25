"""Index DESIGN.md files into design-system storage and patch tokens back to source."""

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
from backend.app.protokflow.service.reconcile import (
    ParsedDesignFile,
    parse_design_file,
    read_design_file,
    read_source_bytes,
    reconcile_design_system,
    upsert_parsed_file,
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


async def _persist_token_patch(written: ParsedDesignFile) -> DesignSystem:
    """Persist one patched file without reviving a row deleted mid-patch.

    The slug's row is re-checked inside the write transaction: the file has
    already been patched by then, and re-creating a deleted row would silently
    undo a deletion. The patched file stays ahead of the database (KTD9) and
    the next index run re-imports it if the file is still present.
    """
    async with db.async_db_session.begin() as session:
        existing = await design_system_dao.get_by_slug(session, written.slug)
        if existing is None:
            raise UnknownDesignSystemError(
                f"design system '{written.slug}' was deleted while its source "
                f"file was being patched; the patched file stays ahead and the "
                f"next index run will re-import it"
            )
        return await upsert_parsed_file(session, written, existing=existing)


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
    to disk around the rename operation.

    When expected_digest is provided, the original is re-read just before the
    temporary file is created and compared against it (CAS): a mismatch means
    a writer landed in the window between the entry pre-check and this write,
    so ConcurrentModificationError is raised and nothing is replaced. The
    remaining verify-to-replace window cannot be eliminated on POSIX; the
    contract is to keep it minimal and fail safely on mismatch.

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
) -> ParsedDesignFile:
    """Serialize, write, and describe a patched document off the event loop.

    Serialization is the most expensive step in a token patch, so it shares the
    worker thread with the file write instead of blocking the loop that serves
    the preview. entry_digest is the CAS baseline observed at entry — the
    reconciliation snapshot's digest, or the digest of the post-entry read;
    a writer landing before the swap raises
    ConcurrentModificationError instead of clobbering its change.
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
    return ParsedDesignFile(
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

    async def index_all(self, *, repo_root: Path) -> list[DesignSystem]:
        """
        Index every DESIGN.md file discovered in a repository

        File-backed rows bound to this repository root that are absent from
        the discovery set are hard-deleted in the same transaction as the
        upserts (KTD11); an empty discovery set still deletes orphans, because
        it is the every-file-deleted path.

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
                    await upsert_parsed_file(session, parsed_file)
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
        Query one design system with its tokens after reconciling its source

        The (mtime_ns, size) pre-check runs first (KTD6): external changes are
        absorbed by re-indexing, a touched-but-identical file refreshes
        metadata only, and a missing file keeps the persisted row and reports
        stale=True as a query-time verdict — no staleness column is stored
        (KTD11).

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
            reconciled = await reconcile_design_system(
                root=root, system=system, for_patch=False
            )
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
                stale=reconciled.stale,
            )

    async def apply_token_patch(
        self,
        *,
        repo_root: Path,
        slug: str,
        token_patches: Mapping[str, str],
    ) -> DesignSystem:
        """
        Patch token values in a DESIGN.md file and write the change through to storage

        Every entry passes the reconciliation pre-check first (KTD6), so an
        external change that landed before the call — including a file left
        ahead by a failed database commit (KTD9) — is absorbed and the patch
        applies on top of the reconciled latest content. The concurrent-modification
        error is reserved for a real race: a writer landing after the entry
        pre-check but before the atomic write is caught by the CAS re-read and
        the swap never happens. A missing source file rejects the patch with
        MissingSourceFileError because a patch must always write the file.

        The file is the recovery source of truth, so the on-disk document is
        patched in-place first and the database is committed afterwards; a
        database failure leaves the file ahead for change detection to re-index.
        The resolved repo_root must match the root recorded at index time;
        otherwise the patch is rejected with SourceRootMismatchError.

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

            reconciled = await reconcile_design_system(
                root=root, system=system, for_patch=True
            )
            if not token_patches:
                # An empty patch changes nothing, so it must not rewrite the
                # file or bump its mtime; return the reconciled state unchanged.
                return reconciled.system

            snapshot = reconciled.snapshot
            if snapshot is None:
                # The stat pre-check matched, so the stored digest already
                # describes the current bytes; read once for the parse the
                # patch itself needs.
                source = DiscoveredDesignFile(slug=slug, path=root / source_path_value)
                content, _, current = await asyncio.to_thread(read_design_file, source)
                entry_digest = hashlib.sha256(content).hexdigest()
            else:
                # Reconciliation just read and parsed the changed source, so
                # its snapshot is both the patch baseline and the CAS digest;
                # the file is not read again here.
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

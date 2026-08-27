"""Index DESIGN.md files into storage and write token patches back to source."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path

from backend.app.protokflow.core.discovery import (
    DiscoveredDesignFile,
    discover_design_files,
)
from backend.app.protokflow.crud.crud_design_system import design_system_dao
from backend.app.protokflow.crud.crud_design_token import design_token_dao
from backend.app.protokflow.model import DesignSystem
from backend.app.protokflow.service.design_system_types import (
    DesignSystemDetail,
    ReconciledSystem,
)
from backend.app.protokflow.storage.design_source import (
    DesignSourceSnapshot,
    SourceChange,
    SourceMetadata,
    observe_design_source,
    parse_design_file,
    write_token_patch,
)
from backend.app.protokflow.storage.design_system_store import (
    refresh_source_metadata,
    sync_source_snapshot,
)
from backend.app.protokflow.error.storage import (
    MissingSourceFileError,
    SourceRootMismatchError,
    SourceRootNotFoundError,
    UnbackedDesignSystemError,
    UnknownDesignSystemError,
)
from backend.common.rwlock import AsyncReadWriteLock
from backend.database import db


class DesignSystemService:
    """Design system service class."""

    def __init__(self) -> None:
        self._index_lock = AsyncReadWriteLock()
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

    async def _persist_token_patch(self, written: DesignSourceSnapshot) -> DesignSystem:
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

    async def index_all(self, *, repo_root: Path) -> list[DesignSystem]:
        """
        Index every DESIGN.md file discovered in a repository.

        File-backed rows bound to this repository root that are absent from
        the discovery set are unbound in the same transaction: they survive as
        DB-only rows and a later run rebinds them by slug. An empty discovery
        set still unbinds, so deleting every DESIGN.md drops every binding —
        which is why a root that is not an existing directory is rejected
        rather than read as an empty repository.

        Indexing takes the write side of the index lock, excluding queries and
        patches for its duration.

        :param repo_root: Repository root path
        :raises SourceRootNotFoundError: The root is not an existing directory
        :return:
        """
        root = Path(repo_root).resolve()
        if not root.is_dir():
            raise SourceRootNotFoundError(
                f"repository root is not an existing directory: {root}; "
                f"indexing it would unbind every design system indexed from it"
            )
        async with self._index_lock.write():
            discovered = discover_design_files(root)
            parsed_files = await asyncio.to_thread(
                lambda: [
                    parse_design_file(root, design_file) for design_file in discovered
                ]
            )

            async with db.async_db_session.begin() as session:
                systems = [
                    await sync_source_snapshot(session, parsed_file)
                    for parsed_file in parsed_files
                ]
                await design_system_dao.unbind_orphan_sources(
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
        async with self._index_lock.read(), self._lock_for(slug):
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
        async with self._index_lock.read(), self._lock_for(slug):
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
                # Reconciliation returned no snapshot (the stat matched, or a
                # touch-only refresh ran): read and parse once for the patch.
                source = DiscoveredDesignFile(slug=slug, path=root / source_path_value)
                snapshot = await asyncio.to_thread(parse_design_file, root, source)
            # The snapshot serves as both the patch baseline and the CAS digest.
            current = snapshot.parsed
            entry_digest = snapshot.source_digest

            written = await asyncio.to_thread(
                write_token_patch,
                slug,
                root,
                source_path_value,
                current,
                token_patches,
                entry_digest,
            )
            return await self._persist_token_patch(written)


design_system_service: DesignSystemService = DesignSystemService()

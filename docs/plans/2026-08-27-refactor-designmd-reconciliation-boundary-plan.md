---
title: "DESIGN.md Reconciliation Boundary Refactor - Plan Brief"
type: refactor
date: 2026-08-27
origin: docs/plans/2026-08-24-1252-feat-designmd-storage-layer-plan.md
execution: code
---

# DESIGN.md Reconciliation Boundary Refactor

## Summary

`backend/app/protokflow/service/reconcile.py` currently combines filesystem
observation, parsing, ORM mapping, DAO composition, transaction creation, and
query-versus-patch policy. Split this mixed module so storage mechanisms live
under `storage/`, while `DesignSystemService` retains locks, use-case policy,
and transaction ownership.

The refactor must preserve the U6 external-change reconciliation behavior and
requires no database schema, public API, or product-contract change.

## Decision

- `storage` is a technical adapter boundary, not a new business layer.
- `storage/design_source.py` owns filesystem observation, reading, hashing, and
  parsing, with no database dependencies.
- `storage/design_system_store.py` owns ORM mapping and multi-DAO persistence
  operations, using only caller-provided sessions.
- `service/design_system_service.py` owns locks, repository-root validation,
  use-case-specific missing-file behavior, and session/transaction lifecycle.
- `crud/` remains limited to SQLAlchemy statements and never commits.
- Do not introduce a generic Repository, Unit of Work, Protocol, or compatibility
  alias in this refactor.

## Scope

### In scope

- Delete the mixed `service/reconcile.py` module after its responsibilities are
  relocated.
- Replace the `for_patch` policy flag with a neutral source-observation result.
- Centralize all session creation and transaction boundaries in the service.
- Reorganize tests around storage mechanisms and service behavior.
- Update the existing storage-layer plan to describe the resulting boundary.

### Out of scope

- Changes to reconciliation behavior, source-of-truth ordering, CAS semantics,
  orphan deletion, or stale-state policy.
- Database schema or migration changes.
- Changes to parser and serializer semantics in `core/design_md.py`.
- New filesystem watchers, background jobs, or cross-process locks.
- Public API, CLI, MCP, or ASGI adapter changes.

## U1. Extract the design-source adapter

**Files**

- Add `backend/app/protokflow/storage/__init__.py`.
- Add `backend/app/protokflow/storage/design_source.py`.
- Add `tests/app/protokflow/storage/__init__.py`.
- Add `tests/app/protokflow/storage/test_design_source.py`.
- Modify imports in `backend/app/protokflow/service/design_system_service.py`.

**Changes**

- Rename `ParsedDesignFile` to `DesignSourceSnapshot` and move it to the source
  adapter.
- Move `parse_design_content`, `read_source_bytes`, `read_design_file`,
  `parse_design_file`, `stat_source`, and `stat_matches` from
  `service/reconcile.py`.
- Introduce `SourceMetadata`, `SourceChange`, and `SourceObservation`.
- Implement `observe_design_source(...)` with four neutral outcomes:
  `UNCHANGED`, `TOUCHED`, `CHANGED`, and `MISSING`.
- Return new metadata for `TOUCHED` and a parsed `DesignSourceSnapshot` for
  `CHANGED`.
- Do not branch on query or patch intent and do not mutate the database.

**Boundary requirements**

- `design_source.py` may depend on the standard library, `core/design_md.py`,
  `core/discovery.py`, and storage/design parsing errors.
- It must not import SQLAlchemy, CRUD modules, ORM models, or
  `backend.database.db`.
- The service remains responsible for offloading blocking observation work with
  `asyncio.to_thread`.

**Tests**

- Matching `(mtime_ns, size)` returns `UNCHANGED` without reading file bytes.
- Touch-only changes return `TOUCHED` without reparsing.
- Same-size content changes and a 1ns mtime delta reach digest comparison.
- Changed content returns a snapshot whose digest and metadata describe the same
  opened file version.
- A missing source returns `MISSING` rather than selecting query or patch policy.
- Invalid UTF-8 and invalid DESIGN.md content preserve the existing errors.
- The documented stat-preserving edit detection boundary remains unchanged.

## U2. Extract source-to-database persistence

**Files**

- Add `backend/app/protokflow/storage/design_system_store.py`.
- Add `tests/app/protokflow/storage/test_design_system_store.py`.
- Modify `backend/app/protokflow/service/design_system_service.py`.
- Modify `tests/app/protokflow/service/test_indexing.py`.

**Changes**

- Move `build_design_system` and `build_design_tokens` into
  `design_system_store.py`.
- Replace `upsert_parsed_file` with `sync_source_snapshot(session, snapshot,
  existing=...)`.
- Add `refresh_source_metadata(session, slug, metadata)` for touch-only updates.
- Keep design-system upsert and token replacement together on the caller's
  session.
- Continue rejecting token reparenting.

**Boundary requirements**

- Every persistence operation receives an `AsyncSession` from its caller.
- The module must not call `async_db_session`, `begin`, `commit`, or `rollback`.
- The module must not perform filesystem I/O or select query-versus-patch policy.

**Tests**

- Snapshot synchronization upserts the design system and replaces its full token
  set without duplication.
- Touch-only refresh changes only `source_mtime_ns` and `source_size`.
- A caller-owned transaction can roll back all store changes.
- Persistence functions do not commit the supplied session.
- Token reparenting remains rejected.

## U3. Concentrate reconciliation policy in the service

**Files**

- Modify `backend/app/protokflow/service/design_system_service.py`.
- Delete `backend/app/protokflow/service/reconcile.py`.
- Modify `tests/app/protokflow/service/test_reconcile.py`.
- Modify `tests/app/protokflow/service/test_patch_reconciliation.py`.
- Modify `tests/app/protokflow/service/test_write_through.py`.

**Changes**

- Move `ReconciledSystem` into `design_system_service.py` as an internal result
  type.
- Add a private `_reconcile_source(root, system)` orchestration method.
- Have `_reconcile_source` call `observe_design_source` and handle outcomes as
  follows:
  - `UNCHANGED`: return the existing system without a write transaction.
  - `TOUCHED`: open a service-owned transaction and refresh metadata.
  - `CHANGED`: open a service-owned transaction, reload the existing row, and
    synchronize the snapshot.
  - `MISSING`: return a neutral missing result without changing the database.
- Remove the `for_patch` argument entirely.
- Make `get` translate `MISSING` to the persisted system and `stale=True`.
- Make `apply_token_patch` translate `MISSING` to
  `MissingSourceFileError`.
- Preserve snapshot reuse as the patch baseline and CAS digest.
- Update `index_all` and `_persist_token_patch` to use the new storage APIs.
- Keep `_index_lock`, per-slug locks, source-root validation, row rechecks, and
  transaction creation in `DesignSystemService`.

**Tests**

- Query and patch continue to pass through reconciliation while holding their
  existing service locks.
- External edits are absorbed before query and patch behavior proceeds.
- Missing files yield stale query results but reject patches.
- A file-ahead state caused by commit failure is recovered from the file.
- A changed reconciliation snapshot is reused without a duplicate parse/read.
- CAS still rejects a writer landing between entry observation and atomic write.
- A design-system row deleted during reconciliation is not revived.
- Invalid external content leaves the prior database state intact.

## U4. Reorganize test ownership

**Files**

- Modify `tests/app/protokflow/service/test_reconcile.py`.
- Modify `tests/app/protokflow/service/test_write_through.py`.
- Modify `tests/app/protokflow/service/test_indexing.py`.
- Add the storage tests listed in U1 and U2.

**Changes**

- Move filesystem mechanism assertions to `tests/app/protokflow/storage/`.
- Keep end-to-end query, patch, transaction, and recovery assertions in service
  tests.
- Replace imports and monkeypatch targets that reference `service.reconcile`.
- Prefer testing service policy through `get`, `index_all`, and
  `apply_token_patch`; use direct storage tests only for storage mechanisms.

**Tests**

- Existing U4-U6 behavioral scenarios remain represented after reorganization.
- No test relies on a compatibility import from the deleted module.
- Coverage continues to prove the unchanged fast path, touch-only path, changed
  path, missing path, recovery path, and concurrent-write path.

## U5. Align architecture documentation

**Files**

- Modify `docs/plans/2026-08-24-1252-feat-designmd-storage-layer-plan.md`.

**Changes**

- Revise KTD5 so service owns policy, locks, and transactions; storage adapters
  own filesystem access and ORM mapping; CRUD owns SQLAlchemy statements.
- Update the high-level file-to-database diagram with the storage adapter
  boundary.
- Add a post-U6 implementation unit describing this responsibility split.
- Record that the Product Contract and U6 behavior are unchanged.

## Sequencing

1. Add the storage package and source-observation types while preserving current
   callers.
2. Move persistence mapping and DAO composition behind caller-owned-session APIs.
3. Switch `DesignSystemService` to the new APIs and remove `for_patch`.
4. Delete `service/reconcile.py` and update all imports and test targets.
5. Reorganize tests and update the architecture plan.

Each step should leave one authoritative implementation of the moved behavior;
do not retain aliases or compatibility wrappers because the project is
pre-release.

## Verification

- `service/reconcile.py` no longer exists.
- `storage/design_source.py` has no SQLAlchemy, CRUD, ORM, or database-session
  imports.
- `storage/design_system_store.py` never creates or commits a session.
- `for_patch` no longer exists in production code or tests.
- All session and transaction creation for reconciliation is visible in
  `DesignSystemService`.
- Existing U6 behavior and regression scenarios pass unchanged.
- Run `uv run ruff check`.
- Run `uv run ruff format --check`.
- Run `uv run pytest`.


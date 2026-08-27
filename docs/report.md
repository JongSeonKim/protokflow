# Code Review -- PR #24 (feat/designmd-storage-layer-u6)

**Scope:** local-aligned (PR; local tree diff). Base `7a31c697`, head `e284594`, 10 files, ~1695 executable changed lines. Working tree was clean and matched the PR head exactly.
**Mode:** report-only. Nothing was applied.
**Plan:** `docs/plans/2026-08-27-refactor-designmd-reconciliation-boundary-plan.md` (`plan_source: explicit`, supplied in your request).
**Intent:** Split the mixed `service/reconcile.py` into a `storage/` adapter boundary (`design_source.py` for filesystem observation and parsing; `design_system_store.py` for ORM mapping on caller-owned sessions) while `DesignSystemService` keeps locks, policy and transactions. Reconciliation behavior, CAS semantics, orphan deletion and stale-state policy were to stay unchanged.

**Reviewers:** correctness (always on); project-standards (root `AGENTS.md` governs every changed file); testing (~890 lines of tests moved and rewritten); maintainability (module-boundary refactor); reliability (atomic write, CAS and recovery paths); performance (`index_all` does filesystem work inline); learnings (repo documents a test-DB isolation harness); adversarial (in-process). Security excluded at your request.

## The refactor itself is sound

Every boundary requirement the plan sets is met. `design_source.py` imports only stdlib, `core/design_md`, `core/discovery` and the error modules -- its four `database` mentions are all docstrings. `design_system_store.py` never calls `async_db_session`, `begin`, `commit` or `rollback`. `service/reconcile.py` is gone with no importer left, `for_patch` appears nowhere, `ParsedDesignFile` and `upsert_parsed_file` are fully renamed, and U5's documentation alignment (KTD5, the diagram, the new U6.1 unit) is complete and well-formed. Correctness traced the pre-refactor module line-by-line against the new split and found no silent behavior change. `ruff check` and `ruff format --check` are clean.

The findings below are almost all in the U6 feature code the refactor carried forward, plus plan deliverables that were not shipped.

## Triage Groups

| Group | Findings | Context | Preferred Resolution | Why | Queue |
|-------|----------|---------|----------------------|-----|-------|
| Orphan deletion is a data-loss surface | #1, #2 | `index_all` prunes with no root guard, and the hard delete reaches far more than its docstring admits | Decide delete-vs-unbind once. Unbinding (NULL the `source_*` columns) fixes both: ids and `derived_from_id` survive, and the blast radius shrinks to what the docstring claims. Do #1 first | One design call resolves both; they share the same statement | Decision gate |
| Storage boundary has no tests of its own | #4, #5, #10, #12 | Plan units U1/U2/U4 name three test files; none were committed. `__pycache__` shows one of them ran locally and was never added | Commit `tests/app/protokflow/storage/` with both `__init__.py` files and the two modules. #5 and #12 are the same guard: port the deleted test, then decide whether to keep an unreachable guard | The missing package is one unit of work; #12 is a decision inside it | Apply queue, with #12 as a decision |
| Tests that cannot pass on Windows | #6, #7 | Two newly added tests encode platform assumptions | Independent one-line fixes | Same class, no shared fix path | Apply queue |
| Lock scope | #3 | The new global lock makes the pre-existing per-slug lock inert | Reader/writer gate, or drop the per-slug lock as dead weight | Single design call | Decision gate |

## P1 -- High

**#1 `index_all` on a missing or empty root hard-deletes every file-backed row of that root**
`backend/app/protokflow/service/design_system_service.py:349` -- adversarial, validated. Confidence 100.
`index_all` calls `Path(repo_root).resolve()` and never checks the root exists. A missing path, unmounted volume or typo makes `discover_design_files` return `[]`, so `keep_slugs=[]` and `delete_orphan_sources` deletes every row bound to that `source_root`. Re-indexing cannot undo it: new rows get new ULIDs, so `derived_from_id` links are gone for good. The empty-discovery prune is intentional and tested; the *unguarded root* is not.
**Fix:** skip or raise when `not root.is_dir()`, and gate the full-prune path behind an explicit keyword when discovery is empty while file-backed rows still exist for the root. Prefer unbinding over deleting (see #2). Log the affected count instead of discarding `rowcount`.
Latent today: nothing under `backend/` calls `index_all` outside tests.

**#2 Orphan hard-delete cascades to five tables its docstring does not name**
`backend/app/protokflow/crud/crud_design_system.py:100` -- adversarial, validated. Confidence 100.
The docstring says only that tokens go via the `design_tokens` cascade. Verified in the models: `prototype_runs.design_system_id` is `ON DELETE CASCADE`, which chains `candidates` -> `exports`, `slot_contents`, `token_patches`; and `design_systems.derived_from_id` is `ON DELETE SET NULL`, so deleting a system silently strips provenance from any derived fork. A contributor reading that docstring will materially under-estimate the operation.
**Fix:** correct the docstring to name the real chain, and either unbind instead of deleting or restrict the delete to rows with no dependents and report what it refused.

**#3 The new global `_index_lock` makes the per-slug lock inert and serializes unrelated slugs**
`backend/app/protokflow/service/design_system_service.py:371` -- performance + reliability (two independent reviewers), validated. Confidence 100.
`_index_lock` is taken unconditionally at all three entry points (lines 337, 371, 426), always before `_lock_for(slug)`. The per-slug lock can therefore never be the deciding exclusion, and two `get()` calls on different slugs serialize against each other. At BASE there was no global lock: `index_all` was an unlocked staticmethod and `apply_token_patch` used only the per-slug lock. Serializing `index_all` against queries is the stated intent; serializing every query against every other is the side effect. It also means the pre-existing synchronous parse work in `index_all` (lines 339-342, unchanged from BASE) now blocks the event loop while a global lock is held.
Side effect worth knowing: `test_concurrent_token_patches_are_serialized_without_lost_updates` now passes on the global lock alone, so it no longer proves the mechanism its name describes.
**Fix (design call):** give `get`/`apply_token_patch` reader access against `index_all`'s writer mode and keep the per-slug lock meaningful, or accept global serialization and delete the per-slug lock and its dict as dead weight.

## P2 -- Moderate

**#4 Storage adapter ships with zero direct tests; plan units U1/U2/U4 unmet**
`backend/app/protokflow/storage/design_system_store.py:60` -- correctness, corroborated as a gap by testing, maintainability and project-standards. Confidence 100.
`tests/app/protokflow/storage/` exists but holds no `__init__.py` and no test modules, while the plan names three files there. `__pycache__/test_design_system_store.cpython-314-pytest-9.1.1.pyc` shows that module was written and ran locally but was never committed. Service-level tests do cover most named behaviors, but two U2 invariants are genuinely unproven anywhere: **the store never commits the caller's session**, and **a caller-owned rollback discards all store writes** -- the two guarantees the whole boundary rests on. `refresh_source_metadata`'s rollback path is entirely unexercised.
**Fix:** commit the package with both `__init__.py` files and the two modules; minimum content is the two invariants above plus the ported reparenting test.

**#5 Reparenting guard coverage was deleted, not relocated**
`backend/app/protokflow/storage/design_system_store.py:51` -- testing + project-standards (two independent reviewers). Confidence 100.
`test_build_design_tokens_rejects_mismatched_reparenting` and its positive counterpart existed at BASE in `test_indexing.py` and were removed with no replacement; `TokenReparentingError` now matches only its own raise site. This is the one finding tied to a quotable rule: `AGENTS.md` makes "write/update tests for changed behavior" and "confirm the blast radius of a change (callers, related tests)" non-negotiable even pre-release.
**Fix:** port both tests onto `storage.design_system_store.build_design_tokens`, then read #12 before deciding what the negative case should assert.

**#6 New empty-patch test asserts byte equality it cannot achieve on Windows**
`tests/app/protokflow/service/test_patch_reconciliation.py:150` -- correctness, validated. Confidence 100.
The test writes fixtures with `write_text(..., encoding="utf-8")`, which leaves `newline=None` and translates every LF to CRLF on Windows, then asserts `read_bytes() == external_content.encode("utf-8")` and that the stored digest is the SHA-256 of the LF bytes. Both fail on any Windows checkout regardless of git settings -- confirmed directly: `write_text` of `a\nb\n` yields `b'a\r\nb\r\n'`. Introduced by commit `19f4f24` in this PR. This is a genuine portability defect, not the autocrlf noise the other failures are.
**Fix:** `write_bytes(...encode("utf-8"))` (or `write_text(..., newline="")`) at both write sites.

**#7 1ns mtime-delta test cannot pass on NTFS**
`tests/app/protokflow/service/test_reconcile.py:177` -- testing, validated. Confidence 100.
The test bumps mtime by exactly 1ns and requires reconciliation to notice. NTFS stores 100ns ticks, so the delta is silently discarded and `stat_matches` reports UNCHANGED -- verified directly on this volume. The R21 regression it guards is worth keeping; the mechanism is not portable.
**Fix:** probe whether the filesystem actually applied a delta and skip with a clear reason when it did not, or bump by the filesystem's real granularity.

**#8 `observe_design_source` raises instead of returning MISSING when the file disappears after the stat**
`backend/app/protokflow/storage/design_source.py:157` -- correctness + reliability (two independent reviewers), validated. Confidence 75.
MISSING is classified only by the early `if stat is None` branch. A deletion between `stat_source()` (line 151) and `read_source_bytes()` (line 157) makes the latter raise `MissingSourceFileError`, and nothing in `_reconcile_source` or `get()` catches it -- so `get()` propagates an exception instead of honoring its documented "keeps the persisted row and returns `stale=True`" contract. Branch switching, the scenario the plan cites, is exactly when this window opens.
**Fix:** catch `MissingSourceFileError` inside `observe_design_source` and return `SourceChange.MISSING`, making the outcome enum total and leaving the query-vs-patch policy in the service untouched.

**#9 `apply_token_patch` reimplements `parse_design_file` inline**
`backend/app/protokflow/service/design_system_service.py:458` -- maintainability. Confidence 100.
The stat-matched branch builds a `DiscoveredDesignFile`, calls `read_design_file` and re-hashes, duplicating what the already-imported `parse_design_file` does.
**Fix:** call `parse_design_file(root, source)` and take `current`/`entry_digest` from the snapshot; drop the then-unused `read_design_file` import.

## P3 -- Low

**#10 `storage/` has no `__init__.py` unlike every sibling package**
`backend/app/protokflow/storage/` -- correctness + maintainability + adversarial (three reviewers). Confidence 100.
`api`, `core`, `crud`, `error`, `model`, `schema` and `service` all have one; `storage` does not, and plan U1 explicitly lists it. It imports today via namespace packages, so this is tidiness plus the plan item -- but the missing `tests/.../storage/__init__.py` matters more, since pytest's prepend import mode relies on regular packages to keep same-named test modules from colliding.

**#11 `SourceMetadata.from_snapshot` is dead code**
`backend/app/protokflow/storage/design_source.py:30` -- maintainability. Confidence 100. Zero callers anywhere; `observe_design_source` constructs `SourceMetadata` directly. Delete it unless a caller lands with it.

**#12 Token reparenting guard is unreachable by construction**
`backend/app/protokflow/storage/design_system_store.py:51` -- correctness, validated. Confidence 100.
`DesignToken` inherits a `MappedAsDataclass` base with no custom `__init__`, no `@validates` and no attribute event listener anywhere in `backend/`, so the constructor assigns `design_system_id` verbatim and `design_token.design_system_id != design_system_id` can never be true. Confirmed empirically. The only test that ever covered it had to monkeypatch the constructor -- which is why #5's port needs a decision, not a copy-paste.
**Fix (decision):** move the check where it can fail (validate in `design_token_dao.replace` that every supplied row belongs to the parent being replaced), or delete the branch and assert the constructor contract once.

## Requirements Completeness

`plan_source: explicit`. Unit-by-unit against the refactor brief:

| Unit | Status | Notes |
|------|--------|-------|
| U1 extract design-source adapter | Partially addressed | Code complete and boundary-clean. `storage/__init__.py` not added (#10); `tests/.../storage/test_design_source.py` not added (#4) |
| U2 extract source-to-database persistence | Partially addressed | Code complete; store never creates or commits a session. `tests/.../storage/test_design_system_store.py` not added (#4); reparenting coverage deleted (#5) |
| U3 concentrate policy in the service | Met | All four outcomes mapped as specified; `for_patch` removed; MISSING asymmetry, snapshot reuse, locks, root validation and row rechecks all present |
| U4 reorganize test ownership | Partially addressed | Service-level reorganization is clean with no stale monkeypatch targets, but "move filesystem mechanism assertions to `tests/app/protokflow/storage/`" did not happen |
| U5 align architecture documentation | Met | KTD5 revised, diagram updated with the storage boundary, U6.1 added with populated Files/Approach/Test scenarios/Verification, Product Contract recorded unchanged |

Plan verification checklist: `service/reconcile.py` gone (yes), no SQLAlchemy/CRUD/ORM/session imports in `design_source.py` (yes), store never creates or commits a session (yes), `for_patch` absent (yes), all reconciliation transactions visible in the service (yes), `ruff check` (pass), `ruff format --check` (pass), `pytest` (14 failed / 154 passed -- see Coverage).

One documentation inconsistency: U6.1 as written into the storage-layer plan asserts that storage tests prove observation and persistence mechanisms. They do not exist, so that plan text is currently untrue.

## Learnings and Past Solutions

**Known pattern -- honored.** `docs/solutions/architecture-patterns/test-db-isolation-harness.md` is the one captured learning and it applies directly. Every new async test takes the shared `test_db` fixture, no test defines a local isolation fixture, none calls `_set_engine_for_testing`/`_set_factory_for_testing`, and all DB access goes through the `db.async_db_session` proxy. This diff is a clean example of the documented pattern.

**Gap in the learning itself (pre-existing, not this PR).** `tests/support/ast_guards.py:40` calls `path.read_text()` with no `encoding=`, so the AST guard that enforces this learning crashes with `UnicodeDecodeError` on any machine whose locale codepage is not UTF-8 -- which is why two `tests/meta/test_xdist_isolation.py` tests fail here. The guard fails *before* checking anything, so the corpus's documented protection is not actually universal. Worth a follow-up: pass `encoding="utf-8"` and record cross-locale read encoding as an invariant in the learning.

## Coverage

- **Reviewers:** 8 dispatched, 8 returned, 0 failed. Skipped with reasons: security (excluded at your request), previous-comments (no prior PR comments), data-migration (no migration or schema artifacts), api-contract (no externally consumed boundary; no production callers exist yet), agent-native, julik-frontend-races, swift-ios.
- **Cross-model pass: not run.** The Codex route was resolved, disclosed and started, but the worker exited before contacting the provider because `jq` is not installed on this host. **No diff or code was sent to any external provider.** The adversarial lens was covered by the in-process reviewer instead, so `independence_verified: false`, `receipt_supported: false`, `model_actual: unverified`, `effort_actual: unverified`. This review has no cross-provider corroboration; agreement counts below are same-family only. Installing `jq` would enable the pass on future runs.
- **Merge:** 7 structured returns, 23 raw findings, 22 after exact-fingerprint dedup, 4 semantic merges applied by synthesis, 12 primary findings final. 1 finding suppressed at confidence anchor 50 (per-slug lock dict growth -> residual risk). 0 malformed findings, 0 malformed returns, 0 quote-gate demotions.
- **Validation:** one batch of 11 findings, covering every P1. 7 validated, 4 rejected and dropped from the primary set (listed under Rejected below). 0 validator skips for cross-model corroboration (none was available). No P1 is validation-degraded. The 5 findings not in the batch (#4, #5, #9, #10, #11) were each confirmed by direct orchestrator inspection of the cited code, git history or filesystem rather than by the validator.
- **Test suite:** 168 collected, **154 passed / 14 failed**, so the PR body's "168 passing tests" does not hold as written. 13 failures are environmental on this Windows host: git `core.autocrlf=true` with no `.gitattributes` (mangles `"\r\n"` literals in test sources), Windows symlink privileges, Windows `chmod` and directory-`fsync` semantics, and NTFS mtime granularity. 1 is a real portable defect this PR introduced (#6). Adding a `.gitattributes` pinning `tests/**/*.py` to LF would remove the CRLF subset entirely. Separately, a plain `uv run pytest` crashes in `pytest_sessionfinish` teardown here (`PermissionError` cleaning temp symlinks), which hides the failure summary unless `--basetemp` is overridden.
- **Rejected by validation (not defects):** the patch-overwrites-external-edit claim -- KTD6 in the storage-layer plan documents absorb-don't-raise at BASE, so the code implements the contract; `index_all` blocking the event loop -- BASE had the identical synchronous comprehension, so it is pre-existing, and only the added global lock amplifies it (folded into #3); empty `token_patches` no longer being a strict no-op -- intentional reorder, covered by a new test, with the file/mtime guarantee still proven; `read_source_bytes`'s TOCTOU docstring -- a reworded carryover of the BASE docstring, with `index_all` as the documented escape hatch.
- **Removable surface:** roughly 20 lines across #9, #11 and #12 if applied.
- **Residual risks:** with KTD6's absorb-don't-raise settled, `apply_token_patch` has no parameter by which a caller can say "I read version V", so a concurrent edit to the *same* token path is silently overwritten and last-writer-wins is the contract -- worth confirming that is what you want before an adapter exposes it. `design_token_dao.replace` deletes tokens of every `origin` and `get()` now reaches it on any external file change, so once `admin_ui` or `agent` tokens exist a read-only query would destroy them. `_patched_parse`'s derived-parse shortcut held across a 160-case fuzz but rests on undocumented ruamel emitter quoting behavior with no pinned version floor and no test. `get()` opens three sessions per call; each of the three lookups is deliberate and separately tested, so the cost is intentional rather than waste. `_locks` never evicts. `index_all` aborts the whole batch on the first unparsable file. `SourceObservation`'s all-optional fields force two defensive `RuntimeError` guards. Slug is globally unique while `source_root` is per-row, so two roots both containing `DESIGN.md` rebind one row -- and the new hard delete raises the stakes. `stat_source` catches `FileNotFoundError`/`NotADirectoryError` while `read_source_bytes` catches `FileNotFoundError`/`IsADirectoryError`; other `OSError` subclasses propagate unwrapped, asymmetric with the write path's `SourceWriteError`. Malformed on-disk content makes `get()` raise rather than degrade to stale, which `test_rejected_reindex_keeps_previous_db_state` deliberately locks in -- consistent but asymmetric with the MISSING path, so worth a conscious confirmation.
- **Testing gaps:** no conflicting-same-token concurrency test (both existing concurrency tests use disjoint paths, so a same-token overwrite reproduces outside the suite while it stays green); nothing asserts what orphan deletion does to `prototype_runs`, `candidates`, `exports`, `slot_contents`, `token_patches` or `derived_from_id`; no test runs `index_all` against a missing or transiently empty root holding file-backed rows; no test covers the post-stat deletion window (#8), a `source_path` resolving to a directory, TOUCHED-then-patch (where `reconciled.snapshot` is `None` although reconciliation opened a write transaction, and the comment at line 456 describes only the other path), the store not committing the caller's session, or a caller-owned rollback discarding store writes.
- **Review side effects, reverted:** `uv run` re-resolved `uv.lock` against this machine's internal Nexus mirror (package versions and hashes unchanged, registry URLs rewritten) and a reviewer wrote a stray `nonascii_report.txt` into the repo root. Both were restored/removed. Final tree state: clean.

---

## Verdict: Not ready

The refactor you asked me to review is faithful -- the boundary holds, behavior is preserved, and U3 and U5 are fully met. Two things hold it back.

First, the explicit plan has unaddressed units: U1, U2 and U4 all require `tests/app/protokflow/storage/`, and it was never committed even though `__pycache__` shows one of those modules ran locally. The two invariants that justify the entire storage split -- the store never commits the caller's session, and a caller-owned rollback discards its writes -- are unproven anywhere in the suite.

Second, the orphan-deletion path is an unrecoverable data-loss surface (#1, #2) whose real blast radius is not documented. It is latent only because nothing calls `index_all` yet, which makes now the cheap time to fix it rather than after U7/U8 wires an adapter.

Fix order: **#1 and #2 together** (one delete-vs-unbind decision), then **#4 and #5** (commit the storage tests, deciding #12 as you port), then **#6 and #7** (two one-line test fixes), then **#3** as a deliberate lock-scope decision. #9, #10, #11 are cleanup to sweep in with any of the above.

Also worth a line in the PR body: "168 passing tests" should read 154 passing / 14 failing, or the environmental cause should be named, so the next reader is not misled.

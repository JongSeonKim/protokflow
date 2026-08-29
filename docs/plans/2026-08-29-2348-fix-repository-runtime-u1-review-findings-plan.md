# Repository Runtime U1 — Review Findings Fix Plan

- **Source report:** /tmp/compound-engineering-501/ce-code-review/20260829-222402-1fafe6eb/report.md
- **Scope:** PR #26 branch `feat/repository-runtime-u1-git-context` (head `d6b19f4`). All 17 findings are in scope; findings #1–#8 are P1.
- **Settled decisions honored:** KTD8 (commit identity fallback = `Protokflow Runtime <runtime@protokflow.invalid>`, injected explicitly) and KTD9 (plumbing seam = frozen `GitRepo` dataclass threaded through module functions), both recorded as `session-settled: user-approved` in the U1 plan. No open decision gates remain.
- **Constraints:** no backward-compatibility shims (pre-release); `ruff check` / `ruff format` clean; `uv run pytest` green with default `-n 4`. The U1 plan document has uncommitted user edits and must not be touched by this work.
- **Blast radius:** the git adapter layer has no production callers yet; all callers are the new tests. API shapes may change freely within this PR.

## Batch order and dependencies

The report's triage groups impose this order: environment sanitation first (it is the precondition that makes the isolation test able to fail), then CAS classification, then the case probe, then the remaining mechanical work. Each batch lands with its own tests and a green `uv run pytest` run.

### Batch 1 — Sanitize the git child environment and inject commit identity (findings #3, #6)

Root fix in one place: `backend/app/protokflow/git/process.py` (`run_git`, line 48).

1. Build a sanitized child environment in `run_git` instead of copying `os.environ` wholesale:
   - Strip repository/index/object/config/discovery controls: `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_COMMON_DIR`, `GIT_NAMESPACE`, `GIT_CONFIG_GLOBAL`, `GIT_CONFIG_SYSTEM`, `GIT_CONFIG_COUNT`, `GIT_CEILING_DIRECTORIES`, `GIT_DISCOVERY_ACROSS_FILESYSTEM`.
   - Set `GIT_OPTIONAL_LOCKS=0` and `LC_ALL=C` (locale pinning is hardening for #2, not a substitute for it).
   - Layer explicit per-call environment values on top via the existing overlay mechanism.
2. `backend/app/protokflow/git/plumbing.py` (`create_commit`, line 115) resolves author/committer per KTD8:
   - Read `user.name` / `user.email` from the repository's git config (through the sanitized `run_git`).
   - Fall back to `Protokflow Runtime <runtime@protokflow.invalid>` when either is unset.
   - Inject the resolved values explicitly as `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, `GIT_COMMITTER_EMAIL` on the `commit-tree` child env. Dates and signing stay on git defaults (no hooks, no `commit.gpgsign` via `commit-tree`).

Tests: commit succeeds in a repository with global and local git config disabled (identity = runtime fixed identity); a child process with ambient `GIT_DIR`/`GIT_INDEX_FILE` exported still writes the requested repository.

Done when: no git child can be redirected by ambient routing variables, and an unconfigured service account can create export commits.

### Batch 2 — Classify compare-and-swap conflicts by OID probe (findings #2, #10, #16)

File: `backend/app/protokflow/git/plumbing.py` (`update_ref` line 187, `RefUpdateResult` line 37, `current_oid` line 211). One edit, three findings.

1. Remove the `"but expected"` stderr match. On a non-zero exit from `update-ref <ref> <new> <expected>`:
   - Read the ref's current OID (`rev-parse --verify --quiet` or equivalent). A current OID different from `expected_oid` (including a concurrently deleted ref, current = `None`) is a rejected CAS: return `accepted=False`.
   - A current OID equal to `expected_oid` means git failed for another reason: raise the permanent `GitCommandError`.
2. `RefUpdateResult` keeps one failure detail (the raw stderr); delete the constructed-but-unraised `cause` field and stop advertising it in the docstring.
3. `current_oid` returns `str | None` (`None` = ref does not resolve) instead of the `""` sentinel; callers updated.
4. Fix the module docstring, which still claims the staged index is never touched — `update_index_entry` writes the real index by design.

Tests: CAS conflict under a foreign locale returns `accepted=False`; concurrently deleted ref returns `accepted=False` (not a raised error); genuine failure still raises.

Done when: retryable-vs-permanent classification no longer depends on English git output.

### Batch 3 — Replace sibling-name case inference with a self-created probe (findings #1, #5, #14)

File: `backend/app/protokflow/core/identity.py` (`_is_case_insensitive` around line 72, `normalize_path` line 20).

1. Delete the swapped-case *sibling name* heuristic. Replace with a probe the code creates itself: create a uniquely named hidden marker (e.g. `.protokflow-case-probe-<uuid>`) plus its swapcase twin in the probed directory; if the second creation collides with the first, the filesystem is case-insensitive; otherwise clean up both and report case-sensitive. A probe the code owns cannot be a pre-existing symlink alias, which resolves #1, and its name always contains cased letters, which resolves #5.
2. Provide an explicit `case_policy` configuration override (`sensitive` / `insensitive` bypassing the probe) so operators can pin behavior on filesystems where transient probes are undesirable.
3. Cache the probe result with `functools.cache` (finding #14); the property cannot change during a process.

Plan note (decision made here, flag to user): the probe performs a create-then-remove of one hidden file per directory, once per process. The no-mutation guarantee that matters is the documented one — observation never locks or refreshes the user's index — and the cache plus config override bound the cost. If even that transient write is unacceptable for observation, the config override becomes mandatory; the probe path still stands for identity registration.

Tests: swapped-case symlink alias produces distinct `worktree_id`s; uncased leaf name (`2024`) folds identically to its case twin; probe runs once per directory (cached).

Done when: distinct checkouts cannot collide on one ID and the offline-reproducibility property (KTD7) holds on uncased names.

### Batch 4 — Subprocess timeout (finding #4)

File: `backend/app/protokflow/git/process.py`.

1. Add `timeout: float | None = None` to `run_git`; pass it to `subprocess.run`.
2. Add `GitTimeoutError` to the existing `GitError` hierarchy; translate `subprocess.TimeoutExpired` into it, preserving the command vector in the message.
3. Introduce a module-level `DEFAULT_GIT_TIMEOUT_SECONDS` (plan value: 60.0 — chosen here; long-lived-server callers must not pin a thread indefinitely on a stalled FUSE/network mount) and have the adapters forward a caller-supplied bound that defaults to it.

Tests: unit-level conversion of `TimeoutExpired` to `GitTimeoutError` (monkeypatched `subprocess.run`; do not depend on real wall-clock hangs).

### Batch 5 — Newline-safe rev-parse framing, then call consolidation (findings #9, #15)

File: `backend/app/protokflow/git/context.py` (`_worktree_paths` line 102 area, `symbolic-ref` pair at line 47).

1. Stop positional `splitlines()[:3]` parsing. Parse each requested value as a whole-stdout single value (strip one trailing newline) so embedded newlines in paths cannot shift fields — order #9 before #15, since #15 would otherwise add a fourth fragile value.
2. Fold `symbolic-ref` + `rev-parse HEAD` into a single call where possible (`rev-parse --symbolic-full-name HEAD` returns `refs/heads/<name>` attached and `HEAD` detached; keep the `symbolic-ref -q` fallback for unborn branches), mirroring the existing batching pattern.

Tests: `observe_checkout` on a worktree whose path contains a newline returns correct toplevel/common-dir/git-dir and identity.

### Batch 6 — Collapse the plumbing seam onto `GitRepo` (findings #13, #11, #12)

File: `backend/app/protokflow/git/plumbing.py`. KTD9 is settled; this is mechanical.

1. Introduce frozen dataclass `GitRepo(worktree_root, git_executable)`. Every module function (`create_blob`, `create_commit`, `update_index_entry`, ref helpers) takes `repo: GitRepo` as its first parameter.
2. `IsolatedIndex` holds a `GitRepo` plus its temp path and keeps its real temp-index state.
3. Extract one private helper for the `update-index --add --cacheinfo <mode>,<oid>,<path>` argument vector (dissolves #11).
4. `isolated_index`: after `os.close(descriptor)`, `Path(path).unlink(missing_ok=True)` so git never sees a zero-byte index; the existing `finally` already tolerates a missing file.

Tests: existing plumbing suite updated to the new signatures; no behavior change intended beyond #12.

Done when: U2's export sequence can chain plumbing calls on one calling convention.

### Batch 7 — Test harness sanitation and negative controls (findings #7, #8, plus guard extension)

Files: `tests/fixtures/git.py`, `tests/app/protokflow/git/test_plumbing.py`, `tests/support/ast_guards.py`.

1. `TemporaryGitRepository.run` passes an explicit sanitizing env: `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM` pointed at `os.devnull`, `GIT_CONFIG_NOSYSTEM=1`, routing variables unset; deliberate per-test env injection keeps working through the overlay. (#8; depends on Batch 1's sanitized `run_git`.)
2. Isolation test negative control (#7): `monkeypatch.delenv("GIT_INDEX_FILE", raising=False)` before staging `notes.txt`, and assert afterwards that `notes.txt` is still present in `git_repo.index_entries()` with its staged mode and OID intact — the test must be able to fail when isolation breaks.
3. Add the git fixture names (`TemporaryGitRepository`, `test_git_repo`) to `ISOLATION_FIXTURE_NAMES` in `tests/support/ast_guards.py` (report learnings follow-up), mirroring the `test_db`/`test_engine` discipline.
4. Vocabulary-invariant test from the report: observe checkout before and after a commit on the same branch and assert identity is unchanged — the invariant Checkout Epoch (U6) and Mutation Fence (U7) build on.

### Batch 8 — Documentation (finding #17) and post-land follow-ups

1. `CONCEPTS.md`: add glossary entries in the existing style for checkout observation, isolated index, compare-and-swap ref update, `repository_id`, `worktree_id`.
2. Flagged for explicit settlement (not silent divergence): the `docs/solutions/architecture-patterns/test-db-isolation-harness.md` rule requiring `@pytest.mark.tooling` for external-CLI tests predates git becoming a core runtime dependency. Default direction: update the doc (untagged git tests stay in default runs); do not tag the tests. Also refresh that doc's now-stale single-plugin `pytest_plugins` description and, after landing, capture the two-harness comparison as a new solution entry.

## Verification

Per batch: `uv run ruff check`, `uv run ruff format` (clean diff), targeted tests for the touched modules, then full `uv run pytest` (default `-n 4`). Final pass runs the full suite sequentially once (`uv run pytest -n 0`) to catch xdist-masked ordering issues in the new harness tests.

## Out of scope

- U2+ persistence (R10), checkout-epoch transitions (U6), mutation fence (U7) — deferred by the parent plan.
- Security review lens — excluded from the source review at the user's request; no security work is authorized by this plan.
- Any edit to `docs/plans/2026-08-29-2052-feat-repository-runtime-u1-git-context-plan.md` (carries uncommitted user edits).

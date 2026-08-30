---
title: Repository Runtime Git Adapter Architecture
date: 2026-08-30
category: solutions/architecture-patterns
module: Repository Runtime Git adapter (backend.app.protokflow.git)
problem_type: architecture_pattern
component: infrastructure
severity: high
applies_when:
  - "Adding or changing any Git command execution in the backend"
  - "Composing commits that must exclude the user staged or working-tree changes"
  - "Deriving stable repository or worktree identifiers offline"
  - "Advancing refs atomically under concurrent writers"
related_components: [testing_framework, development_workflow]
tags: [git, subprocess, plumbing, isolated-index, compare-and-swap, worktree-identity, adapter, porcelain]
---

# Repository Runtime Git Adapter Architecture

## Context

The Repository Runtime treats the user's Git repository as untrusted shared state: it observes the checkout, derives stable identities, and during export must create a commit containing only the `DESIGN.md` change while the user may concurrently have unrelated work staged. Porcelain commands cannot guarantee this — `git commit` reads the user's index and runs hooks, and no porcelain ref update is conditional on an expected OID.

To ensure safe operation in shared environments, the architecture enforces strict subprocess isolation and identity fallbacks: ambient environment variables (such as `GIT_DIR`) are stripped to prevent redirection of index writes, and fallback runtime identities ensure `commit-tree` operations succeed even on unconfigured hosts. Git access is organized into an adapter package over a pure identity core, accompanied by a dedicated domain-exception hierarchy.

## Guidance

### 1. Route every git invocation through one sanitized subprocess wrapper

`run_git` (`backend/app/protokflow/git/process.py:58`) is the only place that spawns git. It strips ambient routing variables — `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_COMMON_DIR`, `GIT_NAMESPACE`, `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM`/`GIT_CONFIG_COUNT`/`GIT_CONFIG_PARAMETERS`, `GIT_CEILING_DIRECTORIES`, `GIT_DISCOVERY_ACROSS_FILESYSTEM` (`process.py:31`) — so a parent process launched inside another repository cannot redirect child reads or writes. It sets `GIT_OPTIONAL_LOCKS=0` (`process.py:85`) so read-only observation never locks or refreshes the user index, pins `LC_ALL=C` (`process.py:87`) for locale-stable output, and lets explicit per-call entries win over the sanitized base, with `None` removing a variable (`process.py:89`). Streams decode as UTF-8 with replacement (`process.py:120`), a 60-second default timeout bounds each invocation (`process.py:27`, raising `GitTimeoutError` at `process.py:106`), and failures become domain exceptions preserving argv, exit code, and both streams (`process.py:124`).

### 2. Observe the checkout as one read-only snapshot

`observe_checkout` (`backend/app/protokflow/git/context.py:32`) returns a frozen `CheckoutContext` (`context.py:18`) holding the worktree root, Git common directory, per-worktree Git directory, full symbolic ref, HEAD OID, detached flag, and both derived identifiers. A detached HEAD reports no symbolic ref (`context.py:64`) and is the unsupported checkout state; an unborn branch still resolves the symbolic ref without an OID through a `symbolic-ref` fallback (`context.py:122`). Each `rev-parse` value is parsed as whole stdout with exactly one trailing newline stripped, so a worktree path containing newlines cannot shift positional parsing (`context.py:79`), and the HEAD OID plus symbolic-full-name resolve in one batched invocation (`context.py:110`).

### 3. Keep identifier derivation pure and deterministic

`backend/app/protokflow/core/identity.py` has no SQLAlchemy or FastAPI references, so clients can recompute both identifiers offline for binding verification. The two hashes are domain-separated (`backend/app/protokflow/core/identity.py:18`) and computed as SHA-256 over a domain prefix plus the UTF-8 normalized path (`identity.py:60`). Normalization resolves symlinks, applies Unicode NFC, and folds case only on case-insensitive filesystems (`identity.py:22`). Case behavior is probed by creating a uniquely named hidden marker and its swapcase twin inside the directory (`identity.py:82`) — self-created, so it can never collide with a pre-existing alias and stays correct even when the directory's own name contains no cased characters, with the probe result cached per directory (`identity.py:72`).

### 4. Mutate only through plumbing; touch the real index from exactly one function

The plumbing module states its contract in the docstring: trees are composed inside a temporary index, commits are generated with `commit-tree`, refs advance via compare-and-swap, and `update_index_entry` is the single deliberate writer to the repository's real index (`backend/app/protokflow/git/plumbing.py:1`). Blobs enter the object database through `hash-object -w --stdin` (`plumbing.py:115`). The `isolated_index` context manager (`plumbing.py:84`) creates the temporary index with `mkstemp` and guarantees deletion on every exit path including exceptions (`plumbing.py:97`, `plumbing.py:106`), and every command inside the scope carries an explicit `GIT_INDEX_FILE` (`plumbing.py:78`) so inherited overrides are inert.

`create_commit` resolves author/committer from the repository's `--local` config (`plumbing.py:176`) and falls back to the fixed runtime identity (`plumbing.py:24`, `plumbing.py:170`), injecting all four values through the child environment (`plumbing.py:144`). This removes ambient-config dependence and satisfies the no-hooks and no-signing requirements inherently, because `commit-tree` runs no hooks and ignores `commit.gpgsign`.
 
`update_ref_conditionally` uses the CAS form of `update-ref` (`plumbing.py:256`); on non-zero exit it classifies by probing the ref's current OID (`plumbing.py:271`, `plumbing.py:289`) rather than matching localized stderr — a moved or deleted ref is a rejected CAS returned as `RefUpdateResult(accepted=False)` for retry, while a ref still at the expected OID is a permanent `GitCommandError` (`plumbing.py:281`). `update_index_entry` addresses the real index by its explicit absolute path (`plumbing.py:227`) so an inherited `GIT_INDEX_FILE` cannot misdirect the write. A frozen `GitRepo` dataclass (`plumbing.py:46`) binds worktree root, executable, and timeout for all plumbing functions, providing a uniform interface for export operations.

### 5. Map process outcomes onto a small domain exception hierarchy

`backend/app/protokflow/error/git.py` defines `GitError(ValueError)` as the base (`backend/app/protokflow/error/git.py:9`), with `GitBinaryMissingError` preserving the underlying `OSError` (`backend/app/protokflow/error/git.py:13`), `GitCommandError` preserving argv, exit code, and captured stdout/stderr (`backend/app/protokflow/error/git.py:21`), `GitTimeoutError` (`backend/app/protokflow/error/git.py:47`), and `GitWorktreeInvalidError` (`backend/app/protokflow/error/git.py:62`). Callers can distinguish retryable concurrency conflicts from permanent failures without parsing stderr.

### 6. Test through shared worktree fixtures, including negative controls

`tests/fixtures/git.py` provides a `TemporaryGitRepository` fixture building real repositories and linked worktrees under per-test `tmp_path`, with host ambient config neutralized so global hooks and signing defaults never leak into test repositories. The suite pins each rule: staged changes are excluded from isolated-index commits (`tests/app/protokflow/git/test_plumbing.py:24`), CAS accept/reject/concurrent-delete/permanent-failure paths are separate cases (`test_plumbing.py:101`, `test_plumbing.py:122`, `test_plumbing.py:151`, `test_plumbing.py:175`), inherited `GIT_INDEX_FILE` is ignored and cleanup holds on exceptions (`test_plumbing.py:215`, `test_plumbing.py:231`), ambient routing and config variables do not reach children (`tests/app/protokflow/git/test_process.py:84`, `test_process.py:101`), newline-bearing worktree paths observe correctly (`tests/app/protokflow/git/test_context.py:105`), unborn heads resolve (`test_context.py:71`), and the case probe handles symlink aliases and uncased directory names (`tests/app/protokflow/core/test_identity.py:62`, `test_identity.py:77`).
 
## Why This Matters
 
- Porcelain cannot satisfy the export contract: `git commit` consumes the user's index and runs hooks, and no porcelain ref update is conditional on an expected OID. Plumbing plus a temporary index plus a CAS `update-ref` is the minimal set that does.
- Ambient environment is a correctness surface, not just a security one: one inherited `GIT_DIR` silently retargets every child, so observation reads another repository while the real-index write mutates another repository.
- Classifying CAS failures by stderr text is fragile under locale and Git version changes; probing the ref's current OID is semantic.
- Database-issued identifiers would force clients to contact the runtime before binding verification; path-derived deterministic hashes keep client and server independent.
- Observation without `GIT_OPTIONAL_LOCKS=0` can lock or stat-refresh the user's index as a side effect of a read — preventing unintended index modifications or lock contention during observation.

## When to Apply

- Adding or changing any Git command execution in the backend: extend `run_git` callers, never spawn git elsewhere.
- Composing commits that must exclude staged or working-tree changes: `isolated_index` + `hash-object` + `write-tree` + `commit-tree` + conditional ref update.
- Deriving stable repository or worktree identifiers: the core identity functions, never database identifiers.
- Advancing refs atomically under concurrent writers: `update_ref_conditionally` with an expected OID.

## Examples

Export-shaped commit composition:

```python
with isolated_index(worktree_root) as index:
    blob = create_blob(repo, design_md_bytes)
    index.read_tree(head_tree)
    index.update_entry(mode="100644", oid=blob, path="DESIGN.md")
    tree = index.write_tree()
    commit = create_commit(repo, tree=tree, parent=head_oid, message="...")
    result = update_ref_conditionally(
        repo, ref=symbolic_ref, new_oid=commit,
        expected_oid=head_oid, reason="protokflow export",
    )
    if not result.accepted:
        ...  # retryable checkout conflict
```

The temporary index vanishes at scope exit; the user's staged work was never read into it.

## Related

- [CONCEPTS.md](../../../CONCEPTS.md) — Checkout Observation, Isolated Index, Compare-and-Swap Ref Update, repository_id, worktree_id, Checkout Identity, Export Operation
- [test-db-isolation-harness.md](test-db-isolation-harness.md) — adjacent learning; the git adapter tests consume the same shared-fixture and negative-control discipline

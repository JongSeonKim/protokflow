# Concepts

> Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## Test DB Isolation

### Test Harness
The project-standard testing foundation ensuring every pytest run consumes a dedicated, isolated database through shared fixtures.

Test modules consume the shared fixtures rather than defining local isolation mechanisms or calling internal isolation hooks directly, a rule enforced by structural meta-tests. When the harness is active, all database writes, including lifecycle schema manipulations, route to the test database path.

### Active Engine
The database engine that lifecycle schema operations resolve at invocation time, defaulting to the production singleton unless a test override is set.

This engine lookup operates in tandem with the session factory substitution boundary. Swapping only the factory for tests without setting this boundary allows schema operations to leak into the production engine.

### Run ID
A unique identifier assigned to each test run that acts as a namespace to prevent test database filename collisions.

The controller and serial test executions use the run ID alone in their database filenames, while xdist workers append a worker identifier suffix. This prevents leftover database files from abnormal terminations from colliding with subsequent test runs.

### Tooling Lane
An optional suite of tests with external tooling dependencies, partitioned by an opt-in marker that is automatically deselected from standard test runs.

## Storage Reconciliation

### Repository Runtime
The single repository-scoped process that owns canonical `DESIGN.md` synchronization, SQLite writes, candidate operations, and the local protocol consumed by MCP, CLI, and Web clients.

Clients do not bypass an unavailable Runtime to access the canonical file or database directly.

### Canonical Design
The root `DESIGN.md` tracked by Git and treated as the repository's only authoritative design document.

Candidate documents remain in SQLite until an explicit export promotes one immutable revision to a new canonical generation.

### Canonical Generation
A monotonically ordered, fully committed version of the canonical design and its normalized token projection.

Reads identify the generation they return. Commands that create or change canonical-dependent state wait until the Runtime has finished processing a newer observed file state.

### Candidate Series
A branch-like identity for one design direction whose head points to its latest candidate revision.

### Candidate Revision
An immutable candidate `DESIGN.md` document and normalized token projection, linked to at most one parent revision and to the canonical generation from which its series was derived.

Editing a candidate creates a new revision instead of modifying history.

### Change Origin
The source category recorded for a canonical generation: `runtime` when a Repository Runtime operation initiated the file write, or `external` when the watcher observed a valid change without a matching Runtime operation.

### Precheck
The startup or explicit synchronization check that compares the observed canonical `DESIGN.md` with the last committed canonical generation before the Runtime becomes ready or reports synchronization complete.

### Reconcile
The process by which the Repository Runtime validates a changed canonical `DESIGN.md` and commits the complete design and token projection as one new canonical generation.

### File-Ahead State
The failure state after a Runtime operation replaces the canonical file but stops before the corresponding canonical generation and operation result are fully committed.

Runtime startup resolves this state from durable operation identity, target digest, the observed file, and committed canonical generations before accepting requests.

### Stale
A freshness status for a valid committed canonical generation when the Runtime knows a newer file state is waiting for validation or cannot be committed because the current canonical source is invalid or missing.

### Checkout Observation
The single-pass inspection of a worktree's checkout state: worktree root, common and per-worktree Git directories, symbolic ref, HEAD OID, detached flag, and the path-derived repository and worktree identifiers.

Observation runs read-only git commands under a sanitized child environment and never locks or refreshes the user's index.

### Isolated Index
A temporary index file used to compose export commits without touching the user's staged work or working tree.

Trees are read, updated, and written entirely inside the temporary index, which is deleted on exit even when the operation fails.

### Compare-and-Swap Ref Update
The conditional ref advance that moves a ref to a new OID only when the ref still points at the expected OID.

A concurrent move or deletion is reported as a rejected update rather than an error so callers can retry; classification probes the ref's current OID instead of matching git output text.

### repository_id
The stable SHA-256 identifier of a Git repository, derived from the common Git directory path.

Case folding on case-insensitive filesystems and Unicode NFC normalization make both spellings of the same directory produce one identifier, so clients can recompute it offline.

### worktree_id
The stable SHA-256 identifier of one Git worktree, derived from its root path under the same normalization rules as repository_id.

Distinct worktrees of one repository share a repository_id but never a worktree_id.

### Checkout Identity
The Git checkout the Repository Runtime treats as the current one: the full symbolic ref on an attached HEAD, or the commit OID on a detached HEAD.

A new HEAD OID on the same symbolic ref does not change this identity.

### Checkout Epoch
A monotonically increasing number the Repository Runtime commits whenever Checkout Identity changes, regardless of whether the canonical file content changed.

Candidate revisions record the epoch they were created under. A revision from an earlier epoch is never automatically revalidated, so returning to a previous branch does not make it exportable again.

### Mutation Fence
The per-worktree serialization boundary every canonical-dependent command passes through.

On entry it drains pending watcher observations, waits for synchronization, and pins Checkout Identity, Checkout Epoch, canonical generation, and digest as the command's baseline. It revalidates the same baseline immediately before committing a database or Git result, and fails the command as a retryable checkout conflict on any mismatch.

### Export Operation
The durable record of one promotion of a candidate revision to a new canonical generation through a Git commit.

It advances through committed phases — intent, commit created, ref updated, worktree reflected, finalized — so an interrupted runtime resolves it to exactly one of completed, conflict, or failed on restart. A matching file digest is never accepted as proof that the Git result landed.

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

### Precheck
The stat-based first check every storage entry point runs against the linked DESIGN.md: compare the stored `(mtime_ns, size)` pair, and compute sha256 only on mismatch to decide between a metadata-only refresh and re-indexing.

### Reconcile
The process by which a storage entry point catches the database up to an externally changed DESIGN.md — the file is the recovery source of truth, so a digest mismatch re-indexes from the file before the entry point proceeds.

### File-Ahead State
The failure state after a successful file write whose database commit failed: the file is ahead of the database, and the next entry point's precheck absorbs the change by re-indexing rather than treating it as a concurrent modification.

### Stale
A read-time derived status for a design system whose source file is absent: the record is retained because a branch switch may make the file reappear, and staleness is computed at query time instead of being stored.

Stale is a momentary report from a single-system entry point, not a state change — the system still claims its file. A system that has actually given up its file linkage is Unbound.

### Orphan
A file-backed design system that no longer appears in a repository root's discovery set, because its DESIGN.md was deleted, renamed, or moved out of a discovered location.

Orphan describes what a batch reindex finds, not a status the system carries — the outcome of finding one is that the system becomes Unbound.

### Unbound
A design system whose file linkage has been cleared after it was found to be an orphan, leaving it as a database-only record that is re-linked by slug if its file returns.

Unbinding is deliberately not deletion. A design system is the anchor for prototype runs, exports, and derived-system provenance, none of which can be regenerated from a DESIGN.md, and re-indexing issues fresh identities rather than restoring the ones a delete destroyed. Unbinding therefore keeps the blast radius of a vanished file at the file linkage itself. A repository root that does not exist is rejected rather than treated as a root whose files were all deleted, since discovery cannot tell the two apart.

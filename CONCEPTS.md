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

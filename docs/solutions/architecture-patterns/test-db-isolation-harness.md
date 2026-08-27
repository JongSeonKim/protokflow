---
title: Test Database Isolation Harness Architecture
date: 2026-08-25
category: solutions/architecture-patterns
module: pytest Test Database Isolation Harness
problem_type: architecture_pattern
component: testing_framework
severity: high
applies_when:
  - "Running pytest in parallel (xdist) or serial mode"
  - "Tests using SQLite lifecycle DDL alongside session factories"
  - "Ensuring test suites never access or mutate the repository production database"
related_components: [database, development_workflow]
tags: [pytest, xdist, sqlite, test-isolation, database-harness, engine-injection, meta-testing, parallel-tests, encoding, cross-platform]
---

# Test Database Isolation Harness Architecture

## Context

Running `pytest` with `pytest-xdist` workers against an asynchronous SQLite database introduces significant isolation risks. Without a strict isolation harness, the test controller, individual worker processes, and lifecycle DDL operations can inadvertently bind to the repository-local production database (`.protokflow/protokflow.db`), causing data corruption and test crosstalk.

To guarantee zero database side effects and complete parallel test isolation, the architecture enforces four core invariants:

1. **Strict Lifecycle Sequencing**: Testing engine and factory overrides must be registered before executing `create_tables()`, ensuring DDL operations and initial schema seeding bind exclusively to the isolated test database.
2. **Non-Interference Verification**: Test integrity is validated by asserting the existence and modification timestamp (`mtime`) invariance of the production database file across test runs, avoiding false positives in active development environments.
3. **Pre-Import Environment Injection**: Because Python modules instantiate top-level database singletons upon import, `PROTOKFLOW_DATABASE_URL` and `PROTOKFLOW_HOME` must be injected in the pytest bootstrap phase prior to module imports.
4. **AST-Enforced Fixture Discipline**: All test modules must consume the shared `test_db` fixture via registered pytest plugins, strictly forbidding manual hook calls or local fixture overrides.

## Guidance

### 1. Bootstrap and Environment Setup (`tests/conftest.py`)
`tests/conftest.py` serves as the test suite entry point:
- Registers the database fixture plugin (`pytest_plugins = ("tests.fixtures.db",)`).
- Generates a worker-isolated temporary directory (`_TEST_HOME`), sets `PROTOKFLOW_TEST_RUN_ID` (via `setdefault`), and sets `PROTOKFLOW_HOME`.
- Pre-injects `PROTOKFLOW_DATABASE_URL = create_database_url(unittest=True)` into `os.environ` before `backend/database/db.py` creates its module-level `async_engine`.
- Removes the temporary test directory in `pytest_unconfigure` on a best-effort basis upon session completion.

### 2. Database Naming and Worker Scoping (`backend/database/url.py`, `tests/support/worker.py`)
When `unittest=True`, database URL resolution derives an isolated SQLite path:
- Base stem is set to `protokflow_test`.
- Appends the unique run identifier (`PROTOKFLOW_TEST_RUN_ID`).
- Appends the `pytest-xdist` worker identifier (`PYTEST_XDIST_WORKER`, e.g., `gw0`, `gw1`) if executing under a worker process; the controller defaults to `master`.
- Resolves paths such as `protokflow_test_r12345678.db` (controller) and `protokflow_test_r12345678_gw0.db` (worker `gw0`).

### 3. Active Engine and Session Factory Proxies (`backend/database/db.py`)
Global database access uses dynamic proxy indirection to support test isolation:
- `_SessionFactoryProxy`: Delegates calls and `.begin()` to the active session factory (`_active_factory`), which can be overridden via `_set_factory_for_testing()`.
- `_get_active_engine()`: Returns the active test engine override (`_active_engine`) if set, falling back to the default `async_engine`.
- Dynamic DDL Routing: `create_tables()` and `drop_tables()` dynamically query `_get_active_engine()`, guaranteeing that DDL statements and schema versioning (`PRAGMA user_version`) target the active test database.

### 4. Fixture Hierarchy and Cleanup Lifecycle (`tests/fixtures/db.py`, `tests/support/db.py`)
The harness provides a structured three-tier fixture hierarchy:
- `_test_database_guard` (`session`, `autouse=True`): Validates that resolved database paths match the test prefix, reside inside the temporary test home, and carry a `.db` extension.
- `test_engine` (`session`): Creates a worker-scoped SQLite async engine, sets `_set_engine_for_testing`, and on teardown disposes the engine, restores the previous engine, and deletes the main SQLite file along with `-wal` and `-shm` sidecars.
- `test_db` (`function`): Creates a session factory bound to `test_engine`, sets `_set_factory_for_testing`, runs `create_tables()`, yields an active `AsyncSession`, and on teardown rolls back open transactions, closes the session, runs `drop_tables()`, and restores the previous factory.

### 5. Meta-Testing and Architectural AST Guards (`tests/meta/test_xdist_isolation.py`, `tests/support/ast_guards.py`)
The integrity of the test harness is enforced through automated meta-tests:
- Validates `pyproject.toml` default options (`-n 4 --dist=loadscope -m 'not tooling'`).
- Asserts controller and worker database URL resolution and import-time binding invariants.
- Verifies that the production database file path (`.protokflow/protokflow.db`) modification time (`mtime`) is strictly preserved across the test run.
- Uses AST analysis to scan all non-meta test modules, failing if any test directly calls private hooks (`_set_engine_for_testing`, `_set_factory_for_testing`) or defines local `test_db`/`test_engine` fixtures.
- Reads every scanned module with an explicit `encoding="utf-8"`. The guard parses test sources itself, so it inherits their encoding problem: relying on the platform default made `read_text()` raise `UnicodeDecodeError` on any machine whose locale codepage is not UTF-8, and because that happens *before* any check runs, the harness's own enforcement silently failed open on those machines. A guard that can crash before asserting protects nothing — the encoding is part of the guarantee, not an implementation detail.
- Every test directory carries an `__init__.py`. `pytest`'s prepend import mode relies on regular packages to keep same-named test modules in different directories from colliding, and the AST guard walks `TESTS_DIR.rglob("*.py")` across all of them.

## Why This Matters

### Pre-Import Environment Configuration
Modifying environment variables after importing `backend/database/db.py` cannot alter existing module-level engine singletons. Pre-configuring `PROTOKFLOW_DATABASE_URL` in `conftest.py` combined with runtime engine override hooks ensures that import-time bindings and runtime invocations route to the exact same isolated database.

### Decoupling from Framework Lifespans
Threading database engines through FastAPI lifespan parameters pollutes the production application architecture with test-specific concerns. Module-level proxy indirection cleanly isolates test hooks to the test suite while keeping production entry points minimal and robust.

### Full SQLite Transactional and File Fidelity
Unlike connection-level rollback mocks or in-memory SQLite instances (which fail to replicate multi-connection concurrency and disk synchronization), per-worker SQLite files execute true file-backed async WAL transactions. This verifies real persistence and schema migration semantics without risking production data.

## When to Apply

- **Parallel Test Suites**: Apply whenever executing SQLAlchemy async SQLite test suites under `pytest-xdist`.
- **Writing Tests**: All tests requiring database interaction must declare and consume the shared `test_db` fixture. Tests must never instantiate custom engines or invoke private testing hooks directly.
- **Adding a Test Directory**: Create its `__init__.py` in the same change, or same-named modules across directories can collide under prepend import mode.
- **Reading or Writing Files in Tests**: Pass `encoding` explicitly. The platform default varies by locale, and byte-exact fixtures additionally need `write_bytes`/`newline=""` rather than `write_text`, whose `newline=None` rewrites LF to CRLF on Windows. `.gitattributes` pins `*.py` and `*.md` to LF so committed sources survive checkout unmangled.
- **Tooling Test Isolation**: Tests requiring external CLI binaries or slow external dependencies must be tagged with `@pytest.mark.tooling`, excluding them from default runs via `-m 'not tooling'`.

## Examples

### Consuming the `test_db` Fixture
`pyproject.toml` sets `asyncio_mode = "auto"`, so async tests need no
`@pytest.mark.asyncio` decorator — declaring the `test_db` fixture is the whole
contract.

```python
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.protokflow.model import DesignSystem
from backend.database.db import async_db_session


async def test_design_system_persistence(test_db: AsyncSession) -> None:
    # Direct session usage
    system = DesignSystem(slug="default", title="Default System")
    test_db.add(system)
    await test_db.flush()

    # Proxy session verification (resolves to the same test engine)
    async with async_db_session.begin() as session:
        result = await session.get(DesignSystem, system.id)
        assert result is not None
        assert result.slug == "default"
```

### Running Test Suites
```bash
# Run all tests in parallel (default: 4 workers, loadscope distribution)
uv run pytest

# Run sequentially for debugging
uv run pytest -n 0

# Run tooling tests explicitly
uv run pytest -m tooling
```

## Related

- [Database Schema Design](../../concepts/database-schema.md) — Single source of truth for repository-isolated SQLite databases and `PRAGMA user_version` schema management.

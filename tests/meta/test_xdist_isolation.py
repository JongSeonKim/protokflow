"""Meta-tests for pytest and database isolation invariants.

These tests intentionally inspect the configuration and source tree in addition
to exercising the active test database.  The test harness is infrastructure for
all other tests, so a local redefinition or direct hook call should fail close
to the change that introduced it.
"""

from __future__ import annotations

import ast
import os
import re
import shlex
import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.protokflow.model import DesignSystem
from backend.database import db
from backend.database.db import async_db_session as imported_async_db_session
from tests.conftest import PRODUCTION_DB_PATH
from tests.support import db as db_fixtures
from tests.support.ast_guards import (
    ALLOWED_MODULES,
    TESTS_DIR,
    direct_testing_hook_calls,
    is_allowed_harness_module,
    local_isolation_fixtures,
    scanned_modules,
)
from tests.support.db import TEST_DATABASE_PREFIX, table_names

pytestmark = pytest.mark.meta

_REPO_ROOT = TESTS_DIR.parent


def test_pytest_xdist_defaults_are_locked() -> None:
    """Default pytest execution keeps parallelism and tooling opt-in."""
    config = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())
    addopts = str(config["tool"]["pytest"]["ini_options"]["addopts"])
    tokens = shlex.split(addopts)

    workers: str | None = None
    for index, token in enumerate(tokens):
        if token == "-n" and index + 1 < len(tokens):
            workers = tokens[index + 1]
            break
        if token.startswith("-n") and token[2:]:
            workers = token[2:]
            break

    assert workers is not None, f"-n not found in addopts: {addopts!r}"
    assert int(workers) > 0, f"Expected positive xdist worker count, got {workers!r}"
    assert "--dist=loadscope" in tokens
    assert "-m" in tokens
    marker_expression = tokens[tokens.index("-m") + 1]
    assert re.search(r"\bnot\s+tooling\b", marker_expression)


def test_controller_and_worker_database_names_are_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Controller and workers share a run id but never share a DB filename."""
    run_id = os.environ["PROTOKFLOW_TEST_RUN_ID"]
    home = Path(os.environ["PROTOKFLOW_HOME"]).resolve()

    monkeypatch.setenv("PYTEST_XDIST_WORKER", "master")
    controller = db.create_database_path(unittest=True)
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    worker = db.create_database_path(unittest=True)

    assert controller == home / f"{TEST_DATABASE_PREFIX}{run_id}.db"
    assert worker == home / f"{TEST_DATABASE_PREFIX}{run_id}_gw0.db"
    assert controller != worker


def test_import_time_engine_observes_the_test_database_namespace() -> None:
    """The pytest signal is consumed before the backend singleton is built."""
    expected = db.create_database_path(unittest=True).resolve()
    actual = Path(str(db.async_engine.url.database)).resolve()

    assert actual == expected
    assert actual.name.startswith(TEST_DATABASE_PREFIX)
    assert actual.parent == Path(os.environ["PROTOKFLOW_HOME"]).resolve()


async def test_lifecycle_ddl_and_schema_seed_stay_on_test_database(
    test_db: AsyncSession,
) -> None:
    """The active lifecycle engine and factory route DDL and seed writes together."""
    del test_db
    test_path = db.create_database_path(unittest=True).resolve()
    await db.drop_tables()
    await db.create_tables()

    async with db._get_active_engine().connect() as connection:
        names = await connection.run_sync(table_names)
    assert "design_systems" in names

    async with imported_async_db_session() as session:
        schema_version = await session.scalar(text("PRAGMA user_version"))
    assert schema_version == db.EXPECTED_SCHEMA_VERSION
    assert test_path.parent == Path(os.environ["PROTOKFLOW_HOME"]).resolve()
    assert test_path != PRODUCTION_DB_PATH


async def test_import_bound_factory_proxy_routes_to_test_engine(
    test_db: AsyncSession,
) -> None:
    """A symbol imported before the fixture swap still follows the proxy."""
    del test_db
    slug = "meta-factory-proxy-route"
    async with imported_async_db_session.begin() as session:
        session.add(DesignSystem(slug=slug, title="Meta factory proxy"))

    async with db.async_db_session() as session:
        row = await session.scalar(
            select(DesignSystem).where(DesignSystem.slug == slug)
        )

    assert imported_async_db_session is db.async_db_session
    assert row is not None
    assert row.title == "Meta factory proxy"


def test_test_database_guard_is_strict_about_name_and_home(tmp_path: Path) -> None:
    """Only the test prefix under the configured test home is accepted."""
    home = tmp_path / "test-home"
    accepted = (
        home / "protokflow_test_r12345678.db",
        home / "protokflow_test_r12345678_gw3.db",
    )
    for path in accepted:
        assert (
            db_fixtures.validate_test_database_path(path, home=home) == path.resolve()
        )

    rejected = (
        home / "protokflow.db",
        home / "protokflow_test.db",
        tmp_path / "other-home" / "protokflow_test_r12345678.db",
    )
    for path in rejected:
        with pytest.raises(RuntimeError, match="test database"):
            db_fixtures.validate_test_database_path(path, home=home)


@pytest.fixture(scope="module", autouse=True)
def _production_database_must_remain_unchanged() -> Iterator[None]:
    """Capture production DB state around this module's isolation exercises."""
    before = _file_state(PRODUCTION_DB_PATH)
    yield
    after = _file_state(PRODUCTION_DB_PATH)
    assert after == before, (
        "Meta isolation tests changed the production database path: "
        f"before={before!r}, after={after!r}"
    )


def test_no_non_meta_test_module_calls_testing_hooks() -> None:
    """Engine and factory swaps stay inside the shared harness or boundary tests."""
    offenders: list[str] = []
    for path, tree in scanned_modules():
        calls = direct_testing_hook_calls(tree)
        if calls:
            offenders.append(f"{path}: {calls}")

    assert offenders == []


def test_no_non_meta_test_module_defines_local_isolation_fixtures() -> None:
    """The shared fixture stack cannot be silently shadowed by a test module."""
    offenders: list[str] = []
    for path, tree in scanned_modules():
        fixtures = local_isolation_fixtures(tree)
        if fixtures:
            offenders.append(f"{path}: {fixtures}")

    assert offenders == []


@pytest.mark.parametrize(
    "source",
    [
        "from backend.database.db import _set_engine_for_testing\n_set_engine_for_testing(None)\n",
        "from backend.database import db\ndb._set_factory_for_testing(None)\n",
    ],
)
def test_ast_guard_detects_direct_testing_hook_calls(source: str) -> None:
    tree = ast.parse(source)

    assert direct_testing_hook_calls(tree)


def test_ast_guard_detects_local_isolation_fixture() -> None:
    tree = ast.parse("import pytest\n\n@pytest.fixture\ndef test_engine():\n    pass\n")

    assert local_isolation_fixtures(tree) == ["test_engine"]


def test_ast_guard_exceptions_are_narrow() -> None:
    assert all(is_allowed_harness_module(path) for path in ALLOWED_MODULES)
    assert not is_allowed_harness_module(
        (TESTS_DIR / "database" / "test_fixtures.py").resolve()
    )


def _file_state(path: Path) -> tuple[bool, int | None]:
    try:
        return True, path.stat().st_mtime_ns
    except FileNotFoundError:
        return False, None

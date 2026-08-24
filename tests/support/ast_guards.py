"""AST-based structural checks for test suite database isolation.

Scans test modules to ensure that internal testing hooks and isolation fixtures
remain confined to the shared test harness (``tests/fixtures/db.py``) rather than
being called or shadowed in individual test files.

These checks are executed by meta-tests in ``tests/meta/``.
"""

from __future__ import annotations

import ast
from functools import cache
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parents[1]

# Internal hooks in backend.database.db that should only be invoked by the harness.
TESTING_HOOKS = {"_set_engine_for_testing", "_set_factory_for_testing"}

# Fixtures that manage test database isolation and must not be redefined locally.
ISOLATION_FIXTURE_NAMES = {
    "_test_database_guard",
    "test_db",
    "test_engine",
}

# Modules explicitly allowed to invoke testing hooks or define harness fixtures.
ALLOWED_MODULES = {
    (TESTS_DIR / "fixtures" / "db.py").resolve(),
    (TESTS_DIR / "database" / "test_engine_boundary.py").resolve(),
}


@cache
def scanned_modules() -> tuple[tuple[Path, ast.AST], ...]:
    """Scan and parse all eligible test files into AST trees, cached for meta-tests."""
    return tuple(
        (path, ast.parse(path.read_text(), filename=str(path)))
        for path in TESTS_DIR.rglob("*.py")
        if not is_meta_module(path) and not is_allowed_harness_module(path)
    )


def is_meta_module(path: Path) -> bool:
    """Check if a path is within the ``tests/meta/`` directory."""
    relative = path.resolve().relative_to(TESTS_DIR.resolve())
    return bool(relative.parts) and relative.parts[0] == "meta"


def is_allowed_harness_module(path: Path) -> bool:
    """Check if a path is explicitly allowed to use testing hooks or fixtures."""
    return path.resolve() in ALLOWED_MODULES


def direct_testing_hook_calls(tree: ast.AST) -> list[str]:
    """Return a list of direct calls to internal database testing hooks in an AST."""
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function_name = _called_name(node.func)
        if function_name in TESTING_HOOKS:
            offenders.append(f"line {node.lineno}: {function_name}")
    return offenders


def _called_name(node: ast.AST) -> str | None:
    """Extract the callable name from an AST Call node (identifier or attribute)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def local_isolation_fixtures(tree: ast.AST) -> list[str]:
    """Return names of local pytest fixtures that match reserved isolation fixture names."""
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name in ISOLATION_FIXTURE_NAMES and any(
            _is_fixture_decorator(decorator) for decorator in node.decorator_list
        ):
            offenders.append(node.name)
    return offenders


def _is_fixture_decorator(node: ast.AST) -> bool:
    """Check whether an AST decorator node represents ``@fixture`` or ``@pytest.fixture``."""
    target = node.func if isinstance(node, ast.Call) else node
    return (isinstance(target, ast.Name) and target.id == "fixture") or (
        isinstance(target, ast.Attribute) and target.attr == "fixture"
    )

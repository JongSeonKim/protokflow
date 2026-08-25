"""Tests for DESIGN.md repository discovery."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from backend.app.protokflow.core import discovery
from backend.app.protokflow.core.errors import DuplicateSlugError


def test_discovery_is_storage_and_transport_free() -> None:
    tree = ast.parse(inspect.getsource(discovery))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    for module in imported:
        assert not module.startswith(("sqlalchemy", "fastapi", "backend.database"))


def test_discover_root_and_sibling_design_files_without_recursion(
    tmp_path: Path,
) -> None:
    (tmp_path / "DESIGN.md").write_text("root", encoding="utf-8")
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    (design_dir / "admin-dark.md").write_text("admin", encoding="utf-8")
    (design_dir / "marketing.md").write_text("marketing", encoding="utf-8")
    nested = tmp_path / "src"
    nested.mkdir()
    (nested / "DESIGN.md").write_text("nested", encoding="utf-8")

    discovered = discovery.discover_design_files(tmp_path)

    assert [
        (item.slug, item.path.relative_to(tmp_path).as_posix()) for item in discovered
    ] == [
        ("default", "DESIGN.md"),
        ("admin-dark", "design/admin-dark.md"),
        ("marketing", "design/marketing.md"),
    ]


def test_discover_missing_or_empty_design_directory_returns_empty(
    tmp_path: Path,
) -> None:
    assert discovery.discover_design_files(tmp_path) == []

    (tmp_path / "design").mkdir()

    assert discovery.discover_design_files(tmp_path) == []


def test_discover_matches_markdown_suffix_case_insensitively(
    tmp_path: Path,
) -> None:
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    (design_dir / "Admin.MD").write_text("admin", encoding="utf-8")
    (design_dir / "notes.txt").write_text("notes", encoding="utf-8")

    discovered = discovery.discover_design_files(tmp_path)

    assert [(item.slug, item.path.name) for item in discovered] == [
        ("Admin", "Admin.MD")
    ]


def test_discover_duplicate_slug_raises_error(tmp_path: Path) -> None:
    (tmp_path / "DESIGN.md").write_text("root", encoding="utf-8")
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    (design_dir / "default.md").write_text("sibling", encoding="utf-8")

    with pytest.raises(DuplicateSlugError) as exc_info:
        discovery.discover_design_files(tmp_path)

    message = str(exc_info.value)
    assert "default" in message
    assert "DESIGN.md" in message
    assert "design/default.md" in message

"""Tests for DESIGN.md repository discovery."""

from __future__ import annotations

import inspect

from backend.app.protokflow.core import discovery


def test_discovery_is_storage_and_transport_free() -> None:
    source = inspect.getsource(discovery)

    assert "sqlalchemy" not in source
    assert "fastapi" not in source
    assert "backend.database" not in source


def test_discover_root_and_sibling_design_files_without_recursion(tmp_path) -> None:
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


def test_discover_missing_or_empty_design_directory_returns_empty(tmp_path) -> None:
    assert discovery.discover_design_files(tmp_path) == []

    (tmp_path / "design").mkdir()

    assert discovery.discover_design_files(tmp_path) == []

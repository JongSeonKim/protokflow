"""Discover DESIGN.md files from the repository root and design directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.app.protokflow.error.design_md import DuplicateSlugError


@dataclass(frozen=True, slots=True)
class DiscoveredDesignFile:
    """A DESIGN.md file and the slug assigned to it."""

    slug: str
    path: Path


def discover_design_files(repo_root: Path) -> list[DiscoveredDesignFile]:
    """Return root and sibling DESIGN.md files in stable order without recursion.

    The markdown suffix match is case-insensitive, so design/Admin.MD is
    discovered just like design/admin.md.
    """
    root = Path(repo_root).resolve()
    discovered: list[DiscoveredDesignFile] = []

    root_design = root / "DESIGN.md"
    if root_design.is_file():
        discovered.append(DiscoveredDesignFile(slug="default", path=root_design))

    design_dir = root / "design"
    if design_dir.is_dir():
        markdown_files = [
            path
            for path in design_dir.iterdir()
            if path.is_file() and path.suffix.lower() == ".md"
        ]
        discovered.extend(
            DiscoveredDesignFile(slug=path.stem, path=path)
            for path in sorted(markdown_files, key=lambda candidate: candidate.name)
        )

    paths_by_slug: dict[str, list[Path]] = {}
    for item in discovered:
        paths_by_slug.setdefault(item.slug, []).append(item.path)

    duplicates = {
        slug: [path.relative_to(root).as_posix() for path in paths]
        for slug, paths in paths_by_slug.items()
        if len(paths) > 1
    }
    if duplicates:
        details = "; ".join(
            f"{slug!r}: {', '.join(paths)}" for slug, paths in duplicates.items()
        )
        raise DuplicateSlugError(f"duplicate design slug(s): {details}")

    return discovered

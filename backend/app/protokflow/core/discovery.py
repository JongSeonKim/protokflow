"""Discover DESIGN.md files from the repository root and design directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DiscoveredDesignFile:
    """A DESIGN.md file and the slug assigned to it."""

    slug: str
    path: Path


def discover_design_files(repo_root: Path) -> list[DiscoveredDesignFile]:
    """Return root and sibling DESIGN.md files in stable order without recursion."""
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
            if path.is_file() and path.suffix == ".md"
        ]
        discovered.extend(
            DiscoveredDesignFile(slug=path.stem, path=path)
            for path in sorted(markdown_files, key=lambda candidate: candidate.name)
        )

    return discovered

"""Result types returned by the design system service."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from backend.app.protokflow.model import DesignSystem, DesignToken
from backend.app.protokflow.storage.design_source import DesignSourceSnapshot


@dataclass(frozen=True, slots=True)
class DesignSystemDetail:
    """Query result: the system row, its tokens, and the derived stale flag."""

    system: DesignSystem
    tokens: Sequence[DesignToken]
    stale: bool


@dataclass(frozen=True, slots=True)
class ReconciledSystem:
    """Result of reconciling a persisted system against its source file.

    ``missing`` indicates the source file was absent; callers decide whether
    that means a stale query result or a rejected patch.
    """

    system: DesignSystem
    missing: bool = False
    snapshot: DesignSourceSnapshot | None = None

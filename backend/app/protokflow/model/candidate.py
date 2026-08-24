"""Candidate model representing variant screens within a prototype run."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.app.protokflow.model.types import Json, Ulid
from backend.common.model import Base


class Candidate(Base):
    """Side-by-side compared variant within a run."""

    __tablename__ = "candidates"
    __table_args__ = (
        sa.PrimaryKeyConstraint("run_id", "candidate_key"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["prototype_runs.id"],
            ondelete="CASCADE",
        ),
        {"comment": "Candidates per prototype run"},
    )

    run_id: Mapped[str] = mapped_column(Ulid(), comment="Parent run ID")
    candidate_key: Mapped[str] = mapped_column(
        sa.String(64), comment="Candidate key (e.g. c1, c2)"
    )
    label: Mapped[str] = mapped_column(sa.Text, comment="Display label")
    position: Mapped[int] = mapped_column(
        sa.Integer, default=0, comment="Display order"
    )
    initial_tokens: Mapped[dict[str, Any]] = mapped_column(
        Json(), default_factory=dict, comment="Initial token values at creation"
    )
    token_overrides: Mapped[dict[str, Any]] = mapped_column(
        Json(), default_factory=dict, comment="Effective token overrides"
    )
    snapshot_path: Mapped[str | None] = mapped_column(
        sa.String(1024), default=None, comment="Snapshot image file path"
    )

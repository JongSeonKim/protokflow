"""Prototype run table (schema doc §5.4)."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.app.protokflow.model.types import Json, Ulid, new_ulid
from backend.common.model import Base


class PrototypeRun(Base):
    """One prototyping run; carries the resolved token snapshot for replay."""

    __tablename__ = "prototype_runs"
    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('active', 'exported', 'archived')", name="status"
        ),
        sa.Index("ix_prototype_runs_ds_created", "design_system_id", "created_time"),
        sa.ForeignKeyConstraint(
            ["design_system_id"],
            ["design_systems.id"],
            ondelete="CASCADE",
        ),
        {"comment": "Prototype runs with token snapshots"},
    )

    id: Mapped[str] = mapped_column(
        Ulid(),
        primary_key=True,
        init=False,
        default_factory=new_ulid,
        sort_order=-999,
        comment="ULID primary key",
    )
    design_system_id: Mapped[str] = mapped_column(
        Ulid(), comment="Origin system (filter/provenance)"
    )
    screen_goal: Mapped[str] = mapped_column(sa.Text, comment="What this run explores")
    layout_preset: Mapped[str] = mapped_column(
        sa.String(128), comment="e.g. split-card"
    )
    token_snapshot: Mapped[dict[str, Any]] = mapped_column(
        Json(), comment="Resolved Layer 1/2 flat map at run creation (§5.4)"
    )
    variation_axes: Mapped[list[str]] = mapped_column(
        Json(), default_factory=list, comment="Varied Layer 3 token paths"
    )
    status: Mapped[str] = mapped_column(
        sa.String(64), default="active", comment="active | exported | archived"
    )

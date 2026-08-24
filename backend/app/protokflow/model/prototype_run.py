"""Prototype run model."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.app.protokflow.model.types import Json, Ulid, new_ulid
from backend.common.model import Base


class PrototypeRun(Base):
    """Prototype run session holding token snapshots."""

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
        {"comment": "Prototype runs"},
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
        Ulid(), comment="Associated design system ID"
    )
    screen_goal: Mapped[str] = mapped_column(sa.Text, comment="Goal of this run")
    layout_preset: Mapped[str] = mapped_column(
        sa.String(128), comment="Layout preset identifier (e.g. split-card)"
    )
    token_snapshot: Mapped[dict[str, Any]] = mapped_column(
        Json(), comment="Resolved token flat map at run creation"
    )
    variation_axes: Mapped[list[str]] = mapped_column(
        Json(), default_factory=list, comment="Varied token paths"
    )
    status: Mapped[str] = mapped_column(
        sa.String(64), default="active", comment="active | exported | archived"
    )

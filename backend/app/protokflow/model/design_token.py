"""Layer 1/2 normalized design token table (schema doc §5.3)."""

from __future__ import annotations

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.app.protokflow.model.types import Ulid, new_ulid
from backend.common.model import Base


class DesignToken(Base):
    """Row-per-token normalization; reference expressions stored verbatim."""

    __tablename__ = "design_tokens"
    __table_args__ = (
        sa.CheckConstraint("tier IN ('foundation', 'component')", name="tier"),
        sa.CheckConstraint(
            "origin IN ('design_md', 'admin_ui', 'agent')", name="origin"
        ),
        sa.UniqueConstraint(
            "design_system_id", "token_path", name="uq_design_tokens_ds_path"
        ),
        sa.Index("ix_design_tokens_ds_tier", "design_system_id", "tier"),
        sa.ForeignKeyConstraint(
            ["design_system_id"],
            ["design_systems.id"],
            ondelete="CASCADE",
        ),
        {"comment": "Layer 1/2 normalized design tokens"},
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
        Ulid(), comment="Owning design system"
    )
    tier: Mapped[str] = mapped_column(sa.String(64), comment="foundation | component")
    token_path: Mapped[str] = mapped_column(
        sa.String(512), comment="e.g. colors.primary"
    )
    value: Mapped[str] = mapped_column(
        sa.Text, comment="Literal or reference expression as written"
    )
    origin: Mapped[str] = mapped_column(
        sa.String(64), default="design_md", comment="design_md | admin_ui | agent"
    )

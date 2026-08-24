"""Slot custom content model."""

from __future__ import annotations

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.app.protokflow.model.types import Ulid
from backend.common.model import Base


class SlotContent(Base):
    """Custom slot content override for a candidate."""

    __tablename__ = "slot_contents"
    __table_args__ = (
        sa.CheckConstraint("content_kind IN ('text', 'html', 'markdown')", name="kind"),
        sa.PrimaryKeyConstraint("run_id", "candidate_key", "slot_key"),
        sa.ForeignKeyConstraint(
            ["run_id", "candidate_key"],
            ["candidates.run_id", "candidates.candidate_key"],
            ondelete="CASCADE",
        ),
        {"comment": "Custom slot contents"},
    )

    run_id: Mapped[str] = mapped_column(Ulid(), comment="Parent run ID")
    candidate_key: Mapped[str] = mapped_column(
        sa.String(64), comment="Target candidate key"
    )
    slot_key: Mapped[str] = mapped_column(
        sa.String(256), comment="Slot key (e.g. headline, cta-label)"
    )
    content: Mapped[str] = mapped_column(sa.Text, comment="Slot body content")
    content_kind: Mapped[str] = mapped_column(
        sa.String(64), default="text", comment="text | html | markdown"
    )

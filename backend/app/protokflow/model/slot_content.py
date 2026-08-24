"""Slot custom content table (schema doc §5.7)."""

from __future__ import annotations

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.app.protokflow.model.types import Ulid
from backend.common.model import Base


class SlotContent(Base):
    """Upserted custom slot text for update_slot_custom."""

    __tablename__ = "slot_contents"
    __table_args__ = (
        sa.CheckConstraint("content_kind IN ('text', 'html', 'markdown')", name="kind"),
        sa.PrimaryKeyConstraint("run_id", "candidate_key", "slot_key"),
        sa.ForeignKeyConstraint(
            ["run_id", "candidate_key"],
            ["candidates.run_id", "candidates.candidate_key"],
            ondelete="CASCADE",
        ),
        {"comment": "Per-candidate custom slot contents"},
    )

    run_id: Mapped[str] = mapped_column(Ulid(), comment="Parent run")
    candidate_key: Mapped[str] = mapped_column(
        sa.String(64), comment="Target candidate key"
    )
    slot_key: Mapped[str] = mapped_column(
        sa.String(256), comment="e.g. headline, cta-label"
    )
    content: Mapped[str] = mapped_column(sa.Text, comment="Slot body")
    content_kind: Mapped[str] = mapped_column(
        sa.String(64), default="text", comment="text | html | markdown"
    )

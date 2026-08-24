"""Export record model."""

from __future__ import annotations

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.app.protokflow.model.types import Ulid, new_ulid
from backend.common.model import Base


class Export(Base):
    """Export record for generated prototype code."""

    __tablename__ = "exports"
    __table_args__ = (
        sa.CheckConstraint(
            "format IN ('react-tailwind', 'vue-tailwind', 'html-css', 'json-tokens')",
            name="format",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "candidate_key"],
            ["candidates.run_id", "candidates.candidate_key"],
            ondelete="CASCADE",
        ),
        {"comment": "Export records per candidate"},
    )

    id: Mapped[str] = mapped_column(
        Ulid(),
        primary_key=True,
        init=False,
        default_factory=new_ulid,
        sort_order=-999,
        comment="ULID primary key",
    )
    run_id: Mapped[str] = mapped_column(Ulid(), comment="Parent run ID")
    candidate_key: Mapped[str] = mapped_column(
        sa.String(64), comment="Exported candidate key"
    )
    format: Mapped[str] = mapped_column(sa.String(64), comment="Export format")
    output_path: Mapped[str | None] = mapped_column(
        sa.String(1024), default=None, comment="Written file path, if any"
    )
    byte_size: Mapped[int | None] = mapped_column(
        sa.Integer, default=None, comment="Emitted payload size in bytes"
    )

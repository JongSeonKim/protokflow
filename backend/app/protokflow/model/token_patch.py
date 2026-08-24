"""Append-only token patch history table (schema doc §5.6)."""

from __future__ import annotations

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.app.protokflow.model.types import Ulid
from backend.common.model import Base


class TokenPatch(Base):
    """Append-only patch log; current state lives in candidates overrides."""

    __tablename__ = "token_patches"
    __table_args__ = (
        sa.CheckConstraint("origin IN ('agent', 'admin_ui')", name="origin"),
        sa.Index("ix_token_patches_target", "run_id", "candidate_key", "seq"),
        sa.ForeignKeyConstraint(
            ["run_id", "candidate_key"],
            ["candidates.run_id", "candidates.candidate_key"],
            ondelete="CASCADE",
        ),
        # seq means application order; sqlite_autoincrement forbids rowid
        # reuse after pruning, which would silently corrupt that meaning.
        {"sqlite_autoincrement": True, "comment": "Append-only token patch history"},
    )

    seq: Mapped[int] = mapped_column(
        sa.Integer,
        primary_key=True,
        autoincrement=True,
        init=False,
        sort_order=-999,
        comment="Monotonic application order",
    )
    run_id: Mapped[str] = mapped_column(Ulid(), comment="Parent run")
    candidate_key: Mapped[str] = mapped_column(
        sa.String(64), comment="Target candidate key"
    )
    token_path: Mapped[str] = mapped_column(
        sa.String(512), comment="Patched token path"
    )
    origin: Mapped[str] = mapped_column(sa.String(64), comment="agent | admin_ui")
    next_value: Mapped[str] = mapped_column(sa.Text, comment="Value after the patch")
    previous_value: Mapped[str | None] = mapped_column(
        sa.Text, default=None, comment="NULL = new override"
    )

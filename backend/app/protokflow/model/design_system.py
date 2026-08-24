"""DESIGN.md-mapped design system table (schema doc §5.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.app.protokflow.model.types import Json, Timestamp, Ulid, new_ulid
from backend.common.model import Base


class DesignSystem(Base):
    """Self-contained sibling design system; one DESIGN.md = one row."""

    __tablename__ = "design_systems"
    __table_args__ = (
        sa.UniqueConstraint("slug", name="uq_design_systems_slug"),
        sa.ForeignKeyConstraint(
            ["derived_from_id"],
            ["design_systems.id"],
            ondelete="SET NULL",
        ),
        {"comment": "DESIGN.md-mapped sibling design systems"},
    )

    id: Mapped[str] = mapped_column(
        Ulid(),
        primary_key=True,
        init=False,
        default_factory=new_ulid,
        sort_order=-999,
        comment="ULID primary key",
    )
    slug: Mapped[str] = mapped_column(
        sa.String(256), comment="User/agent-facing identifier, e.g. default"
    )
    title: Mapped[str] = mapped_column(sa.Text, comment="Front matter name")
    description: Mapped[str | None] = mapped_column(
        sa.Text, default=None, comment="Front matter description"
    )
    spec_version: Mapped[str | None] = mapped_column(
        sa.String(256), default=None, comment="Front matter version"
    )
    derived_from_id: Mapped[str | None] = mapped_column(
        Ulid(), default=None, comment="Provenance of a derived system"
    )
    front_matter_extras: Mapped[dict[str, Any]] = mapped_column(
        Json(),
        default_factory=dict,
        comment="Unmodeled front matter keys preserved verbatim",
    )
    front_matter_raw: Mapped[str] = mapped_column(
        sa.Text,
        default="",
        comment="Verbatim front matter: comments, blank lines, quote style, key order",
    )
    guide_markdown: Mapped[str] = mapped_column(
        sa.Text, default="", comment="DESIGN.md body without front matter"
    )
    source_path: Mapped[str | None] = mapped_column(
        sa.String(1024), default=None, comment="Linked DESIGN.md path; NULL = DB-only"
    )
    source_digest: Mapped[str | None] = mapped_column(
        sa.String(256), default=None, comment="sha256 at last sync"
    )
    source_mtime: Mapped[float | None] = mapped_column(
        sa.Float, default=None, comment="mtime precheck (§6)"
    )
    source_size: Mapped[int | None] = mapped_column(
        sa.Integer, default=None, comment="size precheck (§6)"
    )
    synced_at: Mapped[datetime | None] = mapped_column(
        Timestamp(), default=None, comment="Last file sync time"
    )

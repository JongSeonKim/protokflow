"""Design system model mapped to DESIGN.md files."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.app.protokflow.model.types import Json, Timestamp, Ulid, new_ulid
from backend.common.model import Base


class DesignSystem(Base):
    """Design system configuration and source metadata."""

    __tablename__ = "design_systems"
    __table_args__ = (
        sa.UniqueConstraint("slug", name="uq_design_systems_slug"),
        sa.ForeignKeyConstraint(
            ["derived_from_id"],
            ["design_systems.id"],
            ondelete="SET NULL",
        ),
        {"comment": "Design systems"},
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
        sa.String(256), comment="Unique slug identifier (e.g. default)"
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
        comment="Raw front matter text",
    )
    guide_markdown: Mapped[str] = mapped_column(
        sa.Text, default="", comment="DESIGN.md body without front matter"
    )
    source_path: Mapped[str | None] = mapped_column(
        sa.String(1024), default=None, comment="Linked DESIGN.md path; NULL = DB-only"
    )
    source_digest: Mapped[str | None] = mapped_column(
        sa.String(256), default=None, comment="sha256 digest at last sync"
    )
    source_mtime_ns: Mapped[int | None] = mapped_column(
        sa.BigInteger, default=None, comment="Source file mtime in nanoseconds"
    )
    source_size: Mapped[int | None] = mapped_column(
        sa.Integer, default=None, comment="Source file size in bytes"
    )
    synced_at: Mapped[datetime | None] = mapped_column(
        Timestamp(), default=None, comment="Last file sync time"
    )

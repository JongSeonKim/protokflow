"""ORM persistence adapter for DESIGN.md source snapshots."""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.protokflow.crud.crud_design_system import design_system_dao
from backend.app.protokflow.crud.crud_design_token import design_token_dao
from backend.app.protokflow.error.storage import UnknownDesignSystemError
from backend.app.protokflow.model import DesignSystem, DesignToken
from backend.app.protokflow.model.types import utcnow
from backend.app.protokflow.storage.design_source import (
    DesignSourceSnapshot,
    SourceMetadata,
)


def build_design_system(snapshot: DesignSourceSnapshot) -> DesignSystem:
    """Build a storage model from already validated source data."""
    parsed = snapshot.parsed
    return DesignSystem(
        slug=snapshot.slug,
        title=parsed.title or snapshot.slug,
        description=parsed.description,
        spec_version=parsed.spec_version,
        front_matter_extras=parsed.front_matter_extras,
        front_matter_raw=parsed.front_matter_raw or "",
        guide_markdown=parsed.guide_markdown,
        source_root=snapshot.source_root,
        source_path=snapshot.source_path,
        source_digest=snapshot.source_digest,
        source_mtime_ns=snapshot.source_mtime_ns,
        source_size=snapshot.source_size,
        synced_at=utcnow(),
    )


def build_design_tokens(
    snapshot: DesignSourceSnapshot, design_system_id: str
) -> list[DesignToken]:
    """Build storage token models owned by ``design_system_id``.

    Ownership is enforced where it can actually be violated — by
    ``design_token_dao.replace``, which checks every supplied row against the
    parent whose token set it replaces.
    """
    return [
        DesignToken(
            design_system_id,
            token.tier,
            token.token_path,
            token.value,
        )
        for token in snapshot.parsed.tokens
    ]


async def sync_source_snapshot(
    session: AsyncSession,
    snapshot: DesignSourceSnapshot,
    *,
    existing: DesignSystem | None = None,
) -> DesignSystem:
    """Upsert one source snapshot and replace its complete token set."""
    design_system = await design_system_dao.upsert(
        session, build_design_system(snapshot), existing=existing
    )
    await design_token_dao.replace(
        session,
        design_system.id,
        build_design_tokens(snapshot, design_system.id),
    )
    return design_system


async def refresh_source_metadata(
    session: AsyncSession, slug: str, metadata: SourceMetadata
) -> DesignSystem:
    """Refresh touch-only source metadata on the caller's session."""
    system = await design_system_dao.get_by_slug(session, slug)
    if system is None:
        raise UnknownDesignSystemError(
            f"design system '{slug}' was deleted while its source was being reconciled"
        )
    system.source_mtime_ns = metadata.source_mtime_ns
    system.source_size = metadata.source_size
    await session.flush()
    return system

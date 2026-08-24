"""Unified custom SQL types for protokflow storage models (schema doc §8).

Three portable types every storage model must use, so the future Postgres
move is a variant swap instead of a schema audit:

- `Timestamp` — rejects naive datetimes, normalizes aware ones to UTC.
- `Ulid`      — TEXT(26) fixed-length identifier.
- `Json`      — sa.JSON mapping (SQLite TEXT <-> Postgres jsonb later).
"""

from __future__ import annotations

import os
import time

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

from sqlalchemy import TypeDecorator

# Crockford base32 alphabet (ULID spec): no I, L, O, U.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    """Generate a 26-char ULID: 48-bit ms timestamp + 80-bit randomness."""
    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    randomness = int.from_bytes(os.urandom(10), "big") & ((1 << 80) - 1)
    value = (timestamp_ms << 80) | randomness
    return "".join(_CROCKFORD[(value >> (5 * (25 - i))) & 0x1F] for i in range(26))


def utcnow() -> datetime:
    """UTC-aware now() for model defaults."""
    return datetime.now(UTC)


class Timestamp(TypeDecorator[datetime]):
    """UTC-aware-only datetime — naive values are rejected at bind time."""

    impl = sa.DateTime(timezone=True)
    cache_ok = True

    @property
    def python_type(self) -> type[datetime]:
        return datetime

    def process_bind_param(
        self, value: datetime | None, dialect: Any
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            # Prefect-style hard rejection: a local-timezone accident must
            # fail loudly instead of silently shifting stored instants.
            raise ValueError("Timestamps must have a timezone.")
        # Non-UTC aware values are normalized to UTC, then stored. SQLite's
        # DATETIME storage format drops tzinfo, so read-back re-attaches UTC.
        return value.astimezone(UTC)

    def process_result_value(
        self, value: datetime | None, dialect: Any
    ) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


class Ulid(TypeDecorator[str]):
    """TEXT(26) fixed-length ULID identifier."""

    impl = sa.String(26)
    cache_ok = True

    @property
    def python_type(self) -> type[str]:
        return str

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        if value is None:
            return None
        if len(value) != 26:
            raise ValueError(f"Ulid must be exactly 26 characters, got {len(value)}.")
        return value

    def process_result_value(self, value: str | None, dialect: Any) -> str | None:
        return value


class Json(TypeDecorator[Any]):
    """sa.JSON mapping for small, non-indexed structures."""

    impl = sa.JSON
    cache_ok = True

    @property
    def python_type(self) -> type[Any]:
        return object

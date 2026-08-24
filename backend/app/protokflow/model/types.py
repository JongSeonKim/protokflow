"""Custom SQLAlchemy types for protokflow models."""

from __future__ import annotations

import os
import time

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

from sqlalchemy import TypeDecorator

# Crockford base32 alphabet for ULID
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    """Generate a 26-character ULID."""
    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    randomness = int.from_bytes(os.urandom(10), "big") & ((1 << 80) - 1)
    value = (timestamp_ms << 80) | randomness
    return "".join(_CROCKFORD[(value >> (5 * (25 - i))) & 0x1F] for i in range(26))


def utcnow() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(UTC)


class Timestamp(TypeDecorator[datetime]):
    """UTC datetime type that enforces timezone awareness."""

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
            raise ValueError("Timestamps must have a timezone.")
        return value.astimezone(UTC)

    def process_result_value(
        self, value: datetime | None, dialect: Any
    ) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


class Ulid(TypeDecorator[str]):
    """Fixed-length (26-char) ULID string identifier."""

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
    """JSON type mapping."""

    impl = sa.JSON
    cache_ok = True

    @property
    def python_type(self) -> type[Any]:
        return object

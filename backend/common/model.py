from datetime import datetime
from typing import Annotated, Any

from sqlalchemy import BigInteger, DateTime, MetaData, Text, TypeDecorator
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    MappedAsDataclass,
    declared_attr,
    mapped_column,
)

from backend.utils.timezone import timezone

# Common Mapped type primary key, needs to be added manually, refer to the following usage
# MappedBase -> id: Mapped[id_key]
# DataClassBase && Base -> id: Mapped[id_key] = mapped_column(init=False)
id_key = Annotated[
    int,
    mapped_column(
        BigInteger,
        primary_key=True,
        unique=True,
        index=True,
        autoincrement=True,
        sort_order=-999,
        comment="Primary key ID",
    ),
]


class UniversalText(TypeDecorator[str]):
    """PostgreSQL, MySQL compatibility (long) text type"""

    # This backend supports sqlite/postgresql only; TEXT is correct for both.
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:  # ruff:ignore[missing-type-function-argument]
        return value

    def process_result_value(self, value: str | None, dialect) -> str | None:  # ruff:ignore[missing-type-function-argument]
        return value


class TimeZone(TypeDecorator[datetime]):
    """PostgreSQL, MySQL compatibility timezone-aware type"""

    impl = DateTime(timezone=True)
    cache_ok = True

    @property
    def python_type(self) -> type[datetime]:
        return datetime

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:  # ruff:ignore[missing-type-function-argument]
        if value is not None and value.utcoffset() != timezone.now().utcoffset():
            # TODO Handle daylight saving time offset
            value = timezone.from_datetime(value)
        return value

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:  # ruff:ignore[missing-type-function-argument]
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.tz_info)
        return value


class DateTimeMixin(MappedAsDataclass):
    """DateTime Mixin dataclass"""

    created_time: Mapped[datetime] = mapped_column(
        TimeZone,
        init=False,
        default_factory=timezone.now,
        sort_order=999,
        comment="Created time",
    )
    updated_time: Mapped[datetime | None] = mapped_column(
        TimeZone,
        init=False,
        onupdate=timezone.now,
        sort_order=999,
        comment="Updated time",
    )


class LogicalDeleteMixin(MappedAsDataclass):
    """Logical delete Mixin dataclass"""

    deleted: Mapped[int] = mapped_column(
        BigInteger,
        init=False,
        default=0,
        server_default="0",
        sort_order=999,
        comment="Logical delete flag (0: No, primary key ID: Yes)",
    )
    deleted_time: Mapped[datetime | None] = mapped_column(
        TimeZone,
        init=False,
        default=None,
        sort_order=999,
        comment="Deleted time",
    )


class MappedBase(AsyncAttrs, DeclarativeBase):
    """
    Declarative base class, exists as the parent class for all base classes or data model classes

    `AsyncAttrs <https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#sqlalchemy.ext.asyncio.AsyncAttrs>`__

    `DeclarativeBase <https://docs.sqlalchemy.org/en/20/orm/declarative_config.html>`__

    `mapped_column() <https://docs.sqlalchemy.org/en/20/orm/mapping_api.html#sqlalchemy.orm.mapped_column>`__
    """

    # Explicit constraint naming (ck_/uq_/fk_/ix_/pk_ prefixes) so a future
    # Alembic adoption does not trip over anonymous-constraint false diffs
    # (docs/concepts/database-schema.md §5 preamble).
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )

    @declared_attr.directive
    def __tablename__(self) -> str:
        """Generate table name"""
        return self.__name__.lower()

    @declared_attr.directive
    def __table_args__(self) -> tuple[Any, ...] | dict[str, Any]:
        """Table configuration"""
        return {"comment": self.__doc__ or ""}


class DataClassBase(MappedAsDataclass, MappedBase):
    """
    Declarative dataclass base class, with dataclass integration, allows for more advanced configuration,
    but you must be aware of some of its features, especially when used with DeclarativeBase

    `MappedAsDataclass <https://docs.sqlalchemy.org/en/20/orm/dataclasses.html#orm-declarative-native-dataclasses>`__
    """

    __abstract__ = True


class Base(DataClassBase, DateTimeMixin, LogicalDeleteMixin):
    """
    Declarative dataclass base class, with dataclass integration, and includes Mixin dataclass base table structure
    """

    __abstract__ = True

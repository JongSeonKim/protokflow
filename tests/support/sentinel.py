"""Model sentinel generation utilities for CRUD and drift-guard testing."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import ColumnProperty, Mapper

from backend.app.protokflow.model.types import Json
from backend.common.model import DateTimeMixin, LogicalDeleteMixin
from backend.utils.timezone import timezone

DEFAULT_AUDIT_MIXINS: tuple[type, ...] = (DateTimeMixin, LogicalDeleteMixin)


def get_audit_column_names(
    *mixins: type,
) -> set[str]:
    """Return all non-private attribute names defined on the given audit mixin classes."""
    target_mixins = mixins if mixins else DEFAULT_AUDIT_MIXINS
    return {
        name
        for mixin in target_mixins
        for name in dir(mixin)
        if not name.startswith("_")
    }


def generate_sentinel(
    column_or_attr: ColumnProperty | sa.Column[Any],
) -> Any:
    """Generate a distinct non-default sentinel value for a SQLAlchemy column based on its type."""
    if isinstance(column_or_attr, ColumnProperty):
        col = column_or_attr.columns[0]
        name = column_or_attr.key
    elif isinstance(column_or_attr, sa.Column):
        col = column_or_attr
        name = col.name
    else:
        raise TypeError(
            f"Expected ColumnProperty or Column, got {type(column_or_attr)!r}"
        )

    if isinstance(col.type, (sa.JSON, Json)):
        return {f"sentinel_{name}": f"value_{name}"}

    py_type = getattr(col.type, "python_type", None)
    if py_type is str:
        return f"sentinel_{name}"
    if py_type is int:
        return 424242
    if py_type is float:
        return 42.42
    if py_type is bool:
        return True
    if py_type is datetime:
        return timezone.now()
    if py_type is dict:
        return {f"sentinel_{name}": f"value_{name}"}
    if py_type is list:
        return [f"sentinel_{name}"]

    raise TypeError(
        f"Cannot generate sentinel value for column {name!r} of type {col.type}"
    )


def generate_model_sentinels(
    model_cls: type,
    *,
    excluded: set[str] | None = None,
    audit_mixins: tuple[type, ...] = DEFAULT_AUDIT_MIXINS,
) -> dict[str, Any]:
    """Generate a mapping of column names to sentinel values for all updatable model columns.

    Excludes primary keys/provenance columns specified in ``excluded`` as well as
    audit columns derived from ``audit_mixins``.
    """
    mapper: Mapper[Any] = sa.inspect(model_cls)
    excluded_set = set(excluded or ()) | get_audit_column_names(*audit_mixins)

    return {
        attr.key: generate_sentinel(attr)
        for attr in mapper.column_attrs
        if attr.key not in excluded_set
    }

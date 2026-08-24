import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base


class SchemaMeta(Base):
    """Schema version key/value table"""

    __tablename__ = "schema_meta"

    key: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    value: Mapped[str] = mapped_column(sa.Text)

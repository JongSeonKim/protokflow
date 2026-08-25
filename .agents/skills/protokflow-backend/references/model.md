# Database Model Standards

## Model Base Class

- Explicitly specify table name (`__tablename__`)
- Primary key must be explicitly defined

```python
from sqlalchemy.orm import Mapped, mapped_column
from backend.common.model import Base, id_key


class MyModel(Base):
    """Model table"""

    __tablename__ = 'my_model'

    id: Mapped[id_key] = mapped_column(init=False)
    name: Mapped[str] = mapped_column(comment='Name')
    status: Mapped[int] = mapped_column(default=1, comment='Status')
```

## Field Types

```python
import sqlalchemy as sa
from backend.common.model import TimeZone, UniversalText
```

**String (common lengths: 32, 64, 128, 256, 512)**

```python
name: Mapped[str] = mapped_column(sa.String(64), comment='Name')
```

**Nullable string**

```python
email: Mapped[str | None] = mapped_column(sa.String(256), default=None, comment='Email')
```

**Integer**

```python
status: Mapped[int] = mapped_column(default=1, comment='Status')
```

**Boolean**

```python
is_active: Mapped[bool] = mapped_column(default=True, comment='Is active')
```

**Datetime (timezone compatible)**

```python
event_time: Mapped[datetime] = mapped_column(TimeZone, comment='Event time')
```

**Long text (MySQL/PostgreSQL compatible)**

```python
content: Mapped[str] = mapped_column(UniversalText, comment='Content')
```

**Unique index**

```python
username: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True, comment='Username')
```

## Primary Key Modes

Configured via `DATABASE_PK_MODE`:

- **autoincrement**: Auto-increment ID (default)
- **snowflake**: Snowflake algorithm ID

> ⚠️ **Warning**: Do not arbitrarily switch primary key modes, otherwise it will cause fatal issues!

## Database Migration

**Generate migration script**

```bash
alembic revision --autogenerate -m "Description information"
```

**Execute migration**

```bash
alembic upgrade head
```

**Rollback**

```bash
alembic downgrade -1
```

## Complete Example

```python
import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key, TimeZone, UniversalText


class Article(Base):
    """Article table"""

    __tablename__ = 'sys_article'

    id: Mapped[id_key] = mapped_column(init=False)
    title: Mapped[str] = mapped_column(sa.String(256), comment='Title')
    content: Mapped[str] = mapped_column(UniversalText, comment='Content')
    author_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='Author ID')
    status: Mapped[int] = mapped_column(default=1, comment='Status (0 draft, 1 published)')
    published_at: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='Published at')
    view_count: Mapped[int] = mapped_column(default=0, comment='View count')
```

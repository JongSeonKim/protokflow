# Schema Reference

## Base Class Usage

All Schemas should inherit from `SchemaBase`:

```python
class UserSchemaBase(SchemaBase):
    """User base schema"""

    username: str
    email: str | None = None
```

## Field Definition

### Required Fields

It is **not recommended** to set the default value of required fields to `...`.

```python
username: str = Field(description='Username')
```

### description Parameter

It is **recommended** to add a `description` parameter to all fields, which is very useful for API documentation:

```python
class CreateUserParam(SchemaBase):
    username: str = Field(description='Username')
    email: str | None = Field(None, description='Email')
    status: int = Field(default=1, description='Status (0 disabled, 1 enabled)')
```

### Optional Fields

Update params typically have all fields as optional:

```python
class UpdateUserParam(SchemaBase):
    username: str | None = Field(None, description='Username')
    email: str | None = Field(None, description='Email')
    status: int | None = Field(None, description='Status')
```

## Complete Example

```python
from datetime import datetime

from pydantic import Field

from backend.common.schema import SchemaBase


class ArticleSchemaBase(SchemaBase):
    """Article base schema"""

    title: str = Field(description='Title')
    content: str = Field(description='Content')
    status: StatusType = Field(description='Status')


class CreateArticleParam(ArticleSchemaBase):
    """Create article parameters"""


class UpdateArticleParam(ArticleSchemaBase):
    """Update article parameters"""


class DeleteArticleParam(SchemaBase):
    """Batch delete article parameters"""

    ids: list[int] = Field(description='Article ID list')


class GetArticleDetail(ArticleSchemaBase):
    """Article detail response"""

    id: int = Field(description='Article ID')
    created_time: datetime = Field(description='Created time')
    updated_time: datetime | None = Field(None, description='Updated time')


class GetArticleWithAuthorDetail(GetArticleDetail):
    """Article detail response (with author info)"""

    author_name: str = Field(description='Author name')
```

## Camel Case Response

See [the api reference guide](references/api.md) for details.

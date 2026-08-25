# API Reference

## Route Structure

```
backend
├── app
│   ├── xxx                           # Custom app (Contains sub-packages).
│   │   └── api
│   │       ├── v1
│   │       │   └── xxx               # Sub-package
│   │       │       ├── __init__.py   # Routes in the xxx.py file within this file are registered within the subpack.
│   │       │       ├── xxx.py
│   │       │       └── ...
│   │       ├── __init__.py
│   │       └── router.py             # Register the routes in the __init__.py files of all sub-packages within this file.
│   └── xxx                           # Custom app (No sub-packages are included).
│       └── api
│           ├── v1
│           │   ├── __init__.py       # Do nothing.
│           │   ├── xxx.py
│           │   └── ...
│           ├── __init__.py
│           └── router.py             # Register all routes from the xxx.py files within this file.
├── __init__.py
└── router.py                         # Register all routes in the router.py file under the app directory within this file.
```

### Route Import Rules

All API route parameters should be uniformly named `router`. When importing, always use `as` aliases to avoid conflicts:

```python
from backend.app.admin.api.v1.sys.user import router as user_router
```

### RESTful Route Conventions

```
GET    /api/v1/resources/all     # All (non-paginated)
GET    /api/v1/resources         # List (paginated)
GET    /api/v1/resources/{pk}    # Details
POST   /api/v1/resources         # Create
PUT    /api/v1/resources/{pk}    # Update
DELETE /api/v1/resources/{pk}    # Delete
DELETE /api/v1/resources         # Batch delete
```

## Database Transaction

### CurrentSession (Read-only Session)

Used for query operations:

```python
@router.get('/users')
async def get_all_users(db: CurrentSession) -> ResponseModel:
    data = await user_service.get_all(db=db)
    return response_base.success(data=data)
```

### CurrentSessionTransaction (Transaction Session)

Used for create/update/delete operations:

```python
@router.post('/users')
async def create_user(db: CurrentSessionTransaction, obj: CreateApiParam) -> ResponseModel:
    await user_service.create(db=db, obj=obj)
    return response_base.success()
```

### Manual Transaction (begin)

Used for scenarios that need to start a transaction at any point:

```python
async with async_db_session.begin() as db:
    ...
```

---

## Response Standards

### Response Models

**No data response**

```python
@router.create('/users')
async def create_user(db: CurrentSessionTransaction, obj: CreateApiParam) -> ResponseModel:
    await user_service.create(db=db, obj=obj)
    return response_base.success()
```

**With data response**

```python
@router.get('/{pk}')
async def get_user(db: CurrentSession, pk: int) -> ResponseSchemaModel[GetApiDetail]:
    data = await user_service.get(db=db, pk=pk)
    return response_base.success(data=data)
```

### Response Methods

| Method                         | Purpose                                | Default Response                                           |
|--------------------------------|----------------------------------------|------------------------------------------------------------|
| `response_base.success()`      | Success response                       | `{"code": 200, "msg": "Request successful", "data": null}` |
| `response_base.fail()`         | Failure response                       | `{"code": 400, "msg": "Request error", "data": null}`      |
| `response_base.fast_success()` | High-performance response (large JSON) | Same as success, but skips Pydantic validation             |

### Camel Case Response

To automatically convert response data to lowerCamelCase (e.g., `created_time` → `createdTime`), modify
`backend/common/schema.py`:

```python
from pydantic.alias_generators import to_camel


class SchemaBase(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )
```

After configuration, response data will be automatically converted.

## Error Handling

Raise typed errors from the service layer; the global exception handlers convert them to standard responses. Each error carries an HTTP `code` and an i18n-resolvable `msg`.

```python
from backend.common.exception import errors

user = await user_dao.get(db, pk)
if not user:
    raise errors.NotFoundError(msg='사용자를 찾을 수 없습니다')  # 404
if not user.is_staff:
    raise errors.ForbiddenError(msg='권한이 없습니다')  # 403
```

| Error                                       | HTTP    |
|---------------------------------------------|---------|
| `NotFoundError`                             | 404     |
| `ForbiddenError`                            | 403     |
| `RequestError` / `InvalidCredentialsError`  | 400 / 401 |
| `TooManyRequestsError`                      | 429     |
| `ServerError`                               | 500     |

For i18n-templated messages, pair `CustomError` with a predefined error object: `raise errors.CustomError(error=<PredefinedError>, **msg_kwargs)` — `msg_kwargs` interpolate `{...}` placeholders in the template.

## Pagination

List endpoints declare `DependsPagination`, return `ResponseSchemaModel[PageData[Schema]]`, and let the service build the page via `paging_data(db, select)`.

```python
from backend.common.pagination import DependsPagination, PageData


@router.get(
    '',
    summary='Get user list (paginated)',
    dependencies=[DependsJwtAuth, DependsPagination],
)
async def get_users_paginated(
    db: CurrentSession,
    username: Annotated[str | None, Query()] = None,
) -> ResponseSchemaModel[PageData[GetUserDetail]]:
    page_data = await user_service.get_list(db=db, username=username)
    return response_base.success(data=page_data)
```

Inside the service, build the SQLAlchemy `select` and call `paging_data`:

```python
from backend.common.pagination import paging_data

stmt = select(User).where(...).order_by(User.id)
return await paging_data(db, stmt)
```

`page` / `size` are parsed from the query string automatically by `DependsPagination`. For cursor pagination, use `CursorPageData` + `cursor_paging_data`.

## I18n

### Usage Syntax

Chain-style access to get field values from the language pack

```python
msg = t('response.success')
```

### Language Pack Location

`backend/locale` directory, supports `.json` and `.yaml/.yml` files

### Dynamic Switching

Automatically retrieves the `Accept-Language` parameter from the request header

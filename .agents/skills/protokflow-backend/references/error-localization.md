# Error Message Localization

How to raise **operator-facing business errors** so the message is localized and, when the
frontend branches on it, carries a stable language-independent code. Builds on the base i18n
mechanism in `references/i18n.md` (the `t()` function + `Accept-Language` switching).

## The rule

Business error messages that the admin frontend displays must be raised through
`t('error.<domain>.<key>')`, never as raw English literals. The backend is the single source
of operator copy; the frontend must not string-match backend wording.

- **Locale packs:** `backend/locale/ko-KR.yaml` and `backend/locale/en-US.json`.
- **Always add the key to BOTH packs.** A missing key resolves to the raw dotted key string
  (not a translation), so the `en-US` entry is the degrade-to-English fallback. Default
  language is `ko-KR`, so a request without `Accept-Language` gets Korean copy.
- **Namespace:** `error.<domain>.<key>` (e.g. `error.role.name_conflict`).

## Decision: copy-only vs behavioral code

| Frontend behavior | Mechanism | Envelope |
|-------------------|-----------|----------|
| Just **displays** the message (name collisions, guard rejections) | `ConflictError(msg=t('error.<domain>.<key>'))` | HTTP-status `code` (409), localized `msg` |
| **Branches** on the error (different UI per conflict type) | `CustomError(error=CustomErrorCode.X, ...)` | numeric `code` from the registry member, localized `msg` |

Add behavioral codes **only where the frontend acts differently** per error. Copy-only is the
default — don't mint a code just to localize a message.

### Copy-only (most conflicts)

```python
from backend.common.i18n import t

raise errors.ConflictError(msg=t('error.role.name_conflict'))
```

### Behavioral code

The code vocabulary lives in **`CustomErrorCode`** (`backend/common/response/response_code.py`)
— the single source of truth. Each member is a `(numeric_code, 'error.<domain>.<key>')` pair:

```python
# response_code.py
class CustomErrorCode(CustomCodeBase):
    EMAIL_VERIFY_ERROR = (40001, 'error.email_verify.error')
    MENU_HAS_CHILDREN = (40901, 'error.menu.has_children')  # 409xx band = conflict-class
    MENU_MAPPED_TO_ROLES = (40902, 'error.menu.mapped_to_roles')
```

```python
# service
raise errors.CustomError(error=CustomErrorCode.MENU_HAS_CHILDREN)
```

`CustomError` sets the envelope `code` to the member's numeric code and `msg` to its
i18n-resolved string — no new envelope field, no `exception_handler.py` change.

> **HTTP status note:** a numeric code that is not a valid HTTP status (e.g. `40901`) makes the
> handler fall back to **HTTP 400** (same as `EMAIL_VERIFY_ERROR`). The semantic lives in the
> envelope `code`, which is what the frontend reads — not the HTTP status. Don't expect 409.

## Templates (parameterized messages)

Store the placeholder in the locale value and pass it as a kwarg. `t()` interpolates via
`str.format(**kwargs)`:

```yaml
# ko-KR.yaml
error:
  menu:
    mapped_to_roles: "이 메뉴를 사용하는 역할이 {count}개 있어 삭제할 수 없습니다. ..."
  auth:
    account_locked_temp: "계정이 잠겼습니다. {minutes}분 후에 다시 시도해 주세요."
```

```python
# copy-only template
raise errors.ConflictError(msg=t('error.auth.account_locked_temp', minutes=remaining))
```

For a **`CustomError`**, pass the kwargs straight to the constructor — it interpolates the
resolved template (because `CustomErrorCode.msg` resolves the template *without* kwargs, the
constructor applies `.format()`):

```python
raise errors.CustomError(
    error=CustomErrorCode.MENU_MAPPED_TO_ROLES,
    data={'role_count': role_count},  # machine-readable — frontend never parses the message
    count=role_count,  # interpolated into the localized msg
)
```

Use the **same placeholder name in both packs** (`{count}` in ko and en) or one pack won't
interpolate.

## Structured data over message-parsing

When the frontend needs a value (a count, an id), put it in `data=` so it never regex-parses
the message. The localized `msg` is for humans; `data` is the machine contract.

## Contract (numeric code values)

The numeric `CustomErrorCode` **values** are a backend-frontend seam: the frontend branches on
them. **Ratify a new value with the frontend before shipping** — changing an assigned number
later is a breaking change. Reserve a band per class (e.g. `409xx` for conflict-class).

## Adding a new localized error — checklist

1. Add the key to **both** `ko-KR.yaml` and `en-US.json` under `error.<domain>.<key>`.
2. Copy-only? → `raise errors.ConflictError(msg=t('error.<domain>.<key>'))` (or the matching
   error class — `RequestError`, `AuthorizationError`, etc.).
3. Frontend branches on it? → add a `CustomErrorCode` member (ratify the number cross-repo) and
   `raise errors.CustomError(error=..., data=..., **template_kwargs)`.
4. Parameterized? → use `{name}` placeholders, identical in both packs.

## Precedents in the codebase

- `backend/common/response/response_code.py` — `CustomErrorCode` registry.
- `backend/common/exception/errors.py` — `CustomError` (interpolates kwargs),
    pattern for *new* behavioral codes; use `CustomErrorCode` instead.
- `backend/common/exception/exception_handler.py` — `custom_exception_handler` emits
  `code`/`msg`/`success`/`data`; do not change the envelope keys.

---
name: protokflow-backend
description: Used for developing ProtokFlow backend. Provide complete architecture specifications, coding styles, and development guidance.
---

## Core Architecture

Project adopts **Three-tier architecture**:

| Layer   | Responsibility                                                     |
|---------|--------------------------------------------------------------------|
| API     | Route processing, parameter validation, and response return        |
| Schema  | Data transfer objects, request/response data structure definitions |
| Service | Business logic, data processing, exception handling                |
| CRUD    | Database operations (inherits `CRUDPlus`)                          |
| Model   | ORM models (inherits `Base`)                                       |

### App Module Boundaries

`backend/app/` is split into feature apps (`protokflow`).

## Development Workflow

1. Define database models (model)
2. Define data validation models (schema)
3. Define routes (router)
4. Write business logic (service)
5. Write database operations (crud)

## Detailed Guides

| Module             | Document                        |
|--------------------|---------------------------------|
| API                | references/api.md               |
| Coding Style       | references/coding-style.md      |
| Config             | references/config.md            |
| Schema             | references/schema.md            |
| Error Localization | references/error-localization.md |
| i18n Mechanism     | references/i18n.md              |
| Model              | references/model.md             |
| Naming             | references/naming.md            |
| Schema             | references/schema.md            |

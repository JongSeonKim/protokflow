from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi_pagination import add_pagination
from starlette.middleware.cors import CORSMiddleware

from backend.app.router import router
from backend.common.exception.exception_handler import register_exception
from backend.common.log import set_custom_logfile, setup_logging
from backend.common.response.response_code import StandardResponseCode
from backend.core.conf import settings
from backend.database.db import initialize_database
from starlette_context.middleware import ContextMiddleware
from backend.middleware.access_middleware import AccessMiddleware
from backend.middleware.i18n_middleware import I18nMiddleware
from backend.middleware.state_middleware import StateMiddleware
from backend.utils.openapi import ensure_unique_route_names, simplify_operation_ids
from backend.utils.serializers import MsgSpecJSONResponse

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@asynccontextmanager
async def register_init(app: FastAPI) -> AsyncGenerator[None]:
    # Transitional wiring: the parent U5 runtime start owner replaces this call.
    await initialize_database(worktree_root=Path.cwd())
    yield


def register_app() -> FastAPI:
    """Register FastAPI application"""

    app = FastAPI(
        title=settings.FASTAPI_TITLE,
        description=settings.FASTAPI_DESCRIPTION,
        docs_url=settings.FASTAPI_DOCS_URL,
        redoc_url=settings.FASTAPI_REDOC_URL,
        openapi_url=settings.FASTAPI_OPENAPI_URL,
        default_response_class=MsgSpecJSONResponse,
        lifespan=register_init,
    )

    # Register components
    register_logger()
    register_middleware(app)
    register_router(app)
    register_page(app)
    register_exception(app)

    return app


def register_logger() -> None:
    """Register logger"""
    setup_logging()
    set_custom_logfile()


def register_middleware(app: FastAPI) -> None:
    """
    Register middleware (execution order from bottom to top)

    :param app: FastAPI application instance
    :return:
    """
    # State
    app.add_middleware(StateMiddleware)

    # I18n
    app.add_middleware(I18nMiddleware)

    # Access log
    app.add_middleware(AccessMiddleware)

    # ContextVar
    app.add_middleware(
        ContextMiddleware,
        default_error_response=MsgSpecJSONResponse(
            content={
                "code": StandardResponseCode.HTTP_400,
                "msg": "BAD_REQUEST",
                "data": None,
            },
            status_code=StandardResponseCode.HTTP_400,
        ),
    )

    # CORS
    # https://github.com/fastapi-practices/fastapi-best-architecture/pull/789/changes
    # https://github.com/open-telemetry/opentelemetry-python-contrib/issues/4031
    if settings.MIDDLEWARE_CORS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ALLOWED_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=settings.CORS_EXPOSE_HEADERS,
        )


def register_router(app: FastAPI) -> None:
    """
    Register routes

    :param app: FastAPI application instance
    :return:
    """
    # API
    app.include_router(router)

    # Extra
    ensure_unique_route_names(app)
    simplify_operation_ids(app)


def register_page(app: FastAPI) -> None:
    """
    Register pagination query function

    :param app: FastAPI application instance
    :return:
    """
    add_pagination(app)

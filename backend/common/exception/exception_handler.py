from typing import TYPE_CHECKING, Any, cast

from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from uvicorn.protocols.http.h11_impl import STATUS_PHRASES

from backend.common.context import ctx
from backend.common.exception.errors import BaseExceptionError
from backend.common.i18n import i18n, t
from backend.common.response.response_code import (
    StandardResponseCode,
)
from backend.core.conf import settings
from backend.utils.serializers import MsgSpecJSONResponse
from backend.utils.trace_id import get_request_trace_id

if TYPE_CHECKING:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse


def _get_exception_code(status_code: int) -> int:
    """
    Get return status code (available status codes based on RFC definition)

    `python status code standard support <https://github.com/python/cpython/blob/6e3cc72afeaee2532b4327776501eb8234ac787b/Lib/http/__init__.py#L7>`__

    `IANA status code registration table <https://www.iana.org/assignments/http-status-codes/http-status-codes.xhtml>`__

    :param status_code: HTTP status code
    :return:
    """
    try:
        STATUS_PHRASES[status_code]
    except Exception:
        return StandardResponseCode.HTTP_400

    return status_code


async def _validation_exception_handler(exc: RequestValidationError | ValidationError):
    """
    Data validation exception handling

    :param exc: Validation exception
    :return:
    """
    errors = []
    for error in exc.errors():
        # Use custom error message if not en-US language
        if i18n.current_language != "en-US":
            custom_message = t(f"pydantic.{error['type']}")
            if custom_message:
                error_ctx = error.get("ctx")
                if not error_ctx:
                    error["msg"] = custom_message
                else:
                    e = error_ctx.get("error")
                    if e:
                        error["msg"] = custom_message.format(**error_ctx)
                        error["ctx"]["error"] = (
                            e.__str__().replace("'", '"')
                            if isinstance(e, Exception)
                            else None
                        )
        errors.append(error)
    error = errors[0]
    if error.get("type") == "json_invalid":
        message = "json parse failed"
    else:
        error_input = error.get("input")
        field = str(error.get("loc")[-1])
        error_msg = error.get("msg")
        message = f"{field} {error_msg}, Input: {error_input}"
    msg = f"Invalid request parameters: {message}"
    data = {"errors": errors}
    content = {
        "code": StandardResponseCode.HTTP_422,
        "msg": msg,
        "success": False,
        "data": data,
    }
    ctx.__request_validation_exception__ = (
        content  # Used to get exception information in middleware
    )
    content.update(trace_id=get_request_trace_id())
    return MsgSpecJSONResponse(
        status_code=StandardResponseCode.HTTP_422, content=content
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    Global HTTP exception handling

    :param request: FastAPI request object
    :param exc: HTTP exception
    :return:
    """
    content = {
        "code": exc.status_code,
        "msg": exc.detail,
        "success": False,
        "data": None,
    }
    ctx.__request_http_exception__ = content
    content.update(trace_id=get_request_trace_id())
    return MsgSpecJSONResponse(
        status_code=_get_exception_code(exc.status_code),
        content=content,
        headers=exc.headers,
    )


async def fastapi_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """
    FastAPI data validation exception handling

    :param request: FastAPI request object
    :param exc: Validation exception
    :return:
    """
    return await _validation_exception_handler(exc)


async def pydantic_validation_exception_handler(
    request: Request,
    exc: ValidationError,
) -> JSONResponse:
    """
    Pydantic data validation exception handling

    :param request: Request object
    :param exc: Validation exception
    :return:
    """
    return await _validation_exception_handler(exc)


async def assertion_error_handler(
    request: Request, exc: AssertionError
) -> JSONResponse:
    """
    Assertion error handling

    :param request: FastAPI request object
    :param exc: Assertion error
    :return:
    """
    content = {
        "code": StandardResponseCode.HTTP_500,
        "msg": str("".join(exc.args) if exc.args else exc.__doc__),
        "success": False,
        "data": None,
    }
    ctx.__request_assertion_error__ = content
    content.update(trace_id=get_request_trace_id())
    return MsgSpecJSONResponse(
        status_code=StandardResponseCode.HTTP_500,
        content=content,
    )


async def custom_exception_handler(
    request: Request, exc: BaseExceptionError
) -> JSONResponse:
    """
    Global custom exception handling

    :param request: FastAPI request object
    :param exc: Custom exception
    :return:
    """
    content = {
        "code": exc.code,
        "msg": str(exc.msg),
        "success": False,
        "data": exc.data or None,
    }
    ctx.__request_custom_exception__ = content
    content.update(trace_id=get_request_trace_id())
    status_code = (
        exc.http_status
        if exc.http_status is not None
        else _get_exception_code(exc.code)
    )
    return MsgSpecJSONResponse(
        status_code=status_code,
        content=content,
        background=exc.background,
        headers=exc.headers,
    )


async def all_unknown_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """
    Global unknown exception handling

    :param request: FastAPI request object
    :param exc: Unknown exception
    :return:
    """
    content = {
        "code": StandardResponseCode.HTTP_500,
        "msg": str(exc),
        "success": False,
        "data": None,
    }
    content.update(trace_id=get_request_trace_id())
    return MsgSpecJSONResponse(
        status_code=StandardResponseCode.HTTP_500,
        content=content,
    )


async def cors_custom_code_500_exception_handler(
    app: FastAPI,
    request: Request,
    exc: BaseExceptionError | Exception,
) -> JSONResponse:
    """
    CORS 500 exception handler.

    Ensures 500 error responses include CORS headers so browsers can
    read the error body on cross-origin requests. Without this, the
    FastAPI CORS middleware may not cover responses generated directly
    by exception handlers.

    :param app: FastAPI application instance
    :param request: FastAPI request object
    :param exc: Custom or unknown exception
    :return:
    """

    # If the exception is a project-defined BaseExceptionError, use its
    # own code/msg/data so the intended error format is preserved.
    if isinstance(exc, BaseExceptionError):
        content = {
            "code": exc.code,
            "msg": exc.msg,
            "data": exc.data,
        }
    else:
        content = {
            "code": StandardResponseCode.HTTP_500,
            "msg": str(exc),
            "data": None,
        }

    # Store the exception content on the request context so downstream
    # middleware can inspect the error details (e.g. for logging).
    if isinstance(exc, BaseExceptionError):
        ctx.__request_custom_exception__ = content
    else:
        ctx.__request_unknown_exception__ = content

    # Attach the trace ID and build the JSON response. Use the exception's
    # own HTTP status for custom errors; fall back to standard 500 otherwise.
    content.update(trace_id=get_request_trace_id())
    response = MsgSpecJSONResponse(
        status_code=exc.code
        if isinstance(exc, BaseExceptionError)
        else StandardResponseCode.HTTP_500,
        content=content,
        background=exc.background if isinstance(exc, BaseExceptionError) else None,
    )

    # --- CORS header injection ---
    # Exception handlers bypass the normal CORS middleware pipeline, so
    # cross-origin browsers would see no CORS headers and reject the
    # response. We manually compute and attach the necessary headers.
    origin = request.headers.get("origin")
    if origin:
        # Instantiate CORSMiddleware just to reuse its header-logic helpers.
        cors = CORSMiddleware(
            app=app,
            allow_origins=settings.CORS_ALLOWED_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=settings.CORS_EXPOSE_HEADERS,
        )
        # Apply the standard CORS response headers (Allow-Methods, etc.).
        response.headers.update(cors.simple_headers)

        # Credential-aware origin handling: when credentials (cookies) are
        # present, `Access-Control-Allow-Origin` cannot be `*`.
        has_cookie = "cookie" in request.headers
        if cors.allow_all_origins and has_cookie:
            # Replace the wildcard with the actual request origin.
            response.headers["Access-Control-Allow-Origin"] = origin
        elif not cors.allow_all_origins and cors.is_allowed_origin(origin=origin):
            # Echo the allowed origin and add Vary so caches respect it.
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers.add_vary_header("Origin")
    return response


def register_exception(app: FastAPI) -> None:
    """Register global exception handlers on the FastAPI app."""
    app.add_exception_handler(HTTPException, cast(Any, http_exception_handler))
    app.add_exception_handler(
        RequestValidationError, cast(Any, fastapi_validation_exception_handler)
    )
    app.add_exception_handler(
        ValidationError, cast(Any, pydantic_validation_exception_handler)
    )
    app.add_exception_handler(AssertionError, cast(Any, assertion_error_handler))
    app.add_exception_handler(BaseExceptionError, cast(Any, custom_exception_handler))
    app.add_exception_handler(Exception, cast(Any, all_unknown_exception_handler))

    if settings.MIDDLEWARE_CORS:

        async def _cors_handler(
            req: Request, exc: BaseExceptionError | Exception
        ) -> JSONResponse:
            return await cors_custom_code_500_exception_handler(app, req, exc)

        app.add_exception_handler(StandardResponseCode.HTTP_500, _cors_handler)

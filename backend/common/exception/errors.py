from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from backend.common.response.response_code import CustomErrorCode, StandardResponseCode

if TYPE_CHECKING:
    from starlette.background import BackgroundTask


class BaseExceptionError(Exception):
    """Base exception mixin class"""

    code: int

    def __init__(
        self,
        *,
        msg: str | None = None,
        data: Any = None,
        background: BackgroundTask | None = None,
        headers: dict[str, Any] | None = None,
        http_status: int | None = None,
    ) -> None:
        self.msg = msg
        self.data = data
        # The original background task: https://www.starlette.io/background/
        self.background = background
        self.headers = headers
        self.http_status = http_status


class HTTPError(HTTPException):
    """HTTP exception"""

    def __init__(
        self, *, code: int, msg: Any = None, headers: dict[str, Any] | None = None
    ) -> None:
        super().__init__(status_code=code, detail=msg, headers=headers)


class CustomError(BaseExceptionError):
    """Custom exception"""

    def __init__(
        self,
        *,
        error: CustomErrorCode,
        data: Any = None,
        background: BackgroundTask | None = None,
        headers: dict[str, Any] | None = None,
        http_status: int | None = None,
        **msg_kwargs: Any,
    ) -> None:
        self.code = error.code
        # ``error.msg`` is the i18n-resolved template; interpolate any ``{...}`` placeholders
        # against the supplied kwargs (e.g. ``count`` for the menu role-mapping conflict).
        # Without kwargs the message is passed through unchanged, so existing call sites are
        # unaffected.
        msg = error.msg
        if msg_kwargs:
            msg = msg.format(**msg_kwargs)
        super().__init__(
            msg=msg,
            data=data,
            background=background,
            headers=headers,
            http_status=http_status,
        )


class RequestError(BaseExceptionError):
    """Request exception"""

    def __init__(
        self,
        *,
        code: int = StandardResponseCode.HTTP_400,
        msg: str = "Bad Request",
        data: Any = None,
        background: BackgroundTask | None = None,
    ) -> None:
        self.code = code
        super().__init__(msg=msg, data=data, background=background)


class TooManyRequestsError(BaseExceptionError):
    """Rate-limited / too many requests exception"""

    code = StandardResponseCode.HTTP_429

    def __init__(
        self,
        *,
        msg: str = "Too Many Requests",
        retry_after: int | None = None,
        data: Any = None,
        background: BackgroundTask | None = None,
    ) -> None:
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        super().__init__(msg=msg, data=data, background=background, headers=headers)


class InvalidCredentialsError(RequestError):
    """Invalid login credentials exception"""

    def __init__(
        self,
        *,
        msg: str = "Incorrect username or password",
        data: Any = None,
        background: BackgroundTask | None = None,
    ) -> None:
        super().__init__(
            code=StandardResponseCode.HTTP_401,
            msg=msg,
            data=data,
            background=background,
        )


class ForbiddenError(BaseExceptionError):
    """Forbidden access exception"""

    code = StandardResponseCode.HTTP_403

    def __init__(
        self,
        *,
        msg: str = "Forbidden",
        data: Any = None,
        background: BackgroundTask | None = None,
    ) -> None:
        super().__init__(msg=msg, data=data, background=background)


class NotFoundError(BaseExceptionError):
    """Resource not found exception"""

    code = StandardResponseCode.HTTP_404

    def __init__(
        self,
        *,
        msg: str = "Not Found",
        data: Any = None,
        background: BackgroundTask | None = None,
    ) -> None:
        super().__init__(msg=msg, data=data, background=background)


class ServerError(BaseExceptionError):
    """Server exception"""

    code = StandardResponseCode.HTTP_500

    def __init__(
        self,
        *,
        msg: str = "Internal Server Error",
        data: Any = None,
        background: BackgroundTask | None = None,
    ) -> None:
        super().__init__(msg=msg, data=data, background=background)


class GatewayError(BaseExceptionError):
    """Gateway exception"""

    code = StandardResponseCode.HTTP_502

    def __init__(
        self,
        *,
        msg: str = "Bad Gateway",
        data: Any = None,
        background: BackgroundTask | None = None,
    ) -> None:
        super().__init__(msg=msg, data=data, background=background)


class AuthorizationError(BaseExceptionError):
    """Authorization exception"""

    code = StandardResponseCode.HTTP_403

    def __init__(
        self,
        *,
        msg: str = "Permission Denied",
        data: Any = None,
        background: BackgroundTask | None = None,
    ) -> None:
        super().__init__(msg=msg, data=data, background=background)


class AccountStatusError(AuthorizationError):
    """Account lock or disabled status exception"""


class AccountDisabledError(AccountStatusError):
    """Account disabled by admin — safe to surface in login responses"""


class TokenError(HTTPError):
    """Token exception"""

    code = StandardResponseCode.HTTP_401

    def __init__(
        self, *, msg: str = "Not Authenticated", headers: dict[str, Any] | None = None
    ) -> None:
        super().__init__(
            code=self.code, msg=msg, headers=headers or {"WWW-Authenticate": "Bearer"}
        )


class ConflictError(BaseExceptionError):
    """Resource conflict exception"""

    code = StandardResponseCode.HTTP_409

    def __init__(
        self,
        *,
        msg: str = "Conflict",
        data: Any = None,
        background: BackgroundTask | None = None,
    ) -> None:
        super().__init__(msg=msg, data=data, background=background)

from typing import TYPE_CHECKING, Any, Protocol

from starlette_context.ctx import _Context, context

if TYPE_CHECKING:
    from datetime import datetime


class TypedContextProtocol(Protocol):
    perf_time: float
    start_time: datetime

    ip: str
    country: str | None
    region: str | None
    city: str | None

    user_agent: str | None
    os: str | None
    browser: str | None
    device: str | None

    permission: str | None
    language: str

    user_id: int | None

    __request_validation_exception__: Any
    __request_http_exception__: Any
    __request_assertion_error__: Any
    __request_custom_exception__: Any
    __request_unknown_exception__: Any

    def exists(self) -> bool: ...
    def get(self, key: Any, default: Any = None) -> Any: ...


class TypedContext(_Context):
    def __getattr__(self, name: str) -> Any:
        return context.get(name)

    def __setattr__(self, name: str, value: Any) -> None:
        context[name] = value


ctx: TypedContextProtocol = TypedContext()  # type: ignore[assignment]

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from backend.common.context import ctx
from backend.utils.request_parse import parse_user_agent_info

if TYPE_CHECKING:
    from fastapi import Request, Response


class StateMiddleware(BaseHTTPMiddleware):
    """Request state middleware."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """
        Process the request and set request state information.

        :param request: FastAPI request object.
        :param call_next: Next middleware or route handler.
        :return:
        """
        ua_info = parse_user_agent_info(request)
        ctx.user_agent = ua_info.user_agent
        ctx.os = ua_info.os
        ctx.browser = ua_info.browser
        ctx.device = ua_info.device

        response = await call_next(request)

        return response

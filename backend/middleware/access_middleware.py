import time

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from backend.common.context import ctx
from backend.common.log import log
from backend.utils.timezone import timezone

if TYPE_CHECKING:
    from fastapi import Request, Response


class AccessMiddleware(BaseHTTPMiddleware):
    """Access Log Middleware"""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """
        Process requests and log access.

        :param request: FastAPI Request object
        :param call_next: Next middleware or route handling function
        :return:
        """
        perf_time = time.perf_counter()
        ctx.perf_time = perf_time

        start_time = timezone.now()
        ctx.start_time = start_time

        path = request.url.path
        method = request.method

        if method != "OPTIONS":
            log.debug(
                f"--> Request start [{path if not request.url.query else request.url.path + '?' + request.url.query}]"
            )

        response = await call_next(request)

        return response

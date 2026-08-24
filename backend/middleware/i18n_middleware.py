from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

from backend.common.i18n import i18n
from backend.core.conf import settings

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import Request, Response


def get_current_language(request: Request) -> str | None:
    """
    Get the current request language preference

    :param request: FastAPI request object
    :return:
    """
    accept_language = request.headers.get("Accept-Language", "")
    if not accept_language:
        return settings.I18N_DEFAULT_LANGUAGE

    languages = [lang.split(";")[0] for lang in accept_language.split(",")]
    lang = languages[0].lower().strip()

    # Language mapping
    lang_mapping = {
        "en": "en-US",
        "en-us": "en-US",
        "ko": "ko-KR",
        "ko-kr": "ko-KR",
    }

    return lang_mapping.get(lang, lang)


class I18nMiddleware(BaseHTTPMiddleware):
    """Internationalization middleware"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process the request and set the internationalization language

        :param request: FastAPI request object
        :param call_next: The next middleware or route handler function
        :return:
        """
        language = get_current_language(request)

        # Set the internationalization language
        if language and i18n.current_language != language:
            i18n.current_language = language

        response = await call_next(request)

        return response

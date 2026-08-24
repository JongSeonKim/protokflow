from typing import TYPE_CHECKING

from user_agents import parse  # type: ignore[import-untyped]

from backend.common.dataclasses import UserAgentInfo

if TYPE_CHECKING:
    from fastapi import Request


def parse_user_agent_info(request: Request) -> UserAgentInfo:
    """
    Parse request user agent information

    :param request: FastAPI request object
    :return:
    """
    os, browser, device = None, None, None
    user_agent = request.headers.get("User-Agent")
    if user_agent:
        user_agent_ = parse(user_agent)
        os = user_agent_.get_os()
        browser = user_agent_.get_browser()
        device = user_agent_.get_device()
    return UserAgentInfo(user_agent=user_agent, device=device, os=os, browser=browser)

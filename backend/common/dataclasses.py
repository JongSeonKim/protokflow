import dataclasses


@dataclasses.dataclass
class UserAgentInfo:
    user_agent: str | None
    os: str | None
    browser: str | None
    device: str | None

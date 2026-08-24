import shutil

from functools import cache
from typing import Literal

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from backend.core.path_conf import ENV_EXAMPLE_FILE_PATH, ENV_FILE_PATH


class Settings(BaseSettings):
    """Application settings"""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        extra="allow",
        case_sensitive=True,
        hide_input_in_errors=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Custom configuration source priority"""
        return env_settings, dotenv_settings

    # FastAPI
    FASTAPI_API_V1_PATH: str = "/api/v1"
    FASTAPI_TITLE: str = "ProtokFlow API"
    FASTAPI_DESCRIPTION: str = "Workflows for agent-native prototypes of design systems"
    FASTAPI_DOCS_URL: str = "/docs"
    FASTAPI_REDOC_URL: str = "/redoc"
    FASTAPI_OPENAPI_URL: str | None = "/openapi"
    FASTAPI_STATIC_FILES: bool = True

    # .env Database
    DATABASE_TYPE: Literal["sqlite"] = "sqlite"
    DATABASE_SQLITE_BUSY_TIMEOUT_MS: int = 5_000

    # CORS
    CORS_ALLOWED_ORIGINS: list[str] = [  # No trailing slash
        "http://127.0.0.1:8000",
        "http://localhost:5173",
    ]
    CORS_EXPOSE_HEADERS: list[str] = [
        "X-Request-ID",
        "Retry-After",
    ]

    # Middleware configuration
    MIDDLEWARE_CORS: bool = True

    # Time
    DATETIME_TIMEZONE: str = "Asia/Seoul"
    DATETIME_FORMAT: str = "%Y-%m-%d %H:%M:%S"

    # Trace ID
    TRACE_ID_REQUEST_HEADER_KEY: str = "X-Request-ID"
    TRACE_ID_LOG_LENGTH: int = 32
    TRACE_ID_LOG_DEFAULT_VALUE: str = "-"

    # Log
    LOG_FORMAT: str = "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</> | <lvl>{level: <8}</> | <cyan>{request_id}</> | <lvl>{message}</>"

    # Log (Console)
    LOG_STD_LEVEL: str = "INFO"

    # Log (file)
    LOG_FILE_ENABLE: bool = True
    LOG_FILE_ACCESS_LEVEL: str = "INFO"
    LOG_FILE_ERROR_LEVEL: str = "ERROR"
    LOG_ACCESS_FILENAME: str = "access.log"
    LOG_ERROR_FILENAME: str = "error.log"

    # I18n configuration
    I18N_DEFAULT_LANGUAGE: str = "ko-KR"


@cache
def get_settings() -> Settings:
    if not ENV_FILE_PATH.exists():
        shutil.copy(ENV_EXAMPLE_FILE_PATH, ENV_FILE_PATH)
    return Settings()  # type: ignore[call-arg]


settings = get_settings()

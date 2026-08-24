import re

from datetime import datetime
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    field_serializer,
    validate_email,
)

from backend.utils.timezone import timezone


def normalize_phone_number(value: Any) -> Any:
    """Normalize Korean mobile phone input before schema validation."""
    if not isinstance(value, str):
        return value
    phone = re.sub(r"[\s-]+", "", value.strip())
    if phone.startswith("+82"):
        return f"0{phone[3:]}"
    if phone.startswith("82"):
        return f"0{phone[2:]}"
    return phone


CustomPhoneNumber = Annotated[
    str, BeforeValidator(normalize_phone_number), Field(pattern=r"^010\d{8}$")
]
CustomPin = Annotated[str, Field(pattern=r"^\d{6}$")]


class CustomEmailStr(EmailStr):
    """Custom email type"""

    @classmethod
    def _validate(cls, input_value: str, /) -> str | None:
        return None if not input_value else validate_email(input_value)[1]


class SchemaBase(BaseModel):
    """Base model configuration"""

    model_config = ConfigDict(
        use_enum_values=True,
        extra="forbid",
    )

    @field_serializer("*", check_fields=False, return_type=Any)
    @classmethod
    def _serialize_datetime(cls, v: Any, info: Any) -> Any:
        if info.mode != "json":
            return v
        if isinstance(v, datetime):
            if v.tzinfo is not None and v.tzinfo != timezone.tz_info:
                return timezone.to_str(timezone.from_datetime(v))
            return timezone.to_str(v)
        return v


def ser_string(value: Any) -> str | None:
    if value:
        return str(value)
    return value

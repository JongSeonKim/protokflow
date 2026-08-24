from enum import Enum
from enum import IntEnum as SourceIntEnum
from enum import StrEnum as SourceStrEnum
from typing import Any, TypeVar

T = TypeVar("T", bound=Enum)


class _EnumBase:
    """Enum base class, providing common methods"""

    __members__: dict[str, Any]

    @classmethod
    def get_member_keys(cls) -> list[str]:
        """Get the list of enum member names"""
        return list(cls.__members__.keys())

    @classmethod
    def get_member_values(cls) -> list:
        """Get the list of enum member values"""
        return [item.value for item in cls.__members__.values()]

    @classmethod
    def get_member_dict(cls) -> dict[str, Any]:
        """Get the enum member dictionary"""
        return {name: item.value for name, item in cls.__members__.items()}


class IntEnum(_EnumBase, SourceIntEnum):
    """Integer enum base class"""


class StrEnum(_EnumBase, SourceStrEnum):
    """String enum base class"""


class StatusType(IntEnum):
    """Status type"""

    disable = 0
    enable = 1


class DataBaseType(StrEnum):
    """Database type"""

    sqlite = "sqlite"
    postgresql = "postgresql"

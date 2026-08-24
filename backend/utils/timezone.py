import zoneinfo

from datetime import UTC, datetime, tzinfo

from backend.core.conf import settings

# 基于 wikipedia：https://en.wikipedia.org/wiki/List_of_tz_database_time_zones#List
_UTC_IDENTIFIERS = frozenset(
    {
        "Etc/UCT",
        "Etc/Universal",
        "Etc/UTC",
        "Etc/Zulu",
        "UCT",
        "Universal",
        "UTC",
        "Zulu",
    }
)


class TimeZone:
    def __init__(self) -> None:
        """Initialize timezone converter"""
        self.tz_info: tzinfo
        if settings.DATETIME_TIMEZONE in _UTC_IDENTIFIERS:
            self.tz_info = UTC
        else:
            self.tz_info = zoneinfo.ZoneInfo(settings.DATETIME_TIMEZONE)

    def now(self) -> datetime:
        """Get current time in the configured timezone"""
        return datetime.now(self.tz_info)

    def from_datetime(self, t: datetime) -> datetime:
        """
        Convert a datetime object to the configured timezone.

        :param t: Datetime object to convert
        :return:
        """
        return t.astimezone(self.tz_info)

    def from_str(
        self, t_str: str, format_str: str = settings.DATETIME_FORMAT
    ) -> datetime:
        """
        Parse a time string into a datetime object in the configured timezone.

        :param t_str: Time string
        :param format_str: Time format string, defaults to settings.DATETIME_FORMAT
        :return:
        """
        return datetime.strptime(t_str, format_str).replace(tzinfo=self.tz_info)

    @staticmethod
    def to_str(t: datetime, format_str: str = settings.DATETIME_FORMAT) -> str:
        """
        Convert a datetime object to a formatted time string.

        :param t: Datetime object
        :param format_str: Time format string, defaults to settings.DATETIME_FORMAT
        :return:
        """
        return t.strftime(format_str)

    @staticmethod
    def to_utc(t: datetime | int) -> datetime:
        """
        Convert a datetime object or timestamp to UTC timezone.

        :param t: Datetime object or timestamp to convert
        :return:
        """
        if isinstance(t, datetime):
            return t.astimezone(UTC)
        return datetime.fromtimestamp(t, tz=UTC)


timezone: TimeZone = TimeZone()

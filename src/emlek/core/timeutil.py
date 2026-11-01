"""Timestamps and event-time validation.

created_at is UTC (ISO 8601, milliseconds). event_time keeps the precision the user gave:
year/month/day are calendar dates (no time zone); hour/minute/second carry an offset.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

PRECISIONS = ("year", "month", "day", "hour", "minute", "second")

_OFFSET = r"(?:Z|[+-]\d{2}:\d{2})"
_PATTERNS: dict[str, re.Pattern[str]] = {
    "year": re.compile(r"^\d{4}$"),
    "month": re.compile(r"^\d{4}-\d{2}$"),
    "day": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "hour": re.compile(rf"^\d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}{_OFFSET}$"),
    "minute": re.compile(rf"^\d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}:\d{{2}}{_OFFSET}$"),
    "second": re.compile(rf"^\d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}:\d{{2}}:\d{{2}}{_OFFSET}$"),
}
_TIME_PARTS = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2})(?::(\d{2}))?(?::(\d{2}))?(Z|[+-]\d{2}:\d{2})$"
)


def utc_now_iso() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def infer_precision(value: str) -> str | None:
    for precision in PRECISIONS:
        if _PATTERNS[precision].match(value):
            return precision
    return None


def is_valid_event_time(value: str, precision: str) -> bool:
    pattern = _PATTERNS.get(precision)
    if pattern is None or not pattern.match(value):
        return False
    try:
        if precision == "year":
            return int(value) >= 1
        if precision == "month":
            year, month = value.split("-")
            datetime(int(year), int(month), 1)
            return True
        if precision == "day":
            year, month, day = value.split("-")
            datetime(int(year), int(month), int(day))
            return True
        match = _TIME_PARTS.match(value)
        if match is None:
            return False
        year_s, month_s, day_s, hour_s, minute_s, second_s, offset = match.groups()
        tz = UTC if offset == "Z" else _parse_offset(offset)
        datetime(
            int(year_s),
            int(month_s),
            int(day_s),
            int(hour_s),
            int(minute_s or 0),
            int(second_s or 0),
            tzinfo=tz,
        )
        return True
    except ValueError:
        return False


def _parse_offset(offset: str) -> timezone:
    sign = -1 if offset[0] == "-" else 1
    hours, minutes = int(offset[1:3]), int(offset[4:6])
    if hours > 23 or minutes > 59:
        raise ValueError("bad offset")
    return timezone(sign * timedelta(hours=hours, minutes=minutes))
